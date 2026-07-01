#!/usr/bin/env python3
"""V3 校准V2 — 修复回撤0%错误、完成缺失配置、审计学习模块实际影响"""

import csv, json, os, sys
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.makedirs("reports", exist_ok=True)

from execution_engine import TransactionCostModel, ExecutionEngine
from capital_guard import CapitalGuard
from decision_engine import DecisionEngine, DecisionAction
from market_regime_engine import MarketRegimeEngine
from position_engine import PositionEngine
from portfolio_engine import PortfolioEngine, PositionInfo
from price_provider_v2 import PriceResultV2, PRICE_STATUS_OK
from risk_engine import RiskEngine
from signal_engine import SignalEngine
from strategy_engine import StrategyEngine, StrategySignal, StrategyType
from strategy_optimizer import StrategyOptimizer
from live_learning_engine import LiveLearningEngine
from backtest_engine import BacktestConfig

COST = TransactionCostModel(commission_rate=Decimal("0.0003"), min_commission=Decimal("0.5"),
    spread_bps=Decimal("1"), slippage_base=Decimal("0.0005"), slippage_volatility_factor=Decimal("0.3"))
IC = Decimal("100000")

SYMBOLS = ['NVDA','AAPL','MSFT','GOOGL','META','AMZN','AMD','AVGO','TSM','PLTR','SPY','QQQ']

raw = json.loads(Path("eval_data.json").read_text(encoding="utf-8"))
data = {}
for sym in SYMBOLS:
    pts = raw.get(sym, [])
    prices = [(Decimal(str(p)), ts) for p, ts in pts]
    prices.sort(key=lambda x: x[1])
    data[sym] = prices

SYMBOLS = [s for s in SYMBOLS if len(data.get(s,[]))>=200]
SPLIT_TRAIN=0.6; SPLIT_VAL=0.2; SPLIT_BLIND=0.2

def _compute_dd(equity_curve):
    if len(equity_curve) < 2: return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for val in equity_curve:
        if val > peak: peak = val
        dd = (peak - val) / peak * 100 if peak > 0 else 0.0
        if dd > max_dd: max_dd = dd
    return max_dd

class SimV2:
    def __init__(self, cooldown_days=0, confirm_buy=2, allow_risk_sell=True,
                 enable_learning=True, enable_optimizer=True):
        self.cash = IC
        self.positions = {}; self.position_costs = {}
        self.equity_curve = [float(IC)]
        self.timestamps = []
        self.trades = []; self.trade_pnls = []; self.trade_details = []
        self.regime_history = []; self.cap_mode_history = []
        self.regime_pnl = defaultdict(float)
        self.regime_days = defaultdict(int)
        self.strat_pnl = defaultdict(float); self.strat_days = defaultdict(int)
        self.risk_blocked = 0; self.cap_switches = 0
        self.last_cap_mode = "NORMAL"; self.prev_prices = {}
        self.cooldown_until = {}; self.open_positions = {}
        self.cooldown_days = cooldown_days; self.confirm_buy = confirm_buy
        self.allow_risk_sell = allow_risk_sell
        self._buy_confirm_counter = {}
        self.current_strategy_weights = {}; self.current_learning_updates = {}
        self.weight_changes = 0; self.learning_adjustments = 0
        self.learning_changed_decision = 0
        self.optimizer_changed_decision = 0
        self.mre = MarketRegimeEngine(); self.se = StrategyEngine()
        self.so = StrategyOptimizer() if enable_optimizer else None
        self.lle = LiveLearningEngine() if enable_learning else None
        self.sige = SignalEngine(); self.re = RiskEngine()
        self.de = DecisionEngine(); self.pe = PositionEngine()
        self.pfe = PortfolioEngine(); self.cg = CapitalGuard()
        self.enable_learning = enable_learning; self.enable_optimizer = enable_optimizer

    def _market_value(self, current_prices):
        """Returns Decimal: total market value of all positions."""
        total = Decimal("0")
        for sym in SYMBOLS:
            qty = self.positions.get(sym, Decimal("0"))
            if qty > 0:
                p = current_prices.get(sym, PriceResultV2(symbol=sym, price=Decimal("0"), status=PRICE_STATUS_OK))
                total += qty * (p.price or Decimal("0"))
        return total

    def run_day(self, sym_prices, day_idx):
        ts = list(sym_prices.values())[0][1] if sym_prices else ""
        current_prices = {}
        for sym in SYMBOLS:
            if sym in sym_prices:
                p, t = sym_prices[sym]
                current_prices[sym] = PriceResultV2(symbol=sym, price=p, status=PRICE_STATUS_OK, market_time=t)
        if not current_prices: return

        prices_only = [sym_prices[s][0] for s in SYMBOLS if s in sym_prices]
        if len(prices_only) >= 55:
            regime = self.mre.detect(prices_only).regime.value
        else:
            regime = "UNKNOWN"
        self.regime_history.append(regime); self.regime_days[regime] += 1

        cap_mode = self.last_cap_mode
        if len(prices_only) >= 50:
            current_strat = self.se.select(market_regime=regime, capital_mode=cap_mode, price_series=prices_only).strategy_type.value
        else:
            current_strat = "DEFENSIVE"
        self.strat_days[current_strat] += 1

        weight_override = None
        if self.enable_optimizer and self.so and len(self.trades) > 20:
            try:
                sw = self.so.evaluate(current_strat, regime, total_return_pct=self._total_return_from_curve(),
                    max_drawdown_pct=_compute_dd(self.equity_curve), trade_count=len(self.trades),
                    win_rate=self._win_rate(), profit_loss_ratio=self._pl_ratio())
                old_w = self.current_strategy_weights.get(current_strat, 0.5)
                new_w = sw.weight
                self.current_strategy_weights[current_strat] = new_w
                if abs(new_w - old_w) > 0.05:
                    self.weight_changes += 1
                    weight_override = "boost" if new_w > 0.7 else ("reduce" if new_w < 0.3 else None)
            except: pass

        learning_override = None
        if self.enable_learning and self.lle and len(self.trade_pnls) > 0:
            try:
                last_pnl = self.trade_pnls[-1]
                au = self.lle.record_trade(current_strat, pnl=last_pnl,
                    drawdown=_compute_dd(self.equity_curve), win_rate=self._win_rate(), market_regime=regime)
                self.current_learning_updates[current_strat] = au
                if au.learning_signal.value == "POSITIVE":
                    learning_override = "boost"; self.learning_adjustments += 1
                elif au.learning_signal.value == "NEGATIVE":
                    learning_override = "penalize"; self.learning_adjustments += 1
            except: pass

        for sym in SYMBOLS:
            if sym not in current_prices: continue
            price = current_prices[sym].price or Decimal("0")
            if price <= 0: continue
            self.prev_prices.setdefault(sym, price)
            prev = self.prev_prices[sym]
            chg = (price - prev) / prev * Decimal("100") if prev > 0 else Decimal("0")
            self.prev_prices[sym] = price

            try:
                sl = self.sige.evaluate_with_change_pct(sym, price, chg) if day_idx > 0 else self.sige.evaluate({sym: current_prices[sym]})
                sig = sl[0] if sl else None
                if not sig: continue
            except: continue

            try:
                rd = self.re.evaluate([sig])[0] if self.re.evaluate([sig]) else None
                if rd and rd.blocked: self.risk_blocked += 1; continue
            except: continue

            adj_conf = sig.confidence
            if weight_override == "boost": adj_conf = min(1.0, adj_conf * 1.2)
            elif weight_override == "reduce": adj_conf = adj_conf * 0.6
            if learning_override == "boost": adj_conf = min(1.0, adj_conf * 1.15)
            elif learning_override == "penalize": adj_conf = adj_conf * 0.5

            # Use Decimal for total_val, pos_val
            total_val = self.cash + self._market_value(current_prices)
            pos_val = self.positions.get(sym, Decimal("0")) * price
            pos_pct = float(pos_val / total_val * Decimal("100")) if total_val > Decimal("0") else 0.0

            orig_decision = self.de.evaluate(sig, rd, position_pct=pos_pct, market_regime=regime)
            if adj_conf != sig.confidence:
                from signal_engine import Signal
                adj_sig = Signal(symbol=sig.symbol, signal_type=sig.signal_type, strength=sig.strength,
                                 confidence=adj_conf, reason=sig.reason + " (adjusted)", source=sig.source)
                decision = self.de.evaluate(adj_sig, rd, position_pct=pos_pct, market_regime=regime)
                if decision.action != orig_decision.action:
                    if learning_override: self.learning_changed_decision += 1
                    if weight_override: self.optimizer_changed_decision += 1
            else:
                decision = orig_decision

            if decision.action == DecisionAction.BLOCKED: self.risk_blocked += 1; continue
            if decision.action == DecisionAction.HOLD: continue

            cool = self.cooldown_until.get(sym, -1)
            if day_idx < cool and decision.action in (DecisionAction.BUY, DecisionAction.SELL, DecisionAction.REDUCE):
                if self.allow_risk_sell and decision.action in (DecisionAction.SELL, DecisionAction.REDUCE) and rd and rd.risk_level.value in ("HIGH","CRITICAL","BLOCKED"):
                    pass
                else: continue

            if decision.action == DecisionAction.BUY:
                self._buy_confirm_counter.setdefault(sym, 0)
                self._buy_confirm_counter[sym] += 1
                if self._buy_confirm_counter[sym] < self.confirm_buy: continue
            else:
                self._buy_confirm_counter = {}

            qty = Decimal("100"); cost = price * qty
            if decision.action == DecisionAction.BUY and cost > self.cash: continue
            cq = self.positions.get(sym, Decimal("0"))
            if decision.action in (DecisionAction.SELL, DecisionAction.REDUCE) and qty > cq: qty = cq if cq > 0 else Decimal("0")
            if qty <= 0: continue

            ee = ExecutionEngine(deterministic=True, seed=42 + day_idx, cost_model=COST)
            ex = ee.submit_order(decision, price, qty)
            if ex and ex.status in ("FILLED","PARTIAL"):
                fp = ex.fill_price or price; fq = ex.filled_qty or qty
                tcost = COST.total_cost(fp, fq, is_buy=(decision.action==DecisionAction.BUY))
                slip = float(fp - price) if fp != price else 0.0

                if decision.action == DecisionAction.BUY:
                    tc = fp * fq + tcost
                    if tc <= self.cash:
                        self.cash -= tc
                        oq = self.positions.get(sym, Decimal("0"))
                        oc = self.position_costs.get(sym, Decimal("0"))
                        cb = oc * oq + fp * fq
                        self.positions[sym] = oq + fq
                        self.position_costs[sym] = cb / self.positions[sym] if self.positions[sym] > 0 else Decimal("0")
                        self.open_positions[sym] = {"buy_date":ts, "buy_price":float(fp), "buy_regime":regime,
                            "strategy":current_strat, "qty":float(fq)}
                        self.trades.append({"date":ts,"action":"BUY","sym":sym,"qty":str(fq),"price":str(fp),"cost":str(tcost)})

                elif decision.action in (DecisionAction.SELL, DecisionAction.REDUCE):
                    if fq <= self.positions.get(sym, Decimal("0")):
                        proceeds = fp * fq - tcost
                        cb = self.position_costs.get(sym, Decimal("0")) * fq
                        pnl = float(proceeds - cb)
                        self.cash += proceeds; self.positions[sym] -= fq
                        self.trade_pnls.append(pnl)
                        oi = self.open_positions.pop(sym, {})
                        br = oi.get("buy_regime", regime)
                        gp = float(fp * fq - cb)
                        self.regime_pnl[br] += pnl
                        self.trade_details.append({"date":ts,"sym":sym,"action":decision.action.value,
                            "buy_date":oi.get("buy_date",""),"buy_regime":br,"sell_regime":regime,
                            "strategy":oi.get("strategy",current_strat),"gross_pnl":round(gp,2),
                            "cost":float(tcost),"slippage":slip,"net_pnl":round(pnl,2)})
                        self.trades.append({"date":ts,"action":decision.action.value,"sym":sym,"qty":str(fq),"price":str(fp),"pnl":str(pnl)})
                        if self.positions[sym] <= 0:
                            self.positions.pop(sym,None); self.position_costs.pop(sym,None)
                self.cooldown_until[sym] = day_idx + self.cooldown_days

        # AFTER trades: equity = cash + market value
        total_equity = self.cash + self._market_value(current_prices)
        self.equity_curve.append(float(total_equity))
        self.timestamps.append(ts)

        # Portfolio
        pos_infos = []
        for sym in SYMBOLS:
            qty = self.positions.get(sym, Decimal("0"))
            p = current_prices.get(sym, PriceResultV2(symbol=sym, price=Decimal("0"), status=PRICE_STATUS_OK))
            mv = qty * (p.price or Decimal("0"))
            pct = float(mv / (self.cash + mv) * Decimal("100")) / 100.0 if (self.cash + mv) > Decimal("0") else 0.0
            if pct > 0: pos_infos.append(PositionInfo(sym, pct))
        if pos_infos: self.pfe.calculate(pos_infos, market_regime=regime)

        cap = self.cg.evaluate(equity_curve=self.equity_curve)
        nm = cap.capital_mode.value
        if nm != self.last_cap_mode: self.cap_switches += 1
        self.last_cap_mode = nm; self.cap_mode_history.append(nm)

    def _total_return_from_curve(self):
        if len(self.equity_curve) < 2: return 0.0
        return (self.equity_curve[-1] - self.equity_curve[0]) / self.equity_curve[0] * 100

    def _win_rate(self):
        if not self.trade_pnls: return 0.5
        return sum(1 for p in self.trade_pnls if p > 0) / len(self.trade_pnls)

    def _pl_ratio(self):
        wins = [p for p in self.trade_pnls if p > 0]
        losses = [p for p in self.trade_pnls if p <= 0]
        aw = sum(wins)/len(wins) if wins else 1
        al = abs(sum(losses)/len(losses)) if losses else 1
        return aw/al if al > 0 else 0.0

    def run_range(self, data_slice, start_off, end_off):
        max_len = max(len(v) for v in data_slice.values()) if data_slice else 0
        end = min(end_off, max_len)
        for idx in range(start_off, end):
            sp = {}
            for sym in SYMBOLS:
                series = data_slice.get(sym, [])
                if idx < len(series): sp[sym] = series[idx]
            self.run_day(sp, idx)
        return self

    def result_summary(self):
        wins = [p for p in self.trade_pnls if p > 0]
        losses = [p for p in self.trade_pnls if p <= 0]
        avg_hold = len(self.timestamps) / max(len(self.trades), 1) if self.trades else 0
        tc = sum(abs(t.get("cost",0)) for t in self.trade_details)
        ts = sum(abs(t.get("slippage",0)) for t in self.trade_details)
        max_cl = 0; cur = 0
        for p in self.trade_pnls:
            if p < 0: cur += 1; max_cl = max(max_cl, cur)
            else: cur = 0
        total_net = sum(self.trade_pnls)
        rp_sum = sum(self.regime_pnl.values())
        dd = _compute_dd(self.equity_curve)
        ret = self._total_return_from_curve()
        return {
            "final_equity": round(self.equity_curve[-1], 2),
            "total_return": round(ret, 2),
            "max_dd": round(dd, 2),
            "trade_count": len(self.trades),
            "buy_trades": sum(1 for t in self.trades if t["action"]=="BUY"),
            "sell_trades": sum(1 for t in self.trades if t["action"] in ("SELL","REDUCE")),
            "win_rate": round(len(wins)/max(len(self.trade_pnls),1),4),
            "pl_ratio": round((sum(wins)/len(wins))/(abs(sum(losses)/len(losses)) if losses else 1),4) if wins and losses else 0,
            "avg_hold_days": round(avg_hold, 1),
            "total_costs": round(tc+ts, 2),
            "max_cons_loss": max_cl,
            "risk_blocked": self.risk_blocked,
            "cap_switches": self.cap_switches,
            "weight_changes": self.weight_changes,
            "learning_adjustments": self.learning_adjustments,
            "learning_changed_decisions": self.learning_changed_decision,
            "optimizer_changed_decisions": self.optimizer_changed_decision,
            "regime_pnl": {k: round(v,2) for k,v in self.regime_pnl.items() if v != 0},
            "pnl_check_match": abs(rp_sum - total_net) < 1.0,
            "total_net_pnl": round(total_net, 2),
            "equity_curve_len": len(self.equity_curve),
            "equity_peak": round(max(self.equity_curve), 2) if self.equity_curve else 0,
            "equity_min": round(min(self.equity_curve), 2) if self.equity_curve else 0,
        }

blind_start = int(len(data[SYMBOLS[0]]) * (SPLIT_TRAIN + SPLIT_VAL))
blind_end = len(data[SYMBOLS[0]])
print(f"=== Blind period: days {blind_start} to {blind_end} ({blind_end-blind_start} days) ===")

configs = [
    ("calibrated_full",              0, 2, True, True,  True),
    ("calibrated_no_learning",       0, 2, True, False, True),
    ("calibrated_no_opt_learn",      0, 2, True, False, False),
    ("original_no_cooldown",         0, 1, True, False, False),
]

all_results = {}
for cfg_name, cool, confirm, risk_sell, learning, optimizer in configs:
    print(f"\nRunning: {cfg_name}...", flush=True)
    try:
        sim = SimV2(cooldown_days=cool, confirm_buy=confirm, allow_risk_sell=risk_sell,
                    enable_learning=learning, enable_optimizer=optimizer)
        sim.run_range(data, blind_start, blind_end)
        r = sim.result_summary()
        all_results[cfg_name] = r
        print(f"  ret={r['total_return']:>+7.2f}%  dd={r['max_dd']:5.2f}%  trades={r['trade_count']:>4d}  "
              f"hold={r['avg_hold_days']:>4.1f}d  win={r['win_rate']:.1%}  "
              f"learn_chg={r['learning_changed_decisions']}  opt_chg={r['optimizer_changed_decisions']}  "
              f"peak=${r['equity_peak']:,.0f}  min=${r['equity_min']:,.0f}", flush=True)
    except Exception as e:
        import traceback
        print(f"  FAILED: {e}\n{traceback.format_exc()}", flush=True)
        all_results[cfg_name] = {"error": str(e)}

print("\nBuy & Hold (blind period):")
bh_blind = {}
for sym in SYMBOLS:
    sp = data[sym][blind_start][0]; ep = data[sym][-1][0]
    bh = float((ep - sp) / sp * Decimal("100"))
    bh_blind[sym] = round(bh, 2)
avg_bh = sum(bh_blind.values()) / len(bh_blind)
print(f"  AVG BH: {avg_bh:+.2f}%")

years = blind_end / 252
for cfg_name, r in all_results.items():
    if "error" in r: continue
    tps = r["trade_count"] / len(SYMBOLS) / years if years > 0 else 0
    tpm = r["trade_count"] / (years * 12) if years > 0 else 0
    print(f"\n{cfg_name}: {r['trade_count']} trades over {years:.1f}y across {len(SYMBOLS)} stocks = "
          f"{tps:.1f} trades/stock/year ({tpm:.1f}/month)")

report = {
    "methodology": "V2 fix: Decimal equity, peak-to-trough dd, learning/optimizer change tracking",
    "blind_period": {"start_idx": blind_start, "days": blind_end-blind_start, "years": round(years,1)},
    "blind_results": all_results,
    "bh_blind_per_stock": bh_blind,
    "bh_blind_avg": round(avg_bh, 2),
}
json.dump(report, open("reports/v3_calibration_report.json","w"), indent=2, ensure_ascii=False)
print(f"\nSummary:")
for cfg, r in all_results.items():
    if "error" in r: print(f"  {cfg}: ERROR: {r['error']}")
    else: print(f"  {cfg}: ret={r['total_return']:+.2f}% dd={r['max_dd']:.2f}% trades={r['trade_count']} learn_chg={r['learning_changed_decisions']}")
print(f"  BH avg: {avg_bh:+.2f}%")