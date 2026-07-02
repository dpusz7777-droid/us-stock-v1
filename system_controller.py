#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B6: 串联 B1-B5 的本地量化系统控制器。"""

from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import Any

from analytics_engine import AnalyticsEngine
from backtest_engine import BacktestEngine
from report_engine import ReportEngine
from strategy_optimizer import StrategyOptimizer


def _default_historical_data() -> dict[str, list[tuple[Decimal, str]]]:
    """返回固定的本地样本；不读取文件、不访问网络。"""
    multipliers = (
        Decimal("1.03"), Decimal("1.035"), Decimal("1.01"),
        Decimal("0.97"), Decimal("0.96"), Decimal("1.04"),
        Decimal("1.045"), Decimal("0.99"),
    )
    prices = [Decimal("100.00")]
    for index in range(1, 33):
        prices.append(
            (prices[-1] * multipliers[(index - 1) % len(multipliers)])
            .quantize(Decimal("0.01"))
        )
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return {
        "AAPL": [
            (
                price,
                (start + timedelta(days=index)).isoformat(),
            )
            for index, price in enumerate(prices)
        ]
    }


def normalize_historical_data(
    historical_data: dict | None,
) -> dict[str, list[tuple[Decimal, str]]]:
    """将 JSON 或 Python 历史数据规范化为 BacktestEngine 输入格式。"""
    source = historical_data if historical_data is not None else _default_historical_data()
    if not isinstance(source, dict) or not source:
        raise ValueError("historical_data must be a non-empty object.")

    normalized: dict[str, list[tuple[Decimal, str]]] = {}
    for raw_symbol, raw_series in source.items():
        symbol = str(raw_symbol).strip().upper()
        if not symbol:
            raise ValueError("Historical data contains an empty symbol.")
        if not isinstance(raw_series, (list, tuple)) or not raw_series:
            raise ValueError(f"{symbol} price series must be non-empty.")

        series: list[tuple[Decimal, str]] = []
        for index, item in enumerate(raw_series):
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise ValueError(
                    f"{symbol} item {index} must be [price, timestamp]."
                )
            try:
                price = Decimal(str(item[0]))
            except (InvalidOperation, ValueError, TypeError) as exc:
                raise ValueError(
                    f"{symbol} item {index} has an invalid price."
                ) from exc
            if not price.is_finite() or price <= Decimal("0"):
                raise ValueError(
                    f"{symbol} item {index} price must be finite and positive."
                )
            timestamp = str(item[1])
            if not timestamp:
                raise ValueError(
                    f"{symbol} item {index} has an empty timestamp."
                )
            series.append((price, timestamp))
        normalized[symbol] = series
    return normalized


class SystemController:
    """以内存数据驱动完整的确定性量化流水线。"""

    def __init__(
        self,
        historical_data: dict | None = None,
        initial_cash: Decimal | float | str = Decimal("100000"),
    ) -> None:
        self._uses_default_data = historical_data is None
        self.historical_data = normalize_historical_data(historical_data)
        self.initial_cash = Decimal(str(initial_cash))
        if not self.initial_cash.is_finite() or self.initial_cash <= 0:
            raise ValueError("initial_cash must be finite and positive.")

    def _new_engine(self) -> BacktestEngine:
        engine = BacktestEngine(
            initial_cash=self.initial_cash,
            deterministic=True,
            seed=42,
        )
        # 产品化流水线固定滑点且不模拟等待，不消费任何随机值。
        engine._execution_engine._simulate_slippage = lambda: Decimal("0.002")
        engine._execution_engine._sleep_ms = lambda _milliseconds: None
        engine._suppress_reports = True
        return engine

    def _data_for_symbol(
        self,
        symbol: str | None,
    ) -> dict[str, list[tuple[Decimal, str]]]:
        if symbol is None:
            return {
                name: list(series)
                for name, series in self.historical_data.items()
            }
        normalized_symbol = symbol.strip().upper()
        if normalized_symbol not in self.historical_data:
            if self._uses_default_data and len(self.historical_data) == 1:
                default_series = next(iter(self.historical_data.values()))
                return {
                    normalized_symbol: list(default_series)
                }
            available = ", ".join(sorted(self.historical_data))
            raise ValueError(
                f"Unknown symbol {normalized_symbol!r}. Available: {available}."
            )
        return {
            normalized_symbol: list(self.historical_data[normalized_symbol])
        }

    @staticmethod
    def _serialize_backtest(result: Any, engine: BacktestEngine) -> dict:
        return {
            "summary": result.to_dict(),
            "symbols": {
                symbol: symbol_result.to_dict()
                for symbol, symbol_result in result.symbol_results.items()
            },
            "equity_curve": [
                float(value) for value in engine.get_equity_curve()
            ],
        }

    def run_backtest(self, symbol: str | None = None) -> dict:
        """运行 B1 BacktestEngine。"""
        data = self._data_for_symbol(symbol)
        engine = self._new_engine()
        result = engine.run(data)
        return self._serialize_backtest(result, engine)

    def run_analysis(self, symbol: str | None = None) -> dict[str, float]:
        """运行 BacktestEngine → B3 AnalyticsEngine。"""
        data = self._data_for_symbol(symbol)
        engine = self._new_engine()
        engine.run(data)
        return AnalyticsEngine(
            engine.get_equity_curve(),
            engine.pnl_history,
        ).analyze()

    def run_optimization(self, symbol: str | None = None) -> dict:
        """运行 BacktestEngine → AnalyticsEngine → B4 StrategyOptimizer。"""
        data = self._data_for_symbol(symbol)
        engine = self._new_engine()
        engine.run(data)
        optimizer = StrategyOptimizer(engine, AnalyticsEngine, data)
        with redirect_stdout(StringIO()):
            return optimizer.run()

    def _run_pipeline(
        self,
        data: dict[str, list[tuple[Decimal, str]]],
    ) -> dict:
        engine = self._new_engine()

        # B1/B2: 建立基线回测状态。
        engine.run(data)

        # B3/B4: 搜索参数组合。
        optimizer = StrategyOptimizer(engine, AnalyticsEngine, data)
        with redirect_stdout(StringIO()):
            optimizer_result = optimizer.run()

        # 用最优配置重跑，保证后续分析和报告口径一致。
        best_result = engine.run_with_config(
            optimizer_result["best_config"],
            data,
        )
        analytics = AnalyticsEngine(
            engine.get_equity_curve(),
            engine.pnl_history,
        )
        metrics = analytics.analyze()

        # B5: 统一生成结构化报告。
        report = ReportEngine(
            engine,
            analytics,
            optimizer_result,
            data,
        ).generate_report()

        return {
            "backtest": self._serialize_backtest(best_result, engine),
            "analysis": metrics,
            "optimization": optimizer_result,
            "report": report,
        }

    def run_full_pipeline(self, symbol: str | None = "NVDA") -> dict:
        """串联 Backtest → Analytics → Optimizer → Report。"""
        return self._run_pipeline(self._data_for_symbol(symbol))

    def run_daily_report(self) -> dict:
        """生成完全基于输入数据的确定性日报。"""
        return self.run_full_pipeline(None)["report"]

    def run_symbol(self, symbol: str) -> dict:
        """对单一股票运行完整 B1-B5 流水线。"""
        return self._run_pipeline(self._data_for_symbol(symbol))
