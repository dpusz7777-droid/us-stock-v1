#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SignalEngine — 统一信号生成层。V4 Phase 1.

架构说明
--------
SignalEngine 从 PriceProviderV2 和 BrokerProvider 获取输入，
通过多个策略规则生成交易信号。信号仅用于参考和 Dashboard/Doctor 展示，
不自动执行任何交易。

新增 (V4 Phase 1):
- generate_signal(price_data): 统一信号函数，基于 volatility / change_pct 决策
- SignalEngine 内部集成 generate_signal，保证 Signal → Decision → Execution 链路通畅

当前策略
--------
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

4. Unified Signal (统一信号) (V4 Phase 1)
   - volatility > 0.03 → REDUCE
   - change_pct > 0.02 → BUY
   - change_pct < -0.02 → SELL
   - 其他 → HOLD

数据来源
--------
- PriceProviderV2: get_price() / get_prices() → PriceResultV2
- BrokerProvider: get_portfolio_snapshot() → BrokerPortfolioSnapshot

安全约束
--------
- 无交易执行能力
- 无订单函数
- 无 API Key 使用
- 无外部网络请求
- 无文件写入
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from broker_provider import BrokerPortfolioSnapshot
from event_bus import event_bus
from events import SIGNAL_GENERATED
from price_provider_v2 import PriceResultV2
from strategies.scorer import SignalScorer

# ── v1 loop: report_feedback bridge ─────────────────────────────────────────
_REPORT_FEEDBACK_CACHE: dict | None = None
_REPORT_FEEDBACK_FILE = Path(__file__).resolve().parent / ".runtime" / "report_feedback.json"


def _load_report_feedback() -> dict:
    """Load report feedback adjustment from .runtime/report_feedback.json (cached 30s)."""
    global _REPORT_FEEDBACK_CACHE  # noqa: PLW0602
    now = time.monotonic()
    if getattr(_load_report_feedback, "_cache_ts", 0) + 30 < now:
        _load_report_feedback._cache_ts = now  # type: ignore[attr-defined]
        try:
            if _REPORT_FEEDBACK_FILE.is_file():
                _REPORT_FEEDBACK_CACHE = json.loads(
                    _REPORT_FEEDBACK_FILE.read_text(encoding="utf-8")
                )
            else:
                _REPORT_FEEDBACK_CACHE = None
        except Exception:
            _REPORT_FEEDBACK_CACHE = None
    return _REPORT_FEEDBACK_CACHE or {"report_score": 50.0}


def apply_report_feedback(strength: int, confidence: float) -> tuple[int, float]:
    """Adjust signal strength and confidence based on latest report feedback.

    Returns (adjusted_strength, adjusted_confidence).
    """
    try:
        fb_path = _REPORT_FEEDBACK_FILE
        if fb_path.is_file():
            data = json.loads(fb_path.read_text(encoding="utf-8"))
            score = data.get("report_score", 50.0)
        else:
            score = 50.0

        if score >= 80:
            weight_multiplier = 1.20
            confidence_adjust = 0.20
        elif score >= 60:
            weight_multiplier = 1.10
            confidence_adjust = 0.10
        elif score >= 40:
            weight_multiplier = 1.00
            confidence_adjust = 0.00
        elif score >= 20:
            weight_multiplier = 0.90
            confidence_adjust = -0.10
        else:
            weight_multiplier = 0.80
            confidence_adjust = -0.20
    except Exception:
        weight_multiplier = 1.0
        confidence_adjust = 0.0
        score = 50.0

    new_strength = max(0, min(100, round(strength * weight_multiplier)))
    new_confidence = max(0.0, min(1.0, confidence + confidence_adjust))
    return new_strength, new_confidence


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
    source: str            # "price" / "broker" / "hybrid" / "unified"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "signal_type": self.signal_type.value,
            "action": self.signal_type.value,   # 兼容字段，同 signal_type
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
# 统一信号函数 (V4 Phase 1)
# ---------------------------------------------------------------------------


def generate_signal(price_data: dict) -> Signal:
    """统一信号函数。

    输入:
        price_data: {
            "symbol": str,
            "price": float,
            "change_pct": float,
            "volatility": float
        }

    输出:
        Signal — 包含 action / symbol / timestamp

    规则:
        - volatility > 0.03 → REDUCE
        - change_pct > 0.02  → BUY
        - change_pct < -0.02 → SELL
        - 其他 → HOLD
    """
    symbol = price_data.get("symbol", "UNKNOWN")
    price = float(price_data.get("price", 0.0))
    change_pct = float(price_data.get("change_pct", 0.0))
    volatility = float(price_data.get("volatility", 0.0))

    # 规则: volatility > 0.03 → REDUCE
    if volatility > 0.03:
        signal = Signal(
            symbol=symbol,
            signal_type=SignalType.REDUCE,
            strength=80,
            confidence=0.8,
            reason=(
                f"Volatility {volatility:.4f} exceeds 0.03 threshold. "
                f"Reducing exposure. Price: ${price:.2f}."
            ),
            source="unified",
        )
    # 规则: change_pct > 0.02 → BUY
    elif change_pct > 0.02:
        signal = Signal(
            symbol=symbol,
            signal_type=SignalType.BUY,
            strength=75,
            confidence=0.7,
            reason=(
                f"Change +{change_pct:.4f} exceeds +0.02 threshold. "
                f"Bullish signal. Price: ${price:.2f}."
            ),
            source="unified",
        )
    # 规则: change_pct < -0.02 → SELL
    elif change_pct < -0.02:
        signal = Signal(
            symbol=symbol,
            signal_type=SignalType.SELL,
            strength=75,
            confidence=0.7,
            reason=(
                f"Change {change_pct:.4f} below -0.02 threshold. "
                f"Bearish signal. Price: ${price:.2f}."
            ),
            source="unified",
        )
    # 其他 → HOLD
    else:
        signal = Signal(
            symbol=symbol,
            signal_type=SignalType.HOLD,
            strength=30,
            confidence=0.5,
            reason=(
                f"No significant signal. "
                f"change_pct={change_pct:.4f}, volatility={volatility:.4f}. "
                f"Price: ${price:.2f}."
            ),
            source="unified",
        )

    return signal


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

        # A4: 通过 SignalScorer 加权评分决策唯一最终信号
        final_signal = SignalScorer.score(signals)

        # 只 publish 最终决策
        event_bus.publish(SIGNAL_GENERATED, {
            "signal": final_signal.to_dict(),
            "has_portfolio": broker_snapshot is not None,
        })

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
                source="momentum",
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
                source="momentum",
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
                source="mean_reversion",
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
                source="mean_reversion",
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

        # A4: 通过 SignalScorer 加权评分决策唯一最终信号
        final_signal = SignalScorer.score(signals)

        # 只 publish 最终决策
        event_bus.publish(SIGNAL_GENERATED, {
            "signal": final_signal.to_dict(),
            "has_portfolio": False,
        })

        return signals

    # ------------------------------------------------------------------
    # V4 Phase 1: 统一信号入口
    # ------------------------------------------------------------------

    def evaluate_unified(self, price_data: dict) -> Signal:
        """使用 generate_signal 生成统一信号，并发布到 EventBus。

        Args:
            price_data: {
                "symbol": str,
                "price": float,
                "change_pct": float,
                "volatility": float
            }

        Returns:
            Signal — 包含 action / symbol / timestamp
        """
        signal = generate_signal(price_data)

        # 发布到 EventBus
        event_bus.publish(SIGNAL_GENERATED, {
            "signal": signal.to_dict(),
            "has_portfolio": True,
        })

        return signal

    def evaluate_unified_to_decision(
        self,
        price_data: dict,
        decision_engine: Any,
        risk_decision: Any = None,
        position_pct: float | None = None,
        market_regime: str = "",
    ) -> Any:
        """统一信号 → 决策 全链路。

        从 generate_signal 生成信号，直接传入 DecisionEngine 生成决策。
        确保 Signal → Decision → Execution 链路通畅且不返回 None。

        Args:
            price_data: generate_signal 的输入
            decision_engine: DecisionEngine 实例
            risk_decision: 可选 RiskDecision
            position_pct: 可选仓位百分比
            market_regime: 可选市场状态

        Returns:
            Decision — 最终决策
        """
        from decision_engine import DecisionEngine

        signal = self.evaluate_unified(price_data)

        # 转为 Signal 对象给 DecisionEngine
        signal_obj = Signal(
            symbol=signal.symbol,
            signal_type=signal.signal_type,
            strength=signal.strength,
            confidence=signal.confidence,
            reason=signal.reason,
            source=signal.source,
        )

        decision = decision_engine.evaluate(
            signal=signal_obj,
            risk_decision=risk_decision,
            position_pct=position_pct,
            market_regime=market_regime,
        )

        return decision

    # ------------------------------------------------------------------
    # 内部策略方法
    # ------------------------------------------------------------------

    def _evaluate_price_strategies(
        self, symbol: str, pr: PriceResultV2
    ) -> list[Signal]:
        """Momentum (> gain) + Mean Reversion (< loss)."""
        signals: list[Signal] = []
        if pr.price is None:
            return signals

        if not pr.is_ok and not pr.status == "STALE":
            return signals

        if pr.status == "STALE":
            return signals

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

    def _evaluate_exposure_strategies(
        self, snapshot: BrokerPortfolioSnapshot
    ) -> list[Signal]:
        """Portfolio exposure strategy."""
        signals: list[Signal] = []
        positions = snapshot.positions

        if not positions:
            return signals

        total_market_value = Decimal("0")
        position_values: dict[str, Decimal] = {}
        for pos in positions:
            mv = pos.market_value or Decimal("0")
            total_market_value += mv
            position_values[pos.symbol] = mv

        if total_market_value <= Decimal("0"):
            return signals

        for pos in positions:
            mv = pos.market_value or Decimal("0")
            pct = mv / total_market_value * Decimal("100")

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

        return signals


# ---------------------------------------------------------------------------
# Global engine instance (singleton)
# ---------------------------------------------------------------------------

signal_engine = SignalEngine()