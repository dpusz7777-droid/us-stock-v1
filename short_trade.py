# -*- coding: utf-8 -*-
"""
短线交易系统 - 技术面信号 + 支撑阻力 + 仓位计算

用法:
  python short_trade.py PLTR                  # 分析一只股票的技术面
  python short_trade.py PLTR --buy $120       # 模拟买入点
  python short_trade.py --watchlist           # 批量扫描短线机会
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.stdout.reconfigure(encoding="utf-8")

DATA_DIR = Path(__file__).parent
WATCHLIST_FILE = DATA_DIR / "short_watchlist.json"

DEFAULT_SHORT_WATCH = ["PLTR", "SOFI", "UBER", "HOOD", "RKLB", "AMD", "NVDA"]


def load_watchlist():
    if WATCHLIST_FILE.exists():
        return json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
    return DEFAULT_SHORT_WATCH


# ═══════════════════════════════════════════════════════════
#  技术面数据获取
# ═══════════════════════════════════════════════════════════

def fetch_technical_data(ticker: str) -> Optional[Dict]:
    """获取技术分析所需的全部数据"""
    try:
        import yfinance as yf
        import numpy as np
    except ImportError:
        print("请安装: pip install yfinance numpy pandas")
        return None

    try:
        tk = yf.Ticker(ticker)
        info = tk.info

        # 获取历史K线（近6个月日线+近30天小时线）
        hist_daily = tk.history(period="6mo", interval="1d")
        hist_1h = tk.history(period="1mo", interval="1h")

        if hist_daily.empty:
            return None

        close = hist_daily["Close"].values
        high = hist_daily["High"].values
        low = hist_daily["Low"].values
        volume = hist_daily["Volume"].values

        # --- 均线 ---
        ma5  = np.mean(close[-5:])   if len(close) >= 5 else None
        ma10 = np.mean(close[-10:])  if len(close) >= 10 else None
        ma20 = np.mean(close[-20:])  if len(close) >= 20 else None
        ma60 = np.mean(close[-60:])  if len(close) >= 60 else None

        # --- 支撑/阻力 ---
        recent_high = np.max(high[-20:]) if len(high) >= 20 else None
        recent_low  = np.min(low[-20:])  if len(low) >= 20 else None

        # 用近3个月高低点做大级别支撑阻力
        high_3m = np.max(high[-60:]) if len(high) >= 60 else recent_high
        low_3m  = np.min(low[-60:])  if len(low) >= 60 else recent_low

        # --- RSI(14) ---
        def calc_rsi(prices, period=14):
            deltas = np.diff(prices)
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)
            avg_gain = np.mean(gains[-period:]) if len(gains) >= period else 0
            avg_loss = np.mean(losses[-period:]) if len(losses) >= period else 0
            if avg_loss == 0:
                return 100
            rs = avg_gain / avg_loss
            return 100 - (100 / (1 + rs))

        rsi = calc_rsi(close) if len(close) >= 15 else 50

        # --- MACD ---
        def calc_ema(data, period):
            alpha = 2 / (period + 1)
            ema = [data[0]]
            for i in range(1, len(data)):
                ema.append(data[i] * alpha + ema[-1] * (1 - alpha))
            return np.array(ema)

        macd_line = None
        signal_line = None
        macd_hist = None
        if len(close) >= 26:
            ema12 = calc_ema(close, 12)
            ema26 = calc_ema(close, 26)
            macd_line = ema12 - ema26
            signal_line = calc_ema(macd_line, 9) if len(macd_line) >= 9 else None
            if signal_line is not None:
                macd_hist = macd_line[-1] - signal_line[-1]

        # --- 布林带 ---
        bb_mid = ma20
        bb_std = np.std(close[-20:]) if len(close) >= 20 else None
        bb_upper = bb_mid + 2 * bb_std if bb_mid and bb_std else None
        bb_lower = bb_mid - 2 * bb_std if bb_mid and bb_std else None

        # --- 成交量变化 ---
        avg_vol = np.mean(volume[-20:]) if len(volume) >= 20 else None
        recent_vol = np.mean(volume[-5:]) if len(volume) >= 5 else None
        vol_ratio = round(recent_vol / avg_vol, 2) if avg_vol and recent_vol else None

        # --- 日内数据 ---
        price = info.get("currentPrice") or info.get("regularMarketPrice") or close[-1]
        prev_close = info.get("previousClose") or close[-2] if len(close) >= 2 else price

        return {
            "ticker": ticker.upper(),
            "name": info.get("longName") or info.get("shortName") or ticker,
            "price": round(float(price), 2),
            "prev_close": round(float(prev_close), 2),
            "day_change_pct": round((price - prev_close) / prev_close * 100, 2),
            "ma5": round(float(ma5), 2) if ma5 else None,
            "ma10": round(float(ma10), 2) if ma10 else None,
            "ma20": round(float(ma20), 2) if ma20 else None,
            "ma60": round(float(ma60), 2) if ma60 else None,
            "support_short": round(float(recent_low), 2) if recent_low else None,
            "resistance_short": round(float(recent_high), 2) if recent_high else None,
            "support_major": round(float(low_3m), 2) if low_3m else None,
            "resistance_major": round(float(high_3m), 2) if high_3m else None,
            "rsi": round(float(rsi), 1),
            "macd_hist": round(float(macd_hist), 2) if macd_hist is not None else None,
            "bb_upper": round(float(bb_upper), 2) if bb_upper else None,
            "bb_lower": round(float(bb_lower), 2) if bb_lower else None,
            "vol_ratio": vol_ratio,
            "market_cap": info.get("marketCap"),
            "pe": info.get("trailingPE") or info.get("forwardPE"),
        }
    except Exception as e:
        return None


# ═══════════════════════════════════════════════════════════
#  信号判断
# ═══════════════════════════════════════════════════════════

def analyze_signals(data: Dict) -> List[Dict]:
    """综合分析技术信号"""
    signals = []
    p = data["price"]
    rsi = data["rsi"]

    # --- RSI ---
    if rsi < 30:
        signals.append(("超卖", f"RSI={rsi}，超卖区，可能反弹", "buy"))
    elif rsi < 40:
        signals.append(("偏弱", f"RSI={rsi}，接近超卖，关注", "watch_buy"))
    elif rsi > 70:
        signals.append(("超买", f"RSI={rsi}，超买区，注意回调风险", "sell"))
    elif rsi > 60:
        signals.append(("偏强", f"RSI={rsi}，偏强但未超买", "watch"))

    # --- 均线关系 ---
    if data["ma5"] and data["ma20"]:
        if p > data["ma5"] > data["ma20"]:
            signals.append(("多头排列", "价格>MA5>MA20，短线趋势向上", "bullish"))
        elif p < data["ma5"] < data["ma20"]:
            signals.append(("空头排列", "价格<MA5<MA20，短线趋势向下", "bearish"))
        elif p > data["ma5"] and p < data["ma20"]:
            signals.append(("均线纠结", "价格在MA5和MA20之间，方向不明", "neutral"))

    # --- 价格位置（相对布林带） ---
    if data["bb_upper"] and data["bb_lower"]:
        if p >= data["bb_upper"]:
            signals.append(("触布林上轨", f"价格${p}触及布林上轨${data['bb_upper']}，压力位", "sell"))
        elif p <= data["bb_lower"]:
            signals.append(("触布林下轨", f"价格${p}触及布林下轨${data['bb_lower']}，支撑位", "buy"))

    # --- MACD ---
    if data["macd_hist"] is not None:
        if data["macd_hist"] > 0:
            signals.append(("MACD为正", f"柱状图+{data['macd_hist']}，多头动能", "bullish"))
        else:
            signals.append(("MACD为负", f"柱状图{data['macd_hist']}，空头动能", "bearish"))

    # --- 成交量 ---
    if data["vol_ratio"] and data["vol_ratio"] > 1.5:
        if data["day_change_pct"] > 0:
            signals.append(("放量上涨", f"成交量{data['vol_ratio']}倍均量，资金涌入", "bullish"))
        else:
            signals.append(("放量下跌", f"成交量{data['vol_ratio']}倍均量，抛压大", "bearish"))

    return signals


# ═══════════════════════════════════════════════════════════
#  仓位计算
# ═══════════════════════════════════════════════════════════

def calc_position(capital: float, entry: float, stop_loss: float) -> Dict:
    """计算合理仓位"""
    risk_per_share = abs(entry - stop_loss)
    if risk_per_share == 0:
        return {"error": "止损价不能等于入场价"}

    # 单笔最多亏总资金的3%
    max_risk = capital * 0.03
    shares = int(max_risk / risk_per_share)
    cost = shares * entry
    actual_risk = shares * risk_per_share

    return {
        "total_capital": round(capital, 2),
        "entry_price": round(entry, 2),
        "stop_loss": round(stop_loss, 2),
        "risk_per_share": round(risk_per_share, 2),
        "max_loss_budget": round(max_risk, 2),
        "suggested_shares": shares,
        "suggested_cost": round(cost, 2),
        "actual_risk": round(actual_risk, 2),
        "risk_pct": round(actual_risk / capital * 100, 2),
        "target1": round(entry + risk_per_share * 2, 2),  # 盈亏比2:1
        "target2": round(entry + risk_per_share * 3, 2),  # 盈亏比3:1
    }


# ═══════════════════════════════════════════════════════════
#  输出
# ═══════════════════════════════════════════════════════════

def print_technical_report(data: Dict):
    """打印技术面分析报告"""
    print(f"\n{'='*60}")
    print(f"  {data['ticker']} — {data['name']}")
    print(f"  现价: ${data['price']}  ({data['day_change_pct']:+.2f}%)")
    print(f"{'='*60}")

    print(f"\n  [均线系统]")
    print(f"    MA5(周线):  ${data['ma5']:<8}  ", end="")
    print(f"MA10: ${data['ma10']:<8}  ", end="")
    print(f"MA20(月线): ${data['ma20']:<8}")
    print(f"    MA60(季线): ${data['ma60']:<8}")
    trend = "上升" if data['ma5'] and data['ma20'] and data['ma5'] > data['ma20'] else "下降" if data['ma5'] and data['ma20'] and data['ma5'] < data['ma20'] else "震荡"
    print(f"    短线趋势: {trend}")

    print(f"\n  [支撑阻力]")
    print(f"    强阻力: ${data['resistance_major']}  |  短线阻力: ${data['resistance_short']}")
    print(f"    强支撑: ${data['support_major']}  |  短线支撑: ${data['support_short']}")
    bb_pos = "上轨附近" if data['price'] >= (data['bb_upper'] or 99999) else "下轨附近" if data['price'] <= (data['bb_lower'] or 0) else "中轨区域"
    print(f"    布林带: 上轨${data['bb_upper']} 下轨${data['bb_lower']} (当前{bb_pos})")

    print(f"\n  [技术指标]")
    rsi_label = "超卖" if data['rsi'] < 30 else "偏弱" if data['rsi'] < 40 else "中性" if data['rsi'] < 60 else "偏强" if data['rsi'] < 70 else "超买"
    print(f"    RSI(14): {data['rsi']} ({rsi_label})")
    print(f"    MACD柱: {data['macd_hist']:+.2f}")
    print(f"    量比: {data['vol_ratio']}x")

    # 信号汇总
    signals = analyze_signals(data)
    buy_signals = [s for s in signals if s[2] in ("buy", "bullish", "watch_buy")]
    sell_signals = [s for s in signals if s[2] in ("sell", "bearish")]

    print(f"\n  [信号汇总]")
    print(f"    🟢 偏多信号: {len(buy_signals)}个")
    for s in buy_signals:
        print(f"       {s[0]}: {s[1]}")
    print(f"    🔴 偏空信号: {len(sell_signals)}个")
    for s in sell_signals:
        print(f"       {s[0]}: {s[1]}")

    # 综合判断
    score = len(buy_signals) - len(sell_signals)
    if score >= 3:
        judgement = "🟢 强烈看多，可考虑买入"
    elif score >= 1:
        judgement = "🟡 偏多，关注买入机会"
    elif score >= -1:
        judgement = "⚪ 震荡观望，等待方向"
    elif score >= -3:
        judgement = "🟠 偏空，不建议买入"
    else:
        judgement = "🔴 强烈看空，回避"

    print(f"\n  综合信号评分: {score:+d}")
    print(f"  判断: {judgement}")


def print_position_plan(data: Dict, capital: float, entry: float, stop: float):
    """打印仓位计划"""
    plan = calc_position(capital, entry, stop)
    if "error" in plan:
        print(f"\n  ❌ {plan['error']}")
        return

    print(f"\n  {'='*60}")
    print(f"  📋 仓位计划")
    print(f"  {'='*60}")
    print(f"  总资金: ${plan['total_capital']:,.0f}")
    print(f"  入场:   ${plan['entry_price']}  |  止损: ${plan['stop_loss']}")
    print(f"  盈亏比: 1:{int((plan['target1']-plan['entry_price'])/plan['risk_per_share'])}")
    print(f"  ─────────────────────────────────")
    print(f"  建议买入: {plan['suggested_shares']}股")
    print(f"  占用资金: ${plan['suggested_cost']}")
    print(f"  最大亏损: ${plan['actual_risk']} ({plan['risk_pct']}%)")
    print(f"  ─────────────────────────────────")
    print(f"  🎯 止盈目标1: ${plan['target1']} (+{plan['target1']-plan['entry_price']:.2f})")
    print(f"  🎯 止盈目标2: ${plan['target2']} (+{plan['target2']-plan['entry_price']:.2f})")
    print(f"  🛑 止损价:   ${plan['stop_loss']} (-{plan['entry_price']-plan['stop_loss']:.2f})")


# ═══════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="短线交易系统")
    parser.add_argument("ticker", nargs="?", help="股票代码")
    parser.add_argument("--buy", type=float, help="模拟买入价")
    parser.add_argument("--stop", type=float, help="止损价")
    parser.add_argument("--capital", type=float, default=2868.0, help="可用资金")
    parser.add_argument("--watchlist", action="store_true", help="扫描所有观察股")
    parser.add_argument("--add", type=str, help="添加到观察名单")
    args = parser.parse_args()

    # 管理观察名单
    if args.add:
        wl = load_watchlist()
        t = args.add.upper()
        if t not in wl:
            wl.append(t)
            WATCHLIST_FILE.write_text(json.dumps(wl, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"✅ {t} 已加入短线观察名单")
        else:
            print(f"{t} 已在观察名单中")
        return

    # 扫描全部
    if args.watchlist:
        wl = load_watchlist()
        print(f"\n⏳ 扫描 {len(wl)} 只观察股...\n")
        results = []
        for t in wl:
            data = fetch_technical_data(t)
            if data:
                signals = analyze_signals(data)
                buy_score = sum(1 for s in signals if s[2] in ("buy", "bullish", "watch_buy"))
                sell_score = sum(1 for s in signals if s[2] in ("sell", "bearish"))
                net = buy_score - sell_score
                results.append((net, data))
            time.sleep(0.5)

        results.sort(key=lambda x: x[0], reverse=True)
        print(f"\n{'='*60}")
        print(f"  📊 短线机会排名 (按信号强度)")
        print(f"{'='*60}")
        print(f"  {'代码':>6} {'现价':>8} {'信号':>6} {'RSI':>6} {'MA趋势':>10} {'成交量':>8}")
        print(f"  {'─'*50}")
        for net, d in results:
            trend = "↑" if d['ma5'] and d['ma20'] and d['ma5'] > d['ma20'] else "↓"
            vol = f"{d['vol_ratio']}x" if d['vol_ratio'] else "?"
            tag = "🟢" if net >= 2 else "🟡" if net >= 0 else "🔴"
            print(f"  {tag} {d['ticker']:>6} ${d['price']:<6.2f} {net:+3d}  {d['rsi']:>5.1f} {trend:>8} {vol:>8}")

        return

    # 单只分析
    if not args.ticker:
        parser.print_help()
        return

    data = fetch_technical_data(args.ticker.upper())
    if not data:
        print(f"❌ 无法获取 {args.ticker} 数据")
        return

    print_technical_report(data)

    if args.buy and args.stop:
        print_position_plan(data, args.capital, args.buy, args.stop)
    elif args.buy:
        # 默认8%止损
        stop = round(args.buy * 0.92, 2)
        print_position_plan(data, args.capital, args.buy, stop)
    else:
        print(f"\n  💡 想算仓位? 加上 --buy <买入价> --stop <止损价>")
        print(f"     如: python short_trade.py {args.ticker.upper()} --buy {data['price']} --stop {data['support_short']}")


if __name__ == "__main__":
    main()
