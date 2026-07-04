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

    st.markdown('<div class="ftr">北极星 · 仅用于研究参考 · 不构成投资建议</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    run()
