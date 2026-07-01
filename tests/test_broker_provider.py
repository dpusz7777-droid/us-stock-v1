# -*- coding: utf-8 -*-
"""BrokerProvider 测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from broker_provider import (
    BROKER_STATUS_OK,
    BROKER_STATUS_DEGRADED,
    BROKER_STATUS_NOT_CONFIGURED,
    BROKER_STATUS_UNSUPPORTED,
    BROKER_STATUS_PROVIDER_ERROR,
    BrokerAccountSnapshot,
    BrokerPosition,
    BrokerPortfolioSnapshot,
    BaseBrokerProvider,
    MockBrokerProvider,
    DisabledBrokerProvider,
    create_broker_provider,
    check_broker_provider_safety,
    _check_no_trade_methods,
)


def _make_portfolio(cash: float = 100.0, buying_power: float = 80.0,
                    shares: float = 2, avg_cost: float = 10.0,
                    account_id: str = "test_acc_001") -> dict:
    return {
        "schema_version": "1.1",
        "account": {
            "account_id": account_id,
            "account_name": "test",
            "broker": "test",
            "base_currency": "USD",
            "cash_status": "known",
            "cash": cash,
            "buying_power": buying_power,
            "created_at": "2026-06-22T17:00:00Z",
            "updated_at": "2026-06-22T17:00:00Z",
        },
        "settings": {
            "stop_loss_pct": 8,
            "target_profit_pct": 25,
            "max_single_position_pct": 20,
        },
        "transactions": [
            {
                "transaction_id": "txn_001",
                "external_id": None,
                "transaction_type": "OPENING_POSITION",
                "symbol": "SOFI",
                "shares": shares,
                "price": avg_cost,
                "amount": None,
                "fees": 0,
                "executed_at": None,
                "effective_at": "2026-06-22T17:15:41Z",
                "recorded_at": "2026-06-22T17:15:41Z",
                "source": "legacy_migration",
                "note": "test",
            }
        ],
    }


class TestBrokerAccountSnapshot(unittest.TestCase):
    def test_default_read_only(self) -> None:
        snap = BrokerAccountSnapshot(account_id_masked="test***", broker="mock")
        self.assertTrue(snap.read_only)
        self.assertEqual(snap.status, BROKER_STATUS_OK)
        self.assertEqual(snap.base_currency, "USD")

    def test_to_dict_converts_decimals(self) -> None:
        snap = BrokerAccountSnapshot(
            account_id_masked="test***", broker="mock",
            cash=Decimal("100.50"), buying_power=Decimal("80.00"),
        )
        d = snap.to_dict()
        self.assertEqual(d["cash"], "100.50")
        self.assertEqual(d["buying_power"], "80.00")
        self.assertEqual(d["read_only"], True)

    def test_degraded_status(self) -> None:
        snap = BrokerAccountSnapshot(
            account_id_masked="unknown***", broker="mock",
            status=BROKER_STATUS_DEGRADED,
            error_code="NO_PORTFOLIO",
        )
        self.assertEqual(snap.status, BROKER_STATUS_DEGRADED)
        self.assertEqual(snap.error_code, "NO_PORTFOLIO")


class TestBrokerPosition(unittest.TestCase):
    def test_minimal_position(self) -> None:
        pos = BrokerPosition(symbol="SOFI")
        self.assertEqual(pos.symbol, "SOFI")
        self.assertEqual(pos.asset_type, "STOCK")
        self.assertEqual(pos.currency, "USD")

    def test_full_position(self) -> None:
        pos = BrokerPosition(
            symbol="SOFI", display_name="SoFi Technologies",
            shares=Decimal("10"), avg_cost=Decimal("8.50"),
            last_price=Decimal("12.00"), market_value=Decimal("120.00"),
            unrealized_pnl=Decimal("35.00"), unrealized_pnl_pct=Decimal("41.18"),
        )
        self.assertEqual(pos.shares, Decimal("10"))
        self.assertEqual(pos.market_value, Decimal("120.00"))

    def test_to_dict(self) -> None:
        pos = BrokerPosition(symbol="SOFI", shares=Decimal("10"))
        d = pos.to_dict()
        self.assertEqual(d["symbol"], "SOFI")
        self.assertEqual(d["shares"], "10")


class TestBrokerPortfolioSnapshot(unittest.TestCase):
    def test_minimal_snapshot(self) -> None:
        account = BrokerAccountSnapshot(account_id_masked="test***", broker="mock")
        snap = BrokerPortfolioSnapshot(account=account, positions=[])
        self.assertTrue(snap.read_only)
        self.assertEqual(len(snap.positions), 0)

    def test_with_positions(self) -> None:
        account = BrokerAccountSnapshot(account_id_masked="test***", broker="mock")
        pos = BrokerPosition(symbol="SOFI", shares=Decimal("10"))
        snap = BrokerPortfolioSnapshot(account=account, positions=[pos])
        self.assertEqual(len(snap.positions), 1)
        self.assertEqual(snap.positions[0].symbol, "SOFI")

    def test_to_dict(self) -> None:
        account = BrokerAccountSnapshot(account_id_masked="test***", broker="mock")
        snap = BrokerPortfolioSnapshot(account=account, positions=[])
        d = snap.to_dict()
        self.assertIn("account", d)
        self.assertIn("positions", d)
        self.assertIn("read_only", d)
        self.assertTrue(d["read_only"])


class TestBaseBrokerProvider(unittest.TestCase):
    def test_no_trade_methods_on_base(self) -> None:
        """BaseBrokerProvider must not have trade methods."""
        for name in ["place_order", "cancel_order", "modify_order", "trade", "auto_trade"]:
            with self.subTest(name=name):
                self.assertFalse(hasattr(BaseBrokerProvider, name))

    def test_subclass_with_trade_method_raises(self) -> None:
        """Defining a trade method on a subclass must raise TypeError."""
        with self.assertRaises(TypeError) as ctx:
            class BadProvider(BaseBrokerProvider):
                def place_order(self) -> None:
                    pass
        self.assertIn("place_order", str(ctx.exception))

    def test_subclass_with_auto_trade_raises(self) -> None:
        with self.assertRaises(TypeError):
            class BadProvider(BaseBrokerProvider):
                def auto_trade(self) -> None:
                    pass

    def test_base_raises_not_implemented(self) -> None:
        """Direct instantiation of Base must raise NotImplementedError."""
        class Minimal(BaseBrokerProvider):
            pass
        m = Minimal()
        with self.assertRaises(NotImplementedError):
            m.get_account_snapshot()
        with self.assertRaises(NotImplementedError):
            m.get_positions()
        with self.assertRaises(NotImplementedError):
            m.get_portfolio_snapshot()
        with self.assertRaises(NotImplementedError):
            m.health_check()

    def test_check_no_trade_methods_passes_clean(self) -> None:
        """_check_no_trade_methods should pass for clean classes."""
        class CleanClass:
            def get_data(self) -> str:
                return "clean"
        # Should not raise
        _check_no_trade_methods(CleanClass)

    def test_check_no_trade_methods_fails_on_bad_name(self) -> None:
        class BadClass:
            def place_order(self) -> None:
                pass
        with self.assertRaises(TypeError):
            _check_no_trade_methods(BadClass)


class TestMockBrokerProvider(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.portfolio_path = Path(self.temp_dir.name) / "portfolio.json"
        self.portfolio_path.write_text(
            json.dumps(_make_portfolio(cash=100.0, buying_power=80.0)),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_init(self) -> None:
        provider = MockBrokerProvider(portfolio_path=self.portfolio_path)
        self.assertIsNotNone(provider)

    def test_get_account_snapshot(self) -> None:
        provider = MockBrokerProvider(portfolio_path=self.portfolio_path)
        snap = provider.get_account_snapshot()
        self.assertTrue(snap.read_only)
        self.assertIn("***", snap.account_id_masked)
        self.assertEqual(snap.status, BROKER_STATUS_OK)
        self.assertIsNotNone(snap.cash)
        self.assertIsNotNone(snap.buying_power)

    def test_get_positions(self) -> None:
        provider = MockBrokerProvider(portfolio_path=self.portfolio_path)
        positions = provider.get_positions()
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].symbol, "SOFI")
        self.assertEqual(positions[0].shares, Decimal("2"))

    def test_get_portfolio_snapshot(self) -> None:
        provider = MockBrokerProvider(portfolio_path=self.portfolio_path)
        snap = provider.get_portfolio_snapshot()
        self.assertTrue(snap.read_only)
        self.assertEqual(len(snap.positions), 1)
        self.assertEqual(snap.account.status, BROKER_STATUS_OK)

    def test_health_check(self) -> None:
        provider = MockBrokerProvider(portfolio_path=self.portfolio_path)
        hc = provider.health_check()
        self.assertTrue(hc["ok"])
        self.assertTrue(hc["read_only"])
        self.assertFalse(hc["connected_to_broker"])
        self.assertFalse(hc["has_sensitive_data"])

    def test_no_network(self) -> None:
        """MockBrokerProvider must not import network libraries."""
        import importlib
        spec = importlib.util.find_spec("broker_provider")
        self.assertIsNotNone(spec)
        with open(spec.origin, "r", encoding="utf-8") as fh:
            source = fh.read()
        for lib in ["requests", "httpx", "yfinance"]:
            with self.subTest(lib=lib):
                # import of the library should not appear in source
                self.assertNotIn(f"import {lib}", source)

    def test_no_portfolio_file(self) -> None:
        missing = Path(self.temp_dir.name) / "missing.json"
        provider = MockBrokerProvider(portfolio_path=missing)
        snap = provider.get_account_snapshot()
        self.assertEqual(snap.status, BROKER_STATUS_DEGRADED)
        self.assertEqual(snap.error_code, "NO_PORTFOLIO")

    def test_no_portfolio_positions_empty(self) -> None:
        missing = Path(self.temp_dir.name) / "missing.json"
        provider = MockBrokerProvider(portfolio_path=missing)
        positions = provider.get_positions()
        self.assertEqual(positions, [])

    def test_account_id_masked(self) -> None:
        provider = MockBrokerProvider(portfolio_path=self.portfolio_path)
        snap = provider.get_account_snapshot()
        self.assertIn("***", snap.account_id_masked)
        self.assertNotEqual(snap.account_id_masked, "test_acc_001")

    def test_read_only_always_true(self) -> None:
        provider = MockBrokerProvider(portfolio_path=self.portfolio_path)
        snap = provider.get_portfolio_snapshot()
        self.assertTrue(snap.read_only)
        self.assertTrue(snap.account.read_only)

    def test_no_trade_methods_on_mock(self) -> None:
        """MockBrokerProvider must not have trade methods."""
        for name in ["place_order", "cancel_order", "modify_order", "trade", "auto_trade"]:
            with self.subTest(name=name):
                self.assertFalse(hasattr(MockBrokerProvider, name))


class TestDisabledBrokerProvider(unittest.TestCase):
    def test_init(self) -> None:
        provider = DisabledBrokerProvider()
        self.assertIsNotNone(provider)

    def test_status_not_configured(self) -> None:
        provider = DisabledBrokerProvider()
        snap = provider.get_account_snapshot()
        self.assertEqual(snap.status, BROKER_STATUS_NOT_CONFIGURED)

    def test_portfolio_snapshot_empty(self) -> None:
        provider = DisabledBrokerProvider()
        snap = provider.get_portfolio_snapshot()
        self.assertEqual(snap.status, BROKER_STATUS_NOT_CONFIGURED)
        self.assertEqual(len(snap.positions), 0)

    def test_health_check(self) -> None:
        provider = DisabledBrokerProvider()
        hc = provider.health_check()
        self.assertFalse(hc["ok"])
        self.assertTrue(hc["read_only"])
        self.assertFalse(hc["connected_to_broker"])

    def test_no_trade_methods(self) -> None:
        for name in ["place_order", "cancel_order", "modify_order", "trade", "auto_trade"]:
            self.assertFalse(hasattr(DisabledBrokerProvider, name))


class TestBrokerProviderFactory(unittest.TestCase):
    def test_create_mock(self) -> None:
        provider = create_broker_provider("mock")
        self.assertIsInstance(provider, MockBrokerProvider)

    def test_create_disabled(self) -> None:
        provider = create_broker_provider("disabled")
        self.assertIsInstance(provider, DisabledBrokerProvider)

    def test_create_default_is_mock(self) -> None:
        provider = create_broker_provider()
        self.assertIsInstance(provider, MockBrokerProvider)

    def test_create_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            create_broker_provider("unknown_broker")

    def test_create_usmart_returns_placeholder(self) -> None:
        provider = create_broker_provider("usmart")
        snap = provider.get_account_snapshot()
        self.assertEqual(snap.status, BROKER_STATUS_UNSUPPORTED)


class TestBrokerProviderSafety(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.portfolio_path = Path(self.temp_dir.name) / "portfolio.json"
        self.portfolio_path.write_text(
            json.dumps(_make_portfolio()),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_safe_mock_provider(self) -> None:
        provider = MockBrokerProvider(portfolio_path=self.portfolio_path)
        warnings = check_broker_provider_safety(provider)
        self.assertEqual(warnings, [])

    def test_safe_disabled_provider(self) -> None:
        provider = DisabledBrokerProvider()
        warnings = check_broker_provider_safety(provider)
        self.assertEqual(warnings, [])

    def test_account_id_masked(self) -> None:
        provider = MockBrokerProvider(portfolio_path=self.portfolio_path)
        snap = provider.get_account_snapshot()
        self.assertIn("***", snap.account_id_masked)

    def test_no_sensitive_data_in_logs(self) -> None:
        """Verify mock provider output doesn't contain raw account IDs."""
        provider = MockBrokerProvider(portfolio_path=self.portfolio_path)
        snap = provider.get_account_snapshot()
        # The raw ID "test_acc_001" should NOT appear in masked output
        self.assertNotIn("test_acc_001", snap.account_id_masked)
        # to_dict should also be safe
        d = snap.to_dict()
        self.assertNotIn("test_acc_001", str(d))


class TestV2Phase3Compatibility(unittest.TestCase):
    """Ensure Phase 3 doesn't break V1/V2 commands."""

    def test_mock_no_portfolio_modification(self) -> None:
        """MockBrokerProvider must not modify portfolio file."""
        import json, os
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio.json"
            path.write_text(json.dumps(_make_portfolio()), encoding="utf-8")
            original = path.read_text(encoding="utf-8")
            provider = MockBrokerProvider(portfolio_path=path)
            _ = provider.get_portfolio_snapshot()
            after = path.read_text(encoding="utf-8")
            self.assertEqual(original, after)

    def test_mock_no_broker_connection(self) -> None:
        provider = MockBrokerProvider()
        hc = provider.health_check()
        self.assertFalse(hc["connected_to_broker"])

    def test_no_sensitive_imports(self) -> None:
        """Verify broker_provider.py has no import of network/sensitive libraries."""
        with open("broker_provider.py", "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        import_lines = [l.strip() for l in lines if l.strip().startswith("import ") or l.strip().startswith("from ")]
        import_text = "\n".join(import_lines).lower()
        for lib in ["requests", "httpx", "yfinance"]:
            with self.subTest(lib=lib):
                self.assertNotIn(lib, import_text, f"broker_provider imports {lib}")


if __name__ == "__main__":
    unittest.main()