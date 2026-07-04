#!/usr/bin/env python3
"""V3 Strategy Evaluation with logging and progress output."""

import csv, datetime, json, os, sys, traceback
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

os.makedirs("logs", exist_ok=True)
log_file = open("logs/v3_strategy_evaluation.log", "w", encoding="utf-8")

def log(msg: str) -> None:
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    log_file.write(line + "\n")
    log_file.flush()

log("=== V3 Strategy Evaluation Start ===")

from backtest_engine import BacktestEngine, BacktestConfig
from execution_engine import TransactionCostModel

BASE_CONFIG = BacktestConfig(
    max_risk_per_trade_pct=Decimal("1.0"),
    max_position_pct=Decimal("20.0"),
    stop_loss_pct=Decimal("5.0"),
    take_profit_pct=Decimal("15.0"),
    trailing_stop_activate_pct=Decimal("8.0"),
    trailing_stop_distance_pct=Decimal("4.0"),
    atr_period=14, atr_buy_threshold=Decimal("1.5"),
    atr_strong_buy_threshold=Decimal("2.5"),
    atr_sell_threshold=Decimal("-1.2"),
    atr_strong_sell_threshold=Decimal("-2.0"),
    validation_split=0.7,
)
COST = TransactionCostModel(commission_rate=Decimal("0.001"), min_commission=Decimal("1.00"),
    spread_bps=Decimal("2"), slippage_base=Decimal("0.001"), slippage_volatility_factor=Decimal("0.5"))
SYMBOLS = ['NVDA','AAPL','MSFT','GOOGL','META','AMZN','AMD','AVGO','TSM','PLTR','SPY','QQQ']
IC = Decimal("100000")

log("Loading data...")
raw_data = json.loads(Path("eval_data.json").read_text(encoding="utf-8"))
data = {}
for sym in SYMBOLS:
    pts = raw_data.get(sym, [])
    data[sym] = [(Decimal(str(p)), ts) for p, ts in pts]
    log(f"  {sym}: {len(data[sym])} days {data[sym][0][1]}~{data[sym][-1][1]}")

def buy_and_hold_return(prices):
    if len(prices) < 2: return Decimal("0")
    return (prices[-1] - prices[0]) / prices[0] * Decimal("100")

def annualized_return(prices, return_pct):
    if len(prices) < 2: return Decimal("0")
    n = len(prices) / 252
    if n <= 0: return Decimal("0")
    return ((Decimal("1") + return_pct/Decimal("100")) ** (Decimal("1")/Decimal(str(n))) - Decimal("1")) * Decimal("100")

SENSITIVITY_TESTS = {
    "ATR threshold -20%": ("atr_buy_threshold", lambda c: c.atr_buy_threshold * Decimal("0.8")),
    "ATR threshold +20%": ("atr_buy_threshold", lambda c: c.atr_buy_threshold * Decimal("1.2")),
    "Stop loss -20%": ("stop_loss_pct", lambda c: c.stop_loss_pct * Decimal("0.8")),
    "Stop loss +20%": ("stop_loss_pct", lambda c: c.stop_loss_pct * Decimal("1.2")),
    "Take profit -20%": ("take_profit_pct", lambda c: c.take_profit_pct * Decimal("0.8")),
    "Take profit +20%": ("take_profit_pct", lambda c: c.take_profit_pct * Decimal("1.2")),
    "Risk ratio -20%": ("max_risk_per_trade_pct", lambda c: c.max_risk_per_trade_pct * Decimal("0.8")),
    "Risk ratio +20%": ("max_risk_per_trade_pct", lambda c: c.max_risk_per_trade_pct * Decimal("1.2")),
}

results = {}
benchmarks = {}
sensitivity = defaultdict(list)

log("Creating engine...")
engine = BacktestEngine(initial_cash=IC, deterministic=True, seed=42, config=BASE_CONFIG, cost_model=COST)

for idx, sym in enumerate(SYMBOLS):
    log(f"--- [{idx+1}/{len(SYMBOLS)}] {sym} ---")
    series = data.get(sym, [])
    if len(series) < 30:
        log(f"  SKIP {sym}: only {len(series)} days")
        continue
    
    try:
        prices_only = [p for p,_ in series]
        bhr = buy_and_hold_return(prices_only)
        bh_ann = annualized_return(prices_only, bhr)
        
        log(f"  Backtest run_single...")
        full = engine.run_single(sym, series)
        ann = annualized_return(prices_only, full.total_return_pct)
        excess = full.total_return_pct - bhr
        log(f"  Result: strat={float(full.total_return_pct):+.2f}% BH={float(bhr):+.2f}% excess={float(excess):+.2f}% trades={full.trade_count}")
        
        # Regime breakdown
        log(f"  Computing regime breakdown...")
        from backtest_engine import _compute_atr
        regime_results = {}
        if len(full.equity_curve) >= 22:
            regime_equities = {"uptrend":[],"downtrend":[],"sideways":[],"high_volatility":[],"low_volatility":[],"normal":[]}
            for i in range(21, min(len(prices_only), len(full.equity_curve))):
                p20 = prices_only[i-20]; p5 = prices_only[i-5]
                chg20 = (prices_only[i]-p20)/p20*Decimal("100") if p20>0 else Decimal("0")
                chg5 = (prices_only[i]-p5)/p5*Decimal("100") if p5>0 else Decimal("0")
                vol = sum(abs(prices_only[j]-prices_only[j-1]) for j in range(i-20,i))/Decimal("20")/prices_only[i]*Decimal("100") if prices_only[i]>0 else Decimal("0")
                if abs(chg20)<3 and abs(chg5)<2: reg="sideways"
                elif chg20>5: reg="uptrend"
                elif chg20<-5: reg="downtrend"
                elif vol>3: reg="high_volatility"
                elif vol<1: reg="low_volatility"
                else: reg="normal"
                if reg in regime_equities:
                    regime_equities[reg].append(full.equity_curve[i])
            for reg, eqs in regime_equities.items():
                if len(eqs)>=2:
                    rtrn = (eqs[-1]-eqs[0])/eqs[0]*Decimal("100") if eqs[0]>0 else Decimal("0")
                    regime_results[reg] = {"days":len(eqs),"return_pct":float(rtrn)}
        
        # Sample split
        log(f"  Computing sample split...")
        split_pt = int(len(series)*0.7)
        in_prices = prices_only[:split_pt]; out_prices = prices_only[split_pt:]
        in_bhr = buy_and_hold_return(in_prices); out_bhr = buy_and_hold_return(out_prices)
        in_excess = (full.in_sample_return_pct or 0)-in_bhr
        out_excess = (full.out_sample_return_pct or 0)-out_bhr
        
        # Metrics
        log(f"  Computing trade metrics...")
        gross_profit = sum(float(t.get("pnl",0)) for t in full.trades if float(t.get("pnl",0))>0)
        gross_loss = abs(sum(float(t.get("pnl",0)) for t in full.trades if float(t.get("pnl",0))<0))
        pf = gross_profit/gross_loss if gross_loss>0 else 0
        
        max_consec_loss=0; curr_loss=0
        for t in full.trades:
            pnl=float(t.get("pnl",0))
            if pnl<0: curr_loss+=1; max_consec_loss=max(max_consec_loss,curr_loss)
            else: curr_loss=0
        
        all_pnls = sorted([float(t.get("pnl",0)) for t in full.trades], reverse=True)
        top3 = sum(all_pnls[:3]) if len(all_pnls)>=3 else sum(all_pnls)
        total_pnl = sum(all_pnls)
        concentration = top3/total_pnl*100 if total_pnl!=0 else 0
        
        results[sym] = {
            "days":len(series),"date_range":f"{series[0][1]}-{series[-1][1]}",
            "buy_hold_return_pct":float(bhr),"buy_hold_ann_pct":float(bh_ann),
            "strategy_return_pct":float(full.total_return_pct),"strategy_ann_pct":float(ann),
            "excess_vs_bh_pct":float(excess),
            "max_drawdown_pct":float(full.max_drawdown),"win_rate":full.win_rate,
            "profit_loss_ratio":full.profit_loss_ratio,"profit_factor":pf,
            "trade_count":full.trade_count,"avg_hold_days":len(series)//max(full.trade_count,1),
            "total_commission":float(full.total_commission),"total_spread":float(full.total_spread_cost),
            "total_slippage":float(full.total_slippage_cost),
            "total_costs":float(full.total_commission+full.total_spread_cost+full.total_slippage_cost),
            "max_consecutive_losses":max_consec_loss,
            "in_sample_return_pct":float(full.in_sample_return_pct or 0),
            "out_sample_return_pct":float(full.out_sample_return_pct or 0),
            "in_excess_vs_bh":float(in_excess),"out_excess_vs_bh":float(out_excess),
            "in_bh":float(in_bhr),"out_bh":float(out_bhr),
            "regime_results":regime_results,"concentration_top3_pct":concentration,
            "stop_loss_cnt":full.stop_loss_triggered,"take_profit_cnt":full.take_profit_triggered,
            "trailing_stop_cnt":full.trailing_stop_triggered,
        }
        
        # Benchmarks
        for bench in ["SPY","QQQ"]:
            bs = data.get(bench,[])
            if bs and len(series)>=2:
                benchmarks.setdefault(sym,{})[bench] = float(buy_and_hold_return([p for p,_ in bs]))
        
        # Sensitivity
        log(f"  Running sensitivity tests...")
        for label, (attr, modifier) in SENSITIVITY_TESTS.items():
            cfg = BacktestConfig(**{k:getattr(BASE_CONFIG,k) for k in [
                "max_risk_per_trade_pct","max_position_pct","stop_loss_pct","take_profit_pct",
                "trailing_stop_activate_pct","trailing_stop_distance_pct","atr_period",
                "atr_buy_threshold","atr_strong_buy_threshold","atr_sell_threshold",
                "atr_strong_sell_threshold","validation_split"]})
            setattr(cfg, attr, modifier(cfg))
            se = BacktestEngine(initial_cash=IC, deterministic=True, seed=42, config=cfg, cost_model=COST)
            sr = se.run_single(sym, series)
            sensitivity[label].append({"symbol":sym,"return_pct":float(sr.total_return_pct),"trades":sr.trade_count,"dd":float(sr.max_drawdown)})
    
    except Exception as e:
        log(f"  ERROR on {sym}: {e}")
        traceback.print_exc(file=log_file)
        log_file.flush()
        continue

log(f"\n=== Generating Reports ===")

# Compute summary
avg_excess = sum(r["excess_vs_bh_pct"] for r in results.values())/len(results) if results else 0
avg_return = sum(r["strategy_ann_pct"] for r in results.values())/len(results) if results else 0
avg_bh = sum(r["buy_hold_ann_pct"] for r in results.values())/len(results) if results else 0
avg_win = sum(r["win_rate"] for r in results.values())/len(results) if results else 0
avg_dd = sum(r["max_drawdown_pct"] for r in results.values())/len(results) if results else 0
total_costs = sum(r["total_costs"] for r in results.values())
total_trades = sum(r["trade_count"] for r in results.values())

if avg_excess>0 and avg_win>0.3 and avg_dd<25:
    topline = "A. 可以进入模拟盘测试"
elif avg_excess<-5 or avg_win<0.25 or avg_dd>30:
    topline = "C. 当前策略没有明显优势，不建议继续使用"
else:
    topline = "B. 需要继续调整后再测试"

log(f"Conclusion: {topline}")

os.makedirs("reports", exist_ok=True)

# Markdown
md = []
md.append("# V3 策略评估报告\n")
md.append(f"> 生成时间: {datetime.datetime.now().isoformat()}")
md.append(f"> 测试股票: {', '.join(SYMBOLS)}")
md.append(f"> 初始资金: ${float(IC):,.0f}")
md.append(f"> 数据范围: ~5年日线数据")
md.append(f"> 成本模型: 佣金0.1%，价差2bp，滑点0.1%\n")
md.append("## 一、结论摘要\n")
md.append(f"**平均年化收益**: {avg_return:.2f}% (vs 买入持有 {avg_bh:.2f}%)")
md.append(f"**平均超额收益**: {avg_excess:.2f}%")
md.append(f"**平均胜率**: {avg_win:.1%}")
md.append(f"**平均最大回撤**: {avg_dd:.2f}%")
md.append(f"**总交易次数**: {total_trades}")
md.append(f"**总交易成本**: ${total_costs:.0f}\n")
md.append(f"**最终结论**: **{topline}**\n")
md.append("## 二、各股票结果\n")
md.append("| 股票 | 天数 | 策略收益 | 年化收益 | BH收益 | 超额 | 最大回撤 | 胜率 | 盈亏比 | 交易次数 | 总成本 |")
md.append("|------|------|----------|----------|--------|------|----------|------|--------|----------|--------|")
for sym in SYMBOLS:
    r=results.get(sym)
    if not r: continue
    md.append(f"| {sym:6s} | {r['days']} | {r['strategy_return_pct']:+6.2f}% | {r['strategy_ann_pct']:+5.2f}% | {r['buy_hold_return_pct']:+5.2f}% | {r['excess_vs_bh_pct']:+5.2f}% | {r['max_drawdown_pct']:5.2f}% | {r['win_rate']:.1%} | {r['profit_loss_ratio']:.2f} | {r['trade_count']} | ${r['total_costs']:.0f} |")
Path("reports/v3_strategy_evaluation.md").write_text("\n".join(md), encoding="utf-8")
log("Markdown report saved")

# CSV
csv_fields = ["symbol","days","strategy_return_pct","strategy_ann_pct","buy_hold_return_pct",
              "excess_vs_bh_pct","max_drawdown_pct","win_rate","profit_loss_ratio","profit_factor",
              "trade_count","avg_hold_days","total_costs","max_consecutive_losses",
              "in_sample_return_pct","out_sample_return_pct","in_excess_vs_bh","out_excess_vs_bh"]
with open("reports/v3_strategy_evaluation.csv","w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=csv_fields); w.writeheader()
    for sym in SYMBOLS:
        r=results.get(sym)
        if r: w.writerow({k:r.get(k,"") for k in csv_fields})
log("CSV saved")

# JSON
json.dump({
    "conclusion":topline,"avg_ann_return_pct":avg_return,"avg_bh_return_pct":avg_bh,
    "avg_excess_vs_bh_pct":avg_excess,"avg_win_rate":avg_win,"avg_max_drawdown_pct":avg_dd,
    "total_trades":total_trades,"total_costs":total_costs,
    "symbols":{sym:results.get(sym) for sym in SYMBOLS if results.get(sym)},
    "sensitivity":{k:v for k,v in sensitivity.items()},
}, open("reports/v3_strategy_summary.json","w",encoding="utf-8"), indent=2, ensure_ascii=False)
log("JSON saved")

log("\n=== DONE ===")
log_file.close()