#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回测策略绩效分析模块（仅使用 Python 标准库）。"""

from __future__ import annotations

import math
from typing import Iterable


class AnalyticsEngine:
    """根据净值曲线和逐笔盈亏计算标准绩效指标。"""

    def __init__(
        self,
        equity_curve: list[float],
        pnl_history: list[float] | None = None,
    ) -> None:
        self.equity_curve = self._to_floats(equity_curve)
        self.pnl_history = self._to_floats(pnl_history or [])

    @staticmethod
    def _to_floats(values: Iterable[float]) -> list[float]:
        return [float(value) for value in values]

    def _total_return(self) -> float:
        if len(self.equity_curve) < 2 or self.equity_curve[0] == 0.0:
            return 0.0
        return (
            self.equity_curve[-1] - self.equity_curve[0]
        ) / self.equity_curve[0]

    def _max_drawdown(self) -> float:
        if not self.equity_curve:
            return 0.0

        peak = self.equity_curve[0]
        max_drawdown = 0.0
        for value in self.equity_curve:
            if value > peak:
                peak = value
            if peak != 0.0:
                drawdown = (peak - value) / peak
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
        return max_drawdown

    def _sharpe_ratio(self) -> float:
        returns = [
            (current - previous) / previous
            for previous, current in zip(
                self.equity_curve, self.equity_curve[1:]
            )
            if previous != 0.0
        ]
        if not returns:
            return 0.0

        mean_return = sum(returns) / len(returns)
        variance = sum(
            (value - mean_return) ** 2 for value in returns
        ) / len(returns)
        standard_deviation = math.sqrt(variance)
        return mean_return / standard_deviation if standard_deviation else 0.0

    def _win_rate(self) -> float:
        if not self.pnl_history:
            return 0.0
        wins = sum(1 for pnl in self.pnl_history if pnl > 0.0)
        return wins / len(self.pnl_history)

    def _profit_factor(self) -> float:
        gross_profit = sum(pnl for pnl in self.pnl_history if pnl > 0.0)
        gross_loss = sum(pnl for pnl in self.pnl_history if pnl < 0.0)
        if gross_loss == 0.0:
            return math.inf if gross_profit > 0.0 else 0.0
        return gross_profit / abs(gross_loss)

    def analyze(self) -> dict:
        """返回策略绩效指标。"""
        return {
            "total_return": self._total_return(),
            "max_drawdown": self._max_drawdown(),
            "sharpe_ratio": self._sharpe_ratio(),
            "win_rate": self._win_rate(),
            "profit_factor": self._profit_factor(),
        }
