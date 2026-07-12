#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only PortfolioRepository CLI; legacy mutation/valuation helpers are disabled."""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from typing import Any

from portfolio_service import PortfolioError, get_portfolio_snapshot
from northstar.data.portfolio_snapshot import (
    FORMAL_PORTFOLIO_PATH,
    PortfolioRepository,
    PortfolioState,
)


PORTFOLIO_FILE = FORMAL_PORTFOLIO_PATH


def _deprecated(*args: Any, **kwargs: Any) -> None:
    raise PortfolioError(
        "deprecated portfolio_tracker helper is disabled; use PortfolioRepository "
        "and value_portfolio(MarketSnapshot)"
    )


# Import compatibility only. None of these helpers may read, write, fetch or value data.
load_portfolio = _deprecated
save_portfolio = _deprecated
load_config = _deprecated
save_config = _deprecated
fetch_prices = _deprecated
calc_position_value = _deprecated
calc_portfolio_summary = _deprecated
add_position = _deprecated
remove_position = _deprecated
print_summary = _deprecated
interactive_add = _deprecated
interactive_config = _deprecated


def print_schema_summary(state: PortfolioState) -> None:
    """Display raw canonical state without inventing a market valuation."""
    print(f"\n{'='*68}")
    print("  [Schema 1.1 持仓只读报告]")
    print(f"  Schema 版本: {state.schema_version}")
    print(f"  持仓数量: {len(state.positions)}")
    total_cost = sum((position.cost_basis for position in state.positions), Decimal("0"))
    print(f"  持仓总成本: ${total_cost:,.2f}")
    print(
        f"  现金: ${state.cash:,.2f} {state.base_currency}"
        if state.cash is not None
        else "  现金: 未知"
    )
    print("  总资产: 未生成 MarketSnapshot，无法计算")
    for warning in state.warnings:
        print(f"  [提示] {warning}")
    print(f"{'='*68}")


def print_schema_positions(state: PortfolioState) -> None:
    """Display source quantities and costs; no current-price calculation."""
    if not state.positions:
        print("\n  暂无持仓")
        return
    print(
        f"\n  {'代码':>8} {'股数':>12} {'平均成本':>14} "
        f"{'持仓成本':>16} {'已实现盈亏':>16}"
    )
    print(f"  {'-'*72}")
    for position in state.positions:
        print(
            f"  {position.symbol:>8} "
            f"{str(position.quantity):>12} "
            f"${position.average_cost:>12,.2f} "
            f"${position.cost_basis:>14,.2f} "
            f"{'—':>16}"
        )


def print_read_only_notice() -> None:
    print("\n[已阻止] Schema 1.1 仅支持只读查看。")
    print("--add、--sell、--sync 和 --config 已禁用。")
    print("本次没有访问网络，也没有修改任何持仓或配置数据。")


def main() -> None:
    parser = argparse.ArgumentParser(description="Schema 1.1 持仓只读报告")
    parser.add_argument(
        "--portfolio-file",
        default=str(PORTFOLIO_FILE),
        help="持仓 JSON 文件路径",
    )
    parser.add_argument("--add", action="store_true", help="已禁用")
    parser.add_argument("--sell", type=str, help="已禁用")
    parser.add_argument("--sync", action="store_true", help="已禁用")
    parser.add_argument("--config", action="store_true", help="已禁用")
    args = parser.parse_args()

    if args.add or args.sell is not None or args.sync or args.config:
        print_read_only_notice()
        return
    try:
        state = PortfolioRepository(args.portfolio_file).load()
    except PortfolioError as exc:
        print(f"\n[错误] 持仓数据无法读取：{exc}")
        print("请使用 Schema 1.1 文件，或通过 --portfolio-file 明确指定候选文件。")
        return
    print_schema_summary(state)
    print_schema_positions(state)
    print("\n只读模式：未访问网络，未调用 yfinance，未写入任何文件。")


if __name__ == "__main__":
    main()
