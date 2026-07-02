#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BacktestEngine — 历史回测系统（增强版 V2）。

增强功能
---------
1. 交易成本模型（佣金、价差、滑点）
2. ATR 动态阈值（替代固定 3%/5%）
3. 仓位计算（风险百分比模型，默认 1% 最大亏损）
4. 止损与止盈（固定止损、固定止盈、移动止损）
5. 样本外验证（策略调整区间 / 最终验证区间分割）

架构说明
----------
BacktestEngine 使用历史价格数据，按时间顺序模拟完整交易流程：
    PriceProvider → SignalEngine → RiskEngine → DecisionEngine → ExecutionEngine

不修改现有 Signal/Risk/Decision/Execution 引擎。
接口向后兼容：run_single(), run() 签名不变。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from decision_engine import DecisionEngine, DecisionAction
from execution_engine import ExecutionEngine, OrderStatus, TransactionCostModel
from risk_engine import RiskEngine, RiskLevel
from signal_engine import Signal, SignalEngine, SignalType


# ---------------------------------------------------------------------------
# ATR 计算
# ---------------------------------------------------------------------------


def _compute_atr(
    prices: list[Decimal], period: int = 14
) -> list[Decimal]:
    """计算平均真实波幅 (ATR)。"""
    if len(prices) < period + 1:
        return [Decimal("0")] * len(prices)
    atrs: list[Decimal] = [Decimal("0")] * period
    for i in range(period, len(prices)):
        tr = abs(prices[i] - prices[i - 1])
        if i == period:
            atr = tr
        else:
            atr = (atrs[-1] * Decimal(str(period - 1)) + tr) / Decimal(str(period))
        atrs.append(atr)
    return atrs


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


@dataclass
class BacktestConfig:
    """回测配置参数（全部可配置）。"""

    # 仓位管理
    max_risk_per_trade_pct: Decimal = Decimal("1.0")   # 单笔最大亏损 ≤ 1%
    max_position_pct: Decimal = Decimal("20.0")         # 单票最大仓位
    fixed_qty: Decimal | None = None                    # 固定股数（None 则启用动态仓位）

    # 止损止盈
    stop_loss_pct: Decimal = Decimal("5.0")             # 固定止损 -5%
    take_profit_pct: Decimal = Decimal("15.0")          # 固定止盈 +15%
    trailing_stop_activate_pct: Decimal = Decimal("8.0")  # 移动止损激活 +8%
    trailing_stop_distance_pct: Decimal = Decimal("4.0")  # 移动止损距离 4%

    # 动态阈值
    atr_period: int = 14                                 # ATR 计算周期
    atr_buy_threshold: Decimal = Decimal("1.5")          # 买入阈值：ATR × 1.5 倍
    atr_strong_buy_threshold: Decimal = Decimal("2.5")   # 强买入：ATR × 2.5 倍
    atr_sell_threshold: Decimal = Decimal("-1.2")        # 卖出阈值：ATR × -1.2 倍
    atr_strong_sell_threshold: Decimal = Decimal("-2.0") # 强卖出：ATR × -2.0 倍

    # 样本分割
    validation_split: float = 0.7                        # 70% 策略调整 / 30% 最终验证

    # ---- 过度交易抑制 ----
    cooldown_days: int = 5                               # 同一股票买卖后冷却 N 天
    trend_lock_days: int = 20                            # 趋势均线周期
    signal_confirmation: int = 2                         # BUY 信号需连续确认 N 次

    @property
    def max_risk_ratio(self) -> Decimal:
        return self.max_risk_per_trade_pct / Decimal("100")


# ---------------------------------------------------------------------------
# 回测结果（增强版）
# ---------------------------------------------------------------------------


@dataclass
class BacktestResult:
    """增强回测结果。"""

    total_return: Decimal = Decimal("0")
    total_return_pct: Decimal = Decimal("0")
    win_rate: float = 0.0
    max_drawdown: Decimal = Decimal("0")
    final_cash: Decimal = Decimal("0")
    final_equity: Decimal = Decimal("0")
    trade_count: int = 0
    win_count: int = 0
    lose_count: int = 0
    equity_curve: list[Decimal] = field(default_factory=list)
    timestamps: list[str] = field(default_factory=list)
    initial_cash: Decimal = Decimal("0")
    # 新增字段
    profit_loss_ratio: float = 0.0            # 盈亏比
    total_commission: Decimal = Decimal("0")  # 总佣金
    total_spread_cost: Decimal = Decimal("0") # 总价差成本
    total_slippage_cost: Decimal = Decimal("0")  # 总滑点成本
    avg_win: Decimal = Decimal("0")           # 平均盈利
    avg_loss: Decimal = Decimal("0")          # 平均亏损
    max_win: Decimal = Decimal("0")           # 最大单笔盈利
    max_loss: Decimal = Decimal("0")          # 最大单笔亏损
    in_sample_return_pct: Decimal | None = None   # 样本内收益率
    out_sample_return_pct: Decimal | None = None  # 样本外收益率
    stop_loss_triggered: int = 0              # 止损触发次数
    take_profit_triggered: int = 0            # 止盈触发次数
    trailing_stop_triggered: int = 0          # 移动止损触发次数
    trades: list[dict[str, Any]] = field(default_factory=list)  # 每笔详细交易

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_return": str(self.total_return),
            "total_return_pct": str(self.total_return_pct),
            "win_rate": self.win_rate,
            "profit_loss_ratio": self.profit_loss_ratio,
            "max_drawdown": str(self.max_drawdown),
            "final_cash": str(self.final_cash),
            "final_equity": str(self.final_equity),
            "trade_count": self.trade_count,
            "win_count": self.win_count,
            "lose_count": self.lose_count,
            "initial_cash": str(self.initial_cash),
            "equity_curve_len": len(self.equity_curve),
            "total_commission": str(self.total_commission),
            "total_spread_cost": str(self.total_spread_cost),
            "total_slippage_cost": str(self.total_slippage_cost),
            "avg_win": str(self.avg_win),
            "avg_loss": str(self.avg_loss),
            "max_win": str(self.max_win),
            "max_loss": str(self.max_loss),
            "in_sample_return_pct": str(self.in_sample_return_pct) if self.in_sample_return_pct is not None else None,
            "out_sample_return_pct": str(self.out_sample_return_pct) if self.out_sample_return_pct is not None else None,
            "stop_loss_triggered": self.stop_loss_triggered,
            "take_profit_triggered": self.take_profit_triggered,
            "trailing_stop_triggered": self.trailing_stop_triggered,
            "trades": self.trades,
        }

    def __repr__(self) -> str:
        return (
            f"BacktestResult(return={self.total_return_pct:.2f}%, "
            f"trades={self.trade_count}, win_rate={self.win_rate:.1%}, "
            f"dd={self.max_drawdown:.2f}%, pl_ratio={self.profit_loss_ratio:.2f})"
        )


# ---------------------------------------------------------------------------
# MultiSymbolBacktestResult
# ---------------------------------------------------------------------------


@dataclass
class MultiSymbolBacktestResult:
    symbol_results: dict[str, BacktestResult] = field(default_factory=dict)
    total_return: Decimal = Decimal("0")
    total_return_pct: Decimal = Decimal("0")
    avg_win_rate: float = 0.0
    total_trade_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_return": str(self.total_return),
            "total_return_pct": str(self.total_return_pct),
            "avg_win_rate": self.avg_win_rate,
            "total_trade_count": self.total_trade_count,
            "symbols": list(self.symbol_results.keys()),
        }


# ---------------------------------------------------------------------------
# BacktestEngine V2
# ---------------------------------------------------------------------------


class BacktestEngine:
    """增强回测引擎。

    用法与 V1 相同：
        engine = BacktestEngine(initial_cash=Decimal("100000"))
        result = engine.run_single("NVDA", price_series)
        multi = engine.run({"NVDA": series, "AAPL": series})
    """

    def __init__(
        self,
        initial_cash: Decimal = Decimal("100000"),
        deterministic: bool = True,
        seed: int = 42,
        config: BacktestConfig | None = None,
        cost_model: TransactionCostModel | None = None,
    ):
        self._deterministic = deterministic
        self._seed = seed
        self._initial_cash = initial_cash
        self._config = config or BacktestConfig()
        self._signal_engine = SignalEngine()
        self._risk_engine = RiskEngine()
        self._decision_engine = DecisionEngine()
        self._execution_engine = ExecutionEngine(
            deterministic=deterministic, seed=seed,
            cost_model=cost_model,
        )
        self._cost_model = cost_model or TransactionCostModel()
        self._rng = random.Random(seed) if deterministic else random.Random()
        self.equity_curve: list[Decimal] = []
        self.pnl_history: list[Decimal] = []
        self._last_historical_data: dict[
            str, list[tuple[Decimal, str]]
        ] | None = None
        self._strategy_overrides: dict[str, float] = {}
        self._suppress_reports = False
        self.signal_stats: dict[str, int] = {
            "BUY": 0,
            "SELL": 0,
            "HOLD": 0,
            "REDUCE": 0,
            "RISK_OFF": 0,
        }

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def get_equity_curve(self) -> list[Decimal]:
        """返回最近一次回测的净值曲线（每步 portfolio value）。"""
        return list(self.equity_curve)

    def get_analysis(self) -> dict:
        """返回最近一次回测的策略绩效分析。"""
        from analytics_engine import AnalyticsEngine

        return AnalyticsEngine(
            equity_curve=self.equity_curve,
            pnl_history=self.pnl_history,
        ).analyze()

    def run_with_config(
        self,
        config: dict[str, float],
        historical_data: dict[str, list[tuple[Decimal, str]]] | None = None,
    ) -> MultiSymbolBacktestResult:
        """使用临时策略参数运行回测，不改变 SignalEngine 主逻辑。"""
        required = {
            "momentum_threshold",
            "volatility_threshold",
            "risk_penalty",
            "mean_reversion_threshold",
        }
        missing = required.difference(config)
        if missing:
            raise ValueError(
                f"Missing strategy config values: {', '.join(sorted(missing))}"
            )

        data = historical_data or self._last_historical_data
        if data is None:
            raise ValueError(
                "No historical data available. Run the backtest once or "
                "provide historical_data."
            )

        momentum = float(config["momentum_threshold"])
        volatility = float(config["volatility_threshold"])
        risk_penalty = float(config["risk_penalty"])
        mean_reversion = float(config["mean_reversion_threshold"])
        if momentum <= 0.0 or volatility <= 0.0 or risk_penalty <= 0.0:
            raise ValueError(
                "momentum_threshold, volatility_threshold, and "
                "risk_penalty must be positive."
            )
        if mean_reversion >= 0.0:
            raise ValueError("mean_reversion_threshold must be negative.")

        original_momentum = self._signal_engine.MOMENTUM_BUY_THRESHOLD
        original_reversion = self._signal_engine.REVERSION_SELL_THRESHOLD
        original_overrides = self._strategy_overrides
        original_suppress = self._suppress_reports

        try:
            self._strategy_overrides = dict(config)
            self._signal_engine.MOMENTUM_BUY_THRESHOLD = Decimal(
                str(momentum * 100.0)
            )
            self._signal_engine.REVERSION_SELL_THRESHOLD = Decimal(
                str(mean_reversion * 100.0)
            )
            self._execution_engine = ExecutionEngine(
                deterministic=True,
                seed=self._seed,
                cost_model=self._cost_model,
            )
            # 参数搜索不模拟真实等待，并使用固定滑点，确保无随机扰动。
            self._execution_engine._sleep_ms = lambda _milliseconds: None
            self._execution_engine._simulate_slippage = lambda: Decimal("0.002")
            self._risk_engine = RiskEngine()
            self._suppress_reports = True
            return self.run(data)
        finally:
            self._signal_engine.MOMENTUM_BUY_THRESHOLD = original_momentum
            self._signal_engine.REVERSION_SELL_THRESHOLD = original_reversion
            self._strategy_overrides = original_overrides
            self._suppress_reports = original_suppress

    def _print_analysis(self) -> None:
        """打印最近一次回测的绩效报告。"""
        analysis = self.get_analysis()
        print("=== Performance Report ===")
        print(f"Total Return: {analysis['total_return']:.2%}")
        print(f"Max Drawdown: {analysis['max_drawdown']:.2%}")
        print(f"Sharpe Ratio: {analysis['sharpe_ratio']:.2f}")
        print(f"Win Rate: {analysis['win_rate']:.2%}")
        print(f"Profit Factor: {analysis['profit_factor']:.2f}")

    def get_diagnostics(self) -> dict:
        """返回策略诊断报告。

        Returns:
            dict with keys:
                - signal_distribution: dict of signal_type → count
                - total_trades: BUY + SELL + REDUCE 总数
                - hold_ratio: HOLD / total_steps (需要 set_diagnostics_total_steps 先设置)
                - risk_events: RISK_OFF 计数
        """
        total_trades = (
            self.signal_stats["BUY"]
            + self.signal_stats["SELL"]
            + self.signal_stats["REDUCE"]
        )
        total_steps = getattr(self, "_diagnostics_total_steps", 0)
        hold_ratio = (
            self.signal_stats["HOLD"] / total_steps
            if total_steps > 0
            else 0.0
        )
        return {
            "signal_distribution": dict(self.signal_stats),
            "total_trades": total_trades,
            "hold_ratio": hold_ratio,
            "risk_events": self.signal_stats["RISK_OFF"],
        }

    def _print_diagnostics(self) -> None:
        """打印策略诊断报告到 stdout。"""
        diag = self.get_diagnostics()
        dist = diag["signal_distribution"]
        hold_ratio_pct = diag["hold_ratio"] * 100

        print()
        print("=" * 40)
        print("  === Strategy Diagnostics ===")
        print("=" * 40)
        for sig_type in ("BUY", "SELL", "HOLD", "REDUCE", "RISK_OFF"):
            print(f"  {sig_type}: {dist.get(sig_type, 0)}")
        print(f"  Hold Ratio: {hold_ratio_pct:.1f}%")
        print(f"  Total Trades: {diag['total_trades']}")
        print(f"  Risk Events: {diag['risk_events']}")
        print("=" * 40)
        print()

    def run(
        self,
        historical_data: dict[str, list[tuple[Decimal, str]]],
    ) -> MultiSymbolBacktestResult:
        self._last_historical_data = {
            symbol: list(series)
            for symbol, series in historical_data.items()
        }
        # 重置信号统计
        self.signal_stats = {k: 0 for k in self.signal_stats}
        total_steps = sum(len(v) for v in historical_data.values())

        symbol_results: dict[str, BacktestResult] = {}
        for symbol, price_series in historical_data.items():
            symbol_results[symbol] = self._run_single(symbol, price_series)
        total_return = sum(r.total_return for r in symbol_results.values())
        avg_win = (
            sum(r.win_rate for r in symbol_results.values()) / len(symbol_results)
            if symbol_results else 0.0
        )
        total_trades = sum(r.trade_count for r in symbol_results.values())

        # B2: 保存 total_steps 供 get_diagnostics() 使用
        self._diagnostics_total_steps = total_steps

        # B2: 输出策略诊断报告
        if not self._suppress_reports:
            self._print_diagnostics()
            self._print_analysis()

        return MultiSymbolBacktestResult(
            symbol_results=symbol_results,
            total_return=total_return,
            total_return_pct=(
                total_return / self._initial_cash * Decimal("100")
                if self._initial_cash > Decimal("0") else Decimal("0")
            ),
            avg_win_rate=avg_win,
            total_trade_count=total_trades,
        )

    def run_single(
        self,
        symbol: str,
        price_series: list[tuple[Decimal, str]],
    ) -> BacktestResult:
        result = self._run_single(symbol, price_series)
        self._print_analysis()
        return result

    def run_with_split(
        self,
        symbol: str,
        price_series: list[tuple[Decimal, str]],
    ) -> tuple[BacktestResult, BacktestResult, BacktestResult]:
        """运行回测并返回 (full, in_sample, out_sample) 结果。"""
        n = len(price_series)
        split_idx = int(n * float(self._config.validation_split))
        in_sample = price_series[:split_idx]
        out_sample = price_series[split_idx:]

        full = self._run_single(symbol, price_series)
        ins = self._run_single(symbol + "_IN", in_sample) if len(in_sample) >= 5 else full
        outs = self._run_single(symbol + "_OUT", out_sample) if len(out_sample) >= 5 else full

        if len(in_sample) >= 5:
            full.in_sample_return_pct = ins.total_return_pct
        if len(out_sample) >= 5:
            full.out_sample_return_pct = outs.total_return_pct

        return full, ins, outs

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _run_single(
        self,
        symbol: str,
        price_series: list[tuple[Decimal, str]],
    ) -> BacktestResult:
        cfg = self._config
        cash = self._initial_cash
        position_qty = Decimal("0")
        position_avg_cost = Decimal("0")
        position_peak_price = Decimal("0")  # 用于移动止损
        entry_price = Decimal("0")
        equity_curve: list[Decimal] = []
        timestamps: list[str] = []
        trade_records: list[dict[str, Any]] = []
        trade_count = win_count = lose_count = 0
        stop_loss_cnt = take_profit_cnt = trailing_stop_cnt = 0
        total_commission = total_spread = total_slippage = Decimal("0")
        trade_pnls: list[Decimal] = []
        max_loss_trade = Decimal("0")
        max_win_trade = Decimal("0")

        if not price_series:
            self.equity_curve = []
            self.pnl_history = []
            return BacktestResult(initial_cash=self._initial_cash, final_cash=cash, final_equity=cash)

        prices_only = [p for p, _ in price_series]
        atr_series = _compute_atr(prices_only, cfg.atr_period)
        
        # 过度交易抑制状态
        cooldown_until: int = -1                    # 冷却期截止索引
        signal_confirm_count: dict[str, int] = {}   # 信号确认计数 {symbol: count}
        last_action: str | None = None              # 上次操作
        consecutive_buys: int = 0                    # 连续买入计数

        # 趋势锁定：计算 20 日均线
        sma20: list[Decimal] = []
        for j in range(len(prices_only)):
            if j < cfg.trend_lock_days:
                sma20.append(Decimal("0"))
            else:
                sma20.append(sum(prices_only[j-cfg.trend_lock_days:j]) / Decimal(str(cfg.trend_lock_days)))

        for i, (price, ts) in enumerate(price_series):
            from price_provider_v2 import PriceResultV2, PRICE_STATUS_OK
            price_result = PriceResultV2(symbol=symbol, price=price, status=PRICE_STATUS_OK, market_time=ts)
            atr = atr_series[i] if i < len(atr_series) else Decimal("0")

            # ---- 检查止损/止盈 ----
            stop_reason = None
            if position_qty > Decimal("0") and entry_price > Decimal("0"):
                # 固定止损
                loss_pct = (price - entry_price) / entry_price * Decimal("100")
                if loss_pct <= -cfg.stop_loss_pct:
                    stop_reason = "stop_loss"
                    stop_loss_cnt += 1
                # 固定止盈
                elif loss_pct >= cfg.take_profit_pct:
                    stop_reason = "take_profit"
                    take_profit_cnt += 1
                # 移动止损
                if stop_reason is None:
                    if price > position_peak_price:
                        position_peak_price = price
                    if position_peak_price > entry_price * (Decimal("1") + cfg.trailing_stop_activate_pct / Decimal("100")):
                        trail_stop = position_peak_price * (Decimal("1") - cfg.trailing_stop_distance_pct / Decimal("100"))
                        if price <= trail_stop:
                            stop_reason = "trailing_stop"
                            trailing_stop_cnt += 1

            if stop_reason:
                fill_qty = position_qty
                fill_price = price
                proceeds = fill_price * fill_qty
                cost_basis = position_avg_cost * fill_qty
                pnl = proceeds - cost_basis
                cost = self._cost_model.total_cost(fill_price, fill_qty, is_buy=False)
                proceeds_net = proceeds - cost
                pnl_net = proceeds_net - cost_basis
                cash += proceeds_net
                total_commission += cost * Decimal("0.5")
                total_spread += cost * Decimal("0.3")
                total_slippage += cost * Decimal("0.2")
                trade_pnls.append(pnl_net)
                if pnl_net > max_win_trade: max_win_trade = pnl_net
                if pnl_net < max_loss_trade: max_loss_trade = pnl_net
                trade_count += 1
                if pnl_net > Decimal("0"): win_count += 1
                else: lose_count += 1
                trade_records.append({
                    "date": ts, "action": stop_reason, "symbol": symbol,
                    "qty": str(fill_qty), "price": str(fill_price),
                    "pnl": str(pnl_net), "pnl_pct": str(pnl / cost_basis * Decimal("100") if cost_basis > Decimal("0") else Decimal("0")),
                })
                position_qty = Decimal("0")
                position_avg_cost = Decimal("0")
                entry_price = Decimal("0")

            # ---- 信号生成 ----
            if i == 0:
                signal_list = self._signal_engine.evaluate({symbol: price_result})
            else:
                prev_price = price_series[i - 1][0]
                if prev_price > Decimal("0") and atr > Decimal("0"):
                    change_pct = (price - prev_price) / prev_price * Decimal("100")
                    # 用 ATR 动态调整阈值
                    atr_pct = atr / price * Decimal("100")
                    threshold = atr_pct * cfg.atr_buy_threshold
                    strong_threshold = atr_pct * cfg.atr_strong_buy_threshold
                    sell_threshold = atr_pct * Decimal("-1") * abs(cfg.atr_sell_threshold)
                    strong_sell_threshold = atr_pct * Decimal("-1") * abs(cfg.atr_strong_sell_threshold)
                    signal_list = self._signal_engine.evaluate_with_change_pct(symbol, price, change_pct)
                else:
                    signal_list = self._signal_engine.evaluate({symbol: price_result})

                volatility_threshold = self._strategy_overrides.get(
                    "volatility_threshold"
                )
                daily_change = (
                    abs(float((price - prev_price) / prev_price))
                    if prev_price != Decimal("0")
                    else 0.0
                )
                if (
                    volatility_threshold is not None
                    and daily_change >= float(volatility_threshold)
                ):
                    signal_list = [Signal(
                        symbol=symbol,
                        signal_type=SignalType.REDUCE,
                        strength=80,
                        confidence=0.8,
                        reason=(
                            f"Volatility {daily_change:.4f} reached optimizer "
                            f"threshold {float(volatility_threshold):.4f}."
                        ),
                        source="optimizer_config",
                    )]

            if not signal_list:
                equity = cash + position_qty * price
                equity_curve.append(equity)
                timestamps.append(ts)
                continue

            signal = signal_list[0]

            # B2: 记录信号分布统计
            sig_type = signal.signal_type.value
            if sig_type in self.signal_stats:
                self.signal_stats[sig_type] += 1

            risk_decisions = self._risk_engine.evaluate(signal_list)
            risk_decision = risk_decisions[0] if risk_decisions else None

            position_value = position_qty * price
            total_value = cash + position_value
            position_pct = float(position_value / total_value * Decimal("100")) if total_value > Decimal("0") else 0.0

            decision = self._decision_engine.evaluate(signal, risk_decision, position_pct=position_pct)

            # ---- 过度交易抑制 ----
            # 1. 冷却期检查
            if cooldown_until > i:
                # 冷却期内：强制 HOLD
                if decision.action in (DecisionAction.BUY, DecisionAction.SELL, DecisionAction.REDUCE):
                    decision = self._decision_engine.evaluate(
                        Signal(symbol=symbol, signal_type=SignalType.HOLD, strength=10, confidence=0.3,
                               reason=f"Cooldown until day {cooldown_until}", source="backtest"),
                        risk_decision, position_pct=position_pct
                    )

            # 2. BUY 信号确认机制
            if decision.action == DecisionAction.BUY:
                consecutive_buys += 1
                if consecutive_buys < cfg.signal_confirmation:
                    # 未达到确认次数 -> 暂不执行 BUY，改为 HOLD
                    decision = self._decision_engine.evaluate(
                        Signal(symbol=symbol, signal_type=SignalType.HOLD, strength=15, confidence=0.4,
                               reason=f"BUY confirmation {consecutive_buys}/{cfg.signal_confirmation}", source="backtest"),
                        risk_decision, position_pct=position_pct
                    )
            else:
                consecutive_buys = 0

            # 3. 趋势锁定：上涨趋势中禁止 SELL/REDUCE
            if decision.action in (DecisionAction.SELL, DecisionAction.REDUCE) and i >= cfg.trend_lock_days:
                sma = sma20[i]
                if sma > Decimal("0") and price > sma:
                    # 价格在 20 日均线上方 -> 上涨趋势 -> 锁定，不卖出
                    decision = self._decision_engine.evaluate(
                        Signal(symbol=symbol, signal_type=SignalType.HOLD, strength=20, confidence=0.5,
                               reason=f"Trend lock: price ${price:.2f} above SMA20 ${sma:.2f}", source="backtest"),
                        risk_decision, position_pct=position_pct
                    )

            # 记录冷却期
            if decision.action in (DecisionAction.BUY, DecisionAction.SELL, DecisionAction.REDUCE):
                cooldown_until = i + cfg.cooldown_days

            # ---- 动态仓位计算 ----
            requested_qty = cfg.fixed_qty
            if requested_qty is None and decision.action == DecisionAction.BUY:
                stop_dist = cfg.stop_loss_pct / Decimal("100")
                risk_penalty = Decimal(str(
                    self._strategy_overrides.get("risk_penalty", 1.0)
                ))
                risk_cash = total_value * cfg.max_risk_ratio / risk_penalty
                if stop_dist > Decimal("0") and price > Decimal("0"):
                    qty_raw = risk_cash / (price * stop_dist)
                    qty_raw = qty_raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                    max_by_portfolio = (total_value * (cfg.max_position_pct / Decimal("100"))) / price
                    max_by_portfolio = max_by_portfolio.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                    requested_qty = min(qty_raw, max_by_portfolio)
                    if requested_qty < Decimal("1"):
                        requested_qty = Decimal("1")

            ex_result = self._execution_engine.submit_order(decision, price, requested_qty=requested_qty)
            if ex_result and ex_result.status in (OrderStatus.FILLED, OrderStatus.PARTIAL):
                fill_price = ex_result.fill_price or price
                fill_qty = ex_result.filled_qty or Decimal("0")

                if decision.action == DecisionAction.BUY:
                    cost = fill_price * fill_qty
                    tcost = self._cost_model.total_cost(fill_price, fill_qty, is_buy=True)
                    total_commission += tcost * Decimal("0.5")
                    total_spread += tcost * Decimal("0.3")
                    total_slippage += tcost * Decimal("0.2")
                    total_cost = cost + tcost
                    if total_cost <= cash:
                        cash -= total_cost
                        total_cb = position_avg_cost * position_qty + cost
                        position_qty += fill_qty
                        position_avg_cost = total_cb / position_qty if position_qty > Decimal("0") else Decimal("0")
                        entry_price = fill_price
                        position_peak_price = fill_price
                        trade_count += 1
                        trade_records.append({
                            "date": ts, "action": "BUY", "symbol": symbol,
                            "qty": str(fill_qty), "price": str(fill_price),
                            "cost": str(tcost),
                        })

                elif decision.action in (DecisionAction.SELL, DecisionAction.REDUCE):
                    if fill_qty <= position_qty:
                        proceeds = fill_price * fill_qty
                        cost_basis = position_avg_cost * fill_qty
                        pnl = proceeds - cost_basis
                        tcost = self._cost_model.total_cost(fill_price, fill_qty, is_buy=False)
                        total_commission += tcost * Decimal("0.5")
                        total_spread += tcost * Decimal("0.3")
                        total_slippage += tcost * Decimal("0.2")
                        cash += proceeds - tcost
                        position_qty -= fill_qty
                        trade_pnls.append(pnl - tcost)
                        if pnl - tcost > max_win_trade: max_win_trade = pnl - tcost
                        if pnl - tcost < max_loss_trade: max_loss_trade = pnl - tcost
                        trade_count += 1
                        if pnl - tcost > Decimal("0"): win_count += 1
                        else: lose_count += 1
                        trade_records.append({
                            "date": ts, "action": decision.action.value, "symbol": symbol,
                            "qty": str(fill_qty), "price": str(fill_price),
                            "pnl": str(pnl - tcost),
                            "pnl_pct": str(pnl / cost_basis * Decimal("100") if cost_basis > Decimal("0") else Decimal("0")),
                        })
                        if position_qty == Decimal("0"):
                            entry_price = Decimal("0")

            equity = cash + position_qty * price
            equity_curve.append(equity)
            timestamps.append(ts)

        # 收盘平仓
        if position_qty > Decimal("0") and price_series:
            last_price = price_series[-1][0]
            cost_basis = position_avg_cost * position_qty
            pnl = last_price * position_qty - cost_basis
            trade_pnls.append(pnl)
            if pnl > max_win_trade: max_win_trade = pnl
            if pnl < max_loss_trade: max_loss_trade = pnl
            trade_count += 1
            if pnl > Decimal("0"): win_count += 1
            else: lose_count += 1

        # 最终统计
        final_equity = cash + position_qty * (price_series[-1][0] if price_series else Decimal("0"))
        total_return = final_equity - self._initial_cash
        total_return_pct = total_return / self._initial_cash * Decimal("100") if self._initial_cash > Decimal("0") else Decimal("0")
        win_rate = win_count / trade_count if trade_count > 0 else 0.0

        # 盈亏比
        wins = [t for t in trade_pnls if t > Decimal("0")]
        losses = [t for t in trade_pnls if t <= Decimal("0")]
        avg_win = sum(wins) / Decimal(str(len(wins))) if wins else Decimal("0")
        avg_loss = sum(losses) / Decimal(str(len(losses))) if losses else Decimal("0")
        profit_loss_ratio = float(avg_win / abs(avg_loss)) if avg_loss != Decimal("0") else 0.0

        # 最大回撤
        max_drawdown = Decimal("0")
        running_peak = self._initial_cash
        for eq in equity_curve:
            if eq > running_peak: running_peak = eq
            dd = (running_peak - eq) / running_peak * Decimal("100") if running_peak > Decimal("0") else Decimal("0")
            if dd > max_drawdown: max_drawdown = dd

        # 保存最近一次回测的净值曲线与逐笔已实现盈亏
        self.equity_curve = list(equity_curve)
        self.pnl_history = list(trade_pnls)

        return BacktestResult(
            total_return=total_return,
            total_return_pct=total_return_pct,
            win_rate=win_rate,
            profit_loss_ratio=profit_loss_ratio,
            max_drawdown=max_drawdown,
            final_cash=cash,
            final_equity=final_equity,
            trade_count=trade_count,
            win_count=win_count,
            lose_count=lose_count,
            equity_curve=equity_curve,
            timestamps=timestamps,
            initial_cash=self._initial_cash,
            total_commission=total_commission,
            total_spread_cost=total_spread,
            total_slippage_cost=total_slippage,
            avg_win=avg_win,
            avg_loss=avg_loss,
            max_win=max_win_trade,
            max_loss=max_loss_trade,
            stop_loss_triggered=stop_loss_cnt,
            take_profit_triggered=take_profit_cnt,
            trailing_stop_triggered=trailing_stop_cnt,
            trades=trade_records,
        )


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

backtest_engine = BacktestEngine()
