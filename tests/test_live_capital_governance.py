# -*- coding: utf-8 -*-
"""实盘资金治理层测试 — LiveCapitalGovernanceEngine 的只读测试。"""

from __future__ import annotations
import sys, unittest, os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.capital.live_capital_governance_engine import LiveCapitalGovernanceEngine


class TestLiveCapitalGovernance(unittest.TestCase):
    def setUp(self):
        self.engine = LiveCapitalGovernanceEngine(total_capital=100000.0)
        self.good_metrics = {
            "governance": {"grade_distribution": {"A": 2, "B": 1, "C": 0, "D": 0}, "total_strategies": 3},
            "robustness": {"stability_score": 85},
            "walkforward": {"consistency_score": 80},
            "execution": {"execution_gap": -1.5},
            "risk_status": {"risk_level": "LOW"},
        }

    def test_empty_no_crash(self):
        """空指标不崩溃"""
        r = self.engine.evaluate_live_readiness(None)
        self.assertIn("status", r)
        self.assertIn("readiness_score", r)

    def test_good_metrics_returns_go(self):
        """良好指标应返回 GO"""
        r = self.engine.evaluate_live_readiness(self.good_metrics)
        self.assertEqual(r["status"], "GO")
        self.assertGreaterEqual(r["readiness_score"], 70)

    def test_poor_metrics_returns_no_go(self):
        """差指标应返回 NO_GO"""
        poor = {
            "governance": {"grade_distribution": {"A": 0, "B": 1, "C": 2}, "total_strategies": 3},
            "robustness": {"stability_score": 40},
            "walkforward": {"consistency_score": 30},
            "execution": {"execution_gap": -5.0},
            "risk_status": {"risk_level": "HIGH"},
        }
        r = self.engine.evaluate_live_readiness(poor)
        self.assertEqual(r["status"], "NO_GO")
        self.assertGreater(len(r["blocking_reasons"]), 0)

    def test_initial_phase_1(self):
        """初始阶段应为 Phase 1"""
        self.assertEqual(self.engine.phase, 1)

    def test_release_controller_upgrades_to_phase_2(self):
        """连续7天正收益应升级到 Phase 2"""
        for _ in range(7):
            self.engine.capital_release_controller(daily_pnl=1.0)
        self.assertEqual(self.engine.phase, 2)

    def test_circuit_breaker_freeze(self):
        """单日亏损 > 4% 应冻结"""
        r = self.engine.circuit_breaker_system(daily_pnl=-5.0)
        self.assertTrue(r["circuit_breaker_active"])
        self.assertTrue(r["freeze_status"])

    def test_circuit_breaker_consecutive_losses(self):
        """连续3天亏损应触发"""
        self.engine.circuit_breaker_system(daily_pnl=-1.0)
        self.engine.circuit_breaker_system(daily_pnl=-2.0)
        r = self.engine.circuit_breaker_system(daily_pnl=-1.0)
        self.assertTrue(r["circuit_breaker_active"])

    def test_circuit_breaker_drawdown_downgrade(self):
        """回撤 > 8% 应降级至 Phase 1"""
        self.engine.phase = 3
        for _ in range(10):
            self.engine.circuit_breaker_system(daily_pnl=-1.0)
        self.assertEqual(self.engine.phase, 1)

    def test_risk_capital_positive(self):
        """风险资金应 >= 0"""
        r = self.engine.evaluate_live_readiness(self.good_metrics)
        self.assertGreaterEqual(r["risk_capital"], 0)

    def test_file_output(self):
        """应生成 JSON 文件"""
        today = __import__("datetime").date.today().isoformat().replace("-", "")
        report_file = Path(__file__).parent.parent / "reports" / f"live_capital_governance_{today}.json"
        if report_file.exists():
            os.unlink(report_file)
        r = self.engine.evaluate_live_readiness(self.good_metrics)
        self.assertTrue(report_file.exists())


if __name__ == "__main__":
    unittest.main()