#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B8: ReportGenerator — 将回测结果结构化为可读报告。

用法:
    from report_generator import ReportGenerator
    report = ReportGenerator.build_report(backtest_result)
"""

from __future__ import annotations

from typing import Any


class ReportGenerator:
    """将 backtest 结果转换为标准报告结构。"""

    @staticmethod
    def build_report(backtest_result: dict) -> dict:
        """从 backtest_result 提取关键指标，生成结构化报告。

        Args:
            backtest_result: 来自 system_controller.run_backtest() 的输出，
                             包含 summary, symbols, equity_curve。

        Returns:
            标准报告 dict，包含 title, summary, top_trades, equity_curve, risk_notes。
        """
        # --- 提取 summary 字段（defensive） ---
        summary_raw = backtest_result.get("summary", {})
        total_return_pct_raw = summary_raw.get("total_return_pct", "0")
        win_rate_raw = summary_raw.get("avg_win_rate", 0.0)
        total_trade_count = int(summary_raw.get("total_trade_count", 0))

        # --- 提取 drawdown 和 max_drawdown ---
        # 从 symbols 中收集各标的的最大回撤，取最大值
        symbols_data = backtest_result.get("symbols", {})
        max_drawdown = 0.0
        trades: list[dict] = []
        for sym_name, sym_result in symbols_data.items():
            dd_raw = sym_result.get("max_drawdown", "0")
            try:
                dd = float(dd_raw)
            except (ValueError, TypeError):
                dd = 0.0
            if dd > max_drawdown:
                max_drawdown = dd

            # 收集该标的的交易记录
            sym_trades = sym_result.get("trades", [])
            for t in sym_trades:
                trades.append(t)

        # --- 计算汇总指标 ---
        total_return_pct = _safe_float(total_return_pct_raw)
        win_rate = _safe_float(win_rate_raw)

        # --- 构造 top_trades: 按 pnl 降序取前 5 笔 ---
        top_trades: list[dict] = []
        for t in trades:
            pnl = _safe_float(t.get("pnl", 0))
            pnl_pct = _safe_float(t.get("pnl_pct", 0))
            top_trades.append({
                "symbol": str(t.get("symbol", "UNKNOWN")),
                "pnl": pnl,
                "return_pct": pnl_pct,
            })
        # 按 pnl 绝对值降序排序，取前 5
        top_trades.sort(key=lambda x: abs(x["pnl"]), reverse=True)
        top_trades = top_trades[:5]

        # --- equity_curve: 最多保留最后 50 个点 ---
        equity_curve_raw = backtest_result.get("equity_curve", [])
        if isinstance(equity_curve_raw, list):
            equity_curve = [float(v) for v in equity_curve_raw][-50:]
        else:
            equity_curve = []

        # --- risk_notes ---
        risk_notes: list[str] = []
        if max_drawdown < 2.0:
            risk_notes.append("Low drawdown strategy")
        if win_rate > 0.6:
            risk_notes.append("High win-rate behavior detected")
        if total_trade_count > 100:
            risk_notes.append("High-frequency trading pattern")
        if not risk_notes:
            risk_notes.append("Normal risk profile")

        # --- 构造最终报告 ---
        return {
            "title": "Daily Backtest Report",
            "summary": {
                "total_return_pct": total_return_pct,
                "win_rate": win_rate,
                "max_drawdown": max_drawdown,
                "trade_count": total_trade_count,
            },
            "top_trades": top_trades,
            "equity_curve": equity_curve,
            "risk_notes": risk_notes,
        }


def _safe_float(value: Any, default: float = 0.0) -> float:
    """安全地将值转换为 float。"""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default