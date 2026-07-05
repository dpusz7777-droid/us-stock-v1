#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI选股系统 — 基于市场洞察和价格数据的股票信号生成。

用法：
    from northstar.ai.stock_selector import generate_stock_signals
    signals = generate_stock_signals(market, watchlist, price_data)
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


def _compute_5d_change(symbol: str, price_data: dict) -> float:
    """计算单只股票5日涨跌幅。"""
    prices = price_data.get(symbol, [])
    if len(prices) < 2:
        return 0.0
    first = prices[0]
    last = prices[-1]
    if first and last and first > 0:
        return round((last - first) / first * 100, 2)
    return 0.0


def _is_consecutive_decline(symbol: str, price_data: dict) -> bool:
    """检查是否连续下跌。"""
    prices = price_data.get(symbol, [])
    if len(prices) < 3:
        return False
    declines = 0
    for i in range(1, len(prices)):
        if prices[i] < prices[i - 1]:
            declines += 1
    return declines >= 3


def generate_stock_signals(
    market: dict[str, Any],
    watchlist: list[str],
    price_data: dict[str, list[float]],
) -> list[dict[str, Any]]:
    """生成股票交易信号。

    Args:
        market: build_market_summary() 的输出
        watchlist: 关注的股票列表
        price_data: 价格数据 {symbol: [price_day1, ..., price_day5]}

    Returns:
        list[StockSignal]: [{"symbol": str, "signal": str, "confidence": float, "reason": str, "expected_horizon": str}]
    """
    sector_strength = market.get("sector_strength", {})
    risk_level = market.get("risk_level", "medium")
    market_trend = market.get("market_trend", "neutral")

    # 构建股票到行业的映射
    symbol_to_sector = {}
    for sector, symbols in {
        "ai": ["NVDA", "MSFT", "META"],
        "semiconductors": ["AMD", "TSM", "AVGO"],
        "software": ["PLTR", "CRM"],
        "energy": ["XLE"],
    }.items():
        for sym in symbols:
            symbol_to_sector[sym] = sector

    signals = []
    for symbol in watchlist:
        sector = symbol_to_sector.get(symbol, "unknown")
        sector_str = sector_strength.get(sector, 0.0)
        change_5d = _compute_5d_change(symbol, price_data)
        is_declining = _is_consecutive_decline(symbol, price_data)
        is_high_risk = risk_level == "high"

        # BUY条件: sector_strength > 0.5 AND 5日涨幅 > 2% AND 非高风险
        if sector_str > 0.5 and change_5d > 2.0 and not is_high_risk:
            signal = "BUY"
            confidence = round(min(abs(sector_str) / 5 + abs(change_5d) / 10, 0.95), 2)
            reason = f"{sector}板块走强(强度{sector_str:.1f})，{symbol}5日涨{change_5d:+.1f}%"
            horizon = "short_term"

        # AVOID条件: sector_strength < -0.2 OR 连续下跌 OR 高波动市场
        elif sector_str < -0.2 or is_declining or is_high_risk:
            signal = "AVOID"
            confidence = round(min(abs(sector_str) / 3 + (0.3 if is_declining else 0.0), 0.9), 2)
            reasons = []
            if sector_str < -0.2:
                reasons.append(f"{sector}板块偏弱(强度{sector_str:.1f})")
            if is_declining:
                reasons.append(f"{symbol}连续下跌")
            if is_high_risk:
                reasons.append("市场风险高")
            reason = "，".join(reasons)
            horizon = "unknown"

        # WATCH条件: 其他情况
        else:
            signal = "WATCH"
            confidence = round(max(abs(sector_str) / 10 + abs(change_5d) / 20, 0.3), 2)
            if sector_str > -0.2 and sector_str < 0.5:
                reason = f"{sector}板块趋势不明朗(强度{sector_str:.1f})，继续观察"
            else:
                reason = f"{symbol}5日涨{change_5d:+.1f}%，等待明确信号"
            horizon = "medium_term"

        signals.append({
            "symbol": symbol,
            "signal": signal,
            "confidence": confidence,
            "reason": reason,
            "expected_horizon": horizon,
        })

    # 输出到文件
    today = date.today().isoformat()
    reports_dir = Path(__file__).parent.parent.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_file = reports_dir / f"stock_signals_{today.replace('-', '')}.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump({"date": today, "signals": signals}, f, ensure_ascii=False, indent=2)

    return signals