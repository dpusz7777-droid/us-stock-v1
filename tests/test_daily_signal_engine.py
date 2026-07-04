# -*- coding: utf-8 -*-
"""每日交易信号系统测试 — generate_daily_signals 的只读测试。"""

from __future__ import annotations
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.engine.daily_signal_engine import generate_daily_signals


class TestDailySignalEngine(unittest.TestCase):
    def setUp(self):
        self.sample_portfolio = {
            "cash": 5000.0,
            "total_value": 10000.0,
            "positions": [{"symbol": "AAPL", "qty": 10, "avg_cost": 150.0}],
        }
        self.sample_attr = {
            "strategy_attribution": {
                "momentum": {"total_return": 12.0, "win_rate": 0.65, "trade_count": 10},
                "defensive": {"total_return": 8.0, "win_rate": 0.70, "trade_count": 8},
            },
            "regime_attribution": {
                "bull": {"return": 15.0, "accuracy": 0.75, "trade_count": 12},
                "bear": {"return": -2.0, "accuracy": 0.40, "trade_count": 5},
            },
            "source_attribution": {
                "v37": {"quality_score": 0.72, "trade_count": 10},
                "v39": {"quality_score": 0.65, "trade_count": 8},
            },
            "overall_system_score": 0.65,
        }
        self.sample_evolution = {
            "weight_vector": {"momentum": 0.30, "defensive": 0.40, "mean_reversion": 0.20, "breakout": 0.10},
        }
        self.sample_governance = {"system_status": "stable"}

    def test_empty_no_crash(self):
        """空数据不崩溃"""
        r = generate_daily_signals(None, None, None, "unknown", None, None)
        self.assertIn("date", r)
        self.assertIn("signals", r)
        self.assertIn("portfolio_summary", r)
        self.assertIn("market_view", r)

    def test_signals_generated(self):
        """应生成信号列表"""
        r = generate_daily_signals(
            self.sample_portfolio, [], self.sample_attr,
            "bull", self.sample_evolution, self.sample_governance,
        )
        self.assertGreater(len(r["signals"]), 0)

    def test_signal_has_fields(self):
        """信号应包含所需字段"""
        r = generate_daily_signals(
            self.sample_portfolio, [], self.sample_attr,
            "bull", self.sample_evolution, self.sample_governance,
        )
        for signal in r["signals"]:
            self.assertIn("symbol", signal)
            self.assertIn("action", signal)
            self.assertIn("confidence", signal)
            self.assertIn("position_sizing", signal)
            self.assertIn("strategy_source", signal)
            self.assertIn("reason", signal)

    def test_action_in_valid_set(self):
        """动作应为 BUY/SELL/HOLD"""
        r = generate_daily_signals(
            self.sample_portfolio, [], self.sample_attr,
            "bull", self.sample_evolution, self.sample_governance,
        )
        for signal in r["signals"]:
            self.assertIn(signal["action"], ["BUY", "SELL", "HOLD"])

    def test_confidence_in_range(self):
        """confidence 应在 0~1 之间"""
        r = generate_daily_signals(
            self.sample_portfolio, [], self.sample_attr,
            "bull", self.sample_evolution, self.sample_governance,
        )
        for signal in r["signals"]:
            self.assertGreaterEqual(signal["confidence"], 0.0)
            self.assertLessEqual(signal["confidence"], 1.0)

    def test_position_sizing_in_range(self):
        """position_sizing 应在 0~1 之间"""
        r = generate_daily_signals(
            self.sample_portfolio, [], self.sample_attr,
            "bull", self.sample_evolution, self.sample_governance,
        )
        for signal in r["signals"]:
            self.assertGreaterEqual(signal["position_sizing"], 0.0)
            self.assertLessEqual(signal["position_sizing"], 1.0)

    def test_portfolio_summary_has_keys(self):
        """portfolio_summary 应包含所需字段"""
        r = generate_daily_signals(
            self.sample_portfolio, [], self.sample_attr,
            "bull", self.sample_evolution, self.sample_governance,
        )
        ps = r["portfolio_summary"]
        self.assertIn("risk_level", ps)
        self.assertIn("exposure", ps)

    def test_market_view_has_keys(self):
        """market_view 应包含所需字段"""
        r = generate_daily_signals(
            self.sample_portfolio, [], self.sample_attr,
            "bull", self.sample_evolution, self.sample_governance,
        )
        mv = r["market_view"]
        self.assertIn("regime", mv)
        self.assertIn("confidence", mv)

    def test_top_risks_non_empty(self):
        """top_risks 应非空"""
        r = generate_daily_signals(
            self.sample_portfolio, [], self.sample_attr,
            "bull", self.sample_evolution, self.sample_governance,
        )
        self.assertGreater(len(r["top_risks"]), 0)

    def test_top_opportunities_non_empty(self):
        """top_opportunities 应非空"""
        r = generate_daily_signals(
            self.sample_portfolio, [], self.sample_attr,
            "bull", self.sample_evolution, self.sample_governance,
        )
        self.assertGreater(len(r["top_opportunities"]), 0)

    def test_strategy_allocation_has_keys(self):
        """strategy_allocation 应包含权重"""
        r = generate_daily_signals(
            self.sample_portfolio, [], self.sample_attr,
            "bull", self.sample_evolution, self.sample_governance,
        )
        sa = r["strategy_allocation"]
        self.assertGreater(len(sa), 0)

    def test_custom_symbols(self):
        """自定义 symbol 列表"""
        r = generate_daily_signals(
            self.sample_portfolio, [], self.sample_attr,
            "bull", self.sample_evolution, self.sample_governance,
            available_symbols=["NVDA"],
        )
        self.assertEqual(len(r["signals"]), 1)
        self.assertEqual(r["signals"][0]["symbol"], "NVDA")


if __name__ == "__main__":
    unittest.main()