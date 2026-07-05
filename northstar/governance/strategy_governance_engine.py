#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""策略治理与系统收敛层 — 对所有策略进行统一管理、筛选、淘汰与版本控制。

用法：
    from northstar.governance.strategy_governance_engine import StrategyGovernanceEngine
    engine = StrategyGovernanceEngine()
    engine.register_strategy("momentum_v1", {"return_score": 85, "stability_score": 75, ...})
    engine.prune_strategies()
    portfolio = engine.select_active_portfolio()
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

MAX_STRATEGIES = 10
MAX_A_STRATEGIES = 3
MAX_B_STRATEGIES = 5


class StrategyGovernanceEngine:
    """策略治理引擎 — 策略生命周期管理。"""

    def __init__(self) -> None:
        self._strategies: dict[str, dict[str, Any]] = {}
        self._health_cache: dict[str, float] = {}
        self._classification_cache: dict[str, str] = {}
        self._governance_log: list[str] = []
        self._consecutive_low_score: dict[str, int] = {}

    def register_strategy(
        self,
        strategy_id: str,
        metrics: dict[str, Any],
    ) -> None:
        """注册一个策略及其评价指标。

        Args:
            strategy_id: 策略唯一标识
            metrics: 包含 return_score, stability_score, consistency_score, max_drawdown 等
        """
        self._strategies[strategy_id] = metrics
        self._health_cache.pop(strategy_id, None)
        self._classification_cache.pop(strategy_id, None)

    def _compute_health_score(self, metrics: dict[str, Any]) -> float:
        """计算策略健康评分 (0-100)。

        health_score = 
            0.35 * return_score +
            0.25 * stability_score +
            0.20 * consistency_score +
            0.20 * risk_adjusted_score

        risk_adjusted_score = 100 - max_drawdown_penalty
        """
        return_score = metrics.get("return_score", 50)
        stability_score = metrics.get("stability_score", 50)
        consistency_score = metrics.get("consistency_score", 50)
        max_drawdown = metrics.get("max_drawdown", 15)

        drawdown_penalty = min(max_drawdown * 2, 60)
        risk_adjusted = max(0, 100 - drawdown_penalty)

        health = (
            0.35 * return_score
            + 0.25 * stability_score
            + 0.20 * consistency_score
            + 0.20 * risk_adjusted
        )
        return round(health, 1)

    def evaluate_strategy_health(self, strategy_id: str) -> float:
        """评估单个策略的健康评分。"""
        metrics = self._strategies.get(strategy_id)
        if not metrics:
            return 0.0
        score = self._compute_health_score(metrics)
        self._health_cache[strategy_id] = score
        return score

    def _classify_single(self, health_score: float, metrics: dict[str, Any]) -> str:
        """对单个策略进行分类。"""
        stability = metrics.get("stability_score", 0)
        max_dd = metrics.get("max_drawdown", 100)

        if health_score >= 80 and stability >= 75 and max_dd < 10:
            return "A"
        if health_score >= 60:
            return "B"
        if health_score >= 40:
            return "C"
        return "D"

    def classify_strategies(self) -> dict[str, str]:
        """对所有注册策略进行分类。"""
        result = {}
        for sid, metrics in self._strategies.items():
            health = self.evaluate_strategy_health(sid)
            cls = self._classify_single(health, metrics)
            result[sid] = cls
            self._classification_cache[sid] = cls
        return result

    def prune_strategies(self) -> list[str]:
        """执行策略淘汰与清理。

        Returns:
            被删除的策略ID列表
        """
        classification = self.classify_strategies()
        pruned = []

        # D级策略必须立即移除
        for sid, cls in classification.items():
            if cls == "D":
                pruned.append(sid)
                self._log_governance(f"removed D-grade strategy: {sid}")

        for sid in pruned:
            self._strategies.pop(sid, None)
            self._health_cache.pop(sid, None)
            self._classification_cache.pop(sid, None)

        # 更新分类
        classification = self.classify_strategies()

        # B级策略最多保留Top 5
        b_strategies = [s for s, c in classification.items() if c == "B"]
        b_strategies.sort(key=lambda s: self._health_cache.get(s, 0), reverse=True)
        for sid in b_strategies[MAX_B_STRATEGIES:]:
            pruned.append(sid)
            self._log_governance(f"pruned B-grade strategy (limit): {sid}")
            self._strategies.pop(sid, None)
            self._classification_cache.pop(sid, None)

        # A级策略最多保留Top 3
        classification = self.classify_strategies()
        a_strategies = [s for s, c in classification.items() if c == "A"]
        a_strategies.sort(key=lambda s: self._health_cache.get(s, 0), reverse=True)
        for sid in a_strategies[MAX_A_STRATEGIES:]:
            pruned.append(sid)
            self._log_governance(f"pruned A-grade strategy (overlimit): {sid}")
            self._strategies.pop(sid, None)
            self._classification_cache.pop(sid, None)

        # 强制限制策略总数 <= 10
        classification = self.classify_strategies()
        all_sorted = sorted(classification.keys(), key=lambda s: self._health_cache.get(s, 0), reverse=True)
        for sid in all_sorted[MAX_STRATEGIES:]:
            pruned.append(sid)
            self._log_governance(f"pruned strategy (max limit): {sid}")
            self._strategies.pop(sid, None)
            self._classification_cache.pop(sid, None)

        return pruned

    def select_active_portfolio(self) -> dict[str, Any]:
        """选择当前可运行策略组合。

        Returns:
            ActiveStrategyPortfolio: {strategies, weights, expected_return, expected_drawdown}
        """
        classification = self.classify_strategies()

        # 仅 A级 + Top B级
        a_strategies = [s for s, c in classification.items() if c == "A"]
        b_strategies = [s for s, c in classification.items() if c == "B"]
        b_strategies.sort(key=lambda s: self._health_cache.get(s, 0), reverse=True)

        # 保留所有A级 + Top 3 B级
        active = a_strategies + b_strategies[:3]

        # 权重分配
        scores = {s: self._health_cache.get(s, 0) for s in active}
        total_score = sum(scores.values())
        weights = {s: round(v / total_score, 4) if total_score > 0 else 0.0 for s, v in scores.items()}

        # 期望收益与回撤
        returns = []
        drawdowns = []
        for sid in active:
            metrics = self._strategies.get(sid, {})
            # 估算为 health_score 映射到 0~10% 收益
            est_return = (self._health_cache.get(sid, 50) / 100) * 10
            returns.append(est_return)
            drawdowns.append(metrics.get("max_drawdown", 15))

        expected_return = round(sum(returns) / len(returns), 2) if returns else 0.0
        expected_drawdown = round(max(drawdowns), 2) if drawdowns else 0.0

        return {
            "strategies": active,
            "weights": weights,
            "expected_return_pct": expected_return,
            "expected_max_drawdown_pct": expected_drawdown,
        }

    def get_system_complexity_score(self) -> float:
        """计算系统复杂度评分。"""
        n = len(self._strategies)
        if n <= 5:
            return round(n / 5 * 20, 1)
        if n <= MAX_STRATEGIES:
            return round(20 + (n - 5) / 5 * 30, 1)
        return 100.0

    def get_report(self) -> dict[str, Any]:
        """生成完整治理报告。"""
        classification = self.classify_strategies()
        active_portfolio = self.select_active_portfolio()

        grade_counts = {"A": 0, "B": 0, "C": 0, "D": 0}
        for cls in classification.values():
            grade_counts[cls] = grade_counts.get(cls, 0) + 1

        a_ratio = round(grade_counts["A"] / max(len(classification), 1) * 100, 1)
        passed = a_ratio > 30

        result = {
            "total_strategies": len(self._strategies),
            "grade_distribution": grade_counts,
            "classification": classification,
            "health_scores": dict(self._health_cache),
            "active_portfolio": active_portfolio,
            "system_complexity_score": self.get_system_complexity_score(),
            "governance_action_log": self._governance_log[-20:],
            "governance_check_passed": passed,
            "is_over_complex": len(self._strategies) > MAX_STRATEGIES,
        }

        today = date.today().isoformat().replace("-", "")
        reports_dir = Path(__file__).parent.parent.parent / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_file = reports_dir / f"strategy_governance_{today}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        return result

    def get_strategy_count(self) -> int:
        """获取当前策略数量。"""
        return len(self._strategies)

    def _log_governance(self, message: str) -> None:
        """记录治理日志。"""
        from datetime import datetime
        self._governance_log.append(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")

    def clear(self) -> None:
        """清空所有策略。"""
        self._strategies = {}
        self._health_cache = {}
        self._classification_cache = {}
        self._governance_log = []
        self._consecutive_low_score = {}