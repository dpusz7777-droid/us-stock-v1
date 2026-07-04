#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Northstar backend data loop.

Each iteration reads the real portfolio, obtains real price results, evaluates
signals, updates the persistent simulator/equity curve, refreshes strategy
feedback, and writes the three runtime JSON files.
"""

from __future__ import annotations

import json
import math
import os
import socket
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).parent.parent
TRADE_HIST_PATH = PROJECT_ROOT / "northstar" / "data" / "trade_history.json"
EQUITY_CURVE_PATH = PROJECT_ROOT / "northstar" / "data" / "equity_curve.json"
SYSTEM_STATE_PATH = PROJECT_ROOT / "northstar" / "data" / "system_state.json"
BACKEND_LOG_PATH = PROJECT_ROOT / "logs" / "backend.log"


def _read_json(path: Path) -> Any:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, data: Any) -> None:
    """Atomically write strict JSON; NaN and Infinity are rejected."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(
                data,
                handle,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def _json_number(value: Any) -> float | None:
    """Convert Decimal-like values to finite JSON numbers."""
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"non-finite numeric value: {value!r}")
    return round(number, 2)


def _price_snapshot(price_results: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Serialize the exact iteration snapshot without secrets or provider objects."""
    snapshot: dict[str, dict[str, Any]] = {}
    for symbol, result in sorted(price_results.items()):
        snapshot[symbol] = {
            "latest_price": _json_number(getattr(result, "price", None)),
            "currency": getattr(result, "currency", None),
            "price_as_of": getattr(result, "price_as_of", None),
            "source": getattr(result, "source", None),
            "status": getattr(result, "status", None),
            "error_code": getattr(result, "error_code", None),
            "error_message": getattr(result, "error_message", None),
            "cached": bool(getattr(result, "cached", False)),
        }
    return snapshot


class BackendEngine:
    """Continuous backend engine with one persistent simulation session."""

    def __init__(self, interval: float = 3.0) -> None:
        if interval <= 0:
            raise ValueError("interval must be positive")
        self._interval = interval
        self._iteration = 0
        from northstar.backtest.simulator import Simulator

        self._simulator = Simulator()

    def _run_once(self) -> None:
        """Run one complete backend pipeline iteration."""
        self._iteration += 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        from northstar.data.portfolio_state import PortfolioState

        portfolio_state = PortfolioState()
        holdings = portfolio_state.summary()
        symbols = [position.symbol for position in holdings.positions]

        from northstar.core.signal_engine import SignalEngine

        signal_engine = SignalEngine()
        price_results = (
            signal_engine.get_price_results(symbols) if symbols else {}
        )
        summary = portfolio_state.summary(price_results)
        signals = (
            signal_engine.generate(symbols, price_results=price_results)
            if symbols
            else []
        )
        positions_by_symbol = {
            position.symbol: position for position in summary.positions
        }

        simulator = self._simulator
        for signal in signals[:3]:
            position = positions_by_symbol.get(signal.symbol)
            if position is None or position.current_price is None:
                continue
            price = float(position.current_price)
            quantity = int(position.shares) if position.shares > 0 else 10
            action = signal.signal_type.value
            if action in {"BUY", "INCREASE"}:
                simulator.execute(
                    signal.symbol, "buy", price, quantity, signal.reason
                )
            elif action in {"SELL", "REDUCE"}:
                simulator.execute(
                    signal.symbol,
                    "sell",
                    price,
                    max(1, quantity // 2),
                    signal.reason,
                )

        simulated = simulator.portfolio()
        simulator_initialized = simulated.trade_count > 0
        simulator_value = (
            _json_number(simulated.total_equity)
            if simulator_initialized
            else None
        )
        simulator_pnl = (
            _json_number(simulated.total_pnl)
            if simulator_initialized
            else None
        )
        simulator_initial_capital = (
            round(simulator_value - simulator_pnl, 2)
            if simulator_value is not None and simulator_pnl is not None
            else None
        )
        if simulator_initialized:
            simulator.record_equity_snapshot(
                timestamp=now,
                position_count=summary.position_count,
            )
            simulator.save_equity_curve()
        simulator.save_trade_history()

        from northstar.backtest.evaluator import Evaluator

        feedback = Evaluator().compute_and_save_feedback()

        _write_json(
            SYSTEM_STATE_PATH,
            {
                "last_run_time": now,
                "system_health": "OK",
                "last_run_status": "running",
                "iteration": self._iteration,
                "position_count": summary.position_count,
                "cash": _json_number(summary.cash),
                "position_market_value": _json_number(
                    summary.total_market_value
                ),
                "total_equity": _json_number(summary.total_equity),
                "equity": _json_number(summary.total_equity),
                "unrealized_pnl": _json_number(summary.total_pnl),
                "valuation_status": summary.valuation_status,
                "valued_position_count": summary.valued_position_count,
                "total_position_count": summary.total_position_count,
                "missing_price_symbols": list(summary.missing_price_symbols),
                "price_as_of": summary.price_as_of,
                "price_snapshot": _price_snapshot(price_results),
                "signals_count": len(signals),
                "simulator_initialized": simulator_initialized,
                "simulator_initial_capital": simulator_initial_capital,
                "simulator_value": simulator_value,
                "simulator_pnl": simulator_pnl,
                "simulator_trade_count": simulated.trade_count,
                "strategy_score": feedback["strategy_score"],
                "market_regime": signal_engine.get_regime(),
            },
        )

        sys.stdout.write(
            f"[{now}] Iteration {self._iteration}: "
            f"signals={len(signals)}, valuation={summary.valuation_status}, "
            f"total_equity={_json_number(summary.total_equity)}\n"
        )
        sys.stdout.flush()

    def run_forever(self) -> None:
        """Run until interrupted; retry only bounded, demonstrably transient errors."""
        sys.stdout.write(f"Backend engine started (interval={self._interval}s)\n")
        sys.stdout.flush()
        recoverable_failures = 0

        while True:
            try:
                self._run_once()
                recoverable_failures = 0
            except Exception as error:
                if _is_recoverable(error) and recoverable_failures < 2:
                    recoverable_failures += 1
                    sys.stderr.write(
                        f"[WARN] recoverable failure {recoverable_failures}/2: "
                        f"{type(error).__name__}: {error}\n"
                    )
                    sys.stderr.flush()
                    time.sleep(self._interval)
                    continue
                _report_fatal(error)
                raise SystemExit(1) from error
            time.sleep(self._interval)


def _is_recoverable(error: Exception) -> bool:
    """Identify only network timeouts and Windows sharing violations."""
    if isinstance(error, (TimeoutError, ConnectionError, socket.timeout)):
        return True
    return isinstance(error, OSError) and getattr(error, "winerror", None) in {32, 33}


def _report_fatal(error: Exception) -> None:
    """Print one complete traceback and persist it for standalone execution."""
    message = (
        f"\n[FATAL] non-recoverable backend error: "
        f"{type(error).__name__}: {error}\n"
    )
    sys.stderr.write(message)
    traceback.print_exc(file=sys.stderr)
    sys.stderr.flush()

    # launch.py captures the combined stream into this same file. Avoid duplicates.
    if os.environ.get("NORTHSTAR_LAUNCHED") == "1":
        return
    BACKEND_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(BACKEND_LOG_PATH, "a", encoding="utf-8") as handle:
        handle.write(message)
        traceback.print_exc(file=handle)


def _precheck_dependencies() -> None:
    """Import and validate the complete backend dependency chain."""
    modules = [
        "northstar.core.strategy_feedback",
        "northstar.core.market_regime",
        "northstar.core.signal_engine",
        "northstar.backtest.equity_curve",
        "northstar.backtest.simulator",
        "northstar.backtest.evaluator",
        "northstar.data.portfolio_state",
        "northstar.data.trade_history",
    ]
    for module_name in modules:
        __import__(module_name, fromlist=[""])

    from northstar.core.strategy_feedback import (
        compute_adjusted_weight,
        compute_strategy_score,
        load_feedback,
        save_feedback,
    )

    for function in (
        load_feedback,
        save_feedback,
        compute_adjusted_weight,
        compute_strategy_score,
    ):
        if not callable(function):
            raise TypeError(f"{function.__name__} is not callable")


def run_backend() -> None:
    """Start the backend, exiting nonzero after any deterministic startup error."""
    try:
        _precheck_dependencies()
        BackendEngine(interval=3.0).run_forever()
    except SystemExit:
        raise
    except Exception as error:
        _report_fatal(error)
        raise SystemExit(1) from error


if __name__ == "__main__":
    run_backend()
