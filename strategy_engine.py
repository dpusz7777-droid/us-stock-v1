#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
StrategyEngine — 策略引擎层。

架构说明
--------
StrategyEngine 在 SignalEngine 之上提供多策略选择 + 自动切换能力。
它根据市场状态（MarketRegime）、资金模式（CapitalMode）和技术指标，
选择最佳策略并输出策略信号。

输入:
- market_regime: BULL / BEAR / CHOPPY / HIGH_RISK
- capital_mode: NORMAL / CAUTION / DEFENSIVE / LOCKDOWN
- price_series: list[Decimal]
- volatility: float
- trend_strength: float

输出:
- StrategySignal: { strategy_type, signal_strength, confidence, reason }

策略规则:
- BULL: 趋势跟随 > 突破 > 均值回归(禁止)
- BEAR: 防守 > 均值回归(反弹) > 趋势跟随(禁止追涨)
- CHOPPY: 均值回归(高抛低吸) > 防守
- HIGH_RISK: 防守(信号强度×0.5)

不修改 SignalEngine / RiskEngine / DecisionEngine / ExecutionEngine / 任何引擎。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from event_bus import event_bus
from events import STRATEGY_SELECTED
from market_regime_engine import MarketRegime
from capital_guard import CapitalMode


# ---------------------------------------------------------------------------
# Strategy types
# ---------------------------------------------------------------------------


class StrategyType(str, Enum):
    MOMENTUM = "MOMENTUM"           # 趋势跟随
    MEAN_REVERSION = "MEAN_REVERSION"  # 均值回归
    DEFENSIVE = "DEFENSIVE"          # 防守
    BREAKOUT = "BREAKOUT"           # 突破


# ---------------------------------------------------------------------------
# StrategySignal
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StrategySignal:
    """策略引擎输出信号。"""

    strategy_type: StrategyType
    signal_strength: float          # 0–1 信号强度
    confidence: float                # 0–1 置信度
    reason: str                      # 选择理由
    market_regime: str = ""
    capital_mode: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_type": self.strategy_type.value,
            "signal_strength": self.signal_strength,
            "confidence": self.confidence,
            "reason": self.reason,
            "market_regime": self.market_regime,
            "capital_mode": self.capital_mode,
            "timestamp": self.timestamp,
        }

    def __repr__(self) -> str:
        return (
            f"StrategySignal(type={self.strategy_type.value}, "
            f"strength={self.signal_strength:.2f}, conf={self.confidence:.2f})"
        )


# ---------------------------------------------------------------------------
# StrategyEngine
# ---------------------------------------------------------------------------


class StrategyEngine:
    """策略选择引擎。根据市场和资金状态自动切换策略。"""

    # 策略基础强度
    BASE_STRENGTH = {
        StrategyType.MOMENTUM: 0.7,
        StrategyType.MEAN_REVERSION: 0.6,
        StrategyType.DEFENSIVE: 0.5,
        StrategyType.BREAKOUT: 0.6,
    }

    # 策略置信度
    BASE_CONFIDENCE = {
        StrategyType.MOMENTUM: 0.7,
        StrategyType.MEAN_REVERSION: 0.5,
        StrategyType.DEFENSIVE: 0.8,
        StrategyType.BREAKOUT: 0.5,
    }

    # CapitalMode 乘数
    CAPITAL_MULTIPLIERS = {
        CapitalMode.NORMAL: 1.0,
        CapitalMode.CAUTION: 0.8,
        CapitalMode.DEFENSIVE: 0.5,
        CapitalMode.LOCKDOWN: 0.0,
    }

    def select(
        self,
        market_regime: str = "",
        capital_mode: str = "",
        price_series: list[Decimal] | None = None,
        **kwargs: Any,
    ) -> StrategySignal:
        """根据输入选择最佳策略。

        Args:
            market_regime: 市场状态
            capital_mode: 资金模式
            price_series: 价格序列（用于技术指标计算）
            **kwargs: 扩展参数

        Returns:
            StrategySignal
        """
        regime = market_regime or ""
        cap_mode = capital_mode or ""

        # 默认策略
        strategy = StrategyType.DEFENSIVE
        strength = 0.3
        confidence = 0.5
        reasons: list[str] = []

        # ---- 根据市场状态选择策略 ----
        if regime == MarketRegime.BULL.value:
            # 牛市优先趋势跟随
            if self._trend_following_condition(price_series):
                strategy = StrategyType.MOMENTUM
                strength = self.BASE_STRENGTH[StrategyType.MOMENTUM]
                confidence = self.BASE_CONFIDENCE[StrategyType.MOMENTUM]
                reasons.append("BULL: 趋势跟随优先")
            else:
                strategy = StrategyType.BREAKOUT
                strength = self.BASE_STRENGTH[StrategyType.BREAKOUT] * 0.9
                confidence = self.BASE_CONFIDENCE[StrategyType.BREAKOUT]
                reasons.append("BULL: 突破策略次优")

        elif regime == MarketRegime.BEAR.value:
            # 熊市优先防守
            if cap_mode == CapitalMode.DEFENSIVE.value or cap_mode == CapitalMode.LOCKDOWN.value:
                strategy = StrategyType.DEFENSIVE
                strength = 0.3
                confidence = 0.9
                reasons.append("BEAR + DEFENSIVE: 强制防守")
            else:
                strategy = StrategyType.DEFENSIVE
                strength = self.BASE_STRENGTH[StrategyType.DEFENSIVE] * 0.7
                confidence = self.BASE_CONFIDENCE[StrategyType.DEFENSIVE]
                reasons.append("BEAR: 防守策略，允许反弹卖出")

        elif regime == MarketRegime.CHOPPY.value:
            # 震荡优先均值回归
            if self._mean_reversion_condition(price_series):
                strategy = StrategyType.MEAN_REVERSION
                strength = self.BASE_STRENGTH[StrategyType.MEAN_REVERSION]
                confidence = self.BASE_CONFIDENCE[StrategyType.MEAN_REVERSION]
                reasons.append("CHOPPY: 均值回归高抛低吸")
            else:
                strategy = StrategyType.DEFENSIVE
                strength = 0.4
                confidence = 0.6
                reasons.append("CHOPPY: 降低交易频率")

        elif regime == MarketRegime.HIGH_RISK.value:
            # 高风险只允许防守
            strategy = StrategyType.DEFENSIVE
            strength = self.BASE_STRENGTH[StrategyType.DEFENSIVE] * 0.5
            confidence = self.BASE_CONFIDENCE[StrategyType.DEFENSIVE] * 1.2
            reasons.append("HIGH_RISK: 防守策略，信号强度×0.5")

        else:
            # 未知状态默认防守
            strategy = StrategyType.DEFENSIVE
            strength = self.BASE_STRENGTH[StrategyType.DEFENSIVE] * 0.5
            confidence = self.BASE_CONFIDENCE[StrategyType.DEFENSIVE]
            reasons.append(f"UNKNOWN({regime}): 默认防守策略")

        # ---- 应用 CapitalMode 乘数 ----
        cap_mult = self.CAPITAL_MULTIPLIERS.get(CapitalMode(cap_mode), 1.0) if cap_mode in [m.value for m in CapitalMode] else 1.0
        strength *= cap_mult
        if cap_mode != CapitalMode.NORMAL.value and cap_mode:
            reasons.append(f"CapitalMode={cap_mode}: strength×{cap_mult}")

        # 最终裁剪
        strength = max(0.0, min(1.0, strength))
        confidence = max(0.0, min(1.0, confidence))

        signal = StrategySignal(
            strategy_type=strategy,
            signal_strength=round(strength, 4),
            confidence=round(confidence, 4),
            reason="; ".join(reasons),
            market_regime=regime,
            capital_mode=cap_mode,
        )

        # 发布事件
        event_bus.publish(STRATEGY_SELECTED, {
            "strategy_signal": signal.to_dict(),
        })

        return signal

    # ------------------------------------------------------------------
    # 内部条件判断
    # ------------------------------------------------------------------

    @staticmethod
    def _trend_following_condition(prices: list[Decimal] | None) -> bool:
        """判断是否满足趋势跟随条件：短期均线上穿长期均线。"""
        if not prices or len(prices) < 50:
            return False
        short = sum(prices[-20:]) / Decimal("20")
        long = sum(prices[-50:]) / Decimal("50")
        return short > long

    @staticmethod
    def _mean_reversion_condition(prices: list[Decimal] | None) -> bool:
        """判断是否满足均值回归条件：价格在均线附近波动，且价格方向无明显趋势。"""
        if not prices or len(prices) < 25:
            return False
        sma20 = sum(prices[-20:]) / Decimal("20")
        sma50 = sum(prices[-50:]) / Decimal("50") if len(prices) >= 50 else sma20
        current = prices[-1]
        deviation = abs(current - sma20) / sma20 * Decimal("100") if sma20 > Decimal("0") else Decimal("0")
        # 价格在均线附近（1-8%偏离）
        if not (Decimal("1") <= deviation <= Decimal("8")):
            return False
        # 无强趋势（短期均线与长期均线接近）
        if abs(sma20 - sma50) / sma50 * Decimal("100") > Decimal("3"):
            return False
        return True


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

strategy_engine = StrategyEngine()