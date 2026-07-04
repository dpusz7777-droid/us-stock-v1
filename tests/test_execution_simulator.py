# -*- coding: utf-8 -*-
"""执行仿真测试 — ExecutionSimulator 的只读测试。"""

from __future__ import annotations
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.engine.execution_simulator import ExecutionSimulator


class TestExecutionSimulator(unittest.TestCase):
    def setUp(self):
        self.sim = ExecutionSimulator(initial_cash=10000.0)

    def test_initial_state(self):
        """初始状态正确"""
        status = self.sim.get_portfolio_status()
        self.assertEqual(status["cash"], 10000.0)
        self.assertEqual(status["positions"], {})
        self.assertEqual(status["total_value"], 10000.0)
        self.assertEqual(status["trade_count"], 0)

    def test_buy_reduces_cash(self):
        """买入减少现金"""
        result = self.sim.execute_decision("AAPL", "BUY", price=150.0, qty=10)
        self.assertTrue(result["success"])
        status = self.sim.get_portfolio_status()
        self.assertEqual(status["cash"], 10000.0 - 1500.0)
        self.assertEqual(status["positions"]["AAPL"], 10.0)

    def test_buy_insufficient_cash(self):
        """现金不足返回失败"""
        result = self.sim.execute_decision("AAPL", "BUY", price=100000.0, qty=1)
        self.assertFalse(result["success"])
        self.assertIn("现金不足", result["message"])

    def test_sell_reduces_position(self):
        """卖出减少持仓"""
        self.sim.execute_decision("AAPL", "BUY", price=150.0, qty=10)
        result = self.sim.execute_decision("AAPL", "SELL", price=160.0, qty=5)
        self.assertTrue(result["success"])
        status = self.sim.get_portfolio_status()
        self.assertEqual(status["positions"]["AAPL"], 5.0)

    def test_sell_all_when_qty_none(self):
        """不传 qty 时全卖"""
        self.sim.execute_decision("AAPL", "BUY", price=150.0, qty=10)
        result = self.sim.execute_decision("AAPL", "SELL", price=160.0)
        self.assertTrue(result["success"])
        self.assertEqual(result["qty"], 10.0)
        self.assertNotIn("AAPL", self.sim.positions)

    def test_sell_no_position(self):
        """无持仓时卖出失败"""
        result = self.sim.execute_decision("AAPL", "SELL", price=160.0)
        self.assertFalse(result["success"])
        self.assertIn("无 AAPL 持仓", result["message"])

    def test_hold_no_op(self):
        """HOLD 不改变状态"""
        self.sim.execute_decision("AAPL", "BUY", price=150.0, qty=10)
        result = self.sim.execute_decision("AAPL", "HOLD", price=155.0)
        self.assertTrue(result["success"])
        self.assertEqual(result["qty"], 0)

    def test_portfolio_value_with_prices(self):
        """带价格的组合市值计算正确"""
        self.sim.execute_decision("AAPL", "BUY", price=150.0, qty=10)
        self.sim.execute_decision("MSFT", "BUY", price=300.0, qty=5)
        prices = {"AAPL": 160.0, "MSFT": 310.0}
        status = self.sim.get_portfolio_status(prices)
        expected_value = 10 * 160.0 + 5 * 310.0
        self.assertEqual(status["position_value"], expected_value)

    def test_execution_history(self):
        """执行历史正确记录"""
        self.sim.execute_decision("AAPL", "BUY", price=150.0, qty=10, reason="signal")
        history = self.sim.get_execution_history(limit=5)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["symbol"], "AAPL")
        self.assertEqual(history[0]["action"], "BUY")
        self.assertEqual(history[0]["reason"], "signal")

    def test_get_summary(self):
        """get_summary 返回正确结构"""
        self.sim.execute_decision("AAPL", "BUY", price=150.0, qty=10)
        self.sim.execute_decision("AAPL", "HOLD", price=155.0)
        summary = self.sim.get_summary()
        self.assertIn("initial_cash", summary)
        self.assertIn("current_cash", summary)
        self.assertIn("positions_count", summary)
        self.assertIn("total_trades", summary)
        self.assertEqual(summary["buys"], 1)
        self.assertEqual(summary["holds"], 1)

    def test_reset(self):
        """reset 清空所有状态"""
        self.sim.execute_decision("AAPL", "BUY", price=150.0, qty=10)
        self.sim.reset(initial_cash=5000.0)
        status = self.sim.get_portfolio_status()
        self.assertEqual(status["cash"], 5000.0)
        self.assertEqual(status["positions"], {})
        self.assertEqual(status["trade_count"], 0)

    def test_auto_qty_buy(self):
        """不传 qty 时自动计算最大可买数量"""
        result = self.sim.execute_decision("AAPL", "BUY", price=150.0)
        self.assertTrue(result["success"])
        expected_qty = int(10000.0 / 150.0)
        self.assertEqual(result["qty"], expected_qty)


if __name__ == "__main__":
    unittest.main()