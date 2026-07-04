"""JSON report output for B12 backtests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_report(path: Path, report: dict[str, Any]) -> None:
    """Atomically write runtime/backtest_report.json."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)
