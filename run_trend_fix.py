#!/usr/bin/env python3
"""V3 趋势持有策略修复 + 完整校准验证"""

import csv, json, os, sys
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.makedirs("reports", exist_ok=True)

from execution_engine import TransactionCostModel, ExecutionEngine
from capital_guard import CapitalGuard, CapitalMode
from decision_engine import DecisionEngine, DecisionAction, Decision
from market_regime_engine import MarketRegimeEngine, MarketRegime
from position_engine import PositionEngine
from portfolio_engine import PortfolioEngine, PositionInfo
from price_provider_v2 import PriceResultV2, PRICE_STATUS_OK
from risk_engine import RiskEngine
from signal_engine import SignalEngine, Signal, SignalType
from strategy_engine import StrategyEngine
from live_learning_engine import LiveLearningEngine
from strategy_optimizer import StrategyOptimizer

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

# ── Helper: SMA with no future leak ──
def sma(prices, idx, period):
    if idx < period-1: return Decimal("0")
    return sum(prices[idx-period+1:idx+1]) / Decimal(str(period))

def peak_since_entry(price_history: list[Decimal], entry_idx: int, current_idx: int) -> Decimal:
    if entry_idx >= current_idx or entry_idx < 0: return Decimal("0")
    return max(price_history[entry_idx:current_idx+1])

class TrendSimulator:
    """模拟器 - 支持趋势持有 + 退出原因跟踪。"""
    
    def __init__(self, trend_exit_pct=12, enable_trend=True):
        self.cash = IC; self.positions = {}; self.position_costs = {}
        self.equity_curve = [float(IC)]; self.timestamps = []
        self.trades = []; self.trade_pnls = []; self.trade_details = []
        self.exit_reasons = []  # each sell records reason
        self.regime_history = []; self.cap_mode_history = []
        self.regime_pnl = defaultdict(float); self.regime_days = defaultdict(int)
        self.risk_blocked = 0; self.cap_switches = 0
        self.last_cap_mode = "NORMAL"; self.prev_prices = {}
        self._buy_confirm_counter = {}
        self.open_positions = {}  # sym -> {entry_idx, entry_price, peak_price}
        self.buy_confirm = 2; self.sell_confirm = 2
        self.trend_exit_pct = trend_exit_pct  # exit at peak drop %
        self.enable_trend = enable_trend  # enable trend protection
        self.mre = MarketRegimeEngine(); self.se = StrategyEngine()
        self.sige = SignalEngine(); self.re = RiskEngine()
        self.de = DecisionEngine(); self.pe = PositionEngine()
        self.pfe = PortfolioEngine(); self.cg = CapitalGuard()

    def _market_value(self, cp):
        total = Decimal("0")
        for sym in SYMBOLS:
            q = self.positions.get(sym, Decimal("0"))
            if q > 0:
                p = cp.get(sym, PriceResultV2(symbol=sym, price=Decimal("0"), status=PRICE_STATUS_OK)).price or Decimal("0")
                total += q * p
        return total

    def run_day(self, sp, day_idx, price_idx=None):
        """price_idx = actual index in full data for SMA calculations"""
        if price_idx is None: price_idx = day_idx
        ts = list(sp.values())[0][1] if sp else ""
        cp = {}
        for sym in SYMBOLS:
            if sym in sp:
                p, t = sp[sym]; cp[sym] = PriceResultV2(symbol=sym, price=p, status=PRICE_STATUS_OK, market_time=t)
        if not cp: return
        
        po = [sp[s][0] for s in SYMBOLS if s in sp]
        if len(po) >= 55:
            regime = self.mre.detect(po).regime.value
        else:
            regime = "UNKNOWN"
        self.regime_history.append(regime); self.regime_days[regime] += 1
        
        cap_mode = self.last_cap_mode
        if len(po) >= 50:
            cur_strat = self.se.select(market_regime=regime, capital_mode=cap_mode, price_series=po).strategy_type.value
        else:
            cur_strat = "DEFENSIVE"
        
        # ── Trend protection: check for uptrend ──
        is_uptrend = False
        if self.enable_trend and regime == "BULL" and cap_mode != "LOCKDOWN":
            for sym in SYMBOLS:
                if sym in self.positions and self.positions[sym] > 0:
                    full_prices = [p for p,_ in data.get(sym,[])]
                    if price_idx >= 199:
                        sma50 = sum(full_prices[price_idx-49:price_idx+1]) / Decimal("50")
                        sma200 = sum(full_prices[price_idx-199:price_idx+1]) / Decimal("200")
                        sma20 = sum(full_prices[price_idx-19:price_idx+1]) / Decimal("20")
                        cur_p = full_prices[price_idx] if price_idx < len(full_prices) else full_prices[-1]
                        if (cur_p > sma50 and sma50 > sma200 and len(full_prices) >= price_idx+1 and
                            len(full_prices) >= price_idx+1):
                            # Recent 20 day trend slope
                            if len(full_prices) >= price_idx-19:
                                slope20 = sma20 - sum(full_prices[price_idx-39:price_idx-19]) / Decimal("20") if price_idx >= 39 else Decimal("1")
                                if slope20 > 0:
                                    is_uptrend = True
                                    break
        
        for sym in SYMBOLS:
            if sym not in cp: continue
            price = cp[sym].price or Decimal("0")
            if price <= 0: continue
            self.prev_prices.setdefault(sym, price)
            prev = self.prev_prices[sym]; chg = (price-prev)/prev*Decimal("100") if prev>0 else Decimal("0")
            self.prev_prices[sym] = price
            
            # Update peak for open positions
            if sym in self.open_positions:
                op = self.open_positions[sym]
                if price > op["peak_price"]: op["peak_price"] = price
            
            # ── Check exit conditions ──
            exit_reason = None
            if sym in self.positions and self.positions[sym] > 0 and sym in self.open_positions:
                op = self.open_positions[sym]
                # 1. Risk blocked exit
                if regime == "HIGH_RISK" and cap_mode == "LOCKDOWN":
                    exit_reason = "risk_forced"
                if exit_reason is None and Decimal(str(op["peak_price"])) > 0:
                    drop = (Decimal(str(op["peak_price"])) - price) / Decimal(str(op["peak_price"])) * Decimal("100")
                    if drop >= Decimal(str(self.trend_exit_pct)):
                        exit_reason = f"peak_drop_{self.trend_exit_pct}pct"
                # 3. 3 days below SMA50
                if exit_reason is None:
                    full_prices = [p for p,_ in data.get(sym,[])]
                    if price_idx >= 49:
                        sma50 = sum(full_prices[price_idx-49:price_idx+1]) / Decimal("50")
                        if price < sma50 and self.prev_prices.get(f"_{sym}_below50", 0) >= 2:
                            exit_reason = "below_sma50_3d"
                        elif price < sma50:
                            self.prev_prices[f"_{sym}_below50"] = self.prev_prices.get(f"_{sym}_below50", 0) + 1
                        else:
                            self.prev_prices[f"_{sym}_below50"] = 0
                # 4. SMA20 crosses below SMA50
                if exit_reason is None and price_idx >= 50:
                    full_prices = [p for p,_ in data.get(sym,[])]
                    sma20v = sum(full_prices[price_idx-19:price_idx+1]) / Decimal("20")
                    sma50v = sum(full_prices[price_idx-49:price_idx+1]) / Decimal("50")
                    if sma20v < sma50v:
                        exit_reason = "sma20_below_sma50"
            
            if exit_reason:
                self._execute_exit(sym, price, ts, exit_reason)
                continue
            
            # Signal
            try:
                sl = self.sige.evaluate_with_change_pct(sym, price, chg) if day_idx>0 else self.sige.evaluate({sym: cp[sym]})
                sig = sl[0] if sl else None
                if not sig: continue
            except: continue
            
            # Risk
            try:
                rd = self.re.evaluate([sig])[0] if self.re.evaluate([sig]) else None
                if rd and rd.blocked: self.risk_blocked += 1; continue
            except: continue
            
            # ── Trend protection: SELL/REDUCE → HOLD in uptrend ──
            use_sig = sig
            if is_uptrend and self.enable_trend and sig.signal_type in (SignalType.SELL, SignalType.REDUCE):
                use_sig = Signal(symbol=sym, signal_type=SignalType.HOLD, strength=20, confidence=0.6,
                    reason=f"Trend hold {sig.reason}", source="trend_protect")
            
            # Decision
            total_val = self.cash + self._market_value(cp)
            pos_val = self.positions.get(sym, Decimal("0")) * price
            pos_pct = float(pos_val / total_val * Decimal("100")) if total_val > 0 else 0.0
            decision = self.de.evaluate(use_sig, rd, position_pct=pos_pct, market_regime=regime)
            if decision.action == DecisionAction.BLOCKED: self.risk_blocked += 1; continue
            if decision.action == DecisionAction.HOLD: continue
            
            # BUY/Sell confirmation
            if decision.action == DecisionAction.BUY:
                self._buy_confirm_counter.setdefault(sym,0)
                self._buy_confirm_counter[sym] += 1
                if self._buy_confirm_counter[sym] < self.buy_confirm: continue
            elif decision.action in (DecisionAction.SELL, DecisionAction.REDUCE) and not exit_reason:
                # SELL needs confirmation too
                continue  # simplified: skip single sell signals, only exit via conditions
            
            qty = Decimal("100"); cost = price * qty
            if decision.action == DecisionAction.BUY and cost > self.cash: continue
            cq = self.positions.get(sym, Decimal("0"))
            if decision.action in (DecisionAction.SELL, DecisionAction.REDUCE) and qty > cq: qty = cq if cq>0 else Decimal("0")
            if qty <= 0: continue
            
            ee = ExecutionEngine(deterministic=True, seed=42+day_idx, cost_model=COST)
            ex = ee.submit_order(decision, price, qty)
            if ex and ex.status in ("FILLED","PARTIAL"):
                fp = ex.fill_price or price; fq = ex.filled_qty or qty
                tcost = COST.total_cost(fp,fq, is_buy=(decision.action==DecisionAction.BUY))
                slip = float(fp-price) if fp!=price else 0.0
                if decision.action == DecisionAction.BUY:
                    tc = fp*fq + tcost
                    if tc <= self.cash:
                        self.cash -= tc
                        oq = self.positions.get(sym, Decimal("0"))
                        oc = self.position_costs.get(sym, Decimal("0"))
                        cb = oc*oq + fp*fq
                        self.positions[sym] = oq+fq
                        self.position_costs[sym] = cb/self.positions[sym] if self.positions[sym]>0 else Decimal("0")
                        self.open_positions[sym] = {"entry_idx": price_idx, "entry_price": float(price),
                            "peak_price": float(price), "buy_date": ts}
                        self.trades.append({"date":ts,"action":"BUY","sym":sym,"qty":str(fq),"price":str(fp)})
                elif decision.action in (DecisionAction.SELL, DecisionAction.REDUCE):
                    if fq <= self.positions.get(sym, Decimal("0")):
                        proceeds = fp*fq - tcost
                        cb = self.position_costs.get(sym, Decimal("0")) * fq
                        pnl = float(proceeds - cb)
                        self.cash += proceeds; self.positions[sym] -= fq
                        self.trade_pnls.append(pnl)
                        oi = self.open_positions.pop(sym, {})
                        self.regime_pnl[regime] += pnl
                        self.exit_reasons.append(exit_reason or "sell_signal")
                        self.trades.append({"date":ts,"action":decision.action.value,"sym":sym,"qty":str(fq),"price":str(fp),"pnl":str(pnl)})
                        if self.positions[sym] <= 0: self.positions.pop(sym,None); self.position_costs.pop(sym,None)
                    self._buy_confirm_counter = {}
        
        eq = float(self.cash + self._market_value(cp))
        self.equity_curve.append(eq); self.timestamps.append(ts)
        cap = self.cg.evaluate(equity_curve=self.equity_curve)
        nm = cap.capital_mode.value
        if nm != self.last_cap_mode: self.cap_switches += 1
        self.last_cap_mode = nm; self.cap_mode_history.append(nm)

    def _execute_exit(self, sym, price, ts, reason):
        qty = self.positions.get(sym, Decimal("0"))
        if qty <= 0: return
        fp = price; fq = qty
        tcost = COST.total_cost(fp, fq, is_buy=False)
        proceeds = fp*fq - tcost
        cb = self.position_costs.get(sym, Decimal("0")) * fq
        pnl = float(proceeds - cb)
        self.cash += proceeds; self.positions[sym] -= fq
        self.trade_pnls.append(pnl)
        oi = self.open_positions.pop(sym, {})
        self.regime_pnl[self.regime_history[-1] if self.regime_history else "UNKNOWN"] += pnl
        self.exit_reasons.append(reason)
        self.trades.append({"date":ts,"action":"EXIT","sym":sym,"qty":str(fq),"price":str(fp),"pnl":str(pnl),"reason":reason})
        self._buy_confirm_counter = {}
        if self.positions[sym] <= 0: self.positions.pop(sym,None); self.position_costs.pop(sym,None)

    def run_range(self, ds, start_off, end_off):
        max_len = max(len(v) for v in ds.values()) if ds else 0
        end = min(end_off, max_len)
        for idx in range(start_off, end):
            sp = {}
            for sym in SYMBOLS:
                series = ds.get(sym, [])
                if idx < len(series): sp[sym] = series[idx]
            self.run_day(sp, idx, price_idx=idx)
        return self

    def _dd(self):
        if len(self.equity_curve)<2: return 0.0
        peak=self.equity_curve[0]; md=0.0
        for v in self.equity_curve:
            if v>peak: peak=v
            dd=(peak-v)/peak*100 if peak>0 else 0
            if dd>md: md=dd
        return md

    def summary(self):
        w=[p for p in self.trade_pnls if p>0]; l=[p for p in self.trade_pnls if p<=0]
        ah = len(self.timestamps)/max(len(self.trades),1) if self.trades else 0
        tc = sum(abs(t.get("cost",0)) for t in getattr(self,'trade_details',[])) if hasattr(self,'trade_details') else 0
        mc=0; cu=0
        for p in self.trade_pnls:
            if p<0: cu+=1; mc=max(mc,cu)
            else: cu=0
        ret=(self.equity_curve[-1]-self.equity_curve[0])/self.equity_curve[0]*100 if len(self.equity_curve)>=2 else 0
        er = defaultdict(int)
        for r in self.exit_reasons: er[r]+=1
        return {"final_equity":round(self.equity_curve[-1],2),"return":round(ret,2),
            "dd":round(self._dd(),2),"trades":len(self.trades),"peak":round(max(self.equity_curve),2),
            "min":round(min(self.equity_curve),2),"hold":round(ah,1),
            "win":round(len(w)/max(len(self.trade_pnls),1),4),"costs":round(tc,2),
            "max_cons_loss":mc,"exit_reasons":dict(er)}

# ── Phase 1: Calibrate T1/T2/T3 on train+val ──
train_end = int(len(data[SYMBOLS[0]]) * 0.6)
val_end = int(len(data[SYMBOLS[0]]) * 0.8)
print(f"=== Calibration on train+val (days 0-{val_end}) ===")
results_t = {}
for label, exit_pct in [("T1(8%)",8), ("T2(12%)",12), ("T3(15%)",15)]:
    sim = TrendSimulator(trend_exit_pct=exit_pct, enable_trend=True)
    sim.run_range(data, 0, val_end)
    r = sim.summary()
    results_t[label] = r
    print(f"  {label}: ret={r['return']:>+7.2f}%  dd={r['dd']:5.2f}%  trades={r['trades']:>4d}  hold={r['hold']:>4.1f}d  win={r['win']:.1%}")

# Also run baseline (no trend) on val only
print("\n  Baseline (no trend):")
sim_base = TrendSimulator(trend_exit_pct=12, enable_trend=False)
sim_base.run_range(data, 0, val_end)
r_base = sim_base.summary()
results_t["Baseline"] = r_base
print(f"  Baseline: ret={r_base['return']:>+7.2f}%  dd={r_base['dd']:5.2f}%  trades={r_base['trades']:>4d}  hold={r_base['hold']:>4.1f}d  win={r_base['win']:.1%}")

# Score: prefer higher ret, lower dd, reasonable trades
def score(r):
    return r['return'] - max(0, r['dd']-15)*1.5 - max(0, r['trades']-200)*0.02
best_t = max(results_t.items(), key=lambda kv: score(kv[1]))
best_name, best_r = best_t
print(f"\n  Selected: {best_name} (score={score(best_r):.1f})")
best_exit_pct = 8 if "8%" in best_name else (12 if "12%" in best_name else 15)

# ── Phase 2: Run 5 configs on blind (review) ──
blind_start = val_end
blind_end = len(data[SYMBOLS[0]])
print(f"\n=== Blind Review (days {blind_start}-{blind_end}) ===")

configs = [
    ("trend_best",         best_exit_pct, True, True, False, False),
    ("trend_no_learn",     best_exit_pct, True, True, False, False),
    ("trend_no_trend",     best_exit_pct, True, False, False, False),
    ("baseline_no_trend",  best_exit_pct, False, True, False, False),
]

all_results = {}
for cfg_name, exit_pct, enable_trend, learning, optimizer, _ in configs:
    print(f"  Running: {cfg_name}...", end=" ", flush=True)
    try:
        sim = TrendSimulator(trend_exit_pct=exit_pct, enable_trend=enable_trend)
        sim.run_range(data, blind_start, blind_end)
        r = sim.summary()
        all_results[cfg_name] = r
        print(f"ret={r['return']:>+7.2f}%  dd={r['dd']:5.2f}%  trades={r['trades']:>4d}  hold={r['hold']:>4.1f}d  win={r['win']:.1%}")
        if r['exit_reasons']:
            print(f"    exits: {dict(list(r['exit_reasons'].items())[:5])}")
    except Exception as e:
        import traceback; traceback.print_exc()
        all_results[cfg_name] = {"error": str(e)}
        print(f"FAILED: {e}")

# BH
bh_blind = {}
for sym in SYMBOLS:
    sp = data[sym][blind_start][0]; ep = data[sym][-1][0]
    bh_blind[sym] = round(float((ep-sp)/sp*Decimal("100")), 2)
avg_bh = sum(bh_blind.values())/len(bh_blind)
print(f"\n  Buy & Hold avg: {avg_bh:+.2f}%")

# ── Walk-forward validation ──
print(f"\n=== Walk-Forward Validation ===")
wf_results = []
windows = [(0, int(0.4*len(SYMBOLS[0])), int(0.6*len(SYMBOLS[0]))),
           (int(0.2*len(SYMBOLS[0])), int(0.6*len(SYMBOLS[0])), int(0.8*len(SYMBOLS[0])))]
for train_start, train_end, test_end in windows:
    sim = TrendSimulator(trend_exit_pct=best_exit_pct, enable_trend=True)
    sim.run_range(data, 0, test_end)
    # Use last 20% of this window as pseudo-blind
    pseudo_start = max(train_end, test_end - int(0.15*test_end))
    train_ret = (sim.equity_curve[train_end] - sim.equity_curve[0])/sim.equity_curve[0]*100 if len(sim.equity_curve)>train_end else 0
    test_ret = (sim.equity_curve[-1] - sim.equity_curve[train_end])/sim.equity_curve[train_end]*100 if len(sim.equity_curve)>train_end else 0
    bh_train = bh_blind if test_end>1000 else None
    wf_results.append({"window":f"{train_start}-{test_end}","train_ret":round(train_ret,2),"test_ret":round(test_ret,2)})
    print(f"  window {train_start}-{test_end}: train={train_ret:+.2f}% test={test_ret:+.2f}%")

# ── Save report ──
report = {
    "methodology": "Trend fix: uptrend holds SELL->HOLD, exits via peak_drop/sma50_cross/sma20_death",
    "calibration_stage": f"train 0-{train_end} + val {train_end}-{val_end} for T1/T2/T3 selection",
    "blind_stage": f"frozen params on {blind_start}-{blind_end}",
    "calibration_results": results_t,
    "selected_trend_exit": best_name,
    "blind_results": all_results,
    "bh_blind_avg": round(avg_bh, 2),
    "walk_forward": wf_results,
}
json.dump(report, open("reports/v3_trend_strategy_report.json","w"), indent=2, ensure_ascii=False)
print(f"\n=== Summary ===")
for cfg, r in all_results.items():
    if "error" in r: print(f"  {cfg}: ERROR")
    else: print(f"  {cfg}: ret={r['return']:+.2f}% dd={r['dd']:.2f}% trades={r['trades']} hold={r['hold']}d")
print(f"  BH avg: {avg_bh:+.2f}%")
print(f"Best trend exit: {best_name}")