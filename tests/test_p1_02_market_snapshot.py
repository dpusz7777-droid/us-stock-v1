"""P1-02 regression tests for one immutable, fail-closed quote snapshot."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from northstar.data.market_snapshot import (
    MarketSnapshot,
    SnapshotMarketDataProvider,
    build_market_snapshot,
)
from northstar.reports.daily_decision_report import generate_daily_decision_report
from northstar.ui.dashboard import (
    _report_is_formal_decision_safe,
    load_latest_daily_decision_report,
)


NOW = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)


class MappingProvider:
    def __init__(self, rows):
        self.rows = rows
        self.calls: list[str] = []

    def get_price(self, symbol):
        self.calls.append(symbol)
        row = self.rows[symbol]
        if isinstance(row, Exception):
            raise row
        return row


def quote(symbol: str, price: float = 100.0, **overrides):
    row = {
        "symbol": symbol,
        "price": price,
        "currency": "USD",
        "source": "fixture_provider",
        "as_of": NOW.isoformat(),
        "status": "valid",
        "is_stale": False,
        "is_mock": False,
        "previous_close": price - 1 if price is not None else None,
        "change_pct_today": 1.0,
        "change_pct_5d": 3.0,
        "change_pct_20d": 5.0,
    }
    row.update(overrides)
    return row


def snapshot_for(symbols, rows=None) -> MarketSnapshot:
    data = rows or {symbol: quote(symbol, 100 + index) for index, symbol in enumerate(symbols)}
    return build_market_snapshot(symbols, MappingProvider(data), clock=lambda: NOW)


def test_snapshot_fetches_each_symbol_once_and_deduplicates() -> None:
    provider = MappingProvider({"AAPL": quote("AAPL"), "NVDA": quote("NVDA")})
    snapshot = build_market_snapshot(["aapl", "NVDA", "AAPL"], provider, clock=lambda: NOW)
    assert provider.calls == ["AAPL", "NVDA"]
    assert snapshot.requested_symbols == ("AAPL", "NVDA")


def test_snapshot_is_immutable() -> None:
    snapshot = snapshot_for(["AAPL"])
    with pytest.raises(FrozenInstanceError):
        snapshot.snapshot_id = "changed"
    with pytest.raises(TypeError):
        snapshot.quotes["AAPL"] = snapshot.quotes["AAPL"]


def test_snapshot_round_trip_is_stable() -> None:
    snapshot = snapshot_for(["AAPL", "NVDA"])
    assert MarketSnapshot.from_dict(snapshot.to_dict()).to_dict() == snapshot.to_dict()


def test_zero_and_missing_price_are_invalid() -> None:
    rows = {
        "ZERO": quote("ZERO", 0),
        "NONE": quote("NONE", price=None),
    }
    snapshot = snapshot_for(["ZERO", "NONE"], rows)
    assert snapshot.valid_symbols == ()
    assert snapshot.market_status == "UNAVAILABLE"


def test_mock_quote_is_invalid() -> None:
    rows = {"NVDA": quote("NVDA", status="mock", is_mock=True, source="demo")}
    snapshot = snapshot_for(["NVDA"], rows)
    assert snapshot.quote("NVDA").status == "mock"
    assert not snapshot.quote("NVDA").decision_eligible


def test_old_quote_is_marked_stale() -> None:
    rows = {"AAPL": quote("AAPL", as_of=(NOW - timedelta(days=5)).isoformat())}
    snapshot = snapshot_for(["AAPL"], rows)
    assert snapshot.quote("AAPL").status == "stale"
    assert snapshot.quote("AAPL").is_stale


def test_missing_provenance_is_error() -> None:
    snapshot = snapshot_for(["AAPL"], {"AAPL": quote("AAPL", source="", as_of=None)})
    assert snapshot.quote("AAPL").status == "error"


def test_provider_exception_becomes_error_row() -> None:
    snapshot = snapshot_for(["AAPL"], {"AAPL": RuntimeError("offline")})
    assert snapshot.quote("AAPL").status == "error"
    assert snapshot.quote("AAPL").price is None


def test_partial_failure_sets_degraded() -> None:
    rows = {symbol: quote(symbol) for symbol in ["A", "B", "C", "D"]}
    rows["D"] = RuntimeError("offline")
    snapshot = snapshot_for(rows, rows)
    assert snapshot.market_status == "DEGRADED"
    assert snapshot.coverage_ratio == 0.75


def test_snapshot_adapter_never_calls_network() -> None:
    snapshot = snapshot_for(["AAPL"])
    adapter = SnapshotMarketDataProvider(snapshot)
    assert adapter.get_price("AAPL")["price"] == 100
    assert adapter.get_technical_features("AAPL")["status"] == "valid"


def test_report_uses_same_snapshot_id_everywhere() -> None:
    symbols = ["NVDA", "AMD", "MSFT", "AAPL", "META"]
    snapshot = snapshot_for(symbols)
    report = generate_daily_decision_report(
        snapshot=snapshot,
        symbols=symbols,
        portfolio={"NVDA": {"shares": 2, "avg_cost": 80}},
        save=False,
    )
    assert report["snapshot_id"] == snapshot.snapshot_id
    assert report["market_snapshot"]["snapshot_id"] == snapshot.snapshot_id
    assert report["portfolio_valuation"]["snapshot_id"] == snapshot.snapshot_id
    assert all(row["snapshot_id"] == snapshot.snapshot_id for row in report["top5_opportunity"])


def test_report_with_supplied_snapshot_never_calls_provider() -> None:
    class BombProvider:
        def get_price(self, symbol):
            raise AssertionError("provider must not be called after snapshot is frozen")

    symbols = ["A", "B", "C", "D", "E"]
    snapshot = snapshot_for(symbols)
    report = generate_daily_decision_report(
        snapshot=snapshot,
        symbols=symbols,
        portfolio={},
        provider=BombProvider(),
        save=False,
    )
    assert report["snapshot_id"] == snapshot.snapshot_id


def test_mock_in_formal_chain_disables_recommendations() -> None:
    symbols = ["A", "B", "C", "D", "E"]
    rows = {symbol: quote(symbol) for symbol in symbols}
    rows["E"] = quote("E", source="demo", status="mock", is_mock=True)
    snapshot = snapshot_for(symbols, rows)
    report = generate_daily_decision_report(snapshot=snapshot, symbols=symbols, portfolio={}, save=False)
    assert report["recommendation_status"] == "DATA_INSUFFICIENT"
    assert report["top5_opportunity"] == []
    assert report["top5_risk"] == []
    assert not _report_is_formal_decision_safe(report)


def test_missing_holding_price_makes_total_valuation_incomplete() -> None:
    symbols = ["A", "B", "C", "D", "E"]
    snapshot = snapshot_for(symbols)
    report = generate_daily_decision_report(
        snapshot=snapshot,
        symbols=symbols,
        portfolio={"MISSING": {"shares": 3, "avg_cost": 50}},
        save=False,
    )
    valuation = report["portfolio_valuation"]
    assert valuation["valuation_status"] == "error"
    assert valuation["total_market_value"] is None
    assert valuation["total_unrealized_pnl"] is None


def test_ui_loader_reads_latest_valid_json_without_writing(tmp_path) -> None:
    symbols = ["A", "B", "C", "D", "E"]
    snapshot = snapshot_for(symbols)
    report = generate_daily_decision_report(snapshot=snapshot, symbols=symbols, portfolio={}, save=False)
    old = tmp_path / "daily_decision_2026-07-09.json"
    new = tmp_path / "daily_decision_2026-07-10.json"
    old.write_text("{}", encoding="utf-8")
    new.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    before = new.stat().st_mtime_ns
    loaded = load_latest_daily_decision_report(tmp_path)
    assert loaded is not None
    assert loaded["snapshot_id"] == snapshot.snapshot_id
    assert new.stat().st_mtime_ns == before


def test_ui_loader_rejects_report_snapshot_id_mismatch(tmp_path) -> None:
    symbols = ["A", "B", "C", "D", "E"]
    report = generate_daily_decision_report(
        snapshot=snapshot_for(symbols), symbols=symbols, portfolio={}, save=False
    )
    report["snapshot_id"] = "tampered"
    path = tmp_path / "daily_decision_2026-07-10.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    assert load_latest_daily_decision_report(tmp_path) is None
