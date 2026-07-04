#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""北极星交易决策界面。

启动方式：streamlit run northstar/ui/dashboard.py
"""

from __future__ import annotations

import html
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

WATCHLIST = ["NVDA", "AAPL", "MSFT", "GOOG", "TSLA", "AMZN", "META"]


def _load_json(path: Path, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as source:
            return json.load(source)
    except (OSError, ValueError, TypeError):
        return default


def _portfolio_engine_from_state(state: dict[str, Any]):
    from northstar.engine.portfolio_engine import PortfolioEngine

    cash = float(state.get("cash", 0.0) or 0.0)
    engine = PortfolioEngine(initial_cash=cash, mode="paper")
    positions = state.get("positions", [])
    if isinstance(positions, list):
        for position in positions:
            if not isinstance(position, dict):
                continue
            symbol = str(position.get("symbol", "")).upper()
            quantity = float(position.get("qty", 0.0) or 0.0)
            if not symbol or quantity <= 0.0:
                continue
            engine.positions[symbol] = quantity
            engine.avg_cost[symbol] = float(
                position.get("avg_cost", position.get("avg_price", 0.0)) or 0.0
            )
    return engine


def _governance_for_guard(state: dict[str, Any]) -> dict[str, Any]:
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
        "risk_level": state.get("risk_level", governance.get("system_status", "stable")),
    }


def _generate_decisions(
    state: dict[str, Any],
    refresh_market_data: bool = False,
) -> dict[str, Any]:
    from northstar.data.market_data_provider import MarketDataProvider
    from northstar.engine.daily_signal_engine import generate_daily_signals
    from northstar.engine.execution_guard import guard_execution
    from northstar.engine.signal_recalibration import recalibrate_signals

    provider = MarketDataProvider()
    if refresh_market_data:
        provider.cache = {}

    market_context = provider.get_market_context()
    portfolio_engine = _portfolio_engine_from_state(state)
    portfolio_snapshot = portfolio_engine.get_snapshot()
    if state.get("total_equity"):
        portfolio_snapshot["total_value"] = float(state["total_equity"])
        portfolio_snapshot["position_value"] = float(
            state.get("position_market_value", 0.0) or 0.0
        )
        portfolio_snapshot["cash"] = float(state.get("cash", 0.0) or 0.0)

    daily_report = generate_daily_signals(
        portfolio_state=portfolio_snapshot,
        decision_history=state.get("decision_history"),
        performance_attribution=state.get("performance_attribution"),
        market_regime=str(market_context.get("market_regime", "unknown")),
        strategy_evolution=state.get("strategy_evolution"),
        governance=state.get("governance"),
        available_symbols=WATCHLIST,
    )
    raw_signals = daily_report.get("signals", [])
    recalibrated = recalibrate_signals(
        raw_signals,
        provider,
        portfolio_engine,
    )

    # v54 also needs the v51 strategy label for sideways-regime protection.
    for index, adjusted in enumerate(recalibrated):
        if index < len(raw_signals):
            adjusted["strategy_source"] = raw_signals[index].get(
                "strategy_source",
                "",
            )

    guarded = guard_execution(
        recalibrated,
        portfolio_snapshot,
        market_context,
        _governance_for_guard(state),
    )
    quotes = provider.get_batch_prices(WATCHLIST)
    generated_at = datetime.now().astimezone().strftime("%H:%M:%S")
    return {
        "market_context": market_context,
        "signals": guarded,
        "quotes": quotes,
        "generated_at": generated_at,
    }


def _run_backtest_summary() -> dict[str, Any]:
    from northstar.engine.backtest_engine import run_backtest

    trades_path = PROJECT_ROOT / "northstar" / "data" / "trade_history.json"
    history = _load_json(trades_path, [])
    decisions = history if isinstance(history, list) else []
    result = run_backtest(decision_history=decisions)
    return {
        "total_return": float(result.get("total_return", 0.0) or 0.0),
        "win_rate": float(result.get("win_rate", 0.0) or 0.0),
        "trade_count": len(decisions),
    }


def _market_copy(context: dict[str, Any]) -> tuple[str, str, str]:
    regime = str(context.get("market_regime", "sideways")).lower()
    trend = str(context.get("SPY_trend", "sideways")).lower()
    if regime == "bull":
        return "偏多", "市场动能积极，可选择性关注高置信度机会。", "positive"
    if regime == "bear":
        return "防守", "市场处于弱势，控制仓位并优先处理持仓风险。", "negative"
    trend_copy = "向上" if trend == "up" else ("向下" if trend == "down" else "震荡")
    return "观望", f"市场方向尚未形成，SPY 短线{trend_copy}。", "neutral"


def translate_signal_reason(reason: str) -> str:
    """把引擎原因翻译成非技术用户可以直接理解的中文。"""
    original = str(reason or "").strip()
    normalized = original.lower()
    translations = (
        ("weak momentum", "上涨趋势较弱"),
        ("strong momentum", "上涨趋势明显"),
        ("momentum", "上涨趋势"),
        ("volatility high", "波动较大"),
        ("high volatility", "波动较大"),
        ("low volatility", "市场波动较小"),
        ("regime match", "市场环境匹配"),
        ("regime mismatch", "市场环境不匹配"),
        ("sideways regime", "震荡行情不利于追涨"),
        ("bear market", "熊市环境下已降低仓位"),
        ("risk high", "风险较高"),
        ("portfolio exposure", "当前持仓比例偏高"),
        ("exposure cap", "当前持仓比例已达上限"),
        ("existing position sell", "已有持仓的风险正在上升"),
        ("existing position buy", "已有持仓，不宜继续加仓"),
        ("insufficient cash", "可用现金不足"),
        ("confidence below", "当前信号不够明确"),
        ("high-risk strategy", "当前策略风险偏高"),
        ("governance drift", "策略表现出现偏离"),
        ("governance lock", "风控规则暂不允许交易"),
        ("drift", "策略表现出现偏离"),
    )
    for key, translated in translations:
        if key in normalized:
            return translated
    if any("\u4e00" <= character <= "\u9fff" for character in original):
        return original
    return "当前信号需要谨慎评估"


def _human_signal_reason(action: str, reasons: Any) -> str:
    reason_items = reasons if isinstance(reasons, list) else [reasons]
    translated = [
        translate_signal_reason(reason)
        for reason in reason_items
        if str(reason or "").strip()
    ]
    translated = list(dict.fromkeys(translated))
    if translated:
        return " + ".join(translated)
    if action == "BUY":
        return "上涨趋势 + 市场环境匹配 + 风险较低"
    if action == "SELL":
        return "风险正在上升，建议降低持仓"
    return "当前信号不明确，不建议交易"


def _market_labels(context: dict[str, Any]) -> tuple[str, str, str]:
    regime = str(context.get("market_regime", "sideways")).lower()
    volatility = float(context.get("volatility", 0.0) or 0.0)
    market_state = {
        "bull": "牛市",
        "bear": "熊市",
        "sideways": "震荡市",
    }.get(regime, "震荡市")
    if volatility > 0.30 or regime == "bear":
        return market_state, "高", "降低仓位"
    if volatility > 0.18 or regime == "sideways":
        return market_state, "中", "观望"
    return market_state, "低", "交易"


def _risk_messages(
    context: dict[str, Any],
    signals: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    risks: list[tuple[str, str]] = []
    volatility = float(context.get("volatility", 0.0) or 0.0)
    if volatility > 0.30:
        risks.append(("严重", "波动率极高，所有买入已被暂停。"))
    elif volatility > 0.20:
        risks.append(("注意", "市场波动偏高，建议缩小单笔仓位。"))

    blocked = sum(1 for item in signals if item.get("final_action") == "HOLD")
    if blocked:
        risks.append(("提示", f"{blocked} 个候选信号未通过最终安全检查。"))
    if not risks:
        risks.append(("正常", "当前未发现需要额外处置的市场风险。"))
    return risks


def run() -> None:
    import streamlit as st

    st.set_page_config(
        page_title="北极星交易决策",
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
        [data-testid="stMainBlockContainer"]{max-width:1280px;padding:1.4rem 2rem 3rem}
        [data-testid="stSidebar"],#MainMenu,footer{display:none!important}
        h1,h2,h3,p{font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
        .brand{font-size:13px;font-weight:800;letter-spacing:.18em;color:#8B98AA}
        .headline{font-size:34px;font-weight:760;letter-spacing:-.035em;margin:.3rem 0 0}
        .timestamp{font-size:12px;color:#687386;margin-top:.35rem}
        .panel{background:linear-gradient(145deg,#121821,#0D1219);border:1px solid #202936;
          border-radius:18px;padding:22px;box-shadow:0 18px 45px rgba(0,0,0,.2);height:100%}
        .eyebrow{font-size:11px;font-weight:750;letter-spacing:.14em;color:#6E7B8F;text-transform:uppercase}
        .market-call{font-size:42px;font-weight:800;letter-spacing:-.04em;margin:10px 0 3px}
        .positive{color:#20D69B}.negative{color:#FF647C}.neutral{color:#F5C76B}
        .market-copy{color:#AAB4C2;font-size:15px;line-height:1.55;max-width:620px}
        .metric-row{display:flex;gap:28px;margin-top:24px}
        .metric-label{font-size:11px;color:#697588}.metric-value{font:700 16px ui-monospace,SFMono-Regular,Menlo,monospace;margin-top:4px}
        .section-title{font-size:18px;font-weight:750;letter-spacing:-.015em;margin:26px 0 12px}
        .signal{display:grid;grid-template-columns:74px 112px 120px 1fr 120px;align-items:center;gap:12px;
          background:#10151D;border:1px solid #1D2632;border-radius:14px;padding:15px 18px;margin-bottom:9px}
        .ticker{font-size:17px;font-weight:800;letter-spacing:.02em}
        .badge{display:inline-flex;width:92px;justify-content:center;border-radius:7px;padding:5px 0;font-size:11px;font-weight:850}
        .buy{background:rgba(32,214,155,.12);color:#20D69B}.sell{background:rgba(255,100,124,.13);color:#FF647C}
        .hold{background:rgba(139,152,170,.12);color:#9AA6B7}
        .price{font:650 13px ui-monospace,SFMono-Regular,Menlo,monospace;color:#D8DEE8}
        .decision-note{font-size:12px;color:#778397;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        .confidence{text-align:right;font-size:12px;color:#9BA7B8}
        .risk{border-left:3px solid #F5C76B;background:#12171F;border-radius:8px;padding:12px 14px;margin:9px 0;color:#C8D0DB;font-size:13px}
        .risk strong{color:#F5C76B;margin-right:8px}
        .empty{color:#6F7B8C;text-align:center;padding:34px;border:1px dashed #27313E;border-radius:14px}
        .stButton>button{height:44px;border-radius:10px;border:1px solid #2A3543;background:#131A23;color:#E7ECF3;font-weight:750}
        .stButton>button:hover{border-color:#20D69B;color:#20D69B;background:#121B20}
        .stButton>button[kind="primary"]{background:#20D69B;color:#07110E;border-color:#20D69B}
        .backtest{background:#10151D;border:1px solid #202A36;border-radius:12px;padding:14px;margin-top:12px;color:#AEB8C6}
        @media(max-width:800px){.signal{grid-template-columns:64px 72px 1fr}.price,.decision-note{display:none}.metric-row{gap:15px}.market-call{font-size:34px}}
        </style>
        """,
        unsafe_allow_html=True,
    )

    state_path = PROJECT_ROOT / "northstar" / "data" / "system_state.json"
    state = _load_json(state_path, {})
    if not isinstance(state, dict):
        state = {}

    st.markdown('<div class="brand">✦ 北极星</div>', unsafe_allow_html=True)
    st.markdown('<div class="headline">今日交易决策</div>', unsafe_allow_html=True)

    action_1, action_2, action_3, action_4, spacer = st.columns(
        [1.25, 1.25, 1.2, 1.45, 2.2]
    )
    with action_1:
        generate_clicked = st.button(
            "▶ 生成今日信号",
            type="primary",
            use_container_width=True,
        )
    with action_2:
        refresh_clicked = st.button("🔄 刷新市场数据", use_container_width=True)
    with action_3:
        backtest_clicked = st.button("📊 回测最近5日", use_container_width=True)
    with action_4:
        health_clicked = st.button("🧠 查看策略健康状态", use_container_width=True)

    if (
        "decision_snapshot" not in st.session_state
        or generate_clicked
        or refresh_clicked
    ):
        with st.spinner("正在读取市场并生成决策…"):
            st.session_state.decision_snapshot = _generate_decisions(
                state,
                refresh_market_data=refresh_clicked,
            )
    if backtest_clicked:
        st.session_state.backtest_summary = _run_backtest_summary()
    if health_clicked:
        st.session_state.show_strategy_health = not st.session_state.get(
            "show_strategy_health",
            False,
        )

    snapshot = st.session_state.decision_snapshot
    context = snapshot.get("market_context", {})
    signals = snapshot.get("signals", [])
    quotes = snapshot.get("quotes", {})
    conclusion, market_description, tone = _market_copy(context)
    volatility = float(context.get("volatility", 0.0) or 0.0)
    trend = {
        "up": "向上",
        "down": "向下",
        "sideways": "震荡",
    }.get(str(context.get("SPY_trend", "sideways")).lower(), "震荡")
    market_state, risk_level, today_advice = _market_labels(context)

    st.markdown(
        f'<div class="timestamp">行情更新于 {html.escape(snapshot.get("generated_at", "—"))}</div>',
        unsafe_allow_html=True,
    )

    market_col, risk_col = st.columns([1.75, 1])
    with market_col:
        st.markdown(
            f"""
            <div class="panel">
              <div class="eyebrow">📊 今日市场结论</div>
              <div class="market-call {tone}">{conclusion}</div>
              <div class="market-copy">{html.escape(market_description)}</div>
              <div class="metric-row">
                <div><div class="metric-label">市场状态</div><div class="metric-value">{market_state}</div></div>
                <div><div class="metric-label">风险等级</div><div class="metric-value">{risk_level}</div></div>
                <div><div class="metric-label">今日建议</div><div class="metric-value">{today_advice}</div></div>
                <div><div class="metric-label">SPY 趋势</div><div class="metric-value">{html.escape(trend)}</div></div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with risk_col:
        risk_markup = "".join(
            f'<div class="risk"><strong>{html.escape(level)}</strong>{html.escape(message)}</div>'
            for level, message in _risk_messages(context, signals)
        )
        st.markdown(
            f'<div class="panel"><div class="eyebrow">⚠ 风险提示</div>{risk_markup}</div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div class="section-title">今日交易信号</div>', unsafe_allow_html=True)
    if not signals:
        st.markdown('<div class="empty">当前没有交易候选</div>', unsafe_allow_html=True)
    else:
        for item in signals:
            symbol = str(item.get("symbol", "—"))
            action = str(item.get("final_action", "HOLD")).upper()
            action_class = action.lower() if action in {"BUY", "SELL", "HOLD"} else "hold"
            action_text = {
                "BUY": "建议买入",
                "SELL": "建议卖出",
                "HOLD": "建议观望",
            }.get(action, "建议观望")
            confidence = float(item.get("confidence", 0.0) or 0.0)
            sizing = float(item.get("position_sizing", 0.0) or 0.0)
            price = float(quotes.get(symbol, 0.0) or 0.0)
            reasons = item.get("blocked_reasons", [])
            note = _human_signal_reason(action, reasons)
            sizing_text = f"仓位 {sizing:.0%}" if action == "BUY" else "无需新增仓位"
            st.markdown(
                f"""
                <div class="signal">
                  <div class="ticker">{html.escape(symbol)}</div>
                  <div><span class="badge {action_class}">{action_text}</span></div>
                  <div class="price">${price:,.2f}</div>
                  <div class="decision-note">理由：{html.escape(note)}</div>
                  <div class="confidence">{confidence:.0%} · {sizing_text}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    if st.session_state.get("show_strategy_health"):
        guarded_count = sum(
            1 for item in signals if item.get("blocked_reasons")
        )
        if volatility > 0.30 or guarded_count > max(len(signals) // 2, 1):
            health_text = "需要关注：市场风险较高，多个交易建议已被风控拦截。"
        else:
            health_text = "状态稳定：当前决策规则运行正常，未发现明显异常。"
        st.markdown(
            f'<div class="backtest">策略健康状态：{health_text}</div>',
            unsafe_allow_html=True,
        )

    if "backtest_summary" in st.session_state:
        summary = st.session_state.backtest_summary
        if summary["trade_count"]:
            st.markdown(
                f'<div class="backtest">历史验证：收益 {summary["total_return"]:.2f}% · '
                f'胜率 {summary["win_rate"]:.0%} · {summary["trade_count"]} 笔记录</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="backtest">暂无足够的历史交易记录用于回测。</div>',
                unsafe_allow_html=True,
            )


if __name__ == "__main__":
    run()
