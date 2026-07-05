# -*- coding: utf-8 -*-
"""风险控制与资金管理系统测试 — RiskManager 的只读测试。"""

from __future__ import annotations
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.risk.risk_manager import RiskManager


class TestRiskManager(unittest.TestCase):
    def setUp(self):
        self.rm = RiskManager(initial_capital=100000.0)

    def test_initial_risk_level_low(self):
        """初始风险等级应为 LOW"""
        self.assertEqual(self.rm.risk_level, "LOW")

    def test_calculate_position_size_high_confidence(self):
        """高置信度应该返回较大仓位"""
        size = self.rm.calculate_position_size(confidence=0.85, price=100.0)
        expected = 100000.0 * 0.2
        self.assertEqual(size, expected)

    def test_calculate_position_size_medium_confidence(self):
        """中等置信度返回10%仓位"""
        size = self.rm.calculate_position_size(confidence=0.6, price=100.0)
        expected = 100000.0 * 0.1
        self.assertEqual(size, expected)

    def test_calculate_position_size_low_confidence(self):
        """低置信度返回5%仓位"""
        size = self.rm.calculate_position_size(confidence=0.4, price=100.0)
        expected = 100000.0 * 0.05
        self.assertEqual(size, expected)

    def test_high_risk_reduces_position(self):
        """高风险状态下仓位减半"""
        self.rm.risk_level = "HIGH"
        size = self.rm.calculate_position_size(confidence=0.85, price=100.0)
        expected = 100000.0 * 0.2 * 0.5
        self.assertEqual(size, expected)

    def test_check_risk_limits_allows_by_default(self):
        """默认应允许开仓"""
        allowed = self.rm.check_risk_limits()
        self.assertTrue(allowed)

    def test_daily_loss_blocks_trading(self):
        """单日亏损超限应禁止开仓"""
        self.rm.record_daily_pnl(-4000.0)
        allowed = self.rm.check_risk_limits()
        self.assertFalse(allowed)

    def test_drawdown_blocks_trading(self):
        """总回撤超10%应禁止开仓"""
        self.rm.total_drawdown_pct = 0.15
        allowed = self.rm.check_risk_limits()
        self.assertFalse(allowed)

    def test_consecutive_losses_raise_risk(self):
        """连续3笔亏损应提升风险等级"""
        self.rm.record_trade_result(-2.0)
        self.rm.record_trade_result(-1.0)
        self.rm.record_trade_result(-3.0)
        self.assertEqual(self.rm.risk_level, "HIGH")

    def test_consecutive_wins_lower_risk(self):
        """连续3笔盈利应降低风险等级"""
        self.rm.risk_level = "HIGH"
        self.rm.record_trade_result(2.0)
        self.rm.record_trade_result(1.0)
        self.rm.record_trade_result(3.0)
        self.assertEqual(self.rm.risk_level, "MEDIUM")

    def test_adjust_exposure_low_drawdown(self):
        """低回撤时应返回1.0"""
        mult = self.rm.adjust_exposure(0.03)
        self.assertEqual(mult, 1.0)

    def test_adjust_exposure_high_drawdown(self):
        """高回撤时应返回0.5"""
        mult = self.rm.adjust_exposure(0.15)
        self.assertEqual(mult, 0.5)

    def test_get_risk_metrics_has_keys(self):
        """风险指标应包含所需字段"""
        metrics = self.rm.get_risk_metrics()
        self.assertIn("risk_level", metrics)
        self.assertIn("max_drawdown_pct", metrics)
        self.assertIn("position_utilization", metrics)
        self.assertIn("can_trade_today", metrics)
        self.assertIn("consecutive_losses", metrics)
        self.assertIn("consecutive_wins", metrics)
        self.assertIn("recent_risk_events", metrics)

    def test_reset(self):
        """reset 重置所有状态"""
        self.rm.risk_level = "HIGH"
        self.rm.record_daily_pnl(-5000.0)
        self.rm.reset()
        self.assertEqual(self.rm.risk_level, "LOW")
        self.assertEqual(self.rm.capital, 100000.0)
        self.assertEqual(len(self.rm.daily_pnl), 0)

    def test_set_position_utilization(self):
        """设置仓位利用率"""
        self.rm.set_position_utilization(50000.0, 100000.0)
        self.assertEqual(self.rm._position_utilization, 0.5)


if __name__ == "__main__":
    unittest.main()