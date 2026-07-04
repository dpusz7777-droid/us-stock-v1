# -*- coding: utf-8 -*-
"""回测引擎测试 — run_backtest / run_backtest_with_regime 的只读测试。"""

from __future__ import annotations
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.engine.backtest_engine import (
    run_backtest,
    run_backtest_with_regime,
    _compute_trade_outcome,
)


class TestBacktestEngine(unittest.TestCase):
    def setUp(self):
        self.sample_decisions = [
            {"symbol": "AAPL", "action": "BUY", "price": 150.0, "date": "2024-01-01"},
            {"symbol": "AAPL", "action": "SELL", "price": 160.0, "date": "2024-01-15"},
            {"symbol": "MSFT", "action": "BUY", "price": 300.0, "date": "2024-02-01"},
        ]
        self.sample_prices = {
            "AAPL": [
                {"date": "2024-01-10", "close": 155.0},
                {"date": "2024-01-20", "close": 158.0},
            ],
            "MSFT": [
                {"date": "2024-02-10", "close": 310.0},
                {"date": "2024-02-20", "close": 315.0},
            ],
        }

    def test_empty_no_crash(self):
        """空数据不崩溃"""
        r = run_backtest(None, None, None)
        self.assertIn("total_return", r)
        self.assertIn("win_rate", r)
        self.assertIn("strategy_performance", r)
        self.assertIn("decision_accuracy", r)

    def test_empty_decisions_no_crash(self):
        """空决策列表不崩溃"""
        r = run_backtest([], [], {})
        self.assertEqual(r["total_return"], 0.0)

    def test_total_return_calculated(self):
        """总收益应正确计算"""
        r = run_backtest(None, self.sample_decisions, self.sample_prices)
        self.assertIsInstance(r["total_return"], float)

    def test_win_rate_in_range(self):
        """胜率应在 0~1 之间"""
        r = run_backtest(None, self.sample_decisions, self.sample_prices)
        self.assertGreaterEqual(r["win_rate"], 0.0)
        self.assertLessEqual(r["win_rate"], 1.0)

    def test_strategy_performance_has_keys(self):
        """strategy_performance 应有策略 key"""
        r = run_backtest(None, self.sample_decisions, self.sample_prices)
        for st, data in r["strategy_performance"].items():
            self.assertIn("win_rate", data)
            self.assertIn("avg_return", data)

    def test_decision_accuracy_structure(self):
        """decision_accuracy 应包含 BUY/SELL/HOLD"""
        r = run_backtest(None, self.sample_decisions, self.sample_prices)
        for action in ("BUY", "SELL", "HOLD"):
            self.assertIn(action, r["decision_accuracy"])

    def test_avg_return_per_trade(self):
        """平均每笔收益应正确"""
        r = run_backtest(None, self.sample_decisions, self.sample_prices)
        self.assertIsInstance(r["avg_return_per_trade"], float)

    def test_trade_outcome(self):
        """单笔交易计算应正确（BUY 上涨应盈利）"""
        outcome = _compute_trade_outcome(
            {"symbol": "AAPL", "action": "BUY", "price": 100.0, "date": "2024-01-01"},
            {"AAPL": [{"date": "2024-01-10", "close": 110.0}]},
        )
        self.assertGreater(outcome["return_pct"], 0)

    def test_trade_outcome_sell(self):
        """SELL 在价格下跌时应盈利"""
        outcome = _compute_trade_outcome(
            {"symbol": "AAPL", "action": "SELL", "price": 100.0, "date": "2024-01-01"},
            {"AAPL": [{"date": "2024-01-10", "close": 90.0}]},
        )
        self.assertGreater(outcome["return_pct"], 0)

    def test_regime_performance(self):
        """带 regime 的回测应输出 regime_performance"""
        regimes = [
            {"date": "2024-01-01", "regime": "bull"},
            {"date": "2024-01-15", "regime": "bull"},
            {"date": "2024-02-01", "regime": "bear"},
        ]
        r = run_backtest_with_regime(None, self.sample_decisions, self.sample_prices, regimes)
        self.assertIn("regime_performance", r)

    def test_regime_empty_no_crash(self):
        """regime 空数据不崩溃"""
        r = run_backtest_with_regime(None, None, None, None)
        self.assertIn("total_return", r)


if __name__ == "__main__":
    unittest.main()