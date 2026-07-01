#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PositionEngine — 仓位控制层。

架构说明
--------
PositionEngine 是交易系统的仓位控制层，根据市场状态（MarketRegime）、
风控决策（RiskDecision）和信号置信度（confidence）计算每笔交易的仓位比例。

输入:
- market_regime (str): BULL / BEAR / CHOPPY / HIGH_RISK
- signal_confidence (float): 0–1
- risk_level (str): LOW / MEDIUM / HIGH / CRITICAL / BLOCKED
- current_position_pct (float): 当前该标的仓位 %

输出:
- position_size_pct (float): 0–1，建议仓位占比
- action_override (str | None): 可选的动作覆盖

规则:
BULL:
- confidence > 0.8 → 80% 仓位
- confidence 0.5~0.8 → 50% 仓位
- <0.5 → 20% 仓位

BEAR:
- 只允许 0~30% 仓位
- 强制降低风险敞口

CHOPPY:
- 最大 30% 仓位
- 优先 HOLD

HIGH_RISK:
- 最大 10% 仓位
- 默认只允许防守性操作

安全约束
---------
- 不修改 SignalEngine / RiskEngine / DecisionEngine / ExecutionEngine
- 不接入任何外部 API
- 纯逻辑层
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from event_bus import event_bus
from events import POSITION_CALCULATED
from market_regime_engine import MarketRegime


# ---------------------------------------------------------------------------
# PositionAction (可选动作覆盖)
# ---------------------------------------------------------------------------


class PositionAction(str, Enum):
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    CLOSE = "CLOSE"


# ---------------------------------------------------------------------------
# PositionResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PositionResult:
    """仓位计算结果。不可变。"""

    symbol: str
    position_size_pct: float         # 0–1，建议仓位占比
    action_override: str = ""        # 可选动作覆盖
    confidence_adjusted: float = 0.0  # 调整后的置信度
    regime: str = ""                  # 使用的市场状态
    max_position_pct: float = 1.0    # 该 regime 下最大仓位
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "position_size_pct": self.position_size_pct,
            "action_override": self.action_override,
            "confidence_adjusted": self.confidence_adjusted,
            "regime": self.regime,
            "max_position_pct": self.max_position_pct,
            "timestamp": self.timestamp,
        }

    def __repr___(self) -> str:
        return (
            f"PositionResult(symbol={self.symbol}, size={self.position_size_pct:.1%}, "
            f"regime={self.regime})"
        )


# ---------------------------------------------------------------------------
# PositionEngine
# ---------------------------------------------------------------------------


class PositionEngine:
    """仓位控制引擎。根据市场和信号计算仓位比例。"""

    # BULL 仓位规则
    BULL_HIGH_CONF = 0.8     # 高置信度阈值
    BULL_SIZE_HIGH = 0.8     # 高置信度仓位 80%
    BULL_SIZE_MED = 0.5      # 中置信度仓位 50%
    BULL_SIZE_LOW = 0.2      # 低置信度仓位 20%

    # BEAR 规则
    BEAR_MAX_POSITION = 0.3  # 最大仓位 30%

    # CHOPPY 规则
    CHOPPY_MAX_POSITION = 0.3  # 最大仓位 30%

    # HIGH_RISK 规则
    HIGH_RISK_MAX_POSITION = 0.1  # 最大仓位 10%

    # 风险等级乘数
    RISK_MULTIPLIERS = {
        "LOW": 1.0,
        "MEDIUM": 0.7,
        "HIGH": 0.4,
        "CRITICAL": 0.2,
        "BLOCKED": 0.0,
    }

    def calculate(
        self,
        symbol: str,
        confidence: float,
        risk_level: str = "LOW",
        market_regime: str = "",
        current_position_pct: float = 0.0,
    ) -> PositionResult:
        """计算建议仓位。

        Args:
            symbol: 股票代码
            confidence: 信号置信度 (0–1)
            risk_level: 风控等级 (LOW/MEDIUM/HIGH/CRITICAL/BLOCKED)
            market_regime: 市场状态 (BULL/BEAR/CHOPPY/HIGH_RISK)
            current_position_pct: 当前该标的仓位占比 (0–1)

        Returns:
            PositionResult
        """
        regime = market_regime or ""
        base_size = self._base_size(confidence, regime)
        risk_mult = self.RISK_MULTIPLIERS.get(risk_level, 0.5)
        max_pos = self._max_position(regime)

        # 应用风险乘数和最大仓位限制
        final_size = base_size * risk_mult
        final_size = min(final_size, max_pos)

        # 如果已经有仓位，考虑当前持仓
        action_override = ""
        if final_size < current_position_pct:
            action_override = PositionAction.REDUCE.value

        # 极端情况下强制 CLOSE
        if final_size < 0.05 or risk_level == "BLOCKED":
            action_override = PositionAction.CLOSE.value
            final_size = 0.0

        result = PositionResult(
            symbol=symbol,
            position_size_pct=round(final_size, 4),
            action_override=action_override,
            confidence_adjusted=round(confidence * risk_mult, 4),
            regime=regime,
            max_position_pct=max_pos,
        )

        event_bus.publish(POSITION_CALCULATED, {
            "position_result": result.to_dict(),
        })

        return result

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _base_size(self, confidence: float, regime: str) -> float:
        """根据置信度和市场状态计算基础仓位。"""
        # BULL 规则
        if regime == MarketRegime.BULL.value:
            if confidence > self.BULL_HIGH_CONF:
                return self.BULL_SIZE_HIGH
            elif confidence >= 0.5:
                return self.BULL_SIZE_MED
            else:
                return self.BULL_SIZE_LOW

        # BEAR 规则
        if regime == MarketRegime.BEAR.value:
            return min(self.BEAR_MAX_POSITION, confidence * 0.5)

        # CHOPPY 规则
        if regime == MarketRegime.CHOPPY.value:
            return min(self.CHOPPY_MAX_POSITION, confidence * 0.4)

        # HIGH_RISK 规则
        if regime == MarketRegime.HIGH_RISK.value:
            return min(self.HIGH_RISK_MAX_POSITION, confidence * 0.2)

        # 默认 (无 regime)
        return confidence * 0.5

    def _max_position(self, regime: str) -> float:
        """返回该市场状态下的最大许可仓位。"""
        if regime == MarketRegime.BULL.value:
            return self.BULL_SIZE_HIGH
        elif regime == MarketRegime.BEAR.value:
            return self.BEAR_MAX_POSITION
        elif regime == MarketRegime.CHOPPY.value:
            return self.CHOPPY_MAX_POSITION
        elif regime == MarketRegime.HIGH_RISK.value:
            return self.HIGH_RISK_MAX_POSITION
        else:
            return 1.0


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

position_engine = PositionEngine()