#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""策略评估器 — 预测准确率 + 策略评分。

评估策略的历史表现和预测准确度。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from northstar.data.trade_history import TradeHistory, TradeRecord
from northstar.core.strategy_feedback import compute_strategy_score, save_feedback, load_feedback


@dataclass(frozen=True)
class PredictionResult:
    """一次预测的结果。"""
    symbol: str
    predicted_action: str
    actual_outcome: float  # 实际收益率 %
    correct: bool  # 预测方向是否正确
    confidence: float


@dataclass(frozen=True)
class EvaluationReport:
    """策略评估报告。"""
    total_predictions: int
    accuracy: float  # 0-1
    avg_return: float
    win_rate: float
    max_drawdown: float
    sharpe_ratio: float
    profit_factor: float  # 总盈利/总亏损
    total_return_pct: float  # 总收益率
    summary: str


class Evaluator:
    """策略评估器。

    用法：
        eval = Evaluator()
        report = eval.evaluate()
        accuracy = eval.accuracy()
    """

    def __init__(self, history: TradeHistory | None = None) -> None:
        self._history = history or TradeHistory()

    def evaluate(self) -> EvaluationReport:
        """评估策略整体表现。"""
        trades = self._history.recent(100)
        if not trades:
            return EvaluationReport(
                total_predictions=0, accuracy=0.0, avg_return=0.0,
                win_rate=0.0, max_drawdown=0.0, sharpe_ratio=0.0,
                profit_factor=0.0, total_return_pct=0.0,
                summary="暂无交易数据。",
            )

        with_pnl = [t for t in trades if t.pnl is not None]
        if not with_pnl:
            return EvaluationReport(
                total_predictions=len(trades), accuracy=0.0, avg_return=0.0,
                win_rate=0.0, max_drawdown=0.0, sharpe_ratio=0.0,
                profit_factor=0.0, total_return_pct=0.0,
                summary="交易数据缺少盈亏信息。",
            )

        total = len(with_pnl)
        wins = sum(1 for t in with_pnl if t.pnl and t.pnl > 0)
        returns = [t.pnl or 0.0 for t in with_pnl]

        accuracy = wins / total if total > 0 else 0.0
        avg_ret = sum(returns) / len(returns) if returns else 0.0
        win_rate = wins / total if total > 0 else 0.0
        max_dd = min(0, min(returns)) if returns else 0.0

        # Profit Factor = total_gains / total_losses
        gains = sum(r for r in returns if r > 0)
        losses = abs(sum(r for r in returns if r < 0))
        profit_factor = gains / losses if losses > 0 else (gains if gains > 0 else 0.0)

        # Total Return % (sum of all returns)
        total_return_pct = sum(returns)

        # Simplified Sharpe: mean / std
        import math
        if len(returns) > 1:
            mean = sum(returns) / len(returns)
            variance = sum((r - mean) ** 2 for r in returns) / len(returns)
            std = math.sqrt(variance) if variance > 0 else 1.0
            sharpe = mean / std if std > 0 else 0.0
        else:
            sharpe = 0.0

        if accuracy >= 0.6 and avg_ret > 0:
            summary = f"策略表现良好：准确率 {accuracy:.0%}，平均收益 {avg_ret:+.2f}%，总收益 {total_return_pct:+.2f}%。"
        elif accuracy >= 0.4:
            summary = f"策略表现中等：准确率 {accuracy:.0%}，平均收益 {avg_ret:+.2f}%。"
        else:
            summary = f"策略表现偏弱：准确率 {accuracy:.0%}，平均收益 {avg_ret:+.2f}%。"

        return EvaluationReport(
            total_predictions=total,
            accuracy=round(accuracy, 4),
            avg_return=round(avg_ret, 2),
            win_rate=round(win_rate, 4),
            max_drawdown=round(max_dd, 2),
            sharpe_ratio=round(sharpe, 4),
            profit_factor=round(profit_factor, 2),
            total_return_pct=round(total_return_pct, 2),
            summary=summary,
        )

    def compute_and_save_feedback(self) -> dict[str, Any]:
        """评估策略并保存反馈到 strategy_feedback.json。
        
        Returns:
            策略反馈字典（含 strategy_score）
        """
        report = self.evaluate()
        fb = compute_strategy_score(
            win_rate=report.win_rate,
            profit_factor=report.profit_factor,
            max_drawdown=report.max_drawdown,
            total_return_pct=report.total_return_pct,
            num_trades=report.total_predictions,
        )
        save_feedback(fb)
        return {
            "strategy_score": fb.strategy_score,
            "win_rate": fb.win_rate,
            "profit_factor": fb.profit_factor,
            "max_drawdown": fb.max_drawdown,
            "trend_accuracy": fb.trend_accuracy,
            "risk_level": fb.risk_level,
            "adaptability": fb.adaptability,
            "summary": fb.summary,
        }

    def accuracy(self) -> float:
        """快速获取准确率。"""
        return self.evaluate().accuracy

    def by_symbol(self, symbol: str) -> EvaluationReport:
        """按标的评估。"""
        trades = self._history.by_symbol(symbol)
        if not trades:
            return EvaluationReport(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, f"{symbol} 无交易数据。")

        wins = sum(1 for t in trades if t.pnl and t.pnl > 0)
        total = len(trades)
        returns = [t.pnl or 0.0 for t in trades]
        avg_ret = sum(returns) / len(returns) if returns else 0.0
        total_ret = sum(returns)
        gains = sum(r for r in returns if r > 0)
        losses = abs(sum(r for r in returns if r < 0))
        pf = gains / losses if losses > 0 else (gains if gains > 0 else 0.0)

        return EvaluationReport(
            total_predictions=total,
            accuracy=round(wins / total, 4) if total > 0 else 0.0,
            avg_return=round(avg_ret, 2),
            win_rate=round(wins / total, 4) if total > 0 else 0.0,
            max_drawdown=round(min(0, min(returns)), 2) if returns else 0.0,
            sharpe_ratio=0.0,
            profit_factor=round(pf, 2),
            total_return_pct=round(total_ret, 2),
            summary=f"{symbol}: {wins}/{total} 胜，平均 {avg_ret:+.2f}%，总收益 {total_ret:+.2f}%。",
        )
