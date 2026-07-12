# -*- coding: utf-8 -*-
"""Strict market-provider tests: failures never become invented prices."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from northstar.data.market_data_provider import MarketDataProvider


NOW = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)


class FakeTicker:
    def __init__(self, symbol: str):
        self.symbol = symbol

    def history(self, period: str, interval: str = "1d") -> pd.DataFrame:
        count = 5 if period == "5d" else 30
        index = pd.date_range(end=NOW, periods=count, freq="D", tz="UTC")
        values = [100.0 + item for item in range(count)]
        return pd.DataFrame({"Close": values}, index=index)


class FailingTicker:
    def history(self, period: str, interval: str = "1d") -> pd.DataFrame:
        raise RuntimeError("network unavailable")


def make_provider(tmp_path, **overrides) -> MarketDataProvider:
    defaults = {
        "cache_file": tmp_path / "price_cache.json",
        "ticker_factory": FakeTicker,
        "fallback_fetcher": lambda symbols: {},
        "persist_cache": True,
        "clock": lambda: NOW,
    }
    defaults.update(overrides)
    return MarketDataProvider(**defaults)


def test_real_quote_has_required_provenance(tmp_path) -> None:
    quote = make_provider(tmp_path).get_price("aapl")
    assert quote["symbol"] == "AAPL"
    assert quote["price"] == 129.0
    assert quote["source"] == "yfinance"
    assert quote["status"] == "valid"
    assert quote["as_of"]
    assert quote["is_mock"] is False


def test_batch_returns_attributed_quotes(tmp_path) -> None:
    quotes = make_provider(tmp_path).get_batch_prices(["AAPL", "NVDA"])
    assert set(quotes) == {"AAPL", "NVDA"}
    assert all(row["status"] == "valid" for row in quotes.values())


def test_fresh_trusted_cache_fallback_is_eligible(tmp_path) -> None:
    provider = make_provider(tmp_path, ticker_factory=lambda symbol: FailingTicker())
    provider.cache = {
        "AAPL": {
            "price": 175.5,
            "source": "yfinance",
            "origin_source": "yfinance",
            "as_of": NOW.isoformat(),
            "cached_at": NOW.isoformat(),
        }
    }
    quote = provider.get_price("AAPL")
    assert quote["price"] == 175.5
    assert quote["source"] == "cache"
    assert quote["status"] == "valid"


def test_stale_cache_is_explicit_and_not_refreshed(tmp_path) -> None:
    provider = make_provider(
        tmp_path,
        ticker_factory=lambda symbol: FailingTicker(),
        cache_ttl=timedelta(minutes=15),
    )
    provider.cache = {
        "AAPL": {
            "price": 175.5,
            "origin_source": "yfinance",
            "as_of": (NOW - timedelta(days=1)).isoformat(),
            "cached_at": (NOW - timedelta(hours=1)).isoformat(),
        }
    }
    quote = provider.get_price("AAPL")
    assert quote["status"] == "stale"
    assert quote["is_stale"] is True


def test_untrusted_legacy_cache_is_rejected(tmp_path) -> None:
    provider = make_provider(tmp_path, ticker_factory=lambda symbol: FailingTicker())
    provider.cache = {"AAPL": {"price": 175.5, "timestamp": NOW.isoformat()}}
    quote = provider.get_price("AAPL")
    assert quote["price"] is None
    assert quote["status"] == "error"
    assert quote["error_code"] == "QUOTE_UNAVAILABLE"


def test_total_failure_does_not_persist_mock_price(tmp_path) -> None:
    cache_file = tmp_path / "price_cache.json"
    provider = make_provider(tmp_path, ticker_factory=lambda symbol: FailingTicker())
    quote = provider.get_price("NVDA")
    assert quote["price"] is None
    assert quote["source"] == "unavailable"
    assert quote["status"] == "error"
    assert quote["is_mock"] is False
    assert not cache_file.exists()


def test_demo_mode_is_explicitly_mock(tmp_path) -> None:
    provider = make_provider(tmp_path, mode="demo", demo_prices={"NVDA": 42.0})
    quote = provider.get_price("NVDA")
    assert quote["price"] == 42.0
    assert quote["source"] == "demo"
    assert quote["status"] == "mock"
    assert quote["is_mock"] is True


def test_context_and_features_fail_closed(tmp_path) -> None:
    provider = make_provider(tmp_path, ticker_factory=lambda symbol: FailingTicker())
    assert provider.get_market_context()["status"] == "error"
    features = provider.get_technical_features("NVDA")
    assert features["status"] == "error"
    assert features["momentum"] is None
