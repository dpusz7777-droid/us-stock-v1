#!/usr/bin/env python3
"""Run all 4 scenarios and save results."""
import json, os
from v3_pipeline import V3Pipeline, create_scenario_data

os.makedirs("reports", exist_ok=True)
results = {}

for sc in ["bull", "bear", "choppy", "high-risk"]:
    p = V3Pipeline()
    p.reset()
    inp = create_scenario_data(sc)
    r = p.run(inp)
    steps = [s.step_name for s in r.steps]
    mods = {name: any(name in s for s in steps)
            for name in ["PriceProvider","BrokerProvider","MarketRegimeEngine","StrategyEngine",
                          "StrategyOptimizer","LiveLearningEngine","SignalEngine","RiskEngine",
                          "DecisionEngine","PositionEngine","PortfolioEngine","CapitalGuard","ExecutionEngine"]}
    results[sc] = {
        "regime": r.market_regime, "strategy": r.selected_strategy, "cap_mode": r.capital_mode,
        "status": r.status.value, "cash": float(p.cash), "equity": float(r.total_equity),
        "errors": len(r.errors), "warnings": len(r.warnings),
        "modules": {k: bool(v) for k,v in mods.items()},
        "cash_ok": bool(p.cash >= 0), "pos_ok": bool(all(q >= 0 for q in p.positions.values())),
        "sim_only": bool(r.simulation_only),
        "decisions": [f"{d.action.value}:{d.symbol}" for d in r.final_decisions],
    }
    print(f"{sc:10s} regime={r.market_regime:10s} strat={r.selected_strategy:15s} cap={r.capital_mode:8s} cash=$ {float(p.cash):8.2f} status={r.status.value:8s} errors={len(r.errors)} mods={sum(mods.values())}/13")

json.dump(results, open("reports/v3_scenario_validation.json","w"), indent=2, ensure_ascii=False)
print(f"\nReport saved. All modules: {all(all(v.values()) for v in results.values())}")
print(f"All cash>=0: {all(v['cash_ok'] for v in results.values())}")
print(f"All pos>=0:  {all(v['pos_ok'] for v in results.values())}")
print(f"All sim:     {all(v['sim_only'] for v in results.values())}")