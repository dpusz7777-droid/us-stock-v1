#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一行情适配层。

本模块提供统一接口，方便未来接入 Yahoo Finance、Finnhub、IBKR、盈立 API 等。
StaticPriceProvider / MockPriceProvider 用于本地测试和离线演示；
YFinancePriceProvider 用于从 yfinance 获取真实美股行情。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable, Mapping


class PriceProviderError(Exception):
    """行情提供器基础异常。"""


class InvalidSymbolError(PriceProviderError):
    """股票代码无效。"""


class PriceNotFoundError(PriceProviderError):
    """未找到指定股票的价格。"""


class InvalidPriceError(PriceProviderError):
    """行情价格无效。"""


class DuplicateSymbolError(PriceProviderError):
    """初始化时发现重复的股票代码。"""


@dataclass(frozen=True)
class PriceQuote:
    """统一行情结果。"""

    symbol: str
    price: Decimal
    previous_close: Decimal | None
    source: str
    price_as_of: str


def normalize_symbol(symbol: str) -> str:
    """标准化股票代码：去除前后空格并转为大写。"""
    if not isinstance(symbol, str):
        raise InvalidSymbolError("symbol must be a string")
    normalized = symbol.strip().upper()
    if not normalized:
        raise InvalidSymbolError("symbol must not be empty")
    return normalized


def _to_decimal_price(value: Any, symbol: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise InvalidPriceError(
            f"price for {symbol!r} must be a non-negative number"
        )
    if isinstance(value, str):
        raise InvalidPriceError(
            f"price for {symbol!r} must be a numeric value, not string"
        )
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise InvalidPriceError(
            f"price for {symbol!r} is not a valid number"
        ) from exc
    if price <= Decimal("0"):
        raise InvalidPriceError(
            f"price for {symbol!r} must be greater than zero"
        )
    return price


def _to_optional_decimal_price(value: Any, symbol: str) -> Decimal | None:
    if value is None:
        return None
    return _to_decimal_price(value, symbol)


def _iso_utc_from_timestamp(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    return (
        datetime.fromtimestamp(timestamp, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _iso_utc_from_datetime_like(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


class PriceProvider:
    """行情提供器接口基类。"""

    def get_price(self, symbol: str) -> Decimal:
        raise NotImplementedError

    def get_prices(self, symbols: Iterable[str]) -> dict[str, Decimal]:
        raise NotImplementedError

    def get_quote(self, symbol: str) -> PriceQuote:
        normalized = normalize_symbol(symbol)
        return PriceQuote(
            symbol=normalized,
            price=self.get_price(normalized),
            previous_close=None,
            source=self.__class__.__name__,
            price_as_of=datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
        )

    def get_quotes(self, symbols: Iterable[str]) -> dict[str, PriceQuote]:
        result: dict[str, PriceQuote] = {}
        seen: set[str] = set()
        for symbol in symbols:
            normalized = normalize_symbol(symbol)
            if normalized in seen:
                raise DuplicateSymbolError(
                    f"duplicate symbol in request: {normalized}"
                )
            seen.add(normalized)
            result[normalized] = self.get_quote(normalized)
        return result


class StaticPriceProvider(PriceProvider):
    """静态行情提供器，从预定义字典读取价格。"""

    def __init__(self, prices: Mapping[str, Any]):
        if not isinstance(prices, Mapping):
            raise InvalidPriceError("prices must be a mapping of symbol to price")
        normalized: dict[str, Decimal] = {}
        for raw_symbol, raw_price in prices.items():
            norm_symbol = normalize_symbol(raw_symbol)
            if norm_symbol in normalized:
                raise DuplicateSymbolError(
                    f"duplicate symbol after normalization: {norm_symbol}"
                )
            normalized[norm_symbol] = _to_decimal_price(raw_price, norm_symbol)
        self._prices = normalized

    def get_price(self, symbol: str) -> Decimal:
        symbol = normalize_symbol(symbol)
        try:
            return self._prices[symbol]
        except KeyError as exc:
            raise PriceNotFoundError(f"price not found for symbol: {symbol}") from exc

    def get_prices(self, symbols: Iterable[str]) -> dict[str, Decimal]:
        result: dict[str, Decimal] = {}
        seen: set[str] = set()
        for symbol in symbols:
            normalized = normalize_symbol(symbol)
            if normalized in seen:
                raise DuplicateSymbolError(
                    f"duplicate symbol in request: {normalized}"
                )
            seen.add(normalized)
            result[normalized] = self.get_price(normalized)
        return result


class MockPriceProvider(StaticPriceProvider):
    """Mock 行情提供器，当前阶段与 StaticPriceProvider 的行为一致。"""

    pass


class YFinancePriceProvider(PriceProvider):
    """通过 yfinance 获取真实行情。"""

    SOURCE = "yfinance"

    def __init__(
        self,
        ticker_factory: Callable[[str], Any] | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self._ticker_factory = ticker_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _get_ticker_factory(self) -> Callable[[str], Any]:
        if self._ticker_factory is not None:
            return self._ticker_factory
        try:
            import yfinance as yf
        except ImportError as exc:
            raise PriceProviderError(
                "yfinance is not installed; run: pip install yfinance"
            ) from exc
        return yf.Ticker

    def _now_iso(self) -> str:
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return (
            now.astimezone(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    def _quote_from_info(self, symbol: str, info: Mapping[str, Any]) -> PriceQuote:
        price_value = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("previousClose")
        )
        previous_close_value = info.get("previousClose")
        price_as_of = _iso_utc_from_timestamp(info.get("regularMarketTime"))

        return PriceQuote(
            symbol=symbol,
            price=_to_decimal_price(price_value, symbol),
            previous_close=_to_optional_decimal_price(previous_close_value, symbol),
            source=self.SOURCE,
            price_as_of=price_as_of or self._now_iso(),
        )

    def _quote_from_fast_info(self, symbol: str, fast_info: Any) -> PriceQuote:
        price_value = (
            fast_info.get("lastPrice")
            or fast_info.get("last_price")
            or fast_info.get("regularMarketPrice")
            or fast_info.get("previousClose")
            or fast_info.get("previous_close")
        )
        previous_close_value = (
            fast_info.get("previousClose")
            or fast_info.get("previous_close")
            or fast_info.get("regular_market_previous_close")
        )
        return PriceQuote(
            symbol=symbol,
            price=_to_decimal_price(price_value, symbol),
            previous_close=_to_optional_decimal_price(previous_close_value, symbol),
            source=self.SOURCE,
            price_as_of=self._now_iso(),
        )

    def _quote_from_history(self, symbol: str, ticker: Any) -> PriceQuote:
        history = ticker.history(period="5d", interval="1d")
        if getattr(history, "empty", True):
            raise PriceNotFoundError(f"price not found for symbol: {symbol}")

        closes = history["Close"].dropna()
        if len(closes) == 0:
            raise PriceNotFoundError(f"price not found for symbol: {symbol}")

        price_value = closes.iloc[-1]
        previous_close_value = closes.iloc[-2] if len(closes) >= 2 else None
        price_as_of = _iso_utc_from_datetime_like(closes.index[-1])
        return PriceQuote(
            symbol=symbol,
            price=_to_decimal_price(price_value, symbol),
            previous_close=_to_optional_decimal_price(previous_close_value, symbol),
            source=self.SOURCE,
            price_as_of=price_as_of or self._now_iso(),
        )

    def get_quote(self, symbol: str) -> PriceQuote:
        normalized = normalize_symbol(symbol)
        ticker_factory = self._get_ticker_factory()
        try:
            ticker = ticker_factory(normalized)
        except Exception as exc:
            raise PriceNotFoundError(
                f"price not found for symbol: {normalized}"
            ) from exc

        last_error: Exception | None = None
        try:
            info = ticker.info
            if isinstance(info, Mapping):
                return self._quote_from_info(normalized, info)
            last_error = PriceNotFoundError(
                f"price not found for symbol: {normalized}"
            )
        except InvalidPriceError as exc:
            last_error = exc
        except Exception as exc:
            last_error = exc

        try:
            return self._quote_from_fast_info(normalized, ticker.fast_info)
        except InvalidPriceError as exc:
            if last_error is None:
                last_error = exc
        except Exception as exc:
            if not isinstance(last_error, InvalidPriceError):
                last_error = exc

        try:
            return self._quote_from_history(normalized, ticker)
        except InvalidPriceError:
            raise
        except Exception as exc:
            if isinstance(last_error, InvalidPriceError):
                raise last_error
            raise PriceNotFoundError(
                f"price not found for symbol: {normalized}"
            ) from exc

    def get_quotes(self, symbols: Iterable[str]) -> dict[str, PriceQuote]:
        result: dict[str, PriceQuote] = {}
        seen: set[str] = set()
        for symbol in symbols:
            normalized = normalize_symbol(symbol)
            if normalized in seen:
                raise DuplicateSymbolError(
                    f"duplicate symbol in request: {normalized}"
                )
            seen.add(normalized)
            result[normalized] = self.get_quote(normalized)
        return result

    def get_price(self, symbol: str) -> Decimal:
        return self.get_quote(symbol).price

    def get_prices(self, symbols: Iterable[str]) -> dict[str, Decimal]:
        return {
            symbol: quote.price for symbol, quote in self.get_quotes(symbols).items()
        }
