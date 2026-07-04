# -*- coding: utf-8 -*-
"""
每日看盘仪表盘 - 大盘指数、板块轮动、热点扫描

用法:
  python market_dashboard.py                    # 完整看盘
  python market_dashboard.py --quick            # 快速扫一眼
  python market_dashboard.py --sector           # 板块轮动
"""
import argparse
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import sys
sys.stdout.reconfigure(encoding="utf-8")

# ── 关键指数 ──────────────────────────────────────────────
INDEX_TICKERS = {
    "^IXIC":   "纳斯达克综合指数",
    "^DJI":    "道琼斯工业指数",
    "^GSPC":   "标普500指数",
    "^VIX":    "VIX恐慌指数",
    "^RUT":    "罗素2000小盘股",
    "SOXX":    "费城半导体指数",
    "QQQ":     "纳斯达克100 ETF",
    "SPY":     "标普500 ETF",
    "IWM":     "罗素2000 ETF",
}

# ── 热门观察股票 ─────────────────────────────────────────
WATCH_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    "AMD", "AVGO", "TSM", "LLY", "JPM", "V", "COST", "PLTR",
]


def fetch_data(tickers: List[str]) -> Dict[str, Dict]:
    """批量获取行情数据"""
    try:
        import yfinance as yf
    except ImportError:
        print("❌ 缺少 yfinance，请运行: pip install yfinance")
        return {}

    results = {}
    for ticker in tickers:
        try:
            tk = yf.Ticker(ticker)
            info = tk.info
            price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
            prev_close = info.get("previousClose")
            chg = None
            chg_pct = None
            if price and prev_close:
                chg = price - prev_close
                chg_pct = (chg / prev_close) * 100
            results[ticker] = {
                "price": round(float(price), 2) if price else None,
                "change": round(float(chg), 2) if chg else None,
                "change_pct": round(float(chg_pct), 2) if chg_pct else None,
                "name": info.get("shortName") or info.get("longName") or ticker,
                "volume": info.get("volume"),
                "avg_vol": info.get("averageVolume"),
            }
        except Exception:
            pass
        time.sleep(0.2)
    return results


# ── 打印模块 ──────────────────────────────────────────────

def print_market_overview(data: Dict[str, Dict]):
    """大盘概览"""
    print(f"\n{'█'*60}")
    print(f"  📊 美股大盘概览")
    print(f"  🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')} (美东时间)")
    print(f"{'█'*60}")

    print(f"\n  {'指数':<20} {'最新价':>10} {'涨跌':>10} {'涨跌幅':>10}")
    print(f"  {'─'*55}")
    for ticker, name in INDEX_TICKERS.items():
        d = data.get(ticker)
        if d and d["price"]:
            chg_str = f"+{d['change']}" if d['change'] and d['change'] >= 0 else str(d['change'] or "?")
            pct_str = f"+{d['change_pct']}%" if d['change_pct'] and d['change_pct'] >= 0 else f"{d['change_pct']}%" if d['change_pct'] else "?"
            print(f"  {name:<20} ${d['price']:<8,.2f} {chg_str:>8} {pct_str:>8}")
        else:
            print(f"  {name:<20} {'N/A':>10}")


def print_top_movers(data: Dict[str, Dict], tickers: List[str]):
    """热门股票涨跌"""
    stocks = [(t, data[t]) for t in tickers if t in data and data[t].get("price")]
    stocks.sort(key=lambda x: x[1].get("change_pct") or 0, reverse=True)
    gainers = [s for s in stocks if s[1].get("change_pct", 0) > 0][:5]
    losers = [s for s in stocks if s[1].get("change_pct", 0) < 0][-5:]
    losers.reverse()

    print(f"\n  {'─'*60}")
    print(f"  🔥 热门股票涨跌")
    print(f"  {'─'*60}")
    print(f"  {'代码':>6} {'最新价':>8} {'涨跌幅':>10} {'成交额':>12}")
    print(f"  {'─'*45}")
    
    all_sorted = sorted(stocks, key=lambda x: abs(x[1].get("change_pct", 0) or 0), reverse=True)
    for t, d in all_sorted[:10]:
        pct = d["change_pct"]
        vol_str = ""
        if d.get("volume") and d.get("avg_vol"):
            ratio = d["volume"] / d["avg_vol"]
            if ratio > 2:
                vol_str = "🔥放量"
            elif ratio > 1.5:
                vol_str = "📈增量"
        color = "🟢" if pct and pct > 2 else ("🔴" if pct and pct < -2 else "⚪")
        pct_str = f"+{pct}%" if pct and pct >= 0 else f"{pct}%" if pct else "?"
        print(f"  {color} {t:>6} ${d['price']:<6,.2f} {pct_str:>9} {vol_str:>10}")


def print_market_breadth(data: Dict[str, Dict]):
    """市场宽度"""
    up = sum(1 for d in data.values() if d.get("change_pct") and d["change_pct"] > 0)
    down = sum(1 for d in data.values() if d.get("change_pct") and d["change_pct"] < 0)
    flat = sum(1 for d in data.values() if d.get("change_pct") == 0)
    total = up + down + flat

    if total > 0:
        print(f"\n  📈 市场宽度 (扫描{total}只): 涨{up} 跌{down} 平{flat}")
        ratio = up / down if down > 0 else float("inf")
        if ratio > 2:
            print(f"     市场情绪: 🟢 乐观 (涨跌比 {ratio:.1f})")
        elif ratio > 1:
            print(f"     市场情绪: 🟡 偏多 (涨跌比 {ratio:.1f})")
        elif ratio > 0.5:
            print(f"     市场情绪: 🟠 偏空 (涨跌比 {ratio:.1f})")
        else:
            print(f"     市场情绪: 🔴 悲观 (涨跌比 {ratio:.1f})")


def print_sector_performance(data: Dict[str, Dict]):
    """板块表现（简版，基于个股归类）"""
    sector_map = {}
    try:
        import yfinance as yf
        for ticker, d in data.items():
            if not d.get("price"):
                continue
            try:
                info = yf.Ticker(ticker).info
                sector = info.get("sector", "其他")
                if sector not in sector_map:
                    sector_map[sector] = {"count": 0, "sum_pct": 0.0}
                sector_map[sector]["count"] += 1
                if d.get("change_pct"):
                    sector_map[sector]["sum_pct"] += d["change_pct"]
            except Exception:
                pass
            time.sleep(0.1)
    except ImportError:
        return

    if sector_map:
        print(f"\n  {'─'*60}")
        print(f"  🏭 板块表现")
        print(f"  {'─'*60}")
        sectors = sorted(sector_map.items(), key=lambda x: x[1]["sum_pct"]/x[1]["count"], reverse=True)
        for sector, sdata in sectors:
            avg = sdata["sum_pct"] / sdata["count"]
            icon = "🟢" if avg > 0.5 else ("🔴" if avg < -0.5 else "⚪")
            print(f"  {icon} {sector:<20} {avg:+.2f}%")


def generate_tip(vix_data: Optional[Dict]):
    """综合建议"""
    tips = []
    
    if vix_data and vix_data.get("price"):
        vix = vix_data["price"]
        if vix > 30:
            tips.append("🔴 VIX > 30: 市场恐慌，建议减仓避险")
        elif vix > 20:
            tips.append("🟡 VIX > 20: 市场波动加大，谨慎操作")
        else:
            tips.append("🟢 VIX < 20: 市场情绪平稳")

    print(f"\n  {'─'*60}")
    print(f"  💡 综合建议")
    print(f"  {'─'*60}")
    for t in tips:
        print(f"  {t}")
    if not tips:
        print(f"  数据不足，无法生成建议")


# ── 主入口 ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="美股每日看盘仪表盘")
    parser.add_argument("--quick", action="store_true", help="快速模式：只看指数")
    parser.add_argument("--sector", action="store_true", help="板块表现")
    args = parser.parse_args()

    print(f"\n⏳ 正在获取市场数据...")

    all_tickers = list(INDEX_TICKERS.keys())
    if not args.quick:
        all_tickers += WATCH_TICKERS

    data = fetch_data(all_tickers)

    print_market_overview(data)

    if args.sector:
        print_sector_performance(data)

    if not args.quick:
        print_top_movers(data, WATCH_TICKERS)
        print_market_breadth(data)

    generate_tip(data.get("^VIX"))

    print(f"\n{'='*60}")
    print(f"  ⚡ 快速操作:")
    print(f"    python market_dashboard.py              完整看盘")
    print(f"    python market_dashboard.py --quick       只看指数")
    print(f"    python market_dashboard.py --sector      板块轮动")
    print(f"    python stock_analyzer.py AAPL           分析个股")
    print(f"    python portfolio_tracker.py             查看持仓")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
