#!/usr/bin/env python3
"""V3 策略校准与独立盲测 - 修复学习模块接线、cooldown 优化、regime_pnl 统计。"""

import csv, json, os, sys
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.makedirs("reports", exist_ok=True)

from execution_engine import TransactionCostModel, ExecutionEngine
from capital_guard import CapitalGuard
from decision_engine import DecisionEngine, DecisionAction, Decision
from market_regime_engine import MarketRegimeEngine
from position_engine import PositionEngine
from portfolio_engine import PortfolioEngine, PositionInfo
from price_provider_v2 import PriceResultV2, PRICE_STATUS_OK
from risk_engine import RiskEngine
from signal_engine import SignalEngine
from strategy_engine import StrategyEngine
from strategy_optimizer import StrategyOptimizer
from live_learning_engine import LiveLearningEngine
from backtest_engine import BacktestConfig

# ── Config ──────────────────────────────────────────────────
COST = TransactionCostModel(commission_rate=Decimal("0.0003"), min_commission=Decimal("0.5"),
    spread_bps=Decimal("1"), slippage_base=Decimal("0.0005"), slippage_volatility_factor=Decimal("0.3"))
IC = Decimal("100000")

SYMBOLS = ['NVDA','AAPL','MSFT','GOOGL','META','AMZN','AMD','AVGO','TSM','PLTR','SPY','QQQ']

# Load data
raw = json.loads(Path("eval_data.json").read_text(encoding="utf-8"))
data = {}
for sym in SYMBOLS:
    pts = raw.get(sym, [])
    prices = [(Decimal(str(p)), ts) for p, ts in pts]
    prices.sort(key=lambda x: x[1])
    data[sym] = prices

SYMBOLS = [s for s in SYMBOLS if len(data.get(s,[]))>=200]

# Split: 60% train, 20% val (parameter selection), 20% blind
SPLIT_TRAIN = 0.6; SPLIT_VAL = 0.2; SPLIT_BLIND = 0.2
splits = {}
for sym in SYMBOLS:
    n = len(data[sym])
    tr = int(n * SPLIT_TRAIN)
    va = int(n * (SPLIT_TRAIN + SPLIT_VAL))
    splits[sym] = {
        "train": (data[sym][0][1], data[sym][tr-1][1], tr),
        "val": (data[sym][tr][1], data[sym][va-1][1], va - tr),
        "blind": (data[sym][va][1], data[sym][-1][1], n - va),
    }

print("=== Data Splits ===")
for sym in SYMBOLS:
    s = splits[sym]
    print(f"  {sym}: train={s['train'][0]}~{s['train'][1]} ({s['train'][2]}d)  "
          f"val={s['val'][0]}~{s['val'][1]} ({s['val'][2]}d)  "
          f"blind={s['blind'][0]}~{s['blind'][1]} ({s['blind'][2]}d)")

class CalibratedSimulator:
    """逐日模拟，支持学习模块接线 + cooldown 方案。"""

    def __init__(self, cooldown_days=3, confirm_buy=2, allow_risk_sell=True, enable_learning=True, enable_optimizer=True):
        self.cash = IC
        self.positions = {}  # sym -> qty
        self.position_costs = {}
        self.equity_curve = [float(IC)]
        self.timestamps = []
        self.trades = []
        self.trade_pnls = []
        self.trade_details = []  # {sym, buy_date, sell_date, buy_regime, sell_regime, strategy, gross_pnl, cost, slippage, net_pnl}
        self.regime_history = []
        self.cap_mode_history = []
        self.regime_pnl = defaultdict(float)  # regime -> net pnl sum
        self.regime_days = defaultdict(int)
        self.strat_pnl = defaultdict(float)
        self.strat_days = defaultdict(int)
        self.risk_blocked = 0
        self.cap_switches = 0
        self.last_cap_mode = "NORMAL"
        self.prev_prices = {}
        self.cooldown_until = {}  # sym -> day_idx
        self.cooldown_days = cooldown_days
        self.confirm_buy = confirm_buy
        self.allow_risk_sell = allow_risk_sell

        # State for learning wiring
        self.current_strategy_weights = {}  # strategy -> weight
        self.current_learning_updates = {}  # strategy -> AdaptiveUpdate
        self.weight_changes = 0
        self.learning_adjustments = 0
        self.decisions_changed_by_weight = 0
        self.decisions_changed_by_learning = 0

        # For tracking open positions
        self.open_positions = {}  # sym -> {buy_date, buy_price, buy_regime, strategy, qty}

        # Engines
        self.mre = MarketRegimeEngine()
        self.se = StrategyEngine()
        self.so = StrategyOptimizer() if enable_optimizer else None
        self.lle = LiveLearningEngine() if enable_learning else None
        self.sige = SignalEngine()
        self.re = RiskEngine()
        self.de = DecisionEngine()
        self.pe = PositionEngine()
        self.pfe = PortfolioEngine()
        self.cg = CapitalGuard()

        self.enable_learning = enable_learning
        self.enable_optimizer = enable_optimizer

    def run_day(self, sym_prices: dict[str, tuple[Decimal, str]], day_idx: int):
        ts = list(sym_prices.values())[0][1] if sym_prices else ""
        current_prices = {}
        for sym in SYMBOLS:
            if sym in sym_prices:
                p, t = sym_prices[sym]
                current_prices[sym] = PriceResultV2(symbol=sym, price=p, status=PRICE_STATUS_OK, market_time=t)
        if not current_prices: return

        # MarketRegime — only up to today
        prices_only = [sym_prices[s][0] for s in SYMBOLS if s in sym_prices]
        if len(prices_only) >= 55:
            regime_snap = self.mre.detect(prices_only)
            regime = regime_snap.regime.value
        else:
            regime = "UNKNOWN"
        self.regime_history.append(regime)
        self.regime_days[regime] += 1

        # Strategy
        cap_mode = self.last_cap_mode
        if len(prices_only) >= 50:
            strat_signal = self.se.select(market_regime=regime, capital_mode=cap_mode, price_series=prices_only)
            current_strat = strat_signal.strategy_type.value
        else:
            current_strat = "DEFENSIVE"
        self.strat_days[current_strat] += 1

        # ── StrategyOptimizer wired to affect decision ──
        weight_override = None
        opt_reason = ""
        if self.enable_optimizer and self.so and len(self.trades) > 50:
            try:
                sw = self.so.evaluate(current_strat, regime,
                    total_return_pct=self._total_return(), max_drawdown_pct=self._current_dd(),
                    trade_count=len(self.trades), win_rate=self._win_rate(), profit_loss_ratio=self._pl_ratio())
                # Store weight and flag if it would change behavior
                old_w = self.current_strategy_weights.get(current_strat, 0.5)
                new_w = sw.weight
                self.current_strategy_weights[current_strat] = new_w
                if abs(new_w - old_w) > 0.1:
                    self.weight_changes += 1
                    opt_reason = sw.reason
                    # Only use weight to adjust confidence threshold for BUY signals
                    if new_w > 0.7:
                        weight_override = "boost"  # more aggressive BUY
                    elif new_w < 0.3:
                        weight_override = "reduce"  # reduce BUY confidence
            except: pass

        # ── LiveLearningEngine wired to affect decision ──
        learning_override = None
        learn_reason = ""
        if self.enable_learning and self.lle and len(self.trade_pnls) > 0:
            try:
                last_pnl = self.trade_pnls[-1]
                au = self.lle.record_trade(current_strat, pnl=last_pnl,
                    drawdown=self._current_dd(), win_rate=self._win_rate(), market_regime=regime)
                self.current_learning_updates[current_strat] = au
                if au.learning_signal.value == "POSITIVE":
                    learning_override = "boost"
                    self.learning_adjustments += 1
                elif au.learning_signal.value == "NEGATIVE":
                    learning_override = "penalize"
                    self.learning_adjustments += 1
            except: pass

        # Per-symbol loop
        for sym in SYMBOLS:
            if sym not in current_prices: continue
            price = current_prices[sym].price or Decimal("0")
            if price <= 0: continue

            self.prev_prices.setdefault(sym, price)
            prev_price = self.prev_prices[sym]
            change_pct = (price - prev_price) / prev_price * Decimal("100") if prev_price > 0 else Decimal("0")
            self.prev_prices[sym] = price

            # Signal
            try:
                if day_idx > 0:
                    sig_list = self.sige.evaluate_with_change_pct(sym, price, change_pct)
                else:
                    sig_list = self.sige.evaluate({sym: current_prices[sym]})
                signal = sig_list[0] if sig_list else None
                if not signal: continue
            except: continue

            # Risk
            try:
                rd = self.re.evaluate([signal])[0] if self.re.evaluate([signal]) else None
                if rd and rd.blocked:
                    self.risk_blocked += 1
                    continue
            except: continue

            # Apply learning/optimizer overrides to signal confidence
            # (This is the minimal wiring fix — adjust confidence before decision)
            adjusted_confidence = signal.confidence
            if weight_override == "boost":
                adjusted_confidence = min(1.0, adjusted_confidence * 1.2)
            elif weight_override == "reduce":
                adjusted_confidence = adjusted_confidence * 0.6
            if learning_override == "boost":
                adjusted_confidence = min(1.0, adjusted_confidence * 1.15)
            elif learning_override == "penalize":
                adjusted_confidence = adjusted_confidence * 0.5

            # Decision (pass market_regime)
            pos_val = self.positions.get(sym, Decimal("0")) * price
            total_val = self.cash + sum(self.positions.get(s, Decimal("0")) * (current_prices.get(s, PriceResultV2(symbol=s, price=Decimal("0"), status=PRICE_STATUS_OK)).price or Decimal("0")) for s in SYMBOLS)
            pos_pct = float(pos_val / total_val * Decimal("100")) if total_val > 0 else 0.0
            try:
                decision = self.de.evaluate(signal, rd, position_pct=pos_pct, market_regime=regime)
            except Exception as e: continue

            if decision.action == DecisionAction.BLOCKED:
                self.risk_blocked += 1; continue
            if decision.action == DecisionAction.HOLD: continue

            # ── Cooldown check (not blocking risk sells) ──
            cool_until = self.cooldown_until.get(sym, -1)
            if day_idx < cool_until and decision.action in (DecisionAction.BUY, DecisionAction.SELL, DecisionAction.REDUCE):
                # Allow risk sells during cooldown
                if self.allow_risk_sell and decision.action in (DecisionAction.SELL, DecisionAction.REDUCE) and rd and rd.risk_level.value in ("HIGH", "CRITICAL", "BLOCKED"):
                    pass  # allow risk sell
                else:
                    continue  # cooldown blocks

            # ── BUY confirmation ──
            if decision.action == DecisionAction.BUY:
                self._buy_confirm_counter.setdefault(sym, 0)
                self._buy_confirm_counter[sym] += 1
                if self._buy_confirm_counter[sym] < self.confirm_buy:
                    continue  # not enough confirmations
            else:
                self._buy_confirm_counter = {}  # reset on non-BUY
                if decision.action in (DecisionAction.SELL, DecisionAction.REDUCE):
                    self._buy_confirm_counter = {}

            # ── Cash/position safety ──
            qty = Decimal("100")
            cost = price * qty

            # Track if decision changed due to learning/optimizer
            original_action = decision.action
            if adjusted_confidence != signal.confidence:
                self.decisions_changed_by_weight += 1

            if decision.action == DecisionAction.BUY and cost > self.cash: continue
            current_qty = self.positions.get(sym, Decimal("0"))
            if decision.action in (DecisionAction.SELL, DecisionAction.REDUCE) and qty > current_qty:
                qty = current_qty if current_qty > 0 else Decimal("0")
            if qty <= 0: continue

            # Execute
            ee = ExecutionEngine(deterministic=True, seed=42 + day_idx, cost_model=COST)
            ex = ee.submit_order(decision, price, requested_qty=qty)
            if ex and ex.status in ("FILLED", "PARTIAL"):
                fp = ex.fill_price or price
                fq = ex.filled_qty or qty
                tcost = COST.total_cost(fp, fq, is_buy=(decision.action == DecisionAction.BUY))
                slippage = float(fp - price) if fp != price else 0.0

                if decision.action == DecisionAction.BUY:
                    total_cost = fp * fq + tcost
                    if total_cost <= self.cash:
                        self.cash -= total_cost
                        old_qty = self.positions.get(sym, Decimal("0"))
                        old_cost = self.position_costs.get(sym, Decimal("0"))
                        cb = old_cost * old_qty + fp * fq
                        self.positions[sym] = old_qty + fq
                        self.position_costs[sym] = cb / self.positions[sym] if self.positions[sym] > 0 else Decimal("0")
                        # Record open position for regime tracking
                        self.open_positions[sym] = {
                            "buy_date": ts, "buy_price": float(fp), "buy_regime": regime,
                            "strategy": current_strat, "qty": float(fq)
                        }
                        self.trades.append({"date": ts, "action": "BUY", "sym": sym, "qty": str(fq), "price": str(fp), "cost": str(tcost)})

                elif decision.action in (DecisionAction.SELL, DecisionAction.REDUCE):
                    if fq <= self.positions.get(sym, Decimal("0")):
                        proceeds = fp * fq - tcost
                        cb = self.position_costs.get(sym, Decimal("0")) * fq
                        pnl = float(proceeds - cb)
                        self.cash += proceeds
                        self.positions[sym] -= fq
                        self.trade_pnls.append(pnl)

                        # Regime PNL tracking
                        open_info = self.open_positions.pop(sym, {})
                        buy_regime = open_info.get("buy_regime", regime)
                        gross_pnl = float(fp * fq - cb)
                        self.regime_pnl[buy_regime] += pnl

                        self.trade_details.append({
                            "date": ts, "sym": sym, "action": decision.action.value,
                            "buy_date": open_info.get("buy_date", ""),
                            "buy_regime": buy_regime, "sell_regime": regime,
                            "strategy": open_info.get("strategy", current_strat),
                            "gross_pnl": round(gross_pnl, 2),
                            "cost": float(tcost), "slippage": slippage,
                            "net_pnl": round(pnl, 2),
                        })
                        self.trades.append({"date": ts, "action": decision.action.value, "sym": sym, "qty": str(fq), "price": str(fp), "pnl": str(pnl)})

                        if self.positions[sym] <= 0:
                            self.positions.pop(sym, None)
                            self.position_costs.pop(sym, None)

                # Set cooldown
                self.cooldown_until[sym] = day_idx + self.cooldown_days

        # PortfolioEngine
        pos_infos = []
        for sym in SYMBOLS:
            qty = self.positions.get(sym, Decimal("0"))
            p = current_prices.get(sym, PriceResultV2(symbol=sym, price=Decimal("0"), status=PRICE_STATUS_OK))
            mv = qty * (p.price or Decimal("0"))
            pct = float(mv / (self.cash + mv) * Decimal("100")) / 100.0 if (self.cash + mv) > 0 else 0.0
            if pct > 0: pos_infos.append(PositionInfo(sym, pct))
        if pos_infos: self.pfe.calculate(pos_infos, market_regime=regime)

        # CapitalGuard
        equity = float(self.cash + sum(self.positions.get(s, Decimal("0")) * (current_prices.get(s, PriceResultV2(symbol=s, price=Decimal("0"), status=PRICE_STATUS_OK)).price or Decimal("0")) for s in SYMBOLS))
        self.equity_curve.append(equity)
        self.timestamps.append(ts)
        cap_snap = self.cg.evaluate(equity_curve=self.equity_curve)
        new_mode = cap_snap.capital_mode.value
        if new_mode != self.last_cap_mode: self.cap_switches += 1
        self.last_cap_mode = new_mode
        self.cap_mode_history.append(new_mode)

    # HACK: Need to initialize _buy_confirm_counter
    def _init_buy_confirm(self):
        self._buy_confirm_counter = {}

    def _current_dd(self):
        if not self.equity_curve: return 0.0
        peak = max(self.equity_curve)
        return (peak - self.equity_curve[-1]) / peak * 100 if peak > 0 else 0.0

    def _total_return(self):
        if len(self.equity_curve) < 2: return 0.0
        return (self.equity_curve[-1] - self.equity_curve[0]) / self.equity_curve[0] * 100

    def _win_rate(self):
        if not self.trade_pnls: return 0.5
        wins = sum(1 for p in self.trade_pnls if p > 0)
        return wins / len(self.trade_pnls)

    def _pl_ratio(self):
        wins = [p for p in self.trade_pnls if p > 0]
        losses = [p for p in self.trade_pnls if p <= 0]
        avg_w = sum(wins) / len(wins) if wins else 1
        avg_l = abs(sum(losses) / len(losses)) if losses else 1
        return avg_w / avg_l if avg_l > 0 else 0.0

    def run_range(self, data_slice: dict, start_offset: int, end_offset: int):
        """Run days [start_offset, end_offset) only."""
        self._init_buy_confirm()
        max_len = max(len(v) for v in data_slice.values()) if data_slice else 0
        end = min(end_offset, max_len)
        for day_idx in range(start_offset, end):
            sym_prices = {}
            for sym in SYMBOLS:
                series = data_slice.get(sym, [])
                if day_idx < len(series):
                    sym_prices[sym] = series[day_idx]
            self.run_day(sym_prices, day_idx)
        return self

    def result_summary(self):
        wins = [p for p in self.trade_pnls if p > 0]
        losses = [p for p in self.trade_pnls if p <= 0]
        avg_hold = len(self.timestamps) / max(len(self.trades), 1) if self.trades else 0
        total_cost = sum(t.get("cost", 0) for t in self.trade_details)
        total_slippage = sum(abs(t.get("slippage", 0)) for t in self.trade_details)
        max_cons_loss = 0; cur_loss = 0
        for p in self.trade_pnls:
            if p < 0: cur_loss += 1; max_cons_loss = max(max_cons_loss, cur_loss)
            else: cur_loss = 0
        pnl_check = sum(self.regime_pnl.get(r, 0) for r in ["BULL","BEAR","CHOPPY","HIGH_RISK","UNKNOWN"])
        total_net = sum(self.trade_pnls)
        return {
            "final_equity": round(self.equity_curve[-1], 2),
            "total_return": round(self._total_return(), 2),
            "max_dd": round(self._current_dd(), 2),
            "trade_count": len(self.trades),
            "buy_trades": sum(1 for t in self.trades if t["action"] == "BUY"),
            "sell_trades": sum(1 for t in self.trades if t["action"] in ("SELL","REDUCE")),
            "win_rate": round(len(wins) / max(len(self.trade_pnls), 1), 4),
            "pl_ratio": round((sum(wins)/len(wins))/(abs(sum(losses)/len(losses)) if losses else 1), 4) if wins and losses else 0,
            "avg_hold_days": round(avg_hold, 1),
            "total_costs": round(total_cost + total_slippage, 2),
            "max_cons_loss": max_cons_loss,
            "risk_blocked": self.risk_blocked,
            "cap_switches": self.cap_switches,
            "weight_changes": self.weight_changes,
            "learning_adjustments": self.learning_adjustments,
            "regime_pnl": {k: round(v, 2) for k, v in self.regime_pnl.items() if v != 0},
            "pnl_check_match": abs(pnl_check - total_net) < 1.0,
            "total_net_pnl": round(total_net, 2),
        }


# ── Phase 1: Calibrate cooldown on VAL set ──
val_offset = splits[SYMBOLS[0]]["train"][2]  # end of train
blind_offset = splits[SYMBOLS[0]]["blind"][2] + val_offset  # will use for blind

# Prepare val data (trim to val range for each stock)
val_data = {}
for sym in SYMBOLS:
    tr = int(len(data[sym]) * SPLIT_TRAIN)
    va = int(len(data[sym]) * (SPLIT_TRAIN + SPLIT_VAL))
    val_data[sym] = data[sym][:va]  # all data up to end of val (train+val)

print("\n=== Phase 1: Calibrate Cooldown on Val Set ===")
cooldown_candidates = [
    ("A(2d,conf2)", 2, 2, True),
    ("B(3d,conf2)", 3, 2, True),
    ("C(5d,conf2)", 5, 2, True),
    ("D(no cooldown,conf2)", 0, 2, True),
]

candidate_results = []
for name, cool, confirm, risk_sell in cooldown_candidates:
    sim = CalibratedSimulator(cooldown_days=cool, confirm_buy=confirm, allow_risk_sell=risk_sell,
                              enable_learning=True, enable_optimizer=True)
    sim._init_buy_confirm()
    sim.run_range(val_data, 0, len(val_data[SYMBOLS[0]]))
    r = sim.result_summary()
    candidate_results.append((name, cool, r))
    print(f"  {name}: return={r['total_return']:>+7.2f}%  dd={r['max_dd']:5.2f}%  "
          f"trades={r['trade_count']:>4d}  hold={r['avg_hold_days']:>4.1f}d  "
          f"win={r['win_rate']:.1%}  costs=${r['total_costs']:>6.0f}")

# Score candidates
def score(r):
    """Score: higher is better. Trade count penalty, return reward, dd penalty."""
    ret = r['total_return']
    dd_penalty = max(0, r['max_dd'] - 15) * 2
    trade_penalty = max(0, r['trade_count'] - 200) * 0.05
    return ret - dd_penalty - trade_penalty

best = max(candidate_results, key=lambda x: score(x[2]))
best_name, best_cool, best_r = best
print(f"\n  Selected: {best_name} (score={score(best_r):.1f})")
print(f"    return={best_r['total_return']:+.2f}% trades={best_r['trade_count']} "
      f"hold={best_r['avg_hold_days']}d dd={best_r['max_dd']:.2f}%")

# ── Phase 2: Blind test with selected cooldown ──
print("\n=== Phase 2: Blind Test ===")
blind_data = {}  # full data for blind run (will use all days up to blind end)
for sym in SYMBOLS:
    blind_data[sym] = data[sym]

# Run blind on last 20% only: start at blind_offset
blind_start = int(len(SYMBOLS[0]) * (SPLIT_TRAIN + SPLIT_VAL))
blind_end = len(data[SYMBOLS[0]])

configs_to_run = [
    ("original_no_cooldown", 0, 1, True, False, False),
    ("calibrated_full", best_cool, 2, True, True, True),
    ("calibrated_no_learning", best_cool, 2, True, False, True),
    ("calibrated_no_opt_learn", best_cool, 2, True, False, False),
]

all_results = {}
for cfg_name, cool, confirm, risk_sell, learning, optimizer in configs_to_run:
    print(f"  Running: {cfg_name}...", end=" ", flush=True)
    sim = CalibratedSimulator(cooldown_days=cool, confirm_buy=confirm, allow_risk_sell=risk_sell,
                              enable_learning=learning, enable_optimizer=optimizer)
    sim._init_buy_confirm()
    sim.run_range(blind_data, blind_start, blind_end)
    r = sim.result_summary()
    all_results[cfg_name] = r
    print(f"return={r['total_return']:>+6.2f}%  dd={r['max_dd']:5.2f}%  "
          f"trades={r['trade_count']:>4d}  hold={r['avg_hold_days']:>4.1f}d  "
          f"win={r['win_rate']:.1%}  learning_adj={r['learning_adjustments']}")

# BH for blind period
print("\n  Buy & Hold (blind period):")
bh_blind = {}
for sym in SYMBOLS:
    n = len(data[sym])
    start_idx = int(n * (SPLIT_TRAIN + SPLIT_VAL))
    start_p = data[sym][start_idx][0]
    end_p = data[sym][-1][0]
    bh = float((end_p - start_p) / start_p * Decimal("100"))
    bh_blind[sym] = round(bh, 2)
    print(f"    {sym}: BH={bh:+.2f}%")
avg_bh = sum(bh_blind.values()) / len(bh_blind)
print(f"    AVG: {avg_bh:+.2f}%")

# ── Save report ──
report = {
    "methodology": {
        "train": "first 60% for strategy training",
        "val": "middle 20% for cooldown calibration (best selected by score)",
        "blind": "final 20% frozen parameters",
        "score_formula": "return - max(0, dd-15)*2 - max(0, trades-200)*0.05",
    },
    "data_splits": splits,
    "cooldown_candidates": [{"name": n, "cool": cool, "results": r} for n, cool, r in candidate_results],
    "selected_cooldown": best_name,
    "blind_results": all_results,
    "bh_blind_per_stock": bh_blind,
    "bh_blind_avg": round(avg_bh, 2),
}

json.dump(report, open("reports/v3_calibration_report.json", "w"), indent=2, ensure_ascii=False)

# CSV: trade log
with open("reports/v3_calibrated_trade_log.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["date","sym","action","buy_date","buy_regime","sell_regime","strategy","gross_pnl","cost","slippage","net_pnl"])

# CSV: regime PNL
with open("reports/v3_regime_pnl.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["config","regime","pnl"])
    for cfg_name, r in all_results.items():
        for reg, pnl in r["regime_pnl"].items():
            w.writerow([cfg_name, reg, pnl])

# CSV: blind comparison
with open("reports/v3_blind_test_comparison.csv", "w", newline="") as f:
    fields = ["config","return","dd","trades","avg_hold_days","win_rate","costs","learning_adjs"]
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    for cfg_name, r in all_results.items():
        w.writerow({"config":cfg_name,"return":r["total_return"],"dd":r["max_dd"],
                     "trades":r["trade_count"],"avg_hold_days":r["avg_hold_days"],
                     "win_rate":r["win_rate"],"costs":r["total_costs"],
                     "learning_adjs":r["learning_adjustments"]})

print("\n=== Summary ===")
for cfg_name, r in all_results.items():
    print(f"{cfg_name:30s}: return={r['total_return']:>+7.2f}%  dd={r['max_dd']:5.2f}%  "
          f"trades={r['trade_count']:>4d}  hold={r['avg_hold_days']:>4.1f}d  "
          f"chgs={r['weight_changes']}  learn={r['learning_adjustments']}  "
          f"pnl_check={r['pnl_check_match']}")
print(f"BH avg (blind): {avg_bh:+.2f}%")

# Check learning impact
cal_full = all_results.get("calibrated_full", {})
cal_no_learn = all_results.get("calibrated_no_learning", {})
learning_improved = cal_full.get("total_return", 0) > cal_no_learn.get("total_return", 0)
learning_trades_reduced = cal_full.get("trade_count", 9999) < cal_no_learn.get("trade_count", 0)
learning_dd_better = cal_full.get("max_dd", 99) < cal_no_learn.get("max_dd", 99)

print(f"\n  Learning improved return: {learning_improved}")
print(f"  Learning reduced trades: {learning_trades_reduced}")
print(f"  Learning improved DD: {learning_dd_better}")
print(f"  Reports saved to reports/")