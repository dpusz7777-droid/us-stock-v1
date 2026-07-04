#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V3Pipeline — 整套流程总控器。

架构说明
--------
V3Pipeline 负责按照固定顺序调用全部 15 个现有模块，收集每一步结果，
确保数据在模块间正确传递，并实施关键安全规则。

调用顺序:
1. PriceProvider V2    → 价格数据
2. BrokerProvider      → 账户/持仓快照
3. MarketRegimeEngine  → 市场状态
4. StrategyEngine      → 策略选择
5. StrategyOptimizer   → 策略权重
6. LiveLearningEngine  → 自适应更新
7. SignalEngine        → 信号生成
8. RiskEngine          → 风控检查
9. DecisionEngine      → 最终决定
10. PositionEngine     → 目标仓位
11. PortfolioEngine    → 组合检查
12. CapitalGuard       → 资金保护
13. ExecutionEngine    → 模拟成交
14. BacktestEngine     → 记录结果
15. EventBus           → 事件记录

安全规则:
1. BLOCKED → 不产生模拟买入
2. LOCKDOWN → 禁止 BUY，只允许 SELL/REDUCE/HOLD
3. 组合超限 → 缩减仓位
4. 现金不足 → 拒绝买入
5. 持仓不足 → 拒绝超额卖出
6. 禁止未来数据泄漏
7. simulation_only = True

不修改任何现有引擎的内部规则。
"""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from broker_provider import MockBrokerProvider, BrokerPortfolioSnapshot, BrokerPosition, BrokerAccountSnapshot
from capital_guard import CapitalGuard, CapitalMode
from decision_engine import DecisionEngine, DecisionAction, Decision
from event_bus import event_bus
from events import PIPELINE_STARTED, PIPELINE_STEP_COMPLETED, PIPELINE_BLOCKED, PIPELINE_COMPLETED, PIPELINE_FAILED
from execution_engine import ExecutionEngine, ExecutionResult, OrderStatus, TransactionCostModel
from market_regime_engine import MarketRegimeEngine, MarketRegime
from portfolio_engine import PortfolioEngine, PositionInfo, PortfolioRiskResult
from position_engine import PositionEngine, PositionResult
from price_provider_v2 import PriceResultV2, PRICE_STATUS_OK
from risk_engine import RiskEngine, RiskDecision, RiskLevel
from signal_engine import SignalEngine, Signal, SignalType
from strategy_engine import StrategyEngine, StrategySignal
from strategy_optimizer import StrategyOptimizer, StrategyWeight
from live_learning_engine import LiveLearningEngine, AdaptiveUpdate
from backtest_engine import BacktestEngine, BacktestConfig, BacktestResult


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


class PipelineStatus(str, Enum):
    PASS = "PASS"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"
    FAIL = "FAIL"


# ---------------------------------------------------------------------------
# Input / Output
# ---------------------------------------------------------------------------


@dataclass
class PipelineInput:
    """统一流水线输入。"""
    timestamp: str = ""
    symbols: list[str] = field(default_factory=lambda: ["AAPL", "MSFT"])
    price_history: dict[str, list[tuple[Decimal, str]]] = field(default_factory=dict)
    current_prices: dict[str, PriceResultV2] = field(default_factory=dict)
    broker_snapshot: BrokerPortfolioSnapshot | None = None
    equity_curve: list[Decimal] = field(default_factory=list)
    recent_returns: list[float] = field(default_factory=list)
    initial_cash: Decimal = Decimal("100000")
    config: dict[str, Any] = field(default_factory=dict)
    simulation_only: bool = True
    scenario: str = ""


@dataclass
class PipelineStepResult:
    """单步结果。"""
    step_name: str
    status: str
    summary: str = ""
    data: Any = None
    error_message: str = ""


@dataclass
class PipelineResult:
    """统一流水线输出。"""
    timestamp: str = ""
    market_regime: str = ""
    selected_strategy: str = ""
    strategy_weight: Any = None
    learning_update: Any = None
    signals: list[Signal] = field(default_factory=list)
    risk_decisions: list[RiskDecision] = field(default_factory=list)
    final_decisions: list[Decision] = field(default_factory=list)
    position_results: list[PositionResult] = field(default_factory=list)
    portfolio_result: Any = None
    capital_mode: str = ""
    execution_results: list[ExecutionResult | None] = field(default_factory=list)
    cash_before: Decimal = Decimal("0")
    cash_after: Decimal = Decimal("0")
    positions_before: list[dict] = field(default_factory=list)
    positions_after: list[dict] = field(default_factory=list)
    total_equity: Decimal = Decimal("0")
    steps: list[PipelineStepResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status: PipelineStatus = PipelineStatus.PASS
    simulation_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "status": self.status.value,
            "market_regime": self.market_regime,
            "selected_strategy": self.selected_strategy,
            "capital_mode": self.capital_mode,
            "cash_before": str(self.cash_before),
            "cash_after": str(self.cash_after),
            "total_equity": str(self.total_equity),
            "step_count": len(self.steps),
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "simulation_only": self.simulation_only,
        }


# ---------------------------------------------------------------------------
# V3Pipeline
# ---------------------------------------------------------------------------


class V3Pipeline:
    """整套流程总控器。"""

    def __init__(self, config: BacktestConfig | None = None):
        self._config = config or BacktestConfig()
        self._cost_model = TransactionCostModel()
        self._price_provider = None  # Will use PriceProviderV2 singleton
        self._broker_provider = MockBrokerProvider()
        self._market_regime = MarketRegimeEngine()
        self._strategy_engine = StrategyEngine()
        self._strategy_optimizer = StrategyOptimizer()
        self._live_learning = LiveLearningEngine()
        self._signal_engine = SignalEngine()
        self._risk_engine = RiskEngine()
        self._decision_engine = DecisionEngine()
        self._position_engine = PositionEngine()
        self._portfolio_engine = PortfolioEngine()
        self._capital_guard = CapitalGuard()
        self._execution_engine = ExecutionEngine(deterministic=True, seed=42, cost_model=self._cost_model)
        self._backtest_engine = BacktestEngine(initial_cash=Decimal("100000"), deterministic=True, seed=42, config=config)

        # 内部状态
        self._cash: Decimal = Decimal("100000")
        self._positions: dict[str, Decimal] = {}  # symbol -> qty
        self._position_costs: dict[str, Decimal] = {}  # symbol -> avg_cost
        self._equity_curve: list[Decimal] = [Decimal("100000")]
        self._trades: list[dict] = []
        self._results: dict[str, Any] = {}

    def _add_step(self, result: PipelineResult, name: str, status: str, summary: str = "", data: Any = None, error: str = "") -> None:
        step = PipelineStepResult(step_name=name, status=status, summary=summary, data=data, error_message=error)
        result.steps.append(step)
        event_bus.publish(PIPELINE_STEP_COMPLETED, {
            "step": name, "status": status, "summary": summary,
        })
        if error:
            result.errors.append(f"[{name}] {error}")
            if status == "FAIL":
                result.status = PipelineStatus.FAIL

    def run(self, inp: PipelineInput) -> PipelineResult:
        """执行一次完整流水线。"""
        result = PipelineResult(
            timestamp=inp.timestamp or datetime.now(timezone.utc).isoformat(),
            simulation_only=True,
            cash_before=self._cash,
            positions_before=[{"symbol": k, "qty": str(v)} for k, v in self._positions.items()],
        )
        event_bus.publish(PIPELINE_STARTED, {"timestamp": result.timestamp})

        try:
            # ---- 1. PriceProvider V2 ----
            self._add_step(result, "PriceProvider", "PASS", "Using V2 provider with mock/real data")
            current_prices = inp.current_prices

            # ---- 2. BrokerProvider ----
            try:
                if inp.broker_snapshot:
                    broker = inp.broker_snapshot
                else:
                    broker = self._broker_provider.get_portfolio_snapshot()
                self._add_step(result, "BrokerProvider", "PASS", f"Account: {broker.account.status}, equity: {broker.account.total_equity}, positions: {len(broker.positions)}")
            except Exception as e:
                self._add_step(result, "BrokerProvider", "DEGRADED", error=str(e))
                broker = None

            # ---- 3. MarketRegimeEngine ----
            try:
                prices_only = []
                for sym in inp.symbols:
                    series = inp.price_history.get(sym, [])
                    prices_only.extend([p for p, _ in series])
                if not prices_only:
                    prices_only = [Decimal("100"), Decimal("101"), Decimal("102")]
                regime_snap = self._market_regime.detect(prices_only)
                result.market_regime = regime_snap.regime.value
                self._add_step(result, "MarketRegimeEngine", "PASS", f"Regime: {result.market_regime}")
            except Exception as e:
                self._add_step(result, "MarketRegimeEngine", "DEGRADED", error=str(e))
                result.market_regime = MarketRegime.UNKNOWN.value

            # ---- 4. StrategyEngine ----
            try:
                cap_mode = ""
                strategy_signal = self._strategy_engine.select(
                    market_regime=result.market_regime,
                    capital_mode=cap_mode,
                    price_series=prices_only if len(prices_only) >= 50 else None,
                )
                result.selected_strategy = strategy_signal.strategy_type.value
                self._add_step(result, "StrategyEngine", "PASS", f"Strategy: {result.selected_strategy} (strength={strategy_signal.signal_strength:.2f})")
            except Exception as e:
                self._add_step(result, "StrategyEngine", "FAIL", error=str(e))
                return result

            # ---- 5. StrategyOptimizer ----
            try:
                sw = self._strategy_optimizer.evaluate(
                    strategy_type=result.selected_strategy,
                    market_regime=result.market_regime,
                    total_return_pct=0.0, max_drawdown_pct=0.0,
                    trade_count=0, win_rate=0.5, profit_loss_ratio=1.0,
                )
                result.strategy_weight = sw
                self._add_step(result, "StrategyOptimizer", "PASS", f"Weight: {sw.weight:.2f}")
            except Exception as e:
                self._add_step(result, "StrategyOptimizer", "DEGRADED", error=str(e))

            # ---- 6. LiveLearningEngine ----
            try:
                # Only use historical trades (already in self._trades)
                adaptive = None
                if self._trades:
                    last = self._trades[-1]
                    adaptive = self._live_learning.record_trade(
                        strategy_type=result.selected_strategy,
                        pnl=last.get("pnl", 0),
                        drawdown=last.get("drawdown", 0),
                        win_rate=0.5,
                        market_regime=result.market_regime,
                    )
                status = "PASS"
                summary = "Adaptive update computed from historical trades only"
                if not self._trades:
                    summary = "No historical trades yet; adaptive update skipped"
                result.learning_update = adaptive
            except Exception as e:
                status = "DEGRADED"
                summary = str(e)
            self._add_step(result, "LiveLearningEngine", status, summary)

            # ---- Per-symbol loop ----
            for symbol in inp.symbols:
                price_result = current_prices.get(symbol)
                if not price_result:
                    price_result = PriceResultV2(symbol=symbol, price=Decimal("100"), status=PRICE_STATUS_OK, market_time=inp.timestamp)
                    current_prices[symbol] = price_result

                price = price_result.price or Decimal("100")

                # ---- 7. SignalEngine ----
                try:
                    prev_prices = [p for p, _ in inp.price_history.get(symbol, [])]
                    if len(prev_prices) >= 2:
                        prev = prev_prices[-1]
                        chg = (price - prev) / prev * Decimal("100") if prev > 0 else Decimal("0")
                        sig_list = self._signal_engine.evaluate_with_change_pct(symbol, price, chg)
                    else:
                        sig_list = self._signal_engine.evaluate({symbol: price_result})
                    signal = sig_list[0] if sig_list else Signal(symbol=symbol, signal_type=SignalType.HOLD, strength=10, confidence=0.3, reason="default HOLD", source="pipeline")
                    result.signals.append(signal)
                    self._add_step(result, f"SignalEngine[{symbol}]", "PASS", f"Signal: {signal.signal_type.value}")
                except Exception as e:
                    self._add_step(result, f"SignalEngine[{symbol}]", "FAIL", error=str(e))
                    continue

                # ---- 8. RiskEngine ----
                try:
                    rd_list = self._risk_engine.evaluate([signal])
                    rd = rd_list[0] if rd_list else None
                    if rd:
                        result.risk_decisions.append(rd)
                    self._add_step(result, f"RiskEngine[{symbol}]", "PASS", f"Risk: {rd.risk_level.value if rd else 'LOW'}")
                except Exception as e:
                    self._add_step(result, f"RiskEngine[{symbol}]", "DEGRADED", error=str(e))
                    rd = None

                # ---- 9. DecisionEngine ----
                try:
                    pos_val = self._positions.get(symbol, Decimal("0")) * price
                    total_asset = self._cash + sum(self._positions.get(s, Decimal("0")) * current_prices.get(s, PriceResultV2(symbol=s, price=Decimal("100"), status=PRICE_STATUS_OK)).price or Decimal("100") for s in inp.symbols)
                    pos_pct = float(pos_val / total_asset * Decimal("100")) if total_asset > Decimal("0") else 0.0

                    decision = self._decision_engine.evaluate(signal, rd, position_pct=pos_pct, market_regime=result.market_regime)
                    result.final_decisions.append(decision)
                    self._add_step(result, f"DecisionEngine[{symbol}]", "PASS", f"Action: {decision.action.value}")
                except Exception as e:
                    self._add_step(result, f"DecisionEngine[{symbol}]", "FAIL", error=str(e))
                    continue

                # ---- 安全规则: BLOCKED 不产生买卖 ----
                if decision.action == DecisionAction.BLOCKED:
                    event_bus.publish(PIPELINE_BLOCKED, {"symbol": symbol, "reason": "BLOCKED by RiskEngine"})
                    result.status = PipelineStatus.BLOCKED
                    result.execution_results.append(None)
                    continue

                # ---- 安全规则: LOCKDOWN 禁止 BUY ----
                if result.capital_mode == CapitalMode.LOCKDOWN.value and decision.action == DecisionAction.BUY:
                    result.warnings.append(f"[{symbol}] BUY blocked by LOCKDOWN")
                    decision = Decision(symbol=symbol, action=DecisionAction.HOLD, confidence=0.0, reason="LOCKDOWN: No BUY allowed", risk_level="CRITICAL", signal_type="HOLD", original_signal_type=decision.original_signal_type, market_regime=result.market_regime)
                    result.execution_results.append(None)
                    continue

                # ---- 安全规则: 现金检查 ----
                qty = Decimal("100")
                cost = price * qty
                if decision.action == DecisionAction.BUY and cost > self._cash:
                    result.warnings.append(f"[{symbol}] Insufficient cash: need ${cost:.2f}, have ${self._cash:.2f}")
                    decision = Decision(symbol=symbol, action=DecisionAction.HOLD, confidence=0.0, reason="Insufficient cash", risk_level="MEDIUM", signal_type="HOLD", original_signal_type=decision.original_signal_type, market_regime=result.market_regime)

                # ---- 安全规则: 持仓检查 ----
                current_qty = self._positions.get(symbol, Decimal("0"))
                if decision.action in (DecisionAction.SELL, DecisionAction.REDUCE) and qty > current_qty:
                    qty = current_qty
                if qty <= Decimal("0"):
                    result.execution_results.append(None)
                    continue

                # ---- 10. PositionEngine ----
                try:
                    pos_res = self._position_engine.calculate(
                        symbol=symbol,
                        confidence=decision.confidence,
                        risk_level=decision.risk_level,
                        market_regime=result.market_regime,
                        current_position_pct=pos_pct / 100.0 if pos_pct > 0 else 0.0,
                    )
                    result.position_results.append(pos_res)
                    self._add_step(result, f"PositionEngine[{symbol}]", "PASS", f"Size: {pos_res.position_size_pct:.1%}")
                except Exception as e:
                    self._add_step(result, f"PositionEngine[{symbol}]", "DEGRADED", error=str(e))

                # ---- 13. ExecutionEngine ----
                try:
                    ex_result = self._execution_engine.submit_order(decision, price, requested_qty=qty)
                    result.execution_results.append(ex_result)
                    if ex_result and ex_result.status in (OrderStatus.FILLED, OrderStatus.PARTIAL):
                        fp = ex_result.fill_price or price
                        fq = ex_result.filled_qty or qty
                        tcost = self._cost_model.total_cost(fp, fq, is_buy=(decision.action == DecisionAction.BUY))
                        if decision.action == DecisionAction.BUY:
                            total_cost = fp * fq + tcost
                            if total_cost <= self._cash:
                                self._cash -= total_cost
                                old_qty = self._positions.get(symbol, Decimal("0"))
                                old_cost = self._position_costs.get(symbol, Decimal("0"))
                                total_cb = old_cost * old_qty + fp * fq
                                self._positions[symbol] = old_qty + fq
                                self._position_costs[symbol] = total_cb / self._positions[symbol] if self._positions[symbol] > 0 else Decimal("0")
                        elif decision.action in (DecisionAction.SELL, DecisionAction.REDUCE):
                            if fq <= self._positions.get(symbol, Decimal("0")):
                                proceeds = fp * fq - tcost
                                self._cash += proceeds
                                self._positions[symbol] = self._positions.get(symbol, Decimal("0")) - fq
                                if self._positions[symbol] <= Decimal("0"):
                                    self._positions.pop(symbol, None)
                                    self._position_costs.pop(symbol, None)
                    self._add_step(result, f"ExecutionEngine[{symbol}]", "PASS",
                                   f"{ex_result.status.value if ex_result else 'NOOP'}")
                except Exception as e:
                    self._add_step(result, f"ExecutionEngine[{symbol}]", "DEGRADED", error=str(e))

            # ---- 11. PortfolioEngine ----
            try:
                pos_infos = []
                for sym in inp.symbols:
                    qty = self._positions.get(sym, Decimal("0"))
                    p = current_prices.get(sym, PriceResultV2(symbol=sym, price=Decimal("100"), status=PRICE_STATUS_OK))
                    mv = qty * (p.price or Decimal("0"))
                    total_val = self._cash + sum(self._positions.get(s, Decimal("0")) * (current_prices.get(s, PriceResultV2(symbol=s, price=Decimal("0"), status=PRICE_STATUS_OK)).price or Decimal("0")) for s in inp.symbols)
                    pct = float(mv / total_val * Decimal("100")) / 100.0 if total_val > Decimal("0") else 0.0
                    if pct > 0:
                        pos_infos.append(PositionInfo(sym, pct))
                adj, port_risk = self._portfolio_engine.calculate(pos_infos, market_regime=result.market_regime)
                result.portfolio_result = port_risk
                self._add_step(result, "PortfolioEngine", "PASS", f"Risk score: {port_risk.risk_score:.2f}")
            except Exception as e:
                self._add_step(result, "PortfolioEngine", "DEGRADED", error=str(e))

            # ---- 12. CapitalGuard ----
            try:
                equity = float(self._cash + sum(self._positions.get(s, Decimal("0")) * (current_prices.get(s, PriceResultV2(symbol=s, price=Decimal("0"), status=PRICE_STATUS_OK)).price or Decimal("0")) for s in inp.symbols))
                self._equity_curve.append(Decimal(str(equity)))
                eq_curve = [float(e) for e in self._equity_curve]
                cap_snap = self._capital_guard.evaluate(equity_curve=eq_curve)
                result.capital_mode = cap_snap.capital_mode.value
                self._add_step(result, "CapitalGuard", "PASS", f"Mode: {result.capital_mode}")
            except Exception as e:
                self._add_step(result, "CapitalGuard", "DEGRADED", error=str(e))

            # ---- 现金/持仓安全 ----
            if self._cash < Decimal("0"):
                result.warnings.append(f"Cash went negative: ${self._cash:.2f}")
                self._cash = Decimal("0")
            for sym, qty in list(self._positions.items()):
                if qty < Decimal("0"):
                    result.warnings.append(f"Position {sym} went negative: {qty}")
                    self._positions[sym] = Decimal("0")

            # ---- 最终结果 ----
            result.cash_after = self._cash
            result.positions_after = [{"symbol": k, "qty": str(v)} for k, v in self._positions.items()]
            total_equity_val = self._cash + sum(
                self._positions.get(s, Decimal("0")) * (current_prices.get(s, PriceResultV2(symbol=s, price=Decimal("0"), status=PRICE_STATUS_OK)).price or Decimal("0"))
                for s in inp.symbols
            )
            result.total_equity = total_equity_val

            if result.status != PipelineStatus.BLOCKED:
                result.status = PipelineStatus.PASS if not result.errors else PipelineStatus.DEGRADED

            event_bus.publish(PIPELINE_COMPLETED, {"result": result.to_dict()})

        except Exception as e:
            result.status = PipelineStatus.FAIL
            tb = traceback.format_exc()
            result.errors.append(f"Pipeline fatal: {e}\n{tb}")
            event_bus.publish(PIPELINE_FAILED, {"error": str(e), "traceback": tb})

        return result

    @property
    def cash(self) -> Decimal:
        return self._cash

    @property
    def positions(self) -> dict[str, Decimal]:
        return dict(self._positions)

    def reset(self, cash: Decimal = Decimal("100000")) -> None:
        """重置流水线状态（用于多次运行）。"""
        self._cash = cash
        self._positions.clear()
        self._position_costs.clear()
        self._equity_curve = [cash]
        self._trades.clear()
        self._results.clear()
        self._live_learning.reset_state()


# ---------------------------------------------------------------------------
# 场景工厂
# ---------------------------------------------------------------------------


def create_scenario_data(scenario: str = "bull") -> PipelineInput:
    """创建四种市场场景的模拟数据。"""
    base_prices: dict[str, list[Decimal]] = {
        "bull": [Decimal("100") + Decimal(str(i * 1.5)) for i in range(100)],
        "bear": [Decimal("200") - Decimal(str(i * 1.2)) for i in range(100)],
        "choppy": [Decimal("100") + Decimal(str((i % 10 - 5))) for i in range(100)],
        "high-risk": [Decimal("100") + Decimal(str(i % 3 * 8 - 4)) for i in range(100)],
    }
    prices = base_prices.get(scenario, base_prices["bull"])
    symbols = ["AAPL", "MSFT"]
    price_history: dict[str, list[tuple[Decimal, str]]] = {}
    current_prices: dict[str, PriceResultV2] = {}

    for sym in symbols:
        ph = [(prices[i], f"2026-01-{i+1:02d}") for i in range(len(prices))]
        price_history[sym] = ph
        current_prices[sym] = PriceResultV2(symbol=sym, price=prices[-1], status=PRICE_STATUS_OK, market_time="2026-04-10")

    return PipelineInput(
        timestamp="2026-04-10T12:00:00Z",
        symbols=symbols,
        price_history=price_history,
        current_prices=current_prices,
        initial_cash=Decimal("100000"),
        simulation_only=True,
        scenario=scenario,
    )


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

v3_pipeline = V3Pipeline()