#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""北极星系统后端入口 — 供 launch.py 以子进程方式调用。

用法（由 launch.py 内部启动）：
    python -m northstar.main --mode run      (后台交易引擎)
    python -m northstar.main --mode report    (生成报告)
    python -m northstar.main --mode status    (查看状态)

规则：
    - 本文件只负责后端业务运行
    - 不打开浏览器
    - 不启动 Streamlit
    - 不调用 launch.py
"""

from __future__ import annotations

import argparse
import sys
import time


def run_dashboard() -> None:
    """启动 Streamlit 决策终端。
    
    注意：此函数供开发时直接调用，生产环境由 launch.py 管理 UI 进程。
    本函数不触发 webbrowser.open。
    """
    import streamlit as st
    sys.path.insert(0, ".")
    from dashboard import run as dashboard_run
    dashboard_run()


def run_report() -> None:
    """生成今日报告。"""
    from northstar.report.report_generator import ReportGenerator

    rg = ReportGenerator()
    morning = rg.daily_morning()
    print(f"=== {morning.title} ===")
    print(morning.content[:500] + "..." if len(morning.content) > 500 else morning.content)
    print()


def run_backend() -> None:
    """启动后台交易引擎（持续运行）。"""
    from northstar.backend import run_backend as _run
    _run()


def run_status() -> None:
    """输出系统状态摘要。"""
    from northstar.data.portfolio_state import PortfolioState
    from northstar.core.signal_engine import SignalEngine
    from northstar.core.risk_engine import RiskEngine

    ps = PortfolioState()
    summary = ps.summary()

    print("=== 北极星系统状态 ===")
    print(f"持仓数量: {summary.position_count}")
    print(f"总资产: {summary.total_equity or 'N/A'}")
    print(f"现金: {summary.cash or 'N/A'}")
    print(f"最大集中度: {summary.concentration_max or 'N/A'}")
    print()

    risk = RiskEngine()
    report = risk.assess()
    print(f"风险评分: {report.risk_score}/100")
    print(f"建议: {'; '.join(report.suggestions[:3])}")
    print()

    se = SignalEngine()
    if summary.positions:
        syms = [p.symbol for p in summary.positions]
        sigs = se.generate(syms)
        for s in sigs[:3]:
            print(f"  {s.symbol}: {s.signal_type.value} (强度 {s.strength})")

    print()
    print("系统运行正常。")


def main() -> None:
    parser = argparse.ArgumentParser(description="北极星交易决策系统")
    parser.add_argument(
        "--mode", "-m",
        choices=["dashboard", "report", "status", "run"],
        default="status",
        help="运行模式: dashboard=启动UI, report=生成报告, status=查看状态",
    )
    args = parser.parse_args()

    if args.mode == "dashboard":
        run_dashboard()
    elif args.mode == "report":
        run_report()
    elif args.mode == "run":
        run_backend()
    else:
        run_status()


if __name__ == "__main__":
    main()