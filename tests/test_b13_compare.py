import json

from backtest.compare import build_regime_report, compare_reports
from backtest.runner import BacktestRunner


def test_runner_generates_both_strategy_reports(tmp_path):
    signals_path = tmp_path / "signals.json"
    signals_path.write_text(
        json.dumps(
            [
                {
                    "cycle_id": f"{index:06d}",
                    "signals": [{
                        "symbol": "AAPL",
                        "price": price,
                        "volume": 1000 + index,
                        "timestamp": f"T{index}",
                        "source": "realtime_sim",
                        "action": "HOLD",
                        "score": 0,
                    }],
                }
                for index, price in enumerate(
                    [200, 170, 190, 230, 180, 210],
                    start=1,
                )
            ]
        ),
        encoding="utf-8",
    )

    results = BacktestRunner().run_all(signals_path, tmp_path)

    assert set(results) == {"MomentumStrategy", "MeanReversionStrategy"}
    for filename in (
        "backtest_report_momentum.json",
        "backtest_report_meanrev.json",
    ):
        report = json.loads((tmp_path / filename).read_text(encoding="utf-8"))
        assert report["equity_curve"]
        assert report["strategy"]
        assert "metrics" in report


def test_compare_ranks_reports(tmp_path):
    reports = {
        "momentum": ("MomentumStrategy", 0.21, 0.07, 1.5),
        "meanrev": ("MeanReversionStrategy", 0.12, 0.02, 2.5),
    }
    for suffix, (strategy, total_return, drawdown, profit_factor) in reports.items():
        (tmp_path / f"backtest_report_{suffix}.json").write_text(
            json.dumps({
                "strategy": strategy,
                "metrics": {
                    "total_return": total_return,
                    "max_drawdown": drawdown,
                    "profit_factor": profit_factor,
                },
            }),
            encoding="utf-8",
        )

    output_path = tmp_path / "backtest_compare.json"
    comparison = compare_reports(tmp_path, output_path)

    assert comparison["best_strategy"] == "MeanReversionStrategy"
    assert comparison["best_return"]["strategy"] == "MomentumStrategy"
    assert comparison["best_drawdown"]["strategy"] == "MeanReversionStrategy"
    assert comparison["best_sharpe"]["strategy"] == "MeanReversionStrategy"
    assert [row["strategy"] for row in comparison["ranking"]] == [
        "MeanReversionStrategy",
        "MomentumStrategy",
    ]
    assert output_path.exists()


def test_regime_report_detects_ranking_changes(tmp_path):
    reports = {
        "momentum": {
            "strategy": "MomentumStrategy",
            "metrics": {
                "strategy_performance_by_regime": {
                    "trending_up": {"return": 0.2, "win_rate": 0.8, "trade_count": 4},
                    "sideways": {"return": -0.1, "win_rate": 0.2, "trade_count": 4},
                }
            },
        },
        "meanrev": {
            "strategy": "MeanReversionStrategy",
            "metrics": {
                "strategy_performance_by_regime": {
                    "trending_up": {"return": 0.05, "win_rate": 0.5, "trade_count": 2},
                    "sideways": {"return": 0.15, "win_rate": 0.75, "trade_count": 4},
                }
            },
        },
    }
    for suffix, report in reports.items():
        (tmp_path / f"backtest_report_{suffix}.json").write_text(
            json.dumps(report),
            encoding="utf-8",
        )

    result = build_regime_report(
        tmp_path,
        tmp_path / "backtest_regime_report.json",
    )

    assert result["ranking_changes"] is True
    assert result["regimes"]["trending_up"]["best_strategy"] == "MomentumStrategy"
    assert result["regimes"]["sideways"]["best_strategy"] == "MeanReversionStrategy"
