#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一只读简报入口。"""

from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path
from typing import Any

from ai_briefing import LLMClient, LLMClientError, AIBriefingError, generate_ai_briefing
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
from screener import ScreenerRow, screen_stocks


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


def show_ai_briefing(
    portfolio_path: str | Path = DEFAULT_SCHEMA_PORTFOLIO_FILE,
    watchlist_path: str | Path = DEFAULT_WATCHLIST_FILE,
    *,
    price_provider: PriceProvider | None = None,
    news_provider: NewsProvider | None = None,
    llm_client: LLMClient | None = None,
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
    args = parser.parse_args()
    if args.ai:
        show_ai_briefing(args.portfolio_file, args.watchlist)
    else:
        show_briefing(args.portfolio_file, args.watchlist)


if __name__ == "__main__":
    main()
