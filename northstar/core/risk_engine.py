#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""风控引擎 — 统一仓位、风险、暴露管理。

封装 risk_engine.py + capital_guard.py。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from risk_engine import RiskEngine as _RiskEngine
from capital_guard import CapitalGuard as _CapitalGuard


@dataclass(frozen=True)
class RiskReport:
    """风险评估报告。"""
    max_drawdown: float
    concentration_risk: float
    var_95: float
    risk_score: int  # 0-100
    suggestions: tuple[str, ...]


@dataclass(frozen=True)
class CapitalStatus:
    """资金状态。"""
    total: Decimal
    cash: Decimal
    exposure: float
    health: str  # "safe" | "warning" | "danger"


class RiskEngine:
    """风控引擎封装。

    用法：
        engine = RiskEngine()
        risk = engine.assess()
        cap = engine.capital_status()
    """

    def __init__(self) -> None:
        self._engine = _RiskEngine()
        self._guard = _CapitalGuard()

    def assess(self) -> RiskReport:
        """评估当前组合风险。"""
        raw = self._engine.assess()
        suggestions = self._guard.get_suggestions()
        return RiskReport(
            max_drawdown=raw.get("max_drawdown", 0.0),
            concentration_risk=raw.get("concentration", 0.0),
            var_95=raw.get("var_95", 0.0),
            risk_score=raw.get("score", 50),
            suggestions=tuple(suggestions),
        )

    def capital_status(self) -> CapitalStatus:
        """获取资金状态。"""
        raw = self._engine.capital_status()
        return CapitalStatus(
            total=raw.get("total", Decimal("0")),
            cash=raw.get("cash", Decimal("0")),
            exposure=raw.get("exposure", 0.0),
            health=raw.get("health", "unknown"),
        )

    def check_trade(self, symbol: str, amount: Decimal) -> bool:
        """检查某笔交易是否合规。"""
        return self._engine.check_trade(symbol, amount)