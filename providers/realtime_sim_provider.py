"""Offline market-tick simulation implemented as a SignalProvider."""

from __future__ import annotations

import random
from datetime import datetime, timezone

from .base_provider import MarketTick, SignalProvider

SYMBOLS = ("AAPL", "MSFT", "NVDA", "TSLA", "AMZN")


class RealtimeSimProvider(SignalProvider):
    """Generate realistic market-shaped data without network access."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()
        self._last_symbol: str | None = None
        self._last_price: float | None = None
        self._last_volume: int | None = None

    @property
    def source(self) -> str:
        return "realtime_sim"

    def next_tick(self) -> MarketTick:
        symbol_choices = [symbol for symbol in SYMBOLS if symbol != self._last_symbol]
        symbol = self._rng.choice(symbol_choices)

        price = round(self._rng.uniform(100.0, 300.0), 2)
        while price == self._last_price:
            price = round(self._rng.uniform(100.0, 300.0), 2)

        volume = self._rng.randint(1_000, 100_000)
        while volume == self._last_volume:
            volume = self._rng.randint(1_000, 100_000)

        self._last_symbol = symbol
        self._last_price = price
        self._last_volume = volume

        return {
            "symbol": symbol,
            "price": price,
            "volume": volume,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": self.source,
        }
