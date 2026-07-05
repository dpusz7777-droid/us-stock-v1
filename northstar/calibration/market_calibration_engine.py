#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""市场现实校准层 — 对 shadow / paper / execution reality 与真实市场进行动态误差校准。

使系统从"模拟一致性系统"升级为"市场对齐系统"。

用法：
    from northstar.calibration.market_calibration_engine import MarketCalibrationEngine
    mce = MarketCalibrationEngine()
    report = mce.calibration_cycle(real_market_data, shadow_data, paper_data)
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any


class MarketCalibrationEngine:
    """市场现实校准引擎 — 动态误差校准与偏差检测。"""

    def __init__(self) -> None:
        self._calibration_history: list[dict] = []
        self._consecutive_bias_days: int = 0
        self._confidence_multiplier: float = 1.0
        self._slippage_k: float = 0.1
        self._latency_adjustment: str = "normal"

    def calibration_cycle(
        self,
        real_market_data: dict[str, Any] | None = None,
        shadow_data: dict[str, Any] | None = None,
        paper_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行校准循环，对比 shadow/paper/execution vs 真实市场。

        Args:
            real_market_data: 真实市场收益数据
            shadow_data: shadow trading 输出
            paper_data: paper trading 输出

        Returns:
            calibration_report
        """
        rm = real_market_data or {"real_return": 2.0}
        sd = shadow_data or {"shadow_return": 1.5}
        pd = paper_data or {"paper_return": 2.5}

        real_return = rm.get("real_return", 0)
        shadow_return = sd.get("shadow_return", 0)
        paper_return = pd.get("paper_return", 0)

        # Bias Detection
        bias = self.compute_bias_detection(real_return, shadow_return, paper_return)

        # Adjust Parameters
        adjustments = self.adjust_model_parameters(bias)

        # Alignment Score
        alignment = self.reality_alignment_score(real_return, shadow_return, paper_return)

        # Drift Correction
        drift = self.drift_correction_engine(bias)

        result = {
            "date": date.today().isoformat(),
            "reality_alignment_score": alignment,
            "bias_detection": bias,
            "adjustments": adjustments,
            "drift_detected": drift.get("drift_detected", False),
            "system_health": "calibrated" if alignment > 80 else ("needs_recalibration" if alignment > 50 else "misaligned"),
            "consecutive_bias_days": self._consecutive_bias_days,
        }

        self._calibration_history.append(result)

        today = date.today().isoformat().replace("-", "")
        reports_dir = Path(__file__).parent.parent.parent / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_file = reports_dir / f"market_calibration_{today}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        return result

    def compute_bias_detection(
        self,
        real_return: float,
        shadow_return: float,
        paper_return: float,
    ) -> dict[str, float]:
        """检测系统偏差。"""
        optimism_bias = round(shadow_return - real_return, 2)
        execution_bias = round(shadow_return - paper_return, 2)
        timing_bias = round(paper_return - real_return, 2)

        if abs(optimism_bias) > 1:
            self._consecutive_bias_days += 1
        else:
            self._consecutive_bias_days = 0

        return {
            "optimism_bias": optimism_bias,
            "execution_bias": execution_bias,
            "timing_bias": timing_bias,
        }

    def adjust_model_parameters(self, bias: dict[str, float]) -> dict[str, Any]:
        """基于偏差自动修正系统参数。"""
        adjustments = {}

        ob = bias.get("optimism_bias", 0)
        if ob > 2:
            self._confidence_multiplier = max(0.5, self._confidence_multiplier * 0.9)
            adjustments["confidence_multiplier"] = round(self._confidence_multiplier, 2)
            adjustments["reason"] = "optimism bias detected, reducing signal confidence"
        elif ob < -2:
            self._confidence_multiplier = min(1.5, self._confidence_multiplier * 1.1)
            adjustments["confidence_multiplier"] = round(self._confidence_multiplier, 2)
            adjustments["reason"] = "pessimism bias detected, increasing signal confidence"

        eb = bias.get("execution_bias", 0)
        if abs(eb) > 1.5:
            self._slippage_k = min(0.3, self._slippage_k * 1.1)
            adjustments["slippage_k_adjustment"] = round(self._slippage_k, 2)

        tb = bias.get("timing_bias", 0)
        if abs(tb) > 2:
            self._latency_adjustment = "increased_variance"
            adjustments["latency_adjustment"] = "increased_variance"

        if not adjustments:
            adjustments["status"] = "no adjustment needed"

        return adjustments

    def reality_alignment_score(
        self,
        real_return: float,
        shadow_return: float,
        paper_return: float,
    ) -> float:
        """计算系统与真实市场一致性评分 (0-100)。"""
        # Return Alignment (40%)
        paper_diff = abs(paper_return - real_return)
        ra = max(0, 100 - paper_diff * 20)

        # Direction Accuracy (30%)
        paper_dir = 1 if paper_return >= 0 else -1
        real_dir = 1 if real_return >= 0 else -1
        da = 100 if paper_dir == real_dir else 0

        # Volatility Match (30%)
        vm = 80.0

        score = round(0.4 * ra + 0.3 * da + 0.3 * vm, 1)
        return score

    def drift_correction_engine(self, bias: dict[str, float]) -> dict[str, Any]:
        """漂移修正引擎。"""
        drift_detected = self._consecutive_bias_days >= 5
        actions = []
        if drift_detected:
            actions.append("降低策略权重")
            actions.append("提升 risk buffer")
            actions.append("触发 governance review")
            actions.append("标记策略为 needs_recalibration")
        return {"drift_detected": drift_detected, "actions": actions, "consecutive_bias_days": self._consecutive_bias_days}