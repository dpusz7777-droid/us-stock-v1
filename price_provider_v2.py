#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PriceProvider V2 — 统一行情获取层。

架构说明
--------
本模块定义了统一的行情返回结构 PriceResultV2，以及多个 Provider 实现。
所有行情请求都通过 PriceProviderV2 统一入口完成，禁止调用方直接访问 yfinance
或其他行情源。

数据源优先级
-------------
1. 内存缓存 (最快)
2. 本地磁盘缓存 (.cache/prices/ 目录)
3. 实时行情源 (Yahoo Finance / yfinance)
4. Fallback provider 链 (可扩展)

缓存策略
---------
- 内存缓存: 进程内共享，过期时间可配置，默认 60 秒
- 磁盘缓存: .cache/prices/{symbol}.json，过期时间可配置，默认 300 秒
- 如果实时行情失败但缓存可用：返回 STALE 状态，cached=true

错误状态定义 (status)
----------------------
- OK             — 实时行情成功
- STALE          — 实时失败，使用缓存数据
- NOT_FOUND      — 股票代码无效/不存在
- TIMEOUT        — 行情源超时
- PROVIDER_ERROR — 行情源内部错误
- DEGRADED       — 部分数据缺失但仍可用

预留位置
---------
- YuantaOpenAPIProvider    — 未来接入盈立 OpenAPI
- IBKRProvider            — 未来接入盈透证券

当前限制
---------
- 不支持自动交易
- 不连接券商生产环境
- 不修改任何 portfolio 数据
"""

from __future__ import annotations

import json
import os
import time
import socket
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import quote

# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

PRICE_STATUS_OK = "OK"
PRICE_STATUS_STALE = "STALE"
PRICE_STATUS_NOT_FOUND = "NOT_FOUND"
PRICE_STATUS_TIMEOUT = "TIMEOUT"
PRICE_STATUS_PROVIDER_ERROR = "PROVIDER_ERROR"
PRICE_STATUS_DEGRADED = "DEGRADED"
PRICE_STATUSES = {
    PRICE_STATUS_OK,
    PRICE_STATUS_STALE,
    PRICE_STATUS_NOT_FOUND,
    PRICE_STATUS_TIMEOUT,
    PRICE_STATUS_PROVIDER_ERROR,
    PRICE_STATUS_DEGRADED,
}

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent
DEFAULT_CACHE_DIR = ROOT / ".cache" / "prices"
DEFAULT_MEMORY_TTL = 60       # seconds
DEFAULT_DISK_TTL = 300        # seconds
DEFAULT_TIMEOUT = 10          # seconds
DEFAULT_RETRIES = 1

# ---------------------------------------------------------------------------
# Unified result object
# ---------------------------------------------------------------------------


@dataclass
class PriceResultV2:
    """统一价格结果对象。"""

    symbol: str
    price: Decimal | None
    currency: str = "USD"
    market_time: str | None = None
    previous_close: Decimal | None = None
    source: str = "unknown"
    status: str = PRICE_STATUS_OK
    error_code: str | None = None
    error_message: str | None = None
    cached: bool = False
    latency_ms: float = 0.0
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    is_realtime: bool = False
    is_mock: bool = False

    def to_dict(self) -> dict[str, Any]:
        dct = asdict(self)
        if self.price is not None:
            dct["price"] = str(self.price)
        if self.previous_close is not None:
            dct["previous_close"] = str(self.previous_close)
        dct["as_of"] = self.market_time or self.fetched_at
        dct["is_stale"] = self.status == PRICE_STATUS_STALE
        return dct

    @property
    def is_ok(self) -> bool:
        return self.status == PRICE_STATUS_OK

    @property
    def is_fail(self) -> bool:
        return self.status in (PRICE_STATUS_NOT_FOUND, PRICE_STATUS_PROVIDER_ERROR)

    @property
    def price_as_of(self) -> str:
        """V1 compatibility: returns market_time or fetched_at."""
        return self.market_time or self.fetched_at

    def __repr__(self) -> str:
        return (
            f"PriceResultV2(symbol={self.symbol}, price={self.price}, "
            f"status={self.status}, source={self.source}, cached={self.cached})"
        )


# ---------------------------------------------------------------------------
# Error utility
# ---------------------------------------------------------------------------


class PriceProviderV2Error(Exception):
    """PriceProvider V2 基础异常。"""


# ---------------------------------------------------------------------------
# Base provider interface
# ---------------------------------------------------------------------------


class BasePriceProviderV2:
    """V2 provider 基类。子类只需实现 _fetch_one(symbol) -> PriceResultV2。"""

    def get_price(self, symbol: str) -> PriceResultV2:
        raise NotImplementedError

    def get_prices(self, symbols: Iterable[str]) -> dict[str, PriceResultV2]:
        result: dict[str, PriceResultV2] = {}
        for symbol in symbols:
            result[symbol.strip().upper()] = self.get_price(symbol)
        return result


# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------


class _MemoryCache:
    def __init__(self, ttl: float = DEFAULT_MEMORY_TTL):
        self._ttl = ttl
        self._data: dict[str, tuple[float, PriceResultV2]] = {}

    def get(self, symbol: str) -> PriceResultV2 | None:
        entry = self._data.get(symbol)
        if entry is None:
            return None
        ts, result = entry
        if time.monotonic() - ts >= self._ttl:
            del self._data[symbol]
            return None
        return result

    def set(self, symbol: str, result: PriceResultV2) -> None:
        self._data[symbol] = (time.monotonic(), result)

    def invalidate(self, symbol: str) -> None:
        self._data.pop(symbol, None)

    def clear(self) -> None:
        self._data.clear()


# ---------------------------------------------------------------------------
# Disk cache
# ---------------------------------------------------------------------------


class _DiskCache:
    def __init__(self, cache_dir: str | Path = DEFAULT_CACHE_DIR, ttl: float = DEFAULT_DISK_TTL):
        self._dir = Path(cache_dir).resolve()
        self._ttl = ttl
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            self._dir = None  # cache unavailable

    def _path(self, symbol: str) -> Path:
        return (self._dir or Path()) / f"{symbol}.json"

    def get(self, symbol: str, *, allow_expired: bool = False) -> PriceResultV2 | None:
        if self._dir is None:
            return None
        path = self._path(symbol)
        if not path.is_file():
            return None
        try:
            age = time.time() - path.stat().st_mtime
            if age >= self._ttl and not allow_expired:
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
            return PriceResultV2(
                symbol=data.get("symbol", symbol),
                price=Decimal(str(data["price"])) if data.get("price") else None,
                currency=data.get("currency", "USD"),
                market_time=data.get("market_time"),
                previous_close=(
                    Decimal(str(data["previous_close"]))
                    if data.get("previous_close") is not None else None
                ),
                source=data.get("source", "cache"),
                status=PRICE_STATUS_STALE if age >= self._ttl else PRICE_STATUS_OK,
                cached=True,
                fetched_at=data.get("fetched_at", ""),
                is_realtime=False,
                is_mock=bool(data.get("is_mock", False)),
            )
        except (json.JSONDecodeError, OSError, KeyError, InvalidOperation):
            return None

    def set(self, result: PriceResultV2) -> None:
        if self._dir is None:
            return
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            data = result.to_dict()
            data["price"] = str(result.price) if result.price is not None else None
            self._path(result.symbol).write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass


# ---------------------------------------------------------------------------
# V2 YFinance provider (wraps the V1 logic with unified result)
# ---------------------------------------------------------------------------


class YFinanceProviderV2(BasePriceProviderV2):
    """通过 yfinance 获取实时行情，返回 PriceResultV2。"""

    SOURCE = "yfinance"

    def __init__(
        self,
        ticker_factory: Callable[[str], Any] | None = None,
        *,
        timeout: int = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        disk_cache: _DiskCache | None = None,
        memory_cache: _MemoryCache | None = None,
        session: Any | None = None,
    ):
        self._ticker_factory = ticker_factory
        self._timeout = max(1, int(timeout))
        self._retries = max(0, int(retries))
        self._disk_cache = disk_cache or _DiskCache()
        self._memory_cache = memory_cache or _MemoryCache()
        self._session = session
        self._cache_error: str | None = None

    def _get_ticker_factory(self) -> Callable[[str], Any]:
        if self._ticker_factory is not None:
            return self._ticker_factory
        try:
            import yfinance as yf
        except ImportError as exc:
            raise PriceProviderV2Error("yfinance not installed; run: pip install yfinance") from exc
        return yf.Ticker

    def _result_from_live(self, symbol: str) -> PriceResultV2:
        if self._ticker_factory is None:
            return self._result_from_chart(symbol)

        start = time.monotonic()
        ticker_factory = self._get_ticker_factory()
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(self._timeout)
        try:
            ticker = ticker_factory(symbol)
            price_value: Decimal | None = None
            market_time: str | None = None
            previous_close_value: Decimal | None = None
            source_text = self.SOURCE

            # Try info
            try:
                info = ticker.info
                if isinstance(info, Mapping):
                    pv = (info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose"))
                    pc = info.get("previousClose")
                    if pv is not None:
                        price_value = Decimal(str(pv))
                    if pc is not None:
                        previous_close_value = Decimal(str(pc))
                    mt = info.get("regularMarketTime")
                    if mt:
                        try:
                            market_time = datetime.fromtimestamp(float(mt), tz=timezone.utc).isoformat()
                        except (TypeError, ValueError, OSError):
                            pass
            except Exception:
                pass

            # Fallback to fast_info
            if price_value is None:
                try:
                    fi = ticker.fast_info
                    pv = (fi.get("lastPrice") or fi.get("last_price") or fi.get("regularMarketPrice"))
                    if pv is not None:
                        price_value = Decimal(str(pv))
                except Exception:
                    pass

            # Fallback to history
            if price_value is None:
                try:
                    history = ticker.history(period="5d", interval="1d")
                    if history is not None and not history.empty:
                        closes = history["Close"].dropna()
                        if len(closes) > 0:
                            price_value = Decimal(str(closes.iloc[-1]))
                            if len(closes) >= 2:
                                previous_close_value = Decimal(str(closes.iloc[-2]))
                            try:
                                ts = closes.index[-1]
                                market_time = str(ts)
                            except Exception:
                                pass
                except Exception:
                    pass

            if price_value is None or price_value <= Decimal("0"):
                elapsed = (time.monotonic() - start) * 1000
                return PriceResultV2(
                    symbol=symbol,
                    price=None,
                    status=PRICE_STATUS_NOT_FOUND,
                    error_code="NO_PRICE",
                    error_message=f"price not found for symbol: {symbol}",
                    source=source_text,
                    latency_ms=elapsed,
                )

            elapsed = (time.monotonic() - start) * 1000
            return PriceResultV2(
                symbol=symbol,
                price=price_value,
                currency="USD",
                market_time=market_time or datetime.now(timezone.utc).isoformat(),
                previous_close=previous_close_value,
                source=source_text,
                status=PRICE_STATUS_OK,
                latency_ms=elapsed,
                is_realtime=False,
            )
        except socket.timeout:
            elapsed = (time.monotonic() - start) * 1000
            return PriceResultV2(
                symbol=symbol,
                price=None,
                status=PRICE_STATUS_TIMEOUT,
                error_code="TIMEOUT",
                error_message=f"yfinance timeout for {symbol} after {self._timeout}s",
                source=self.SOURCE,
                latency_ms=elapsed,
            )
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            return PriceResultV2(
                symbol=symbol,
                price=None,
                status=PRICE_STATUS_PROVIDER_ERROR,
                error_code="PROVIDER_ERROR",
                error_message=f"yfinance error for {symbol}: {exc}",
                source=self.SOURCE,
                latency_ms=elapsed,
            )
        finally:
            socket.setdefaulttimeout(old_timeout)

    def _result_from_chart(self, symbol: str) -> PriceResultV2:
        """Fetch one quote through Yahoo Chart v8 using the shared project session."""
        start = time.monotonic()
        try:
            import requests
            from northstar.config.network import get_price_provider_session, get_request_timeout

            session = self._session or get_price_provider_session()
            configured = get_request_timeout()
            timeout = (
                min(float(self._timeout), configured[0]),
                min(float(self._timeout), configured[1]),
            )
            encoded = quote(symbol, safe="")
            errors: list[str] = []
            for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
                endpoint = f"https://{host}/v8/finance/chart/{encoded}"
                try:
                    response = session.get(
                        endpoint,
                        params={"range": "5d", "interval": "1d", "events": "div,splits"},
                        timeout=timeout,
                    )
                    if response.status_code != 200:
                        errors.append(f"{host} HTTP {response.status_code}")
                        continue
                    chart = response.json().get("chart", {})
                    if chart.get("error"):
                        errors.append(f"{host} chart_error={chart['error']}")
                        continue
                    rows = chart.get("result") or []
                    if not rows:
                        errors.append(f"{host} empty_result")
                        continue
                    item = rows[0]
                    meta = item.get("meta") or {}
                    timestamps = item.get("timestamp") or []
                    quote_rows = ((item.get("indicators") or {}).get("quote") or [{}])[0]
                    closes = quote_rows.get("close") or []
                    valid = [
                        (int(timestamps[index]), value)
                        for index, value in enumerate(closes)
                        if index < len(timestamps) and value is not None and float(value) > 0
                    ]
                    raw_price = meta.get("regularMarketPrice")
                    if raw_price is None and valid:
                        raw_price = valid[-1][1]
                    if raw_price is None or Decimal(str(raw_price)) <= 0:
                        errors.append(f"{host} no_positive_price")
                        continue
                    raw_previous = meta.get("chartPreviousClose", meta.get("previousClose"))
                    market_epoch = meta.get("regularMarketTime")
                    if market_epoch is None and valid:
                        market_epoch = valid[-1][0]
                    market_time = (
                        datetime.fromtimestamp(float(market_epoch), tz=timezone.utc).isoformat()
                        if market_epoch is not None else datetime.now(timezone.utc).isoformat()
                    )
                    market_state = str(meta.get("marketState") or "").upper()
                    return PriceResultV2(
                        symbol=symbol,
                        price=Decimal(str(raw_price)),
                        previous_close=(Decimal(str(raw_previous)) if raw_previous is not None else None),
                        currency=str(meta.get("currency") or "USD"),
                        market_time=market_time,
                        source="yahoo-chart-v8",
                        status=PRICE_STATUS_OK,
                        latency_ms=(time.monotonic() - start) * 1000,
                        is_realtime=market_state in {"REGULAR", "PRE", "POST"},
                    )
                except requests.Timeout as exc:
                    errors.append(f"{host} {type(exc).__name__}")
                except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                    errors.append(f"{host} {type(exc).__name__}: {exc}")
            message = "; ".join(errors) or "Yahoo Chart returned no usable result"
            status = PRICE_STATUS_TIMEOUT if any("Timeout" in item for item in errors) else PRICE_STATUS_PROVIDER_ERROR
            return PriceResultV2(
                symbol=symbol,
                price=None,
                source="yahoo-chart-v8",
                status=status,
                error_code="YAHOO_CHART_FAILED",
                error_message=message,
                latency_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as exc:
            return PriceResultV2(
                symbol=symbol,
                price=None,
                source="yahoo-chart-v8",
                status=PRICE_STATUS_PROVIDER_ERROR,
                error_code="PROVIDER_ERROR",
                error_message=f"{type(exc).__name__}: {exc}",
                latency_ms=(time.monotonic() - start) * 1000,
            )

    def get_price(self, symbol: str) -> PriceResultV2:
        sym = symbol.strip().upper()
        if not sym:
            return PriceResultV2(
                symbol=sym,
                price=None,
                status=PRICE_STATUS_NOT_FOUND,
                error_code="EMPTY_SYMBOL",
                error_message="symbol is empty",
            )

        # 1. Try memory cache (fastest)
        cached = self._memory_cache.get(sym)
        if cached is not None:
            return cached

        # 2. Reuse a still-fresh disk quote before making a network request.
        if self._ticker_factory is None:
            cached = self._disk_cache.get(sym)
            if cached is not None:
                self._memory_cache.set(sym, cached)
                return cached

        # 3. Live quote with finite retries
        last_result: PriceResultV2 | None = None
        for attempt in range(self._retries + 1):
            result = self._result_from_live(sym)
            if result.is_ok:
                # Cache and return
                self._memory_cache.set(sym, result)
                self._disk_cache.set(result)
                return result
            last_result = result
            if result.status in {PRICE_STATUS_TIMEOUT, PRICE_STATUS_PROVIDER_ERROR} and attempt < self._retries:
                continue  # retry on timeout
            break

        # 4. Live failed — an expired disk quote is allowed only as explicit STALE data.
        stale = self._disk_cache.get(sym, allow_expired=True)
        if stale is not None:
            stale.status = PRICE_STATUS_STALE
            stale.cached = True
            stale.error_code = last_result.error_code if last_result else "LIVE_FAILED"
            stale.error_message = (
                f"Live price failed, using cached price. "
                f"Live error: {last_result.error_message if last_result else 'unknown'}"
            )
            stale.source = "yfinance-cache"
            self._memory_cache.set(sym, stale)
            return stale

        # 5. Complete failure (no cache, no live)
        if last_result is None:
            return PriceResultV2(
                symbol=sym,
                price=None,
                status=PRICE_STATUS_PROVIDER_ERROR,
                error_code="UNKNOWN",
                error_message=f"price fetch failed for {sym}",
            )
        return last_result


# ---------------------------------------------------------------------------
# Mock provider for testing
# ---------------------------------------------------------------------------


class MockProviderV2(BasePriceProviderV2):
    """Mock provider — returns static prices for testing."""

    def __init__(self, prices: dict[str, Decimal] | None = None):
        self._prices: dict[str, Decimal] = prices or {}

    def set_price(self, symbol: str, price: Decimal) -> None:
        self._prices[symbol.strip().upper()] = price

    def get_price(self, symbol: str) -> PriceResultV2:
        sym = symbol.strip().upper()
        if not sym:
            return PriceResultV2(
                symbol=sym,
                price=None,
                status=PRICE_STATUS_NOT_FOUND,
                error_code="EMPTY_SYMBOL",
                error_message="symbol is empty",
            )
        px = self._prices.get(sym)
        if px is None:
            return PriceResultV2(
                symbol=sym,
                price=None,
                status=PRICE_STATUS_NOT_FOUND,
                error_code="NOT_FOUND",
                error_message=f"mock price not found for {sym}",
                source="mock",
            )
        return PriceResultV2(
            symbol=sym,
            price=px,
            currency="USD",
            market_time=datetime.now(timezone.utc).isoformat(),
            source="mock",
            status=PRICE_STATUS_OK,
            cached=False,
        )


# ---------------------------------------------------------------------------
# Fallback chain provider
# ---------------------------------------------------------------------------


class FallbackChainV2(BasePriceProviderV2):
    """
    Fallback provider chain.
    Tries providers in order; returns first successful result.
    If all fail, returns the last result.
    """

    def __init__(self, providers: list[BasePriceProviderV2]):
        if not providers:
            raise PriceProviderV2Error("fallback chain must have at least one provider")
        self._providers = providers

    def get_price(self, symbol: str) -> PriceResultV2:
        last_result: PriceResultV2 | None = None
        for provider in self._providers:
            result = provider.get_price(symbol)
            if result.is_ok:
                return result
            last_result = result
        if last_result is not None:
            last_result.error_message = (
                f"All providers failed. Last error: {last_result.error_message}"
            )
            return last_result
        return PriceResultV2(
            symbol=symbol.strip().upper(),
            price=None,
            status=PRICE_STATUS_PROVIDER_ERROR,
            error_code="ALL_FAILED",
            error_message="no provider available",
        )


# ---------------------------------------------------------------------------
# Unified singleton / factory
# ---------------------------------------------------------------------------

_global_provider: BasePriceProviderV2 | None = None


def get_price_provider_v2(
    *,
    use_cache: bool = True,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    memory_ttl: float = DEFAULT_MEMORY_TTL,
    disk_ttl: float = DEFAULT_DISK_TTL,
) -> BasePriceProviderV2:
    """Get or create the global PriceProvider V2 singleton."""
    global _global_provider
    if _global_provider is not None:
        return _global_provider
    if not use_cache:
        provider = YFinanceProviderV2(
            timeout=timeout,
            retries=retries,
            disk_cache=_DiskCache(ttl=0),  # no disk cache when disabled
            memory_cache=_MemoryCache(ttl=0),
        )
    else:
        provider = YFinanceProviderV2(
            timeout=timeout,
            retries=retries,
            disk_cache=_DiskCache(ttl=disk_ttl),
            memory_cache=_MemoryCache(ttl=memory_ttl),
        )
    _global_provider = provider
    return provider


def reset_price_provider_v2() -> None:
    """Reset global singleton (for testing)."""
    global _global_provider
    _global_provider = None


# ---------------------------------------------------------------------------
# V1 compatibility bridge — wraps PriceResultV2 into old PriceQuote shape
# ---------------------------------------------------------------------------


class V1CompatibleBridge:
    """
    Bridge that provides the old PriceProvider interface (get_quote, get_price, get_prices)
    while using PriceProvider V2 internally.
    Dashboard, morning, evening can use this without changing their call patterns.
    """

    def __init__(self, v2_provider: BasePriceProviderV2 | None = None):
        self._v2 = v2_provider or get_price_provider_v2()

    def get_price(self, symbol: str) -> Decimal | None:
        result = self._v2.get_price(symbol)
        return result.price

    def get_prices(self, symbols: Iterable[str]) -> dict[str, Decimal | None]:
        results = self._v2.get_prices(symbols)
        return {sym: res.price for sym, res in results.items()}

    def get_quote(self, symbol: str) -> PriceResultV2:
        return self._v2.get_price(symbol)

    def get_quotes(self, symbols: Iterable[str]) -> dict[str, PriceResultV2]:
        return self._v2.get_prices(symbols)

    @property
    def v2_provider(self) -> BasePriceProviderV2:
        return self._v2
