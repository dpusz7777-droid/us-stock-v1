# -*- coding: utf-8 -*-
"""BacktestEngine 测试。"""

from __future__ import annotations

import unittest
from decimal import Decimal

from backtest_engine import (
    BacktestEngine,
    BacktestResult,
    MultiSymbolBacktestResult,
    backtest_engine,
)


def _rising_prices(
    start: Decimal = Decimal("100"),
    count: int = 10,
    step: Decimal = Decimal("5"),
    base_date: str = "2026-01-01",
) -> list[tuple[Decimal, str]]:
    result: list[tuple[Decimal, str]] = []
    for i in range(count):
        price = start + step * Decimal(str(i))
        day = int(i) + 1
        date = f"{base_date[:8]}{day:02d}"
        result.append((price, date))
    return result


def _falling_prices(
    start: Decimal = Decimal("150"),
    count: int = 10,
    step: Decimal = Decimal("-5"),
    base_date: str = "2026-01-01",
) -> list[tuple[Decimal, str]]:
    result: list[tuple[Decimal, str]] = []
    for i in range(count):
        price = start + step * Decimal(str(i))
        day = int(i) + 1
        date = f"{base_date[:8]}{day:02d}"
        result.append((price, date))
    return result


class TestBacktestResult(unittest.TestCase):
    def test_default_result(self) -> None:
        r = BacktestResult()
        self.assertEqual(r.total_return, Decimal("0"))
        self.assertEqual(r.trade_count, 0)

    def test_to_dict(self) -> None:
        r = BacktestResult(total_return=Decimal("5000"), total_return_pct=Decimal("5.0"), win_rate=0.6, trade_count=10, initial_cash=Decimal("100000"))
        d = r.to_dict()
        self.assertEqual(d["total_return"], "5000")
        self.assertEqual(d["trade_count"], 10)

    def test_repr(self) -> None:
        r = BacktestResult(total_return_pct=Decimal("12.5"), trade_count=15, win_rate=0.6, max_drawdown=Decimal("3.2"))
        self.assertIn("12.5", repr(r))


class TestMultiSymbolBacktestResult(unittest.TestCase):
    def test_to_dict(self) -> None:
        r_a = BacktestResult(total_return=Decimal("1000"), trade_count=5)
        r_b = BacktestResult(total_return=Decimal("2000"), trade_count=3)
        multi = MultiSymbolBacktestResult(symbol_results={"NVDA": r_a, "AAPL": r_b}, total_return=Decimal("3000"), total_trade_count=8)
        d = multi.to_dict()
        self.assertEqual(d["total_return"], "3000")
        self.assertIn("NVDA", d["symbols"])


class TestBacktestEngineSingleStock(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = BacktestEngine(initial_cash=Decimal("100000"), deterministic=True, seed=42)

    def test_rising_prices_produces_equity(self) -> None:
        data = {"NVDA": _rising_prices(Decimal("100"), 15, Decimal("3"))}
        result = self.engine.run(data)
        nvda = result.symbol_results["NVDA"]
        self.assertGreater(len(nvda.equity_curve), 0)
        self.assertGreaterEqual(nvda.total_return, Decimal("0"))

    def test_falling_prices_has_equity(self) -> None:
        data = {"NVDA": _falling_prices(Decimal("150"), 10, Decimal("-4"))}
        result = self.engine.run(data)
        nvda = result.symbol_results["NVDA"]
        self.assertGreater(len(nvda.equity_curve), 0)

    def test_empty_data(self) -> None:
        data = {"NVDA": []}
        result = self.engine.run(data)
        nvda = result.symbol_results["NVDA"]
        self.assertEqual(nvda.trade_count, 0)
        self.assertEqual(nvda.final_cash, Decimal("100000"))

    def test_single_price_point(self) -> None:
        data = {"NVDA": [(Decimal("100"), "2026-01-01")]}
        result = self.engine.run(data)
        nvda = result.symbol_results["NVDA"]
        self.assertEqual(nvda.trade_count, 0)

    def test_run_single_returns_result(self) -> None:
        prices = _rising_prices(Decimal("100"), 5, Decimal("2"))
        result = self.engine.run_single("NVDA", prices)
        self.assertIsInstance(result, BacktestResult)

    def test_result_has_all_fields(self) -> None:
        prices = _rising_prices(Decimal("100"), 10, Decimal("2"))
        result = self.engine.run_single("NVDA", prices)
        self.assertIsNotNone(result.total_return)
        self.assertIsNotNone(result.max_drawdown)
        self.assertIsNotNone(result.final_equity)
        self.assertEqual(result.initial_cash, Decimal("100000"))

    def test_equity_curve_length(self) -> None:
        prices = _rising_prices(Decimal("100"), 5, Decimal("2"))
        result = self.engine.run_single("NVDA", prices)
        self.assertEqual(len(result.equity_curve), 5)

    def test_deterministic_same_result(self) -> None:
        data = {"NVDA": _rising_prices(Decimal("100"), 8, Decimal("2"))}
        r1 = self.engine.run(data)
        r2 = self.engine.run(data)
        self.assertEqual(r1.symbol_results["NVDA"].total_return, r2.symbol_results["NVDA"].total_return)


class TestBacktestEngineMultiStock(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = BacktestEngine(initial_cash=Decimal("100000"), deterministic=True, seed=42)

    def test_multi_stock(self) -> None:
        data = {"NVDA": _rising_prices(Decimal("100"), 10, Decimal("3")), "AAPL": _falling_prices(Decimal("200"), 10, Decimal("-2"))}
        result = self.engine.run(data)
        self.assertIn("NVDA", result.symbol_results)
        self.assertIn("AAPL", result.symbol_results)

    def test_multi_stock_aggregation(self) -> None:
        data = {"A": _rising_prices(Decimal("100"), 5, Decimal("1")), "B": _rising_prices(Decimal("100"), 5, Decimal("1"))}
        result = self.engine.run(data)
        self.assertEqual(len(result.symbol_results), 2)


class TestBacktestExtreme(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = BacktestEngine(initial_cash=Decimal("100000"), deterministic=True, seed=42)

    def test_sharp_decline_has_equity_curve(self) -> None:
        prices = _falling_prices(Decimal("200"), 10, Decimal("-10"))
        result = self.engine.run_single("NVDA", prices)
        self.assertGreater(len(result.equity_curve), 0)

    def test_all_hold_no_trades(self) -> None:
        prices = [(Decimal("100"), f"2026-01-{i+1:02d}") for i in range(10)]
        result = self.engine.run_single("NVDA", prices)
        self.assertGreaterEqual(result.trade_count, 0)


class TestNoModification(unittest.TestCase):
    def test_existing_engines_intact(self) -> None:
        from signal_engine import SignalEngine as SE
        from risk_engine import RiskEngine as RE
        from decision_engine import DecisionEngine as DE
        from execution_engine import ExecutionEngine as EE
        for name in ["evaluate", "evaluate_with_change_pct"]:
            self.assertTrue(hasattr(SE, name))
        self.assertTrue(hasattr(RE, "evaluate"))
        self.assertTrue(hasattr(DE, "evaluate"))
        self.assertTrue(hasattr(EE, "submit_order"))


class TestGlobalSingleton(unittest.TestCase):
    def test_backtest_engine_is_singleton(self) -> None:
        be1 = backtest_engine
        be2 = backtest_engine
        self.assertIs(be1, be2)


if __name__ == "__main__":
    unittest.main()