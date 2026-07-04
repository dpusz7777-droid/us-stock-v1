"""Performance metrics for the independent B12 backtest engine."""

from __future__ import annotations

import math
from typing import Any


def calculate_metrics(
    equity_curve: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    initial_cash: float,
) -> dict[str, float | int]:
    """Calculate total return, win rate, drawdown, and trade count."""
    equities = [float(point["equity"]) for point in equity_curve]
    final_equity = equities[-1] if equities else initial_cash
    total_return = (final_equity - initial_cash) / initial_cash

    peak = initial_cash
    max_drawdown = 0.0
    for equity in equities:
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)

    closed_trades = [trade for trade in trades if trade["action"] == "SELL"]
    realized_pnls = [float(trade.get("pnl", 0.0)) for trade in closed_trades]
    wins = sum(pnl > 0 for pnl in realized_pnls)
    win_rate = wins / len(closed_trades) if closed_trades else 0.0
    total_realized_profit = sum(realized_pnls)
    avg_profit_per_trade = (
        total_realized_profit / len(trades) if trades else 0.0
    )
    win_sum = sum(pnl for pnl in realized_pnls if pnl > 0)
    loss_sum = abs(sum(pnl for pnl in realized_pnls if pnl < 0))
    profit_factor = win_sum / max(loss_sum, 1e-12) if win_sum else 0.0

    regime_returns: dict[str, float] = {}
    previous_equity = initial_cash
    for point in equity_curve:
        regime = str(point.get("regime", "unclassified"))
        equity = float(point["equity"])
        cycle_return = (
            (equity - previous_equity) / previous_equity
            if previous_equity
            else 0.0
        )
        regime_returns[regime] = regime_returns.get(regime, 0.0) + cycle_return
        previous_equity = equity

    performance_by_regime: dict[str, dict[str, float | int]] = {}
    regimes = set(regime_returns) | {
        str(trade.get("regime", "unclassified")) for trade in trades
    }
    for regime in sorted(regimes):
        regime_trades = [
            trade for trade in trades
            if str(trade.get("regime", "unclassified")) == regime
        ]
        regime_closed = [
            float(trade.get("pnl", 0.0))
            for trade in regime_trades
            if trade["action"] == "SELL"
        ]
        regime_wins = sum(pnl > 0 for pnl in regime_closed)
        performance_by_regime[regime] = {
            "return": round(regime_returns.get(regime, 0.0), 6),
            "win_rate": round(
                regime_wins / len(regime_closed) if regime_closed else 0.0,
                6,
            ),
            "trade_count": len(regime_trades),
        }

    prediction_edges: list[float] = []
    correct_predictions = 0
    future_price_by_symbol: dict[str, float] = {}
    for point in reversed(equity_curve):
        symbol = str(point.get("symbol", ""))
        action = str(point.get("action", "HOLD"))
        price = float(point.get("price", 0.0))
        future_price = future_price_by_symbol.get(symbol)
        if action in {"BUY", "SELL"} and future_price is not None and price > 0:
            direction = 1.0 if action == "BUY" else -1.0
            edge = direction * (future_price - price) / price
            prediction_edges.append(edge)
            correct_predictions += edge > 0
        if symbol:
            future_price_by_symbol[symbol] = price

    signal_accuracy = (
        correct_predictions / len(prediction_edges)
        if prediction_edges
        else 0.0
    )
    edge_per_trade = (
        sum(prediction_edges) / len(prediction_edges)
        if prediction_edges
        else 0.0
    )
    correct_count = sum(edge > 0 for edge in prediction_edges)
    prediction_count = len(prediction_edges)
    alpha_mean = signal_accuracy - 0.5 if prediction_count else -0.5
    alpha_std = (
        math.sqrt(signal_accuracy * (1 - signal_accuracy) / prediction_count)
        if prediction_count
        else 0.0
    )
    alpha_p_value = (
        sum(
            math.comb(prediction_count, wins)
            for wins in range(correct_count, prediction_count + 1)
        )
        / (2 ** prediction_count)
        if prediction_count
        else 1.0
    )

    return {
        "total_return": round(total_return, 6),
        "win_rate": round(win_rate, 6),
        "max_drawdown": round(max_drawdown, 6),
        "trade_count": len(trades),
        "avg_profit_per_trade": round(avg_profit_per_trade, 6),
        "profit_factor": round(profit_factor, 6),
        "regime_return_breakdown": {
            regime: round(value, 6)
            for regime, value in sorted(regime_returns.items())
        },
        "strategy_performance_by_regime": performance_by_regime,
        "signal_accuracy": round(signal_accuracy, 6),
        "edge_per_trade": round(edge_per_trade, 6),
        "alpha_mean": round(alpha_mean, 6),
        "alpha_std": round(alpha_std, 6),
        "alpha_p_value": round(alpha_p_value, 6),
    }
