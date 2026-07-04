#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B8: UI Service Layer — 提供供 UI 消费的结构化数据。

严格遵守数据流：
    engine → controller → ui_service → api → ui

禁止：
    - 调用核心引擎逻辑
    - 执行策略计算
    - 反向依赖 UI 模块
"""

from __future__ import annotations

import json
import math
from decimal import Decimal
from typing import Any

from system_controller import SystemController


def _json_safe(value: Any) -> Any:
    """递归转换为严格 JSON 可编码值。"""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class UIDataService:
    """为 UI 提供格式化后的只读数据。

    所有数据来自 SystemController，UI 层不执行任何计算。
    """

    def __init__(self, controller: SystemController | None = None):
        self._controller = controller or SystemController()

    def get_backtest_data(self, symbol: str = "NVDA") -> dict:
        """返回 UI 渲染回测视图所需数据。"""
        raw = self._controller.run_backtest(symbol)
        return self._format_backtest(raw)

    def get_optimizer_data(self, symbol: str = "NVDA") -> dict:
        """返回 UI 渲染策略优化结果所需数据。"""
        raw = self._controller.run_optimization(symbol)
        return self._format_optimizer(raw)

    def get_report_data(self, symbol: str = "NVDA") -> dict:
        """返回 UI 渲染报告所需数据。"""
        raw = self._controller.run_full_pipeline(symbol)
        return self._format_report(raw)

    def get_strategy_list(self, symbol: str = "NVDA") -> list[dict]:
        """返回所有策略结果列表，供 UI 排序/筛选/对比。"""
        raw = self._controller.run_optimization(symbol)
        top_results = raw.get("top_results", [])
        strategies = []
        for entry in top_results:
            config = entry.get("config", {})
            score = entry.get("score", 0.0)
            strategies.append({
                "id": f"strategy_{len(strategies)}",
                "score": score,
                "config": config,
                "metrics": {
                    "momentum": config.get("momentum_threshold", 0.0),
                    "mean_reversion": config.get("mean_reversion_threshold", 0.0),
                    "volatility": config.get("volatility_threshold", 0.0),
                    "risk_penalty": config.get("risk_penalty", 1.0),
                },
            })
        return strategies

    def _format_backtest(self, raw: dict) -> dict:
        """抽取 equity curve、trade markers 等信息。"""
        equity_curve = raw.get("equity_curve", [])
        symbols_data = raw.get("symbols", {})
        summary = raw.get("summary", {})

        # 提取交易标记点
        trade_markers: list[dict] = []
        for sym_name, sym_result in symbols_data.items():
            trades = sym_result.get("trades", [])
            for t in trades:
                trade_markers.append({
                    "symbol": sym_name,
                    "date": t.get("date", ""),
                    "action": t.get("action", ""),
                    "price": float(t.get("price", 0)),
                    "qty": float(t.get("qty", 0)),
                    "pnl": float(t.get("pnl", 0)) if t.get("pnl") else None,
                    "cost": float(t.get("cost", 0)) if t.get("cost") else None,
                })

        # 性能摘要
        perf: dict[str, Any] = {
            "total_return_pct": float(summary.get("total_return_pct", "0")),
            "total_trade_count": int(summary.get("total_trade_count", 0)),
            "avg_win_rate": float(summary.get("avg_win_rate", 0.0)),
            "symbols": list(summary.get("symbols", [])),
        }

        # 个股详情
        symbol_details: dict[str, dict] = {}
        for sym_name, sym_result in symbols_data.items():
            symbol_details[sym_name] = {
                "win_rate": float(sym_result.get("win_rate", 0.0)),
                "trade_count": int(sym_result.get("trade_count", 0)),
                "profit_loss_ratio": float(sym_result.get("profit_loss_ratio", 0.0)),
                "max_drawdown": float(sym_result.get("max_drawdown", "0")),
                "total_return_pct": float(sym_result.get("total_return_pct", "0")),
                "final_equity": float(sym_result.get("final_equity", "0")),
                "initial_cash": float(sym_result.get("initial_cash", "0")),
                "avg_win": float(sym_result.get("avg_win", "0")),
                "avg_loss": float(sym_result.get("avg_loss", "0")),
                "trades": [
                    {
                        "date": t.get("date", ""),
                        "action": t.get("action", ""),
                        "price": float(t.get("price", 0)),
                        "qty": float(t.get("qty", 0)),
                        "pnl": float(t.get("pnl", 0)) if t.get("pnl") else None,
                    }
                    for t in sym_result.get("trades", [])
                ],
            }

        return {
            "equity_curve": [float(v) for v in equity_curve] if equity_curve else [],
            "trade_markers": trade_markers,
            "performance": perf,
            "symbol_details": symbol_details,
        }

    def _format_optimizer(self, raw: dict) -> dict:
        """抽取 optimizer 结果。"""
        best_config = raw.get("best_config", {})
        best_score = raw.get("best_score", 0.0)
        top_results = raw.get("top_results", [])

        strategies = []
        for idx, entry in enumerate(top_results):
            config = entry.get("config", {})
            strategies.append({
                "id": f"strategy_{idx}",
                "rank": idx + 1,
                "score": entry.get("score", 0.0),
                "config": {
                    "momentum_threshold": config.get("momentum_threshold", 0.0),
                    "mean_reversion_threshold": config.get("mean_reversion_threshold", 0.0),
                    "volatility_threshold": config.get("volatility_threshold", 0.0),
                    "risk_penalty": config.get("risk_penalty", 0.0),
                },
            })

        return {
            "best_config": best_config,
            "best_score": best_score,
            "strategy_count": len(strategies),
            "strategies": strategies,
        }

    def _format_report(self, raw: dict) -> dict:
        """抽取完整报告数据。"""
        report = raw.get("report", {})
        analysis = raw.get("analysis", {})
        backtest = raw.get("backtest", {})
        optimization = raw.get("optimization", {})

        # 摘要指标
        summary = report.get("summary", {})
        diagnostics = report.get("diagnostics", {})
        signal_dist = diagnostics.get("signal_distribution", {})

        # equity 曲线
        equity = report.get("equity", {})
        equity_curve = equity.get("curve", [])

        return {
            "performance_summary": {
                "total_return_pct": float(summary.get("total_return_pct", 0.0)),
                "sharpe_ratio": float(summary.get("sharpe_ratio", 0.0)),
                "max_drawdown": float(summary.get("max_drawdown", 0.0)),
                "win_rate": float(summary.get("win_rate", 0.0)),
            },
            "risk_metrics": {
                "max_drawdown": float(analysis.get("max_drawdown", 0.0)),
                "sharpe_ratio": float(analysis.get("sharpe_ratio", 0.0)),
                "profit_factor": float(analysis.get("profit_factor", 0.0)) if analysis.get("profit_factor") else None,
                "total_return": float(analysis.get("total_return", 0.0)),
                "win_rate": float(analysis.get("win_rate", 0.0)),
            },
            "optimizer_results": {
                "best_config": optimization.get("best_config", {}),
                "best_score": optimization.get("best_score", 0.0),
                "top_results": [
                    {
                        "score": entry.get("score", 0.0),
                        "config": entry.get("config", {}),
                    }
                    for entry in optimization.get("top_results", [])
                ],
            },
            "signal_breakdown": {
                "BUY": signal_dist.get("BUY", 0),
                "SELL": signal_dist.get("SELL", 0),
                "HOLD": signal_dist.get("HOLD", 0),
                "REDUCE": signal_dist.get("REDUCE", 0),
                "RISK_OFF": signal_dist.get("RISK_OFF", 0),
            },
            "equity_curve": [float(v) for v in equity_curve] if equity_curve else [],
            "insights": report.get("insights", []),
        }