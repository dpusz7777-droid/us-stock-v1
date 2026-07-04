# -*- coding: utf-8 -*-
"""Tests for the Northstar v52 market data layer."""

from __future__ import annotations

import json
from unittest.mock import patch

import pandas as pd

from northstar.data.market_data_provider import MarketDataProvider


class FakeTicker:
    def __init__(self, symbol: str):
        self.symbol = symbol

    def history(self, period: str) -> pd.DataFrame:
        if period == "1d":
            return pd.DataFrame({"Close": [189.2]})
        if self.symbol == "SPY":
            return pd.DataFrame({"Close": [100.0, 100.5, 101.0, 101.5, 102.0]})
        return pd.DataFrame({"Close": [100.0 + index for index in range(30)]})


class FailingTicker:
    def history(self, period: str) -> pd.DataFrame:
        raise RuntimeError("network unavailable")


def make_provider(tmp_path) -> MarketDataProvider:
    provider = MarketDataProvider()
    provider.cache_file = str(tmp_path / "price_cache.json")
    provider.cache = {}
    return provider


def test_get_price_returns_float(tmp_path) -> None:
    provider = make_provider(tmp_path)

    with patch("northstar.data.market_data_provider.yf.Ticker", FakeTicker):
        quote = provider.get_price("aapl")

    assert quote["symbol"] == "AAPL"
    assert quote["price"] == 189.2
    assert isinstance(quote["price"], float)
    assert quote["source"] == "yfinance"


def test_get_batch_prices_works(tmp_path) -> None:
    provider = make_provider(tmp_path)

    with patch("northstar.data.market_data_provider.yf.Ticker", FakeTicker):
        prices = provider.get_batch_prices(["AAPL", "NVDA"])

    assert prices == {"AAPL": 189.2, "NVDA": 189.2}


def test_cache_fallback_works(tmp_path) -> None:
    provider = make_provider(tmp_path)
    provider.cache = {
        "AAPL": {"price": 175.5, "timestamp": "2026-07-05T00:00:00+00:00"}
    }

    with patch(
        "northstar.data.market_data_provider.yf.Ticker",
        return_value=FailingTicker(),
    ):
        quote = provider.get_price("AAPL")

    assert quote["price"] == 175.5
    assert quote["source"] == "cache"


def test_market_context_returns_regime(tmp_path) -> None:
    provider = make_provider(tmp_path)

    with patch("northstar.data.market_data_provider.yf.Ticker", FakeTicker):
        context = provider.get_market_context()

    assert context["market_regime"] == "bull"
    assert context["SPY_trend"] == "up"
    assert isinstance(context["volatility"], float)


def test_failure_does_not_crash_and_persists_mock_price(tmp_path) -> None:
    provider = make_provider(tmp_path)

    with patch(
        "northstar.data.market_data_provider.yf.Ticker",
        return_value=FailingTicker(),
    ):
        quote = provider.get_price("NVDA")
        context = provider.get_market_context()
        features = provider.get_technical_features("NVDA")

    assert quote["price"] == 123.45
    assert quote["source"] == "cache"
    assert context["market_regime"] == "sideways"
    assert features["trend"] == "flat"

    with open(provider.cache_file, encoding="utf-8") as cache_handle:
        cache = json.load(cache_handle)
    assert cache["NVDA"]["price"] == 123.45


def test_technical_features_return_expected_shape(tmp_path) -> None:
    provider = make_provider(tmp_path)

    with patch("northstar.data.market_data_provider.yf.Ticker", FakeTicker):
        features = provider.get_technical_features("AAPL")

    assert set(features) == {"momentum", "volatility", "trend"}
    assert isinstance(features["momentum"], float)
    assert isinstance(features["volatility"], float)
    assert features["trend"] == "up"
