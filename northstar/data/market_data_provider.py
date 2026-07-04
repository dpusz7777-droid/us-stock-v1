#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Northstar v52 market data layer backed by yfinance."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import yfinance as yf


class MarketDataProvider:
    """Provide live prices and basic market features with a local fallback."""

    MOCK_PRICE = 123.45

    def __init__(self):
        self.cache = {}
        self.cache_file = "northstar/data/price_cache.json"
        self._load_cache()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

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

    def get_price(self, symbol: str) -> dict[str, Any]:
        """Return the latest close, falling back to cache or a mock price."""
        normalized_symbol = self._normalize_symbol(symbol)
        timestamp = self._now()

        try:
            ticker = yf.Ticker(normalized_symbol)
            closes = self._close_series(ticker.history(period="1d"))
            if closes.empty:
                raise ValueError(f"No price data returned for {normalized_symbol}")
            price = float(closes.iloc[-1])
            self.cache[normalized_symbol] = {
                "price": price,
                "timestamp": timestamp,
            }
            self._save_cache()
            source = "yfinance"
        except Exception:
            cached_quote = self.cache.get(normalized_symbol, {})
            try:
                price = float(cached_quote["price"])
                timestamp = str(cached_quote.get("timestamp") or timestamp)
            except (KeyError, TypeError, ValueError):
                price = self.MOCK_PRICE
                self.cache[normalized_symbol] = {
                    "price": price,
                    "timestamp": timestamp,
                }
                self._save_cache()
            source = "cache"

        return {
            "symbol": normalized_symbol,
            "price": price,
            "timestamp": timestamp,
            "source": source,
        }

    def get_batch_prices(self, symbols: list) -> dict[str, float]:
        """Return a symbol-to-price mapping."""
        prices: dict[str, float] = {}
        for symbol in symbols:
            quote = self.get_price(symbol)
            prices[quote["symbol"]] = float(quote["price"])
        return prices

    def get_market_context(self) -> dict[str, Any]:
        """Describe the current market regime using the latest SPY closes."""
        try:
            closes = self._close_series(yf.Ticker("SPY").history(period="5d"))
            if len(closes) < 2:
                raise ValueError("Insufficient SPY history")

            spy_return = float(closes.iloc[-1] / closes.iloc[0] - 1.0)
            daily_returns = closes.pct_change().dropna()
            volatility = float(daily_returns.std(ddof=0)) if not daily_returns.empty else 0.0

            if spy_return > 0.01:
                regime = "bull"
                trend = "up"
            elif spy_return < -0.01:
                regime = "bear"
                trend = "down"
            else:
                regime = "sideways"
                trend = "sideways"

            if regime == "sideways":
                confidence = max(0.0, 1.0 - abs(spy_return) / 0.01)
            else:
                confidence = min(1.0, abs(spy_return) / 0.03)
        except Exception:
            trend = "sideways"
            volatility = 0.0
            regime = "sideways"
            confidence = 0.0

        return {
            "SPY_trend": trend,
            "volatility": float(volatility),
            "market_regime": regime,
            "confidence": float(confidence),
        }

    def get_technical_features(self, symbol: str) -> dict[str, Any]:
        """Calculate medium-term momentum and volatility features."""
        normalized_symbol = self._normalize_symbol(symbol)
        try:
            closes = self._close_series(
                yf.Ticker(normalized_symbol).history(period="3mo")
            )
            if len(closes) < 2:
                raise ValueError(f"Insufficient history for {normalized_symbol}")

            return_5d = (
                float(closes.iloc[-1] / closes.iloc[-6] - 1.0)
                if len(closes) >= 6
                else float(closes.iloc[-1] / closes.iloc[0] - 1.0)
            )
            return_20d = (
                float(closes.iloc[-1] / closes.iloc[-21] - 1.0)
                if len(closes) >= 21
                else float(closes.iloc[-1] / closes.iloc[0] - 1.0)
            )
            daily_returns = closes.pct_change().dropna()
            volatility = (
                float(daily_returns.std(ddof=0)) if not daily_returns.empty else 0.0
            )
            momentum = float((return_5d + return_20d) / 2.0)

            if momentum > 0.005:
                trend = "up"
            elif momentum < -0.005:
                trend = "down"
            else:
                trend = "flat"
        except Exception:
            momentum = 0.0
            volatility = 0.0
            trend = "flat"

        return {
            "momentum": float(momentum),
            "volatility": float(volatility),
            "trend": trend,
        }
