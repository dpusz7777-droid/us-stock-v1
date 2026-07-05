#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""现实市场迁移与真实资金验证准备层 — v5.

v5: Risk-Constrained Portfolio Optimizer (RCPO) — 约束优化分配系统。
替换heuristic allocation为constrained optimization。

仍不执行真实交易，只做真实数据驱动的行为对照与资金安全预演。
"""

from __future__ import annotations

import json
import math
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

TARGET_VOLATILITY = 0.10
MAX_DRAWDOWN_ESTIMATE = 0.05
REGIME_MULTIPLIERS = {"trend": 1.0, "range": 0.9, "volatile": 0.6, "liquidity_stress": 0.2}


class RealityTransitionEngine:
    """现实过渡引擎 v5 — Risk-Constrained Portfolio Optimizer。"""

    def __init__(self) -> None:
        self._consecutive_breakdown_days: int = 0
        self._kill_switch_active: bool = False
        self._kill_switch_until: datetime | None = None
        self._micro_live_portfolio: dict[str, Any] = {"cash": 10000.0, "positions": {}, "peak_value": 10000.0}
        self._rmai_history: list[float] = []

    def run_reality_mirror_cycle(self, live_market_data: dict[str, Any] | None = None,
                                  shadow_data: dict[str, Any] | None = None,
                                  paper_data: dict[str, Any] | None = None) -> dict[str, Any]:
        lm = live_market_data or {"live_return": 2.0, "volatility": 0.15, "volume": 1.0, "spread_proxy": 0.001, "returns": [0.1, 0.2, 0.15]}
        sd = shadow_data or {"shadow_return": 1.8}
        pd = paper_data or {"paper_return": 2.5}
        lr = lm.get("live_return", 0); sr = sd.get("shadow_return", 0); pr = pd.get("paper_return", 0)

        regime = self.market_regime_detector(lm)
        base_rmai = self.compute_reality_alignment_index(lr, sr, pr)
        self._rmai_history.append(base_rmai["score"])
        dynamic = self.compute_dynamic_rmai(base_rmai["score"], regime["regime_type"])
        breakdown = self.detect_reality_breakdown(lr, sr, pr)
        self._consecutive_breakdown_days = self._consecutive_breakdown_days + 1 if breakdown["breakdown_detected"] else 0
        drawdown = lm.get("drawdown_pct", 0)
        vol = lm.get("volatility", 0.15)
        corr = lm.get("correlation_matrix", None)

        # v5: Risk-Constrained Portfolio Optimizer
        allocation = self.compute_capital_allocation_signal(
            rmai=dynamic["dynamic_rmai"], regime=regime["regime_type"],
            regime_confidence=regime["confidence"], stability_score=0.8,
            drawdown=drawdown, pnl_alignment=0.8, volatility=vol,
            correlation_matrix=corr, signal_strength=base_rmai["signal_match"])
        readiness = self.capital_deployment_readiness_engine(
            {"score": dynamic["dynamic_rmai"]}, breakdown, regime=regime["regime_type"], regime_confidence=regime["confidence"])

        stress = self.stress_test_mode(lm, sd, pd)
        wfv = self.walk_forward_validation(lm, sd, pd)
        micro = self.micro_live_cycle(lr)
        ks = {"kill_switch_active": self._kill_switch_active}
        if self._kill_switch_active and self._kill_switch_until and datetime.now() >= self._kill_switch_until:
            self._kill_switch_active = False; self._kill_switch_until = None; ks["kill_switch_active"] = False

        result = dict(date=date.today().isoformat(), rmai_score=base_rmai["score"],
                      dynamic_rmai=dynamic["dynamic_rmai"], rmai_multiplier=dynamic["multiplier"],
                      current_regime=regime["regime_type"], regime_confidence=regime["confidence"],
                      regime_switch_probability=regime["regime_switch_probability"],
                      regime_adjusted_allocation_signal=dynamic["allocation_signal"],
                      capital_allocation_pct=round(allocation["optimized_allocation"] * 100, 1),
                      allocation_risk_level=allocation.get("risk_level", "medium"),
                      allocation_action=allocation.get("position_sizing_action", "hold"),
                      allocation_reasoning=allocation.get("reasoning", ""),
                      risk_adjusted_exposure=round(allocation["optimized_allocation"], 2),
                      risk_budget_used=allocation.get("risk_budget_used", 0),
                      expected_volatility=allocation.get("expected_volatility", 0),
                      constraint_saturation=allocation.get("constraint_saturation", {}),
                      optimizer_status=allocation.get("optimizer_status", "feasible"),
                      shadow_vs_live_correlation=base_rmai["shadow_corr"],
                      paper_vs_live_correlation=base_rmai["paper_corr"],
                      execution_accuracy=base_rmai["exec_accuracy"],
                      signal_match_rate=base_rmai["signal_match"],
                      breakdown_detected=breakdown["breakdown_detected"],
                      breakdown_type=breakdown.get("breakdown_type"),
                      consecutive_breakdown_days=self._consecutive_breakdown_days,
                      capital_readiness=readiness, divergence_matrix={"shadow_vs_live": round(sr - lr, 2), "paper_vs_live": round(pr - lr, 2)},
                      stress_test=stress, walk_forward=wfv, micro_live_sandbox=micro, kill_switch=ks)

        today = date.today().isoformat().replace("-", "")
        reports_dir = Path(__file__).parent.parent.parent / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        with open(reports_dir / f"reality_transition_{today}.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return result

    # ─── v5: Risk-Constrained Portfolio Optimizer ───

    def compute_capital_allocation_signal(self, rmai: float, regime: str = "range",
                                          regime_confidence: float = 0.5, stability_score: float = 0.8,
                                          drawdown: float = 0.0, pnl_alignment: float = 1.0,
                                          volatility: float = 0.15, correlation_matrix: Any = None,
                                          signal_strength: float = 0.5) -> dict[str, Any]:
        """Risk-Constrained Portfolio Optimizer.

        maximize: RMAI × regime_weight × signal_strength
        subject to:
          1. total_allocation ≤ 1.0
          2. volatility_budget ≤ TARGET_VOLATILITY (10%)
          3. max_drawdown_estimate ≤ MAX_DRAWDOWN_ESTIMATE (5%)
          4. liquidity_stress → allocation ≤ 0.1
          5. correlation penalty applied
        """
        # --- Objective ---
        reg_w = REGIME_MULTIPLIERS.get(regime, 1.0)
        raw_score = rmai * reg_w * signal_strength

        # --- Initial allocation guess ---
        alloc = raw_score / 10000.0  # normalize RMAI(0-100) * weight(0.2-1.0) * signal(0-1) → 0~100
        alloc = max(0.0, min(1.0, alloc))

        # --- Constraint 4: liquidity_stress hard cap ---
        if regime == "liquidity_stress":
            alloc = min(alloc, 0.1)

        # --- Constraint 1: total_allocation ≤ 1.0 (always satisfied by min) ---

        # --- Constraint 2: volatility budget ---
        est_vol = volatility * alloc
        if est_vol > TARGET_VOLATILITY:
            alloc = TARGET_VOLATILITY / max(volatility, 0.001)

        # --- Constraint 3: max drawdown estimate ---
        est_dd = drawdown * alloc
        if est_dd > MAX_DRAWDOWN_ESTIMATE:
            alloc = MAX_DRAWDOWN_ESTIMATE / max(drawdown, 0.001)

        # --- Constraint 5: correlation penalty ---
        corr_penalty = 1.0
        if correlation_matrix is not None and isinstance(correlation_matrix, dict):
            vals = list(correlation_matrix.values())
            avg_corr = sum(vals) / len(vals) if vals else 0
            if avg_corr > 0.5:
                corr_penalty = 1.0 - (avg_corr - 0.5) * 2
        alloc *= corr_penalty

        # --- Final clamp ---
        if drawdown > 0.05:
            alloc = 0.0
        if stability_score < 0.6:
            alloc = min(alloc, 0.2)

        alloc = max(0.0, min(1.0, alloc))

        # --- Output ---
        risk_budget_used = round((volatility * alloc) / TARGET_VOLATILITY, 2) if TARGET_VOLATILITY > 0 else 0
        expected_vol = round(volatility * alloc, 4)
        pct = round(alloc * 100, 1)
        sat = dict(allocation=round(alloc, 2), volatility=round(est_vol, 4) if volatility > 0 else 0,
                   drawdown=round(est_dd, 4) if drawdown > 0 else 0, regime=f"capped_{regime}" if regime == "liquidity_stress" else "ok")
        status = "feasible" if alloc >= 0.05 else ("tight" if alloc > 0 else "infeasible")

        if pct >= 60: rl = "low"; act = "increase"
        elif pct >= 35: rl = "medium"; act = "hold"
        elif pct >= 10: rl = "high"; act = "decrease"
        else: rl = "extreme"; act = "decrease"

        return dict(optimized_allocation=round(alloc, 4), risk_budget_used=risk_budget_used,
                    expected_volatility=expected_vol, constraint_saturation=sat,
                    optimizer_status=status, risk_level=rl, position_sizing_action=act,
                    reasoning=f"RCPO: RMAI={rmai:.0f} sig={signal_strength:.2f} vol={volatility:.2f} dd={drawdown:.2f} → {pct:.1f}% [{status}]")

    # ─── Market Regime Detector ───

    def market_regime_detector(self, market_data: dict[str, Any]) -> dict[str, Any]:
        returns = market_data.get("returns", [0.1, 0.05, -0.02, 0.08, 0.12])
        vol = market_data.get("volatility", 0.15)
        spread = market_data.get("spread_proxy", 0.001)
        dd = abs(market_data.get("drawdown_pct", 0))
        if not returns: returns = [0.1]
        pos_r = sum(1 for r in returns if r > 0) / len(returns)
        rev = sum(1 for i in range(1, len(returns)) if (returns[i] >= 0) != (returns[i-1] >= 0)) / max(len(returns)-1, 1)
        avg = sum(returns) / len(returns)

        rt, cf, sp = "range", 0.5, 0.1
        if pos_r > 0.65 and avg > 0.02 and dd < 0.05:
            rt, cf, sp = "trend", min(1, 0.5+pos_r*0.5), max(0.05, 0.3-pos_r*0.3)
        elif rev > 0.4 and vol < 0.2:
            rt, cf, sp = "range", min(1, 0.5+rev*0.5), 0.15
        elif vol > 0.25 and rev > 0.3:
            rt, cf, sp = "volatile", min(1, 0.5+vol*1.5), 0.3
        if vol > 0.3 and spread > 0.005 and dd > 0.05:
            rt, cf, sp = "liquidity_stress", min(1, 0.5+vol*1.0+spread*50), 0.4
        return dict(regime_type=rt, confidence=round(cf, 2), regime_switch_probability=round(sp, 2))

    def compute_dynamic_rmai(self, base_rmai: float, regime: str) -> dict[str, Any]:
        m = REGIME_MULTIPLIERS.get(regime, 1.0)
        d = round(base_rmai * m, 1)
        return dict(dynamic_rmai=d, multiplier=m, allocation_signal=round(min(d, 100), 1))

    def compute_reality_alignment_index(self, live_return: float, shadow_return: float, paper_return: float) -> dict[str, Any]:
        sc = max(0, 1 - abs(shadow_return - live_return) / max(abs(live_return), 0.01)) if live_return != 0 else 1 - min(abs(shadow_return), 5) / 5
        pc = max(0, 1 - abs(paper_return - live_return) / max(abs(live_return), 0.01)) if live_return != 0 else 1 - min(abs(paper_return), 5) / 5
        sc = round(min(sc, 1), 2); pc = round(min(pc, 1), 2)
        ea = round(min(1, sc*0.9+0.1), 2)
        sm = round(0.8 if (shadow_return >= 0) == (live_return >= 0) else 0.4, 2)
        return dict(score=round(0.3*sc*100+0.3*pc*100+0.2*ea*100+0.2*sm*100, 1),
                    shadow_corr=sc, paper_corr=pc, exec_accuracy=ea, signal_match=sm)

    def detect_reality_breakdown(self, lr: float, sr: float, pr: float) -> dict[str, Any]:
        b, bt = False, None
        if abs(sr - lr) / max(abs(lr), 0.01) > 0.25 if lr != 0 else 0: b, bt = True, "execution_failure"
        if (pr >= 0) != (lr >= 0): b, bt = True, "signal_failure"
        return dict(breakdown_detected=b, breakdown_type=bt)

    def stress_test_mode(self, ld: dict, sd: dict, pd: dict) -> dict[str, Any]:
        bl, bs, bp = ld.get("live_return", 2), sd.get("shadow_return", 1.8), pd.get("paper_return", 2.5)
        nd, all_s, bc, fg, fn = 30, [], 0, 0, 0
        pert = [("extreme_volatility", [random.uniform(-0.1, 0.1) for _ in range(nd)]),
                ("latency_shock", [random.uniform(0.3, 2.0) for _ in range(nd)]),
                ("signal_reversal", [(-1 if random.random() < 0.3 else 1) for _ in range(nd)])]
        for pt, sh in pert:
            for d in range(min(nd, len(sh))):
                s = sh[d]
                if pt == "extreme_volatility": l, ss, pp = bl + s * 100, bs + s * 80, bp + s * 90
                elif pt == "latency_shock": l, ss, pp = bl, bs * (1 - s * 0.01), bp * (1 - s * 0.01)
                elif pt == "signal_reversal": l, ss, pp = bl * s, bs * s * 0.8, bp * s * 0.9
                else: l, ss, pp = bl, bs, bp
                r = self.compute_reality_alignment_index(l, ss, pp)
                all_s.append(r["score"])
                if self.detect_reality_breakdown(l, ss, pp)["breakdown_detected"]: bc += 1
                if r["score"] > 85 and abs(s) > 0.05: fg += 1
                if r["score"] < 60 and abs(s) < 0.02: fn += 1
        avg = sum(all_s) / len(all_s) if all_s else 0
        var = sum((x - avg)**2 for x in all_s) / len(all_s) if all_s else 0
        tt = len(pert) * nd
        return dict(rmai_volatility=round(math.sqrt(var), 2) if all_s else 0,
                    breakdown_trigger_frequency=round(bc / max(tt, 1), 2),
                    false_go_rate=round(fg / max(tt, 1), 4), false_no_go_rate=round(fn / max(tt, 1), 4), total_stress_tests=tt)

    def walk_forward_validation(self, ld: dict, sd: dict, pd: dict) -> dict[str, Any]:
        bl, bs, bp = ld.get("live_return", 2), sd.get("shadow_return", 1.8), pd.get("paper_return", 2.5)
        nd, ws = 30, 5
        wscores, adrifts, emis = [], [], []
        for st in range(0, nd - ws + 1):
            wr = []
            for d in range(st, st + ws):
                dr = (d / nd) * 0.1
                wr.append(self.compute_reality_alignment_index(
                    bl * (1 + dr * random.uniform(-0.5, 0.5)),
                    bs * (1 + dr * random.uniform(-0.5, 0.5)),
                    bp * (1 + dr * random.uniform(-0.5, 0.5)))["score"])
            wscores.append(sum(wr) / len(wr))
            adrifts.append(max(wr) - min(wr))
            emis.append(sum(1 for s in wr if s < 60) / len(wr))
        wavg = sum(wscores) / len(wscores) if wscores else 0
        wvar = sum((s - wavg)**2 for s in wscores) / len(wscores) if wscores else 0
        return dict(stability_score=round(max(0, 100 - math.sqrt(wvar) * 5), 1),
                    regime_sensitivity="high" if max(adrifts) > 20 else ("medium" if max(adrifts) > 10 else "low") if adrifts else "low",
                    avg_alignment_drift=round(sum(adrifts) / len(adrifts), 2) if adrifts else 0,
                    execution_mismatch_rate=round(sum(emis) / len(emis), 2) if emis else 0, windows_analyzed=len(wscores))

    def capital_deployment_readiness_engine(self, rmai: dict, breakdown: dict, regime: str = "range", regime_confidence: float = 0.5) -> dict[str, Any]:
        score = rmai.get("score", 0)
        hb = breakdown.get("breakdown_detected", False)
        if self._kill_switch_active:
            return dict(status="NO_GO", confidence=0.0, max_safe_capital_pct=0.0, recommended_phase="shadow", kill_switch_active=True)
        if regime == "liquidity_stress":
            return dict(status="NO_GO", confidence=0.0, max_safe_capital_pct=0.0, recommended_phase="shadow", kill_switch_active=False)
        st, ms, ph = ("GO", 0.15, "micro_live") if (score > 85 and self._consecutive_breakdown_days == 0 and regime_confidence > 0.6) else \
                     ("CONDITIONAL", 0.05, "shadow") if (score > 65 and not hb) else ("NO_GO", 0.0, "shadow")
        return dict(status=st, confidence=round(score / 100, 2), max_safe_capital_pct=ms, recommended_phase=ph, kill_switch_active=False)

    def trigger_kill_switch(self, pnl_drawdown_pct: float) -> None:
        if pnl_drawdown_pct > 3.0:
            self._kill_switch_active = True
            self._kill_switch_until = datetime.now().replace(hour=23, minute=59, second=59) + timedelta(days=1)

    def micro_live_cycle(self, live_return: float) -> dict[str, Any]:
        p = self._micro_live_portfolio; c, pos = p["cash"], p["positions"]
        act = "BUY" if live_return > 1 else ("SELL" if live_return < -1 else "HOLD")
        price = 100.0 + live_return * 0.5
        dm = random.uniform(50, 500)
        pd_ = random.uniform(-0.001, 0.001) * price
        sp = random.uniform(0.0005, 0.003)
        ep = price + pd_ + (price * sp if act == "BUY" else -price * sp if act == "SELL" else 0)
        if act == "BUY" and c >= ep * 10:
            q = min(int(c / ep), 10); c -= round(q * ep, 2); pos["SIM"] = pos.get("SIM", 0) + q
        elif act == "SELL" and pos.get("SIM", 0) > 0:
            c += round(pos["SIM"] * ep, 2); del pos["SIM"]
        tv = c + sum(q * price for q in pos.values())
        pnl = round(tv - 10000.0, 2)
        if tv > p["peak_value"]: p["peak_value"] = tv
        dd = self._micro_live_drawdown()
        if dd > 3.0: self.trigger_kill_switch(dd)
        p["cash"] = c
        exp = live_return * 100
        pa = min(1, max(0, pnl / max(abs(exp), 0.01))) if exp != 0 else 1.0
        cr = round(self._rmai_history[-1] * 0.7 + pa * 100 * 0.3, 1) if self._rmai_history else round(pa * 100, 1)
        return dict(action=act, execution_price=round(ep, 2), delay_ms=round(dm, 1), slippage_pct=round(sp * 100, 3),
                    total_value=round(tv, 2), pnl=pnl, positions=dict(pos), drawdown_pct=round(dd, 2),
                    rmai_corrected=cr, pnl_alignment=round(pa, 2), kill_switch_triggered=self._kill_switch_active)

    def _micro_live_drawdown(self) -> float:
        p = self._micro_live_portfolio
        cur = p["cash"] + sum(q * 100 for q in p["positions"].values())
        pk = p["peak_value"]
        return 0.0 if pk <= 0 else round(max(0, (pk - cur) / pk * 100), 2)