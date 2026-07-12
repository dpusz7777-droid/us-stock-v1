#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Immutable, serializable market-data snapshots for production decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Protocol
from uuid import uuid4


QUOTE_STATUSES = frozenset({"valid", "stale", "missing", "error", "mock"})
MARKET_STATUSES = frozenset({"NORMAL", "DEGRADED", "UNAVAILABLE"})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO-8601 or Unix timestamp into an aware UTC datetime."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if text.isdigit():
            try:
                parsed = datetime.fromtimestamp(float(text), tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                return None
        else:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if not symbol:
        raise ValueError("symbol must not be empty")
    return symbol


@dataclass(frozen=True, slots=True)
class QuoteSnapshot:
    symbol: str
    price: float | None
    currency: str
    source: str
    as_of: str | None
    status: str
    is_stale: bool = False
    is_mock: bool = False
    error_code: str | None = None
    error_message: str | None = None
    previous_close: float | None = None
    change_pct_today: float | None = None
    change_pct_5d: float | None = None
    change_pct_20d: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", normalize_symbol(self.symbol))
        if self.status not in QUOTE_STATUSES:
            raise ValueError(f"unsupported quote status: {self.status}")
        if self.price is not None and self.price <= 0:
            raise ValueError("quote price must be greater than zero or None")
        if self.status == "valid":
            if self.price is None or not self.source or parse_timestamp(self.as_of) is None:
                raise ValueError("valid quote requires price, source, and timezone-aware as_of")
            if self.is_stale or self.is_mock:
                raise ValueError("valid quote cannot be stale or mock")

    @property
    def decision_eligible(self) -> bool:
        return (
            self.status == "valid"
            and self.price is not None
            and self.price > 0
            and bool(self.source)
            and parse_timestamp(self.as_of) is not None
            and not self.is_stale
            and not self.is_mock
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "price": self.price,
            "currency": self.currency,
            "source": self.source,
            "as_of": self.as_of,
            "status": self.status,
            "is_stale": self.is_stale,
            "is_mock": self.is_mock,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "previous_close": self.previous_close,
            "change_pct_today": self.change_pct_today,
            "change_pct_5d": self.change_pct_5d,
            "change_pct_20d": self.change_pct_20d,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "QuoteSnapshot":
        return cls(**{key: value.get(key) for key in cls.__dataclass_fields__})


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    snapshot_id: str
    generated_at_utc: str
    generated_at_local: str
    market_status: str
    requested_symbols: tuple[str, ...]
    valid_symbols: tuple[str, ...]
    invalid_symbols: tuple[str, ...]
    coverage_ratio: float
    provider_summary: Mapping[str, int] = field(default_factory=dict)
    quotes: Mapping[str, QuoteSnapshot] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.snapshot_id:
            raise ValueError("snapshot_id must not be empty")
        if parse_timestamp(self.generated_at_utc) is None:
            raise ValueError("generated_at_utc must be timezone-aware ISO-8601")
        if parse_timestamp(self.generated_at_local) is None:
            raise ValueError("generated_at_local must be timezone-aware ISO-8601")
        if self.market_status not in MARKET_STATUSES:
            raise ValueError(f"unsupported market status: {self.market_status}")
        requested = tuple(normalize_symbol(value) for value in self.requested_symbols)
        valid = tuple(normalize_symbol(value) for value in self.valid_symbols)
        invalid = tuple(normalize_symbol(value) for value in self.invalid_symbols)
        quote_map = {normalize_symbol(key): value for key, value in self.quotes.items()}
        if set(quote_map) != set(requested):
            raise ValueError("quotes must contain every requested symbol exactly once")
        if set(valid) & set(invalid) or set(valid) | set(invalid) != set(requested):
            raise ValueError("valid_symbols and invalid_symbols must partition requested_symbols")
        if any(not quote_map[symbol].decision_eligible for symbol in valid):
            raise ValueError("valid_symbols contains an ineligible quote")
        object.__setattr__(self, "requested_symbols", requested)
        object.__setattr__(self, "valid_symbols", valid)
        object.__setattr__(self, "invalid_symbols", invalid)
        object.__setattr__(self, "coverage_ratio", round(float(self.coverage_ratio), 6))
        object.__setattr__(self, "provider_summary", MappingProxyType(dict(self.provider_summary)))
        object.__setattr__(self, "quotes", MappingProxyType(quote_map))

    def quote(self, symbol: str) -> QuoteSnapshot:
        return self.quotes[normalize_symbol(symbol)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "generated_at_utc": self.generated_at_utc,
            "generated_at_local": self.generated_at_local,
            "market_status": self.market_status,
            "requested_symbols": list(self.requested_symbols),
            "valid_symbols": list(self.valid_symbols),
            "invalid_symbols": list(self.invalid_symbols),
            "coverage_ratio": self.coverage_ratio,
            "provider_summary": dict(sorted(self.provider_summary.items())),
            "quotes": {symbol: self.quotes[symbol].to_dict() for symbol in self.requested_symbols},
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MarketSnapshot":
        raw_quotes = value.get("quotes") or {}
        quotes = {
            normalize_symbol(symbol): QuoteSnapshot.from_dict(quote)
            for symbol, quote in raw_quotes.items()
        }
        return cls(
            snapshot_id=str(value.get("snapshot_id") or ""),
            generated_at_utc=str(value.get("generated_at_utc") or ""),
            generated_at_local=str(value.get("generated_at_local") or ""),
            market_status=str(value.get("market_status") or ""),
            requested_symbols=tuple(value.get("requested_symbols") or ()),
            valid_symbols=tuple(value.get("valid_symbols") or ()),
            invalid_symbols=tuple(value.get("invalid_symbols") or ()),
            coverage_ratio=float(value.get("coverage_ratio") or 0.0),
            provider_summary=dict(value.get("provider_summary") or {}),
            quotes=quotes,
        )


class SnapshotQuoteProvider(Protocol):
    def get_price(self, symbol: str) -> Mapping[str, Any] | QuoteSnapshot:
        ...


def _error_quote(symbol: str, code: str, message: str) -> QuoteSnapshot:
    return QuoteSnapshot(
        symbol=symbol,
        price=None,
        currency="USD",
        source="unavailable",
        as_of=None,
        status="error",
        error_code=code,
        error_message=message,
    )


def _coerce_quote(
    symbol: str,
    raw: Mapping[str, Any] | QuoteSnapshot,
    *,
    now: datetime,
    stale_after: timedelta,
) -> QuoteSnapshot:
    if not isinstance(raw, (QuoteSnapshot, Mapping)) and callable(getattr(raw, "to_dict", None)):
        raw = raw.to_dict()
    if isinstance(raw, QuoteSnapshot):
        quote = raw
        as_of_dt = parse_timestamp(quote.as_of)
        if (
            quote.status == "valid"
            and as_of_dt is not None
            and now - as_of_dt > stale_after
        ):
            values = quote.to_dict()
            values.update(
                status="stale",
                is_stale=True,
                error_code="QUOTE_STALE",
                error_message="quote exceeded snapshot freshness threshold",
            )
            quote = QuoteSnapshot.from_dict(values)
    elif isinstance(raw, Mapping):
        raw_price = raw.get("price")
        try:
            price = float(raw_price) if raw_price is not None else None
        except (TypeError, ValueError):
            price = None
        if price is not None and price <= 0:
            price = None
        source = str(raw.get("source") or "").strip()
        as_of_raw = raw.get("as_of", raw.get("timestamp"))
        as_of_dt = parse_timestamp(as_of_raw)
        is_mock = bool(raw.get("is_mock")) or str(raw.get("status") or "").lower() == "mock"
        is_stale = bool(raw.get("is_stale"))
        if as_of_dt is not None and now - as_of_dt > stale_after:
            is_stale = True
        raw_status = str(raw.get("status") or "").lower()
        if is_mock:
            status = "mock"
        elif price is None:
            status = "error" if raw.get("error") or raw.get("error_message") else "missing"
        elif not source or as_of_dt is None:
            status = "error"
        elif is_stale or raw_status == "stale":
            status = "stale"
        elif raw_status in {"missing", "error", "mock"}:
            status = raw_status
        else:
            status = "valid"
        quote = QuoteSnapshot(
            symbol=symbol,
            price=price,
            currency=str(raw.get("currency") or "USD"),
            source=source or "unavailable",
            as_of=_iso_utc(as_of_dt) if as_of_dt is not None else None,
            status=status,
            is_stale=status == "stale",
            is_mock=status == "mock",
            error_code=raw.get("error_code"),
            error_message=raw.get("error_message", raw.get("error")),
            previous_close=raw.get("previous_close"),
            change_pct_today=raw.get("change_pct_today", raw.get("change_pct")),
            change_pct_5d=raw.get("change_pct_5d"),
            change_pct_20d=raw.get("change_pct_20d"),
        )
    else:
        raise TypeError("provider returned an unsupported quote type")
    if quote.symbol != symbol:
        raise ValueError(f"provider returned {quote.symbol} for requested {symbol}")
    return quote


def build_market_snapshot(
    symbols: Iterable[str],
    provider: SnapshotQuoteProvider,
    *,
    stale_after: timedelta = timedelta(hours=96),
    clock: Any = _utc_now,
) -> MarketSnapshot:
    """Fetch every symbol once through one provider and freeze the result."""
    requested = tuple(dict.fromkeys(normalize_symbol(symbol) for symbol in symbols))
    now = clock()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    quotes: dict[str, QuoteSnapshot] = {}
    batch: Mapping[str, Any] | None = None
    get_prices = getattr(provider, "get_prices", None)
    if callable(get_prices):
        try:
            candidate = get_prices(requested)
            if isinstance(candidate, Mapping):
                batch = candidate
        except Exception:
            batch = None
    for symbol in requested:
        try:
            raw = batch.get(symbol) if batch is not None else provider.get_price(symbol)
            quotes[symbol] = _coerce_quote(
                symbol,
                raw,
                now=now,
                stale_after=stale_after,
            )
        except Exception as exc:
            quotes[symbol] = _error_quote(symbol, "PROVIDER_ERROR", str(exc))
    valid = tuple(symbol for symbol in requested if quotes[symbol].decision_eligible)
    invalid = tuple(symbol for symbol in requested if symbol not in set(valid))
    coverage = len(valid) / len(requested) if requested else 0.0
    market_status = "NORMAL" if coverage >= 0.9 else "DEGRADED" if valid else "UNAVAILABLE"
    summary: dict[str, int] = {}
    for quote in quotes.values():
        key = f"{quote.source}:{quote.status}"
        summary[key] = summary.get(key, 0) + 1
    return MarketSnapshot(
        snapshot_id=f"mkt_{now.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:12]}",
        generated_at_utc=_iso_utc(now),
        generated_at_local=now.astimezone().isoformat(),
        market_status=market_status,
        requested_symbols=requested,
        valid_symbols=valid,
        invalid_symbols=invalid,
        coverage_ratio=coverage,
        provider_summary=summary,
        quotes=quotes,
    )


class SnapshotMarketDataProvider:
    """Read-only adapter for legacy consumers; it never performs I/O."""

    def __init__(self, snapshot: MarketSnapshot):
        self.snapshot = snapshot

    def get_price(self, symbol: str) -> dict[str, Any]:
        return self.snapshot.quote(symbol).to_dict()

    def get_batch_prices(self, symbols: Iterable[str]) -> dict[str, dict[str, Any]]:
        return {normalize_symbol(symbol): self.get_price(symbol) for symbol in symbols}

    def get_technical_features(self, symbol: str) -> dict[str, Any]:
        quote = self.snapshot.quote(symbol)
        if not quote.decision_eligible:
            return {"status": quote.status, "momentum": None, "volatility": None, "trend": "unknown"}
        changes = [value for value in (quote.change_pct_5d, quote.change_pct_20d) if value is not None]
        momentum = sum(changes) / len(changes) / 100 if changes else 0.0
        trend = "up" if momentum > 0.005 else "down" if momentum < -0.005 else "flat"
        return {"status": "valid", "momentum": momentum, "volatility": None, "trend": trend}

    def get_market_context(self) -> dict[str, Any]:
        return {
            "status": "snapshot_only",
            "snapshot_id": self.snapshot.snapshot_id,
            "market_regime": "unknown",
            "SPY_trend": "unknown",
            "volatility": None,
            "confidence": 0.0,
        }
