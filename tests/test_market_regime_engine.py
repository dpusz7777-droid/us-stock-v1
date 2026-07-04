# -*- coding: utf-8 -*-
"""MarketRegimeEngine 测试。"""

from __future__ import annotations

import unittest
from decimal import Decimal
from typing import Any

from event_bus import event_bus
from events import MARKET_REGIME_UPDATED
from market_regime_engine import (
    MarketRegimeEngine,
    MarketRegime,
    MarketRegimeSnapshot,
    market_regime_engine,
)
from backtest_engine import BacktestConfig


def _rising_prices(count: int = 100, step: Decimal = Decimal("1")) -> list[Decimal]:
    return [Decimal("100") + Decimal(str(i)) * step for i in range(count)]


def _falling_prices(count: int = 100, step: Decimal = Decimal("1")) -> list[Decimal]:
    return [Decimal("200") - Decimal(str(i)) * step for i in range(count)]


def _choppy_prices(count: int = 100, base: Decimal = Decimal("100"), amp: Decimal = Decimal("3")) -> list[Decimal]:
    prices: list[Decimal] = []
    for i in range(count):
        if i % 2 == 0:
            prices.append(base + amp)
        else:
            prices.append(base - amp)
    return prices


def _volatile_prices(count: int = 100, base: Decimal = Decimal("100"), amp: Decimal = Decimal("10")) -> list[Decimal]:
    prices: list[Decimal] = []
    for i in range(count):
        direction = 1 if i % 3 < 2 else -1
        prices.append(base + Decimal(str(direction * amp * (i % 5 + 1))))
    return prices


class TestMarketRegime(unittest.TestCase):
    def test_regime_values(self) -> None:
        self.assertEqual(MarketRegime.BULL.value, "BULL")
        self.assertEqual(MarketRegime.BEAR.value, "BEAR")
        self.assertEqual(MarketRegime.CHOPPY.value, "CHOPPY")
        self.assertEqual(MarketRegime.HIGH_RISK.value, "HIGH_RISK")
        self.assertEqual(MarketRegime.UNKNOWN.value, "UNKNOWN")


class TestMarketRegimeSnapshot(unittest.TestCase):
    def test_minimal(self) -> None:
        snap = MarketRegimeSnapshot(regime=MarketRegime.BULL)
        self.assertEqual(snap.regime, MarketRegime.BULL)
        self.assertEqual(snap.trend_strength, 0.0)

    def test_to_dict(self) -> None:
        snap = MarketRegimeSnapshot(regime=MarketRegime.HIGH_RISK, volatility_pct=5.5)
        d = snap.to_dict()
        self.assertEqual(d["regime"], "HIGH_RISK")
        self.assertEqual(d["volatility_pct"], 5.5)

    def test_repr(self) -> None:
        snap = MarketRegimeSnapshot(regime=MarketRegime.BEAR, trend_strength=-0.5)
        r = repr(snap)
        self.assertIn("BEAR", r)
        self.assertIn("-0.50", r)


class TestMarketRegimeEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = MarketRegimeEngine()
        event_bus.clear_log()

    def test_bull_detection(self) -> None:
        prices = _rising_prices(150, Decimal("0.5"))
        snap = self.engine.detect(prices)
        self.assertEqual(snap.regime, MarketRegime.BULL)

    def test_bear_detection(self) -> None:
        prices = _falling_prices(150, Decimal("0.5"))
        snap = self.engine.detect(prices)
        self.assertEqual(snap.regime, MarketRegime.BEAR)

    def test_unknown_insufficient_data(self) -> None:
        prices = [Decimal("100")] * 10
        snap = self.engine.detect(prices)
        self.assertEqual(snap.regime, MarketRegime.UNKNOWN)

    def test_event_published(self) -> None:
        received: list[dict] = []
        def listener(data: Any) -> None:
            received.append(data)
        event_bus.subscribe(MARKET_REGIME_UPDATED, listener)
        prices = _rising_prices(100)
        self.engine.detect(prices)
        self.assertTrue(len(received) > 0)
        self.assertIn("regime_snapshot", received[0])

    def test_update_bull_config(self) -> None:
        config = BacktestConfig()
        old_cooldown = config.cooldown_days
        old_confirm = config.signal_confirmation
        self.engine.update_backtest_config(config, MarketRegime.BULL)
        self.assertLess(config.cooldown_days, old_cooldown)
        self.assertEqual(config.signal_confirmation, 1)

    def test_update_bear_config(self) -> None:
        config = BacktestConfig()
        old_cooldown = config.cooldown_days
        self.engine.update_backtest_config(config, MarketRegime.BEAR)
        self.assertGreaterEqual(config.cooldown_days, old_cooldown)
        self.assertGreaterEqual(config.signal_confirmation, 2)

    def test_update_high_risk_config(self) -> None:
        config = BacktestConfig()
        old_cooldown = config.cooldown_days
        self.engine.update_backtest_config(config, MarketRegime.HIGH_RISK)
        self.assertGreaterEqual(config.cooldown_days, old_cooldown)

    def test_sma_calculation(self) -> None:
        prices = [Decimal(str(i)) for i in range(1, 101)]
        sma = MarketRegimeEngine._sma(prices, 10)
        self.assertEqual(len(sma), 91)
        self.assertAlmostEqual(float(sma[0]), 5.5, places=1)

    def test_slope_calculation(self) -> None:
        values = [Decimal(str(i)) for i in range(20)]
        slope = MarketRegimeEngine._slope(values, 10)
        self.assertGreater(float(slope), 0)

    def test_volatility_calculation(self) -> None:
        prices = _volatile_prices(50)
        vol = MarketRegimeEngine._volatility(prices, 20)
        self.assertGreater(float(vol), 0)

    def test_deterministic(self) -> None:
        p1 = _rising_prices(100)
        p2 = _rising_prices(100)
        s1 = self.engine.detect(p1)
        s2 = self.engine.detect(p2)
        self.assertEqual(s1.regime, s2.regime)


class TestGlobalSingleton(unittest.TestCase):
    def test_market_regime_engine_is_singleton(self) -> None:
        mre1 = market_regime_engine
        mre2 = market_regime_engine
        self.assertIs(mre1, mre2)


if __name__ == "__main__":
    unittest.main()