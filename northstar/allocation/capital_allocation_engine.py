#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""资金分配与组合管理系统 — 将策略组合转换为资金分配方案。

用法：
    from northstar.allocation.capital_allocation_engine import CapitalAllocationEngine
    engine = CapitalAllocationEngine(total_capital=100000)
    allocation = engine.allocate_capital(active_portfolio)
    rebalanced = engine.rebalance_portfolio(market_state)
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

# 集中度限制
MAX_SINGLE_WEIGHT = 0.25
MAX_TOP2_TOTAL = 0.45
MAX_TOP3_TOTAL = 0.60
REBALANCE_INTERVAL_DAYS = 7
MAX_ADJUSTMENT_PCT = 0.20

RISK_ADJUSTMENT = {"LOW": 1.0, "MEDIUM": 0.8, "HIGH": 0.5}


class CapitalAllocationEngine:
    """资金分配与组合管理引擎。"""

    def __init__(self, total_capital: float = 100000.0) -> None:
        self.total_capital: float = total_capital
        self.last_rebalance: date | None = None
        self._allocation_history: list[dict] = []

    def allocate_capital(self, active_portfolio: dict[str, Any] | None = None) -> dict[str, Any]:
        """根据治理输出的策略组合生成资金分配方案。

        Args:
            active_portfolio: StrategyGovernanceEngine.select_active_portfolio() 输出

        Returns:
            CapitalAllocation: {strategy_allocations, cash_reserve, risk_budget, exposure_pct, ...}
        """
        if not active_portfolio or not active_portfolio.get("strategies"):
            return {
                "total_capital": self.total_capital,
                "strategy_allocations": {},
                "cash_reserve": self.total_capital,
                "exposure_pct": 0.0,
                "risk_budget": 0.0,
                "top_strategy_weight": 0.0,
                "portfolio_concentration": 0.0,
                "constraints_satisfied": True,
            }

        strategies = active_portfolio.get("strategies", [])
        governance_weights = active_portfolio.get("weights", {})
        expected_drawdown = active_portfolio.get("expected_max_drawdown_pct", 5.0)

        # 基础权重分配
        raw_allocations: dict[str, float] = {}
        total_weight = 0.0
        for s in strategies:
            w = governance_weights.get(s, 0.0)
            raw_allocations[s] = w
            total_weight += w

        # 归一化
        if total_weight > 0:
            for s in raw_allocations:
                raw_allocations[s] /= total_weight

        # 风险调整因子
        for s in raw_allocations:
            risk_level = self._get_strategy_risk(s)
            adj = RISK_ADJUSTMENT.get(risk_level, 1.0)
            raw_allocations[s] *= adj

        # 重新归一化
        total_adj = sum(raw_allocations.values())
        if total_adj > 0:
            for s in raw_allocations:
                raw_allocations[s] /= total_adj

        # 集中度控制
        self._enforce_concentration(raw_allocations)

        # 回撤保护
        cash_reserve_pct = 0.1
        exposure_multiplier = 1.0
        if expected_drawdown > 15:
            exposure_multiplier = 0.5
            cash_reserve_pct = 0.35
        elif expected_drawdown > 10:
            exposure_multiplier = 0.7
            cash_reserve_pct = 0.20

        # 计算最终分配
        cash_reserve = round(self.total_capital * cash_reserve_pct, 2)
        investable_capital = self.total_capital - cash_reserve
        investable_capital *= exposure_multiplier

        strategy_allocations: dict[str, float] = {}
        for s, w in raw_allocations.items():
            strategy_allocations[s] = round(investable_capital * w, 2)

        actual_exposure = sum(strategy_allocations.values()) / self.total_capital if self.total_capital > 0 else 0.0
        cash_after = self.total_capital - sum(strategy_allocations.values())

        # 集中度计算
        sorted_weights = sorted(raw_allocations.values(), reverse=True)
        top1 = sorted_weights[0] if sorted_weights else 0.0
        top2 = sum(sorted_weights[:2]) if len(sorted_weights) >= 2 else top1
        top3 = sum(sorted_weights[:3]) if len(sorted_weights) >= 3 else top2

        epsilon = 1e-9
        constraints_ok = (
            top1 <= MAX_SINGLE_WEIGHT + epsilon
            and top2 <= MAX_TOP2_TOTAL + epsilon
            and top3 <= MAX_TOP3_TOTAL + epsilon
        )

        # 风险预算
        risk_budget = round(self.total_capital * (expected_drawdown / 100) * 0.5, 2)

        result = {
            "total_capital": self.total_capital,
            "strategy_allocations": strategy_allocations,
            "cash_reserve": round(cash_after, 2),
            "exposure_pct": round(actual_exposure, 2),
            "risk_budget": risk_budget,
            "top_strategy_weight": round(top1, 4),
            "portfolio_concentration": round(top3, 4),
            "constraints_satisfied": constraints_ok,
        }

        self._allocation_history.append({"timestamp": datetime.now().isoformat(), **result})

        self._save_report(result)
        return result

    def rebalance_portfolio(self, market_state: dict[str, Any] | None = None) -> dict[str, Any]:
        """动态再平衡。

        Args:
            market_state: 市场状态信息（可选）

        Returns:
            再平衡后的分配方案
        """
        now = date.today()
        if self.last_rebalance and (now - self.last_rebalance).days < REBALANCE_INTERVAL_DAYS:
            return {"rebalanced": False, "reason": f"距上次再平衡不足{REBALANCE_INTERVAL_DAYS}天", "allocation": None}

        self.last_rebalance = now
        portfolio = {"strategies": ["momentum_v2", "defensive_v1", "ai_alpha_v3"],
                     "weights": {"momentum_v2": 0.4, "defensive_v1": 0.35, "ai_alpha_v3": 0.25},
                     "expected_max_drawdown_pct": 8.0}
        allocation = self.allocate_capital(portfolio)
        return {"rebalanced": True, "reason": "定期再平衡", "allocation": allocation}

    def _enforce_concentration(self, weights: dict[str, float]) -> None:
        """强制集中度限制。直接对所有策略进行硬限制，不归一化（剩余部分视为现金分配）。"""
        n = len(weights)
        if n <= 1:
            return

        # 先硬限制每个单一策略
        for s in list(weights.keys()):
            if weights[s] > MAX_SINGLE_WEIGHT:
                weights[s] = MAX_SINGLE_WEIGHT

        # 硬限制 Top N 合计
        sorted_w = sorted(weights.items(), key=lambda x: -x[1])
        if n >= 2:
            top2 = sorted_w[:2]
            t2 = sum(v for _, v in top2)
            if t2 > MAX_TOP2_TOTAL:
                r = MAX_TOP2_TOTAL / t2
                for s, _ in top2:
                    weights[s] = round(weights[s] * r, 6)

        sorted_w = sorted(weights.items(), key=lambda x: -x[1])
        if n >= 3:
            top3 = sorted_w[:3]
            t3 = sum(v for _, v in top3)
            if t3 > MAX_TOP3_TOTAL:
                r = MAX_TOP3_TOTAL / t3
                for s, _ in top3:
                    weights[s] = round(weights[s] * r, 6)

    def _get_strategy_risk(self, strategy_id: str) -> str:
        """获取策略风险等级。"""
        risk_map = {"momentum": "MEDIUM", "defensive": "LOW", "breakout": "HIGH", "mean_reversion": "MEDIUM"}
        for key, risk in risk_map.items():
            if key in strategy_id.lower():
                return risk
        return "MEDIUM"

    def _save_report(self, allocation: dict) -> None:
        """保存报告到JSON。"""
        today = date.today().isoformat().replace("-", "")
        reports_dir = Path(__file__).parent.parent.parent / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_file = reports_dir / f"capital_allocation_{today}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(allocation, f, ensure_ascii=False, indent=2)

    def get_allocation_summary(self) -> dict[str, Any]:
        """获取分配摘要。"""
        if not self._allocation_history:
            return {"status": "no_allocation", "message": "尚未运行资金分配"}
        return self._allocation_history[-1]
