#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模拟盘执行器 — 虚拟交易 + 组合跟踪 + 资金曲线。

每次执行 trade 后自动更新 EquityCurve 并写入 equity_curve.json。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from northstar.data.trade_history import TradeHistory
from northstar.backtest.equity_curve import EquityCurve


@dataclass(frozen=True)
class SimulatedPosition:
    """模拟持仓。"""
    symbol: str
    shares: Decimal
    avg_cost: Decimal
    current_price: Decimal | None
    market_value: Decimal | None
    unrealized_pnl: Decimal | None


@dataclass(frozen=True)
class SimulatedPortfolio:
    """模拟组合完整状态。"""
    cash: Decimal
    total_cost: Decimal
    total_market_value: Decimal | None
    total_equity: Decimal | None
    total_pnl: Decimal | None
    positions: tuple[SimulatedPosition, ...]
    trade_count: int


CURVE_FILE = Path(__file__).parent.parent / "data" / "equity_curve.json"


class Simulator:
    """模拟盘执行器。

    用法：
        sim = Simulator(initial_capital=10000.0)
        sim.execute("NVDA", "buy", price=195.0, qty=10)
        portfolio = sim.portfolio()
        sim.save_equity_curve()  # 生成 equity_curve.json
    """

    def __init__(
        self,
        initial_capital: float = 10000.0,
        log_path: Path | None = None,
    ) -> None:
        self._cash = Decimal(str(initial_capital))
        self._positions: dict[str, dict[str, Any]] = {}
        self._trade_count = 0
        self._history = TradeHistory(path=log_path) if log_path else TradeHistory()
        self._equity_curve = EquityCurve(
            initial_capital=initial_capital,
            path=CURVE_FILE,
            history=self._history,
        )
        self._initial_capital = initial_capital
        self._has_saved_curve = False

    def execute(
        self,
        symbol: str,
        action: str,
        price: float | None,
        quantity: int = 0,
        reason: str = "",
    ) -> bool:
        """执行一条模拟交易，并更新资金曲线。"""
        if action not in ("buy", "sell"):
            return False
        if price is None or price <= 0:
            return False

        sym = symbol.upper()
        cost = Decimal(str(price)) * Decimal(str(quantity))

        if action == "buy":
            if cost > self._cash:
                return False  # 资金不足
            self._cash -= cost
            if sym in self._positions:
                pos = self._positions[sym]
                total_shares = pos["shares"] + Decimal(str(quantity))
                total_cost = pos["cost_basis"] + cost
                pos["shares"] = total_shares
                pos["avg_cost"] = total_cost / total_shares
                pos["cost_basis"] = total_cost
            else:
                self._positions[sym] = {
                    "shares": Decimal(str(quantity)),
                    "avg_cost": Decimal(str(price)),
                    "cost_basis": cost,
                }

        elif action == "sell":
            if sym not in self._positions:
                return False
            pos = self._positions[sym]
            if Decimal(str(quantity)) > pos["shares"]:
                return False
            pos["shares"] -= Decimal(str(quantity))
            self._cash += cost
            if pos["shares"] <= 0:
                del self._positions[sym]

        self._trade_count += 1
        self._history.record(sym, action, price, quantity, reason)

        # ★ 更新资金曲线
        date = datetime.now().strftime("%Y-%m-%d")
        self._equity_curve.update(action, sym, price, quantity, date)

        return True

    def save_equity_curve(self) -> None:
        """保存资金曲线到 JSON 文件。"""
        self._equity_curve.save(CURVE_FILE)
        self._has_saved_curve = True

    def save_trade_history(self) -> Path:
        """Persist the real trade history without manufacturing records."""
        return self._history.save()

    def record_equity_snapshot(
        self,
        *,
        timestamp: str | None = None,
        position_count: int | None = None,
    ) -> dict[str, Any]:
        """Append the currently observed simulated portfolio value."""
        portfolio = self.portfolio()
        return self._equity_curve.append_point(
            equity=portfolio.total_equity or Decimal("0"),
            cash=portfolio.cash,
            timestamp=timestamp,
            position_count=position_count,
        )

    def rebuild_curve_from_history(self) -> list[dict[str, Any]]:
        """从 trade_history.json 重建完整资金曲线。
        
        用于跨 session 恢复（连续运行不重置）。
        """
        curve_points = self._equity_curve.update_from_history()
        self._equity_curve.save(CURVE_FILE)
        self._has_saved_curve = True
        return self._equity_curve.get_curve()

    def get_equity_curve(self) -> list[dict[str, Any]]:
        """获取当前资金曲线数据。"""
        return self._equity_curve.get_curve()

    def portfolio(self) -> SimulatedPortfolio:
        """获取当前模拟组合状态。"""
        total_cost = Decimal("0")
        positions = []
        for sym, data in self._positions.items():
            pos = SimulatedPosition(
                symbol=sym,
                shares=data["shares"],
                avg_cost=data["avg_cost"],
                current_price=None,
                market_value=None,
                unrealized_pnl=None,
            )
            total_cost += data["cost_basis"]
            positions.append(pos)

        total_equity = self._cash + total_cost
        return SimulatedPortfolio(
            cash=self._cash,
            total_cost=total_cost,
            total_market_value=total_cost,
            total_equity=total_equity,
            total_pnl=total_equity - Decimal(str(self._initial_capital)),
            positions=tuple(positions),
            trade_count=self._trade_count,
        )

    def pnl(self) -> float:
        """获取总盈亏。"""
        p = self.portfolio()
        if p.total_equity is None:
            return 0.0
        return float(p.total_equity - Decimal(str(self._initial_capital)))

    def reset(self, initial_capital: float = 10000.0) -> None:
        """重置模拟盘。"""
        self._cash = Decimal(str(initial_capital))
        self._positions = {}
        self._trade_count = 0
        self._initial_capital = initial_capital
        self._equity_curve = EquityCurve(
            initial_capital=initial_capital,
            path=CURVE_FILE,
            history=self._history,
        )
        self._has_saved_curve = False
