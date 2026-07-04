"""Statistical robustness tests for completed strategy backtests."""

from __future__ import annotations

import math
import random
import statistics
from typing import Any


def _observations(
    equity_curve: list[dict[str, Any]],
    *,
    actions: list[str] | None = None,
    prices: list[float] | None = None,
) -> list[float]:
    curve_actions = actions or [
        str(point.get("action", "HOLD")) for point in equity_curve
    ]
    curve_prices = prices or [
        float(point.get("price", 0.0)) for point in equity_curve
    ]
    edges: list[float] = []
    for index, point in enumerate(equity_curve[:-1]):
        action = curve_actions[index]
        price = curve_prices[index]
        symbol = str(point.get("symbol", ""))
        if action not in {"BUY", "SELL"} or price <= 0:
            continue
        future_index = next(
            (
                candidate
                for candidate in range(index + 1, len(equity_curve))
                if str(equity_curve[candidate].get("symbol", "")) == symbol
            ),
            None,
        )
        if future_index is None:
            continue
        direction = 1.0 if action == "BUY" else -1.0
        edges.append(
            direction
            * (curve_prices[future_index] - price)
            / price
        )
    return edges


def _directional_alpha(edges: list[float]) -> float:
    if not edges:
        return -0.5
    return sum(edge > 0 for edge in edges) / len(edges) - 0.5


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def bootstrap_test(
    equity_curve: list[dict[str, Any]],
    samples: int = 100,
    seed: int = 101,
) -> dict[str, Any]:
    edges = _observations(equity_curve)
    rng = random.Random(seed)
    distribution = []
    for _ in range(samples):
        resampled = [rng.choice(edges) for _ in edges] if edges else []
        distribution.append(_directional_alpha(resampled))
    return {
        "samples": samples,
        "alpha_mean": round(statistics.mean(distribution), 6),
        "alpha_std": round(
            statistics.pstdev(distribution) if len(distribution) > 1 else 0.0,
            6,
        ),
        "confidence_interval": [
            round(_percentile(distribution, 0.025), 6),
            round(_percentile(distribution, 0.975), 6),
        ],
    }


def permutation_test(
    equity_curve: list[dict[str, Any]],
    permutations: int = 100,
    seed: int = 202,
) -> dict[str, Any]:
    observed = _directional_alpha(_observations(equity_curve))
    original_actions = [
        str(point.get("action", "HOLD")) for point in equity_curve
    ]
    rng = random.Random(seed)
    null_distribution = []
    for _ in range(permutations):
        shuffled = list(original_actions)
        rng.shuffle(shuffled)
        null_distribution.append(
            _directional_alpha(_observations(equity_curve, actions=shuffled))
        )
    extreme = sum(alpha >= observed for alpha in null_distribution)
    p_value = (extreme + 1) / (permutations + 1)
    return {
        "permutations": permutations,
        "observed_alpha": round(observed, 6),
        "null_alpha_mean": round(statistics.mean(null_distribution), 6),
        "p_value": round(p_value, 6),
    }


def noise_sensitivity_test(
    equity_curve: list[dict[str, Any]],
    noise_levels: tuple[float, ...] = (0.5, 1.0, 2.0),
    seed: int = 303,
) -> dict[str, Any]:
    original_prices = [
        float(point.get("price", 0.0)) for point in equity_curve
    ]
    results = []
    for index, noise_std in enumerate(noise_levels):
        rng = random.Random(seed + index)
        noisy_prices = [
            max(0.01, price + rng.gauss(0.0, noise_std))
            for price in original_prices
        ]
        alpha = _directional_alpha(
            _observations(equity_curve, prices=noisy_prices)
        )
        results.append({
            "noise_std": noise_std,
            "alpha": round(alpha, 6),
        })
    return {
        "levels": results,
        "stable": all(result["alpha"] > 0 for result in results),
    }


def run_statistical_tests(
    equity_curve: list[dict[str, Any]],
) -> dict[str, Any]:
    bootstrap = bootstrap_test(equity_curve)
    permutation = permutation_test(equity_curve)
    noise = noise_sensitivity_test(equity_curve)
    p_value = float(permutation["p_value"])
    if p_value < 0.05 and noise["stable"]:
        classification = "significant"
    elif p_value > 0.1:
        classification = "likely_noise"
    elif noise["stable"]:
        classification = "stable"
    else:
        classification = "unstable"
    return {
        "bootstrap": bootstrap,
        "permutation": permutation,
        "noise_sensitivity": noise,
        "alpha_mean": bootstrap["alpha_mean"],
        "alpha_std": bootstrap["alpha_std"],
        "alpha_p_value": permutation["p_value"],
        "classification": classification,
        "passed": classification in {"significant", "stable"},
    }
