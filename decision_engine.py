#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DecisionEngine — 交易系统最终决策层（V3 接入 MarketRegime）。

架构说明
--------
DecisionEngine 是 SignalEngine → RiskEngine → DecisionEngine 管线的最后一层。
它根据 Signal（信号）、RiskDecision（风控决策）和 MarketRegime（市场状态）生成最终执行决策。

决策优先级（严格顺序）:
1. RiskEngine BLOCKED → 强制 BLOCKED
2. RiskEngine RISK_OFF → 强制 HOLD
3. Signal BUY + Risk LOW/MEDIUM → BUY (regime 调整权重)
4. Signal BUY + Risk HIGH → HOLD
5. Signal SELL + Risk OK → SELL (regime 调整权重)
6. Position > 20% exposure → REDUCE
7. Signal HOLD → HOLD

市场状态叠加规则:
- BULL: BUY 权重 +20%, HOLD 优先级提高
- BEAR: BUY 降级为 HOLD, SELL 权重 +30%
- CHOPPY: BUY 需额外确认
- HIGH_RISK: BUY 禁止, 只允许 SELL/REDUCE/HOLD

安全约束
---------
- 不修改 SignalEngine
- 不修改 RiskEngine
- 不引入 order/trade execution
- 不访问任何 API
- 纯逻辑层
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from event_bus import event_bus
from events import DECISION_CREATED, MARKET_REGIME_USED
from market_regime_engine import MarketRegime
from risk_engine import RiskDecision, RiskLevel
from signal_engine import Signal, SignalType


# ---------------------------------------------------------------------------
# Action type
# ---------------------------------------------------------------------------


class DecisionAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    BLOCKED = "BLOCKED"
    REDUCE = "REDUCE"


# ---------------------------------------------------------------------------
# Decision dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Decision:
    """最终执行决策。不可变。"""

    symbol: str
    action: DecisionAction
    confidence: float          # 0-1 最终置信度
    reason: str
    risk_level: str            # RiskLevel.value 或 "N/A"
    signal_type: str           # SignalType.value 或 "N/A"
    original_signal_type: str  # 原始 Signal 的类型
    market_regime: str = ""    # MarketRegime.value (BULL/BEAR/CHOPPY/HIGH_RISK)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "action": self.action.value,
            "confidence": self.confidence,
            "reason": self.reason,
            "risk_level": self.risk_level,
            "signal_type": self.signal_type,
            "original_signal_type": self.original_signal_type,
            "market_regime": self.market_regime,
            "timestamp": self.timestamp,
        }

    def __repr__(self) -> str:
        return (
            f"Decision(symbol={self.symbol}, action={self.action.value}, "
            f"confidence={self.confidence:.2f}, risk={self.risk_level}, "
            f"regime={self.market_regime})"
        )


# ---------------------------------------------------------------------------
# DecisionEngine
# ---------------------------------------------------------------------------

# 仓位阈值
REDUCE_POSITION_THRESHOLD = 20.0  # position > 20% → REDUCE


class DecisionEngine:
    """最终决策引擎（V3 接入 MarketRegime）。"""

    def evaluate(
        self,
        signal: Signal,
        risk_decision: RiskDecision | None = None,
        position_pct: float | None = None,
        market_regime: str = "",
    ) -> Decision:
        """根据 Signal、RiskDecision 和 MarketRegime 生成最终决策。

        Args:
            signal: SignalEngine 输出的信号
            risk_decision: RiskEngine 输出的风控决策（可选）
            position_pct: 该股票在组合中的仓位百分比（可选）
            market_regime: MarketRegimeEngine 识别的市场状态 (BULL/BEAR/CHOPPY/HIGH_RISK)

        Returns:
            Decision
        """
        symbol = signal.symbol
        signal_type = signal.signal_type
        signal_type_str = signal_type.value
        orig_type_str = signal_type_str

        risk_level = RiskLevel.LOW
        adjusted_signal = None
        risk_blocked = False

        if risk_decision is not None:
            risk_level = risk_decision.risk_level
            adjusted_signal = risk_decision.adjusted_signal
            risk_blocked = risk_decision.blocked

            if adjusted_signal is not None:
                signal_type = adjusted_signal.signal_type
                signal_type_str = signal_type.value

        risk_level_str = risk_level.value

        # 发布 MarketRegime 使用事件
        if market_regime:
            event_bus.publish(MARKET_REGIME_USED, {
                "regime": market_regime,
                "symbol": symbol,
            })

        # ---- 决策规则 ----
        action: DecisionAction | None = None
        confidence: float = 0.0
        reason: str = ""

        # (1) RiskEngine BLOCKED → 强制 BLOCKED
        if risk_blocked:
            action = DecisionAction.BLOCKED
            confidence = 0.0
            reason = (
                f"BLOCKED by RiskEngine (risk={risk_level_str}). "
                f"Original signal: {orig_type_str}."
            )

        # (2) RiskEngine RISK_OFF → 强制 HOLD
        elif risk_level == RiskLevel.CRITICAL and signal_type == SignalType.RISK_OFF:
            action = DecisionAction.HOLD
            confidence = 0.1
            reason = f"RISK_OFF by RiskEngine. Forced HOLD."

        # (6) Position > 20% exposure → REDUCE
        elif position_pct is not None and position_pct > REDUCE_POSITION_THRESHOLD:
            action = DecisionAction.REDUCE
            confidence = 0.75
            reason = (
                f"Position {position_pct:.1f}% exceeds {REDUCE_POSITION_THRESHOLD:.0f}% "
                f"threshold. Reduce exposure."
            )

        # ---- MarketRegime 叠加（统一处理，避免提前 return） ----
        regime = market_regime

        # 初始化 regime 调整参数
        regime_action_override: DecisionAction | None = None
        regime_confidence_multiplier: float = 1.0
        regime_reason_parts: list[str] = []

        if regime == MarketRegime.HIGH_RISK.value:
            # HIGH_RISK: 禁止 BUY，只允许 SELL/REDUCE/HOLD
            if signal_type == SignalType.BUY:
                regime_action_override = DecisionAction.HOLD
                regime_confidence_multiplier = 0.3
                regime_reason_parts.append("BUY blocked by HIGH_RISK regime")
            else:
                regime_reason_parts.append("HIGH_RISK regime active")

        elif regime == MarketRegime.BEAR.value:
            # BEAR: BUY 降级为 HOLD, SELL 权重 +30%
            if signal_type == SignalType.BUY and not risk_blocked:
                regime_action_override = DecisionAction.HOLD
                regime_confidence_multiplier = 0.4
                regime_reason_parts.append("BUY blocked by BEAR regime")
            elif signal_type == SignalType.SELL:
                regime_confidence_multiplier = 1.3
                regime_reason_parts.append("BEAR regime: SELL boosted")
            elif signal_type == SignalType.BUY and risk_level == RiskLevel.HIGH:
                regime_action_override = DecisionAction.HOLD
                regime_confidence_multiplier = 0.5
                regime_reason_parts.append("BUY + HIGH risk in BEAR regime")
            else:
                regime_reason_parts.append("BEAR regime active")

        elif regime == MarketRegime.BULL.value:
            # BULL: BUY 权重 +20%, HOLD 优先级提高
            if signal_type == SignalType.HOLD:
                regime_confidence_multiplier = 1.1
                regime_reason_parts.append("BULL regime: HOLD maintained")
            elif signal_type == SignalType.BUY:
                regime_confidence_multiplier = 1.2
                regime_reason_parts.append("BULL regime: BUY boosted")
            else:
                regime_reason_parts.append("BULL regime active")

        # 应用 regime 调整
        if regime_action_override is not None:
            action = regime_action_override
            confidence = signal.confidence * regime_confidence_multiplier
            reason = "; ".join(regime_reason_parts)
            decision = self._build_decision(symbol, action, confidence, reason,
                risk_level_str, signal_type_str, orig_type_str, regime)
            event_bus.publish(DECISION_CREATED, {"decision": decision.to_dict(), "has_risk_decision": risk_decision is not None})
            return decision

        # (3)-(7) Fallback rules only when action not already set
        if action is None:
            if signal_type == SignalType.BUY and risk_level in (RiskLevel.LOW, RiskLevel.MEDIUM):
                action = DecisionAction.BUY
                confidence = signal.confidence * (1.0 - (risk_decision.confidence_penalty if risk_decision else 0.0))
                confidence = max(0.0, min(1.0, confidence))
                reason = (
                    f"BUY signal with {risk_level_str} risk confirmed. "
                    f"Strength: {signal.strength}/100."
                )
            elif signal_type == SignalType.BUY and risk_level == RiskLevel.HIGH:
                action = DecisionAction.HOLD
                confidence = signal.confidence * 0.5
                reason = f"BUY downgraded to HOLD due to {risk_level_str} risk."
            elif signal_type == SignalType.SELL:
                action = DecisionAction.SELL
                confidence = signal.confidence
                reason = f"SELL signal with {risk_level_str} risk. {signal.reason}"
            elif signal_type == SignalType.HOLD:
                action = DecisionAction.HOLD
                confidence = signal.confidence
                reason = f"HOLD signal. {signal.reason}"
            elif signal_type == SignalType.REDUCE:
                action = DecisionAction.REDUCE
                confidence = signal.confidence
                reason = f"REDUCE signal. {signal.reason}"
            else:
                action = DecisionAction.HOLD
                confidence = 0.3
                reason = f"Default HOLD for {signal_type_str} with {risk_level_str} risk."

        decision = self._build_decision(symbol, action, confidence, reason,
            risk_level_str, signal_type_str, orig_type_str, regime)

        event_bus.publish(DECISION_CREATED, {
            "decision": decision.to_dict(),
            "has_risk_decision": risk_decision is not None,
        })
        return decision

    @staticmethod
    def _build_decision(
        symbol: str, action: DecisionAction, confidence: float, reason: str,
        risk_level: str, signal_type: str, orig_type: str, regime: str,
    ) -> Decision:
        return Decision(
            symbol=symbol, action=action, confidence=min(1.0, max(0.0, confidence)),
            reason=reason, risk_level=risk_level, signal_type=signal_type,
            original_signal_type=orig_type, market_regime=regime,
        )


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

decision_engine = DecisionEngine()
