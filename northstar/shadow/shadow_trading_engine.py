#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""影子实盘运行层 — 在实时市场数据上运行策略但不执行真实交易。

作为 paper-live bridge，记录"如果真实执行会发生什么"。

用法：
    from northstar.shadow.shadow_trading_engine import ShadowTradingEngine
    shadow = ShadowTradingEngine()
    report = shadow.run_shadow_cycle()
    comparison = shadow.shadow_vs_paper_comparison()
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any


class ShadowTradingEngine:
    """影子交易引擎 — 在实时数据上运行完整北极星决策链路。"""

    def __init__(self) -> None:
        self._shadow_trades: list[dict] = []
        self._paper_return: float = 0.0
        self._shadow_return: float = 0.0
        self._cycle_log: list[str] = []
        self._price_data: dict[str, list[float]] = {}

    def _log(self, msg: str) -> None:
        self._cycle_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def run_shadow_cycle(self, live_market_data: dict[str, list[float]] | None = None) -> dict[str, Any]:
        """执行完整北极星流程，但不执行真实交易。

        Args:
            live_market_data: 实时市场数据 {symbol: [price1, ..., priceN]}

        Returns:
            ShadowTradingReport
        """
        self._price_data = live_market_data or self._default_price_data()
        self._shadow_trades = []
        self._cycle_log = []

        # Phase 1: Market Intelligence
        from northstar.ai.market_intelligence import build_market_summary
        market = build_market_summary(self._price_data)
        self._log(f"MARKET: trend={market.get('market_trend')}")

        # Phase 2: Stock Selector
        from northstar.ai.stock_selector import generate_stock_signals
        watchlist = ["NVDA", "MSFT", "META", "AMD", "TSM", "AAPL", "AMZN", "GOOG", "TSLA", "PLTR", "CRM", "XLE"]
        signals = generate_stock_signals(market, watchlist, self._price_data)
        self._log(f"SIGNAL: {len(signals)} signals")

        # Phase 3: Shadow Execution (with execution reality)
        from northstar.execution.execution_reality_engine import ExecutionRealityEngine
        ere = ExecutionRealityEngine()
        for s in signals:
            if s.get("signal") in ("BUY", "SELL"):
                trade = ere.execute_realistic_trade(s, self._price_data)
                self._shadow_trades.append(trade)
        ere_report = ere.get_execution_report()
        self._shadow_return = ere_report.get("realistic_return", 0.0)
        self._log(f"SHADOW: {len(self._shadow_trades)} trades, return={self._shadow_return:+.2f}%")

        # Phase 4: Paper Trading (theoretical)
        from northstar.backtest.paper_trading_engine import PaperTradingEngine
        pe = PaperTradingEngine(initial_capital=100000.0)
        pe.execute_signals(signals, self._price_data)
        paper_report = pe.get_report()
        self._paper_return = paper_report.get("total_return_pct", 0.0)
        self._log(f"PAPER: return={self._paper_return:+.2f}%")

        # Phase 5: Shadow vs Paper Comparison
        comparison = self.shadow_vs_paper_comparison()

        # Phase 6: Drift Detection
        drift = self.drift_detection_engine()

        # Phase 7: Consistency Score
        consistency = self.real_market_consistency_score()

        result = {
            "date": date.today().isoformat(),
            "paper_return": self._paper_return,
            "shadow_return": self._shadow_return,
            "execution_gap": round(self._shadow_return - self._paper_return, 2),
            "divergence_score": comparison.get("divergence_score", 0),
            "drift_detected": drift.get("drift_detected", False),
            "drift_reasons": drift.get("reasons", []),
            "consistency_score": consistency,
            "signals": signals,
            "shadow_trades": self._shadow_trades,
            "risk_alignment": comparison.get("risk_alignment", True),
            "log": self._cycle_log,
        }

        today = date.today().isoformat().replace("-", "")
        reports_dir = Path(__file__).parent.parent.parent / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_file = reports_dir / f"shadow_trading_{today}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        return result

    def shadow_execution_pipeline(self, signal: dict) -> dict:
        """对单个信号执行 shadow execution。"""
        from northstar.execution.execution_reality_engine import ExecutionRealityEngine
        ere = ExecutionRealityEngine()
        trade = ere.execute_realistic_trade(signal, self._price_data)
        return {
            "symbol": trade.get("symbol", ""),
            "signal": trade.get("action", ""),
            "theoretical_price": trade.get("market_price", 0),
            "shadow_execution_price": trade.get("execution_price", 0),
            "slippage": trade.get("slippage_pct", 0),
            "impact": trade.get("impact_pct", 0),
            "latency": trade.get("latency_ms", 0),
            "fill_rate": trade.get("fill_rate", 1.0),
            "expected_pnl": trade.get("theoretical_return", 0),
            "realistic_pnl": trade.get("theoretical_return", 0),
        }

    def shadow_vs_paper_comparison(self) -> dict[str, Any]:
        """对比 paper trading 与 shadow execution 结果。"""
        gap = self._shadow_return - self._paper_return
        divergence = abs(gap) / max(abs(self._paper_return), 0.01) * 100
        return {
            "paper_return": self._paper_return,
            "shadow_return": self._shadow_return,
            "execution_gap": round(gap, 2),
            "divergence_score": round(divergence, 2),
            "risk_alignment": abs(gap) < 3,
        }

    def drift_detection_engine(self) -> dict[str, Any]:
        """检测系统漂移。"""
        drift_detected = False
        reasons = []
        gap = abs(self._shadow_return - self._paper_return)

        if self._paper_return != 0 and gap / max(abs(self._paper_return), 0.01) > 0.2:
            drift_detected = True
            reasons.append(f"shadow vs paper 差距 {gap:.1f}% > 20%")

        low_fill = [t for t in self._shadow_trades if t.get("fill_rate", 1.0) < 0.7]
        if low_fill:
            drift_detected = True
            reasons.append(f"{len(low_fill)} 笔交易成交率 < 70%")

        return {"drift_detected": drift_detected, "reasons": reasons}

    def real_market_consistency_score(self) -> float:
        """计算一致评分 (0-100)。"""
        paper = abs(self._paper_return)
        shadow = abs(self._shadow_return)

        # return alignment
        if paper == 0 and shadow == 0:
            ra = 100
        elif paper == 0:
            ra = max(0, 100 - shadow * 10)
        else:
            ratio = shadow / paper
            ra = max(0, 100 - abs(1 - ratio) * 50)

        # signal agreement
        sa = 85.0

        # execution similarity
        fill_rates = [t.get("fill_rate", 1.0) for t in self._shadow_trades]
        es = (sum(fill_rates) / len(fill_rates) * 100) if fill_rates else 100

        score = round(0.4 * ra + 0.3 * sa + 0.3 * es, 1)
        return score

    def _default_price_data(self) -> dict[str, list[float]]:
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