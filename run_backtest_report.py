#!/usr/bin/env python3
"""Backtest report generator. Reads .backtest_cache.json, runs BacktestEngine, outputs report."""

import json
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

from backtest_engine import BacktestEngine
from decision_engine import DecisionAction
from risk_engine import RiskLevel
from signal_engine import SignalType

# Load cached data
cache_path = Path(".backtest_cache.json")
if not cache_path.exists():
    print("ERROR: .backtest_cache.json not found. Run data fetch first.")
    sys.exit(1)

raw = json.loads(cache_path.read_text(encoding="utf-8"))
data = {}
for sym, points in raw.items():
    data[sym] = [(Decimal(str(p)), ts) for p, ts in points]

initial_cash = Decimal("100000")
engine = BacktestEngine(initial_cash=initial_cash, deterministic=True, seed=42)

print("=" * 72)
print("  V3 SYSTEM BACKTEST REPORT")
print("  Symbol: NVDA, AAPL, TSLA")
print(f"  Period: 1 year daily data")
print(f"  Initial Cash: ${initial_cash:,.2f}")
print("=" * 72)

all_results = {}
total_stats = {"signal_counts": Counter(), "risk_counts": Counter(), "action_counts": Counter()}
all_equity_curves = {}

for sym in ["NVDA", "AAPL", "TSLA"]:
    if sym not in data:
        print(f"\n  SKIP {sym}: no data")
        continue
    series = data[sym]
    print(f"\n--- {sym}: {len(series)} days ---")

    # Run backtest with detailed tracking
    result = engine.run_single(sym, series)
    all_results[sym] = result

    # Re-run with detailed counters (modify engine's internal signal processing)
    # Count signals from a separate detailed pass
    signal_counts = Counter()
    risk_counts = Counter()
    action_counts = Counter()

    # Use a second pass to count (same deterministic seed so same results)
    det_result = engine.run_single(sym, series)
    # Detailed counts need access to intermediate state, which we get by reimplementing
    # the loop here:
    from price_provider_v2 import PriceResultV2, PRICE_STATUS_OK
    from signal_engine import SignalEngine
    from risk_engine import RiskEngine, RiskDecision
    from decision_engine import DecisionEngine
    from execution_engine import ExecutionEngine

    se = SignalEngine()
    re = RiskEngine()
    de = DecisionEngine()
    ee = ExecutionEngine(deterministic=True, seed=42)

    cash = initial_cash
    position_qty = Decimal("0")
    position_avg_cost = Decimal("0")

    for i, (price, ts) in enumerate(series):
        pr = PriceResultV2(symbol=sym, price=price, status=PRICE_STATUS_OK, market_time=ts)
        if i == 0:
            sig_list = se.evaluate({sym: pr})
        else:
            prev_price = series[i-1][0]
            if prev_price > Decimal("0"):
                change = (price - prev_price) / prev_price * Decimal("100")
                sig_list = se.evaluate_with_change_pct(sym, price, change)
            else:
                sig_list = se.evaluate({sym: pr})

        if not sig_list:
            continue
        signal = sig_list[0]
        signal_counts[signal.signal_type.value] += 1

        rd_list = re.evaluate(sig_list)
        rd = rd_list[0] if rd_list else None
        if rd:
            risk_counts[rd.risk_level.value] += 1

        pos_val = position_qty * price
        pos_pct = float(pos_val / (cash + pos_val) * Decimal("100")) if cash + pos_val > Decimal("0") else 0.0
        decision = de.evaluate(signal, rd, position_pct=pos_pct)
        action_counts[decision.action.value] += 1

        ex_result = ee.submit_order(decision, price)
        if ex_result and ex_result.status in ("FILLED", "PARTIAL"):
            fp = ex_result.fill_price or price
            fq = ex_result.filled_qty or Decimal("0")
            if decision.action == DecisionAction.BUY:
                cost = fp * fq
                if cost <= cash:
                    cash -= cost
                    tc = position_avg_cost * position_qty + cost
                    position_qty += fq
                    position_avg_cost = tc / position_qty if position_qty > Decimal("0") else Decimal("0")
            elif decision.action in (DecisionAction.SELL, DecisionAction.REDUCE):
                if fq <= position_qty:
                    proceeds = fp * fq
                    cash += proceeds
                    position_qty -= fq
                    position_avg_cost = position_avg_cost  # unchanged

    total_stats["signal_counts"].update(signal_counts)
    total_stats["risk_counts"].update(risk_counts)
    total_stats["action_counts"].update(action_counts)

    print(f"  Return: {result.total_return_pct:.2f}%")
    print(f"  Win Rate: {result.win_rate:.1%}")
    print(f"  Max Drawdown: {result.max_drawdown:.2f}%")
    print(f"  Trades: {result.trade_count}")
    print(f"  Final Equity: ${result.final_equity:,.2f}")
    print(f"  Signal Distribution: {dict(signal_counts)}")
    print(f"  Risk Distribution: {dict(risk_counts)}")
    print(f"  Action Distribution: {dict(action_counts)}")
    all_equity_curves[sym] = [float(e) for e in result.equity_curve]

# Overall summary
print("\n" + "=" * 72)
print("  PORTFOLIO SUMMARY")
print("=" * 72)
total_equity_final = sum(float(r.final_equity) for r in all_results.values())
total_initial = initial_cash * Decimal(str(len(all_results)))
total_return_val = sum(r.total_return for r in all_results.values())
total_return_pct = float(total_return_val / total_initial * Decimal("100")) if total_initial > Decimal("0") else 0.0
avg_win_rate = sum(r.win_rate for r in all_results.values()) / len(all_results) if all_results else 0.0
total_trades = sum(r.trade_count for r in all_results.values())

print(f"  Total Return: ${float(total_return_val):,.2f} ({total_return_pct:.2f}%)")
print(f"  Avg Win Rate: {avg_win_rate:.1%}")
print(f"  Total Trades: {total_trades}")
print(f"  Total Final Equity: ${total_equity_final:,.2f}")
print(f"\n  Signal Type Distribution: {dict(total_stats['signal_counts'])}")
print(f"  Risk Level Distribution: {dict(total_stats['risk_counts'])}")
print(f"  Decision Action Distribution: {dict(total_stats['action_counts'])}")

# Best / worst
best = max(all_results.items(), key=lambda x: float(x[1].total_return_pct))
worst = min(all_results.items(), key=lambda x: float(x[1].total_return_pct))
print(f"\n  Best Performer: {best[0]} ({float(best[1].total_return_pct):.2f}%)")
print(f"  Worst Performer: {worst[0]} ({float(worst[1].total_return_pct):.2f}%)")

# Stability: max drawdown across portfolio
avg_dd = sum(float(r.max_drawdown) for r in all_results.values()) / len(all_results) if all_results else 0.0
print(f"  Avg Max Drawdown: {avg_dd:.2f}%")
if avg_dd < 10:
    print("  Stability: STABLE (avg drawdown < 10%)")
elif avg_dd < 20:
    print("  Stability: MODERATE (avg drawdown 10-20%)")
else:
    print("  Stability: VOLATILE (avg drawdown > 20%)")

# Viability assessment
print(f"\n{'=' * 72}")
print("  REAL-TRADING VIABILITY ASSESSMENT")
print("=" * 72)
if total_return_pct > 0 and avg_win_rate > 0.3 and avg_dd < 20 and total_trades > 20:
    print("  VERDICT: PARTIALLY VIABLE — Requires tuning for real funds.")
    print("  Strengths: Positive return, reasonable win rate")
    print("  Risks: Backtest-only, no execution cost model, no market impact")
else:
    print("  VERDICT: NOT YET VIABLE — Requires strategy improvement.")
    print("  The current momentum/reversion strategies are simplistic.")
    print("  Recommended improvements:")
    print("    1. Add transaction cost model (commission, spread)")
    print("    2. Add adaptive thresholds based on volatility regime")
    print("    3. Improve position sizing (fixed fractional)")
    print("    4. Add stop-loss/take-profit logic")
    print("    5. Validate on out-of-sample data")

# Save structured JSON result
report_json = {
    "report_date": str(datetime.date.today()),
    "initial_cash": str(initial_cash),
    "symbols": [sym for sym in ["NVDA", "AAPL", "TSLA"] if sym in all_results],
    "individual_results": {
        sym: {
            "total_return_pct": float(r.total_return_pct),
            "win_rate": r.win_rate,
            "max_drawdown": float(r.max_drawdown),
            "trade_count": r.trade_count,
            "final_equity": float(r.final_equity),
            "signal_distribution": dict(total_stats["signal_counts"]),
            "risk_distribution": dict(total_stats["risk_counts"]),
            "action_distribution": dict(total_stats["action_counts"]),
            "equity_curve": [float(e) for e in r.equity_curve],
            "timestamps": r.timestamps,
        }
        for sym, r in all_results.items()
    },
    "portfolio_summary": {
        "total_return_pct": total_return_pct,
        "avg_win_rate": avg_win_rate,
        "total_trade_count": total_trades,
        "total_final_equity": total_equity_final,
        "best_performer": best[0],
        "best_return_pct": float(best[1].total_return_pct),
        "worst_performer": worst[0],
        "worst_return_pct": float(worst[1].total_return_pct),
        "avg_max_drawdown_pct": avg_dd,
    },
}

Path("backtest_report.json").write_text(json.dumps(report_json, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"\n  JSON report saved to backtest_report.json")