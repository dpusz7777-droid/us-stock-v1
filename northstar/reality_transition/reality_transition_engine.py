#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""现实市场迁移与真实资金验证准备层 — v10.

v10: Execution & Market Impact Layer (EMIL).
将 v9 portfolio allocation 转换为真实执行模拟系统 + 市场冲击/滑点/反馈闭环。

仍不执行真实交易，只做真实数据驱动的行为对照与资金安全预演。
"""

from __future__ import annotations

import json
import math
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

BASE_SLIPPAGE = 0.001
REGIME_MULTIPLIERS = {"trend": 1.0, "range": 0.9, "volatile": 0.6, "liquidity_stress": 0.2}
STRATEGY_NAMES = ["momentum", "mean_reversion", "regime", "breakout", "ai_signal"]

REGIME_STRATEGY_PREF = {
    "trend": {"momentum": 1.5, "mean_reversion": 0.3, "regime": 1.0, "breakout": 1.4, "ai_signal": 1.0},
    "range": {"momentum": 0.4, "mean_reversion": 1.5, "regime": 1.0, "breakout": 0.5, "ai_signal": 1.0},
    "volatile": {"momentum": 0.6, "mean_reversion": 0.5, "regime": 1.3, "breakout": 0.7, "ai_signal": 1.4},
    "liquidity_stress": {"momentum": 0.3, "mean_reversion": 0.3, "regime": 0.3, "breakout": 0.3, "ai_signal": 0.3},
}


class RealityTransitionEngine:
    def __init__(self) -> None:
        self._consecutive_breakdown_days: int = 0
        self._kill_switch_active: bool = False
        self._kill_switch_until: datetime | None = None
        self._micro_live_portfolio: dict[str, Any] = {"cash": 10000.0, "positions": {}, "peak_value": 10000.0}
        self._rmai_history: list[float] = []
        self._emil_trade_log: list[dict] = []

    def run_reality_mirror_cycle(self, live_market_data: dict[str, Any] | None = None,
                                  shadow_data: dict[str, Any] | None = None,
                                  paper_data: dict[str, Any] | None = None) -> dict[str, Any]:
        lm = live_market_data or {"live_return": 2.0, "volatility": 0.15, "volume": 1.0, "spread_proxy": 0.001, "returns": [0.1, 0.2, 0.15]}
        sd = shadow_data or {"shadow_return": 1.8}
        pd = paper_data or {"paper_return": 2.5}
        lr = lm.get("live_return", 0); sr = sd.get("shadow_return", 0); pr = pd.get("paper_return", 0)
        vol = lm.get("volatility", 0.15); liq = lm.get("volume", 1.0)

        regime = self.market_regime_detector(lm)
        base_rmai = self.compute_reality_alignment_index(lr, sr, pr)
        self._rmai_history.append(base_rmai["score"])
        dynamic = self.compute_dynamic_rmai(base_rmai["score"], regime["regime_type"])
        breakdown = self.detect_reality_breakdown(lr, sr, pr)
        self._consecutive_breakdown_days = self._consecutive_breakdown_days + 1 if breakdown["breakdown_detected"] else 0

        strategies = self.build_strategy_profiles(dynamic["dynamic_rmai"], base_rmai["signal_match"], regime["regime_type"])
        meta = self.compute_strategy_allocation(strategies, regime["regime_type"])

        # v10: Execution & Market Impact Layer
        emil = self.execute_portfolio(meta["strategy_allocations"], regime["regime_type"], vol, liq)

        # PnL Feedback Loop
        pnl_realized = emil["pnl_realized"]
        pnl_expected = emil["pnl_expected"]
        feedback = self._emil_feedback(pnl_realized, pnl_expected)

        readiness = self.capital_deployment_readiness_engine({"score": dynamic["dynamic_rmai"]}, breakdown, regime["regime_type"], regime["confidence"])
        stress = self.stress_test_mode(lm, sd, pd)
        wfv = self.walk_forward_validation(lm, sd, pd)
        micro = self.micro_live_cycle(lr)
        ks = {"kill_switch_active": self._kill_switch_active}
        if self._kill_switch_active and self._kill_switch_until and datetime.now() >= self._kill_switch_until:
            self._kill_switch_active = False; self._kill_switch_until = None; ks["kill_switch_active"] = False

        result = dict(date=date.today().isoformat(), rmai_score=base_rmai["score"],
                      dynamic_rmai=dynamic["dynamic_rmai"], current_regime=regime["regime_type"],
                      regime_confidence=regime["confidence"],
                      strategy_allocations=meta["strategy_allocations"],
                      total_risk=meta["total_risk"],
                      expected_portfolio_return=meta["expected_portfolio_return"],
                      strategy_diversification_score=meta["strategy_diversification_score"],
                      dominant_strategy=meta["dominant_strategy"],
                      system_status=meta["system_status"],
                      executed_allocations=emil["executed_allocations"],
                      slippage_cost=emil["slippage_cost"],
                      market_impact_cost=emil["market_impact_cost"],
                      execution_quality_score=emil["execution_quality_score"],
                      pnl_realized=pnl_realized, pnl_expected=pnl_expected,
                      execution_efficiency=emil["execution_efficiency"],
                      rmai_corrected=feedback["rmai_corrected"],
                      shadow_vs_live_correlation=base_rmai["shadow_corr"],
                      paper_vs_live_correlation=base_rmai["paper_corr"],
                      execution_accuracy=base_rmai["exec_accuracy"],
                      signal_match_rate=base_rmai["signal_match"],
                      breakdown_detected=breakdown["breakdown_detected"],
                      breakdown_type=breakdown.get("breakdown_type"),
                      consecutive_breakdown_days=self._consecutive_breakdown_days,
                      capital_readiness=readiness, stress_test=stress, walk_forward=wfv,
                      micro_live_sandbox=micro, kill_switch=ks)

        today = date.today().isoformat().replace("-", "")
        reports_dir = Path(__file__).parent.parent.parent / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        with open(reports_dir / f"reality_transition_{today}.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return result

    # ═══════════════════════════════════════════════════════════════════
    # v10: Execution & Market Impact Layer (EMIL)
    # ═══════════════════════════════════════════════════════════════════

    def _slippage_model(self, base: float, volatility: float, regime: str) -> float:
        """滑点模型: base_slippage × volatility_ratio × regime_multiplier."""
        mult = {"trend": 1.0, "range": 1.2, "volatile": 1.5, "liquidity_stress": 2.5}.get(regime, 1.0)
        return base * (1 + volatility * 2) * mult

    def _market_impact(self, order_size: float, liquidity_depth: float) -> float:
        """市场冲击: base × (order / liquidity)^1.2."""
        if liquidity_depth <= 0: return BASE_SLIPPAGE * 3
        ratio = order_size / liquidity_depth
        return BASE_SLIPPAGE * (ratio ** 1.2)

    def _fill_ratio(self, liquidity: float, volatility: float) -> float:
        """随机成交率: 基于流动性和波动率的随机函数."""
        base = min(1.0, 0.5 + liquidity * 0.5)
        noise = random.uniform(-0.1, 0.1)
        vol_penalty = max(0, 1 - volatility * 1.5)
        return max(0.3, min(1.0, base * vol_penalty + noise))

    def execute_portfolio(self, allocation: dict[str, float], regime: str,
                          volatility: float = 0.15, liquidity: float = 1.0) -> dict[str, Any]:
        """执行 portfolio 并模拟市场摩擦。"""
        executed = {}
        total_slippage = 0.0
        total_impact = 0.0
        total_expected_pnl = 0.0
        total_realized_pnl = 0.0
        fill_rates = []
        quality_scores = []

        for name, weight in allocation.items():
            order_size = weight * 100000  # 名义金额
            fill = self._fill_ratio(liquidity, volatility)
            fill_rates.append(fill)
            realized_w = weight * fill
            executed[name] = round(realized_w, 4)

            # Slippage
            slip = self._slippage_model(BASE_SLIPPAGE, volatility, regime)
            slip_cost = slip * order_size * fill
            total_slippage += slip_cost

            # Market impact
            impact = self._market_impact(order_size, liquidity * 1000000)
            impact_cost = impact * order_size * fill
            total_impact += impact_cost

            # Delay (random 50-500ms)
            delay_ms = random.uniform(50, 500)

            # PnL
            exp_pnl = weight * 1000 * random.uniform(-0.02, 0.05)
            real_pnl = exp_pnl - slip_cost - impact_cost
            total_expected_pnl += exp_pnl
            total_realized_pnl += real_pnl

            exec_err = abs(real_pnl - exp_pnl) / max(abs(exp_pnl), 0.01) if exp_pnl != 0 else 1.0
            quality_scores.append(max(0, 1 - exec_err))

            self._emil_trade_log.append(dict(strategy=name, weight=weight, fill=fill, slippage=slip,
                                              impact=impact, delay_ms=delay_ms, pnl_expected=round(exp_pnl, 2),
                                              pnl_realized=round(real_pnl, 2)))

        avg_fill = sum(fill_rates) / len(fill_rates) if fill_rates else 0
        exec_quality = round(sum(quality_scores) / len(quality_scores) * 100, 1) if quality_scores else 0
        exec_eff = round(total_realized_pnl / max(total_expected_pnl, 0.01) * 100, 1) if total_expected_pnl != 0 else 0

        return dict(executed_allocations=executed, slippage_cost=round(total_slippage, 2),
                    market_impact_cost=round(total_impact, 2), execution_quality_score=exec_quality,
                    pnl_realized=round(total_realized_pnl, 2), pnl_expected=round(total_expected_pnl, 2),
                    execution_efficiency=exec_eff)

    def _emil_feedback(self, pnl_realized: float, pnl_expected: float) -> dict[str, Any]:
        """PnL 反馈循环 — 修正 RMAI。"""
        if abs(pnl_expected) < 0.001:
            return dict(rmai_corrected=self._rmai_history[-1] if self._rmai_history else 50.0)
        alignment = max(0, min(1, pnl_realized / max(pnl_expected, 0.01)))
        if self._rmai_history:
            corrected = round(self._rmai_history[-1] * 0.7 + alignment * 100 * 0.3, 1)
        else:
            corrected = round(alignment * 100, 1)
        return dict(rmai_corrected=corrected)

    # ═══════════════════════════════════════════════════
    # v9: MSAAS (unchanged)
    # ═══════════════════════════════════════════════════

    def build_strategy_profiles(self, rmai: float, signal: float, regime: str) -> list[dict[str, Any]]:
        pref = REGIME_STRATEGY_PREF.get(regime, REGIME_STRATEGY_PREF["range"])
        profiles = []
        for name in STRATEGY_NAMES:
            rf = pref.get(name, 1.0)
            sr = rmai * (0.8 + 0.2 * random.random())
            ss = signal * (0.8 + 0.2 * random.random())
            ret = sr * ss * rf / 100
            risk = random.uniform(0.06, 0.18)
            sharpe = ret / max(risk, 0.01)
            profiles.append(dict(name=name, rmai=sr, signal=ss, expected_return=ret,
                                 risk=round(risk, 4), sharpe=round(sharpe, 2), regime_fit=rf))
        return profiles

    def compute_strategy_allocation(self, profiles: list[dict[str, Any]], regime: str) -> dict[str, Any]:
        if not profiles:
            return dict(strategy_allocations={}, total_risk=0, expected_portfolio_return=0,
                        strategy_diversification_score=0, dominant_strategy="?", system_status="infeasible")
        raw = {}
        for p in profiles:
            raw[p["name"]] = p["rmai"] * max(p["sharpe"], 0.01) * p["regime_fit"] / max(p["risk"], 0.001)
        tr = sum(raw.values())
        weights = {k: v / tr for k, v in raw.items()} if tr > 0 else {k: 1.0 / len(profiles) for k in profiles}
        ms = 0.15 if regime == "liquidity_stress" else 0.40
        if regime == "liquidity_stress":
            for k in weights: weights[k] *= 0.3
        for k in list(weights.keys()):
            if weights[k] > ms:
                excess = weights[k] - ms; weights[k] = ms
                others = [x for x in weights if x != k and weights[x] < ms]
                if others:
                    ea = excess / len(others)
                    for o in others: weights[o] = min(ms, weights[o] + ea)
        tw = sum(weights.values())
        if tw > 0: weights = {k: v / tw for k, v in weights.items()}
        total_risk = math.sqrt(sum(weights[p["name"]]**2 * p["risk"]**2 for p in profiles)) if profiles else 0
        exp_ret = sum(weights[p["name"]] * p["expected_return"] for p in profiles) if profiles else 0
        hhi = sum(w**2 for w in weights.values())
        n = len(weights)
        div = round(1.0 - (hhi - 1.0 / n) / (1.0 - 1.0 / n), 4) if n > 1 else 0
        dominant = max(weights, key=weights.get)
        return dict(strategy_allocations={k: round(v, 4) for k, v in sorted(weights.items(), key=lambda x: -x[1])},
                    total_risk=round(total_risk, 4), expected_portfolio_return=round(exp_ret, 4),
                    strategy_diversification_score=div, dominant_strategy=dominant,
                    system_status="optimal" if max(weights.values()) <= ms + 0.01 else "feasible")

    # ─── Regime Detector ───

    def market_regime_detector(self, md: dict[str, Any]) -> dict[str, Any]:
        returns = md.get("returns", [0.1, 0.05, -0.02, 0.08, 0.12]); vol = md.get("volatility", 0.15)
        spread = md.get("spread_proxy", 0.001); dd = abs(md.get("drawdown_pct", 0))
        if not returns: returns = [0.1]
        pr = sum(1 for r in returns if r > 0) / len(returns)
        rev = sum(1 for i in range(1, len(returns)) if (returns[i] >= 0) != (returns[i-1] >= 0)) / max(len(returns)-1, 1)
        avg = sum(returns) / len(returns)
        rt, cf = "range", 0.5
        if pr > 0.65 and avg > 0.02 and dd < 0.05: rt, cf = "trend", min(1, 0.5+pr*0.5)
        elif rev > 0.4 and vol < 0.2: rt, cf = "range", min(1, 0.5+rev*0.5)
        elif vol > 0.25 and rev > 0.3: rt, cf = "volatile", min(1, 0.5+vol*1.5)
        if vol > 0.3 and spread > 0.005 and dd > 0.05: rt, cf = "liquidity_stress", min(1, 0.5+vol*1.0+spread*50)
        return dict(regime_type=rt, confidence=round(cf, 2))

    def compute_dynamic_rmai(self, base: float, regime: str) -> dict[str, Any]:
        m = REGIME_MULTIPLIERS.get(regime, 1.0)
        return dict(dynamic_rmai=round(base * m, 1), multiplier=m)

    def compute_reality_alignment_index(self, lr: float, sr: float, pr: float) -> dict[str, Any]:
        sc = max(0, 1 - abs(sr-lr)/max(abs(lr), 0.01)) if lr != 0 else 1-min(abs(sr),5)/5
        pc = max(0, 1 - abs(pr-lr)/max(abs(lr), 0.01)) if lr != 0 else 1-min(abs(pr),5)/5
        sc = round(min(sc,1),2); pc = round(min(pc,1),2)
        return dict(score=round(0.3*sc*100+0.3*pc*100+0.2*min(1,sc*0.9+0.1)*100+0.2*(0.8 if (sr>=0)==(lr>=0) else 0.4)*100, 1),
                    shadow_corr=sc, paper_corr=pc, exec_accuracy=round(min(1,sc*0.9+0.1),2),
                    signal_match=round(0.8 if (sr>=0)==(lr>=0) else 0.4,2))

    def detect_reality_breakdown(self, lr: float, sr: float, pr: float) -> dict[str, Any]:
        b, bt = False, None
        if abs(sr-lr)/max(abs(lr),0.01) > 0.25 if lr != 0 else 0: b, bt = True, "execution_failure"
        if (pr>=0) != (lr>=0): b, bt = True, "signal_failure"
        return dict(breakdown_detected=b, breakdown_type=bt)

    def stress_test_mode(self, ld: dict, sd: dict, pd: dict) -> dict[str, Any]:
        bl, bs, bp = ld.get("live_return",2), sd.get("shadow_return",1.8), pd.get("paper_return",2.5)
        nd, all_s, bc, fg, fn = 30, [], 0, 0, 0
        pert = [("extreme_volatility", [random.uniform(-0.1,0.1) for _ in range(nd)]),
                ("latency_shock", [random.uniform(0.3,2.0) for _ in range(nd)]),
                ("signal_reversal", [(-1 if random.random()<0.3 else 1) for _ in range(nd)])]
        for pt, sh in pert:
            for d in range(min(nd, len(sh))):
                s = sh[d]
                if pt == "extreme_volatility": l, ss, pp = bl+s*100, bs+s*80, bp+s*90
                elif pt == "latency_shock": l, ss, pp = bl, bs*(1-s*0.01), bp*(1-s*0.01)
                elif pt == "signal_reversal": l, ss, pp = bl*s, bs*s*0.8, bp*s*0.9
                else: l, ss, pp = bl, bs, bp
                r = self.compute_reality_alignment_index(l, ss, pp)
                all_s.append(r["score"])
                if self.detect_reality_breakdown(l, ss, pp)["breakdown_detected"]: bc += 1
                if r["score"]>85 and abs(s)>0.05: fg += 1
                if r["score"]<60 and abs(s)<0.02: fn += 1
        avg = sum(all_s)/len(all_s) if all_s else 0
        var = sum((x-avg)**2 for x in all_s)/len(all_s) if all_s else 0
        tt = len(pert)*nd
        return dict(rmai_volatility=round(math.sqrt(var),2) if all_s else 0,
                    breakdown_trigger_frequency=round(bc/max(tt,1),2),
                    false_go_rate=round(fg/max(tt,1),4), false_no_go_rate=round(fn/max(tt,1),4))

    def walk_forward_validation(self, ld: dict, sd: dict, pd: dict) -> dict[str, Any]:
        bl, bs, bp = ld.get("live_return",2), sd.get("shadow_return",1.8), pd.get("paper_return",2.5)
        nd, ws = 30, 5; wscores, adrifts, emis = [], [], []
        for st in range(0, nd-ws+1):
            wr = []
            for d in range(st, st+ws):
                dr = (d/nd)*0.1
                wr.append(self.compute_reality_alignment_index(bl*(1+dr*random.uniform(-0.5,0.5)),
                    bs*(1+dr*random.uniform(-0.5,0.5)), bp*(1+dr*random.uniform(-0.5,0.5)))["score"])
            wscores.append(sum(wr)/len(wr)); adrifts.append(max(wr)-min(wr)); emis.append(sum(1 for s in wr if s<60)/len(wr))
        wavg = sum(wscores)/len(wscores) if wscores else 0
        wvar = sum((s-wavg)**2 for s in wscores)/len(wscores) if wscores else 0
        return dict(stability_score=round(max(0,100-math.sqrt(wvar)*5),1))

    def capital_deployment_readiness_engine(self, rmai: dict, breakdown: dict, regime: str = "range", regime_confidence: float = 0.5) -> dict[str, Any]:
        score = rmai.get("score", 0); hb = breakdown.get("breakdown_detected", False)
        if self._kill_switch_active: return dict(status="NO_GO", confidence=0.0)
        if regime == "liquidity_stress": return dict(status="NO_GO", confidence=0.0)
        if score > 85 and self._consecutive_breakdown_days == 0 and regime_confidence > 0.6: return dict(status="GO", confidence=round(score/100,2))
        if score > 65 and not hb: return dict(status="CONDITIONAL", confidence=round(score/100,2))
        return dict(status="NO_GO", confidence=round(score/100,2))

    def trigger_kill_switch(self, pnl_drawdown_pct: float) -> None:
        if pnl_drawdown_pct > 3.0:
            self._kill_switch_active = True
            self._kill_switch_until = datetime.now().replace(hour=23, minute=59, second=59) + timedelta(days=1)

    def micro_live_cycle(self, live_return: float) -> dict[str, Any]:
        p = self._micro_live_portfolio; c, pos = p["cash"], p["positions"]
        act = "BUY" if live_return > 1 else ("SELL" if live_return < -1 else "HOLD")
        price = 100.0 + live_return * 0.5
        dm = random.uniform(50, 500); pd_ = random.uniform(-0.001, 0.001) * price; sp = random.uniform(0.0005, 0.003)
        ep = price + pd_ + (price*sp if act == "BUY" else -price*sp if act == "SELL" else 0)
        if act == "BUY" and c >= ep*10:
            q = min(int(c/ep), 10); c -= round(q*ep, 2); pos["SIM"] = pos.get("SIM", 0) + q
        elif act == "SELL" and pos.get("SIM", 0) > 0:
            c += round(pos["SIM"]*ep, 2); del pos["SIM"]
        tv = c + sum(q*price for q in pos.values()); pnl = round(tv-10000.0, 2)
        if tv > p["peak_value"]: p["peak_value"] = tv
        dd = self._micro_live_drawdown()
        if dd > 3.0: self.trigger_kill_switch(dd)
        p["cash"] = c
        exp = live_return*100; pa = min(1, max(0, pnl/max(abs(exp), 0.01))) if exp != 0 else 1.0
        cr = round(self._rmai_history[-1]*0.7 + pa*100*0.3, 1) if self._rmai_history else round(pa*100, 1)
        return dict(action=act, execution_price=round(ep,2), delay_ms=round(dm,1), slippage_pct=round(sp*100,3),
                    total_value=round(tv,2), pnl=pnl, drawdown_pct=round(dd,2), rmai_corrected=cr,
                    pnl_alignment=round(pa,2))

    def _micro_live_drawdown(self) -> float:
        p = self._micro_live_portfolio
        cur = p["cash"] + sum(q*100 for q in p["positions"].values())
        pk = p["peak_value"]
        return 0.0 if pk <= 0 else round(max(0, (pk-cur)/pk*100), 2)