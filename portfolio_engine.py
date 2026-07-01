#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PortfolioEngine — 组合级资金管理层。

架构说明
--------
PortfolioEngine 在 PositionEngine 之上提供账户级风险控制。
它接收所有持仓的 position_size_pct 和建议，输出调整后的最终仓位。

输入:
- positions: list[PositionInfo] (symbol, size_pct, confidence, risk_level)
- market_regime: str
- total_equity: Decimal

输出:
- adjusted_positions: list[AdjustedPosition] (调整后的仓位)
- portfolio_risk_score: float (0~1)

核心规则:
1. 单标的上限 ≤ 50%
2. 前3大持仓总和 ≤ 70%
3. 风险叠加: HIGH_RISK ×0.6, BEAR ×0.5
4. 风险分数: 集中度 + 波动率 + 回撤暴露

不修改 SignalEngine / RiskEngine / DecisionEngine / ExecutionEngine / PositionEngine。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from event_bus import event_bus
from events import PORTFOLIO_UPDATED


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PositionInfo:
    """输入: 单个标的仓位信息。"""
    symbol: str
    size_pct: float           # PositionEngine 输出 (0~1)
    confidence: float = 0.5
    risk_level: str = "LOW"


@dataclass(frozen=True)
class AdjustedPosition:
    """输出: 调整后的仓位。"""
    symbol: str
    original_size_pct: float
    adjusted_size_pct: float
    reduction_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "original_size_pct": self.original_size_pct,
            "adjusted_size_pct": self.adjusted_size_pct,
            "reduction_pct": self.reduction_pct,
        }


@dataclass(frozen=True)
class PortfolioRiskResult:
    """组合风险计算结果。"""
    risk_score: float  # 0~1
    concentration_score: float
    single_exposure_max: float
    top3_exposure: float
    total_exposure: float
    regime_multiplier: float
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_score": self.risk_score,
            "concentration_score": self.concentration_score,
            "single_exposure_max": self.single_exposure_max,
            "top3_exposure": self.top3_exposure,
            "total_exposure": self.total_exposure,
            "regime_multiplier": self.regime_multiplier,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# PortfolioEngine
# ---------------------------------------------------------------------------


class PortfolioEngine:
    """组合级资金管理引擎。"""

    # 单标的上限
    MAX_SINGLE_POSITION_PCT = 0.50
    # 前3大持仓上限
    MAX_TOP3_POSITION_PCT = 0.70
    # 默认总仓位上限
    MAX_TOTAL_POSITION_PCT = 1.0

    # Regime 乘数
    REGIME_MULTIPLIERS = {
        "BULL": 1.0,
        "BEAR": 0.5,
        "CHOPPY": 0.7,
        "HIGH_RISK": 0.6,
    }

    # 风险分数权重
    CONCENTRATION_WEIGHT = 0.4
    SINGLE_WEIGHT = 0.3
    REGIME_WEIGHT = 0.3

    def calculate(
        self,
        positions: list[PositionInfo],
        market_regime: str = "",
        total_equity: Decimal | None = None,
    ) -> tuple[list[AdjustedPosition], PortfolioRiskResult]:
        """计算调整后的组合仓位。

        Args:
            positions: 所有持仓的仓位信息
            market_regime: 市场状态
            total_equity: 总资产（用于计算，暂未使用）

        Returns:
            (adjusted_positions, risk_result)
        """
        regime = market_regime or ""
        regime_mult = self.REGIME_MULTIPLIERS.get(regime, 1.0)

        # 按 size_pct 降序排列
        sorted_pos = sorted(positions, key=lambda p: p.size_pct, reverse=True)
        total_requested = sum(p.size_pct for p in sorted_pos)

        # ---- 规则(1): 单标的上限 50% ----
        capped: list[PositionInfo] = []
        for p in sorted_pos:
            cap = min(p.size_pct, self.MAX_SINGLE_POSITION_PCT)
            capped.append(PositionInfo(p.symbol, cap, p.confidence, p.risk_level))

        # ---- 规则(2): 前3大 ≤ 70% ----
        top3 = capped[:3]
        top3_sum = sum(p.size_pct for p in top3)
        if top3_sum > self.MAX_TOP3_POSITION_PCT:
            scale = self.MAX_TOP3_POSITION_PCT / top3_sum if top3_sum > 0 else 1.0
            for i in range(min(3, len(capped))):
                capped[i] = PositionInfo(
                    capped[i].symbol, capped[i].size_pct * scale,
                    capped[i].confidence, capped[i].risk_level,
                )

        # ---- 规则(3): Regime 乘数 ----
        adjusted: list[AdjustedPosition] = []
        for p in capped:
            adj_size = p.size_pct * regime_mult
            reduction = max(0.0, p.size_pct - adj_size)
            adjusted.append(AdjustedPosition(
                symbol=p.symbol,
                original_size_pct=p.size_pct,
                adjusted_size_pct=adj_size,
                reduction_pct=reduction,
            ))

        # ---- 规则(4): 风险分数 ----
        final_sizes = [a.adjusted_size_pct for a in adjusted]

        # 集中度分数: 前3 / 总和的比值
        total_final = sum(final_sizes) if final_sizes else 0.0
        top3_final = sum(sorted(final_sizes, reverse=True)[:3])
        concentration_score = min(1.0, top3_final / max(total_final, 0.01)) if total_final > 0 else 0.0

        # 单标的风险
        max_single = max(final_sizes) if final_sizes else 0.0
        single_score = max_single / self.MAX_SINGLE_POSITION_PCT

        # Regime 分数
        regime_score = 1.0 - regime_mult

        # 综合风险分数
        risk_score = (
            concentration_score * self.CONCENTRATION_WEIGHT
            + single_score * self.SINGLE_WEIGHT
            + regime_score * self.REGIME_WEIGHT
        )
        risk_score = min(1.0, max(0.0, risk_score))

        risk_result = PortfolioRiskResult(
            risk_score=risk_score,
            concentration_score=concentration_score,
            single_exposure_max=max_single,
            top3_exposure=top3_final,
            total_exposure=total_final,
            regime_multiplier=regime_mult,
        )

        # 发布事件
        event_bus.publish(PORTFOLIO_UPDATED, {
            "risk_result": risk_result.to_dict(),
            "adjusted_positions": [a.to_dict() for a in adjusted],
            "market_regime": regime,
        })

        return adjusted, risk_result


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

portfolio_engine = PortfolioEngine()