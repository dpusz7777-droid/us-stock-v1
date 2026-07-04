#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Portfolio state bridge with caller-supplied market valuation.

This module never requests prices.  The backend supplies the one price snapshot
already fetched for the current iteration.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from portfolio_service import PositionState as _PositionState
from portfolio_service import get_portfolio_snapshot
from position_engine import PositionEngine as _PositionEngine


_DEFAULT_PORTFOLIO = (
    Path(__file__).resolve().parent.parent.parent / "portfolio_migrated_candidate.json"
)


@dataclass(frozen=True)
class Position:
    """Normalized real-account position and its optional market valuation."""

    symbol: str
    shares: Decimal
    cost_basis: Decimal
    avg_cost: Decimal
    currency: str | None
    current_price: Decimal | None
    price_as_of: str | None
    price_source: str | None
    market_value: Decimal | None
    unrealized_pnl: Decimal | None
    unrealized_pnl_pct: Decimal | None
    allocation: float | None = None


@dataclass(frozen=True)
class PortfolioSummary:
    """Real-account totals under complete, partial, or unavailable valuation."""

    total_equity: Decimal | None
    total_cost: Decimal
    total_market_value: Decimal | None
    total_pnl: Decimal | None
    cash: Decimal | None
    positions: tuple[Position, ...]
    position_count: int
    concentration_max: float | None
    valuation_status: str
    valued_position_count: int
    total_position_count: int
    missing_price_symbols: tuple[str, ...]
    price_as_of: str | None


def _field(result: Any, name: str, default: Any = None) -> Any:
    if isinstance(result, Mapping):
        return result.get(name, default)
    return getattr(result, name, default)


def _valid_price(result: Any) -> Decimal | None:
    value = _field(result, "price")
    if value is None:
        return None
    try:
        price = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return price if price.is_finite() and price > 0 else None


class PortfolioState:
    """Read real holdings and value them from an externally supplied snapshot."""

    def __init__(self) -> None:
        self._engine = _PositionEngine()

    @staticmethod
    def _build(raw: _PositionState, price_result: Any = None) -> Position:
        latest_price = _valid_price(price_result)
        market_value = (
            raw.shares * latest_price if latest_price is not None else None
        )
        unrealized_pnl = (
            market_value - raw.cost_basis if market_value is not None else None
        )
        unrealized_pnl_pct = (
            unrealized_pnl / raw.cost_basis * Decimal("100")
            if unrealized_pnl is not None and raw.cost_basis != 0
            else None
        )
        return Position(
            symbol=raw.symbol,
            shares=raw.shares,
            cost_basis=raw.cost_basis,
            avg_cost=raw.avg_cost,
            currency=(
                str(_field(price_result, "currency"))
                if _field(price_result, "currency") is not None
                else None
            ),
            current_price=latest_price,
            price_as_of=(
                str(_field(price_result, "price_as_of"))
                if _field(price_result, "price_as_of") is not None
                else None
            ),
            price_source=(
                str(_field(price_result, "source"))
                if _field(price_result, "source") is not None
                else None
            ),
            market_value=market_value,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
        )

    def summary(
        self,
        price_results: Mapping[str, Any] | None = None,
    ) -> PortfolioSummary:
        """Return holdings valued with the provided iteration price snapshot."""
        snapshot = get_portfolio_snapshot(_DEFAULT_PORTFOLIO)
        price_results = price_results or {}

        positions = [
            self._build(snapshot.positions[symbol], price_results.get(symbol))
            for symbol in sorted(snapshot.positions)
        ]
        total_count = len(positions)
        valued = [position for position in positions if position.market_value is not None]
        missing = tuple(
            position.symbol for position in positions if position.market_value is None
        )
        valued_count = len(valued)

        if total_count == 0:
            valuation_status = "complete"
            total_market_value: Decimal | None = Decimal("0")
            total_pnl: Decimal | None = Decimal("0")
        elif valued_count == total_count:
            valuation_status = "complete"
            total_market_value = sum(
                (position.market_value for position in valued),
                Decimal("0"),
            )
            total_pnl = sum(
                (position.unrealized_pnl for position in valued),
                Decimal("0"),
            )
        elif valued_count > 0:
            valuation_status = "partial"
            total_market_value = sum(
                (position.market_value for position in valued),
                Decimal("0"),
            )
            total_pnl = sum(
                (position.unrealized_pnl for position in valued),
                Decimal("0"),
            )
        else:
            valuation_status = "unavailable"
            total_market_value = None
            total_pnl = None

        total_equity = (
            snapshot.cash + total_market_value
            if snapshot.cash is not None and total_market_value is not None
            else None
        )

        if total_equity is not None and total_equity > 0:
            positions = [
                replace(
                    position,
                    allocation=(
                        round(
                            float(position.market_value / total_equity * Decimal("100")),
                            1,
                        )
                        if position.market_value is not None
                        else None
                    ),
                )
                for position in positions
            ]

        allocations = [
            position.allocation
            for position in positions
            if position.allocation is not None
        ]
        price_times = [
            position.price_as_of for position in valued if position.price_as_of
        ]

        return PortfolioSummary(
            total_equity=total_equity,
            total_cost=snapshot.total_cost_basis,
            total_market_value=total_market_value,
            total_pnl=total_pnl,
            cash=snapshot.cash,
            positions=tuple(positions),
            position_count=total_count,
            concentration_max=max(allocations) if allocations else None,
            valuation_status=valuation_status,
            valued_position_count=valued_count,
            total_position_count=total_count,
            missing_price_symbols=missing,
            price_as_of=max(price_times) if price_times else None,
        )

    def get_position(
        self,
        symbol: str,
        price_results: Mapping[str, Any] | None = None,
    ) -> Position | None:
        """Return one position, optionally valued from the supplied snapshot."""
        for position in self.summary(price_results).positions:
            if position.symbol == symbol.upper():
                return position
        return None
