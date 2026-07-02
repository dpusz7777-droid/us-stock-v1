"""Compare all B13 strategy backtest reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .report import write_report
from .stat_tests import run_statistical_tests


def _strategy_name(path: Path, report: dict[str, Any]) -> str:
    if report.get("strategy"):
        return str(report["strategy"])
    suffix = path.stem.removeprefix("backtest_report_")
    return suffix


def compare_reports(runtime_dir: Path, output_path: Path) -> dict[str, Any]:
    ranking: list[dict[str, Any]] = []
    for path in sorted(runtime_dir.glob("backtest_report_*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        metrics = report.get("metrics", {})
        total_return = float(metrics.get("total_return", 0.0))
        drawdown = float(metrics.get("max_drawdown", 0.0))
        profit_factor = float(metrics.get("profit_factor", 0.0))
        signal_accuracy = float(metrics.get("signal_accuracy", 0.0))
        strategy_alpha = signal_accuracy - 0.5
        # A zero-drawdown run has no risk denominator; use raw return as fallback.
        sharpe = total_return / drawdown if drawdown > 0 else total_return
        ranking.append({
            "strategy": _strategy_name(path, report),
            "return": round(total_return, 6),
            "max_drawdown": round(drawdown, 6),
            "sharpe": round(sharpe, 6),
            "profit_factor": round(profit_factor, 6),
            "signal_accuracy": round(signal_accuracy, 6),
            "strategy_alpha": round(strategy_alpha, 6),
        })

    if not ranking:
        raise ValueError("no backtest_report_*.json files found")

    ranking.sort(
        key=lambda item: (item["profit_factor"], item["return"]),
        reverse=True,
    )
    best_return = max(ranking, key=lambda item: item["return"])
    best_drawdown = min(ranking, key=lambda item: item["max_drawdown"])
    best_sharpe = max(ranking, key=lambda item: item["sharpe"])
    best_alpha = max(ranking, key=lambda item: item["strategy_alpha"])
    comparison = {
        "best_strategy": ranking[0]["strategy"],
        "best_return": {
            "strategy": best_return["strategy"],
            "value": best_return["return"],
        },
        "best_drawdown": {
            "strategy": best_drawdown["strategy"],
            "value": best_drawdown["max_drawdown"],
        },
        "best_sharpe": {
            "strategy": best_sharpe["strategy"],
            "value": best_sharpe["sharpe"],
        },
        "best_alpha": {
            "strategy": best_alpha["strategy"],
            "value": best_alpha["strategy_alpha"],
        },
        "ranking": ranking,
    }
    write_report(output_path, comparison)
    return comparison


def build_regime_report(runtime_dir: Path, output_path: Path) -> dict[str, Any]:
    """Compare strategy return and win rate inside each market regime."""
    strategies: dict[str, dict[str, Any]] = {}
    for path in sorted(runtime_dir.glob("backtest_report_*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        strategy = _strategy_name(path, report)
        metrics = report.get("metrics", {})
        strategies[strategy] = metrics.get(
            "strategy_performance_by_regime",
            {},
        )

    regimes = sorted({
        regime
        for performance in strategies.values()
        for regime in performance
    })
    regime_comparison: dict[str, Any] = {}
    winners: set[str] = set()
    for regime in regimes:
        ranking = []
        for strategy, performance in strategies.items():
            values = performance.get(
                regime,
                {"return": 0.0, "win_rate": 0.0, "trade_count": 0},
            )
            ranking.append({
                "strategy": strategy,
                "return": float(values.get("return", 0.0)),
                "win_rate": float(values.get("win_rate", 0.0)),
                "trade_count": int(values.get("trade_count", 0)),
            })
        ranking.sort(key=lambda row: row["return"], reverse=True)
        if ranking:
            winners.add(ranking[0]["strategy"])
        regime_comparison[regime] = {
            "best_strategy": ranking[0]["strategy"] if ranking else None,
            "ranking": ranking,
            "return_distribution": {
                row["strategy"]: row["return"] for row in ranking
            },
            "win_rate_distribution": {
                row["strategy"]: row["win_rate"] for row in ranking
            },
        }

    output = {
        "regimes": regime_comparison,
        "ranking_changes": len(winners) > 1,
    }
    write_report(output_path, output)
    return output


def build_stat_robustness_report(
    runtime_dir: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Run bootstrap, permutation, and noise-sensitivity tests."""
    ranking = []
    for path in sorted(runtime_dir.glob("backtest_report_*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        strategy = _strategy_name(path, report)
        tests = run_statistical_tests(report.get("equity_curve", []))
        ranking.append({
            "strategy": strategy,
            "classification": tests["classification"],
            "passed": tests["passed"],
            "alpha_mean": tests["alpha_mean"],
            "alpha_std": tests["alpha_std"],
            "alpha_p_value": tests["alpha_p_value"],
            "confidence_interval": tests["bootstrap"]["confidence_interval"],
            "noise_sensitivity": tests["noise_sensitivity"],
            "bootstrap": tests["bootstrap"],
            "permutation": tests["permutation"],
        })

    class_rank = {"significant": 3, "stable": 2, "unstable": 1, "likely_noise": 0}
    ranking.sort(
        key=lambda row: (
            class_rank[row["classification"]],
            -row["alpha_p_value"],
            row["alpha_mean"],
        ),
        reverse=True,
    )
    output = {
        "robustness_ranking": ranking,
        "all_strategies_passed": bool(ranking) and all(
            row["passed"] for row in ranking
        ),
        "significance_rules": {
            "significant": "p < 0.05",
            "likely_noise": "p > 0.1",
        },
    }
    write_report(output_path, output)
    return output
