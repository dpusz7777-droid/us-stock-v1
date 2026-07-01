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
import json
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

from briefing import (
    show_ai_briefing,
    show_briefing,
    show_evening_briefing,
    show_morning_briefing,
)
from price_provider import PriceProvider, PriceProviderError, PriceQuote, YFinancePriceProvider
from market_info import show_earnings_overview, show_news_overview
from portfolio_service import (
    PortfolioError,
    PortfolioState,
    apply_market_prices,
    get_portfolio_snapshot,
    load_portfolio,
)
from usmart_sync import DEFAULT_CASH as DEFAULT_USMART_CASH
from usmart_sync import DEFAULT_EXCEL_FILE as DEFAULT_USMART_EXCEL_FILE
from usmart_sync import parse_usmart_positions, sync_usmart_excel, print_sync_summary
from report_index import recent_reports

ROOT = Path(__file__).parent
DEFAULT_SCHEMA_PORTFOLIO_FILE = ROOT / "portfolio_migrated_candidate.json"
DEFAULT_STOP_LOSS_PCT = Decimal("8")
DEFAULT_TARGET_PROFIT_PCT = Decimal("25")


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


def _to_decimal_setting(value, default: Decimal) -> Decimal:
    if isinstance(value, bool) or value is None:
        return default
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default
    if number <= 0 or number > 100:
        return default
    return number


def load_report_settings(path: str | Path) -> tuple[Decimal, Decimal]:
    """读取日报使用的止损/止盈阈值。"""

    try:
        document = load_portfolio(path)
    except PortfolioError:
        return DEFAULT_STOP_LOSS_PCT, DEFAULT_TARGET_PROFIT_PCT
    settings = document.get("settings")
    if not isinstance(settings, dict):
        settings = {}
    return (
        _to_decimal_setting(settings.get("stop_loss_pct"), DEFAULT_STOP_LOSS_PCT),
        _to_decimal_setting(
            settings.get("target_profit_pct"), DEFAULT_TARGET_PROFIT_PCT
        ),
    )


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


def print_daily_report(
    state: PortfolioState,
    stop_loss_pct: Decimal,
    target_profit_pct: Decimal,
    *,
    quotes: dict[str, PriceQuote] | None = None,
    price_warnings: tuple[str, ...] = (),
) -> None:
    """输出每日持仓报告，只读、不交易。"""

    quotes = quotes or {}
    print("\n=== 每日持仓报告 ===")

    print("\n[账户摘要]")
    print(f"持仓数量: {len(state.positions)}")
    print(f"持仓总成本: ${state.total_cost_basis:,.2f}")
    print(f"当前市值: {_money_or_unknown(state.total_market_value)}")
    print(f"未实现盈亏: {_money_or_unknown(state.total_unrealized_pnl)}")
    if state.total_cost_basis:
        report_pnl_pct = (
            state.total_unrealized_pnl / state.total_cost_basis * Decimal("100")
            if state.total_unrealized_pnl is not None
            else None
        )
    else:
        report_pnl_pct = None
    print(f"盈亏率: {_pct_or_unknown(report_pnl_pct)}")
    if state.cash_status == "unknown":
        print("现金: 未知")
        print("总资产: 无法计算（现金基线未知）")
        print("购买力: 未知")
    else:
        print(f"现金: {_money_or_unknown(state.cash)}")
        print(f"总资产: {_money_or_unknown(state.total_equity)}")
        print(f"购买力: {_money_or_unknown(state.buying_power)}")

    print("\n[当前持仓列表]")
    if not state.positions:
        print("暂无持仓")
    else:
        allocation_base = state.total_equity or state.total_market_value
        print(
            f"{'代码':>8} {'股数':>12} {'平均成本':>14} {'当前价格':>14} "
            f"{'当前市值':>14} {'未实现盈亏':>14} {'盈亏率':>12} {'仓位占比':>12}"
        )
        print(f"{'-' * 110}")
        for symbol in sorted(state.positions):
            position = state.positions[symbol]
            allocation_pct = (
                position.market_value / allocation_base * Decimal("100")
                if position.market_value is not None
                and allocation_base is not None
                and allocation_base != Decimal("0")
                else None
            )
            print(
                f"{position.symbol:>8} {str(position.shares):>12} "
                f"${position.avg_cost:>12,.2f} "
                f"{_money_or_unknown(position.last_price):>14} "
                f"{_money_or_unknown(position.market_value):>14} "
                f"{_money_or_unknown(position.unrealized_pnl):>14} "
                f"{_pct_or_unknown(position.unrealized_pnl_pct):>12} "
                f"{_pct_or_unknown(allocation_pct):>12}"
            )

    print("\n[止盈/止损预警摘要]")
    profit_alerts = []
    stop_alerts = []
    unknown_prices = []
    for symbol in sorted(state.positions):
        position = state.positions[symbol]
        pnl_pct = position.unrealized_pnl_pct
        if pnl_pct is None:
            unknown_prices.append(symbol)
        elif pnl_pct >= target_profit_pct:
            profit_alerts.append((symbol, pnl_pct))
        elif pnl_pct <= -stop_loss_pct:
            stop_alerts.append((symbol, pnl_pct))

    print(f"止盈阈值: +{target_profit_pct}%")
    print(f"止损阈值: -{stop_loss_pct}%")
    if profit_alerts:
        for symbol, pnl_pct in profit_alerts:
            print(f"达到止盈: {symbol} {_pct_or_unknown(pnl_pct)}")
    else:
        print("达到止盈: 无")
    if stop_alerts:
        for symbol, pnl_pct in stop_alerts:
            print(f"达到止损: {symbol} {_pct_or_unknown(pnl_pct)}")
    else:
        print("达到止损: 无")
    if unknown_prices:
        print("价格未知: " + ", ".join(unknown_prices))

    print("\n[今日关注事项]")
    if price_warnings:
        for warning in price_warnings:
            print(f"- 行情检查: {warning}")
    if stop_alerts:
        print("- 风险控制: 有持仓达到止损线，请人工复核。")
    if profit_alerts:
        print("- 收益管理: 有持仓达到止盈线，请人工复核。")
    if state.cash_status == "unknown":
        print("- 账户数据: 现金基线未知，总资产暂无法完整计算。")
    if not price_warnings and not stop_alerts and not profit_alerts:
        print("- 暂无重大预警，继续观察持仓与市场波动。")

    for warning in state.warnings:
        print(f"[提示] {warning}")
    print("\n只读日报：未修改文件，未连接券商，未自动交易。")


def show_daily_report(
    path: str | Path,
    *,
    provider: PriceProvider | None = None,
) -> bool:
    """生成每日持仓报告。"""

    try:
        state = get_portfolio_snapshot(path)
    except PortfolioError as exc:
        print(f"\n[错误] 日报无法读取持仓：{exc}")
        return False

    stop_loss_pct, target_profit_pct = load_report_settings(path)
    quotes: dict[str, PriceQuote] = {}
    price_warnings: tuple[str, ...] = ()
    if state.positions:
        prices, quotes, price_warnings = fetch_portfolio_quotes(
            sorted(state.positions),
            provider=provider,
        )
        if prices:
            state = apply_market_prices(state, prices)

    print_daily_report(
        state,
        stop_loss_pct,
        target_profit_pct,
        quotes=quotes,
        price_warnings=price_warnings,
    )
    return True


def show_product_dashboard(
    path: str | Path = DEFAULT_SCHEMA_PORTFOLIO_FILE,
    *,
    provider: PriceProvider | None = None,
) -> bool:
    """输出本地产品化 dashboard；只读、不交易。"""

    try:
        state = get_portfolio_snapshot(path)
    except PortfolioError as exc:
        print(f"\n[错误] Dashboard 无法读取持仓：{exc}")
        return False

    price_warnings: tuple[str, ...] = ()
    if state.positions:
        prices, _, price_warnings = fetch_portfolio_quotes(
            sorted(state.positions),
            provider=provider,
        )
        if prices:
            state = apply_market_prices(state, prices)

    print("\n=== 本地投资助手 Dashboard ===")
    print("\n[最新持仓]")
    if not state.positions:
        print("暂无持仓")
    else:
        for symbol in sorted(state.positions):
            position = state.positions[symbol]
            print(
                f"- {symbol}: {position.shares} 股，成本 ${position.avg_cost:,.2f}，"
                f"现价 {_money_or_unknown(position.last_price)}"
            )

    print("\n[最新 Cash]")
    print(f"现金: {_money_or_unknown(state.cash)}")
    print(f"购买力: {_money_or_unknown(state.buying_power)}")

    print("\n[今日盈亏]")
    print(f"未实现盈亏: {_money_or_unknown(state.total_unrealized_pnl)}")
    if price_warnings:
        for warning in price_warnings:
            print(f"[行情提示] {warning}")

    print("\n[最近3份 Reports]")
    reports = recent_reports(3)
    if not reports:
        print("暂无报告索引。")
    else:
        for item in reports:
            print(
                f"- {item.get('date', '未知日期')} | "
                f"{item.get('type', 'report')} | {item.get('file_path', '')}"
            )

    print("\n只读 Dashboard：未连接券商，未自动交易，未下单。")
    return True


def _check_excel_latest(excel_path: str | Path) -> tuple[bool, str]:
    path = Path(excel_path)
    if not path.is_file():
        return False, f"Excel 不存在：{path}"
    age_days = (time.time() - path.stat().st_mtime) / 86400
    if age_days > 7:
        return False, f"Excel 可能不是最新文件：{path.name}"
    return True, f"Excel 存在：{path.name}"


def _check_portfolio_synced(
    portfolio_path: str | Path,
    excel_path: str | Path,
) -> tuple[bool, str]:
    try:
        state = get_portfolio_snapshot(portfolio_path)
        excel_positions = parse_usmart_positions(excel_path)
    except Exception as exc:
        return False, f"持仓同步检查失败：{exc}"
    excel_map = {position.symbol: position for position in excel_positions}
    if set(state.positions) != set(excel_map):
        return False, "portfolio 与 Excel 股票列表不一致。"
    for symbol, position in state.positions.items():
        excel_position = excel_map[symbol]
        if position.shares != excel_position.shares or position.avg_cost != excel_position.avg_cost:
            return False, f"{symbol} 的股数或成本与 Excel 不一致。"
    return True, "portfolio 已与 Excel 持仓同步。"


def _check_json_valid(portfolio_path: str | Path) -> tuple[bool, str]:
    try:
        get_portfolio_snapshot(portfolio_path)
        json.loads(Path(portfolio_path).read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"JSON 损坏或 Schema 无效：{exc}"
    return True, "portfolio JSON 有效。"


def _check_tests_pass() -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True, "测试通过。"
    tail = "\n".join((result.stderr or result.stdout).splitlines()[-8:])
    return False, f"测试失败：\n{tail}"


def show_doctor(
    portfolio_path: str | Path = DEFAULT_SCHEMA_PORTFOLIO_FILE,
    excel_path: str | Path = DEFAULT_USMART_EXCEL_FILE,
    *,
    run_tests: bool = True,
) -> bool:
    """系统健康检查；只读、不交易。"""

    checks = [
        ("Excel 是否最新", _check_excel_latest(excel_path)),
        ("portfolio 是否同步", _check_portfolio_synced(portfolio_path, excel_path)),
        ("JSON 是否损坏", _check_json_valid(portfolio_path)),
    ]
    if run_tests:
        checks.append(("tests 是否通过", _check_tests_pass()))

    print("\n=== System Doctor ===")
    all_ok = True
    for title, (ok, message) in checks:
        all_ok = all_ok and ok
        status = "OK" if ok else "FAIL"
        print(f"[{status}] {title}: {message}")
    print("\n只读健康检查：未连接券商，未自动交易，未下单。")
    return all_ok


def main():
    parser = argparse.ArgumentParser(description="📊 美股研究系统 v1.0")
    sub = parser.add_subparsers(dest="command")

    # dashboard
    p = sub.add_parser("dashboard", help="本地产品 Dashboard")
    p.add_argument(
        "--portfolio-file",
        default=str(DEFAULT_SCHEMA_PORTFOLIO_FILE),
        help="Schema 1.1 持仓 JSON 文件路径",
    )

    # doctor
    p = sub.add_parser("doctor", help="系统健康检查")
    p.add_argument(
        "--portfolio-file",
        default=str(DEFAULT_SCHEMA_PORTFOLIO_FILE),
        help="Schema 1.1 持仓 JSON 文件路径",
    )
    p.add_argument(
        "--excel",
        default=str(DEFAULT_USMART_EXCEL_FILE),
        help="uSMART 持仓 Excel 文件路径",
    )
    p.add_argument("--skip-tests", action="store_true", help="跳过 unittest 检查")

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

    # report
    p = sub.add_parser("report", help="生成报告")
    p.add_argument("--daily", action="store_true", help="每日持仓报告")
    p.add_argument(
        "--portfolio-file",
        default=str(DEFAULT_SCHEMA_PORTFOLIO_FILE),
        help="Schema 1.1 持仓 JSON 文件路径",
    )

    # screener
    p = sub.add_parser("screener", help="只读股票筛选")
    p.add_argument("--watchlist", help="watchlist JSON 文件路径")

    # news
    p = sub.add_parser("news", help="只读新闻摘要")
    p.add_argument(
        "--portfolio-file",
        default=str(DEFAULT_SCHEMA_PORTFOLIO_FILE),
        help="Schema 1.1 持仓 JSON 文件路径",
    )
    p.add_argument(
        "--watchlist",
        default=str(ROOT / "watchlist.json"),
        help="watchlist JSON 文件路径",
    )

    # earnings
    p = sub.add_parser("earnings", help="只读财报关注")
    p.add_argument(
        "--portfolio-file",
        default=str(DEFAULT_SCHEMA_PORTFOLIO_FILE),
        help="Schema 1.1 持仓 JSON 文件路径",
    )
    p.add_argument(
        "--watchlist",
        default=str(ROOT / "watchlist.json"),
        help="watchlist JSON 文件路径",
    )

    # briefing
    p = sub.add_parser("briefing", help="每日统一简报")
    p.add_argument(
        "--portfolio-file",
        default=str(DEFAULT_SCHEMA_PORTFOLIO_FILE),
        help="Schema 1.1 持仓 JSON 文件路径",
    )
    p.add_argument(
        "--watchlist",
        default=str(ROOT / "watchlist.json"),
        help="watchlist JSON 文件路径",
    )
    p.add_argument("--ai", action="store_true", help="调用 LLM 生成 AI 简报")
    p.add_argument("--save", action="store_true", help="保存 AI 简报 Markdown")

    # morning
    p = sub.add_parser("morning", help="盘前 AI 简报")
    p.add_argument(
        "--portfolio-file",
        default=str(DEFAULT_SCHEMA_PORTFOLIO_FILE),
        help="Schema 1.1 持仓 JSON 文件路径",
    )
    p.add_argument(
        "--watchlist",
        default=str(ROOT / "watchlist.json"),
        help="watchlist JSON 文件路径",
    )
    p.add_argument("--save", action="store_true", help="保存盘前简报 Markdown")

    # evening
    p = sub.add_parser("evening", help="盘后复盘")
    p.add_argument(
        "--portfolio-file",
        default=str(DEFAULT_SCHEMA_PORTFOLIO_FILE),
        help="Schema 1.1 持仓 JSON 文件路径",
    )
    p.add_argument(
        "--watchlist",
        default=str(ROOT / "watchlist.json"),
        help="watchlist JSON 文件路径",
    )
    p.add_argument("--save", action="store_true", help="保存盘后复盘 Markdown")

    # sync-usmart
    p = sub.add_parser("sync-usmart", help="从 uSMART Excel 导入本地持仓")
    p.add_argument("excel_path", nargs="?", help="uSMART 持仓 Excel 文件路径")
    p.add_argument(
        "--excel",
        help="uSMART 持仓 Excel 文件路径",
    )
    p.add_argument(
        "--portfolio-file",
        default=str(DEFAULT_SCHEMA_PORTFOLIO_FILE),
        help="Schema 1.1 持仓 JSON 文件路径",
    )
    p.add_argument(
        "--cash",
        default=str(DEFAULT_USMART_CASH),
        help="可用现金",
    )
    p.add_argument("--buying-power", help="购买力；不填则保留现有值或使用现金")
    p.add_argument(
        "--no-legacy-sync",
        action="store_true",
        help="不同步更新旧版 portfolio.json",
    )

    # monitor
    p = sub.add_parser("monitor", help="持仓监控看板")
    p.add_argument("--daily", action="store_true", help="每日简报")
    p.add_argument("--alert", action="store_true", help="只看预警")
    p.add_argument("--add", action="store_true", help="录入买入")
    p.add_argument("--sell", type=str, help="卖出持仓")
    p.add_argument("--import-usmart", action="store_true", help="从uSMART导入")
    p.add_argument("--init", action="store_true", help="初始化示例持仓")
    p.add_argument(
        "--portfolio-file",
        default=str(DEFAULT_SCHEMA_PORTFOLIO_FILE),
        help="Schema 1.1 持仓 JSON 文件路径",
    )

    args = parser.parse_args()

    if args.command == "dashboard":
        show_product_dashboard(args.portfolio_file)

    elif args.command == "doctor":
        show_doctor(
            args.portfolio_file,
            args.excel,
            run_tests=not args.skip_tests,
        )

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

    elif args.command == "report":
        if args.daily:
            show_daily_report(args.portfolio_file)
        else:
            print("请使用: python main.py report --daily")

    elif args.command == "screener":
        cmd_args = []
        if args.watchlist:
            cmd_args += ["--watchlist", args.watchlist]
        run_script("screener.py", cmd_args)

    elif args.command == "news":
        show_news_overview(args.portfolio_file, args.watchlist)

    elif args.command == "earnings":
        show_earnings_overview(args.portfolio_file, args.watchlist)

    elif args.command == "briefing":
        if args.ai:
            show_ai_briefing(args.portfolio_file, args.watchlist, save_report=args.save)
        else:
            show_briefing(args.portfolio_file, args.watchlist)

    elif args.command == "morning":
        show_morning_briefing(
            args.portfolio_file,
            args.watchlist,
            save_report=args.save,
        )

    elif args.command == "evening":
        show_evening_briefing(
            args.portfolio_file,
            args.watchlist,
            save_report=args.save,
        )

    elif args.command == "sync-usmart":
        try:
            cash = Decimal(str(args.cash))
            buying_power = (
                Decimal(str(args.buying_power))
                if args.buying_power is not None
                else None
            )
            positions, backup_path, report_path = sync_usmart_excel(
                args.excel or args.excel_path or DEFAULT_USMART_EXCEL_FILE,
                args.portfolio_file,
                cash=cash,
                buying_power=buying_power,
                legacy_portfolio_path=None if args.no_legacy_sync else ROOT / "portfolio.json",
                reports_dir=ROOT / "reports",
            )
        except Exception as exc:
            print(f"\n[错误] uSMART 导入失败：{exc}")
        else:
            print_sync_summary(positions, backup_path, cash, report_path)

    elif args.command == "monitor":
        cmd_args = ["--portfolio-file", args.portfolio_file]
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
