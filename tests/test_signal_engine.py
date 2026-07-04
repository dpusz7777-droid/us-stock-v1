# -*- coding: utf-8 -*-
"""SignalEngine 测试 — V4 Phase 1."""

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
from decision_engine import Decision, DecisionAction, DecisionEngine
from event_bus import event_bus
from events import SIGNAL_GENERATED
from price_provider_v2 import PriceResultV2, PRICE_STATUS_OK
from signal_engine import (
    SignalEngine,
    SignalType,
    Signal,
    signal_engine,
    generate_signal,
)
from execution_engine import ExecutionEngine, OrderStatus


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


# ======================================================================
# SignalType
# ======================================================================


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


# ======================================================================
# Signal dataclass
# ======================================================================


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
        self.assertEqual(d["action"], "BUY")  # 兼容字段
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


# ======================================================================
# generate_signal — 统一信号函数 (V4 Phase 1)
# ======================================================================


class TestGenerateSignal(unittest.TestCase):
    """测试 generate_signal 统一信号函数。"""

    def test_volatility_high_returns_reduce(self) -> None:
        """volatility > 0.03 → REDUCE。"""
        signal = generate_signal({
            "symbol": "AAPL",
            "price": 150.0,
            "change_pct": 0.01,
            "volatility": 0.04,
        })
        self.assertEqual(signal.signal_type, SignalType.REDUCE)
        self.assertEqual(signal.symbol, "AAPL")
        self.assertEqual(signal.source, "unified")

    def test_change_pct_positive_returns_buy(self) -> None:
        """change_pct > 0.02 → BUY。"""
        signal = generate_signal({
            "symbol": "AAPL",
            "price": 150.0,
            "change_pct": 0.03,
            "volatility": 0.01,
        })
        self.assertEqual(signal.signal_type, SignalType.BUY)
        self.assertEqual(signal.symbol, "AAPL")
        self.assertEqual(signal.source, "unified")

    def test_change_pct_negative_returns_sell(self) -> None:
        """change_pct < -0.02 → SELL。"""
        signal = generate_signal({
            "symbol": "AAPL",
            "price": 150.0,
            "change_pct": -0.03,
            "volatility": 0.01,
        })
        self.assertEqual(signal.signal_type, SignalType.SELL)
        self.assertEqual(signal.symbol, "AAPL")
        self.assertEqual(signal.source, "unified")

    def test_no_signal_returns_hold(self) -> None:
        """其他 → HOLD。"""
        signal = generate_signal({
            "symbol": "AAPL",
            "price": 150.0,
            "change_pct": 0.00,
            "volatility": 0.01,
        })
        self.assertEqual(signal.signal_type, SignalType.HOLD)
        self.assertEqual(signal.source, "unified")

    def test_volatility_takes_priority(self) -> None:
        """高 volatility 优先于 change_pct。"""
        signal = generate_signal({
            "symbol": "AAPL",
            "price": 150.0,
            "change_pct": 0.03,  # 通常是 BUY
            "volatility": 0.05,   # 但 volatility 高 → REDUCE
        })
        self.assertEqual(signal.signal_type, SignalType.REDUCE)

    def test_symbol_in_output(self) -> None:
        signal = generate_signal({
            "symbol": "TSLA",
            "price": 200.0,
            "change_pct": 0.01,
            "volatility": 0.02,
        })
        self.assertEqual(signal.symbol, "TSLA")

    def test_timestamp_exists(self) -> None:
        signal = generate_signal({
            "symbol": "AAPL",
            "price": 150.0,
            "change_pct": 0.0,
            "volatility": 0.0,
        })
        self.assertTrue(len(signal.timestamp) > 0)

    def test_default_symbol(self) -> None:
        """不传 symbol 时默认 UNKNOWN。"""
        signal = generate_signal({
            "price": 150.0,
            "change_pct": 0.0,
            "volatility": 0.0,
        })
        self.assertEqual(signal.symbol, "UNKNOWN")

    def test_volatility_boundary(self) -> None:
        """volatility=0.03 未超阈值 → 不应 REDUCE。"""
        signal = generate_signal({
            "symbol": "AAPL",
            "price": 150.0,
            "change_pct": 0.0,
            "volatility": 0.03,
        })
        self.assertNotEqual(signal.signal_type, SignalType.REDUCE)

    def test_change_pct_boundary_positive(self) -> None:
        """change_pct=0.02 未超阈值 → 不应 BUY。"""
        signal = generate_signal({
            "symbol": "AAPL",
            "price": 150.0,
            "change_pct": 0.02,
            "volatility": 0.01,
        })
        self.assertNotEqual(signal.signal_type, SignalType.BUY)

    def test_change_pct_boundary_negative(self) -> None:
        """change_pct=-0.02 未超阈值 → 不应 SELL。"""
        signal = generate_signal({
            "symbol": "AAPL",
            "price": 150.0,
            "change_pct": -0.02,
            "volatility": 0.01,
        })
        self.assertNotEqual(signal.signal_type, SignalType.SELL)

    def test_always_returns_without_none(self) -> None:
        """generate_signal 永远不返回 None。"""
        for args in [
            {"symbol": "A", "price": 100, "change_pct": 0.0, "volatility": 0.0},
            {"symbol": "A", "price": 100, "change_pct": 0.05, "volatility": 0.01},
            {"symbol": "A", "price": 100, "change_pct": -0.05, "volatility": 0.01},
            {"symbol": "A", "price": 100, "change_pct": 0.01, "volatility": 0.05},
        ]:
            signal = generate_signal(args)
            self.assertIsNotNone(signal)
            self.assertIsInstance(signal, Signal)


# ======================================================================
# SignalEngine — Momentum
# ======================================================================


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


# ======================================================================
# SignalEngine — Mean Reversion
# ======================================================================


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


# ======================================================================
# SignalEngine — Portfolio Exposure
# ======================================================================


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


# ======================================================================
# SignalEngine — evaluate (原有)
# ======================================================================


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


# ======================================================================
# SignalEngine — evaluate_unified (V4 Phase 1)
# ======================================================================


class TestSignalEngineEvaluateUnified(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = SignalEngine()
        event_bus.clear()
        event_bus.clear_log()

    def test_evaluate_unified_returns_signal(self) -> None:
        """evaluate_unified 必须返回 Signal 对象。"""
        signal = self.engine.evaluate_unified({
            "symbol": "AAPL",
            "price": 150.0,
            "change_pct": 0.03,
            "volatility": 0.01,
        })
        self.assertIsInstance(signal, Signal)
        self.assertIsNotNone(signal)

    def test_evaluate_unified_buy(self) -> None:
        signal = self.engine.evaluate_unified({
            "symbol": "AAPL", "price": 150.0,
            "change_pct": 0.03, "volatility": 0.01,
        })
        self.assertEqual(signal.signal_type, SignalType.BUY)

    def test_evaluate_unified_sell(self) -> None:
        signal = self.engine.evaluate_unified({
            "symbol": "AAPL", "price": 150.0,
            "change_pct": -0.03, "volatility": 0.01,
        })
        self.assertEqual(signal.signal_type, SignalType.SELL)

    def test_evaluate_unified_reduce(self) -> None:
        signal = self.engine.evaluate_unified({
            "symbol": "AAPL", "price": 150.0,
            "change_pct": 0.01, "volatility": 0.04,
        })
        self.assertEqual(signal.signal_type, SignalType.REDUCE)

    def test_evaluate_unified_hold(self) -> None:
        signal = self.engine.evaluate_unified({
            "symbol": "AAPL", "price": 150.0,
            "change_pct": 0.0, "volatility": 0.01,
        })
        self.assertEqual(signal.signal_type, SignalType.HOLD)

    def test_evaluate_unified_publishes_event(self) -> None:
        """evaluate_unified 必须发布 SIGNAL_GENERATED 事件。"""
        received: list[dict] = []
        def listener(data: Any) -> None:
            received.append(data)
        event_bus.subscribe(SIGNAL_GENERATED, listener)
        self.engine.evaluate_unified({
            "symbol": "AAPL", "price": 150.0,
            "change_pct": 0.03, "volatility": 0.01,
        })
        self.assertEqual(len(received), 1)
        self.assertIn("signal", received[0])
        self.assertEqual(received[0]["has_portfolio"], True)

    def test_evaluate_unified_never_returns_none(self) -> None:
        """evaluate_unified 永远不返回 None。"""
        for data in [
            {"symbol": "A", "price": 100, "change_pct": 0.0, "volatility": 0.0},
            {"symbol": "A", "price": 100, "change_pct": 0.05, "volatility": 0.01},
            {"symbol": "A", "price": 100, "change_pct": -0.05, "volatility": 0.01},
            {"symbol": "A", "price": 100, "change_pct": 0.01, "volatility": 0.05},
        ]:
            signal = self.engine.evaluate_unified(data)
            self.assertIsNotNone(signal)
            self.assertIsInstance(signal, Signal)

    def test_evaluate_unified_has_timestamp(self) -> None:
        signal = self.engine.evaluate_unified({
            "symbol": "AAPL", "price": 150.0,
            "change_pct": 0.0, "volatility": 0.0,
        })
        self.assertTrue(len(signal.timestamp) > 0)


# ======================================================================
# Signal → Decision → Execution 全链路测试 (V4 Phase 1)
# ======================================================================


class TestSignalToExecutionPipeline(unittest.TestCase):
    """验证 Signal → Decision → Execution 链路通畅。"""

    def setUp(self) -> None:
        self.signal_engine = SignalEngine()
        self.decision_engine = DecisionEngine()
        self.execution_engine = ExecutionEngine(deterministic=True)
        event_bus.clear()
        event_bus.clear_log()

    def test_signal_to_decision_buy(self) -> None:
        """BUY 信号必须能传递到 Decision（返回 BUY）。"""
        decision = self.signal_engine.evaluate_unified_to_decision(
            price_data={
                "symbol": "AAPL",
                "price": 150.0,
                "change_pct": 0.03,
                "volatility": 0.01,
            },
            decision_engine=self.decision_engine,
        )
        self.assertIsNotNone(decision)
        self.assertEqual(decision.action, DecisionAction.BUY)

    def test_signal_to_decision_sell(self) -> None:
        """SELL 信号必须能传递到 Decision（返回 SELL）。"""
        decision = self.signal_engine.evaluate_unified_to_decision(
            price_data={
                "symbol": "AAPL",
                "price": 150.0,
                "change_pct": -0.03,
                "volatility": 0.01,
            },
            decision_engine=self.decision_engine,
        )
        self.assertIsNotNone(decision)
        self.assertEqual(decision.action, DecisionAction.SELL)

    def test_signal_to_decision_reduce(self) -> None:
        """REDUCE 信号必须能传递到 Decision（返回 REDUCE）。"""
        decision = self.signal_engine.evaluate_unified_to_decision(
            price_data={
                "symbol": "AAPL",
                "price": 150.0,
                "change_pct": 0.01,
                "volatility": 0.04,
            },
            decision_engine=self.decision_engine,
        )
        self.assertIsNotNone(decision)
        self.assertEqual(decision.action, DecisionAction.REDUCE)

    def test_signal_to_decision_hold(self) -> None:
        """HOLD 信号必须能传递到 Decision（返回 HOLD）。"""
        decision = self.signal_engine.evaluate_unified_to_decision(
            price_data={
                "symbol": "AAPL",
                "price": 150.0,
                "change_pct": 0.0,
                "volatility": 0.01,
            },
            decision_engine=self.decision_engine,
        )
        self.assertIsNotNone(decision)
        self.assertEqual(decision.action, DecisionAction.HOLD)

    def test_decision_has_required_fields(self) -> None:
        """Decision 必须包含 symbol / action / confidence / timestamp。"""
        decision = self.signal_engine.evaluate_unified_to_decision(
            price_data={
                "symbol": "AAPL",
                "price": 150.0,
                "change_pct": 0.03,
                "volatility": 0.01,
            },
            decision_engine=self.decision_engine,
        )
        self.assertTrue(hasattr(decision, "symbol"))
        self.assertTrue(hasattr(decision, "action"))
        self.assertTrue(hasattr(decision, "confidence"))
        self.assertTrue(hasattr(decision, "timestamp"))

    def test_decision_to_execution_buy(self) -> None:
        """Decision(BUY) → ExecutionEngine.submit_order 必须返回 FILLED。"""
        decision = self.signal_engine.evaluate_unified_to_decision(
            price_data={
                "symbol": "AAPL",
                "price": 150.0,
                "change_pct": 0.03,
                "volatility": 0.01,
            },
            decision_engine=self.decision_engine,
        )
        from decimal import Decimal
        result = self.execution_engine.submit_order(decision, Decimal("150.00"), Decimal("100"))
        self.assertIsNotNone(result)
        self.assertEqual(result.status, OrderStatus.FILLED)

    def test_decision_to_execution_sell(self) -> None:
        """Decision(SELL) → ExecutionEngine.submit_order 必须返回 FILLED。"""
        decision = self.signal_engine.evaluate_unified_to_decision(
            price_data={
                "symbol": "AAPL",
                "price": 150.0,
                "change_pct": -0.03,
                "volatility": 0.01,
            },
            decision_engine=self.decision_engine,
        )
        from decimal import Decimal
        result = self.execution_engine.submit_order(decision, Decimal("150.00"), Decimal("100"))
        self.assertIsNotNone(result)
        self.assertEqual(result.status, OrderStatus.FILLED)

    def test_decision_to_execution_hold(self) -> None:
        """Decision(HOLD) → ExecutionEngine.submit_order 必须返回 NO_OP。"""
        decision = self.signal_engine.evaluate_unified_to_decision(
            price_data={
                "symbol": "AAPL",
                "price": 150.0,
                "change_pct": 0.0,
                "volatility": 0.01,
            },
            decision_engine=self.decision_engine,
        )
        from decimal import Decimal
        result = self.execution_engine.submit_order(decision, Decimal("150.00"))
        self.assertIsNotNone(result)
        self.assertEqual(result.status, OrderStatus.NO_OP)

    def test_decision_to_execution_reduce(self) -> None:
        """Decision(REDUCE) → ExecutionEngine.submit_order 必须返回 PARTIAL。"""
        decision = self.signal_engine.evaluate_unified_to_decision(
            price_data={
                "symbol": "AAPL",
                "price": 150.0,
                "change_pct": 0.01,
                "volatility": 0.04,
            },
            decision_engine=self.decision_engine,
        )
        from decimal import Decimal
        result = self.execution_engine.submit_order(decision, Decimal("150.00"), Decimal("100"))
        self.assertIsNotNone(result)
        self.assertEqual(result.status, OrderStatus.PARTIAL)

    def test_full_pipeline_never_returns_none(self) -> None:
        """全链路中任何环节都不应返回 None。"""
        for data in [
            {"symbol": "AAPL", "price": 150.0, "change_pct": 0.03, "volatility": 0.01},
            {"symbol": "AAPL", "price": 150.0, "change_pct": -0.03, "volatility": 0.01},
            {"symbol": "AAPL", "price": 150.0, "change_pct": 0.0, "volatility": 0.01},
            {"symbol": "AAPL", "price": 150.0, "change_pct": 0.01, "volatility": 0.04},
        ]:
            decision = self.signal_engine.evaluate_unified_to_decision(
                price_data=data, decision_engine=self.decision_engine,
            )
            self.assertIsNotNone(decision)
            from decimal import Decimal
            result = self.execution_engine.submit_order(decision, Decimal(str(data["price"])))
            self.assertIsNotNone(result)
            self.assertIsInstance(result.status, OrderStatus)


# ======================================================================
# EventBus Integration
# ======================================================================


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

    def test_generate_signal_publishes_event_via_engine(self) -> None:
        """通过 engine.evaluate_unified 必须发布事件。"""
        engine = SignalEngine()
        received: list[dict] = []
        def listener(data: Any) -> None:
            received.append(data)
        event_bus.subscribe(SIGNAL_GENERATED, listener)
        engine.evaluate_unified({
            "symbol": "AAPL", "price": 150.0,
            "change_pct": 0.03, "volatility": 0.01,
        })
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["signal"]["signal_type"], "BUY")


# ======================================================================
# 安全约束
# ======================================================================


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


# ======================================================================
# Global Singleton
# ======================================================================


class TestGlobalSingleton(unittest.TestCase):
    def test_signal_engine_is_singleton(self) -> None:
        from signal_engine import signal_engine as se1
        from signal_engine import signal_engine as se2
        self.assertIs(se1, se2)


if __name__ == "__main__":
    unittest.main()