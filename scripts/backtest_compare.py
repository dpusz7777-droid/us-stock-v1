#!/usr/bin/env python3
"""One-command B13 multi-strategy backtest and comparison."""

from __future__ import annotations

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backtest.compare import (
    build_regime_report,
    build_stat_robustness_report,
    compare_reports,
)
from backtest.runner import BacktestRunner


def main() -> None:
    runtime_dir = BASE_DIR / "runtime"
    signals_path = runtime_dir / "signals.json"
    BacktestRunner().run_all(signals_path, runtime_dir)
    comparison = compare_reports(
        runtime_dir,
        runtime_dir / "backtest_compare.json",
    )
    regime_report = build_regime_report(
        runtime_dir,
        runtime_dir / "backtest_regime_report.json",
    )
    stat_report = build_stat_robustness_report(
        runtime_dir,
        runtime_dir / "stat_robustness_report.json",
    )
    print(json.dumps(comparison, ensure_ascii=False, indent=2))
    print(json.dumps(regime_report, ensure_ascii=False, indent=2))
    print(json.dumps(stat_report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
