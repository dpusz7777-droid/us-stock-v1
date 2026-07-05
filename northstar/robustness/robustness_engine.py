#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""策略稳健性验证系统 — 评估策略在不同市场环境、不同股票池下的稳定性表现。

用法：
    from northstar.robustness.robustness_engine import run_robustness_analysis
    report = run_robustness_analysis()
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

REGIME_PRICE_DATA = {
    "bull": {
        "SPY": [500.0, 510.0, 520.0, 530.0, 540.0],
        "QQQ": [400.0, 410.0, 420.0, 430.0, 440.0],
        "NVDA": [800.0, 840.0, 880.0, 920.0, 960.0],
        "MSFT": [300.0, 310.0, 320.0, 330.0, 340.0],
        "META": [200.0, 210.0, 220.0, 230.0, 240.0],
        "AMD": [150.0, 155.0, 160.0, 165.0, 170.0],
        "TSM": [100.0, 105.0, 110.0, 115.0, 120.0],
        "AVGO": [500.0, 520.0, 540.0, 560.0, 580.0],
        "PLTR": [50.0, 53.0, 56.0, 59.0, 62.0],
        "CRM": [200.0, 210.0, 220.0, 230.0, 240.0],
        "XLE": [80.0, 82.0, 84.0, 86.0, 88.0],
        "AAPL": [180.0, 185.0, 190.0, 195.0, 200.0],
        "AMZN": [150.0, 155.0, 160.0, 165.0, 170.0],
        "GOOG": [140.0, 145.0, 150.0, 155.0, 160.0],
        "TSLA": [250.0, 260.0, 270.0, 280.0, 290.0],
    },
    "bear": {
        "SPY": [540.0, 530.0, 520.0, 510.0, 500.0],
        "QQQ": [440.0, 430.0, 420.0, 410.0, 400.0],
        "NVDA": [960.0, 920.0, 880.0, 840.0, 800.0],
        "MSFT": [340.0, 330.0, 320.0, 310.0, 300.0],
        "META": [240.0, 230.0, 220.0, 210.0, 200.0],
        "AMD": [170.0, 165.0, 160.0, 155.0, 150.0],
        "TSM": [120.0, 115.0, 110.0, 105.0, 100.0],
        "AVGO": [580.0, 560.0, 540.0, 520.0, 500.0],
        "PLTR": [62.0, 59.0, 56.0, 53.0, 50.0],
        "CRM": [240.0, 230.0, 220.0, 210.0, 200.0],
        "XLE": [88.0, 86.0, 84.0, 82.0, 80.0],
        "AAPL": [200.0, 195.0, 190.0, 185.0, 180.0],
        "AMZN": [170.0, 165.0, 160.0, 155.0, 150.0],
        "GOOG": [160.0, 155.0, 150.0, 145.0, 140.0],
        "TSLA": [290.0, 280.0, 270.0, 260.0, 250.0],
    },
    "sideways": {
        "SPY": [510.0, 515.0, 510.0, 515.0, 510.0],
        "QQQ": [410.0, 415.0, 410.0, 415.0, 410.0],
        "NVDA": [820.0, 830.0, 820.0, 830.0, 820.0],
        "MSFT": [310.0, 315.0, 310.0, 315.0, 310.0],
        "META": [210.0, 215.0, 210.0, 215.0, 210.0],
        "AMD": [155.0, 158.0, 155.0, 158.0, 155.0],
        "TSM": [105.0, 108.0, 105.0, 108.0, 105.0],
        "AVGO": [510.0, 520.0, 510.0, 520.0, 510.0],
        "PLTR": [52.0, 53.0, 52.0, 53.0, 52.0],
        "CRM": [210.0, 215.0, 210.0, 215.0, 210.0],
        "XLE": [82.0, 83.0, 82.0, 83.0, 82.0],
        "AAPL": [185.0, 188.0, 185.0, 188.0, 185.0],
        "AMZN": [155.0, 158.0, 155.0, 158.0, 155.0],
        "GOOG": [145.0, 148.0, 145.0, 148.0, 145.0],
        "TSLA": [260.0, 265.0, 260.0, 265.0, 260.0],
    },
}

UNIVERSES = {
    "MEGA_CAP": ["NVDA", "MSFT", "AAPL", "META", "AMZN"],
    "AI_ONLY": ["NVDA", "AMD", "MSFT", "META"],
    "SEMI": ["NVDA", "AMD", "TSM", "AVGO"],
    "DIVERSIFIED": ["AAPL", "GOOG", "TSLA", "AMZN", "PLTR", "CRM", "XLE"],
}


def _backtest_on_data(symbols: list[str], price_data: dict) -> dict:
    """在指定数据和股票池上运行回测。"""
    from northstar.backtest.paper_trading_engine import PaperTradingEngine
    from northstar.ai.market_intelligence import build_market_summary
    from northstar.ai.stock_selector import generate_stock_signals

    filtered_prices = {k: v for k, v in price_data.items() if k in symbols or k in ("SPY", "QQQ")}
    market = build_market_summary(filtered_prices)
    signals = generate_stock_signals(market, symbols, filtered_prices)
    engine = PaperTradingEngine(initial_capital=100000.0)
    engine.execute_signals(signals, filtered_prices)
    return engine.get_report()


def _classify_regime(spy_prices: list[float]) -> str:
    """根据SPY价格判断市场状态。"""
    if len(spy_prices) < 2:
        return "unknown"
    first = spy_prices[0]
    last = spy_prices[-1]
    if first > 0:
        change = (last - first) / first * 100
        if change > 1:
            return "bull"
        if change < -1:
            return "bear"
    return "sideways"


def run_regime_test(price_data: dict) -> dict[str, dict]:
    """在bull/bear/sideways三种环境下分别回测。"""
    results = {}
    for regime in ("bull", "bear", "sideways"):
        data = price_data.get(regime, REGIME_PRICE_DATA[regime])
        spy = data.get("SPY", [500.0])
        actual_regime = _classify_regime(spy)
        symbols = list(data.keys())
        report = _backtest_on_data(symbols, data)
        results[actual_regime] = {
            "return_pct": report.get("total_return_pct", 0.0),
            "win_rate": report.get("win_rate", 0.0),
            "max_drawdown_pct": report.get("max_drawdown_pct", 0.0),
            "trade_count": report.get("total_closed_trades", 0),
        }
    return results


def run_universe_test(price_data: dict) -> dict[str, dict]:
    """在不同股票池分别回测。"""
    results = {}
    for name, symbols in UNIVERSES.items():
        report = _backtest_on_data(symbols, price_data.get("bull", REGIME_PRICE_DATA["bull"]))
        results[name] = {
            "return_pct": report.get("total_return_pct", 0.0),
            "win_rate": report.get("win_rate", 0.0),
            "max_drawdown_pct": report.get("max_drawdown_pct", 0.0),
            "trade_count": report.get("total_closed_trades", 0),
        }
    return results


def calculate_stability_score(regime_perf: dict) -> float:
    """计算策略稳定性评分 (0-100)。"""
    returns = [v["return_pct"] for v in regime_perf.values() if v.get("trade_count", 0) > 0]
    if not returns:
        return 0.0

    avg_ret = sum(returns) / len(returns)
    variance = sum((r - avg_ret) ** 2 for r in returns) / len(returns) if len(returns) > 1 else 0.0
    volatility = variance ** 0.5

    # 收益差异越小越好
    stability = 100.0 - volatility * 10

    # 在任何市场不崩溃加分
    for r in returns:
        if r < -10:
            stability -= 20

    return round(max(0.0, min(100.0, stability)), 2)


def calculate_overfitting_score(regime_perf: dict) -> float:
    """计算过拟合评分 (0-100, 越低越好)。"""
    bull = regime_perf.get("bull", {})
    bear = regime_perf.get("bear", {})
    bull_ret = bull.get("return_pct", 0.0)
    bear_ret = bear.get("return_pct", 0.0)

    # 牛市很强但熊市崩溃 → 高过拟合
    if bull_ret > 5 and bear_ret < -3:
        return round(min((bull_ret - bear_ret) * 3, 100.0), 2)

    # 所有市场表现一致 → 低过拟合
    returns = [v["return_pct"] for v in regime_perf.values() if v.get("trade_count", 0) > 0]
    if returns:
        spread = max(returns) - min(returns)
        if spread < 3:
            return 10.0

    return 40.0  # 默认中等过拟合


def run_robustness_analysis() -> dict[str, Any]:
    """运行完整稳健性分析。"""
    regime_perf = run_regime_test(REGIME_PRICE_DATA)
    universe_perf = run_universe_test(REGIME_PRICE_DATA)
    stability = calculate_stability_score(regime_perf)
    overfitting = calculate_overfitting_score(regime_perf)

    worst_regime = min(regime_perf, key=lambda k: regime_perf[k]["return_pct"])
    best_regime = max(regime_perf, key=lambda k: regime_perf[k]["return_pct"])

    result = {
        "regime_performance": regime_perf,
        "universe_performance": universe_perf,
        "stability_score": stability,
        "overfitting_score": overfitting,
        "worst_regime": worst_regime,
        "best_regime": best_regime,
    }

    today = date.today().isoformat().replace("-", "")
    reports_dir = Path(__file__).parent.parent.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_file = reports_dir / f"robustness_report_{today}.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result