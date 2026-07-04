#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""北极星投资系统仪表盘 — Streamlit UI

唯一启动方式：streamlit run northstar/ui/dashboard.py

原则：
  - UI 不直接调用任何引擎模块
  - UI 只读取 JSON 数据文件（由 backend.py 持续写入）
  - 自动刷新（每 3 秒）
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def run() -> None:
    import streamlit as st
    import json
    import pandas as pd

    st.set_page_config(
        page_title="北极星",
        page_icon="▦",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    # ── 3 秒自动刷新 ──
    st_ar = getattr(st, "autorefresh", None)
    if st_ar:
        st_ar(interval=3000, key="ns_ar")

    # ── 数据路径 ──
    STATE = PROJECT_ROOT / "northstar" / "data" / "system_state.json"
    TRADES = PROJECT_ROOT / "northstar" / "data" / "trade_history.json"
    CURVE = PROJECT_ROOT / "northstar" / "data" / "equity_curve.json"

    def _lj(p: Path) -> Any:
        if p.exists():
            try:
                with open(p, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    # ── CSS ──
    st.markdown("""
    <style>
    .stApp{background:#F8FAFC;color:#1E293B}
    [data-testid="stAppViewContainer"]{background:#F8FAFC}
    [data-testid="stHeader"]{background:rgba(248,250,252,0.95)}
    [data-testid="stMainBlockContainer"]{padding-top:0.8rem;max-width:1200px;margin:0 auto}
    h1{color:#0F172A!important;font-weight:700!important;font-size:22px!important}
    .mt{font:700 11px Inter,sans-serif;color:#64748B;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;padding-bottom:5px;border-bottom:1px solid #E2E8F0}
    .cd{background:#FFF;border:1px solid #E2E8F0;border-radius:12px;padding:14px 18px;box-shadow:0 1px 3px rgba(0,0,0,0.04);margin-bottom:10px}
    .rw{display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid #F1F5F9}
    .rw:last-child{border-bottom:none}
    .lb{color:#64748B;font-size:12px;font-weight:500}
    .vl{color:#0F172A;font-size:13px;font-weight:600;font-family:'SF Mono',Consolas,monospace}
    .ok{color:#16A34A;font-weight:600}.er{color:#DC2626;font-weight:600}
    .kr{display:flex;gap:10px;margin:6px 0}
    .kc{background:#FFF;border:1px solid #E2E8F0;border-radius:10px;padding:12px 14px;flex:1;text-align:center;box-shadow:0 1px 2px rgba(0,0,0,0.03)}
    .kl{color:#94A3B8;font-size:9px;text-transform:uppercase;letter-spacing:0.3px}
    .kv{color:#0F172A;font-size:20px;font-weight:700;margin:3px 0 0;font-family:'SF Mono',Consolas,monospace}
    .gn{color:#16A34A}.rd{color:#DC2626}.am{color:#B45309}
    .sg{background:#FFF;border:1px solid #E2E8F0;border-radius:10px;padding:9px 14px;margin-bottom:5px;display:flex;align-items:center;gap:8px;box-shadow:0 1px 2px rgba(0,0,0,0.02)}
    .sb{min-width:42px;text-align:center;padding:2px 7px;border-radius:999px;font:700 10px 'SF Mono',Consolas,monospace}
    .sbuy{background:#DCFCE7;color:#16A34A}
    .ssell{background:#FEE2E2;color:#DC2626}
    .shold{background:#F3F4F6;color:#6B7280}
    .stk{font-weight:700;color:#2563EB;min-width:44px;font-size:12px}
    .srs{color:#475569;font-size:11px;flex:1}
    .fts{color:#94A3B8;font-size:9px;min-width:60px;text-align:right}
    .ftr{text-align:center;color:#94A3B8;font-size:9px;padding:16px 0 6px;border-top:1px solid #E2E8F0;margin-top:16px}
    </style>
    """, unsafe_allow_html=True)

    st.markdown('<h1>▦ 北极星</h1>', unsafe_allow_html=True)

    # ── 读取后端数据 ──
    ss = _lj(STATE) or {}
    trades = _lj(TRADES) or []
    curve = _lj(CURVE) or []

    if not isinstance(ss, dict): ss = {}
    if not isinstance(trades, list): trades = []
    if not isinstance(curve, list): curve = []

    # ── v26: 项目状态总览 ──
    def render_project_status_overview(st_: Any, ss_: dict) -> None:
        """渲染项目状态总览区域（轻量、折叠、小白友好）。"""
        with st_.expander("🧭 北极星项目状态总览", expanded=False):
            st_.markdown("**运行状态**")
            br = ss_.get("system_health") is not None
            bs = "运行中" if br else "等待后台启动"
            c1, c2, c3, c4 = st_.columns(4)
            c1.metric("Backend", bs)
            c2.metric("UI", "运行中")
            c3.metric("数据更新时间", (ss_.get("last_run_time") or "暂无数据")[-19:] if ss_.get("last_run_time") else "暂无数据")
            c4.metric("总资产", f"${float(ss_.get('total_equity', 0)):,.2f}" if ss_.get("total_equity") else "暂无数据")
            st_.markdown("**开发状态**")
            c5, c6, c7, c8 = st_.columns(4)
            c5.metric("当前版本", "v26 项目状态总览")
            c6.metric("最新已知 commit", "9f2abcf")
            c7.metric("开发平台", "Mac")
            c8.metric("项目目录", "~/Documents/北极星")
            st_.markdown("**复盘模块完成情况**")
            modules = [("建议留痕","已完成"),("建议复盘","已完成"),("单条分级","已完成"),("分级趋势","已完成"),("复盘质量解释","已完成"),("失效原因归类","已完成"),("失效原因总览","已完成"),("模块文档","已完成")]
            mc1, mc2, mc3, mc4 = st_.columns(4)
            for i, (n, s) in enumerate(modules):
                [mc1, mc2, mc3, mc4][i % 4].metric(n, s)
            st_.markdown("**测试状态**")
            st_.metric("复盘相关测试", "73/73 通过")
            st_.caption("来自最近一次验收；每次改动需重新运行。")
            st_.markdown("**下一步建议**")
            st_.info("1️⃣ 优化项目总览（已完成）\n2️⃣ 统一 action 识别（待开发）\n3️⃣ 快照自动保存策略（待开发）\n4️⃣ 暂不做自动交易")
            st_.caption("仅用于历史复盘验证，不构成投资建议。")

    render_project_status_overview(st, ss)

    # ── 顶部说明 ──
    st.info(
        "**北极星** — AI 投资研究与建议复盘系统\n\n"
        "• 当前阶段仅做**研究、记录与复盘验证**，不执行自动交易\n"
        "• 所有建议、信号、模拟交易**仅用于复盘研究**，不构成投资建议\n"
        "• 真实买卖操作请自行判断决策"
    )

    def _money(value: Any, unavailable: str = "暂无法估值") -> str:
        if value is None:
            return unavailable
        try:
            return f"${float(value):,.2f}"
        except (TypeError, ValueError):
            return unavailable

    valuation_status = ss.get("valuation_status", "unavailable")
    valuation_text = {
        "complete": "估值完整",
        "partial": "部分持仓缺少价格",
        "unavailable": "暂无法估值",
    }.get(valuation_status, "暂无法估值")
    missing_symbols = ss.get("missing_price_symbols") or []
    if valuation_status == "partial" and missing_symbols:
        valuation_text += f"（{', '.join(missing_symbols)}）"
    valuation_time = ss.get("price_as_of") or "—"

    st.caption(f"更新于 {ss.get('last_run_time', '—')} | 迭代 {ss.get('iteration', 0)}")

    c1, c2, c3 = st.columns(3)

    # ── 模块1: 系统状态 ──
    with c1:
        st.markdown('<div class="mt">📊 系统状态</div>', unsafe_allow_html=True)
        health = ss.get("system_health", "OK")
        hc = "ok" if health == "OK" else "er"
        backend_running = ss.get("system_health") is not None
        backend_status = "运行中" if backend_running else "等待后台启动"
        backend_color = "ok" if backend_running else "am"
        st.markdown(f"""
        <div class="cd">
            <div class="rw"><span class="lb">Backend</span><span class="vl {backend_color}">{backend_status}</span></div>
            <div class="rw"><span class="lb">运行状态</span><span class="vl {hc}">{health}</span></div>
            <div class="rw"><span class="lb">最后运行</span><span class="vl">{ss.get("last_run_time","暂无数据")}</span></div>
            <div class="rw"><span class="lb">迭代次数</span><span class="vl">{ss.get("iteration",0)}</span></div>
            <div class="rw"><span class="lb">信号数</span><span class="vl">{ss.get("signals_count",0)}</span></div>
        </div>
        <div class="cd">
            <div class="rw"><span class="lb">持仓数量</span><span class="vl">{ss.get("position_count","暂无数据")}</span></div>
            <div class="rw"><span class="lb">持仓市值</span><span class="vl">{_money(ss.get("position_market_value"))}</span></div>
            <div class="rw"><span class="lb">现金</span><span class="vl">{_money(ss.get("cash"), "暂无数据")}</span></div>
            <div class="rw"><span class="lb">总资产</span><span class="vl">{_money(ss.get("total_equity"))}</span></div>
            <div class="rw"><span class="lb">未实现盈亏</span><span class="vl">{_money(ss.get("unrealized_pnl"))}</span></div>
            <div class="rw"><span class="lb">估值状态</span><span class="vl">{valuation_text}</span></div>
            <div class="rw"><span class="lb">价格时间</span><span class="vl">{valuation_time}</span></div>
        </div>
        """, unsafe_allow_html=True)

    # ── 模块2: 今日信号 ──
    with c2:
        st.markdown('<div class="mt">🎯 今日信号</div>', unsafe_allow_html=True)
        sigs = list(reversed(trades[-10:] if len(trades) > 10 else trades))
        if not sigs:
            st.markdown('<div class="cd"><span style="color:#94A3B8;font-size:12px;">暂无信号 —— 等待后台引擎生成...</span></div>', unsafe_allow_html=True)
        else:
            for s in sigs[:10]:
                act = s.get("action", "hold").upper()
                tk = s.get("symbol", "?")
                rsn = s.get("reason", "")
                ts = s.get("timestamp", "")[-5:] if s.get("timestamp") else ""
                sc = {"BUY": "sbuy", "SELL": "ssell", "HOLD": "shold"}.get(act, "shold")
                st.markdown(f'<div class="sg"><span class="sb {sc}">{act}</span><span class="stk">{tk}</span><span class="srs">{rsn}</span><span class="fts">{ts}</span></div>', unsafe_allow_html=True)

    # ── 模块3: 绩效 ──
    with c3:
        st.markdown('<div class="mt">📈 模拟绩效</div>', unsafe_allow_html=True)
        simulator_initialized = bool(ss.get("simulator_initialized", False))
        simulator_value = ss.get("simulator_value")
        simulator_pnl = ss.get("simulator_pnl")
        simulator_value_text = (
            _money(simulator_value) if simulator_initialized else "未初始化"
        )
        simulator_pnl_text = (
            _money(simulator_pnl) if simulator_initialized else "未初始化"
        )
        pnl_number = (
            float(simulator_pnl)
            if simulator_initialized and simulator_pnl is not None
            else 0.0
        )
        sc = "gn" if pnl_number > 0 else ("rd" if pnl_number < 0 else "")
        trade_count = ss.get("simulator_trade_count", 0)

        st.markdown(f"""
        <div class="kr">
            <div class="kc"><div class="kl">模拟盘资产</div><div class="kv {sc}">{simulator_value_text}</div></div>
            <div class="kc"><div class="kl">模拟盘盈亏</div><div class="kv {sc}">{simulator_pnl_text}</div></div>
            <div class="kc"><div class="kl">模拟交易</div><div class="kv">{trade_count}</div></div>
            <div class="kc"><div class="kl">迭代次数</div><div class="kv">{ss.get("iteration",0)}</div></div>
        </div>
        """, unsafe_allow_html=True)

        # ── 资金曲线图 ──
        if simulator_initialized and len(curve) >= 2:
            st.markdown('<div class="mt" style="margin-top:10px;">📈 资金曲线</div>', unsafe_allow_html=True)
            df = pd.DataFrame(curve)
            if "equity" in df.columns:
                df["equity"] = pd.to_numeric(df["equity"], errors="coerce")
                chart_data = df[["equity"]].copy()
                if "date" in df.columns:
                    chart_data.index = df["date"]
                st.line_chart(chart_data, height=200, width="stretch")
        elif not simulator_initialized:
            st.caption("模拟盘未初始化，等待后台启动…")
        else:
            st.caption("资金曲线由后台引擎持续生成...")

    # ── 建议留痕 ─────────────────────────────────────────────────────────
    st.markdown('<div class="mt" style="margin-top:20px;">💡 建议留痕</div>', unsafe_allow_html=True)

    st.caption(
        "**建议留痕**：记录系统曾经给过的建议（买入、卖出、持有、观察、风险提示），"
        "便于日后回顾和复盘验证。每条建议包含股票代码、动作、价格、置信度和理由。"
    )

    try:
        from northstar.data.recommendation_store import list_recommendations, add_recommendation

        recs = list_recommendations(limit=20)

        if not recs:
            st.markdown(
                '<div class="cd" style="text-align:center;color:#94A3B8;font-size:12px;">暂无建议记录 —— 等待系统生成第一条建议，或使用下方表单手动新增</div>',
                unsafe_allow_html=True,
            )

        for r in recs:
            act = r.get("action", "—")
            act_color = {
                "买入": "sbuy", "卖出": "ssell", "持有": "shold",
                "观察": "shold", "风险提示": "ssell",
            }.get(act, "shold")
            price_str = f"${r['price']:.2f}" if r.get("price") is not None else "—"
            conf = r.get("confidence", "—")
            status = r.get("status", "open")
            status_tag = "🔴 待验证" if status == "open" else "✅ 已验证"
            ts = r.get("created_at", "")[-8:] if r.get("created_at") else ""
            symbol = r.get("symbol", "?")
            reason = r.get("reason", "") or ""
            st.markdown(
                f'<div class="sg">'
                f'<span class="sb {act_color}">{act}</span>'
                f'<span class="stk">{symbol}</span>'
                f'<span class="srs">{price_str} · {conf} · {status_tag} · {reason}</span>'
                f'<span class="fts">{ts}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

        # ── 新增建议表单 ──
        with st.expander("✏️ 新增建议", expanded=False):
            col_a, col_b, col_c, col_d = st.columns([2, 2, 2, 4])
            with col_a:
                rec_symbol = st.text_input("股票代码", value="", key="rec_sym", placeholder="NVDA")
            with col_b:
                rec_action = st.selectbox("建议动作", ["买入", "持有", "卖出", "观察", "风险提示"], key="rec_act")
            with col_c:
                rec_price = st.number_input("当前价格 ($)", min_value=0.0, step=0.01, value=0.0, key="rec_prc")
            with col_d:
                rec_confidence = st.selectbox("置信度", ["低", "中", "高"], key="rec_conf")
            rec_reason = st.text_area("理由", value="", key="rec_reason", placeholder="简要说明建议理由...", max_chars=200)
            if st.button("💾 保存建议", type="primary", key="rec_save"):
                if not rec_symbol.strip():
                    st.warning("请输入股票代码")
                else:
                    result = add_recommendation(
                        symbol=rec_symbol,
                        action=rec_action,
                        price=rec_price if rec_price > 0 else None,
                        confidence=rec_confidence,
                        reason=rec_reason,
                    )
                    if result:
                        st.success(f"建议已保存: {rec_symbol} → {rec_action}")
                        st.rerun()
                    else:
                        st.error("保存失败，请检查输入")
    except ImportError as exc:
        st.markdown(
            f'<div class="cd" style="color:#DC2626;font-size:11px;">建议留痕模块未加载: {exc}</div>',
            unsafe_allow_html=True,
        )
    except Exception as exc:
        st.markdown(
            f'<div class="cd" style="color:#B45309;font-size:11px;">建议留痕异常: {exc}</div>',
            unsafe_allow_html=True,
        )

    # ── 建议复盘模块（已拆分到 dashboard_review.py） ──
    from northstar.ui.dashboard_review import render_recommendation_review_section
    from northstar.data.recommendation_review import (
        review_recommendations,
        format_change_pct, format_change,
        classify_recommendation_review_result,
        classify_recommendation_failure_reason,
        build_failure_reason_summary,
        build_recommendation_review_quality_explanation,
        get_recommendation_review_stats,
        get_recommendation_symbol_stats,
        get_recommendation_action_stats,
        get_recommendation_horizon_stats,
        generate_recommendation_review_summary,
        get_recommendation_review_data_health,
    )
    from northstar.data.recommendation_review_snapshot import (
        save_recommendation_review_snapshot,
        get_latest_recommendation_review_snapshot,
        get_recommendation_review_snapshot_history,
        get_recommendation_review_snapshot_trend,
        generate_recommendation_review_trend_summary,
        load_recommendation_review_snapshots,
    )
    from northstar.data.recommendation_store import (
        get_all_recommendations,
        list_recommendations,
        add_recommendation,
        update_recommendation_review,
    )

    try:
        all_recs_for_review = get_all_recommendations()
    except Exception:
        all_recs_for_review = []

    render_recommendation_review_section(
        st=st,
        ss=ss,
        trades=trades,
        curve=curve,
        all_recs=all_recs_for_review,
        get_all_recommendations_fn=get_all_recommendations,
        list_recommendations_fn=list_recommendations,
        add_recommendation_fn=add_recommendation,
        update_recommendation_review_fn=update_recommendation_review,
        save_snapshot_fn=save_recommendation_review_snapshot,
        get_latest_snapshot_fn=get_latest_recommendation_review_snapshot,
        get_snapshot_history_fn=get_recommendation_review_snapshot_history,
        get_snapshot_trend_fn=get_recommendation_review_snapshot_trend,
        generate_trend_summary_fn=generate_recommendation_review_trend_summary,
        load_snapshots_fn=load_recommendation_review_snapshots,
        review_recommendations_fn=review_recommendations,
        classify_grade_fn=classify_recommendation_review_result,
        classify_failure_fn=classify_recommendation_failure_reason,
        build_summary_fn=build_failure_reason_summary,
        build_quality_fn=build_recommendation_review_quality_explanation,
        get_stats_fn=get_recommendation_review_stats,
        get_symbol_stats_fn=get_recommendation_symbol_stats,
        get_action_stats_fn=get_recommendation_action_stats,
        get_horizon_stats_fn=get_recommendation_horizon_stats,
        get_data_health_fn=get_recommendation_review_data_health,
        generate_summary_fn=generate_recommendation_review_summary,
        format_change_pct_fn=format_change_pct,
        format_change_fn=format_change,
        compute_grade_stats_fn=None,
    )

    st.markdown('<div class="ftr">北极星 · 仅用于研究参考 · 不构成投资建议</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    run()