#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Simulation equity-curve storage and statistics.

This is an infrastructure implementation created to complete the existing
Simulator call contract; it is not a historical restoration.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from northstar.data.trade_history import TradeHistory, TradeRecord


DEFAULT_CURVE_FILE = Path(__file__).parent.parent / "data" / "equity_curve.json"


class EquityCurve:
    """Store, rebuild, serialize, and summarize a simulated equity curve."""

    def __init__(
        self,
        initial_capital: float = 10000.0,
        path: Path | None = DEFAULT_CURVE_FILE,
        history: TradeHistory | None = None,
    ) -> None:
        if initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        self._initial_capital = Decimal(str(initial_capital))
        self._path = path
        self._history = history or TradeHistory()
        self._cash = self._initial_capital
        self._positions: dict[str, dict[str, Decimal]] = {}
        self._last_prices: dict[str, Decimal] = {}
        self._curve: list[dict[str, Any]] = []
        if path is not None and path.exists():
            self.load(path)

    def update(
        self,
        action: str,
        symbol: str,
        price: float,
        quantity: int,
        date: str | None = None,
    ) -> dict[str, Any]:
        """Apply a real simulated trade and append its resulting equity point."""
        if action not in {"buy", "sell"}:
            raise ValueError(f"unsupported action: {action}")
        if price <= 0:
            raise ValueError("price must be positive")
        if quantity <= 0:
            raise ValueError("quantity must be positive")

        symbol = symbol.upper()
        px = Decimal(str(price))
        qty = Decimal(str(quantity))
        value = px * qty
        self._last_prices[symbol] = px

        if action == "buy":
            if value > self._cash:
                raise ValueError("insufficient simulated cash")
            self._cash -= value
            position = self._positions.setdefault(
                symbol, {"shares": Decimal("0"), "cost_basis": Decimal("0")}
            )
            position["shares"] += qty
            position["cost_basis"] += value
        else:
            position = self._positions.get(symbol)
            if position is None or qty > position["shares"]:
                raise ValueError(f"insufficient simulated shares for {symbol}")
            old_shares = position["shares"]
            position["shares"] -= qty
            position["cost_basis"] *= position["shares"] / old_shares
            self._cash += value
            if position["shares"] == 0:
                del self._positions[symbol]

        timestamp = date or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return self.append_point(
            equity=self._current_equity(),
            cash=self._cash,
            timestamp=timestamp,
            position_count=len(self._positions),
        )

    def append_point(
        self,
        equity: float | Decimal,
        *,
        cash: float | Decimal | None = None,
        timestamp: str | None = None,
        position_count: int | None = None,
    ) -> dict[str, Any]:
        """Append one observed simulated account snapshot."""
        equity_value = Decimal(str(equity))
        cash_value = Decimal(str(cash)) if cash is not None else None
        ts = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        point = {
            "date": ts[:10],
            "timestamp": ts,
            "equity": round(float(equity_value), 2),
            "cash": round(float(cash_value), 2) if cash_value is not None else None,
            "pnl": round(float(equity_value - self._initial_capital), 2),
            "position_count": (
                position_count if position_count is not None else len(self._positions)
            ),
        }
        self._curve.append(point)
        return deepcopy(point)

    add_point = append_point

    def update_from_history(
        self, records: Iterable[TradeRecord] | None = None
    ) -> list[dict[str, Any]]:
        """Rebuild the curve chronologically from persisted real trade records."""
        chronological = list(records) if records is not None else self._history.all()
        self._cash = self._initial_capital
        self._positions = {}
        self._last_prices = {}
        self._curve = []
        for record in chronological:
            if (
                record.action in {"buy", "sell"}
                and record.price is not None
                and record.quantity > 0
            ):
                self.update(
                    record.action,
                    record.symbol,
                    record.price,
                    record.quantity,
                    record.timestamp,
                )
        return self.get_curve()

    def get_curve(self) -> list[dict[str, Any]]:
        """Return a defensive copy of all points."""
        return deepcopy(self._curve)

    def to_list(self) -> list[dict[str, Any]]:
        """Return the JSON-serializable representation."""
        return self.get_curve()

    def save(self, path: Path | None = None) -> Path:
        """Persist the curve as a JSON list."""
        target = path or self._path
        if target is None:
            raise ValueError("no equity curve path configured")
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(self._curve[-500:], handle, ensure_ascii=False, indent=2)
        self._path = target
        return target

    def load(self, path: Path | None = None) -> list[dict[str, Any]]:
        """Load and validate a JSON-list curve."""
        target = path or self._path
        if target is None:
            raise ValueError("no equity curve path configured")
        with open(target, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, list) or any(not isinstance(point, dict) for point in data):
            raise ValueError(f"invalid equity curve structure: {target}")
        required = {"date", "timestamp", "equity", "pnl", "position_count"}
        for index, point in enumerate(data):
            missing = required.difference(point)
            if missing:
                raise ValueError(
                    f"equity curve point {index} missing fields: {sorted(missing)}"
                )
        self._curve = data[-500:]
        return self.get_curve()

    def max_drawdown(self) -> float:
        """Return the maximum peak-to-trough drawdown percentage."""
        peak: float | None = None
        maximum = 0.0
        for point in self._curve:
            equity = float(point["equity"])
            peak = equity if peak is None else max(peak, equity)
            if peak > 0:
                maximum = max(maximum, (peak - equity) / peak * 100)
        return round(maximum, 4)

    def total_return_pct(self) -> float:
        """Return total percentage change from initial capital."""
        if not self._curve:
            return 0.0
        last = Decimal(str(self._curve[-1]["equity"]))
        return round(
            float((last - self._initial_capital) / self._initial_capital * 100),
            4,
        )

    def stats(self) -> dict[str, float | int]:
        """Return the minimal statistics required by evaluators and diagnostics."""
        return {
            "points": len(self._curve),
            "total_return_pct": self.total_return_pct(),
            "max_drawdown": self.max_drawdown(),
        }

    def _current_equity(self) -> Decimal:
        market_value = sum(
            (
                position["shares"] * self._last_prices.get(symbol, Decimal("0"))
                for symbol, position in self._positions.items()
            ),
            Decimal("0"),
        )
        return self._cash + market_value
