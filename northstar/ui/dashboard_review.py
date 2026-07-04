#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""北极星投资系统 — 建议复盘 UI 模块

用法：
    from northstar.ui.dashboard_review import render_recommendation_review_section
    render_recommendation_review_section(st, ss, trades, curve, all_recs)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def render_recommendation_review_section(
    st: Any,
    ss: dict,
    trades: list,
    curve: list,
    all_recs: list,
    get_all_recommendations_fn: Any,
    list_recommendations_fn: Any,
    add_recommendation_fn: Any,
    update_recommendation_review_fn: Any,
    save_snapshot_fn: Any,
    get_latest_snapshot_fn: Any,
    get_snapshot_history_fn: Any,
    get_snapshot_trend_fn: Any,
    generate_trend_summary_fn: Any,
    load_snapshots_fn: Any,
    review_recommendations_fn: Any,
    classify_grade_fn: Any,
    classify_failure_fn: Any,
    build_summary_fn: Any,
    build_quality_fn: Any,
    get_stats_fn: Any,
    get_symbol_stats_fn: Any,
    get_action_stats_fn: Any,
    get_horizon_stats_fn: Any,
    get_data_health_fn: Any,
    generate_summary_fn: Any,
    format_change_pct_fn: Any,
    format_change_fn: Any,
    compute_grade_stats_fn: Any,
) -> None:
    """渲染建议复盘 UI 区域。"""
    import json
    import pandas as pd

    # ── 建议复盘 v2 ─────────────────────────────────────────────────────
    st.markdown('<div class="mt" style="margin-top:20px;">📋 建议复盘</div>', unsafe_allow_html=True)

    st.caption(
        "**建议复盘**：查看每条建议之后股票涨跌情况，判断建议是否正确、是否到了复盘时间。"
        "可筛选股票代码、建议动作、复盘状态，并按涨跌幅排序。"
    )

    st.info(
        "💡 **复盘操作指引**\n\n"
        "1️⃣ 先看 **复盘决策看板** —— 了解整体有效率和分级分布\n"
        "2️⃣ 再看 **复盘质量解释** —— 判断这个有效率是否可信\n"
        "3️⃣ 然后看明细表 —— 重点关注 **失效** 和 **数据不足** 的建议\n"
        "4️⃣ 定期保存 **复盘快照** —— 用于观察趋势变化\n\n"
        "仅用于历史复盘验证，不构成投资建议"
    )

    try:
        if not all_recs:
            st.markdown(
                '<div class="cd" style="text-align:center;color:#94A3B8;font-size:12px;">暂无建议数据，暂无可复盘建议 —— 新增建议后，系统会自动计算涨跌幅和复盘时间</div>',
                unsafe_allow_html=True,
            )
        else:
            review_data = review_recommendations_fn(all_recs)
            for rd in review_data:
                if "review_grade" not in rd:
                    try:
                        rd["review_grade"] = classify_grade_fn(rd).get("review_grade", "数据不足")
                    except Exception:
                        rd["review_grade"] = "数据不足"

            grade_priority = {"失效": 0, "数据不足": 1, "待观察": 2, "有效": 3}
            try:
                review_data.sort(key=lambda x: (grade_priority.get(x.get("review_grade", "数据不足"), 99), -abs(x.get("change_pct", 0) or 0)))
            except Exception:
                pass

            col_f1, col_f2, col_f3, col_f4, col_f5 = st.columns(5)
            st.caption("💡 优先查看 失效 → 数据不足 → 待观察 → 有效。有效建议用于总结经验，失效建议用于复盘原因，数据不足建议用于补齐字段。")

            with col_f1:
                filter_symbol = st.text_input("🔍 股票代码", value="", key="rv_sym", placeholder="NVDA").strip().upper()
            with col_f2:
                filter_action = st.selectbox("建议动作", ["全部", "买入", "持有", "卖出", "观察", "风险提示"], key="rv_act")
            with col_f3:
                filter_status = st.selectbox("复盘状态", ["全部", "上涨", "下跌", "持平", "无法计算", "价格获取失败", "缺少建议价格，无法计算收益率", "请使用英文股票代码，例如 NVDA"], key="rv_sts")
            with col_f4:
                filter_due = st.selectbox("到期筛选", ["全部", "已到复盘时间", "未到复盘时间"], key="rv_due")
            with col_f5:
                filter_grade = st.selectbox("分级筛选", ["全部", "失效", "数据不足", "待观察", "有效"], key="rv_grade")

            sort_option = st.selectbox("排序方式", ["分级优先(失效→有效)", "创建时间倒序", "涨跌幅从高到低", "涨跌幅从低到高", "已过天数从高到低", "股票代码排序"], key="rv_sort")

            filtered = []
            for r in review_data:
                if filter_symbol and not r.get("symbol", "").upper().startswith(filter_symbol):
                    continue
                if filter_action != "全部" and r.get("action") != filter_action:
                    continue
                if filter_status != "全部" and r.get("review_status") != filter_status:
                    continue
                if filter_due == "已到复盘时间" and not r.get("due_for_review", False):
                    continue
                if filter_due == "未到复盘时间" and r.get("due_for_review", False):
                    continue
                if filter_grade != "全部":
                    rd_grade = r.get("review_grade", "数据不足")
                    if rd_grade != filter_grade:
                        continue
                filtered.append(r)

            try:
                if sort_option == "创建时间倒序":
                    filtered.sort(key=lambda x: x.get("created_at", ""), reverse=True)
                elif sort_option == "涨跌幅从高到低":
                    filtered.sort(key=lambda x: x.get("change_pct") if x.get("change_pct") is not None else float("-inf"), reverse=True)
                elif sort_option == "涨跌幅从低到高":
                    filtered.sort(key=lambda x: x.get("change_pct") if x.get("change_pct") is not None else float("inf"))
                elif sort_option == "已过天数从高到低":
                    filtered.sort(key=lambda x: x.get("days_since") if x.get("days_since") is not None else 0, reverse=True)
                elif sort_option == "股票代码排序":
                    filtered.sort(key=lambda x: x.get("symbol", ""))
            except Exception:
                pass

            if not filtered:
                st.markdown('<div class="cd" style="text-align:center;color:#94A3B8;font-size:12px;">暂无匹配的复盘记录</div>', unsafe_allow_html=True)
            else:
                # 复盘决策看板
                st.markdown('<div class="mt" style="margin-top:16px;">🎯 复盘决策看板</div>', unsafe_allow_html=True)
                st.caption("**复盘决策看板**：基于 ±3% 阈值对每条建议进行只读分级。「有效」表示建议方向正确，「失效」表示建议方向错误。有效率仅用于历史建议验证，不代表未来收益。")
                grade_counts = {"有效": 0, "待观察": 0, "失效": 0, "数据不足": 0}
                for gr in filtered:
                    g = classify_grade_fn(gr)
                    grade_counts[g["review_grade"]] = grade_counts.get(g["review_grade"], 0) + 1
                total_graded = sum(grade_counts.values())
                effective = grade_counts.get("有效", 0)
                invalid = grade_counts.get("失效", 0)
                eff_denom = effective + invalid
                eff_rate = f"{effective / eff_denom * 100:.1f}%" if eff_denom > 0 else "暂无足够样本"
                gc1, gc2, gc3, gc4, gc5 = st.columns(5)
                gc1.metric("建议总数", total_graded)
                gc2.metric("✅ 有效", grade_counts.get("有效", 0))
                gc3.metric("⏳ 待观察", grade_counts.get("待观察", 0))
                gc4.metric("❌ 失效", grade_counts.get("失效", 0))
                gc5.metric("📊 有效率", eff_rate)
                st.caption("有效率 = 有效 / (有效 + 失效)，数据不足和待观察不计入分母。仅用于历史建议验证，不代表未来收益。")

                # 复盘质量解释
                st.markdown('<div class="mt" style="margin-top:16px;">🧠 复盘质量解释</div>', unsafe_allow_html=True)
                try:
                    quality = build_quality_fn(filtered)
                    ql_icon = {"良好": "✅", "一般": "⚠️", "较差": "❌", "暂无足够样本": "ℹ️"}.get(quality.get("quality_level", ""), "ℹ️")
                    st.markdown(
                        f'<div class="cd">'
                        f'<div class="rw"><span class="lb">样本质量等级</span><span class="vl" style="font-size:14px;">{ql_icon} {quality.get("quality_level", "")}</span></div>'
                        f'<div class="rw"><span class="lb">当前主要问题</span><span class="vl" style="font-size:13px;">{quality.get("main_issue", "")}</span></div>'
                        f'<div class="rw"><span class="lb">人话解释</span><span style="color:#475569;font-size:12px;flex:1;text-align:right;">{quality.get("explanation", "")}</span></div>'
                        f'<div class="rw" style="border-bottom:none;"><span class="lb">下一步建议</span><span style="color:#2563EB;font-size:12px;flex:1;text-align:right;">{quality.get("next_action", "")}</span></div>'
                        f'</div>', unsafe_allow_html=True)
                    if quality.get("warning_flags"):
                        st.caption(f"问题标签：{' · '.join(quality['warning_flags'])}")
                    st.caption("仅用于历史复盘验证，不构成投资建议。")
                except Exception as exc:
                    st.markdown(f'<div class="cd" style="color:#B45309;font-size:11px;">复盘质量解释异常: {exc}</div>', unsafe_allow_html=True)

                # 失效原因分布
                try:
                    f_stats = {"买入后下跌": 0, "卖出后上涨": 0, "动作类型无法识别": 0, "数据不足导致无法判断": 0, "其他失效原因": 0}
                    sev_counts = {"高": 0, "中": 0, "低": 0}
                    for fr in filtered:
                        frr = classify_failure_fn(fr)
                        reason = frr.get("failure_reason", "")
                        sev = frr.get("failure_severity", "")
                        if reason in f_stats:
                            f_stats[reason] += 1
                        if sev in sev_counts:
                            sev_counts[sev] += 1
                    total_f = sum(f_stats.values())
                    if total_f > 0:
                        st.markdown('<div class="mt" style="margin-top:16px;">🔍 失效原因分布</div>', unsafe_allow_html=True)
                        fc1, fc2, fc3, fc4, fc5 = st.columns(5)
                        fc1.metric("📉 买入后下跌", f_stats.get("买入后下跌", 0))
                        fc2.metric("📈 卖出后上涨", f_stats.get("卖出后上涨", 0))
                        fc3.metric("⚠️ 动作无法识别", f_stats.get("动作类型无法识别", 0))
                        fc4.metric("📋 数据不足", f_stats.get("数据不足导致无法判断", 0))
                        fc5.metric("❓ 其他", f_stats.get("其他失效原因", 0))
                        sc1, sc2, sc3 = st.columns(3)
                        sc1.metric("🔴 高严重程度", sev_counts.get("高", 0))
                        sc2.metric("🟡 中严重程度", sev_counts.get("中", 0))
                        sc3.metric("🟢 低严重程度", sev_counts.get("低", 0))
                        st.caption("仅用于历史复盘验证，不构成投资建议。")
                except Exception:
                    pass

                # 复盘结论总览
                try:
                    conclusion = build_summary_fn(filtered)
                    if conclusion.get("total_failed_count", 0) > 0:
                        st.markdown('<div class="mt" style="margin-top:16px;">📌 复盘结论总览</div>', unsafe_allow_html=True)
                        cc1, cc2, cc3, cc4 = st.columns(4)
                        cc1.metric("💥 失效建议", conclusion.get("total_failed_count", 0))
                        cc2.metric("🔍 主要失效原因", conclusion.get("top_failure_reason", "—"))
                        cc3.metric("📊 主要原因占比", f'{conclusion.get("top_failure_ratio", 0):.0%}' if conclusion.get("top_failure_ratio") else "—")
                        cc4.metric("🔴 高严重程度", conclusion.get("severity_counts", {}).get("高", 0))
                        conc = conclusion.get("conclusion", "")
                        na = conclusion.get("next_action", "")
                        if conc:
                            st.info(conc)
                        if na:
                            st.caption(f"💡 下一步：{na}")
                        st.caption("仅用于历史复盘验证，不构成投资建议。")
                except Exception:
                    pass

                # 每条记录展示
                for r in filtered:
                    g_result = classify_grade_fn(r)
                    grade_label = g_result["review_grade"]
                    grade_color = {"有效": "gn", "失效": "rd", "待观察": "am"}.get(grade_label, "")
                    grade_icon = {"有效": "✅", "失效": "❌", "待观察": "⏳"}.get(grade_label, "⚠️")
                    rec_id = r.get("id", "")
                    act = r.get("action", "—")
                    act_color = {"买入": "sbuy", "卖出": "ssell", "持有": "shold", "观察": "shold", "风险提示": "ssell"}.get(act, "shold")
                    symbol = r.get("symbol", "?")
                    entry_price = r.get("price")
                    entry_price_str = f"${entry_price:.2f}" if entry_price else "—"
                    current_price = r.get("current_price")
                    current_price_str = f"${current_price:.2f}" if current_price else "—"
                    change_pct = r.get("change_pct")
                    change_pct_str = format_change_pct_fn(change_pct) if current_price else "N/A"
                    change_pct_color = "gn" if change_pct and change_pct > 0 else ("rd" if change_pct and change_pct < 0 else "")
                    change_value = r.get("change")
                    change_str = format_change_fn(change_value)
                    change_color = "gn" if change_value and change_value > 0 else ("rd" if change_value and change_value < 0 else "")
                    days_since = r.get("days_since")
                    days_str = f"{days_since}天" if days_since is not None else "—"
                    due = r.get("due_for_review", False)
                    due_tag = "🔔 已到期" if due else "⏳ 未到期"
                    status = r.get("review_status", "无法计算")
                    ts = r.get("created_at", "")[-8:] if r.get("created_at") else ""
                    orig_record = next((rec for rec in all_recs if rec.get("id") == rec_id), None)
                    already_reviewed = orig_record is not None and orig_record.get("status") == "reviewed"
                    grade_tag = f'<span class="{grade_color}" style="font-weight:600;font-size:10px;">{grade_icon} {grade_label}</span>'

                    if already_reviewed:
                        orig_result = orig_record.get("review_result", {})
                        if isinstance(orig_result, dict):
                            reviewed_at = orig_result.get("reviewed_at", "")[-8:] if orig_result.get("reviewed_at") else ""
                            review_price = orig_result.get("review_price")
                            review_price_str = f"${review_price:.2f}" if review_price else "—"
                            review_pct = orig_result.get("change_pct")
                            review_pct_str = format_change_pct_fn(review_pct) if review_pct is not None else "N/A"
                            review_status_text = orig_result.get("review_status", "已复盘")
                        else:
                            reviewed_at = ""
                            review_price_str = "—"
                            review_pct_str = "N/A"
                            review_status_text = "已复盘"
                        st.markdown(
                            f'<div class="sg" style="border-left:3px solid #16A34A;">'
                            f'<span class="sb {act_color}">{act}</span><span class="stk">{symbol}</span>'
                            f'<span class="srs">{grade_tag} · 建议价 {entry_price_str} → 当前 {current_price_str} · '
                            f'涨跌 <span class="{change_color}">{change_str}</span> · <span class="{change_pct_color}">{change_pct_str}</span> · '
                            f'{days_str} · ✅ 已复盘({review_status_text}) · 复盘价 {review_price_str} · {review_pct_str}'
                            f'{f" · {reviewed_at}" if reviewed_at else ""}</span><span class="fts">{ts}</span></div>', unsafe_allow_html=True)
                    else:
                        if status in ("缺少建议价格，无法计算收益率", "请使用英文股票代码，例如 NVDA"):
                            st.markdown(f'<div class="sg"><span class="sb {act_color}">{act}</span><span class="stk">{symbol}</span><span class="srs" style="color:#B45309;">{grade_tag} ⚠️ {status}</span><span class="fts">{ts}</span></div>', unsafe_allow_html=True)
                        elif status in ("价格获取失败", "暂无当前价格", "无法计算"):
                            st.markdown(f'<div class="sg"><span class="sb {act_color}">{act}</span><span class="stk">{symbol}</span><span class="srs">{grade_tag} · 建议价 {entry_price_str} · 当前价 {current_price_str} · 涨跌 {change_str} · {status}</span><span class="fts">{ts}</span></div>', unsafe_allow_html=True)
                        else:
                            st.markdown(f'<div class="sg"><span class="sb {act_color}">{act}</span><span class="stk">{symbol}</span><span class="srs">{grade_tag} · 建议价 {entry_price_str} → 当前 {current_price_str} · 涨跌 <span class="{change_color}">{change_str}</span> · <span class="{change_pct_color}">{change_pct_str}</span> · {days_str} · {due_tag} · {status}</span><span class="fts">{ts}</span></div>', unsafe_allow_html=True)

                        btn_key = f"review_btn_{rec_id}"
                        if st.button(f"✅ 标记已复盘", key=btn_key, help=f"将 {symbol} 的建议标记为已复盘"):
                            from datetime import datetime as _dt
                            review_at = _dt.now().strftime("%Y-%m-%dT%H:%M:%S")
                            if status in ("缺少建议价格，无法计算收益率", "请使用英文股票代码，例如 NVDA"):
                                rd = {"reviewed_at": review_at, "review_price": None, "change": None, "change_pct": None, "days_since": days_since, "review_status": status, "review_notes": status}
                            elif status in ("价格获取失败", "暂无当前价格", "无法计算"):
                                sn = "缺少建议价格或当前价格，无法计算收益率" if not entry_price else f"当前价格获取失败: {r.get('price_fetch_error', '')}"
                                rd = {"reviewed_at": review_at, "review_price": current_price, "change": None, "change_pct": None, "days_since": days_since, "review_status": status, "review_notes": sn}
                            else:
                                rd = {"reviewed_at": review_at, "review_price": current_price, "change": change_value, "change_pct": change_pct, "days_since": days_since, "review_status": status}
                            ok, msg = update_recommendation_review_fn(recommendation_id=rec_id, review_result=rd)
                            if ok:
                                st.success(f"{symbol} 已标记为已复盘")
                                st.rerun()
                            else:
                                st.error(f"标记失败: {msg}")
    except ImportError as exc:
        st.markdown(f'<div class="cd" style="color:#DC2626;font-size:11px;">建议复盘模块未加载: {exc}</div>', unsafe_allow_html=True)
    except Exception as exc:
        st.markdown(f'<div class="cd" style="color:#B45309;font-size:11px;">建议复盘异常: {exc}</div>', unsafe_allow_html=True)

    # 复盘摘要结论
    st.markdown('<div class="mt" style="margin-top:20px;">🧭 复盘摘要结论</div>', unsafe_allow_html=True)
    st.caption("**复盘摘要**：根据所有已复盘建议自动生成的统计结论，包含整体胜率、平均涨跌幅、样本可信度等指标。")
    try:
        summary_recs = get_all_recommendations_fn()
        if summary_recs:
            o_s = get_stats_fn(summary_recs)
            s_s = get_symbol_stats_fn(summary_recs)
            a_s = get_action_stats_fn(summary_recs)
            h_s = get_horizon_stats_fn(summary_recs)
            sm = generate_summary_fn(o_s, s_s, a_s, h_s)
            if sm["status"] == "no_data":
                st.info(sm["headline"])
                for b in sm["bullets"]:
                    st.markdown(f"- {b}")
            elif sm["status"] == "low_confidence":
                st.warning(sm["headline"])
                for b in sm["bullets"]:
                    st.markdown(f"- {b}")
                for w in sm["warnings"]:
                    st.caption(f"⚠️ {w}")
            else:
                st.success(sm["headline"])
                for b in sm["bullets"]:
                    st.markdown(f"- {b}")
        else:
            st.info("暂无建议数据，无法生成复盘摘要 —— 新增建议并运行一段时间后会自动生成统计结论")
    except Exception:
        pass

    # 数据体检
    st.markdown('<div class="mt" style="margin-top:20px;">🩺 复盘数据体检</div>', unsafe_allow_html=True)
    st.caption("**数据体检**：检查建议数据的完整性和质量，包括是否缺少股票代码、建议价格、复盘状态是否一致等。")
    try:
        health_recs = get_all_recommendations_fn()
        if not health_recs:
            st.info("暂无建议数据，无法进行数据体检 —— 新增建议后会自动检查数据质量")
        else:
            health = get_data_health_fn(health_recs)
            if health["status"] == "ok":
                st.success(health["summary"])
            elif health["status"] == "warning":
                st.warning(health["summary"])
            else:
                st.error(health["summary"])
            hc1, hc2, hc3, hc4 = st.columns(4)
            hc1.metric("建议总数", health.get("total_count", 0))
            hc2.metric("数据健康分", f'{health.get("health_score", 100):.0f}')
            hc3.metric("问题总数", health.get("issue_count", 0))
            hc4.metric("受影响记录", health.get("affected_count", 0))
            issues = health.get("issues_by_type", {})
            non_zero = {k: v for k, v in issues.items() if v > 0}
            if non_zero:
                labels = {"missing_symbol": "缺少股票代码", "missing_action": "缺少建议动作", "unknown_action": "无法识别建议动作", "missing_recommendation_price": "缺少建议价", "missing_current_price": "已复盘但缺少当前价", "missing_change_pct": "已复盘但缺少涨跌幅", "invalid_date": "日期格式异常", "review_status_inconsistent": "复盘状态不一致", "outcome_unknown": "已复盘但无法判断胜负"}
                rows = [{"问题类型": labels.get(k, k), "数量": v} for k, v in sorted(non_zero.items(), key=lambda x: -x[1])]
                st.markdown("**问题类型统计**")
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            else:
                st.caption("暂无数据质量问题")
            if health.get("issue_rows"):
                st.markdown("**问题明细（前 20 条）**")
                detail = [{"序号": r["index"] + 1, "股票代码": r.get("symbol", "—"), "日期": r.get("date", "—"), "复盘状态": r.get("review_status", "—"), "问题说明": r.get("message", "")} for r in health["issue_rows"][:20]]
                st.dataframe(pd.DataFrame(detail), use_container_width=True, hide_index=True)
            else:
                st.caption("暂无问题明细")
    except Exception:
        pass

    # 复盘快照
    st.markdown('<div class="mt" style="margin-top:20px;">📝 复盘快照</div>', unsafe_allow_html=True)
    st.caption("**复盘快照**：手动保存当前复盘统计结果，便于日后对比系统建议质量变化趋势。")
    try:
        latest = get_latest_snapshot_fn()
        if latest:
            st.caption(f"最近快照：{(latest.get('created_at', '') or '')[-8:]}")
        else:
            st.caption("暂无复盘快照 —— 运行一段时间后点击下方按钮保存第一份快照")
        st.info("💡 **快照使用提示**\n\n• 建议每次完成一轮复盘后保存快照\n• 至少保存 **2 条快照** 后才能观察趋势\n• 快照用于历史复盘验证，不代表未来收益")
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("💾 保存当前复盘快照", key="snap_save", type="primary"):
                try:
                    snap_recs = get_all_recommendations_fn()
                    if snap_recs:
                        o = get_stats_fn(snap_recs)
                        s = get_symbol_stats_fn(snap_recs)
                        a = get_action_stats_fn(snap_recs)
                        h = get_horizon_stats_fn(snap_recs)
                        sm = generate_summary_fn(o, s, a, h)
                        rows = review_recommendations_fn(snap_recs)
                        gc = {"有效": 0, "待观察": 0, "失效": 0, "数据不足": 0}
                        for gr in rows:
                            g = classify_grade_fn(gr)
                            gc[g["review_grade"]] = gc.get(g["review_grade"], 0) + 1
                        v, i = gc.get("有效", 0), gc.get("失效", 0)
                        sample = v + i
                        gs = {"grade_valid_count": v, "grade_watch_count": gc.get("待观察", 0), "grade_invalid_count": i, "grade_insufficient_count": gc.get("数据不足", 0), "grade_effective_rate": round(v / sample * 100, 1) if sample > 0 else None, "grade_sample_count": sample} if sample > 0 else None
                        save_snapshot_fn(o, s, a, h, sm, gs)
                        st.success("已保存当前复盘快照")
                        st.rerun()
                    else:
                        st.info("暂无建议数据，无法保存快照")
                except Exception:
                    st.error("保存快照失败")
        with col2:
            st.caption("点击保存当前复盘统计结果，便于日后对比建议质量变化")
        snap_hist = get_snapshot_history_fn(limit=5)
        if snap_hist:
            def _sp(v):
                return "暂无数据" if v is None else format_change_pct_fn(v)
            def _sr(v):
                return "暂无数据" if v is None else f"{v:.2f}%"
            snap_rows = [{"快照时间": (s.get("created_at", "") or "")[-8:] or "—", "方向胜率": _sr(s.get("overall", {}).get("win_rate")), "平均方向涨跌幅": _sp(s.get("overall", {}).get("avg_normalized_change_pct")), "可判断样本": s.get("overall", {}).get("evaluable_count", 0), "样本可信度": s.get("overall", {}).get("confidence_label", "暂无数据"), "摘要结论": (s.get("summary", {}).get("headline") or "")[:30] or "—"} for s in snap_hist]
            st.dataframe(pd.DataFrame(snap_rows), use_container_width=True, hide_index=True)
    except Exception:
        pass

    # 复盘趋势
    st.markdown('<div class="mt" style="margin-top:20px;">📈 复盘趋势</div>', unsafe_allow_html=True)
    st.caption("**复盘趋势**：基于多次复盘快照绘制的胜率、涨跌幅、样本数变化趋势。至少需要 2 条快照才能显示。")
    try:
        trend_data = get_snapshot_trend_fn(limit=30)
        if len(trend_data) < 2:
            st.markdown('<div class="cd" style="text-align:center;color:#94A3B8;font-size:12px;">复盘快照不足，至少需要 2 条快照才能展示趋势 —— 请先在上方保存几条复盘快照</div>', unsafe_allow_html=True)
        else:
            ts = generate_trend_summary_fn(trend_data)
            st.info(ts)
            df = pd.DataFrame(trend_data)
            st.subheader("方向胜率趋势")
            st.line_chart(df[["display_time", "win_rate"]].set_index("display_time"), height=200)
            st.subheader("平均方向涨跌幅趋势")
            st.line_chart(df[["display_time", "avg_normalized_change_pct"]].set_index("display_time"), height=200)
            st.subheader("可判断样本数趋势")
            st.line_chart(df[["display_time", "evaluable_count"]].set_index("display_time"), height=200)

            st.subheader("📊 建议分级趋势")
            st.caption("**分级趋势**：基于每次快照的分级统计绘制。「有效」指建议方向正确，「失效」指方向错误。")
            has_grade = any(t.get("grade_valid_count") is not None for t in trend_data)
            if has_grade:
                st.caption("有效建议数量趋势")
                st.line_chart(df[["display_time", "grade_valid_count"]].set_index("display_time"), height=150)
                st.caption("失效建议数量趋势")
                st.line_chart(df[["display_time", "grade_invalid_count"]].set_index("display_time"), height=150)
                st.caption("有效率趋势")
                st.line_chart(df[["display_time", "grade_effective_rate"]].set_index("display_time"), height=150)
            else:
                st.markdown('<div class="cd" style="text-align:center;color:#94A3B8;font-size:12px;">旧快照尚未包含分级数据 —— 保存新的快照后，分级趋势将自动生成</div>', unsafe_allow_html=True)

            st.subheader("趋势明细")
            def _tp(v):
                return "暂无数据" if v is None else format_change_pct_fn(v)
            def _tr(v):
                return "暂无数据" if v is None else f"{v:.2f}%"
            def _ti(v):
                return "—" if v is None else v
            rows = [{"快照时间": t["display_time"], "方向胜率": _tr(t.get("win_rate")), "平均方向涨跌幅": _tp(t.get("avg_normalized_change_pct")), "可判断样本": t.get("evaluable_count", 0), "样本可信度": t.get("confidence_label", ""), "摘要结论": (t.get("headline") or "")[:30] or "—", "✅有效": _ti(t.get("grade_valid_count")), "❌失效": _ti(t.get("grade_invalid_count")), "📊有效率": _tr(t.get("grade_effective_rate"))} for t in trend_data]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    except Exception:
        pass

    # 失效原因趋势
    st.subheader("📉 失效原因趋势")
    try:
        all_snaps = load_snapshots_fn()
        snaps_with_fail = [s for s in all_snaps if s.get("failure_stats") and s["failure_stats"].get("total_failed_count", 0) > 0]
        if len(snaps_with_fail) >= 2:
            latest_fs = snaps_with_fail[-1].get("failure_stats", {})
            st.info(f"最近包含失效原因统计的快照：{latest_fs.get('top_failure_reason', '—')}（占比 {latest_fs.get('top_failure_ratio', 0)*100:.0f}%），共 {latest_fs.get('total_failed_count', 0)} 条失效建议。仅用于历史复盘验证。")
        else:
            st.markdown('<div class="cd" style="text-align:center;color:#94A3B8;font-size:12px;">至少需要 2 条包含失效原因统计的快照后才能观察失效原因趋势。</div>', unsafe_allow_html=True)
    except Exception:
        st.markdown('<div class="cd" style="text-align:center;color:#94A3B8;font-size:12px;">至少需要 2 条包含失效原因统计的快照后才能观察失效原因趋势。</div>', unsafe_allow_html=True)

    # ── v37: Autonomous Strategy Research Loop ──
    try:
        from northstar.data.recommendation_review import build_research_report
        ar_recs = get_all_recommendations_fn()
        if ar_recs:
            ar = build_research_report(ar_recs)
            with st.expander("🔬 Autonomous Research Insights", expanded=False):
                st.caption("**自动研究洞察**：基于策略 × 市场状态矩阵、稳定性、失效风险的规则驱动研究。")
                kf = ar.get("key_findings", [])
                if kf:
                    st.markdown("**Key Findings**")
                    for f in kf:
                        st.markdown(f"- {f}")
                else:
                    st.caption("暂无研究发现（样本不足）。")
                ai = ar.get("actionable_insights", [])
                if ai:
                    st.markdown("**Actionable Insights**")
                    for a in ai:
                        st.markdown(f"- {a}")
                conf = ar.get("confidence", 0)
                st.metric("Research Confidence", f"{conf:.0%}")
                st.caption("自动研究仅基于已有历史数据，不构成投资建议。")
        else:
            pass
    except Exception:
        pass

    # ── v36: Portfolio Intelligence Layer ──
    try:
        from northstar.data.recommendation_review import build_portfolio_intelligence_summary, build_portfolio_rebalance_insight
        pi_recs = get_all_recommendations_fn()
        if pi_recs:
            pi = build_portfolio_intelligence_summary(pi_recs)
            rebal = build_portfolio_rebalance_insight(pi_recs)
            ph = pi.get("portfolio_health", {})
            with st.expander("📊 Portfolio Intelligence", expanded=False):
                st.caption("**组合智能分析**：基于策略稳定性、失效风险和多元化的组合级评分。")
                c1, c2, c3 = st.columns(3)
                c1.metric("Overall Score", f'{ph.get("overall_score", 0):.2f}')
                c2.metric("Risk Level", ph.get("risk_level", "unknown").upper())
                c3.metric("Diversification", f'{ph.get("diversification_score", 0):.2f}')
                ws = pi.get("strategy_weights_suggestion", {})
                if ws:
                    st.markdown("**Suggested Strategy Weights**")
                    w_rows = [{"Strategy": k, "Weight": v} for k, v in sorted(ws.items(), key=lambda x: -x[1])]
                    st.dataframe(w_rows, use_container_width=True, hide_index=True)
                else:
                    st.caption("暂无策略权重建议（样本不足）。")
                ra = rebal.get("action", "maintain")
                st.markdown(f"**Rebalance Action**: {ra}")
                adj = rebal.get("top_adjustments", [])
                if adj:
                    st.markdown("**Top Adjustments**")
                    for a in adj:
                        st.markdown(f"- {a['strategy']}: **{a['action']}** — {a['reason']}")
                else:
                    st.caption("暂无调整建议。")
                st.caption("组合分析仅用于参考，不构成投资建议。")
        else:
            pass
    except Exception:
        pass

    # 建议复盘统计
    st.markdown('<div class="mt" style="margin-top:20px;">📊 建议复盘统计</div>', unsafe_allow_html=True)
    st.caption("**建议复盘统计**：整体建议的复盘汇总，包含胜率、涨跌幅、最佳/最差建议等统计指标。")
    try:
        stats_recs = get_all_recommendations_fn()
        if not stats_recs:
            st.markdown('<div class="cd" style="text-align:center;color:#94A3B8;font-size:12px;">暂无建议数据，暂无统计结果</div>', unsafe_allow_html=True)
        else:
            stats = get_stats_fn(stats_recs)
            def _ps(v):
                return "暂无数据" if v is None else format_change_pct_fn(v)
            def _ri(item):
                if item is None:
                    return '<span style="color:#94A3B8;font-size:11px;">暂无数据</span>'
                return f'<span style="font-weight:600;color:#2563EB;font-size:12px;">{item["symbol"]}</span> <span style="color:#94A3B8;font-size:10px;">{(item.get("created_at","") or "")[:10]}</span> <span class=' + ('"gn"' if (item.get("normalized_change_pct") or 0) > 0 else '"rd"') + f' style="font-size:11px;">{format_change_pct_fn(item.get("normalized_change_pct",0))}</span>'
            ws = _ps(stats.get("win_rate"))
            asp = _ps(stats.get("avg_change_pct"))
            adp = _ps(stats.get("avg_normalized_change_pct"))
            cl = stats.get("confidence_label", "暂无数据")
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("建议总数", stats.get("total_count", 0))
            c2.metric("已复盘", stats.get("reviewed_count", 0))
            c3.metric("待复盘", stats.get("pending_count", 0))
            c4.metric("到期未复盘", stats.get("due_count", 0))
            c5.metric("样本可信度", f"{cl}（{stats.get('evaluable_count', 0)}条）")
            c5, c6, c7 = st.columns(3)
            c5.metric("胜率（按方向）", ws)
            c6.metric("平均原始涨跌幅", asp)
            c7.metric("平均方向涨跌幅", adp)
            best = stats.get("best_review")
            worst = stats.get("worst_review")
            best_html = _ri(best)
            worst_html = _ri(worst)
            st.markdown(f'<div class="cd"><div class="rw"><span class="lb">最佳建议（按方向收益）</span><span>{best_html}</span></div><div class="rw" style="border-bottom:none;"><span class="lb">最差建议（按方向收益）</span><span>{worst_html}</span></div></div>', unsafe_allow_html=True)
    except Exception:
        pass

    # 按股票统计
    st.markdown('<div class="mt" style="margin-top:20px;">📊 按股票统计</div>', unsafe_allow_html=True)
    st.caption("按股票代码统计的复盘汇总。")
    try:
        sym_recs = get_all_recommendations_fn()
        if not sym_recs:
            st.markdown('<div class="cd" style="text-align:center;color:#94A3B8;font-size:12px;">暂无股票复盘统计</div>', unsafe_allow_html=True)
        else:
            symbol_rows = get_symbol_stats_fn(sym_recs)
            if symbol_rows:
                def _sv(v):
                    return "暂无数据" if v is None else format_change_pct_fn(v)
                def _sr(v):
                    return "暂无数据" if v is None else f"{v:.2f}%"
                table = [{"股票代码": r["symbol"], "建议总数": r["total_count"], "已复盘": r["reviewed_count"], "待复盘": r["pending_count"], "胜率": _sr(r["win_rate"]), "可判断样本": r.get("evaluable_count", 0), "样本可信度": r.get("confidence_label", "暂无数据"), "平均涨跌幅": _sv(r["avg_change_pct"]), "最佳涨跌幅": _sv(r["best_change_pct"]), "最差涨跌幅": _sv(r["worst_change_pct"]), "最近建议日期": r.get("latest_date") or "—", "最近复盘状态": r.get("latest_status") or "—"} for r in symbol_rows]
                st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)
            else:
                st.markdown('<div class="cd" style="text-align:center;color:#94A3B8;font-size:12px;">暂无股票复盘统计</div>', unsafe_allow_html=True)
    except Exception:
        pass

    # 按建议动作统计
    st.markdown('<div class="mt" style="margin-top:20px;">📊 按建议动作统计</div>', unsafe_allow_html=True)
    st.caption("按建议动作（买入、卖出、持有等）统计的复盘汇总。")
    try:
        act_recs = get_all_recommendations_fn()
        if act_recs:
            action_rows = get_action_stats_fn(act_recs)
            if action_rows:
                def _ap(v):
                    return "暂无数据" if v is None else format_change_pct_fn(v)
                def _ar(v):
                    return "暂无数据" if v is None else f"{v:.2f}%"
                table = [{"建议动作": r["action_display"], "建议总数": r["total_count"], "已复盘": r["reviewed_count"], "待复盘": r["pending_count"], "判断正确": r["win_count"], "判断错误": r["loss_count"], "胜率": _ar(r["win_rate"]), "可判断样本": r.get("evaluable_count", 0), "样本可信度": r.get("confidence_label", "暂无可判断样本"), "平均原始涨跌幅": _ap(r["avg_raw_change_pct"]), "平均归一化涨跌幅": _ap(r["avg_normalized_change_pct"])} for r in action_rows]
                st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)
            else:
                st.markdown('<div class="cd" style="text-align:center;color:#94A3B8;font-size:12px;">暂无建议动作统计</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="cd" style="text-align:center;color:#94A3B8;font-size:12px;">暂无建议动作统计</div>', unsafe_allow_html=True)
    except Exception:
        pass

    # 按复盘周期统计
    st.markdown('<div class="mt" style="margin-top:20px;">📊 按复盘周期统计</div>', unsafe_allow_html=True)
    st.caption("按复盘周期（短期、中期、长期等）统计。")
    try:
        hor_recs = get_all_recommendations_fn()
        if hor_recs:
            hor_rows = get_horizon_stats_fn(hor_recs)
            if hor_rows:
                def _hp(v):
                    return "暂无数据" if v is None else format_change_pct_fn(v)
                def _hr(v):
                    return "暂无数据" if v is None else f"{v:.2f}%"
                table = [{"复盘周期": r["label"], "建议总数": r["total_count"], "已复盘": r["reviewed_count"], "待复盘": r["pending_count"], "判断正确": r["win_count"], "判断错误": r["loss_count"], "胜率": _hr(r["win_rate"]), "可判断样本": r.get("evaluable_count", 0), "平均原始涨跌幅": _hp(r["avg_raw_change_pct"]), "平均方向涨跌幅": _hp(r["avg_normalized_change_pct"])} for r in hor_rows]
                st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)
            else:
                st.markdown('<div class="cd" style="text-align:center;color:#94A3B8;font-size:12px;">暂无复盘周期统计</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="cd" style="text-align:center;color:#94A3B8;font-size:12px;">暂无复盘周期统计</div>', unsafe_allow_html=True)
    except Exception:
        pass