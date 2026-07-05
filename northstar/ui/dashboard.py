#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""北极星极简交易执行界面。"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

WATCHLIST = ["NVDA", "AAPL", "MSFT", "GOOG", "TSLA", "AMZN", "META"]


def _load_state() -> dict[str, Any]:
    state_path = PROJECT_ROOT / "northstar" / "data" / "system_state.json"
    try:
        with open(state_path, encoding="utf-8") as source:
            state = json.load(source)
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _portfolio_engine_from_state(state: dict[str, Any]):
    from northstar.engine.portfolio_engine import PortfolioEngine

    engine = PortfolioEngine(
        initial_cash=float(state.get("cash", 0.0) or 0.0),
        mode="paper",
    )
    positions = state.get("positions", [])
    if not isinstance(positions, list):
        return engine

    for position in positions:
        if not isinstance(position, dict):
            continue
        symbol = str(position.get("symbol", "")).strip().upper()
        quantity = float(position.get("qty", 0.0) or 0.0)
        if not symbol or quantity <= 0.0:
            continue
        engine.positions[symbol] = quantity
        engine.avg_cost[symbol] = float(
            position.get("avg_cost", position.get("avg_price", 0.0)) or 0.0
        )
    return engine


def _governance_state(state: dict[str, Any]) -> dict[str, Any]:
    from northstar.engine.strategy_governance import run_strategy_governance

    governance = run_strategy_governance(
        state.get("strategy_evolution"),
        state.get("performance_attribution"),
    )
    drift = governance.get("drift_detection", {})
    return {
        "locked_strategies": governance.get("locked_strategies", []),
        "drift_detected": bool(
            governance.get("drift_detected")
            or (isinstance(drift, dict) and drift.get("is_drifting"))
        ),
        "risk_level": state.get("risk_level", governance.get("system_status")),
    }


def _generate_decisions(state: dict[str, Any]) -> dict[str, Any]:
    from northstar.data.market_data_provider import MarketDataProvider
    from northstar.engine.daily_signal_engine import generate_daily_signals
    from northstar.engine.execution_guard import guard_execution
    from northstar.engine.signal_recalibration import recalibrate_signals

    provider = MarketDataProvider()
    market_context = provider.get_market_context()
    portfolio_engine = _portfolio_engine_from_state(state)
    portfolio_snapshot = portfolio_engine.get_snapshot()

    if state.get("total_equity"):
        portfolio_snapshot["total_value"] = float(state["total_equity"])
        portfolio_snapshot["position_value"] = float(
            state.get("position_market_value", 0.0) or 0.0
        )
        portfolio_snapshot["cash"] = float(state.get("cash", 0.0) or 0.0)

    report = generate_daily_signals(
        portfolio_state=portfolio_snapshot,
        decision_history=state.get("decision_history"),
        performance_attribution=state.get("performance_attribution"),
        market_regime=str(market_context.get("market_regime", "unknown")),
        strategy_evolution=state.get("strategy_evolution"),
        governance=state.get("governance"),
        available_symbols=WATCHLIST,
    )
    original_signals = report.get("signals", [])
    recalibrated = recalibrate_signals(
        original_signals,
        provider,
        portfolio_engine,
    )

    for index, signal in enumerate(recalibrated):
        if index < len(original_signals):
            signal["strategy_source"] = original_signals[index].get(
                "strategy_source",
                "",
            )

    signals = guard_execution(
        recalibrated,
        portfolio_snapshot,
        market_context,
        _governance_state(state),
    )
    return {"signals": signals, "market_context": market_context}


def _today_action(
    signals: list[dict[str, Any]],
    market_context: dict[str, Any],
) -> str:
    actions = {
        str(signal.get("final_action", "HOLD")).upper()
        for signal in signals
    }
    if "SELL" in actions:
        return "卖"

    regime = str(market_context.get("market_regime", "sideways")).lower()
    volatility = float(market_context.get("volatility", 0.0) or 0.0)
    if regime == "bear" or volatility > 0.30:
        return "降仓"
    if "BUY" in actions:
        return "买"
    return "观望"


def _risk_summary(market_context: dict[str, Any]) -> tuple[str, str]:
    regime = str(market_context.get("market_regime", "sideways")).lower()
    volatility = float(market_context.get("volatility", 0.0) or 0.0)
    if regime == "bear" or volatility > 0.30:
        return "高", "否"
    if regime == "sideways" or volatility > 0.18:
        return "中", "否"
    return "低", "否"


def _action_display(signal: dict[str, Any]) -> tuple[str, str, str]:
    action = str(signal.get("final_action", "HOLD")).upper()
    sizing = max(0.0, min(1.0, float(signal.get("position_sizing", 0.0) or 0.0)))
    if action == "BUY":
        return "买入", f"{sizing:.0%}", "buy"
    if action == "SELL":
        return "卖出", f"{sizing:.0%}", "sell"
    return "观望", "—", "hold"


def run() -> None:
    import streamlit as st

    st.set_page_config(
        page_title="今日交易建议",
        page_icon="✦",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown(
        """
        <style>
        :root{color-scheme:dark}
        .stApp,[data-testid="stAppViewContainer"]{background:#080B10;color:#F4F7FB}
        [data-testid="stHeader"]{background:rgba(8,11,16,.92)}
        [data-testid="stMainBlockContainer"]{max-width:1050px;padding:2.5rem 2rem 4rem}
        [data-testid="stSidebar"],#MainMenu,footer{display:none!important}
        .block{background:linear-gradient(145deg,#121821,#0D1219);border:1px solid #202936;
          border-radius:20px;padding:24px 26px;margin-bottom:18px;box-shadow:0 18px 45px rgba(0,0,0,.2)}
        .label{font-size:13px;font-weight:750;color:#8793A5;letter-spacing:.08em;margin-bottom:12px}
        .one-line{font-size:48px;font-weight:850;letter-spacing:-.05em;color:#F5C76B}
        .signal-row{display:grid;grid-template-columns:1fr 130px 120px;align-items:center;
          border-top:1px solid #202936;padding:16px 4px}
        .signal-row:first-of-type{border-top:0}
        .symbol{font-size:19px;font-weight:850;letter-spacing:.04em}
        .action{font-size:14px;font-weight:800}
        .buy{color:#20D69B}.sell{color:#FF647C}.hold{color:#A0AABA}
        .size{text-align:right;font:750 15px ui-monospace,SFMono-Regular,Menlo,monospace;color:#E5EAF1}
        .size small{font:500 11px Inter,-apple-system,sans-serif;color:#6F7A8B;margin-right:8px}
        .risk-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
        .risk-item{background:#10151D;border:1px solid #202936;border-radius:13px;padding:17px}
        .risk-key{font-size:12px;color:#758195}.risk-value{font-size:25px;font-weight:850;margin-top:5px}
        @media(max-width:700px){
          [data-testid="stMainBlockContainer"]{padding:1.4rem 1rem 3rem}
          .one-line{font-size:40px}.signal-row{grid-template-columns:1fr 90px 80px}
          .block{padding:20px}.risk-grid{grid-template-columns:1fr}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    state = _load_state()
    if "execution_decisions" not in st.session_state:
        with st.spinner("正在生成今日交易建议…"):
            st.session_state.execution_decisions = _generate_decisions(state)

    decision_data = st.session_state.execution_decisions
    signals = decision_data.get("signals", [])
    market_context = decision_data.get("market_context", {})
    today_action = _today_action(signals, market_context)
    risk_level, full_position = _risk_summary(market_context)

    st.markdown(
        f"""
        <div class="block">
          <div class="label">今日一句话策略</div>
          <div class="one-line">{today_action}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    rows = []
    for signal in signals:
        symbol = html.escape(str(signal.get("symbol", "—")))
        action, sizing, style = _action_display(signal)
        rows.append(
            f"""
            <div class="signal-row">
              <div class="symbol">{symbol}</div>
              <div class="action {style}">{action}</div>
              <div class="size"><small>仓位</small>{sizing}</div>
            </div>
            """
        )
    if not rows:
        rows.append(
            '<div class="signal-row"><div class="symbol">—</div>'
            '<div class="action hold">观望</div>'
            '<div class="size"><small>仓位</small>—</div></div>'
        )

    st.markdown(
        f"""
        <div class="block">
          <div class="label">股票操作列表</div>
          {"".join(rows)}
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div class="block">
          <div class="label">风险提示</div>
          <div class="risk-grid">
            <div class="risk-item">
              <div class="risk-key">风险等级</div>
              <div class="risk-value">{risk_level}</div>
            </div>
            <div class="risk-item">
              <div class="risk-key">是否建议满仓</div>
              <div class="risk-value">{full_position}</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_market_intelligence(st: Any) -> None:
    """渲染每日AI市场洞察。"""
    try:
        from northstar.ai.market_intelligence import build_market_summary
        from northstar.ai.stock_selector import generate_stock_signals

        # 构建示例价格数据
        price_data = {
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
        }

        with st.expander("📊 每日AI市场洞察", expanded=False):
            market = build_market_summary(price_data)
            trend_icon = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}.get(market["market_trend"], "⚪")
            risk_icon = {"low": "✅", "medium": "⚠️", "high": "🔴"}.get(market["risk_level"], "❓")

            col1, col2, col3 = st.columns(3)
            col1.metric("市场趋势", f"{trend_icon} {market['market_trend'].upper()}")
            col2.metric("风险等级", f"{risk_icon} {market['risk_level'].upper()}")
            col3.metric("日期", market["date"])

            st.markdown("**行业强度**")
            ss = market.get("sector_strength", {})
            for sector, strength in sorted(ss.items(), key=lambda x: -x[1]):
                bar_color = "🟢" if strength > 2 else ("🔴" if strength < -2 else "🟡")
                st.markdown(f"- {sector}: {bar_color} {strength:+.1f}%")

            st.markdown("**关键驱动因素**")
            for driver in market.get("key_drivers", []):
                st.markdown(f"- {driver}")

            # 生成股票信号
            watchlist = ["NVDA", "MSFT", "META", "AMD", "TSM", "PLTR", "CRM", "XLE"]
            signals = generate_stock_signals(market, watchlist, price_data)

            st.markdown("**选股信号**")
            for s in signals:
                icon = {"BUY": "🟢", "WATCH": "🟡", "AVOID": "🔴"}.get(s["signal"], "⚪")
                st.markdown(f"- {s['symbol']}: {icon} **{s['signal']}** (置信度{s['confidence']:.0%}) — {s['reason']}")

            st.caption("AI市场洞察仅基于历史价格数据，不构成投资建议")
    except Exception as exc:
        st.caption(f"AI市场洞察暂不可用: {exc}")


def render_paper_trading(st: Any) -> None:
    """渲染模拟交易结果。"""
    try:
        from northstar.backtest.paper_trading_engine import PaperTradingEngine
        from northstar.ai.market_intelligence import build_market_summary
        from northstar.ai.stock_selector import generate_stock_signals

        price_data = {
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
        }

        with st.expander("💰 模拟交易结果", expanded=False):
            market = build_market_summary(price_data)
            watchlist = ["NVDA", "MSFT", "META", "AMD", "TSM", "PLTR", "CRM", "XLE"]
            signals = generate_stock_signals(market, watchlist, price_data)

            engine = PaperTradingEngine(initial_capital=100000.0)
            engine.execute_signals(signals, price_data)
            report = engine.get_report()

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("总收益率", f'{report["total_return_pct"]:+.2f}%')
            c2.metric("胜率", f'{report["win_rate"]:.0%}')
            c3.metric("最大回撤", f'{report["max_drawdown_pct"]:.2f}%')
            c4.metric("当前持仓", report["open_positions"])

            st.markdown("**最近5笔交易**")
            for t in report.get("closed_trades", [])[:5]:
                icon = "🟢" if t["pnl_pct"] > 0 else "🔴"
                st.markdown(f"- {t['symbol']}: {icon} {t['pnl_pct']:+.2f}% (持仓{t.get('days_held', '?')}天)")

            st.caption("模拟交易仅基于历史价格数据回测，不构成投资建议")
    except Exception as exc:
        st.caption(f"模拟交易暂不可用: {exc}")


def render_risk_control_panel(st: Any) -> None:
    """渲染风险控制面板。"""
    try:
        from northstar.risk.risk_manager import RiskManager
        from northstar.ai.market_intelligence import build_market_summary
        from northstar.ai.stock_selector import generate_stock_signals
        from northstar.backtest.paper_trading_engine import PaperTradingEngine

        price_data = {
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
        }

        with st.expander("🛡 风险控制面板", expanded=False):
            market = build_market_summary(price_data)
            watchlist = ["NVDA", "MSFT", "META", "AMD", "TSM", "PLTR", "CRM", "XLE"]
            signals = generate_stock_signals(market, watchlist, price_data)

            # 运行模拟交易并通过RiskManager控制
            engine = PaperTradingEngine(initial_capital=100000.0)
            rm = RiskManager(initial_capital=100000.0)
            engine.execute_signals(signals, price_data)
            report = engine.get_report()

            # 更新RiskManager状态
            rm.update_portfolio(report["current_capital"], report["max_drawdown_pct"] / 100)
            total_used = sum(t["position_size"] for t in report.get("closed_trades", []))
            rm.set_position_utilization(total_used, report["current_capital"])
            for t in report.get("closed_trades", [])[:5]:
                rm.record_trade_result(t["pnl_pct"])

            metrics = rm.get_risk_metrics()
            risk_icon = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴"}.get(metrics["risk_level"], "⚪")
            trade_icon = "✅" if metrics["can_trade_today"] else "🔴"

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("当前风险等级", f"{risk_icon} {metrics['risk_level']}")
            c2.metric("仓位利用率", f"{metrics['position_utilization']:.0%}")
            c3.metric("最大回撤", f"{metrics['max_drawdown_pct']:.2f}%")
            c4.metric("今日是否交易", trade_icon)

            # 风险事件
            events = metrics.get("recent_risk_events", [])
            if events:
                st.markdown("**最近风险事件**")
                for evt in events[:3]:
                    st.markdown(f"- {evt.get('type', '')}: {evt.get('detail', '')}")
            else:
                st.markdown("**最近风险事件**")
                st.caption("暂无风险事件")

            st.caption("风险控制面板仅用于监控模拟交易风险，不构成投资建议")
    except Exception as exc:
        st.caption(f"风险控制面板暂不可用: {exc}")


def render_strategy_optimizer_panel(st: Any) -> None:
    """渲染策略评分与优化面板。"""
    try:
        from northstar.optimizer.strategy_evaluator import evaluate_system_performance
        from northstar.optimizer.strategy_optimizer import optimize_parameters
        from northstar.backtest.paper_trading_engine import PaperTradingEngine
        from northstar.ai.market_intelligence import build_market_summary
        from northstar.ai.stock_selector import generate_stock_signals
        from northstar.risk.risk_manager import RiskManager

        with st.expander("📊 策略评分与优化面板", expanded=False):
            price_data = {
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
            }
            market = build_market_summary(price_data)
            watchlist = ["NVDA", "MSFT", "META", "AMD", "TSM", "PLTR", "CRM", "XLE"]
            signals = generate_stock_signals(market, watchlist, price_data)

            engine = PaperTradingEngine(initial_capital=100000.0)
            engine.execute_signals(signals, price_data)
            report = engine.get_report()

            rm = RiskManager(initial_capital=100000.0)
            rm.update_portfolio(report["current_capital"], report["max_drawdown_pct"] / 100)
            metrics = rm.get_risk_metrics()

            # 策略评分
            score = evaluate_system_performance(report, None, metrics)
            grade_icon = {"A": "🟢", "B": "🟡", "C": "🟠", "D": "🔴"}.get(score["grade"], "⚪")

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("等级", f"{grade_icon} {score['grade']}")
            c2.metric("总评分", f"{score['total_score']:.0f}")
            c3.metric("收益评分", f"{score['return_score']:.0f}")
            c4.metric("稳定性评分", f"{score['stability_score']:.0f}")

            # 优化结果
            opt = optimize_parameters(None)
            is_optimal = opt["best_score"] <= opt["baseline_score"] + 1
            st.metric("是否达到最优策略", "✅ 是" if is_optimal else "🔄 否")

            st.markdown("**推荐参数调整建议**")
            for s in opt.get("parameter_suggestions", []):
                st.markdown(f"- {s}")

            st.caption("策略评分与优化仅基于历史回测数据，不构成投资建议")
    except Exception as exc:
        st.caption(f"策略评分暂不可用: {exc}")


def render_robustness_analysis(st: Any) -> None:
    """渲染策略稳健性分析面板。"""
    try:
        from northstar.robustness.robustness_engine import run_robustness_analysis

        with st.expander("🧪 策略稳健性分析面板", expanded=False):
            report = run_robustness_analysis()
            stability = report.get("stability_score", 0)
            overfitting = report.get("overfitting_score", 100)
            passed = stability > 70 and overfitting < 40
            passed_icon = "✅" if passed else "❌"

            c1, c2, c3 = st.columns(3)
            c1.metric("稳健性评分", f"{stability:.0f}")
            c2.metric("过拟合评分", f"{overfitting:.0f} (越低越好)")
            c3.metric("通过测试", f"{passed_icon} {'是' if passed else '否'}")

            st.markdown("**不同市场环境表现**")
            rp = report.get("regime_performance", {})
            for regime, data in rp.items():
                icon = "🟢" if data.get("return_pct", 0) > 0 else "🔴"
                st.markdown(f"- {regime.upper()}: {icon} 收益{data.get('return_pct', 0):+.1f}% | 胜率{data.get('win_rate', 0):.0%} | 回撤{data.get('max_drawdown_pct', 0):.1f}%")

            st.markdown("**不同股票池表现**")
            up = report.get("universe_performance", {})
            for name, data in up.items():
                icon = "🟢" if data.get("return_pct", 0) > 0 else "🔴"
                st.markdown(f"- {name}: {icon} 收益{data.get('return_pct', 0):+.1f}% | 胜率{data.get('win_rate', 0):.0%}")

            st.caption(f"最佳环境: {report.get('best_regime', '?').upper()} | 最差环境: {report.get('worst_regime', '?').upper()}")
            st.caption("策略稳健性分析仅基于历史数据回测，不构成投资建议")
    except Exception as exc:
        st.caption(f"策略稳健性分析暂不可用: {exc}")


def render_walkforward_panel(st: Any) -> None:
    """渲染Walk-Forward验证面板。"""
    try:
        from northstar.ensemble.walkforward_engine import run_walkforward_test

        with st.expander("🧭 Walk-Forward 验证面板", expanded=False):
            report = run_walkforward_test()
            windows = report.get("windows", [])
            consistency = report.get("time_consistency_score", 0)
            decay = report.get("performance_decay", 0)
            passed = consistency > 70 and decay < 20
            passed_icon = "✅" if passed else "❌"

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("时间一致性", f"{consistency:.0f}")
            c2.metric("性能衰减", f"{decay:.1f}%")
            c3.metric("窗口数量", len(windows))
            c4.metric("通过测试", f"{passed_icon} {'是' if passed else '否'}")

            st.markdown("**各窗口收益**")
            for w in windows:
                icon = "🟢" if w.get("test_return_pct", 0) > 0 else "🔴"
                st.markdown(f"- 窗口{w['window_id']}: {icon} 训练{w.get('train_return_pct', 0):+.1f}% → 测试{w.get('test_return_pct', 0):+.1f}%")

            st.markdown(f"**市场依赖**: {report.get('regime_dependency', '?')}")
            st.markdown(f"**最佳窗口**: #{report.get('best_window', '?')} | **最差窗口**: #{report.get('worst_window', '?')}")
            st.caption("Walk-Forward验证仅基于历史数据滚动回测，不构成投资建议")
    except Exception as exc:
        st.caption(f"Walk-Forward验证暂不可用: {exc}")


def render_governance_panel(st: Any) -> None:
    """渲染策略治理与系统收敛面板。"""
    try:
        from northstar.governance.strategy_governance_engine import StrategyGovernanceEngine

        with st.expander("🧭 策略治理与系统收敛面板", expanded=False):
            engine = StrategyGovernanceEngine()
            # 注册示例策略
            engine.register_strategy("momentum_v1", {"return_score": 85, "stability_score": 75, "consistency_score": 70, "max_drawdown": 6})
            engine.register_strategy("defensive_v1", {"return_score": 70, "stability_score": 85, "consistency_score": 80, "max_drawdown": 4})
            engine.register_strategy("breakout_v1", {"return_score": 55, "stability_score": 45, "consistency_score": 40, "max_drawdown": 15})
            engine.register_strategy("mean_reversion_v1", {"return_score": 60, "stability_score": 55, "consistency_score": 50, "max_drawdown": 10})
            engine.register_strategy("momentum_v2", {"return_score": 90, "stability_score": 80, "consistency_score": 75, "max_drawdown": 5})

            engine.prune_strategies()
            report = engine.get_report()

            grade_counts = report.get("grade_distribution", {})
            total = report.get("total_strategies", 0)
            passed = report.get("governance_check_passed", False)
            over_complex = report.get("is_over_complex", False)
            complexity = report.get("system_complexity_score", 0)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("策略总数", total)
            c2.metric("复杂度", f"{complexity:.0f}")
            c3.metric("A级占比", f"{grade_counts.get('A', 0)}/{total}")
            c4.metric("治理检查", "✅ 通过" if passed else "❌ 未通过")

            if over_complex:
                st.warning("⚠️ 系统过于复杂，需要收敛！")

            st.markdown("**等级分布**")
            for grade in ("A", "B", "C", "D"):
                count = grade_counts.get(grade, 0)
                icon = {"A": "🟢", "B": "🟡", "C": "🟠", "D": "🔴"}.get(grade, "⚪")
                st.markdown(f"- {grade}: {icon} {count} 个策略")

            st.markdown("**可运行策略组合**")
            ap = report.get("active_portfolio", {})
            for s in ap.get("strategies", []):
                w = ap.get("weights", {}).get(s, 0)
                st.markdown(f"- {s}: 权重 {w:.1%}")

            st.caption("策略治理仅基于历史数据评分的生命周期管理")
    except Exception as exc:
        st.caption(f"策略治理暂不可用: {exc}")


def render_capital_allocation_panel(st: Any) -> None:
    """渲染资金分配与组合控制面板。"""
    try:
        from northstar.allocation.capital_allocation_engine import CapitalAllocationEngine
        from northstar.governance.strategy_governance_engine import StrategyGovernanceEngine

        with st.expander("💰 资金分配与组合控制面板", expanded=False):
            engine = StrategyGovernanceEngine()
            engine.register_strategy("momentum_v2", {"return_score": 85, "stability_score": 75, "consistency_score": 70, "max_drawdown": 6})
            engine.register_strategy("defensive_v1", {"return_score": 70, "stability_score": 85, "consistency_score": 80, "max_drawdown": 4})
            engine.register_strategy("ai_alpha_v3", {"return_score": 80, "stability_score": 70, "consistency_score": 65, "max_drawdown": 8})
            engine.prune_strategies()
            governance_report = engine.get_report()

            alloc_engine = CapitalAllocationEngine(total_capital=100000.0)
            portfolio = governance_report.get("active_portfolio", {})
            allocation = alloc_engine.allocate_capital(portfolio)

            total = allocation.get("total_capital", 0)
            cash = allocation.get("cash_reserve", 0)
            exposure = allocation.get("exposure_pct", 0)
            concentration = allocation.get("portfolio_concentration", 0)
            constraints_ok = allocation.get("constraints_satisfied", True)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("总资金", f"${total:,.0f}")
            c2.metric("现金储备", f"${cash:,.0f} ({cash/total*100:.0f}%)")
            c3.metric("总暴露", f"{exposure:.0%}")
            c4.metric("合规", "✅" if constraints_ok else "❌")

            st.markdown("**各策略资金分配**")
            sa = allocation.get("strategy_allocations", {})
            for s, amt in sorted(sa.items(), key=lambda x: -x[1]):
                pct = amt / total * 100 if total > 0 else 0
                st.markdown(f"- {s}: ${amt:,.0f} ({pct:.1f}%)")

            if concentration > 0.6:
                st.warning(f"⚠️ 组合集中度较高（{concentration:.0%}），超过60%建议阈值")
            else:
                st.info(f"组合集中度 {concentration:.0%}，在安全范围内")

            st.caption("资金分配仅基于模拟策略评分，不构成投资建议")
    except Exception as exc:
        st.caption(f"资金分配暂不可用: {exc}")


def render_northstar_control_panel(st: Any) -> None:
    """渲染北极星系统控制面板。"""
    try:
        from northstar.engine.northstar_engine import NorthstarEngine

        with st.expander("🧠 Northstar System Control Panel", expanded=False):
            engine = NorthstarEngine(total_capital=100000.0)
            report = engine.run_daily_cycle()

            sd = report.get("system_decision", {})
            action = sd.get("action", "HOLD")
            confidence = sd.get("confidence", 0)
            action_icon = {"TRADE": "✅", "HOLD": "⏸️", "REDUCE_RISK": "⚠️"}.get(action, "❓")

            run_ok = report.get("run_success", False)
            pt = report.get("paper_trading", {})
            risk = report.get("risk_status", {})
            gov = report.get("governance", {})
            gc = gov.get("governance_check_passed", False)
            rob = report.get("robustness", {})
            rob_ok = rob.get("stability_score", 0) > 70
            wf = report.get("walkforward", {})
            wf_ok = wf.get("consistency_score", 0) > 70
            n_strategies = gov.get("total_strategies", 0)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("运行状态", "✅ 成功" if run_ok else "❌ 失败")
            c2.metric("系统决策", f"{action_icon} {action}")
            c3.metric("置信度", f"{confidence:.0%}")
            c4.metric("总收益", f'{pt.get("total_return_pct", 0):+.2f}%')

            st.markdown("**系统检查项**")
            st.markdown(f"- 风险等级: {risk.get('risk_level', '?')}")
            st.markdown(f"- 治理检查: {'✅' if gc else '❌'}")
            st.markdown(f"- 稳健性检查: {'✅' if rob_ok else '❌'} (评分{rob.get('stability_score', 0):.0f})")
            st.markdown(f"- WalkForward: {'✅' if wf_ok else '❌'} (一致{wf.get('consistency_score', 0):.0f})")
            st.markdown(f"- 策略数量: {n_strategies}")

            st.markdown("**运行日志**")
            for line in report.get("log", [])[-5:]:
                st.markdown(f"- {line}")

            st.caption("北极星系统控制面板显示今日完整决策闭环结果")
    except Exception as exc:
        st.caption(f"控制系统暂不可用: {exc}")


def render_execution_reality_panel(st: Any) -> None:
    """渲染执行现实层面板。"""
    try:
        from northstar.execution.execution_reality_engine import ExecutionRealityEngine

        with st.expander("🌍 Execution Reality Layer", expanded=False):
            ere = ExecutionRealityEngine()
            signals = [
                {"symbol": "NVDA", "signal": "BUY", "confidence": 0.85},
                {"symbol": "MSFT", "signal": "BUY", "confidence": 0.75},
                {"symbol": "AAPL", "signal": "WATCH", "confidence": 0.50},
            ]
            for s in signals:
                ere.execute_realistic_trade(s)
            report = ere.get_execution_report()

            theoretical = report.get("theoretical_return", 0)
            realistic = report.get("realistic_return", 0)
            gap = report.get("execution_gap", 0)
            fill_rate = report.get("fill_rate", 1.0)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("理论收益", f"{theoretical:+.2f}%")
            c2.metric("现实收益", f"{realistic:+.2f}%")
            c3.metric("执行差距", f"{gap:+.2f}%")
            c4.metric("成交率", f"{fill_rate:.0%}")

            st.markdown("**成本明细**")
            st.markdown(f"- 滑点成本: {report.get('slippage_cost', 0):.2f}%")
            st.markdown(f"- 市场冲击成本: {report.get('market_impact_cost', 0):.2f}%")
            st.markdown(f"- 延迟成本: {report.get('latency_cost', 0):.2f}%")

            is_tradable = realistic > 0 and gap > -5
            st.metric("是否仍可交易", "✅ 是" if is_tradable else "❌ 否")

            pending = report.get("pending_orders", 0)
            if pending > 0:
                st.warning(f"⚠️ {pending} 个订单未完全成交")
            st.caption("执行现实层模拟真实市场摩擦，不构成投资建议")
    except Exception as exc:
        st.caption(f"执行现实层暂不可用: {exc}")


def render_live_capital_governance_panel(st: Any) -> None:
    """渲染实盘资金安全闸门面板。"""
    try:
        from northstar.capital.live_capital_governance_engine import LiveCapitalGovernanceEngine

        with st.expander("🚦 实盘资金安全闸门面板", expanded=False):
            engine = LiveCapitalGovernanceEngine(total_capital=100000.0)
            metrics = {
                "governance": {"grade_distribution": {"A": 2, "B": 1, "C": 0, "D": 0}, "total_strategies": 3},
                "robustness": {"stability_score": 85},
                "walkforward": {"consistency_score": 80},
                "execution": {"execution_gap": -1.5},
                "risk_status": {"risk_level": "LOW"},
            }
            report = engine.evaluate_live_readiness(metrics)

            status = report.get("status", "NO_GO")
            score = report.get("readiness_score", 0)
            phase = report.get("phase", 1)
            phase_label = report.get("capital_allocation_phase", "?")
            frozen = report.get("freeze_status", False)
            cb_active = report.get("circuit_breaker_active", False)
            risk_cap = report.get("risk_capital", 0)
            safe_cap = report.get("safe_capital", 0)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("实盘状态", "🟢 GO" if status == "GO" else "🔴 NO_GO")
            c2.metric("准备评分", f"{score:.0f}")
            c3.metric("资金阶段", f"Phase {phase} ({phase_label})")
            c4.metric("冻结状态", "🔒 冻结" if frozen else "✅ 正常")

            st.markdown("**资金分布**")
            st.markdown(f"- 风险资金: ${risk_cap:,.0f}")
            st.markdown(f"- 安全资金: ${safe_cap:,.0f}")
            st.markdown(f"- 熔断状态: {'⚠️ 已触发' if cb_active else '✅ 正常'}")

            reasons = report.get("blocking_reasons", [])
            if reasons:
                st.error("**阻止实盘的原因**")
                for r in reasons:
                    st.markdown(f"- {r}")
            else:
                st.success("✅ 未发现阻止实盘的问题")

            st.caption("实盘资金安全闸门仅用于风险评估，不构成投资建议")
    except Exception as exc:
        st.caption(f"实盘资金闸门暂不可用: {exc}")


if __name__ == "__main__":
    run()
