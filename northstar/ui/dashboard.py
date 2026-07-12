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
DAILY_REPORT_DIR = PROJECT_ROOT / "reports" / "daily_decision"
DEMO_DATA_NOTICE = "DEMO/历史固定样例：不得用于正式投资建议或持仓估值。"


def _load_state() -> dict[str, Any] | None:
    state_path = PROJECT_ROOT / "northstar" / "data" / "system_state.json"
    try:
        with open(state_path, encoding="utf-8") as source:
            state = json.load(source)
        return state if isinstance(state, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def load_latest_daily_decision_report(
    report_dir: str | Path = DAILY_REPORT_DIR,
) -> dict[str, Any] | None:
    """Read, validate and return the newest saved report without generating data."""
    from northstar.data.market_snapshot import MarketSnapshot
    from northstar.data.portfolio_snapshot import PortfolioSnapshot

    directory = Path(report_dir)
    candidates = sorted(directory.glob("daily_decision_*.json"), reverse=True)
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                continue
            snapshot_payload = payload.get("market_snapshot")
            if not isinstance(snapshot_payload, dict):
                continue
            snapshot = MarketSnapshot.from_dict(snapshot_payload)
            if payload.get("snapshot_id") != snapshot.snapshot_id:
                continue
            portfolio_payload = payload.get("portfolio_snapshot")
            if not isinstance(portfolio_payload, dict):
                continue
            portfolio_snapshot = PortfolioSnapshot.from_dict(portfolio_payload)
            if (
                portfolio_snapshot.market_snapshot_id != snapshot.snapshot_id
                or payload.get("portfolio_snapshot_id") != portfolio_snapshot.portfolio_snapshot_id
            ):
                continue
            payload["_json_path"] = str(path)
            payload.setdefault("_md_path", str(path.with_suffix(".md")))
            return payload
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return None


def _report_is_formal_decision_safe(report: dict[str, Any]) -> bool:
    quality = report.get("data_quality", {})
    issue_counts = quality.get("issue_counts", {}) if isinstance(quality, dict) else {}
    return (
        report.get("recommendation_status") == "OK"
        and not any(
            int(issue_counts.get(kind, 0) or 0) > 0
            for kind in ("stale", "missing", "error", "mock")
        )
    )


def _portfolio_display_model(report: dict[str, Any]) -> dict[str, Any]:
    """Return already-calculated portfolio fields; never perform valuation in UI."""
    payload = report.get("portfolio_snapshot")
    if not isinstance(payload, dict):
        return {
            "valuation_status": "error",
            "warning": "缺少统一 PortfolioSnapshot，禁止展示资产总值。",
            "show_totals": False,
            "positions": [],
            "missing_symbols": [],
        }
    status = str(payload.get("valuation_status") or "error")
    show_totals = status in {"complete", "no_positions"}
    return {
        "portfolio_snapshot_id": payload.get("portfolio_snapshot_id"),
        "market_snapshot_id": payload.get("market_snapshot_id"),
        "generated_at": payload.get("generated_at"),
        "valuation_status": status,
        "coverage_ratio": float(payload.get("coverage_ratio", 0.0) or 0.0),
        "missing_symbols": list(payload.get("missing_symbols") or []),
        "cash": payload.get("cash"),
        "base_currency": payload.get("base_currency"),
        "total_market_value": payload.get("total_market_value") if show_totals else None,
        "total_unrealized_pnl": payload.get("total_unrealized_pnl") if show_totals else None,
        "total_asset_value": payload.get("total_asset_value") if show_totals else None,
        "partial_market_value": payload.get("partial_market_value"),
        "show_totals": show_totals,
        "positions": list(payload.get("positions") or []),
        "warning": "" if show_totals else "持仓估值不完整；总市值、总盈亏和总资产已隐藏。",
    }


def _portfolio_engine_from_state(state: dict[str, Any]):
    from northstar.engine.portfolio_engine import PortfolioEngine

    if "cash" not in state or not isinstance(state.get("positions"), list):
        raise ValueError("system_state lacks explicit cash/positions; defaults are forbidden")
    engine = PortfolioEngine(
        initial_cash=float(state["cash"]),
        mode="paper",
    )
    positions = state["positions"]

    for position in positions:
        if not isinstance(position, dict):
            continue
        symbol = str(position.get("symbol", "")).strip().upper()
        raw_quantity = position.get("qty", position.get("shares"))
        raw_cost = position.get("avg_cost", position.get("avg_price"))
        if raw_quantity is None or raw_cost is None:
            raise ValueError(f"system_state position {symbol or '?'} lacks quantity/average_cost")
        quantity = float(raw_quantity)
        if not symbol or quantity <= 0.0:
            continue
        engine.positions[symbol] = quantity
        engine.avg_cost[symbol] = float(raw_cost)
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


def _generate_decisions(
    state: dict[str, Any],
    snapshot: Any,
) -> dict[str, Any]:
    from northstar.data.market_snapshot import MarketSnapshot, SnapshotMarketDataProvider
    from northstar.engine.daily_signal_engine import generate_daily_signals
    from northstar.engine.execution_guard import guard_execution
    from northstar.engine.signal_recalibration import recalibrate_signals

    if not isinstance(snapshot, MarketSnapshot):
        raise TypeError("a validated MarketSnapshot is required")
    provider = SnapshotMarketDataProvider(snapshot)
    market_context = provider.get_market_context()
    portfolio_engine = _portfolio_engine_from_state(state)
    portfolio_snapshot = portfolio_engine.get_snapshot()

    if state.get("total_equity"):
        portfolio_snapshot["total_value"] = float(state["total_equity"])
        if "position_market_value" not in state or "cash" not in state:
            raise ValueError("system_state totals are incomplete")
        portfolio_snapshot["position_value"] = float(state["position_market_value"])
        portfolio_snapshot["cash"] = float(state["cash"])

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


def _generate_holdings_for_dashboard(manual_items: tuple[tuple[str, str], ...]):
    """Cache-safe boundary: serializable manual valuation inputs only."""
    from decimal import Decimal
    from northstar.engine.holdings_decision_engine import generate_holdings_decisions

    manual = {symbol: Decimal(value) for symbol, value in manual_items}
    return generate_holdings_decisions(manual_prices=manual)


def run() -> None:
    import streamlit as st

    st.set_page_config(
        page_title="今日交易建议",
        page_icon="✦",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    # ── CSS 样式（全部用 st.markdown + unsafe_allow_html） ──
    st.markdown("""
<style>
:root{color-scheme:dark}
.stApp,[data-testid="stAppViewContainer"]{background:#080B10;color:#F4F7FB}
[data-testid="stHeader"]{background:rgba(8,11,16,.92)}
[data-testid="stMainBlockContainer"]{max-width:1050px;padding:2.5rem 2rem 4rem}
[data-testid="stSidebar"],#MainMenu,footer{display:none!important}
.block{background:linear-gradient(145deg,#121821,#0D1219);border:1px solid #202936;border-radius:20px;padding:24px 26px;margin-bottom:18px;box-shadow:0 18px 45px rgba(0,0,0,.2)}
.label{font-size:13px;font-weight:750;color:#8793A5;letter-spacing:.08em;margin-bottom:12px}
.one-line{font-size:48px;font-weight:850;letter-spacing:-.05em;color:#F5C76B}
.signal-row{display:grid;grid-template-columns:1fr 130px 120px;align-items:center;border-top:1px solid #202936;padding:16px 4px}
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
</style>""", unsafe_allow_html=True)

    report = load_latest_daily_decision_report()
    if report is None:
        st.warning("未找到每日决策快照，持仓操作建议仍将尝试生成。")
        # 即使没有每日决策报告，仍然保留首页的持仓、日报状态与建议复盘入口。
        _render_holdings_decisions(st)
        _render_daily_decision_report_block(st, None)
        _render_recommendation_review(st)
        return

    unsafe_market_data = not _report_is_formal_decision_safe(report)
    top5 = report.get("top5_opportunity", []) if not unsafe_market_data else []
    signals = [row for row in top5 if isinstance(row, dict)]
    today_action = report.get("overall_conclusion", "观望") if not unsafe_market_data else "数据不足，禁止生成正式建议"
    risk_level = "未知" if unsafe_market_data else "以快照报告为准"
    full_position = "否" if unsafe_market_data else "不由本页面自动判断"

    snapshot_id = html.escape(str(report.get("snapshot_id", "—")))
    generated_at = html.escape(str(report.get("generated_at", "—")))
    sources = report.get("provider_summary", {})
    source_text = html.escape(", ".join(f"{key}:{value}" for key, value in sources.items()) or "—")
    coverage = float(report.get("coverage_ratio", 0.0) or 0.0)
    st.caption(
        f"快照 {snapshot_id} · 生成时间 {generated_at} · 覆盖率 {coverage:.1%} · 来源 {source_text}"
    )
    if unsafe_market_data:
        st.warning("行情快照未通过正式建议门槛；本页仅展示数据质量，不展示买卖信号。")

    # ── 我的持仓操作建议（首页顶部；正式行情不足时明确阻断） ──
    _render_holdings_decisions(st)

    _render_portfolio_snapshot_block(st, report)

    # ── 今日一句话策略 ──
    st.markdown(f"""
    <div class="block">
      <div class="label">今日一句话策略</div>
      <div class="one-line">{today_action}</div>
    </div>
    """, unsafe_allow_html=True)

    # ── 股票操作列表 ──
    rows = []
    for signal in signals:
        symbol = html.escape(str(signal.get("symbol", "—")))
        action, sizing, style = "关注", "—", "hold"
        rows.append(f"""
        <div class="signal-row">
          <div class="symbol">{symbol}</div>
          <div class="action {style}">{action}</div>
          <div class="size"><small>仓位</small>{sizing}</div>
        </div>""")
    if not rows:
        rows.append('<div class="signal-row"><div class="symbol">—</div><div class="action hold">观望</div><div class="size"><small>仓位</small>—</div></div>')

    st.markdown(f"""
    <div class="block">
      <div class="label">股票操作列表</div>
      {"".join(rows)}
    </div>
    """, unsafe_allow_html=True)

    # ── 风险提示 ──
    st.markdown(f"""
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
    """, unsafe_allow_html=True)

    # ── 每日决策报告 ──
    _render_daily_decision_report_block(st, report)

    # ── 历史建议复盘（保留原首页核心能力） ──
    _render_recommendation_review(st)


def _render_recommendation_review(st: Any) -> None:
    """Wire the existing review module without creating a second Dashboard."""
    try:
        from northstar.data import recommendation_review as rr
        from northstar.data import recommendation_review_snapshot as rs
        from northstar.data import recommendation_store as store
        from northstar.ui.dashboard_review import render_recommendation_review_section

        all_recs = store.get_all_recommendations()
        render_recommendation_review_section(
            st, st.session_state, [], [], all_recs,
            store.get_all_recommendations, store.list_recommendations,
            store.add_recommendation, store.update_recommendation_review,
            rs.save_recommendation_review_snapshot,
            rs.get_latest_recommendation_review_snapshot,
            rs.get_recommendation_review_snapshot_history,
            rs.get_recommendation_review_snapshot_trend,
            rs.generate_recommendation_review_trend_summary,
            rs.load_recommendation_review_snapshots,
            rr.review_recommendations, rr.classify_recommendation_review_result,
            rr.classify_recommendation_failure_reason,
            rr.build_failure_reason_summary,
            rr.build_recommendation_review_quality_explanation,
            rr.get_recommendation_review_stats,
            rr.get_recommendation_symbol_stats,
            rr.get_recommendation_action_stats,
            rr.get_recommendation_horizon_stats,
            rr.get_recommendation_review_data_health,
            rr.generate_recommendation_review_summary,
            rr.format_change_pct, rr.format_change,
            rs.compute_grade_stats_from_overall,
        )
    except Exception as exc:
        st.caption(f"建议复盘暂不可用: {exc}")


def _render_portfolio_snapshot_block(st: Any, report: dict[str, Any]) -> None:
    """Render the immutable PortfolioSnapshot without recalculating any totals."""
    model = _portfolio_display_model(report)
    st.markdown("### 持仓与资产估值")
    st.caption(
        f"PortfolioSnapshot {model.get('portfolio_snapshot_id') or '—'} · "
        f"MarketSnapshot {model.get('market_snapshot_id') or '—'} · "
        f"估值时间 {model.get('generated_at') or '—'} · "
        f"状态 {model['valuation_status']} · 覆盖率 {model.get('coverage_ratio', 0.0):.1%}"
    )
    if model.get("warning"):
        st.warning(model["warning"])
    if model.get("missing_symbols"):
        st.error("缺失或不可换算持仓：" + ", ".join(model["missing_symbols"]))

    positions = model.get("positions", [])
    if positions:
        rows = [
            {
                "股票": row.get("symbol"),
                "数量": row.get("quantity"),
                "成本价": row.get("average_cost"),
                "当前价": row.get("current_price"),
                "行情来源": row.get("price_source"),
                "行情时间": row.get("price_as_of"),
                "市值": row.get("market_value"),
                "未实现盈亏": row.get("unrealized_pnl"),
                "收益率%": row.get("unrealized_pnl_percent"),
                "估值状态": row.get("valuation_status"),
            }
            for row in positions
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)

    if model.get("show_totals"):
        columns = st.columns(4)
        currency = model.get("base_currency") or ""
        columns[0].metric("现金", f"{model.get('cash')} {currency}")
        columns[1].metric("持仓总市值", f"{model.get('total_market_value')} {currency}")
        columns[2].metric("总未实现盈亏", f"{model.get('total_unrealized_pnl')} {currency}")
        columns[3].metric("总资产", f"{model.get('total_asset_value')} {currency}")
    elif model.get("partial_market_value") is not None:
        st.caption(f"部分已定价市值（非总值）：{model['partial_market_value']} {model.get('base_currency') or ''}")


def _render_daily_decision_report_block(
    st: Any,
    result: dict[str, Any] | None = None,
) -> None:
    """渲染每日决策报告中文区域。"""
    try:
        result = result or load_latest_daily_decision_report()
        if result is None or "error" in result:
            st.caption("⚠ 每日决策报告暂不可用")
            return

        overview = result.get("overview", {})
        safe = _report_is_formal_decision_safe(result)
        top5_opp = result.get("top5_opportunity", []) if safe else []
        top5_risk = result.get("top5_risk", []) if safe else []
        conclusion = result.get("overall_conclusion", "")
        md_path = result.get("_md_path", "")

        st.markdown(f"""
        <div class="block">
          <div class="label">📋 每日决策报告</div>
          <div style="font-size:14px;font-weight:600;color:#F5C76B;margin-bottom:12px">最新报告日期: {overview.get("当前日期", "—")}</div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px">
            <div style="background:#10151D;border:1px solid #202936;border-radius:13px;padding:14px">
              <div style="font-size:12px;color:#758195">观察池数量</div>
              <div style="font-size:22px;font-weight:850;margin-top:4px">{overview.get("观察池股票数量", "—")}</div>
            </div>
            <div style="background:#10151D;border:1px solid #202936;border-radius:13px;padding:14px">
              <div style="font-size:12px;color:#758195">数据更新时间</div>
              <div style="font-size:22px;font-weight:850;margin-top:4px">{overview.get("数据更新时间", "—")}</div>
            </div>
          </div>
          <div style="margin-bottom:10px">
            <div style="font-size:13px;font-weight:750;color:#8793A5;margin-bottom:6px">🟢 Top 5 机会</div>
            <div style="font-size:13px;color:#20D69B">{" | ".join(s["symbol"] for s in top5_opp[:5]) if top5_opp else "暂无数据"}</div>
          </div>
          <div style="margin-bottom:10px">
            <div style="font-size:13px;font-weight:750;color:#8793A5;margin-bottom:6px">🔴 Top 5 风险</div>
            <div style="font-size:13px;color:#FF647C">{" | ".join(s["symbol"] for s in top5_risk[:5]) if top5_risk else "暂无数据"}</div>
          </div>
          <div style="margin-bottom:10px">
            <div style="font-size:13px;font-weight:750;color:#8793A5;margin-bottom:6px">💡 今日一句话结论</div>
            <div style="font-size:16px;font-weight:800;color:#F5C76B">{conclusion}</div>
          </div>
          <div style="font-size:12px;color:#6F7A8B;margin-top:10px">报告路径: <code>{md_path}</code></div>
        </div>
        """, unsafe_allow_html=True)
    except Exception as exc:
        st.caption(f"每日决策报告暂不可用: {exc}")


def render_market_intelligence(st: Any) -> None:
    """Render an explicitly isolated demo based on fixed historical samples."""
    try:
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
        with st.expander("DEMO · 📊 历史固定样例市场洞察", expanded=False):
            st.warning(DEMO_DATA_NOTICE)
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
    """Render an explicitly isolated paper-trading demo."""
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
        with st.expander("DEMO · 💰 历史固定样例模拟交易", expanded=False):
            st.warning(DEMO_DATA_NOTICE)
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
            engine = PaperTradingEngine(initial_capital=100000.0)
            rm = RiskManager(initial_capital=100000.0)
            engine.execute_signals(signals, price_data)
            report = engine.get_report()
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
            score = evaluate_system_performance(report, None, metrics)
            grade_icon = {"A": "🟢", "B": "🟡", "C": "🟠", "D": "🔴"}.get(score["grade"], "⚪")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("等级", f"{grade_icon} {score['grade']}")
            c2.metric("总评分", f"{score['total_score']:.0f}")
            c3.metric("收益评分", f"{score['return_score']:.0f}")
            c4.metric("稳定性评分", f"{score['stability_score']:.0f}")
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
        with st.expander("🧭 滚动验证面板", expanded=False):
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
            st.caption("滚动验证仅基于历史数据滚动回测，不构成投资建议")
    except Exception as exc:
        st.caption(f"滚动验证暂不可用: {exc}")


def render_governance_panel(st: Any) -> None:
    """渲染策略治理与系统收敛面板。"""
    try:
        from northstar.governance.strategy_governance_engine import StrategyGovernanceEngine
        with st.expander("🧭 策略治理与系统收敛面板", expanded=False):
            engine = StrategyGovernanceEngine()
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
        with st.expander("🧠 北极星系统控制面板", expanded=False):
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
        with st.expander("🌍 执行现实层", expanded=False):
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


def render_shadow_trading_panel(st: Any) -> None:
    """渲染影子实盘控制面板。"""
    try:
        from northstar.shadow.shadow_trading_engine import ShadowTradingEngine
        with st.expander("🧪 影子交易验证控制面板", expanded=False):
            shadow = ShadowTradingEngine()
            report = shadow.run_shadow_cycle()
            paper = report.get("paper_return", 0)
            shadow_ret = report.get("shadow_return", 0)
            gap = report.get("execution_gap", 0)
            drift = report.get("drift_detected", False)
            consistency = report.get("consistency_score", 0)
            risk_align = report.get("risk_alignment", True)
            status = "stable" if consistency > 80 else ("warning" if consistency > 50 else "unstable")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Paper 收益", f"{paper:+.2f}%")
            c2.metric("Shadow 收益", f"{shadow_ret:+.2f}%")
            c3.metric("执行差距", f"{gap:+.2f}%")
            c4.metric("漂移检测", "⚠️ 是" if drift else "✅ 否")
            st.metric("一致性评分", f"{consistency:.0f}/100 ({status.upper()})")
            st.metric("风险对齐", "✅" if risk_align else "❌")
            if drift:
                st.warning("**漂移原因**")
                for r in report.get("drift_reasons", []):
                    st.markdown(f"- {r}")
            st.caption("影子交易验证仅模拟实时市场运行，不执行真实交易")
    except Exception as exc:
        st.caption(f"影子交易暂不可用: {exc}")


def render_market_calibration_panel(st: Any) -> None:
    """渲染市场现实校准面板。"""
    try:
        from northstar.calibration.market_calibration_engine import MarketCalibrationEngine
        with st.expander("🌍 市场校准控制面板", expanded=False):
            mce = MarketCalibrationEngine()
            report = mce.calibration_cycle({"real_return": 2.0}, {"shadow_return": 1.8}, {"paper_return": 2.5})
            alignment = report.get("reality_alignment_score", 0)
            bias = report.get("bias_detection", {})
            drift = report.get("drift_detected", False)
            health = report.get("system_health", "?")
            cm = report.get("adjustments", {}).get("confidence_multiplier", 1.0)
            health_icon = {"calibrated": "🟢", "needs_recalibration": "🟡", "misaligned": "🔴"}.get(health, "⚪")
            aligned = "Aligned" if alignment > 80 else ("Partially Misaligned" if alignment > 50 else "Misaligned")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("对齐评分", f"{alignment:.0f}")
            c2.metric("系统健康", f"{health_icon} {health}")
            c3.metric("置信度系数", f"{cm:.2f}")
            c4.metric("漂移检测", "⚠️ 是" if drift else "✅ 否")
            st.markdown("**偏差检测**")
            st.markdown(f"- 乐观偏差: {bias.get('optimism_bias', 0):+.2f}%")
            st.markdown(f"- 执行偏差: {bias.get('execution_bias', 0):+.2f}%")
            st.markdown(f"- 时序偏差: {bias.get('timing_bias', 0):+.2f}%")
            st.metric(f"系统状态: **{aligned}**")
            st.caption("市场校准层对比真实市场数据，不构成投资建议")
    except Exception as exc:
        st.caption(f"市场校准暂不可用: {exc}")


def render_reality_transition_panel(st: Any) -> None:
    """渲染现实迁移控制面板。"""
    try:
        from northstar.reality_transition.reality_transition_engine import RealityTransitionEngine
        with st.expander("🌐 现实过渡控制面板 (v2)", expanded=False):
            rte = RealityTransitionEngine()
            report = rte.run_reality_mirror_cycle()
            rmai = report.get("rmai_score", 0)
            shadow_corr = report.get("shadow_vs_live_correlation", 0)
            paper_corr = report.get("paper_vs_live_correlation", 0)
            exec_acc = report.get("execution_accuracy", 0)
            breakdown = report.get("breakdown_detected", False)
            readiness = report.get("capital_readiness", {})
            phase = readiness.get("recommended_phase", "shadow")
            ks = report.get("kill_switch", {})
            stress = report.get("stress_test", {})
            wfv = report.get("walk_forward", {})
            micro = report.get("micro_live_sandbox", {})
            rmai_status = "🟢 Highly Aligned" if rmai > 85 else ("🟡 Partially Aligned" if rmai > 60 else "🔴 Misaligned")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("RMAI", f"{rmai:.0f}")
            c2.metric("Shadow 对齐", f"{shadow_corr:.0%}")
            c3.metric("Paper 对齐", f"{paper_corr:.0%}")
            c4.metric("执行准确率", f"{exec_acc:.0%}")
            st.markdown(f"**系统状态**: {rmai_status}")
            st.markdown(f"**崩溃检测**: {'⚠️ 是' if breakdown else '✅ 否'} ({report.get('consecutive_breakdown_days', 0)}天)")
            st.markdown(f"**资金部署**: {readiness.get('status', '?')} (置信度{readiness.get('confidence', 0):.0%})")
            st.markdown(f"**推荐阶段**: {phase} | **最大安全资金**: {readiness.get('max_safe_capital_pct', 0):.0%}")
            st.markdown(f"**Kill Switch**: {'🔴 激活' if ks.get('kill_switch_active') else '✅ 正常'}")
            if breakdown:
                st.error(f"崩溃类型: {report.get('breakdown_type', '?')}")
            st.markdown("**🌍 市场状态 (v3)**")
            st.markdown(f"- 当前regime: **{report.get('current_regime', '?')}** (置信度{report.get('regime_confidence', 0):.0%})")
            st.markdown(f"- 切换概率: {report.get('regime_switch_probability', 0):.0%}")
            st.markdown(f"- 动态RMAI: {report.get('dynamic_rmai', 0):.0f} (乘数{report.get('rmai_multiplier', 0):.2f})")
            st.markdown(f"- 信号分配: {report.get('regime_adjusted_allocation_signal', 0):.0f}/100")
            st.markdown("**🧪 压力测试**")
            st.markdown(f"- RMAI波动率: {stress.get('rmai_volatility', 0):.1f}")
            st.markdown(f"- Breakdown频率: {stress.get('breakdown_trigger_frequency', 0):.0%}")
            st.markdown(f"- 误放行率: {stress.get('false_go_rate', 0):.2%} | 误杀率: {stress.get('false_no_go_rate', 0):.2%}")
            st.markdown("**📊 滚动验证**")
            st.markdown(f"- 稳定性: {wfv.get('stability_score', 0):.0f} | Regime敏感: {wfv.get('regime_sensitivity', '?')}")
            st.markdown(f"- 窗口数: {wfv.get('windows_analyzed', 0)} | 对齐漂移: {wfv.get('avg_alignment_drift', 0):.1f}")
            st.markdown("**🔬 微额实盘沙盒**")
            st.markdown(f"- 操作: {micro.get('action', '?')} | PnL: ${micro.get('pnl', 0):,.0f}")
            st.markdown(f"- 滑点: {micro.get('slippage_pct', 0):.3f}% | 延迟: {micro.get('delay_ms', 0):.0f}ms")
            st.markdown(f"- RMAI修正: {micro.get('rmai_corrected', 0):.0f} | PnL对齐: {micro.get('pnl_alignment', 0):.2f}")
            st.caption("现实过渡层v3 — 市场状态感知 + 动态RMAI + stress/walk-forward/micro-live 闭环")
    except Exception as exc:
        st.caption(f"现实过渡暂不可用: {exc}")


def _render_holdings_decisions(st: Any) -> None:
    """Render the holdings decision cards section.

    Generates decisions from the real portfolio + market data,
    and renders them using holdings_decision_ui.
    Includes manual broker price input for when market data is unavailable.
    Errors are reported inline; never blocks the rest of the dashboard.
    """
    from decimal import Decimal, InvalidOperation

    # ── 人工输入券商当前价格入口 ──
    # 仅当行情接口不可用时使用（source=manual_broker_input）
    st.markdown("**📝 人工输入券商当前价格**（仅在行情接口故障时使用）")
    st.caption(
        "此入口仅用于数据接口故障时估算当前市值、盈亏和仓位比例。"
        "人工价格不会进入历史 K 线、MA、ATR、支撑阻力、止损、目标价或建议数量计算。"
        "人工价格仅用于账户估值，不构成完整交易建议。"
    )
    col_nvda, col_sofi, col_spcx = st.columns(3)
    manual_prices: dict[str, Decimal | None] = {}
    for col, sym, label in [(col_nvda, "NVDA", "NVDA"), (col_sofi, "SOFI", "SOFI"), (col_spcx, "SPCX", "SPCX")]:
        with col:
            val = st.text_input(f"{label} 当前价格 (USD)", key=f"manual_price_{sym}", value="", placeholder="例如 120.50")
            if val.strip():
                try:
                    manual_prices[sym] = Decimal(val.strip())
                except InvalidOperation:
                    st.caption(f"⚠ {sym}: 无效数字格式")

    try:
        from northstar.ui.holdings_decision_ui import render_holdings_decision_cards

        cached_generate = st.cache_data(ttl=60, show_spinner=False)(_generate_holdings_for_dashboard)
        manual_items = tuple(sorted(
            (symbol, str(value)) for symbol, value in manual_prices.items() if value is not None
        ))
        decisions, summary = cached_generate(manual_items)

        st.caption(
            f"持仓决策生成时间: {summary.get('generated_at', '?')} | "
            f"交易时段: {'是' if summary.get('is_market_hours') else '否'} | "
            f"持仓数: {summary.get('position_count', 0)}"
        )
        render_holdings_decision_cards(st, decisions)
    except Exception as exc:
        st.error(f"持仓决策生成失败: {exc}")


if __name__ == "__main__":
    run()
