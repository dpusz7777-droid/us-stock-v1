# -*- coding: utf-8 -*-
"""策略治理层测试 — run_strategy_governance 的只读测试。"""

from __future__ import annotations
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.engine.strategy_governance import run_strategy_governance


class TestStrategyGovernance(unittest.TestCase):
    def setUp(self):
        self.sample_evolution = {
            "strategy_updates": {
                "momentum": {"action": "increase", "weight_change": 0.08, "reason": "high win_rate"},
                "defensive": {"action": "maintain", "weight_change": 0.0, "reason": "stable"},
                "breakout": {"action": "decrease", "weight_change": -0.05, "reason": "low win_rate"},
            }
        }
        self.sample_attr = {
            "strategy_attribution": {
                "momentum": {"total_return": 12.0, "win_rate": 0.65, "trade_count": 10},
                "defensive": {"total_return": 8.0, "win_rate": 0.70, "trade_count": 8},
                "breakout": {"total_return": -3.0, "win_rate": 0.25, "trade_count": 6},
                "mean_reversion": {"total_return": 1.0, "win_rate": 0.50, "trade_count": 4},
            }
        }

    def test_empty_no_crash(self):
        """空数据不崩溃"""
        r = run_strategy_governance(None, None)
        self.assertIn("locked_strategies", r)
        self.assertIn("restricted_evolution", r)
        self.assertIn("evolution_rate_limit", r)
        self.assertIn("stability_score", r)
        self.assertIn("drift_detection", r)
        self.assertIn("system_status", r)

    def test_locked_strategies_contains_core(self):
        """锁定策略应包含 core 策略"""
        r = run_strategy_governance(self.sample_evolution, self.sample_attr)
        ls = {s["strategy"] for s in r["locked_strategies"]}
        self.assertIn("defensive", ls)
        self.assertIn("mean_reversion", ls)

    def test_stability_score_in_range(self):
        """稳定性分数应在 0~1 之间"""
        r = run_strategy_governance(self.sample_evolution, self.sample_attr)
        self.assertGreaterEqual(r["stability_score"], 0.0)
        self.assertLessEqual(r["stability_score"], 1.0)

    def test_drift_detection_has_keys(self):
        """漂移检测应包含 is_drifting 和 drift_reason"""
        r = run_strategy_governance(self.sample_evolution, self.sample_attr)
        dd = r["drift_detection"]
        self.assertIn("is_drifting", dd)
        self.assertIn("drift_reason", dd)

    def test_system_status_valid(self):
        """系统状态应有效"""
        r = run_strategy_governance(self.sample_evolution, self.sample_attr)
        self.assertIn(r["system_status"], ["stable", "warning", "unstable"])

    def test_evolution_rate_limit_has_keys(self):
        """进化速率限制应包含所需字段"""
        r = run_strategy_governance(self.sample_evolution, self.sample_attr)
        erl = r["evolution_rate_limit"]
        self.assertIn("max_changes_per_cycle", erl)
        self.assertIn("current_changes", erl)
        self.assertIn("throttled", erl)

    def test_restricted_evolution(self):
        """应返回限制列表"""
        r = run_strategy_governance(self.sample_evolution, self.sample_attr)
        self.assertIsInstance(r["restricted_evolution"], list)

    def test_locked_strategies_reason(self):
        """锁定策略应包含原因"""
        r = run_strategy_governance(self.sample_evolution, self.sample_attr)
        for s in r["locked_strategies"]:
            self.assertIn("strategy", s)
            self.assertIn("reason", s)

    def test_restricted_strategy_has_fields(self):
        """限制策略应包含所需字段"""
        r = run_strategy_governance(self.sample_evolution, self.sample_attr)
        for s in r["restricted_evolution"]:
            self.assertIn("strategy", s)
            self.assertIn("restriction", s)
            self.assertIn("reason", s)


if __name__ == "__main__":
    unittest.main()