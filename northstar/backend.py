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

        from decimal import Decimal

        from northstar.data.market_data_provider import MarketDataProvider
        from northstar.data.market_snapshot import build_market_snapshot
        from northstar.data.portfolio_snapshot import (
            load_portfolio_state,
            requested_market_symbols,
            value_portfolio,
        )
        from northstar.reports.daily_decision_report import load_watchlist

        portfolio_state = load_portfolio_state()
        symbols = list(portfolio_state.position_symbols)
        requested = requested_market_symbols(load_watchlist(), portfolio_state)
        market_snapshot = build_market_snapshot(requested, MarketDataProvider())
        portfolio_snapshot = value_portfolio(portfolio_state, market_snapshot)

        from northstar.core.signal_engine import SignalEngine

        from price_provider_v2 import (
            PRICE_STATUS_OK,
            PRICE_STATUS_PROVIDER_ERROR,
            PriceResultV2,
        )

        signal_engine = SignalEngine(price_provider=object())
        price_results = {
            symbol: PriceResultV2(
                symbol=symbol,
                price=Decimal(str(market_snapshot.quote(symbol).price))
                if market_snapshot.quote(symbol).decision_eligible
                else None,
                currency=market_snapshot.quote(symbol).currency,
                market_time=market_snapshot.quote(symbol).as_of,
                source=market_snapshot.quote(symbol).source,
                status=PRICE_STATUS_OK
                if market_snapshot.quote(symbol).decision_eligible
                else PRICE_STATUS_PROVIDER_ERROR,
                error_code=market_snapshot.quote(symbol).error_code,
                error_message=market_snapshot.quote(symbol).error_message,
            )
            for symbol in symbols
        }
        signals = (
            signal_engine.generate(symbols, price_results=price_results)
            if symbols
            else []
        )
        positions_by_symbol = {
            position.symbol: position for position in portfolio_snapshot.positions
        }

        simulator = self._simulator
        for signal in signals[:3]:
            position = positions_by_symbol.get(signal.symbol)
            if position is None or position.current_price is None:
                continue
            price = float(position.current_price)
            quantity = int(position.quantity) if position.quantity > 0 else 10
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
                position_count=len(portfolio_snapshot.positions),
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
                "position_count": len(portfolio_snapshot.positions),
                "cash": _json_number(portfolio_snapshot.cash),
                "position_market_value": _json_number(
                    portfolio_snapshot.total_market_value
                ),
                "total_equity": _json_number(portfolio_snapshot.total_asset_value),
                "equity": _json_number(portfolio_snapshot.total_asset_value),
                "unrealized_pnl": _json_number(portfolio_snapshot.total_unrealized_pnl),
                "valuation_status": portfolio_snapshot.valuation_status,
                "valued_position_count": sum(
                    1 for position in portfolio_snapshot.positions
                    if position.valuation_status == "complete"
                ),
                "total_position_count": len(portfolio_snapshot.positions),
                "missing_price_symbols": list(portfolio_snapshot.missing_symbols),
                "price_as_of": max(
                    (
                        position.price_as_of
                        for position in portfolio_snapshot.positions
                        if position.price_as_of
                    ),
                    default=None,
                ),
                "market_snapshot_id": market_snapshot.snapshot_id,
                "portfolio_snapshot_id": portfolio_snapshot.portfolio_snapshot_id,
                "portfolio_snapshot": portfolio_snapshot.to_dict(),
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
            f"signals={len(signals)}, valuation={portfolio_snapshot.valuation_status}, "
            f"total_equity={_json_number(portfolio_snapshot.total_asset_value)}\n"
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
