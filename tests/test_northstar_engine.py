# -*- coding: utf-8 -*-
"""北极星主运行引擎测试 — NorthstarEngine 的只读测试。"""

from __future__ import annotations
import sys, unittest, os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.engine.northstar_engine import NorthstarEngine


class TestNorthstarEngine(unittest.TestCase):
    def setUp(self):
        self.engine = NorthstarEngine(total_capital=100000.0)

    def test_run_daily_cycle_returns_report(self):
        """运行每日循环应返回报告"""
        r = self.engine.run_daily_cycle()
        self.assertIn("date", r)
        self.assertIn("market_summary", r)
        self.assertIn("signals", r)
        self.assertIn("system_decision", r)

    def test_system_decision_has_action(self):
        """系统决策应包含 action"""
        r = self.engine.run_daily_cycle()
        sd = r["system_decision"]
        self.assertIn("action", sd)
        self.assertIn(sd["action"], ["TRADE", "HOLD", "REDUCE_RISK"])

    def test_all_phases_run(self):
        """所有阶段应执行完成"""
        r = self.engine.run_daily_cycle()
        for phase in ("market_summary", "signals", "risk_status", "capital_allocation", "paper_trading", "performance", "robustness", "walkforward", "governance"):
            self.assertIn(phase, r)

    def test_run_success_flag(self):
        """运行成功标志应为 True"""
        r = self.engine.run_daily_cycle()
        self.assertTrue(r.get("run_success", False))

    def test_market_summary_has_trend(self):
        """市场摘要应包含趋势"""
        r = self.engine.run_daily_cycle()
        ms = r.get("market_summary", {})
        self.assertIn("market_trend", ms)

    def test_signals_list(self):
        """信号列表应非空"""
        r = self.engine.run_daily_cycle()
        self.assertGreater(len(r.get("signals", [])), 0)

    def test_system_decision_confidence_in_range(self):
        """决策置信度应在 0~1 之间"""
        r = self.engine.run_daily_cycle()
        conf = r["system_decision"].get("confidence", 0)
        self.assertGreaterEqual(conf, 0.0)
        self.assertLessEqual(conf, 1.0)

    def test_log_not_empty(self):
        """日志应非空"""
        r = self.engine.run_daily_cycle()
        self.assertGreater(len(r.get("log", [])), 0)

    def test_file_output(self):
        """应生成 JSON 文件"""
        today = __import__("datetime").date.today().isoformat().replace("-", "")
        report_file = Path(__file__).parent.parent / "reports" / f"northstar_daily_cycle_{today}.json"
        if report_file.exists():
            os.unlink(report_file)
        r = self.engine.run_daily_cycle()
        self.assertTrue(report_file.exists())

    def test_paper_trading_return(self):
        """模拟交易应产生收益"""
        r = self.engine.run_daily_cycle()
        pt = r.get("paper_trading", {})
        self.assertIn("total_return_pct", pt)


if __name__ == "__main__":
    unittest.main()