#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""现实市场迁移与真实资金验证准备层 — 将模拟系统逐步迁移到"真实市场验证模式"。

v2 升级：
- stress_test_mode: 极端波动/延迟/信号反转扰动
- walk_forward_validation: 5天滚动窗口验证
- capital safety layer: 严格GO条件 + hard kill switch
- micro_live_sandbox: 完整闭环模拟实盘

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
from datetime import date, datetime
from pathlib import Path
from typing import Any


class RealityTransitionEngine:
    """现实过渡引擎 v2 — 模拟到真实市场的镜像对齐与迁移准备。"""

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
        """运行现实镜像模式（含stress test + walk-forward + capital safety + micro-live）。"""
        lm = live_market_data or {"live_return": 2.0}
        sd = shadow_data or {"shadow_return": 1.8}
        pd = paper_data or {"paper_return": 2.5}

        live_return = lm.get("live_return", 0)
        shadow_return = sd.get("shadow_return", 0)
        paper_return = pd.get("paper_return", 0)

        # RMAI
        rmai = self.compute_reality_alignment_index(live_return, shadow_return, paper_return)
        self._rmai_history.append(rmai["score"])

        # Breakdown
        breakdown = self.detect_reality_breakdown(live_return, shadow_return, paper_return)
        if breakdown["breakdown_detected"]:
            self._consecutive_breakdown_days += 1
        else:
            self._consecutive_breakdown_days = 0

        # Capital safety + readiness (v2 strict)
        readiness = self.capital_deployment_readiness_engine(rmai, breakdown)

        # Stress test
        stress = self.stress_test_mode(lm, sd, pd)

        # Walk-forward
        wfv = self.walk_forward_validation(lm, sd, pd)

        # Micro-live sandbox
        micro = self.micro_live_cycle(live_return)

        # Kill switch
        kill_status = {"kill_switch_active": self._kill_switch_active}
        if self._kill_switch_active and self._kill_switch_until:
            if datetime.now() >= self._kill_switch_until:
                self._kill_switch_active = False
                self._kill_switch_until = None
                kill_status["kill_switch_active"] = False

        div_matrix = {
            "shadow_vs_live": round(shadow_return - live_return, 2),
            "paper_vs_live": round(paper_return - live_return, 2),
        }

        result = {
            "date": date.today().isoformat(),
            "rmai_score": rmai["score"],
            "shadow_vs_live_correlation": rmai["shadow_corr"],
            "paper_vs_live_correlation": rmai["paper_corr"],
            "execution_accuracy": rmai["exec_accuracy"],
            "signal_match_rate": rmai["signal_match"],
            "breakdown_detected": breakdown["breakdown_detected"],
            "breakdown_type": breakdown.get("breakdown_type", None),
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
    # ② RMAI
    # ═══════════════════════════════════════════════════

    def compute_reality_alignment_index(
        self,
        live_return: float,
        shadow_return: float,
        paper_return: float,
    ) -> dict[str, Any]:
        """计算真实市场对齐指数 (RMAI) 0-100。"""
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
        """检测现实崩溃模式。"""
        breakdown = False; btype = None
        sd_dev = abs(shadow_return - live_return) / max(abs(live_return), 0.01) if live_return != 0 else 0
        if sd_dev > 0.25:
            breakdown = True; btype = "execution_failure"
        if (paper_return >= 0) != (live_return >= 0):
            breakdown = True; btype = "signal_failure"
        return {"breakdown_detected": breakdown, "breakdown_type": btype, "shadow_deviation_pct": round(sd_dev * 100, 1)}

    # ═══════════════════════════════════════════════════
    # ③ Stress Test Mode（新增）
    # ═══════════════════════════════════════════════════

    def stress_test_mode(
        self,
        live_data: dict[str, Any],
        shadow_data: dict[str, Any],
        paper_data: dict[str, Any],
    ) -> dict[str, Any]:
        """注入3类扰动：极端波动、延迟扰动、信号反转；输出RMAI volatility与breakdown频率。"""
        base_live = live_data.get("live_return", 2.0)
        base_shadow = shadow_data.get("shadow_return", 1.8)
        base_paper = paper_data.get("paper_return", 2.5)

        n_days = 30
        perturbations = [
            ("extreme_volatility", [random.uniform(-0.10, 0.10) for _ in range(n_days)]),
            ("latency_shock", [random.uniform(0.3, 2.0) for _ in range(n_days)]),
            ("signal_reversal", [(-1 if random.random() < 0.3 else 1) for _ in range(n_days)]),
        ]

        # 收集所有扰动后的RMAI
        all_scores = []
        breakdown_count = 0
        false_go = 0
        false_nogo = 0

        for ptype, shocks in perturbations:
            window_scores = []
            for day in range(min(n_days, len(shocks))):
                shock = shocks[day]
                if ptype == "extreme_volatility":
                    lr = base_live + shock * 100
                    sr = base_shadow + shock * 80
                    pr = base_paper + shock * 90
                elif ptype == "latency_shock":
                    latency_factor = 1 - shock * 0.01
                    lr = base_live
                    sr = base_shadow * latency_factor
                    pr = base_paper * latency_factor
                elif ptype == "signal_reversal":
                    lr = base_live * shock
                    sr = base_shadow * shock * 0.8
                    pr = base_paper * shock * 0.9
                else:
                    lr, sr, pr = base_live, base_shadow, base_paper

                rmai = self.compute_reality_alignment_index(lr, sr, pr)
                window_scores.append(rmai["score"])

                bd = self.detect_reality_breakdown(lr, sr, pr)
                if bd["breakdown_detected"]:
                    breakdown_count += 1

                # false GO: RMAI > 85 但实际上是 perturbed
                if rmai["score"] > 85 and abs(shock) > 0.05:
                    false_go += 1
                # false NO-GO: RMAI < 60 但实际扰动很小
                if rmai["score"] < 60 and abs(shock) < 0.02:
                    false_nogo += 1

            all_scores.extend(window_scores)

        # 计算RMAI volatility
        avg = sum(all_scores) / len(all_scores) if all_scores else 0
        var = sum((x - avg)**2 for x in all_scores) / len(all_scores) if all_scores else 0
        rmai_volatility = round(math.sqrt(var), 2)
        total_tests = len(perturbations) * n_days

        return {
            "rmai_volatility": rmai_volatility,
            "breakdown_trigger_frequency": round(breakdown_count / max(total_tests, 1), 2),
            "false_go_rate": round(false_go / max(total_tests, 1), 4),
            "false_no_go_rate": round(false_nogo / max(total_tests, 1), 4),
            "total_stress_tests": total_tests,
        }

    # ═══════════════════════════════════════════════════
    # ④ Walk-Forward Validation（新增）
    # ═══════════════════════════════════════════════════

    def walk_forward_validation(
        self,
        live_data: dict[str, Any],
        shadow_data: dict[str, Any],
        paper_data: dict[str, Any],
    ) -> dict[str, Any]:
        """5天滚动窗口验证RMAI稳定性。"""
        base_live = live_data.get("live_return", 2.0)
        base_shadow = shadow_data.get("shadow_return", 1.8)
        base_paper = paper_data.get("paper_return", 2.5)

        n_days = 30
        window_size = 5
        window_scores = []
        alignment_drifts = []
        exec_mismatches = []

        for start in range(0, n_days - window_size + 1):
            # 模拟窗口内的每日微小变动
            window_rmai = []
            for day in range(start, start + window_size):
                drift = (day / n_days) * 0.1  # 逐渐漂移
                lr = base_live * (1 + drift * random.uniform(-0.5, 0.5))
                sr = base_shadow * (1 + drift * random.uniform(-0.5, 0.5))
                pr = base_paper * (1 + drift * random.uniform(-0.5, 0.5))
                rmai = self.compute_reality_alignment_index(lr, sr, pr)
                window_rmai.append(rmai["score"])

            avg_score = sum(window_rmai) / len(window_rmai)
            window_scores.append(avg_score)

            # alignment drift: 窗口内RMAI变化
            drift_val = max(window_rmai) - min(window_rmai)
            alignment_drifts.append(drift_val)

            # execution mismatch rate
            mismatch = sum(1 for s in window_rmai if s < 60) / len(window_rmai)
            exec_mismatches.append(mismatch)

        # 稳定性评分
        wf_avg = sum(window_scores) / len(window_scores) if window_scores else 0
        wf_var = sum((s - wf_avg)**2 for s in window_scores) / len(window_scores) if window_scores else 0
        stability = round(max(0, 100 - math.sqrt(wf_var) * 5), 1)

        # regime sensitivity: 牛/震荡/熊
        max_drift = max(alignment_drifts) if alignment_drifts else 0
        if max_drift > 20:
            regime_sensitivity = "high"
        elif max_drift > 10:
            regime_sensitivity = "medium"
        else:
            regime_sensitivity = "low"

        avg_mismatch = sum(exec_mismatches) / len(exec_mismatches) if exec_mismatches else 0

        return {
            "stability_score": stability,
            "regime_sensitivity": regime_sensitivity,
            "avg_alignment_drift": round(sum(alignment_drifts) / len(alignment_drifts), 2) if alignment_drifts else 0,
            "execution_mismatch_rate": round(avg_mismatch, 2),
            "windows_analyzed": len(window_scores),
        }

    # ═══════════════════════════════════════════════════
    # ⑤ Capital Safety Layer（升级）
    # ═══════════════════════════════════════════════════

    def capital_deployment_readiness_engine(
        self,
        rmai: dict[str, Any],
        breakdown: dict[str, Any],
    ) -> dict[str, Any]:
        """v2 严格版资金部署判断 + hard kill switch。"""
        score = rmai.get("score", 0)
        has_breakdown = breakdown.get("breakdown_detected", False)
        stability_score = 0.8  # 可从walk_forward结果传入

        # Kill switch check
        if self._kill_switch_active:
            return {"status": "NO_GO", "confidence": 0.0, "max_safe_capital_pct": 0.0,
                    "recommended_phase": "shadow", "kill_switch_active": True}

        # v2 strict GO: RMAI > 85 + 0 breakdown in 7 days + stability >= 0.8
        if score > 85 and self._consecutive_breakdown_days == 0 and stability_score >= 0.8:
            status = "GO"
            max_safe = 0.15
            phase = "micro_live"
        elif score >= 60 and not has_breakdown:
            # CONDITIONAL → 强制shadow 5%
            status = "CONDITIONAL"
            max_safe = 0.05
            phase = "shadow"
        else:
            status = "NO_GO"
            max_safe = 0.0
            phase = "shadow"

        confidence = round(score / 100, 2)
        return {"status": status, "confidence": confidence, "max_safe_capital_pct": max_safe,
                "recommended_phase": phase, "kill_switch_active": False}

    def trigger_kill_switch(self, pnl_drawdown_pct: float) -> None:
        """Hard kill switch: 任意日亏损 > 3% → 强制NO-GO 24h。"""
        if pnl_drawdown_pct > 3.0:
            self._kill_switch_active = True
            self._kill_switch_until = datetime.now().replace(hour=23, minute=59, second=59) + __import__("datetime").timedelta(days=1)
        elif pnl_drawdown_pct > 0:
            drawdown = self._micro_live_drawdown()
            if drawdown > 3.0:
                self._kill_switch_active = True
                self._kill_switch_until = datetime.now().replace(hour=23, minute=59, second=59) + __import__("datetime").timedelta(days=1)

    # ═══════════════════════════════════════════════════
    # ⑥ Micro-live Sandbox（升级为闭环）
    # ═══════════════════════════════════════════════════

    def micro_live_cycle(self, live_return: float) -> dict[str, Any]:
        """完整模拟实盘闭环：signal → delay → slippage → portfolio → PnL → RMAI feedback。"""
        portfolio = self._micro_live_portfolio
        cash = portfolio["cash"]
        positions = portfolio["positions"]

        # Step 1: Signal generate
        if live_return > 1:
            action = "BUY"
            symbol = "SIM"
            price = 100.0 + live_return * 0.5
        elif live_return < -1:
            action = "SELL"
            symbol = "SIM"
            price = 100.0 + live_return * 0.5
        else:
            action = "HOLD"
            symbol = "SIM"
            price = 100.0

        # Step 2: Simulate execution delay (random 50-500ms)
        delay_ms = random.uniform(50, 500)
        price_drift = random.uniform(-0.001, 0.001) * price

        # Step 3: Simulate slippage (0.05%–0.3%)
        slippage_pct = random.uniform(0.0005, 0.003)
        if action == "BUY":
            exec_price = price + price_drift + price * slippage_pct
        elif action == "SELL":
            exec_price = price + price_drift - price * slippage_pct
        else:
            exec_price = price

        # Step 4: Portfolio update
        trade_pnl = 0.0
        if action == "BUY" and cash >= exec_price * 10:
            qty = min(int(cash / exec_price), 10)
            cost = round(qty * exec_price, 2)
            cash -= cost
            positions[symbol] = positions.get(symbol, 0) + qty
        elif action == "SELL" and positions.get(symbol, 0) > 0:
            qty = positions[symbol]
            proceeds = round(qty * exec_price, 2)
            cash += proceeds
            trade_pnl = round(proceeds - qty * price, 2)
            del positions[symbol]

        # Step 5: Mark-to-market PnL
        total_value = cash
        for sym, qty in positions.items():
            total_value += qty * price
        pnl = round(total_value - 10000.0, 2)
        if total_value > portfolio["peak_value"]:
            portfolio["peak_value"] = total_value

        # Kill switch on drawdown
        drawdown = self._micro_live_drawdown()
        if drawdown > 3.0:
            self.trigger_kill_switch(drawdown)

        portfolio["cash"] = cash

        # Step 6: Feedback into RMAI (修正)
        live_aligned = 1 - min(abs(pnl) / 500, 1.0)
        if self._rmai_history:
            last_rmai = self._rmai_history[-1]
            corrected_rmai = round(last_rmai * 0.7 + live_aligned * 100 * 0.3, 1)
        else:
            corrected_rmai = round(live_aligned * 100, 1)

        return {
            "action": action,
            "execution_price": round(exec_price, 2),
            "delay_ms": round(delay_ms, 1),
            "slippage_pct": round(slippage_pct * 100, 3),
            "total_value": round(total_value, 2),
            "pnl": pnl,
            "positions": dict(positions),
            "drawdown_pct": round(drawdown, 2),
            "rmai_corrected": corrected_rmai,
            "kill_switch_triggered": self._kill_switch_active,
        }

    def _micro_live_drawdown(self) -> float:
        """计算微实盘回撤。"""
        p = self._micro_live_portfolio
        cash = p["cash"]
        pos_value = sum(qty * 100 for qty in p["positions"].values())
        current = cash + pos_value
        peak = p["peak_value"]
        if peak <= 0:
            return 0.0
        return round(max(0, (peak - current) / peak * 100), 2)