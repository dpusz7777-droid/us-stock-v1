# -*- coding: utf-8 -*-
"""SignalEngine 测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from broker_provider import (
    BrokerAccountSnapshot,
    BrokerPosition,
    BrokerPortfolioSnapshot,
    MockBrokerProvider,
)
from event_bus import event_bus
from events import SIGNAL_GENERATED
from price_provider_v2 import PriceResultV2, PRICE_STATUS_OK
from signal_engine import SignalEngine, SignalType, Signal, signal_engine


def _make_price_result(
    symbol: str,
    price: Decimal | None = Decimal("100.0"),
    status: str = PRICE_STATUS_OK,
) -> PriceResultV2:
    return PriceResultV2(symbol=symbol, price=price, status=status)


def _make_broker_snapshot(
    positions: list[tuple[str, Decimal, Decimal, Decimal, Decimal]] | None = None,
    cash: Decimal = Decimal("1000"),
    buying_power: Decimal = Decimal("800"),
    unrealized_pnl: Decimal = Decimal("0"),
) -> BrokerPortfolioSnapshot:
    """Create a BrokerPortfolioSnapshot from simplified position data."""
    account = BrokerAccountSnapshot(
        account_id_masked="test***",
        broker="mock",
        cash=cash,
        buying_power=buying_power,
        unrealized_pnl=unrealized_pnl,
        positions_market_value=Decimal("0"),
    )
    broker_positions: list[BrokerPosition] = []
    total_mv = Decimal("0")
    for sym, shares, avg_cost, last_price, upnl_pct in (positions or []):
        mv = shares * last_price
        upnl = (last_price - avg_cost) * shares
        total_mv += mv
        broker_positions.append(BrokerPosition(
            symbol=sym,
            shares=shares,
            avg_cost=avg_cost,
            last_price=last_price,
            market_value=mv,
            unrealized_pnl=upnl,
            unrealized_pnl_pct=upnl_pct,
        ))
    account = BrokerAccountSnapshot(
        account_id_masked="test***",
        broker="mock",
        cash=cash,
        buying_power=buying_power,
        unrealized_pnl=unrealized_pnl,
        positions_market_value=total_mv,
    )
    return BrokerPortfolioSnapshot(account=account, positions=broker_positions)


class TestSignalType(unittest.TestCase):
    def test_signal_type_values(self) -> None:
        self.assertEqual(SignalType.BUY.value, "BUY")
        self.assertEqual(SignalType.SELL.value, "SELL")
        self.assertEqual(SignalType.HOLD.value, "HOLD")
        self.assertEqual(SignalType.REDUCE.value, "REDUCE")
        self.assertEqual(SignalType.INCREASE.value, "INCREASE")
        self.assertEqual(SignalType.RISK_OFF.value, "RISK_OFF")

    def test_signal_type_is_enum(self) -> None:
        self.assertTrue(issubclass(SignalType, Enum))


class TestSignalDataclass(unittest.TestCase):
    def test_minimal_signal(self) -> None:
        s = Signal(symbol="AAPL", signal_type=SignalType.BUY, strength=80, confidence=0.75, reason="test", source="price")
        self.assertEqual(s.symbol, "AAPL")
        self.assertEqual(s.signal_type, SignalType.BUY)
        self.assertEqual(s.strength, 80)
        self.assertEqual(s.confidence, 0.75)
        self.assertEqual(s.source, "price")

    def test_signal_immutable(self) -> None:
        s = Signal(symbol="AAPL", signal_type=SignalType.HOLD, strength=30, confidence=0.3, reason="test", source="price")
        with self.assertRaises(AttributeError):
            s.strength = 100

    def test_to_dict(self) -> None:
        s = Signal(symbol="AAPL", signal_type=SignalType.BUY, strength=85, confidence=0.8, reason="momentum", source="price")
        d = s.to_dict()
        self.assertEqual(d["symbol"], "AAPL")
        self.assertEqual(d["signal_type"], "BUY")
        self.assertEqual(d["strength"], 85)
        self.assertEqual(d["confidence"], 0.8)

    def test_strength_range(self) -> None:
        for val in [0, 1, 50, 99, 100]:
            s = Signal(symbol="T", signal_type=SignalType.HOLD, strength=val, confidence=0.5, reason="test", source="price")
            self.assertEqual(s.strength, val)

    def test_confidence_range(self) -> None:
        for val in [0.0, 0.1, 0.5, 0.99, 1.0]:
            s = Signal(symbol="T", signal_type=SignalType.HOLD, strength=50, confidence=val, reason="test", source="price")
            self.assertEqual(s.confidence, val)


class TestSignalEngineMomentum(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = SignalEngine()
        event_bus.clear_log()

    def test_strong_buy_above_5pct(self) -> None:
        signals = self.engine.evaluate_with_change_pct("AAPL", Decimal("105.0"), Decimal("5.5"))
        self.assertTrue(any(s.signal_type == SignalType.BUY for s in signals))
        buy = [s for s in signals if s.signal_type == SignalType.BUY][0]
        self.assertGreaterEqual(buy.strength, 90)
        self.assertGreaterEqual(buy.confidence, 0.8)

    def test_buy_above_3pct(self) -> None:
        signals = self.engine.evaluate_with_change_pct("AAPL", Decimal("103.5"), Decimal("3.5"))
        self.assertTrue(any(s.signal_type == SignalType.BUY for s in signals))
        buy = [s for s in signals if s.signal_type == SignalType.BUY][0]
        self.assertGreaterEqual(buy.strength, 70)
        self.assertLess(buy.strength, 95)

    def test_momentum_strength_increases_with_change(self) -> None:
        s1 = self.engine.evaluate_with_change_pct("AAPL", Decimal("103"), Decimal("3.0"))
        s2 = self.engine.evaluate_with_change_pct("AAPL", Decimal("104"), Decimal("4.0"))
        b1 = [s for s in s1 if s.signal_type == SignalType.BUY]
        b2 = [s for s in s2 if s.signal_type == SignalType.BUY]
        if b1 and b2:
            self.assertGreaterEqual(b2[0].strength, b1[0].strength)

    def test_no_buy_below_3pct(self) -> None:
        signals = self.engine.evaluate_with_change_pct("AAPL", Decimal("101"), Decimal("1.0"))
        buys = [s for s in signals if s.signal_type == SignalType.BUY]
        self.assertEqual(len(buys), 0)


class TestSignalEngineMeanReversion(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = SignalEngine()
        event_bus.clear_log()

    def test_strong_sell_below_minus5pct(self) -> None:
        signals = self.engine.evaluate_with_change_pct("AAPL", Decimal("94"), Decimal("-6.0"))
        self.assertTrue(any(s.signal_type == SignalType.SELL for s in signals))
        sell = [s for s in signals if s.signal_type == SignalType.SELL][0]
        self.assertGreaterEqual(sell.strength, 90)

    def test_risk_off_below_minus3pct(self) -> None:
        signals = self.engine.evaluate_with_change_pct("AAPL", Decimal("96"), Decimal("-4.0"))
        self.assertTrue(any(s.signal_type == SignalType.RISK_OFF for s in signals))

    def test_hold_for_small_decline(self) -> None:
        signals = self.engine.evaluate_with_change_pct("AAPL", Decimal("99"), Decimal("-1.0"))
        holds = [s for s in signals if s.signal_type == SignalType.HOLD]
        self.assertTrue(len(holds) > 0)

    def test_hold_for_small_gain(self) -> None:
        signals = self.engine.evaluate_with_change_pct("AAPL", Decimal("101"), Decimal("1.0"))
        holds = [s for s in signals if s.signal_type == SignalType.HOLD]
        self.assertTrue(len(holds) > 0)


class TestSignalEnginePortfolioExposure(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = SignalEngine()
        event_bus.clear_log()

    def test_reduce_when_position_over_20pct(self) -> None:
        snap = _make_broker_snapshot([
            ("SOFI", Decimal("1000"), Decimal("10"), Decimal("15"), Decimal("50")),
            ("AAPL", Decimal("20"), Decimal("150"), Decimal("150"), Decimal("0")),
        ])
        signals = self.engine._evaluate_exposure_strategies(snap)
        reduces = [s for s in signals if s.signal_type == SignalType.REDUCE]
        self.assertTrue(len(reduces) > 0)
        self.assertTrue(any("SOFI" in s.symbol for s in reduces))

    def test_sell_when_loss_over_10pct(self) -> None:
        snap = _make_broker_snapshot([
            ("SOFI", Decimal("100"), Decimal("20"), Decimal("17"), Decimal("-15")),
        ])
        signals = self.engine._evaluate_exposure_strategies(snap)
        sells = [s for s in signals if s.signal_type == SignalType.SELL]
        self.assertTrue(len(sells) > 0)

    def test_risk_off_when_portfolio_loss_high(self) -> None:
        snap = _make_broker_snapshot(
            positions=[("SOFI", Decimal("100"), Decimal("20"), Decimal("17"), Decimal("-15"))],
            unrealized_pnl=Decimal("-300"),
        )
        signals = self.engine._evaluate_exposure_strategies(snap)
        risk_off = [s for s in signals if s.signal_type == SignalType.RISK_OFF]
        self.assertTrue(len(risk_off) > 0)

    def test_no_signals_for_healthy_portfolio(self) -> None:
        # 6 equal positions, each ~16.7% (< 20% single position threshold)
        snap = _make_broker_snapshot([
            ("A", Decimal("10"), Decimal("10"), Decimal("10"), Decimal("0")),
            ("B", Decimal("10"), Decimal("10"), Decimal("10"), Decimal("0")),
            ("C", Decimal("10"), Decimal("10"), Decimal("10"), Decimal("0")),
            ("D", Decimal("10"), Decimal("10"), Decimal("10"), Decimal("0")),
            ("E", Decimal("10"), Decimal("10"), Decimal("10"), Decimal("0")),
            ("F", Decimal("10"), Decimal("10"), Decimal("10"), Decimal("0")),
        ])
        signals = self.engine._evaluate_exposure_strategies(snap)
        self.assertEqual(len(signals), 0)

    def test_empty_positions_no_signals(self) -> None:
        snap = _make_broker_snapshot([])
        signals = self.engine._evaluate_exposure_strategies(snap)
        self.assertEqual(signals, [])


class TestSignalEngineEvaluate(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = SignalEngine()
        event_bus.clear_log()

    def test_evaluate_with_price_only(self) -> None:
        prices = {"AAPL": _make_price_result("AAPL", Decimal("100"))}
        signals = self.engine.evaluate(prices)
        self.assertTrue(len(signals) > 0)
        self.assertTrue(any(s.signal_type == SignalType.HOLD for s in signals))

    def test_evaluate_with_broker(self) -> None:
        prices = {"AAPL": _make_price_result("AAPL", Decimal("100"))}
        snap = _make_broker_snapshot([
            ("AAPL", Decimal("500"), Decimal("90"), Decimal("100"), Decimal("11")),
        ])
        signals = self.engine.evaluate(prices, snap)
        self.assertTrue(len(signals) > 0)

    def test_evaluate_with_stale_price_skipped(self) -> None:
        from price_provider_v2 import PRICE_STATUS_STALE
        prices = {"AAPL": _make_price_result("AAPL", Decimal("100"), status=PRICE_STATUS_STALE)}
        signals = self.engine.evaluate(prices)
        self.assertEqual(len(signals), 0)

    def test_evaluate_empty_prices(self) -> None:
        signals = self.engine.evaluate({})
        self.assertEqual(signals, [])

    def test_signals_sorted_by_strength(self) -> None:
        prices = {
            "A": _make_price_result("A", Decimal("100")),
            "B": _make_price_result("B", Decimal("200")),
        }
        signals = self.engine.evaluate(prices)
        for i in range(len(signals) - 1):
            self.assertGreaterEqual(signals[i].strength, signals[i + 1].strength)


class TestEventBusIntegration(unittest.TestCase):
    def setUp(self) -> None:
        event_bus.clear()
        event_bus.clear_log()

    def test_signal_generated_event_published(self) -> None:
        engine = SignalEngine()
        received: list[dict] = []
        def listener(data: Any) -> None:
            received.append(data)
        event_bus.subscribe(SIGNAL_GENERATED, listener)
        engine.evaluate_with_change_pct("AAPL", Decimal("105"), Decimal("5.0"))
        self.assertTrue(len(received) > 0)
        self.assertIn("signal", received[0])

    def test_event_contains_signal_data(self) -> None:
        engine = SignalEngine()
        received: list[dict] = []
        def listener(data: Any) -> None:
            received.append(data)
        event_bus.subscribe(SIGNAL_GENERATED, listener)
        engine.evaluate_with_change_pct("AAPL", Decimal("105"), Decimal("5.0"))
        self.assertEqual(received[0]["signal"]["symbol"], "AAPL")
        self.assertEqual(received[0]["signal"]["signal_type"], "BUY")


class TestNoNetworkOrPortfolioModification(unittest.TestCase):
    def test_no_network_imports(self) -> None:
        with open("signal_engine.py", "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        import_lines = [l.strip() for l in lines if l.strip().startswith("import ") or l.strip().startswith("from ")]
        import_text = "\n".join(import_lines).lower()
        for lib in ["socket", "http", "requests", "yfinance"]:
            with self.subTest(lib=lib):
                self.assertNotIn(lib, import_text)

    def test_no_trade_methods(self) -> None:
        for name in dir(SignalEngine):
            lower = name.lower()
            if "order" in lower or "trade" in lower or "place" in lower:
                self.fail(f"SignalEngine has forbidden method: {name}")

    def test_no_file_write(self) -> None:
        with open("signal_engine.py", "r", encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn(".write(", source)
        self.assertNotIn("open(", source)


class TestGlobalSingleton(unittest.TestCase):
    def test_signal_engine_is_singleton(self) -> None:
        from signal_engine import signal_engine as se1
        from signal_engine import signal_engine as se2
        self.assertIs(se1, se2)


if __name__ == "__main__":
    unittest.main()