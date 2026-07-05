#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""策略评分系统 — 对交易系统进行统一评分，评估收益能力、稳定性、胜率与风险控制。

用法：
    from northstar.optimizer.strategy_evaluator import evaluate_system_performance
    score = evaluate_system_performance(paper_trading_report, market_data, risk_metrics)
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


def _compute_return_score(total_return_pct: float, avg_return_pct: float) -> float:
    """计算收益能力评分 (权重40%)。"""
    scores = []
    # 总收益率评分 (0~50分)
    if total_return_pct > 20:
        scores.append(50)
    elif total_return_pct > 10:
        scores.append(40)
    elif total_return_pct > 5:
        scores.append(30)
    elif total_return_pct > 2:
        scores.append(20)
    elif total_return_pct > 0:
        scores.append(10)
    else:
        scores.append(0)

    # 平均每笔收益评分 (0~50分)
    if avg_return_pct > 5:
        scores.append(50)
    elif avg_return_pct > 3:
        scores.append(40)
    elif avg_return_pct > 1:
        scores.append(30)
    elif avg_return_pct > 0.5:
        scores.append(20)
    elif avg_return_pct > 0:
        scores.append(10)
    else:
        scores.append(0)

    return round(sum(scores) / 2, 1)


def _compute_stability_score(max_drawdown_pct: float) -> float:
    """计算稳定性评分 (权重25%)。"""
    if max_drawdown_pct == 0:
        return 100.0
    if max_drawdown_pct <= -3:
        return 80.0
    if max_drawdown_pct <= -5:
        return 60.0
    if max_drawdown_pct <= -10:
        return 40.0
    if max_drawdown_pct <= -15:
        return 20.0
    return 0.0


def _compute_win_rate_score(win_rate: float) -> float:
    """计算胜率评分 (权重20%)。"""
    if win_rate >= 0.8:
        return 100.0
    if win_rate >= 0.6:
        return 80.0
    if win_rate >= 0.5:
        return 60.0
    if win_rate >= 0.4:
        return 40.0
    if win_rate >= 0.3:
        return 20.0
    return 0.0


def _compute_risk_score(risk_metrics: dict | None) -> float:
    """计算风险控制评分 (权重15%)。"""
    if not risk_metrics:
        return 50.0

    scores = []
    # 风险等级评分 (0~40分)
    rl = risk_metrics.get("risk_level", "LOW")
    if rl == "LOW":
        scores.append(40)
    elif rl == "MEDIUM":
        scores.append(25)
    else:
        scores.append(10)

    # 仓位利用率评分 (0~30分)
    util = risk_metrics.get("position_utilization", 0.5)
    if 0.3 <= util <= 0.7:
        scores.append(30)
    elif 0.1 <= util <= 0.8:
        scores.append(20)
    else:
        scores.append(10)

    # 是否触发风控 (0~30分)
    can_trade = risk_metrics.get("can_trade_today", True)
    if can_trade:
        scores.append(30)
    else:
        scores.append(0)

    return round(sum(scores) / 3 * 100 / 100, 1)


def _compute_grade(total_score: float) -> str:
    """根据总分计算等级。"""
    if total_score >= 85:
        return "A"
    if total_score >= 70:
        return "B"
    if total_score >= 50:
        return "C"
    return "D"


def evaluate_system_performance(
    paper_trading_report: dict | None = None,
    market_data: dict | None = None,
    risk_metrics: dict | None = None,
) -> dict[str, Any]:
    """对交易系统进行统一评分。

    Args:
        paper_trading_report: PaperTradingEngine.get_report() 输出
        market_data: 市场数据（可选）
        risk_metrics: RiskManager.get_risk_metrics() 输出

    Returns:
        StrategyScore: {total_score, return_score, stability_score, win_rate_score, risk_score, grade}
    """
    if not paper_trading_report:
        return {
            "total_score": 0.0,
            "return_score": 0.0,
            "stability_score": 0.0,
            "win_rate_score": 0.0,
            "risk_score": 0.0,
            "grade": "D",
        }

    total_return = paper_trading_report.get("total_return_pct", 0.0)
    avg_return = paper_trading_report.get("avg_return_pct", 0.0)
    max_dd = paper_trading_report.get("max_drawdown_pct", 0.0)
    win_rate = paper_trading_report.get("win_rate", 0.0)

    # 各维度评分
    return_score = _compute_return_score(total_return, avg_return)
    stability_score = _compute_stability_score(-abs(max_dd))
    win_rate_score = _compute_win_rate_score(win_rate)
    risk_score = _compute_risk_score(risk_metrics)

    # 综合评分 (加权)
    total_score = round(
        return_score * 0.4
        + stability_score * 0.25
        + win_rate_score * 0.2
        + risk_score * 0.15,
        1,
    )

    grade = _compute_grade(total_score)

    result = {
        "total_score": total_score,
        "return_score": return_score,
        "stability_score": stability_score,
        "win_rate_score": win_rate_score,
        "risk_score": risk_score,
        "grade": grade,
    }

    # 输出到文件
    today = date.today().isoformat().replace("-", "")
    reports_dir = Path(__file__).parent.parent.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_file = reports_dir / f"strategy_evaluation_{today}.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result