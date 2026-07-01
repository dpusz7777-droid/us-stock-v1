# -*- coding: utf-8 -*-
"""CapitalGuard 测试。"""

from __future__ import annotations

import unittest
from typing import Any

from event_bus import event_bus
from events import CAPITAL_MODE_UPDATED
from capital_guard import CapitalGuard, CapitalMode, CapitalGuardSnapshot, capital_guard


class TestCapitalMode(unittest.TestCase):
    def test_mode_values(self) -> None:
        self.assertEqual(CapitalMode.NORMAL.value, "NORMAL")
        self.assertEqual(CapitalMode.CAUTION.value, "CAUTION")
        self.assertEqual(CapitalMode.DEFENSIVE.value, "DEFENSIVE")
        self.assertEqual(CapitalMode.LOCKDOWN.value, "LOCKDOWN")


class TestCapitalGuardSnapshot(unittest.TestCase):
    def test_to_dict(self) -> None:
        snap = CapitalGuardSnapshot(capital_mode=CapitalMode.DEFENSIVE, drawdown_pct=12.0, consecutive_losses=5, position_multiplier=0.5)
        d = snap.to_dict()
        self.assertEqual(d["capital_mode"], "DEFENSIVE")
        self.assertEqual(d["drawdown_pct"], 12.0)
        self.assertEqual(d["position_multiplier"], 0.5)

    def test_repr(self) -> None:
        snap = CapitalGuardSnapshot(capital_mode=CapitalMode.CAUTION, drawdown_pct=7.0, consecutive_losses=3, position_multiplier=0.8)
        r = repr(snap)
        self.assertIn("CAUTION", r)
        self.assertIn("7.0", r)


class TestCapitalGuard(unittest.TestCase):
    def setUp(self) -> None:
        self.guard = CapitalGuard()
        event_bus.clear_log()

    def test_normal_dd(self) -> None:
        snap = self.guard.evaluate(drawdown_pct=2.0)
        self.assertEqual(snap.capital_mode, CapitalMode.NORMAL)
        self.assertAlmostEqual(snap.position_multiplier, 1.0)

    def test_caution_dd(self) -> None:
        snap = self.guard.evaluate(drawdown_pct=7.0)
        self.assertEqual(snap.capital_mode, CapitalMode.CAUTION)
        self.assertAlmostEqual(snap.position_multiplier, 0.8)

    def test_defensive_dd(self) -> None:
        snap = self.guard.evaluate(drawdown_pct=12.0)
        self.assertEqual(snap.capital_mode, CapitalMode.DEFENSIVE)
        self.assertAlmostEqual(snap.position_multiplier, 0.5)

    def test_lockdown_dd(self) -> None:
        snap = self.guard.evaluate(drawdown_pct=18.0)
        self.assertEqual(snap.capital_mode, CapitalMode.LOCKDOWN)
        self.assertAlmostEqual(snap.position_multiplier, 0.0)

    def test_caution_by_losses(self) -> None:
        snap = self.guard.evaluate(drawdown_pct=1.0, consecutive_losses=3)
        self.assertEqual(snap.capital_mode, CapitalMode.CAUTION)

    def test_defensive_by_losses(self) -> None:
        snap = self.guard.evaluate(drawdown_pct=1.0, consecutive_losses=5)
        self.assertEqual(snap.capital_mode, CapitalMode.DEFENSIVE)

    def test_lockdown_by_losses(self) -> None:
        snap = self.guard.evaluate(drawdown_pct=1.0, consecutive_losses=7)
        self.assertEqual(snap.capital_mode, CapitalMode.LOCKDOWN)

    def test_losses_stricter_than_dd(self) -> None:
        """6 days losses > 3 day CAUTION threshold, so DEFENSIVE."""
        snap = self.guard.evaluate(drawdown_pct=1.0, consecutive_losses=6)
        self.assertEqual(snap.capital_mode, CapitalMode.DEFENSIVE)

    def test_dd_stricter_than_losses(self) -> None:
        """12% dd > 10% DEFENSIVE threshold, so DEFENSIVE."""
        snap = self.guard.evaluate(drawdown_pct=12.0, consecutive_losses=1)
        self.assertEqual(snap.capital_mode, CapitalMode.DEFENSIVE)

    def test_equity_curve_calculates_dd(self) -> None:
        """peak=105, cur=75 → dd=28.6% >15% → LOCKDOWN."""
        equity = [100.0, 105.0, 95.0, 85.0, 75.0]
        snap = self.guard.evaluate(equity_curve=equity)
        self.assertEqual(snap.capital_mode, CapitalMode.LOCKDOWN)
        self.assertGreater(snap.drawdown_pct, 15.0)

    def test_equity_curve_counts_losses(self) -> None:
        equity = [100.0, 99.0, 98.0, 97.0, 96.0]
        snap = self.guard.evaluate(equity_curve=equity)
        self.assertGreaterEqual(snap.consecutive_losses, 4)

    def test_rising_equity_normal(self) -> None:
        equity = [100.0, 101.0, 102.0, 103.0, 104.0]
        snap = self.guard.evaluate(equity_curve=equity)
        self.assertEqual(snap.capital_mode, CapitalMode.NORMAL)

    def test_empty_equity_default(self) -> None:
        snap = self.guard.evaluate(equity_curve=[])
        self.assertEqual(snap.capital_mode, CapitalMode.NORMAL)

    def test_event_published(self) -> None:
        received: list[dict] = []
        def listener(data: Any) -> None:
            received.append(data)
        event_bus.subscribe(CAPITAL_MODE_UPDATED, listener)
        self.guard.evaluate(drawdown_pct=5.0)
        self.assertTrue(len(received) > 0)
        self.assertIn("capital_snapshot", received[0])


class TestGlobalSingleton(unittest.TestCase):
    def test_capital_guard_is_singleton(self) -> None:
        cg1 = capital_guard
        cg2 = capital_guard
        self.assertIs(cg1, cg2)


if __name__ == "__main__":
    unittest.main()