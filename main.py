# -*- coding: utf-8 -*-
"""
美股研究系统 - 统一入口

用法:
  python main.py dashboard         看盘
  python main.py dashboard --quick 快速看盘
  python main.py analyze AAPL     分析个股
  python main.py analyze AAPL MSFT 批量分析
  python main.py portfolio         查看持仓
  python main.py portfolio --add   添加交易
  python main.py rank              F-score排序所有观察股
  python main.py watchlist         管理观察名单
"""
import argparse
import subprocess
import sys
from pathlib import Path

from price_provider import PriceProvider, PriceProviderError, PriceQuote, YFinancePriceProvider
from portfolio_service import (
    PortfolioError,
    PortfolioState,
    apply_market_prices,
    get_portfolio_snapshot,
)

ROOT = Path(__file__).parent
DEFAULT_SCHEMA_PORTFOLIO_FILE = ROOT / "portfolio_migrated_candidate.json"


def run_script(name: str, args: list = None):
    """运行子模块"""
    cmd = [sys.executable, str(ROOT / name)]
    if args:
        cmd += args
    return subprocess.run(cmd)


def _money_or_unknown(value) -> str:
    return "价格未知" if value is None else f"${value:,.2f}"


def _pct_or_unknown(value) -> str:
    return "价格未知" if value is None else f"{value:+.2f}%"


def fetch_portfolio_quotes(
    symbols: list[str],
    provider: PriceProvider | None = None,
) -> tuple[dict[str, dict], dict[str, PriceQuote], tuple[str, ...]]:
    """按持仓代码获取行情；单只失败不影响其他持仓展示。"""

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


def print_portfolio_overview(
    state: PortfolioState,
    *,
    with_price: bool = False,
    quotes: dict[str, PriceQuote] | None = None,
    price_warnings: tuple[str, ...] = (),
) -> None:
    """输出 Schema 1.1 只读持仓概览。"""

    quotes = quotes or {}
    print("\n=== 持仓概览（Schema 1.1，只读）===")
    print(f"Schema 版本: {state.schema_version}")
    print(f"持仓数量: {len(state.positions)}")
    print(f"持仓总成本: ${state.total_cost_basis:,.2f}")
    print(f"追踪期内已实现盈亏: ${state.realized_pnl:,.2f}")
    if with_price:
        market_value = _money_or_unknown(state.total_market_value)
        unrealized = _money_or_unknown(state.total_unrealized_pnl)
        print(f"持仓当前市值: {market_value}")
        print(f"未实现盈亏: {unrealized}")

    if state.cash_status == "unknown":
        print("现金: 未知")
        reason = "现金基线未知" if with_price else "现金基线未知且未加载实时行情"
        print(f"总资产: 无法计算（{reason}）")
    else:
        cash = "未知" if state.cash is None else f"${state.cash:,.2f}"
        equity = (
            "无法计算" if state.total_equity is None else f"${state.total_equity:,.2f}"
        )
        print(f"现金: {cash}")
        print(f"总资产: {equity}")

    if not state.positions:
        print("\n暂无持仓")
    elif with_price:
        print(
            f"\n{'代码':>8} {'股数':>12} {'平均成本':>14} {'当前价格':>14} "
            f"{'当前市值':>14} {'未实现盈亏':>14} {'盈亏率':>12} {'来源':>10} {'价格时间':>22}"
        )
        print(f"{'-' * 130}")
        for symbol in sorted(state.positions):
            position = state.positions[symbol]
            quote = quotes.get(symbol)
            source = quote.source if quote else "-"
            price_as_of = quote.price_as_of if quote else "-"
            print(
                f"{position.symbol:>8} {str(position.shares):>12} "
                f"${position.avg_cost:>12,.2f} "
                f"{_money_or_unknown(position.last_price):>14} "
                f"{_money_or_unknown(position.market_value):>14} "
                f"{_money_or_unknown(position.unrealized_pnl):>14} "
                f"{_pct_or_unknown(position.unrealized_pnl_pct):>12} "
                f"{source:>10} {price_as_of:>22}"
            )
    else:
        print(f"\n{'代码':>8} {'股数':>12} {'平均成本':>14} {'持仓成本':>16}")
        print(f"{'-' * 56}")
        for symbol in sorted(state.positions):
            position = state.positions[symbol]
            print(
                f"{position.symbol:>8} {str(position.shares):>12} "
                f"${position.avg_cost:>12,.2f} ${position.cost_basis:>14,.2f}"
            )

    for warning in state.warnings:
        print(f"[提示] {warning}")
    for warning in price_warnings:
        print(f"[行情提示] {warning}")
    if with_price:
        print("\n只读模式：已按 --with-price 请求行情；未连接券商，未写入持仓文件。")
    else:
        print("\n只读模式：未连接券商，未访问网络，未写入持仓文件。")


def show_portfolio_overview(
    path: str | Path,
    *,
    with_price: bool = False,
    provider: PriceProvider | None = None,
) -> bool:
    """加载并展示持仓；错误转成用户可读消息，避免主程序崩溃。"""
    try:
        state = get_portfolio_snapshot(path)
    except PortfolioError as exc:
        print(f"\n[错误] 持仓概览无法读取：{exc}")
        return False

    quotes: dict[str, PriceQuote] = {}
    price_warnings: tuple[str, ...] = ()
    if with_price and state.positions:
        prices, quotes, price_warnings = fetch_portfolio_quotes(
            sorted(state.positions),
            provider=provider,
        )
        if prices:
            state = apply_market_prices(state, prices)

    print_portfolio_overview(
        state,
        with_price=with_price,
        quotes=quotes,
        price_warnings=price_warnings,
    )
    return True


def main():
    parser = argparse.ArgumentParser(description="📊 美股研究系统 v1.0")
    sub = parser.add_subparsers(dest="command")

    # dashboard
    p = sub.add_parser("dashboard", help="每日看盘")
    p.add_argument("--quick", action="store_true", help="快速模式")
    p.add_argument("--sector", action="store_true", help="板块表现")

    # analyze
    p = sub.add_parser("analyze", help="分析个股")
    p.add_argument("tickers", nargs="+", help="股票代码")
    p.add_argument("-v", "--verbose", action="store_true", help="详细数据")

    # portfolio
    p = sub.add_parser("portfolio", help="持仓管理")
    p.add_argument("--add", action="store_true", help="添加买入")
    p.add_argument("--sell", type=str, help="卖出持仓")
    p.add_argument("--sync", action="store_true", help="刷新价格")
    p.add_argument("--config", action="store_true", help="配置资金")
    p.add_argument("--with-price", action="store_true", help="联网获取真实行情")
    p.add_argument(
        "--portfolio-file",
        default=str(DEFAULT_SCHEMA_PORTFOLIO_FILE),
        help="Schema 1.1 持仓 JSON 文件路径",
    )

    # rank
    p = sub.add_parser("rank", help="F-score排序观察股")
    p.add_argument("-v", "--verbose", action="store_true", help="详细数据")

    # watchlist
    p = sub.add_parser("watchlist", help="管理观察名单")
    p.add_argument("--add", nargs="+", help="添加股票")
    p.add_argument("--remove", nargs="+", help="移除股票")

    # init
    p = sub.add_parser("init", help="初始化系统配置")

    # monitor
    p = sub.add_parser("monitor", help="持仓监控看板")
    p.add_argument("--daily", action="store_true", help="每日简报")
    p.add_argument("--alert", action="store_true", help="只看预警")
    p.add_argument("--add", action="store_true", help="录入买入")
    p.add_argument("--sell", type=str, help="卖出持仓")
    p.add_argument("--import-usmart", action="store_true", help="从uSMART导入")
    p.add_argument("--init", action="store_true", help="初始化示例持仓")

    args = parser.parse_args()

    if args.command == "dashboard":
        cmd_args = []
        if args.quick:
            cmd_args.append("--quick")
        if args.sector:
            cmd_args.append("--sector")
        run_script("market_dashboard.py", cmd_args)

    elif args.command == "analyze":
        run_script("stock_analyzer.py", args.tickers + (["-v"] if args.verbose else []))

    elif args.command == "portfolio":
        if args.add or args.sell is not None or args.sync or args.config:
            print("\n[已阻止] 主程序持仓概览当前仅支持 Schema 1.1 只读查看。")
            print("--add、--sell、--sync 和 --config 尚未迁移到 transactions 模式。")
            print("本次没有连接券商、访问网络或修改持仓文件。")
        else:
            show_portfolio_overview(args.portfolio_file, with_price=args.with_price)

    elif args.command == "rank":
        run_script("stock_analyzer.py", ["--watchlist"] + (["-v"] if args.verbose else []))

    elif args.command == "watchlist":
        if args.add:
            run_script("stock_analyzer.py", ["--add-watch"] + args.add)
        elif args.remove:
            run_script("stock_analyzer.py", ["--remove-watch"] + args.remove)
        else:
            run_script("stock_analyzer.py", ["--list-watch"])

    elif args.command == "init":
        print(f"\n🔧 初始化美股研究系统...")
        print(f"\n  安装依赖...")
        subprocess.run([sys.executable, "-m", "pip", "install", "yfinance", "pandas", "numpy"])
        print(f"\n✅ 初始化完成！")
        print(f"\n📋 使用指南:")
        print(f"  python main.py dashboard       看盘")
        print(f"  python main.py analyze NVDA     分析英伟达")
        print(f"  python main.py rank             评分排序")
        print(f"  python main.py portfolio        查看持仓")
        print(f"  python main.py watchlist        观察名单")

    elif args.command == "monitor":
        cmd_args = []
        if args.daily:
            cmd_args.append("--daily")
        if args.alert:
            cmd_args.append("--alert")
        if args.add:
            cmd_args.append("--add")
        if args.sell:
            cmd_args += ["--sell", args.sell]
        if args.import_usmart:
            cmd_args.append("--import-usmart")
        if args.init:
            cmd_args.append("--init")
        run_script("monitor.py", cmd_args)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
