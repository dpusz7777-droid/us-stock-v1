# -*- coding: utf-8 -*-
"""price_provider 单元测试。"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd

from price_provider import (
    DuplicateSymbolError,
    InvalidPriceError,
    InvalidSymbolError,
    MockPriceProvider,
    PriceQuote,
    PriceNotFoundError,
    StaticPriceProvider,
    YFinancePriceProvider,
    normalize_symbol,
)


class PriceProviderTests(unittest.TestCase):
    def test_normalize_symbol_strips_spaces_and_uppercases(self) -> None:
        self.assertEqual(normalize_symbol(" sofi "), "SOFI")
        self.assertEqual(normalize_symbol("spcx"), "SPCX")

    def test_normalize_symbol_raises_for_empty_string(self) -> None:
        with self.assertRaises(InvalidSymbolError):
            normalize_symbol("  ")

    def test_normalize_symbol_raises_for_non_string(self) -> None:
        with self.assertRaises(InvalidSymbolError):
            normalize_symbol(123)  # type: ignore[arg-type]

    def test_static_provider_reads_prices(self) -> None:
        provider = StaticPriceProvider({"SOFI": 20.5, "SPCX": 161.0})
        self.assertEqual(provider.get_price("sofi"), Decimal("20.5"))
        self.assertEqual(provider.get_price(" SPCX "), Decimal("161.0"))

    def test_mock_provider_inherits_static_behavior(self) -> None:
        provider = MockPriceProvider({"SOFI": 20.5})
        self.assertEqual(provider.get_price("sofi"), Decimal("20.5"))

    def test_get_prices_returns_all_requested_symbols(self) -> None:
        provider = StaticPriceProvider({"SOFI": 20.5, "SPCX": 161.0})
        prices = provider.get_prices(["sofi", "spcx"])
        self.assertEqual(prices, {"SOFI": Decimal("20.5"), "SPCX": Decimal("161.0")})

    def test_get_prices_raises_for_duplicate_requested_symbol(self) -> None:
        provider = StaticPriceProvider({"SOFI": 20.5})
        with self.assertRaises(DuplicateSymbolError):
            provider.get_prices(["sofi", " SOFI "])

    def test_static_provider_raises_for_unknown_symbol(self) -> None:
        provider = StaticPriceProvider({"SOFI": 20.5})
        with self.assertRaises(PriceNotFoundError):
            provider.get_price("SPCX")

    def test_static_provider_raises_for_empty_symbol(self) -> None:
        provider = StaticPriceProvider({"SOFI": 20.5})
        with self.assertRaises(InvalidSymbolError):
            provider.get_price("  ")

    def test_static_provider_raises_for_negative_price(self) -> None:
        with self.assertRaises(InvalidPriceError):
            StaticPriceProvider({"SOFI": -1.0})

    def test_static_provider_raises_for_zero_price(self) -> None:
        with self.assertRaises(InvalidPriceError):
            StaticPriceProvider({"SOFI": 0})

    def test_static_provider_raises_for_non_numeric_price(self) -> None:
        with self.assertRaises(InvalidPriceError):
            StaticPriceProvider({"SOFI": "invalid"})

    def test_static_provider_raises_for_duplicate_symbol_in_input(self) -> None:
        with self.assertRaises(DuplicateSymbolError):
            StaticPriceProvider({"SOFI": 20.5, " sofi ": 21.0})

    def test_static_provider_with_decimal_price(self) -> None:
        provider = StaticPriceProvider({"SOFI": Decimal("20.5")})
        self.assertEqual(provider.get_price("SOFI"), Decimal("20.5"))

    def test_static_provider_can_return_quote_shape(self) -> None:
        provider = StaticPriceProvider({"SOFI": Decimal("20.5")})

        quote = provider.get_quote("sofi")

        self.assertIsInstance(quote, PriceQuote)
        self.assertEqual(quote.symbol, "SOFI")
        self.assertEqual(quote.price, Decimal("20.5"))
        self.assertIsNone(quote.previous_close)
        self.assertEqual(quote.source, "StaticPriceProvider")
        self.assertTrue(quote.price_as_of.endswith("Z"))


class FakeTicker:
    def __init__(self, info: dict):
        self.info = info


class HistoryFallbackTicker:
    @property
    def info(self) -> dict:
        raise RuntimeError("info unavailable")

    @property
    def fast_info(self) -> dict:
        return {}

    def history(self, period: str, interval: str):
        return pd.DataFrame(
            {"Close": [17.91, 17.10]},
            index=pd.to_datetime(["2026-06-18 20:00:00Z", "2026-06-22 20:00:00Z"]),
        )


class YFinancePriceProviderTests(unittest.TestCase):
    def make_provider(self, data: dict[str, dict]) -> YFinancePriceProvider:
        def ticker_factory(symbol: str) -> FakeTicker:
            if symbol not in data:
                raise KeyError(symbol)
            return FakeTicker(data[symbol])

        return YFinancePriceProvider(
            ticker_factory=ticker_factory,
            clock=lambda: datetime(2026, 6, 23, 15, 30, tzinfo=timezone.utc),
        )

    def test_get_quote_returns_normalized_yfinance_data(self) -> None:
        provider = self.make_provider(
            {
                "SOFI": {
                    "currentPrice": 20.5,
                    "previousClose": 19.75,
                    "regularMarketTime": 1782199800,
                }
            }
        )

        quote = provider.get_quote(" sofi ")

        self.assertEqual(quote.symbol, "SOFI")
        self.assertEqual(quote.price, Decimal("20.5"))
        self.assertEqual(quote.previous_close, Decimal("19.75"))
        self.assertEqual(quote.source, "yfinance")
        self.assertEqual(quote.price_as_of, "2026-06-23T07:30:00Z")

    def test_get_quote_falls_back_to_regular_market_price(self) -> None:
        provider = self.make_provider(
            {"SPCX": {"regularMarketPrice": 161.25, "previousClose": 160}}
        )

        quote = provider.get_quote("SPCX")

        self.assertEqual(quote.price, Decimal("161.25"))
        self.assertEqual(quote.previous_close, Decimal("160"))
        self.assertEqual(quote.price_as_of, "2026-06-23T15:30:00Z")

    def test_get_quote_falls_back_to_history_when_info_is_unavailable(self) -> None:
        provider = YFinancePriceProvider(
            ticker_factory=lambda symbol: HistoryFallbackTicker(),
            clock=lambda: datetime(2026, 6, 23, 15, 30, tzinfo=timezone.utc),
        )

        quote = provider.get_quote("SOFI")

        self.assertEqual(quote.symbol, "SOFI")
        self.assertEqual(quote.price, Decimal("17.1"))
        self.assertEqual(quote.previous_close, Decimal("17.91"))
        self.assertEqual(quote.source, "yfinance")
        self.assertEqual(quote.price_as_of, "2026-06-22T20:00:00Z")

    def test_get_price_returns_decimal_for_compatibility(self) -> None:
        provider = self.make_provider({"SOFI": {"currentPrice": 20.5}})

        self.assertEqual(provider.get_price("SOFI"), Decimal("20.5"))

    def test_get_quotes_returns_all_requested_quotes(self) -> None:
        provider = self.make_provider(
            {
                "SOFI": {"currentPrice": 20.5, "previousClose": 19.75},
                "SPCX": {"currentPrice": 161.0, "previousClose": 160.0},
            }
        )

        quotes = provider.get_quotes(["sofi", "spcx"])

        self.assertEqual(set(quotes), {"SOFI", "SPCX"})
        self.assertEqual(quotes["SOFI"].price, Decimal("20.5"))
        self.assertEqual(quotes["SPCX"].previous_close, Decimal("160.0"))

    def test_get_prices_returns_decimal_prices_for_compatibility(self) -> None:
        provider = self.make_provider(
            {
                "SOFI": {"currentPrice": 20.5},
                "SPCX": {"currentPrice": 161.0},
            }
        )

        prices = provider.get_prices(["sofi", "spcx"])

        self.assertEqual(prices, {"SOFI": Decimal("20.5"), "SPCX": Decimal("161.0")})

    def test_get_quotes_raises_for_duplicate_symbols(self) -> None:
        provider = self.make_provider({"SOFI": {"currentPrice": 20.5}})

        with self.assertRaises(DuplicateSymbolError):
            provider.get_quotes(["sofi", " SOFI "])

    def test_get_quote_raises_for_missing_symbol(self) -> None:
        provider = self.make_provider({})

        with self.assertRaises(PriceNotFoundError):
            provider.get_quote("SOFI")

    def test_get_quote_raises_for_invalid_price(self) -> None:
        provider = self.make_provider({"SOFI": {"currentPrice": None}})

        with self.assertRaises(InvalidPriceError):
            provider.get_quote("SOFI")


if __name__ == "__main__":
    unittest.main()
