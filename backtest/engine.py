"""Read-only signal replay engine for B12."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .metrics import calculate_metrics
from .microstructure import MarketMicrostructure, write_price_series
from .regime_generator import RegimeGenerator, apply_regime_score_bias
from .report import write_report


@dataclass
class BacktestResult:
    equity_curve: list[dict[str, Any]]
    final_pnl: float
    metrics: dict[str, float | int]
    trades: list[dict[str, Any]]

    def to_report(self) -> dict[str, Any]:
        return {
            "equity_curve": self.equity_curve,
            "final_pnl": self.final_pnl,
            "metrics": self.metrics,
        }


def _cycle_sort_key(cycle_id: str) -> tuple[int, int | str]:
    return (0, int(cycle_id)) if cycle_id.isdigit() else (1, cycle_id)


def load_signals(path: Path) -> list[dict[str, Any]]:
    """Load current snapshot or a future list/history of signal cycles."""
    data = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(data, list):
        cycles = data
    elif isinstance(data, dict):
        history = data.get("cycles") or data.get("history")
        cycles = history if isinstance(history, list) else [data]
    else:
        raise ValueError("signals.json must contain an object or list")

    replay_rows: list[dict[str, Any]] = []
    for cycle in cycles:
        if not isinstance(cycle, dict):
            continue
        cycle_id = str(cycle.get("cycle_id", ""))
        signals = cycle.get("signals", [])
        if not cycle_id or not isinstance(signals, list):
            continue
        for signal in signals:
            if isinstance(signal, dict):
                replay_rows.append({"cycle_id": cycle_id, **signal})

    replay_rows.sort(key=lambda row: _cycle_sort_key(str(row["cycle_id"])))
    return replay_rows


_PRICE_FACTORS = (1.00, 0.96, 1.04, 0.93, 1.08, 0.98, 1.05, 0.91, 1.10, 0.95)


def expand_signal_sequence(
    rows: list[dict[str, Any]],
    minimum_size: int = 50,
    repeat_count: int = 10,
) -> list[dict[str, Any]]:
    """Create an internal, deterministic replay sequence for small inputs."""
    if len(rows) >= minimum_size:
        return [dict(row) for row in rows]

    expanded: list[dict[str, Any]] = []
    for repeat_index in range(repeat_count):
        for row in rows:
            item = dict(row)
            cycle_id = str(row["cycle_id"])
            if cycle_id.isdigit():
                item["cycle_id"] = str(
                    int(cycle_id) + repeat_index * 1000
                ).zfill(len(cycle_id))
            else:
                item["cycle_id"] = f"{cycle_id}-{repeat_index:02d}"

            timestamp = str(row.get("timestamp", ""))
            try:
                item["timestamp"] = (
                    datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    + timedelta(seconds=repeat_index)
                ).isoformat()
            except ValueError:
                item["timestamp"] = f"{timestamp}+{repeat_index}s"

            # A repeated single price cannot distinguish strategies. This
            # deterministic replay-only wave supplies market movement without
            # changing the source file.
            if "price" in item:
                item["price"] = round(
                    float(item["price"]) * _PRICE_FACTORS[repeat_index % len(_PRICE_FACTORS)],
                    2,
                )
            expanded.append(item)

    expanded.sort(key=lambda row: _cycle_sort_key(str(row["cycle_id"])))
    return expanded


def sliding_windows(
    rows: list[dict[str, Any]],
    window_size: int,
) -> list[list[dict[str, Any]]]:
    """Return overlapping replay windows in cycle order."""
    if window_size <= 0:
        raise ValueError("window_size must be positive")
    if len(rows) <= window_size:
        return [rows]
    return [
        rows[index:index + window_size]
        for index in range(len(rows) - window_size + 1)
    ]


class BacktestEngine:
    """Replay signals without writing to the live execution chain."""

    def __init__(
        self,
        initial_cash: float = 100_000.0,
        buy_fraction: float = 0.10,
    ) -> None:
        self.initial_cash = float(initial_cash)
        self.buy_fraction = float(buy_fraction)

    def run(
        self,
        signals_path: Path,
        report_path: Path | None = None,
        *,
        auto_expand: bool = True,
        inject_regimes: bool = True,
        apply_microstructure: bool = True,
        price_series_path: Path | None = None,
    ) -> BacktestResult:
        rows = load_signals(signals_path)
        if not rows:
            raise ValueError("signals.json contains no replayable signals")
        if inject_regimes:
            rows = RegimeGenerator().generate(rows)
        elif auto_expand:
            rows = expand_signal_sequence(rows)
        if apply_microstructure:
            rows = MarketMicrostructure().generate(rows)
        if price_series_path is None and report_path is not None:
            price_series_path = report_path.parent / "price_series.json"
        if price_series_path is not None:
            write_price_series(price_series_path, rows)

        cash = self.initial_cash
        positions: dict[str, dict[str, float]] = {}
        latest_prices: dict[str, float] = {}
        trades: list[dict[str, Any]] = []
        equity_curve: list[dict[str, Any]] = []

        for raw_row in rows:
            row = apply_regime_score_bias(raw_row)
            cycle_id = str(row["cycle_id"])
            symbol = str(row.get("symbol", ""))
            action = str(row.get("action", "HOLD")).upper()
            price = float(row.get("price", 0.0))
            if not symbol or price <= 0:
                raise ValueError(f"cycle {cycle_id} has invalid symbol or price")
            latest_prices[symbol] = price

            if action == "BUY" and cash > 0:
                amount = cash * self.buy_fraction
                quantity = amount / price
                position = positions.setdefault(symbol, {"quantity": 0.0, "cost": 0.0})
                position["quantity"] += quantity
                position["cost"] += amount
                cash -= amount
                trades.append({
                    "cycle_id": cycle_id,
                    "symbol": symbol,
                    "action": "BUY",
                    "price": price,
                    "quantity": quantity,
                    "amount": amount,
                    "regime": str(row.get("regime", "unclassified")),
                })
            elif action == "SELL" and symbol in positions:
                position = positions.pop(symbol)
                proceeds = position["quantity"] * price
                pnl = proceeds - position["cost"]
                cash += proceeds
                trades.append({
                    "cycle_id": cycle_id,
                    "symbol": symbol,
                    "action": "SELL",
                    "price": price,
                    "quantity": position["quantity"],
                    "amount": proceeds,
                    "pnl": pnl,
                    "regime": str(row.get("regime", "unclassified")),
                })

            market_value = sum(
                position["quantity"] * latest_prices.get(held_symbol, price)
                for held_symbol, position in positions.items()
            )
            total_position = sum(position["quantity"] for position in positions.values())
            equity = cash + market_value
            point = {
                "cycle_id": cycle_id,
                "symbol": symbol,
                "regime": str(row.get("regime", "unclassified")),
                "action": action,
                "price": round(price, 2),
                "cash": round(cash, 2),
                "position": round(total_position, 6),
                "equity": round(equity, 2),
                "score": int(row.get("score", 0)),
            }
            equity_curve.append(point)
            print(
                f"{cycle_id} {action} cash={cash:.2f} "
                f"position={total_position:.6f} equity={equity:.2f}",
                flush=True,
            )

        metrics = calculate_metrics(equity_curve, trades, self.initial_cash)
        final_pnl = round(float(equity_curve[-1]["equity"]) - self.initial_cash, 2)
        result = BacktestResult(equity_curve, final_pnl, metrics, trades)
        if report_path is not None:
            write_report(report_path, result.to_report())
        return result
