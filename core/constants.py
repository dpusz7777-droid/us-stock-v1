#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Polaris System Constants – single source of truth for all UI text.

Rules:
    - All UI-facing strings live here.
    - dashboard.py and view_model.py must import from here.
    - No f-string or concatenation for titles/page names.
    - APP_NAME is locked to "北极星" (no variants allowed).
"""

from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════════════
# System identity (LOCKED – do not change)
# ═══════════════════════════════════════════════════════════════════════════════

APP_NAME: str = "北极星"
APP_TITLE: str = "北极星 · 每日决策"
APP_TAGLINE: str = "美股账户 · 3秒决策"

# ═══════════════════════════════════════════════════════════════════════════════
# Account labels
# ═══════════════════════════════════════════════════════════════════════════════

ACCOUNT_LABEL: str = "美元账户"
ACCOUNT_SUBTEXT: str = "数据实时更新"

# ═══════════════════════════════════════════════════════════════════════════════
# Navigation (page names & sidebar)
# ═══════════════════════════════════════════════════════════════════════════════

NAV_ITEMS: tuple[str, ...] = (
    "账户概览",
    "我的持仓",
    "交易信号",
    "持仓分析",
    "研究报告",
)

NAV_LABEL_DASHBOARD: str = "每日决策"
NAV_LABEL_PORTFOLIO: str = "我的持仓"
NAV_LABEL_SIGNALS: str = "交易信号"
NAV_LABEL_INSIGHTS: str = "持仓分析"
NAV_LABEL_REPORTS: str = "研究报告"

# ═══════════════════════════════════════════════════════════════════════════════
# Page titles & captions
# ═══════════════════════════════════════════════════════════════════════════════

PAGE_TITLE_DASHBOARD: str = "每日决策"
PAGE_CAPTION_DASHBOARD: str = "3秒判断 · 今日交易方向"

PAGE_TITLE_PORTFOLIO: str = "我的持仓"
PAGE_CAPTION_PORTFOLIO: str = "行业暴露 · 持仓集中度 · 风险监测"

PAGE_TITLE_SIGNALS: str = "信号中心"
PAGE_CAPTION_SIGNALS: str = "策略信号 · 仅供研究参考"

PAGE_TITLE_INSIGHTS: str = "持仓分析"
PAGE_CAPTION_INSIGHTS: str = "持仓解读 · 趋势观察 · 风险辅助"

PAGE_TITLE_REPORTS: str = "报告中心"
PAGE_CAPTION_REPORTS: str = "报告时间轴 · 按时间倒序"

# ═══════════════════════════════════════════════════════════════════════════════
# KPI labels
# ═══════════════════════════════════════════════════════════════════════════════

KPI_TOTAL_ASSETS: str = "总资产"
KPI_CASH: str = "可用资金"
KPI_BUYING_POWER: str = "购买力"
KPI_TODAY_PNL: str = "今日盈亏"

KPI_SUB_EQUITY: str = "美元计价"
KPI_SUB_CASH: str = "可用资金"
KPI_SUB_BUYING_POWER: str = "融资额度"
KPI_SUB_PNL: str = "未实现"

# ═══════════════════════════════════════════════════════════════════════════════
# Decision layer labels
# ═══════════════════════════════════════════════════════════════════════════════

LAYER0_DECISION: str = "今日决策"
LAYER1_PILLARS: str = "风控·健康·动量"
LAYER2_SIGNALS: str = "核心信号"
LAYER3_POSITIONS: str = "当前持仓"
LAYER4_WHY: str = "决策依据"

DECISION_ADD: str = "加仓"
DECISION_REDUCE: str = "减仓"
DECISION_WAIT: str = "观望"

HEALTH_LABELS: dict[str, str] = {
    "score-strong": "良好",
    "score-neutral": "中等",
    "score-weak": "偏低",
}

# ═══════════════════════════════════════════════════════════════════════════════
# Risk panel
# ═══════════════════════════════════════════════════════════════════════════════

RISK_SECTION: str = "风险监测"
RISK_EXPOSURE: str = "总风险暴露"
RISK_CONCENTRATION: str = "最大持仓集中度"
RISK_DRAWDOWN: str = "最大回撤风险提示"
RISK_NO_DRAWDOWN: str = "暂未发现显著回撤"
RISK_DRAWDOWN_TEMPLATE: str = "最大持仓回撤 {pct}%"

# ═══════════════════════════════════════════════════════════════════════════════
# Positions table
# ═══════════════════════════════════════════════════════════════════════════════

TABLE_SECTION: str = "当前持仓"
TABLE_EMPTY: str = "暂无持仓数据。"

TABLE_HEADERS: dict[str, str] = {
    "symbol": "代码",
    "quantity": "数量",
    "avg_cost": "成本价",
    "current_price": "现价",
    "market_value": "市值",
    "pnl_amount": "盈亏额",
    "pnl_pct": "盈亏率",
    "signal": "信号",
    "insight": "解读",
}

CONCENTRATION_ALERT_TEMPLATE: str = "⚠ {symbol} 持仓集中度 {pct}%，已超过 50% 阈值。"
CONCENTRATION_NONE: str = "当前没有持仓超过 50% 集中度阈值。"

# ═══════════════════════════════════════════════════════════════════════════════
# Signals
# ═══════════════════════════════════════════════════════════════════════════════

SIGNAL_SECTION: str = "核心交易信号"
SIGNAL_EMPTY: str = "暂无交易建议。"
SIGNAL_ENGINE_LABEL: str = "信号强度 {strength}/5"

SIGNAL_BUY: str = "买入"
SIGNAL_SELL: str = "卖出"
SIGNAL_HOLD: str = "观望"

# ═══════════════════════════════════════════════════════════════════════════════
# Insights
# ═══════════════════════════════════════════════════════════════════════════════

INSIGHT_SECTION: str = "持仓洞察"
INSIGHT_EMPTY: str = "暂无可分析的持仓数据。"

# ═══════════════════════════════════════════════════════════════════════════════
# Reports
# ═══════════════════════════════════════════════════════════════════════════════

REPORT_SECTION: str = "报告时间轴"
REPORT_EMPTY: str = "暂无研究报告。"
REPORT_CONTENT_UNAVAILABLE: str = "报告内容暂不可用。"
REPORT_DATE_UNKNOWN: str = "日期未知"
REPORT_FALLBACK_TYPE: str = "研究报告"

# ═══════════════════════════════════════════════════════════════════════════════
# Market status
# ═══════════════════════════════════════════════════════════════════════════════

MARKET_SECTION: str = "市场行情"
MARKET_NO_DATA: str = "暂无数据"

# ═══════════════════════════════════════════════════════════════════════════════
# Sector exposure
# ═══════════════════════════════════════════════════════════════════════════════

SECTOR_SECTION: str = "行业暴露"

# ═══════════════════════════════════════════════════════════════════════════════
# Position insights (sector + status text)
# ═══════════════════════════════════════════════════════════════════════════════

POSITION_INSIGHTS: dict[str, tuple[str, str]] = {
    "NVDA": ("🟢 强势", "AI 芯片需求强劲，技术趋势长期向好。"),
    "SOFI": ("🟡 中性", "消费信贷回暖中，关注财报表现。"),
    "SPCX": ("🔴 风险", "流动性偏弱，建议保持观望。"),
}

POSITION_INSIGHT_DEFAULT: tuple[str, str] = ("🟡 中性", "等待更多市场数据。")

# ═══════════════════════════════════════════════════════════════════════════════
# Report type mappings
# ═══════════════════════════════════════════════════════════════════════════════

REPORT_TYPE_MORNING: str = "晨间报告"
REPORT_TYPE_EVENING: str = "晚间报告"
REPORT_TYPE_SYNC: str = "同步报告"

REPORT_TYPE_NAMES: dict[str, str] = {
    "morning": "晨间研究报告",
    "evening": "晚间研究报告",
    "sync": "数据同步报告",
    "report": "研究报告",
}

# ═══════════════════════════════════════════════════════════════════════════════
# Market source labels
# ═══════════════════════════════════════════════════════════════════════════════

SOURCE_V2: str = "行情服务"
SOURCE_YFINANCE: str = "行情服务"
SOURCE_CACHE: str = "缓存数据"
SOURCE_STATIC: str = "参考价格"

# ═══════════════════════════════════════════════════════════════════════════════
# Warning / status messages
# ═══════════════════════════════════════════════════════════════════════════════

WARN_SECTION: str = "行情状态"
WARN_STALE_TEMPLATE: str = "{symbol}: 数据超过1小时，显示缓存。"
WARN_MISSING_TEMPLATE: str = "{symbol}: 暂无最新行情。"

ERROR_DATA_UNAVAILABLE: str = "持仓数据暂不可用。"
ERROR_PAGE_UNAVAILABLE: str = "页面暂时不可用。"
ERROR_PAGE_RETRY: str = "账户数据未发生变化，请稍后重试。"

# ═══════════════════════════════════════════════════════════════════════════════
# Refresh / action labels
# ═══════════════════════════════════════════════════════════════════════════════

REFRESH_LABEL: str = "🔄 刷新数据"

# ═══════════════════════════════════════════════════════════════════════════════
# Placeholder / empty values
# ═══════════════════════════════════════════════════════════════════════════════

PLACEHOLDER: str = "—"
ZERO_USD: str = "$0.00"