#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MarketRegimeEngine — 市场状态识别模块。

架构说明
--------
MarketRegimeEngine 从价格历史数据中识别当前市场状态（BULL / BEAR / CHOPPY / HIGH_RISK），
通过 EventBus 发布 MARKET_REGIME_UPDATED 事件，供 BacktestEngine 和 Dashboard 使用。

本模块只读，不修改 SignalEngine / RiskEngine / ExecutionEngine 结构。

状态定义
---------
- BULL: 单边上涨，趋势斜率 > 0，波动率正常
- BEAR: 单边下跌，趋势斜率 < 0，波动率正常
- CHOPPY: 震荡，趋势斜率接近 0，波动率正常
- HIGH_RISK: 高波动，波动率超过阈值

使用方式
---------
regime = MarketRegimeEngine()
state = regime.detect(prices)  # 返回 MarketRegime enum
regime.update_backtest_config(config)  # 根据状态调整 BacktestConfig
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from event_bus import event_bus
from events import MARKET_REGIME_UPDATED


# ---------------------------------------------------------------------------
# Market Regime enum
# ---------------------------------------------------------------------------


class MarketRegime(str, Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    CHOPPY = "CHOPPY"
    HIGH_RISK = "HIGH_RISK"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# MarketRegimeEngine
# ---------------------------------------------------------------------------


@dataclass
class MarketRegimeSnapshot:
    """市场状态快照。"""

    regime: MarketRegime
    trend_strength: float = 0.0       # 趋势强度 (-1~1)
    volatility_pct: float = 0.0       # 波动率 (%)
    sma_slope: float = 0.0            # 均线斜率
    price_vs_sma: float = 0.0         # 价格相对均线位置 (%)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime.value,
            "trend_strength": self.trend_strength,
            "volatility_pct": self.volatility_pct,
            "sma_slope": self.sma_slope,
            "price_vs_sma": self.price_vs_sma,
            "timestamp": self.timestamp,
        }

    def __repr__(self) -> str:
        return (
            f"MarketRegimeSnapshot(regime={self.regime.value}, "
            f"trend={self.trend_strength:.2f}, vol={self.volatility_pct:.2f}%)"
        )


class MarketRegimeEngine:
    """市场状态识别引擎。

    输入: 价格历史 (list[Decimal])
    输出: MarketRegimeSnapshot
    """

    # 参数
    SMA_SHORT = 20          # 短期均线周期
    SMA_LONG = 50           # 长期均线周期
    VOLATILITY_PERIOD = 20  # 波动率计算周期
    TREND_PERIOD = 10       # 趋势斜率计算周期

    # 阈值
    BULL_SLOPE = Decimal("0.002")        # 上涨趋势斜率阈值
    BEAR_SLOPE = Decimal("-0.002")       # 下跌趋势斜率阈值
    HIGH_VOL_PCT = Decimal("3.0")         # 高波动阈值（日波动率 %）
    CHOPPY_SLOPE = Decimal("0.0005")     # 震荡判定斜率上限

    def detect(self, prices: list[Decimal]) -> MarketRegimeSnapshot:
        """检测当前市场状态。

        Args:
            prices: 价格序列（按时间升序）

        Returns:
            MarketRegimeSnapshot
        """
        if len(prices) < self.SMA_LONG + 5:
            return MarketRegimeSnapshot(regime=MarketRegime.UNKNOWN)

        # 计算均线
        sma_short = self._sma(prices, self.SMA_SHORT)
        sma_long = self._sma(prices, self.SMA_LONG)

        # 当前价格和均线
        current_price = prices[-1]
        current_sma_short = sma_short[-1] if sma_short else current_price
        current_sma_long = sma_long[-1] if sma_long else current_price

        # 价格相对均线位置
        price_vs_sma = float((current_price - current_sma_short) / current_sma_short * Decimal("100")) if current_sma_short > Decimal("0") else 0.0

        # 均线斜率（短期均线的趋势）
        slope = self._slope(sma_short, self.TREND_PERIOD)

        # 波动率
        vol = self._volatility(prices, self.VOLATILITY_PERIOD)

        # 判断状态
        regime = MarketRegime.BULL
        if vol > self.HIGH_VOL_PCT:
            regime = MarketRegime.HIGH_RISK
        elif slope > self.BULL_SLOPE:
            regime = MarketRegime.BULL
        elif slope < self.BEAR_SLOPE:
            regime = MarketRegime.BEAR
        elif abs(slope) < self.CHOPPY_SLOPE:
            regime = MarketRegime.CHOPPY

        snapshot = MarketRegimeSnapshot(
            regime=regime,
            trend_strength=min(1.0, max(-1.0, float(slope) * 100)),
            volatility_pct=float(vol),
            sma_slope=float(slope),
            price_vs_sma=price_vs_sma,
        )

        # 发布事件
        event_bus.publish(MARKET_REGIME_UPDATED, {
            "regime_snapshot": snapshot.to_dict(),
            "price_count": len(prices),
        })

        return snapshot

    def update_backtest_config(self, config: Any, regime: MarketRegime) -> None:
        """根据市场状态调整 BacktestConfig 参数。

        不修改不可覆盖的属性，只调整与市场状态相关的参数。

        Args:
            config: BacktestConfig 实例
            regime: 当前市场状态
        """
        if regime == MarketRegime.BULL:
            # BULL 市：更宽松的冷却期，更高的持仓容忍度
            config.cooldown_days = max(2, getattr(config, 'cooldown_days', 5) - 2)
            config.signal_confirmation = 1  # BULL 市 BUY 不需要双确认

        elif regime == MarketRegime.BEAR:
            # BEAR 市：更严格的冷却，降低买入
            config.cooldown_days = min(10, getattr(config, 'cooldown_days', 5) + 3)
            config.signal_confirmation = max(2, getattr(config, 'signal_confirmation', 2))

        elif regime == MarketRegime.CHOPPY:
            # CHOPPY 市：双确认，正常冷却
            config.cooldown_days = max(5, getattr(config, 'cooldown_days', 5))
            config.signal_confirmation = max(2, getattr(config, 'signal_confirmation', 2))

        elif regime == MarketRegime.HIGH_RISK:
            # HIGH_RISK：强行禁用 BUY，冷却期最长
            config.cooldown_days = min(15, getattr(config, 'cooldown_days', 5) + 5)

    # ------------------------------------------------------------------
    # 内部计算方法
    # ------------------------------------------------------------------

    @staticmethod
    def _sma(prices: list[Decimal], period: int) -> list[Decimal]:
        """简单移动平均。"""
        if len(prices) < period:
            return []
        result: list[Decimal] = []
        for i in range(len(prices)):
            if i < period - 1:
                continue
            result.append(sum(prices[i - period + 1:i + 1]) / Decimal(str(period)))
        return result

    @staticmethod
    def _slope(values: list[Decimal], period: int) -> Decimal:
        """计算最近 period 的线性斜率。"""
        if len(values) < period:
            return Decimal("0")
        recent = values[-period:]
        n = Decimal(str(period))
        sum_x = n * (n + Decimal("1")) / Decimal("2")
        sum_y = sum(recent)
        sum_xy = sum((Decimal(str(i + 1)) * v) for i, v in enumerate(recent))
        sum_x2 = sum((Decimal(str(i + 1)) ** Decimal("2")) for i in range(period))
        denominator = n * sum_x2 - sum_x * sum_x
        if denominator == Decimal("0"):
            return Decimal("0")
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        return slope / (values[-1] if values[-1] > Decimal("0") else Decimal("1"))

    @staticmethod
    def _volatility(prices: list[Decimal], period: int) -> Decimal:
        """计算最近 period 的日波动率（百分比）。"""
        if len(prices) < period + 1:
            return Decimal("0")
        recent = prices[-period - 1:]
        returns: list[Decimal] = []
        for i in range(1, len(recent)):
            if recent[i - 1] > Decimal("0"):
                returns.append((recent[i] - recent[i - 1]) / recent[i - 1] * Decimal("100"))
        if not returns:
            return Decimal("0")
        mean = sum(returns) / Decimal(str(len(returns)))
        variance = sum((r - mean) ** Decimal("2") for r in returns) / Decimal(str(len(returns)))
        return variance.sqrt() if variance > Decimal("0") else Decimal("0")


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

market_regime_engine = MarketRegimeEngine()