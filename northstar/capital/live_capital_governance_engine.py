#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实盘资金治理层 — 模拟交易系统之上的资金安全控制机制。

用法：
    from northstar.capital.live_capital_governance_engine import LiveCapitalGovernanceEngine
    engine = LiveCapitalGovernanceEngine(total_capital=100000)
    report = engine.evaluate_live_readiness()
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

PHASES = {1: "sandbox", 2: "small_live", 3: "full_live"}


class LiveCapitalGovernanceEngine:
    """实盘资金安全治理引擎。"""

    def __init__(self, total_capital: float = 100000.0) -> None:
        self.total_capital: float = total_capital
        self.phase: int = 1
        self.freeze_until: datetime | None = None
        self._daily_pnl: list[float] = []
        self._consecutive_positive_days: int = 0
        self._consecutive_loss_days: int = 0
        self._peak_capital: float = total_capital

    def evaluate_live_readiness(self, system_metrics: dict[str, Any] | None = None) -> dict[str, Any]:
        """评估系统是否具备实盘条件。

        Args:
            system_metrics: 包含 governance, robustness, walkforward, execution, risk 指标

        Returns:
            LiveReadinessReport: {status, readiness_score, blocking_reasons, ...}
        """
        metrics = system_metrics or {}
        blocking_reasons = []
        score_components = []

        # governance A级占比
        gov = metrics.get("governance", {})
        grade_dist = gov.get("grade_distribution", {})
        total_strategies = gov.get("total_strategies", 0)
        a_count = grade_dist.get("A", 0)
        a_ratio = a_count / max(total_strategies, 1)
        if a_ratio >= 0.4:
            score_components.append(25)
        else:
            blocking_reasons.append(f"A级策略占比{a_ratio:.0%} < 40%")
            score_components.append(a_ratio * 25 * 2.5)

        # robustness_score
        rob = metrics.get("robustness", {})
        rob_score = rob.get("stability_score", 0)
        if rob_score >= 75:
            score_components.append(25)
        else:
            blocking_reasons.append(f"稳健性评分{rob_score:.0f} < 75")
            score_components.append(rob_score * 25 / 75)

        # walkforward consistency
        wf = metrics.get("walkforward", {})
        wf_consistency = wf.get("consistency_score", 0)
        if wf_consistency >= 70:
            score_components.append(20)
        else:
            blocking_reasons.append(f"WalkForward一致性{wf_consistency:.0f} < 70")
            score_components.append(wf_consistency * 20 / 70)

        # execution_gap
        exec_data = metrics.get("execution", {})
        exec_gap = exec_data.get("execution_gap", 0)
        if exec_gap >= -3:
            score_components.append(20)
        else:
            blocking_reasons.append(f"执行差距{exec_gap:.1f}% < -3%")
            score_components.append(max(0, 20 + exec_gap * 5))

        # risk system status
        risk = metrics.get("risk_status", {})
        risk_level = risk.get("risk_level", "LOW")
        if risk_level != "HIGH":
            score_components.append(10)
        else:
            blocking_reasons.append("风险系统为 HIGH 状态")
            score_components.append(5)

        readiness_score = round(sum(score_components), 1)
        status = "GO" if (len(blocking_reasons) == 0 and readiness_score >= 70) else "NO_GO"

        result = {
            "status": status,
            "readiness_score": readiness_score,
            "phase": self.phase,
            "capital_allocation_phase": PHASES.get(self.phase, "unknown"),
            "total_capital": self.total_capital,
            "risk_capital": self._calculate_risk_capital(),
            "safe_capital": self.total_capital - self._calculate_risk_capital(),
            "freeze_status": self._is_frozen(),
            "blocking_reasons": blocking_reasons,
            "circuit_breaker_active": self._circuit_breaker_triggered(),
        }

        self._save_report(result)
        return result

    def capital_release_controller(self, daily_pnl: float | None = None) -> dict[str, Any]:
        """资金分批释放控制。

        Args:
            daily_pnl: 今日盈亏百分比

        Returns:
            当前资金阶段信息
        """
        if daily_pnl is not None:
            self._daily_pnl.append(daily_pnl)
            if daily_pnl > 0:
                self._consecutive_positive_days += 1
                self._consecutive_loss_days = 0
            else:
                self._consecutive_loss_days += 1
                self._consecutive_positive_days = 0

            current_capital = self.total_capital * (1 + sum(self._daily_pnl[-30:]) / 100)
            if current_capital > self._peak_capital:
                self._peak_capital = current_capital

        phase_capital = {
            1: self.total_capital * 0.1,
            2: self.total_capital * 0.3,
            3: self.total_capital * 0.6,
        }

        # 升级检查
        if self.phase == 1 and self._consecutive_positive_days >= 7:
            dd = self._current_drawdown()
            if dd < 5:
                self.phase = 2

        if self.phase == 2 and self._consecutive_positive_days >= 14:
            dd = self._current_drawdown()
            if dd < 5:
                self.phase = 3

        return {
            "current_phase": self.phase,
            "phase_label": PHASES.get(self.phase, "unknown"),
            "release_capital": round(phase_capital.get(self.phase, 0), 2),
            "consecutive_profitable_days": self._consecutive_positive_days,
            "max_drawdown": round(self._current_drawdown(), 2),
        }

    def circuit_breaker_system(self, daily_pnl: float | None = None) -> dict[str, Any]:
        """熔断机制。

        Args:
            daily_pnl: 今日盈亏百分比

        Returns:
            熔断状态
        """
        triggered = False
        actions = []

        if daily_pnl is not None:
            self._daily_pnl.append(daily_pnl)
            self._consecutive_loss_days = self._consecutive_loss_days + 1 if daily_pnl < 0 else 0

            if daily_pnl < -4:
                self.freeze_until = datetime.now() + timedelta(hours=24)
                triggered = True
                actions.append(f"单日亏损{daily_pnl:.1f}% > 4%，冻结24小时")

            if self._consecutive_loss_days >= 3:
                triggered = True
                actions.append(f"连续{self._consecutive_loss_days}天亏损，降低暴露50%")

            dd = self._current_drawdown()
            if dd > 8:
                self.phase = 1
                triggered = True
                actions.append(f"最大回撤{dd:.1f}% > 8%，降级至Phase 1")

        return {
            "circuit_breaker_active": triggered,
            "freeze_status": self._is_frozen(),
            "freeze_until": self.freeze_until.isoformat() if self.freeze_until else None,
            "actions": actions,
        }

    def capital_at_risk_calculator(self) -> dict[str, Any]:
        """计算真实风险资金暴露。"""
        return self.evaluate_live_readiness()

    def _calculate_risk_capital(self) -> float:
        """计算风险资金。"""
        exposure_pct = {1: 0.1, 2: 0.3, 3: 0.6}.get(self.phase, 0.1)
        dd_risk = min(self._current_drawdown() / 100, 0.1) if self._daily_pnl else 0.05
        return round(self.total_capital * exposure_pct * dd_risk, 2)

    def _current_drawdown(self) -> float:
        """计算当前回撤百分比。"""
        if not self._daily_pnl or self._peak_capital <= 0:
            return 0.0
        current = self.total_capital * (1 + sum(self._daily_pnl[-30:]) / 100)
        return max(0, round((self._peak_capital - current) / self._peak_capital * 100, 2))

    def _is_frozen(self) -> bool:
        """检查是否冻结。"""
        if self.freeze_until is None:
            return False
        return datetime.now() < self.freeze_until

    def _circuit_breaker_triggered(self) -> bool:
        """检查是否触发熔断。"""
        return self._is_frozen() or self._consecutive_loss_days >= 3

    def _save_report(self, report: dict) -> None:
        """保存报告。"""
        today = date.today().isoformat().replace("-", "")
        reports_dir = Path(__file__).parent.parent.parent / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_file = reports_dir / f"live_capital_governance_{today}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)