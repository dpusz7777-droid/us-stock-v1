"""Mean-reversion strategy for simulated realtime ticks."""

from __future__ import annotations

from collections import deque

from providers import MarketTick

from .base_strategy import BaseStrategy, StrategyResult


class MeanReversionStrategy(BaseStrategy):
    """Trade deviations from a rolling mean and otherwise hold."""

    def __init__(self, window: int = 5, tolerance: float = 0.08) -> None:
        self._prices: deque[float] = deque(maxlen=window)
        self._tolerance = tolerance

    def generate(self, tick: MarketTick) -> StrategyResult:
        price = float(tick["price"])
        if not self._prices:
            self._prices.append(price)
            return {"action": "HOLD", "score": 10}

        mean = sum(self._prices) / len(self._prices)
        deviation = (price - mean) / max(mean, 1.0)

        if deviation > self._tolerance:
            action = "SELL"
        elif deviation < -self._tolerance:
            action = "BUY"
        else:
            action = "HOLD"

        score = min(100, max(10, int(10 + abs(deviation) * 180)))
        self._prices.append(price)
        return {"action": action, "score": score}
