#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读股票筛选器。

第一版只扫描固定候选池，不扫描全市场、不写入文件、不连接券商。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from price_provider import PriceProvider, PriceProviderError, YFinancePriceProvider

sys.stdout.reconfigure(encoding="utf-8")

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

    for raw_symbol in symbols:
        symbol = raw_symbol.strip().upper()
        if not symbol:
            continue
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
        "--symbols",
        nargs="+",
        default=list(DEFAULT_CANDIDATES),
        help="候选股票代码，默认使用固定候选池",
    )
    args = parser.parse_args()

    print_screener_results(screen_stocks(args.symbols))


if __name__ == "__main__":
    main()
