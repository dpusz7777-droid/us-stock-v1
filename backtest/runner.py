"""Run the B12 engine independently for multiple strategy types."""

from __future__ import annotations

import json
import random
import tempfile
from pathlib import Path
from typing import Any

from strategies import BaseStrategy, MeanReversionStrategy, MomentumStrategy

from .engine import (
    BacktestEngine,
    BacktestResult,
    load_signals,
)
from .microstructure import MarketMicrostructure, write_price_series
from .regime_generator import RegimeGenerator
from .report import write_report

STRATEGY_REPORTS: tuple[tuple[type[BaseStrategy], str], ...] = (
    (MomentumStrategy, "backtest_report_momentum.json"),
    (MeanReversionStrategy, "backtest_report_meanrev.json"),
)


def _create_strategy(strategy_type: type[BaseStrategy]) -> BaseStrategy:
    if strategy_type is MomentumStrategy:
        return MomentumStrategy(random.Random(42))
    return strategy_type()


def _strategy_cycles(
    rows: list[dict[str, Any]],
    strategy: BaseStrategy,
) -> list[dict[str, Any]]:
    cycles: list[dict[str, Any]] = []
    for row in rows:
        tick = {
            "symbol": str(row["symbol"]),
            "price": float(row["price"]),
            "volume": int(row.get("volume", 0)),
            "timestamp": str(row.get("timestamp", "")),
            "source": str(row.get("source", "realtime_sim")),
        }
        decision = strategy.generate(tick)
        signal = {
            key: value
            for key, value in row.items()
            if key not in {"cycle_id", "action", "score"}
        }
        signal.update(decision)
        cycles.append({
            "cycle_id": str(row["cycle_id"]),
            "signals": [signal],
        })
    return cycles


class BacktestRunner:
    """Apply strategy types to one signals source and run B12 for each."""

    def __init__(
        self,
        engine: BacktestEngine | None = None,
        microstructure_seed: int = 43,
    ) -> None:
        self.engine = engine or BacktestEngine()
        self.microstructure_seed = microstructure_seed

    def run_strategy(
        self,
        signals_path: Path,
        strategy_type: type[BaseStrategy],
        report_path: Path,
    ) -> BacktestResult:
        rows = load_signals(signals_path)
        if not rows:
            raise ValueError("signals.json contains no replayable signals")
        rows = RegimeGenerator().generate(rows)
        rows = MarketMicrostructure(seed=self.microstructure_seed).generate(rows)
        return self._run_strategy_rows(rows, strategy_type, report_path)

    def _run_strategy_rows(
        self,
        rows: list[dict[str, Any]],
        strategy_type: type[BaseStrategy],
        report_path: Path,
    ) -> BacktestResult:
        strategy = _create_strategy(strategy_type)
        cycles = _strategy_cycles(rows, strategy)

        with tempfile.TemporaryDirectory(prefix="b13_backtest_") as temp_dir:
            replay_path = Path(temp_dir) / "signals.json"
            replay_path.write_text(
                json.dumps(cycles, ensure_ascii=False),
                encoding="utf-8",
            )
            result = self.engine.run(
                replay_path,
                auto_expand=False,
                inject_regimes=False,
                apply_microstructure=False,
            )

        report = result.to_report()
        report["strategy"] = strategy_type.__name__
        write_report(report_path, report)
        return result

    def run_all(
        self,
        signals_path: Path,
        runtime_dir: Path,
    ) -> dict[str, BacktestResult]:
        rows = load_signals(signals_path)
        if not rows:
            raise ValueError("signals.json contains no replayable signals")
        rows = RegimeGenerator().generate(rows)
        rows = MarketMicrostructure(seed=self.microstructure_seed).generate(rows)
        write_price_series(runtime_dir / "price_series.json", rows)

        results: dict[str, BacktestResult] = {}
        for strategy_type, filename in STRATEGY_REPORTS:
            results[strategy_type.__name__] = self._run_strategy_rows(
                rows,
                strategy_type,
                runtime_dir / filename,
            )
        return results
