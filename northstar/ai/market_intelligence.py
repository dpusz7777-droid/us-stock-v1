#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI市场洞察系统 — 基于规则的市场趋势分析、行业强度评估、风险等级判断。

用法：
    from northstar.ai.market_intelligence import build_market_summary
    summary = build_market_summary(price_data)
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


SPY_SYMBOLS = ["SPY", "QQQ"]

SECTOR_MAP = {
    "ai": ["NVDA", "MSFT", "META"],
    "semiconductors": ["AMD", "TSM", "AVGO"],
    "software": ["PLTR", "CRM"],
    "energy": ["XLE"],
}


def _compute_avg_change(symbols: list[str], price_data: dict) -> float:
    """计算一组股票5日平均涨跌幅。"""
    changes = []
    for sym in symbols:
        prices = price_data.get(sym, [])
        if len(prices) >= 2:
            first = prices[0]
            last = prices[-1]
            if first and last and first > 0:
                chg = (last - first) / first * 100
                changes.append(chg)
    return round(sum(changes) / len(changes), 2) if changes else 0.0


def _compute_volatility(symbols: list[str], price_data: dict) -> float:
    """计算一组股票的波动率（日收益率标准差）。"""
    returns = []
    for sym in symbols:
        prices = price_data.get(sym, [])
        for i in range(1, len(prices)):
            prev = prices[i - 1]
            curr = prices[i]
            if prev and prev > 0:
                r = (curr - prev) / prev
                returns.append(r)
    if len(returns) < 2:
        return 0.0
    avg = sum(returns) / len(returns)
    var = sum((r - avg) ** 2 for r in returns) / len(returns)
    return var ** 0.5


def build_market_summary(price_data: dict[str, list[float]]) -> dict[str, Any]:
    """构建市场洞察摘要。

    Args:
        price_data: 价格数据字典 {symbol: [price_day1, price_day2, ...]}，
                    最近5个交易日的收盘价

    Returns:
        MarketSummary: {
            "date": str,
            "market_trend": "bullish" | "bearish" | "neutral",
            "sector_strength": {"ai": float, "semiconductors": float, ...},
            "key_drivers": list[str],
            "risk_level": "low" | "medium" | "high",
        }
    """
    today = date.today().isoformat()

    # 市场趋势 (基于 SPY 和 QQQ 5日涨跌幅)
    spy_change = _compute_avg_change(SPY_SYMBOLS, price_data)
    if spy_change > 2.0:
        market_trend = "bullish"
    elif spy_change < -2.0:
        market_trend = "bearish"
    else:
        market_trend = "neutral"

    # 行业强度
    sector_strength = {}
    for sector, symbols in SECTOR_MAP.items():
        sector_strength[sector] = _compute_avg_change(symbols, price_data)

    # 波动率
    all_symbols = []
    for syms in SECTOR_MAP.values():
        all_symbols.extend(syms)
    all_symbols.extend(SPY_SYMBOLS)
    volatility = _compute_volatility(list(set(all_symbols)), price_data)

    # 风险等级
    if market_trend == "bearish" and volatility > 0.02:
        risk_level = "high"
    elif market_trend == "bullish" and volatility < 0.01:
        risk_level = "low"
    else:
        risk_level = "medium"

    # 关键驱动因素
    key_drivers = []
    for sym in SPY_SYMBOLS:
        prices = price_data.get(sym, [])
        if len(prices) >= 2:
            first = prices[0]
            last = prices[-1]
            if first and last and first > 0:
                chg = (last - first) / first * 100
                if sym == "SPY" and chg > 1:
                    key_drivers.append("标普500指数上涨，市场情绪积极")
                elif sym == "QQQ" and chg > 1:
                    key_drivers.append("科技股资金流入，纳斯达克走强")
                elif sym == "SPY" and chg < -1:
                    key_drivers.append("标普500指数下跌，市场承压")
                elif sym == "QQQ" and chg < -1:
                    key_drivers.append("科技板块资金流出，纳斯达克承压")

    # 行业驱动因素
    for sector, strength in sector_strength.items():
        if sector == "ai" and strength > 2:
            key_drivers.append("AI板块受NVDA带动强势上涨")
        elif sector == "semiconductors" and strength > 2:
            key_drivers.append("半导体板块走强，芯片周期回升")
        elif sector == "energy" and strength > 1:
            key_drivers.append("能源板块上涨，原油价格支撑")
        elif sector == "software" and strength > 2:
            key_drivers.append("软件服务板块表现活跃")
        elif sector == "ai" and strength < -2:
            key_drivers.append("AI板块回调，获利盘抛压")
        elif sector == "semiconductors" and strength < -2:
            key_drivers.append("半导体板块走弱，行业周期下行")

    if not key_drivers:
        key_drivers.append("市场缺乏明确方向，短期震荡整理")

    summary = {
        "date": today,
        "market_trend": market_trend,
        "sector_strength": sector_strength,
        "key_drivers": key_drivers,
        "risk_level": risk_level,
    }

    # 输出到文件
    reports_dir = Path(__file__).parent.parent.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_file = reports_dir / f"market_intelligence_{today.replace('-', '')}.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return summary