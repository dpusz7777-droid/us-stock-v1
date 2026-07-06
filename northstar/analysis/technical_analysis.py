#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""K线技术分析模块。

功能
----
1. 获取最近 60 个交易日 OHLCV 数据
2. 计算 MA5 / MA20 / MA60
3. 计算 RSI14
4. 计算成交量相对 20 日均量的倍数
5. 计算近 20 日高低点
6. 判断技术状态：强势/修复/震荡/弱势/破位
7. 生成技术风险等级
"""

from __future__ import annotations

import logging
import sys
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger("technical_analysis")


@dataclass
class TechnicalIndicators:
    """单只股票的技术指标汇总。"""
    symbol: str
    company_cn: str = ""
    current_price: float = 0.0
    change_pct_today: float = 0.0

    # 均线
    ma5: float | None = None
    ma20: float | None = None
    ma60: float | None = None

    # 均线位置
    above_ma20: bool = False  # 是否站上 MA20
    above_ma60: bool = False  # 是否站上 MA60

    # RSI
    rsi14: float | None = None

    # 成交量
    volume_ratio: float | None = None  # 当日量 / 20日均量

    # 20日高低点
    high_20d: float | None = None
    low_20d: float | None = None

    # 5日、20日涨跌
    change_pct_5d: float | None = None
    change_pct_20d: float | None = None

    # 技术状态判定
    tech_status: str = "中性"   # 强势/修复/震荡/弱势/破位
    tech_risk: str = "中"       # 低/中/高

    # 综合评分
    opportunity_score: float = 50.0  # 0-100
    risk_score: float = 50.0
    trend_score: float = 50.0
    final_score: float = 50.0

    # 中文分析总结（约200字）
    analysis_summary: str = ""


def fetch_technical_data(symbols: list[str]) -> dict[str, TechnicalIndicators]:
    """获取 25 支股票的技术指标数据。

    通过 yfinance 获取最近 60 个交易日 OHLCV 数据，计算所有指标。
    """
    import pandas as pd
    import numpy as np
    from northstar.reports.daily_decision_report import COMPANY_NAMES

    from price_provider import YFinancePriceProvider

    # 应用代理
    from northstar.config.network import apply_proxy_environment
    apply_proxy_environment()

    provider = YFinancePriceProvider()
    result: dict[str, TechnicalIndicators] = {}

    for symbol in symbols:
        sym = symbol.strip().upper()
        ti = TechnicalIndicators(symbol=sym, company_cn=COMPANY_NAMES.get(sym, sym))

        try:
            tf = provider._get_ticker_factory()
            ticker = tf(sym)

            # 获取最近 60 个交易日数据
            hist = ticker.history(period="3mo", interval="1d")
            if hist is None or hist.empty:
                logger.warning("无法获取 %s 历史K线数据", sym)
                result[sym] = ti
                continue

            closes = hist["Close"].dropna().values.astype(float)
            highs = hist["High"].dropna().values.astype(float) if "High" in hist else closes
            lows = hist["Low"].dropna().values.astype(float) if "Low" in hist else closes
            volumes = hist["Volume"].dropna().values.astype(float) if "Volume" in hist else None

            if len(closes) == 0:
                result[sym] = ti
                continue

            # 当前价格
            ti.current_price = float(closes[-1])

            # 今日涨跌幅
            if len(closes) >= 2:
                prev_close = float(closes[-2])
                if prev_close > 0:
                    ti.change_pct_today = round((ti.current_price - prev_close) / prev_close * 100, 2)

            # 5日涨跌
            if len(closes) >= 5:
                old_5 = float(closes[-5])
                ti.change_pct_5d = round((ti.current_price - old_5) / old_5 * 100, 2)

            # 20日涨跌
            if len(closes) >= 20:
                old_20 = float(closes[-20])
                ti.change_pct_20d = round((ti.current_price - old_20) / old_20 * 100, 2)

            # MA5
            if len(closes) >= 5:
                ti.ma5 = round(float(np.mean(closes[-5:])), 2)

            # MA20
            if len(closes) >= 20:
                ti.ma20 = round(float(np.mean(closes[-20:])), 2)
                ti.above_ma20 = ti.current_price > ti.ma20

            # MA60
            if len(closes) >= 60:
                ti.ma60 = round(float(np.mean(closes[-60:])), 2)
                ti.above_ma60 = ti.current_price > ti.ma60
            elif len(closes) >= 20:
                ti.ma60 = round(float(np.mean(closes[-20:])), 2)

            # RSI14
            if len(closes) >= 15:
                ti.rsi14 = round(_calc_rsi(closes, 14), 1)

            # 成交量
            if volumes is not None and len(volumes) >= 21:
                vol_current = float(volumes[-1])
                vol_ma20 = float(np.mean(volumes[-21:-1]))
                if vol_ma20 > 0:
                    ti.volume_ratio = round(vol_current / vol_ma20, 2)

            # 近 20 日高低点
            if len(closes) >= 20:
                ti.high_20d = round(float(np.max(closes[-20:])), 2)
                ti.low_20d = round(float(np.min(closes[-20:])), 2)
            else:
                ti.high_20d = round(float(np.max(closes)), 2)
                ti.low_20d = round(float(np.min(closes)), 2)

            # 技术状态判定
            ti.tech_status = _judge_tech_status(ti)
            ti.tech_risk = _judge_tech_risk(ti)

            # 综合评分
            scores = _compute_scores(ti)
            ti.opportunity_score = scores["opportunity"]
            ti.risk_score = scores["risk"]
            ti.trend_score = scores["trend"]
            ti.final_score = scores["final"]

            # 中文分析总结
            ti.analysis_summary = _generate_analysis(ti)

        except Exception as exc:
            logger.debug("获取 %s 技术数据异常: %s", sym, exc)

        result[sym] = ti

    return result


def _calc_rsi(closes: np.ndarray, period: int = 14) -> float:
    """计算 RSI 指标。"""
    import numpy as np
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _judge_tech_status(ti: TechnicalIndicators) -> str:
    """根据技术指标判断技术状态。"""
    score = 0
    if ti.above_ma20:
        score += 2
    if ti.above_ma60:
        score += 2
    if ti.ma5 and ti.ma20 and ti.ma5 > ti.ma20:
        score += 1  # 短期均线在长期之上
    if ti.rsi14 is not None:
        if 40 <= ti.rsi14 <= 60:
            score += 1
        elif ti.rsi14 > 70:
            score -= 1  # 过热
        elif ti.rsi14 < 30:
            score -= 2  # 过弱
    if ti.volume_ratio and ti.volume_ratio > 1.5 and ti.change_pct_today > 0:
        score += 1  # 放量上涨
    if ti.change_pct_20d is not None:
        if ti.change_pct_20d > 10:
            score += 2
        elif ti.change_pct_20d < -10:
            score -= 2

    if score >= 5:
        return "强势"
    if score >= 3:
        return "修复"
    if score >= 1:
        return "震荡"
    if score >= -1:
        return "弱势"
    return "破位"


def _judge_tech_risk(ti: TechnicalIndicators) -> str:
    """根据技术指标判断技术风险。"""
    risk = 0
    if ti.tech_status in ("弱势", "破位"):
        risk += 2
    if ti.change_pct_20d is not None and ti.change_pct_20d < -15:
        risk += 2
    if ti.rsi14 is not None and ti.rsi14 > 80:
        risk += 2  # 严重过热
    if ti.volume_ratio and ti.volume_ratio > 3 and ti.change_pct_today < 0:
        risk += 1  # 放量下跌
    if ti.change_pct_5d is not None and ti.change_pct_5d < -8:
        risk += 1

    if risk >= 3:
        return "高"
    if risk >= 1:
        return "中"
    return "低"


def _compute_scores(ti: TechnicalIndicators) -> dict[str, float]:
    """计算机会分、风险分、趋势分、综合分。"""
    opp = 50.0
    risk = 50.0
    trend = 50.0

    # 趋势加分
    if ti.above_ma20:
        trend += 15
    if ti.above_ma60:
        trend += 10
    if ti.change_pct_5d is not None:
        trend += max(-20, min(20, ti.change_pct_5d))
    if ti.rsi14 is not None:
        if 40 <= ti.rsi14 <= 60:
            trend += 5

    # 机会分
    opp = trend * 0.6 + 20
    if ti.volume_ratio and ti.volume_ratio > 1.2 and ti.change_pct_today > 0:
        opp += 10
    if ti.tech_status == "强势":
        opp += 10
    elif ti.tech_status in ("弱势", "破位"):
        opp -= 15
    if ti.above_ma20:
        opp += 5
    opp = max(0, min(100, round(opp, 1)))

    # 风险分
    risk = 100 - trend * 0.5 + 10
    if ti.rsi14 is not None and ti.rsi14 > 75:
        risk += 15
    if ti.change_pct_20d is not None and ti.change_pct_20d < -15:
        risk += 15
    if ti.volume_ratio and ti.volume_ratio > 2 and ti.change_pct_today < 0:
        risk += 10
    if ti.tech_status in ("弱势", "破位"):
        risk += 10
    risk = max(0, min(100, round(risk, 1)))

    # 综合分 = 机会分 - 风险分权重
    final = max(0, min(100, round(opp * 0.6 - risk * 0.2 + trend * 0.2, 1)))

    return {"opportunity": opp, "risk": risk, "trend": round(trend, 1), "final": final}


def _generate_analysis(ti: TechnicalIndicators) -> str:
    """生成约 200 字的中文分析总结。"""
    parts: list[str] = []
    sym = ti.symbol
    name = ti.company_cn or sym

    # 开头
    status_map = {"强势": "处于强势上涨通道", "修复": "正在修复阶段",
                  "震荡": "处于震荡整理区间", "弱势": "处于弱势下跌趋势",
                  "破位": "已破位下行"}
    status_cn = status_map.get(ti.tech_status, "走势不明")
    parts.append(f"{name}({sym})当前{status_cn}")

    # 价格位置
    if ti.above_ma20 and ti.above_ma60:
        parts.append("，成功站上 MA20 和 MA60，短期和中期均线支撑良好")
    elif ti.above_ma20:
        parts.append("，站上 MA20 但仍在 MA60 下方，中期趋势有待确认")
    elif ti.ma20 and ti.current_price < ti.ma20 * 0.95:
        parts.append(f"，明显跌破 MA20，近 20 日均线压力较大")
    else:
        parts.append("，均线系统方向不明，需等待选择方向")

    # RSI
    if ti.rsi14 is not None:
        if ti.rsi14 > 70:
            parts.append(f"，RSI14 为 {ti.rsi14}，处于超买区域，短线追高风险较大")
        elif ti.rsi14 < 30:
            parts.append(f"，RSI14 为 {ti.rsi14}，处于超卖区域，存在技术性反弹可能")
        else:
            parts.append(f"，RSI14 为 {ti.rsi14}，处于中性区间")

    # 成交量
    if ti.volume_ratio is not None:
        if ti.volume_ratio > 1.5 and ti.change_pct_today > 0:
            parts.append(f"，今日成交量放大至 20 日均量的 {ti.volume_ratio} 倍，量价配合良好")
        elif ti.volume_ratio > 1.5 and ti.change_pct_today < 0:
            parts.append(f"，今日放量下跌，成交量达 {ti.volume_ratio} 倍，抛压较大")
        elif ti.volume_ratio < 0.7:
            parts.append("，成交量萎缩，市场关注度下降")
        else:
            parts.append("，成交量正常")

    # 20日高低点
    if ti.high_20d and ti.low_20d and ti.high_20d > ti.low_20d:
        pos_ratio = (ti.current_price - ti.low_20d) / (ti.high_20d - ti.low_20d) * 100
        if pos_ratio > 80:
            parts.append(f"，价格处于近 20 日高位区域（{pos_ratio:.0f}%分位）")
        elif pos_ratio < 20:
            parts.append(f"，价格处于近 20 日低位区域（{pos_ratio:.0f}%分位），关注能否企稳反弹")
        else:
            parts.append(f"，价格在近 20 日区间中位震荡（{pos_ratio:.0f}%分位）")

    # 5日、20日趋势
    if ti.change_pct_5d is not None:
        if ti.change_pct_5d > 5:
            parts.append(f"，近 5 日涨幅 {ti.change_pct_5d:+.1f}%，短线动能较强")
        elif ti.change_pct_5d < -5:
            parts.append(f"，近 5 日跌幅 {ti.change_pct_5d:.1f}%，短线承压")

    # 结论
    if ti.tech_status == "强势":
        parts.append("。综合来看，技术面偏强，可继续持有或关注加仓机会。")
    elif ti.tech_status == "修复":
        parts.append("。技术面正在改善中，建议保持观察，确认趋势后再操作。")
    elif ti.tech_status == "震荡":
        parts.append("。短期方向不明，建议耐心等待突破信号，不宜追涨杀跌。")
    elif ti.tech_status == "弱势":
        parts.append("。技术面偏弱，建议控制仓位，暂不急于抄底。")
    elif ti.tech_status == "破位":
        parts.append("。技术面明显破位，风险较大，建议暂时回避。")

    return "".join(parts)