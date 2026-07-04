#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Northstar v53 market-aware signal recalibration layer.

This module only adjusts signals.  It does not place or simulate trades.
"""

from __future__ import annotations

from typing import Any


ACTION_CONFIDENCE_THRESHOLD = 0.65


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def _portfolio_state(
    portfolio_engine: Any,
    market_data_provider: Any,
) -> tuple[set[str], float, float]:
    """Return held symbols, total exposure ratio, and cash ratio."""
    if portfolio_engine is None:
        return set(), 0.0, 1.0

    positions = getattr(portfolio_engine, "positions", {})
    held_symbols: set[str] = set()
    if isinstance(positions, dict):
        held_symbols = {
            str(symbol).upper()
            for symbol, quantity in positions.items()
            if float(quantity or 0.0) > 0.0
        }
    elif isinstance(positions, list):
        held_symbols = {
            str(position.get("symbol", "")).upper()
            for position in positions
            if isinstance(position, dict) and float(position.get("qty", 0.0) or 0.0) > 0.0
        }

    explicit_exposure = getattr(portfolio_engine, "total_exposure", None)
    explicit_cash = getattr(portfolio_engine, "cash_ratio", None)

    snapshot: dict[str, Any] = {}
    get_snapshot = getattr(portfolio_engine, "get_snapshot", None)
    if callable(get_snapshot):
        market_prices: dict[str, float] = {}
        for symbol in held_symbols:
            try:
                quote = market_data_provider.get_price(symbol)
                market_prices[symbol] = float(quote["price"])
            except (AttributeError, KeyError, TypeError, ValueError):
                continue
        try:
            snapshot = get_snapshot(market_prices)
        except TypeError:
            snapshot = get_snapshot()
        except Exception:
            snapshot = {}

    snapshot_positions = snapshot.get("positions", [])
    if not held_symbols and isinstance(snapshot_positions, list):
        held_symbols = {
            str(position.get("symbol", "")).upper()
            for position in snapshot_positions
            if isinstance(position, dict) and float(position.get("qty", 0.0) or 0.0) > 0.0
        }

    total_value = float(snapshot.get("total_value", 0.0) or 0.0)
    position_value = float(snapshot.get("position_value", 0.0) or 0.0)
    cash_value = float(
        snapshot.get("cash", getattr(portfolio_engine, "cash", 0.0)) or 0.0
    )

    if explicit_exposure is not None:
        total_exposure = _clamp(float(explicit_exposure))
    elif total_value > 0.0:
        total_exposure = _clamp(position_value / total_value)
    else:
        total_exposure = _clamp(
            float(getattr(portfolio_engine, "exposure", 0.0) or 0.0)
        )

    if explicit_cash is not None:
        cash_ratio = _clamp(float(explicit_cash))
    elif total_value > 0.0:
        cash_ratio = _clamp(cash_value / total_value)
    else:
        raw_cash = float(getattr(portfolio_engine, "cash", 1.0) or 0.0)
        cash_ratio = _clamp(raw_cash) if raw_cash <= 1.0 else 1.0

    return held_symbols, total_exposure, cash_ratio


def _market_context(market_data_provider: Any) -> dict[str, Any]:
    try:
        context = market_data_provider.get_market_context()
        return context if isinstance(context, dict) else {}
    except Exception:
        return {}


def _technical_features(
    market_data_provider: Any,
    symbol: str,
) -> dict[str, Any]:
    try:
        features = market_data_provider.get_technical_features(symbol)
        return features if isinstance(features, dict) else {}
    except Exception:
        return {}


def recalibrate_signals(
    signals,
    market_data_provider,
    portfolio_engine,
):
    """Recalibrate v51 signals using v52 features and v50 portfolio risk.

    Invalid or unavailable external data is treated neutrally so that this
    adjustment layer remains safe during market-data outages.
    """
    if not signals:
        return []

    context = _market_context(market_data_provider)
    market_regime = str(context.get("market_regime", "unknown")).lower()
    held_symbols, total_exposure, cash_ratio = _portfolio_state(
        portfolio_engine,
        market_data_provider,
    )

    recalibrated: list[dict[str, Any]] = []
    for source_signal in signals:
        signal = source_signal if isinstance(source_signal, dict) else {}
        symbol = str(signal.get("symbol", "")).strip().upper()
        original_action = str(signal.get("action", "HOLD")).upper()
        confidence = _clamp(float(signal.get("confidence", 0.0) or 0.0))
        position_sizing = _clamp(float(signal.get("position_sizing", 0.0) or 0.0))
        adjustments: list[str] = []

        features = _technical_features(market_data_provider, symbol)
        momentum = float(features.get("momentum", 0.2) or 0.0)
        volatility = float(features.get("volatility", 0.1) or 0.0)

        if original_action == "BUY":
            if momentum < 0.2:
                confidence -= 0.2
                adjustments.append("weak momentum confidence reduction")
            elif momentum > 0.7:
                confidence += 0.1
                adjustments.append("strong momentum confidence increase")

        if volatility > 0.25:
            position_sizing *= 0.7
            adjustments.append("high volatility reduction")
        elif volatility < 0.1:
            position_sizing *= 1.1
            adjustments.append("low volatility sizing increase")

        expected_regime = signal.get(
            "signal_expected_regime",
            signal.get("expected_regime", signal.get("market_regime")),
        )
        if (
            expected_regime is not None
            and market_regime != "unknown"
            and str(expected_regime).lower() != market_regime
        ):
            confidence *= 0.6
            adjustments.append("regime mismatch penalty")

        if original_action == "BUY" and total_exposure > 0.6:
            position_sizing *= 0.5
            adjustments.append("portfolio exposure cap")

        is_existing_position = symbol in held_symbols
        if is_existing_position and original_action == "SELL":
            confidence *= 1.2
            adjustments.append("existing position sell protection")
        elif is_existing_position and original_action == "BUY":
            position_sizing *= 0.5
            adjustments.append("existing position buy reduction")

        confidence = _clamp(confidence)
        position_sizing = _clamp(position_sizing)
        recalibrated_action = original_action

        if original_action == "BUY" and not is_existing_position and cash_ratio < 0.2:
            recalibrated_action = "HOLD"
            position_sizing = 0.0
            adjustments.append("insufficient cash suppresses new buy")
        elif (
            original_action in {"BUY", "SELL"}
            and confidence < ACTION_CONFIDENCE_THRESHOLD
        ):
            recalibrated_action = "HOLD"
            if original_action == "BUY":
                position_sizing = 0.0
            adjustments.append("confidence below action threshold")
        elif original_action != "BUY":
            position_sizing = 0.0

        recalibrated.append(
            {
                "symbol": symbol,
                "original_action": original_action,
                "recalibrated_action": recalibrated_action,
                "confidence": round(confidence, 4),
                "position_sizing": round(position_sizing, 4),
                "adjustments": adjustments,
            }
        )

    return recalibrated
