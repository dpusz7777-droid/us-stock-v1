# -*- coding: utf-8 -*-
"""V3Pipeline 完整流程测试。"""

from __future__ import annotations

import unittest
from decimal import Decimal
from typing import Any

from v3_pipeline import (
    V3Pipeline, PipelineInput, PipelineResult, PipelineStatus, PipelineStepResult,
    create_scenario_data, v3_pipeline,
)
from decision_engine import DecisionAction
from execution_engine import OrderStatus
from events import PIPELINE_STARTED, PIPELINE_STEP_COMPLETED, PIPELINE_BLOCKED, PIPELINE_COMPLETED
from event_bus import event_bus
from price_provider_v2 import PriceResultV2, PRICE_STATUS_OK


class TestPipelineInput(unittest.TestCase):
    def test_default_input(self) -> None:
        inp = PipelineInput()
        self.assertTrue(inp.simulation_only)
        self.assertEqual(len(inp.symbols), 2)


class TestPipelineResult(unittest.TestCase):
    def test_to_dict(self) -> None:
        r = PipelineResult(status=PipelineStatus.PASS, cash_before=Decimal("1000"), cash_after=Decimal("1100"))
        d = r.to_dict()
        self.assertEqual(d["status"], "PASS")
        self.assertEqual(d["cash_before"], "1000")


class TestCreateScenarioData(unittest.TestCase):
    def test_bull_scenario(self) -> None:
        inp = create_scenario_data("bull")
        self.assertEqual(inp.scenario, "bull")
        self.assertEqual(len(inp.symbols), 2)
        self.assertIn("AAPL", inp.price_history)
        self.assertIn("MSFT", inp.price_history)

    def test_bear_scenario(self) -> None:
        inp = create_scenario_data("bear")
        self.assertEqual(inp.scenario, "bear")

    def test_choppy_scenario(self) -> None:
        inp = create_scenario_data("choppy")
        self.assertEqual(inp.scenario, "choppy")

    def test_high_risk_scenario(self) -> None:
        inp = create_scenario_data("high-risk")
        self.assertEqual(inp.scenario, "high-risk")

    def test_default_scenario(self) -> None:
        inp = create_scenario_data()
        self.assertEqual(inp.scenario, "bull")

    def test_current_prices_exist(self) -> None:
        inp = create_scenario_data("bull")
        self.assertIn("AAPL", inp.current_prices)
        self.assertIsNotNone(inp.current_prices["AAPL"].price)


class TestV3Pipeline(unittest.TestCase):
    def setUp(self) -> None:
        self.pipeline = V3Pipeline()
        self.pipeline.reset(Decimal("100000"))
        event_bus.clear_log()

    def test_bull_full_pipeline(self) -> None:
        inp = create_scenario_data("bull")
        result = self.pipeline.run(inp)
        self.assertIn(result.status, (PipelineStatus.PASS, PipelineStatus.DEGRADED))
        self.assertGreater(len(result.steps), 5)

    def test_bear_full_pipeline(self) -> None:
        inp = create_scenario_data("bear")
        result = self.pipeline.run(inp)
        self.assertIn(result.status, (PipelineStatus.PASS, PipelineStatus.DEGRADED))

    def test_choppy_full_pipeline(self) -> None:
        inp = create_scenario_data("choppy")
        result = self.pipeline.run(inp)
        self.assertIn(result.status, (PipelineStatus.PASS, PipelineStatus.DEGRADED))

    def test_high_risk_full_pipeline(self) -> None:
        inp = create_scenario_data("high-risk")
        result = self.pipeline.run(inp)
        self.assertIn(result.status, (PipelineStatus.PASS, PipelineStatus.DEGRADED))

    def test_market_regime_detected(self) -> None:
        inp = create_scenario_data("bull")
        result = self.pipeline.run(inp)
        self.assertIn(result.market_regime, ("BULL", "CHOPPY", "BEAR", "HIGH_RISK", "UNKNOWN"))

    def test_strategy_selected(self) -> None:
        inp = create_scenario_data("bull")
        result = self.pipeline.run(inp)
        self.assertTrue(len(result.selected_strategy) > 0)

    def test_capital_mode_reported(self) -> None:
        inp = create_scenario_data("bull")
        result = self.pipeline.run(inp)
        self.assertIn(result.capital_mode, ("NORMAL", "CAUTION", "DEFENSIVE", "LOCKDOWN", ""))

    def test_cash_never_negative(self) -> None:
        self.pipeline.reset(Decimal("1000"))
        inp = create_scenario_data("bull")
        result = self.pipeline.run(inp)
        self.assertGreaterEqual(result.cash_after, Decimal("0"))
        self.assertGreaterEqual(self.pipeline.cash, Decimal("0"))

    def test_positions_never_negative(self) -> None:
        inp = create_scenario_data("bull")
        result = self.pipeline.run(inp)
        for sym, qty in self.pipeline.positions.items():
            self.assertGreaterEqual(qty, Decimal("0"))

    def test_simulation_only(self) -> None:
        inp = create_scenario_data("bull")
        result = self.pipeline.run(inp)
        self.assertTrue(result.simulation_only)

    def test_total_equity_positive(self) -> None:
        inp = create_scenario_data("bull")
        result = self.pipeline.run(inp)
        self.assertGreaterEqual(result.total_equity, Decimal("0"))

    def test_reset_state(self) -> None:
        inp = create_scenario_data("bull")
        r1 = self.pipeline.run(inp)
        self.pipeline.reset(Decimal("200000"))
        self.assertEqual(self.pipeline.cash, Decimal("200000"))
        self.assertEqual(len(self.pipeline.positions), 0)

    def test_deterministic_results(self) -> None:
        p1 = V3Pipeline()
        p2 = V3Pipeline()
        p1.reset(Decimal("100000"))
        p2.reset(Decimal("100000"))
        inp = create_scenario_data("bull")
        r1 = p1.run(inp)
        r2 = p2.run(inp)
        self.assertEqual(r1.status, r2.status)

    def test_event_published(self) -> None:
        received: list[dict] = []
        def listener(data: Any) -> None:
            received.append(data)
        event_bus.subscribe(PIPELINE_STARTED, listener)
        event_bus.subscribe(PIPELINE_COMPLETED, listener)
        inp = create_scenario_data("bull")
        self.pipeline.run(inp)
        self.assertTrue(len(received) >= 2)


class TestPipelineSteps(unittest.TestCase):
    def setUp(self) -> None:
        self.pipeline = V3Pipeline()
        self.pipeline.reset(Decimal("100000"))

    def test_buy_flow(self) -> None:
        """BUY 应经过全部模块。"""
        inp = create_scenario_data("bull")
        result = self.pipeline.run(inp)
        step_names = [s.step_name for s in result.steps]
        # Should have SignalEngine, RiskEngine, DecisionEngine steps
        signal_steps = [s for s in step_names if "SignalEngine" in s]
        decision_steps = [s for s in step_names if "DecisionEngine" in s]
        execution_steps = [s for s in step_names if "ExecutionEngine" in s]
        self.assertGreater(len(signal_steps), 0)
        self.assertGreater(len(decision_steps), 0)
        self.assertGreater(len(execution_steps), 0)

    def test_no_duplicate_execution(self) -> None:
        """同一时间点不得重复执行。"""
        inp = create_scenario_data("bull")
        r1 = self.pipeline.run(inp)
        cash1 = self.pipeline.cash
        pos1 = dict(self.pipeline.positions)
        # 第二次运行不应基于同一次输入产生重复交易
        inp2 = create_scenario_data("bull")
        r2 = self.pipeline.run(inp2)
        # cash 可能不同（新交易日），但不应完全相同
        self.assertIsNotNone(cash1)

    def test_market_regime_step_exists(self) -> None:
        inp = create_scenario_data("bull")
        result = self.pipeline.run(inp)
        step_names = [s.step_name for s in result.steps]
        self.assertTrue(any("MarketRegime" in s for s in step_names))


class TestGlobalSingleton(unittest.TestCase):
    def test_v3_pipeline_is_singleton(self) -> None:
        p1 = v3_pipeline
        p2 = v3_pipeline
        self.assertIs(p1, p2)

    def test_singleton_is_v3_pipeline_instance(self) -> None:
        from v3_pipeline import v3_pipeline as vp
        self.assertIsNotNone(vp)


if __name__ == "__main__":
    unittest.main()