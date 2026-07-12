#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deprecated compatibility facade over the canonical portfolio snapshot service."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from northstar.data.market_snapshot import MarketSnapshot, build_market_snapshot
from northstar.data.portfolio_snapshot import (
    PortfolioSnapshot,
    load_portfolio_state,
    value_portfolio,
)


@dataclass(frozen=True)
class Position:
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
    portfolio_snapshot_id: str | None = None
    market_snapshot_id: str | None = None


def _field(result: Any, name: str, default: Any = None) -> Any:
    if isinstance(result, Mapping):
        return result.get(name, default)
    return getattr(result, name, default)


class _ExistingResultsProvider:
    """No-I/O adapter for old callers that already fetched their iteration results."""

    def __init__(self, results: Mapping[str, Any]) -> None:
        self.results = results

    def get_price(self, symbol: str) -> dict[str, Any]:
        result = self.results.get(symbol)
        status = str(_field(result, "status", "")).upper()
        is_ok = bool(_field(result, "is_ok", status in {"OK", "VALID"}))
        return {
            "symbol": symbol,
            "price": _field(result, "price") if is_ok else None,
            "currency": _field(result, "currency", "USD"),
            "source": _field(result, "source", "unavailable"),
            "as_of": _field(result, "price_as_of", _field(result, "as_of")),
            "status": "valid" if is_ok else "error",
            "is_stale": status == "STALE",
            "is_mock": bool(_field(result, "is_mock", False)),
            "error_code": _field(result, "error_code"),
            "error_message": _field(result, "error_message"),
        }


class PortfolioState:
    """Compatibility class; all loading and calculations delegate to P1-04."""

    def summary(
        self,
        price_results: Mapping[str, Any] | None = None,
        *,
        market_snapshot: MarketSnapshot | None = None,
        portfolio_snapshot: PortfolioSnapshot | None = None,
    ) -> PortfolioSummary:
        state = load_portfolio_state()
        if portfolio_snapshot is None and market_snapshot is None and price_results is not None:
            market_snapshot = build_market_snapshot(
                state.position_symbols,
                _ExistingResultsProvider(price_results),
            )
        if portfolio_snapshot is None and market_snapshot is not None:
            portfolio_snapshot = value_portfolio(state, market_snapshot)

        valuations = {
            position.symbol: position
            for position in (portfolio_snapshot.positions if portfolio_snapshot is not None else ())
        }
        positions: list[Position] = []
        for raw in state.positions:
            valued = valuations.get(raw.symbol)
            positions.append(Position(
                symbol=raw.symbol,
                shares=raw.quantity,
                cost_basis=raw.cost_basis,
                avg_cost=raw.average_cost,
                currency=raw.currency,
                current_price=valued.current_price if valued is not None else None,
                price_as_of=valued.price_as_of if valued is not None else None,
                price_source=valued.price_source if valued is not None else None,
                market_value=valued.market_value if valued is not None else None,
                unrealized_pnl=valued.unrealized_pnl if valued is not None else None,
                unrealized_pnl_pct=valued.unrealized_pnl_percent if valued is not None else None,
            ))

        valued_positions = [position for position in positions if position.market_value is not None]
        missing = tuple(position.symbol for position in positions if position.market_value is None)
        price_times = [position.price_as_of for position in valued_positions if position.price_as_of]
        if portfolio_snapshot is None:
            status = "incomplete" if positions else "no_positions"
            total_market_value = total_pnl = total_equity = None
            portfolio_snapshot_id = market_snapshot_id = None
        else:
            status = portfolio_snapshot.valuation_status
            total_market_value = portfolio_snapshot.total_market_value
            total_pnl = portfolio_snapshot.total_unrealized_pnl
            total_equity = portfolio_snapshot.total_asset_value
            portfolio_snapshot_id = portfolio_snapshot.portfolio_snapshot_id
            market_snapshot_id = portfolio_snapshot.market_snapshot_id

        return PortfolioSummary(
            total_equity=total_equity,
            total_cost=sum((position.cost_basis for position in positions), Decimal("0")),
            total_market_value=total_market_value,
            total_pnl=total_pnl,
            cash=state.cash,
            positions=tuple(positions),
            position_count=len(positions),
            concentration_max=None,
            valuation_status=status,
            valued_position_count=len(valued_positions),
            total_position_count=len(positions),
            missing_price_symbols=missing,
            price_as_of=max(price_times) if price_times else None,
            portfolio_snapshot_id=portfolio_snapshot_id,
            market_snapshot_id=market_snapshot_id,
        )

    def get_position(
        self,
        symbol: str,
        price_results: Mapping[str, Any] | None = None,
    ) -> Position | None:
        for position in self.summary(price_results).positions:
            if position.symbol == symbol.upper():
                return position
        return None
