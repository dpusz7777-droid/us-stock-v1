"""Price momentum strategy for simulated realtime ticks."""

from __future__ import annotations

import random

from providers import MarketTick

from .base_strategy import BaseStrategy, StrategyResult


class MomentumStrategy(BaseStrategy):
    """Follow the direction of price changes with small random jitter."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()
        self._previous_price: float | None = None

    def generate(self, tick: MarketTick) -> StrategyResult:
        price = float(tick["price"])
        previous = self._previous_price
        self._previous_price = price

        if previous is None:
            return {"action": "HOLD", "score": self._rng.randint(30, 45)}

        # Small perturbation makes the synthetic trend less mechanically exact.
        adjusted_delta = price - previous + self._rng.uniform(-2.0, 2.0)
        if adjusted_delta > 0:
            action = "BUY"
        elif adjusted_delta < 0:
            action = "SELL"
        else:
            action = "HOLD"

        magnitude = abs(adjusted_delta) / max(previous, 1.0)
        score = min(100, max(30, int(30 + magnitude * 140)))
        return {"action": action, "score": score}
