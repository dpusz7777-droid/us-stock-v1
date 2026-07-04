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
        st.markdown('<div class="mt">📊 System Status</div>', unsafe_allow_html=True)
        health = ss.get("system_health", "OK")
        hc = "ok" if health == "OK" else "er"
        st.markdown(f"""
        <div class="cd">
            <div class="rw"><span class="lb">系统状态</span><span class="vl {hc}">{health}</span></div>
            <div class="rw"><span class="lb">最后运行</span><span class="vl">{ss.get("last_run_time","—")}</span></div>
            <div class="rw"><span class="lb">迭代次数</span><span class="vl">{ss.get("iteration",0)}</span></div>
            <div class="rw"><span class="lb">信号数</span><span class="vl">{ss.get("signals_count",0)}</span></div>
        </div>
        <div class="cd">
            <div class="rw"><span class="lb">持仓数量</span><span class="vl">{ss.get("position_count","?")}</span></div>
            <div class="rw"><span class="lb">持仓市值</span><span class="vl">{_money(ss.get("position_market_value"))}</span></div>
            <div class="rw"><span class="lb">现金</span><span class="vl">{_money(ss.get("cash"), "未知")}</span></div>
            <div class="rw"><span class="lb">总资产</span><span class="vl">{_money(ss.get("total_equity"))}</span></div>
            <div class="rw"><span class="lb">未实现盈亏</span><span class="vl">{_money(ss.get("unrealized_pnl"))}</span></div>
            <div class="rw"><span class="lb">估值状态</span><span class="vl">{valuation_text}</span></div>
            <div class="rw"><span class="lb">价格时间</span><span class="vl">{valuation_time}</span></div>
        </div>
        """, unsafe_allow_html=True)

    # ── 模块2: 今日信号 ──
    with c2:
        st.markdown('<div class="mt">🎯 Today Signals</div>', unsafe_allow_html=True)
        sigs = list(reversed(trades[-10:] if len(trades) > 10 else trades))
        if not sigs:
            st.markdown('<div class="cd"><span style="color:#94A3B8;font-size:12px;">信号将由后台引擎持续生成...</span></div>', unsafe_allow_html=True)
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
        st.markdown('<div class="mt">📈 Performance</div>', unsafe_allow_html=True)
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
            <div class="kc"><div class="kl">Iterations</div><div class="kv">{ss.get("iteration",0)}</div></div>
        </div>
        """, unsafe_allow_html=True)

        # ── 资金曲线图 ──
        if simulator_initialized and len(curve) >= 2:
            st.markdown('<div class="mt" style="margin-top:10px;">📈 Equity Curve</div>', unsafe_allow_html=True)
            df = pd.DataFrame(curve)
            if "equity" in df.columns:
                df["equity"] = pd.to_numeric(df["equity"], errors="coerce")
                chart_data = df[["equity"]].copy()
                if "date" in df.columns:
                    chart_data.index = df["date"]
                st.line_chart(chart_data, height=200, width="stretch")
        elif not simulator_initialized:
            st.caption("模拟盘未初始化")
        else:
            st.caption("资金曲线由后台引擎持续生成...")

    # ── 建议留痕 ─────────────────────────────────────────────────────────
    st.markdown('<div class="mt" style="margin-top:20px;">💡 建议留痕</div>', unsafe_allow_html=True)

    try:
        from northstar.data.recommendation_store import list_recommendations, add_recommendation

        recs = list_recommendations(limit=20)

        if not recs:
            st.markdown(
                '<div class="cd" style="text-align:center;color:#94A3B8;font-size:12px;">暂无建议记录 —— 使用下方表单新增建议</div>',
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

    # ── 建议复盘 ─────────────────────────────────────────────────────────
    st.markdown('<div class="mt" style="margin-top:20px;">📋 建议复盘</div>', unsafe_allow_html=True)

    try:
        from northstar.data.recommendation_review import review_recommendations, format_change, format_change_pct

        try:
            from northstar.data.recommendation_store import list_recommendations as _list_recs
            recs_for_review = _list_recs(limit=20)
        except Exception:
            recs_for_review = []

        if not recs_for_review:
            st.markdown(
                '<div class="cd" style="text-align:center;color:#94A3B8;font-size:12px;">暂无可复盘建议</div>',
                unsafe_allow_html=True,
            )
        else:
            review_data = review_recommendations(recs_for_review)

            for r in review_data:
                act = r.get("action", "—")
                act_color = {
                    "买入": "sbuy", "卖出": "ssell", "持有": "shold",
                    "观察": "shold", "风险提示": "ssell",
                }.get(act, "shold")
                symbol = r.get("symbol", "?")
                entry_price = r.get("price")
                entry_price_str = f"${entry_price:.2f}" if entry_price else "—"
                current_price = r.get("current_price")
                current_price_str = f"${current_price:.2f}" if current_price else "—"
                change_pct = r.get("change_pct")
                change_pct_str = format_change_pct(change_pct) if current_price else "N/A"
                change_pct_color = "gn" if change_pct and change_pct > 0 else ("rd" if change_pct and change_pct < 0 else "")
                days_since = r.get("days_since")
                days_str = f"{days_since}天" if days_since is not None else "—"
                due = r.get("due_for_review", False)
                due_tag = "🔔 已到期" if due else "⏳ 未到期"
                status = r.get("review_status", "无法计算")
                ts = r.get("created_at", "")[-8:] if r.get("created_at") else ""

                # 根据 review_status 定制显示
                change_value = r.get("change")
                change_str = format_change(change_value)

                if status in ("缺少建议价格，无法计算收益率", "请使用英文股票代码，例如 NVDA"):
                    # 非标准场景：单行显示提示
                    st.markdown(
                        f'<div class="sg">'
                        f'<span class="sb {act_color}">{act}</span>'
                        f'<span class="stk">{symbol}</span>'
                        f'<span class="srs" style="color:#B45309;">⚠️ {status}</span>'
                        f'<span class="fts">{ts}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                elif status in ("价格获取失败", "暂无当前价格", "无法计算"):
                    st.markdown(
                        f'<div class="sg">'
                        f'<span class="sb {act_color}">{act}</span>'
                        f'<span class="stk">{symbol}</span>'
                        f'<span class="srs">建议价 {entry_price_str} · 当前价 {current_price_str} · 涨跌 {change_str} · {status}</span>'
                        f'<span class="fts">{ts}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    # 正常计算场景
                    change_color = "gn" if change_value and change_value > 0 else ("rd" if change_value and change_value < 0 else "")
                    st.markdown(
                        f'<div class="sg">'
                        f'<span class="sb {act_color}">{act}</span>'
                        f'<span class="stk">{symbol}</span>'
                        f'<span class="srs">建议价 {entry_price_str} → 当前 {current_price_str} · '
                        f'涨跌 <span class="{change_color}">{change_str}</span> · '
                        f'<span class="{change_pct_color}">{change_pct_str}</span> · {days_str} · {due_tag} · {status}</span>'
                        f'<span class="fts">{ts}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
    except ImportError as exc:
        st.markdown(
            f'<div class="cd" style="color:#DC2626;font-size:11px;">建议复盘模块未加载: {exc}</div>',
            unsafe_allow_html=True,
        )
    except Exception as exc:
        st.markdown(
            f'<div class="cd" style="color:#B45309;font-size:11px;">建议复盘异常: {exc}</div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div class="ftr">北极星 · 仅用于研究参考 · 不构成投资建议</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    run()
