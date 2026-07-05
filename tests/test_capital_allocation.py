# -*- coding: utf-8 -*-
"""资金分配测试 — CapitalAllocationEngine 的只读测试。"""

from __future__ import annotations
import sys, unittest, os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.allocation.capital_allocation_engine import CapitalAllocationEngine


class TestCapitalAllocation(unittest.TestCase):
    def setUp(self):
        self.engine = CapitalAllocationEngine(total_capital=100000.0)
        self.sample_portfolio = {
            "strategies": ["momentum_v2", "defensive_v1", "ai_alpha_v3"],
            "weights": {"momentum_v2": 0.4, "defensive_v1": 0.35, "ai_alpha_v3": 0.25},
            "expected_max_drawdown_pct": 8.0,
        }

    def test_empty_no_crash(self):
        """空数据不崩溃"""
        r = self.engine.allocate_capital(None)
        self.assertIn("total_capital", r)
        self.assertIn("cash_reserve", r)
        self.assertEqual(r["cash_reserve"], 100000.0)

    def test_allocation_returns_keys(self):
        """分配结果应包含所需字段"""
        r = self.engine.allocate_capital(self.sample_portfolio)
        self.assertIn("strategy_allocations", r)
        self.assertIn("cash_reserve", r)
        self.assertIn("exposure_pct", r)
        self.assertIn("risk_budget", r)
        self.assertIn("top_strategy_weight", r)
        self.assertIn("portfolio_concentration", r)
        self.assertIn("constraints_satisfied", r)

    def test_allocation_has_strategies(self):
        """分配结果应包含策略"""
        r = self.engine.allocate_capital(self.sample_portfolio)
        self.assertGreater(len(r["strategy_allocations"]), 0)

    def test_exposure_in_range(self):
        """exposure 应在 0~1 之间"""
        r = self.engine.allocate_capital(self.sample_portfolio)
        self.assertGreaterEqual(r["exposure_pct"], 0.0)
        self.assertLessEqual(r["exposure_pct"], 1.0)

    def test_cash_reserve_positive(self):
        """现金储备应 >= 0"""
        r = self.engine.allocate_capital(self.sample_portfolio)
        self.assertGreaterEqual(r["cash_reserve"], 0.0)

    def test_enforce_concentration_single(self):
        """单一策略应被限制在 25%"""
        weights = {"a": 0.5, "b": 0.5}
        self.engine._enforce_concentration(weights)
        for w in weights.values():
            self.assertLessEqual(w, 0.25)

    def test_enforce_concentration_top2(self):
        """前2大合计应 ≤ 45%"""
        weights = {"a": 0.24, "b": 0.24, "c": 0.52}
        self.engine._enforce_concentration(weights)
        sorted_w = sorted(weights.values(), reverse=True)
        self.assertLessEqual(sorted_w[0] + sorted_w[1], 0.45)

    def test_drawdown_protection(self):
        """高回撤应减少exposure"""
        high_dd = dict(self.sample_portfolio)
        high_dd["expected_max_drawdown_pct"] = 16.0
        r = self.engine.allocate_capital(high_dd)
        self.assertGreaterEqual(r["cash_reserve"] / 100000.0, 0.30)

    def test_rebalance_returns_result(self):
        """再平衡应返回结果"""
        r = self.engine.rebalance_portfolio()
        self.assertIn("rebalanced", r)

    def test_file_output(self):
        """应生成 JSON 文件"""
        today = __import__("datetime").date.today().isoformat().replace("-", "")
        report_file = Path(__file__).parent.parent / "reports" / f"capital_allocation_{today}.json"
        if report_file.exists():
            os.unlink(report_file)
        r = self.engine.allocate_capital(self.sample_portfolio)
        self.assertTrue(report_file.exists())

    def test_allocation_constraints_all_pass(self):
        """低收敛权重应通过约束检查"""
        portfolio = {
            "strategies": ["a", "b", "c", "d"],
            "weights": {"a": 0.15, "b": 0.15, "c": 0.15, "d": 0.05},
            "expected_max_drawdown_pct": 5.0,
        }
        r = self.engine.allocate_capital(portfolio)
        self.assertTrue(r["constraints_satisfied"])


if __name__ == "__main__":
    unittest.main()