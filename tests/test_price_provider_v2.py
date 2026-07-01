# -*- coding: utf-8 -*-
"""PriceProvider V2 测试。"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path

from price_provider_v2 import (
    PRICE_STATUS_OK,
    PRICE_STATUS_STALE,
    PRICE_STATUS_NOT_FOUND,
    PRICE_STATUS_TIMEOUT,
    PRICE_STATUS_PROVIDER_ERROR,
    PriceResultV2,
    YFinanceProviderV2,
    MockProviderV2,
    FallbackChainV2,
    _MemoryCache,
    _DiskCache,
    get_price_provider_v2,
    reset_price_provider_v2,
)


class TestPriceResultV2(unittest.TestCase):
    def test_success_result(self) -> None:
        r = PriceResultV2(symbol="AAPL", price=Decimal("150.25"))
        self.assertEqual(r.symbol, "AAPL")
        self.assertEqual(r.price, Decimal("150.25"))
        self.assertEqual(r.currency, "USD")
        self.assertEqual(r.status, PRICE_STATUS_OK)
        self.assertTrue(r.is_ok)
        self.assertFalse(r.is_fail)
        self.assertFalse(r.cached)
        self.assertIsNotNone(r.fetched_at)

    def test_not_found_result(self) -> None:
        r = PriceResultV2(
            symbol="UNKNOWN",
            price=None,
            status=PRICE_STATUS_NOT_FOUND,
            error_code="NO_PRICE",
            error_message="price not found",
        )
        self.assertFalse(r.is_ok)
        self.assertTrue(r.is_fail)
        self.assertEqual(r.error_code, "NO_PRICE")

    def test_stale_result(self) -> None:
        r = PriceResultV2(
            symbol="AAPL",
            price=Decimal("150.00"),
            status=PRICE_STATUS_STALE,
            cached=True,
        )
        self.assertFalse(r.is_ok)
        self.assertFalse(r.is_fail)
        self.assertTrue(r.cached)

    def test_to_dict_includes_price_as_string(self) -> None:
        r = PriceResultV2(symbol="AAPL", price=Decimal("150.25"))
        d = r.to_dict()
        self.assertEqual(d["symbol"], "AAPL")
        self.assertEqual(d["price"], "150.25")
        self.assertEqual(d["status"], PRICE_STATUS_OK)

    def test_to_dict_with_none_price(self) -> None:
        r = PriceResultV2(symbol="TEST", price=None, status=PRICE_STATUS_NOT_FOUND)
        d = r.to_dict()
        self.assertIsNone(d["price"])


class TestMemoryCache(unittest.TestCase):
    def test_set_and_get(self) -> None:
        cache = _MemoryCache(ttl=60)
        r = PriceResultV2(symbol="AAPL", price=Decimal("150"))
        cache.set("AAPL", r)
        cached = cache.get("AAPL")
        self.assertIsNotNone(cached)
        self.assertEqual(cached.price, Decimal("150"))

    def test_expired(self) -> None:
        cache = _MemoryCache(ttl=0)
        r = PriceResultV2(symbol="AAPL", price=Decimal("150"))
        cache.set("AAPL", r)
        cached = cache.get("AAPL")
        self.assertIsNone(cached)

    def test_missing(self) -> None:
        cache = _MemoryCache()
        self.assertIsNone(cache.get("MISSING"))

    def test_invalidate(self) -> None:
        cache = _MemoryCache()
        cache.set("AAPL", PriceResultV2(symbol="AAPL", price=Decimal("150")))
        cache.invalidate("AAPL")
        self.assertIsNone(cache.get("AAPL"))

    def test_clear(self) -> None:
        cache = _MemoryCache()
        cache.set("A", PriceResultV2(symbol="A", price=Decimal("100")))
        cache.set("B", PriceResultV2(symbol="B", price=Decimal("200")))
        cache.clear()
        self.assertIsNone(cache.get("A"))
        self.assertIsNone(cache.get("B"))


class TestDiskCache(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache = _DiskCache(cache_dir=self.temp_dir.name, ttl=300)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_set_and_get(self) -> None:
        r = PriceResultV2(symbol="AAPL", price=Decimal("150.25"))
        self.cache.set(r)
        cached = self.cache.get("AAPL")
        self.assertIsNotNone(cached)
        self.assertEqual(cached.price, Decimal("150.25"))
        self.assertTrue(cached.cached)

    def test_missing_returns_none(self) -> None:
        self.assertIsNone(self.cache.get("MISSING"))

    def test_expired_returns_none(self) -> None:
        cache = _DiskCache(cache_dir=self.temp_dir.name, ttl=0)
        r = PriceResultV2(symbol="AAPL", price=Decimal("150"))
        cache.set(r)
        time.sleep(0.01)
        self.assertIsNone(cache.get("AAPL"))

    def test_invalid_json_returns_none(self) -> None:
        path = Path(self.temp_dir.name) / "BAD.json"
        path.write_text("not json", encoding="utf-8")
        self.assertIsNone(self.cache.get("BAD"))


class TestMockProviderV2(unittest.TestCase):
    def test_mock_price_success(self) -> None:
        provider = MockProviderV2({"AAPL": Decimal("150.25")})
        result = provider.get_price("AAPL")
        self.assertEqual(result.price, Decimal("150.25"))
        self.assertEqual(result.status, PRICE_STATUS_OK)
        self.assertEqual(result.source, "mock")

    def test_mock_price_not_found(self) -> None:
        provider = MockProviderV2({})
        result = provider.get_price("UNKNOWN")
        self.assertIsNone(result.price)
        self.assertEqual(result.status, PRICE_STATUS_NOT_FOUND)

    def test_mock_get_prices(self) -> None:
        provider = MockProviderV2({"AAPL": Decimal("150"), "MSFT": Decimal("300")})
        results = provider.get_prices(["AAPL", "MSFT"])
        self.assertEqual(len(results), 2)
        self.assertEqual(results["AAPL"].price, Decimal("150"))
        self.assertEqual(results["MSFT"].price, Decimal("300"))

    def test_mock_empty_symbol(self) -> None:
        provider = MockProviderV2()
        result = provider.get_price("")
        self.assertEqual(result.status, PRICE_STATUS_NOT_FOUND)
        self.assertEqual(result.error_code, "EMPTY_SYMBOL")

    def test_mock_set_price(self) -> None:
        provider = MockProviderV2()
        provider.set_price("AAPL", Decimal("200"))
        result = provider.get_price("AAPL")
        self.assertEqual(result.price, Decimal("200"))


class TestFallbackChainV2(unittest.TestCase):
    def test_first_provider_succeeds(self) -> None:
        mock1 = MockProviderV2({"AAPL": Decimal("100")})
        mock2 = MockProviderV2({"AAPL": Decimal("200")})
        chain = FallbackChainV2([mock1, mock2])
        result = chain.get_price("AAPL")
        self.assertEqual(result.price, Decimal("100"))

    def test_fallback_on_failure(self) -> None:
        mock1 = MockProviderV2({})
        mock2 = MockProviderV2({"AAPL": Decimal("200")})
        chain = FallbackChainV2([mock1, mock2])
        result = chain.get_price("AAPL")
        self.assertEqual(result.price, Decimal("200"))

    def test_all_fail(self) -> None:
        mock1 = MockProviderV2({})
        mock2 = MockProviderV2({})
        chain = FallbackChainV2([mock1, mock2])
        result = chain.get_price("AAPL")
        self.assertEqual(result.status, PRICE_STATUS_NOT_FOUND)

    def test_empty_provider_list_raises(self) -> None:
        with self.assertRaises(Exception):
            FallbackChainV2([])


class TestYFinanceProviderV2(unittest.TestCase):
    """Test with mock ticker factory and isolated temp cache."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _make_ticker_factory(self, name: str, price_val: float = 150.0, raises: type[Exception] | None = None):
        """Return a ticker factory that returns configured mock info."""
        class MockTicker:
            def __init__(self, symbol: str):
                self._symbol = symbol

            @property
            def info(self) -> dict:
                if raises is not None:
                    raise raises("mock error")
                return {"currentPrice": price_val}

            @property
            def fast_info(self):
                return {}

            def history(self, period=None, interval=None):
                import pandas as pd
                return pd.DataFrame()

        return lambda s: MockTicker(s)

    def _make_provider(self, factory, retries=0, timeout=5):
        return YFinanceProviderV2(
            ticker_factory=factory,
            timeout=timeout,
            retries=retries,
            disk_cache=_DiskCache(cache_dir=self.tmp.name, ttl=300),
            memory_cache=_MemoryCache(ttl=300),
        )

    def test_single_price_success(self) -> None:
        factory = self._make_ticker_factory("AAPL", 150.25)
        provider = self._make_provider(factory)
        result = provider.get_price("AAPL")
        self.assertEqual(result.price, Decimal("150.25"))
        self.assertEqual(result.status, PRICE_STATUS_OK)
        self.assertEqual(result.source, "yfinance")

    def test_batch_prices(self) -> None:
        class MultiTicker:
            def __init__(self, symbol: str):
                self._symbol = symbol

            @property
            def info(self) -> dict:
                prices = {"AAPL": 150.0, "MSFT": 300.0}
                return {"currentPrice": prices.get(self._symbol)}

            @property
            def fast_info(self):
                return {}

            def history(self, period=None, interval=None):
                import pandas as pd
                return pd.DataFrame()

        factory = lambda s: MultiTicker(s)
        provider = self._make_provider(factory)
        results = provider.get_prices(["AAPL", "MSFT"])
        self.assertEqual(len(results), 2)
        self.assertEqual(results["AAPL"].price, Decimal("150.0"))
        self.assertEqual(results["MSFT"].price, Decimal("300.0"))

    def test_not_found_returns_error(self) -> None:
        factory = self._make_ticker_factory("UNKNOWN", price_val=0)
        provider = self._make_provider(factory)
        result = provider.get_price("UNKNOWN")
        self.assertEqual(result.status, PRICE_STATUS_NOT_FOUND)
        self.assertIsNone(result.price)

    def test_timeout_returns_timeout_status(self) -> None:
        def slow_factory(symbol: str):
            import socket
            raise socket.timeout("timed out")

        provider = self._make_provider(slow_factory)
        result = provider.get_price("AAPL")
        self.assertEqual(result.status, PRICE_STATUS_TIMEOUT)

    def test_provider_error_caught(self) -> None:
        """Factory itself throws -> PROVIDER_ERROR."""
        def broken_factory(s):
            raise ValueError("network error")
        provider = self._make_provider(broken_factory)
        result = provider.get_price("AAPL")
        self.assertEqual(result.status, PRICE_STATUS_PROVIDER_ERROR)

    def test_live_fail_stale_cache(self) -> None:
        """Live fails but disk cache exists -> STALE."""
        # Step 1: first get_price succeeds and writes to cache
        factory_ok = self._make_ticker_factory("AAPL", 100.0)
        ok_provider = self._make_provider(factory_ok, retries=0)
        result_ok = ok_provider.get_price("AAPL")
        self.assertEqual(result_ok.status, PRICE_STATUS_OK)

        # Step 2: second get_price with failing factory 
        # uses a FRESH memory cache so it doesn't skip live 
        def fail_factory(s):
            raise ConnectionError("network down")

        fail_provider = YFinanceProviderV2(
            ticker_factory=fail_factory,
            timeout=5,
            retries=0,
            disk_cache=_DiskCache(cache_dir=self.tmp.name, ttl=300),
            memory_cache=_MemoryCache(ttl=300),  # fresh memory cache
        )
        result = fail_provider.get_price("AAPL")
        self.assertEqual(result.status, PRICE_STATUS_STALE)
        self.assertEqual(result.price, Decimal("100.0"))
        self.assertTrue(result.cached)

    def test_empty_symbol(self) -> None:
        factory = self._make_ticker_factory("", 100.0)
        provider = self._make_provider(factory)
        result = provider.get_price("")
        self.assertEqual(result.status, PRICE_STATUS_NOT_FOUND)
        self.assertEqual(result.error_code, "EMPTY_SYMBOL")

    def test_case_normalization(self) -> None:
        factory = self._make_ticker_factory("AAPL", 150.0)
        provider = self._make_provider(factory)
        r1 = provider.get_price("aapl")
        r2 = provider.get_price("AAPL")
        self.assertEqual(r1.price, r2.price)

    def test_cache_avoided_when_disabled(self) -> None:
        factory = self._make_ticker_factory("AAPL", 200.0)
        no_cache_disk = _DiskCache(cache_dir=self.tmp.name, ttl=0)
        no_cache_mem = _MemoryCache(ttl=0)
        provider = YFinanceProviderV2(
            ticker_factory=factory,
            timeout=5,
            retries=0,
            disk_cache=no_cache_disk,
            memory_cache=no_cache_mem,
        )
        r1 = provider.get_price("AAPL")
        self.assertEqual(r1.price, Decimal("200.0"))


class TestGlobalProvider(unittest.TestCase):
    def tearDown(self) -> None:
        reset_price_provider_v2()

    def test_get_provider_returns_instance(self) -> None:
        provider = get_price_provider_v2()
        self.assertIsNotNone(provider)

    def test_get_provider_is_singleton(self) -> None:
        p1 = get_price_provider_v2()
        p2 = get_price_provider_v2()
        self.assertIs(p1, p2)

    def test_reset_provider(self) -> None:
        p1 = get_price_provider_v2()
        reset_price_provider_v2()
        p2 = get_price_provider_v2()
        self.assertIsNot(p1, p2)

    def test_no_cache_provider(self) -> None:
        provider = get_price_provider_v2(use_cache=False)
        self.assertIsNotNone(provider)


class TestV2DoesNotModifyPortfolio(unittest.TestCase):
    def test_mock_provider_no_portfolio_access(self) -> None:
        provider = MockProviderV2({"AAPL": Decimal("150")})
        result = provider.get_price("AAPL")
        self.assertEqual(result.price, Decimal("150"))

    def test_v2_no_broker_connection(self) -> None:
        provider = MockProviderV2({"TEST": Decimal("100")})
        result = provider.get_price("TEST")
        self.assertEqual(result.status, PRICE_STATUS_OK)
        self.assertEqual(result.source, "mock")

    def test_provider_accepts_no_args(self) -> None:
        provider = MockProviderV2()
        p = provider.get_price("MISSING")
        self.assertEqual(p.status, PRICE_STATUS_NOT_FOUND)


if __name__ == "__main__":
    unittest.main()