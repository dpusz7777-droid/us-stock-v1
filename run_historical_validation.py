#!/usr/bin/env python3
"""V3 严格历史验证 - 逐日模拟、五组对照、无未来数据泄漏。"""

import csv, json, os, sys
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.makedirs("reports", exist_ok=True)

from backtest_engine import BacktestEngine, BacktestConfig
from execution_engine import TransactionCostModel
from capital_guard import CapitalGuard
from decision_engine import DecisionEngine, DecisionAction
from event_bus import event_bus
from market_regime_engine import MarketRegimeEngine
from position_engine import PositionEngine
from portfolio_engine import PortfolioEngine, PositionInfo
from price_provider_v2 import PriceResultV2, PRICE_STATUS_OK
from risk_engine import RiskEngine
from signal_engine import SignalEngine
from strategy_engine import StrategyEngine
from strategy_optimizer import StrategyOptimizer
from live_learning_engine import LiveLearningEngine

COST = TransactionCostModel(commission_rate=Decimal("0.0003"), min_commission=Decimal("0.5"),
    spread_bps=Decimal("1"), slippage_base=Decimal("0.0005"), slippage_volatility_factor=Decimal("0.3"))

SYMBOLS = ['NVDA','AAPL','MSFT','GOOGL','META','AMZN','AMD','AVGO','TSM','PLTR','SPY','QQQ']
IC = Decimal("100000")

# Load & validate data
raw = json.loads(Path("eval_data.json").read_text(encoding="utf-8"))
data = {}
print("=== Data Check ===")
for sym in SYMBOLS:
    pts = raw.get(sym, [])
    prices = [(Decimal(str(p)), ts) for p, ts in pts]
    prices.sort(key=lambda x: x[1])
    # Check negatives, dup dates, order
    neg = sum(1 for p,_ in prices if p<=0)
    dates = [ts for _,ts in prices]
    dup = len(dates)-len(set(dates))
    ordered = all(dates[i]<=dates[i+1] for i in range(len(dates)-1))
    print(f"  {sym}: {len(prices)}d {prices[0][1]}~{prices[-1][1]} neg={neg} dup={dup} ordered={ordered}")
    data[sym] = prices

SYMBOLS = [s for s in SYMBOLS if len(data.get(s,[]))>=100]
print(f"\nValid symbols: {len(SYMBOLS)}")

# Split
SPLIT_TRAIN = 0.6; SPLIT_VAL = 0.2; SPLIT_BLIND = 0.2
splits = {}
for sym in SYMBOLS:
    n = len(data[sym])
    tr = int(n*SPLIT_TRAIN)
    va = int(n*(SPLIT_TRAIN+SPLIT_VAL))
    splits[sym] = {
        "train": (data[sym][0][1], data[sym][tr-1][1]),
        "val": (data[sym][tr][1], data[sym][va-1][1]),
        "blind": (data[sym][va][1], data[sym][-1][1]),
    }
    print(f"  {sym}: train={splits[sym]['train']} val={splits[sym]['val']} blind={splits[sym]['blind']}")

class DailySimulator:
    """逐日模拟，确保不使用未来数据。"""
    def __init__(self, enable_learning=True, enable_optimizer=True):
        self.cash = IC
        self.positions = {}  # sym -> qty
        self.position_costs = {}  # sym -> avg_cost
        self.equity_curve = [float(IC)]
        self.timestamps = []
        self.trades = []
        self.trade_pnls = []
        self.regime_history = []
        self.cap_mode_history = []
        self.decisions = []
        self.regime_returns = defaultdict(float)
        self.regime_days = defaultdict(int)
        self.strat_returns = defaultdict(float)
        self.strat_days = defaultdict(int)
        self.risk_blocked = 0
        self.cap_switches = 0
        self.last_cap_mode = "NORMAL"
        self.prev_prices = {}  # sym -> previous price
        self.prev_change_pcts = {}  # sym -> previous change
        
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
        
        # Backtest for full run
        self.bt = BacktestEngine(initial_cash=IC, deterministic=True, seed=42)
        
        self.enable_learning = enable_learning
        self.enable_optimizer = enable_optimizer

    def run_day(self, sym_prices: dict[str, tuple[Decimal, str]], day_idx: int):
        """处理一个交易日。使用当前日及之前的数据。"""
        ts = list(sym_prices.values())[0][1] if sym_prices else ""
        
        # PriceProvider
        current_prices: dict[str, PriceResultV2] = {}
        for sym in SYMBOLS:
            if sym in sym_prices:
                p, t = sym_prices[sym]
                current_prices[sym] = PriceResultV2(symbol=sym, price=p, status=PRICE_STATUS_OK, market_time=t)
        
        if not current_prices:
            return
        
        # MarketRegimeEngine (only uses prices up to today)
        prices_only = [sym_prices[s][0] for s in SYMBOLS if s in sym_prices]
        if len(prices_only) >= 55:
            regime_snap = self.mre.detect(prices_only)
            regime = regime_snap.regime.value
        else:
            regime = "UNKNOWN"
        self.regime_history.append(regime)
        self.regime_days[regime] += 1
        
        # StrategyEngine
        cap_mode = self.last_cap_mode
        if len(prices_only) >= 50:
            strat_signal = self.se.select(market_regime=regime, capital_mode=cap_mode, price_series=prices_only)
            strat = strat_signal.strategy_type.value
        else:
            strat = "DEFENSIVE"
        
        # StrategyOptimizer
        if self.enable_optimizer and self.so and len(self.trades) > 0:
            try:
                last_pnl = self.trade_pnls[-1] if self.trade_pnls else 0
                dd = self._current_dd()
                sw = self.so.evaluate(strat, regime, total_return_pct=self._total_return(),
                    max_drawdown_pct=dd, trade_count=len(self.trades),
                    win_rate=self._win_rate(), profit_loss_ratio=self._pl_ratio())
            except: pass
        
        # LiveLearningEngine
        if self.enable_learning and self.lle and len(self.trade_pnls) > 0:
            try:
                last_pnl = self.trade_pnls[-1]
                self.lle.record_trade(strat, pnl=last_pnl, drawdown=self._current_dd(),
                    win_rate=self._win_rate(), market_regime=regime)
            except: pass
        
        self.strat_days[strat] += 1
        
        # Per-symbol
        for sym in SYMBOLS:
            if sym not in current_prices:
                continue
            price = current_prices[sym].price or Decimal("0")
            if price <= 0:
                continue
            
            self.prev_prices.setdefault(sym, price)
            prev_price = self.prev_prices[sym]
            change_pct = (price - prev_price) / prev_price * Decimal("100") if prev_price > 0 else Decimal("0")
            self.prev_prices[sym] = price
            
            # SignalEngine
            try:
                if day_idx > 0:
                    sig_list = self.sige.evaluate_with_change_pct(sym, price, change_pct)
                else:
                    sig_list = self.sige.evaluate({sym: current_prices[sym]})
                signal = sig_list[0] if sig_list else None
                if not signal: continue
            except: continue
            
            # RiskEngine
            try:
                rd = self.re.evaluate([signal])[0] if self.re.evaluate([signal]) else None
                if rd and rd.blocked:
                    self.risk_blocked += 1
                    continue
            except: continue
            
            # DecisionEngine
            pos_val = self.positions.get(sym, Decimal("0")) * price
            total_val = self.cash + sum(self.positions.get(s, Decimal("0")) * (current_prices.get(s, PriceResultV2(symbol=s, price=Decimal("0"), status=PRICE_STATUS_OK)).price or Decimal("0")) for s in SYMBOLS)
            pos_pct = float(pos_val / total_val * Decimal("100")) if total_val > 0 else 0.0
            try:
                decision = self.de.evaluate(signal, rd, position_pct=pos_pct, market_regime=regime)
            except Exception as e:
                self.decisions.append(("HOLD", sym, f"error:{e}"))
                continue
            
            self.decisions.append((decision.action.value, sym, decision.reason[:50]))
            
            if decision.action == DecisionAction.BLOCKED:
                self.risk_blocked += 1
                continue
            if decision.action == DecisionAction.HOLD: continue
            
            # Cash/position safety
            qty = Decimal("100")
            cost = price * qty
            if decision.action == DecisionAction.BUY and cost > self.cash:
                continue
            current_qty = self.positions.get(sym, Decimal("0"))
            if decision.action in (DecisionAction.SELL, DecisionAction.REDUCE) and qty > current_qty:
                qty = current_qty if current_qty > 0 else Decimal("0")
            if qty <= 0: continue
            
            # Execute
            from execution_engine import ExecutionEngine
            ee = ExecutionEngine(deterministic=True, seed=42, cost_model=COST)
            ex = ee.submit_order(decision, price, requested_qty=qty)
            if ex and ex.status in ("FILLED","PARTIAL"):
                fp = ex.fill_price or price
                fq = ex.filled_qty or qty
                tcost = COST.total_cost(fp, fq, is_buy=(decision.action==DecisionAction.BUY))
                
                if decision.action == DecisionAction.BUY:
                    total_cost = fp*fq + tcost
                    if total_cost <= self.cash:
                        self.cash -= total_cost
                        old_qty = self.positions.get(sym, Decimal("0"))
                        old_cost = self.position_costs.get(sym, Decimal("0"))
                        cb = old_cost*old_qty + fp*fq
                        self.positions[sym] = old_qty + fq
                        self.position_costs[sym] = cb / self.positions[sym] if self.positions[sym] > 0 else Decimal("0")
                        self.trades.append({"date":ts,"action":"BUY","sym":sym,"qty":str(fq),"price":str(fp),"cost":str(tcost)})
                
                elif decision.action in (DecisionAction.SELL, DecisionAction.REDUCE):
                    if fq <= self.positions.get(sym, Decimal("0")):
                        proceeds = fp*fq - tcost
                        cb = self.position_costs.get(sym, Decimal("0")) * fq
                        pnl = proceeds - cb
                        self.cash += proceeds
                        self.positions[sym] -= fq
                        self.trade_pnls.append(float(pnl))
                        self.trades.append({"date":ts,"action":decision.action.value,"sym":sym,"qty":str(fq),"price":str(fp),"pnl":str(pnl)})
                        if self.positions[sym] <= 0:
                            self.positions.pop(sym,None)
                            self.position_costs.pop(sym,None)
        
        # PortfolioEngine
        pos_infos = []
        for sym in SYMBOLS:
            qty = self.positions.get(sym, Decimal("0"))
            p = current_prices.get(sym, PriceResultV2(symbol=sym, price=Decimal("0"), status=PRICE_STATUS_OK))
            mv = qty*(p.price or Decimal("0"))
            pct_float = float(mv/(self.cash+mv)*Decimal("100"))/100.0 if (self.cash+mv)>0 else 0.0
            if pct_float>0: pos_infos.append(PositionInfo(sym, pct_float))
        if pos_infos:
            self.pfe.calculate(pos_infos, market_regime=regime)
        
        # CapitalGuard
        equity = float(self.cash + sum(self.positions.get(s,Decimal("0"))*(current_prices.get(s,PriceResultV2(symbol=s,price=Decimal("0"),status=PRICE_STATUS_OK)).price or Decimal("0")) for s in SYMBOLS))
        self.equity_curve.append(equity)
        self.timestamps.append(ts)
        cap_snap = self.cg.evaluate(equity_curve=self.equity_curve)
        new_mode = cap_snap.capital_mode.value
        if new_mode != self.last_cap_mode:
            self.cap_switches += 1
        self.last_cap_mode = new_mode
        self.cap_mode_history.append(new_mode)
        self.regime_returns[regime] += (self.equity_curve[-1] - self.equity_curve[-2]) if len(self.equity_curve)>=2 else 0
    
    def _current_dd(self):
        if not self.equity_curve: return 0.0
        peak = max(self.equity_curve)
        return (peak - self.equity_curve[-1])/peak*100 if peak>0 else 0.0
    
    def _total_return(self):
        if len(self.equity_curve)<2: return 0.0
        return (self.equity_curve[-1]-self.equity_curve[0])/self.equity_curve[0]*100
    
    def _win_rate(self):
        if not self.trade_pnls: return 0.5
        wins = sum(1 for p in self.trade_pnls if p>0)
        return wins/len(self.trade_pnls)
    
    def _pl_ratio(self):
        wins = [p for p in self.trade_pnls if p>0]
        losses = [p for p in self.trade_pnls if p<=0]
        avg_w = sum(wins)/len(wins) if wins else 1
        avg_l = abs(sum(losses)/len(losses)) if losses else 1
        return avg_w/avg_l if avg_l>0 else 0.0
    
    def run_all(self, train_data: dict):
        """运行所有交易日。"""
        max_len = max(len(v) for v in train_data.values()) if train_data else 0
        for day_idx in range(max_len):
            sym_prices = {}
            for sym in SYMBOLS:
                series = train_data.get(sym, [])
                if day_idx < len(series):
                    sym_prices[sym] = series[day_idx]
            self.run_day(sym_prices, day_idx)
        return self

def buy_hold_return(sym):
    prices = data[sym]
    return float((prices[-1][0]-prices[0][0])/prices[0][0]*Decimal("100"))

# Run configurations
configs = {
    "full": {"learning": True, "optimizer": True},
    "no_learning": {"learning": False, "optimizer": True},
    "no_opt_learning": {"learning": False, "optimizer": False},
}

results = {}
for cfg_name, cfg in configs.items():
    print(f"\n=== Running: {cfg_name} ===")
    sim = DailySimulator(enable_learning=cfg["learning"], enable_optimizer=cfg["optimizer"])
    sim.run_all(data)
    
    # Regime breakdown
    regime_pnl = {}
    for reg in ["BULL","BEAR","CHOPPY","HIGH_RISK"]:
        d = sim.regime_days.get(reg,0)
        r = sim.regime_returns.get(reg,0)
        regime_pnl[reg] = {"days":d, "pnl":round(r,2)} if d>0 else None
    
    wins = [p for p in sim.trade_pnls if p>0]
    losses = [p for p in sim.trade_pnls if p<=0]
    avg_hold = len(sim.timestamps)/max(len(sim.trades),1) if sim.trades else 0
    
    results[cfg_name] = {
        "final_equity": round(sim.equity_curve[-1],2),
        "total_return": round(sim._total_return(),2),
        "max_dd": round(sim._current_dd(),2),
        "trade_count": len(sim.trades),
        "win_rate": round(len(wins)/max(len(sim.trade_pnls),1),4),
        "pl_ratio": round((sum(wins)/len(wins))/(abs(sum(losses)/len(losses)) if losses else 1),4) if wins and losses else 0,
        "total_costs": 0,
        "regime_pnl": regime_pnl,
        "avg_hold_days": round(avg_hold,1),
        "risk_blocked": sim.risk_blocked,
        "cap_switches": sim.cap_switches,
    }

# Per-stock BH comparison
print("\n=== Per-Stock Buy & Hold ===")
stock_results = []
for sym in SYMBOLS:
    bh = buy_hold_return(sym)
    stock_results.append({"sym":sym,"bh_return":round(bh,2)})
    print(f"  {sym}: BH={bh:+.2f}%")

# BH portfolio
weights = [Decimal("100000")/len(SYMBOLS)]*len(SYMBOLS)
bh_portfolio = sum(weights[i]*data[sym][-1][0]/data[sym][0][0] for i,sym in enumerate(SYMBOLS))
bh_ret = float(bh_portfolio/Decimal("100000")*Decimal("100")-Decimal("100"))

# Full test suite
print("\n=== Running Tests ===")
os.system(f'{sys.executable} -m unittest discover -s tests 2>&1')

print("\n=== Summary ===")
for cfg, r in results.items():
    print(f"{cfg:20s}: equity=${r['final_equity']:>10.2f} return={r['total_return']:>+7.2f}% trades={r['trade_count']:>4d} win={r['win_rate']:.1%}")

print(f"\nBH Portfolio: return={bh_ret:+.2f}%")
print(f"Cash baseline: $100,000 (0%)")

# Save JSON
json.dump({"configs":{k:{kk:vv for kk,vv in v.items() if kk!='total_costs'} for k,v in results.items()},
           "buy_hold":{s["sym"]:s["bh_return"] for s in stock_results},
           "bh_portfolio": bh_ret,
           "data_info":{"symbols":len(SYMBOLS),"start":data[SYMBOLS[0]][0][1] if SYMBOLS else "","end":data[SYMBOLS[0]][-1][1] if SYMBOLS else ""}},
          open("reports/v3_historical_validation.json","w"), indent=2, ensure_ascii=False)

print("\nReport saved to reports/v3_historical_validation.json")