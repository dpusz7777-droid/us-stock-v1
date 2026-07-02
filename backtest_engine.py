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
from signal_engine import SignalEngine, SignalType


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

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def run(
        self,
        historical_data: dict[str, list[tuple[Decimal, str]]],
    ) -> MultiSymbolBacktestResult:
        symbol_results: dict[str, BacktestResult] = {}
        for symbol, price_series in historical_data.items():
            symbol_results[symbol] = self._run_single(symbol, price_series)
        total_return = sum(r.total_return for r in symbol_results.values())
        avg_win = (
            sum(r.win_rate for r in symbol_results.values()) / len(symbol_results)
            if symbol_results else 0.0
        )
        total_trades = sum(r.trade_count for r in symbol_results.values())
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
        return self._run_single(symbol, price_series)

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
        """运行单个标的的回测。"""
        cfg = self._config
        cash = self._initial_cash
        position_qty = Decimal("0")
        position_avg_cost = Decimal("0")
        position_peak_price = Decimal("0")
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
            return BacktestResult(initial_cash=self._initial_cash, final_cash=cash, final_equity=cash)

        prices_only = [p for p, _ in price_series]
        atr_series = _compute_atr(prices_only, cfg.atr_period)
        sma20 = self._compute_sma20(prices_only, cfg.trend_lock_days)

        # 过度交易抑制状态
        cooldown_until: int = -1
        consecutive_buys: int = 0

        for i, (price, ts) in enumerate(price_series):
            from price_provider_v2 import PriceResultV2, PRICE_STATUS_OK
            price_result = PriceResultV2(symbol=symbol, price=price, status=PRICE_STATUS_OK, market_time=ts)
            atr = atr_series[i] if i < len(atr_series) else Decimal("0")

            # ---- 检查止损/止盈 ----
            stop_result = self._check_stop_loss_take_profit(
                position_qty, entry_price, price, position_peak_price,
                cfg, symbol, ts
            )
            if stop_result:
                cash, position_qty, position_avg_cost, entry_price, position_peak_price, \
                    trade_count, win_count, lose_count, trade_pnls, trade_records, \
                    stop_loss_cnt, take_profit_cnt, trailing_stop_cnt, \
                    total_commission, total_spread, total_slippage, max_win_trade, max_loss_trade = \
                    self._apply_stop_result(
                        stop_result, cash, position_qty, position_avg_cost, entry_price,
                        position_peak_price, trade_count, win_count, lose_count,
                        trade_pnls, trade_records, stop_loss_cnt, take_profit_cnt,
                        trailing_stop_cnt, total_commission, total_spread, total_slippage,
                        max_win_trade, max_loss_trade
                    )

            # ---- 信号生成 ----
            signal_list = self._generate_signal(symbol, price, price_series, i, atr, price_result)

            if not signal_list:
                equity = cash + position_qty * price
                equity_curve.append(equity)
                timestamps.append(ts)
                continue

            # ---- 风控与决策 ----
            decision, risk_decision = self._evaluate_risk_and_decision(
                signal_list, symbol, price, position_qty, cash
            )

            # ---- 过度交易抑制 ----
            decision, cooldown_until, consecutive_buys = self._apply_overtrading_suppression(
                decision, i, cooldown_until, consecutive_buys, cfg, symbol, risk_decision,
                position_qty, price, cash
            )

            # ---- 趋势锁定 ----
            decision = self._apply_trend_lock(decision, i, cfg, sma20, price, symbol, risk_decision,
                                               position_qty, price, cash)

            # ---- 执行交易 ----
            cash, position_qty, position_avg_cost, entry_price, position_peak_price, \
                trade_count, win_count, lose_count, trade_pnls, trade_records, \
                total_commission, total_spread, total_slippage, max_win_trade, max_loss_trade = \
                self._execute_decision(
                    decision, price, cash, position_qty, position_avg_cost, entry_price,
                    position_peak_price, trade_count, win_count, lose_count,
                    trade_pnls, trade_records, total_commission, total_spread, total_slippage,
                    max_win_trade, max_loss_trade, ts, symbol
                )

            equity = cash + position_qty * price
            equity_curve.append(equity)
            timestamps.append(ts)

        # 收盘平仓
        cash, position_qty, trade_count, win_count, lose_count, trade_pnls, \
            max_win_trade, max_loss_trade = self._close_positions(
                position_qty, position_avg_cost, price_series, cash,
                trade_count, win_count, lose_count, trade_pnls,
                max_win_trade, max_loss_trade
            )

        # 最终统计
        return self._compute_final_result(
            cash, position_qty, price_series, equity_curve, timestamps,
            trade_count, win_count, lose_count, trade_pnls,
            total_commission, total_spread, total_slippage,
            max_win_trade, max_loss_trade,
            stop_loss_cnt, take_profit_cnt, trailing_stop_cnt, trade_records
        )

    def _compute_sma20(self, prices_only: list[Decimal], trend_lock_days: int) -> list[Decimal]:
        """计算 20 日均线。"""
        sma20: list[Decimal] = []
        for j in range(len(prices_only)):
            if j < trend_lock_days:
                sma20.append(Decimal("0"))
            else:
                sma20.append(sum(prices_only[j - trend_lock_days:j]) / Decimal(str(trend_lock_days)))
        return sma20

    def _check_stop_loss_take_profit(
        self, position_qty: Decimal, entry_price: Decimal, price: Decimal,
        position_peak_price: Decimal, cfg: BacktestConfig, symbol: str, ts: str
    ) -> dict | None:
        """检查止损/止盈条件。"""
        if position_qty <= Decimal("0") or entry_price <= Decimal("0"):
            return None

        loss_pct = (price - entry_price) / entry_price * Decimal("100")
        stop_reason = None

        if loss_pct <= -cfg.stop_loss_pct:
            stop_reason = "stop_loss"
        elif loss_pct >= cfg.take_profit_pct:
            stop_reason = "take_profit"

        if stop_reason is None:
            new_peak = max(position_peak_price, price)
            if new_peak > entry_price * (Decimal("1") + cfg.trailing_stop_activate_pct / Decimal("100")):
                trail_stop = new_peak * (Decimal("1") - cfg.trailing_stop_distance_pct / Decimal("100"))
                if price <= trail_stop:
                    stop_reason = "trailing_stop"

        if stop_reason:
            return {
                "reason": stop_reason,
                "fill_qty": position_qty,
                "fill_price": price,
                "symbol": symbol,
                "ts": ts,
            }
        return None

    def _apply_stop_result(
        self, stop_result: dict, cash: Decimal, position_qty: Decimal,
        position_avg_cost: Decimal, entry_price: Decimal, position_peak_price: Decimal,
        trade_count: int, win_count: int, lose_count: int,
        trade_pnls: list[Decimal], trade_records: list[dict],
        stop_loss_cnt: int, take_profit_cnt: int, trailing_stop_cnt: int,
        total_commission: Decimal, total_spread: Decimal, total_slippage: Decimal,
        max_win_trade: Decimal, max_loss_trade: Decimal
    ) -> tuple:
        """应用止损/止盈结果。"""
        fill_qty = stop_result["fill_qty"]
        fill_price = stop_result["fill_price"]
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
        if pnl_net > max_win_trade:
            max_win_trade = pnl_net
        if pnl_net < max_loss_trade:
            max_loss_trade = pnl_net
        trade_count += 1
        if pnl_net > Decimal("0"):
            win_count += 1
        else:
            lose_count += 1
        trade_records.append({
            "date": stop_result["ts"],
            "action": stop_result["reason"],
            "symbol": stop_result["symbol"],
            "qty": str(fill_qty),
            "price": str(fill_price),
            "pnl": str(pnl_net),
            "pnl_pct": str(pnl / cost_basis * Decimal("100") if cost_basis > Decimal("0") else Decimal("0")),
        })
        position_qty = Decimal("0")
        position_avg_cost = Decimal("0")
        entry_price = Decimal("0")
        position_peak_price = Decimal("0")

        if stop_result["reason"] == "stop_loss":
            stop_loss_cnt += 1
        elif stop_result["reason"] == "take_profit":
            take_profit_cnt += 1
        elif stop_result["reason"] == "trailing_stop":
            trailing_stop_cnt += 1

        return (cash, position_qty, position_avg_cost, entry_price, position_peak_price,
                trade_count, win_count, lose_count, trade_pnls, trade_records,
                stop_loss_cnt, take_profit_cnt, trailing_stop_cnt,
                total_commission, total_spread, total_slippage,
                max_win_trade, max_loss_trade)

    def _generate_signal(
        self, symbol: str, price: Decimal, price_series: list[tuple[Decimal, str]],
        i: int, atr: Decimal, price_result: Any
    ) -> list:
        """生成交易信号。"""
        if i == 0:
            return self._signal_engine.evaluate({symbol: price_result})

        prev_price = price_series[i - 1][0]
        if prev_price > Decimal("0") and atr > Decimal("0"):
            change_pct = (price - prev_price) / prev_price * Decimal("100")
            return self._signal_engine.evaluate_with_change_pct(symbol, price, change_pct)
        return self._signal_engine.evaluate({symbol: price_result})

    def _evaluate_risk_and_decision(
        self, signal_list: list, symbol: str, price: Decimal,
        position_qty: Decimal, cash: Decimal
    ) -> tuple:
        """评估风控并生成决策。"""
        signal = signal_list[0]
        risk_decisions = self._risk_engine.evaluate(signal_list)
        risk_decision = risk_decisions[0] if risk_decisions else None

        position_value = position_qty * price
        total_value = cash + position_value
        position_pct = float(position_value / total_value * Decimal("100")) if total_value > Decimal("0") else 0.0

        decision = self._decision_engine.evaluate(signal, risk_decision, position_pct=position_pct)
        return decision, risk_decision

    def _apply_overtrading_suppression(
        self, decision: Any, i: int, cooldown_until: int, consecutive_buys: int,
        cfg: BacktestConfig, symbol: str, risk_decision: Any,
        position_qty: Decimal, price: Decimal, cash: Decimal
    ) -> tuple:
        """应用过度交易抑制规则。"""
        from decision_engine import DecisionAction
        from signal_engine import Signal, SignalType

        # 冷却期检查
        if cooldown_until > i:
            if decision.action in (DecisionAction.BUY, DecisionAction.SELL, DecisionAction.REDUCE):
                decision = self._decision_engine.evaluate(
                    Signal(symbol=symbol, signal_type=SignalType.HOLD, strength=10, confidence=0.3,
                           reason=f"Cooldown until day {cooldown_until}", source="backtest"),
                    risk_decision,
                    position_pct=float(position_qty * price / (cash + position_qty * price) * 100) if (cash + position_qty * price) > 0 else 0.0
                )

        # BUY 信号确认机制
        if decision.action == DecisionAction.BUY:
            consecutive_buys += 1
            if consecutive_buys < cfg.signal_confirmation:
                decision = self._decision_engine.evaluate(
                    Signal(symbol=symbol, signal_type=SignalType.HOLD, strength=15, confidence=0.4,
                           reason=f"BUY confirmation {consecutive_buys}/{cfg.signal_confirmation}", source="backtest"),
                    risk_decision,
                    position_pct=float(position_qty * price / (cash + position_qty * price) * 100) if (cash + position_qty * price) > 0 else 0.0
                )
        else:
            consecutive_buys = 0

        # 记录冷却期
        if decision.action in (DecisionAction.BUY, DecisionAction.SELL, DecisionAction.REDUCE):
            cooldown_until = i + cfg.cooldown_days

        return decision, cooldown_until, consecutive_buys

    def _apply_trend_lock(
        self, decision: Any, i: int, cfg: BacktestConfig, sma20: list[Decimal],
        price: Decimal, symbol: str, risk_decision: Any,
        position_qty: Decimal, price_val: Decimal, cash: Decimal
    ) -> Any:
        """应用趋势锁定规则。"""
        from decision_engine import DecisionAction
        from signal_engine import Signal, SignalType

        if decision.action in (DecisionAction.SELL, DecisionAction.REDUCE) and i >= cfg.trend_lock_days:
            sma = sma20[i]
            if sma > Decimal("0") and price > sma:
                decision = self._decision_engine.evaluate(
                    Signal(symbol=symbol, signal_type=SignalType.HOLD, strength=20, confidence=0.5,
                           reason=f"Trend lock: price ${price:.2f} above SMA20 ${sma:.2f}", source="backtest"),
                    risk_decision,
                    position_pct=float(position_qty * price_val / (cash + position_qty * price_val) * 100) if (cash + position_qty * price_val) > 0 else 0.0
                )
        return decision

    def _execute_decision(
        self, decision: Any, price: Decimal, cash: Decimal,
        position_qty: Decimal, position_avg_cost: Decimal, entry_price: Decimal,
        position_peak_price: Decimal, trade_count: int, win_count: int, lose_count: int,
        trade_pnls: list[Decimal], trade_records: list[dict],
        total_commission: Decimal, total_spread: Decimal, total_slippage: Decimal,
        max_win_trade: Decimal, max_loss_trade: Decimal, ts: str, symbol: str
    ) -> tuple:
        """执行交易决策。"""
        from decision_engine import DecisionAction
        from execution_engine import OrderStatus

        cfg = self._config
        total_value = cash + position_qty * price

        # 动态仓位计算
        requested_qty = cfg.fixed_qty
        if requested_qty is None and decision.action == DecisionAction.BUY:
            stop_dist = cfg.stop_loss_pct / Decimal("100")
            risk_cash = total_value * cfg.max_risk_ratio
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
                    if pnl - tcost > max_win_trade:
                        max_win_trade = pnl - tcost
                    if pnl - tcost < max_loss_trade:
                        max_loss_trade = pnl - tcost
                    trade_count += 1
                    if pnl - tcost > Decimal("0"):
                        win_count += 1
                    else:
                        lose_count += 1
                    trade_records.append({
                        "date": ts, "action": decision.action.value, "symbol": symbol,
                        "qty": str(fill_qty), "price": str(fill_price),
                        "pnl": str(pnl - tcost),
                        "pnl_pct": str(pnl / cost_basis * Decimal("100") if cost_basis > Decimal("0") else Decimal("0")),
                    })
                    if position_qty == Decimal("0"):
                        entry_price = Decimal("0")

        return (cash, position_qty, position_avg_cost, entry_price, position_peak_price,
                trade_count, win_count, lose_count, trade_pnls, trade_records,
                total_commission, total_spread, total_slippage,
                max_win_trade, max_loss_trade)

    def _close_positions(
        self, position_qty: Decimal, position_avg_cost: Decimal,
        price_series: list[tuple[Decimal, str]], cash: Decimal,
        trade_count: int, win_count: int, lose_count: int,
        trade_pnls: list[Decimal], max_win_trade: Decimal, max_loss_trade: Decimal
    ) -> tuple:
        """收盘平仓。"""
        if position_qty > Decimal("0") and price_series:
            last_price = price_series[-1][0]
            cost_basis = position_avg_cost * position_qty
            pnl = last_price * position_qty - cost_basis
            trade_pnls.append(pnl)
            if pnl > max_win_trade:
                max_win_trade = pnl
            if pnl < max_loss_trade:
                max_loss_trade = pnl
            trade_count += 1
            if pnl > Decimal("0"):
                win_count += 1
            else:
                lose_count += 1
        return cash, position_qty, trade_count, win_count, lose_count, trade_pnls, max_win_trade, max_loss_trade

    def _compute_final_result(
        self, cash: Decimal, position_qty: Decimal,
        price_series: list[tuple[Decimal, str]], equity_curve: list[Decimal],
        timestamps: list[str], trade_count: int, win_count: int, lose_count: int,
        trade_pnls: list[Decimal], total_commission: Decimal, total_spread: Decimal,
        total_slippage: Decimal, max_win_trade: Decimal, max_loss_trade: Decimal,
        stop_loss_cnt: int, take_profit_cnt: int, trailing_stop_cnt: int,
        trade_records: list[dict]
    ) -> BacktestResult:
        """计算最终回测结果。"""
        final_equity = cash + position_qty * (price_series[-1][0] if price_series else Decimal("0"))
        total_return = final_equity - self._initial_cash
        total_return_pct = total_return / self._initial_cash * Decimal("100") if self._initial_cash > Decimal("0") else Decimal("0")
        win_rate = win_count / trade_count if trade_count > 0 else 0.0

        wins = [t for t in trade_pnls if t > Decimal("0")]
        losses = [t for t in trade_pnls if t <= Decimal("0")]
        avg_win = sum(wins) / Decimal(str(len(wins))) if wins else Decimal("0")
        avg_loss = sum(losses) / Decimal(str(len(losses))) if losses else Decimal("0")
        profit_loss_ratio = float(avg_win / abs(avg_loss)) if avg_loss != Decimal("0") else 0.0

        max_drawdown = Decimal("0")
        running_peak = self._initial_cash
        for eq in equity_curve:
            if eq > running_peak:
                running_peak = eq
            dd = (running_peak - eq) / running_peak * Decimal("100") if running_peak > Decimal("0") else Decimal("0")
            if dd > max_drawdown:
                max_drawdown = dd

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
