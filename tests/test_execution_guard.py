# -*- coding: utf-8 -*-
"""Tests for the Northstar v54 execution guard."""

from __future__ import annotations

import unittest

from northstar.engine.execution_guard import guard_execution


def signal(**overrides) -> dict:
    value = {
        "symbol": "NVDA",
        "recalibrated_action": "BUY",
        "confidence": 0.8,
        "position_sizing": 0.2,
        "strategy_source": "defensive_regime_aware_v2",
    }
    value.update(overrides)
    return value


class TestExecutionGuard(unittest.TestCase):
    def test_volatility_blocks_buy(self) -> None:
        result = guard_execution(
            [signal()],
            {"exposure": 0.2},
            {"volatility": 0.31, "market_regime": "bull"},
            {},
        )

        self.assertEqual(result[0]["final_action"], "HOLD")
        self.assertIn("high volatility market", result[0]["blocked_reasons"])

    def test_governance_lock_forces_hold(self) -> None:
        result = guard_execution(
            [signal(recalibrated_action="SELL")],
            {},
            {},
            {"locked_strategies": ["NVDA"]},
        )

        self.assertEqual(result[0]["final_action"], "HOLD")
        self.assertIn("governance lock override", result[0]["blocked_reasons"])

    def test_v48_strategy_lock_forces_hold(self) -> None:
        result = guard_execution(
            [signal(strategy_source="momentum_regime_aware_v2")],
            {},
            {},
            {"locked_strategies": [{"strategy": "momentum"}]},
        )

        self.assertEqual(result[0]["final_action"], "HOLD")

    def test_exposure_cap_works(self) -> None:
        result = guard_execution(
            [signal()],
            {"position_value": 7000, "total_value": 10000, "cash": 3000},
            {},
            {},
        )

        self.assertEqual(result[0]["final_action"], "HOLD")
        self.assertIn("exposure cap reached", result[0]["blocked_reasons"])

    def test_confidence_floor_works(self) -> None:
        result = guard_execution(
            [signal(confidence=0.54)],
            {},
            {},
            {},
        )

        self.assertEqual(result[0]["final_action"], "HOLD")
        self.assertIn(
            "confidence below execution floor",
            result[0]["blocked_reasons"],
        )

    def test_bear_regime_reduces_buy_size(self) -> None:
        result = guard_execution(
            [signal()],
            {},
            {"market_regime": "bear"},
            {},
        )

        self.assertEqual(result[0]["final_action"], "BUY")
        self.assertEqual(result[0]["position_sizing"], 0.1)

    def test_sideways_regime_suppresses_momentum(self) -> None:
        result = guard_execution(
            [signal(strategy_source="momentum_regime_aware_v2")],
            {},
            {"market_regime": "sideways"},
            {},
        )

        self.assertEqual(result[0]["final_action"], "HOLD")
        self.assertIn(
            "sideways regime suppresses high-risk strategy",
            result[0]["blocked_reasons"],
        )

    def test_drift_protection_works_but_allows_sell(self) -> None:
        result = guard_execution(
            [
                signal(),
                signal(symbol="AAPL", recalibrated_action="SELL"),
            ],
            {},
            {},
            {"drift_detected": True},
        )

        self.assertEqual(result[0]["final_action"], "HOLD")
        self.assertEqual(result[1]["final_action"], "SELL")
        self.assertIn("governance drift protection", result[0]["blocked_reasons"])

    def test_action_field_is_supported(self) -> None:
        basic_signal = {
            "symbol": "MSFT",
            "action": "BUY",
            "confidence": 0.9,
            "position_sizing": 0.1,
        }

        result = guard_execution([basic_signal], {}, {}, {})

        self.assertEqual(result[0]["original_action"], "BUY")
        self.assertEqual(result[0]["final_action"], "BUY")

    def test_empty_input_safe(self) -> None:
        self.assertEqual(guard_execution([], {}, {}, {}), [])


if __name__ == "__main__":
    unittest.main()
