#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""现实市场迁移与真实资金验证准备层 — v12.

v12: Controlled Capital Deployment System (CCDS).
资金分级系统 + 自动升降级 + 平滑控制 + 风险暴露限制。

仍不执行真实交易。所有资本部署受CCDS安全门控。
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
TIER_LIMITS = {0: 0.0, 1: 0.01, 2: 0.05, 3: 0.25, 4: 1.0}
TIER_NAMES = {0: "shadow", 1: "micro_live", 2: "limited_live", 3: "scaled_live", 4: "full_live"}


class BrokerAdapter:
    def __init__(self, name: str = "simulated"):
        self.name = name; self._status = "ready"; self._orders: list[dict] = []; self._fills: list[dict] = []
    def submit_order(self, symbol: str, qty: float, price: float, order_type: str = "limit") -> dict:
        o = dict(order_id=len(self._orders) + 1, symbol=symbol, qty=qty, price=price, type=order_type, status="submitted")
        self._orders.append(o); return o
    def cancel_order(self, order_id: int) -> bool:
        for o in self._orders:
            if o["order_id"] == order_id: o["status"] = "cancelled"; return True
        return False
    def fetch_fills(self) -> list[dict]: return self._fills
    def fetch_positions(self) -> list[dict]: return [{"symbol": "SIM", "qty": 10, "avg_price": 100.0}]
    @property
    def status(self) -> str: return self._status
    @status.setter
    def status(self, v: str) -> None: self._status = v


class ExecutionBiasModel:
    def __init__(self, alpha: float = 0.3): self.alpha = alpha; self.bias = 0.0
    def update(self, error: float) -> None: self.bias = self.alpha * error + (1 - self.alpha) * self.bias
    def apply(self, value: float) -> float: return value + self.bias


class RealityTransitionEngine:
    def __init__(self) -> None:
        self._consecutive_breakdown_days: int = 0
        self._kill_switch_active: bool = False
        self._kill_switch_until: datetime | None = None
        self._micro_live_portfolio: dict[str, Any] = {"cash": 10000.0, "positions": {}, "peak_value": 10000.0}
        self._rmai_history: list[float] = []
        self._emil_trade_log: list[dict] = []
        self._mode: str = "shadow"
        self._execution_bias = ExecutionBiasModel(alpha=0.3)
        self._broker = BrokerAdapter()
        self._divergence_history: list[float] = []
        # v12: CCDS state
        self._tier: int = 0
        self._tier_stable_days: int = 0
        self._consecutive_loss_days: int = 0
        self._smooth_allocation: float = 0.0
        self._total_pnl: float = 0.0

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

        shadow_result = self.execute_portfolio(meta["strategy_allocations"], regime["regime_type"], vol, liq)
        live_sim_result = self._live_simulation(meta["strategy_allocations"], regime["regime_type"], vol, liq)
        divergence = self.compute_market_divergence(shadow_result, live_sim_result)
        self._divergence_history.append(divergence["execution_divergence_score"])

        live_readiness = self._live_risk_gate(divergence, regime)
        if live_readiness["live_allowed"] and self._mode == "shadow": self._mode = "live_shadow"
        elif not live_readiness["live_allowed"]: self._mode = "shadow"
        self._sync_shadow_to_live(shadow_result, live_sim_result)

        pnl_realized = shadow_result["pnl_realized"]
        pnl_expected = shadow_result["pnl_expected"]
        feedback = self._emil_feedback(pnl_realized, pnl_expected)

        # v12: CCDS updates
        self._total_pnl += pnl_realized
        if pnl_realized < 0: self._consecutive_loss_days += 1
        else: self._consecutive_loss_days = 0
        ccds = self.compute_capital_tier(dict(
            execution_divergence_score=divergence["execution_divergence_score"],
            pnl_divergence=divergence["pnl_divergence"],
            slippage_divergence=divergence["slippage_divergence"],
            stability_score=0.8 if self._consecutive_breakdown_days == 0 else 0.5,
            regime=regime["regime_type"], kill_switch=self._kill_switch_active,
            consecutive_loss_days=self._consecutive_loss_days,
            total_pnl=self._total_pnl,
        ))
        ccds = self._apply_capital_smoothing(ccds, alpha=0.7)

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
                      mode=self._mode,
                      strategy_allocations=meta["strategy_allocations"],
                      total_risk=meta["total_risk"],
                      expected_portfolio_return=meta["expected_portfolio_return"],
                      dominant_strategy=meta["dominant_strategy"],
                      system_status=meta["system_status"],
                      executed_allocations=shadow_result["executed_allocations"],
                      slippage_cost=shadow_result["slippage_cost"],
                      market_impact_cost=shadow_result["market_impact_cost"],
                      execution_quality_score=shadow_result["execution_quality_score"],
                      pnl_realized=pnl_realized, pnl_expected=pnl_expected,
                      execution_efficiency=shadow_result["execution_efficiency"],
                      rmai_corrected=feedback["rmai_corrected"],
                      execution_divergence_score=divergence["execution_divergence_score"],
                      live_readiness_score=live_readiness["score"],
                      live_allowed=live_readiness["live_allowed"],
                      broker_adapter_status=self._broker.status,
                      slippage_bias=round(self._execution_bias.bias, 6),
                      # v12 CCDS fields
                      current_tier=ccds["tier_name"],
                      allowed_capital_pct=round(ccds["allowed_pct"] * 100, 2),
                      next_tier=ccds["next_tier"],
                      upgrade_ready=ccds["upgrade_ready"],
                      downgrade_triggered=ccds["downgrade_triggered"],
                      exposure_limit=round(ccds["exposure_limit"], 4),
                      risk_status=ccds["risk_status"],
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
    # v12: Controlled Capital Deployment System
    # ═══════════════════════════════════════════════════════════════════

    def compute_capital_tier(self, metrics: dict[str, Any]) -> dict[str, Any]:
        """计算当前资金层级及升降级状态。"""
        es = metrics.get("execution_divergence_score", 0)
        pd = metrics.get("pnl_divergence", 100)
        sd = metrics.get("slippage_divergence", 100)
        ss = metrics.get("stability_score", 0.5)
        regime = metrics.get("regime", "range")
        ks = metrics.get("kill_switch", False)
        loss_days = metrics.get("consecutive_loss_days", 0)
        total_pnl = metrics.get("total_pnl", 0)

        downgrade = False
        reason = ""
        pnl_dd = abs(total_pnl) / 10000.0 if self._micro_live_portfolio.get("peak_value", 10000) > 0 else 0

        # Auto-downgrade conditions
        if pnl_dd > 0.05 or es < 70 or (regime == "liquidity_stress" and loss_days > 0) or ks:
            self._tier = 0; self._tier_stable_days = 0
            downgrade = True
            reason = "auto-downgrade triggered"
        else:
            # Upgrade logic
            if self._tier == 0 and es > 90 and pd < 3 and sd < 15:
                self._tier = 1; self._tier_stable_days = 1
                reason = "upgraded to micro_live"
            elif self._tier == 0:
                self._tier_stable_days = 0

            if self._tier == 1:
                self._tier_stable_days += 1
                if self._tier_stable_days >= 7 and sd < 10 and not ks:
                    self._tier = 2; self._tier_stable_days = 1
                    reason = "upgraded to limited_live"
            elif self._tier == 2:
                self._tier_stable_days += 1
                if self._tier_stable_days >= 30 and total_pnl > 0:
                    self._tier = 3; self._tier_stable_days = 1
                    reason = "upgraded to scaled_live (manual confirm recommended)"
            elif self._tier == 3:
                if self._tier_stable_days >= 90 and total_pnl > 500:
                    self._tier = 4; self._tier_stable_days = 1
                    reason = "upgraded to full_live (manual confirm)"

        allowed_pct = TIER_LIMITS.get(self._tier, 0)
        if self._tier == 0: allowed_pct = 0.0
        if ks: allowed_pct = 0.0

        tier_name = TIER_NAMES.get(self._tier, "shadow")
        next_tier = TIER_NAMES.get(min(self._tier + 1, 4), "full_live")
        upgrade_ready = (self._tier == 0 and es > 90 and pd < 3) or \
                        (self._tier == 1 and self._tier_stable_days >= 7) or \
                        (self._tier == 2 and self._tier_stable_days >= 30 and total_pnl > 0)
        exposure_limit = TIER_LIMITS.get(self._tier, 0)
        risk_status = "safe"
        if self._tier == 0: risk_status = "shadow_only"
        if ks: risk_status = "frozen"
        if downgrade: risk_status = "downgraded"

        return dict(tier=self._tier, tier_name=tier_name, allowed_pct=allowed_pct,
                    next_tier=next_tier, upgrade_ready=upgrade_ready,
                    downgrade_triggered=downgrade, exposure_limit=exposure_limit,
                    risk_status=risk_status, reason=reason)

    def _apply_capital_smoothing(self, ccds: dict, alpha: float = 0.7) -> dict:
        """资金平滑：防止跳跃式加仓。"""
        target = ccds.get("allowed_pct", 0)
        self._smooth_allocation = alpha * self._smooth_allocation + (1 - alpha) * target
        ccds["allowed_pct"] = round(self._smooth_allocation, 4)
        return ccds

    def execute_live_order(self, order: dict) -> dict:
        """实盘执行控制器 — 必须通过所有安全门。"""
        if self._kill_switch_active:
            return dict(executed=False, reason="kill_switch_active")
        if self._tier == 0:
            return dict(executed=False, reason=f"tier_0: shadow only")
        if self._broker.status != "ready":
            return dict(executed=False, reason=f"broker_status: {self._broker.status}")
        self._broker.submit_order(order.get("symbol", ""), order.get("qty", 0), order.get("price", 0))
        return dict(executed=True, order_id=len(self._broker._orders))

    # ═══════════════════════════════════════════════════
    # v11: SLTS
    # ═══════════════════════════════════════════════════

    def compute_market_divergence(self, shadow: dict, live_sim: dict) -> dict[str, Any]:
        sd = shadow.get("slippage_cost", 0); ld = live_sim.get("slippage_cost", 0)
        sp = shadow.get("pnl_realized", 0); lp = live_sim.get("pnl_realized", 0)
        fill_div = abs(max(live_sim.get("execution_efficiency", 50), 1) - max(shadow.get("execution_efficiency", 50), 1))
        slip_div = abs(ld - sd) / max(abs(sd), 0.01) * 100 if sd != 0 else 0
        pnl_div = abs(lp - sp) / max(abs(sp), 0.01) * 100 if sp != 0 else 0
        return dict(execution_divergence_score=max(0, min(100, 100 - fill_div)),
                    fill_divergence=round(fill_div, 1), slippage_divergence=round(slip_div, 1), pnl_divergence=round(pnl_div, 1))

    def _live_simulation(self, allocation: dict, regime: str, vol: float, liq: float) -> dict[str, Any]:
        bias = self._execution_bias.bias
        ba = {k: v * (1 + random.uniform(-0.02, 0.02)) for k, v in allocation.items()}
        tw = sum(ba.values())
        if tw > 0: ba = {k: v / tw for k, v in ba.items()}
        r = self.execute_portfolio(ba, regime, vol, liq)
        r["slippage_cost"] *= (1 + max(bias, 0)); r["pnl_realized"] *= (1 - abs(bias) * 0.5)
        return r

    def _live_risk_gate(self, divergence: dict, regime: dict) -> dict[str, Any]:
        score = divergence.get("execution_divergence_score", 0)
        pnl_d = divergence.get("pnl_divergence", 100); slip_d = divergence.get("slippage_divergence", 100)
        if score > 85 and pnl_d < 5 and slip_d < 20 and not self._kill_switch_active and regime.get("regime_type", "") != "liquidity_stress":
            return dict(score=round(score, 1), live_allowed=True)
        reasons = []
        if score <= 85: reasons.append(f"execution_stability {score} <= 85")
        if pnl_d >= 5: reasons.append(f"pnl_divergence {pnl_d:.1f}% >= 5%")
        if slip_d >= 20: reasons.append(f"slippage_divergence {slip_d:.1f}% >= 20%")
        if self._kill_switch_active: reasons.append("kill_switch ON")
        if regime.get("regime_type", "") == "liquidity_stress": reasons.append("liquidity_stress")
        return dict(score=round(score, 1), live_allowed=False, blocked_reason="; ".join(reasons))

    def _sync_shadow_to_live(self, shadow: dict, live_sim: dict) -> None:
        fb = (live_sim.get("execution_efficiency", 50) - shadow.get("execution_efficiency", 50)) / 100
        self._execution_bias.update(fb)
        if abs(fb) > 0.15: self._divergence_history.append(100)

    def set_mode(self, mode: str) -> None:
        if mode in ("shadow", "live_shadow", "live"): self._mode = mode
    @property
    def mode(self) -> str: return self._mode

    # ═══════════════════════════════════════════════════
    # v10: EMIL
    # ═══════════════════════════════════════════════════

    def _slippage_model(self, base: float, volatility: float, regime: str) -> float:
        return base * (1 + volatility * 2) * {"trend": 1.0, "range": 1.2, "volatile": 1.5, "liquidity_stress": 2.5}.get(regime, 1.0)

    def _market_impact(self, order_size: float, liquidity_depth: float) -> float:
        if liquidity_depth <= 0: return BASE_SLIPPAGE * 3
        return BASE_SLIPPAGE * ((order_size / liquidity_depth) ** 1.2)

    def _fill_ratio(self, liquidity: float, volatility: float) -> float:
        base = min(1.0, 0.5 + liquidity * 0.5)
        return max(0.3, min(1.0, base * max(0, 1 - volatility * 1.5) + random.uniform(-0.1, 0.1)))

    def execute_portfolio(self, allocation: dict[str, float], regime: str,
                          volatility: float = 0.15, liquidity: float = 1.0) -> dict[str, Any]:
        executed = {}; ts, ti, tep, trp = 0.0, 0.0, 0.0, 0.0; frs, qs = [], []
        for name, weight in allocation.items():
            os_ = weight * 100000; fill = self._fill_ratio(liquidity, volatility)
            frs.append(fill); executed[name] = round(weight * fill, 4)
            slip = self._slippage_model(BASE_SLIPPAGE, volatility, regime)
            sc = slip * os_ * fill; ts += sc
            imp = self._market_impact(os_, liquidity * 1000000); ic = imp * os_ * fill; ti += ic
            epnl = weight * 1000 * random.uniform(-0.02, 0.05)
            rpnl = epnl - sc - ic; tep += epnl; trp += rpnl
            ee = abs(rpnl - epnl) / max(abs(epnl), 0.01) if epnl != 0 else 1.0
            qs.append(max(0, 1 - ee))
            self._emil_trade_log.append(dict(strategy=name, weight=weight, fill=fill, slippage=slip, impact=imp))
        return dict(executed_allocations=executed, slippage_cost=round(ts, 2), market_impact_cost=round(ti, 2),
                    execution_quality_score=round(sum(qs) / len(qs) * 100, 1) if qs else 0,
                    pnl_realized=round(trp, 2), pnl_expected=round(tep, 2),
                    execution_efficiency=round(trp / max(tep, 0.01) * 100, 1) if tep != 0 else 0)

    def _emil_feedback(self, pr: float, pe: float) -> dict[str, Any]:
        if abs(pe) < 0.001: return dict(rmai_corrected=self._rmai_history[-1] if self._rmai_history else 50.0)
        al = max(0, min(1, pr / max(pe, 0.01)))
        cr = round(self._rmai_history[-1] * 0.7 + al * 100 * 0.3, 1) if self._rmai_history else round(al * 100, 1)
        return dict(rmai_corrected=cr)

    # ═══════════════════════════════════════════════════
    # v9: MSAAS
    # ═══════════════════════════════════════════════════

    def build_strategy_profiles(self, rmai: float, signal: float, regime: str) -> list[dict[str, Any]]:
        pref = REGIME_STRATEGY_PREF.get(regime, REGIME_STRATEGY_PREF["range"]); profiles = []
        for name in STRATEGY_NAMES:
            rf = pref.get(name, 1.0)
            sr = rmai * (0.8 + 0.2 * random.random()); ss = signal * (0.8 + 0.2 * random.random())
            risk = random.uniform(0.06, 0.18)
            profiles.append(dict(name=name, rmai=sr, signal=ss, expected_return=sr * ss * rf / 100,
                                 risk=round(risk, 4), sharpe=round((sr * ss * rf / 100) / max(risk, 0.01), 2), regime_fit=rf))
        return profiles

    def compute_strategy_allocation(self, profiles: list[dict[str, Any]], regime: str) -> dict[str, Any]:
        if not profiles: return dict(strategy_allocations={}, total_risk=0, expected_portfolio_return=0, strategy_diversification_score=0, dominant_strategy="?", system_status="infeasible")
        raw = {p["name"]: p["rmai"] * max(p["sharpe"], 0.01) * p["regime_fit"] / max(p["risk"], 0.001) for p in profiles}
        tr = sum(raw.values()); w = {k: v / tr for k, v in raw.items()} if tr > 0 else {k: 1.0 / len(profiles) for k in profiles}
        ms = 0.15 if regime == "liquidity_stress" else 0.40
        if regime == "liquidity_stress":
            for k in w: w[k] *= 0.3
        for k in list(w.keys()):
            if w[k] > ms:
                excess = w[k] - ms; w[k] = ms
                others = [x for x in w if x != k and w[x] < ms]
                if others:
                    ea = excess / len(others)
                    for o in others: w[o] = min(ms, w[o] + ea)
        tw = sum(w.values())
        if tw > 0: w = {k: v / tw for k, v in w.items()}
        tr = math.sqrt(sum(w[p["name"]] ** 2 * p["risk"] ** 2 for p in profiles)) if profiles else 0
        er = sum(w[p["name"]] * p["expected_return"] for p in profiles) if profiles else 0
        hhi = sum(v ** 2 for v in w.values()); n = len(w); div = round(1.0 - (hhi - 1.0 / n) / (1.0 - 1.0 / n), 4) if n > 1 else 0
        return dict(strategy_allocations={k: round(v, 4) for k, v in sorted(w.items(), key=lambda x: -x[1])},
                    total_risk=round(tr, 4), expected_portfolio_return=round(er, 4), strategy_diversification_score=div,
                    dominant_strategy=max(w, key=w.get), system_status="optimal" if max(w.values()) <= ms + 0.01 else "feasible")

    # ─── Legacy modules ───

    def market_regime_detector(self, md: dict) -> dict:
        returns = md.get("returns", [0.1, 0.05, -0.02, 0.08, 0.12]); vol = md.get("volatility", 0.15)
        spread = md.get("spread_proxy", 0.001); dd = abs(md.get("drawdown_pct", 0))
        if not returns: returns = [0.1]
        pr = sum(1 for r in returns if r > 0) / len(returns)
        rev = sum(1 for i in range(1, len(returns)) if (returns[i] >= 0) != (returns[i - 1] >= 0)) / max(len(returns) - 1, 1)
        avg = sum(returns) / len(returns)
        rt, cf = "range", 0.5
        if pr > 0.65 and avg > 0.02 and dd < 0.05: rt, cf = "trend", min(1, 0.5 + pr * 0.5)
        elif rev > 0.4 and vol < 0.2: rt, cf = "range", min(1, 0.5 + rev * 0.5)
        elif vol > 0.25 and rev > 0.3: rt, cf = "volatile", min(1, 0.5 + vol * 1.5)
        if vol > 0.3 and spread > 0.005 and dd > 0.05: rt, cf = "liquidity_stress", min(1, 0.5 + vol * 1.0 + spread * 50)
        return dict(regime_type=rt, confidence=round(cf, 2))

    def compute_dynamic_rmai(self, base: float, regime: str) -> dict:
        m = REGIME_MULTIPLIERS.get(regime, 1.0)
        return dict(dynamic_rmai=round(base * m, 1), multiplier=m)

    def compute_reality_alignment_index(self, lr: float, sr: float, pr: float) -> dict:
        sc = max(0, 1 - abs(sr - lr) / max(abs(lr), 0.01)) if lr != 0 else 1 - min(abs(sr), 5) / 5
        pc = max(0, 1 - abs(pr - lr) / max(abs(lr), 0.01)) if lr != 0 else 1 - min(abs(pr), 5) / 5
        sc = round(min(sc, 1), 2); pc = round(min(pc, 1), 2)
        return dict(score=round(0.3 * sc * 100 + 0.3 * pc * 100 + 0.2 * min(1, sc * 0.9 + 0.1) * 100 + 0.2 * (0.8 if (sr >= 0) == (lr >= 0) else 0.4) * 100, 1),
                    shadow_corr=sc, paper_corr=pc, exec_accuracy=round(min(1, sc * 0.9 + 0.1), 2), signal_match=round(0.8 if (sr >= 0) == (lr >= 0) else 0.4, 2))

    def detect_reality_breakdown(self, lr: float, sr: float, pr: float) -> dict:
        b, bt = False, None
        if abs(sr - lr) / max(abs(lr), 0.01) > 0.25 if lr != 0 else 0: b, bt = True, "execution_failure"
        if (pr >= 0) != (lr >= 0): b, bt = True, "signal_failure"
        return dict(breakdown_detected=b, breakdown_type=bt)

    def stress_test_mode(self, ld: dict, sd: dict, pd: dict) -> dict:
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
        var = sum((x - avg) ** 2 for x in all_s) / len(all_s) if all_s else 0
        tt = len(pert) * nd
        return dict(rmai_volatility=round(math.sqrt(var), 2) if all_s else 0,
                    breakdown_trigger_frequency=round(bc / max(tt, 1), 2),
                    false_go_rate=round(fg / max(tt, 1), 4), false_no_go_rate=round(fn / max(tt, 1), 4))

    def walk_forward_validation(self, ld: dict, sd: dict, pd: dict) -> dict:
        bl, bs, bp = ld.get("live_return", 2), sd.get("shadow_return", 1.8), pd.get("paper_return", 2.5)
        nd, ws = 30, 5; wscores, adrifts, emis = [], [], []
        for st in range(0, nd - ws + 1):
            wr = []
            for d in range(st, st + ws):
                dr = (d / nd) * 0.1
                wr.append(self.compute_reality_alignment_index(bl * (1 + dr * random.uniform(-0.5, 0.5)),
                                                               bs * (1 + dr * random.uniform(-0.5, 0.5)),
                                                               bp * (1 + dr * random.uniform(-0.5, 0.5)))["score"])
            wscores.append(sum(wr) / len(wr)); adrifts.append(max(wr) - min(wr)); emis.append(sum(1 for s in wr if s < 60) / len(wr))
        wavg = sum(wscores) / len(wscores) if wscores else 0
        wvar = sum((s - wavg) ** 2 for s in wscores) / len(wscores) if wscores else 0
        return dict(stability_score=round(max(0, 100 - math.sqrt(wvar) * 5), 1))

    def capital_deployment_readiness_engine(self, rmai: dict, breakdown: dict, regime: str = "range", regime_confidence: float = 0.5) -> dict:
        score = rmai.get("score", 0); hb = breakdown.get("breakdown_detected", False)
        if self._kill_switch_active or regime == "liquidity_stress": return dict(status="NO_GO", confidence=0.0)
        if score > 85 and self._consecutive_breakdown_days == 0 and regime_confidence > 0.6: return dict(status="GO", confidence=round(score / 100, 2))
        if score > 65 and not hb: return dict(status="CONDITIONAL", confidence=round(score / 100, 2))
        return dict(status="NO_GO", confidence=round(score / 100, 2))

    def trigger_kill_switch(self, pnl_drawdown_pct: float) -> None:
        if pnl_drawdown_pct > 3.0:
            self._kill_switch_active = True
            self._kill_switch_until = datetime.now().replace(hour=23, minute=59, second=59) + timedelta(days=1)

    def micro_live_cycle(self, live_return: float) -> dict:
        p = self._micro_live_portfolio; c, pos = p["cash"], p["positions"]
        act = "BUY" if live_return > 1 else ("SELL" if live_return < -1 else "HOLD")
        price = 100.0 + live_return * 0.5
        dm = random.uniform(50, 500); pd_ = random.uniform(-0.001, 0.001) * price; sp = random.uniform(0.0005, 0.003)
        ep = price + pd_ + (price * sp if act == "BUY" else -price * sp if act == "SELL" else 0)
        if act == "BUY" and c >= ep * 10: q = min(int(c / ep), 10); c -= round(q * ep, 2); pos["SIM"] = pos.get("SIM", 0) + q
        elif act == "SELL" and pos.get("SIM", 0) > 0: c += round(pos["SIM"] * ep, 2); del pos["SIM"]
        tv = c + sum(q * price for q in pos.values()); pnl = round(tv - 10000.0, 2)
        if tv > p["peak_value"]: p["peak_value"] = tv
        dd = self._micro_live_drawdown()
        if dd > 3.0: self.trigger_kill_switch(dd)
        p["cash"] = c
        exp = live_return * 100; pa = min(1, max(0, pnl / max(abs(exp), 0.01))) if exp != 0 else 1.0
        cr = round(self._rmai_history[-1] * 0.7 + pa * 100 * 0.3, 1) if self._rmai_history else round(pa * 100, 1)
        return dict(action=act, execution_price=round(ep, 2), delay_ms=round(dm, 1), slippage_pct=round(sp * 100, 3),
                    total_value=round(tv, 2), pnl=pnl, drawdown_pct=round(dd, 2), rmai_corrected=cr, pnl_alignment=round(pa, 2))

    def _micro_live_drawdown(self) -> float:
        p = self._micro_live_portfolio
        cur = p["cash"] + sum(q * 100 for q in p["positions"].values())
        pk = p["peak_value"]
        return 0.0 if pk <= 0 else round(max(0, (pk - cur) / pk * 100), 2)