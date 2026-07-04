#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""市场状态模块 — 链接 signal_engine 与 market_regime_engine。

本模块是基础设施桥接层，不修改原始市场体制识别逻辑。
"""

from __future__ import annotations

from enum import Enum

from market_regime_engine import MarketRegime as _EngineRegime
from market_regime_engine import MarketRegimeEngine


class RegimeType(str, Enum):
    """市场状态枚举 (供 signal_engine 使用)。"""
    BULL = "BULL"
    BEAR = "BEAR"
    CHOPPY = "CHOPPY"
    SIDEWAYS = "SIDEWAYS"
    HIGH_RISK = "HIGH_RISK"
    UNKNOWN = "UNKNOWN"


class MarketRegime:
    """市场状态封装层。

    提供 signal_engine 所需的：
        - load(): 获取当前市场状态快照
        - get_regime_multiplier(regime): 获取权重调整乘数
    """

    _REGIME_MULTIPLIERS = {
        "BULL": 1.05,
        "BEAR": 0.95,
        "CHOPPY": 1.00,
        "SIDEWAYS": 1.00,
        "HIGH_RISK": 0.90,
        "UNKNOWN": 1.00,
    }

    def load(self) -> dict:
        """加载当前市场状态。

        Returns:
            dict: {"regime": str, "regime_multiplier": float, ...}
        """
        engine = MarketRegimeEngine()
        snapshot = engine.detect([])
        regime = snapshot.regime.value

        mult = self.get_regime_multiplier(regime)
        return {
            "regime": regime,
            "regime_multiplier": mult,
            "trend_strength": snapshot.trend_strength,
            "volatility_pct": snapshot.volatility_pct,
        }

    def get_regime_multiplier(self, regime: str) -> float:
        """获取市场状态对应的权重调整乘数。

        Args:
            regime: 市场状态字符串

        Returns:
            float: 乘数 (0.90 ~ 1.05)
        """
        regime_upper = regime.upper() if regime else "SIDEWAYS"
        return self._REGIME_MULTIPLIERS.get(regime_upper, 1.0)
