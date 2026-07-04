# -*- coding: utf-8 -*-
"""SignalScorer — A4 权重评分引擎。

从多个策略信号中通过加权评分决策出唯一最终信号。

权重规则:
    source="risk"          → weight 1.0
    source="momentum"      → weight 0.7
    source="mean_reversion"→ weight 0.5
    其他 source             → weight 0.3

score = strength × weight

特殊规则:
    1. RISK_OFF 存在 → 直接返回 RISK_OFF（极端风险 override）
    2. SELL 且 source="risk" → score × 1.5
    3. 空列表 → HOLD (strength=30)

所有逻辑确定性，无随机、无外部依赖。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from signal_engine import Signal, SignalType


class SignalScorer:
    """A4 权重评分引擎。

    用法:
        scorer = SignalScorer()
        final_signal = scorer.score([signal1, signal2, ...])
    """

    # source → weight 映射
    _WEIGHTS: dict[str, float] = {
        "risk":           1.0,
        "momentum":       0.7,
        "mean_reversion": 0.5,
    }

    _DEFAULT_WEIGHT: float = 0.3

    @classmethod
    def score(cls, signals: list) -> "Signal":
        """对多个信号加权评分，返回唯一最终信号。

        Args:
            signals: 多个策略产生的信号列表

        Returns:
            单一最终 Signal，永远不返回 None
        """
        from signal_engine import Signal, SignalType

        # 规则 2: RISK_OFF 直接返回
        for signal in signals:
            if signal.signal_type == SignalType.RISK_OFF:
                return signal

        # 规则 3: 空列表 → HOLD
        if not signals:
            return Signal(
                symbol="UNKNOWN",
                signal_type=SignalType.HOLD,
                strength=30,
                confidence=0.5,
                reason="No signals generated. Default HOLD.",
                source="scorer",
            )

        # 计算每个信号的加权分数
        best_signal: Signal | None = None
        best_score: float = -1.0

        for signal in signals:
            weight = cls._WEIGHTS.get(signal.source, cls._DEFAULT_WEIGHT)
            score_val = float(signal.strength) * weight

            # 规则 1: SELL + risk source → score × 1.5
            if signal.signal_type == SignalType.SELL and signal.source == "risk":
                score_val *= 1.5

            if score_val > best_score or (
                score_val == best_score and best_signal is not None
                and signal.confidence > best_signal.confidence
            ):
                best_score = score_val
                best_signal = signal

        # 保底
        if best_signal is None:
            return Signal(
                symbol=signals[0].symbol,
                signal_type=SignalType.HOLD,
                strength=30,
                confidence=0.5,
                reason="Scorer fallback. Default HOLD.",
                source="scorer",
            )

        return best_signal