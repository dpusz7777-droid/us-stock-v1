#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
StrategyOptimizer — 策略优化层。

架构说明
--------
StrategyOptimizer 在 StrategyEngine 之上提供策略表现评估 + 自动权重调整。
它根据回测结果、市场状态和策略表现，计算每个策略的最优权重。

输入:
- strategy_type (str): 来自 StrategyEngine
- backtest_result (dict): 收益率/最大回撤/交易次数
- market_regime (str): BULL/BEAR/CHOPPY/HIGH_RISK

输出:
- StrategyWeight: { strategy_type, weight, expected_return, max_drawdown, confidence_score }

不修改任何现有模块: Signal/Risk/Decision/Execution/Position/Portfolio/CapitalGuard/MarketRegime。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from event_bus import event_bus
from events import STRATEGY_WEIGHT_UPDATED
from strategy_engine import StrategyType


# ---------------------------------------------------------------------------
# StrategyWeight
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StrategyWeight:
    """策略权重结果。"""

    strategy_type: str
    weight: float                    # 0–1
    expected_return: float = 0.0
    max_drawdown: float = 0.0
    confidence_score: float = 0.0    # 0–1
    reason: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_type": self.strategy_type,
            "weight": self.weight,
            "expected_return": self.expected_return,
            "max_drawdown": self.max_drawdown,
            "confidence_score": self.confidence_score,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }

    def __repr__(self) -> str:
        return (
            f"StrategyWeight(type={self.strategy_type}, "
            f"weight={self.weight:.2f}, conf={self.confidence_score:.2f})"
        )


# ---------------------------------------------------------------------------
# StrategyOptimizer
# ---------------------------------------------------------------------------


class StrategyOptimizer:
    """策略优化引擎。根据历史表现和市场状态调整策略权重。"""

    # 权重映射
    WEIGHT_MAP = {
        "high": 1.0,
        "medium_high": 0.7,
        "medium": 0.4,
        "low": 0.1,
    }

    # BULL regime 强化
    BULL_BOOST = {
        StrategyType.MOMENTUM.value: 1.2,
        StrategyType.BREAKOUT.value: 1.15,
        StrategyType.MEAN_REVERSION.value: 0.7,
        StrategyType.DEFENSIVE.value: 0.8,
    }

    # BEAR regime 强化
    BEAR_BOOST = {
        StrategyType.DEFENSIVE.value: 1.3,
        StrategyType.MEAN_REVERSION.value: 1.1,
        StrategyType.MOMENTUM.value: 0.5,
        StrategyType.BREAKOUT.value: 0.5,
    }

    # CHOPPY regime 强化
    CHOPPY_BOOST = {
        StrategyType.MEAN_REVERSION.value: 1.3,
        StrategyType.DEFENSIVE.value: 1.1,
        StrategyType.MOMENTUM.value: 0.6,
        StrategyType.BREAKOUT.value: 0.7,
    }

    # HIGH_RISK regime 所有 ×0.5
    HIGH_RISK_PENALTY = 0.5

    def evaluate(
        self,
        strategy_type: str,
        market_regime: str = "",
        total_return_pct: float = 0.0,
        max_drawdown_pct: float = 0.0,
        trade_count: int = 0,
        win_rate: float = 0.0,
        profit_loss_ratio: float = 0.0,
    ) -> StrategyWeight:
        """评估策略表现并计算最优权重。

        Args:
            strategy_type: 策略类型
            market_regime: 市场状态
            total_return_pct: 总收益率 (%)
            max_drawdown_pct: 最大回撤 (%)
            trade_count: 交易次数
            win_rate: 胜率
            profit_loss_ratio: 盈亏比

        Returns:
            StrategyWeight
        """
        regime = market_regime or ""

        # (1) 计算基础分数
        score = self._calculate_score(
            total_return_pct, max_drawdown_pct, trade_count,
            win_rate, profit_loss_ratio,
        )

        # (2) 基础权重
        weight = self._score_to_weight(score)

        # (3) MarketRegime 调整
        boost = 1.0
        if regime == "BULL":
            boost = self.BULL_BOOST.get(strategy_type, 1.0)
        elif regime == "BEAR":
            boost = self.BEAR_BOOST.get(strategy_type, 1.0)
        elif regime == "CHOPPY":
            boost = self.CHOPPY_BOOST.get(strategy_type, 1.0)
        elif regime == "HIGH_RISK":
            boost = self.HIGH_RISK_PENALTY

        weight = min(1.0, weight * boost)

        # (4) 置信度
        confidence = min(1.0, max(0.1, score * 0.8 + win_rate * 0.2))

        # 构造理由
        reasons = [
            f"score={score:.2f}",
            f"boost={boost:.2f}",
            f"regime={regime}",
        ]

        result = StrategyWeight(
            strategy_type=strategy_type,
            weight=round(weight, 4),
            expected_return=round(total_return_pct, 2),
            max_drawdown=round(max_drawdown_pct, 2),
            confidence_score=round(confidence, 4),
            reason="; ".join(reasons),
        )

        event_bus.publish(STRATEGY_WEIGHT_UPDATED, {
            "strategy_weight": result.to_dict(),
        })

        return result

    # ------------------------------------------------------------------
    # 内部评分方法
    # ------------------------------------------------------------------

    def _calculate_score(
        self,
        return_pct: float,
        dd_pct: float,
        trades: int,
        win_rate: float,
        pl_ratio: float,
    ) -> float:
        """策略评分公式。

        规则:
        score = return_score - drawdown_penalty - overtrade_penalty + stability_bonus
        """
        # 收益率评分 (0~1)
        return_score = min(1.0, max(0.0, return_pct / 50.0))

        # 回撤惩罚 (0~1)
        drawdown_penalty = min(1.0, dd_pct / 30.0)

        # 过度交易惩罚 (0~0.5)
        overtrade_penalty = min(0.5, trades / 500.0)

        # 稳定性加分 (基于盈亏比和胜率)
        stability = (win_rate * pl_ratio) / 3.0
        stability_bonus = min(0.3, max(0.0, stability))

        score = return_score - drawdown_penalty - overtrade_penalty + stability_bonus
        return max(0.0, min(1.0, score))

    @staticmethod
    def _score_to_weight(score: float) -> float:
        """将评分映射到权重。"""
        if score > 0.7:
            return 1.0
        elif score >= 0.5:
            return 0.7
        elif score >= 0.3:
            return 0.4
        else:
            return 0.1


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

strategy_optimizer = StrategyOptimizer()