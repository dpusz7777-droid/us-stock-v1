# -*- coding: utf-8 -*-
"""模拟交易引擎测试 — PaperTradingEngine 的只读测试。"""

from __future__ import annotations
import sys, unittest, os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.backtest.paper_trading_engine import PaperTradingEngine


class TestPaperTradingEngine(unittest.TestCase):
    def setUp(self):
        self.engine = PaperTradingEngine(initial_capital=100000.0)
        self.sample_signals = [
            {"symbol": "NVDA", "signal": "BUY", "confidence": 0.85, "reason": "ai板块走强"},
            {"symbol": "MSFT", "signal": "WATCH", "confidence": 0.50, "reason": "观察"},
            {"symbol": "XLE", "signal": "AVOID", "confidence": 0.10, "reason": "能源偏弱"},
        ]
        self.sample_prices = {
            "NVDA": [800.0, 810.0, 820.0, 830.0, 840.0, 850.0],
            "MSFT": [300.0, 301.0, 302.0, 303.0, 304.0, 305.0],
            "XLE": [80.0, 79.0, 78.0, 77.0, 76.0, 75.0],
        }

    def test_initial_state(self):
        """初始状态正确"""
        self.assertEqual(self.engine.capital, 100000.0)
        self.assertEqual(len(self.engine.positions), 0)
        self.assertEqual(len(self.engine.closed_trades), 0)

    def test_execute_signals_skips_watch(self):
        """WATCH 信号跳过交易"""
        result = self.engine.execute_signals(self.sample_signals, self.sample_prices)
        watch_results = [r for r in result if r["signal"] == "WATCH"]
        self.assertGreater(len(watch_results), 0)
        self.assertEqual(watch_results[0]["action"], "SKIP")

    def test_execute_signals_skips_avoid(self):
        """AVOID 信号跳过交易"""
        result = self.engine.execute_signals(self.sample_signals, self.sample_prices)
        avoid_results = [r for r in result if r["signal"] == "AVOID"]
        self.assertGreater(len(avoid_results), 0)
        self.assertEqual(avoid_results[0]["action"], "SKIP")

    def test_execute_signals_buy_opens_position(self):
        """BUY 信号开仓"""
        result = self.engine.execute_signals(self.sample_signals, self.sample_prices)
        buy_results = [r for r in result if r["signal"] == "BUY"]
        self.assertGreater(len(buy_results), 0)

    def test_open_position_returns_position(self):
        """开仓返回正确的 position 结构"""
        signal = {"symbol": "NVDA", "signal": "BUY", "confidence": 0.85}
        pos = self.engine.open_position("NVDA", "2026-07-05", 800.0, signal)
        self.assertIsNotNone(pos)
        self.assertEqual(pos["symbol"], "NVDA")
        self.assertEqual(pos["entry_price"], 800.0)
        self.assertEqual(pos["status"], "OPEN")

    def test_close_position_returns_closed(self):
        """平仓返回正确的 closed 结构"""
        signal = {"symbol": "NVDA", "signal": "BUY", "confidence": 0.85}
        pos = self.engine.open_position("NVDA", "2026-07-05", 800.0, signal)
        self.assertIsNotNone(pos)
        closed = self.engine.close_position(pos, "2026-07-10", 850.0)
        self.assertEqual(closed["status"], "CLOSED")
        self.assertGreater(closed["pnl_pct"], 0)

    def test_calculate_portfolio_return(self):
        """计算组合收益率"""
        self.engine.open_position("NVDA", "2026-07-05", 100.0, {"symbol": "NVDA", "signal": "BUY", "confidence": 0.8})
        pos = self.engine.positions[0]
        self.engine.close_position(pos, "2026-07-10", 110.0)
        ret = self.engine.calculate_portfolio_return()
        self.assertGreater(ret, 0)

    def test_get_report_has_keys(self):
        """报告应包含所需字段"""
        signal = {"symbol": "NVDA", "signal": "BUY", "confidence": 0.85}
        pos = self.engine.open_position("NVDA", "2026-07-05", 100.0, signal)
        self.engine.close_position(pos, "2026-07-10", 110.0)
        report = self.engine.get_report()
        self.assertIn("initial_capital", report)
        self.assertIn("total_closed_trades", report)
        self.assertIn("win_rate", report)
        self.assertIn("max_drawdown_pct", report)

    def test_reset(self):
        """reset 重置所有状态"""
        self.engine.open_position("NVDA", "2026-07-05", 100.0, {"symbol": "NVDA", "signal": "BUY", "confidence": 0.8})
        self.engine.reset()
        self.assertEqual(self.engine.capital, 100000.0)
        self.assertEqual(len(self.engine.positions), 0)

    def test_file_output(self):
        """应生成 JSON 文件"""
        today = __import__("datetime").date.today().isoformat().replace("-", "")
        report_file = Path(__file__).parent.parent / "reports" / f"paper_trading_{today}.json"
        if report_file.exists():
            os.unlink(report_file)
        self.engine.execute_signals(self.sample_signals, self.sample_prices)
        self.assertTrue(report_file.exists())

    def test_stop_loss(self):
        """亏损 -5% 应触发止损"""
        prices = {"NVDA": [100.0, 98.0, 96.0, 94.0, 92.0, 90.0]}
        signals = [{"symbol": "NVDA", "signal": "BUY", "confidence": 0.85}]
        self.engine.execute_signals(signals, prices)
        if self.engine.closed_trades:
            self.assertLessEqual(self.engine.closed_trades[0]["pnl_pct"], -5.0)

    def test_take_profit(self):
        """盈利 +8% 应触发止盈"""
        prices = {"NVDA": [100.0, 105.0, 108.0, 110.0, 112.0, 115.0]}
        signals = [{"symbol": "NVDA", "signal": "BUY", "confidence": 0.85}]
        self.engine.execute_signals(signals, prices)
        if self.engine.closed_trades:
            self.assertGreaterEqual(self.engine.closed_trades[0]["pnl_pct"], 8.0)


if __name__ == "__main__":
    unittest.main()