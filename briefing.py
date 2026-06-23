#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一只读简报入口。"""

from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path

from market_info import (
    DEFAULT_SCHEMA_PORTFOLIO_FILE,
    DEFAULT_WATCHLIST_FILE,
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
    args = parser.parse_args()
    show_briefing(args.portfolio_file, args.watchlist)


if __name__ == "__main__":
    main()
