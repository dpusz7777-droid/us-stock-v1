#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ExecutionEngine — 模拟交易执行层 (Paper Trading Only).

架构说明
--------
ExecutionEngine 是 SignalEngine → RiskEngine → DecisionEngine → ExecutionEngine
管线的最后一环。它接收最终决策（Decision），模拟市场执行过程。

本系统为纯模拟系统：
- 不连接任何 broker
- 不访问 API
- 不执行真实交易
- 所有价格和成交均为模拟

订单生命周期
-------------
Decision → submit_order() → PENDING
                          → simulate_fill() → FILLED (含滑点)
                          → reject_order() → REJECTED
                          → partial_fill() → FILLED (部分成交)

执行规则
---------
- BUY    → 市价 + 滑点 (0~0.1%)
- SELL   → 市价 - 滑点
- BLOCKED → REJECTED
- HOLD   → 不执行 (返回 None)
- REDUCE → 部分减仓

安全约束
---------
- 不连接任何 broker
- 不访问 API
- 不修改 DecisionEngine / RiskEngine / SignalEngine
- 纯模拟系统
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from decision_engine import Decision, DecisionAction
from event_bus import event_bus
from events import ORDER_SUBMITTED, ORDER_FILLED, ORDER_REJECTED


# ---------------------------------------------------------------------------
# Order status
# ---------------------------------------------------------------------------


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    PARTIAL = "PARTIAL"
    NO_OP = "NO_OP"


# ---------------------------------------------------------------------------
# ExecutionResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExecutionResult:
    """模拟执行结果。不可变。"""

    order_id: str
    symbol: str
    action: str                # DecisionAction value
    status: OrderStatus
    fill_price: Decimal | None = None
    slippage: Decimal | None = None      # 滑点比例 (0=无滑点)
    filled_qty: Decimal | None = None
    requested_qty: Decimal | None = None
    reject_reason: str = ""
    latency_ms: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        dct = {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "action": self.action,
            "status": self.status.value,
            "slippage": str(self.slippage) if self.slippage is not None else None,
            "filled_qty": str(self.filled_qty) if self.filled_qty is not None else None,
            "requested_qty": str(self.requested_qty) if self.requested_qty is not None else None,
            "reject_reason": self.reject_reason,
            "latency_ms": self.latency_ms,
            "timestamp": self.timestamp,
        }
        if self.fill_price is not None:
            dct["fill_price"] = str(self.fill_price)
        else:
            dct["fill_price"] = None
        return dct

    def __repr__(self) -> str:
        return (
            f"ExecutionResult(order={self.order_id}, symbol={self.symbol}, "
            f"action={self.action}, status={self.status.value})"
        )


# ---------------------------------------------------------------------------
# ExecutionEngine
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TransactionCostModel:
    """交易成本模型。所有参数可配置，默认保守值。"""

    commission_rate: Decimal = Decimal("0.001")     # 0.1% 佣金
    min_commission: Decimal = Decimal("1.00")       # 最低佣金 $1
    spread_bps: Decimal = Decimal("2")               # 买卖价差 2 基点 (0.02%)
    slippage_base: Decimal = Decimal("0.001")       # 基础滑点 0.1%
    slippage_volatility_factor: Decimal = Decimal("0.5")  # 波动率滑点因子

    def total_cost(self, price: Decimal, qty: Decimal, is_buy: bool) -> Decimal:
        """计算单笔交易的总成本。"""
        notional = price * qty
        commission = max(notional * self.commission_rate, self.min_commission)
        spread = notional * (self.spread_bps / Decimal("10000"))
        if is_buy:
            return commission + spread + spread  # 买入: 佣金 + 价差
        else:
            return commission + spread  # 卖出: 佣金 + 价差

    def adjusted_price(self, price: Decimal, is_buy: bool, volatility: Decimal | None = None) -> Decimal:
        """返回含滑点的调整价格。"""
        base_slip = self.slippage_base
        if volatility is not None:
            base_slip = base_slip + volatility * self.slippage_volatility_factor
        if is_buy:
            return price * (Decimal("1") + base_slip)
        else:
            return price * (Decimal("1") - base_slip)


class ExecutionEngine:
    """模拟交易执行引擎 (Paper Trading Only)."""

    # 滑点范围 (用于随机模式)
    MIN_SLIPPAGE = Decimal("0.001")    # 0.1%
    MAX_SLIPPAGE = Decimal("0.003")    # 0.3%

    # 部分成交比例 (REDUCE 时)
    REDUCE_FILL_RATIO = Decimal("0.5")  # 减仓一半

    # 延迟范围 (ms)
    MIN_LATENCY_MS = 0
    MAX_LATENCY_MS = 200

    def __init__(
        self,
        deterministic: bool = False,
        seed: int = 42,
        cost_model: TransactionCostModel | None = None,
    ) -> None:
        """初始化执行引擎。

        Args:
            deterministic: 如果为 True，使用固定种子 RNG（用于测试）
            seed: 随机种子
            cost_model: 交易成本模型（默认保守值）
        """
        self._cost_model = cost_model or TransactionCostModel()
        self._rng = random.Random(seed) if deterministic else random.Random()
        self._deterministic = deterministic
        self._order_counter = 0

    def submit_order(
        self,
        decision: Decision,
        market_price: Decimal,
        requested_qty: Decimal | None = None,
    ) -> ExecutionResult | None:
        """提交订单进行模拟执行。

        Args:
            decision: DecisionEngine 的最终决策
            market_price: 当前市场价格
            requested_qty: 请求数量（可选，默认 100 股）

        Returns:
            ExecutionResult 或 None（HOLD 不执行）
        """
        self._order_counter += 1
        order_id = f"SIM-{self._order_counter:06d}"

        action = decision.action
        submitted = {
            "order_id": order_id,
            "symbol": decision.symbol,
            "action": action.value,
            "market_price": str(market_price),
            "requested_qty": str(requested_qty) if requested_qty is not None else None,
        }
        event_bus.publish(ORDER_SUBMITTED, {"execution_order": submitted})

        # HOLD → 不执行
        if action == DecisionAction.HOLD:
            return ExecutionResult(
                order_id=order_id,
                symbol=decision.symbol,
                action=action.value,
                status=OrderStatus.NO_OP,
                slippage=Decimal("0"),
            )

        # BLOCKED → REJECTED
        if action == DecisionAction.BLOCKED:
            result = self._reject_order(order_id, decision, "Order BLOCKED by RiskEngine")
            event_bus.publish(ORDER_REJECTED, {"execution_result": result.to_dict()})
            return result

        qty = requested_qty or Decimal("100")
        latency = self._simulate_latency()

        # BUY / SELL → 尝试成交
        if action in (DecisionAction.BUY, DecisionAction.SELL):
            slippage = self._simulate_slippage()
            is_buy = action == DecisionAction.BUY
            fill_price = self._calc_fill_price(market_price, slippage, is_buy)

            # 模拟成交延迟
            self._sleep_ms(latency)

            result = ExecutionResult(
                order_id=order_id,
                symbol=decision.symbol,
                action=action.value,
                status=OrderStatus.FILLED,
                fill_price=fill_price,
                slippage=slippage,
                filled_qty=qty,
                requested_qty=qty,
                latency_ms=latency,
            )
            event_bus.publish(ORDER_FILLED, {"execution_result": result.to_dict()})
            return result

        # REDUCE → 部分成交
        if action == DecisionAction.REDUCE:
            slippage = self._simulate_slippage()
            fill_price = self._calc_fill_price(market_price, slippage, is_buy=False)
            filled_qty = (qty * self.REDUCE_FILL_RATIO).quantize(Decimal("1"))
            latency = self._simulate_latency()

            self._sleep_ms(latency)

            result = ExecutionResult(
                order_id=order_id,
                symbol=decision.symbol,
                action=action.value,
                status=OrderStatus.PARTIAL,
                fill_price=fill_price,
                slippage=slippage,
                filled_qty=filled_qty,
                requested_qty=qty,
                latency_ms=latency,
            )
            event_bus.publish(ORDER_FILLED, {"execution_result": result.to_dict()})
            return result

        # 未知 action → REJECTED
        result = self._reject_order(order_id, decision, f"Unknown action: {action.value}")
        event_bus.publish(ORDER_REJECTED, {"execution_result": result.to_dict()})
        return result

    def simulate_fill(
        self,
        decision: Decision,
        market_price: Decimal,
        qty: Decimal = Decimal("100"),
    ) -> ExecutionResult:
        """直接模拟全额成交（无延迟/无滑点），用于确定性测试。"""
        order_id = f"SIM-FILL-{self._order_counter:06d}"
        self._order_counter += 1

        result = ExecutionResult(
            order_id=order_id,
            symbol=decision.symbol,
            action=decision.action.value,
            status=OrderStatus.FILLED,
            fill_price=market_price,
            slippage=Decimal("0"),
            filled_qty=qty,
            requested_qty=qty,
        )
        event_bus.publish(ORDER_SUBMITTED, {"execution_order": {
            "order_id": order_id, "symbol": decision.symbol,
            "action": decision.action.value, "market_price": str(market_price),
            "requested_qty": str(qty),
        }})
        event_bus.publish(ORDER_FILLED, {"execution_result": result.to_dict()})
        return result

    def reject_order(
        self,
        decision: Decision,
        reason: str = "Manual reject",
    ) -> ExecutionResult:
        """手动拒绝订单。"""
        order_id = f"SIM-REJ-{self._order_counter:06d}"
        self._order_counter += 1
        event_bus.publish(ORDER_SUBMITTED, {"execution_order": {
            "order_id": order_id, "symbol": decision.symbol,
            "action": decision.action.value, "market_price": None, "requested_qty": None,
        }})
        result = self._reject_order(order_id, decision, reason)
        event_bus.publish(ORDER_REJECTED, {"execution_result": result.to_dict()})
        return result

    def partial_fill(
        self,
        decision: Decision,
        market_price: Decimal,
        fill_ratio: Decimal = Decimal("0.5"),
    ) -> ExecutionResult:
        """模拟部分成交。"""
        order_id = f"SIM-PARTIAL-{self._order_counter:06d}"
        self._order_counter += 1
        slippage = self._simulate_slippage()
        is_buy = decision.action == DecisionAction.BUY
        fill_price = self._calc_fill_price(market_price, slippage, is_buy)
        qty = Decimal("100")
        filled = (qty * fill_ratio).quantize(Decimal("1"))

        result = ExecutionResult(
            order_id=order_id,
            symbol=decision.symbol,
            action=decision.action.value,
            status=OrderStatus.PARTIAL,
            fill_price=fill_price,
            slippage=slippage,
            filled_qty=filled,
            requested_qty=qty,
        )
        event_bus.publish(ORDER_FILLED, {"execution_result": result.to_dict()})
        return result

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _reject_order(self, order_id: str, decision: Decision, reason: str) -> ExecutionResult:
        return ExecutionResult(
            order_id=order_id,
            symbol=decision.symbol,
            action=decision.action.value,
            status=OrderStatus.REJECTED,
            reject_reason=reason,
        )

    def _simulate_slippage(self) -> Decimal:
        """生成随机滑点 (0~0.1%)。"""
        raw = self._rng.random()  # 0.0 ~ 1.0
        slippage = self.MIN_SLIPPAGE + (self.MAX_SLIPPAGE - self.MIN_SLIPPAGE) * Decimal(str(raw))
        return slippage

    def _calc_fill_price(
        self, market_price: Decimal, slippage: Decimal, is_buy: bool
    ) -> Decimal:
        """计算含滑点的成交价。"""
        if is_buy:
            return market_price * (Decimal("1") + slippage)
        else:
            return market_price * (Decimal("1") - slippage)

    def _simulate_latency(self) -> float:
        """生成随机延迟 (0~200ms)。"""
        if self._deterministic:
            # 测试模式下，返回固定延迟
            return 50.0
        return self._rng.uniform(self.MIN_LATENCY_MS, self.MAX_LATENCY_MS)

    def _sleep_ms(self, ms: float) -> None:
        """模拟延迟等待。"""
        if self._deterministic:
            # 测试模式下跳过延迟
            return
        if ms > 0:
            time.sleep(ms / 1000.0)

    @property
    def deterministic(self) -> bool:
        return self._deterministic

    def set_seed(self, seed: int) -> None:
        """重置随机种子（用于测试）。"""
        self._rng = random.Random(seed)


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

execution_engine = ExecutionEngine()
