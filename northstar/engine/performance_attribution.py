#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""绩效归因系统 — 分析什么策略赚钱、什么市场赚钱、什么来源最可靠。

用法：
    from northstar.engine.performance_attribution import run_performance_attribution
    result = run_performance_attribution(decision_log, backtest_results)
"""

from __future__ import annotations

from typing import Any


def _compute_strategy_attribution(decision_log: list[dict]) -> dict[str, dict]:
    """按策略类型归因。"""
    strategies: dict[str, dict] = {}
    for d in decision_log:
        st = d.get("strategy_type", "unknown") or "unknown"
        action = d.get("action", "HOLD")
        pnl = d.get("pnl")
        if st not in strategies:
            strategies[st] = {"total_return": 0.0, "win_rate": 0.0, "trade_count": 0, "wins": 0}
        if action == "HOLD":
            continue
        strategies[st]["trade_count"] += 1
        if pnl is not None:
            strategies[st]["total_return"] += pnl
            if pnl > 0:
                strategies[st]["wins"] += 1
    for st, data in strategies.items():
        if data["trade_count"] > 0:
            data["win_rate"] = round(data["wins"] / data["trade_count"], 2)
        data["total_return"] = round(data["total_return"], 2)
        del data["wins"]
    return strategies


def _compute_regime_attribution(decision_log: list[dict]) -> dict[str, dict]:
    """按市场状态归因。"""
    regimes: dict[str, dict] = {}
    for d in decision_log:
        rg = d.get("market_regime", "unknown") or "unknown"
        action = d.get("action", "HOLD")
        pnl = d.get("pnl")
        if rg not in regimes:
            regimes[rg] = {"return": 0.0, "accuracy": 0.0, "trade_count": 0, "correct": 0}
        if action == "HOLD":
            continue
        regimes[rg]["trade_count"] += 1
        if pnl is not None:
            regimes[rg]["return"] += pnl
            if pnl > 0:
                regimes[rg]["correct"] += 1
    for rg, data in regimes.items():
        if data["trade_count"] > 0:
            data["accuracy"] = round(data["correct"] / data["trade_count"], 2)
        data["return"] = round(data["return"], 2)
        del data["correct"]
    return regimes


def _compute_action_attribution(decision_log: list[dict]) -> dict[str, dict]:
    """按决策动作归因。"""
    actions: dict[str, dict] = {}
    for d in decision_log:
        action = d.get("action", "HOLD")
        pnl = d.get("pnl")
        if action not in actions:
            actions[action] = {"accuracy": 0.0, "avg_return": 0.0, "trade_count": 0, "correct": 0, "total_return": 0.0}
        if action == "HOLD":
            continue
        actions[action]["trade_count"] += 1
        if pnl is not None:
            actions[action]["total_return"] += pnl
            if pnl > 0:
                actions[action]["correct"] += 1
    for action, data in actions.items():
        if data["trade_count"] > 0:
            data["avg_return"] = round(data["total_return"] / data["trade_count"], 2)
            data["accuracy"] = round(data["correct"] / data["trade_count"], 2)
        del data["correct"]
        del data["total_return"]
    return actions


def _compute_source_attribution(decision_log: list[dict]) -> dict[str, dict]:
    """按决策来源归因。"""
    sources: dict[str, dict] = {}
    for d in decision_log:
        src = d.get("source", "unknown") or "unknown"
        action = d.get("action", "HOLD")
        pnl = d.get("pnl")
        if src not in sources:
            sources[src] = {"quality_score": 0.0, "trade_count": 0, "total_return": 0.0, "wins": 0}
        if action == "HOLD":
            continue
        sources[src]["trade_count"] += 1
        if pnl is not None:
            sources[src]["total_return"] += pnl
            if pnl > 0:
                sources[src]["wins"] += 1
    for src, data in sources.items():
        if data["trade_count"] > 0:
            # quality_score = win_rate * 0.6 + avg_return_norm * 0.4
            win_rate = data["wins"] / data["trade_count"]
            avg_ret = data["total_return"] / data["trade_count"]
            # Normalize avg_return to 0~1 range (cap at 20%)
            avg_ret_norm = min(max(avg_ret / 20, 0.0), 1.0)
            data["quality_score"] = round(win_rate * 0.6 + avg_ret_norm * 0.4, 2)
        del data["wins"]
        del data["total_return"]
    return sources


def _find_best_worst(data: dict[str, dict], key: str) -> tuple[str, str]:
    """从归因数据中找出最佳和最差项。"""
    filtered = {k: v for k, v in data.items() if v.get(key, 0) != 0 or v.get("trade_count", 0) > 0}
    if not filtered:
        return "unknown", "unknown"
    best = max(filtered, key=lambda k: filtered[k].get(key, 0))
    worst = min(filtered, key=lambda k: filtered[k].get(key, 0))
    return best, worst


def run_performance_attribution(
    decision_log: list[dict] | None = None,
    backtest_results: dict | None = None,
) -> dict[str, Any]:
    """绩效归因分析。

    Args:
        decision_log: 来自 v45 DecisionMemory.get_all() 的决策记录列表
        backtest_results: 来自 v44 run_backtest() 的回测结果

    Returns:
        {
            "strategy_attribution": dict,
            "regime_attribution": dict,
            "action_attribution": dict,
            "source_attribution": dict,
            "best_strategy": str,
            "worst_strategy": str,
            "best_regime": str,
            "overall_system_score": float,
        }
    """
    empty_result: dict[str, Any] = {
        "strategy_attribution": {},
        "regime_attribution": {},
        "action_attribution": {},
        "source_attribution": {},
        "best_strategy": "unknown",
        "worst_strategy": "unknown",
        "best_regime": "unknown",
        "overall_system_score": 0.0,
    }

    if not decision_log:
        return empty_result

    # 如果有 backtest_results，补齐 pnl
    if backtest_results and decision_log:
        pass  # 直接用 decision_log 中的 pnl

    strategy_attr = _compute_strategy_attribution(decision_log)
    regime_attr = _compute_regime_attribution(decision_log)
    action_attr = _compute_action_attribution(decision_log)
    source_attr = _compute_source_attribution(decision_log)

    best_strat, worst_strat = _find_best_worst(strategy_attr, "win_rate")
    best_reg, _ = _find_best_worst(regime_attr, "accuracy")

    # overall_system_score: 加权平均
    scores = []
    weights = []
    for st, data in strategy_attr.items():
        if data["win_rate"] > 0:
            scores.append(data["win_rate"])
            weights.append(data["trade_count"])
    if scores and weights:
        total_weight = sum(weights)
        overall = sum(s * w for s, w in zip(scores, weights)) / total_weight if total_weight > 0 else 0.0
    else:
        overall = 0.0

    return {
        "strategy_attribution": strategy_attr,
        "regime_attribution": regime_attr,
        "action_attribution": action_attr,
        "source_attribution": source_attr,
        "best_strategy": best_strat,
        "worst_strategy": worst_strat,
        "best_regime": best_reg,
        "overall_system_score": round(overall, 2),
    }