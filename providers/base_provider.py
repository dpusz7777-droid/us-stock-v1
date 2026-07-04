"""Common interface for realtime signal providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypedDict


class MarketTick(TypedDict):
    """Provider-neutral market data record."""

    symbol: str
    price: float
    volume: int
    timestamp: str
    source: str


class SignalProvider(ABC):
    """Source of market ticks consumed by realtime_signal_worker."""

    @property
    @abstractmethod
    def source(self) -> str:
        """Stable source name written to runtime/signals.json."""

    @abstractmethod
    def next_tick(self) -> MarketTick:
        """Return the next provider-neutral market tick."""
