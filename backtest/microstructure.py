"""Market microstructure noise and impact for backtest price generation."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any


class MarketMicrostructure:
    """Apply trend, regime bias, Gaussian noise, and rare shocks."""

    def __init__(
        self,
        seed: int = 43,
        shock_probability: float = 0.01,
    ) -> None:
        self._rng = random.Random(seed)
        self.shock_probability = shock_probability

    def generate(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not rows:
            return []

        previous_price = float(rows[0].get("price", 100.0))
        generated: list[dict[str, Any]] = []
        regime_biases = {
            "trending_up": 0.40,
            "trending_down": -0.40,
            "sideways": 0.0,
        }

        for row in rows:
            item = dict(row)
            target_price = float(row.get("price", previous_price))
            regime = str(row.get("regime"))
            # Preserve enough of the sideways mean-reversion wave to remain
            # detectable while trend regimes stay probabilistic under noise.
            trend_strength = 0.75 if regime == "sideways" else 0.35
            trend = (target_price - previous_price) * trend_strength
            regime_bias = regime_biases.get(regime, 0.0)
            noise_std = self._rng.uniform(0.5, 1.5)
            noise = self._rng.gauss(0.0, noise_std)
            shock = 0.0
            if self._rng.random() < self.shock_probability:
                shock = self._rng.gauss(0.0, 8.0)

            price = max(
                1.0,
                previous_price + trend + regime_bias + noise + shock,
            )
            item["price"] = round(price, 2)
            item["microstructure"] = {
                "trend": round(trend, 6),
                "regime_bias": regime_bias,
                "noise": round(noise, 6),
                "noise_std": round(noise_std, 6),
                "shock": round(shock, 6),
                "shock_event": shock != 0.0,
            }
            generated.append(item)
            previous_price = price

        return generated


def write_price_series(path: Path, rows: list[dict[str, Any]]) -> None:
    """Atomically persist the generated backtest-only price series."""
    series = [{
        "cycle_id": row.get("cycle_id"),
        "symbol": row.get("symbol"),
        "timestamp": row.get("timestamp"),
        "regime": row.get("regime"),
        "price": row.get("price"),
        "microstructure": row.get("microstructure", {}),
    } for row in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps(series, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)
