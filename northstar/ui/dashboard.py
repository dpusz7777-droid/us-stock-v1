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


if __name__ == "__main__":
    run()
