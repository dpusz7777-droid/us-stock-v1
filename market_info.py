#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读新闻和财报关注模块。

第一版只生成结构化占位信息：读取持仓和观察池 symbol，不访问网络、不写文件。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from portfolio_service import PortfolioError, get_portfolio_snapshot
from screener import (
    DEFAULT_WATCHLIST_FILE,
    WatchlistLoadError,
    load_watchlist_symbols,
    normalize_symbols,
)


ROOT = Path(__file__).parent
DEFAULT_SCHEMA_PORTFOLIO_FILE = ROOT / "portfolio_migrated_candidate.json"


@dataclass(frozen=True)
class NewsRow:
    symbol: str
    headline: str
    source: str
    published_at: str
    sentiment_hint: str
    risk_note: str


@dataclass(frozen=True)
class EarningsRow:
    symbol: str
    earnings_date: str
    importance: str
    note: str


MOCK_EARNINGS: dict[str, tuple[str, str, str]] = {
    "AAPL": ("TBD", "high", "大型科技权重股，财报可能影响纳指情绪。"),
    "AMD": ("TBD", "medium", "关注数据中心和 AI 芯片业务指引。"),
    "AVGO": ("TBD", "medium", "关注 AI 网络和半导体订单趋势。"),
    "GOOGL": ("TBD", "high", "关注广告、云业务和 AI 投入节奏。"),
    "META": ("TBD", "high", "关注广告增长、资本开支和 AI 产品化。"),
    "MSFT": ("TBD", "high", "关注云业务、AI 相关收入和利润率。"),
    "NVDA": ("TBD", "high", "AI 龙头，财报和指引对市场影响较大。"),
    "PLTR": ("TBD", "medium", "关注商业客户增长和 AI 平台落地。"),
    "SOFI": ("TBD", "medium", "关注贷款质量、会员增长和盈利能力。"),
    "SPCX": ("TBD", "low", "ETF/主题基金，优先关注底层持仓和主题波动。"),
    "TSLA": ("TBD", "high", "关注交付量、毛利率和自动驾驶业务表述。"),
}


def collect_focus_symbols(
    portfolio_path: str | Path = DEFAULT_SCHEMA_PORTFOLIO_FILE,
    watchlist_path: str | Path = DEFAULT_WATCHLIST_FILE,
) -> tuple[list[str], tuple[str, ...]]:
    """合并持仓和观察池 symbol；读取失败只产生提示，不中断。"""

    symbols: list[str] = []
    warnings: list[str] = []

    try:
        state = get_portfolio_snapshot(portfolio_path)
        symbols.extend(sorted(state.positions))
    except PortfolioError as exc:
        warnings.append(f"持仓读取失败：{exc}")

    try:
        watchlist_symbols, watchlist_warnings = load_watchlist_symbols(watchlist_path)
        symbols.extend(watchlist_symbols)
        warnings.extend(watchlist_warnings)
    except FileNotFoundError:
        warnings.append(f"watchlist 不存在，已仅使用持仓股票：{watchlist_path}")
    except WatchlistLoadError as exc:
        warnings.append(f"watchlist 格式错误，已仅使用持仓股票：{exc}")

    normalized, symbol_warnings = normalize_symbols(symbols)
    warnings.extend(symbol_warnings)
    return normalized, tuple(warnings)


def build_news_rows(symbols: Iterable[str]) -> list[NewsRow]:
    """生成新闻摘要占位结构，后续可替换为真实新闻源。"""

    normalized, warnings = normalize_symbols(symbols)
    rows = [
        NewsRow(
            symbol=symbol,
            headline=f"{symbol} 新闻摘要待接入真实数据源。",
            source="placeholder",
            published_at="TBD",
            sentiment_hint="neutral",
            risk_note="第一版仅提供占位结构，请人工核对真实新闻后再决策。",
        )
        for symbol in normalized
    ]
    rows.extend(
        NewsRow(
            symbol="INVALID",
            headline="非法 symbol 已跳过。",
            source="local",
            published_at="TBD",
            sentiment_hint="unknown",
            risk_note=warning,
        )
        for warning in warnings
    )
    return rows


def build_earnings_rows(symbols: Iterable[str]) -> list[EarningsRow]:
    """生成未来财报关注列表；第一版使用静态/mock 数据。"""

    normalized, warnings = normalize_symbols(symbols)
    rows: list[EarningsRow] = []
    for symbol in normalized:
        earnings_date, importance, note = MOCK_EARNINGS.get(
            symbol,
            ("TBD", "medium", "暂无静态财报备注，后续接入真实财报日历。"),
        )
        rows.append(
            EarningsRow(
                symbol=symbol,
                earnings_date=earnings_date,
                importance=importance,
                note=note,
            )
        )
    rows.extend(
        EarningsRow(
            symbol="INVALID",
            earnings_date="TBD",
            importance="unknown",
            note=warning,
        )
        for warning in warnings
    )
    return rows


def print_news_rows(rows: list[NewsRow], warnings: tuple[str, ...] = ()) -> None:
    print("\n=== 股票新闻摘要（占位版）===")
    for warning in warnings:
        print(f"[提示] {warning}")
    if not rows:
        print("暂无可关注股票。")
    else:
        print(
            f"{'symbol':>8} {'source':>12} {'published_at':>16} "
            f"{'sentiment':>12}  headline / risk_note"
        )
        print("-" * 118)
        for row in rows:
            print(
                f"{row.symbol:>8} {row.source:>12} {row.published_at:>16} "
                f"{row.sentiment_hint:>12}  {row.headline} | {row.risk_note}"
            )
    print("\n只读新闻：未修改文件，未连接券商，未自动交易。")


def print_earnings_rows(rows: list[EarningsRow], warnings: tuple[str, ...] = ()) -> None:
    print("\n=== 未来财报关注列表 ===")
    for warning in warnings:
        print(f"[提示] {warning}")
    if not rows:
        print("暂无可关注股票。")
    else:
        print(f"{'symbol':>8} {'earnings_date':>16} {'importance':>12}  note")
        print("-" * 88)
        for row in rows:
            print(
                f"{row.symbol:>8} {row.earnings_date:>16} "
                f"{row.importance:>12}  {row.note}"
            )
    print("\n只读财报：未修改文件，未连接券商，未自动交易。")


def show_news_overview(
    portfolio_path: str | Path = DEFAULT_SCHEMA_PORTFOLIO_FILE,
    watchlist_path: str | Path = DEFAULT_WATCHLIST_FILE,
) -> bool:
    symbols, warnings = collect_focus_symbols(portfolio_path, watchlist_path)
    print_news_rows(build_news_rows(symbols), warnings)
    return True


def show_earnings_overview(
    portfolio_path: str | Path = DEFAULT_SCHEMA_PORTFOLIO_FILE,
    watchlist_path: str | Path = DEFAULT_WATCHLIST_FILE,
) -> bool:
    symbols, warnings = collect_focus_symbols(portfolio_path, watchlist_path)
    print_earnings_rows(build_earnings_rows(symbols), warnings)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="只读新闻和财报关注模块")
    parser.add_argument("command", choices=("news", "earnings"))
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

    if args.command == "news":
        show_news_overview(args.portfolio_file, args.watchlist)
    else:
        show_earnings_overview(args.portfolio_file, args.watchlist)


if __name__ == "__main__":
    main()
