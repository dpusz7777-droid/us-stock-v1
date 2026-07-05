#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""执行现实层 — 模拟真实市场执行误差（滑点、冲击、延迟、部分成交）。

在paper_trading基础上叠加市场摩擦，使回测更接近真实市场表现。

用法：
    from northstar.execution.execution_reality_engine import ExecutionRealityEngine
    ere = ExecutionRealityEngine()
    result = ere.execute_realistic_trade(signal, market_data)
    report = ere.get_execution_report()
"""

from __future__ import annotations

import json
import math
import random
from datetime import date, datetime
from pathlib import Path
from typing import Any


class ExecutionRealityEngine:
    """执行现实层引擎 — 模拟真实市场摩擦。"""

    def __init__(self) -> None:
        self._trades: list[dict] = []
        self._pending_orders: list[dict] = []
        self._base_slippage: float = 0.0001  # 0.01%
        self._impact_k: float = 0.1
        self._avg_volumes: dict[str, float] = {
            "NVDA": 50000000, "MSFT": 30000000, "META": 25000000,
            "AMD": 40000000, "TSM": 15000000, "AAPL": 60000000,
            "GOOG": 20000000, "TSLA": 35000000, "AMZN": 40000000,
            "PLTR": 80000000, "CRM": 10000000, "XLE": 5000000,
            "AVGO": 15000000, "SPY": 80000000, "QQQ": 40000000,
        }

    def slippage_model(self, order: dict, market_price: float) -> float:
        """计算滑点百分比。

        slippage_pct = base_slippage + volatility_factor + liquidity_penalty
        """
        symbol = order.get("symbol", "")
        atr = order.get("atr", market_price * 0.02)
        volatility_factor = (atr / market_price) * 0.5 if market_price > 0 else 0.001

        avg_vol = self._avg_volumes.get(symbol, 10000000)
        order_size = order.get("order_size", 10000)
        liquidity_penalty = min(0.003, max(0.0001, order_size / avg_vol * 0.1))

        slippage = self._base_slippage + volatility_factor + liquidity_penalty
        return round(slippage, 6)

    def market_impact_model(self, order_size: float, avg_volume: float) -> float:
        """计算市场冲击百分比。

        impact = k × sqrt(order_size / avg_volume)
        """
        if avg_volume <= 0 or order_size <= 0:
            return 0.0
        ratio = order_size / avg_volume
        impact = self._impact_k * math.sqrt(ratio)
        return round(min(impact, 0.05), 6)

    def latency_model(self) -> tuple[float, float]:
        """计算延迟影响。

        Returns:
            (latency_ms, price_drift_pct)
        """
        latency_ms = random.uniform(50, 2000)
        price_drift_pct = random.uniform(-0.0005, 0.0005) * (latency_ms / 1000)
        return round(latency_ms, 1), round(price_drift_pct, 6)

    def partial_fill_model(self, order_size: float, avg_volume: float) -> float:
        """计算部分成交比例。

        Returns:
            fill_rate (0~1)
        """
        if avg_volume <= 0:
            return 1.0
        size_ratio = order_size / avg_volume
        if size_ratio > 0.05:
            fill_rate = max(0.3, 1.0 - size_ratio * 2)
        else:
            fill_rate = 1.0
        return round(fill_rate, 2)

    def execute_realistic_trade(
        self,
        signal: dict[str, Any],
        market_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行带市场摩擦的模拟交易。

        Args:
            signal: 交易信号
            market_data: 市场数据（包含价格、波动率等）

        Returns:
            执行结果
        """
        symbol = signal.get("symbol", "")
        action = signal.get("signal", "WATCH")
        confidence = signal.get("confidence", 0.5)
        market_price = 100.0
        atr = market_price * 0.02

        if market_data and isinstance(market_data, dict):
            prices = market_data.get(symbol, [])
            if prices:
                market_price = prices[-1] if isinstance(prices, list) else prices
            atr_val = market_data.get(f"{symbol}_atr", None)
            if atr_val:
                atr = atr_val

        if action not in ("BUY", "SELL"):
            return {"action": "SKIP", "symbol": symbol, "reason": f"非交易信号: {action}"}

        order_size = 10000.0 + confidence * 50000.0

        # 1. 延迟模型
        latency_ms, price_drift = self.latency_model()

        # 2. 滑点模型
        slippage_pct = self.slippage_model({"symbol": symbol, "order_size": order_size, "atr": atr}, market_price)

        # 3. 市场冲击
        avg_vol = self._avg_volumes.get(symbol, 10000000)
        impact_pct = self.market_impact_model(order_size, avg_vol)

        # 4. 部分成交
        fill_rate = self.partial_fill_model(order_size, avg_vol)

        # 5. 计算成交价格
        drift_adjustment = market_price * price_drift
        if action == "BUY":
            execution_price = market_price * (1 + slippage_pct + impact_pct) + drift_adjustment
            slippage_cost = market_price * slippage_pct * order_size * fill_rate
        else:
            execution_price = market_price * (1 - slippage_pct - impact_pct) + drift_adjustment
            slippage_cost = market_price * slippage_pct * order_size * fill_rate

        filled_qty = order_size * fill_rate
        impact_cost = market_price * impact_pct * filled_qty
        latency_cost = abs(drift_adjustment) * filled_qty

        # 6. 理论 vs 实际
        theoretical_return = (execution_price - market_price) / market_price * 100 if action == "BUY" else (market_price - execution_price) / market_price * 100
        theoretical_return = round(theoretical_return, 2)

        trade = {
            "symbol": symbol,
            "action": action,
            "market_price": round(market_price, 2),
            "execution_price": round(execution_price, 2),
            "order_size": round(order_size, 2),
            "filled_size": round(filled_qty, 2),
            "fill_rate": fill_rate,
            "slippage_pct": round(slippage_pct * 100, 4),
            "impact_pct": round(impact_pct * 100, 4),
            "latency_ms": latency_ms,
            "price_drift_pct": round(price_drift * 100, 4),
            "slippage_cost": round(slippage_cost, 2),
            "impact_cost": round(impact_cost, 2),
            "latency_cost": round(latency_cost, 2),
            "theoretical_return": round((execution_price - market_price) / market_price * 100, 2) if action == "BUY" else round((market_price - execution_price) / market_price * 100, 2),
        }
        self._trades.append(trade)

        # 未成交部分进入等待队列
        if fill_rate < 1.0:
            remaining = round(order_size * (1 - fill_rate), 2)
            self._pending_orders.append({
                "symbol": symbol,
                "action": action,
                "remaining_size": remaining,
                "created_at": datetime.now().isoformat(),
            })

        return trade

    def get_execution_report(self) -> dict[str, Any]:
        """获取执行报告。"""
        if not self._trades:
            return {
                "theoretical_return": 0.0, "realistic_return": 0.0, "slippage_cost": 0.0,
                "market_impact_cost": 0.0, "latency_cost": 0.0, "fill_rate": 1.0, "execution_gap": 0.0,
            }

        total_slippage = sum(t["slippage_cost"] for t in self._trades)
        total_impact = sum(t["impact_cost"] for t in self._trades)
        total_latency = sum(t["latency_cost"] for t in self._trades)
        avg_fill_rate = sum(t["fill_rate"] for t in self._trades) / len(self._trades)
        total_theoretical = sum(t["theoretical_return"] for t in self._trades)

        # realistic: subtract costs as % of notional
        total_notional = sum(t["market_price"] * t["order_size"] for t in self._trades) / max(len(self._trades), 1)
        cost_pct = (total_slippage + total_impact + total_latency) / max(total_notional, 1) * 100
        realistic_return = round(total_theoretical / max(len(self._trades), 1) - cost_pct, 2)

        result = {
            "theoretical_return": round(total_theoretical / max(len(self._trades), 1), 2),
            "realistic_return": realistic_return,
            "slippage_cost": round(-total_slippage / max(len(self._trades), 1), 2),
            "market_impact_cost": round(-total_impact / max(len(self._trades), 1), 2),
            "latency_cost": round(-total_latency / max(len(self._trades), 1), 2),
            "fill_rate": round(avg_fill_rate, 2),
            "execution_gap": round(realistic_return - total_theoretical / max(len(self._trades), 1), 2),
            "pending_orders": len(self._pending_orders),
        }

        today = date.today().isoformat().replace("-", "")
        reports_dir = Path(__file__).parent.parent.parent / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_file = reports_dir / f"execution_reality_{today}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        return result

    def get_pending_orders(self) -> list[dict]:
        """获取未成交订单。"""
        return self._pending_orders

    def reset(self) -> None:
        """重置引擎。"""
        self._trades = []
        self._pending_orders = []