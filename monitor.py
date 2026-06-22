# -*- coding: utf-8 -*-
"""Schema 1.1 持仓只读看板。

第一阶段只通过 portfolio_service 重建和显示持仓，不访问网络、不写入数据。

测试候选文件：
  python monitor.py --portfolio-file portfolio_migrated_candidate.json

旧写入参数 --add、--sell、--import-usmart、--init 已暂时禁用。
"""
import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from portfolio_service import PortfolioError, PortfolioState, get_portfolio_snapshot

sys.stdout.reconfigure(encoding="utf-8")

DATA_DIR = Path(__file__).parent
PORTFOLIO_FILE = DATA_DIR / "portfolio.json"
CONFIG_FILE = DATA_DIR / "portfolio_config.json"
HISTORY_FILE = DATA_DIR / "portfolio_history.json"
USMART_FILE = DATA_DIR / "usmart_holdings.json"


# ═══════════════════════════════════════════════════════════
#  数据层
# ═══════════════════════════════════════════════════════════

def load_json(path: Path, default=None):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default if default else {}


def save_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_portfolio() -> dict:
    return load_json(PORTFOLIO_FILE, {"positions": [], "transactions": [], "cash": 5000.0, "created": datetime.now().isoformat()})


def load_config() -> dict:
    cfg = load_json(CONFIG_FILE)
    if not cfg:
        cfg = {"total_capital": 5000.0, "currency": "USD", "stop_loss_pct": 8.0, "target_profit_pct": 25.0}
        save_json(CONFIG_FILE, cfg)
    return cfg


def save_portfolio(data):
    save_json(PORTFOLIO_FILE, data)


def load_history() -> list:
    return load_json(HISTORY_FILE, [])


def save_history(records: list):
    save_json(HISTORY_FILE, records)


# ═══════════════════════════════════════════════════════════
#  行情获取
# ═══════════════════════════════════════════════════════════

def fetch_prices(tickers: list) -> Dict[str, dict]:
    """批量获取股价 + 涨跌幅 + 日内变动"""
    try:
        import yfinance as yf
    except ImportError:
        print("[!] 请先安装: pip install yfinance")
        return {}

    data = {}
    for t in tickers:
        try:
            tk = yf.Ticker(t)
            info = tk.info
            price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
            prev = info.get("previousClose")
            day_high = info.get("dayHigh")
            day_low = info.get("dayLow")
            vol = info.get("volume", 0)
            data[t] = {
                "price": round(float(price), 2) if price else None,
                "prev_close": round(float(prev), 2) if prev else None,
                "day_high": round(float(day_high), 2) if day_high else None,
                "day_low": round(float(day_low), 2) if day_low else None,
                "volume": int(vol) if vol else 0,
            }
        except Exception:
            pass
        time.sleep(0.3)
    return data


# ═══════════════════════════════════════════════════════════
#  持仓计算
# ═══════════════════════════════════════════════════════════

def calc_positions(portfolio: dict, market_data: dict) -> list:
    """计算所有持仓的实时盈亏"""
    results = []
    for pos in portfolio.get("positions", []):
        t = pos["ticker"]
        md = market_data.get(t, {})
        price = md.get("price") or pos["avg_cost"]
        shares = pos["shares"]
        cost_basis = pos["avg_cost"]
        total_cost = shares * cost_basis
        market_value = shares * price
        pnl = market_value - total_cost
        pnl_pct = (pnl / total_cost * 100) if total_cost else 0.0
        day_chg = 0.0
        day_chg_pct = 0.0
        if md.get("prev_close") and price:
            day_chg = price - md["prev_close"]
            day_chg_pct = (day_chg / md["prev_close"]) * 100

        results.append({
            "ticker": t,
            "shares": shares,
            "avg_cost": cost_basis,
            "price": price,
            "prev_close": md.get("prev_close"),
            "day_change": round(day_chg, 2),
            "day_change_pct": round(day_chg_pct, 2),
            "total_cost": round(total_cost, 2),
            "market_value": round(market_value, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "day_high": md.get("day_high"),
            "day_low": md.get("day_low"),
            "volume": md.get("volume", 0),
        })
    return results


def calc_summary(positions: list, cash: float, total_capital: float) -> dict:
    """组合总览"""
    total_cost = sum(p["total_cost"] for p in positions)
    total_value = sum(p["market_value"] for p in positions)
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
        "position_count": len(positions),
        "used_ratio": round(total_value / total_capital * 100, 1),
    }


# ═══════════════════════════════════════════════════════════
#  看板输出
# ═══════════════════════════════════════════════════════════

def print_banner():
    now = datetime.now()
    print(f"\n{'='*60}")
    print(f"  [持仓监控] {now.strftime('%Y-%m-%d %H:%M')}")
    print(f"  NYSE/NASDAQ 交易时段: 09:30-16:00 ET")
    print(f"{'='*60}")


def print_summary(positions: list, summary: dict, config: dict):
    """打印概览"""
    total = config["total_capital"]
    pnl_color = "+" if summary["total_pnl"] >= 0 else ""
    print(f"\n  总资产: ${summary['total_equity']:>8,.2f}")
    print(f"  本金:   ${total:>8,.2f}")
    print(f"  持仓:   ${summary['total_value']:>8,.2f}  ({summary['used_ratio']}%)")
    print(f"  现金:   ${summary['cash']:>8,.2f}")
    print(f"  总盈亏: {pnl_color}${summary['total_pnl']:>8,.2f}  ({pnl_color}{summary['total_pnl_pct']:+.2f}%)")

    # 风险指标
    if positions:
        max_pos = max(positions, key=lambda p: p["market_value"])
        max_pct = max_pos["market_value"] / total * 100
        print(f"\n  [风险指标]")
        print(f"    最大仓位: {max_pos['ticker']} {max_pct:.1f}% (限20%)")
        if max_pct > 20:
            print(f"    [!] 仓位超限! 建议减仓")
        print(f"    持仓数量: {len(positions)}只")


def print_positions(positions: list, config: dict):
    """打印持仓明细"""
    if not positions:
        print(f"\n  (空仓)")
        return

    print(f"\n  {'代码':>6} {'持股':>6} {'成本价':>8} {'现价':>8}", end="")
    print(f" {'日涨跌':>8} {'浮动盈亏':>10} {'%':>8} {'仓位':>6}")
    print(f"  {'-'*65}")

    sorted_pos = sorted(positions, key=lambda p: p["market_value"], reverse=True)
    total_val = sum(p["market_value"] for p in sorted_pos)

    for p in sorted_pos:
        ticker = p["ticker"]
        day_str = f"+{p['day_change']:.2f}" if p['day_change'] >= 0 else f"{p['day_change']:.2f}"
        pnl_str = f"+${p['pnl']:<.2f}" if p['pnl'] >= 0 else f"-${abs(p['pnl']):<.2f}"
        pos_pct = p["market_value"] / total_val * 100 if total_val else 0

        # 日涨跌颜色标识
        day_indicator = ""
        if p["day_change_pct"] > 2:
            day_indicator = " ++"
        elif p["day_change_pct"] < -2:
            day_indicator = " --"

        print(f"  {ticker:>6} {p['shares']:>6}  ${p['avg_cost']:<6.2f} ${p['price']:<6.2f}", end="")
        print(f" {day_str:>8}{day_indicator} {pnl_str:>10} {p['pnl_pct']:+8.2f}% {pos_pct:>5.1f}%")


def print_alerts(positions: list, config: dict):
    """打印预警"""
    stop_loss = config.get("stop_loss_pct", 8)
    target = config.get("target_profit_pct", 25)

    alerts = []
    for p in positions:
        if p["pnl_pct"] < -stop_loss:
            alerts.append(("CRITICAL", f"{p['ticker']} 亏损 {p['pnl_pct']:.1f}% (止损线{stop_loss}%) 建议立即执行止损!"))
        elif p["pnl_pct"] > target:
            alerts.append(("PROFIT", f"{p['ticker']} 盈利 {p['pnl_pct']:.1f}% (止盈线{target}%) 考虑分批止盈"))
        elif p["pnl_pct"] < 0:
            alerts.append(("WARN", f"{p['ticker']} 浮亏 {p['pnl_pct']:.1f}% 距离止损还有 {abs(p['pnl_pct']+stop_loss):.1f}%"))

    print(f"\n  [预警] (止损={stop_loss}%, 止盈={target}%)")
    if not alerts:
        print(f"    一切正常，无预警")
    else:
        for level, msg in alerts:
            tag = "[!]" if level == "CRITICAL" else ("[+]" if level == "PROFIT" else "[?]")
            print(f"    {tag} {msg}")


def print_daily_change(positions: list):
    """日内变动"""
    if not positions:
        return
    day_pnl = sum(p.get("day_change", 0) * p["shares"] for p in positions)
    day_pnl_pct = 0
    total_val = sum(p["market_value"] for p in positions)
    if total_val:
        day_pnl_pct = day_pnl / (total_val - day_pnl) * 100 if total_val != day_pnl else 0

    up = sum(1 for p in positions if p.get("day_change_pct", 0) > 0)
    down = sum(1 for p in positions if p.get("day_change_pct", 0) < 0)

    color = "+" if day_pnl >= 0 else ""
    print(f"\n  [日内变动]  ${color}{day_pnl:>+,.2f}  ({color}{day_pnl_pct:+.2f}%)")
    print(f"    上涨: {up}只  下跌: {down}只")


def print_market_context():
    """简版大盘参考"""
    indices = {"^IXIC": "纳斯达克", "^DJI": "道指", "^GSPC": "标普", "^VIX": "VIX"}
    try:
        import yfinance as yf
        print(f"\n  [大盘参考]")
        for t, name in indices.items():
            tk = yf.Ticker(t)
            info = tk.info
            price = info.get("regularMarketPrice") or info.get("previousClose")
            prev = info.get("previousClose")
            if price and prev:
                chg = (price - prev) / prev * 100
                print(f"    {name}: {price:.0f}  ({chg:+.2f}%)")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
#  交易录入
# ═══════════════════════════════════════════════════════════

def cmd_buy():
    """交互式买入"""
    pf = load_portfolio()
    print(f"\n== 买入 ==")
    t = input("代码: ").strip().upper()
    try:
        s = float(input("股数: "))
        p = float(input("价格: "))
    except ValueError:
        print("无效数字")
        return

    # 检查余额
    total_cost = s * p
    if total_cost > pf.get("cash", 0):
        print(f"现金不足! 需${total_cost:.2f}, 余额${pf['cash']:.2f}")
        return

    # 检查集中度
    cfg = load_config()
    max_pos = cfg["total_capital"] * 0.20
    for pos in pf["positions"]:
        if pos["ticker"] == t:
            new_total = (pos["shares"] + s) * ((pos["shares"]*pos["avg_cost"] + s*p) / (pos["shares"] + s))
            if new_total > max_pos:
                print(f"加仓后仓位可能超限(>{max_pos:.0f})，确认?(y/n)")
                if input().lower() != "y":
                    return

    # 执行
    for pos in pf["positions"]:
        if pos["ticker"] == t:
            old_cost = pos["shares"] * pos["avg_cost"]
            pos["shares"] += s
            pos["avg_cost"] = round((old_cost + total_cost) / pos["shares"], 2)
            break
    else:
        pf["positions"].append({"ticker": t, "shares": s, "avg_cost": p, "added": datetime.now().isoformat()})

    pf["cash"] = round(pf["cash"] - total_cost, 2)
    pf.setdefault("transactions", []).append({
        "type": "buy", "ticker": t, "shares": s, "price": p,
        "amount": round(total_cost, 2), "timestamp": datetime.now().isoformat()
    })
    save_portfolio(pf)
    print(f"  已买入 {s}股 {t} @ ${p:.2f}, 花费${total_cost:.2f}")
    print(f"  剩余现金: ${pf['cash']:.2f}")


def cmd_sell(ticker: str):
    """卖出持仓"""
    pf = load_portfolio()
    for pos in pf["positions"][:]:
        if pos["ticker"] == ticker.upper():
            print(f"\n当前持仓: {pos['shares']}股, 均价${pos['avg_cost']:.2f}")
            try:
                s = float(input(f"卖出股数 (回车=全部, 最大{pos['shares']}): ") or pos["shares"])
                p = float(input("卖出价格: "))
            except ValueError:
                print("无效数字")
                return
            s = min(s, pos["shares"])
            proceed = s * p
            if s >= pos["shares"]:
                pf["positions"].remove(pos)
            else:
                pos["shares"] -= s
            pf["cash"] = round(pf["cash"] + proceed, 2)
            pf.setdefault("transactions", []).append({
                "type": "sell", "ticker": ticker.upper(), "shares": s, "price": p,
                "amount": round(proceed, 2), "timestamp": datetime.now().isoformat()
            })
            save_portfolio(pf)
            print(f"  已卖出 {s}股 {ticker.upper()} @ ${p:.2f}, 入账${proceed:.2f}")
            print(f"  剩余现金: ${pf['cash']:.2f}")
            return
    print(f"未找到 {ticker.upper()} 的持仓")


def cmd_import_usmart():
    """从uSMART导入持仓"""
    usmart = load_json(USMART_FILE)
    holdings = usmart.get("holdings", [])
    if not holdings:
        print("uSMART持仓为空，请先运行 抓取机器人.py 获取持仓数据")
        return

    pf = load_portfolio()
    imported = 0
    for h in holdings:
        ticker = h.get("ticker", "").upper()
        shares = float(h.get("shares", 0))
        price = float(h.get("price", 0))
        if ticker and shares > 0 and price > 0:
            for pos in pf["positions"]:
                if pos["ticker"] == ticker:
                    break
            else:
                pf["positions"].append({
                    "ticker": ticker, "shares": shares, "avg_cost": price,
                    "added": datetime.now().isoformat()
                })
                imported += 1

    if imported:
        save_portfolio(pf)
        print(f"已从uSMART导入 {imported} 只持仓")
    else:
        print("没有新持仓可导入")


# ═══════════════════════════════════════════════════════════
#  Schema 1.1 只读看板
# ═══════════════════════════════════════════════════════════

def print_schema_summary(state: PortfolioState):
    """显示统一服务计算出的账户概览，不把未知值伪装成 0。"""
    print(f"\n{'='*60}")
    print("  [Schema 1.1 持仓只读看板]")
    print(f"  Schema 版本: {state.schema_version}")
    print(f"  持仓数量: {len(state.positions)}")
    print(f"  持仓总成本: ${state.total_cost_basis:,.2f}")

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
    print(f"{'='*60}")


def print_schema_positions(state: PortfolioState):
    """显示 shares、avg_cost 和 cost_basis，不请求实时行情。"""
    if not state.positions:
        print("\n  暂无持仓")
        return

    print(f"\n  {'代码':>8} {'股数':>12} {'平均成本':>14} {'持仓成本':>16}")
    print(f"  {'-'*56}")
    for symbol in sorted(state.positions):
        position = state.positions[symbol]
        print(
            f"  {position.symbol:>8} "
            f"{str(position.shares):>12} "
            f"${position.avg_cost:>12,.2f} "
            f"${position.cost_basis:>14,.2f}"
        )


def print_read_only_notice():
    """解释为什么旧写入操作在 Schema 1.1 第一阶段被阻止。"""
    print("\n[已阻止] Schema 1.1 第一阶段仅支持只读查看。")
    print("--add、--sell、--import-usmart 和 --init 尚未迁移到 transactions 写入模式。")
    print("本次没有修改任何持仓数据。")


# ═══════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Schema 1.1 持仓只读监控")
    parser.add_argument("--portfolio-file", default=str(PORTFOLIO_FILE), help="持仓 JSON 文件路径")
    parser.add_argument("--daily", action="store_true", help="只读概览（第一阶段与默认显示相同）")
    parser.add_argument("--alert", action="store_true", help="价格预警（第一阶段暂不可用）")
    parser.add_argument("--add", action="store_true", help="暂时禁用：添加买入")
    parser.add_argument("--sell", type=str, help="暂时禁用：卖出持仓")
    parser.add_argument("--import-usmart", action="store_true", help="暂时禁用：从uSMART导入")
    parser.add_argument("--init", action="store_true", help="暂时禁用：初始化示例持仓")
    args = parser.parse_args()

    # 所有旧写入逻辑仍基于 positions/cash 快照，第一阶段一律禁止调用。
    if args.add or args.sell is not None or args.import_usmart or args.init:
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

    if args.alert:
        print("\n[提示] 第一阶段尚未接入行情，无法计算价格、止损或止盈预警。")

    print("\n只读模式：未访问网络，未调用 yfinance，未写入任何文件。")


def save_daily_snapshot(summary: dict, cash: float):
    """记录每日快照用于趋势分析"""
    records = load_history()
    today = datetime.now().strftime("%Y-%m-%d")
    if not records or records[-1]["date"] != today:
        records.append({
            "date": today,
            "equity": summary["total_equity"],
            "value": summary["total_value"],
            "cash": cash,
            "pnl": summary["total_pnl"],
            "timestamp": datetime.now().isoformat(),
        })
        save_history(records)


def init_sample_portfolio():
    """初始化示例持仓用于测试"""
    pf = {
        "positions": [
            {"ticker": "NVDA", "shares": 5, "avg_cost": 195.50, "added": "2026-06-15T10:00:00"},
            {"ticker": "MSFT", "shares": 3, "avg_cost": 385.00, "added": "2026-06-16T10:00:00"},
            {"ticker": "AAPL", "shares": 4, "avg_cost": 290.00, "added": "2026-06-17T10:00:00"},
        ],
        "cash": 1500.0,
        "transactions": [],
        "created": datetime.now().isoformat(),
    }
    save_portfolio(pf)
    print("示例持仓已初始化: NVDA x5, MSFT x3, AAPL x4")
    print(f"现金: ${pf['cash']:.2f}, 总资金: $5,000")


if __name__ == "__main__":
    main()
