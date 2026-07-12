#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Strict production market provider with explicit cache and demo isolation."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd
import yfinance as yf

from northstar.data.market_snapshot import parse_timestamp


class MarketDataProvider:
    """Fetch real quotes; failures are explicit and never become invented prices."""

    SUPPORTED_MODES = frozenset({"production", "demo"})

    def __init__(
        self,
        *,
        mode: str = "production",
        cache_file: str | Path = "northstar/data/price_cache.json",
        cache_ttl: timedelta = timedelta(minutes=15),
        ticker_factory: Callable[[str], Any] | None = None,
        fallback_fetcher: Callable[[list[str]], Mapping[str, Mapping[str, Any]]] | None = None,
        demo_prices: Mapping[str, float] | None = None,
        persist_cache: bool = True,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if mode not in self.SUPPORTED_MODES:
            raise ValueError(f"unsupported market-data mode: {mode}")
        if mode == "demo" and demo_prices is None:
            raise ValueError("demo mode requires explicit demo_prices")
        self.mode = mode
        self.cache_file = str(cache_file)
        self.cache_ttl = cache_ttl
        self.ticker_factory = ticker_factory or yf.Ticker
        self.fallback_fetcher = fallback_fetcher
        self.demo_prices = {str(k).upper(): float(v) for k, v in (demo_prices or {}).items()}
        self.persist_cache = persist_cache
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.cache: dict[str, dict[str, Any]] = {}
        self._load_cache()

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _iso(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        normalized = str(symbol).strip().upper()
        if not normalized:
            raise ValueError("symbol must not be empty")
        return normalized

    def _load_cache(self) -> None:
        try:
            with open(self.cache_file, "r", encoding="utf-8") as cache_handle:
                cached_data = json.load(cache_handle)
            if isinstance(cached_data, dict):
                self.cache = cached_data
        except (OSError, ValueError, TypeError):
            self.cache = {}

    def _save_cache(self) -> None:
        if not self.persist_cache:
            return
        cache_directory = os.path.dirname(self.cache_file)
        if cache_directory:
            os.makedirs(cache_directory, exist_ok=True)
        temporary_file = f"{self.cache_file}.tmp"
        try:
            with open(temporary_file, "w", encoding="utf-8") as cache_handle:
                json.dump(self.cache, cache_handle, ensure_ascii=False, indent=2)
            os.replace(temporary_file, self.cache_file)
        except OSError:
            try:
                if os.path.exists(temporary_file):
                    os.remove(temporary_file)
            except OSError:
                pass

    @staticmethod
    def _close_series(history: pd.DataFrame) -> pd.Series:
        if history is None or history.empty or "Close" not in history:
            return pd.Series(dtype=float)
        return pd.to_numeric(history["Close"], errors="coerce").dropna()

    def _history_quote(self, symbol: str) -> dict[str, Any]:
        ticker = self.ticker_factory(symbol)
        history = ticker.history(period="1mo", interval="1d")
        closes = self._close_series(history)
        if closes.empty:
            raise ValueError(f"no price data returned for {symbol}")
        price = float(closes.iloc[-1])
        if price <= 0:
            raise ValueError(f"invalid non-positive price for {symbol}")
        previous = float(closes.iloc[-2]) if len(closes) >= 2 else None
        index_value = closes.index[-1] if len(closes.index) else None
        if hasattr(index_value, "to_pydatetime"):
            index_value = index_value.to_pydatetime()
        as_of_dt = parse_timestamp(index_value)
        if as_of_dt is None:
            raise ValueError(f"quote timestamp unavailable for {symbol}")
        c5 = float((price - float(closes.iloc[-5])) / float(closes.iloc[-5]) * 100) if len(closes) >= 5 else None
        c20 = float((price - float(closes.iloc[0])) / float(closes.iloc[0]) * 100) if len(closes) >= 2 else None
        change_today = float((price - previous) / previous * 100) if previous and previous > 0 else None
        quote = {
            "symbol": symbol,
            "price": price,
            "currency": "USD",
            "source": "yfinance",
            "as_of": self._iso(as_of_dt),
            "status": "valid",
            "is_stale": False,
            "is_mock": False,
            "error_code": None,
            "error_message": None,
            "previous_close": previous,
            "change_pct_today": round(change_today, 4) if change_today is not None else None,
            "change_pct_5d": round(c5, 4) if c5 is not None else None,
            "change_pct_20d": round(c20, 4) if c20 is not None else None,
        }
        self.cache[symbol] = {
            **quote,
            "origin_source": "yfinance",
            "cached_at": self._iso(self._now()),
        }
        self._save_cache()
        return quote

    def _real_fallback(self, symbol: str) -> dict[str, Any] | None:
        fetcher = self.fallback_fetcher
        if fetcher is None:
            from northstar.data.yahoo_quote_provider import fetch_quotes

            fetcher = fetch_quotes
        try:
            raw = dict(fetcher([symbol]).get(symbol, {}))
        except Exception:
            return None
        price = raw.get("price")
        as_of = parse_timestamp(raw.get("as_of", raw.get("timestamp")))
        try:
            numeric_price = float(price) if price is not None else None
        except (TypeError, ValueError):
            numeric_price = None
        if numeric_price is None or numeric_price <= 0 or as_of is None:
            return None
        quote = {
            "symbol": symbol,
            "price": numeric_price,
            "currency": str(raw.get("currency") or "USD"),
            "source": str(raw.get("source") or "yahoo_quote"),
            "as_of": self._iso(as_of),
            "status": "valid",
            "is_stale": False,
            "is_mock": False,
            "error_code": None,
            "error_message": None,
            "previous_close": raw.get("previous_close"),
            "change_pct_today": raw.get("change_pct_today", raw.get("change_pct")),
            "change_pct_5d": raw.get("change_pct_5d"),
            "change_pct_20d": raw.get("change_pct_20d"),
        }
        self.cache[symbol] = {
            **quote,
            "origin_source": quote["source"],
            "cached_at": self._iso(self._now()),
        }
        self._save_cache()
        return quote

    def _cache_quote(self, symbol: str) -> dict[str, Any] | None:
        raw = self.cache.get(symbol)
        if not isinstance(raw, dict):
            return None
        origin = str(raw.get("origin_source") or "").strip()
        as_of = parse_timestamp(raw.get("as_of"))
        cached_at = parse_timestamp(raw.get("cached_at"))
        try:
            price = float(raw.get("price"))
        except (TypeError, ValueError):
            return None
        if not origin or origin in {"cache", "mock", "demo"} or as_of is None or cached_at is None or price <= 0:
            return None
        stale = self._now() - cached_at > self.cache_ttl
        return {
            "symbol": symbol,
            "price": price,
            "currency": str(raw.get("currency") or "USD"),
            "source": "cache",
            "as_of": self._iso(as_of),
            "status": "stale" if stale else "valid",
            "is_stale": stale,
            "is_mock": False,
            "error_code": "CACHE_STALE" if stale else None,
            "error_message": "cached quote exceeded TTL" if stale else None,
            "previous_close": raw.get("previous_close"),
            "change_pct_today": raw.get("change_pct_today"),
            "change_pct_5d": raw.get("change_pct_5d"),
            "change_pct_20d": raw.get("change_pct_20d"),
            "origin_source": origin,
        }

    def _demo_quote(self, symbol: str) -> dict[str, Any]:
        price = self.demo_prices.get(symbol)
        if price is None or price <= 0:
            return self._error(symbol, "DEMO_PRICE_MISSING", "demo price missing")
        return {
            "symbol": symbol,
            "price": price,
            "currency": "USD",
            "source": "demo",
            "as_of": self._iso(self._now()),
            "status": "mock",
            "is_stale": False,
            "is_mock": True,
            "error_code": "DEMO_ONLY",
            "error_message": "explicit demo quote; forbidden for production decisions",
            "previous_close": None,
            "change_pct_today": None,
            "change_pct_5d": None,
            "change_pct_20d": None,
        }

    @staticmethod
    def _error(symbol: str, code: str, message: str) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "price": None,
            "currency": "USD",
            "source": "unavailable",
            "as_of": None,
            "status": "error",
            "is_stale": False,
            "is_mock": False,
            "error_code": code,
            "error_message": message,
            "previous_close": None,
            "change_pct_today": None,
            "change_pct_5d": None,
            "change_pct_20d": None,
        }

    def get_price(self, symbol: str) -> dict[str, Any]:
        normalized = self._normalize_symbol(symbol)
        if self.mode == "demo":
            return self._demo_quote(normalized)
        primary_error = "unknown market-data failure"
        try:
            return self._history_quote(normalized)
        except Exception as exc:
            primary_error = str(exc)
        fallback = self._real_fallback(normalized)
        if fallback is not None:
            return fallback
        cached = self._cache_quote(normalized)
        if cached is not None:
            return cached
        return self._error(normalized, "QUOTE_UNAVAILABLE", primary_error)

    def get_batch_prices(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        return {self._normalize_symbol(symbol): self.get_price(symbol) for symbol in symbols}

    def get_market_context(self) -> dict[str, Any]:
        try:
            closes = self._close_series(self.ticker_factory("SPY").history(period="5d", interval="1d"))
            if len(closes) < 2:
                raise ValueError("insufficient SPY history")
            spy_return = float(closes.iloc[-1] / closes.iloc[0] - 1.0)
            daily_returns = closes.pct_change().dropna()
            volatility = float(daily_returns.std(ddof=0)) if not daily_returns.empty else 0.0
            regime = "bull" if spy_return > 0.01 else "bear" if spy_return < -0.01 else "sideways"
            trend = "up" if regime == "bull" else "down" if regime == "bear" else "sideways"
            confidence = min(1.0, abs(spy_return) / 0.03) if regime != "sideways" else max(0.0, 1.0 - abs(spy_return) / 0.01)
            return {"status": "valid", "SPY_trend": trend, "volatility": volatility, "market_regime": regime, "confidence": confidence}
        except Exception as exc:
            return {"status": "error", "SPY_trend": "unknown", "volatility": None, "market_regime": "unknown", "confidence": 0.0, "error": str(exc)}

    def get_technical_features(self, symbol: str) -> dict[str, Any]:
        normalized = self._normalize_symbol(symbol)
        try:
            closes = self._close_series(self.ticker_factory(normalized).history(period="3mo", interval="1d"))
            if len(closes) < 2:
                raise ValueError(f"insufficient history for {normalized}")
            return_5d = float(closes.iloc[-1] / closes.iloc[-6] - 1.0) if len(closes) >= 6 else float(closes.iloc[-1] / closes.iloc[0] - 1.0)
            return_20d = float(closes.iloc[-1] / closes.iloc[-21] - 1.0) if len(closes) >= 21 else float(closes.iloc[-1] / closes.iloc[0] - 1.0)
            daily_returns = closes.pct_change().dropna()
            volatility = float(daily_returns.std(ddof=0)) if not daily_returns.empty else 0.0
            momentum = float((return_5d + return_20d) / 2.0)
            trend = "up" if momentum > 0.005 else "down" if momentum < -0.005 else "flat"
            return {"status": "valid", "momentum": momentum, "volatility": volatility, "trend": trend}
        except Exception as exc:
            return {"status": "error", "momentum": None, "volatility": None, "trend": "unknown", "error": str(exc)}
