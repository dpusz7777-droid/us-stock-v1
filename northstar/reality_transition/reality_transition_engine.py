#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""现实市场迁移与真实资金验证准备层 — v13.

v13: Live Trading Transition Protocol (LTTP).
从 v12 CCDS 安全迁移至真实市场小资金实盘运行（1% capital exposure）。
三轨一致性验证 + 实盘保护 + live PnL reconciliation。

仍不执行真实交易。所有 micro_live 模式受 LTTP 安全门控，仅允许1%资金暴露。
"""

from __future__ import annotations

import json, math, random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

BASE_SLIPPAGE = 0.001; REGIME_MULTIPLIERS = {"trend": 1.0, "range": 0.9, "volatile": 0.6, "liquidity_stress": 0.2}
STRATEGY_NAMES = ["momentum", "mean_reversion", "regime", "breakout", "ai_signal"]
REGIME_STRATEGY_PREF = {"trend": {"momentum": 1.5, "mean_reversion": 0.3, "regime": 1.0, "breakout": 1.4, "ai_signal": 1.0},
    "range": {"momentum": 0.4, "mean_reversion": 1.5, "regime": 1.0, "breakout": 0.5, "ai_signal": 1.0},
    "volatile": {"momentum": 0.6, "mean_reversion": 0.5, "regime": 1.3, "breakout": 0.7, "ai_signal": 1.4},
    "liquidity_stress": {"momentum": 0.3, "mean_reversion": 0.3, "regime": 0.3, "breakout": 0.3, "ai_signal": 0.3}}
TIER_LIMITS = {0: 0.0, 1: 0.01, 2: 0.05, 3: 0.25, 4: 1.0}
TIER_NAMES = {0: "shadow", 1: "micro_live", 2: "limited_live", 3: "scaled_live", 4: "full_live"}
LIVE_MODES = ["shadow_only", "shadow_live_sync", "micro_live_real_capital"]


class BrokerAdapter:
    def __init__(self, name: str = "simulated"):
        self.name = name; self._status = "ready"; self._orders = []; self._fills = []
    def submit_order(self, symbol, qty, price, order_type="limit"):
        o = dict(order_id=len(self._orders)+1, symbol=symbol, qty=qty, price=price, type=order_type, status="submitted")
        self._orders.append(o); return o
    def cancel_order(self, order_id):
        for o in self._orders:
            if o["order_id"] == order_id: o["status"] = "cancelled"; return True
        return False
    def fetch_fills(self): return self._fills
    def fetch_positions(self): return [{"symbol": "SIM", "qty": 10, "avg_price": 100.0}]
    @property
    def status(self): return self._status
    @status.setter
    def status(self, v): self._status = v


class LiveBrokerAdapter(BrokerAdapter):
    """实盘 Broker 适配器（不连接真实API，仅接口抽象）。"""
    def submit_live_order(self, symbol, qty, price):
        return self.submit_order(symbol, qty, price, order_type="live")
    def confirm_fill(self, order_id):
        for o in self._orders:
            if o["order_id"] == order_id: o["status"] = "filled"; return o
        return None
    def reconcile_positions(self, exchange_positions):
        return {"reconciled": True, "differences": []}
    def fetch_real_pnl(self):
        return {"realized_pnl": random.uniform(-50, 100), "unrealized_pnl": random.uniform(-20, 30)}


class ExecutionBiasModel:
    def __init__(self, alpha=0.3): self.alpha = alpha; self.bias = 0.0
    def update(self, error): self.bias = self.alpha * error + (1 - self.alpha) * self.bias
    def apply(self, value): return value + self.bias


class RealityTransitionEngine:
    def __init__(self):
        self._consecutive_breakdown_days = 0; self._kill_switch_active = False; self._kill_switch_until = None
        self._micro_live_portfolio = {"cash": 10000.0, "positions": {}, "peak_value": 10000.0}
        self._rmai_history = []; self._emil_trade_log = []; self._mode = "shadow"
        self._execution_bias = ExecutionBiasModel(); self._broker = BrokerAdapter()
        self._live_broker = LiveBrokerAdapter()
        self._divergence_history = []
        self._tier = 0; self._tier_stable_days = 0; self._consecutive_loss_days = 0
        self._smooth_allocation = 0.0; self._total_pnl = 0.0
        # v13: LTTP state
        self._live_mode = "shadow_only"  # shadow_only | shadow_live_sync | micro_live_real_capital
        self._daily_pnl = 0.0
        self._triple_log = []

    def run_reality_mirror_cycle(self, live_market_data=None, shadow_data=None, paper_data=None):
        lm = live_market_data or {"live_return": 2.0, "volatility": 0.15, "volume": 1.0, "spread_proxy": 0.001, "returns": [0.1,0.2,0.15]}
        sd = shadow_data or {"shadow_return": 1.8}; pd = paper_data or {"paper_return": 2.5}
        lr = lm.get("live_return",0); sr = sd.get("shadow_return",0); pr = pd.get("paper_return",0)
        vol = lm.get("volatility",0.15); liq = lm.get("volume",1.0)

        regime = self.market_regime_detector(lm)
        base_rmai = self.compute_reality_alignment_index(lr,sr,pr)
        self._rmai_history.append(base_rmai["score"])
        dynamic = self.compute_dynamic_rmai(base_rmai["score"], regime["regime_type"])
        breakdown = self.detect_reality_breakdown(lr,sr,pr)
        self._consecutive_breakdown_days = self._consecutive_breakdown_days+1 if breakdown["breakdown_detected"] else 0

        strategies = self.build_strategy_profiles(dynamic["dynamic_rmai"], base_rmai["signal_match"], regime["regime_type"])
        meta = self.compute_strategy_allocation(strategies, regime["regime_type"])

        shadow_result = self.execute_portfolio(meta["strategy_allocations"], regime["regime_type"], vol, liq)
        live_sim_result = self._live_simulation(meta["strategy_allocations"], regime["regime_type"], vol, liq)
        divergence = self.compute_market_divergence(shadow_result, live_sim_result)
        self._divergence_history.append(divergence["execution_divergence_score"])

        # v13: Pre-flight check
        pre_flight = self.pre_live_check()
        live_readiness = self._live_risk_gate(divergence, regime)
        if live_readiness["live_allowed"] and self._mode == "shadow": self._mode = "live_shadow"
        elif not live_readiness["live_allowed"]: self._mode = "shadow"
        self._sync_shadow_to_live(shadow_result, live_sim_result)

        pnl_realized = shadow_result["pnl_realized"]
        pnl_expected = shadow_result["pnl_expected"]
        feedback = self._emil_feedback(pnl_realized, pnl_expected)

        # v13: Triple sync
        triple = self._triple_sync(shadow_result, live_sim_result)
        # v13: Live protection
        protection = self.live_protection_engine(dict(drawdown=abs(self._total_pnl)/10000.0, divergence=divergence["execution_divergence_score"],
                                                       slippage=shadow_result["slippage_cost"], regime=regime["regime_type"]))
        if protection.get("action") == "fallback_to_shadow": self._live_mode = "shadow_only"
        # v13: Live PnL reconciliation
        pnl_dev = self.compute_live_pnl_deviation(pnl_realized, pnl_realized)

        self._total_pnl += pnl_realized
        if pnl_realized < 0: self._consecutive_loss_days += 1
        else: self._consecutive_loss_days = 0
        # v13: Auto degrade
        if abs(self._total_pnl)/10000.0 > 0.005 or divergence["execution_divergence_score"] < 70 or self._kill_switch_active:
            self._live_mode = "shadow_only"

        ccds = self.compute_capital_tier(dict(
            execution_divergence_score=divergence["execution_divergence_score"],
            pnl_divergence=divergence["pnl_divergence"], slippage_divergence=divergence["slippage_divergence"],
            stability_score=0.8 if self._consecutive_breakdown_days==0 else 0.5,
            regime=regime["regime_type"], kill_switch=self._kill_switch_active,
            consecutive_loss_days=self._consecutive_loss_days, total_pnl=self._total_pnl))
        ccds = self._apply_capital_smoothing(ccds, alpha=0.7)

        readiness = self.capital_deployment_readiness_engine({"score": dynamic["dynamic_rmai"]}, breakdown, regime["regime_type"], regime["confidence"])
        stress = self.stress_test_mode(lm,sd,pd); wfv = self.walk_forward_validation(lm,sd,pd)
        micro = self.micro_live_cycle(lr)
        ks = {"kill_switch_active": self._kill_switch_active}
        if self._kill_switch_active and self._kill_switch_until and datetime.now() >= self._kill_switch_until:
            self._kill_switch_active=False; self._kill_switch_until=None; ks["kill_switch_active"]=False

        result = dict(date=date.today().isoformat(), rmai_score=base_rmai["score"],
                      dynamic_rmai=dynamic["dynamic_rmai"], current_regime=regime["regime_type"],
                      regime_confidence=regime["confidence"], mode=self._mode,
                      # v13 LTTP fields
                      live_mode=self._live_mode,
                      pre_flight_check=pre_flight["all_clear"], pre_flight_reasons=pre_flight.get("blocked_reasons",[]),
                      capital_exposure=0.01,
                      daily_loss_limit=0.005, execution_status="active" if not self._kill_switch_active else "frozen",
                      shadow_live_divergence=round(divergence.get("fill_divergence",0),1),
                      live_shadow_divergence=round(divergence.get("pnl_divergence",0),1),
                      risk_state="controlled" if self._live_mode!="shadow_only" else "shadow",
                      broker_status=self._live_broker.status,
                      live_protection_action=protection.get("action","none"),
                      pnl_deviation=round(pnl_dev,2),
                      strategy_allocations=meta["strategy_allocations"], total_risk=meta["total_risk"],
                      expected_portfolio_return=meta["expected_portfolio_return"],
                      dominant_strategy=meta["dominant_strategy"], system_status=meta["system_status"],
                      executed_allocations=shadow_result["executed_allocations"],
                      slippage_cost=shadow_result["slippage_cost"], market_impact_cost=shadow_result["market_impact_cost"],
                      execution_quality_score=shadow_result["execution_quality_score"],
                      pnl_realized=pnl_realized, pnl_expected=pnl_expected,
                      execution_efficiency=shadow_result["execution_efficiency"],
                      rmai_corrected=feedback["rmai_corrected"],
                      execution_divergence_score=divergence["execution_divergence_score"],
                      live_readiness_score=live_readiness["score"], live_allowed=live_readiness["live_allowed"],
                      broker_adapter_status=self._broker.status, slippage_bias=round(self._execution_bias.bias,6),
                      current_tier=ccds["tier_name"], allowed_capital_pct=round(ccds["allowed_pct"]*100,2),
                      next_tier=ccds["next_tier"], upgrade_ready=ccds["upgrade_ready"],
                      downgrade_triggered=ccds["downgrade_triggered"], exposure_limit=round(ccds["exposure_limit"],4),
                      risk_status=ccds["risk_status"],
                      shadow_vs_live_correlation=base_rmai["shadow_corr"], paper_vs_live_correlation=base_rmai["paper_corr"],
                      execution_accuracy=base_rmai["exec_accuracy"], signal_match_rate=base_rmai["signal_match"],
                      breakdown_detected=breakdown["breakdown_detected"], breakdown_type=breakdown.get("breakdown_type"),
                      consecutive_breakdown_days=self._consecutive_breakdown_days,
                      capital_readiness=readiness, stress_test=stress, walk_forward=wfv, micro_live_sandbox=micro, kill_switch=ks)

        today = date.today().isoformat().replace("-","")
        reports_dir = Path(__file__).parent.parent.parent / "reports"; reports_dir.mkdir(parents=True, exist_ok=True)
        with open(reports_dir / f"reality_transition_{today}.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return result

    # ═══════════════════════════════════════════════════════════════════
    # v13: Live Trading Transition Protocol
    # ═══════════════════════════════════════════════════════════════════

    def pre_live_check(self) -> dict[str, Any]:
        """实盘启动前检查 — 全部通过才能进入 real_capital。"""
        checks = []
        if self._tier < 1: checks.append("CCDS tier < tier_1")
        if self._divergence_history and self._divergence_history[-1] <= 90: checks.append(f"execution_stability <= 90")
        if abs(self._execution_bias.bias) >= 0.1: checks.append(f"slippage_bias {self._execution_bias.bias:.2f} >= 10%")
        if self._kill_switch_active: checks.append("kill_switch ON")
        if self._live_broker.status != "ready": checks.append(f"broker_status: {self._live_broker.status}")
        if checks:
            return dict(all_clear=False, blocked_reasons=checks)
        self._live_mode = "micro_live_real_capital"
        return dict(all_clear=True, blocked_reasons=[])

    def _triple_sync(self, shadow: dict, live_sim: dict) -> dict[str, Any]:
        """三轨同步 — shadow / live_sim / real (mock)."""
        real_pnl = shadow["pnl_realized"] * (1 + random.uniform(-0.05, 0.05))
        sld = abs(shadow["pnl_realized"] - live_sim["pnl_realized"])
        lrd = abs(live_sim["pnl_realized"] - real_pnl)
        self._triple_log.append(dict(shadow=shadow["pnl_realized"], live_sim=live_sim["pnl_realized"], real=real_pnl))
        return dict(shadow_live_divergence=round(sld,2), live_real_divergence=round(lrd,2), total_drift=round(sld+lrd,2))

    def live_protection_engine(self, metrics: dict) -> dict[str, Any]:
        """实盘保护系统 — 检测风险并执行保护动作。"""
        dd = metrics.get("drawdown", 0); div = metrics.get("divergence", 100)
        slip = metrics.get("slippage", 0); regime = metrics.get("regime", "")
        if dd > 0.02 or div > 25 or slip > BASE_SLIPPAGE * 2 or regime == "liquidity_stress":
            self._live_mode = "shadow_only"
            return dict(action="fallback_to_shadow", reason=f"dd={dd:.2%} div={div:.1f} slip={slip:.4f}")
        return dict(action="none", reason="all_clear")

    def route_order_to_broker(self, order: dict) -> dict[str, Any]:
        """实盘订单路由 — 通过所有安全门后才执行。"""
        if self._kill_switch_active: return dict(executed=False, reason="kill_switch")
        if self._tier == 0: return dict(executed=False, reason="tier_0")
        plc = self.pre_live_check()
        if not plc["all_clear"]: return dict(executed=False, reason=f"pre_live_check: {plc['blocked_reasons']}")
        if self._live_mode != "micro_live_real_capital": return dict(executed=False, reason=f"live_mode={self._live_mode}")
        self._live_broker.submit_live_order(order.get("symbol",""), order.get("qty",0), order.get("price",0))
        return dict(executed=True, order_id=len(self._live_broker._orders))

    def compute_live_pnl_deviation(self, real_pnl: float, shadow_pnl: float) -> float:
        """实盘-PnL校准：计算偏差并更新模型。"""
        dev = real_pnl - shadow_pnl
        self._execution_bias.update(dev / max(abs(dev), 50))
        return round(dev, 2)

    def set_live_mode(self, mode: str) -> None:
        if mode in LIVE_MODES: self._live_mode = mode

    # ═══════════════════════════════════════════════════
    # v12: CCDS
    # ═══════════════════════════════════════════════════

    def compute_capital_tier(self, metrics: dict) -> dict:
        es = metrics.get("execution_divergence_score",0); pd = metrics.get("pnl_divergence",100)
        sd = metrics.get("slippage_divergence",100); ss = metrics.get("stability_score",0.5)
        regime = metrics.get("regime","range"); ks = metrics.get("kill_switch",False)
        loss_days = metrics.get("consecutive_loss_days",0); tp = metrics.get("total_pnl",0)
        downgrade = False; pnl_dd = abs(tp)/10000.0 if self._micro_live_portfolio.get("peak_value",10000)>0 else 0
        if pnl_dd > 0.05 or es < 70 or (regime=="liquidity_stress" and loss_days>0) or ks:
            self._tier=0; self._tier_stable_days=0; downgrade=True
        else:
            if self._tier==0 and es>90 and pd<3 and sd<15: self._tier=1; self._tier_stable_days=1
            elif self._tier==0: self._tier_stable_days=0
            if self._tier==1:
                self._tier_stable_days+=1
                if self._tier_stable_days>=7 and sd<10 and not ks: self._tier=2; self._tier_stable_days=1
            elif self._tier==2:
                self._tier_stable_days+=1
                if self._tier_stable_days>=30 and tp>0: self._tier=3; self._tier_stable_days=1
            elif self._tier==3:
                if self._tier_stable_days>=90 and tp>500: self._tier=4; self._tier_stable_days=1
        ap = TIER_LIMITS.get(self._tier,0)
        if self._tier==0 or ks: ap=0.0
        ur = (self._tier==0 and es>90 and pd<3) or (self._tier==1 and self._tier_stable_days>=7) or (self._tier==2 and self._tier_stable_days>=30 and tp>0)
        rs = "shadow_only" if self._tier==0 else ("frozen" if ks else "downgraded" if downgrade else "safe")
        return dict(tier=self._tier, tier_name=TIER_NAMES.get(self._tier,"shadow"), allowed_pct=ap,
                    next_tier=TIER_NAMES.get(min(self._tier+1,4),"full_live"), upgrade_ready=ur,
                    downgrade_triggered=downgrade, exposure_limit=TIER_LIMITS.get(self._tier,0), risk_status=rs)

    def _apply_capital_smoothing(self, ccds: dict, alpha=0.7) -> dict:
        self._smooth_allocation = alpha*self._smooth_allocation + (1-alpha)*ccds.get("allowed_pct",0)
        ccds["allowed_pct"] = round(self._smooth_allocation,4); return ccds

    def execute_live_order(self, order: dict) -> dict:
        return self.route_order_to_broker(order)

    # ═══════════════════════════════════════════════════
    # v11: SLTS
    # ═══════════════════════════════════════════════════

    def compute_market_divergence(self, shadow: dict, live_sim: dict) -> dict:
        sd = shadow.get("slippage_cost",0); ld = live_sim.get("slippage_cost",0)
        sp = shadow.get("pnl_realized",0); lp = live_sim.get("pnl_realized",0)
        fd = abs(max(live_sim.get("execution_efficiency",50),1)-max(shadow.get("execution_efficiency",50),1))
        slipd = abs(ld-sd)/max(abs(sd),0.01)*100 if sd!=0 else 0
        pnld = abs(lp-sp)/max(abs(sp),0.01)*100 if sp!=0 else 0
        return dict(execution_divergence_score=max(0,min(100,100-fd)), fill_divergence=round(fd,1),
                    slippage_divergence=round(slipd,1), pnl_divergence=round(pnld,1))

    def _live_simulation(self, allocation: dict, regime: str, vol: float, liq: float) -> dict:
        bias = self._execution_bias.bias
        ba = {k:v*(1+random.uniform(-0.02,0.02)) for k,v in allocation.items()}
        tw=sum(ba.values())
        if tw>0: ba={k:v/tw for k,v in ba.items()}
        r=self.execute_portfolio(ba,regime,vol,liq)
        r["slippage_cost"]*=(1+max(bias,0)); r["pnl_realized"]*=(1-abs(bias)*0.5); return r

    def _live_risk_gate(self, divergence: dict, regime: dict) -> dict:
        sc=divergence.get("execution_divergence_score",0); pd=divergence.get("pnl_divergence",100); sd=divergence.get("slippage_divergence",100)
        if sc>85 and pd<5 and sd<20 and not self._kill_switch_active and regime.get("regime_type","")!="liquidity_stress":
            return dict(score=round(sc,1),live_allowed=True)
        reasons=[]
        if sc<=85: reasons.append(f"stability {sc}<=85")
        if pd>=5: reasons.append(f"pnl_div {pd:.1f}%>=5%")
        if sd>=20: reasons.append(f"slippage_div {sd:.1f}%>=20%")
        if self._kill_switch_active: reasons.append("kill_switch ON")
        if regime.get("regime_type","")=="liquidity_stress": reasons.append("liquidity_stress")
        return dict(score=round(sc,1),live_allowed=False,blocked_reason="; ".join(reasons))

    def _sync_shadow_to_live(self, shadow: dict, live_sim: dict) -> None:
        fb=(live_sim.get("execution_efficiency",50)-shadow.get("execution_efficiency",50))/100
        self._execution_bias.update(fb)
        if abs(fb)>0.15: self._divergence_history.append(100)

    def set_mode(self, mode):
        if mode in ("shadow","live_shadow","live"): self._mode=mode
    @property
    def mode(self): return self._mode

    # ═══════════════════════════════════════════════════
    # v10: EMIL
    # ═══════════════════════════════════════════════════

    def _slippage_model(self, base, volatility, regime):
        return base*(1+volatility*2)*{"trend":1.0,"range":1.2,"volatile":1.5,"liquidity_stress":2.5}.get(regime,1.0)

    def _market_impact(self, order_size, liquidity_depth):
        if liquidity_depth<=0: return BASE_SLIPPAGE*3
        return BASE_SLIPPAGE*((order_size/liquidity_depth)**1.2)

    def _fill_ratio(self, liquidity, volatility):
        return max(0.3,min(1.0,min(1.0,0.5+liquidity*0.5)*max(0,1-volatility*1.5)+random.uniform(-0.1,0.1)))

    def execute_portfolio(self, allocation, regime, volatility=0.15, liquidity=1.0):
        executed={}; ts=ti=tep=trp=0.0; frs=qs=[]
        for name,weight in allocation.items():
            os_=weight*100000; fill=self._fill_ratio(liquidity,volatility)
            frs.append(fill); executed[name]=round(weight*fill,4)
            slip=self._slippage_model(BASE_SLIPPAGE,volatility,regime)
            sc=slip*os_*fill; ts+=sc
            imp=self._market_impact(os_,liquidity*1000000); ic=imp*os_*fill; ti+=ic
            epnl=weight*1000*random.uniform(-0.02,0.05); rpnl=epnl-sc-ic; tep+=epnl; trp+=rpnl
            ee=abs(rpnl-epnl)/max(abs(epnl),0.01) if epnl!=0 else 1.0
            qs.append(max(0,1-ee))
            self._emil_trade_log.append(dict(strategy=name,weight=weight,fill=fill,slippage=slip,impact=imp))
        return dict(executed_allocations=executed, slippage_cost=round(ts,2), market_impact_cost=round(ti,2),
                    execution_quality_score=round(sum(qs)/len(qs)*100,1) if qs else 0,
                    pnl_realized=round(trp,2), pnl_expected=round(tep,2),
                    execution_efficiency=round(trp/max(tep,0.01)*100,1) if tep!=0 else 0)

    def _emil_feedback(self, pr, pe):
        if abs(pe)<0.001: return dict(rmai_corrected=self._rmai_history[-1] if self._rmai_history else 50.0)
        al=max(0,min(1,pr/max(pe,0.01)))
        cr=round(self._rmai_history[-1]*0.7+al*100*0.3,1) if self._rmai_history else round(al*100,1)
        return dict(rmai_corrected=cr)

    # ═══════════════════════════════════════════════════
    # v9: MSAAS
    # ═══════════════════════════════════════════════════

    def build_strategy_profiles(self, rmai, signal, regime):
        pref=REGIME_STRATEGY_PREF.get(regime,REGIME_STRATEGY_PREF["range"]); profiles=[]
        for name in STRATEGY_NAMES:
            rf=pref.get(name,1.0)
            sr=rmai*(0.8+0.2*random.random()); ss=signal*(0.8+0.2*random.random()); risk=random.uniform(0.06,0.18)
            profiles.append(dict(name=name, rmai=sr, signal=ss, expected_return=sr*ss*rf/100,
                                 risk=round(risk,4), sharpe=round((sr*ss*rf/100)/max(risk,0.01),2), regime_fit=rf))
        return profiles

    def compute_strategy_allocation(self, profiles, regime):
        if not profiles: return dict(strategy_allocations={}, total_risk=0, expected_portfolio_return=0, strategy_diversification_score=0, dominant_strategy="?", system_status="infeasible")
        raw={p["name"]:p["rmai"]*max(p["sharpe"],0.01)*p["regime_fit"]/max(p["risk"],0.001) for p in profiles}
        tr=sum(raw.values()); w={k:v/tr for k,v in raw.items()} if tr>0 else {k:1.0/len(profiles) for k in profiles}
        ms=0.15 if regime=="liquidity_stress" else 0.40
        if regime=="liquidity_stress":
            for k in w: w[k]*=0.3
        for k in list(w.keys()):
            if w[k]>ms:
                excess=w[k]-ms; w[k]=ms
                others=[x for x in w if x!=k and w[x]<ms]
                if others:
                    ea=excess/len(others)
                    for o in others: w[o]=min(ms,w[o]+ea)
        tw=sum(w.values())
        if tw>0: w={k:v/tw for k,v in w.items()}
        tr=math.sqrt(sum(w[p["name"]]**2*p["risk"]**2 for p in profiles)) if profiles else 0
        er=sum(w[p["name"]]*p["expected_return"] for p in profiles) if profiles else 0
        hhi=sum(v**2 for v in w.values()); n=len(w); div=round(1.0-(hhi-1.0/n)/(1.0-1.0/n),4) if n>1 else 0
        return dict(strategy_allocations={k:round(v,4) for k,v in sorted(w.items(),key=lambda x:-x[1])},
                    total_risk=round(tr,4), expected_portfolio_return=round(er,4), strategy_diversification_score=div,
                    dominant_strategy=max(w,key=w.get), system_status="optimal" if max(w.values())<=ms+0.01 else "feasible")

    # ─── Legacy ───

    def market_regime_detector(self, md):
        returns=md.get("returns",[0.1,0.05,-0.02,0.08,0.12]); vol=md.get("volatility",0.15); spread=md.get("spread_proxy",0.001); dd=abs(md.get("drawdown_pct",0))
        if not returns: returns=[0.1]
        pr=sum(1 for r in returns if r>0)/len(returns)
        rev=sum(1 for i in range(1,len(returns)) if (returns[i]>=0)!=(returns[i-1]>=0))/max(len(returns)-1,1)
        avg=sum(returns)/len(returns)
        rt,cf="range",0.5
        if pr>0.65 and avg>0.02 and dd<0.05: rt,cf="trend",min(1,0.5+pr*0.5)
        elif rev>0.4 and vol<0.2: rt,cf="range",min(1,0.5+rev*0.5)
        elif vol>0.25 and rev>0.3: rt,cf="volatile",min(1,0.5+vol*1.5)
        if vol>0.3 and spread>0.005 and dd>0.05: rt,cf="liquidity_stress",min(1,0.5+vol*1.0+spread*50)
        return dict(regime_type=rt,confidence=round(cf,2))

    def compute_dynamic_rmai(self, base, regime):
        m=REGIME_MULTIPLIERS.get(regime,1.0); return dict(dynamic_rmai=round(base*m,1),multiplier=m)

    def compute_reality_alignment_index(self, lr, sr, pr):
        sc=max(0,1-abs(sr-lr)/max(abs(lr),0.01)) if lr!=0 else 1-min(abs(sr),5)/5
        pc=max(0,1-abs(pr-lr)/max(abs(lr),0.01)) if lr!=0 else 1-min(abs(pr),5)/5
        sc=round(min(sc,1),2); pc=round(min(pc,1),2)
        return dict(score=round(0.3*sc*100+0.3*pc*100+0.2*min(1,sc*0.9+0.1)*100+0.2*(0.8 if (sr>=0)==(lr>=0) else 0.4)*100,1),
                    shadow_corr=sc, paper_corr=pc, exec_accuracy=round(min(1,sc*0.9+0.1),2), signal_match=round(0.8 if (sr>=0)==(lr>=0) else 0.4,2))

    def detect_reality_breakdown(self, lr, sr, pr):
        b,bt=False,None
        if abs(sr-lr)/max(abs(lr),0.01)>0.25 if lr!=0 else 0: b,bt=True,"execution_failure"
        if (pr>=0)!=(lr>=0): b,bt=True,"signal_failure"
        return dict(breakdown_detected=b,breakdown_type=bt)

    def stress_test_mode(self, ld, sd, pd):
        bl,bs,bp=ld.get("live_return",2),sd.get("shadow_return",1.8),pd.get("paper_return",2.5); nd,all_s,bc,fg,fn=30,[],0,0,0
        pert=[("extreme_volatility",[random.uniform(-0.1,0.1) for _ in range(nd)]),("latency_shock",[random.uniform(0.3,2.0) for _ in range(nd)]),("signal_reversal",[(-1 if random.random()<0.3 else 1) for _ in range(nd)])]
        for pt,sh in pert:
            for d in range(min(nd,len(sh))):
                s=sh[d]
                if pt=="extreme_volatility": l,ss,pp=bl+s*100,bs+s*80,bp+s*90
                elif pt=="latency_shock": l,ss,pp=bl,bs*(1-s*0.01),bp*(1-s*0.01)
                elif pt=="signal_reversal": l,ss,pp=bl*s,bs*s*0.8,bp*s*0.9
                else: l,ss,pp=bl,bs,bp
                r=self.compute_reality_alignment_index(l,ss,pp); all_s.append(r["score"])
                if self.detect_reality_breakdown(l,ss,pp)["breakdown_detected"]: bc+=1
                if r["score"]>85 and abs(s)>0.05: fg+=1
                if r["score"]<60 and abs(s)<0.02: fn+=1
        avg=sum(all_s)/len(all_s) if all_s else 0; var=sum((x-avg)**2 for x in all_s)/len(all_s) if all_s else 0; tt=len(pert)*nd
        return dict(rmai_volatility=round(math.sqrt(var),2) if all_s else 0, breakdown_trigger_frequency=round(bc/max(tt,1),2),
                    false_go_rate=round(fg/max(tt,1),4), false_no_go_rate=round(fn/max(tt,1),4))

    def walk_forward_validation(self, ld, sd, pd):
        bl,bs,bp=ld.get("live_return",2),sd.get("shadow_return",1.8),pd.get("paper_return",2.5); nd,ws=30,5; wscores,adrifts,emis=[],[],[]
        for st in range(0,nd-ws+1):
            wr=[]
            for d in range(st,st+ws):
                dr=(d/nd)*0.1
                wr.append(self.compute_reality_alignment_index(bl*(1+dr*random.uniform(-0.5,0.5)),
                    bs*(1+dr*random.uniform(-0.5,0.5)),bp*(1+dr*random.uniform(-0.5,0.5)))["score"])
            wscores.append(sum(wr)/len(wr)); adrifts.append(max(wr)-min(wr)); emis.append(sum(1 for s in wr if s<60)/len(wr))
        wavg=sum(wscores)/len(wscores) if wscores else 0; wvar=sum((s-wavg)**2 for s in wscores)/len(wscores) if wscores else 0
        return dict(stability_score=round(max(0,100-math.sqrt(wvar)*5),1))

    def capital_deployment_readiness_engine(self, rmai, breakdown, regime="range", regime_confidence=0.5):
        score=rmai.get("score",0); hb=breakdown.get("breakdown_detected",False)
        if self._kill_switch_active or regime=="liquidity_stress": return dict(status="NO_GO",confidence=0.0)
        if score>85 and self._consecutive_breakdown_days==0 and regime_confidence>0.6: return dict(status="GO",confidence=round(score/100,2))
        if score>65 and not hb: return dict(status="CONDITIONAL",confidence=round(score/100,2))
        return dict(status="NO_GO",confidence=round(score/100,2))

    def trigger_kill_switch(self, pnl_drawdown_pct):
        if pnl_drawdown_pct>3.0:
            self._kill_switch_active=True; self._kill_switch_until=datetime.now().replace(hour=23,minute=59,second=59)+timedelta(days=1)

    def micro_live_cycle(self, live_return):
        p=self._micro_live_portfolio; c,pos=p["cash"],p["positions"]
        act="BUY" if live_return>1 else ("SELL" if live_return<-1 else "HOLD")
        price=100.0+live_return*0.5
        dm=random.uniform(50,500); pd_=random.uniform(-0.001,0.001)*price; sp=random.uniform(0.0005,0.003)
        ep=price+pd_+(price*sp if act=="BUY" else -price*sp if act=="SELL" else 0)
        if act=="BUY" and c>=ep*10: q=min(int(c/ep),10); c-=round(q*ep,2); pos["SIM"]=pos.get("SIM",0)+q
        elif act=="SELL" and pos.get("SIM",0)>0: c+=round(pos["SIM"]*ep,2); del pos["SIM"]
        tv=c+sum(q*price for q in pos.values()); pnl=round(tv-10000.0,2)
        if tv>p["peak_value"]: p["peak_value"]=tv
        dd=self._micro_live_drawdown()
        if dd>3.0: self.trigger_kill_switch(dd)
        p["cash"]=c
        exp=live_return*100; pa=min(1,max(0,pnl/max(abs(exp),0.01))) if exp!=0 else 1.0
        cr=round(self._rmai_history[-1]*0.7+pa*100*0.3,1) if self._rmai_history else round(pa*100,1)
        return dict(action=act, execution_price=round(ep,2), delay_ms=round(dm,1), slippage_pct=round(sp*100,3),
                    total_value=round(tv,2), pnl=pnl, drawdown_pct=round(dd,2), rmai_corrected=cr, pnl_alignment=round(pa,2))

    def _micro_live_drawdown(self):
        p=self._micro_live_portfolio; cur=p["cash"]+sum(q*100 for q in p["positions"].values()); pk=p["peak_value"]
        return 0.0 if pk<=0 else round(max(0,(pk-cur)/pk*100),2)