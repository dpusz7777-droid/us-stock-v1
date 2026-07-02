import json

from backtest.compare import build_stat_robustness_report
from backtest.stat_tests import run_statistical_tests


def _strong_curve():
    curve = []
    for index in range(21):
        low = index % 2 == 0
        curve.append({
            "cycle_id": f"{index:06d}",
            "symbol": "AAPL",
            "price": 100.0 if low else 110.0,
            "action": "BUY" if low else "SELL",
            "equity": 100000.0 + index * 100,
            "regime": "sideways",
        })
    return curve


def test_statistical_tests_produce_ci_p_value_and_noise_results():
    result = run_statistical_tests(_strong_curve())

    assert result["bootstrap"]["samples"] == 100
    assert len(result["bootstrap"]["confidence_interval"]) == 2
    assert result["permutation"]["permutations"] == 100
    assert result["alpha_p_value"] < 0.05
    assert result["noise_sensitivity"]["stable"] is True
    assert result["classification"] == "significant"
    assert result["passed"] is True


def test_robustness_report_writes_ranking(tmp_path):
    for suffix, strategy in (
        ("momentum", "MomentumStrategy"),
        ("meanrev", "MeanReversionStrategy"),
    ):
        (tmp_path / f"backtest_report_{suffix}.json").write_text(
            json.dumps({
                "strategy": strategy,
                "equity_curve": _strong_curve(),
            }),
            encoding="utf-8",
        )

    output_path = tmp_path / "stat_robustness_report.json"
    report = build_stat_robustness_report(tmp_path, output_path)

    assert len(report["robustness_ranking"]) == 2
    assert report["all_strategies_passed"] is True
    assert output_path.exists()
