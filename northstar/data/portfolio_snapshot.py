#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Canonical, read-only portfolio repository and Decimal valuation service."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

import portfolio_service

from northstar.data.market_snapshot import MarketSnapshot, normalize_symbol, parse_timestamp


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FORMAL_PORTFOLIO_PATH = PROJECT_ROOT / "portfolio_migrated_candidate.json"
LEGACY_PORTFOLIO_PATH = PROJECT_ROOT / "portfolio.json"
ZERO = Decimal("0")
PORTFOLIO_VALUATION_STATUSES = frozenset({"complete", "incomplete", "error", "no_positions"})


class PortfolioSnapshotError(Exception):
    """Base error for canonical portfolio loading and valuation."""


class PortfolioSourceConflictError(PortfolioSnapshotError):
    """Raised when two real-data sources disagree and require user choice."""


def _decimal(value: Any, field_name: str, *, allow_none: bool = False) -> Decimal | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or value is None:
        raise portfolio_service.PortfolioValidationError(f"{field_name} 必须是有效数字。")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise portfolio_service.PortfolioValidationError(f"{field_name} 必须是有效数字。") from exc
    if not number.is_finite():
        raise portfolio_service.PortfolioValidationError(f"{field_name} 不能是 NaN 或无穷大。")
    return number


def _aware_iso(value: Any, field_name: str) -> str:
    parsed = parse_timestamp(value)
    if parsed is None:
        raise portfolio_service.PortfolioValidationError(f"{field_name} 必须是带时区 ISO 8601。")
    return parsed.isoformat().replace("+00:00", "Z")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now(clock: Any) -> str:
    value = clock()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _decimal_text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


@dataclass(frozen=True, slots=True)
class Position:
    symbol: str
    quantity: Decimal
    average_cost: Decimal
    currency: str
    source: str
    opened_at: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", normalize_symbol(self.symbol))
        quantity = _decimal(self.quantity, f"positions.{self.symbol}.quantity")
        average_cost = _decimal(self.average_cost, f"positions.{self.symbol}.average_cost")
        if quantity <= ZERO:
            raise portfolio_service.PortfolioValidationError("非零持仓 quantity 必须大于 0。")
        if average_cost < ZERO:
            raise portfolio_service.PortfolioValidationError("average_cost 不能小于 0。")
        currency = str(self.currency or "").strip().upper()
        if not currency:
            raise portfolio_service.PortfolioValidationError("position currency 不能为空。")
        if not str(self.source or "").strip():
            raise portfolio_service.PortfolioValidationError("position source 不能为空。")
        if self.opened_at is not None:
            object.__setattr__(self, "opened_at", _aware_iso(self.opened_at, "opened_at"))
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "average_cost", average_cost)
        object.__setattr__(self, "currency", currency)

    @property
    def cost_basis(self) -> Decimal:
        return self.quantity * self.average_cost

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "quantity": _decimal_text(self.quantity),
            "average_cost": _decimal_text(self.average_cost),
            "currency": self.currency,
            "source": self.source,
            "opened_at": self.opened_at,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Position":
        return cls(
            symbol=str(value.get("symbol") or ""),
            quantity=_decimal(value.get("quantity"), "quantity"),
            average_cost=_decimal(value.get("average_cost"), "average_cost"),
            currency=str(value.get("currency") or ""),
            source=str(value.get("source") or ""),
            opened_at=value.get("opened_at"),
            notes=value.get("notes"),
        )


@dataclass(frozen=True, slots=True)
class PortfolioState:
    schema_version: str
    account_id: str
    account_type: str
    base_currency: str
    cash: Decimal | None
    positions: tuple[Position, ...]
    source: str
    updated_at: str
    valuation_status: str = "unvalued"
    valuation_snapshot_id: str | None = None
    missing_symbols: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    buying_power: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.schema_version or not self.account_id or not self.account_type:
            raise portfolio_service.PortfolioValidationError("portfolio identity fields are required")
        base_currency = str(self.base_currency or "").strip().upper()
        if not base_currency:
            raise portfolio_service.PortfolioValidationError("base_currency 不能为空。")
        cash = _decimal(self.cash, "cash", allow_none=True)
        buying_power = _decimal(self.buying_power, "buying_power", allow_none=True)
        if cash is not None and cash < ZERO:
            raise portfolio_service.PortfolioValidationError("cash 不能小于 0。")
        if buying_power is not None and buying_power < ZERO:
            raise portfolio_service.PortfolioValidationError("buying_power 不能小于 0。")
        symbols = [position.symbol for position in self.positions]
        if len(symbols) != len(set(symbols)):
            raise portfolio_service.PortfolioValidationError("positions 存在重复股票代码。")
        if self.valuation_status not in {"unvalued", "error"}:
            raise portfolio_service.PortfolioValidationError("PortfolioState valuation_status 无效。")
        object.__setattr__(self, "base_currency", base_currency)
        object.__setattr__(self, "cash", cash)
        object.__setattr__(self, "buying_power", buying_power)
        object.__setattr__(self, "positions", tuple(self.positions))
        object.__setattr__(self, "updated_at", _aware_iso(self.updated_at, "updated_at"))
        object.__setattr__(self, "missing_symbols", tuple(normalize_symbol(s) for s in self.missing_symbols))
        object.__setattr__(self, "warnings", tuple(self.warnings))

    @property
    def position_symbols(self) -> tuple[str, ...]:
        return tuple(position.symbol for position in self.positions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "account_id": self.account_id,
            "account_type": self.account_type,
            "base_currency": self.base_currency,
            "cash": _decimal_text(self.cash),
            "positions": [position.to_dict() for position in self.positions],
            "source": self.source,
            "updated_at": self.updated_at,
            "valuation_status": self.valuation_status,
            "valuation_snapshot_id": self.valuation_snapshot_id,
            "missing_symbols": list(self.missing_symbols),
            "warnings": list(self.warnings),
            "buying_power": _decimal_text(self.buying_power),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PortfolioState":
        return cls(
            schema_version=str(value.get("schema_version") or ""),
            account_id=str(value.get("account_id") or ""),
            account_type=str(value.get("account_type") or ""),
            base_currency=str(value.get("base_currency") or ""),
            cash=_decimal(value.get("cash"), "cash", allow_none=True),
            positions=tuple(Position.from_dict(row) for row in value.get("positions") or ()),
            source=str(value.get("source") or ""),
            updated_at=str(value.get("updated_at") or ""),
            valuation_status=str(value.get("valuation_status") or "unvalued"),
            valuation_snapshot_id=value.get("valuation_snapshot_id"),
            missing_symbols=tuple(value.get("missing_symbols") or ()),
            warnings=tuple(value.get("warnings") or ()),
            buying_power=_decimal(value.get("buying_power"), "buying_power", allow_none=True),
        )


@dataclass(frozen=True, slots=True)
class PositionValuation:
    symbol: str
    quantity: Decimal
    average_cost: Decimal
    current_price: Decimal | None
    price_source: str | None
    price_as_of: str | None
    market_value: Decimal | None
    cost_basis: Decimal
    unrealized_pnl: Decimal | None
    unrealized_pnl_percent: Decimal | None
    valuation_status: str
    error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", normalize_symbol(self.symbol))
        quantity = _decimal(self.quantity, f"{self.symbol}.quantity")
        average_cost = _decimal(self.average_cost, f"{self.symbol}.average_cost")
        cost_basis = _decimal(self.cost_basis, f"{self.symbol}.cost_basis")
        if quantity <= ZERO or average_cost < ZERO or cost_basis < ZERO:
            raise portfolio_service.PortfolioValidationError("PositionValuation 数量/成本无效。")
        if self.valuation_status not in {"complete", "missing_price", "currency_mismatch", "error"}:
            raise portfolio_service.PortfolioValidationError("PositionValuation status 无效。")
        if self.valuation_status == "complete":
            if (
                self.current_price is None
                or self.current_price <= ZERO
                or not self.price_source
                or parse_timestamp(self.price_as_of) is None
                or self.market_value is None
                or self.unrealized_pnl is None
            ):
                raise portfolio_service.PortfolioValidationError("complete 持仓估值字段不完整。")
        elif any(value is not None for value in (self.current_price, self.market_value, self.unrealized_pnl)):
            raise portfolio_service.PortfolioValidationError("无效持仓不得携带当前价或伪精确估值。")
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "average_cost", average_cost)
        object.__setattr__(self, "cost_basis", cost_basis)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "quantity": _decimal_text(self.quantity),
            "average_cost": _decimal_text(self.average_cost),
            "current_price": _decimal_text(self.current_price),
            "price_source": self.price_source,
            "price_as_of": self.price_as_of,
            "market_value": _decimal_text(self.market_value),
            "cost_basis": _decimal_text(self.cost_basis),
            "unrealized_pnl": _decimal_text(self.unrealized_pnl),
            "unrealized_pnl_percent": _decimal_text(self.unrealized_pnl_percent),
            "valuation_status": self.valuation_status,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PositionValuation":
        return cls(
            symbol=normalize_symbol(value.get("symbol")),
            quantity=_decimal(value.get("quantity"), "quantity"),
            average_cost=_decimal(value.get("average_cost"), "average_cost"),
            current_price=_decimal(value.get("current_price"), "current_price", allow_none=True),
            price_source=value.get("price_source"),
            price_as_of=value.get("price_as_of"),
            market_value=_decimal(value.get("market_value"), "market_value", allow_none=True),
            cost_basis=_decimal(value.get("cost_basis"), "cost_basis"),
            unrealized_pnl=_decimal(value.get("unrealized_pnl"), "unrealized_pnl", allow_none=True),
            unrealized_pnl_percent=_decimal(value.get("unrealized_pnl_percent"), "unrealized_pnl_percent", allow_none=True),
            valuation_status=str(value.get("valuation_status") or ""),
            error=value.get("error"),
        )


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    portfolio_snapshot_id: str
    market_snapshot_id: str
    generated_at: str
    base_currency: str
    cash: Decimal | None
    cash_currency: str
    positions: tuple[PositionValuation, ...]
    total_market_value: Decimal | None
    total_cost_basis: Decimal | None
    total_unrealized_pnl: Decimal | None
    total_asset_value: Decimal | None
    partial_market_value: Decimal | None
    partial_unrealized_pnl: Decimal | None
    valuation_status: str
    missing_symbols: tuple[str, ...]
    coverage_ratio: float
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.portfolio_snapshot_id or not self.market_snapshot_id:
            raise portfolio_service.PortfolioValidationError("portfolio/market snapshot id 不能为空。")
        if self.valuation_status not in PORTFOLIO_VALUATION_STATUSES:
            raise portfolio_service.PortfolioValidationError("valuation_status 无效。")
        if self.valuation_status == "complete":
            if (
                self.cash is None
                or self.missing_symbols
                or any(position.valuation_status != "complete" for position in self.positions)
                or any(value is None for value in (
                    self.total_market_value,
                    self.total_cost_basis,
                    self.total_unrealized_pnl,
                    self.total_asset_value,
                ))
            ):
                raise portfolio_service.PortfolioValidationError("complete PortfolioSnapshot 字段不完整。")
        elif self.valuation_status in {"incomplete", "error"} and any(
            value is not None
            for value in (self.total_market_value, self.total_unrealized_pnl, self.total_asset_value)
        ):
            raise portfolio_service.PortfolioValidationError("非完整估值不得携带伪完整总值。")
        elif self.valuation_status == "no_positions" and self.positions:
            raise portfolio_service.PortfolioValidationError("no_positions 状态不得包含持仓。")
        object.__setattr__(self, "generated_at", _aware_iso(self.generated_at, "generated_at"))
        object.__setattr__(self, "positions", tuple(self.positions))
        object.__setattr__(self, "missing_symbols", tuple(self.missing_symbols))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(self, "coverage_ratio", round(float(self.coverage_ratio), 6))

    def to_dict(self) -> dict[str, Any]:
        return {
            "portfolio_snapshot_id": self.portfolio_snapshot_id,
            "market_snapshot_id": self.market_snapshot_id,
            "generated_at": self.generated_at,
            "base_currency": self.base_currency,
            "cash": _decimal_text(self.cash),
            "cash_currency": self.cash_currency,
            "positions": [position.to_dict() for position in self.positions],
            "total_market_value": _decimal_text(self.total_market_value),
            "total_cost_basis": _decimal_text(self.total_cost_basis),
            "total_unrealized_pnl": _decimal_text(self.total_unrealized_pnl),
            "total_asset_value": _decimal_text(self.total_asset_value),
            "partial_market_value": _decimal_text(self.partial_market_value),
            "partial_unrealized_pnl": _decimal_text(self.partial_unrealized_pnl),
            "valuation_status": self.valuation_status,
            "missing_symbols": list(self.missing_symbols),
            "coverage_ratio": self.coverage_ratio,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PortfolioSnapshot":
        decimal_fields = {
            name: _decimal(value.get(name), name, allow_none=True)
            for name in (
                "cash", "total_market_value", "total_cost_basis",
                "total_unrealized_pnl", "total_asset_value",
                "partial_market_value", "partial_unrealized_pnl",
            )
        }
        return cls(
            portfolio_snapshot_id=str(value.get("portfolio_snapshot_id") or ""),
            market_snapshot_id=str(value.get("market_snapshot_id") or ""),
            generated_at=str(value.get("generated_at") or ""),
            base_currency=str(value.get("base_currency") or ""),
            cash=decimal_fields["cash"],
            cash_currency=str(value.get("cash_currency") or ""),
            positions=tuple(PositionValuation.from_dict(row) for row in value.get("positions") or ()),
            total_market_value=decimal_fields["total_market_value"],
            total_cost_basis=decimal_fields["total_cost_basis"],
            total_unrealized_pnl=decimal_fields["total_unrealized_pnl"],
            total_asset_value=decimal_fields["total_asset_value"],
            partial_market_value=decimal_fields["partial_market_value"],
            partial_unrealized_pnl=decimal_fields["partial_unrealized_pnl"],
            valuation_status=str(value.get("valuation_status") or ""),
            missing_symbols=tuple(value.get("missing_symbols") or ()),
            coverage_ratio=float(value.get("coverage_ratio") or 0.0),
            warnings=tuple(value.get("warnings") or ()),
        )


class PortfolioRepository:
    """The only formal read entry for the local real portfolio."""

    def __init__(self, path: str | Path = FORMAL_PORTFOLIO_PATH) -> None:
        self.path = Path(path)

    def load(self) -> PortfolioState:
        document, service_state = _load_service_state(self.path)
        account = document["account"]
        base_currency = str(account.get("base_currency") or "").strip().upper()
        if not base_currency:
            raise portfolio_service.PortfolioValidationError("account.base_currency 不能为空。")
        if service_state.cash is None:
            raise portfolio_service.PortfolioValidationError("正式账户现金未知，禁止生成资产估值。")

        transaction_meta: dict[str, dict[str, list[str]]] = {}
        for transaction in document["transactions"]:
            symbol = normalize_symbol(transaction["symbol"])
            meta = transaction_meta.setdefault(symbol, {"sources": [], "times": [], "notes": []})
            source = str(transaction.get("source") or "").strip()
            event_time = transaction.get("effective_at") or transaction.get("executed_at")
            note = str(transaction.get("note") or "").strip()
            if source and source not in meta["sources"]:
                meta["sources"].append(source)
            if event_time:
                meta["times"].append(_aware_iso(event_time, f"{symbol}.opened_at"))
            if note and note not in meta["notes"]:
                meta["notes"].append(note)

        positions: list[Position] = []
        for symbol in sorted(service_state.positions):
            raw = service_state.positions[symbol]
            meta = transaction_meta.get(symbol, {"sources": [], "times": [], "notes": []})
            positions.append(Position(
                symbol=symbol,
                quantity=raw.shares,
                average_cost=raw.avg_cost,
                currency=base_currency,
                source=",".join(meta["sources"]) or "portfolio_transactions",
                opened_at=min(meta["times"]) if meta["times"] else None,
                notes=" | ".join(meta["notes"]) or None,
            ))

        updated_at = account.get("updated_at") or account.get("created_at")
        return PortfolioState(
            schema_version=str(document["schema_version"]),
            account_id=str(account.get("account_id") or "local_portfolio"),
            account_type="brokerage",
            base_currency=base_currency,
            cash=service_state.cash,
            positions=tuple(positions),
            source=self.path.name,
            updated_at=_aware_iso(updated_at, "account.updated_at"),
            warnings=tuple(service_state.warnings),
            buying_power=service_state.buying_power,
        )


def _load_service_state(path: str | Path) -> tuple[dict[str, Any], portfolio_service.PortfolioState]:
    """Single internal file-read boundary shared by canonical and compatibility DTOs."""
    document = portfolio_service.load_portfolio(path)
    portfolio_service.validate_portfolio(document)
    return document, portfolio_service.build_portfolio_state(document)


def load_legacy_service_state(
    path: str | Path = FORMAL_PORTFOLIO_PATH,
) -> portfolio_service.PortfolioState:
    """Deprecated DTO adapter; loading still passes through the canonical boundary."""
    return _load_service_state(path)[1]


def load_portfolio_state(path: str | Path = FORMAL_PORTFOLIO_PATH) -> PortfolioState:
    """Canonical one-shot read; never supplies default cash or positions."""
    return PortfolioRepository(path).load()


def requested_market_symbols(
    watchlist_symbols: list[str] | tuple[str, ...],
    portfolio_state: PortfolioState,
) -> tuple[str, ...]:
    """Return normalized watchlist ∪ non-zero portfolio symbols, in stable order."""
    return tuple(dict.fromkeys(
        [normalize_symbol(symbol) for symbol in watchlist_symbols]
        + list(portfolio_state.position_symbols)
    ))


def value_portfolio(
    state: PortfolioState,
    market_snapshot: MarketSnapshot,
    *,
    clock: Any = _now_utc,
) -> PortfolioSnapshot:
    """The sole formal valuation formula; this function performs no I/O."""
    valuations: list[PositionValuation] = []
    missing: list[str] = []
    warnings = list(state.warnings)

    for position in state.positions:
        quote = market_snapshot.quotes.get(position.symbol)
        cost_basis = position.cost_basis
        error: str | None = None
        if quote is None:
            error = "symbol not present in MarketSnapshot"
        elif not quote.decision_eligible:
            error = f"quote status={quote.status}; stale={quote.is_stale}; mock={quote.is_mock}"
        elif quote.currency.upper() != position.currency or position.currency != state.base_currency:
            error = (
                f"currency mismatch: position={position.currency}, quote={quote.currency}, "
                f"base={state.base_currency}; no trusted FX rate"
            )

        if error is not None:
            currency_mismatch = quote is not None and (
                quote.currency.upper() != position.currency
                or position.currency != state.base_currency
            )
            missing.append(position.symbol)
            valuations.append(PositionValuation(
                symbol=position.symbol,
                quantity=position.quantity,
                average_cost=position.average_cost,
                current_price=None,
                price_source=quote.source if quote is not None else None,
                price_as_of=quote.as_of if quote is not None else None,
                market_value=None,
                cost_basis=cost_basis,
                unrealized_pnl=None,
                unrealized_pnl_percent=None,
                valuation_status="currency_mismatch" if currency_mismatch else "missing_price",
                error=error,
            ))
            continue

        current_price = _decimal(quote.price, f"quotes.{position.symbol}.price")
        market_value = position.quantity * current_price
        unrealized_pnl = market_value - cost_basis
        pnl_percent = unrealized_pnl / cost_basis * Decimal("100") if cost_basis > ZERO else None
        valuations.append(PositionValuation(
            symbol=position.symbol,
            quantity=position.quantity,
            average_cost=position.average_cost,
            current_price=current_price,
            price_source=quote.source,
            price_as_of=quote.as_of,
            market_value=market_value,
            cost_basis=cost_basis,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_percent=pnl_percent,
            valuation_status="complete",
        ))

    valid = [item for item in valuations if item.valuation_status == "complete"]
    total_positions = len(valuations)
    coverage = len(valid) / total_positions if total_positions else 1.0
    total_cost_basis = sum((item.cost_basis for item in valuations), ZERO)
    partial_market_value = sum((item.market_value for item in valid), ZERO) if valid else ZERO
    partial_unrealized = sum((item.unrealized_pnl for item in valid), ZERO) if valid else ZERO

    if state.valuation_status == "error" or state.cash is None:
        status = "error"
        total_market_value = total_unrealized = total_asset_value = None
        warnings.append("现金或原始持仓状态无效，禁止生成总资产。")
    elif total_positions == 0:
        status = "no_positions"
        total_market_value = ZERO
        total_unrealized = ZERO
        total_asset_value = state.cash
    elif missing:
        status = "incomplete"
        total_market_value = total_unrealized = total_asset_value = None
        warnings.append("部分持仓缺少可信行情或币种不可直接换算；总值字段已关闭。")
    else:
        status = "complete"
        total_market_value = partial_market_value
        total_unrealized = partial_unrealized
        total_asset_value = state.cash + total_market_value

    generated_at = _iso_now(clock)
    return PortfolioSnapshot(
        portfolio_snapshot_id=f"pf_{generated_at.replace(':', '').replace('-', '')}_{uuid4().hex[:12]}",
        market_snapshot_id=market_snapshot.snapshot_id,
        generated_at=generated_at,
        base_currency=state.base_currency,
        cash=state.cash,
        cash_currency=state.base_currency,
        positions=tuple(valuations),
        total_market_value=total_market_value,
        total_cost_basis=total_cost_basis,
        total_unrealized_pnl=total_unrealized,
        total_asset_value=total_asset_value,
        partial_market_value=partial_market_value,
        partial_unrealized_pnl=partial_unrealized,
        valuation_status=status,
        missing_symbols=tuple(missing),
        coverage_ratio=coverage,
        warnings=tuple(warnings),
    )


def portfolio_state_from_mapping(
    positions: Mapping[str, Mapping[str, Any]],
    *,
    cash: Any | None,
    base_currency: str = "USD",
    updated_at: str = "2026-07-10T00:00:00Z",
) -> PortfolioState:
    """Deprecated no-I/O adapter for tests/legacy callers; never invents cash."""
    normalized: list[Position] = []
    for symbol, row in positions.items():
        quantity = _decimal(row.get("quantity", row.get("shares")), f"{symbol}.quantity")
        if quantity == ZERO:
            continue
        normalized.append(Position(
            symbol=symbol,
            quantity=quantity,
            average_cost=_decimal(row.get("average_cost", row.get("avg_cost")), f"{symbol}.average_cost"),
            currency=str(row.get("currency") or base_currency),
            source="deprecated_mapping_adapter",
        ))
    cash_value = _decimal(cash, "cash", allow_none=True)
    return PortfolioState(
        schema_version="compat-1",
        account_id="local_compat",
        account_type="compatibility",
        base_currency=base_currency,
        cash=cash_value,
        positions=tuple(normalized),
        source="deprecated_mapping_adapter",
        updated_at=updated_at,
        valuation_status="error" if cash_value is None else "unvalued",
        warnings=("兼容输入缺少可信现金。",) if cash_value is None else (),
    )


def migrate_legacy_document(
    document: Mapping[str, Any],
    *,
    account_id: str,
    base_currency: str,
    migration_time: str,
) -> dict[str, Any]:
    """Pure, idempotent legacy-schema migration; never reads or writes files."""
    if document.get("schema_version") == portfolio_service.SUPPORTED_SCHEMA_VERSION:
        migrated = copy.deepcopy(dict(document))
        portfolio_service.validate_portfolio(migrated)
        return migrated
    positions = document.get("positions")
    transactions = document.get("transactions")
    if not isinstance(positions, list) or not isinstance(transactions, list):
        raise portfolio_service.PortfolioValidationError("legacy positions/transactions schema 无效。")
    if transactions:
        raise PortfolioSourceConflictError("旧交易记录非空，禁止自动推断或合并。")
    cash = _decimal(document.get("cash"), "legacy.cash")
    if cash < ZERO:
        raise portfolio_service.PortfolioValidationError("legacy.cash 不能小于 0。")
    timestamp = _aware_iso(migration_time, "migration_time")
    currency = str(base_currency or "").strip().upper()
    if not currency:
        raise portfolio_service.PortfolioValidationError("base_currency 不能为空。")

    seen: set[str] = set()
    opening_transactions: list[dict[str, Any]] = []
    for index, row in enumerate(positions, start=1):
        if not isinstance(row, Mapping):
            raise portfolio_service.PortfolioValidationError(f"legacy.positions[{index - 1}] 必须是对象。")
        symbol = normalize_symbol(row.get("ticker", row.get("symbol")))
        if symbol in seen:
            raise PortfolioSourceConflictError(f"legacy positions 重复股票代码：{symbol}")
        seen.add(symbol)
        quantity = _decimal(row.get("shares", row.get("quantity")), f"legacy.{symbol}.quantity")
        average_cost = _decimal(row.get("avg_cost", row.get("average_cost")), f"legacy.{symbol}.average_cost")
        if quantity < ZERO or average_cost < ZERO:
            raise portfolio_service.PortfolioValidationError("legacy quantity/average_cost 不能小于 0。")
        if quantity == ZERO:
            continue
        if average_cost == ZERO:
            raise portfolio_service.PortfolioValidationError("非零 legacy 持仓平均成本必须大于 0。")
        opened_at = row.get("added") or timestamp
        opened_at = _aware_iso(opened_at, f"legacy.{symbol}.opened_at")
        opening_transactions.append({
            "transaction_id": f"txn_legacy_{index:06d}_{symbol}",
            "external_id": None,
            "transaction_type": "OPENING_POSITION",
            "symbol": symbol,
            "shares": quantity,
            "price": average_cost,
            "amount": None,
            "fees": ZERO,
            "executed_at": None,
            "effective_at": opened_at,
            "recorded_at": timestamp,
            "source": "legacy_migration",
            "note": "旧持仓快照的幂等迁移记录；不代表原始逐笔成交。",
        })
    migrated = {
        "schema_version": portfolio_service.SUPPORTED_SCHEMA_VERSION,
        "account": {
            "account_id": str(account_id),
            "account_name": "local migrated portfolio",
            "broker": "local",
            "base_currency": currency,
            "cash_status": "known",
            "cash": cash,
            "buying_power": None,
            "created_at": timestamp,
            "updated_at": timestamp,
        },
        "settings": {},
        "transactions": opening_transactions,
    }
    portfolio_service.validate_portfolio(migrated)
    return migrated


def compare_portfolio_sources(
    formal_path: str | Path = FORMAL_PORTFOLIO_PATH,
    legacy_path: str | Path = LEGACY_PORTFOLIO_PATH,
) -> dict[str, Any]:
    """Compare quantity/cost/cash without writing or selecting a winner."""
    formal_state = load_portfolio_state(formal_path)
    legacy_file = Path(legacy_path)
    try:
        legacy = json.loads(legacy_file.read_text(encoding="utf-8"), parse_float=Decimal, parse_int=Decimal)
    except (OSError, ValueError, TypeError) as exc:
        raise portfolio_service.PortfolioLoadError(f"无法读取旧持仓来源：{legacy_file}: {exc}") from exc
    legacy_positions: dict[str, tuple[Decimal, Decimal]] = {}
    for index, row in enumerate(legacy.get("positions") or []):
        symbol = normalize_symbol(row.get("ticker", row.get("symbol")))
        if symbol in legacy_positions:
            raise PortfolioSourceConflictError(f"旧持仓来源包含重复标的：{symbol}")
        legacy_positions[symbol] = (
            _decimal(row.get("shares", row.get("quantity")), f"legacy.positions[{index}].quantity"),
            _decimal(row.get("avg_cost", row.get("average_cost")), f"legacy.positions[{index}].average_cost"),
        )
    formal_positions = {position.symbol: (position.quantity, position.average_cost) for position in formal_state.positions}
    differences: list[dict[str, str]] = []
    for symbol in sorted(set(legacy_positions) | set(formal_positions)):
        legacy_value = legacy_positions.get(symbol)
        formal_value = formal_positions.get(symbol)
        if legacy_value is None or formal_value is None:
            differences.append({"symbol": symbol, "field": "presence"})
            continue
        if legacy_value[0] != formal_value[0]:
            differences.append({"symbol": symbol, "field": "quantity"})
        if legacy_value[1] != formal_value[1]:
            differences.append({"symbol": symbol, "field": "average_cost"})
    legacy_cash = _decimal(legacy.get("cash"), "legacy.cash")
    if legacy_cash != formal_state.cash:
        differences.append({"symbol": "CASH", "field": "cash"})
    return {
        "formal_path": str(Path(formal_path)),
        "legacy_path": str(legacy_file),
        "conflict": bool(differences),
        "differences": differences,
        "formal_position_count": len(formal_positions),
        "legacy_position_count": len(legacy_positions),
        "legacy_currency_present": bool(legacy.get("base_currency") or legacy.get("currency")),
    }
