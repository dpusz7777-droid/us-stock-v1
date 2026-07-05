# -*- coding: utf-8 -*-
"""执行现实层测试 — ExecutionRealityEngine 的只读测试。"""

from __future__ import annotations
import sys, unittest, os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.execution.execution_reality_engine import ExecutionRealityEngine


class TestExecutionReality(unittest.TestCase):
    def setUp(self):
        self.engine = ExecutionRealityEngine()
        self.buy_signal = {"symbol": "NVDA", "signal": "BUY", "confidence": 0.85}
        self.sell_signal = {"symbol": "MSFT", "signal": "SELL", "confidence": 0.75}
        self.watch_signal = {"symbol": "AAPL", "signal": "WATCH", "confidence": 0.50}

    def test_initial_state(self):
        """初始状态正确"""
        self.assertEqual(len(self.engine._trades), 0)
        self.assertEqual(len(self.engine._pending_orders), 0)

    def test_slippage_model_returns_positive(self):
        """滑点模型应返回正值"""
        slippage = self.engine.slippage_model({"symbol": "NVDA", "order_size": 50000, "atr": 20.0}, 800.0)
        self.assertGreater(slippage, 0)

    def test_impact_model_large_order(self):
        """大单应产生更大冲击"""
        small = self.engine.market_impact_model(1000, 10000000)
        large = self.engine.market_impact_model(1000000, 10000000)
        self.assertGreater(large, small)

    def test_latency_model_returns_tuple(self):
        """延迟模型应返回 (ms, drift)"""
        ms, drift = self.engine.latency_model()
        self.assertGreaterEqual(ms, 50)
        self.assertLessEqual(ms, 2000)

    def test_partial_fill_large_order(self):
        """大单应部分成交"""
        fill = self.engine.partial_fill_model(1000000, 10000000)
        self.assertLess(fill, 1.0)

    def test_partial_fill_small_order(self):
        """小单应完全成交"""
        fill = self.engine.partial_fill_model(100, 10000000)
        self.assertEqual(fill, 1.0)

    def test_execute_buy_trade_returns_trade(self):
        """BUY 交易应返回 trade 结构"""
        trade = self.engine.execute_realistic_trade(self.buy_signal)
        self.assertIn("execution_price", trade)
        self.assertIn("slippage_cost", trade)
        self.assertIn("fill_rate", trade)
        self.assertEqual(trade["action"], "BUY")

    def test_execute_watch_skips(self):
        """WATCH 信号应跳过"""
        trade = self.engine.execute_realistic_trade(self.watch_signal)
        self.assertEqual(trade["action"], "SKIP")

    def test_execution_gap_negative(self):
        """执行 gap 应为负（现实 < 理论）"""
        self.engine.execute_realistic_trade(self.buy_signal)
        report = self.engine.get_execution_report()
        self.assertLessEqual(report["execution_gap"], 0)

    def test_report_has_keys(self):
        """报告应包含所需字段"""
        self.engine.execute_realistic_trade(self.buy_signal)
        report = self.engine.get_execution_report()
        for key in ("theoretical_return", "realistic_return", "slippage_cost", "market_impact_cost", "latency_cost", "fill_rate", "execution_gap"):
            self.assertIn(key, report)

    def test_reset_clears(self):
        """reset 清空所有"""
        self.engine.execute_realistic_trade(self.buy_signal)
        self.engine.reset()
        self.assertEqual(len(self.engine._trades), 0)

    def test_file_output(self):
        """应生成 JSON 文件"""
        today = __import__("datetime").date.today().isoformat().replace("-", "")
        report_file = Path(__file__).parent.parent / "reports" / f"execution_reality_{today}.json"
        if report_file.exists():
            os.unlink(report_file)
        self.engine.execute_realistic_trade(self.buy_signal)
        self.engine.get_execution_report()
        self.assertTrue(report_file.exists())


if __name__ == "__main__":
    unittest.main()