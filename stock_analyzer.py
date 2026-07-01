# -*- coding: utf-8 -*-
"""
个股深度分析引擎 - 多维度评分 + 估值判断 + 技术信号

用法:
  python stock_analyzer.py AAPL                  # 单只分析
  python stock_analyzer.py AAPL MSFT NVDA        # 批量分析
  python stock_analyzer.py --watchlist            # 分析观察名单
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

# 兼容 exec 调用
try:
    __file__
except NameError:
    __file__ = r"e:\美股研究文件夹\stock_analyzer.py"

DATA_DIR = Path(__file__).parent
WATCHLIST_FILE = DATA_DIR / "watchlist.json"


# ═══════════════════════════════════════════════════════════
#  评分权重配置
# ═══════════════════════════════════════════════════════════
SCORE_WEIGHTS = {
    "估值": 0.20,        # PE/PB相对行业位置
    "盈利能力": 0.20,     # ROE、毛利率、净利率
    "成长性": 0.20,      # 收入/利润增长率
    "财务健康": 0.15,    # 负债率、流动比率
    "动量": 0.10,        # 近期价格走势
    "机构情绪": 0.10,    # 机构持仓变化
    "流动性": 0.05,      # 日均成交额
}


# ═══════════════════════════════════════════════════════════
#  数据获取
# ═══════════════════════════════════════════════════════════
def fetch_stock_data(ticker: str) -> Optional[Dict]:
    """从 yfinance 获取完整的股票基本面数据"""
    try:
        import yfinance as yf
    except ImportError:
        print("❌ 缺少 yfinance，请运行: pip install yfinance")
        return None

    try:
        tk = yf.Ticker(ticker)
        info = tk.info
        return info
    except Exception as e:
        print(f"❌ 获取 {ticker} 数据失败: {e}")
        return None


# ═══════════════════════════════════════════════════════════
#  各维度评分函数 (每项返回 0-100)
# ═══════════════════════════════════════════════════════════

def score_valuation(info: Dict) -> Tuple[float, str]:
    """估值评分：PE vs 行业PE"""
    pe = info.get("trailingPE") or info.get("forwardPE")
    sector_pe = info.get("sectorPE") or 25

    if not pe or pe <= 0:
        return 50, "无PE数据"

    ratio = pe / sector_pe
    if ratio < 0.5:
        return 90, f"严重低估 (PE={pe:.1f}, 行业={sector_pe})"
    elif ratio < 0.8:
        return 75, f"偏低 (PE={pe:.1f}, 行业={sector_pe})"
    elif ratio < 1.2:
        return 60, f"合理 (PE={pe:.1f}, 行业={sector_pe})"
    elif ratio < 1.8:
        return 40, f"偏高 (PE={pe:.1f}, 行业={sector_pe})"
    else:
        return 25, f"严重高估 (PE={pe:.1f}, 行业={sector_pe})"


def score_profitability(info: Dict) -> Tuple[float, str]:
    """盈利能力评分：ROE + 毛利率 + 净利率"""
    roe = info.get("returnOnEquity")
    gross_margin = info.get("grossMargins")
    net_margin = info.get("profitMargins")

    score = 50
    details = []

    if roe:
        r = roe * 100
        if r > 30:
            score += 20
            details.append(f"ROE={r:.1f}%优秀")
        elif r > 15:
            score += 10
            details.append(f"ROE={r:.1f}%良好")
        elif r > 5:
            details.append(f"ROE={r:.1f}%一般")
        else:
            score -= 10
            details.append(f"ROE={r:.1f}%较差")

    if gross_margin:
        gm = gross_margin * 100
        if gm > 60:
            score += 15
            details.append(f"毛利率={gm:.1f}%优秀")
        elif gm > 40:
            score += 8
            details.append(f"毛利率={gm:.1f}%良好")
        else:
            details.append(f"毛利率={gm:.1f}%一般")

    if net_margin:
        nm = net_margin * 100
        if nm > 20:
            score += 15
            details.append(f"净利率={nm:.1f}%优秀")
        elif nm > 10:
            score += 8
            details.append(f"净利率={nm:.1f}%良好")
        elif nm > 0:
            details.append(f"净利率={nm:.1f}%盈利")
        else:
            score -= 15
            details.append(f"净利率={nm:.1f}%亏损")

    return min(100, max(0, score)), " | ".join(details)


def score_growth(info: Dict) -> Tuple[float, str]:
    """成长性评分：收入/利润增长率"""
    rev_growth = info.get("revenueGrowth")
    earn_growth = info.get("earningsGrowth")

    score = 50
    details = []

    if rev_growth:
        rg = rev_growth * 100
        if rg > 30:
            score += 25
            details.append(f"收入增长={rg:.1f}%高速")
        elif rg > 15:
            score += 15
            details.append(f"收入增长={rg:.1f}%快速")
        elif rg > 5:
            score += 5
            details.append(f"收入增长={rg:.1f}%稳健")
        elif rg > 0:
            details.append(f"收入增长={rg:.1f}%缓慢")
        else:
            score -= 15
            details.append(f"收入增长={rg:.1f}%负增长")

    if earn_growth:
        eg = earn_growth * 100
        if eg > 30:
            score += 25
            details.append(f"利润增长={eg:.1f}%高速")
        elif eg > 15:
            score += 15
            details.append(f"利润增长={eg:.1f}%快速")
        elif eg > 0:
            score += 5
            details.append(f"利润增长={eg:.1f}%正增长")
        else:
            score -= 15
            details.append(f"利润增长={eg:.1f}%下滑")

    return min(100, max(0, score)), " | ".join(details)


def score_financial_health(info: Dict) -> Tuple[float, str]:
    """财务健康评分：负债率 + 流动比率"""
    debt_equity = info.get("debtToEquity")
    current_ratio = info.get("currentRatio")

    score = 50
    details = []

    if debt_equity is not None:
        if debt_equity < 30:
            score += 20
            details.append(f"负债率={debt_equity:.0f}%极低")
        elif debt_equity < 60:
            score += 15
            details.append(f"负债率={debt_equity:.0f}%健康")
        elif debt_equity < 100:
            score += 5
            details.append(f"负债率={debt_equity:.0f}%适中")
        elif debt_equity < 200:
            score -= 5
            details.append(f"负债率={debt_equity:.0f}%偏高")
        else:
            score -= 15
            details.append(f"负债率={debt_equity:.0f}%过高⚠️")

    if current_ratio:
        if current_ratio > 3:
            score += 15
            details.append(f"流动比率={current_ratio:.1f}优秀")
        elif current_ratio > 2:
            score += 10
            details.append(f"流动比率={current_ratio:.1f}良好")
        elif current_ratio > 1:
            details.append(f"流动比率={current_ratio:.1f}合格")
        else:
            score -= 10
            details.append(f"流动比率={current_ratio:.1f}偏低⚠️")

    return min(100, max(0, score)), " | ".join(details)


def score_momentum(info: Dict) -> Tuple[float, str]:
    """动量评分：近期涨跌幅"""
    chg_3m = info.get("52WeekChange")
    chg_1m = info.get("sandP52WeekChange")  # 不一定有

    score = 50
    details = []

    if chg_3m:
        c = chg_3m * 100
        if c > 30:
            score += 20
            details.append(f"52周+{c:.1f}%强势")
        elif c > 10:
            score += 10
            details.append(f"52周+{c:.1f}%上行")
        elif c > -10:
            details.append(f"52周{c:+.1f}%横盘")
        elif c > -30:
            score -= 10
            details.append(f"52周{c:.1f}%下跌")
        else:
            score -= 20
            details.append(f"52周{c:.1f}%深跌")

    return min(100, max(0, score)), " | ".join(details)


def score_institutional(info: Dict) -> Tuple[float, str]:
    """机构情绪评分"""
    hold = info.get("heldPercentInstitutions")
    score = 50
    details = []

    if hold:
        h = hold * 100
        if h > 70:
            score += 20
            details.append(f"机构持仓{h:.1f}%极高")
        elif h > 40:
            score += 10
            details.append(f"机构持仓{h:.1f}%较高")
        elif h > 10:
            details.append(f"机构持仓{h:.1f}%适中")
        else:
            score -= 10
            details.append(f"机构持仓{h:.1f}%偏低")

    return min(100, max(0, score)), " | ".join(details)


def score_liquidity(info: Dict) -> Tuple[float, str]:
    """流动性评分：日均成交额"""
    vol = info.get("averageVolume")
    price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
    score = 50
    details = []

    if vol and price:
        dollar_vol = vol * price
        if dollar_vol > 5_000_000_000:
            score += 25
            details.append(f"日成交额${dollar_vol/1e9:.1f}B极好")
        elif dollar_vol > 1_000_000_000:
            score += 15
            details.append(f"日成交额${dollar_vol/1e9:.1f}B良好")
        elif dollar_vol > 200_000_000:
            score += 5
            details.append(f"日成交额${dollar_vol/1e6:.0f}M一般")
        else:
            score -= 10
            details.append(f"日成交额${dollar_vol/1e6:.0f}M偏低")

    return min(100, max(0, score)), " | ".join(details)


# ═══════════════════════════════════════════════════════════
#  综合评分 & 报告
# ═══════════════════════════════════════════════════════════

def analyze_stock(ticker: str) -> Optional[Dict]:
    """对单个股票进行全维度分析"""
    info = fetch_stock_data(ticker)
    if not info:
        return None

    name = info.get("longName") or info.get("shortName") or ticker
    price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose", 0)
    sector = info.get("sector") or "未知"
    industry = info.get("industry") or "未知"
    mkt_cap = info.get("marketCap") or 0

    # 各维度评分
    dimensions = {
        "估值": score_valuation(info),
        "盈利能力": score_profitability(info),
        "成长性": score_growth(info),
        "财务健康": score_financial_health(info),
        "动量": score_momentum(info),
        "机构情绪": score_institutional(info),
        "流动性": score_liquidity(info),
    }

    # 加权总分
    total = sum(SCORE_WEIGHTS[k] * v[0] for k, v in dimensions.items())

    # 评级
    if total >= 80:
        rating = "[强烈推荐]"
    elif total >= 65:
        rating = "[推荐关注]"
    elif total >= 50:
        rating = "[观望]"
    elif total >= 35:
        rating = "[谨慎]"
    else:
        rating = "[回避]"

    pe = info.get("trailingPE") or info.get("forwardPE") or 0
    roe = info.get("returnOnEquity", 0)

    return {
        "ticker": ticker.upper(),
        "name": name,
        "price": round(float(price), 2) if price else 0,
        "sector": sector,
        "industry": industry,
        "market_cap": mkt_cap,
        "pe": round(float(pe), 1) if pe else None,
        "roe": round(float(roe) * 100, 1) if roe else None,
        "total_score": round(total, 1),
        "rating": rating,
        "dimensions": {k: {"score": round(v[0], 1), "detail": v[1]} for k, v in dimensions.items()},
    }


def print_report(result: Dict, verbose: bool = False):
    """打印分析报告"""
    cap_str = ""
    mc = result["market_cap"]
    if mc > 1e12:
        cap_str = f"${mc/1e12:.2f}T"
    elif mc > 1e9:
        cap_str = f"${mc/1e9:.2f}B"
    elif mc > 1e6:
        cap_str = f"${mc/1e6:.2f}M"

    print(f"\n{'='*60}")
    print(f"  {result['ticker']} — {result['name']}")
    print(f"  {result['rating']}  |  综合评分: {result['total_score']}/100")
    print(f"{'='*60}")
    print(f"  价格: ${result['price']:<8.2f} 市值: {cap_str}")
    print(f"  行业: {result['sector']} > {result['industry']}")
    if result["pe"]:
        print(f"  PE: {result['pe']}  ROE: {result['roe']}%")

    print(f"\n  {'─'*50}")
    print(f"  维度评分:")
    print(f"  {'─'*50}")
    for dim, data in result["dimensions"].items():
        bar = "█" * int(data["score"] / 10) + "░" * (10 - int(data["score"] / 10))
        weight = SCORE_WEIGHTS.get(dim, 0) * 100
        print(f"  {dim:>8} {bar} {data['score']:5.1f}/100 (权重{weight:.0f}%)")
        if verbose:
            print(f"           {data['detail']}")

    if verbose:
        print(f"\n  详细说明:")
        for dim, data in result["dimensions"].items():
            print(f"  [{dim}] {data['detail']}")

    print(f"\n{'='*60}\n")


# ═══════════════════════════════════════════════════════════
#  观察名单管理
# ═══════════════════════════════════════════════════════════

DEFAULT_WATCHLIST = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "LLY", "AVGO", "TSM", "PLTR"]

def load_watchlist() -> list:
    if WATCHLIST_FILE.exists():
        return json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
    return DEFAULT_WATCHLIST

def save_watchlist(tickers: list):
    WATCHLIST_FILE.write_text(json.dumps(tickers, ensure_ascii=False, indent=2), encoding="utf-8")

def manage_watchlist(args):
    wl = load_watchlist()
    if args.add_watch:
        for t in args.add_watch:
            t = t.upper()
            if t not in wl:
                wl.append(t)
                print(f"✅ {t} 已加入观察名单")
        save_watchlist(wl)
    elif args.remove_watch:
        for t in args.remove_watch:
            t = t.upper()
            if t in wl:
                wl.remove(t)
                print(f"✅ {t} 已移出观察名单")
        save_watchlist(wl)
    else:
        print(f"\n📋 当前观察名单 ({len(wl)}只):")
        for i, t in enumerate(wl, 1):
            print(f"  {i}. {t}")


# ═══════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="美股个股深度分析")
    parser.add_argument("tickers", nargs="*", help="股票代码，如 AAPL MSFT")
    parser.add_argument("--watchlist", action="store_true", help="分析观察名单所有股票")
    parser.add_argument("--list-watch", action="store_true", help="显示观察名单")
    parser.add_argument("--add-watch", nargs="+", help="添加股票到观察名单")
    parser.add_argument("--remove-watch", nargs="+", help="从观察名单移除")
    parser.add_argument("-v", "--verbose", action="store_true", help="显示详细数据")
    args = parser.parse_args()

    # 管理观察名单
    if args.list_watch or args.add_watch or args.remove_watch:
        manage_watchlist(args)
        return

    # 确定待分析列表
    tickers = []
    if args.watchlist:
        tickers = load_watchlist()
    elif args.tickers:
        tickers = [t.upper() for t in args.tickers]
    else:
        # 默认显示观察名单
        manage_watchlist(args)
        return

    # 分析
    results = []
    for t in tickers:
        print(f"\n⏳ 正在分析 {t}...")
        r = analyze_stock(t)
        if r:
            results.append(r)
            print_report(r, args.verbose)
        time.sleep(0.5)  # 避免请求过快

    if len(results) > 1:
        # 排名
        results.sort(key=lambda x: x["total_score"], reverse=True)
        print(f"\n{'='*60}")
        print(f"  📊 综合排名")
        print(f"{'='*60}")
        print(f"  {'排名':>4} {'代码':>6} {'评分':>6} {'评级':<16} {'价格':>8}")
        print(f"  {'─'*50}")
        for i, r in enumerate(results, 1):
            print(f"  {i:>4} {r['ticker']:>6} {r['total_score']:>5.1f} {r['rating']:<16} ${r['price']:<8.2f}")


if __name__ == "__main__":
    main()
