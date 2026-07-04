# -*- coding: utf-8 -*-
"""实时账户引擎测试 — PortfolioEngine 的只读测试。"""

from __future__ import annotations
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.engine.portfolio_engine import PortfolioEngine


class TestPortfolioEngine(unittest.TestCase):
    def setUp(self):
        self.pe = PortfolioEngine(initial_cash=10000.0, mode="paper")

    def test_initial_state(self):
        """初始状态正确"""
        s = self.pe.get_snapshot()
        self.assertEqual(s["cash"], 10000.0)
        self.assertEqual(s["positions"], [])
        self.assertEqual(s["total_value"], 10000.0)
        self.assertEqual(s["mode"], "paper")

    def test_buy_reduces_cash(self):
        """买入减少现金"""
        r = self.pe.buy("AAPL", price=150.0, qty=10)
        self.assertTrue(r["success"])
        s = self.pe.get_snapshot()
        self.assertEqual(s["cash"], 10000.0 - 1500.0)
        self.assertEqual(len(s["positions"]), 1)

    def test_buy_insufficient_cash(self):
        """现金不足返回失败"""
        r = self.pe.buy("AAPL", price=100000.0, qty=1)
        self.assertFalse(r["success"])
        self.assertIn("现金不足", r["message"])

    def test_avg_cost_calculated(self):
        """平均成本计算正确"""
        self.pe.buy("AAPL", price=100.0, qty=10)
        self.pe.buy("AAPL", price=200.0, qty=10)
        avg = self.pe.avg_cost["AAPL"]
        self.assertEqual(avg, 150.0)

    def test_sell_reduces_position(self):
        """卖出减少持仓"""
        self.pe.buy("AAPL", price=150.0, qty=10)
        r = self.pe.sell("AAPL", price=160.0, qty=5)
        self.assertTrue(r["success"])
        s = self.pe.get_snapshot()
        self.assertEqual(len(s["positions"]), 1)
        self.assertEqual(s["positions"][0]["qty"], 5.0)

    def test_sell_all_when_qty_none(self):
        """不传 qty 时全卖"""
        self.pe.buy("AAPL", price=150.0, qty=10)
        r = self.pe.sell("AAPL", price=160.0)
        self.assertTrue(r["success"])
        self.assertEqual(r["qty"], 10.0)

    def test_sell_tracks_realized_pnl(self):
        """卖出记录已实现盈亏"""
        self.pe.buy("AAPL", price=100.0, qty=10)
        self.pe.sell("AAPL", price=110.0, qty=10)
        self.assertEqual(self.pe.realized_pnl, 100.0)

    def test_sell_no_position(self):
        """无持仓时卖出失败"""
        r = self.pe.sell("AAPL", price=160.0)
        self.assertFalse(r["success"])

    def test_hold_no_op(self):
        """HOLD 不影响状态"""
        self.pe.buy("AAPL", price=150.0, qty=10)
        r = self.pe.hold("AAPL")
        self.assertTrue(r["success"])
        s = self.pe.get_snapshot()
        self.assertEqual(len(s["positions"]), 1)

    def test_snapshot_with_market_prices(self):
        """快照计算未实现盈亏"""
        self.pe.buy("AAPL", price=100.0, qty=10)
        s = self.pe.get_snapshot({"AAPL": 110.0})
        self.assertEqual(s["unrealized_pnl"], 100.0)
        self.assertEqual(s["position_value"], 1100.0)

    def test_get_position(self):
        """获取单个持仓"""
        self.pe.buy("AAPL", price=150.0, qty=10)
        pos = self.pe.get_position("AAPL")
        self.assertIsNotNone(pos)
        self.assertEqual(pos["qty"], 10.0)

    def test_get_position_nonexistent(self):
        """不存在的持仓返回 None"""
        pos = self.pe.get_position("NONEXIST")
        self.assertIsNone(pos)

    def test_get_trade_history(self):
        """交易历史正确记录"""
        self.pe.buy("AAPL", price=150.0, qty=10)
        h = self.pe.get_trade_history()
        self.assertEqual(len(h), 1)
        self.assertEqual(h[0]["action"], "BUY")

    def test_get_summary(self):
        """摘要结构正确"""
        self.pe.buy("AAPL", price=150.0, qty=10)
        summary = self.pe.get_summary()
        self.assertIn("mode", summary)
        self.assertIn("cash", summary)
        self.assertIn("positions_count", summary)
        self.assertIn("realized_pnl", summary)
        self.assertEqual(summary["mode"], "paper")

    def test_invalid_mode_raises(self):
        """非法模式抛出异常"""
        with self.assertRaises(ValueError):
            PortfolioEngine(initial_cash=10000, mode="invalid")

    def test_live_mode(self):
        """live 模式正常工作"""
        pe = PortfolioEngine(initial_cash=5000, mode="live")
        self.assertEqual(pe.mode, "live")
        pe.buy("AAPL", price=100.0, qty=10)
        s = pe.get_snapshot()
        self.assertEqual(len(s["positions"]), 1)

    def test_reset(self):
        """reset 清空状态"""
        self.pe.buy("AAPL", price=150.0, qty=10)
        self.pe.reset(initial_cash=5000.0)
        s = self.pe.get_snapshot()
        self.assertEqual(s["cash"], 5000.0)
        self.assertEqual(len(s["positions"]), 0)
        self.assertEqual(s["realized_pnl"], 0.0)


if __name__ == "__main__":
    unittest.main()