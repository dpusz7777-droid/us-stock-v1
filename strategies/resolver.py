# -*- coding: utf-8 -*-
"""SignalResolver — 信号冲突解决层。

从多个策略信号中决策出唯一最终信号。

优先级（从高到低）:
    RISK_OFF > SELL > REDUCE > BUY > HOLD

冲突规则:
    1. 最高优先级胜出
    2. BUY 与 SELL 同时存在 → RISK_OFF（强制风险模式）
    3. 同类型取最大 strength
    4. 空列表 → HOLD (strength=30)

所有逻辑确定性，无随机、无外部依赖。
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from signal_engine import Signal, SignalType


class SignalResolver:
    """信号冲突解决器。

    用法:
        resolver = SignalResolver()
        final_signal = resolver.resolve([signal1, signal2, ...])
    """

    @classmethod
    def resolve(cls, signals: list) -> "Signal":
        """从多个信号中解析出唯一最终信号。

        Args:
            signals: 多个策略产生的信号列表

        Returns:
            单一最终 Signal，永远不返回 None
        """
        from signal_engine import Signal, SignalType

        # 优先级映射：值越小优先级越高
        _PRIORITY: dict = {
            SignalType.RISK_OFF: 0,
            SignalType.SELL:     1,
            SignalType.REDUCE:   2,
            SignalType.BUY:      3,
            SignalType.HOLD:     4,
            SignalType.INCREASE: 5,
        }

        if not signals:
            return Signal(
                symbol="UNKNOWN",
                signal_type=SignalType.HOLD,
                strength=30,
                confidence=0.5,
                reason="No signals generated. Default HOLD.",
                source="resolver",
            )

        # 规则 2: BUY 与 SELL 冲突 → RISK_OFF
        has_buy = any(s.signal_type == SignalType.BUY for s in signals)
        has_sell = any(s.signal_type == SignalType.SELL for s in signals)
        if has_buy and has_sell:
            # 取两者中更高的 strength 和 confidence 作为参考
            max_strength = max(s.strength for s in signals)
            max_confidence = max(s.confidence for s in signals)
            symbols = {s.symbol for s in signals}
            return Signal(
                symbol=",".join(sorted(symbols)),
                signal_type=SignalType.RISK_OFF,
                strength=min(max_strength + 5, 100),
                confidence=max_confidence,
                reason=(
                    f"BUY/SELL conflict detected among {len(symbols)} symbols. "
                    f"Forcing RISK_OFF to avoid contradictory positions."
                ),
                source="resolver",
            )

        # 规则 1 & 3: 按优先级分组，高优先级胜出，同类型取 max strength
        best_signal: Signal | None = None
        best_priority: int = 999

        for signal in signals:
            priority = _PRIORITY.get(signal.signal_type, 99)
            if priority < best_priority:
                best_priority = priority
                best_signal = signal
            elif priority == best_priority and best_signal is not None:
                # 同类型取最大 strength
                if signal.strength > best_signal.strength:
                    best_signal = signal
                elif signal.strength == best_signal.strength and signal.confidence > best_signal.confidence:
                    best_signal = signal

        # 保底：不应到达此处，但防御性编程
        if best_signal is None:
            return Signal(
                symbol=signals[0].symbol,
                signal_type=SignalType.HOLD,
                strength=30,
                confidence=0.5,
                reason="Resolver fallback. Default HOLD.",
                source="resolver",
            )

        return best_signal