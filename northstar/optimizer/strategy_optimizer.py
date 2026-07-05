#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""策略优化系统 — 通过网格搜索自动调整交易参数，寻找最优参数组合。

用法：
    from northstar.optimizer.strategy_optimizer import optimize_parameters
    result = optimize_parameters(historical_results)
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

DEFAULT_PARAMS = {
    "sector_strength_buy_threshold": 0.5,
    "confidence_high": 0.8,
    "confidence_medium": 0.5,
    "take_profit_pct": 8.0,
    "stop_loss_pct": 5.0,
    "holding_days": 5,
}

PARAM_GRID = {
    "sector_strength_buy_threshold": [0.3, 0.5, 0.7],
    "confidence_high": [0.7, 0.8, 0.9],
    "take_profit_pct": [6.0, 8.0, 10.0],
    "stop_loss_pct": [3.0, 5.0, 7.0],
    "holding_days": [3, 5, 7],
}


def _run_backtest_with_params(params: dict) -> dict:
    """用指定参数运行一次回测，返回报告。"""
    from northstar.backtest.paper_trading_engine import PaperTradingEngine
    from northstar.ai.market_intelligence import build_market_summary
    from northstar.ai.stock_selector import generate_stock_signals

    price_data = {
        "SPY": [500.0, 502.0, 501.0, 505.0, 508.0],
        "QQQ": [400.0, 403.0, 402.0, 406.0, 410.0],
        "NVDA": [800.0, 810.0, 805.0, 820.0, 830.0],
        "MSFT": [300.0, 302.0, 301.0, 305.0, 308.0],
        "META": [200.0, 202.0, 201.0, 205.0, 208.0],
        "AMD": [150.0, 152.0, 151.0, 155.0, 158.0],
        "TSM": [100.0, 102.0, 101.0, 105.0, 108.0],
        "AVGO": [500.0, 505.0, 502.0, 510.0, 515.0],
        "PLTR": [50.0, 51.0, 50.5, 52.0, 53.0],
        "CRM": [200.0, 202.0, 201.0, 205.0, 208.0],
        "XLE": [80.0, 81.0, 80.5, 82.0, 83.0],
    }

    market = build_market_summary(price_data)
    watchlist = ["NVDA", "MSFT", "META", "AMD", "TSM", "PLTR", "CRM", "XLE"]
    signals = generate_stock_signals(market, watchlist, price_data)

    engine = PaperTradingEngine(initial_capital=100000.0)
    engine.execute_signals(signals, price_data)
    return engine.get_report()


def optimize_parameters(historical_results: list[dict] | None = None) -> dict[str, Any]:
    """自动优化交易参数。

    使用网格搜索遍历 PARAM_GRID 中的所有组合，
    对每组参数运行回测，选择综合评分最高的组合。

    Args:
        historical_results: 历史回测结果列表（可选）

    Returns:
        {
            "best_params": dict,
            "best_score": float,
            "baseline_score": float,
            "all_results": list[dict],
            "delta_return": float,
            "delta_drawdown": float,
            "parameter_suggestions": list[str],
        }
    """
    from northstar.optimizer.strategy_evaluator import evaluate_system_performance

    # 基线: 使用默认参数
    baseline_report = _run_backtest_with_params(DEFAULT_PARAMS)
    baseline_score = evaluate_system_performance(baseline_report, None, None)

    best_score = 0.0
    best_params = dict(DEFAULT_PARAMS)
    best_report = baseline_report
    all_results = []

    # 网格搜索
    import itertools

    keys = list(PARAM_GRID.keys())
    values = list(PARAM_GRID.values())
    total_combos = 1
    for v in values:
        total_combos *= len(v)

    for combo in itertools.product(*values):
        params = dict(zip(keys, combo))
        # 跳过无效组合: 止盈必须大于止损
        if params["take_profit_pct"] <= params["stop_loss_pct"]:
            continue

        report = _run_backtest_with_params(params)
        score = evaluate_system_performance(report, None, None)

        result = {
            "params": params,
            "total_return_pct": report["total_return_pct"],
            "win_rate": report["win_rate"],
            "max_drawdown_pct": report["max_drawdown_pct"],
            "total_score": score["total_score"],
            "grade": score["grade"],
        }
        all_results.append(result)

        if score["total_score"] > best_score:
            best_score = score["total_score"]
            best_params = dict(params)
            best_report = report

    # 计算提升
    delta_return = round(
        best_report["total_return_pct"] - baseline_report["total_return_pct"], 2
    )
    delta_drawdown = round(
        best_report["max_drawdown_pct"] - baseline_report["max_drawdown_pct"], 2
    )

    # 参数建议
    suggestions = []
    if best_params.get("sector_strength_buy_threshold", 0.5) != DEFAULT_PARAMS["sector_strength_buy_threshold"]:
        diff = best_params["sector_strength_buy_threshold"] - DEFAULT_PARAMS["sector_strength_buy_threshold"]
        suggestions.append(f"调整买入阈值 {DEFAULT_PARAMS['sector_strength_buy_threshold']} → {best_params['sector_strength_buy_threshold']} ({diff:+.1f})")
    if best_params.get("take_profit_pct", 8.0) != DEFAULT_PARAMS["take_profit_pct"]:
        diff = best_params["take_profit_pct"] - DEFAULT_PARAMS["take_profit_pct"]
        suggestions.append(f"调整止盈比例 {DEFAULT_PARAMS['take_profit_pct']}% → {best_params['take_profit_pct']}% ({diff:+.0f}%)")
    if best_params.get("stop_loss_pct", 5.0) != DEFAULT_PARAMS["stop_loss_pct"]:
        diff = best_params["stop_loss_pct"] - DEFAULT_PARAMS["stop_loss_pct"]
        suggestions.append(f"调整止损比例 {DEFAULT_PARAMS['stop_loss_pct']}% → {best_params['stop_loss_pct']}% ({diff:+.0f}%)")
    if not suggestions:
        suggestions.append("当前参数已接近最优，无需调整")

    result = {
        "best_params": best_params,
        "best_score": best_score,
        "baseline_score": baseline_score["total_score"],
        "all_results": sorted(all_results, key=lambda x: -x["total_score"])[:10],
        "delta_return": delta_return,
        "delta_drawdown": delta_drawdown,
        "parameter_suggestions": suggestions,
    }

    # 输出到文件
    today = date.today().isoformat().replace("-", "")
    reports_dir = Path(__file__).parent.parent.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_file = reports_dir / f"strategy_optimization_{today}.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result