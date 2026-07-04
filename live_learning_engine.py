#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LiveLearningEngine — 实时学习与自适应层。

架构说明
--------
LiveLearningEngine 让系统具备根据真实（或模拟）交易结果自动调整策略权重和参数的能力。
它记录每笔交易的结果，跟踪连续盈亏，并根据市场状态输出自适应更新。

输入:
- strategy_type (str): 策略类型
- pnl (float): 单笔盈亏金额
- drawdown (float): 当前回撤 %
- win_rate (float): 近期胜率
- market_regime (str): BULL/BEAR/CHOPPY/HIGH_RISK

输出:
- AdaptiveUpdate { strategy_weight_adjustment, risk_adjustment_factor, confidence_update, learning_signal }

不修改任何现有模块: MarketRegime/Strategy/Optimizer/Signal/Risk/Decision/Execution/Portfolio/CapitalGuard。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from event_bus import event_bus
from events import LIVE_LEARNING_UPDATED
from strategy_engine import StrategyType


# ---------------------------------------------------------------------------
# Learning signal
# ---------------------------------------------------------------------------


class LearningSignal(str, Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"


# ---------------------------------------------------------------------------
# Adaptation Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdaptiveUpdate:
    """自适应更新结果。"""

    strategy_type: str
    weight_adjustment: float         # -0.5 ~ +0.5
    risk_adjustment_factor: float    # 0~1
    confidence_update: float         # -0.3 ~ +0.3
    learning_signal: LearningSignal
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    reason: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_type": self.strategy_type,
            "weight_adjustment": self.weight_adjustment,
            "risk_adjustment_factor": self.risk_adjustment_factor,
            "confidence_update": self.confidence_update,
            "learning_signal": self.learning_signal.value,
            "consecutive_wins": self.consecutive_wins,
            "consecutive_losses": self.consecutive_losses,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }

    def __repr__(self) -> str:
        return (
            f"AdaptiveUpdate(type={self.strategy_type}, "
            f"signal={self.learning_signal.value}, "
            f"weight_adj={self.weight_adjustment:+.2f})"
        )


# ---------------------------------------------------------------------------
# LiveLearningEngine
# ---------------------------------------------------------------------------


class LiveLearningEngine:
    """实时学习引擎。

    跟踪每个策略的连续盈亏，根据结果和市况输出自适应参数调整。

    学习规则:
    1. 连续盈利 → weight +0.1 (最多 +0.5)
    2. win_rate > 60% → confidence +0.1
    3. 连续亏损 → weight -0.2 (最多 -0.5)
    4. drawdown > 10% → risk_factor -0.3
    5. BULL 强化 MOMENTUM, BEAR 强化 DEFENSIVE, CHOPPY 强化 MEAN_REVERSION
    """

    # 学习参数
    WIN_WEIGHT_BOOST = 0.1
    MAX_WEIGHT_BOOST = 0.5
    LOSS_WEIGHT_PENALTY = -0.2
    MAX_WEIGHT_PENALTY = -0.5
    HIGH_WIN_CONFIDENCE_BOOST = 0.1
    HIGH_WIN_THRESHOLD = 0.6
    DD_RISK_PENALTY = -0.3
    DD_THRESHOLD = 10.0

    # 市场强化乘数
    BULL_BOOST = {StrategyType.MOMENTUM.value: 0.15, StrategyType.BREAKOUT.value: 0.1}
    BEAR_BOOST = {StrategyType.DEFENSIVE.value: 0.15, StrategyType.MEAN_REVERSION.value: 0.1}
    CHOPPY_BOOST = {StrategyType.MEAN_REVERSION.value: 0.15}
    HIGH_RISK_PENALTY = 0.5

    def __init__(self) -> None:
        # 策略学习状态 {strategy: {"wins": int, "losses": int, "total_trades": int}}
        self._state: dict[str, dict[str, int]] = {}

    def record_trade(
        self,
        strategy_type: str,
        pnl: float = 0.0,
        drawdown: float = 0.0,
        win_rate: float = 0.0,
        market_regime: str = "",
    ) -> AdaptiveUpdate:
        """记录一笔交易并返回自适应更新。

        Args:
            strategy_type: 策略类型
            pnl: 盈亏金额
            drawdown: 当前回撤 %
            win_rate: 近期胜率
            market_regime: 市场状态

        Returns:
            AdaptiveUpdate
        """
        # 初始化状态
        if strategy_type not in self._state:
            self._state[strategy_type] = {"wins": 0, "losses": 0, "total_trades": 0}

        state = self._state[strategy_type]
        state["total_trades"] += 1

        # 更新连续盈亏
        is_win = pnl > 0
        if is_win:
            state["wins"] += 1
            state["losses"] = 0
        else:
            state["losses"] += 1
            state["wins"] = 0

        consecutive_wins = state["wins"]
        consecutive_losses = state["losses"]

        # ---- 计算调整 ----
        reasons: list[str] = []
        weight_adj = 0.0
        risk_factor = 1.0
        conf_adj = 0.0

        # (1) 连续盈利强化
        if consecutive_wins >= 2:
            boost = min(self.WIN_WEIGHT_BOOST * consecutive_wins, self.MAX_WEIGHT_BOOST)
            weight_adj += boost
            reasons.append(f"连胜{consecutive_wins}次: weight+{boost:.2f}")

        # (2) 高胜率增强信心
        if win_rate > self.HIGH_WIN_THRESHOLD:
            conf_adj += self.HIGH_WIN_CONFIDENCE_BOOST
            reasons.append(f"胜率{win_rate:.0%}>60%: confidence+0.1")

        # (3) 连续亏损削弱
        if consecutive_losses >= 1:
            penalty = max(self.LOSS_WEIGHT_PENALTY * consecutive_losses, self.MAX_WEIGHT_PENALTY)
            weight_adj += penalty
            reasons.append(f"连亏{consecutive_losses}次: weight{penalty:.2f}")
            # 降低风险
            risk_factor = max(0.3, risk_factor + min(-0.1 * consecutive_losses, -0.5))

        # (4) 高回撤降风险
        if drawdown > self.DD_THRESHOLD:
            risk_factor = max(0.2, risk_factor + self.DD_RISK_PENALTY)
            reasons.append(f"回撤{drawdown:.1f}%>10%: risk-0.3")

        # (5) 市场状态调整
        regime = market_regime or ""
        if regime == "BULL":
            boost = self.BULL_BOOST.get(strategy_type, 0.0)
            if boost != 0:
                weight_adj += boost
                reasons.append(f"BULL强化{strategy_type}: +{boost:.2f}")
        elif regime == "BEAR":
            boost = self.BEAR_BOOST.get(strategy_type, 0.0)
            if boost != 0:
                weight_adj += boost
                reasons.append(f"BEAR强化{strategy_type}: +{boost:.2f}")
        elif regime == "CHOPPY":
            boost = self.CHOPPY_BOOST.get(strategy_type, 0.0)
            if boost != 0:
                weight_adj += boost
                reasons.append(f"CHOPPY强化{strategy_type}: +{boost:.2f}")
        elif regime == "HIGH_RISK":
            weight_adj += -self.MAX_WEIGHT_BOOST * (1 - self.HIGH_RISK_PENALTY)
            reasons.append(f"HIGH_RISK: 所有权重×{self.HIGH_RISK_PENALTY}")

        # 裁剪
        weight_adj = max(self.MAX_WEIGHT_PENALTY, min(self.MAX_WEIGHT_BOOST, weight_adj))
        risk_factor = max(0.1, min(1.0, risk_factor))
        conf_adj = max(-0.3, min(0.3, conf_adj))

        # 学习信号
        if weight_adj > 0:
            signal = LearningSignal.POSITIVE
        elif weight_adj < 0:
            signal = LearningSignal.NEGATIVE
        else:
            signal = LearningSignal.NEUTRAL

        result = AdaptiveUpdate(
            strategy_type=strategy_type,
            weight_adjustment=round(weight_adj, 4),
            risk_adjustment_factor=round(risk_factor, 4),
            confidence_update=round(conf_adj, 4),
            learning_signal=signal,
            consecutive_wins=consecutive_wins,
            consecutive_losses=consecutive_losses,
            reason="; ".join(reasons) if reasons else "无调整",
        )

        event_bus.publish(LIVE_LEARNING_UPDATED, {
            "adaptive_update": result.to_dict(),
        })

        return result

    def reset_state(self, strategy_type: str | None = None) -> None:
        """重置学习状态（用于测试）。"""
        if strategy_type:
            self._state.pop(strategy_type, None)
        else:
            self._state.clear()


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

live_learning_engine = LiveLearningEngine()