#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Walk-Forward验证系统 — 通过时间滚动验证策略在不同时间段的稳定性。

用法：
    from northstar.ensemble.walkforward_engine import run_walkforward_test
    result = run_walkforward_test()
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

TRAIN_WINDOW = 30
TEST_WINDOW = 7
ROLLING_STEP = 7


def _slice_data(data: dict, start_idx: int, end_idx: int) -> dict:
    """从价格数据中截取一个窗口。"""
    sliced = {}
    for symbol, prices in data.items():
        if start_idx < len(prices):
            sliced[symbol] = prices[start_idx:min(end_idx, len(prices))]
    return sliced


def _backtest_on_window(price_data: dict, symbols: list[str]) -> dict:
    """在指定数据窗口上运行回测。"""
    from northstar.backtest.paper_trading_engine import PaperTradingEngine
    from northstar.ai.market_intelligence import build_market_summary
    from northstar.ai.stock_selector import generate_stock_signals

    filtered = {k: v for k, v in price_data.items() if k in symbols or k in ("SPY", "QQQ")}
    market = build_market_summary(filtered)
    signals_list = generate_stock_signals(market, symbols, filtered)
    engine = PaperTradingEngine(initial_capital=100000.0)
    engine.execute_signals(signals_list, filtered)
    return engine.get_report()


def _generate_walkforward_price_data(total_days: int = 60) -> dict:
    """生成长周期的模拟价格数据用于walk-forward测试。"""
    base = {
        "SPY": 500.0, "QQQ": 400.0, "NVDA": 800.0, "MSFT": 300.0,
        "META": 200.0, "AMD": 150.0, "TSM": 100.0, "AVGO": 500.0,
        "PLTR": 50.0, "CRM": 200.0, "XLE": 80.0, "AAPL": 180.0,
        "AMZN": 150.0, "GOOG": 140.0, "TSLA": 250.0,
    }
    price_data: dict[str, list[float]] = {}
    for symbol, start in base.items():
        prices = []
        for day in range(total_days):
            # 模拟周期性波动：先涨后跌再震荡
            cycle = (day % 20) / 20.0
            if cycle < 0.33:
                factor = 1 + cycle * 0.06  # 涨
            elif cycle < 0.66:
                factor = 1 + (0.33 - (cycle - 0.33)) * 0.06  # 跌
            else:
                factor = 1.0 + (cycle - 0.66) * 0.01  # 震荡
            prices.append(round(start * factor, 2))
        price_data[symbol] = prices
    return price_data


def run_walkforward_test() -> dict[str, Any]:
    """运行Walk-Forward时间滚动验证。

    时间切片规则：
    - train_window = 30天
    - test_window = 7天
    - rolling_step = 7天

    Returns:
        {
            "windows": list[dict],
            "overall_return": float,
            "time_consistency_score": float,
            "performance_decay": float,
            "regime_dependency": str,
            "best_window": int,
            "worst_window": int,
        }
    """
    price_data = _generate_walkforward_price_data(60)
    symbols = ["NVDA", "MSFT", "META", "AMD", "TSM", "PLTR", "CRM", "XLE", "AAPL", "AMZN", "GOOG", "TSLA"]

    windows = []
    num_days = len(price_data.get("SPY", []))
    start = 0

    while start + TRAIN_WINDOW + TEST_WINDOW <= num_days:
        train_end = start + TRAIN_WINDOW
        test_end = train_end + TEST_WINDOW

        # Training window (前30天)
        train_data = _slice_data(price_data, start, train_end)
        train_report = _backtest_on_window(train_data, symbols)

        # Test window (后7天)
        test_data = _slice_data(price_data, train_end, test_end)
        test_report = _backtest_on_window(test_data, symbols)

        windows.append({
            "window_id": len(windows) + 1,
            "train_start_day": start,
            "train_end_day": train_end,
            "test_start_day": train_end,
            "test_end_day": test_end,
            "train_return_pct": train_report.get("total_return_pct", 0.0),
            "train_win_rate": train_report.get("win_rate", 0.0),
            "test_return_pct": test_report.get("total_return_pct", 0.0),
            "test_win_rate": test_report.get("win_rate", 0.0),
            "test_max_drawdown": test_report.get("max_drawdown_pct", 0.0),
        })

        start += ROLLING_STEP

    if not windows:
        return {
            "windows": [], "overall_return": 0.0, "time_consistency_score": 0.0,
            "performance_decay": 0.0, "regime_dependency": "insufficient_data",
            "best_window": 0, "worst_window": 0,
        }

    # 综合统计
    test_returns = [w["test_return_pct"] for w in windows]
    overall_return = round(sum(test_returns) / len(test_returns), 2)

    # 时间一致性评分
    avg_ret = sum(test_returns) / len(test_returns)
    variance = sum((r - avg_ret) ** 2 for r in test_returns) / len(test_returns) if len(test_returns) > 1 else 0.0
    vol = variance ** 0.5
    time_consistency_score = round(max(0.0, min(100.0, 100.0 - vol * 5)), 2)

    # 性能衰减（后期 vs 前期）
    half = len(windows) // 2
    early_avg = sum(w["test_return_pct"] for w in windows[:half]) / max(half, 1)
    late_avg = sum(w["test_return_pct"] for w in windows[half:]) / max(len(windows) - half, 1)
    performance_decay = round(max(0.0, (early_avg - late_avg) / max(abs(early_avg), 0.01) * 100), 2) if early_avg != 0 else 0.0

    # 市场依赖判断
    all_positive = all(r >= 0 for r in test_returns)
    all_negative = all(r <= 0 for r in test_returns)
    if all_positive:
        regime_dependency = "all-weather"
    elif all_negative:
        regime_dependency = "bull-only dependent"
    else:
        regime_dependency = "bear-resistant"

    best = max(windows, key=lambda w: w["test_return_pct"])
    worst = min(windows, key=lambda w: w["test_return_pct"])

    result = {
        "windows": windows,
        "overall_return": overall_return,
        "time_consistency_score": time_consistency_score,
        "performance_decay": performance_decay,
        "regime_dependency": regime_dependency,
        "best_window": best["window_id"],
        "worst_window": worst["window_id"],
    }

    today = date.today().isoformat().replace("-", "")
    reports_dir = Path(__file__).parent.parent.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_file = reports_dir / f"walkforward_report_{today}.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result