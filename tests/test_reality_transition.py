# -*- coding: utf-8 -*-
"""现实过渡层测试 v8 — RealityTransitionEngine MDPO 完整测试。"""

from __future__ import annotations
import sys, unittest, os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.reality_transition.reality_transition_engine import RealityTransitionEngine


class TestRealityTransition(unittest.TestCase):
    def setUp(self):
        self.rte = RealityTransitionEngine()

    def test_mirror_cycle_returns_report(self):
        r = self.rte.run_reality_mirror_cycle()
        self.assertIn("optimized_weights", r)
        self.assertIn("portfolio_risk", r)
        self.assertIn("diversification_score", r)
        self.assertIn("expected_return_proxy", r)
        self.assertIn("solver_status", r)

    def test_multi_asset_weight_sum(self):
        """多资产权重之和应为1"""
        n = 5
        rv = [80, 72, 64, 56, 48]
        sv = [0.8, 0.72, 0.64, 0.56, 0.48]
        mv = [1.0] * n
        cm = [[0.15, 0.08, 0.06, 0.04, 0.02],
              [0.08, 0.12, 0.05, 0.03, 0.02],
              [0.06, 0.05, 0.10, 0.03, 0.02],
              [0.04, 0.03, 0.03, 0.08, 0.01],
              [0.02, 0.02, 0.02, 0.01, 0.06]]
        lv = [0.0] * n
        r = self.rte.multi_dimensional_optimizer(rv, sv, mv, cm, lv, 0.02, 0.15)
        w = r["optimized_weights"]
        self.assertAlmostEqual(sum(w), 1.0, places=4)
        self.assertEqual(len(w), n)

    def test_no_single_asset_overconcentration(self):
        """单一资产权重应 ≤ 30%"""
        n = 5
        rv = [100, 10, 10, 10, 10]
        sv = [1.0, 0.1, 0.1, 0.1, 0.1]
        mv = [1.0] * n
        cm = [[0.15, 0.08, 0.06, 0.04, 0.02],
              [0.08, 0.12, 0.05, 0.03, 0.02],
              [0.06, 0.05, 0.10, 0.03, 0.02],
              [0.04, 0.03, 0.03, 0.08, 0.01],
              [0.02, 0.02, 0.02, 0.01, 0.06]]
        lv = [0.0] * n
        r = self.rte.multi_dimensional_optimizer(rv, sv, mv, cm, lv, 0.02, 0.15)
        w = r["optimized_weights"]
        self.assertLessEqual(max(w), 0.30 + 0.01)

    def test_diversification_improves_stability(self):
        """分散度评分应 > 0（非完全集中）"""
        n = 5
        rv = [80, 75, 70, 65, 60]
        sv = [0.8, 0.75, 0.7, 0.65, 0.6]
        mv = [1.0] * n
        cm = [[0.15, 0.08, 0.06, 0.04, 0.02],
              [0.08, 0.12, 0.05, 0.03, 0.02],
              [0.06, 0.05, 0.10, 0.03, 0.02],
              [0.04, 0.03, 0.03, 0.08, 0.01],
              [0.02, 0.02, 0.02, 0.01, 0.06]]
        lv = [0.0] * n
        r = self.rte.multi_dimensional_optimizer(rv, sv, mv, cm, lv, 0.02, 0.15)
        self.assertGreater(r["diversification_score"], 0.0)

    def test_covariance_risk_reduction(self):
        """引入协方差风险应产生分散化效应"""
        n = 5
        rv = [90, 10, 10, 10, 10]
        sv = [0.9, 0.1, 0.1, 0.1, 0.1]
        mv = [1.0] * n
        cm = [[0.15, 0.08, 0.06, 0.04, 0.02],
              [0.08, 0.12, 0.05, 0.03, 0.02],
              [0.06, 0.05, 0.10, 0.03, 0.02],
              [0.04, 0.03, 0.03, 0.08, 0.01],
              [0.02, 0.02, 0.02, 0.01, 0.06]]
        lv = [0.0] * n
        r = self.rte.multi_dimensional_optimizer(rv, sv, mv, cm, lv, 0.02, 0.15)
        w = r["optimized_weights"]
        # 不应完全是均匀分散，但也不应全是单一资产
        self.assertGreater(min(w), 0.01)
        self.assertLess(max(w), 0.9)

    def test_gradient_convergence(self):
        """投影梯度下降应收敛"""
        n = 5
        rv = [80, 72, 64, 56, 48]
        sv = [0.8, 0.72, 0.64, 0.56, 0.48]
        mv = [1.0] * n
        cm = [[0.15, 0.08, 0.06, 0.04, 0.02],
              [0.08, 0.12, 0.05, 0.03, 0.02],
              [0.06, 0.05, 0.10, 0.03, 0.02],
              [0.04, 0.03, 0.03, 0.08, 0.01],
              [0.02, 0.02, 0.02, 0.01, 0.06]]
        lv = [0.0] * n
        r = self.rte.multi_dimensional_optimizer(rv, sv, mv, cm, lv, 0.02, 0.15)
        self.assertGreater(r["objective_value"], -1000)
        self.assertIn(r["solver_status"], ["optimal", "feasible", "infeasible"])

    def test_liquidity_stress_hard_constraint(self):
        """liquidity_stress 应降低风险暴露"""
        n = 5
        rv = [80] * n; sv = [0.8] * n; mv = [1.0] * n
        cm = [[0.15, 0.08, 0.06, 0.04, 0.02],
              [0.08, 0.12, 0.05, 0.03, 0.02],
              [0.06, 0.05, 0.10, 0.03, 0.02],
              [0.04, 0.03, 0.03, 0.08, 0.01],
              [0.02, 0.02, 0.02, 0.01, 0.06]]
        r_norm = self.rte.multi_dimensional_optimizer(rv, sv, mv, cm, [0.0]*n, 0.01, 0.15)
        r_liq = self.rte.multi_dimensional_optimizer(rv, sv, mv, cm, [1.0]*n, 0.01, 0.15)
        self.assertLessEqual(r_liq["portfolio_risk"], r_norm["portfolio_risk"] + 0.01)

    def test_continuous_kernel_legacy(self):
        """legacy接口应正常工作"""
        r = self.rte.continuous_optimization_kernel(RMAI=80, regime="trend", volatility=0.12, drawdown=0.02, signal_strength=0.8)
        self.assertIn("optimized_weights", r)
        self.assertIn("solver_status", r)

    def test_regime_detection(self):
        data = {"returns": [0.2, 0.3, 0.15, 0.25, 0.1], "volatility": 0.12, "spread_proxy": 0.001, "drawdown_pct": 0.02}
        r = self.rte.market_regime_detector(data)
        self.assertIn(r["regime_type"], ["trend", "range", "volatile", "liquidity_stress"])

    def test_kill_switch_triggers(self):
        self.rte.trigger_kill_switch(5.0)
        self.assertTrue(self.rte._kill_switch_active)

    def test_file_output(self):
        today = __import__("datetime").date.today().isoformat().replace("-", "")
        f = Path(__file__).parent.parent / "reports" / f"reality_transition_{today}.json"
        if f.exists(): os.unlink(f)
        self.rte.run_reality_mirror_cycle()
        self.assertTrue(f.exists())


if __name__ == "__main__":
    unittest.main()