#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""报告模板 — 日报 / 周报 / 信号总结模板。

纯文本模板，不依赖外部渲染引擎。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Template:
    """模板定义。"""
    name: str
    header: str
    body_template: str
    footer: str


# ── 模板定义 ──

DAILY_TEMPLATE = Template(
    name="日报",
    header="# 北极星每日报告\n生成时间：{datetime}\n---\n",
    body_template="""
## 今日操作建议
{signals}

## 持仓状态
{portfolio}

## 风险提示
{risk}
""",
    footer="\n---\n*本报告由北极星系统自动生成，仅供参考。*",
)

WEEKLY_TEMPLATE = Template(
    name="周报",
    header="# 北极星周报\n周期：{start_date} → {end_date}\n---\n",
    body_template="""
## 本周操作回顾
{trades}

## 策略表现
{performance}

## 下周展望
{outlook}
""",
    footer="\n---\n*本报告由北极星系统自动生成，仅供参考。*",
)

SIGNAL_TEMPLATE = Template(
    name="信号总结",
    header="# 信号总结\n生成时间：{datetime}\n---\n",
    body_template="""
## 当前信号
{signals}

## 信号历史表现
{history}

## 建议执行
{suggestion}
""",
    footer="\n---\n*信号基于策略模型计算，不构成投资建议。*",
)


def render_daily(signals: str, portfolio: str, risk: str) -> str:
    """渲染日报。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    body = DAILY_TEMPLATE.body_template.format(
        signals=signals,
        portfolio=portfolio,
        risk=risk,
    )
    return f"{DAILY_TEMPLATE.header.format(datetime=now)}{body}{DAILY_TEMPLATE.footer}"


def render_weekly(trades: str, performance: str, outlook: str) -> str:
    """渲染周报。"""
    from datetime import timedelta
    now = datetime.now()
    start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    body = WEEKLY_TEMPLATE.body_template.format(
        trades=trades,
        performance=performance,
        outlook=outlook,
    )
    return f"{WEEKLY_TEMPLATE.header.format(start_date=start, end_date=end)}{body}{WEEKLY_TEMPLATE.footer}"


def render_signal_summary(signals: str, history: str, suggestion: str) -> str:
    """渲染信号总结。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    body = SIGNAL_TEMPLATE.body_template.format(
        signals=signals,
        history=history,
        suggestion=suggestion,
    )
    return f"{SIGNAL_TEMPLATE.header.format(datetime=now)}{body}{SIGNAL_TEMPLATE.footer}"