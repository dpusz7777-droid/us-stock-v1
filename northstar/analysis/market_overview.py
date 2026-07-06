#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大盘环境分析模块。

获取 SPY/QQQ/DIA/IWM/VIX 等大盘指数数据，
计算大盘涨跌幅、5/20/60日趋势、均线位置、市场风险等级。
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger("market_overview")

# 大盘指数 ETF 列表
INDEX_SYMBOLS = ["SPY", "QQQ", "DIA", "IWM", "VIX"]

INDEX_NAMES = {
    "SPY": "标普500 ETF",
    "QQQ": "纳斯达克100 ETF",
    "DIA": "道琼斯 ETF",
    "IWM": "罗素2000 ETF",
    "VIX": "波动率指数",
}


@dataclass
class IndexData:
    """大盘指数数据。"""
    symbol: str
    name: str = ""
    current_price: float = 0.0
    change_pct_today: float = 0.0
    change_pct_5d: float | None = None
    change_pct_20d: float | None = None
    ma20: float | None = None
    ma60: float | None = None
    above_ma20: bool = False
    above_ma60: bool = False
    tech_status: str = "中性"


def fetch_market_overview() -> dict[str, IndexData]:
    """获取大盘指数数据和技术分析。"""
    from northstar.config.network import apply_proxy_environment
    from price_provider import YFinancePriceProvider

    apply_proxy_environment()
    provider = YFinancePriceProvider()

    import numpy as np

    result: dict[str, IndexData] = {}

    for sym in INDEX_SYMBOLS:
        idx = IndexData(symbol=sym, name=INDEX_NAMES.get(sym, sym))
        try:
            tf = provider._get_ticker_factory()
            ticker = tf(sym)
            hist = ticker.history(period="3mo", interval="1d")

            if hist is None or hist.empty:
                result[sym] = idx
                continue

            closes = hist["Close"].dropna().values.astype(float)
            if len(closes) == 0:
                result[sym] = idx
                continue

            idx.current_price = float(closes[-1])
            if len(closes) >= 2:
                prev = float(closes[-2])
                if prev > 0:
                    idx.change_pct_today = round((idx.current_price - prev) / prev * 100, 2)
            if len(closes) >= 5:
                old5 = float(closes[-5])
                idx.change_pct_5d = round((idx.current_price - old5) / old5 * 100, 2)
            if len(closes) >= 20:
                old20 = float(closes[-20])
                idx.change_pct_20d = round((idx.current_price - old20) / old20 * 100, 2)
                idx.ma20 = round(float(np.mean(closes[-20:])), 2)
                idx.above_ma20 = idx.current_price > idx.ma20
            if len(closes) >= 60:
                idx.ma60 = round(float(np.mean(closes[-60:])), 2)
                idx.above_ma60 = idx.current_price > idx.ma60
                # 技术状态
                score = 0
                if idx.above_ma20: score += 2
                if idx.above_ma60: score += 2
                if idx.change_pct_20d and idx.change_pct_20d > 5: score += 1
                elif idx.change_pct_20d and idx.change_pct_20d < -5: score -= 1
                if score >= 3: idx.tech_status = "强势"
                elif score >= 1: idx.tech_status = "震荡"
                else: idx.tech_status = "弱势"
        except Exception as exc:
            logger.debug("获取 %s 大盘数据异常: %s", sym, exc)

        result[sym] = idx

    return result


def generate_market_analysis_text(index_data: dict[str, IndexData]) -> str:
    """生成 300 字以上的中文大盘环境分析。"""
    parts: list[str] = []

    spy = index_data.get("SPY")
    qqq = index_data.get("QQQ")
    dia = index_data.get("DIA")
    iwm = index_data.get("IWM")
    vix = index_data.get("VIX")

    # SPY 分析
    if spy and spy.current_price > 0:
        spy_status = "强势上涨" if spy.tech_status == "强势" else ("震荡整理" if spy.tech_status == "震荡" else "弱势下行")
        above_str = ""
        if spy.above_ma20 and spy.above_ma60:
            above_str = "成功站上 MA20 和 MA60，多头排列良好"
        elif spy.above_ma20:
            above_str = "站上 MA20 但 MA60 上方仍有压力"
        elif spy.ma20 and spy.ma60:
            above_str = "位于 MA20 和 MA60 下方，短期承压"
        else:
            above_str = "均线系统待观察"

        parts.append(f"标普500(SPY)当前 ${spy.current_price:.2f}，今日涨跌 {spy.change_pct_today:+.1f}%，{spy_status}，{above_str}。")

        if spy.change_pct_20d is not None:
            parts.append(f"近 20 日累计涨跌 {spy.change_pct_20d:+.1f}%")

    # QQQ
    if qqq and qqq.current_price > 0:
        parts.append(f"纳斯达克100(QQQ) ${qqq.current_price:.2f}，今日 {qqq.change_pct_today:+.1f}%，5 日 {qqq.change_pct_5d:+.1f}%。")
        above_parts = []
        if qqq.above_ma20:
            above_parts.append("站上 MA20")
        if qqq.above_ma60:
            above_parts.append("站上 MA60")
        if above_parts:
            parts.append("科技板块目前" + "，".join(above_parts) + "，")
        if qqq.tech_status == "强势":
            parts.append("科技股整体偏强，对成长股构成利好支撑。")
        elif qqq.tech_status == "弱势":
            parts.append("科技股承压，高估值成长股面临调整压力，操作上需偏谨慎。")

    # DIA 道琼斯
    if dia and dia.current_price > 0:
        if dia.change_pct_today > 1:
            parts.append(f"道琼斯(DIA)今日上涨 {dia.change_pct_today:+.1f}%，传统蓝筹板块表现稳健。")
        elif dia.change_pct_today < -1:
            parts.append(f"道琼斯(DIA)今日下跌 {dia.change_pct_today:.1f}%，传统蓝筹承压。")

    # IWM 小盘股
    if iwm and iwm.current_price > 0:
        if iwm.change_pct_today > 0.5:
            parts.append(f"罗素2000(IWM)上涨 {iwm.change_pct_today:+.1f}%，小盘股情绪回暖。")
        elif iwm.change_pct_today < -0.5:
            parts.append(f"罗素2000(IWM)下跌 {iwm.change_pct_today:.1f}%，小盘股整体偏弱，市场风险偏好不高。")

    # VIX 波动率
    if vix and vix.current_price > 0:
        if vix.current_price > 25:
            parts.append(f"VIX 波动率指数位于 {vix.current_price:.1f}，市场恐慌情绪较高，注意风险控制。")
        elif vix.current_price > 18:
            parts.append(f"VIX 波动率指数 {vix.current_price:.1f}，市场情绪中性偏谨慎。")
        else:
            parts.append(f"VIX 波动率指数 {vix.current_price:.1f}，市场情绪相对平稳。")

    # 市场风险等级
    risk_level = _assess_market_risk(index_data)
    parts.append(f"综合来看，当前市场风险等级为【{risk_level}】。")

    if risk_level == "高":
        parts.append("建议控制仓位在 5 成以下，以防守为主，耐心等待市场企稳信号。")
    elif risk_level == "中":
        parts.append("建议仓位控制在 5-7 成，精选个股，关注强势板块的补跌风险。")
    else:
        parts.append("市场环境较好，可适度积极操作，但仍需注意个股分化风险。")

    parts.append("以上分析基于技术面数据，不构成投资建议。")

    result = "【大盘环境】" + "".join(parts)
    if len(result) < 300:
        result += "当前市场整体缺乏明显的单边趋势信号，建议以精选个股为主，控制整体仓位暴露。"

    return result


def _assess_market_risk(index_data: dict[str, IndexData]) -> str:
    """评估市场整体风险等级。"""
    spy = index_data.get("SPY")
    vix = index_data.get("VIX")
    risk_score = 0

    if spy:
        if spy.tech_status == "弱势":
            risk_score += 2
        elif spy.tech_status == "震荡":
            risk_score += 1
        if spy.change_pct_20d and spy.change_pct_20d < -5:
            risk_score += 1

    if vix and vix.current_price > 0:
        if vix.current_price > 25:
            risk_score += 2
        elif vix.current_price > 18:
            risk_score += 1

    if risk_score >= 3:
        return "高"
    if risk_score >= 1:
        return "中"
    return "低"