# -*- coding: utf-8 -*-
"""PortfolioEngine 测试。"""

from __future__ import annotations

import unittest
from decimal import Decimal
from typing import Any

from event_bus import event_bus
from events import PORTFOLIO_UPDATED
from portfolio_engine import (
    PositionInfo,
    AdjustedPosition,
    PortfolioRiskResult,
    PortfolioEngine,
    portfolio_engine,
)


class TestAdjustedPosition(unittest.TestCase):
    def test_to_dict(self) -> None:
        ap = AdjustedPosition(symbol="AAPL", original_size_pct=0.5, adjusted_size_pct=0.4, reduction_pct=0.1)
        d = ap.to_dict()
        self.assertEqual(d["symbol"], "AAPL")
        self.assertEqual(d["original_size_pct"], 0.5)
        self.assertEqual(d["adjusted_size_pct"], 0.4)
        self.assertEqual(d["reduction_pct"], 0.1)


class TestPortfolioRiskResult(unittest.TestCase):
    def test_to_dict(self) -> None:
        pr = PortfolioRiskResult(risk_score=0.3, concentration_score=0.5, single_exposure_max=0.4, top3_exposure=0.7, total_exposure=0.9, regime_multiplier=1.0)
        d = pr.to_dict()
        self.assertEqual(d["risk_score"], 0.3)
        self.assertEqual(d["concentration_score"], 0.5)
        self.assertIn("timestamp", d)


class TestPortfolioEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = PortfolioEngine()
        event_bus.clear_log()

    def test_single_position_within_limit(self) -> None:
        """单一仓位 40% < 50% 上限，不调整。"""
        positions = [PositionInfo("AAPL", 0.4)]
        adjusted, risk = self.engine.calculate(positions, "BULL")
        self.assertAlmostEqual(adjusted[0].adjusted_size_pct, 0.4)

    def test_single_position_exceeds_limit(self) -> None:
        """单一仓位 80% > 50% 上限，调整为 50%。"""
        positions = [PositionInfo("AAPL", 0.8)]
        adjusted, risk = self.engine.calculate(positions, "BULL")
        self.assertAlmostEqual(adjusted[0].adjusted_size_pct, 0.5)

    def test_top3_exceeds_limit(self) -> None:
        """前3大持仓 90% > 70% 上限，按比例压缩。"""
        positions = [
            PositionInfo("A", 0.4),
            PositionInfo("B", 0.3),
            PositionInfo("C", 0.2),
            PositionInfo("D", 0.1),
        ]
        adjusted, risk = self.engine.calculate(positions, "BULL")
        top3_sum = sum(a.adjusted_size_pct for a in adjusted[:3])
        self.assertLessEqual(top3_sum, 0.71)

    def test_bear_regime_multiplier(self) -> None:
        """BEAR regime ×0.5。"""
        positions = [PositionInfo("AAPL", 0.4)]
        adjusted, risk = self.engine.calculate(positions, "BEAR")
        self.assertAlmostEqual(adjusted[0].adjusted_size_pct, 0.20)

    def test_high_risk_regime_multiplier(self) -> None:
        """HIGH_RISK regime ×0.6。"""
        positions = [PositionInfo("AAPL", 0.4)]
        adjusted, risk = self.engine.calculate(positions, "HIGH_RISK")
        self.assertAlmostEqual(adjusted[0].adjusted_size_pct, 0.24)

    def test_choppy_regime_multiplier(self) -> None:
        """CHOPPY regime ×0.7。"""
        positions = [PositionInfo("AAPL", 0.4)]
        adjusted, risk = self.engine.calculate(positions, "CHOPPY")
        self.assertAlmostEqual(adjusted[0].adjusted_size_pct, 0.28)

    def test_bull_regime_multiplier(self) -> None:
        """BULL regime ×1.0。"""
        positions = [PositionInfo("AAPL", 0.4)]
        adjusted, risk = self.engine.calculate(positions, "BULL")
        self.assertAlmostEqual(adjusted[0].adjusted_size_pct, 0.4)

    def test_risk_score_in_bull(self) -> None:
        """BULL 下风险分数应低于 HIGH_RISK。"""
        bull_positions = [PositionInfo("AAPL", 0.3)]
        hr_positions = [PositionInfo("AAPL", 0.3)]
        _, bull_risk = self.engine.calculate(bull_positions, "BULL")
        _, hr_risk = self.engine.calculate(hr_positions, "HIGH_RISK")
        self.assertLess(bull_risk.risk_score, hr_risk.risk_score)

    def test_risk_score_in_high_risk(self) -> None:
        """HIGH_RISK 下风险分数应该较高。"""
        positions = [PositionInfo("AAPL", 0.5)]
        _, risk = self.engine.calculate(positions, "HIGH_RISK")
        self.assertGreater(risk.risk_score, 0.3)

    def test_risk_score_range(self) -> None:
        """风险分数必须在 0~1 范围内。"""
        for regime in ["BULL", "BEAR", "CHOPPY", "HIGH_RISK"]:
            positions = [PositionInfo(f"S{i}", 0.3) for i in range(5)]
            _, risk = self.engine.calculate(positions, regime)
            self.assertGreaterEqual(risk.risk_score, 0.0)
            self.assertLessEqual(risk.risk_score, 1.0)

    def test_empty_positions(self) -> None:
        """空持仓应返回空调整列表。"""
        adjusted, risk = self.engine.calculate([], "BULL")
        self.assertEqual(len(adjusted), 0)

    def test_event_published(self) -> None:
        received: list[dict] = []
        def listener(data: Any) -> None:
            received.append(data)
        event_bus.subscribe(PORTFOLIO_UPDATED, listener)
        positions = [PositionInfo("AAPL", 0.3)]
        self.engine.calculate(positions, "BULL")
        self.assertTrue(len(received) > 0)
        self.assertIn("risk_result", received[0])
        self.assertIn("adjusted_positions", received[0])

    def test_top3_after_cap_adjustment(self) -> None:
        """单票超过 50% 被 cap 后，前3大应按比例压缩。"""
        positions = [
            PositionInfo("A", 0.6),
            PositionInfo("B", 0.3),
            PositionInfo("C", 0.2),
        ]
        adjusted, risk = self.engine.calculate(positions, "BULL")
        # A 从 0.6 cap 到 0.5, B=0.3, C=0.2 → top3=1.0 > 0.7 → 按比例 0.7/1.0=0.7
        self.assertAlmostEqual(adjusted[0].adjusted_size_pct, 0.5 * 0.7)
        self.assertAlmostEqual(adjusted[1].adjusted_size_pct, 0.3 * 0.7)

    def test_reduction_pct(self) -> None:
        """BEAR 下 reduction_pct 应为正值。"""
        positions = [PositionInfo("AAPL", 0.5)]
        adjusted, _ = self.engine.calculate(positions, "BEAR")
        self.assertGreater(adjusted[0].reduction_pct, 0.0)

    def test_no_regime_default(self) -> None:
        """无 regime 时 ×1.0。"""
        positions = [PositionInfo("AAPL", 0.4)]
        adjusted, _ = self.engine.calculate(positions)
        self.assertAlmostEqual(adjusted[0].adjusted_size_pct, 0.4)


class TestGlobalSingleton(unittest.TestCase):
    def test_portfolio_engine_is_singleton(self) -> None:
        pe1 = portfolio_engine
        pe2 = portfolio_engine
        self.assertIs(pe1, pe2)


if __name__ == "__main__":
    unittest.main()