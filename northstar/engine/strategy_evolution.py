#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""策略进化引擎 — 基于绩效归因结果自动调整、生成、淘汰策略权重。

用法：
    from northstar.engine.strategy_evolution import run_strategy_evolution
    result = run_strategy_evolution(performance_attribution)
"""

from __future__ import annotations

from typing import Any


DEFAULT_WEIGHTS = {
    "momentum": 0.25,
    "breakout": 0.15,
    "mean_reversion": 0.20,
    "defensive": 0.25,
    "reversal": 0.15,
}


def _compute_strategy_updates(
    strategy_attr: dict[str, dict],
    current_weights: dict[str, float],
) -> dict[str, dict]:
    """基于归因结果计算每个策略的更新动作。"""
    updates: dict[str, dict] = {}
    for st, data in strategy_attr.items():
        wr = data.get("win_rate", 0.0)
        tc = data.get("trade_count", 0)
        tr = data.get("total_return", 0.0)
        current_w = current_weights.get(st, 0.1)

        if tc < 2:
            updates[st] = {"action": "maintain", "weight_change": 0.0, "reason": "insufficient data"}
            continue

        if wr >= 0.6:
            change = round(min(current_w * 0.3, 0.10), 2)
            updates[st] = {"action": "increase", "weight_change": change, "reason": f"high win_rate {wr} across regimes"}
        elif wr <= 0.3:
            change = round(-min(current_w * 0.3, 0.08), 2)
            updates[st] = {"action": "decrease", "weight_change": change, "reason": f"low win_rate {wr} across regimes"}
        else:
            updates[st] = {"action": "maintain", "weight_change": 0.0, "reason": f"neutral win_rate {wr}"}
    return updates


def _compute_new_strategies(
    strategy_attr: dict[str, dict],
    regime_attr: dict[str, dict],
) -> list[dict]:
    """基于归因数据生成新的策略变体。"""
    new_strategies = []
    for st, data in strategy_attr.items():
        wr = data.get("win_rate", 0.0)
        tc = data.get("trade_count", 0)
        if wr >= 0.55 and tc >= 3:
            new_strategies.append({
                "name": f"{st}_regime_aware_v2",
                "base": st,
                "modifiers": ["regime_filter", "volatility_cap"],
            })
    for rg, data in regime_attr.items():
        acc = data.get("accuracy", 0.0)
        tc = data.get("trade_count", 0)
        if acc >= 0.7 and tc >= 3 and rg != "unknown":
            # 如果某个 regime 表现特别好，建议针对它的新策略
            strat_name = f"regime_{rg}_optimized"
            if not any(s["name"] == strat_name for s in new_strategies):
                new_strategies.append({
                    "name": strat_name,
                    "base": "adaptive",
                    "modifiers": [f"{rg}_filter", "dynamic_sizing"],
                })
    return new_strategies


def _compute_deprecated_strategies(
    strategy_attr: dict[str, dict],
    regime_attr: dict[str, dict],
) -> list[dict]:
    """识别应该淘汰的策略。"""
    deprecated = []
    for st, data in strategy_attr.items():
        wr = data.get("win_rate", 0.0)
        tc = data.get("trade_count", 0)
        tr = data.get("total_return", 0.0)
        if tc >= 3 and wr < 0.3 and tr < 0:
            deprecated.append({
                "name": st,
                "reason": f"low win_rate {wr} + negative return {tr}",
            })
    # 检查 regime 表现
    worst_regime_wr = None
    for rg, data in regime_attr.items():
        acc = data.get("accuracy", 0.0)
        tc = data.get("trade_count", 0)
        if tc >= 2 and acc < 0.25:
            if worst_regime_wr is None or acc < worst_regime_wr:
                worst_regime_wr = acc
    return deprecated


def _compute_weight_vector(
    updates: dict[str, dict],
    current_weights: dict[str, float],
) -> dict[str, float]:
    """基于更新计算新的权重向量，确保总和 ≈ 1。"""
    new_weights = dict(current_weights)
    for st, update in updates.items():
        if st in new_weights:
            new_weights[st] = max(0.0, new_weights[st] + update["weight_change"])
        else:
            new_weights[st] = max(0.0, 0.1 + update["weight_change"])

    # 归一化到总和 ≈ 1
    total = sum(new_weights.values())
    if total > 0:
        new_weights = {k: round(v / total, 2) for k, v in new_weights.items()}
    return new_weights


def _generate_evolution_log(
    updates: dict[str, dict],
    deprecated: list[dict],
    new_strategies: list[dict],
) -> list[str]:
    """生成演化日志。"""
    log = []
    for st, update in updates.items():
        if update["action"] == "increase":
            log.append(f"increased {st} allocation due to {update['reason']}")
        elif update["action"] == "decrease":
            log.append(f"reduced {st} allocation due to {update['reason']}")
    for d in deprecated:
        log.append(f"deprecated {d['name']} strategy: {d['reason']}")
    for ns in new_strategies:
        log.append(f"generated new strategy {ns['name']} from {ns['base']}")
    if not log:
        log.append("no strategic changes needed")
    return log


def run_strategy_evolution(
    performance_attribution: dict | None = None,
    current_weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """策略进化引擎。

    Args:
        performance_attribution: v46 run_performance_attribution() 的输出
        current_weights: 当前策略权重字典，不传则使用默认权重

    Returns:
        {
            "strategy_updates": dict,
            "new_strategies": list,
            "deprecated_strategies": list,
            "weight_vector": dict,
            "evolution_log": list,
        }
    """
    empty_result: dict[str, Any] = {
        "strategy_updates": {},
        "new_strategies": [],
        "deprecated_strategies": [],
        "weight_vector": dict(DEFAULT_WEIGHTS),
        "evolution_log": ["insufficient data for evolution"],
    }

    if not performance_attribution:
        return empty_result

    strategy_attr = performance_attribution.get("strategy_attribution", {})
    regime_attr = performance_attribution.get("regime_attribution", {})
    weights = current_weights if current_weights else dict(DEFAULT_WEIGHTS)

    if not strategy_attr:
        return empty_result

    # 计算策略更新
    updates = _compute_strategy_updates(strategy_attr, weights)

    # 生成新策略
    new_strategies = _compute_new_strategies(strategy_attr, regime_attr)

    # 识别淘汰策略
    deprecated = _compute_deprecated_strategies(strategy_attr, regime_attr)

    # 计算新权重向量
    weight_vector = _compute_weight_vector(updates, weights)

    # 生成日志
    evolution_log = _generate_evolution_log(updates, deprecated, new_strategies)

    return {
        "strategy_updates": updates,
        "new_strategies": new_strategies,
        "deprecated_strategies": deprecated,
        "weight_vector": weight_vector,
        "evolution_log": evolution_log,
    }