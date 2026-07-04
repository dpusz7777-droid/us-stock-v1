# -*- coding: utf-8 -*-
"""Tests for the Northstar v53 signal recalibration layer."""

from __future__ import annotations

import unittest

from northstar.engine.signal_recalibration import recalibrate_signals


class FakeMarketDataProvider:
    def __init__(
        self,
        momentum: float = 0.5,
        volatility: float = 0.15,
        regime: str = "bull",
    ) -> None:
        self.momentum = momentum
        self.volatility = volatility
        self.regime = regime

    def get_price(self, symbol: str) -> dict:
        return {"symbol": symbol, "price": 100.0}

    def get_technical_features(self, symbol: str) -> dict:
        return {
            "momentum": self.momentum,
            "volatility": self.volatility,
            "trend": "up",
        }

    def get_market_context(self) -> dict:
        return {"market_regime": self.regime}


class FakePortfolioEngine:
    def __init__(
        self,
        positions: dict[str, float] | None = None,
        exposure: float = 0.2,
        cash_ratio: float = 0.8,
    ) -> None:
        self.positions = positions or {}
        self.total_exposure = exposure
        self.cash_ratio = cash_ratio

    def get_snapshot(self, market_prices=None) -> dict:
        return {
            "cash": self.cash_ratio * 10_000,
            "position_value": self.total_exposure * 10_000,
            "total_value": 10_000,
            "positions": [
                {"symbol": symbol, "qty": quantity}
                for symbol, quantity in self.positions.items()
            ],
        }


def buy_signal(**overrides) -> dict:
    signal = {
        "symbol": "NVDA",
        "action": "BUY",
        "confidence": 0.8,
        "position_sizing": 0.2,
        "strategy_source": "momentum_regime_aware_v2",
        "expected_regime": "bull",
    }
    signal.update(overrides)
    return signal


class TestSignalRecalibration(unittest.TestCase):
    def test_confidence_adjustment_works(self) -> None:
        provider = FakeMarketDataProvider(momentum=0.1)

        result = recalibrate_signals(
            [buy_signal()],
            provider,
            FakePortfolioEngine(),
        )

        self.assertEqual(result[0]["confidence"], 0.6)
        self.assertEqual(result[0]["recalibrated_action"], "HOLD")
        self.assertIn("weak momentum confidence reduction", result[0]["adjustments"])

    def test_volatility_reduces_position_size(self) -> None:
        provider = FakeMarketDataProvider(volatility=0.3)

        result = recalibrate_signals(
            [buy_signal()],
            provider,
            FakePortfolioEngine(),
        )

        self.assertEqual(result[0]["position_sizing"], 0.14)
        self.assertIn("high volatility reduction", result[0]["adjustments"])

    def test_regime_mismatch_lowers_signal(self) -> None:
        provider = FakeMarketDataProvider(regime="bear")

        result = recalibrate_signals(
            [buy_signal(expected_regime="bull")],
            provider,
            FakePortfolioEngine(),
        )

        self.assertEqual(result[0]["confidence"], 0.48)
        self.assertEqual(result[0]["recalibrated_action"], "HOLD")
        self.assertIn("regime mismatch penalty", result[0]["adjustments"])

    def test_portfolio_exposure_cap_works(self) -> None:
        result = recalibrate_signals(
            [buy_signal()],
            FakeMarketDataProvider(),
            FakePortfolioEngine(exposure=0.7),
        )

        self.assertEqual(result[0]["position_sizing"], 0.1)
        self.assertIn("portfolio exposure cap", result[0]["adjustments"])

    def test_existing_position_modifies_signal(self) -> None:
        portfolio = FakePortfolioEngine(positions={"NVDA": 10})
        signals = [
            buy_signal(),
            buy_signal(action="SELL", position_sizing=0.0, confidence=0.7),
        ]

        result = recalibrate_signals(
            signals,
            FakeMarketDataProvider(),
            portfolio,
        )

        self.assertEqual(result[0]["position_sizing"], 0.1)
        self.assertIn("existing position buy reduction", result[0]["adjustments"])
        self.assertEqual(result[1]["confidence"], 0.84)
        self.assertEqual(result[1]["recalibrated_action"], "SELL")

    def test_low_cash_suppresses_new_buy(self) -> None:
        result = recalibrate_signals(
            [buy_signal()],
            FakeMarketDataProvider(),
            FakePortfolioEngine(cash_ratio=0.1),
        )

        self.assertEqual(result[0]["recalibrated_action"], "HOLD")
        self.assertEqual(result[0]["position_sizing"], 0.0)

    def test_empty_input_safe(self) -> None:
        self.assertEqual(
            recalibrate_signals(
                [],
                FakeMarketDataProvider(),
                FakePortfolioEngine(),
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
