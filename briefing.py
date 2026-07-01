#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一只读简报入口。"""

from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from ai_briefing import (
    LLMClient,
    LLMClientError,
    AIBriefingError,
    generate_ai_briefing,
    generate_morning_briefing,
)
from market_info import (
    DEFAULT_SCHEMA_PORTFOLIO_FILE,
    DEFAULT_WATCHLIST_FILE,
    EarningsRow,
    NewsRow,
    NewsProvider,
    build_earnings_rows,
    collect_focus_symbols,
    fetch_news_rows,
)
from portfolio_service import (
    PortfolioError,
    PortfolioState,
    apply_market_prices,
    get_portfolio_snapshot,
)
from price_provider import PriceProvider, PriceProviderError, PriceQuote, YFinancePriceProvider
from report_index import record_report
from screener import ScreenerRow, screen_stocks


DEFAULT_REPORTS_DIR = Path(__file__).parent / "reports"


def _money(value: Decimal | None) -> str:
    return "未知" if value is None else f"${value:,.2f}"


def _pct(value: Decimal | None) -> str:
    return "未知" if value is None else f"{value:+.2f}%"


def _fetch_portfolio_quotes(
    symbols: list[str],
    provider: PriceProvider | None = None,
) -> tuple[dict[str, dict], dict[str, PriceQuote], tuple[str, ...]]:
    quote_provider = provider or YFinancePriceProvider()
    prices: dict[str, dict] = {}
    quotes: dict[str, PriceQuote] = {}
    warnings: list[str] = []

    for symbol in symbols:
        try:
            quote = quote_provider.get_quote(symbol)
        except (PriceProviderError, Exception) as exc:
            warnings.append(f"{symbol} 行情获取失败：{exc}")
            continue
        quotes[quote.symbol] = quote
        prices[quote.symbol] = {
            "price": quote.price,
            "price_as_of": quote.price_as_of,
        }
    return prices, quotes, tuple(warnings)


def _load_priced_portfolio(
    portfolio_path: str | Path,
    provider: PriceProvider | None = None,
) -> tuple[PortfolioState | None, dict[str, PriceQuote], tuple[str, ...]]:
    try:
        state = get_portfolio_snapshot(portfolio_path)
    except PortfolioError as exc:
        return None, {}, (f"持仓读取失败：{exc}",)

    prices, quotes, warnings = _fetch_portfolio_quotes(sorted(state.positions), provider)
    if prices:
        state = apply_market_prices(state, prices)
    return state, quotes, warnings


def _position_to_dict(
    symbol: str,
    state: PortfolioState,
) -> dict[str, Any]:
    position = state.positions[symbol]
    allocation_base = state.total_equity or state.total_market_value
    allocation = (
        position.market_value / allocation_base * Decimal("100")
        if position.market_value is not None
        and allocation_base is not None
        and allocation_base != Decimal("0")
        else None
    )
    return {
        "symbol": position.symbol,
        "shares": str(position.shares),
        "avg_cost": str(position.avg_cost),
        "last_price": str(position.last_price) if position.last_price is not None else None,
        "market_value": str(position.market_value)
        if position.market_value is not None
        else None,
        "unrealized_pnl": str(position.unrealized_pnl)
        if position.unrealized_pnl is not None
        else None,
        "unrealized_pnl_pct": str(position.unrealized_pnl_pct)
        if position.unrealized_pnl_pct is not None
        else None,
        "allocation_pct": str(allocation) if allocation is not None else None,
    }


def _news_to_dict(row: NewsRow) -> dict[str, str]:
    return {
        "symbol": row.symbol,
        "title": row.title,
        "publisher": row.publisher,
        "published_at": row.published_at,
        "link": row.link,
    }


def _earnings_to_dict(row: EarningsRow) -> dict[str, str]:
    return {
        "symbol": row.symbol,
        "earnings_date": row.earnings_date,
        "importance": row.importance,
        "note": row.note,
    }


def _screener_to_dict(row: ScreenerRow) -> dict[str, Any]:
    return {
        "symbol": row.symbol,
        "price": str(row.price) if row.price is not None else None,
        "previous_close": str(row.previous_close)
        if row.previous_close is not None
        else None,
        "change_pct": str(row.change_pct) if row.change_pct is not None else None,
        "reason": row.reason,
        "risk_note": row.risk_note,
        "source": row.source,
    }


def build_briefing_data(
    portfolio_path: str | Path = DEFAULT_SCHEMA_PORTFOLIO_FILE,
    watchlist_path: str | Path = DEFAULT_WATCHLIST_FILE,
    *,
    price_provider: PriceProvider | None = None,
    news_provider: NewsProvider | None = None,
) -> dict[str, Any]:
    """构建统一简报结构化数据；只读、不写文件。"""

    state, quotes, price_warnings = _load_priced_portfolio(
        portfolio_path,
        price_provider,
    )
    symbols, symbol_warnings = collect_focus_symbols(portfolio_path, watchlist_path)
    news_rows, news_warnings = fetch_news_rows(
        symbols,
        provider=news_provider,
        per_symbol_limit=3,
    )
    earnings_rows = build_earnings_rows(symbols)
    try:
        screener_rows = screen_stocks(symbols, provider=price_provider)
        screener_warnings: tuple[str, ...] = ()
    except Exception as exc:
        screener_rows = []
        screener_warnings = (f"观察池筛选失败：{exc}",)

    account = None
    positions: list[dict[str, Any]] = []
    if state is not None:
        account = {
            "cash": str(state.cash) if state.cash is not None else None,
            "buying_power": str(state.buying_power)
            if state.buying_power is not None
            else None,
            "total_equity": str(state.total_equity)
            if state.total_equity is not None
            else None,
            "total_market_value": str(state.total_market_value)
            if state.total_market_value is not None
            else None,
            "total_unrealized_pnl": str(state.total_unrealized_pnl)
            if state.total_unrealized_pnl is not None
            else None,
            "prices_complete": state.prices_complete,
        }
        positions = [_position_to_dict(symbol, state) for symbol in sorted(state.positions)]

    return {
        "account": account,
        "positions": positions,
        "watchlist": symbols,
        "news": [_news_to_dict(row) for row in news_rows],
        "earnings": [_earnings_to_dict(row) for row in earnings_rows],
        "screener": [_screener_to_dict(row) for row in screener_rows[:5]],
        "quotes": {
            symbol: {
                "price": str(quote.price),
                "previous_close": str(quote.previous_close)
                if quote.previous_close is not None
                else None,
                "source": quote.source,
                "price_as_of": quote.price_as_of,
            }
            for symbol, quote in sorted(quotes.items())
        },
        "warnings": [
            *price_warnings,
            *symbol_warnings,
            *news_warnings,
            *screener_warnings,
        ],
        "read_only": True,
        "auto_trade": False,
    }


def _print_account_section(state: PortfolioState | None) -> None:
    print("\n[账户摘要]")
    if state is None:
        print("账户摘要暂不可用。")
        return
    print(f"持仓数量: {len(state.positions)}")
    print(f"现金: {_money(state.cash)}")
    print(f"总资产: {_money(state.total_equity)}")
    print(f"当前市值: {_money(state.total_market_value)}")
    print(f"未实现盈亏: {_money(state.total_unrealized_pnl)}")


def _print_positions_section(state: PortfolioState | None) -> None:
    print("\n[持仓概览]")
    if state is None or not state.positions:
        print("暂无持仓。")
        return

    allocation_base = state.total_equity or state.total_market_value
    print(
        f"{'symbol':>8} {'price':>12} {'market_value':>14} "
        f"{'pnl_pct':>10} {'allocation':>12}"
    )
    print("-" * 72)
    for symbol in sorted(state.positions):
        position = state.positions[symbol]
        allocation = (
            position.market_value / allocation_base * Decimal("100")
            if position.market_value is not None
            and allocation_base is not None
            and allocation_base != Decimal("0")
            else None
        )
        print(
            f"{symbol:>8} {_money(position.last_price):>12} "
            f"{_money(position.market_value):>14} "
            f"{_pct(position.unrealized_pnl_pct):>10} {_pct(allocation):>12}"
        )


def _print_news_section(
    symbols: list[str],
    provider: NewsProvider | None = None,
) -> None:
    print("\n[新闻速览]")
    rows, warnings = fetch_news_rows(symbols, provider=provider, per_symbol_limit=3)
    for warning in warnings:
        print(f"[提示] {warning}")
    if not rows:
        print("暂无新闻。")
        return
    for row in rows:
        print(f"- {row.symbol} | {row.published_at} | {row.publisher} | {row.title}")
        print(f"  {row.link}")


def _print_earnings_section(symbols: list[str]) -> None:
    print("\n[财报关注]")
    rows = build_earnings_rows(symbols)
    if not rows:
        print("暂无财报关注。")
        return
    for row in rows:
        print(
            f"- {row.symbol}: {row.earnings_date} | "
            f"{row.importance} | {row.note}"
        )


def _print_screener_section(
    symbols: list[str],
    provider: PriceProvider | None = None,
    limit: int = 5,
) -> None:
    print("\n[观察池异动]")
    try:
        rows = screen_stocks(symbols, provider=provider)
    except Exception as exc:
        print(f"观察池筛选暂不可用：{exc}")
        return
    if not rows:
        print("暂无观察池候选。")
        return

    for row in rows[:limit]:
        print(
            f"- {row.symbol}: price={_money(row.price)} "
            f"change={_pct(row.change_pct)} source={row.source}"
        )
        print(f"  {row.reason} | {row.risk_note}")


def show_briefing(
    portfolio_path: str | Path = DEFAULT_SCHEMA_PORTFOLIO_FILE,
    watchlist_path: str | Path = DEFAULT_WATCHLIST_FILE,
    *,
    price_provider: PriceProvider | None = None,
    news_provider: NewsProvider | None = None,
) -> bool:
    """输出统一简报；只读、不交易。"""

    print("\n=== 每日统一简报 ===")
    state, _, price_warnings = _load_priced_portfolio(portfolio_path, price_provider)
    symbols, symbol_warnings = collect_focus_symbols(portfolio_path, watchlist_path)

    for warning in (*price_warnings, *symbol_warnings):
        print(f"[提示] {warning}")

    _print_account_section(state)
    _print_positions_section(state)
    _print_news_section(symbols, news_provider)
    _print_earnings_section(symbols)
    _print_screener_section(symbols, price_provider)
    print("\n只读简报：未修改文件，未连接券商，未自动交易。")
    return True


def print_ai_briefing(result: dict[str, str]) -> None:
    """由 briefing.py 负责最终排版。"""

    print("\n=== AI 每日简报 ===")
    print("\n[账户摘要]")
    print(result["account_summary"])
    print("\n[持仓分析]")
    print(result["portfolio_analysis"])
    print("\n[观察池分析]")
    print(result["watchlist_analysis"])
    print("\n[风险提示]")
    print(result["risk_warning"])
    print("\n[今日操作建议]")
    print(result["action_items"])
    print("\n只读 AI 简报：未修改文件，未连接券商，未自动交易。")


def build_ai_briefing_markdown(
    result: dict[str, str],
    *,
    generated_at: datetime | None = None,
) -> str:
    """生成可保存的 AI 简报 Markdown。"""

    timestamp = (generated_at or datetime.now().astimezone()).replace(microsecond=0)
    return (
        "# AI 每日简报\n\n"
        f"生成时间: {timestamp.isoformat()}\n\n"
        "数据源说明: 持仓来自 portfolio_migrated_candidate.json，观察池来自 "
        "watchlist.json，行情和新闻来自 Yahoo Finance/yfinance，AI 分析来自 "
        "DeepSeek 兼容 LLMClient。本文只供人工复核，不构成自动交易指令。\n\n"
        "## 账户摘要\n\n"
        f"{result['account_summary']}\n\n"
        "## 持仓分析\n\n"
        f"{result['portfolio_analysis']}\n\n"
        "## 观察池分析\n\n"
        f"{result['watchlist_analysis']}\n\n"
        "## 风险提示\n\n"
        f"{result['risk_warning']}\n\n"
        "## 今日操作建议\n\n"
        f"{result['action_items']}\n"
    )


def _next_report_path(
    reports_dir: str | Path,
    generated_at: datetime,
    report_slug: str = "ai-briefing",
) -> Path:
    report_dir = Path(reports_dir)
    date_text = generated_at.strftime("%Y-%m-%d")
    base_path = report_dir / f"{date_text}-{report_slug}.md"
    if not base_path.exists():
        return base_path
    timestamp = generated_at.strftime("%H%M%S")
    candidate = report_dir / f"{date_text}-{report_slug}-{timestamp}.md"
    counter = 2
    while candidate.exists():
        candidate = report_dir / f"{date_text}-{report_slug}-{timestamp}-{counter}.md"
        counter += 1
    return candidate


def save_ai_briefing_report(
    result: dict[str, str],
    *,
    reports_dir: str | Path = DEFAULT_REPORTS_DIR,
    generated_at: datetime | None = None,
) -> Path:
    """保存 AI 简报 Markdown；不会覆盖已有报告。"""

    timestamp = generated_at or datetime.now().astimezone()
    report_dir = Path(reports_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = _next_report_path(report_dir, timestamp, "ai-briefing")
    report_path.write_text(
        build_ai_briefing_markdown(result, generated_at=timestamp),
        encoding="utf-8",
    )
    return report_path


def show_ai_briefing(
    portfolio_path: str | Path = DEFAULT_SCHEMA_PORTFOLIO_FILE,
    watchlist_path: str | Path = DEFAULT_WATCHLIST_FILE,
    *,
    price_provider: PriceProvider | None = None,
    news_provider: NewsProvider | None = None,
    llm_client: LLMClient | None = None,
    save_report: bool = False,
    reports_dir: str | Path = DEFAULT_REPORTS_DIR,
) -> bool:
    """输出 AI 简报；AI 返回 JSON，最终排版由本模块负责。"""

    data = build_briefing_data(
        portfolio_path,
        watchlist_path,
        price_provider=price_provider,
        news_provider=news_provider,
    )
    try:
        result = generate_ai_briefing(data, client=llm_client)
    except (LLMClientError, AIBriefingError) as exc:
        print(f"\n[错误] AI 简报生成失败：{exc}")
        print("只读 AI 简报：未修改文件，未连接券商，未自动交易。")
        return False

    print_ai_briefing(result)
    if save_report:
        report_path = save_ai_briefing_report(result, reports_dir=reports_dir)
        print(f"\n已保存 Markdown 报告: {report_path}")
    return True


def print_morning_briefing(result: dict[str, str]) -> None:
    """输出盘前简报。"""

    print("\n=== 今日盘前简报 ===")
    print("\n账户摘要")
    print(result["account_summary"])
    print("\n持仓分析")
    print(result["portfolio_analysis"])
    print("\n市场热点")
    print(result["market_hotspots"])
    print("\n观察池分析")
    print(result["watchlist_analysis"])
    print("\n今日财报")
    print(result["earnings_today"])
    print("\n风险提示")
    print(result["risk_warning"])
    print("\n今日操作建议")
    print(result["action_items"])
    print("\n只读盘前简报：未修改文件，未连接券商，未自动交易。")


def build_morning_markdown(
    result: dict[str, str],
    *,
    generated_at: datetime | None = None,
) -> str:
    """生成盘前简报 Markdown。"""

    timestamp = (generated_at or datetime.now().astimezone()).replace(microsecond=0)
    return (
        "# 今日盘前简报\n\n"
        f"生成时间: {timestamp.isoformat()}\n\n"
        "数据源说明: 账户与持仓来自 portfolio_migrated_candidate.json，观察池来自 "
        "watchlist.json，行情和新闻来自 Yahoo Finance/yfinance，财报信息来自本地静态结构，"
        "AI 分析来自 DeepSeek 兼容 LLMClient。本文只供人工复核，不构成自动交易指令。\n\n"
        "## 账户摘要\n\n"
        f"{result['account_summary']}\n\n"
        "## 持仓分析\n\n"
        f"{result['portfolio_analysis']}\n\n"
        "## 市场热点\n\n"
        f"{result['market_hotspots']}\n\n"
        "## 观察池分析\n\n"
        f"{result['watchlist_analysis']}\n\n"
        "## 今日财报\n\n"
        f"{result['earnings_today']}\n\n"
        "## 风险提示\n\n"
        f"{result['risk_warning']}\n\n"
        "## 今日操作建议\n\n"
        f"{result['action_items']}\n"
    )


def save_morning_report(
    result: dict[str, str],
    *,
    reports_dir: str | Path = DEFAULT_REPORTS_DIR,
    generated_at: datetime | None = None,
) -> Path:
    """保存盘前简报 Markdown；不会覆盖已有报告。"""

    timestamp = generated_at or datetime.now().astimezone()
    report_dir = Path(reports_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = _next_report_path(report_dir, timestamp, "morning")
    report_path.write_text(
        build_morning_markdown(result, generated_at=timestamp),
        encoding="utf-8",
    )
    return report_path


def show_morning_briefing(
    portfolio_path: str | Path = DEFAULT_SCHEMA_PORTFOLIO_FILE,
    watchlist_path: str | Path = DEFAULT_WATCHLIST_FILE,
    *,
    price_provider: PriceProvider | None = None,
    news_provider: NewsProvider | None = None,
    llm_client: LLMClient | None = None,
    save_report: bool = False,
    reports_dir: str | Path = DEFAULT_REPORTS_DIR,
) -> bool:
    """输出盘前 AI 简报；只读、不交易。"""

    data = build_briefing_data(
        portfolio_path,
        watchlist_path,
        price_provider=price_provider,
        news_provider=news_provider,
    )
    try:
        result = generate_morning_briefing(data, client=llm_client)
    except (LLMClientError, AIBriefingError) as exc:
        print(f"\n[错误] 盘前简报生成失败：{exc}")
        print("只读盘前简报：未修改文件，未连接券商，未自动交易。")
        return False

    print_morning_briefing(result)
    if save_report:
        report_path = save_morning_report(result, reports_dir=reports_dir)
        record_report(report_path, "morning", portfolio_path=portfolio_path)
        print(f"\n已保存 Markdown 报告: {report_path}")
    return True


def _join_lines(lines: list[str]) -> str:
    return "\n".join(lines) if lines else "暂无可用信息。"


def build_evening_briefing_result(data: dict[str, Any]) -> dict[str, str]:
    """基于统一简报数据生成盘后复盘内容；不调用交易接口。"""

    account = data.get("account") or {}
    positions = data.get("positions") or []
    news_rows = data.get("news") or []
    earnings_rows = data.get("earnings") or []
    screener_rows = data.get("screener") or []
    warnings = data.get("warnings") or []

    account_lines = [
        f"现金: {account.get('cash') or '未知'}",
        f"购买力: {account.get('buying_power') or '未知'}",
        f"总资产: {account.get('total_equity') or '未知'}",
        f"当前市值: {account.get('total_market_value') or '未知'}",
        f"未实现盈亏: {account.get('total_unrealized_pnl') or '未知'}",
    ]
    if account.get("prices_complete") is False:
        account_lines.append("提示: 部分行情缺失，账户表现可能不完整。")

    position_lines: list[str] = []
    for position in positions:
        position_lines.append(
            "- {symbol}: price={price}, market_value={market_value}, "
            "pnl={pnl}, pnl_pct={pnl_pct}, allocation={allocation}".format(
                symbol=position.get("symbol", "UNKNOWN"),
                price=position.get("last_price") or "未知",
                market_value=position.get("market_value") or "未知",
                pnl=position.get("unrealized_pnl") or "未知",
                pnl_pct=position.get("unrealized_pnl_pct") or "未知",
                allocation=position.get("allocation_pct") or "未知",
            )
        )

    news_lines: list[str] = []
    for row in news_rows[:9]:
        news_lines.append(
            "- {symbol} | {published_at} | {publisher} | {title}".format(
                symbol=row.get("symbol", "UNKNOWN"),
                published_at=row.get("published_at", "未知时间"),
                publisher=row.get("publisher", "未知来源"),
                title=row.get("title", "无标题"),
            )
        )

    event_lines: list[str] = []
    for row in earnings_rows[:10]:
        event_lines.append(
            "- {symbol}: {earnings_date} | {importance} | {note}".format(
                symbol=row.get("symbol", "UNKNOWN"),
                earnings_date=row.get("earnings_date", "TBD"),
                importance=row.get("importance", "medium"),
                note=row.get("note", "等待更新"),
            )
        )

    risk_lines = [f"- {warning}" for warning in warnings]
    large_allocations = [
        position
        for position in positions
        if _parse_optional_decimal(position.get("allocation_pct")) is not None
        and _parse_optional_decimal(position.get("allocation_pct")) >= Decimal("20")
    ]
    for position in large_allocations:
        risk_lines.append(
            f"- {position.get('symbol', 'UNKNOWN')} 单股仓位较高，明日开盘前人工复核。"
        )
    if not risk_lines:
        risk_lines.append("- 暂无额外系统风险提示，仍需人工复核隔夜新闻和行情。")

    plan_lines: list[str] = []
    for row in screener_rows[:5]:
        plan_lines.append(
            "- {symbol}: {reason} | {risk_note}".format(
                symbol=row.get("symbol", "UNKNOWN"),
                reason=row.get("reason", "观察价格变化"),
                risk_note=row.get("risk_note", "控制仓位，避免追高"),
            )
        )
    if not plan_lines:
        for symbol in data.get("watchlist") or []:
            plan_lines.append(f"- {symbol}: 明日继续观察价格、新闻和财报日程。")
            if len(plan_lines) >= 5:
                break

    return {
        "account_performance": _join_lines(account_lines),
        "position_performance": _join_lines(position_lines),
        "important_news": _join_lines(news_lines),
        "tomorrow_events": _join_lines(event_lines),
        "risk_warning": _join_lines(risk_lines),
        "tomorrow_watch_plan": _join_lines(plan_lines),
    }


def _parse_optional_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def print_evening_briefing(result: dict[str, str]) -> None:
    """输出盘后复盘。"""

    print("\n=== 今日盘后复盘 ===")
    print("\n今日账户表现")
    print(result["account_performance"])
    print("\n持仓表现")
    print(result["position_performance"])
    print("\n今日重要新闻")
    print(result["important_news"])
    print("\n明日财报与事件")
    print(result["tomorrow_events"])
    print("\n风险提示")
    print(result["risk_warning"])
    print("\n明日观察计划")
    print(result["tomorrow_watch_plan"])
    print("\n只读盘后复盘：未修改文件，未连接券商下单，未自动交易。")


def build_evening_markdown(
    result: dict[str, str],
    *,
    generated_at: datetime | None = None,
) -> str:
    """生成盘后复盘 Markdown。"""

    timestamp = (generated_at or datetime.now().astimezone()).replace(microsecond=0)
    return (
        "# 今日盘后复盘\n\n"
        f"生成时间: {timestamp.isoformat()}\n\n"
        "数据源说明: 账户与持仓来自 portfolio_migrated_candidate.json，观察池来自 "
        "watchlist.json，行情和新闻来自 Yahoo Finance/yfinance，财报信息来自本地静态结构。"
        "本文只供人工复核，不构成自动交易指令。\n\n"
        "## 今日账户表现\n\n"
        f"{result['account_performance']}\n\n"
        "## 持仓表现\n\n"
        f"{result['position_performance']}\n\n"
        "## 今日重要新闻\n\n"
        f"{result['important_news']}\n\n"
        "## 明日财报与事件\n\n"
        f"{result['tomorrow_events']}\n\n"
        "## 风险提示\n\n"
        f"{result['risk_warning']}\n\n"
        "## 明日观察计划\n\n"
        f"{result['tomorrow_watch_plan']}\n"
    )


def save_evening_report(
    result: dict[str, str],
    *,
    reports_dir: str | Path = DEFAULT_REPORTS_DIR,
    generated_at: datetime | None = None,
) -> Path:
    """保存盘后复盘 Markdown；不会覆盖已有报告。"""

    timestamp = generated_at or datetime.now().astimezone()
    report_dir = Path(reports_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = _next_report_path(report_dir, timestamp, "evening")
    report_path.write_text(
        build_evening_markdown(result, generated_at=timestamp),
        encoding="utf-8",
    )
    return report_path


def show_evening_briefing(
    portfolio_path: str | Path = DEFAULT_SCHEMA_PORTFOLIO_FILE,
    watchlist_path: str | Path = DEFAULT_WATCHLIST_FILE,
    *,
    price_provider: PriceProvider | None = None,
    news_provider: NewsProvider | None = None,
    save_report: bool = False,
    reports_dir: str | Path = DEFAULT_REPORTS_DIR,
) -> bool:
    """输出盘后复盘；只读、不交易。"""

    data = build_briefing_data(
        portfolio_path,
        watchlist_path,
        price_provider=price_provider,
        news_provider=news_provider,
    )
    result = build_evening_briefing_result(data)
    print_evening_briefing(result)
    if save_report:
        report_path = save_evening_report(result, reports_dir=reports_dir)
        record_report(report_path, "evening", portfolio_path=portfolio_path)
        print(f"\n已保存 Markdown 报告: {report_path}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="只读统一简报")
    parser.add_argument(
        "--portfolio-file",
        default=str(DEFAULT_SCHEMA_PORTFOLIO_FILE),
        help="Schema 1.1 持仓 JSON 文件路径",
    )
    parser.add_argument(
        "--watchlist",
        default=str(DEFAULT_WATCHLIST_FILE),
        help="watchlist JSON 文件路径",
    )
    parser.add_argument("--ai", action="store_true", help="调用 LLM 生成 AI 简报")
    parser.add_argument("--save", action="store_true", help="保存 AI 简报 Markdown")
    args = parser.parse_args()
    if args.ai:
        show_ai_briefing(args.portfolio_file, args.watchlist, save_report=args.save)
    else:
        show_briefing(args.portfolio_file, args.watchlist)


if __name__ == "__main__":
    main()
