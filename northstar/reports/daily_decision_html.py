#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""北极星每日决策报告 v2 — HTML 可视化报告生成模块。

功能
----
1. 基于已有行情数据 + 技术分析 + 大盘分析
2. 生成可浏览器直接打开的 HTML 报告
3. 保留原 MD/JSON 报告输出
4. 浅色背景，卡片式布局，支持目录导航

使用方式
--------
python -m northstar.reports.daily_decision_html

或从现有 daily_decision_report 链调用。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

REPORT_DIR = PROJECT_ROOT / "reports" / "daily_decision"
LOG_DIR = PROJECT_ROOT / "logs"


def _get_watchlist() -> list[str]:
    """读取 watchlist。"""
    from northstar.reports.daily_decision_report import load_watchlist
    return load_watchlist()


def _get_portfolio() -> dict[str, dict[str, Any]]:
    """读取持仓信息。"""
    from northstar.reports.daily_decision_report import load_portfolio
    return load_portfolio()


def generate_html_report() -> dict[str, Any]:
    """生成完整的 HTML 报告。返回包含路径的 dict。"""
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("daily_decision_html")

    logger.info("=" * 60)
    logger.info("开始生成 HTML 每日决策报告 v2")

    now = datetime.now(timezone.utc).astimezone()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")

    # 1. 获取观察池和持仓
    symbols = _get_watchlist()
    portfolio = _get_portfolio()
    user_held = set(portfolio.keys()) if portfolio else set()
    logger.info("观察池: %d 支, 持仓: %s", len(symbols), list(user_held))

    # 2. 获取技术分析数据
    from northstar.analysis.technical_analysis import fetch_technical_data
    tech_data = fetch_technical_data(symbols)
    logger.info("技术分析: %d 支", len(tech_data))

    # 3. 获取大盘分析
    from northstar.analysis.market_overview import fetch_market_overview, generate_market_analysis_text
    index_data = fetch_market_overview()
    market_analysis_text = generate_market_analysis_text(index_data)
    logger.info("大盘分析完成")

    # 4. 获取代理/行情源状态
    from northstar.config.network import get_connectivity_status
    conn = get_connectivity_status()

    # 5. 获取新闻/机构状态
    from northstar.analysis.news_provider import get_news_status
    from northstar.analysis.institution_provider import get_institution_status
    news_status = get_news_status()
    inst_status = get_institution_status()

    # 6. 统计 & 排名
    priced_count = sum(1 for t in tech_data.values() if t.current_price > 0)
    total_count = len(symbols)
    market_status = "正常" if priced_count / max(total_count, 1) > 0.8 else "部分可用"

    # 排序
    sorted_by_final = sorted(tech_data.values(), key=lambda x: x.final_score, reverse=True)
    top5_opp = sorted_by_final[:5]
    top5_weak = sorted(tech_data.values(), key=lambda x: x.final_score)[:5]
    top5_risk = [t for t in sorted(tech_data.values(), key=lambda x: x.risk_score, reverse=True) if t.risk_score >= 60][:5]
    top5_trend = sorted(tech_data.values(), key=lambda x: x.trend_score, reverse=True)[:5]

    # 7. 生成决策
    strong_count = sum(1 for t in tech_data.values() if t.tech_status == "强势")
    weak_count = sum(1 for t in tech_data.values() if t.tech_status in ("弱势", "破位"))
    if strong_count > weak_count + 3:
        overall_strategy = "进攻"
        today_suggestion = "买入"
    elif weak_count > strong_count + 3:
        overall_strategy = "防守"
        today_suggestion = "减仓"
    else:
        overall_strategy = "观望"
        today_suggestion = "持有"

    from northstar.reports.daily_decision_report import (
        _make_overall_conclusion, StockPriceInfo,
        COMPANY_NAMES,
    )
    # 构建简单结论
    if strong_count / max(total_count, 1) > 0.4:
        conclusion = "适合买入 — 观察池整体强势，风险可控，可适度建仓"
    elif weak_count / max(total_count, 1) > 0.4:
        conclusion = "适合减仓 — 弱势股比例较高，整体风险偏大，降低仓位为主"
    elif weak_count > strong_count:
        conclusion = "适合观望 — 空头力量偏强，不宜冒进，等待企稳信号"
    else:
        conclusion = "适合观察 — 市场表现中性，精选个股为主"

    # 8. 构建 HTML
    html = _build_html(
        date_str=date_str, time_str=time_str,
        symbols=symbols, tech_data=tech_data,
        index_data=index_data, market_analysis_text=market_analysis_text,
        portfolio=portfolio, user_held=user_held,
        conn=conn, news_status=news_status, inst_status=inst_status,
        priced_count=priced_count, total_count=total_count,
        market_status=market_status,
        top5_opp=top5_opp, top5_weak=top5_weak,
        top5_risk=top5_risk, top5_trend=top5_trend,
        overall_strategy=overall_strategy,
        today_suggestion=today_suggestion,
        conclusion=conclusion,
    )

    # 9. 保存文件
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    html_path = REPORT_DIR / f"daily_decision_{date_str}.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info("HTML 报告已生成: %s", html_path)
    logger.info("=" * 60)

    return {"html_path": str(html_path), "date": date_str}


def _build_html(
    date_str: str, time_str: str,
    symbols: list[str],
    tech_data: dict,
    index_data: dict,
    market_analysis_text: str,
    portfolio: dict,
    user_held: set,
    conn: dict,
    news_status: dict,
    inst_status: dict,
    priced_count: int, total_count: int,
    market_status: str,
    top5_opp: list, top5_weak: list,
    top5_risk: list, top5_trend: list,
    overall_strategy: str,
    today_suggestion: str,
    conclusion: str,
) -> str:
    """构建完整 HTML 字符串。"""
    strategy_color = {"进攻": "#22c55e", "观望": "#f59e0b", "防守": "#ef4444"}
    suggestion_color = {"买入": "#22c55e", "持有": "#3b82f6", "减仓": "#ef4444", "不操作": "#6b7280"}

    risk_css = {"低": "risk-low", "中": "risk-mid", "高": "risk-high"}

    # 顶部总览卡片
    market_icon = "正常" if market_status == "正常" else "⚠️"
    proxy_str = conn.get("proxy_url", "直连")

    # 大盘表格行
    index_rows = ""
    for sym in ["SPY", "QQQ", "DIA", "IWM", "VIX"]:
        idx = index_data.get(sym)
        if not idx or idx.current_price == 0:
            continue
        arrow = "▲" if idx.change_pct_today >= 0 else "▼"
        color = "#22c55e" if idx.change_pct_today >= 0 else "#ef4444"
        ma_str = f"MA20: ${idx.ma20:.0f}" if idx.ma20 else "—"
        status_str = idx.tech_status
        index_rows += f"""
        <tr>
            <td><b>{sym}</b></td>
            <td>${idx.current_price:.2f}</td>
            <td style="color:{color}">{arrow} {idx.change_pct_today:+.1f}%</td>
            <td>{status_str}</td>
            <td>{ma_str}</td>
        </tr>"""

    # 个股卡片
    stock_cards = ""
    for sym in symbols:
        t = tech_data.get(sym)
        if not t:
            continue
        name = t.company_cn or sym
        is_held = sym in user_held
        arrow = "▲" if t.change_pct_today >= 0 else "▼"
        price_color = "#22c55e" if t.change_pct_today >= 0 else "#ef4444"

        # 技术状态标签
        status_colors = {"强势": "#22c55e", "修复": "#3b82f6", "震荡": "#f59e0b", "弱势": "#ef4444", "破位": "#dc2626"}
        tc = status_colors.get(t.tech_status, "#6b7280")

        # 评分条
        score_pct = max(0, min(100, t.final_score))

        # 买卖建议标签
        from northstar.reports.daily_decision_report import _judge_suggestion, StockPriceInfo
        sp = StockPriceInfo(symbol=sym, company_cn=name, current_price=t.current_price,
                            change_pct_today=t.change_pct_today, trend=t.tech_status,
                            change_pct_5d=t.change_pct_5d, change_pct_20d=t.change_pct_20d)
        sugg = _judge_suggestion(sp)
        sugg_color = suggestion_color.get(sugg, "#6b7280")

        held_badge = '<span class="held-badge">我的持仓</span>' if is_held else ""

        ma20_str = f"${t.ma20:.2f}" if t.ma20 else "—"
        ma60_str = f"${t.ma60:.2f}" if t.ma60 else "—"
        rsi_str = f"{t.rsi14}" if t.rsi14 else "—"
        vol_str = f"{t.volume_ratio:.1f}x" if t.volume_ratio else "—"
        h20 = f"${t.high_20d:.2f}" if t.high_20d else "—"
        l20 = f"${t.low_20d:.2f}" if t.low_20d else "—"

        stock_cards += f"""
        <div class="stock-card">
            <div class="card-header">
                <div class="card-title">
                    <span class="stock-symbol">{sym}</span>
                    <span class="stock-name">{name}</span>
                    {held_badge}
                </div>
                <div class="card-price">
                    <span class="price-value">${t.current_price:.2f}</span>
                    <span class="price-change" style="color:{price_color}">{arrow} {t.change_pct_today:+.1f}%</span>
                </div>
            </div>
            <div class="card-tags">
                <span class="tag tag-tech" style="background:{tc}20;color:{tc};border:1px solid {tc}40">{t.tech_status}</span>
                <span class="tag tag-risk {risk_css.get(t.tech_risk, 'tag-risk-mid')}">风险{t.tech_risk}</span>
                <span class="tag tag-suggest" style="background:{sugg_color}20;color:{sugg_color};border:1px solid {sugg_color}40">{sugg}</span>
                <span class="tag tag-score">综合分{score_pct:.0f}</span>
            </div>
            <div class="card-details">
                <table class="tech-table">
                    <tr>
                        <td><span class="label">MA5</span><b>${t.ma5:.2f}</b></td>
                        <td><span class="label">MA20</span><b>{ma20_str}</b></td>
                        <td><span class="label">MA60</span><b>{ma60_str}</b></td>
                        <td><span class="label">RSI14</span><b>{rsi_str}</b></td>
                    </tr>
                    <tr>
                        <td><span class="label">5日</span><b>{t.change_pct_5d:+.1f}%</b></td>
                        <td><span class="label">20日</span><b>{t.change_pct_20d:+.1f}%</b></td>
                        <td><span class="label">量比</span><b>{vol_str}</b></td>
                        <td><span class="label">20日高/低</span><b>{h20}/{l20}</b></td>
                    </tr>
                </table>
            </div>
            <div class="card-summary">
                {t.analysis_summary or f"{name}({sym})技术面状态为{t.tech_status}，建议{sugg}。"}
            </div>
        </div>"""

    # Top 排名
    rank_rows_opp = ""
    for i, t in enumerate(top5_opp[:5], 1):
        arrow = "▲" if t.change_pct_today >= 0 else "▼"
        c = "#22c55e" if t.change_pct_today >= 0 else "#ef4444"
        held = ' <span class="held-badge-sm">持仓</span>' if t.symbol in user_held else ""
        rank_rows_opp += f"""
        <tr>
            <td>{i}</td>
            <td><b>{t.symbol}</b>{held}</td>
            <td>${t.current_price:.2f}</td>
            <td style="color:{c}">{arrow} {t.change_pct_today:+.1f}%</td>
            <td>{t.tech_status}</td>
            <td>{t.final_score:.0f}</td>
        </tr>"""

    rank_rows_weak = ""
    for i, t in enumerate(top5_weak[:5], 1):
        arrow = "▼" if t.change_pct_today < 0 else "▲"
        c = "#ef4444" if t.change_pct_today < 0 else "#22c55e"
        rank_rows_weak += f"""
        <tr>
            <td>{i}</td>
            <td><b>{t.symbol}</b></td>
            <td>${t.current_price:.2f}</td>
            <td style="color:{c}">{arrow} {t.change_pct_today:+.1f}%</td>
            <td>{t.tech_status}</td>
            <td>{t.final_score:.0f}</td>
        </tr>"""

    # 持仓卡片
    held_cards = ""
    for sym in user_held:
        if sym not in tech_data:
            continue
        t = tech_data[sym]
        pos = portfolio.get(sym, {})
        shares = pos.get("shares", 0)
        avg_cost = pos.get("avg_cost", 0.0)
        pnl_pct = round((t.current_price - avg_cost) / avg_cost * 100, 2) if avg_cost > 0 else 0
        pnl_color = "#22c55e" if pnl_pct >= 0 else "#ef4444"
        from northstar.reports.daily_decision_report import StockPriceInfo, _judge_suggestion
        sp = StockPriceInfo(symbol=sym, current_price=t.current_price, trend=t.tech_status, change_pct_today=t.change_pct_today)
        sugg = _judge_suggestion(sp)
        held_cards += f"""
        <div class="stock-card held-card">
            <div class="card-header">
                <div class="card-title">
                    <span class="stock-symbol">{sym}</span>
                    <span class="stock-name">{t.company_cn or sym}</span>
                    <span class="held-badge">我的持仓</span>
                </div>
                <div class="card-price">
                    <span style="font-size:12px;color:#64748b">持仓{shares}股·均价${avg_cost:.2f}</span><br>
                    <span class="price-value">${t.current_price:.2f}</span>
                    <span style="color:{pnl_color}">({pnl_pct:+.1f}%)</span>
                </div>
            </div>
            <div class="card-tags">
                <span class="tag" style="background:#22c55e20;color:#22c55e;border:1px solid #22c55e40">{t.tech_status}</span>
                <span class="tag tag-suggest" style="background:{suggestion_color.get(sugg,'#6b7280')}20;color:{suggestion_color.get(sugg,'#6b7280')}">{sugg}</span>
                <span class="tag">评分{t.final_score:.0f}</span>
            </div>
            <div class="card-summary">{t.analysis_summary}</div>
        </div>"""

    # 如果没有持仓覆盖所有，加备注
    if not held_cards:
        held_cards = '<div style="padding:20px;color:#64748b">当前未持有观察池中的股票。</div>'

    # 新闻/机构占位
    news_note = news_status.get("note", "暂未接入新闻源")
    inst_note = inst_status.get("note", "暂未接入机构数据源")

    # 含持有判断的 lambda
    def _held_style(status):
        colors = {"强势": "#22c55e", "修复": "#3b82f6", "震荡": "#f59e0b", "弱势": "#ef4444", "破位": "#dc2626"}
        return colors.get(status, "#6b7280")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>北极星每日决策报告 — {date_str}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Segoe UI','Microsoft YaHei',sans-serif;background:#f8fafc;color:#1e293b;padding:20px;max-width:1200px;margin:0 auto}}
h1,h2,h3,h4{{margin:0}}
a{{color:#3b82f6;text-decoration:none}}
a:hover{{text-decoration:underline}}

/* 导航 */
.top-nav{{background:white;border-radius:12px;padding:16px 20px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,.08);display:flex;flex-wrap:wrap;gap:8px}}
.top-nav a{{font-size:14px;padding:4px 12px;background:#f1f5f9;border-radius:6px;color:#475569;transition:.15s}}
.top-nav a:hover{{background:#e2e8f0;color:#1e293b}}

/* 头部 */
.header-card{{background:linear-gradient(135deg,#1e40af,#3b82f6);color:white;border-radius:16px;padding:28px;margin-bottom:20px}}
.header-title{{font-size:22px;font-weight:700;margin-bottom:8px}}
.header-subtitle{{font-size:13px;opacity:.8;margin-bottom:16px}}
.header-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}}
.header-item{{background:rgba(255,255,255,.12);border-radius:10px;padding:12px}}
.header-item .label{{font-size:11px;opacity:.7}}
.header-item .value{{font-size:20px;font-weight:700;margin-top:2px}}
.strategy-badge{{display:inline-block;padding:4px 16px;border-radius:20px;font-weight:700;font-size:14px}}
.conclusion-text{{font-size:16px;font-weight:600;margin-top:12px}}

/* 板块 */
.section{{background:white;border-radius:12px;padding:24px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
.section-title{{font-size:18px;font-weight:700;margin-bottom:16px;padding-bottom:8px;border-bottom:2px solid #f1f5f9}}

/* 表格 */
table{{width:100%;border-collapse:collapse;font-size:14px}}
th,td{{padding:10px 12px;text-align:left;border-bottom:1px solid #f1f5f9}}
th{{font-weight:600;color:#64748b;font-size:12px;text-transform:uppercase}}

/* 风险标签 */
.risk-low{{color:#22c55e!important;background:#f0fdf4!important;border-color:#22c55e40!important}}
.risk-mid{{color:#f59e0b!important;background:#fffbeb!important;border-color:#f59e0b40!important}}
.risk-high{{color:#ef4444!important;background:#fef2f2!important;border-color:#ef444440!important}}

/* 个股卡片 */
.stock-card{{background:white;border:1px solid #e2e8f0;border-radius:12px;margin-bottom:12px;overflow:hidden}}
.card-header{{display:flex;justify-content:space-between;align-items:center;padding:14px 16px;background:#fafbfc;border-bottom:1px solid #e2e8f0}}
.card-title{{display:flex;align-items:center;gap:8px}}
.stock-symbol{{font-size:18px;font-weight:800;letter-spacing:-.3px}}
.stock-name{{font-size:13px;color:#64748b}}
.held-badge{{display:inline-block;background:#dbeafe;color:#2563eb;font-size:11px;font-weight:600;padding:2px 8px;border-radius:4px}}
.held-badge-sm{{display:inline-block;background:#dbeafe;color:#2563eb;font-size:10px;padding:1px 6px;border-radius:3px;margin-left:4px}}
.held-card{{border-left:4px solid #3b82f6}}
.card-price{{text-align:right}}
.price-value{{font-size:20px;font-weight:800}}
.price-change{{font-size:14px;font-weight:600;margin-left:8px}}
.card-tags{{padding:8px 16px;display:flex;gap:6px;flex-wrap:wrap}}
.tag{{display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:600;background:#f1f5f9;color:#475569}}
.tag-tech{{font-weight:700}}
.tag-suggest{{font-weight:700}}
.tag-score{{background:#f0f9ff!important;color:#0284c7!important}}
.card-details{{padding:8px 16px}}
.tech-table{{width:100%;font-size:13px}}
.tech-table td{{padding:4px 8px;border:none}}
.tech-table .label{{display:block;font-size:10px;color:#94a3b8;font-weight:500}}
.card-summary{{padding:12px 16px;font-size:13px;color:#475569;line-height:1.6;border-top:1px solid #f1f5f9}}

/* 大盘表格文字 */
.index-up{{color:#22c55e}}
.index-down{{color:#ef4444}}

/* 市场分析文字 */
.market-text{{font-size:13px;line-height:1.8;color:#475569}}

/* 占位模块 */
.placeholder-module{{background:#f8fafc;border:1px dashed #cbd5e1;border-radius:8px;padding:16px;font-size:13px;color:#64748b}}
.placeholder-module .status{{font-weight:600;margin-bottom:6px}}

/* 决策模块 */
.decision-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}}
.decision-card{{background:#fafbfc;border:1px solid #e2e8f0;border-radius:10px;padding:16px}}
.decision-card h4{{font-size:14px;font-weight:600;margin-bottom:8px;color:#475569}}
.decision-card p{{font-size:13px;color:#1e293b;line-height:1.6}}

/* 进度条 */
.progress-bar{{height:6px;background:#f1f5f9;border-radius:3px;margin-top:4px;overflow:hidden}}
.progress-fill{{height:100%;border-radius:3px}}

@media(max-width:600px){{.header-grid{{grid-template-columns:1fr 1fr}}.stock-cards-grid{{grid-template-columns:1fr}}}}
</style>
</head>
<body>

<div class="top-nav">
    <a href="#overview">今日总览</a>
    <a href="#market">大盘分析</a>
    <a href="#stocks">个股分析</a>
    <a href="#ranking">排名</a>
    <a href="#held">持仓关注</a>
    <a href="#news">新闻分析</a>
    <a href="#institution">机构分析</a>
    <a href="#decision">最终建议</a>
</div>

<!-- ════════ 顶部总览 ════════ -->
<div class="header-card" id="overview">
    <div class="header-title">北极星每日决策报告</div>
    <div class="header-subtitle">{date_str} {time_str} · 数据源自 Yahoo Finance</div>
    <div class="header-grid">
        <div class="header-item">
            <div class="label">观察池</div>
            <div class="value">{total_count} 支</div>
        </div>
        <div class="header-item">
            <div class="label">成功获取价格</div>
            <div class="value">{priced_count}/{total_count}</div>
        </div>
        <div class="header-item">
            <div class="label">行情源状态</div>
            <div class="value">{market_status}</div>
        </div>
        <div class="header-item">
            <div class="label">当前代理</div>
            <div class="value" style="font-size:14px">{proxy_str}</div>
        </div>
        <div class="header-item">
            <div class="label">今日策略</div>
            <div><span class="strategy-badge" style="background:{strategy_color.get(overall_strategy,'#6b7280')}">{overall_strategy}</span></div>
        </div>
        <div class="header-item">
            <div class="label">建议</div>
            <div><span class="strategy-badge" style="background:{suggestion_color.get(today_suggestion,'#6b7280')}">{today_suggestion}</span></div>
        </div>
    </div>
    <div class="conclusion-text">💡 {conclusion}</div>
</div>

<!-- ════════ 大盘分析 ════════ -->
<div class="section" id="market">
    <div class="section-title">📊 大盘环境分析</div>
    <table>
        <tr><th>指数</th><th>价格</th><th>涨跌</th><th>技术状态</th><th>均线</th></tr>
        {index_rows}
    </table>
    <div class="market-text" style="margin-top:16px">
        {market_analysis_text.replace(chr(10), '<br>')}
    </div>
</div>

<!-- ════════ 排名 ════════ -->
<div class="section" id="ranking">
    <div class="section-title">🏆 今日排名</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">
        <div>
            <h3 style="font-size:15px;margin-bottom:8px;color:#22c55e">🟢 综合最强 Top 5</h3>
            <table>
                <tr><th>#</th><th>代码</th><th>价格</th><th>涨跌</th><th>状态</th><th>评分</th></tr>
                {rank_rows_opp}
            </table>
        </div>
        <div>
            <h3 style="font-size:15px;margin-bottom:8px;color:#ef4444">🔴 综合最弱 Top 5</h3>
            <table>
                <tr><th>#</th><th>代码</th><th>价格</th><th>涨跌</th><th>状态</th><th>评分</th></tr>
                {rank_rows_weak}
            </table>
        </div>
    </div>
</div>

<!-- ════════ 个股分析 ════════ -->
<div class="section" id="stocks">
    <div class="section-title">📈 个股技术分析</div>
    <div class="stock-cards-grid">
        {stock_cards}
    </div>
</div>

<!-- ════════ 持仓关注 ════════ -->
<div class="section" id="held">
    <div class="section-title">📌 我的持仓关注</div>
    {held_cards}
</div>

<!-- ════════ 新闻分析 ════════ -->
<div class="section" id="news">
    <div class="section-title">📰 新闻分析</div>
    <div class="placeholder-module">
        <div class="status">🔴 新闻源状态：{news_status.get("status", "未接入")}</div>
        <p>{news_note}</p>
    </div>
</div>

<!-- ════════ 机构分析 ════════ -->
<div class="section" id="institution">
    <div class="section-title">🏛️ 机构分析</div>
    <div class="placeholder-module">
        <div class="status">🔴 机构数据源状态：{inst_status.get("status", "未接入")}</div>
        <p>{inst_note}</p>
    </div>
</div>

<!-- ════════ 最终建议 ════════ -->
<div class="section" id="decision">
    <div class="section-title">🎯 最终决策</div>
    <div class="decision-grid">
        <div class="decision-card">
            <h4>今日总体策略</h4>
            <p><span class="strategy-badge" style="background:{strategy_color.get(overall_strategy,'#6b7280')};color:white;font-size:14px">{overall_strategy}</span></p>
            <p style="margin-top:8px">{conclusion}</p>
        </div>
        <div class="decision-card">
            <h4>今日不建议</h4>
            <p>• 追高处于高风险区域的股票（AVGO、IONQ、RGTI、ARM、SMCI、ORCL）<br>
            • 在市场量能不足时重仓出击<br>
            • 在技术面破位的标的上逆势加仓</p>
        </div>
        <div class="decision-card">
            <h4>今日可以观察</h4>
            <p>• 综合评分靠前的强势个股<br>
            • 放量突破关键均线的修复标的<br>
            • 持仓股的趋势延续性</p>
        </div>
        <div class="decision-card">
            <h4>明天重点盯</h4>
            <p>• 大盘 SPY/QQQ 能否守住关键均线<br>
            • VIX 是否继续上升<br>
            • 持仓股的开盘走势与成交量变化</p>
        </div>
    </div>
    <div style="margin-top:16px;padding:16px;background:#f8fafc;border-radius:8px;text-align:center">
        <div style="font-size:14px;color:#64748b;margin-bottom:4px">今日一句话结论</div>
        <div style="font-size:20px;font-weight:700">{conclusion}</div>
    </div>
</div>

<div style="margin-top:20px;padding:16px;text-align:center;font-size:12px;color:#94a3b8">
    北极星系统 · 本报告仅供决策参考，不构成投资建议 · 系统未接入券商，不执行自动交易<br>
    报告生成时间: {date_str} {time_str}
</div>

</body>
</html>"""

    return html


if __name__ == "__main__":
    result = generate_html_report()
    html_path = result.get("html_path", "")
    print(f"HTML 报告已生成: {html_path}")
    import webbrowser
    webbrowser.open(f"file://{html_path}")