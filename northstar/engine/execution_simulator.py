#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""执行仿真层 — 模拟真实交易执行，生成 portfolio 变化路径。

用法：
    from northstar.engine.execution_simulator import ExecutionSimulator
    sim = ExecutionSimulator(initial_cash=10000)
    sim.execute_decision("AAPL", "BUY", price=150.0, qty=10)
    status = sim.get_portfolio_status()
    history = sim.get_execution_history()
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


class ExecutionSimulator:
    """交易执行仿真器。

    模拟 BUY/SELL/HOLD 决策的真实执行效果，维护现金、持仓、交易历史。
    """

    def __init__(self, initial_cash: float = 10000.0) -> None:
        self.cash: float = initial_cash
        self.positions: dict[str, float] = {}  # symbol -> qty
        self.history: list[dict[str, Any]] = []
        self._total_buy_cost: float = 0.0
        self._total_sell_proceeds: float = 0.0

    def _get_position_value(self, prices: dict[str, float] | None = None) -> float:
        """计算持仓市值。"""
        total = 0.0
        for symbol, qty in self.positions.items():
            price = (prices or {}).get(symbol, 0.0)
            total += qty * price
        return total

    def _calculate_qty(self, price: float, max_cost: float | None = None) -> float:
        """根据价格和可用资金计算可买数量。"""
        available = max_cost if max_cost is not None else self.cash
        if price <= 0 or available <= 0:
            return 0.0
        return int(available / price)

    def _record_trade(
        self,
        symbol: str,
        action: str,
        price: float,
        qty: float,
        cost: float,
        reason: str = "",
    ) -> None:
        """记录交易到历史。"""
        self.history.append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": symbol.upper(),
            "action": action,
            "price": round(price, 2),
            "qty": qty,
            "cost": round(cost, 2),
            "cash_after": round(self.cash, 2),
            "reason": reason,
        })

    def execute_decision(
        self,
        symbol: str,
        action: str,
        price: float,
        qty: float | None = None,
        max_cost: float | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        """执行一条交易决策。

        Args:
            symbol: 股票代码
            action: BUY / SELL / HOLD
            price: 执行价格
            qty: 数量（BUY 时不传则自动计算，SELL 时不传则全卖）
            max_cost: BUY 时最大花费（不传则用全部现金）
            reason: 决策原因

        Returns:
            {"success": bool, "action": str, "qty": float, "cost": float, "message": str}
        """
        symbol = symbol.upper()
        action = action.upper()

        if action == "HOLD":
            self._record_trade(symbol, "HOLD", price, 0, 0.0, reason)
            return {"success": True, "action": "HOLD", "qty": 0, "cost": 0.0, "message": "HOLD 无操作"}

        if action == "BUY":
            if price <= 0:
                return {"success": False, "action": "BUY", "qty": 0, "cost": 0.0, "message": "价格无效"}
            if qty is None:
                qty = self._calculate_qty(price, max_cost)
            if qty <= 0:
                return {"success": False, "action": "BUY", "qty": 0, "cost": 0.0, "message": "现金不足"}
            cost = round(qty * price, 2)
            if cost > self.cash:
                qty = self._calculate_qty(price, self.cash)
                cost = round(qty * price, 2)
                if qty <= 0:
                    return {"success": False, "action": "BUY", "qty": 0, "cost": 0.0, "message": "现金不足"}
            self.cash -= cost
            self.positions[symbol] = self.positions.get(symbol, 0.0) + qty
            self._total_buy_cost += cost
            self._record_trade(symbol, "BUY", price, qty, cost, reason)
            return {"success": True, "action": "BUY", "qty": qty, "cost": cost, "message": f"买入 {qty} 股 ${symbol}"}

        if action == "SELL":
            current_qty = self.positions.get(symbol, 0.0)
            if current_qty <= 0:
                return {"success": False, "action": "SELL", "qty": 0, "cost": 0.0, "message": f"无 {symbol} 持仓"}
            if qty is None or qty > current_qty:
                qty = current_qty
            proceeds = round(qty * price, 2)
            self.cash += proceeds
            self.positions[symbol] = current_qty - qty
            if self.positions[symbol] <= 0:
                del self.positions[symbol]
            self._total_sell_proceeds += proceeds
            self._record_trade(symbol, "SELL", price, qty, -proceeds, reason)
            return {"success": True, "action": "SELL", "qty": qty, "cost": -proceeds, "message": f"卖出 {qty} 股 ${symbol}"}

        return {"success": False, "action": action, "qty": 0, "cost": 0.0, "message": f"未知动作 {action}"}

    def get_portfolio_status(self, prices: dict[str, float] | None = None) -> dict[str, Any]:
        """获取当前组合状态。

        Args:
            prices: 当前价格 {"AAPL": 150.0}，用于计算持仓市值

        Returns:
            {
                "cash": float,
                "positions": dict,
                "position_value": float,
                "total_value": float,
                "trade_count": int,
            }
        """
        pos_value = self._get_position_value(prices)
        return {
            "cash": round(self.cash, 2),
            "positions": dict(self.positions),
            "position_value": round(pos_value, 2),
            "total_value": round(self.cash + pos_value, 2),
            "trade_count": len(self.history),
        }

    def get_execution_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """获取执行历史。"""
        recent = self.history[-limit:]
        recent.reverse()
        return recent

    def get_summary(self) -> dict[str, Any]:
        """获取仿真摘要。"""
        buys = sum(1 for h in self.history if h["action"] == "BUY")
        sells = sum(1 for h in self.history if h["action"] == "SELL")
        holds = sum(1 for h in self.history if h["action"] == "HOLD")
        total_inflow = self._total_sell_proceeds + (self.cash - sum(
            h["cost"] for h in self.history if h["action"] == "BUY"
        ))
        return {
            "initial_cash": round(self.cash + self._total_buy_cost - self._total_sell_proceeds, 2) if self.history else round(self.cash, 2),
            "current_cash": round(self.cash, 2),
            "positions_count": len(self.positions),
            "total_trades": len(self.history),
            "buys": buys,
            "sells": sells,
            "holds": holds,
        }

    def reset(self, initial_cash: float | None = None) -> None:
        """重置仿真器。"""
        self.cash = initial_cash if initial_cash is not None else self.cash
        self.positions = {}
        self.history = []
        self._total_buy_cost = 0.0
        self._total_sell_proceeds = 0.0