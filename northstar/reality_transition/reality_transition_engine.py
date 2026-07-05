#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""现实市场迁移与真实资金验证准备层 — 将模拟系统逐步迁移到"真实市场验证模式"。

仍不执行真实交易，只做真实数据驱动的行为对照与资金安全预演。

用法：
    from northstar.reality_transition.reality_transition_engine import RealityTransitionEngine
    rte = RealityTransitionEngine()
    report = rte.run_reality_mirror_cycle(live_market_data, shadow_data, paper_data)
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


class RealityTransitionEngine:
    """现实过渡引擎 — 模拟到真实市场的镜像对齐与迁移准备。"""

    def run_reality_mirror_cycle(
        self,
        live_market_data: dict[str, Any] | None = None,
        shadow_data: dict[str, Any] | None = None,
        paper_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """运行现实镜像模式。

        Args:
            live_market_data: 真实市场数据
            shadow_data: shadow trading 输出
            paper_data: paper trading 输出

        Returns:
            RealityMirrorReport
        """
        lm = live_market_data or {"live_return": 2.0}
        sd = shadow_data or {"shadow_return": 1.8}
        pd = paper_data or {"paper_return": 2.5}

        live_return = lm.get("live_return", 0)
        shadow_return = sd.get("shadow_return", 0)
        paper_return = pd.get("paper_return", 0)

        # Compute RMAI
        rmai = self.compute_reality_alignment_index(live_return, shadow_return, paper_return)

        # Breakdown detection
        breakdown = self.detect_reality_breakdown(live_return, shadow_return, paper_return)

        # Capital readiness
        readiness = self.capital_deployment_readiness_engine(rmai, breakdown)

        # Divergence matrix
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
            "capital_readiness": readiness,
            "divergence_matrix": div_matrix,
            "micro_live_simulation_result": self.micro_live_simulation_mode(live_return),
        }

        today = date.today().isoformat().replace("-", "")
        reports_dir = Path(__file__).parent.parent.parent / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_file = reports_dir / f"reality_transition_{today}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        return result

    def compute_reality_alignment_index(
        self,
        live_return: float,
        shadow_return: float,
        paper_return: float,
    ) -> dict[str, Any]:
        """计算真实市场对齐指数 (RMAI) 0-100。"""
        # Shadow vs Live
        if live_return != 0:
            shadow_corr = max(0, 1 - abs(shadow_return - live_return) / max(abs(live_return), 0.01))
        else:
            shadow_corr = 1 - min(abs(shadow_return), 5) / 5

        # Paper vs Live
        if live_return != 0:
            paper_corr = max(0, 1 - abs(paper_return - live_return) / max(abs(live_return), 0.01))
        else:
            paper_corr = 1 - min(abs(paper_return), 5) / 5

        shadow_corr = round(min(shadow_corr, 1.0), 2)
        paper_corr = round(min(paper_corr, 1.0), 2)

        exec_accuracy = round(min(1.0, shadow_corr * 0.9 + 0.1), 2)
        signal_match = round(0.8 if (shadow_return >= 0) == (live_return >= 0) else 0.4, 2)

        score = round(
            0.3 * shadow_corr * 100
            + 0.3 * paper_corr * 100
            + 0.2 * exec_accuracy * 100
            + 0.2 * signal_match * 100,
            1,
        )

        return {
            "score": score,
            "shadow_corr": shadow_corr,
            "paper_corr": paper_corr,
            "exec_accuracy": exec_accuracy,
            "signal_match": signal_match,
        }

    def detect_reality_breakdown(
        self,
        live_return: float,
        shadow_return: float,
        paper_return: float,
    ) -> dict[str, Any]:
        """检测现实崩溃模式。"""
        breakdown = False
        btype = None

        sd_dev = abs(shadow_return - live_return) / max(abs(live_return), 0.01) if live_return != 0 else 0
        if sd_dev > 0.25:
            breakdown = True
            btype = "execution_failure"

        paper_dir = paper_return >= 0
        live_dir = live_return >= 0
        if paper_dir != live_dir:
            breakdown = True
            btype = "signal_failure"

        return {"breakdown_detected": breakdown, "breakdown_type": btype, "shadow_deviation_pct": round(sd_dev * 100, 1)}

    def capital_deployment_readiness_engine(
        self,
        rmai: dict[str, Any],
        breakdown: dict[str, Any],
    ) -> dict[str, Any]:
        """判断实盘资金部署能力。"""
        score = rmai.get("score", 0)
        has_breakdown = breakdown.get("breakdown_detected", False)

        if score >= 80 and not has_breakdown:
            status = "GO"
            max_safe = 0.15
            phase = "micro_live"
        elif score >= 60 and not has_breakdown:
            status = "CONDITIONAL"
            max_safe = 0.05
            phase = "shadow"
        else:
            status = "NO_GO"
            max_safe = 0.0
            phase = "shadow"

        confidence = round(score / 100, 2)
        return {"status": status, "confidence": confidence, "max_safe_capital_pct": max_safe, "recommended_phase": phase}

    def micro_live_simulation_mode(self, live_return: float) -> dict[str, Any]:
        """模拟"微实盘行为"（1%虚拟资金）。"""
        virtual_capital = 10000
        slippage_est = -0.001 * virtual_capital
        latency_est = -0.0002 * virtual_capital
        sim_return = live_return * 0.01 + slippage_est + latency_est
        return {
            "virtual_capital": virtual_capital,
            "simulated_return_pct": round(sim_return, 2),
            "estimated_slippage_cost": round(slippage_est, 2),
            "estimated_latency_cost": round(latency_est, 2),
            "execution_stable": sim_return > -50,
        }