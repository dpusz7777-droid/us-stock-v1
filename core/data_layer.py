#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Polaris Data Layer – real data gateway for portfolio, prices, reports.

All external data enters the system through this module.

Data sources (in order):
    1. portfolio_service → real portfolio JSON (positions, cash, equity)
    2. V1CompatibleBridge (price_provider_v2) → real market prices
    3. YFinancePriceProvider (yfinance) → fallback prices
    4. Portfolio's own last_price (from JSON) → embedded cache
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from main import DEFAULT_SCHEMA_PORTFOLIO_FILE
from portfolio_service import (
    PortfolioError,
    PositionState,
    apply_market_prices,
    get_portfolio_snapshot,
)
from price_provider import PriceProvider, YFinancePriceProvider
from price_provider_v2 import V1CompatibleBridge

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PricePoint:
    """Price result with status metadata."""

    value: Decimal | None
    status: str  # "ok" | "missing"
    source: str  # "v2" | "yfinance" | "portfolio_cache"
    as_of: float | None = None


@dataclass(frozen=True)
class PortfolioSnapshot:
    """Full portfolio with prices baked into each position."""

    positions: dict[str, "PositionView"]
    total_equity: Decimal | None
    cash: Decimal | None
    buying_power: Decimal | None
    total_unrealized_pnl: Decimal | None


@dataclass(frozen=True)
class PositionView:
    symbol: str
    shares: Decimal
    avg_cost: Decimal | None
    last_price: Decimal | None
    market_value: Decimal | None
    unrealized_pnl: Decimal | None
    unrealized_pnl_pct: Decimal | None
    price_source: str = "—"


@dataclass(frozen=True)
class MarketStatusItem:
    symbol: str
    price: PricePoint


@dataclass(frozen=True)
class ReportMeta:
    date: str
    type: str
    file_path: str
    content: str | None = None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SECTOR_MAP: dict[str, str] = {
    "NVDA": "信息技术",
    "SOFI": "金融服务",
    "SPCX": "航空航天",
}

ROOT = Path(__file__).parent.parent
REPORTS_DIR = ROOT / "reports"

_PRICE_CACHE: dict[str, PricePoint] = {}


# ---------------------------------------------------------------------------
# Core: get a real price for a symbol
# ---------------------------------------------------------------------------

def _get_primary() -> PriceProvider:
    return V1CompatibleBridge()


def _get_fallback() -> PriceProvider | None:
    try:
        return YFinancePriceProvider()
    except Exception:
        return None


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (ValueError, TypeError):
        return None


def _quote_price(quote: Any) -> Decimal | None:
    price = _decimal(getattr(quote, "price", None))
    return price if price is not None and price > 0 else None


def get_price(symbol: str) -> PricePoint:
    """Fetch real price for *symbol*.

    Chain:  V1CompatibleBridge → yfinance → in-memory cache → None
    No static/mock fallback – if no data, returns missing.
    """
    primary = _get_primary()

    # 1. Primary provider (price_provider_v2)
    try:
        quote = primary.get_quote(symbol)
        price = _quote_price(quote)
        if price is not None:
            as_of = getattr(quote, "price_as_of", None)
            if isinstance(as_of, datetime):
                as_of_ts = as_of.timestamp()
            elif isinstance(as_of, (int, float)):
                as_of_ts = float(as_of)
            else:
                as_of_ts = None
            pp = PricePoint(value=price, status="ok", source="v2", as_of=as_of_ts)
            _PRICE_CACHE[symbol] = pp
            return pp
    except Exception:
        pass

    # 2. yfinance fallback
    fallback = _get_fallback()
    if fallback is not None:
        try:
            quote = fallback.get_quote(symbol)
            price = _quote_price(quote)
            if price is not None:
                pp = PricePoint(value=price, status="ok", source="yfinance")
                _PRICE_CACHE[symbol] = pp
                return pp
        except Exception:
            pass

    # 3. In-memory cache (from earlier successful fetch this session)
    if symbol in _PRICE_CACHE:
        cached = _PRICE_CACHE[symbol]
        return PricePoint(value=cached.value, status="ok", source="cache", as_of=cached.as_of)

    return PricePoint(value=None, status="missing", source="no_data")


# ---------------------------------------------------------------------------
# Portfolio (real data from portfolio_service)
# ---------------------------------------------------------------------------

def get_portfolio() -> PortfolioSnapshot:
    """Load real portfolio from portfolio_service, apply real market prices."""
    try:
        state = get_portfolio_snapshot(DEFAULT_SCHEMA_PORTFOLIO_FILE)
    except Exception:
        return PortfolioSnapshot(
            positions={},
            total_equity=None,
            cash=None,
            buying_power=None,
            total_unrealized_pnl=None,
        )

    # Fetch real prices for all positions
    price_updates: dict[str, dict[str, Any]] = {}
    for symbol in state.positions:
        pp = get_price(symbol)
        if pp.value is not None:
            price_updates[symbol] = {"price": pp.value, "price_as_of": pp.as_of}

    # Apply market prices to get computed market_value / unrealized_pnl
    if price_updates:
        try:
            state = apply_market_prices(state, price_updates)
        except (PortfolioError, Exception):
            pass

    positions: dict[str, PositionView] = {}
    for symbol in sorted(state.positions):
        pos: PositionState = state.positions[symbol]
        price_source = "—"
        if symbol in _PRICE_CACHE:
            price_source = _PRICE_CACHE[symbol].source
        elif symbol in price_updates:
            price_source = "v2"

        positions[symbol] = PositionView(
            symbol=symbol,
            shares=pos.shares,
            avg_cost=pos.avg_cost,
            last_price=pos.last_price,
            market_value=pos.market_value,
            unrealized_pnl=pos.unrealized_pnl,
            unrealized_pnl_pct=pos.unrealized_pnl_pct,
            price_source=price_source,
        )

    total_equity = state.total_equity
    if total_equity is None and state.cash is not None:
        known_value = sum(
            (p.market_value or p.shares * p.avg_cost if p.avg_cost else Decimal("0"))
            for p in positions.values()
        )
        total_equity = state.cash + known_value

    return PortfolioSnapshot(
        positions=positions,
        total_equity=total_equity,
        cash=state.cash,
        buying_power=state.buying_power,
        total_unrealized_pnl=state.total_unrealized_pnl,
    )


# ---------------------------------------------------------------------------
# Market status
# ---------------------------------------------------------------------------

MARKET_SYMBOLS = ("NVDA", "SOFI", "SPCX")


def get_market_status() -> list[MarketStatusItem]:
    """Get prices for tracked tickers."""
    return [MarketStatusItem(symbol=s, price=get_price(s)) for s in MARKET_SYMBOLS]


# ---------------------------------------------------------------------------
# Reports (real markdown files from reports/)
# ---------------------------------------------------------------------------

def get_reports(limit: int = 20) -> list[ReportMeta]:
    """Load real report metadata + content from reports/ directory."""
    from report_index import recent_reports

    indexed = recent_reports(limit)
    if not indexed:
        paths = sorted(
            REPORTS_DIR.glob("*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:limit]
        indexed = [
            {
                "date": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
                .strftime("%Y-%m-%d %H:%M"),
                "type": p.stem,
                "file_path": p.relative_to(ROOT).as_posix(),
            }
            for p in paths
        ]

    reports_root = REPORTS_DIR.resolve()
    items: list[ReportMeta] = []
    for r in indexed[:limit]:
        raw_path = Path(str(r.get("file_path", "")))
        path = raw_path if raw_path.is_absolute() else ROOT / raw_path
        try:
            is_safe = path.resolve().is_relative_to(reports_root)
        except (OSError, ValueError):
            is_safe = False

        content: str | None = None
        if is_safe and path.suffix.lower() == ".md" and path.is_file():
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                content = None

        items.append(ReportMeta(
            date=str(r.get("date", "")),
            type=str(r.get("type", "report")),
            file_path=str(r.get("file_path", "")),
            content=content,
        ))
    return items


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

from signal_engine import Signal, signal_engine


def get_signals(symbols: list[str]) -> list[Signal]:
    """Evaluate signals for given symbols based on current prices."""
    from price_provider_v2 import PriceResultV2

    price_results: dict[str, PriceResultV2] = {}
    for symbol in symbols:
        pp = get_price(symbol)
        if pp.value is not None:
            price_results[symbol] = PriceResultV2(
                symbol=symbol,
                price=pp.value,
                source=pp.source,
                market_time=pp.as_of,
            )
    if not price_results:
        return []
    try:
        return list(signal_engine.evaluate(price_results))
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------

def clear_cache() -> None:
    _PRICE_CACHE.clear()


def prefetch_prices(symbols: list[str]) -> None:
    """Warm the price cache for a list of symbols."""
    for s in symbols:
        get_price(s)