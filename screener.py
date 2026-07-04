#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读股票筛选器。

第一版只扫描固定候选池，不扫描全市场、不写入文件、不连接券商。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from price_provider import InvalidSymbolError, PriceProvider, PriceProviderError, YFinancePriceProvider, normalize_symbol

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).parent
DEFAULT_WATCHLIST_FILE = ROOT / "watchlist.json"

DEFAULT_CANDIDATES = (
    "NVDA",
    "AAPL",
    "MSFT",
    "AMD",
    "AVGO",
    "PLTR",
    "SOFI",
    "TSLA",
    "META",
    "GOOGL",
)
DEFAULT_MIN_ABS_CHANGE_PCT = Decimal("2")


@dataclass(frozen=True)
class ScreenerRow:
    symbol: str
    price: Decimal | None
    previous_close: Decimal | None
    change_pct: Decimal | None
    reason: str
    risk_note: str
    source: str


class WatchlistLoadError(Exception):
    """watchlist.json 格式错误。"""


def normalize_symbols(symbols: Iterable[object]) -> tuple[list[str], tuple[str, ...]]:
    """标准化、去重并跳过非法 symbol。"""

    normalized: list[str] = []
    seen: set[str] = set()
    warnings: list[str] = []
    for raw_symbol in symbols:
        try:
            symbol = normalize_symbol(raw_symbol)  # type: ignore[arg-type]
        except InvalidSymbolError:
            warnings.append(f"非法 symbol 已跳过：{raw_symbol!r}")
            continue
        if symbol in seen:
            continue
        seen.add(symbol)
        normalized.append(symbol)
    return normalized, tuple(warnings)


def load_watchlist_symbols(path: str | Path) -> tuple[list[str], tuple[str, ...]]:
    """读取 watchlist JSON，并返回标准化 symbol。"""

    watchlist_path = Path(path)
    try:
        document = json.loads(watchlist_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise exc
    except json.JSONDecodeError as exc:
        raise WatchlistLoadError(
            f"{watchlist_path} 不是有效 JSON：第 {exc.lineno} 行，第 {exc.colno} 列，{exc.msg}"
        ) from exc
    except OSError as exc:
        raise WatchlistLoadError(f"无法读取 watchlist 文件 {watchlist_path}：{exc}") from exc

    if not isinstance(document, dict):
        raise WatchlistLoadError(f"{watchlist_path} 顶层必须是 JSON 对象。")
    symbols = document.get("symbols")
    if not isinstance(symbols, list):
        raise WatchlistLoadError(f"{watchlist_path} 必须包含 symbols 数组。")

    normalized, warnings = normalize_symbols(symbols)
    if not normalized:
        raise WatchlistLoadError(f"{watchlist_path} 没有可用 symbol。")
    return normalized, warnings


def resolve_candidate_symbols(
    watchlist_path: str | Path | None = DEFAULT_WATCHLIST_FILE,
    *,
    fallback_symbols: Iterable[str] = DEFAULT_CANDIDATES,
) -> tuple[list[str], tuple[str, ...]]:
    """优先读取 watchlist；不存在或格式错误时回退默认候选池。"""

    if watchlist_path is None:
        return normalize_symbols(fallback_symbols)

    try:
        symbols, warnings = load_watchlist_symbols(watchlist_path)
        return symbols, warnings
    except FileNotFoundError:
        symbols, warnings = normalize_symbols(fallback_symbols)
        return symbols, (f"watchlist 不存在，已使用内置默认股票池：{watchlist_path}", *warnings)
    except WatchlistLoadError as exc:
        symbols, warnings = normalize_symbols(fallback_symbols)
        return symbols, (f"watchlist 格式错误，已使用内置默认股票池：{exc}", *warnings)


def _calculate_change_pct(
    price: Decimal | None,
    previous_close: Decimal | None,
) -> Decimal | None:
    if price is None or previous_close is None or previous_close == Decimal("0"):
        return None
    return (price - previous_close) / previous_close * Decimal("100")


def _reason_for_change(change_pct: Decimal | None) -> str:
    if change_pct is None:
        return "行情不足，暂无法判断异动原因。"
    if change_pct >= DEFAULT_MIN_ABS_CHANGE_PCT:
        return "当日涨幅较大，可能有资金关注或消息催化，需人工复核。"
    if change_pct <= -DEFAULT_MIN_ABS_CHANGE_PCT:
        return "当日跌幅较大，可能有风险释放或情绪波动，需人工复核。"
    return "价格波动不大，作为候选池持续观察。"


def _risk_note_for_change(change_pct: Decimal | None) -> str:
    if change_pct is None:
        return "行情缺失，不应据此做交易决定。"
    if abs(change_pct) >= Decimal("5"):
        return "波动较大，避免追涨杀跌，先确认新闻和成交量。"
    return "第一版筛选仅基于价格异动，不构成投资建议。"


def screen_stocks(
    symbols: Iterable[str] = DEFAULT_CANDIDATES,
    *,
    provider: PriceProvider | None = None,
    min_abs_change_pct: Decimal = DEFAULT_MIN_ABS_CHANGE_PCT,
) -> list[ScreenerRow]:
    """筛选候选股票；单只行情失败不会中断整个列表。"""

    quote_provider = provider or YFinancePriceProvider()
    rows: list[ScreenerRow] = []

    normalized_symbols, symbol_warnings = normalize_symbols(symbols)
    for raw_symbol in symbol_warnings:
        rows.append(
            ScreenerRow(
                symbol="INVALID",
                price=None,
                previous_close=None,
                change_pct=None,
                reason="候选池包含非法 symbol，已跳过。",
                risk_note=raw_symbol,
                source="local",
            )
        )

    for symbol in normalized_symbols:
        try:
            quote = quote_provider.get_quote(symbol)
            change_pct = _calculate_change_pct(quote.price, quote.previous_close)
            rows.append(
                ScreenerRow(
                    symbol=quote.symbol,
                    price=quote.price,
                    previous_close=quote.previous_close,
                    change_pct=change_pct,
                    reason=_reason_for_change(change_pct),
                    risk_note=_risk_note_for_change(change_pct),
                    source=quote.source,
                )
            )
        except (PriceProviderError, Exception) as exc:
            rows.append(
                ScreenerRow(
                    symbol=symbol,
                    price=None,
                    previous_close=None,
                    change_pct=None,
                    reason="行情获取失败，保留在候选池等待复查。",
                    risk_note=f"价格未知：{exc}",
                    source="unknown",
                )
            )

    def sort_key(row: ScreenerRow) -> tuple[int, Decimal, str]:
        if row.change_pct is None:
            return (1, Decimal("0"), row.symbol)
        highlighted = abs(row.change_pct) >= min_abs_change_pct
        return (0 if highlighted else 1, -abs(row.change_pct), row.symbol)

    return sorted(rows, key=sort_key)


def _money(value: Decimal | None) -> str:
    return "价格未知" if value is None else f"${value:,.2f}"


def _pct(value: Decimal | None) -> str:
    return "未知" if value is None else f"{value:+.2f}%"


def print_screener_results(rows: list[ScreenerRow]) -> None:
    print("\n=== 今日关注股票列表 ===")
    if not rows:
        print("暂无候选股票。")
        return

    print(
        f"{'symbol':>8} {'price':>12} {'previous_close':>16} "
        f"{'change_pct':>12} {'source':>10}  reason / risk_note"
    )
    print("-" * 118)
    for row in rows:
        print(
            f"{row.symbol:>8} {_money(row.price):>12} "
            f"{_money(row.previous_close):>16} {_pct(row.change_pct):>12} "
            f"{row.source:>10}  {row.reason} | {row.risk_note}"
        )
    print("\n只读筛选：未修改文件，未连接券商，未自动交易。")


def main() -> None:
    parser = argparse.ArgumentParser(description="只读股票筛选器")
    parser.add_argument(
        "--watchlist",
        default=str(DEFAULT_WATCHLIST_FILE),
        help="watchlist JSON 文件路径，默认读取项目根目录 watchlist.json",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        help="手动指定候选股票代码；提供时优先于 watchlist",
    )
    args = parser.parse_args()

    if args.symbols:
        symbols, warnings = normalize_symbols(args.symbols)
    else:
        symbols, warnings = resolve_candidate_symbols(args.watchlist)

    for warning in warnings:
        print(f"[提示] {warning}")
    print_screener_results(screen_stocks(symbols))


if __name__ == "__main__":
    main()
