#!/usr/bin/env python3
"""CLI entrypoint for the independent B12 signal replay engine."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backtest import BacktestEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay runtime signals")
    parser.add_argument(
        "--signals",
        type=Path,
        default=BASE_DIR / "runtime" / "signals.json",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=BASE_DIR / "runtime" / "backtest_report.json",
    )
    args = parser.parse_args()

    result = BacktestEngine().run(args.signals, args.report)
    print(json.dumps(result.metrics, ensure_ascii=False, indent=2))
    print(f"final_pnl={result.final_pnl:.2f}")
    print(f"report={args.report}")


if __name__ == "__main__":
    main()
