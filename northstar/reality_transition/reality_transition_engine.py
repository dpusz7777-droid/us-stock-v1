#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""现实市场迁移与真实资金验证准备层 — v3.

v3 升级：MarketRegimeDetector + 动态权重RMAI + 市场状态感知资金分配。

仍不执行真实交易，只做真实数据驱动的行为对照与资金安全预演。

用法：
    from northstar.reality_transition.reality_transition_engine import RealityTransitionEngine
    rte = RealityTransitionEngine()
    report = rte.run_reality_mirror_cycle(live_market_data, shadow_data, paper_data)
"""

from __future__ import annotations

import json
import math
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


class RealityTransitionEngine:
    """现实过渡引擎 v3 — 市场状态感知 + 动态权重RMAI系统。"""

    def __init__(self) -> None:
        self._consecutive_breakdown_days: int = 0
        self._kill_switch_active: bool = False
        self._kill_switch_until: datetime | None = None
        self._micro_live_portfolio: dict[str, Any] = {
            "cash": 10000.0, "positions": {}, "peak_value": 10000.0
        }
        self._rmai_history: list[float] = []

    # ═══════════════════════════════════════════════════
    # ① 主镜像周期
    # ═══════════════════════════════════════════════════

    def run_reality_mirror_cycle(
        self,
        live_market_data: dict[str, Any] | None = None,
        shadow_data: dict[str, Any] | None = None,
        paper_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """运行现实镜像模式（v3：含市场状态检测 + 动态RMAI）。"""
        lm = live_market_data or {"live_return": 2.0, "volatility": 0.15, "volume": 1.0, "spread_proxy": 0.001, "returns": [0.1, 0.2, 0.15]}
        sd = shadow_data or {"shadow_return": 1.8}
        pd = paper_data or {"paper_return": 2.5}

        live_return = lm.get("live_return", 0)
        shadow_return = sd.get("shadow_return", 0)
        paper_return = pd.get("paper_return", 0)

        # Regime detection
        regime = self.market_regime_detector(lm)
        result_regime = regime["regime_type"]

        # Base RMAI
        base_rmai = self.compute_reality_alignment_index(live_return, shadow_return, paper_return)
        self._rmai_history.append(base_rmai["score"])

        # Dynamic RMAI (regime-weighted)
        dynamic = self.compute_dynamic_rmai(base_rmai["score"], result_regime)

        # Breakdown
        breakdown = self.detect_reality_breakdown(live_return, shadow_return, paper_return)
        if breakdown["breakdown_detected"]:
            self._consecutive_breakdown_days += 1
        else:
            self._consecutive_breakdown_days = 0

        # Capital readiness (v3: regime-aware)
        readiness = self.capital_deployment_readiness_engine(
            {"score": dynamic["dynamic_rmai"]}, breakdown,
            regime=result_regime, regime_confidence=regime["confidence"]
        )

        # Stress test
        stress = self.stress_test_mode(lm, sd, pd)

        # Walk-forward
        wfv = self.walk_forward_validation(lm, sd, pd)

        # Micro-live sandbox (v3: with RMAI feedback)
        micro = self.micro_live_cycle(live_return)

        # Kill switch
        kill_status = {"kill_switch_active": self._kill_switch_active}
        if self._kill_switch_active and self._kill_switch_until:
            if datetime.now() >= self._kill_switch_until:
                self._kill_switch_active = False; self._kill_switch_until = None
                kill_status["kill_switch_active"] = False

        div_matrix = {
            "shadow_vs_live": round(shadow_return - live_return, 2),
            "paper_vs_live": round(paper_return - live_return, 2),
        }

        result = {
            "date": date.today().isoformat(),
            "rmai_score": base_rmai["score"],
            "dynamic_rmai": dynamic["dynamic_rmai"],
            "rmai_multiplier": dynamic["multiplier"],
            "current_regime": result_regime,
            "regime_confidence": regime["confidence"],
            "regime_switch_probability": regime["regime_switch_probability"],
            "regime_adjusted_allocation_signal": dynamic["allocation_signal"],
            "shadow_vs_live_correlation": base_rmai["shadow_corr"],
            "paper_vs_live_correlation": base_rmai["paper_corr"],
            "execution_accuracy": base_rmai["exec_accuracy"],
            "signal_match_rate": base_rmai["signal_match"],
            "breakdown_detected": breakdown["breakdown_detected"],
            "breakdown_type": breakdown.get("breakdown_type"),
            "consecutive_breakdown_days": self._consecutive_breakdown_days,
            "capital_readiness": readiness,
            "divergence_matrix": div_matrix,
            "stress_test": stress,
            "walk_forward": wfv,
            "micro_live_sandbox": micro,
            "kill_switch": kill_status,
        }

        today = date.today().isoformat().replace("-", "")
        reports_dir = Path(__file__).parent.parent.parent / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_file = reports_dir / f"reality_transition_{today}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        return result

    # ═══════════════════════════════════════════════════
    # ② 市场状态检测器（v3新增）
    # ═══════════════════════════════════════════════════

    def market_regime_detector(self, market_data: dict[str, Any]) -> dict[str, Any]:
        """检测市场状态: trend / range / volatile / liquidity_stress。"""
        returns = market_data.get("returns", [0.1, 0.05, -0.02, 0.08, 0.12])
        volatility = market_data.get("volatility", 0.15)
        spread_proxy = market_data.get("spread_proxy", 0.001)
        drawdown = abs(market_data.get("drawdown_pct", 0))

        if not returns:
            returns = [0.1]

        # 趋势性指标: 正负比率
        pos = sum(1 for r in returns if r > 0)
        neg = sum(1 for r in returns if r < 0)
        total = len(returns)
        pos_ratio = pos / total if total > 0 else 0.5
        neg_ratio = neg / total if total > 0 else 0.5

        # 均值回归性: 符号变化频率
        sign_changes = sum(1 for i in range(1, len(returns)) if (returns[i] >= 0) != (returns[i - 1] >= 0))
        reversal_rate = sign_changes / max(len(returns) - 1, 1)

        # 平均收益
        avg_ret = sum(returns) / len(returns) if returns else 0

        regime_type = "range"
        confidence = 0.5
        switch_prob = 0.1

        # trend: 单边收益持续 + 回撤浅
        if pos_ratio > 0.65 and avg_ret > 0.02 and drawdown < 0.05:
            regime_type = "trend"
            confidence = min(1.0, 0.5 + pos_ratio * 0.5)
            switch_prob = max(0.05, 0.3 - pos_ratio * 0.3)

        # range: 均值回归明显 + 低趋势性
        elif reversal_rate > 0.4 and volatility < 0.2:
            regime_type = "range"
            confidence = min(1.0, 0.5 + reversal_rate * 0.5)
            switch_prob = 0.15

        # volatile: 高波动 + 方向频繁反转
        elif volatility > 0.25 and reversal_rate > 0.3:
            regime_type = "volatile"
            confidence = min(1.0, 0.5 + volatility * 1.5)
            switch_prob = 0.3

        # liquidity_stress: 波动+滑点+回撤同步上升
        if volatility > 0.3 and spread_proxy > 0.005 and drawdown > 0.05:
            regime_type = "liquidity_stress"
            confidence = min(1.0, 0.5 + volatility * 1.0 + spread_proxy * 50)
            switch_prob = 0.4

        return {
            "regime_type": regime_type,
            "confidence": round(confidence, 2),
            "regime_switch_probability": round(switch_prob, 2),
        }

    # ═══════════════════════════════════════════════════
    # ③ 动态RMAI（v3新增）
    # ═══════════════════════════════════════════════════

    def compute_dynamic_rmai(self, base_rmai: float, regime: str) -> dict[str, Any]:
        """基于市场状态动态调整RMAI。"""
        multipliers = {
            "trend": 0.95,
            "range": 1.05,
            "volatile": 0.85,
            "liquidity_stress": 0.60,
        }
        mult = multipliers.get(regime, 1.0)
        dynamic = round(base_rmai * mult, 1)
        allocation_signal = round(min(dynamic, 100.0), 1)
        return {"dynamic_rmai": dynamic, "multiplier": mult, "allocation_signal": allocation_signal}

    # ═══════════════════════════════════════════════════
    # ④ 基础RMAI
    # ═══════════════════════════════════════════════════

    def compute_reality_alignment_index(self, live_return: float, shadow_return: float, paper_return: float) -> dict[str, Any]:
        if live_return != 0:
            shadow_corr = max(0, 1 - abs(shadow_return - live_return) / max(abs(live_return), 0.01))
        else:
            shadow_corr = 1 - min(abs(shadow_return), 5) / 5
        if live_return != 0:
            paper_corr = max(0, 1 - abs(paper_return - live_return) / max(abs(live_return), 0.01))
        else:
            paper_corr = 1 - min(abs(paper_return), 5) / 5
        shadow_corr = round(min(shadow_corr, 1.0), 2)
        paper_corr = round(min(paper_corr, 1.0), 2)
        exec_accuracy = round(min(1.0, shadow_corr * 0.9 + 0.1), 2)
        signal_match = round(0.8 if (shadow_return >= 0) == (live_return >= 0) else 0.4, 2)
        score = round(
            0.3 * shadow_corr * 100 + 0.3 * paper_corr * 100 +
            0.2 * exec_accuracy * 100 + 0.2 * signal_match * 100, 1,
        )
        return {"score": score, "shadow_corr": shadow_corr, "paper_corr": paper_corr,
                "exec_accuracy": exec_accuracy, "signal_match": signal_match}

    def detect_reality_breakdown(self, live_return: float, shadow_return: float, paper_return: float) -> dict[str, Any]:
        breakdown = False; btype = None
        sd_dev = abs(shadow_return - live_return) / max(abs(live_return), 0.01) if live_return != 0 else 0
        if sd_dev > 0.25:
            breakdown = True; btype = "execution_failure"
        if (paper_return >= 0) != (live_return >= 0):
            breakdown = True; btype = "signal_failure"
        return {"breakdown_detected": breakdown, "breakdown_type": btype, "shadow_deviation_pct": round(sd_dev * 100, 1)}

    # ═══════════════════════════════════════════════════
    # ⑤ Stress Test Mode
    # ═══════════════════════════════════════════════════

    def stress_test_mode(self, live_data: dict[str, Any], shadow_data: dict[str, Any], paper_data: dict[str, Any]) -> dict[str, Any]:
        base_live = live_data.get("live_return", 2.0)
        base_shadow = shadow_data.get("shadow_return", 1.8)
        base_paper = paper_data.get("paper_return", 2.5)
        n_days = 30
        perturbations = [
            ("extreme_volatility", [random.uniform(-0.10, 0.10) for _ in range(n_days)]),
            ("latency_shock", [random.uniform(0.3, 2.0) for _ in range(n_days)]),
            ("signal_reversal", [(-1 if random.random() < 0.3 else 1) for _ in range(n_days)]),
        ]
        all_scores, breakdown_count, false_go, false_nogo = [], 0, 0, 0
        for ptype, shocks in perturbations:
            for day in range(min(n_days, len(shocks))):
                shock = shocks[day]
                if ptype == "extreme_volatility":
                    lr, sr, pr = base_live + shock * 100, base_shadow + shock * 80, base_paper + shock * 90
                elif ptype == "latency_shock":
                    lr, sr, pr = base_live, base_shadow * (1 - shock * 0.01), base_paper * (1 - shock * 0.01)
                elif ptype == "signal_reversal":
                    lr, sr, pr = base_live * shock, base_shadow * shock * 0.8, base_paper * shock * 0.9
                else:
                    lr, sr, pr = base_live, base_shadow, base_paper
                rmai = self.compute_reality_alignment_index(lr, sr, pr)
                all_scores.append(rmai["score"])
                bd = self.detect_reality_breakdown(lr, sr, pr)
                if bd["breakdown_detected"]: breakdown_count += 1
                if rmai["score"] > 85 and abs(shock) > 0.05: false_go += 1
                if rmai["score"] < 60 and abs(shock) < 0.02: false_nogo += 1
        avg = sum(all_scores) / len(all_scores) if all_scores else 0
        var = sum((x - avg)**2 for x in all_scores) / len(all_scores) if all_scores else 0
        total = len(perturbations) * n_days
        return {"rmai_volatility": round(math.sqrt(var), 2) if all_scores else 0,
                "breakdown_trigger_frequency": round(breakdown_count / max(total, 1), 2),
                "false_go_rate": round(false_go / max(total, 1), 4),
                "false_no_go_rate": round(false_nogo / max(total, 1), 4),
                "total_stress_tests": total}

    # ═══════════════════════════════════════════════════
    # ⑥ Walk-Forward Validation
    # ═══════════════════════════════════════════════════

    def walk_forward_validation(self, live_data: dict[str, Any], shadow_data: dict[str, Any], paper_data: dict[str, Any]) -> dict[str, Any]:
        base_live = live_data.get("live_return", 2.0)
        base_shadow = shadow_data.get("shadow_return", 1.8)
        base_paper = paper_data.get("paper_return", 2.5)
        n_days, window_size = 30, 5
        window_scores, alignment_drifts, exec_mismatches = [], [], []
        for start in range(0, n_days - window_size + 1):
            window_rmai = []
            for day in range(start, start + window_size):
                drift = (day / n_days) * 0.1
                lr = base_live * (1 + drift * random.uniform(-0.5, 0.5))
                sr = base_shadow * (1 + drift * random.uniform(-0.5, 0.5))
                pr = base_paper * (1 + drift * random.uniform(-0.5, 0.5))
                window_rmai.append(self.compute_reality_alignment_index(lr, sr, pr)["score"])
            window_scores.append(sum(window_rmai) / len(window_rmai))
            alignment_drifts.append(max(window_rmai) - min(window_rmai))
            exec_mismatches.append(sum(1 for s in window_rmai if s < 60) / len(window_rmai))
        wf_avg = sum(window_scores) / len(window_scores) if window_scores else 0
        wf_var = sum((s - wf_avg)**2 for s in window_scores) / len(window_scores) if window_scores else 0
        max_drift = max(alignment_drifts) if alignment_drifts else 0
        return {"stability_score": round(max(0, 100 - math.sqrt(wf_var) * 5), 1),
                "regime_sensitivity": "high" if max_drift > 20 else ("medium" if max_drift > 10 else "low"),
                "avg_alignment_drift": round(sum(alignment_drifts) / len(alignment_drifts), 2) if alignment_drifts else 0,
                "execution_mismatch_rate": round(sum(exec_mismatches) / len(exec_mismatches), 2) if exec_mismatches else 0,
                "windows_analyzed": len(window_scores)}

    # ═══════════════════════════════════════════════════
    # ⑦ Capital Safety Layer（v3: regime-aware）
    # ═══════════════════════════════════════════════════

    def capital_deployment_readiness_engine(
        self,
        rmai: dict[str, Any],
        breakdown: dict[str, Any],
        regime: str = "range",
        regime_confidence: float = 0.5,
    ) -> dict[str, Any]:
        """v3 regime-aware 资金部署判断。"""
        score = rmai.get("score", 0)
        has_breakdown = breakdown.get("breakdown_detected", False)
        stability_score = 0.8

        if self._kill_switch_active:
            return {"status": "NO_GO", "confidence": 0.0, "max_safe_capital_pct": 0.0,
                    "recommended_phase": "shadow", "kill_switch_active": True}

        # liquidity_stress → 直接NO-GO
        if regime == "liquidity_stress":
            return {"status": "NO_GO", "confidence": 0.0, "max_safe_capital_pct": 0.0,
                    "recommended_phase": "shadow", "kill_switch_active": False,
                    "reason": "liquidity_stress regime blocks deployment"}

        # v3 strict GO
        if (score > 85 and self._consecutive_breakdown_days == 0 and stability_score >= 0.8
                and regime_confidence > 0.6 and regime != "liquidity_stress"):
            status, max_safe, phase = "GO", 0.15, "micro_live"
        elif score > 65 and not has_breakdown:
            status, max_safe, phase = "CONDITIONAL", 0.05, "shadow"
        else:
            status, max_safe, phase = "NO_GO", 0.0, "shadow"

        confidence = round(score / 100, 2)
        return {"status": status, "confidence": confidence, "max_safe_capital_pct": max_safe,
                "recommended_phase": phase, "kill_switch_active": False}

    def trigger_kill_switch(self, pnl_drawdown_pct: float) -> None:
        if pnl_drawdown_pct > 3.0:
            self._kill_switch_active = True
            self._kill_switch_until = datetime.now().replace(hour=23, minute=59, second=59) + timedelta(days=1)

    # ═══════════════════════════════════════════════════
    # ⑧ Micro-live Sandbox（v3: RMAI feedback）
    # ═══════════════════════════════════════════════════

    def micro_live_cycle(self, live_return: float) -> dict[str, Any]:
        portfolio = self._micro_live_portfolio
        cash, positions = portfolio["cash"], portfolio["positions"]

        if live_return > 1: action, symbol, price = "BUY", "SIM", 100.0 + live_return * 0.5
        elif live_return < -1: action, symbol, price = "SELL", "SIM", 100.0 + live_return * 0.5
        else: action, symbol, price = "HOLD", "SIM", 100.0

        delay_ms = random.uniform(50, 500)
        price_drift = random.uniform(-0.001, 0.001) * price
        slippage_pct = random.uniform(0.0005, 0.003)

        if action == "BUY":
            exec_price = price + price_drift + price * slippage_pct
        elif action == "SELL":
            exec_price = price + price_drift - price * slippage_pct
        else:
            exec_price = price

        if action == "BUY" and cash >= exec_price * 10:
            qty = min(int(cash / exec_price), 10)
            cash -= round(qty * exec_price, 2)
            positions[symbol] = positions.get(symbol, 0) + qty
        elif action == "SELL" and positions.get(symbol, 0) > 0:
            qty = positions[symbol]
            cash += round(qty * exec_price, 2)
            del positions[symbol]

        total_value = cash + sum(qty * price for qty in positions.values())
        pnl = round(total_value - 10000.0, 2)
        if total_value > portfolio["peak_value"]:
            portfolio["peak_value"] = total_value
        drawdown = self._micro_live_drawdown()
        if drawdown > 3.0:
            self.trigger_kill_switch(drawdown)
        portfolio["cash"] = cash

        # RMAI feedback with pnl_alignment (v3)
        expected_pnl = live_return * 100
        pnl_alignment = min(1.0, max(0, pnl / max(abs(expected_pnl), 0.01))) if expected_pnl != 0 else 1.0
        if self._rmai_history:
            last_rmai = self._rmai_history[-1]
            corrected_rmai = round(last_rmai * 0.7 + pnl_alignment * 100 * 0.3, 1)
        else:
            corrected_rmai = round(pnl_alignment * 100, 1)

        return {"action": action, "execution_price": round(exec_price, 2), "delay_ms": round(delay_ms, 1),
                "slippage_pct": round(slippage_pct * 100, 3), "total_value": round(total_value, 2),
                "pnl": pnl, "positions": dict(positions), "drawdown_pct": round(drawdown, 2),
                "rmai_corrected": corrected_rmai, "pnl_alignment": round(pnl_alignment, 2),
                "kill_switch_triggered": self._kill_switch_active}

    def _micro_live_drawdown(self) -> float:
        p = self._micro_live_portfolio
        pos_value = sum(qty * 100 for qty in p["positions"].values())
        current = p["cash"] + pos_value
        peak = p["peak_value"]
        if peak <= 0: return 0.0
        return round(max(0, (peak - current) / peak * 100), 2)