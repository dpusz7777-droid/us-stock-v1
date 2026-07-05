#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""北极星主运行引擎 — 将所有模块串联为完整的每日自动运行投资决策闭环。

用法：
    from northstar.engine.northstar_engine import NorthstarEngine
    engine = NorthstarEngine(total_capital=100000)
    report = engine.run_daily_cycle()
"""

from __future__ import annotations

import json
import traceback
from datetime import date, datetime
from pathlib import Path
from typing import Any


class NorthstarEngine:
    """北极星主运行引擎 — 串联所有模块的每日投资决策闭环。"""

    def __init__(
        self,
        total_capital: float = 100000.0,
        watchlist: list[str] | None = None,
        run_mode: str = "paper",
    ) -> None:
        self.total_capital: float = total_capital
        self.watchlist: list[str] = watchlist or ["NVDA", "MSFT", "META", "AMD", "TSM", "AAPL", "AMZN", "GOOG", "TSLA", "PLTR", "CRM", "XLE"]
        self.run_mode: str = run_mode
        self._log: list[str] = []
        self._price_data: dict[str, list[float]] = self._default_price_data()

    def _default_price_data(self) -> dict[str, list[float]]:
        """提供默认价格数据用于模拟运行。"""
        return {
            "SPY": [500.0, 502.0, 501.0, 505.0, 508.0],
            "QQQ": [400.0, 403.0, 402.0, 406.0, 410.0],
            "NVDA": [800.0, 810.0, 805.0, 820.0, 830.0],
            "MSFT": [300.0, 302.0, 301.0, 305.0, 308.0],
            "META": [200.0, 202.0, 201.0, 205.0, 208.0],
            "AMD": [150.0, 152.0, 151.0, 155.0, 158.0],
            "TSM": [100.0, 102.0, 101.0, 105.0, 108.0],
            "AVGO": [500.0, 505.0, 502.0, 510.0, 515.0],
            "PLTR": [50.0, 51.0, 50.5, 52.0, 53.0],
            "CRM": [200.0, 202.0, 201.0, 205.0, 208.0],
            "XLE": [80.0, 81.0, 80.5, 82.0, 83.0],
            "AAPL": [180.0, 182.0, 181.0, 185.0, 188.0],
            "AMZN": [150.0, 152.0, 151.0, 155.0, 158.0],
            "GOOG": [140.0, 142.0, 141.0, 145.0, 148.0],
            "TSLA": [250.0, 255.0, 252.0, 260.0, 265.0],
        }

    def _log_step(self, step: str, status: str, detail: str = "") -> None:
        """记录步骤日志。"""
        msg = f"[{datetime.now().strftime('%H:%M:%S')}] {step}: {status}"
        if detail:
            msg += f" — {detail}"
        self._log.append(msg)

    def run_daily_cycle(self) -> dict[str, Any]:
        """运行每日完整投资决策循环。

        执行顺序：
        1. MARKET  → 市场洞察
        2. SIGNAL  → 选股信号
        3. ENSEMBLE → 策略组合
        4. RISK    → 风险控制
        5. ALLOCATION → 资金分配
        6. EXECUTION → 模拟交易
        7. EVALUATION → 策略评分
        8. ROBUSTNESS → 稳健性验证
        9. TIME VALIDATION → Walk-Forward
        10. GOVERNANCE → 策略治理
        """
        self._log = []
        today = date.today().isoformat()
        result: dict[str, Any] = {"date": today, "run_mode": self.run_mode, "system_decision": {}, "log": []}

        try:
            # ── Phase 1: MARKET ──
            from northstar.ai.market_intelligence import build_market_summary
            market_summary = build_market_summary(self._price_data)
            result["market_summary"] = market_summary
            self._log_step("MARKET", "OK", f"trend={market_summary.get('market_trend')}")
        except Exception as e:
            self._log_step("MARKET", "FAILED", str(e))
            result["market_summary"] = {}

        try:
            # ── Phase 2: SIGNAL ──
            from northstar.ai.stock_selector import generate_stock_signals
            signals = generate_stock_signals(result.get("market_summary", {}), self.watchlist, self._price_data)
            result["signals"] = signals
            buy_count = sum(1 for s in signals if s.get("signal") == "BUY")
            self._log_step("SIGNAL", "OK", f"{len(signals)} signals ({buy_count} BUY)")
        except Exception as e:
            self._log_step("SIGNAL", "FAILED", str(e))
            result["signals"] = []

        try:
            # ── Phase 3: ENSEMBLE ──
            from northstar.ensemble.strategy_ensemble import StrategyEnsemble
            ensemble = StrategyEnsemble()
            ensemble.add_strategy("baseline", result.get("signals", []))
            combined = ensemble.combine_signals()
            result["ensemble_result"] = {
                "strategy_count": ensemble.get_strategy_count(),
                "combined_signals": combined,
            }
            self._log_step("ENSEMBLE", "OK", f"{len(combined)} combined signals")
        except Exception as e:
            self._log_step("ENSEMBLE", "FAILED", str(e))
            result["ensemble_result"] = {}

        try:
            # ── Phase 4: RISK ──
            from northstar.risk.risk_manager import RiskManager
            rm = RiskManager(initial_capital=self.total_capital)
            risk_allowed = rm.check_risk_limits()
            risk_metrics = rm.get_risk_metrics()
            result["risk_status"] = {
                "risk_level": risk_metrics["risk_level"],
                "can_trade": risk_allowed,
                "consecutive_losses": risk_metrics["consecutive_losses"],
            }
            self._log_step("RISK", "OK" if risk_allowed else "BLOCKED", f"level={risk_metrics['risk_level']}")
        except Exception as e:
            self._log_step("RISK", "FAILED", str(e))
            result["risk_status"] = {"risk_level": "unknown", "can_trade": True}

        try:
            # ── Phase 5: ALLOCATION ──
            from northstar.allocation.capital_allocation_engine import CapitalAllocationEngine
            from northstar.governance.strategy_governance_engine import StrategyGovernanceEngine
            g_engine = StrategyGovernanceEngine()
            g_engine.register_strategy("momentum_v2", {"return_score": 85, "stability_score": 75, "consistency_score": 70, "max_drawdown": 6})
            g_engine.register_strategy("defensive_v1", {"return_score": 70, "stability_score": 85, "consistency_score": 80, "max_drawdown": 4})
            g_engine.register_strategy("ai_alpha_v3", {"return_score": 80, "stability_score": 70, "consistency_score": 65, "max_drawdown": 8})
            g_engine.prune_strategies()
            g_report = g_engine.get_report()

            alloc = CapitalAllocationEngine(total_capital=self.total_capital)
            allocation = alloc.allocate_capital(g_report.get("active_portfolio", {}))
            result["capital_allocation"] = allocation
            result["governance"] = g_report
            self._log_step("ALLOCATION", "OK", f"exposure={allocation.get('exposure_pct', 0):.0%}")
        except Exception as e:
            self._log_step("ALLOCATION", "FAILED", str(e))
            result["capital_allocation"] = {}
            result["governance"] = {}

        try:
            # ── Phase 6: EXECUTION ──
            from northstar.backtest.paper_trading_engine import PaperTradingEngine
            pe = PaperTradingEngine(initial_capital=self.total_capital)
            pe.execute_signals(result.get("signals", []), self._price_data)
            paper_report = pe.get_report()
            result["paper_trading"] = paper_report
            self._log_step("EXECUTION", "OK", f"return={paper_report.get('total_return_pct', 0):+.2f}%")
        except Exception as e:
            self._log_step("EXECUTION", "FAILED", str(e))
            result["paper_trading"] = {}

        try:
            # ── Phase 7: EVALUATION ──
            from northstar.optimizer.strategy_evaluator import evaluate_system_performance
            perf = evaluate_system_performance(result.get("paper_trading", {}), None, result.get("risk_status", {}))
            result["performance"] = perf
            self._log_step("EVALUATION", "OK", f"grade={perf.get('grade')}, score={perf.get('total_score', 0):.0f}")
        except Exception as e:
            self._log_step("EVALUATION", "FAILED", str(e))
            result["performance"] = {}

        try:
            # ── Phase 8: ROBUSTNESS ──
            from northstar.robustness.robustness_engine import run_robustness_analysis
            robustness = run_robustness_analysis()
            result["robustness"] = {
                "stability_score": robustness.get("stability_score", 0),
                "overfitting_score": robustness.get("overfitting_score", 100),
                "best_regime": robustness.get("best_regime", "?"),
            }
            self._log_step("ROBUSTNESS", "OK", f"stability={robustness.get('stability_score', 0):.0f}")
        except Exception as e:
            self._log_step("ROBUSTNESS", "FAILED", str(e))
            result["robustness"] = {}

        try:
            # ── Phase 9: TIME VALIDATION ──
            from northstar.ensemble.walkforward_engine import run_walkforward_test
            wf = run_walkforward_test()
            result["walkforward"] = {
                "consistency_score": wf.get("time_consistency_score", 0),
                "performance_decay": wf.get("performance_decay", 0),
                "regime_dependency": wf.get("regime_dependency", "?"),
            }
            self._log_step("WALKFORWARD", "OK", f"consistency={wf.get('time_consistency_score', 0):.0f}")
        except Exception as e:
            self._log_step("WALKFORWARD", "FAILED", str(e))
            result["walkforward"] = {}

        # ── System Decision ──
        result["system_decision"] = self._generate_system_decision(result)

        result["log"] = self._log
        result["run_success"] = True

        self._save_report(result)
        return result

    def _generate_system_decision(self, result: dict) -> dict[str, Any]:
        """生成最终系统决策。"""
        governance = result.get("governance", {})
        risk_status = result.get("risk_status", {})
        performance = result.get("performance", {})
        robustness = result.get("robustness", {})
        walkforward = result.get("walkforward", {})

        grade_dist = governance.get("grade_distribution", {})
        total_strategies = governance.get("total_strategies", 0)
        a_count = grade_dist.get("A", 0)
        a_ratio = a_count / max(total_strategies, 1)

        risk_level = risk_status.get("risk_level", "LOW")
        can_trade = risk_status.get("can_trade", True)

        perf_score = performance.get("total_score", 0)
        stability = robustness.get("stability_score", 0)
        consistency = walkforward.get("consistency_score", 0)

        reasons = []
        confidence = 0.5

        # HOLD条件
        if a_ratio < 0.3:
            reasons.append(f"A级策略占比{a_ratio:.0%} < 30%")
            if not any("HOLD" in r for r in [reasons[-1]]):
                pass
            return {"action": "HOLD", "confidence": 0.3, "reason": "; ".join(reasons)}

        # REDUCE_RISK条件
        if not can_trade or risk_level == "HIGH":
            reasons.append("风险控制禁止交易")
            return {"action": "REDUCE_RISK", "confidence": 0.2, "reason": "; ".join(reasons)}

        # TRADE条件
        if perf_score >= 60 and stability >= 60 and consistency >= 60:
            reasons.append(f"系统评分{perf_score:.0f}，稳健性{stability:.0f}，时间一致性{consistency:.0f}")
            confidence = round((perf_score + stability + consistency) / 300, 2)
            return {"action": "TRADE", "confidence": confidence, "reason": "; ".join(reasons)}

        # 默认
        reasons.append(f"系统条件未完全满足(评分{perf_score:.0f},稳健{stability:.0f},一致{consistency:.0f})")
        return {"action": "HOLD", "confidence": 0.4, "reason": "; ".join(reasons)}

    def _save_report(self, report: dict) -> None:
        """保存统一系统报告。"""
        today = date.today().isoformat().replace("-", "")
        reports_dir = Path(__file__).parent.parent.parent / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        # 精简log避免过长
        report_clean = dict(report)
        report_clean["log"] = report_clean.get("log", [])[-20:]

        report_file = reports_dir / f"northstar_daily_cycle_{today}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report_clean, f, ensure_ascii=False, indent=2)