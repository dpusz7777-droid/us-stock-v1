#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Polaris View Model – decision-layer transformation.

Produces a ViewModel structured for daily decision making:
    Layer 0: Decision Summary (one-liner: 加仓 / 减仓 / 观望)
    Layer 1: Health Score / Risk Exposure / Momentum
    Layer 2: Top 3 Actionable signals (Buy / Sell / Hold)
    Layer 3: Current positions
    Layer 4: Why explanation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from core.constants import (
    PLACEHOLDER,
    ZERO_USD,
    POSITION_INSIGHTS,
    POSITION_INSIGHT_DEFAULT,
    REPORT_TYPE_MORNING,
    REPORT_TYPE_EVENING,
    REPORT_TYPE_SYNC,
    REPORT_TYPE_NAMES,
    SOURCE_V2,
    SOURCE_YFINANCE,
    SOURCE_CACHE,
    WARN_MISSING_TEMPLATE,
    ERROR_DATA_UNAVAILABLE,
    DECISION_ADD,
    DECISION_REDUCE,
    DECISION_WAIT,
)
from core.data_layer import (
    SECTOR_MAP,
    PositionView,
    PortfolioSnapshot,
    MarketStatusItem,
    PricePoint,
    get_portfolio,
    get_market_status,
    get_reports,
    get_signals,
    clear_cache,
)
from signal_engine import Signal


# ---------------------------------------------------------------------------
# Decision-oriented ViewModel
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActionSignal:
    """A single actionable investment signal."""
    symbol: str
    action: str  # "买入" | "卖出" | "观望"
    reason: str
    strength: int  # 1-5
    css_class: str  # "signal-strong" | "signal-neutral" | "signal-weak"
    urgency_score: int = field(default=0)  # higher = more urgent, for sorting


@dataclass(frozen=True)
class ViewModel:
    """Decision-oriented dashboard data."""

    # Layer 0: Decision Summary (THE most important)
    decision_summary: str = ""  # e.g. "今日建议：加仓 → NVDA 趋势强劲，现金充足"
    decision_action: str = DECISION_WAIT  # "加仓" | "减仓" | "观望"

    # Layer 1: Pillars
    health_score: int = 50
    health_label: str = "中等"
    health_css: str = "score-neutral"
    risk_exposure_pct: str = PLACEHOLDER
    risk_single_max: str = PLACEHOLDER
    risk_sector_concentration: str = PLACEHOLDER
    momentum_label: str = "中性"
    momentum_css: str = "momentum-neutral"
    total_equity: str = PLACEHOLDER
    cash: str = PLACEHOLDER
    today_pnl: str = PLACEHOLDER

    # Layer 2: Action signals (MAX 3, sorted by importance)
    action_signals: tuple[ActionSignal, ...] = ()

    # Layer 3: Position rows (for table)
    position_rows: tuple[dict[str, Any], ...] = ()

    # Layer 4: Why section
    why_items: tuple[dict[str, str], ...] = ()

    # Market cards
    market_cards: tuple[dict[str, str], ...] = ()

    # Reports
    reports: tuple[dict[str, Any], ...] = ()

    # Status
    has_data: bool = True
    error: str | None = None
    warnings: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Safe formatting
# ---------------------------------------------------------------------------


def _usd(value: Decimal | None, *, zero_if_none: bool = False) -> str:
    if value is None:
        return "0.00 美元" if zero_if_none else PLACEHOLDER
    return f"{value:,.2f} 美元"


def _signal_for(symbol: str) -> tuple[str, str]:
    return POSITION_INSIGHTS.get(symbol, POSITION_INSIGHT_DEFAULT)


def _report_type_name(report_type: str) -> str:
    lowered = report_type.lower()
    if "morning" in lowered:
        return REPORT_TYPE_MORNING
    if "evening" in lowered:
        return REPORT_TYPE_EVENING
    if "sync" in lowered or "migration" in lowered:
        return REPORT_TYPE_SYNC
    return REPORT_TYPE_NAMES.get(lowered, REPORT_TYPE_NAMES["report"])


# ---------------------------------------------------------------------------
# Health Score calculation (0-100)
# ---------------------------------------------------------------------------


def _compute_health(positions: list[dict[str, Any]], total_equity: Decimal | None, cash: Decimal | None) -> tuple[int, str, str]:
    """Health score based on concentration, drawdown, and cash buffer."""
    score = 70  # baseline

    if not positions:
        return 30, "偏低", "score-weak"

    # Concentration penalty
    values = [r["Market Value"] or r["Quantity"] * r["Avg Cost"] for r in positions]
    total = sum(values, Decimal("0"))
    if total > 0:
        max_w = max(values) / total * Decimal("100")
        if max_w > 60:
            score -= 20
        elif max_w > 40:
            score -= 10

    # Drawdown penalty
    pnl_pcts = [r["PnL %"] for r in positions if r["PnL %"] is not None]
    if pnl_pcts:
        worst = min(pnl_pcts)
        if worst < -15:
            score -= 20
        elif worst < -8:
            score -= 10
        elif worst < -3:
            score -= 5

    # Cash buffer bonus
    if total_equity is not None and total > 0:
        cash_pct = (cash or Decimal("0")) / total_equity * Decimal("100")
        if cash_pct > 30:
            score += 10
        elif cash_pct > 15:
            score += 5

    score = max(10, min(95, score))
    if score >= 75:
        return score, "良好", "score-strong"
    if score >= 50:
        return score, "中等", "score-neutral"
    return score, "偏低", "score-weak"


def _compute_momentum(positions: list[dict[str, Any]]) -> tuple[str, str]:
    """Momentum based on PnL trend across positions."""
    pnl_pcts = [r["PnL %"] for r in positions if r["PnL %"] is not None]
    if not pnl_pcts:
        return "中性", "momentum-neutral"
    avg = sum(pnl_pcts) / len(pnl_pcts)
    if avg > 5:
        return "偏强", "momentum-strong"
    if avg > 1:
        return "温和", "momentum-neutral"
    if avg < -5:
        return "偏弱", "momentum-weak"
    if avg < -1:
        return "谨慎", "momentum-weak"
    return "中性", "momentum-neutral"


def _compute_decision(
    signals: tuple[ActionSignal, ...],
    health_score: int,
    cash_pct: Decimal | None,
    positions: list[dict[str, Any]],
) -> tuple[str, str]:
    """Generate a one-line decision summary.

    Returns (decision_summary, decision_action) where decision_action
    is "加仓", "减仓", or "观望".
    """
    # Count actionable signals
    buy_signals = [s for s in signals if s.action == "买入"]
    sell_signals = [s for s in signals if s.action == "卖出"]

    # Check for critical sell signals (strength >= 4)
    strong_sells = [s for s in sell_signals if s.strength >= 4]
    if strong_sells:
        symbols = "、".join(s.symbol for s in strong_sells[:2])
        reasons = "；".join(s.reason for s in strong_sells[:2])
        return (f"今日建议：减仓 → {symbols} 风险信号较强（{reasons}）", DECISION_REDUCE)

    # Check for health warning
    if health_score < 50:
        return (f"今日建议：观望 → 组合健康度偏低（{health_score}分），暂缓操作", DECISION_WAIT)

    # Check for strong buy signals
    strong_buys = [s for s in buy_signals if s.strength >= 4]
    if strong_buys:
        symbols = "、".join(s.symbol for s in strong_buys[:2])
        reasons = "；".join(s.reason for s in strong_buys[:2])
        cash_note = ""
        if cash_pct is not None and cash_pct > 20:
            cash_note = "，现金充足"
        return (f"今日建议：加仓 → {symbols} 趋势向好（{reasons}）{cash_note}", DECISION_ADD)

    # Check for any buy signals with good health
    if buy_signals and health_score >= 60:
        top = buy_signals[0]
        cash_note = ""
        if cash_pct is not None and cash_pct > 20:
            cash_note = "，现金充裕"
        return (f"今日建议：加仓 → {top.symbol} 信号积极（{top.reason}）{cash_note}", DECISION_ADD)

    # Check for sell signals
    if sell_signals:
        top = sell_signals[0]
        return (f"今日建议：减仓 → {top.symbol} {top.reason}", DECISION_REDUCE)

    # Default: hold
    reason_parts = []
    if health_score >= 75:
        reason_parts.append(f"组合健康（{health_score}分）")
    if cash_pct is not None and cash_pct > 20:
        reason_parts.append("现金充足")
    elif cash_pct is not None and cash_pct < 5:
        reason_parts.append("仓位较高")

    reason_str = "，".join(reason_parts) if reason_parts else "无明显交易信号"
    return (f"今日建议：观望 → {reason_str}", DECISION_WAIT)


def _build_why_items(
    positions: list[dict[str, Any]],
    risk_single_max: str,
    risk_sector: str,
    signals: tuple[ActionSignal, ...],
    pnl_summary: str,
    decision_action: str,
) -> list[dict[str, str]]:
    """Generate market-driven explanations for the Why section."""
    items: list[dict[str, str]] = []

    # PnL explanation
    if pnl_summary and pnl_summary != PLACEHOLDER:
        items.append({
            "label": "盈亏驱动",
            "text": f"当前持仓盈亏 {pnl_summary}。",
        })

    # Signal explanations
    buy_signals = [s for s in signals if s.action == "买入"]
    sell_signals = [s for s in signals if s.action == "卖出"]
    if buy_signals:
        names = "、".join(s.symbol for s in buy_signals[:2])
        reasons = "；".join(s.reason for s in buy_signals[:2])
        items.append({
            "label": "买入逻辑",
            "text": f"{names} 买入依据：{reasons}",
        })
    if sell_signals:
        names = "、".join(s.symbol for s in sell_signals[:2])
        reasons = "；".join(s.reason for s in sell_signals[:2])
        items.append({
            "label": "卖出逻辑",
            "text": f"{names} 卖出依据：{reasons}",
        })

    # Risk explanation
    items.append({
        "label": "风险提示",
        "text": f"单一持仓最大 {risk_single_max}；行业集中度 {risk_sector}。",
    })

    return items


# ---------------------------------------------------------------------------
# Build the view model
# ---------------------------------------------------------------------------


def build_view_model(force_refresh: bool = False) -> ViewModel:
    if force_refresh:
        clear_cache()

    warnings: list[str] = []

    portfolio = get_portfolio()
    if not portfolio.positions:
        return ViewModel(
            decision_summary="今日建议：观望 → 暂无持仓数据",
            has_data=False,
            error=ERROR_DATA_UNAVAILABLE,
        )

    te = portfolio.total_equity
    cash = portfolio.cash
    pnl = portfolio.total_unrealized_pnl

    # --- Position rows ---
    rows: list[dict[str, Any]] = []
    symbols_for_signals: list[str] = []
    for symbol in sorted(portfolio.positions):
        pv: PositionView = portfolio.positions[symbol]
        symbols_for_signals.append(symbol)
        signal_text, insight = _signal_for(symbol)
        rows.append({
            "Symbol": symbol,
            "Quantity": pv.shares,
            "Avg Cost": pv.avg_cost,
            "Current Price": pv.last_price,
            "Market Value": pv.market_value,
            "PnL $": pv.unrealized_pnl,
            "PnL %": pv.unrealized_pnl_pct,
            "Sector": SECTOR_MAP.get(symbol, "其他"),
            "Signal": signal_text,
            "Insight": insight,
        })

    # --- Risk metrics ---
    values = [r["Market Value"] or r["Quantity"] * r["Avg Cost"] for r in rows]
    invested = sum(values, Decimal("0"))
    equity = te if te is not None else (cash + invested if cash is not None else None)
    risk_exposure_pct = (
        f"{invested / equity * Decimal('100'):.1f}%"
        if equity is not None and equity > 0
        else PLACEHOLDER
    )
    max_single = max(values) if invested > 0 else Decimal("0")
    risk_single_max = (
        f"{max_single / invested * Decimal('100'):.1f}%"
        if invested > 0
        else PLACEHOLDER
    )

    # Sector concentration
    sectors: dict[str, Decimal] = {}
    for r in rows:
        sec = SECTOR_MAP.get(r["Symbol"], "其他")
        v = r["Market Value"] or r["Quantity"] * r["Avg Cost"]
        sectors[sec] = sectors.get(sec, Decimal("0")) + v
    max_sector = max(sectors.values()) if sectors else Decimal("0")
    risk_sector = (
        f"{max_sector / invested * Decimal('100'):.1f}%"
        if invested > 0
        else PLACEHOLDER
    )

    # PnL summary for PnL $ string
    pnl_total = portfolio.total_unrealized_pnl
    pnl_str = _usd(pnl_total) if pnl_total is not None else PLACEHOLDER

    # --- Health score ---
    health_score, health_label, health_css = _compute_health(rows, te, cash)

    # --- Momentum ---
    momentum_label, momentum_css = _compute_momentum(rows)

    # --- Cash percentage ---
    cash_pct: Decimal | None = None
    if cash is not None and te is not None and te > 0:
        cash_pct = cash / te * Decimal("100")

    # --- Market cards ---
    market_items = get_market_status()
    market_cards: list[dict[str, str]] = []
    for item in market_items:
        price_str = (
            f"${item.price.value:,.2f}"
            if item.price.value is not None
            else PLACEHOLDER
        )
        src_map = {"v2": SOURCE_V2, "yfinance": SOURCE_YFINANCE, "cache": SOURCE_CACHE}
        market_cards.append({
            "symbol": item.symbol,
            "price": price_str,
            "source": src_map.get(item.price.source, item.price.source),
        })

    # --- Action signals (real engine + overrides) ---
    raw_signals = tuple(get_signals(symbols_for_signals))
    action_signals: list[ActionSignal] = []

    # Map engine signals
    for s in raw_signals:
        stype = s.signal_type.value
        if stype in ("BUY", "INCREASE"):
            action = "买入"
            css = "signal-strong"
            strength = min(5, max(1, s.strength + 2))
        elif stype in ("SELL", "REDUCE", "RISK_OFF"):
            action = "卖出"
            css = "signal-weak"
            strength = min(5, max(1, s.strength + 1))
        else:
            action = "观望"
            css = "signal-neutral"
            strength = 3

        reason = POSITION_INSIGHTS.get(s.symbol, ("", "等待更多数据。"))[1]
        action_signals.append(ActionSignal(
            symbol=s.symbol,
            action=action,
            reason=reason,
            strength=strength,
            css_class=css,
            urgency_score=0,
        ))

    # Add static insights as signals for positions not covered by engine
    seen_symbols = {s.symbol for s in raw_signals}
    for r in rows:
        sym = r["Symbol"]
        if sym not in seen_symbols:
            sig_text, insight = _signal_for(sym)
            if "🟢" in sig_text:
                action_signals.append(ActionSignal(
                    symbol=sym,
                    action="买入",
                    reason=insight,
                    strength=4,
                    css_class="signal-strong",
                    urgency_score=0,
                ))
            elif "🔴" in sig_text:
                action_signals.append(ActionSignal(
                    symbol=sym,
                    action="卖出",
                    reason=insight,
                    strength=3,
                    css_class="signal-weak",
                    urgency_score=0,
                ))
            else:
                action_signals.append(ActionSignal(
                    symbol=sym,
                    action="观望",
                    reason=insight,
                    strength=3,
                    css_class="signal-neutral",
                    urgency_score=0,
                ))

    action_signals.sort(key=_urgency_key)

    # Keep only top 3
    action_signals = action_signals[:3]

    # --- Decision summary (Layer 0) ---
    decision_summary, decision_action = _compute_decision(
        tuple(action_signals), health_score, cash_pct, rows
    )

    # --- Why section ---
    why_items = tuple(_build_why_items(rows, risk_single_max, risk_sector, tuple(action_signals), pnl_str, decision_action))

    # --- Reports ---
    report_metas = get_reports(limit=5)
    reports: list[dict[str, Any]] = []
    for rm in report_metas:
        reports.append({
            "date": rm.date,
            "type": rm.type,
            "file_path": rm.file_path,
            "content": rm.content,
            "type_name": _report_type_name(rm.type),
        })

    # --- Warnings ---
    for item in market_items:
        if item.price.status == "missing":
            warnings.append(WARN_MISSING_TEMPLATE.format(symbol=item.symbol))

    return ViewModel(
        decision_summary=decision_summary,
        decision_action=decision_action,
        total_equity=_usd(te),
        cash=_usd(cash),
        today_pnl=_usd(pnl, zero_if_none=True) if pnl is not None else ZERO_USD,
        health_score=health_score,
        health_label=health_label,
        health_css=health_css,
        risk_exposure_pct=risk_exposure_pct,
        risk_single_max=risk_single_max,
        risk_sector_concentration=risk_sector,
        momentum_label=momentum_label,
        momentum_css=momentum_css,
        action_signals=tuple(action_signals),
        why_items=why_items,
        position_rows=tuple(rows),
        market_cards=tuple(market_cards),
        reports=tuple(reports),
        has_data=True,
        error=None,
        warnings=tuple(warnings),
    )