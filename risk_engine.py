#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RiskEngine — 独立风险控制层。

架构说明
--------
RiskEngine 是 SignalEngine 的后置过滤层，对所有交易信号进行风险评级、
降权、拒绝或熔断。

流程:
Price/Broker → SignalEngine → RiskEngine → FinalSignal

不修改 SignalEngine、PriceProvider、BrokerProvider 任何代码。

风控规则
---------
1. 单票仓位风险: >20%→HIGH, >30%→CRITICAL, >40%→BLOCKED
2. 单票亏损风险: >5%→HIGH, >10%→CRITICAL, >15%→BLOCKED
3. 信号冲突处理: BUY+HIGH→HOLD, BUY+CRITICAL→BLOCKED
4. 市场波动风险: change>8%→HIGH, change>12%→CRITICAL
5. 连续信号抑制: 连续BUY>3次降权, 高频切换→HOLD
6. 风险熔断机制: CRITICAL≥3→全局RISK_OFF, BLOCKED≥1→禁止BUY

安全约束
---------
- 无交易执行能力
- 无 API 调用
- 无文件写入
- 无网络请求
- 无 order / trade 方法
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from broker_provider import BrokerPortfolioSnapshot
from event_bus import event_bus
from events import RISK_EVALUATED
from price_provider_v2 import PriceResultV2
from signal_engine import Signal, SignalType


# ---------------------------------------------------------------------------
# Risk Level
# ---------------------------------------------------------------------------


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    BLOCKED = "BLOCKED"


# ---------------------------------------------------------------------------
# RiskDecision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RiskDecision:
    """风控决策。不可变。"""

    symbol: str
    original_signal: Signal
    risk_level: RiskLevel
    adjusted_signal: Signal | None = None
    reason: str = ""
    confidence_penalty: float = 0.0     # 0=no penalty, 1=full penalty
    blocked: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "original_signal": self.original_signal.to_dict(),
            "risk_level": self.risk_level.value,
            "adjusted_signal": self.adjusted_signal.to_dict() if self.adjusted_signal else None,
            "reason": self.reason,
            "confidence_penalty": self.confidence_penalty,
            "blocked": self.blocked,
            "timestamp": self.timestamp,
        }

    def __repr__(self) -> str:
        return (
            f"RiskDecision(symbol={self.symbol}, risk={self.risk_level.value}, "
            f"blocked={self.blocked})"
        )


# ---------------------------------------------------------------------------
# RiskEngine
# ---------------------------------------------------------------------------


class RiskEngine:
    """风控引擎。后置过滤 SignalEngine 输出。"""

    # 仓位风险阈值
    POSITION_HIGH_PCT = Decimal("20")
    POSITION_CRITICAL_PCT = Decimal("30")
    POSITION_BLOCKED_PCT = Decimal("40")

    # 亏损风险阈值
    LOSS_HIGH_PCT = Decimal("-5")
    LOSS_CRITICAL_PCT = Decimal("-10")
    LOSS_BLOCKED_PCT = Decimal("-15")

    # 波动率阈值
    VOLATILITY_HIGH_PCT = Decimal("8")
    VOLATILITY_CRITICAL_PCT = Decimal("12")

    # 连续信号抑制
    MAX_CONSECUTIVE_BUY = 3

    def __init__(self) -> None:
        # 信号历史记录 {symbol: [(timestamp, SignalType)]}
        self._signal_history: dict[str, list[tuple[str, SignalType]]] = {}

    def evaluate(
        self,
        signals: list[Signal],
        portfolio_snapshot: BrokerPortfolioSnapshot | None = None,
        price_results: dict[str, PriceResultV2] | None = None,
    ) -> list[RiskDecision]:
        """执行所有风控规则，返回决策列表。

        Args:
            signals: SignalEngine 输出的信号列表
            portfolio_snapshot: BrokerProvider 的持仓快照
            price_results: PriceProvider 的行情结果

        Returns:
            List[RiskDecision]
        """
        decisions: list[RiskDecision] = []
        blocked_count = 0
        critical_count = 0
        price_results = price_results or {}

        # 构建仓位索引
        position_by_symbol: dict[str, dict[str, Any]] = {}
        if portfolio_snapshot is not None:
            total_mv = sum(
                (p.market_value or Decimal("0"))
                for p in portfolio_snapshot.positions
            )
            for pos in portfolio_snapshot.positions:
                mv = pos.market_value or Decimal("0")
                pct = (mv / total_mv * Decimal("100")) if total_mv > Decimal("0") else Decimal("0")
                position_by_symbol[pos.symbol] = {
                    "pct": pct,
                    "unrealized_pnl_pct": pos.unrealized_pnl_pct,
                    "market_value": mv,
                }

        for signal in signals:
            sym = signal.symbol
            pos_info = position_by_symbol.get(sym, {})
            pr = price_results.get(sym)

            # ---- Rule 1: 单票仓位风险 ----
            risk1, reason1 = self._check_position_exposure(pos_info.get("pct"))

            # ---- Rule 2: 单票亏损风险 ----
            risk2, reason2 = self._check_position_loss(pos_info.get("unrealized_pnl_pct"))

            # ---- Rule 4: 市场波动风险 ----
            risk4, reason4 = self._check_volatility(pr)

            # 合并 risk level（取最高）
            merged_risk = self._merge_risk_levels([risk1, risk2, risk4])
            merged_reason = "; ".join(r for r in [reason1, reason2, reason4] if r)

            # ---- Rule 3: 信号冲突处理 ----
            adjusted, conflict_reason = self._resolve_signal_conflict(signal, merged_risk)
            if conflict_reason and merged_reason:
                merged_reason = merged_reason + "; " + conflict_reason
            elif conflict_reason:
                merged_reason = conflict_reason

            # ---- Rule 5: 连续信号抑制 ----
            penalty, freq_reason = self._check_signal_frequency(sym, signal.signal_type)
            if freq_reason and merged_reason:
                merged_reason = merged_reason + "; " + freq_reason
            elif freq_reason:
                merged_reason = freq_reason

            blocked = merged_risk == RiskLevel.BLOCKED or (
                signal.signal_type == SignalType.BUY and merged_risk == RiskLevel.CRITICAL
            )

            decision = RiskDecision(
                symbol=sym,
                original_signal=signal,
                risk_level=merged_risk,
                adjusted_signal=adjusted,
                reason=merged_reason,
                confidence_penalty=penalty,
                blocked=blocked,
            )
            decisions.append(decision)

            if blocked:
                blocked_count += 1
            if merged_risk == RiskLevel.CRITICAL:
                critical_count += 1
            elif merged_risk == RiskLevel.BLOCKED:
                blocked_count += 1

        # ---- Rule 6: 风险熔断机制 ----
        decisions = self._apply_circuit_breaker(decisions, critical_count, blocked_count)

        # 更新信号历史
        self._update_signal_history(signals)

        # 发布事件
        event_bus.publish(RISK_EVALUATED, {
            "risk_decisions": [d.to_dict() for d in decisions],
            "blocked_signals_count": sum(1 for d in decisions if d.blocked),
            "critical_count": sum(1 for d in decisions if d.risk_level == RiskLevel.CRITICAL),
            "blocked_count": sum(1 for d in decisions if d.risk_level == RiskLevel.BLOCKED),
            "has_portfolio_snapshot": portfolio_snapshot is not None,
        })

        return decisions

    # ------------------------------------------------------------------
    # Rule 1: 单票仓位风险
    # ------------------------------------------------------------------

    def _check_position_exposure(
        self, position_pct: Decimal | None
    ) -> tuple[RiskLevel, str]:
        if position_pct is None:
            return RiskLevel.LOW, ""
        if position_pct >= self.POSITION_BLOCKED_PCT:
            return RiskLevel.BLOCKED, (
                f"Position {position_pct:.1f}% exceeds {self.POSITION_BLOCKED_PCT}% "
                f"blocked threshold. Concentration risk extreme."
            )
        if position_pct >= self.POSITION_CRITICAL_PCT:
            return RiskLevel.CRITICAL, (
                f"Position {position_pct:.1f}% exceeds {self.POSITION_CRITICAL_PCT}% "
                f"critical threshold. Must reduce position."
            )
        if position_pct >= self.POSITION_HIGH_PCT:
            return RiskLevel.HIGH, (
                f"Position {position_pct:.1f}% exceeds {self.POSITION_HIGH_PCT}% "
                f"high threshold. Monitor concentration."
            )
        return RiskLevel.LOW, ""

    # ------------------------------------------------------------------
    # Rule 2: 单票亏损风险
    # ------------------------------------------------------------------

    def _check_position_loss(
        self, unrealized_pnl_pct: Decimal | None
    ) -> tuple[RiskLevel, str]:
        if unrealized_pnl_pct is None:
            return RiskLevel.LOW, ""
        if unrealized_pnl_pct <= self.LOSS_BLOCKED_PCT:
            return RiskLevel.BLOCKED, (
                f"Unrealized loss {unrealized_pnl_pct:.1f}% exceeds "
                f"{abs(self.LOSS_BLOCKED_PCT)}% blocked threshold. "
                "Forced SELL recommended."
            )
        if unrealized_pnl_pct <= self.LOSS_CRITICAL_PCT:
            return RiskLevel.CRITICAL, (
                f"Unrealized loss {unrealized_pnl_pct:.1f}% exceeds "
                f"{abs(self.LOSS_CRITICAL_PCT)}% critical threshold. "
                "Consider cutting loss."
            )
        if unrealized_pnl_pct <= self.LOSS_HIGH_PCT:
            return RiskLevel.HIGH, (
                f"Unrealized loss {unrealized_pnl_pct:.1f}% exceeds "
                f"{abs(self.LOSS_HIGH_PCT)}% high threshold. Monitor closely."
            )
        return RiskLevel.LOW, ""

    # ------------------------------------------------------------------
    # Rule 3: 信号冲突处理
    # ------------------------------------------------------------------

    def _resolve_signal_conflict(
        self, signal: Signal, risk_level: RiskLevel
    ) -> tuple[Signal | None, str]:
        """根据风险等级调整信号。"""
        if signal.signal_type == SignalType.HOLD:
            return None, ""

        if risk_level == RiskLevel.LOW or risk_level == RiskLevel.MEDIUM:
            return None, ""

        if signal.signal_type == SignalType.BUY:
            if risk_level == RiskLevel.HIGH:
                adjusted = Signal(
                    symbol=signal.symbol,
                    signal_type=SignalType.HOLD,
                    strength=max(10, signal.strength - 40),
                    confidence=signal.confidence * 0.5,
                    reason=f"Risk downgrade: BUY → HOLD (risk={risk_level.value})",
                    source=signal.source,
                )
                return adjusted, (
                    f"BUY signal downgraded to HOLD due to {risk_level.value} risk."
                )
            if risk_level == RiskLevel.CRITICAL or risk_level == RiskLevel.BLOCKED:
                # Already blocked by main logic; return signal as-is with BLOCKED
                return None, (
                    f"BUY signal blocked due to {risk_level.value} risk."
                )

        if signal.signal_type == SignalType.SELL:
            # SELL signals are preserved for risk management
            if risk_level == RiskLevel.HIGH:
                return None, "SELL signal confirmed by high risk level."
            if risk_level == RiskLevel.CRITICAL or risk_level == RiskLevel.BLOCKED:
                return None, "SELL signal confirmed by critical risk level."

        return None, ""

    # ------------------------------------------------------------------
    # Rule 4: 市场波动风险
    # ------------------------------------------------------------------

    def _check_volatility(
        self, pr: PriceResultV2 | None
    ) -> tuple[RiskLevel, str]:
        if pr is None or pr.price is None:
            return RiskLevel.LOW, ""
        # Without change_pct, estimate volatility from price level
        # In real integration, caller should pass change_pct.
        # Default: LOW when no data.
        return RiskLevel.LOW, ""

    def check_volatility_with_change(
        self, change_pct: Decimal
    ) -> tuple[RiskLevel, str]:
        """用 explicit change_pct 评估波动风险。"""
        abs_change = abs(change_pct)
        if abs_change >= self.VOLATILITY_CRITICAL_PCT:
            return RiskLevel.CRITICAL, (
                f"Volatility {abs_change:.1f}% exceeds {self.VOLATILITY_CRITICAL_PCT}% "
                f"critical threshold. Extreme market movement."
            )
        if abs_change >= self.VOLATILITY_HIGH_PCT:
            return RiskLevel.HIGH, (
                f"Volatility {abs_change:.1f}% exceeds {self.VOLATILITY_HIGH_PCT}% "
                f"high threshold. Significant market movement."
            )
        return RiskLevel.LOW, ""

    # ------------------------------------------------------------------
    # Rule 5: 连续信号抑制
    # ------------------------------------------------------------------

    def _check_signal_frequency(
        self, symbol: str, signal_type: SignalType
    ) -> tuple[float, str]:
        """抑制连续同向信号。返回 (confidence_penalty, reason)。"""
        history = self._signal_history.get(symbol, [])

        if not history:
            return 0.0, ""

        # 检查连续 BUY 次数
        recent = history[-self.MAX_CONSECUTIVE_BUY:]
        consecutive_buys = sum(1 for _, st in recent if st == SignalType.BUY)

        if signal_type == SignalType.BUY and consecutive_buys >= self.MAX_CONSECUTIVE_BUY:
            return 0.3, (
                f"Signal suppressed: {consecutive_buys}+ consecutive BUY signals. "
                f"Confidence penalized."
            )

        # 检查高频切换 (BUY↔SELL 在最近 3 次中)
        if len(history) >= 3:
            types = [st for _, st in history[-3:]]
            if all(t == SignalType.BUY for t in types) and signal_type == SignalType.SELL:
                return 0.2, "Frequent BUY→SELL switch detected. Confidence reduced."
            if all(t == SignalType.SELL for t in types) and signal_type == SignalType.BUY:
                return 0.2, "Frequent SELL→BUY switch detected. Confidence reduced."

        return 0.0, ""

    def _update_signal_history(self, signals: list[Signal]) -> None:
        """更新信号历史。"""
        now = datetime.now(timezone.utc).isoformat()
        for signal in signals:
            if signal.symbol not in self._signal_history:
                self._signal_history[signal.symbol] = []
            self._signal_history[signal.symbol].append((now, signal.signal_type))
            # 限制历史长度
            if len(self._signal_history[signal.symbol]) > 20:
                self._signal_history[signal.symbol] = \
                    self._signal_history[signal.symbol][-20:]

    def clear_signal_history(self, symbol: str | None = None) -> None:
        """清除信号历史（用于测试）。"""
        if symbol:
            self._signal_history.pop(symbol, None)
        else:
            self._signal_history.clear()

    # ------------------------------------------------------------------
    # Rule 6: 风险熔断机制
    # ------------------------------------------------------------------

    def _apply_circuit_breaker(
        self,
        decisions: list[RiskDecision],
        critical_count: int,
        blocked_count: int,
    ) -> list[RiskDecision]:
        """应用熔断规则。"""
        circuit_triggered = False
        circuit_reason = ""

        # 规则 6a: CRITICAL ≥ 3 → 全局 RISK_OFF
        if critical_count >= 3:
            circuit_triggered = True
            circuit_reason = (
                f"Circuit breaker triggered: {critical_count} CRITICAL risk assets. "
                "Global RISK_OFF applied."
            )

        # 规则 6b: BLOCKED ≥ 1 → 禁止新增 BUY
        blocked_buy = blocked_count >= 1

        new_decisions: list[RiskDecision] = []
        for decision in decisions:
            adj = decision.adjusted_signal
            sig = decision.original_signal
            new_risk = decision.risk_level
            new_reason = decision.reason
            new_blocked = decision.blocked
            new_penalty = decision.confidence_penalty
            new_adjusted = adj

            if circuit_triggered:
                if sig.signal_type == SignalType.BUY:
                    new_adjusted = Signal(
                        symbol=sig.symbol,
                        signal_type=SignalType.HOLD,
                        strength=max(5, sig.strength - 50),
                        confidence=sig.confidence * 0.3,
                        reason=f"Circuit breaker: BUY→HOLD. {circuit_reason}",
                        source=sig.source,
                    )
                    new_blocked = True
                    new_risk = RiskLevel.CRITICAL
                    new_reason = (decision.reason + "; " if decision.reason else "") + circuit_reason
                    new_penalty = max(new_penalty, 0.5)

            if blocked_buy and not circuit_triggered:
                if sig.signal_type == SignalType.BUY:
                    new_adjusted = Signal(
                        symbol=sig.symbol,
                        signal_type=SignalType.HOLD,
                        strength=max(10, sig.strength - 30),
                        confidence=sig.confidence * 0.5,
                        reason=f"Blocked: BLOCKED asset exists. BUY not allowed.",
                        source=sig.source,
                    )
                    new_blocked = True
                    new_reason = (decision.reason + "; " if decision.reason else "") + \
                        "BLOCKED asset exists globally. BUY suppressed."
                    new_penalty = max(new_penalty, 0.3)

            new_decisions.append(RiskDecision(
                symbol=decision.symbol,
                original_signal=decision.original_signal,
                risk_level=new_risk,
                adjusted_signal=new_adjusted,
                reason=new_reason,
                confidence_penalty=new_penalty,
                blocked=new_blocked,
            ))

        return new_decisions

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_risk_levels(levels: list[RiskLevel]) -> RiskLevel:
        """合并多个 risk level，取最高等级。"""
        priority = {
            RiskLevel.BLOCKED: 5,
            RiskLevel.CRITICAL: 4,
            RiskLevel.HIGH: 3,
            RiskLevel.MEDIUM: 2,
            RiskLevel.LOW: 1,
        }
        max_level = RiskLevel.LOW
        max_priority = 0
        for level in levels:
            p = priority.get(level, 0)
            if p > max_priority:
                max_priority = p
                max_level = level
        return max_level

    @staticmethod
    def risk_decision_summary(decisions: list[RiskDecision]) -> dict[str, Any]:
        """生成风控摘要。"""
        total = len(decisions)
        blocked = sum(1 for d in decisions if d.blocked)
        critical = sum(1 for d in decisions if d.risk_level == RiskLevel.CRITICAL)
        high = sum(1 for d in decisions if d.risk_level == RiskLevel.HIGH)
        modified = sum(1 for d in decisions if d.adjusted_signal is not None)

        return {
            "total_signals": total,
            "blocked": blocked,
            "critical": critical,
            "high": high,
            "modified": modified,
            "circuit_breaker_active": blocked >= 1 or critical >= 3,
        }


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

risk_engine = RiskEngine()