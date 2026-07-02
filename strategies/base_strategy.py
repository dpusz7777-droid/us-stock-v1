"""Common interface for MarketTick-based strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypedDict

from providers import MarketTick


class StrategyResult(TypedDict):
    action: str
    score: int


class BaseStrategy(ABC):
    """Convert a MarketTick into one strategy opinion."""

    @abstractmethod
    def generate(self, tick: MarketTick) -> StrategyResult:
        """Return an action (BUY/SELL/HOLD) and integer score."""
