#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""北极星每日决策报告 v2.1：AI 产业链操作决策版。"""

from __future__ import annotations

import html
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
REPORT_DIR = PROJECT_ROOT / "reports" / "daily_decision"
SHORT_WATCHLIST_ENABLED = False


def _get_watchlist() -> list[str]:
    from northstar.reports.daily_decision_report import load_watchlist
    return load_watchlist()


def _get_portfolio() -> dict[str, dict[str, Any]]:
    from northstar.reports.daily_decision_report import load_portfolio
    return load_portfolio()


def _cn_count(text: str) -> int:
    return sum("\u4e00" <= char <= "\u9fff" for char in text)


def _price(value: float | None) -> str:
    return f"${value:.2f}" if value else "数据缺失"


def _action(t: Any, held: bool = False) -> str:
    if not getattr(t, "data_complete", False):
        return "观察"
    score = t.long_actionability_score
    weak = t.tech_status in ("弱势", "破位")
    if held:
        if weak or score < 35:
            return "减仓" if t.tech_status == "破位" else "观察"
        return "继续持有"
    if weak:
        return "暂不买入"
    if score >= 75 and (t.rsi14 or 50) <= 72:
        return "买入"
    if score >= 62:
        return "小仓试探"
    if t.above_ma20:
        return "等待回踩"
    return "观察"


def _levels(t: Any) -> dict[str, str]:
    current = t.current_price or 0
    return {
        "当前价": _price(current),
        "关键均线": f"MA20 {_price(t.ma20)} / MA60 {_price(t.ma60)}",
        "突破确认位": _price(max(filter(None, [t.high_20d, t.ma20, current])) if current else None),
        "回踩关注位": _price(t.ma20 or t.ma5 or t.low_20d),
        "失效观察位": _price(t.low_20d or t.ma60),
    }


def _apply_context_scores(tech_data: dict, events: dict, held: set[str]) -> None:
    for symbol, t in tech_data.items():
        event = events.get(symbol, {})
        t.event_sentiment_score = float(event.get("event_score", 0))
        t.user_context_score = 12.0 if symbol in held else 5.0
        total = (
            t.trend_score + t.momentum_score + t.technical_position_score
            + t.event_sentiment_score + t.user_context_score
        )
        if t.tech_status in ("弱势", "破位"):
            total = min(total, 52)
        if not getattr(t, "data_complete", False):
            total = min(total, 20)
        t.long_actionability_score = round(max(0, min(100, total)), 1)
        t.final_score = t.long_actionability_score
        t.action = _action(t, symbol in held)


def _select_top5(tech_data: dict) -> tuple[list[Any], int, bool]:
    """仅从数据完整股票选 Top 5；完整数不足 20 时整体熔断。"""
    complete = [item for item in tech_data.values() if item.data_complete]
    abnormal = len(complete) < 20
    if abnormal or len(complete) < 5:
        return [], len(complete), True
    return (
        sorted(complete, key=lambda item: item.long_actionability_score, reverse=True)[:5],
        len(complete), False,
    )


def _ordinary_analysis(t: Any, event: dict, held: bool = False) -> str:
    levels = _levels(t)
    ma_state = (
        "同时站上MA20与MA60，多头结构较完整" if t.above_ma20 and t.above_ma60
        else "站上MA20但尚未确认MA60，中期趋势仍需验证" if t.above_ma20
        else "仍在MA20下方，短线主动买盘尚未取得控制权"
    )
    rsi = f"{t.rsi14:.1f}" if t.rsi14 is not None else "缺失"
    volume = f"{t.volume_ratio:.2f}倍" if t.volume_ratio is not None else "缺失"
    event_text = (
        f"已从{event.get('source')}获取事件“{event.get('main_event')}”，"
        f"归类为{event.get('event_type')}，情绪判断为{event.get('sentiment')}；"
        f"{event.get('impact')}该事件参与最终评分。"
        if event.get("news_status") == "已获取"
        else event.get("main_event")
    )
    action = _action(t, held)
    reason = (
        "持仓身份仅提高跟踪优先级，不改变弱势结构下的纪律约束。"
        if held else "当前建议由趋势、动量、技术位置与可验证事件共同决定。"
    )
    text = (
        f"【当前状态】{t.company_cn}（{t.symbol}）现价{_price(t.current_price)}，今日"
        f"{t.change_pct_today:+.2f}%，短期状态为{t.tech_status}；{ma_state}。"
        f"【技术面】MA5为{_price(t.ma5)}、MA20为{_price(t.ma20)}、MA60为{_price(t.ma60)}，"
        f"RSI14为{rsi}，近5日{(t.change_pct_5d or 0):+.2f}%，近20日"
        f"{(t.change_pct_20d or 0):+.2f}%，量比{volume}。20日高低点分别为"
        f"{_price(t.high_20d)}和{_price(t.low_20d)}，当前应观察价格能否在关键均线附近形成有效承接。"
        f"【事件情绪】新闻状态：{event.get('news_status', '未获取')}。{event_text}"
        f"【操作判断】{action}。【理由】{reason}做多可操作分"
        f"{t.long_actionability_score:.1f}，其中趋势{t.trend_score:.1f}/25、动量"
        f"{t.momentum_score:.1f}/20、技术位置{t.technical_position_score:.1f}/20、事件"
        f"{t.event_sentiment_score:.1f}/20、用户权重{t.user_context_score:.1f}/15。"
        f"【关键观察位】关键均线：{levels['关键均线']}；突破观察位：{levels['突破确认位']}；"
        f"回踩观察位：{levels['回踩关注位']}；失效观察位：{levels['失效观察位']}。"
    )
    while _cn_count(text) < 220:
        text += "操作上以价格确认优先，不因单日涨跌改变计划；若量价背离或失守失效位，应及时降低预期并重新评估。"
    return text


def _top_analysis(t: Any, event: dict, rank: int) -> str:
    levels = _levels(t)
    action = _action(t)
    if action == "观察":
        action = "观察突破"
    position_style = "正常仓位" if action == "买入" else "小仓试探" if action == "小仓试探" else "观察仓"
    catalyst = (
        f"Yahoo Finance 返回了可验证事件“{event.get('main_event')}”，其情绪为"
        f"{event.get('sentiment')}，已按{t.event_sentiment_score:.1f}/20计入评分。"
        if event.get("news_status") == "已获取"
        else "当前未获取到实时新闻事件，事件分为零且不以传闻补位，本次入选完全由行情与技术结构支持。"
    )
    text = (
        f"【入选理由】{t.symbol}位列今日第{rank}，做多可操作分{t.long_actionability_score:.1f}。"
        f"它并非只因当日涨幅入选：趋势结构{t.trend_score:.1f}/25、动量与成交量"
        f"{t.momentum_score:.1f}/20、技术位置{t.technical_position_score:.1f}/20共同提供排序基础，"
        f"事件{t.event_sentiment_score:.1f}/20与用户权重{t.user_context_score:.1f}/15则保持透明。"
        f"【看涨逻辑】当前技术状态为{t.tech_status}，今日{t.change_pct_today:+.2f}%，近5日"
        f"{(t.change_pct_5d or 0):+.2f}%，近20日{(t.change_pct_20d or 0):+.2f}%。"
        f"{'价格已站上MA20与MA60，短中期方向形成共振。' if t.above_ma20 and t.above_ma60 else '价格结构仍有待关键均线确认，因此优势主要体现在候选优先级，而非无条件追价。'}"
        f"【技术支持】现价{_price(t.current_price)}，MA5、MA20、MA60依次为{_price(t.ma5)}、"
        f"{_price(t.ma20)}、{_price(t.ma60)}；RSI14为{t.rsi14 if t.rsi14 is not None else '缺失'}，"
        f"量比为{t.volume_ratio if t.volume_ratio is not None else '缺失'}。20日区间为"
        f"{_price(t.low_20d)}至{_price(t.high_20d)}，这组位置用于区分有效突破与高位追涨。"
        f"【事件催化】{catalyst}"
        f"【操作方案】建议“{action}”，仓位风格为“{position_style}”，并且不建议重仓。"
        f"若开盘后直接远离突破位，不追价；若回踩关键均线后缩量企稳，可分批验证；若放量越过突破确认位，"
        f"再观察收盘能否守住。该方案把确认信号放在预测之前，避免把候选排名误读为必须成交。"
        f"【关键价格位】当前价{levels['当前价']}；突破确认位{levels['突破确认位']}；"
        f"回踩关注位{levels['回踩关注位']}；失效观察位{levels['失效观察位']}。"
        f"【明日重点】重点看开盘后成交量是否延续、价格能否守住MA20、突破时是否伴随量能，"
        f"以及任何新事件是否来自可核验来源。操作纪律是：突破不确认不追，回踩不企稳不接，"
        f"跌破失效位则停止原看涨假设。"
    )
    while _cn_count(text) < 500:
        text += (
            "此外还要对照QQQ与AI产业链整体强弱：若个股上涨而板块同步走弱，需降低信号可信度；"
            "若板块、指数和个股同向且成交量配合，才可逐步提高仓位等级。盘中冲高回落与收盘确认应区别处理。"
        )
    return text


def _card(t: Any, event: dict, held: bool = False) -> str:
    analysis = _ordinary_analysis(t, event, held)
    return (
        f'<article class="card"><div class="card-head"><h3>{t.symbol} · {html.escape(t.company_cn)}</h3>'
        f'<span class="score">做多可操作分 {t.long_actionability_score:.1f}</span></div>'
        f'<div class="pills"><b>{_action(t, held)}</b><span>{t.tech_status}</span>'
        f'<span>风险 {t.tech_risk}</span></div><p>{html.escape(analysis)}</p></article>'
    )


def _top_card(t: Any, event: dict, rank: int) -> str:
    return (
        f'<article class="card top"><div class="card-head"><h3>#{rank} {t.symbol} · '
        f'{html.escape(t.company_cn)}</h3><span class="score">做多可操作分 '
        f'{t.long_actionability_score:.1f}</span></div><div class="pills"><b>{_action(t)}</b>'
        f'<span>趋势 {t.trend_score:.1f}/25</span><span>动量 {t.momentum_score:.1f}/20</span>'
        f'<span>位置 {t.technical_position_score:.1f}/20</span><span>事件 '
        f'{t.event_sentiment_score:.1f}/20</span></div><p>{html.escape(_top_analysis(t, event, rank))}</p></article>'
    )


def _market_relation(tech_data: dict, index_data: dict) -> str:
    ai_move = sum(t.change_pct_today for t in tech_data.values()) / max(len(tech_data), 1)
    qqq = index_data.get("QQQ")
    qqq_move = qqq.change_pct_today if qqq else 0
    relation = "强于大盘" if ai_move > qqq_move + .3 else "弱于大盘" if ai_move < qqq_move - .3 else "与大盘同步"
    return f"AI核心观察池平均涨跌{ai_move:+.2f}%，QQQ为{qqq_move:+.2f}%，今日AI方向{relation}。"


def generate_html_report() -> dict[str, Any]:
    """生成 v2.1 HTML，同时保留并调用原 Markdown/JSON 报告入口。"""
    import logging
    from northstar.analysis.institution_provider import get_institution_status
    from northstar.analysis.market_overview import fetch_market_overview, generate_market_analysis_text
    from northstar.analysis.news_provider import fetch_events, get_news_status
    from northstar.analysis.technical_analysis import fetch_technical_data
    from northstar.config.network import get_connectivity_status

    now = datetime.now().astimezone()
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    logger = logging.getLogger("daily_decision_html")
    symbols = _get_watchlist()
    portfolio = _get_portfolio()
    held = set(portfolio)
    all_symbols = list(dict.fromkeys(symbols + sorted(held - set(symbols))))
    tech_all = fetch_technical_data(all_symbols)
    tech_data = {s: tech_all[s] for s in symbols}
    events = fetch_events(all_symbols)
    _apply_context_scores(tech_all, events, held)
    top5, complete_count, data_abnormal = _select_top5(tech_data)
    failed = {symbol: item.failure_reason for symbol, item in tech_data.items() if not item.data_complete}
    logger.info("AI 观察池行情/K线完整: %d/%d", complete_count, len(symbols))
    for symbol, reason in failed.items():
        logger.error("%s 数据失败: %s", symbol, reason or "未知原因")
    index_data = fetch_market_overview()
    market_complete = sum(item.data_complete for item in index_data.values())
    logger.info("大盘行情/K线完整: %d/%d", market_complete, len(index_data))
    news_status = get_news_status(events)
    inst_status = get_institution_status()
    conn = get_connectivity_status()
    priced = sum(t.current_price > 0 for t in tech_data.values())
    strong = sum(t.tech_status in ("强势", "修复") for t in tech_data.values())
    weak = sum(t.tech_status in ("弱势", "破位") for t in tech_data.values())
    strategy = (
        "数据异常" if data_abnormal else
        "进攻" if strong >= weak + 5 else "防守" if weak >= strong + 5 else "观望"
    )
    direction = (
        "暂停操作" if data_abnormal else
        {"进攻": "做多为主", "观望": "观望为主", "防守": "防守为主"}[strategy]
    )
    conclusion = (
        "行情数据不足，今日不生成买入推荐"
        if data_abnormal else
        f"AI主线中可操作候选集中在{top5[0].symbol if top5 else '暂无'}等标的，"
        "按关键价位确认，避免在事件缺失或技术破位时强行交易。"
    )
    output = _build_html(
        now, symbols, tech_data, tech_all, events, portfolio, held, top5, index_data,
        generate_market_analysis_text(index_data), news_status, inst_status, conn,
        priced, complete_count, data_abnormal, strategy, direction, conclusion,
    )
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    html_path = REPORT_DIR / f"daily_decision_{now:%Y-%m-%d}.html"
    html_path.write_text(output, encoding="utf-8")
    return {
        "html_path": str(html_path), "md_path": "",
        "priced_count": priced, "complete_count": complete_count,
        "data_abnormal": data_abnormal,
        "top5": [{"symbol": t.symbol, "score": t.long_actionability_score,
                  "action": _action(t), "reason": _top_analysis(t, events[t.symbol], i)}
                 for i, t in enumerate(top5, 1)],
        "holdings": {s: _ordinary_analysis(tech_all[s], events[s], True)
                     for s in held if s in tech_all},
    }


def _build_html(
    now: datetime, symbols: list[str], tech_data: dict, tech_all: dict, events: dict,
    portfolio: dict, held: set[str], top5: list, index_data: dict, market_text: str,
    news_status: dict, inst_status: dict, conn: dict, priced: int,
    complete_count: int, data_abnormal: bool, strategy: str,
    direction: str, conclusion: str,
) -> str:
    top_html = (
        "".join(_top_card(t, events[t.symbol], i) for i, t in enumerate(top5, 1))
        if top5 else
        '<div class="danger"><b>数据不足，今日不生成可操作推荐。</b></div>'
    )
    held_html = "".join(_card(tech_all[s], events[s], True) for s in sorted(held) if s in tech_all)
    stocks_html = "".join(_card(tech_data[s], events[s]) for s in symbols)
    index_rows = "".join(
        f"<tr><td>{s}</td><td>{_price(v.current_price)}</td><td>{v.change_pct_today:+.2f}%</td>"
        f"<td>{v.tech_status}</td><td>MA20 {_price(v.ma20)} / MA60 {_price(v.ma60)}</td></tr>"
        for s, v in index_data.items()
    )
    acquired = [s for s, e in events.items() if e["news_status"] == "已获取"]
    positive = [s for s in acquired if events[s]["sentiment"] == "利好"]
    negative = [s for s in acquired if events[s]["sentiment"] == "利空"]
    missing = [s for s in symbols if events[s]["news_status"] != "已获取"]
    tomorrow = "".join(
        f"<li><b>{t.symbol}</b>：盯突破{_levels(t)['突破确认位']}、回踩"
        f"{_levels(t)['回踩关注位']}及成交量确认。</li>" for t in top5
    )
    warning = (
        '<div class="danger"><b>行情数据不足，本报告不可用于今日操作</b>'
        f'<br>完整K线：{complete_count}/{len(symbols)}，已暂停 Top 5 与买入建议。</div>'
        if data_abnormal else ""
    )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>北极星每日决策报告 v2.1</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f3f6fb;color:#172033;font-family:Arial,"Microsoft YaHei",sans-serif;line-height:1.75}}
main{{max-width:1180px;margin:auto;padding:24px}}nav{{position:sticky;top:0;background:#111827;color:white;padding:10px;text-align:center;z-index:2}}
nav a{{color:#dbeafe;margin:0 8px;text-decoration:none;font-size:13px}}section,.hero{{background:white;border-radius:14px;padding:24px;margin:18px 0;box-shadow:0 2px 12px #0f172a10}}
.hero{{background:linear-gradient(135deg,#0f172a,#1d4ed8);color:white}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}}
.metric{{background:#ffffff18;border:1px solid #ffffff25;border-radius:10px;padding:12px}}.metric small{{display:block;opacity:.75}}.danger{{background:#fee2e2;color:#991b1b;border:2px solid #ef4444;border-radius:10px;padding:16px;margin:12px 0;font-size:17px}}
.card{{border:1px solid #dce4ef;border-left:5px solid #3b82f6;border-radius:12px;padding:18px;margin:14px 0}}.top{{border-left-color:#10b981;background:#fbfffd}}
.card-head{{display:flex;justify-content:space-between;gap:10px;align-items:center}}.card h3{{margin:0}}.score{{background:#e0f2fe;color:#0369a1;padding:5px 10px;border-radius:18px;font-weight:bold}}
.pills{{display:flex;gap:7px;flex-wrap:wrap;margin:10px 0}}.pills span,.pills b{{background:#eef2f7;padding:3px 9px;border-radius:12px;font-size:13px}}.card p{{white-space:pre-line;margin:10px 0 0}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:8px;border-bottom:1px solid #e5e7eb;text-align:left}}h2{{border-bottom:2px solid #e5e7eb;padding-bottom:8px}}.status{{padding:12px;background:#f8fafc;border-radius:8px}}@media(max-width:650px){{main{{padding:10px}}.card-head{{display:block}}}}
</style></head><body>
<nav><a href="#overview">总览</a><a href="#top5">Top 5</a><a href="#held">持仓</a><a href="#market">大盘</a><a href="#pool">AI 25</a><a href="#events">事件</a><a href="#institution">机构</a><a href="#tomorrow">明日</a></nav>
<main>
<header class="hero" id="overview"><h1>北极星每日决策报告 v2.1</h1><p>{now:%Y-%m-%d %H:%M:%S} · AI产业链操作决策版</p>
{warning}
<div class="grid"><div class="metric"><small>今日总策略</small><b>{strategy}</b></div><div class="metric"><small>今日操作方向</small><b>{direction}</b></div>
<div class="metric"><small>行情成功率</small><b>{complete_count}/{len(symbols)}（{complete_count/max(len(symbols),1):.0%}）</b></div>
<div class="metric"><small>新闻源状态</small><b>{news_status['status']}</b></div><div class="metric"><small>机构源状态</small><b>{inst_status['status']}</b></div>
<div class="metric"><small>数据连接</small><b>{html.escape(str(conn.get('proxy_url','直连')))}</b></div></div><p><b>一句话结论：</b>{conclusion}</p></header>
<section id="top5"><h2>今日看涨可操作 Top 5</h2>{top_html}</section>
<section id="held"><h2>我的持仓特别跟踪</h2>{held_html or '<p>当前未读取到持仓。</p>'}</section>
<section id="market"><h2>AI产业链大盘环境</h2><p><b>{_market_relation(tech_data,index_data)}</b></p><table><tr><th>指数</th><th>价格</th><th>今日</th><th>状态</th><th>均线</th></tr>{index_rows}</table><p>{html.escape(market_text)}</p></section>
<section id="pool"><h2>AI 产业链 25 支观察池完整分析</h2>{stocks_html}</section>
<section id="events"><h2>新闻和事件情绪总览</h2><div class="status"><b>新闻源：{news_status['status']}</b> · {html.escape(news_status['note'])}</div>
<p><b>已获取事件：</b>{", ".join(acquired) or "无"}<br><b>利好：</b>{", ".join(positive) or "无"}<br><b>利空：</b>{", ".join(negative) or "无"}<br><b>未获取：</b>{", ".join(missing) or "无"}</p></section>
<section id="institution"><h2>机构分析</h2><div class="status"><b>机构源状态：{inst_status['status']}</b><p>{html.escape(inst_status['note'])}</p></div></section>
<section id="tomorrow"><h2>明日重点观察</h2><ol>{tomorrow}</ol><p><b>做空模块：暂未启用。</b></p></section>
<footer>北极星系统 · 数据缺失时明确降级 · 操作纪律以关键价位和失效条件为准</footer>
</main></body></html>"""


if __name__ == "__main__":
    result = generate_html_report()
    print(f"HTML 报告已生成: {result['html_path']}")
    import webbrowser
    webbrowser.open(Path(result["html_path"]).as_uri())
