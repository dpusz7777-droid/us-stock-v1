#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实时账户引擎 — 统一账户状态抽象层，支持模拟/真实/回测三种模式。

系统资金状态的唯一真相源（Single Source of Truth）。

用法：
    from northstar.engine.portfolio_engine import PortfolioEngine
    pe = PortfolioEngine(initial_cash=10000, mode="paper")
    pe.buy("AAPL", price=150.0, qty=10)
    pe.sell("AAPL", price=160.0, qty=5)
    snapshot = pe.get_snapshot()
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


SUPPORTED_MODES = ("paper", "live", "backtest")


class PortfolioEngine:
    """统一账户状态引擎。

    属性：
        cash: 当前现金
        positions: {symbol -> qty}
        avg_cost: {symbol -> 平均成本价}
        realized_pnl: 已实现盈亏
        mode: 账户模式 (paper / live / backtest)
    """

    def __init__(
        self,
        initial_cash: float = 10000.0,
        mode: str = "paper",
    ) -> None:
        if mode not in SUPPORTED_MODES:
            raise ValueError(f"不支持的账户模式: {mode}，可选: {SUPPORTED_MODES}")
        self.mode: str = mode
        self.cash: float = initial_cash
        self.positions: dict[str, float] = {}       # symbol -> qty
        self.avg_cost: dict[str, float] = {}         # symbol -> avg cost per share
        self.realized_pnl: float = 0.0
        self._trade_log: list[dict[str, Any]] = []

    # ── 核心交易方法 ──

    def buy(
        self,
        symbol: str,
        price: float,
        qty: float,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        """买入操作，更新持仓和平均成本。"""
        symbol = symbol.upper()
        ts = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if price <= 0 or qty <= 0:
            return {"success": False, "message": "价格或数量无效", "symbol": symbol}

        cost = round(price * qty, 2)
        if cost > self.cash:
            return {"success": False, "message": f"现金不足: 需要 {cost}，可用 {self.cash}", "symbol": symbol}

        # 更新现金
        self.cash -= cost

        # 更新持仓和平均成本
        old_qty = self.positions.get(symbol, 0.0)
        old_cost = self.avg_cost.get(symbol, 0.0)
        new_qty = old_qty + qty
        if new_qty > 0:
            self.avg_cost[symbol] = round((old_cost * old_qty + price * qty) / new_qty, 2)
        self.positions[symbol] = new_qty

        self._log_trade(ts, symbol, "BUY", price, qty, cost)
        return {"success": True, "message": f"买入 {qty} 股 {symbol} @ ${price}", "symbol": symbol, "qty": qty, "cost": cost}

    def sell(
        self,
        symbol: str,
        price: float,
        qty: float | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        """卖出操作，更新现金和已实现盈亏。"""
        symbol = symbol.upper()
        ts = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        current_qty = self.positions.get(symbol, 0.0)
        if current_qty <= 0:
            return {"success": False, "message": f"无 {symbol} 持仓", "symbol": symbol}

        if qty is None or qty > current_qty:
            qty = current_qty

        if price <= 0 or qty <= 0:
            return {"success": False, "message": "价格或数量无效", "symbol": symbol}

        proceeds = round(price * qty, 2)
        cost_basis = round(self.avg_cost.get(symbol, 0.0) * qty, 2)
        trade_pnl = round(proceeds - cost_basis, 2)

        # 更新现金
        self.cash += proceeds

        # 更新已实现盈亏
        self.realized_pnl += trade_pnl

        # 更新持仓
        new_qty = current_qty - qty
        if new_qty <= 0:
            del self.positions[symbol]
            del self.avg_cost[symbol]
        else:
            self.positions[symbol] = new_qty
            # avg_cost 不变（剩余部分仍按原均价）

        self._log_trade(ts, symbol, "SELL", price, qty, -proceeds, trade_pnl)
        return {"success": True, "message": f"卖出 {qty} 股 {symbol} @ ${price}，盈亏 ${trade_pnl}", "symbol": symbol, "qty": qty, "pnl": trade_pnl}

    def hold(self, symbol: str, timestamp: str | None = None) -> dict[str, Any]:
        """持有操作，仅记录无交易。"""
        symbol = symbol.upper()
        ts = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._log_trade(ts, symbol, "HOLD", 0.0, 0, 0.0, 0.0)
        return {"success": True, "message": f"HOLD {symbol}", "symbol": symbol}

    # ── 快照与查询 ──

    def get_snapshot(self, market_prices: dict[str, float] | None = None) -> dict[str, Any]:
        """获取完整账户快照。

        Args:
            market_prices: 当前市价 {symbol -> price}，用于计算未实现盈亏

        Returns:
            {
                "mode": str,
                "cash": float,
                "positions": list[dict],
                "position_value": float,
                "total_value": float,
                "realized_pnl": float,
                "unrealized_pnl": float,
                "total_pnl": float,
                "trade_count": int,
            }
        """
        positions_list = []
        position_value = 0.0
        unrealized_pnl = 0.0

        for symbol, qty in sorted(self.positions.items()):
            avg_c = self.avg_cost.get(symbol, 0.0)
            mkt_p = (market_prices or {}).get(symbol, avg_c)
            val = round(qty * mkt_p, 2)
            upnl = round((mkt_p - avg_c) * qty, 2) if avg_c > 0 else 0.0
            positions_list.append({
                "symbol": symbol,
                "qty": qty,
                "avg_cost": avg_c,
                "market_price": mkt_p,
                "value": val,
                "unrealized_pnl": upnl,
                "return_pct": round((mkt_p - avg_c) / avg_c * 100, 2) if avg_c > 0 else 0.0,
            })
            position_value += val
            unrealized_pnl += upnl

        return {
            "mode": self.mode,
            "cash": round(self.cash, 2),
            "positions": positions_list,
            "position_value": round(position_value, 2),
            "total_value": round(self.cash + position_value, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "total_pnl": round(self.realized_pnl + unrealized_pnl, 2),
            "trade_count": len(self._trade_log),
        }

    def get_position(self, symbol: str) -> dict[str, Any] | None:
        """获取单个持仓详情。"""
        symbol = symbol.upper()
        if symbol not in self.positions:
            return None
        return {
            "symbol": symbol,
            "qty": self.positions[symbol],
            "avg_cost": self.avg_cost.get(symbol, 0.0),
        }

    def get_trade_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """获取交易历史。"""
        recent = self._trade_log[-limit:]
        recent.reverse()
        return recent

    def get_summary(self) -> dict[str, Any]:
        """获取引擎摘要。"""
        invested = sum(
            self.avg_cost[s] * self.positions[s]
            for s in self.positions
        )
        return {
            "mode": self.mode,
            "cash": round(self.cash, 2),
            "positions_count": len(self.positions),
            "total_invested": round(invested, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "trade_count": len(self._trade_log),
        }

    # ── 内部方法 ──

    def _log_trade(
        self,
        timestamp: str,
        symbol: str,
        action: str,
        price: float,
        qty: float,
        cost: float,
        pnl: float = 0.0,
    ) -> None:
        self._trade_log.append({
            "timestamp": timestamp,
            "symbol": symbol,
            "action": action,
            "price": round(price, 2),
            "qty": qty,
            "cost": round(cost, 2),
            "pnl": round(pnl, 2),
            "cash_after": round(self.cash, 2),
        })

    def reset(self, initial_cash: float | None = None) -> None:
        """重置引擎。"""
        self.cash = initial_cash if initial_cash is not None else self.cash
        self.positions = {}
        self.avg_cost = {}
        self.realized_pnl = 0.0
        self._trade_log = []