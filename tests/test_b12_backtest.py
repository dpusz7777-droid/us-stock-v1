import json

from backtest.engine import (
    BacktestEngine,
    expand_signal_sequence,
    load_signals,
    sliding_windows,
)


def test_backtest_replays_cycles_and_writes_report(tmp_path):
    signals_path = tmp_path / "signals.json"
    report_path = tmp_path / "backtest_report.json"
    signals_path.write_text(
        json.dumps(
            [
                {
                    "cycle_id": "000003",
                    "signals": [
                        {"symbol": "AAPL", "price": 120, "action": "SELL"}
                    ],
                },
                {
                    "cycle_id": "000001",
                    "signals": [
                        {"symbol": "AAPL", "price": 100, "action": "BUY"}
                    ],
                },
                {
                    "cycle_id": "000002",
                    "signals": [
                        {"symbol": "AAPL", "price": 110, "action": "HOLD"}
                    ],
                },
            ]
        ),
        encoding="utf-8",
    )

    assert [row["cycle_id"] for row in load_signals(signals_path)] == [
        "000001",
        "000002",
        "000003",
    ]

    result = BacktestEngine().run(
        signals_path,
        report_path,
        auto_expand=False,
        inject_regimes=False,
        apply_microstructure=False,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert result.final_pnl == 2000.0
    assert result.metrics["total_return"] == 0.02
    assert result.metrics["win_rate"] == 1.0
    assert result.metrics["trade_count"] == 2
    assert result.metrics["max_drawdown"] == 0.0
    assert len(report["equity_curve"]) == 3
    assert report["final_pnl"] == 2000.0
    assert report["metrics"] == result.metrics


def test_small_signal_input_expands_without_mutating_source(tmp_path):
    signals_path = tmp_path / "signals.json"
    original = {
        "cycle_id": "000100",
        "signals": [{
            "symbol": "AAPL",
            "price": 200,
            "timestamp": "2026-01-01T00:00:00+00:00",
            "action": "HOLD",
        }],
    }
    signals_path.write_text(json.dumps(original), encoding="utf-8")
    rows = load_signals(signals_path)
    expanded = expand_signal_sequence(rows)

    assert len(expanded) == 10
    assert expanded[0]["cycle_id"] == "000100"
    assert expanded[1]["cycle_id"] == "001100"
    assert expanded[-1]["cycle_id"] == "009100"
    assert len({row["price"] for row in expanded}) > 1
    assert json.loads(signals_path.read_text(encoding="utf-8")) == original
    assert len(sliding_windows(expanded, 3)) == 8
