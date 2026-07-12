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

    # v2.1 做多可操作分：五个分项合计 100
    opportunity_score: float = 0.0
    risk_score: float = 50.0
    trend_score: float = 0.0
    momentum_score: float = 0.0
    technical_position_score: float = 0.0
    event_sentiment_score: float = 0.0
    user_context_score: float = 0.0
    long_actionability_score: float = 0.0
    final_score: float = 0.0  # 旧调用兼容别名
    action: str = "观察"
    data_complete: bool = False
    history_rows: int = 0
    data_source: str = "unavailable"
    failure_reason: str = ""

    # 中文分析总结（约200字）
    analysis_summary: str = ""


def fetch_technical_data(symbols: list[str]) -> dict[str, TechnicalIndicators]:
    """获取 25 支股票的技术指标数据。

    通过 yfinance 获取最近 60 个交易日 OHLCV 数据，计算所有指标。
    """
    import numpy as np
    from northstar.reports.daily_decision_report import COMPANY_NAMES
    from northstar.data.yahoo_chart_provider import fetch_chart_history
    result: dict[str, TechnicalIndicators] = {}

    for symbol in symbols:
        sym = symbol.strip().upper()
        ti = TechnicalIndicators(symbol=sym, company_cn=COMPANY_NAMES.get(sym, sym))

        try:
            hist = fetch_chart_history(sym, period="3mo", interval="1d")
            rows = [
                (close, high, low, volume)
                for close, high, low, volume in zip(hist.close, hist.high, hist.low, hist.volume)
                if close is not None and close > 0
            ]
            closes = np.array([row[0] for row in rows], dtype=float)
            highs = np.array([row[1] if row[1] is not None else row[0] for row in rows], dtype=float)
            lows = np.array([row[2] if row[2] is not None else row[0] for row in rows], dtype=float)
            volumes = np.array([row[3] if row[3] is not None else 0 for row in rows], dtype=float)
            ti.history_rows = len(closes)
            ti.data_source = hist.source

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
            ti.opportunity_score = scores["long_actionability"]
            ti.risk_score = scores["risk"]
            ti.trend_score = scores["trend"]
            ti.momentum_score = scores["momentum"]
            ti.technical_position_score = scores["technical_position"]
            ti.long_actionability_score = scores["long_actionability"]
            ti.final_score = ti.long_actionability_score

            # 中文分析总结
            ti.analysis_summary = _generate_analysis(ti)
            ti.data_complete = all([
                ti.current_price > 0, ti.history_rows >= 60,
                ti.ma5 is not None, ti.ma20 is not None, ti.ma60 is not None,
                ti.rsi14 is not None, ti.high_20d is not None, ti.low_20d is not None,
                ti.volume_ratio is not None,
            ])
            if not ti.data_complete:
                missing = [
                    name for name, value in {
                        "价格": ti.current_price > 0, "60日K线": ti.history_rows >= 60,
                        "MA5": ti.ma5 is not None, "MA20": ti.ma20 is not None,
                        "MA60": ti.ma60 is not None, "RSI14": ti.rsi14 is not None,
                        "20日高点": ti.high_20d is not None, "20日低点": ti.low_20d is not None,
                        "量比": ti.volume_ratio is not None,
                    }.items() if not value
                ]
                ti.failure_reason = "核心字段缺失: " + "、".join(missing)
                logger.error("%s 数据不完整: %s", sym, ti.failure_reason)

        except Exception as exc:
            ti.failure_reason = f"{type(exc).__name__}: {exc}"
            logger.error("获取 %s 技术数据失败: %s", sym, ti.failure_reason)

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
    """计算技术数据可支持的三个分项；事件与用户分由报告层补入。"""
    trend = 0.0
    trend += 7 if ti.above_ma20 else 0
    trend += 6 if ti.above_ma60 else 0
    if ti.ma5 and ti.ma20 and ti.ma5 > ti.ma20:
        trend += 5
    if (ti.change_pct_5d or 0) > 0 and (ti.change_pct_20d or 0) > 0:
        trend += 4
    if ti.tech_status == "强势":
        trend += 3
    trend = min(25, trend)

    momentum = 8.0
    momentum += max(-4, min(4, (ti.change_pct_today or 0) * 1.2))
    momentum += max(-4, min(4, (ti.change_pct_5d or 0) * .35))
    if ti.volume_ratio is not None:
        if ti.volume_ratio >= 1.3 and ti.change_pct_today > 0:
            momentum += 5
        elif ti.volume_ratio < .8 and ti.change_pct_today >= 0:
            momentum += 2
        elif ti.volume_ratio >= 1.5 and ti.change_pct_today < 0:
            momentum -= 4
    momentum = max(0, min(20, momentum))

    position = 8.0
    if ti.rsi14 is not None:
        if 40 <= ti.rsi14 <= 65:
            position += 6
        elif ti.rsi14 > 75 or ti.rsi14 < 30:
            position -= 4
    if ti.high_20d and ti.low_20d and ti.high_20d > ti.low_20d:
        percentile = (ti.current_price - ti.low_20d) / (ti.high_20d - ti.low_20d)
        if .55 <= percentile <= .9:
            position += 4
        elif percentile < .15:
            position -= 3
    if ti.tech_status == "破位":
        position -= 5
    position = max(0, min(20, position))

    risk = 100 - (trend / 25 * 45 + momentum / 20 * 25 + position / 20 * 30)
    long_score = trend + momentum + position
    return {
        "opportunity": round(long_score, 1), "risk": round(risk, 1),
        "trend": round(trend, 1), "momentum": round(momentum, 1),
        "technical_position": round(position, 1),
        "long_actionability": round(long_score, 1), "final": round(long_score, 1),
    }


def _generate_analysis(ti: TechnicalIndicators, is_held: bool = False) -> str:
    """生成 200-260 字的中文个股综合分析。

    包含 5 个小模块：
    1. 【当前状态】
    2. 【技术面】
    3. 【机会判断】
    4. 【风险提示】
    5. 【操作建议】

    Args:
        ti: 技术指标数据
        is_held: 是否为用户持仓
    """
    sym = ti.symbol
    name = ti.company_cn or sym

    modules: list[str] = []

    # ── 1. 【当前状态】 ──
    arrow = "上涨" if (ti.change_pct_today or 0) >= 0 else "下跌"
    status_cn = ti.tech_status
    # 均线状况
    ma_status = []
    if ti.above_ma20 and ti.above_ma60:
        ma_status.append("站上 MA20 和 MA60")
    elif ti.above_ma20:
        ma_status.append("站上 MA20 但 MA60 上方承压")
    elif ti.ma20 and ti.current_price < ti.ma20 * 0.95:
        ma_status.append("明显跌破 MA20")
    else:
        ma_status.append("均线系统方向不明")
    ma_str = "，".join(ma_status)

    modules.append(
        f"【当前状态】{name}现报 ${ti.current_price:.2f}，"
        f"今日{arrow} {(ti.change_pct_today or 0):+.1f}%。"
        f"技术状态为【{status_cn}】，{ma_str}。"
        f"近 5 日涨跌 {(ti.change_pct_5d or 0):+.1f}%，"
        f"近 20 日涨跌 {(ti.change_pct_20d or 0):+.1f}%。"
    )

    # ── 2. 【技术面】 ──
    tech_parts = []
    if ti.ma5:
        tech_parts.append(f"MA5=${ti.ma5:.2f}")
    if ti.ma20:
        tech_parts.append(f"MA20=${ti.ma20:.2f}")
    if ti.ma60:
        tech_parts.append(f"MA60=${ti.ma60:.2f}")
    ma_line = "，".join(tech_parts)

    rsi_desc = ""
    if ti.rsi14 is not None:
        if ti.rsi14 > 70:
            rsi_desc = f"RSI14={ti.rsi14}，处于超买区域，需注意回调风险"
        elif ti.rsi14 < 30:
            rsi_desc = f"RSI14={ti.rsi14}，处于超卖区域，技术性反弹概率增加"
        else:
            rsi_desc = f"RSI14={ti.rsi14}，处于中性区间，未出现极端信号"

    vol_desc = ""
    if ti.volume_ratio is not None:
        if ti.volume_ratio > 2.0 and (ti.change_pct_today or 0) > 0:
            vol_desc = f"今日成交量异常放大至 20 日均量的 {ti.volume_ratio} 倍，量价齐升"
        elif ti.volume_ratio > 2.0 and (ti.change_pct_today or 0) < 0:
            vol_desc = f"今日放量下跌，成交量为 20 日均量的 {ti.volume_ratio} 倍，抛压明显"
        elif ti.volume_ratio > 1.3:
            vol_desc = f"成交量略高于 20 日均量（{ti.volume_ratio} 倍），市场关注度尚可"
        elif ti.volume_ratio < 0.7:
            vol_desc = f"成交量萎缩至 20 日均量的 {ti.volume_ratio} 倍，市场交投清淡"
        else:
            vol_desc = f"成交量处于正常水平（20 日均量的 {ti.volume_ratio} 倍）"

    # 20日高低点位置
    pos_desc = ""
    if ti.high_20d and ti.low_20d and ti.high_20d > ti.low_20d:
        pos_ratio = (ti.current_price - ti.low_20d) / (ti.high_20d - ti.low_20d) * 100
        if pos_ratio > 85:
            pos_desc = f"当前价格接近 20 日高点(${ti.high_20d:.2f})，处于区间高位（{pos_ratio:.0f}%分位），追高需谨慎"
        elif pos_ratio < 15:
            pos_desc = f"当前价格接近 20 日低点(${ti.low_20d:.2f})，处于区间低位（{pos_ratio:.0f}%分位），关注能否企稳反弹"
        else:
            pos_desc = f"当前价格在 20 日区间中位震荡（{pos_ratio:.0f}%分位），方向未明"

    modules.append(
        f"【技术面】{ma_line}。{rsi_desc}。{vol_desc}。{pos_desc}。"
    )

    # ── 3. 【机会判断】 ──
    opp_parts = []
    score = ti.final_score
    if score >= 70:
        opp_parts.append(f"综合评分 {score:.0f} 分，技术面偏强")
        if ti.above_ma20 and ti.above_ma60:
            opp_parts.append("多头排列清晰，短期和中期趋势共振向上")
        if ti.rsi14 and ti.rsi14 < 65:
            opp_parts.append("RSI 尚未过热，仍有上行空间")
        if ti.volume_ratio and ti.volume_ratio > 1.2 and (ti.change_pct_today or 0) > 0:
            opp_parts.append("量价配合良好，资金关注度提升")

        if ti.above_ma20:
            opp_parts.append("可关注回踩 MA20 不破时的介入机会")
        else:
            opp_parts.append("但目前仍在 MA20 下方，建议等待有效站上后再评估")

    elif score >= 50:
        opp_parts.append(f"综合评分 {score:.0f} 分，技术面中性偏正面")
        if ti.tech_status == "修复":
            opp_parts.append("处于修复阶段，若能放量突破关键均线则有望转强")
        elif ti.tech_status == "震荡":
            opp_parts.append("处于震荡整理阶段，建议等待明确突破信号")
        if ti.rsi14 and 40 <= ti.rsi14 <= 60:
            opp_parts.append("RSI 处于健康区间，不存在极端过热或过弱问题")

        if ti.above_ma20:
            opp_parts.append("当前站上 MA20，短线支撑有效，可小仓观察")
        else:
            opp_parts.append("但尚未站上 MA20，短期均线构成压力")

    elif score >= 30:
        opp_parts.append(f"综合评分 {score:.0f} 分，技术面偏弱")
        if ti.tech_status == "弱势":
            opp_parts.append("处于弱势下跌趋势，不建议逆势操作")
        elif ti.tech_status == "破位":
            opp_parts.append("已破位下行，短期内企稳信号不足")
        if ti.rsi14 and ti.rsi14 < 30:
            opp_parts.append("RSI 已进入超卖区域，虽存在技术性反弹可能，但趋势尚未扭转")
        if ti.change_pct_20d and ti.change_pct_20d < -10:
            opp_parts.append(f"近 20 日跌幅达 {(ti.change_pct_20d or 0):.1f}%，中期趋势偏空")

    else:
        opp_parts.append(f"综合评分 {score:.0f} 分，技术面明显弱势，建议回避为主")

    modules.append("【机会判断】" + "，".join(opp_parts) + "。")

    # ── 4. 【风险提示】 ──
    risk_parts = []
    if ti.tech_risk == "高":
        risk_parts.append(f"当前风险等级【高】，需重点警惕")
    elif ti.tech_risk == "中":
        risk_parts.append(f"当前风险等级【中】，需保持适度谨慎")

    if not ti.above_ma20:
        risk_parts.append("已经跌破 MA20，短期均线构成压力")
    if not ti.above_ma60:
        risk_parts.append("处于 MA60 下方，中期趋势承压")
    if ti.rsi14 and ti.rsi14 > 75:
        risk_parts.append(f"RSI14={ti.rsi14} 已进入严重超买区域，追高风险极大")
    if ti.volume_ratio and ti.volume_ratio > 3 and (ti.change_pct_today or 0) < 0:
        risk_parts.append("今日出现放量下跌的异常信号，需警惕进一步调整")
    if ti.change_pct_5d and ti.change_pct_5d < -8:
        risk_parts.append(f"近 5 日跌幅达 {ti.change_pct_5d:.1f}%，短期抛压较重")
    if ti.change_pct_20d and ti.change_pct_20d < -15:
        risk_parts.append(f"近 20 日累计下跌 {(ti.change_pct_20d or 0):.1f}%，中期趋势较差")
    if ti.high_20d and ti.low_20d and ti.current_price <= ti.low_20d * 1.05:
        risk_parts.append("当前价格接近 20 日最低点，若继续下破则可能加速下跌")

    if not risk_parts:
        risk_parts.append("短期无明显系统风险，但需关注个股分化和大盘回调的联动影响。")

    modules.append("【风险提示】" + "，".join(risk_parts) + "。")

    # ── 5. 【操作建议】 ──
    from northstar.reports.daily_decision_report import _judge_suggestion, StockPriceInfo
    sp = StockPriceInfo(symbol=sym, company_cn=name, current_price=ti.current_price,
                        change_pct_today=ti.change_pct_today, trend=ti.tech_status,
                        change_pct_5d=ti.change_pct_5d, change_pct_20d=ti.change_pct_20d)
    sugg = _judge_suggestion(sp)
    if (ti.change_pct_today or 0) > 0 and ti.above_ma20 and ti.tech_status == "强势":
        sugg = "买入观察"

    adv_parts = []
    adv_parts.append(f"建议：{sugg}")

    if is_held:
        adv_parts.append("【我的持仓】")
        if sugg in ("买入观察", "继续持有"):
            if ti.above_ma20:
                adv_parts.append("目前处于安全区间，可继续持有，观察 MA20 支撑力度。"
                                  f"若跌破 MA20(${ti.ma20:.2f})需考虑减仓")
            else:
                adv_parts.append("当前价格已跌破 MA20，持仓面临均线压力，"
                                  f"建议观察能否在 ${ti.ma20:.2f} 附近企稳。"
                                  "若继续走弱应考虑止损")
        elif sugg == "暂不买入":
            adv_parts.append("当前不适合新增仓位。已持有的仓位建议观察"
                              f"能否重新站回 MA20(${ti.ma20:.2f})，"
                              "若持续在均线下方运行可考虑减仓")
        elif sugg in ("高风险回避", "减仓观察"):
            adv_parts.append("建议控制风险，已持有的仓位可考虑逐步减仓或设置止损。"
                              "不建议继续加仓或抄底")
        adv_parts.append(f"重点关注：能否有效突破 ${ti.ma20:.2f}(MA20)")
        if ti.ma60:
            adv_parts.append(f"和 ${ti.ma60:.2f}(MA60) 两个关键价位")
    else:
        if sugg == "买入观察":
            adv_parts.append("技术面偏强，可小仓观察，但不建议追高。"
                              f"回踩 MA20(${ti.ma20:.2f})不破时是较好的介入时机")
        elif sugg == "继续持有":
            adv_parts.append("当前适合继续持有，不急于加仓也不急于卖出。"
                              f"关注 MA20(${ti.ma20:.2f})支撑是否有效")
        elif sugg == "暂不买入":
            adv_parts.append("暂时观望为宜。等待价格站上 MA20 并确认支撑后再考虑。"
                              "不建议在均线下方抄底")
        elif sugg in ("高风险回避", "减仓观察"):
            adv_parts.append("风险较高，建议回避。不要因为价格低而急于抄底，"
                              "等待趋势反转信号明确后再做决定")

    modules.append("【操作建议】" + "，".join(adv_parts))

    result = "\n".join(modules)

    # 确保最少 180 个中文字符
    cn_chars = sum(1 for c in result if '\u4e00' <= c <= '\u9fff')
    if cn_chars < 180:
        filler = (
            f"综合来看，{name}({sym})技术评分{ti.final_score:.0f}分，"
            f"趋势评分{ti.trend_score:.0f}分，风险评分{ti.risk_score:.0f}分。"
            f"建议结合大盘整体环境和个人风险承受能力做出投资决策。"
            f"以上分析基于技术面数据，不构成投资建议。"
        )
        result += "\n" + filler

    return result
