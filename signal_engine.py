#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SignalEngine — 统一信号生成层。

架构说明
--------
SignalEngine 从 PriceProviderV2 和 BrokerProvider 获取输入，
通过多个策略规则生成交易信号。信号仅用于参考和 Dashboard/Doctor 展示，
不自动执行任何交易。

当前策略
---------
1. Momentum Strategy (动量策略)
   - price change_pct > +3% → BUY (strength 70-90)
   - price change_pct > +5% → BUY (strength 90-100)

2. Mean Reversion Strategy (均值回归)
   - price change_pct < -3% → SELL or RISK_OFF
   - price change_pct < -5% → STRONG SELL

3. Portfolio Exposure Strategy (仓位管理)
   - 单一股票仓位 > 20% → REDUCE
   - 单一股票亏损 > 10% → SELL
   - 总仓位过高 → RISK_OFF

数据来源
---------
- PriceProviderV2: get_price() / get_prices() → PriceResultV2
- BrokerProvider: get_portfolio_snapshot() → BrokerPortfolioSnapshot

安全约束
---------
- 无交易执行能力
- 无订单函数
- 无 API Key 使用
- 无外部网络请求
- 无文件写入
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from broker_provider import BrokerPortfolioSnapshot
from event_bus import event_bus
from events import SIGNAL_GENERATED
from price_provider_v2 import PriceResultV2


# ---------------------------------------------------------------------------
# Signal types
# ---------------------------------------------------------------------------


class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    INCREASE = "INCREASE"
    RISK_OFF = "RISK_OFF"


# ---------------------------------------------------------------------------
# Signal dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Signal:
    """单个交易信号。不可变。"""

    symbol: str
    signal_type: SignalType
    strength: int          # 0-100
    confidence: float      # 0-1
    reason: str
    source: str            # "price" / "broker" / "hybrid"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "signal_type": self.signal_type.value,
            "action": self.signal_type.value,
            "strength": self.strength,
            "confidence": self.confidence,
            "reason": self.reason,
            "source": self.source,
            "timestamp": self.timestamp,
        }

    def __repr__(self) -> str:
        return (
            f"Signal(symbol={self.symbol}, type={self.signal_type.value}, "
            f"strength={self.strength}, confidence={self.confidence:.2f})"
        )


# ---------------------------------------------------------------------------
# SignalEngine
# ---------------------------------------------------------------------------


class SignalEngine:
    """信号引擎。从价格和持仓数据生成信号列表。"""

    # 策略参数
    MOMENTUM_BUY_THRESHOLD = Decimal("3")       # > 3% → BUY
    MOMENTUM_STRONG_BUY_THRESHOLD = Decimal("5") # > 5% → strong BUY
    REVERSION_SELL_THRESHOLD = Decimal("-3")    # < -3% → SELL
    REVERSION_STRONG_SELL_THRESHOLD = Decimal("-5")  # < -5% → strong SELL
    MAX_SINGLE_POSITION_PCT = Decimal("20")     # > 20% → REDUCE
    MAX_SINGLE_LOSS_PCT = Decimal("-10")        # < -10% loss → SELL

    def evaluate(
        self,
        price_results: dict[str, PriceResultV2],
        broker_snapshot: BrokerPortfolioSnapshot | None = None,
    ) -> list[Signal]:
        """Evaluate all strategies and return a list of signals.

        Args:
            price_results: dict of symbol → PriceResultV2
            broker_snapshot: optional BrokerPortfolioSnapshot for exposure check

        Returns:
            List[Signal] — sorted by strength descending
        """
        signals: list[Signal] = []

        # Strategy 1 & 2: Momentum + Mean Reversion (price-based)
        for symbol, pr in price_results.items():
            if pr.price is None:
                continue
            signals.extend(self._evaluate_price_strategies(symbol, pr))

        # Strategy 3: Portfolio exposure (broker-based)
        if broker_snapshot is not None:
            signals.extend(self._evaluate_exposure_strategies(broker_snapshot))

        # Sort by strength descending
        signals.sort(key=lambda s: s.strength, reverse=True)

        # Publish each signal to EventBus
        for signal in signals:
            event_bus.publish(SIGNAL_GENERATED, {
                "signal": signal.to_dict(),
                "has_portfolio": broker_snapshot is not None,
            })

        return signals

    def evaluate_unified(self, price_data: dict[str, Any]) -> Signal:
        """Evaluate the deterministic V4 single-signal rule and publish once."""
        signal = generate_signal(price_data)
        event_bus.publish(SIGNAL_GENERATED, {
            "signal": signal.to_dict(),
            "has_portfolio": True,
        })
        return signal

    def evaluate_unified_to_decision(
        self,
        *,
        price_data: dict[str, Any],
        decision_engine: Any,
    ) -> Any:
        """Bridge the unified signal into the existing read-only decision engine."""
        return decision_engine.evaluate(self.evaluate_unified(price_data))

    def _evaluate_price_strategies(
        self, symbol: str, pr: PriceResultV2, change_pct: Decimal | None = None
    ) -> list[Signal]:
        """Momentum (> gain) + Mean Reversion (< loss).

        Args:
            symbol: 股票代码
            pr: 行情结果对象
            change_pct: 价格变化百分比（可选）

        Returns:
            List[Signal]
        """
        signals: list[Signal] = []
        if pr.price is None:
            return signals

        # 如果提供了 change_pct，使用它生成信号
        if change_pct is not None:
            return self.evaluate_with_change_pct(symbol, pr.price, change_pct)

        # 如果没有 change_pct，尝试从 pr 的状态估算
        if not pr.is_ok and pr.status != "STALE":
            return signals

        if pr.status == "STALE":
            # 陈旧数据不得进入正式信号链。
            return signals

        # 默认 HOLD
        signals.append(Signal(
            symbol=symbol,
            signal_type=SignalType.HOLD,
            strength=30,
            confidence=0.3,
            reason=f"Price available at ${pr.price}. "
                   "No change_pct data — default HOLD. "
                   "Integrate with price_history for momentum analysis.",
            source="price",
        ))
        return signals

    def evaluate_with_change_pct(
        self,
        symbol: str,
        current_price: Decimal,
        change_pct: Decimal,
    ) -> list[Signal]:
        """Evaluate price strategies with explicit change_pct.

        This is the primary method when the caller has computed change_pct.
        Used by screen_stocks / market_info / price_fetchers that have
        previous_close.

        Args:
            symbol: stock symbol
            current_price: current price (Decimal)
            change_pct: percentage change (e.g. Decimal("4.5") means +4.5%)

        Returns:
            List[Signal]
        """
        signals: list[Signal] = []

        # Momentum: price going up
        if change_pct >= self.MOMENTUM_STRONG_BUY_THRESHOLD:
            signals.append(Signal(
                symbol=symbol,
                signal_type=SignalType.BUY,
                strength=95,
                confidence=0.85,
                reason=f"Strong momentum: +{change_pct}% gain. "
                       f"Price: ${current_price}. Above 5% threshold.",
                source="price",
            ))
        elif change_pct >= self.MOMENTUM_BUY_THRESHOLD:
            strength = 70 + int((change_pct - self.MOMENTUM_BUY_THRESHOLD) * 10)
            strength = min(strength, 90)
            signals.append(Signal(
                symbol=symbol,
                signal_type=SignalType.BUY,
                strength=strength,
                confidence=0.6 + float(change_pct) * 0.05,
                reason=f"Momentum: +{change_pct}% gain. "
                       f"Price: ${current_price}. Above 3% threshold.",
                source="price",
            ))

        # Mean Reversion: price dropping
        if change_pct <= self.REVERSION_STRONG_SELL_THRESHOLD:
            signals.append(Signal(
                symbol=symbol,
                signal_type=SignalType.SELL,
                strength=95,
                confidence=0.85,
                reason=f"Sharp decline: {change_pct}% loss. "
                       f"Price: ${current_price}. Below -5% threshold. "
                       "Consider risk control.",
                source="price",
            ))
        elif change_pct <= self.REVERSION_SELL_THRESHOLD:
            strength = 60 + int(abs(change_pct) * 10)
            strength = min(strength, 85)
            confidence = 0.5 + float(abs(change_pct)) * 0.05
            signals.append(Signal(
                symbol=symbol,
                signal_type=SignalType.RISK_OFF,
                strength=strength,
                confidence=min(confidence, 0.8),
                reason=f"Decline: {change_pct}% loss. "
                       f"Price: ${current_price}. Below -3% threshold. "
                       "Check news and fundamentals.",
                source="price",
            ))

        # Default: HOLD
        if not signals:
            signals.append(Signal(
                symbol=symbol,
                signal_type=SignalType.HOLD,
                strength=30,
                confidence=0.5,
                reason=f"Price: ${current_price}, change: {change_pct}%. "
                       "No significant momentum or reversion signal.",
                source="price",
            ))

        # Publish to EventBus
        for signal in signals:
            event_bus.publish(SIGNAL_GENERATED, {
                "signal": signal.to_dict(),
                "has_portfolio": False,
            })

        return signals

    def _evaluate_exposure_strategies(
        self, snapshot: BrokerPortfolioSnapshot
    ) -> list[Signal]:
        """Portfolio exposure strategy."""
        signals: list[Signal] = []
        positions = snapshot.positions

        if not positions:
            return signals

        # Calculate total portfolio value
        total_market_value = Decimal("0")
        position_values: dict[str, Decimal] = {}
        for pos in positions:
            mv = pos.market_value or Decimal("0")
            total_market_value += mv
            position_values[pos.symbol] = mv

        if total_market_value <= Decimal("0"):
            return signals

        # Check each position
        for pos in positions:
            mv = pos.market_value or Decimal("0")
            # Position percentage
            pct = mv / total_market_value * Decimal("100")

            # > 20% → REDUCE
            if pct > self.MAX_SINGLE_POSITION_PCT:
                signals.append(Signal(
                    symbol=pos.symbol,
                    signal_type=SignalType.REDUCE,
                    strength=80,
                    confidence=0.75,
                    reason=f"Position {pct:.1f}% of portfolio exceeds "
                           f"{self.MAX_SINGLE_POSITION_PCT}% threshold. "
                           "Reduce exposure to manage concentration risk.",
                    source="broker",
                ))

            # Loss > 10% → SELL
            if pos.unrealized_pnl_pct is not None and pos.unrealized_pnl_pct < self.MAX_SINGLE_LOSS_PCT:
                signals.append(Signal(
                    symbol=pos.symbol,
                    signal_type=SignalType.SELL,
                    strength=85,
                    confidence=0.8,
                    reason=f"Unrealized loss {pos.unrealized_pnl_pct:.1f}% exceeds "
                           f"{abs(self.MAX_SINGLE_LOSS_PCT)}% threshold. "
                           "Consider cutting loss.",
                    source="broker",
                ))

        # Total unrealized portfolio loss check
        total_unrealized = snapshot.account.unrealized_pnl
        if total_unrealized is not None and total_market_value > Decimal("0"):
            total_loss_pct = total_unrealized / total_market_value * Decimal("100")
            if total_loss_pct < self.MAX_SINGLE_LOSS_PCT:
                signals.append(Signal(
                    symbol="PORTFOLIO",
                    signal_type=SignalType.RISK_OFF,
                    strength=90,
                    confidence=0.9,
                    reason=f"Total portfolio loss {total_loss_pct:.1f}% exceeds threshold. "
                           "Consider reducing overall market exposure.",
                    source="broker",
                ))

        # Publish each signal
        for signal in signals:
            event_bus.publish(SIGNAL_GENERATED, {
                "signal": signal.to_dict(),
                "has_portfolio": True,
            })

        return signals


# ---------------------------------------------------------------------------
# Global engine instance (singleton)
# ---------------------------------------------------------------------------

signal_engine = SignalEngine()


def generate_signal(inputs: dict[str, Any]) -> Signal:
    """Compatibility entry for the V4 unified single-signal rule.

    Inputs use decimal ratios (0.03 == 3%). Risk reduction has priority over
    directional momentum. This helper is pure and never executes an order.
    """
    symbol = str(inputs.get("symbol") or "UNKNOWN").strip().upper() or "UNKNOWN"
    try:
        change_pct = Decimal(str(inputs.get("change_pct", 0) or 0))
    except Exception:
        change_pct = Decimal("0")
    try:
        volatility = Decimal(str(inputs.get("volatility", 0) or 0))
    except Exception:
        volatility = Decimal("0")

    if volatility > Decimal("0.03"):
        kind, strength, confidence, reason = SignalType.REDUCE, 80, 0.8, "Volatility above 3%; reduce risk."
    elif change_pct > Decimal("0.02"):
        kind, strength, confidence, reason = SignalType.BUY, 75, 0.7, "Positive move above 2%."
    elif change_pct < Decimal("-0.02"):
        kind, strength, confidence, reason = SignalType.SELL, 75, 0.7, "Negative move below -2%."
    else:
        kind, strength, confidence, reason = SignalType.HOLD, 30, 0.5, "No unified signal threshold crossed."
    return Signal(
        symbol=symbol,
        signal_type=kind,
        strength=strength,
        confidence=confidence,
        reason=reason,
        source="unified",
    )
