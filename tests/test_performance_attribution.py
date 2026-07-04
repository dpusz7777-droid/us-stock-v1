# -*- coding: utf-8 -*-
"""绩效归因测试 — run_performance_attribution 的只读测试。"""

from __future__ import annotations
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.engine.performance_attribution import run_performance_attribution


class TestPerformanceAttribution(unittest.TestCase):
    def setUp(self):
        self.sample_decisions = [
            {"symbol": "AAPL", "action": "BUY", "strategy_type": "momentum", "market_regime": "bull", "source": "v37", "pnl": 5.0},
            {"symbol": "AAPL", "action": "SELL", "strategy_type": "defensive", "market_regime": "bull", "source": "v39", "pnl": 3.0},
            {"symbol": "MSFT", "action": "BUY", "strategy_type": "momentum", "market_regime": "bear", "source": "v37", "pnl": -2.0},
            {"symbol": "GOOG", "action": "HOLD", "strategy_type": "unknown", "market_regime": "sideways", "source": "system", "pnl": 0.0},
        ]

    def test_empty_no_crash(self):
        """空数据不崩溃"""
        r = run_performance_attribution(None, None)
        self.assertIn("strategy_attribution", r)
        self.assertIn("regime_attribution", r)
        self.assertIn("action_attribution", r)
        self.assertIn("source_attribution", r)

    def test_empty_list_no_crash(self):
        """空列表不崩溃"""
        r = run_performance_attribution([], {})
        self.assertEqual(r["overall_system_score"], 0.0)

    def test_strategy_attribution_has_keys(self):
        """strategy_attribution 应包含策略"""
        r = run_performance_attribution(self.sample_decisions, None)
        sa = r["strategy_attribution"]
        self.assertIn("momentum", sa)
        self.assertIn("defensive", sa)
        for st, data in sa.items():
            self.assertIn("total_return", data)
            self.assertIn("win_rate", data)
            self.assertIn("trade_count", data)

    def test_regime_attribution_has_keys(self):
        """regime_attribution 应包含市场状态"""
        r = run_performance_attribution(self.sample_decisions, None)
        ra = r["regime_attribution"]
        self.assertIn("bull", ra)
        self.assertIn("bear", ra)
        for rg, data in ra.items():
            self.assertIn("return", data)
            self.assertIn("accuracy", data)
            self.assertIn("trade_count", data)

    def test_action_attribution_has_keys(self):
        """action_attribution 应包含 BUY/SELL"""
        r = run_performance_attribution(self.sample_decisions, None)
        aa = r["action_attribution"]
        self.assertIn("BUY", aa)
        self.assertIn("SELL", aa)
        for a, data in aa.items():
            self.assertIn("accuracy", data)
            self.assertIn("avg_return", data)

    def test_source_attribution_has_keys(self):
        """source_attribution 应包含来源"""
        r = run_performance_attribution(self.sample_decisions, None)
        sa = r["source_attribution"]
        self.assertIn("v37", sa)
        self.assertIn("v39", sa)
        for s, data in sa.items():
            self.assertIn("quality_score", data)
            self.assertIn("trade_count", data)

    def test_best_worst_strategy(self):
        """best/worst strategy 应正确输出"""
        r = run_performance_attribution(self.sample_decisions, None)
        self.assertIn(r["best_strategy"], ["momentum", "defensive", "unknown"])
        self.assertIn(r["worst_strategy"], ["momentum", "defensive", "unknown"])

    def test_best_regime(self):
        """best_regime 应正确输出"""
        r = run_performance_attribution(self.sample_decisions, None)
        self.assertIn(r["best_regime"], ["bull", "bear", "unknown"])

    def test_overall_score_in_range(self):
        """overall_system_score 应在 0~1 之间"""
        r = run_performance_attribution(self.sample_decisions, None)
        self.assertGreaterEqual(r["overall_system_score"], 0.0)
        self.assertLessEqual(r["overall_system_score"], 1.0)


if __name__ == "__main__":
    unittest.main()