#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CapitalGuard — 资金回撤保护系统。

架构说明
--------
CapitalGuard 在 PortfolioEngine 之上提供账户级风险刹车。
它根据账户净值曲线、回撤幅度和连续亏损天数判断当前资金模式，
并输出仓位乘数供其他模块使用。

输入:
- equity_curve: list[float] — 账户净值曲线
- drawdown_pct: float — 当前回撤百分比
- recent_returns: list[float] — 最近每日收益率

输出:
- capital_mode: NORMAL / CAUTION / DEFENSIVE / LOCKDOWN
- position_multiplier: float (0~1)

规则:
1. 回撤控制: <5% NORMAL, 5-10% CAUTION, 10-15% DEFENSIVE, >15% LOCKDOWN
2. 连续亏损: 3天→CAUTION, 5天→DEFENSIVE, 7天→LOCKDOWN
3. 系统联动: 各 mode 输出仓位乘数供外部使用

不修改 SignalEngine / RiskEngine / DecisionEngine / ExecutionEngine / PositionEngine / PortfolioEngine。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from event_bus import event_bus
from events import CAPITAL_MODE_UPDATED


# ---------------------------------------------------------------------------
# Capital Mode
# ---------------------------------------------------------------------------


class CapitalMode(str, Enum):
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    DEFENSIVE = "DEFENSIVE"
    LOCKDOWN = "LOCKDOWN"


# ---------------------------------------------------------------------------
# CapitalGuardSnapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapitalGuardSnapshot:
    """资金保护快照。"""

    capital_mode: CapitalMode
    drawdown_pct: float
    consecutive_losses: int
    position_multiplier: float
    reason: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "capital_mode": self.capital_mode.value,
            "drawdown_pct": self.drawdown_pct,
            "consecutive_losses": self.consecutive_losses,
            "position_multiplier": self.position_multiplier,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }

    def __repr__(self) -> str:
        return (
            f"CapitalGuardSnapshot(mode={self.capital_mode.value}, "
            f"dd={self.drawdown_pct:.1f}%, mult={self.position_multiplier:.2f})"
        )


# ---------------------------------------------------------------------------
# CapitalGuard
# ---------------------------------------------------------------------------


class CapitalGuard:
    """资金回撤保护引擎。"""

    # 回撤阈值
    DD_NORMAL = 5.0       # 5% 以下 → NORMAL
    DD_CAUTION = 10.0     # 5-10%  → CAUTION
    DD_DEFENSIVE = 15.0   # 10-15% → DEFENSIVE
    # >15% → LOCKDOWN

    # 连续亏损阈值
    LOSS_CAUTION = 3      # 3天连续亏损 → CAUTION
    LOSS_DEFENSIVE = 5    # 5天 → DEFENSIVE
    LOSS_LOCKDOWN = 7     # 7天 → LOCKDOWN

    # Mode 乘数
    MODE_MULTIPLIERS = {
        CapitalMode.NORMAL: 1.0,
        CapitalMode.CAUTION: 0.8,
        CapitalMode.DEFENSIVE: 0.5,
        CapitalMode.LOCKDOWN: 0.0,
    }

    def evaluate(
        self,
        drawdown_pct: float = 0.0,
        consecutive_losses: int = 0,
        equity_curve: list[float] | None = None,
    ) -> CapitalGuardSnapshot:
        """评估当前资金状态。

        Args:
            drawdown_pct: 当前回撤百分比
            consecutive_losses: 连续亏损天数
            equity_curve: 完整净值曲线（用于计算回撤）

        Returns:
            CapitalGuardSnapshot
        """
        # 如果提供了 equity_curve，从中计算 drawdown
        if equity_curve and len(equity_curve) >= 2:
            peak = max(equity_curve)
            current = equity_curve[-1]
            if peak > 0:
                drawdown_pct = (peak - current) / peak * 100.0

            # 从 equity_curve 计算连续亏损
            consecutive_losses = 0
            for i in range(len(equity_curve) - 1, 0, -1):
                if equity_curve[i] < equity_curve[i - 1]:
                    consecutive_losses += 1
                else:
                    break

        # 判断 mode: 取回撤和连续亏损的较严格者
        mode_by_dd = self._mode_by_drawdown(drawdown_pct)
        mode_by_loss = self._mode_by_losses(consecutive_losses)
        mode = self._stricter_mode(mode_by_dd, mode_by_loss)

        multiplier = self.MODE_MULTIPLIERS.get(mode, 1.0)
        reason = self._reason_text(mode, drawdown_pct, consecutive_losses)

        snapshot = CapitalGuardSnapshot(
            capital_mode=mode,
            drawdown_pct=round(drawdown_pct, 2),
            consecutive_losses=consecutive_losses,
            position_multiplier=multiplier,
            reason=reason,
        )

        event_bus.publish(CAPITAL_MODE_UPDATED, {
            "capital_snapshot": snapshot.to_dict(),
        })

        return snapshot

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _mode_by_drawdown(self, dd: float) -> CapitalMode:
        if dd >= self.DD_DEFENSIVE:
            return CapitalMode.LOCKDOWN
        elif dd >= self.DD_CAUTION:
            return CapitalMode.DEFENSIVE
        elif dd >= self.DD_NORMAL:
            return CapitalMode.CAUTION
        return CapitalMode.NORMAL

    def _mode_by_losses(self, losses: int) -> CapitalMode:
        if losses >= self.LOSS_LOCKDOWN:
            return CapitalMode.LOCKDOWN
        elif losses >= self.LOSS_DEFENSIVE:
            return CapitalMode.DEFENSIVE
        elif losses >= self.LOSS_CAUTION:
            return CapitalMode.CAUTION
        return CapitalMode.NORMAL

    @staticmethod
    def _stricter_mode(a: CapitalMode, b: CapitalMode) -> CapitalMode:
        order = [CapitalMode.NORMAL, CapitalMode.CAUTION, CapitalMode.DEFENSIVE, CapitalMode.LOCKDOWN]
        idx = max(order.index(a), order.index(b))
        return order[idx]

    @staticmethod
    def _reason_text(mode: CapitalMode, dd: float, losses: int) -> str:
        parts = []
        if dd > 0:
            parts.append(f"drawdown={dd:.1f}%")
        if losses > 0:
            parts.append(f"consecutive_losses={losses}")
        return f"Mode={mode.value} ({', '.join(parts)})" if parts else f"Mode={mode.value}"


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

capital_guard = CapitalGuard()