# -*- coding: utf-8 -*-
"""持仓操作建议 UI 渲染 — 在 Streamlit 首页显示每只持仓的中文卡片。"""

from __future__ import annotations

from typing import Any


def _action_color(action: str) -> str:
    """返回建议动作对应的颜色。"""
    mapping = {
        "持有": "#4ADE80",
        "加仓候选": "#60A5FA",
        "减仓": "#FBBF24",
        "清仓": "#F87171",
        "数据不足": "#9CA3AF",
    }
    return mapping.get(action, "#9CA3AF")


def _action_icon(action: str) -> str:
    mapping = {
        "持有": "✅",
        "加仓候选": "📈",
        "减仓": "⚠️",
        "清仓": "🔴",
        "数据不足": "❓",
    }
    return mapping.get(action, "❓")


def _pct_str(value: Any) -> str:
    """安全格式化百分比。"""
    if value is None:
        return "—"
    try:
        return f"{float(value):+.1f}%"
    except (ValueError, TypeError):
        return "—"


def _price_str(value: Any) -> str:
    """安全格式化价格。"""
    if value is None:
        return "—"
    try:
        return f"${float(value):.2f}"
    except (ValueError, TypeError):
        return "—"


def _shares_str(value: Any) -> str:
    """安全格式化股数。"""
    if value is None:
        return "—"
    try:
        v = int(value)
        return str(v)
    except (ValueError, TypeError):
        return str(value)


def render_holdings_decision_cards(st: Any, decisions: list[dict[str, Any]]) -> None:
    """渲染持仓操作建议卡片区域。

    Args:
        st: Streamlit module
        decisions: HoldingsDecision.to_dict() 列表
    """
    if not decisions:
        st.info("当前无持仓记录。")
        return

    st.markdown("## 我的持仓操作建议")
    st.caption("行情状态逐票标注；仅通过正式行情与完整历史数据的证券才会生成技术建议。")

    for d in decisions:
        symbol = d.get("symbol", "?")
        action = d.get("action", "?")
        need_today = d.get("need_action_today", False)
        need_today_reason = d.get("need_action_today_reason", "")
        data_integrity = d.get("data_integrity", "?")
        position_pct = d.get("position_pct")
        data_updated = d.get("data_updated_at", "?")
        price_source = str(d.get("price_source") or d.get("provider") or "unavailable")
        price_status = str(d.get("price_status") or "unknown")
        is_manual = price_source == "manual_broker_input"

        color = _action_color(action)
        icon = _action_icon(action)
        today_label = "⚠️ 需要操作" if need_today else "暂不操作"
        today_color = "#F87171" if need_today else "#4ADE80"

        # 截取数据更新时间
        data_time_short = data_updated[:16].replace("T", " ") if data_updated else "?"

        with st.container():
            st.markdown(f"""
            <div style="
                background: linear-gradient(145deg, #121821, #0D1219);
                border: 1px solid #202936;
                border-radius: 16px;
                padding: 20px 22px;
                margin-bottom: 14px;
                box-shadow: 0 8px 24px rgba(0,0,0,.15);
            ">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
                    <div style="display:flex;align-items:center;gap:8px;">
                        <span style="font-size:22px;font-weight:850;color:#F4F7FB;">{symbol}</span>
                        <span style="
                            background:{color}22;color:{color};
                            border:1px solid {color}55;
                            border-radius:8px;padding:3px 10px;
                            font-size:13px;font-weight:750;
                        ">{icon} {action}</span>
                    </div>
                    <div style="display:flex;align-items:center;gap:10px;">
                        <span style="
                            background:{today_color}22;color:{today_color};
                            border:1px solid {today_color}55;
                            border-radius:8px;padding:3px 10px;
                            font-size:12px;font-weight:750;
                        ">今日：{today_label}</span>
                        <span style="font-size:11px;color:#6F7A8B;">{data_integrity}</span>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # 信息网格
            if is_manual:
                st.warning("人工价格仅用于账户估值，不构成完整交易建议；止损、目标价和建议数量均不可用。")
            elif price_status == "latest_close_non_realtime":
                st.info("当前显示最近有效收盘价，属于非实时行情。")
            elif price_status in {"unavailable", "stale"}:
                st.warning("正式行情不可用或已过期，已阻断技术交易建议。")
            st.caption(f"行情来源：{price_source} · 行情状态：{price_status}")

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("持仓数量", _shares_str(d.get("shares")))
            col2.metric(
                "持仓成本",
                _price_str(d.get("avg_cost")),
                delta=None,
            )
            col3.metric("人工估值价格" if is_manual else "当前价格", _price_str(d.get("current_price")))
            col4.metric(
                "盈亏",
                _price_str(d.get("unrealized_pnl")),
                delta=_pct_str(d.get("unrealized_pnl_pct")),
            )

            col5, col6, col7, col8 = st.columns(4)
            col5.metric("市值", _price_str(d.get("market_value")))
            col6.metric("占比", f"{float(position_pct):.1f}%" if position_pct else "—")
            col7.metric("保护性止损", _price_str(d.get("stop_loss_price")))
            col8.metric("紧急参考线", _price_str(d.get("emergency_stop_price")))

            col9, col10 = st.columns(2)
            col9.metric("第一目标价", _price_str(d.get("target1_price")))
            col10.metric("第二目标价", _price_str(d.get("target2_price")))

            # 建议操作
            suggested_shares = d.get("suggested_shares")
            suggested_pct = d.get("suggested_pct")
            if suggested_shares is not None:
                shares_text = f"{suggested_shares} 股"
                if suggested_pct is not None:
                    try:
                        shares_text += f" (约{float(suggested_pct)*100:.0f}%)"
                    except (ValueError, TypeError):
                        pass
                st.caption(f"📌 建议操作数量：{shares_text}")

            if need_today_reason:
                if need_today:
                    st.warning(need_today_reason)
                else:
                    st.info(need_today_reason)

            # 触发条件展开
            with st.expander("📋 详细条件"):
                st.markdown("**继续持有条件**")
                st.caption(d.get("hold_condition", "—"))

                st.markdown("**加仓条件**")
                st.caption(d.get("add_condition", "—"))

                st.markdown("**减仓条件**")
                st.caption(d.get("reduce_condition", "—"))

                st.markdown("**清仓/止损条件**")
                st.caption(d.get("exit_condition", "—"))

                st.markdown("**核心理由**")
                st.caption(d.get("reason", "—"))

                st.markdown("**主要风险**")
                st.caption(d.get("main_risk", "—"))

                # 计算公式
                with st.expander("🔍 计算公式"):
                    st.caption(f"止损公式: {d.get('stop_loss_formula', '—')}")
                    st.caption(f"目标价公式: {d.get('target_price_formula', '—')}")
                    st.caption(f"建议数量公式: {d.get('sizing_formula', '—')}")

            st.caption(f"数据更新时间: {data_time_short}")
            st.divider()
