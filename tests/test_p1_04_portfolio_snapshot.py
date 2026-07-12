"""P1-04 tests for the canonical portfolio repository and valuation snapshot."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

import portfolio_service
from northstar.data.market_snapshot import build_market_snapshot
from northstar.data.portfolio_snapshot import (
    FORMAL_PORTFOLIO_PATH,
    Position,
    PortfolioRepository,
    PortfolioSnapshot,
    PortfolioSourceConflictError,
    PortfolioState,
    compare_portfolio_sources,
    migrate_legacy_document,
    requested_market_symbols,
    value_portfolio,
)
from northstar.reports.daily_decision_report import generate_daily_decision_report
from northstar.ui.dashboard import _portfolio_display_model, load_latest_daily_decision_report


NOW = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
D = Decimal


def formal_document(positions=None, cash=100.0, currency="USD"):
    positions = positions if positions is not None else [("AAA", 1.5, 10.0), ("BBB", 2, 20.0)]
    transactions = []
    for index, (symbol, quantity, average_cost) in enumerate(positions, start=1):
        transactions.append({
            "transaction_id": f"txn_{index}", "external_id": None,
            "transaction_type": "OPENING_POSITION", "symbol": symbol,
            "shares": quantity, "price": average_cost, "amount": None,
            "fees": 0, "executed_at": None, "effective_at": "2026-07-01T00:00:00Z",
            "recorded_at": "2026-07-01T00:00:00Z", "source": "legacy_migration", "note": "fixture",
        })
    return {
        "schema_version": "1.1",
        "account": {
            "account_id": "fixture_account", "account_name": "fixture", "broker": "local",
            "base_currency": currency, "cash_status": "known", "cash": cash,
            "buying_power": cash, "created_at": "2026-07-01T00:00:00Z",
            "updated_at": "2026-07-01T00:00:00Z",
        },
        "settings": {}, "transactions": transactions,
    }


def legacy_document(positions=None, cash=100.0):
    positions = positions if positions is not None else [("AAA", 1.5, 10.0), ("BBB", 2, 20.0)]
    return {
        "positions": [
            {"ticker": symbol, "shares": quantity, "avg_cost": cost, "added": "2026-07-01T00:00:00Z"}
            for symbol, quantity, cost in positions
        ],
        "cash": cash,
        "transactions": [],
        "created": "2026-07-01T00:00:00Z",
    }


def write_json(path, document):
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")


class QuoteProvider:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def get_price(self, symbol):
        self.calls.append(symbol)
        row = self.rows[symbol]
        if isinstance(row, Exception):
            raise row
        return row


def quote(symbol, price, **updates):
    row = {
        "symbol": symbol, "price": price, "currency": "USD",
        "source": "fixture_provider", "as_of": NOW.isoformat(), "status": "valid",
        "is_stale": False, "is_mock": False,
    }
    row.update(updates)
    return row


def state_and_snapshot(tmp_path, positions=None, cash=100.0, rows=None, currency="USD"):
    path = tmp_path / "portfolio_migrated_candidate.json"
    write_json(path, formal_document(positions, cash, currency))
    state = PortfolioRepository(path).load()
    rows = rows or {symbol: quote(symbol, 20 if symbol == "AAA" else 30) for symbol in state.position_symbols}
    market = build_market_snapshot(state.position_symbols, QuoteProvider(rows), clock=lambda: NOW)
    return state, market, value_portfolio(state, market, clock=lambda: NOW)


def test_unique_formal_repository_loads_schema(tmp_path) -> None:
    state, _, _ = state_and_snapshot(tmp_path)
    assert state.schema_version == "1.1"
    assert state.position_symbols == ("AAA", "BBB")
    assert state.cash == D("100.0")
    assert state.base_currency == "USD"


def test_legacy_migration_preserves_holdings_cash_and_currency() -> None:
    migrated = migrate_legacy_document(
        legacy_document(), account_id="local", base_currency="USD", migration_time=NOW.isoformat()
    )
    state = portfolio_service.build_portfolio_state(migrated)
    assert state.cash == D("100.0")
    assert state.positions["AAA"].shares == D("1.5")
    assert state.positions["AAA"].avg_cost == D("10.0")
    assert migrated["account"]["base_currency"] == "USD"


def test_migration_is_idempotent() -> None:
    first = migrate_legacy_document(
        legacy_document(), account_id="local", base_currency="USD", migration_time=NOW.isoformat()
    )
    second = migrate_legacy_document(
        first, account_id="ignored", base_currency="USD", migration_time=NOW.isoformat()
    )
    assert second == first
    assert len(second["transactions"]) == 2


def test_conflicting_sources_are_reported_without_overwrite(tmp_path) -> None:
    formal = tmp_path / "portfolio_migrated_candidate.json"
    legacy = tmp_path / "portfolio.json"
    write_json(formal, formal_document())
    write_json(legacy, legacy_document([("AAA", 9, 10.0), ("BBB", 2, 20.0)]))
    before = formal.read_bytes(), legacy.read_bytes()
    result = compare_portfolio_sources(formal, legacy)
    assert result["conflict"] is True
    assert {row["field"] for row in result["differences"]} == {"quantity"}
    assert before == (formal.read_bytes(), legacy.read_bytes())


def test_nonempty_legacy_transactions_block_migration() -> None:
    legacy = legacy_document()
    legacy["transactions"] = [{"unknown": True}]
    with pytest.raises(PortfolioSourceConflictError):
        migrate_legacy_document(legacy, account_id="local", base_currency="USD", migration_time=NOW.isoformat())


def test_portfolio_symbols_join_watchlist_and_deduplicate(tmp_path) -> None:
    state, _, _ = state_and_snapshot(tmp_path)
    assert requested_market_symbols(["aaa", "CCC", "AAA"], state) == ("AAA", "CCC", "BBB")


def test_holding_outside_watchlist_is_requested_and_valued(tmp_path) -> None:
    state, market, portfolio = state_and_snapshot(tmp_path, positions=[("OUT", 2, 5)])
    assert requested_market_symbols(["AAA"], state) == ("AAA", "OUT")
    assert market.quote("OUT").decision_eligible
    assert portfolio.positions[0].market_value == D("60")


def test_every_symbol_is_fetched_once(tmp_path) -> None:
    path = tmp_path / "portfolio_migrated_candidate.json"
    write_json(path, formal_document())
    state = PortfolioRepository(path).load()
    provider = QuoteProvider({"AAA": quote("AAA", 20), "BBB": quote("BBB", 30), "CCC": quote("CCC", 40)})
    requested = requested_market_symbols(["AAA", "CCC"], state)
    build_market_snapshot(requested, provider, clock=lambda: NOW)
    assert provider.calls == ["AAA", "CCC", "BBB"]


def test_complete_valuation_and_all_formulas(tmp_path) -> None:
    _, _, snapshot = state_and_snapshot(tmp_path)
    assert snapshot.valuation_status == "complete"
    assert snapshot.total_market_value == D("90.0")
    assert snapshot.total_cost_basis == D("55.00")
    assert snapshot.total_unrealized_pnl == D("35.00")
    assert snapshot.total_asset_value == D("190.0")
    aaa = snapshot.positions[0]
    assert aaa.market_value == D("30.0")
    assert aaa.cost_basis == D("15.00")
    assert aaa.unrealized_pnl == D("15.00")
    assert aaa.unrealized_pnl_percent == D("100")


def test_any_missing_quote_is_incomplete_and_hides_totals(tmp_path) -> None:
    rows = {"AAA": quote("AAA", 20), "BBB": RuntimeError("offline")}
    _, _, snapshot = state_and_snapshot(tmp_path, rows=rows)
    assert snapshot.valuation_status == "incomplete"
    assert snapshot.missing_symbols == ("BBB",)
    assert snapshot.total_market_value is None
    assert snapshot.total_unrealized_pnl is None
    assert snapshot.total_asset_value is None
    assert snapshot.partial_market_value == D("30.0")


@pytest.mark.parametrize(
    "bad_quote",
    [
        quote("BBB", 0),
        quote("BBB", 30, status="mock", source="demo", is_mock=True),
        quote("BBB", 30, status="stale", is_stale=True, as_of=(NOW - timedelta(days=5)).isoformat()),
    ],
)
def test_zero_mock_and_stale_quotes_never_value_holdings(tmp_path, bad_quote) -> None:
    rows = {"AAA": quote("AAA", 20), "BBB": bad_quote}
    _, _, snapshot = state_and_snapshot(tmp_path, rows=rows)
    assert snapshot.valuation_status == "incomplete"
    assert snapshot.positions[1].current_price is None
    assert snapshot.total_asset_value is None


def test_zero_quantity_is_not_a_position() -> None:
    migrated = migrate_legacy_document(
        legacy_document([("ZERO", 0, 10), ("AAA", 1, 10)]),
        account_id="local", base_currency="USD", migration_time=NOW.isoformat(),
    )
    state = portfolio_service.build_portfolio_state(migrated)
    assert tuple(state.positions) == ("AAA",)


@pytest.mark.parametrize(
    "positions,cash",
    [([("AAA", -1, 10)], 100), ([("AAA", 1, -10)], 100), ([("AAA", 1, 10)], "not-a-number")],
)
def test_negative_quantity_cost_and_invalid_cash_are_rejected(tmp_path, positions, cash) -> None:
    path = tmp_path / "portfolio_migrated_candidate.json"
    write_json(path, formal_document(positions, cash))
    with pytest.raises(portfolio_service.PortfolioError):
        PortfolioRepository(path).load()


def test_multi_currency_without_fx_is_incomplete(tmp_path) -> None:
    state = PortfolioState(
        schema_version="1.1", account_id="x", account_type="brokerage", base_currency="USD",
        cash=D("100"), positions=(Position("EURX", D("1"), D("10"), "EUR", "fixture"),),
        source="fixture", updated_at=NOW.isoformat(),
    )
    market = build_market_snapshot(
        ["EURX"], QuoteProvider({"EURX": quote("EURX", 20, currency="EUR")}), clock=lambda: NOW
    )
    snapshot = value_portfolio(state, market, clock=lambda: NOW)
    assert snapshot.valuation_status == "incomplete"
    assert snapshot.positions[0].valuation_status == "currency_mismatch"
    assert snapshot.total_asset_value is None


def test_no_positions_status_keeps_cash_trustworthy(tmp_path) -> None:
    state, _, snapshot = state_and_snapshot(tmp_path, positions=[])
    assert snapshot.valuation_status == "no_positions"
    assert snapshot.total_market_value == D("0")
    assert snapshot.total_asset_value == state.cash


def test_portfolio_snapshot_binds_market_snapshot_id(tmp_path) -> None:
    _, market, snapshot = state_and_snapshot(tmp_path)
    assert snapshot.market_snapshot_id == market.snapshot_id
    assert snapshot.portfolio_snapshot_id.startswith("pf_")


def test_portfolio_snapshot_json_round_trip(tmp_path) -> None:
    _, _, snapshot = state_and_snapshot(tmp_path)
    assert PortfolioSnapshot.from_dict(snapshot.to_dict()).to_dict() == snapshot.to_dict()


def test_report_and_ui_use_same_portfolio_snapshot_without_provider_call(tmp_path) -> None:
    state, market, portfolio = state_and_snapshot(tmp_path)

    class BombProvider:
        def get_price(self, symbol):
            raise AssertionError("report/UI must not refetch prices")

    report = generate_daily_decision_report(
        snapshot=market, symbols=["AAA", "BBB"], portfolio_state=state,
        portfolio_snapshot=portfolio, provider=BombProvider(), save=False,
    )
    assert report["portfolio_snapshot_id"] == portfolio.portfolio_snapshot_id
    assert report["portfolio_snapshot"]["portfolio_snapshot_id"] == portfolio.portfolio_snapshot_id
    path = tmp_path / "daily_decision_2026-07-10.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    loaded = load_latest_daily_decision_report(tmp_path)
    assert loaded["portfolio_snapshot_id"] == portfolio.portfolio_snapshot_id


def test_ui_incomplete_model_warns_and_hides_totals(tmp_path) -> None:
    rows = {"AAA": quote("AAA", 20), "BBB": RuntimeError("offline")}
    state, market, portfolio = state_and_snapshot(tmp_path, rows=rows)
    report = generate_daily_decision_report(
        snapshot=market, symbols=["AAA", "BBB"], portfolio_state=state,
        portfolio_snapshot=portfolio, save=False,
    )
    model = _portfolio_display_model(report)
    assert model["warning"]
    assert model["show_totals"] is False
    assert model["total_asset_value"] is None
    assert model["missing_symbols"] == ["BBB"]


def test_formal_portfolio_bytes_remain_unchanged() -> None:
    before = hashlib.sha256(FORMAL_PORTFOLIO_PATH.read_bytes()).hexdigest()
    PortfolioRepository().load()
    after = hashlib.sha256(FORMAL_PORTFOLIO_PATH.read_bytes()).hexdigest()
    assert after == before
