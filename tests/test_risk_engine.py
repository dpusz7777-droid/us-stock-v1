# -*- coding: utf-8 -*-
"""RiskEngine 测试。"""

from __future__ import annotations

import unittest
from decimal import Decimal
from typing import Any

from broker_provider import (
    BrokerAccountSnapshot,
    BrokerPosition,
    BrokerPortfolioSnapshot,
)
from event_bus import event_bus
from events import RISK_EVALUATED
from price_provider_v2 import PriceResultV2, PRICE_STATUS_OK
from risk_engine import RiskEngine, RiskLevel, RiskDecision, risk_engine
from signal_engine import Signal, SignalType


def _make_signal(
    symbol: str = "AAPL",
    signal_type: SignalType = SignalType.BUY,
    strength: int = 80,
    confidence: float = 0.8,
    source: str = "price",
) -> Signal:
    return Signal(
        symbol=symbol,
        signal_type=signal_type,
        strength=strength,
        confidence=confidence,
        reason="test signal",
        source=source,
    )


def _make_broker_snapshot(
    symbols_pcts: list[tuple[str, Decimal]],
    pnls: dict[str, Decimal] | None = None,
) -> BrokerPortfolioSnapshot:
    """Create a snapshot. pct is exact (e.g. 45 means 45% of portfolio).

    To prevent a single position from being 100%, adds a FILLER position
    if only one position is given.
    """
    pnl_by_sym = pnls or {}
    symbols_pcts = list(symbols_pcts)
    if len(symbols_pcts) == 1:
        sym, pct = symbols_pcts[0]
        filler_pct = Decimal("100") - pct
        symbols_pcts.append(("FILLER", filler_pct))

    total_pct = sum(p for _, p in symbols_pcts)
    total_mv = Decimal("10000")
    positions_list: list[BrokerPosition] = []
    for sym, desired_pct in symbols_pcts:
        mv = total_mv * desired_pct / total_pct
        pnl_pct = pnl_by_sym.get(sym)
        pnl_amount = (pnl_pct / Decimal("100") * mv) if pnl_pct is not None else None
        price = mv / Decimal("100")
        positions_list.append(BrokerPosition(
            symbol=sym,
            shares=Decimal("100"),
            avg_cost=Decimal("10"),
            last_price=price,
            market_value=mv,
            unrealized_pnl=pnl_amount,
            unrealized_pnl_pct=pnl_pct,
        ))
    total_pnl = sum((p.unrealized_pnl or Decimal("0")) for p in positions_list)
    account = BrokerAccountSnapshot(
        account_id_masked="test***",
        broker="mock",
        cash=Decimal("1000"),
        buying_power=Decimal("800"),
        unrealized_pnl=total_pnl,
        positions_market_value=total_mv,
    )
    return BrokerPortfolioSnapshot(account=account, positions=positions_list)


class TestRiskLevel(unittest.TestCase):
    def test_risk_level_values(self) -> None:
        self.assertEqual(RiskLevel.LOW.value, "LOW")
        self.assertEqual(RiskLevel.HIGH.value, "HIGH")
        self.assertEqual(RiskLevel.CRITICAL.value, "CRITICAL")
        self.assertEqual(RiskLevel.BLOCKED.value, "BLOCKED")

    def test_risk_level_is_enum(self) -> None:
        from enum import Enum
        self.assertTrue(issubclass(RiskLevel, Enum))


class TestRiskDecision(unittest.TestCase):
    def test_minimal_decision(self) -> None:
        signal = _make_signal()
        d = RiskDecision(symbol="AAPL", original_signal=signal, risk_level=RiskLevel.HIGH)
        self.assertEqual(d.symbol, "AAPL")
        self.assertEqual(d.risk_level, RiskLevel.HIGH)
        self.assertFalse(d.blocked)

    def test_blocked_decision(self) -> None:
        signal = _make_signal()
        d = RiskDecision(symbol="AAPL", original_signal=signal, risk_level=RiskLevel.BLOCKED, blocked=True)
        self.assertTrue(d.blocked)

    def test_to_dict(self) -> None:
        signal = _make_signal()
        d = RiskDecision(symbol="AAPL", original_signal=signal, risk_level=RiskLevel.HIGH, reason="test")
        dc = d.to_dict()
        self.assertEqual(dc["symbol"], "AAPL")
        self.assertEqual(dc["risk_level"], "HIGH")
        self.assertIn("original_signal", dc)

    def test_immutable(self) -> None:
        signal = _make_signal()
        d = RiskDecision(symbol="AAPL", original_signal=signal, risk_level=RiskLevel.LOW)
        with self.assertRaises(AttributeError):
            d.risk_level = RiskLevel.HIGH

    def test_repr(self) -> None:
        signal = _make_signal()
        d = RiskDecision(symbol="AAPL", original_signal=signal, risk_level=RiskLevel.CRITICAL, blocked=True)
        r = repr(d)
        self.assertIn("AAPL", r)
        self.assertIn("CRITICAL", r)
        self.assertIn("blocked=True", r)


class TestPositionExposure(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = RiskEngine()

    def test_21pct_is_high(self) -> None:
        rl, _ = self.engine._check_position_exposure(Decimal("21"))
        self.assertEqual(rl, RiskLevel.HIGH)

    def test_30pct_is_critical(self) -> None:
        rl, _ = self.engine._check_position_exposure(Decimal("30"))
        self.assertEqual(rl, RiskLevel.CRITICAL)

    def test_35pct_is_critical(self) -> None:
        rl, _ = self.engine._check_position_exposure(Decimal("35"))
        self.assertEqual(rl, RiskLevel.CRITICAL)

    def test_40pct_is_blocked(self) -> None:
        rl, _ = self.engine._check_position_exposure(Decimal("40"))
        self.assertEqual(rl, RiskLevel.BLOCKED)

    def test_50pct_is_blocked(self) -> None:
        rl, _ = self.engine._check_position_exposure(Decimal("50"))
        self.assertEqual(rl, RiskLevel.BLOCKED)

    def test_15pct_is_low(self) -> None:
        rl, _ = self.engine._check_position_exposure(Decimal("15"))
        self.assertEqual(rl, RiskLevel.LOW)

    def test_none_is_low(self) -> None:
        rl, _ = self.engine._check_position_exposure(None)
        self.assertEqual(rl, RiskLevel.LOW)


class TestPositionLoss(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = RiskEngine()

    def test_minus_6pct_is_high(self) -> None:
        rl, _ = self.engine._check_position_loss(Decimal("-6"))
        self.assertEqual(rl, RiskLevel.HIGH)

    def test_minus_10pct_is_critical(self) -> None:
        rl, _ = self.engine._check_position_loss(Decimal("-10"))
        self.assertEqual(rl, RiskLevel.CRITICAL)

    def test_minus_12pct_is_critical(self) -> None:
        rl, _ = self.engine._check_position_loss(Decimal("-12"))
        self.assertEqual(rl, RiskLevel.CRITICAL)

    def test_minus_15pct_is_blocked(self) -> None:
        rl, _ = self.engine._check_position_loss(Decimal("-15"))
        self.assertEqual(rl, RiskLevel.BLOCKED)

    def test_minus_20pct_is_blocked(self) -> None:
        rl, _ = self.engine._check_position_loss(Decimal("-20"))
        self.assertEqual(rl, RiskLevel.BLOCKED)

    def test_minus_3pct_is_low(self) -> None:
        rl, _ = self.engine._check_position_loss(Decimal("-3"))
        self.assertEqual(rl, RiskLevel.LOW)

    def test_none_is_low(self) -> None:
        rl, _ = self.engine._check_position_loss(None)
        self.assertEqual(rl, RiskLevel.LOW)

    def test_positive_pnl_is_low(self) -> None:
        rl, _ = self.engine._check_position_loss(Decimal("5"))
        self.assertEqual(rl, RiskLevel.LOW)


class TestSignalConflict(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = RiskEngine()

    def test_buy_high_becomes_hold(self) -> None:
        signal = _make_signal(signal_type=SignalType.BUY)
        adj, reason = self.engine._resolve_signal_conflict(signal, RiskLevel.HIGH)
        self.assertIsNotNone(adj)
        self.assertEqual(adj.signal_type, SignalType.HOLD)
        self.assertGreater(len(reason), 0)

    def test_buy_critical_is_blocked(self) -> None:
        signal = _make_signal(signal_type=SignalType.BUY)
        adj, reason = self.engine._resolve_signal_conflict(signal, RiskLevel.CRITICAL)
        self.assertIn("blocked", reason.lower())

    def test_sell_high_confirmed(self) -> None:
        signal = _make_signal(signal_type=SignalType.SELL)
        adj, reason = self.engine._resolve_signal_conflict(signal, RiskLevel.HIGH)
        self.assertIn("confirmed", reason.lower())

    def test_hold_unchanged(self) -> None:
        signal = _make_signal(signal_type=SignalType.HOLD)
        adj, reason = self.engine._resolve_signal_conflict(signal, RiskLevel.HIGH)
        self.assertIsNone(adj)
        self.assertEqual(reason, "")

    def test_low_risk_no_change(self) -> None:
        signal = _make_signal(signal_type=SignalType.BUY)
        adj, reason = self.engine._resolve_signal_conflict(signal, RiskLevel.LOW)
        self.assertIsNone(adj)
        self.assertEqual(reason, "")


class TestVolatility(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = RiskEngine()

    def test_volatility_9pct_is_high(self) -> None:
        rl, _ = self.engine.check_volatility_with_change(Decimal("9"))
        self.assertEqual(rl, RiskLevel.HIGH)

    def test_volatility_12pct_is_critical(self) -> None:
        rl, _ = self.engine.check_volatility_with_change(Decimal("12"))
        self.assertEqual(rl, RiskLevel.CRITICAL)

    def test_volatility_15pct_is_critical(self) -> None:
        rl, _ = self.engine.check_volatility_with_change(Decimal("15"))
        self.assertEqual(rl, RiskLevel.CRITICAL)

    def test_volatility_5pct_is_low(self) -> None:
        rl, _ = self.engine.check_volatility_with_change(Decimal("5"))
        self.assertEqual(rl, RiskLevel.LOW)

    def test_negative_volatility_treated_as_abs(self) -> None:
        rl1, _ = self.engine.check_volatility_with_change(Decimal("9"))
        rl2, _ = self.engine.check_volatility_with_change(Decimal("-9"))
        self.assertEqual(rl1, rl2)

    def test_none_price_is_low(self) -> None:
        pr = PriceResultV2(symbol="AAPL", price=None, status=PRICE_STATUS_OK)
        rl, _ = self.engine._check_volatility(pr)
        self.assertEqual(rl, RiskLevel.LOW)


class TestFullEvaluate(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = RiskEngine()
        event_bus.clear_log()

    def test_buy_blocked_by_40pct_position(self) -> None:
        signals = [_make_signal("SOFI", SignalType.BUY, strength=85)]
        snap = _make_broker_snapshot([("SOFI", Decimal("45"))])  # 45% + 55% filler
        decisions = self.engine.evaluate(signals, snap)
        self.assertEqual(len(decisions), 1)
        d = decisions[0]
        self.assertEqual(d.risk_level, RiskLevel.BLOCKED)
        self.assertTrue(d.blocked)

    def test_buy_high_risk_downgraded_to_hold(self) -> None:
        signals = [_make_signal("SOFI", SignalType.BUY, strength=80)]
        snap = _make_broker_snapshot([("SOFI", Decimal("25"))])  # 25% + 75% filler
        decisions = self.engine.evaluate(signals, snap)
        self.assertEqual(len(decisions), 1)
        d = decisions[0]
        self.assertEqual(d.risk_level, RiskLevel.HIGH)
        self.assertIsNotNone(d.adjusted_signal)
        self.assertEqual(d.adjusted_signal.signal_type, SignalType.HOLD)

    def test_loss_blocked_sell_recommended(self) -> None:
        signals = [_make_signal("SOFI", SignalType.HOLD, strength=30)]
        snap = _make_broker_snapshot(
            [("SOFI", Decimal("10"))],  # 10% + 90% filler
            pnls={"SOFI": Decimal("-16")},
        )
        decisions = self.engine.evaluate(signals, snap)
        d = decisions[0]
        self.assertEqual(d.risk_level, RiskLevel.BLOCKED)

    def test_circuit_breaker_with_3_critical(self) -> None:
        """3 CRITICAL assets → global RISK_OFF, all BUY→HOLD."""
        signals = [
            _make_signal("A", SignalType.BUY, 80),
            _make_signal("B", SignalType.BUY, 80),
            _make_signal("C", SignalType.BUY, 80),
        ]
        snap = _make_broker_snapshot([
            ("A", Decimal("35")),
            ("B", Decimal("35")),
            ("C", Decimal("30")),
        ])
        decisions = self.engine.evaluate(signals, snap)
        for d in decisions:
            self.assertTrue(d.blocked, f"{d.symbol} should be blocked by circuit breaker")
            if d.original_signal.signal_type == SignalType.BUY:
                self.assertIsNotNone(d.adjusted_signal)
                if d.adjusted_signal:
                    self.assertEqual(d.adjusted_signal.signal_type, SignalType.HOLD)

    def test_circuit_breaker_with_1_blocked_suppresses_buys(self) -> None:
        """1 BLOCKED position → all other BUY signals suppressed."""
        signals = [
            _make_signal("A", SignalType.BUY, 80),
            _make_signal("B", SignalType.BUY, 80),
        ]
        snap = _make_broker_snapshot(
            [("A", Decimal("10")), ("B", Decimal("10"))],
            pnls={"A": Decimal("-16")},
        )
        decisions = self.engine.evaluate(signals, snap)
        a_dec = [d for d in decisions if d.symbol == "A"]
        b_dec = [d for d in decisions if d.symbol == "B"]
        if a_dec:
            self.assertTrue(a_dec[0].blocked)
        if b_dec:
            self.assertTrue(b_dec[0].blocked)

    def test_healthy_portfolio_no_risk(self) -> None:
        signals = [_make_signal("AAPL", SignalType.BUY, 60)]
        snap = _make_broker_snapshot([("AAPL", Decimal("10"))])  # 10% < 20%
        decisions = self.engine.evaluate(signals, snap)
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].risk_level, RiskLevel.LOW)

    def test_empty_signals(self) -> None:
        decisions = self.engine.evaluate([])
        self.assertEqual(decisions, [])

    def test_sell_preserved_on_high_risk(self) -> None:
        signals = [_make_signal("SOFI", SignalType.SELL, 85)]
        snap = _make_broker_snapshot([("SOFI", Decimal("35"))])  # 35% CRITICAL
        decisions = self.engine.evaluate(signals, snap)
        d = decisions[0]
        self.assertEqual(d.risk_level, RiskLevel.CRITICAL)
        self.assertIsNone(d.adjusted_signal)

    def test_merge_risk_levels(self) -> None:
        merged = RiskEngine._merge_risk_levels([RiskLevel.LOW, RiskLevel.HIGH, RiskLevel.LOW])
        self.assertEqual(merged, RiskLevel.HIGH)

    def test_merge_risk_blocked_wins(self) -> None:
        merged = RiskEngine._merge_risk_levels([RiskLevel.HIGH, RiskLevel.BLOCKED, RiskLevel.LOW])
        self.assertEqual(merged, RiskLevel.BLOCKED)


class TestEventBusIntegration(unittest.TestCase):
    def setUp(self) -> None:
        event_bus.clear()
        event_bus.clear_log()
        self.engine = RiskEngine()

    def test_risk_evaluated_event_published(self) -> None:
        received: list[dict] = []
        def listener(data: Any) -> None:
            received.append(data)
        event_bus.subscribe(RISK_EVALUATED, listener)
        signals = [_make_signal("AAPL", SignalType.BUY)]
        snap = _make_broker_snapshot([("AAPL", Decimal("10"))])
        self.engine.evaluate(signals, snap)
        self.assertTrue(len(received) > 0)
        self.assertIn("risk_decisions", received[0])
        self.assertIn("blocked_signals_count", received[0])
        self.assertIn("critical_count", received[0])


class TestFrequencySuppression(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = RiskEngine()

    def test_consecutive_buys_penalized(self) -> None:
        for _ in range(4):
            self.engine._update_signal_history([_make_signal("AAPL", SignalType.BUY)])
        penalty, reason = self.engine._check_signal_frequency("AAPL", SignalType.BUY)
        self.assertGreater(penalty, 0)
        self.assertIn("consecutive", reason.lower())

    def test_frequent_switch_penalized(self) -> None:
        for _ in range(3):
            self.engine._update_signal_history([_make_signal("AAPL", SignalType.BUY)])
        penalty, reason = self.engine._check_signal_frequency("AAPL", SignalType.SELL)
        self.assertGreater(penalty, 0)
        self.assertIn("switch", reason.lower())

    def test_first_signal_no_penalty(self) -> None:
        penalty, reason = self.engine._check_signal_frequency("NEW", SignalType.BUY)
        self.assertEqual(penalty, 0.0)
        self.assertEqual(reason, "")

    def test_clear_history(self) -> None:
        self.engine._update_signal_history([_make_signal("AAPL", SignalType.BUY)])
        self.engine.clear_signal_history("AAPL")
        penalty, reason = self.engine._check_signal_frequency("AAPL", SignalType.BUY)
        self.assertEqual(penalty, 0.0)

    def test_clear_all_history(self) -> None:
        self.engine._update_signal_history([_make_signal("A", SignalType.BUY)])
        self.engine._update_signal_history([_make_signal("B", SignalType.BUY)])
        self.engine.clear_signal_history()
        self.assertEqual(self.engine._signal_history, {})


class TestRiskDecisionSummary(unittest.TestCase):
    def test_empty_summary(self) -> None:
        summary = RiskEngine.risk_decision_summary([])
        self.assertEqual(summary["total_signals"], 0)

    def test_summary_counts(self) -> None:
        decisions = [
            RiskDecision(symbol="A", original_signal=_make_signal("A"), risk_level=RiskLevel.HIGH),
            RiskDecision(symbol="B", original_signal=_make_signal("B"), risk_level=RiskLevel.CRITICAL),
            RiskDecision(symbol="C", original_signal=_make_signal("C"), risk_level=RiskLevel.BLOCKED, blocked=True),
        ]
        summary = RiskEngine.risk_decision_summary(decisions)
        self.assertEqual(summary["total_signals"], 3)
        self.assertEqual(summary["high"], 1)
        self.assertEqual(summary["critical"], 1)
        self.assertEqual(summary["blocked"], 1)


class TestNoNetworkOrPortfolioModification(unittest.TestCase):
    def test_no_network_imports(self) -> None:
        with open("risk_engine.py", "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        import_lines = [l.strip() for l in lines if l.strip().startswith("import ") or l.strip().startswith("from ")]
        import_text = "\n".join(import_lines).lower()
        for lib in ["socket", "http", "requests", "yfinance"]:
            with self.subTest(lib=lib):
                self.assertNotIn(lib, import_text)

    def test_no_trade_methods(self) -> None:
        for name in dir(RiskEngine):
            lower = name.lower()
            if "order" in lower or "trade" in lower or "place" in lower:
                self.fail(f"RiskEngine has forbidden method: {name}")

    def test_no_file_write(self) -> None:
        with open("risk_engine.py", "r", encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn(".write(", source)
        self.assertNotIn('open(', source)


class TestGlobalSingleton(unittest.TestCase):
    def test_risk_engine_is_singleton(self) -> None:
        from risk_engine import risk_engine as re1
        from risk_engine import risk_engine as re2
        self.assertIs(re1, re2)


if __name__ == "__main__":
    unittest.main()