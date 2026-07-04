#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""策略治理层 — 防止系统过度进化、策略漂移和过拟合。

用法：
    from northstar.engine.strategy_governance import run_strategy_governance
    result = run_strategy_governance(evolution_result, performance_attribution)
"""

from __future__ import annotations

from typing import Any

# 锁定策略：核心策略不受进化影响
LOCKED_STRATEGIES = {"defensive", "mean_reversion"}

# 最大单次变化限制
MAX_WEIGHT_CHANGE = 0.05
MAX_CHANGES_PER_CYCLE = 2
STABILITY_HISTORY_LIMIT = 10


def _identify_locked_strategies(
    strategy_attr: dict[str, dict],
) -> list[dict[str, str]]:
    """识别应锁定的策略（core + stable）。"""
    locked = []
    for st in LOCKED_STRATEGIES:
        locked.append({"strategy": st, "reason": "core strategy locked due to stable performance"})
    for st, data in strategy_attr.items():
        wr = data.get("win_rate", 0.0)
        tc = data.get("trade_count", 0)
        if st not in LOCKED_STRATEGIES and wr >= 0.65 and tc >= 5:
            locked.append({"strategy": st, "reason": f"consistently high win_rate {wr}"})
    return locked


def _identify_restricted_evolution(
    strategy_attr: dict[str, dict],
    strategy_updates: dict[str, dict],
) -> list[dict[str, str]]:
    """识别应限制进化的策略。"""
    restricted = []
    for st, data in strategy_attr.items():
        wr = data.get("win_rate", 0.0)
        tc = data.get("trade_count", 0)
        vol = abs(data.get("total_return", 0.0)) / max(tc, 1)
        if tc >= 3 and vol > 3.0 and wr < 0.5:
            restricted.append({
                "strategy": st,
                "restriction": "max weight change capped at 0.02",
                "reason": f"high volatility in attribution (avg_abs_return {vol:.1f})",
            })
        elif tc >= 3 and st in strategy_updates:
            update = strategy_updates[st]
            if abs(update.get("weight_change", 0)) > MAX_WEIGHT_CHANGE:
                restricted.append({
                    "strategy": st,
                    "restriction": f"weight change capped at {MAX_WEIGHT_CHANGE}",
                    "reason": "exceeded maximum allowed change",
                })
    return restricted


def _compute_evolution_rate_limit(
    strategy_updates: dict[str, dict],
    locked: list[dict],
    restricted: list[dict],
) -> dict[str, Any]:
    """计算进化速率限制。"""
    locked_names = {s["strategy"] for s in locked}
    restricted_names = {s["strategy"] for s in restricted}

    actual_changes = 0
    for st, update in strategy_updates.items():
        if st in locked_names:
            continue
        if st in restricted_names:
            continue
        if update["action"] in ("increase", "decrease"):
            actual_changes += 1

    throttled = actual_changes > MAX_CHANGES_PER_CYCLE
    return {
        "max_changes_per_cycle": MAX_CHANGES_PER_CYCLE,
        "current_changes": actual_changes,
        "throttled": throttled,
    }


def _compute_stability_score(
    strategy_attr: dict[str, dict],
    strategy_updates: dict[str, dict],
) -> float:
    """计算系统稳定性分数。"""
    if not strategy_attr:
        return 1.0

    scores = []
    for st, data in strategy_attr.items():
        wr = data.get("win_rate", 0.0)
        tc = data.get("trade_count", 0)
        if tc >= 3:
            # 稳定性评分 = win_rate * trade_count_factor
            tc_factor = min(tc / 10, 1.0)
            scores.append(wr * tc_factor)

    if not scores:
        return 0.5

    base_stability = sum(scores) / len(scores)

    # 如果有大幅调整，降低稳定性
    change_penalty = 0.0
    for st, update in strategy_updates.items():
        if abs(update.get("weight_change", 0)) > 0.03:
            change_penalty += 0.05

    return round(max(0.0, min(1.0, base_stability - change_penalty)), 2)


def _detect_drift(
    strategy_updates: dict[str, dict],
    evolution_rate: dict[str, Any],
    stability_score: float,
) -> dict[str, Any]:
    """检测策略漂移。"""
    is_drifting = False
    reasons = []

    if evolution_rate.get("throttled", False):
        is_drifting = True
        reasons.append("rapid weight oscillation detected")

    if stability_score < 0.3:
        is_drifting = True
        reasons.append("system stability critically low")

    # 检查是否有频繁的增减交替
    actions = [u["action"] for u in strategy_updates.values()]
    increase_count = actions.count("increase")
    decrease_count = actions.count("decrease")
    if increase_count >= 3 and decrease_count >= 3:
        is_drifting = True
        reasons.append("opposing adjustments detected across strategies")

    return {
        "is_drifting": is_drifting,
        "drift_reason": "; ".join(reasons) if reasons else "no drift detected",
    }


def _compute_system_status(
    stability_score: float,
    drift: dict[str, Any],
    evolution_rate: dict[str, Any],
) -> str:
    """计算系统状态。"""
    if drift.get("is_drifting", False) and stability_score < 0.3:
        return "unstable"
    if drift.get("is_drifting", False):
        return "warning"
    if evolution_rate.get("throttled", False):
        return "warning"
    return "stable"


def run_strategy_governance(
    evolution_result: dict | None = None,
    performance_attribution: dict | None = None,
) -> dict[str, Any]:
    """策略治理层。

    Args:
        evolution_result: v47 run_strategy_evolution() 的输出
        performance_attribution: v46 run_performance_attribution() 的输出

    Returns:
        {
            "locked_strategies": list,
            "restricted_evolution": list,
            "evolution_rate_limit": dict,
            "stability_score": float,
            "drift_detection": dict,
            "system_status": str,
        }
    """
    empty_result: dict[str, Any] = {
        "locked_strategies": [{"strategy": s, "reason": "core strategy locked due to stable performance"} for s in LOCKED_STRATEGIES],
        "restricted_evolution": [],
        "evolution_rate_limit": {"max_changes_per_cycle": MAX_CHANGES_PER_CYCLE, "current_changes": 0, "throttled": False},
        "stability_score": 0.5,
        "drift_detection": {"is_drifting": False, "drift_reason": "no drift detected"},
        "system_status": "stable",
    }

    if not evolution_result and not performance_attribution:
        return empty_result

    strategy_attr = (performance_attribution or {}).get("strategy_attribution", {})
    strategy_updates = (evolution_result or {}).get("strategy_updates", {})

    # 识别锁定策略
    locked = _identify_locked_strategies(strategy_attr)

    # 识别限制策略
    restricted = _identify_restricted_evolution(strategy_attr, strategy_updates)

    # 进化速率限制
    rate_limit = _compute_evolution_rate_limit(strategy_updates, locked, restricted)

    # 稳定性评分
    stability = _compute_stability_score(strategy_attr, strategy_updates)

    # 漂移检测
    drift = _detect_drift(strategy_updates, rate_limit, stability)

    # 系统状态
    status = _compute_system_status(stability, drift, rate_limit)

    return {
        "locked_strategies": locked,
        "restricted_evolution": restricted,
        "evolution_rate_limit": rate_limit,
        "stability_score": stability,
        "drift_detection": drift,
        "system_status": status,
    }