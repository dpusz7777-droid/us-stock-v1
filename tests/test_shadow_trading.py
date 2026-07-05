# -*- coding: utf-8 -*-
"""影子交易测试 — ShadowTradingEngine 的只读测试。"""

from __future__ import annotations
import sys, unittest, os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.shadow.shadow_trading_engine import ShadowTradingEngine


class TestShadowTrading(unittest.TestCase):
    def setUp(self):
        self.shadow = ShadowTradingEngine()

    def test_run_shadow_cycle_returns_report(self):
        """运行shadow cycle返回报告"""
        r = self.shadow.run_shadow_cycle()
        self.assertIn("paper_return", r)
        self.assertIn("shadow_return", r)
        self.assertIn("consistency_score", r)

    def test_drift_detection(self):
        """漂移检测应返回字段"""
        d = self.shadow.drift_detection_engine()
        self.assertIn("drift_detected", d)
        self.assertIn("reasons", d)

    def test_consistency_score_in_range(self):
        """一致性评分0~100"""
        s = self.shadow.real_market_consistency_score()
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_shadow_vs_paper_returns_dict(self):
        """对比返回字典"""
        self.shadow.run_shadow_cycle()
        c = self.shadow.shadow_vs_paper_comparison()
        self.assertIn("execution_gap", c)
        self.assertIn("risk_alignment", c)

    def test_log_not_empty(self):
        """日志非空"""
        self.shadow.run_shadow_cycle()
        self.assertGreater(len(self.shadow._cycle_log), 0)

    def test_file_output(self):
        """生成JSON"""
        today = __import__("datetime").date.today().isoformat().replace("-", "")
        f = Path(__file__).parent.parent / "reports" / f"shadow_trading_{today}.json"
        if f.exists(): os.unlink(f)
        self.shadow.run_shadow_cycle()
        self.assertTrue(f.exists())

    def test_shadow_execution_pipeline(self):
        """shadow execution pipeline返回结构"""
        s = {"symbol": "NVDA", "signal": "BUY", "confidence": 0.85}
        r = self.shadow.shadow_execution_pipeline(s)
        self.assertIn("shadow_execution_price", r)
        self.assertIn("fill_rate", r)

    def test_empty_no_crash(self):
        """空数据不崩溃"""
        r = self.shadow.run_shadow_cycle({})
        self.assertIn("paper_return", r)


if __name__ == "__main__":
    unittest.main()