#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""信号引擎 — 统一信号生成入口。

封装旧 signal_engine.py，支持策略反馈动态调整。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from signal_engine import (
    SignalEngine as _SignalEngine,
    SignalType,
)

from northstar.core.strategy_feedback import load_feedback, compute_adjusted_weight
from northstar.core.market_regime import MarketRegime, RegimeType


@dataclass(frozen=True)
class Signal:
    """标准信号定义。"""
    symbol: str
    signal_type: SignalType
    strength: int  # 1-5
    reason: str
    adjusted_strength: float  # 经反馈调整后的强度
    strategy_score: int  # 当前策略评分
    weight: float  # 调整系数
    market_regime: str  # 当前市场状态
    regime_multiplier: float  # 市场状态乘数
    timestamp: str | None = None


class SignalEngine:
    """信号引擎封装层（支持策略反馈 + 市场状态动态调整）。

    流程：
        1. 从旧引擎生成 raw signals
        2. 读取 strategy_feedback.json 获取 strategy_score
        3. 读取 market_regime.json 获取当前市场状态
        4. 根据 strategy_score + market_regime 调整 strength
        5. 返回调整后的 Signal

    用法：
        engine = SignalEngine()
        signals = engine.generate(symbols=["NVDA", "SOFI"])
    """

    def __init__(self, price_provider: object | None = None) -> None:
        self._engine = _SignalEngine()
        if price_provider is None:
            from price_provider_v2 import get_price_provider_v2

            price_provider = get_price_provider_v2(timeout=1, retries=0)
        self._price_provider = price_provider
        self._strategy_score: int = 50
        self._weight: float = 1.0
        self._regime: str = "SIDEWAYS"
        self._regime_mult: float = 1.0
        self._load_feedback()
        self._load_regime()

    def _load_feedback(self) -> None:
        """加载最新策略反馈。"""
        fb = load_feedback()
        self._strategy_score = fb.get("strategy_score", 50)
        self._weight = compute_adjusted_weight(self._strategy_score)

    def _load_regime(self) -> None:
        """加载最新市场状态。"""
        mr = MarketRegime()
        regime_data = mr.load()
        self._regime = regime_data.get("regime", "SIDEWAYS")
        self._regime_mult = mr.get_regime_multiplier(self._regime)

    def get_price_results(self, symbols: list[str]) -> dict[str, Any]:
        """Fetch one unified price snapshot for a backend iteration."""
        return self._price_provider.get_prices(symbols)

    def generate(
        self,
        symbols: list[str],
        price_results: Mapping[str, Any] | None = None,
    ) -> list[Signal]:
        """为指定标的生成交易信号（已调整）。
        
        适配模式：将 symbols 列表转换为底层 evaluate() 所需的 price_results dict。
        底层引擎 (root signal_engine.py) 的 evaluate() 接受:
            price_results: dict[str, PriceResultV2]
            broker_snapshot: BrokerPortfolioSnapshot | None
        """
        self._load_feedback()
        self._load_regime()

        now = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # Backend passes its iteration snapshot. Other callers retain compatibility.
        if price_results is None:
            price_results = self.get_price_results(symbols)
        
        raw = self._engine.evaluate(dict(price_results), broker_snapshot=None)

        # 综合调整：strategy_weight × regime_multiplier
        combined_weight = self._weight * self._regime_mult

        result = []
        for s in raw:
            adjusted = max(1, min(5, round(s.strength * combined_weight)))
            result.append(Signal(
                symbol=s.symbol,
                signal_type=s.signal_type,
                strength=s.strength,
                reason=s.reason,
                adjusted_strength=adjusted,
                strategy_score=self._strategy_score,
                weight=round(combined_weight, 2),
                market_regime=self._regime,
                regime_multiplier=round(self._regime_mult, 2),
                timestamp=now,
            ))

        return result

    def get_latest(self, symbol: str) -> Signal | None:
        """获取某标的最新信号。"""
        sigs = self.generate([symbol])
        return sigs[0] if sigs else None

    def get_strategy_score(self) -> int:
        """获取当前策略评分。"""
        return self._strategy_score

    def get_weight(self) -> float:
        """获取当前权重系数（含 regime 调整）。"""
        return self._weight * self._regime_mult

    def get_regime(self) -> str:
        """获取当前市场状态。"""
        return self._regime
