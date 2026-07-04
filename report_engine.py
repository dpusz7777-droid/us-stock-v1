#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B5: 将回测、分析与优化结果合并为结构化策略报告。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


class ReportEngine:
    """生成确定性、可读且可机器消费的策略报告。"""

    def __init__(
        self,
        engine: Any,
        analytics_engine: Any,
        optimizer_result: dict,
        historical_data: dict,
    ) -> None:
        self.engine = engine
        self.analytics_engine = analytics_engine
        self.optimizer_result = optimizer_result
        self.historical_data = historical_data

    def _extract_metrics(self) -> dict[str, float]:
        """调用 AnalyticsEngine 并规范化指标类型。"""
        analyzer = self.analytics_engine
        if isinstance(analyzer, type):
            analyzer = analyzer(
                self.engine.get_equity_curve(),
                getattr(self.engine, "pnl_history", []),
            )
        metrics = analyzer.analyze()
        return {
            "total_return": float(metrics["total_return"]),
            "sharpe_ratio": float(metrics["sharpe_ratio"]),
            "max_drawdown": float(metrics["max_drawdown"]),
            "win_rate": float(metrics["win_rate"]),
        }

    def _extract_diagnostics(self) -> dict[str, Any]:
        """提取 BacktestEngine 的诊断数据。"""
        diagnostics = self.engine.get_diagnostics()
        distribution = {
            str(name): int(count)
            for name, count in diagnostics.get(
                "signal_distribution", {}
            ).items()
        }
        return {
            "signal_distribution": distribution,
            "risk_events": int(diagnostics.get(
                "risk_events", distribution.get("RISK_OFF", 0)
            )),
            "trade_count": int(diagnostics.get("total_trades", 0)),
        }

    def _merge_optimizer_results(self) -> dict[str, Any]:
        """提取并复制优化结果，避免报告与源数据共享可变对象。"""
        return {
            "best_config": deepcopy(
                self.optimizer_result.get("best_config", {})
            ),
            "best_score": float(
                self.optimizer_result.get("best_score", 0.0)
            ),
            "top_configs": deepcopy(
                self.optimizer_result.get("top_results", [])
            ),
        }

    @staticmethod
    def _build_insights(
        metrics: dict[str, float],
        diagnostics: dict[str, Any],
    ) -> list[str]:
        """按固定顺序应用规则生成洞察。"""
        insights: list[str] = []
        distribution = diagnostics["signal_distribution"]
        signal_count = sum(distribution.values())
        hold_ratio = (
            distribution.get("HOLD", 0) / signal_count
            if signal_count > 0
            else 0.0
        )
        risk_off_ratio = (
            distribution.get("RISK_OFF", 0) / signal_count
            if signal_count > 0
            else 0.0
        )

        if metrics["sharpe_ratio"] > 1.5:
            insights.append("Strong risk-adjusted performance")
        if metrics["max_drawdown"] > 0.20:
            insights.append("High drawdown risk")
        if metrics["win_rate"] < 0.40:
            insights.append("Low win rate instability")
        if hold_ratio > 0.60:
            insights.append("Over-conservative strategy")
        if risk_off_ratio > 0.20:
            insights.append("High volatility environment detected")
        return insights

    def generate_report(self) -> dict:
        """生成完整报告，不修改任何输入对象。"""
        metrics = self._extract_metrics()
        diagnostics = self._extract_diagnostics()
        optimization = self._merge_optimizer_results()
        equity_curve = [
            float(value) for value in self.engine.get_equity_curve()
        ]

        return {
            "summary": {
                "best_config": optimization["best_config"],
                "total_return_pct": metrics["total_return"] * 100.0,
                "sharpe_ratio": metrics["sharpe_ratio"],
                "max_drawdown": metrics["max_drawdown"],
                "win_rate": metrics["win_rate"],
            },
            "diagnostics": diagnostics,
            "optimization": {
                "top_configs": optimization["top_configs"],
                "best_score": optimization["best_score"],
            },
            "equity": {
                "curve": equity_curve,
                "final_value": (
                    equity_curve[-1] if equity_curve else 0.0
                ),
            },
            "insights": self._build_insights(metrics, diagnostics),
        }
