#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""策略引擎 — 统一的买卖判断与市场状态。

封装 strategy_engine.py + market_regime_engine.py。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from strategy_engine import StrategyEngine as _StrategyEngine
from market_regime_engine import MarketRegimeEngine as _MarketRegimeEngine


@dataclass(frozen=True)
class Regime:
    """市场状态。"""
    label: str  # "bull" | "bear" | "sideways"
    confidence: float
    description: str


@dataclass(frozen=True)
class StrategyDecision:
    """策略层输出的买卖判断。"""
    symbol: str
    action: str  # "buy" | "sell" | "hold"
    reason: str
    confidence: float


class StrategyEngine:
    """策略引擎封装。

    用法：
        engine = StrategyEngine()
        decision = engine.evaluate("NVDA")
        regime = engine.detect_regime()
    """

    def __init__(self) -> None:
        self._engine = _StrategyEngine()
        self._regime = _MarketRegimeEngine()

    def evaluate(self, symbol: str) -> StrategyDecision:
        """评估单个标的的买卖判断。"""
        raw = self._engine.evaluate(symbol)
        return StrategyDecision(
            symbol=symbol,
            action=raw.get("action", "hold"),
            reason=raw.get("reason", ""),
            confidence=raw.get("confidence", 0.5),
        )

    def evaluate_batch(self, symbols: list[str]) -> list[StrategyDecision]:
        """批量评估。"""
        return [self.evaluate(sym) for sym in symbols]

    def detect_regime(self) -> Regime:
        """检测当前市场状态。"""
        raw = self._regime.detect()
        return Regime(
            label=raw.get("regime", "sideways"),
            confidence=raw.get("confidence", 0.5),
            description=raw.get("description", ""),
        )