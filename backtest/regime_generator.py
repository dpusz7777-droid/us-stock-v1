"""Deterministic market-regime injection for backtest-only replay data."""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta
from typing import Any

REGIMES = ("trending_up", "trending_down", "sideways")


class RegimeGenerator:
    """Generate structured price paths without changing source signals."""

    def __init__(
        self,
        block_size: int = 20,
        minimum_cycles: int = 60,
        seed: int = 42,
    ) -> None:
        self.block_size = block_size
        self.minimum_cycles = minimum_cycles
        self._rng = random.Random(seed)

    def _regime_order(self, block_count: int) -> list[str]:
        first_pass = list(REGIMES)
        self._rng.shuffle(first_pass)
        order = first_pass[:block_count]
        while len(order) < block_count:
            choices = [regime for regime in REGIMES if regime != order[-1]]
            order.append(self._rng.choice(choices))
        return order

    def generate(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not rows:
            return []

        target_size = max(self.minimum_cycles, len(rows))
        block_count = math.ceil(target_size / self.block_size)
        regimes = self._regime_order(block_count)
        base_cycle = str(rows[0].get("cycle_id", "000000"))
        cycle_width = len(base_cycle)
        base_cycle_number = int(base_cycle) if base_cycle.isdigit() else 0
        price = float(rows[0].get("price", 100.0))
        block_anchor = price
        generated: list[dict[str, Any]] = []

        for index in range(target_size):
            item = dict(rows[index % len(rows)])
            block_index = index // self.block_size
            offset = index % self.block_size
            regime = regimes[block_index]
            if offset == 0:
                block_anchor = price

            if regime == "trending_up":
                price *= 1.006 + self._rng.uniform(-0.0015, 0.0015)
            elif regime == "trending_down":
                price *= 0.994 + self._rng.uniform(-0.0015, 0.0015)
            else:
                price = block_anchor * (
                    1.0 + 0.12 * math.sin(offset * math.pi / 2)
                )

            item["price"] = round(max(price, 1.0), 2)
            item["regime"] = regime
            if base_cycle.isdigit():
                item["cycle_id"] = str(base_cycle_number + index).zfill(cycle_width)
            else:
                item["cycle_id"] = f"{base_cycle}-R{index:04d}"

            timestamp = str(rows[0].get("timestamp", ""))
            try:
                item["timestamp"] = (
                    datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    + timedelta(seconds=index)
                ).isoformat()
            except ValueError:
                item["timestamp"] = f"{timestamp}+{index}s"
            generated.append(item)

        return generated


def apply_regime_score_bias(row: dict[str, Any]) -> dict[str, Any]:
    """Apply B14 score bias to one replay signal."""
    adjusted = dict(row)
    action = str(adjusted.get("action", "HOLD")).upper()
    regime = str(adjusted.get("regime", "sideways"))
    score = int(adjusted.get("score", 0))

    if regime == "trending_up":
        score += 20 if action == "BUY" else -10 if action == "SELL" else 0
    elif regime == "trending_down":
        score += 20 if action == "SELL" else -10 if action == "BUY" else 0
    elif regime == "sideways" and action == "HOLD":
        score += 15

    adjusted["score"] = max(0, min(100, score))
    return adjusted
