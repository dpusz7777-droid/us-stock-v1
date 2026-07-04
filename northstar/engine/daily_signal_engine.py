#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日交易信号系统 — 基于 v30-v50 生成每天可直接使用的交易信号报告。

用法：
    from northstar.engine.daily_signal_engine import generate_daily_signals
    report = generate_daily_signals(
        portfolio_state=pe.get_snapshot(),
        decision_history=dm.get_all(),
        performance_attribution=pa_result,
        market_regime="bull",
        strategy_evolution=ev_result,
        governance=gv_result,
    )
"""

from __future__ import annotations

from datetime import date
from typing import Any


def _compute_confidence(
    action: str,
    strategy_source: str,
    regime: str,
    strategy_attr: dict[str, dict],
    regime_attr: dict[str, dict],
    source_attr: dict[str, dict],
) -> float:
    """计算信号置信度 (0~1)。"""
    scores = []

    # 策略历史表现
    for st, data in strategy_attr.items():
        if st in strategy_source.lower() or strategy_source.lower().startswith(st):
            wr = data.get("win_rate", 0.0)
            scores.append(wr * 0.4)

    # 市场状态的 regime 准确率
    for rg, data in regime_attr.items():
        if rg == regime:
            acc = data.get("accuracy", 0.0)
            scores.append(acc * 0.3)

    # 来源质量
    for src, data in source_attr.items():
        if src in strategy_source.lower():
            qs = data.get("quality_score", 0.0)
            scores.append(qs * 0.3)

    if not scores:
        return 0.5
    return round(min(sum(scores) / len(scores) * 1.5, 1.0), 2)


def _compute_position_sizing(
    confidence: float,
    cash_ratio: float,
    risk_level: str,
) -> float:
    """计算仓位比例 (0~1)。"""
    base = confidence * 0.8
    if risk_level == "high":
        base *= 0.5
    elif risk_level == "medium":
        base *= 0.75
    # 现金比例限制
    base = min(base, cash_ratio)
    return round(base, 2)


def _compute_exposure(
    signals: list[dict],
    portfolio_state: dict | None,
) -> dict[str, float]:
    """计算行业/策略暴露度。"""
    exposure: dict[str, float] = {"cash": 0.0}
    cash = (portfolio_state or {}).get("cash", 0.0)
    total = (portfolio_state or {}).get("total_value", 1.0)
    if total > 0:
        exposure["cash"] = round(cash / total, 2)

    for signal in signals:
        src = signal.get("strategy_source", "unknown")
        size = signal.get("position_sizing", 0.0)
        if "momentum" in src or "breakout" in src:
            exposure["momentum"] = exposure.get("momentum", 0.0) + size
        elif "defensive" in src:
            exposure["defensive"] = exposure.get("defensive", 0.0) + size
        elif "mean_reversion" in src:
            exposure["mean_reversion"] = exposure.get("mean_reversion", 0.0) + size
        else:
            exposure["other"] = exposure.get("other", 0.0) + size
    return exposure


def _compute_risk_level(
    governance: dict | None,
    performance_attribution: dict | None,
) -> str:
    """计算组合风险等级。"""
    if governance:
        status = governance.get("system_status", "stable")
        if status == "unstable":
            return "high"
        if status == "warning":
            return "medium"
    if performance_attribution:
        score = performance_attribution.get("overall_system_score", 0.5)
        if score < 0.3:
            return "high"
        if score < 0.5:
            return "medium"
    return "low"


def _identify_top_risks(
    strategy_attr: dict[str, dict],
    regime: str,
) -> list[str]:
    """识别主要风险。"""
    risks = []
    for st, data in strategy_attr.items():
        wr = data.get("win_rate", 0.0)
        tc = data.get("trade_count", 0)
        if tc >= 2 and wr < 0.3:
            risks.append(f"{st} degradation in {regime} regime")
    if not risks:
        risks.append("no significant risk detected")
    return risks[:3]


def _identify_top_opportunities(
    strategy_attr: dict[str, dict],
    regime_attr: dict[str, dict],
) -> list[str]:
    """识别主要机会。"""
    opportunities = []
    for rg, data in regime_attr.items():
        acc = data.get("accuracy", 0.0)
        tc = data.get("trade_count", 0)
        if acc >= 0.6 and tc >= 3:
            opportunities.append(f"favorable conditions in {rg} regime")
    for st, data in strategy_attr.items():
        wr = data.get("win_rate", 0.0)
        tc = data.get("trade_count", 0)
        if wr >= 0.6 and tc >= 3:
            opportunities.append(f"{st} performing well across regimes")
    if not opportunities:
        opportunities.append("accumulating data for opportunity detection")
    return opportunities[:3]


def generate_daily_signals(
    portfolio_state: dict | None = None,
    decision_history: list[dict] | None = None,
    performance_attribution: dict | None = None,
    market_regime: str = "unknown",
    strategy_evolution: dict | None = None,
    governance: dict | None = None,
    available_symbols: list[str] | None = None,
) -> dict[str, Any]:
    """生成每日交易信号报告。

    Args:
        portfolio_state: v50 PortfolioEngine.get_snapshot() 输出
        decision_history: v45 DecisionMemory.get_all() 输出
        performance_attribution: v46 run_performance_attribution() 输出
        market_regime: v31 classify_market_regime() 结果
        strategy_evolution: v47 run_strategy_evolution() 输出
        governance: v48 run_strategy_governance() 输出
        available_symbols: 可选，关注的股票列表

    Returns:
        {
            "date": str,
            "signals": list[dict],
            "portfolio_summary": dict,
            "market_view": dict,
            "top_risks": list[str],
            "top_opportunities": list[str],
            "strategy_allocation": dict,
        }
    """
    today = date.today().isoformat()
    pa = performance_attribution or {}
    sv = strategy_evolution or {}

    strategy_attr = pa.get("strategy_attribution", {})
    regime_attr = pa.get("regime_attribution", {})
    source_attr = pa.get("source_attribution", {})
    weight_vector = sv.get("weight_vector", {})
    governance_status = governance.get("system_status", "stable") if governance else "stable"

    risk_level = _compute_risk_level(governance, pa)
    cash_ratio = 1.0
    if portfolio_state:
        total = portfolio_state.get("total_value", 1.0)
        cash = portfolio_state.get("cash", 0.0)
        cash_ratio = cash / total if total > 0 else 1.0

    # 生成信号
    signals = []
    symbols = available_symbols or ["NVDA", "AAPL", "MSFT", "GOOG", "TSLA", "AMZN", "META"]

    for symbol in symbols:
        # 检查已有持仓
        holding_qty = 0.0
        current_positions = (portfolio_state or {}).get("positions", [])
        for pos in current_positions:
            if pos.get("symbol") == symbol:
                holding_qty = pos.get("qty", 0.0)
                break

        # 选择最佳策略来源
        best_source = "momentum"
        best_wr = 0.0
        for st, data in strategy_attr.items():
            wr = data.get("win_rate", 0.0)
            if wr > best_wr:
                best_wr = wr
                base = {"momentum": "momentum", "defensive": "defensive", "breakout": "momentum", "mean_reversion": "mean_reversion"}.get(st, "momentum")
                best_source = f"{base}_regime_aware_v2" if wr >= 0.55 else base

        # 决定动作
        action = "HOLD"
        reason_parts = []
        if holding_qty > 0:
            # 已有持仓：检查是否该卖出
            for st, data in strategy_attr.items():
                if data.get("win_rate", 0.0) < 0.3 and data.get("trade_count", 0) >= 2:
                    action = "SELL"
                    reason_parts.append(f"{st} underperforming")
                    break
            if action == "HOLD":
                reason_parts.append(f"position maintained")
        else:
            # 无持仓：检查是否该买入
            for st, data in strategy_attr.items():
                wr = data.get("win_rate", 0.0)
                if wr >= 0.55 and data.get("trade_count", 0) >= 3:
                    action = "BUY"
                    best_source = base = {"momentum": "momentum", "defensive": "defensive", "breakout": "momentum", "mean_reversion": "mean_reversion"}.get(st, "momentum")
                    best_source = f"{base}_regime_aware_v2"
                    reason_parts.append(f"high win_rate {wr} in {market_regime}")
                    break

        if action == "HOLD" and not reason_parts:
            reason_parts.append(f"monitoring {symbol} for entry signals")

        confidence = _compute_confidence(action, best_source, market_regime, strategy_attr, regime_attr, source_attr)
        sizing = _compute_position_sizing(confidence, cash_ratio, risk_level)

        signals.append({
            "symbol": symbol,
            "action": action,
            "confidence": confidence,
            "position_sizing": sizing if action == "BUY" else 0.0,
            "strategy_source": best_source,
            "reason": "; ".join(reason_parts),
        })

    # 组合摘要
    exposure = _compute_exposure(signals, portfolio_state)
    portfolio_summary = {
        "risk_level": risk_level,
        "exposure": exposure,
    }

    # 市场观点
    regime_conf = 0.5
    for rg, data in regime_attr.items():
        if rg == market_regime:
            regime_conf = data.get("accuracy", 0.5)
            break
    market_view = {
        "regime": market_regime,
        "confidence": round(regime_conf, 2),
        "governance_status": governance_status,
    }

    # 风险与机会
    top_risks = _identify_top_risks(strategy_attr, market_regime)
    top_opportunities = _identify_top_opportunities(strategy_attr, regime_attr)

    # 策略分配
    strategy_allocation = weight_vector or {
        "momentum": 0.25,
        "defensive": 0.35,
        "mean_reversion": 0.20,
        "breakout": 0.10,
        "reversal": 0.10,
    }

    return {
        "date": today,
        "signals": signals,
        "portfolio_summary": portfolio_summary,
        "market_view": market_view,
        "top_risks": top_risks,
        "top_opportunities": top_opportunities,
        "strategy_allocation": strategy_allocation,
    }