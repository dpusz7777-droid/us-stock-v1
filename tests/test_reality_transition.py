# -*- coding: utf-8 -*-
"""现实过渡层测试 — RealityTransitionEngine 的只读测试。"""

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
        """镜像循环返回报告"""
        r = self.rte.run_reality_mirror_cycle()
        self.assertIn("rmai_score", r)
        self.assertIn("capital_readiness", r)
        self.assertIn("breakdown_detected", r)

    def test_rmai_in_range(self):
        """RMAI在0~100"""
        rmai = self.rte.compute_reality_alignment_index(2.0, 1.8, 2.5)
        self.assertGreaterEqual(rmai["score"], 0)
        self.assertLessEqual(rmai["score"], 100)

    def test_breakdown_detected_on_large_deviation(self):
        """大偏差应触发崩溃检测"""
        b = self.rte.detect_reality_breakdown(2.0, -3.0, 4.0)
        self.assertTrue(b["breakdown_detected"])

    def test_high_rmai_go_readiness(self):
        """高RMAI应返回GO状态"""
        rmai = {"score": 85}
        breakdown = {"breakdown_detected": False}
        r = self.rte.capital_deployment_readiness_engine(rmai, breakdown)
        self.assertEqual(r["status"], "GO")

    def test_low_rmai_no_go(self):
        """低RMAI应返回NO_GO"""
        rmai = {"score": 40}
        breakdown = {"breakdown_detected": True}
        r = self.rte.capital_deployment_readiness_engine(rmai, breakdown)
        self.assertEqual(r["status"], "NO_GO")

    def test_micro_live_simulation(self):
        """微实盘模拟返回结构"""
        s = self.rte.micro_live_simulation_mode(2.0)
        self.assertIn("virtual_capital", s)
        self.assertIn("execution_stable", s)

    def test_mirror_cycle_all_fields(self):
        """镜像周期包含所有字段"""
        r = self.rte.run_reality_mirror_cycle({"live_return": 2.0}, {"shadow_return": 1.8}, {"paper_return": 2.5})
        for key in ("shadow_vs_live_correlation", "paper_vs_live_correlation", "divergence_matrix", "micro_live_simulation_result"):
            self.assertIn(key, r)

    def test_file_output(self):
        """应生成JSON"""
        today = __import__("datetime").date.today().isoformat().replace("-", "")
        f = Path(__file__).parent.parent / "reports" / f"reality_transition_{today}.json"
        if f.exists(): os.unlink(f)
        self.rte.run_reality_mirror_cycle()
        self.assertTrue(f.exists())


if __name__ == "__main__":
    unittest.main()