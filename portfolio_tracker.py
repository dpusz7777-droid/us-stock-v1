# -*- coding: utf-8 -*-
"""Schema 1.1 持仓只读报告。

第一阶段只通过 portfolio_service 重建并显示持仓，不访问网络、不写入数据。

测试候选文件：
  python portfolio_tracker.py --portfolio-file portfolio_migrated_candidate.json

旧参数 --add、--sell、--sync、--config 已暂时禁用。
"""
import argparse
import json
import sys
sys.stdout.reconfigure(encoding="utf-8")
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from portfolio_service import PortfolioError, PortfolioState, get_portfolio_snapshot

# ── 文件路径 ──────────────────────────────────────────────
DATA_DIR = Path(__file__).parent
PORTFOLIO_FILE = DATA_DIR / "portfolio.json"
CONFIG_FILE = DATA_DIR / "portfolio_config.json"

# ── 默认配置 ──────────────────────────────────────────────
DEFAULT_CONFIG = {
    "total_capital": 5000.0,
    "currency": "USD",
    "max_single_position_pct": 20.0,  # 单股最大仓位
    "stop_loss_pct": 8.0,             # 默认止损比例
    "target_profit_pct": 25.0,        # 默认止盈比例
}


def load_portfolio() -> dict:
    if PORTFOLIO_FILE.exists():
        return json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
    return {"positions": [], "transactions": [], "created": datetime.now().isoformat()}


def save_portfolio(data: dict):
    PORTFOLIO_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict):
    CONFIG_FILE.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── 获取实时股价 ──────────────────────────────────────────
def fetch_prices(tickers: List[str]) -> Dict[str, float]:
    """从 yfinance 批量获取最新股价"""
    try:
        import yfinance as yf
    except ImportError:
        print("❌ 缺少 yfinance 库，请运行: pip install yfinance")
        return {}

    prices = {}
    for ticker in tickers:
        try:
            tk = yf.Ticker(ticker)
            info = tk.info
            price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
            if price:
                prices[ticker] = round(float(price), 2)
        except Exception:
            pass
    return prices


# ── 持仓计算 ──────────────────────────────────────────────
def calc_position_value(pos: dict, price: float) -> dict:
    """计算单个持仓的盈亏明细"""
    shares = pos["shares"]
    cost_basis = pos["avg_cost"]
    total_cost = shares * cost_basis
    market_value = shares * price
    pnl = market_value - total_cost
    pnl_pct = (pnl / total_cost * 100) if total_cost else 0.0
    return {
        "ticker": pos["ticker"],
        "shares": shares,
        "avg_cost": cost_basis,
        "current_price": price,
        "total_cost": round(total_cost, 2),
        "market_value": round(market_value, 2),
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
    }


def calc_portfolio_summary(portfolio: dict, prices: Dict[str, float]) -> dict:
    """计算投资组合总览"""
    total_cost = 0.0
    total_value = 0.0
    positions_detail = []

    for pos in portfolio.get("positions", []):
        t = pos["ticker"]
        price = prices.get(t, pos["avg_cost"])
        detail = calc_position_value(pos, price)
        positions_detail.append(detail)
        total_cost += detail["total_cost"]
        total_value += detail["market_value"]

    cash = portfolio.get("cash", 0.0)
    total_equity = total_value + cash
    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else 0.0

    return {
        "total_cost": round(total_cost, 2),
        "total_value": round(total_value, 2),
        "cash": round(cash, 2),
        "total_equity": round(total_equity, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "position_count": len(positions_detail),
        "positions": positions_detail,
        "updated": datetime.now().isoformat(),
    }


# ── 增删持仓 ──────────────────────────────────────────────
def add_position(portfolio: dict, ticker: str, shares: float, price: float, note: str = ""):
    """添加或增加持仓"""
    for pos in portfolio["positions"]:
        if pos["ticker"] == ticker.upper():
            # 加仓: 重新计算均价
            old_cost = pos["shares"] * pos["avg_cost"]
            new_cost = shares * price
            pos["shares"] += shares
            pos["avg_cost"] = round((old_cost + new_cost) / pos["shares"], 2)
            break
    else:
        portfolio["positions"].append({
            "ticker": ticker.upper(),
            "shares": shares,
            "avg_cost": price,
            "added": datetime.now().isoformat(),
        })

    portfolio["transactions"].append({
        "type": "buy",
        "ticker": ticker.upper(),
        "shares": shares,
        "price": price,
        "amount": round(shares * price, 2),
        "note": note,
        "timestamp": datetime.now().isoformat(),
    })
    save_portfolio(portfolio)
    print(f"✅ 已买入 {shares}股 {ticker.upper()} @ ${price:.2f}")


def remove_position(portfolio: dict, ticker: str, shares: float = None, note: str = ""):
    """卖出持仓（全部或部分）"""
    for pos in portfolio["positions"][:]:
        if pos["ticker"] == ticker.upper():
            sell_shares = shares if shares is not None else pos["shares"]
            if sell_shares >= pos["shares"]:
                portfolio["positions"].remove(pos)
            else:
                pos["shares"] -= sell_shares
            portfolio["transactions"].append({
                "type": "sell",
                "ticker": ticker.upper(),
                "shares": sell_shares,
                "price": 0,  # 需要传入实际卖出价
                "amount": 0,
                "note": note,
                "timestamp": datetime.now().isoformat(),
            })
            save_portfolio(portfolio)
            print(f"✅ 已卖出 {sell_shares}股 {ticker.upper()}")
            return
    print(f"⚠️ 未找到 {ticker.upper()} 的持仓")


# ── 报表输出 ──────────────────────────────────────────────
def print_summary(summary: dict):
    """打印持仓报表"""
    cfg = load_config()
    total = cfg["total_capital"]

    print(f"\n{'='*60}")
    print(f"  📊 投资组合报告")
    print(f"  🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    # 概览
    print(f"\n  💰 总资产: ${summary['total_equity']:,.2f}")
    print(f"     总本金: ${summary['total_cost']+summary['cash']:,.2f}")
    print(f"     持仓市值: ${summary['total_value']:,.2f}")
    print(f"     现金: ${summary['cash']:,.2f}")
    print(f"     总盈亏: ${summary['total_pnl']:+,.2f} ({summary['total_pnl_pct']:+.2f}%)")
    print(f"     仓位占比: {summary['total_value']/total*100:.1f}%")

    # 持仓明细
    if summary["positions"]:
        print(f"\n  {'─'*60}")
        print(f"  {'代码':>6} {'持股':>6} {'成本':>8} {'现价':>8} {'市值':>10} {'盈亏':>10} {'%':>8}")
        print(f"  {'─'*60}")
        for p in sorted(summary["positions"], key=lambda x: x["market_value"], reverse=True):
            print(f"  {p['ticker']:>6} {p['shares']:>6} ${p['avg_cost']:<6.2f} ", end="")
            print(f"${p['current_price']:<6.2f} ${p['market_value']:<8,.2f} ", end="")
            pnl_str = f"+${p['pnl']:<.2f}" if p['pnl'] >= 0 else f"-${abs(p['pnl']):<.2f}"
            print(f"{pnl_str} {p['pnl_pct']:+7.2f}%")

        # 盈亏排序
        best = max(summary["positions"], key=lambda x: x["pnl_pct"])
        worst = min(summary["positions"], key=lambda x: x["pnl_pct"])
        print(f"\n  🏆 最佳: {best['ticker']} ({best['pnl_pct']:+.2f}%)")
        print(f"  🚨 最差: {worst['ticker']} ({worst['pnl_pct']:+.2f}%)")

        # 止损预警
        print(f"\n  ⚠️  止损预警 (阈值 {cfg['stop_loss_pct']}%):")
        warned = False
        for p in summary["positions"]:
            if p["pnl_pct"] < -cfg["stop_loss_pct"]:
                print(f"     🔴 {p['ticker']}: {p['pnl_pct']:.2f}% 已跌破止损线!")
                warned = True
        if not warned:
            print(f"     ✅ 无预警")
    else:
        print(f"\n  📭 暂无持仓")

    print(f"\n{'='*60}")


# ── 交互式添加交易 ──────────────────────────────────────
def interactive_add():
    portfolio = load_portfolio()
    print("\n=== 添加买入交易 ===")
    ticker = input("股票代码: ").strip().upper()
    try:
        shares = float(input("买入股数: "))
        price = float(input("买入价格: "))
    except ValueError:
        print("❌ 请输入有效数字")
        return
    note = input("备注 (可选): ").strip()
    add_position(portfolio, ticker, shares, price, note)


def interactive_config():
    """配置资金参数"""
    cfg = load_config()
    print(f"\n当前总资金: ${cfg['total_capital']:,.0f}")
    try:
        val = input(f"输入新总资金 (直接回车不变): ").strip()
        if val:
            cfg["total_capital"] = float(val)
        save_config(cfg)
        print(f"✅ 已更新")
    except ValueError:
        print("❌ 无效数字")


# ── Schema 1.1 只读报告 ─────────────────────────────────

def print_schema_summary(state: PortfolioState):
    """显示统一服务返回的账户概览，不把未知值转换成 0。"""
    print(f"\n{'='*68}")
    print("  [Schema 1.1 持仓只读报告]")
    print(f"  Schema 版本: {state.schema_version}")
    print(f"  持仓数量: {len(state.positions)}")
    print(f"  持仓总成本: ${state.total_cost_basis:,.2f}")
    print(f"  追踪期内已实现盈亏: ${state.realized_pnl:,.2f}")

    if state.cash_status == "unknown":
        print("  现金: 未知")
        print("  总资产: 无法计算")
        print("  购买力: 无法计算")
    else:
        cash_text = "未知" if state.cash is None else f"${state.cash:,.2f}"
        equity_text = (
            "无法计算" if state.total_equity is None else f"${state.total_equity:,.2f}"
        )
        buying_power_text = (
            "无法计算" if state.buying_power is None else f"${state.buying_power:,.2f}"
        )
        print(f"  现金: {cash_text}")
        print(f"  总资产: {equity_text}")
        print(f"  购买力: {buying_power_text}")

    for warning in state.warnings:
        print(f"  [提示] {warning}")
    print(f"{'='*68}")


def print_schema_positions(state: PortfolioState):
    """显示 Schema 1.1 运行时持仓，不请求实时行情。"""
    if not state.positions:
        print("\n  暂无持仓")
        return

    print(
        f"\n  {'代码':>8} {'股数':>12} {'平均成本':>14} "
        f"{'持仓成本':>16} {'已实现盈亏':>16}"
    )
    print(f"  {'-'*72}")
    for symbol in sorted(state.positions):
        position = state.positions[symbol]
        print(
            f"  {position.symbol:>8} "
            f"{str(position.shares):>12} "
            f"${position.avg_cost:>12,.2f} "
            f"${position.cost_basis:>14,.2f} "
            f"${position.realized_pnl:>14,.2f}"
        )


def print_read_only_notice():
    """拦截仍依赖旧快照结构的修改和联网操作。"""
    print("\n[已阻止] Schema 1.1 第一阶段仅支持只读查看。")
    print("--add、--sell、--sync 和 --config 尚未迁移到 transactions 模式。")
    print("本次没有访问网络，也没有修改任何持仓或配置数据。")


# ── 主入口 ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Schema 1.1 持仓只读报告")
    parser.add_argument("--portfolio-file", default=str(PORTFOLIO_FILE), help="持仓 JSON 文件路径")
    parser.add_argument("--add", action="store_true", help="暂时禁用：添加买入交易")
    parser.add_argument("--sell", type=str, help="暂时禁用：卖出持仓")
    parser.add_argument("--sync", action="store_true", help="暂时禁用：联网刷新股价")
    parser.add_argument("--config", action="store_true", help="暂时禁用：修改资金配置")
    args = parser.parse_args()

    # 旧操作会修改 positions/cash 快照或访问网络，第一阶段全部禁止。
    if args.add or args.sell is not None or args.sync or args.config:
        print_read_only_notice()
        return

    try:
        state = get_portfolio_snapshot(args.portfolio_file)
    except PortfolioError as exc:
        print(f"\n[错误] 持仓数据无法读取：{exc}")
        print("请使用 Schema 1.1 文件，或通过 --portfolio-file 明确指定候选文件。")
        return

    print_schema_summary(state)
    print_schema_positions(state)
    print("\n只读模式：未访问网络，未调用 yfinance，未写入任何文件。")


if __name__ == "__main__":
    main()
