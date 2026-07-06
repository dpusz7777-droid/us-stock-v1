#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行情数据连通性诊断脚本。

功能
----
1. 测试 5 支代表性股票的行情连通性
2. 检测代理可用性
3. 输出明确的诊断结果（中文）
4. 记录诊断日志到 logs/market_data_check.log

用法
----
python scripts/check_market_data.py

测试股票
--------
NVDA, SOFI, MSFT, PLTR, TSLA
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── 测试股票 ──────────────────────────────────────────────────
TEST_SYMBOLS = ["NVDA", "SOFI", "MSFT", "PLTR", "TSLA"]


def _safe_print(text: str) -> None:
    """安全输出到 Windows 控制台。"""
    try:
        print(text)
    except UnicodeEncodeError:
        safe = text.encode("gbk", errors="replace").decode("gbk", errors="replace")
        print(safe)


def _print_separator(title: str) -> None:
    _safe_print("")
    _safe_print("=" * 60)
    _safe_print(f"  {title}")
    _safe_print("=" * 60)


def _test_yfinance_via_fetch_prices() -> dict[str, Any]:
    """测试通过 fetch_prices (yfinance + yahoo_quote 链) 获取行情。"""
    from northstar.reports.daily_decision_report import fetch_prices

    results: dict[str, Any] = {}
    results["test_name"] = "YFinance + 备用源 综合测试"
    results["symbols_tested"] = TEST_SYMBOLS
    stock_results = []

    try:
        info_map = fetch_prices(TEST_SYMBOLS)
        for sym in TEST_SYMBOLS:
            if sym in info_map:
                info = info_map[sym]
                stock_results.append({
                    "symbol": sym,
                    "success": info.current_price > 0,
                    "current_price": info.current_price,
                    "change_pct_today": info.change_pct_today,
                    "data_source": info.data_source,
                    "reason": "成功" if info.current_price > 0 else "价格为空",
                })
            else:
                stock_results.append({
                    "symbol": sym, "success": False, "current_price": 0.0,
                    "change_pct_today": 0.0, "data_source": "unavailable",
                    "reason": "获取失败",
                })
    except Exception as exc:
        for sym in TEST_SYMBOLS:
            stock_results.append({
                "symbol": sym, "success": False, "current_price": 0.0,
                "change_pct_today": 0.0, "data_source": "unavailable",
                "reason": f"异常: {exc}",
            })

    results["stock_results"] = stock_results
    results["success_count"] = sum(1 for r in stock_results if r["success"])
    results["total_count"] = len(TEST_SYMBOLS)
    return results


def _test_yahoo_quote_provider() -> dict[str, Any]:
    """测试 YahooQuoteProvider 备用行情源。"""
    from northstar.data.yahoo_quote_provider import fetch_quotes

    results: dict[str, Any] = {}
    results["test_name"] = "Yahoo Quote 备用源测试"
    results["symbols_tested"] = TEST_SYMBOLS
    stock_results = []

    try:
        quotes = fetch_quotes(TEST_SYMBOLS)
        for sym in TEST_SYMBOLS:
            q = quotes.get(sym, {})
            price = q.get("price")
            err = q.get("error")
            stock_results.append({
                "symbol": sym,
                "success": price is not None and price > 0,
                "current_price": float(price) if price is not None else 0.0,
                "change_pct_today": float(q.get("change_pct") or 0.0) if q.get("change_pct") is not None else 0.0,
                "data_source": "yahoo_quote",
                "reason": "成功" if (price is not None and price > 0) else str(err or "失败"),
            })
    except Exception as exc:
        for sym in TEST_SYMBOLS:
            stock_results.append({
                "symbol": sym, "success": False, "current_price": 0.0,
                "change_pct_today": 0.0, "data_source": "yahoo_quote",
                "reason": f"异常: {exc}",
            })

    results["stock_results"] = stock_results
    results["success_count"] = sum(1 for r in stock_results if r["success"])
    results["total_count"] = len(TEST_SYMBOLS)
    return results


def _test_proxy_connectivity() -> dict[str, Any]:
    """测试代理连通性。"""
    from northstar.config.network import (
        load_config, get_working_proxy, get_connectivity_status, reset_proxy_cache,
    )

    reset_proxy_cache()
    cfg = load_config()
    status = get_connectivity_status()

    results: dict[str, Any] = {}
    results["test_name"] = "代理连通性测试"
    results["auto_try_enabled"] = status.get("auto_try_enabled", False)
    results["proxy_configured"] = status.get("proxy_configured", False)
    results["timeout_seconds"] = status.get("timeout_seconds", 12)
    results["working_proxy"] = status.get("proxy_url", "直连")
    results["proxy_found"] = status.get("proxy_working", False)

    candidates = cfg.get("candidate_proxies", [])
    candidate_results = []
    for proxy in candidates:
        from northstar.config.network import _test_proxy
        timeout = cfg.get("timeout_seconds", 12)
        ok = _test_proxy(proxy, timeout)
        candidate_results.append({"proxy": proxy, "available": ok})
    results["candidate_results"] = candidate_results
    return results


def _save_diagnosis_log(
    yfinance_result: dict[str, Any],
    yahoo_result: dict[str, Any],
    proxy_result: dict[str, Any],
) -> None:
    """保存诊断日志到 logs/market_data_check.log。"""
    log_path = PROJECT_ROOT / "logs" / "market_data_check.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\n{'='*60}\n")
        f.write(f"诊断时间: {now}\n")
        f.write(f"{'='*60}\n")

        f.write(f"\n【YFinance 综合测试】\n")
        for sr in yfinance_result["stock_results"]:
            status = "✅" if sr["success"] else "❌"
            f.write(f"  {sr['symbol']}: {status}")
            if sr["current_price"]:
                f.write(f" 价格={sr['current_price']:.2f}")
            f.write(f" 源={sr.get('data_source','?')}")
            if sr.get("reason"):
                f.write(f" 原因={sr['reason']}")
            f.write("\n")

        f.write(f"\n【Yahoo Quote 备用源测试】\n")
        for sr in yahoo_result["stock_results"]:
            status = "✅" if sr["success"] else "❌"
            f.write(f"  {sr['symbol']}: {status}")
            if sr["current_price"]:
                f.write(f" 价格={sr['current_price']:.2f}")
            if sr.get("reason"):
                f.write(f" 原因={sr['reason']}")
            f.write("\n")

        f.write(f"\n【代理测试】\n")
        f.write(f"  自动检测: {proxy_result['auto_try_enabled']}\n")
        f.write(f"  工作代理: {proxy_result['working_proxy']}\n")
        for cr in proxy_result.get("candidate_results", []):
            status = "✅" if cr["available"] else "❌"
            f.write(f"  {cr['proxy']}: {status}\n")

        ys = yfinance_result["success_count"]
        yh = yahoo_result["success_count"]
        best = max(ys, yh)
        total = yfinance_result["total_count"]
        if best >= total * 0.8:
            f.write("  结论: 行情源正常\n")
        elif best >= total * 0.3:
            f.write("  结论: 行情源部分可用\n")
        else:
            f.write("  结论: 行情源不可用\n")
        f.write(f"  {'='*60}\n\n")


def main() -> int:
    """执行诊断。"""
    _safe_print("")
    _safe_print("██╗  ██╗ █████╗ ██████╗  ██████╗██╗  ██╗")
    _safe_print("██║  ██║██╔══██╗██╔══██╗██╔════╝██║ ██╔╝")
    _safe_print("███████║███████║██████╔╝██║     █████╔╝ ")
    _safe_print("██╔══██║██╔══██║██╔══██╗██║     ██╔═██╗ ")
    _safe_print("██║  ██║██║  ██║██║  ██║╚██████╗██║  ██╗")
    _safe_print("╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝")
    _safe_print("    行情数据连通性诊断工具")
    _safe_print("")

    # ── Step 1: 代理 ──
    _print_separator("【代理检测】")
    start = time.time()
    proxy_result = _test_proxy_connectivity()
    elapsed = time.time() - start

    if proxy_result["proxy_found"]:
        _safe_print(f"  当前使用代理: {proxy_result['working_proxy']}")
    else:
        _safe_print("  当前使用代理: 直连")
    _safe_print(f"  耗时: {elapsed:.1f}s")

    # ── Step 2: YFinance 综合测试 ──
    _print_separator("【YFinance 综合测试】")
    _safe_print(f"  测试股票: {', '.join(TEST_SYMBOLS)}")
    start = time.time()
    yf_result = _test_yfinance_via_fetch_prices()
    elapsed = time.time() - start

    for sr in yf_result["stock_results"]:
        icon = "✅" if sr["success"] else "❌"
        price_str = f"${sr['current_price']:.2f}" if sr["current_price"] else "—"
        change_str = f"{sr['change_pct_today']:+.1f}%" if sr["current_price"] else "—"
        src = sr.get("data_source", "?")
        _safe_print(f"  {icon} {sr['symbol']}: 价格={price_str} 涨跌={change_str} 源={src}")
    _safe_print(f"  耗时: {elapsed:.1f}s")

    # ── Step 3: Yahoo Quote 备用源 ──
    _print_separator("【Yahoo Quote 备用源测试】")
    start = time.time()
    yq_result = _test_yahoo_quote_provider()
    elapsed = time.time() - start

    for sr in yq_result["stock_results"]:
        icon = "✅" if sr["success"] else "❌"
        price_str = f"${sr['current_price']:.2f}" if sr["current_price"] else "—"
        change_str = f"{sr['change_pct_today']:+.1f}%" if sr["current_price"] else "—"
        _safe_print(f"  {icon} {sr['symbol']}: 价格={price_str} 涨跌={change_str}")
    _safe_print(f"  耗时: {elapsed:.1f}s")

    # ── Step 4: 最终结论 ──
    _print_separator("【最终结论】")
    ys = yf_result["success_count"]
    yq = yq_result["success_count"]
    best = max(ys, yq)
    total = yf_result["total_count"]

    if best == total:
        conclusion = "行情源正常"
        icon = "✅"
    elif best >= total * 0.3:
        conclusion = "行情源部分可用"
        icon = "⚠️"
    else:
        conclusion = "行情源不可用"
        icon = "🔴"

    _safe_print(f"  {icon} {conclusion}")
    _safe_print(f"  YFinance 综合成功: {ys}/{total}")
    _safe_print(f"  Yahoo Quote 成功: {yq}/{total}")
    _safe_print(f"  当前使用代理: {proxy_result['working_proxy']}")

    if best < total:
        _safe_print("")
        _safe_print("  💡 建议:")
        _safe_print("    - 检查 northstar/config/network_config.json 中的代理配置")
        _safe_print("    - 如果开启了 VPN/代理，确保端口与配置文件匹配")
        _safe_print("    - 编辑 network_config.json 后重新运行诊断")

    _save_diagnosis_log(yf_result, yq_result, proxy_result)
    _safe_print("")
    _safe_print("  诊断日志已保存: logs/market_data_check.log")
    _safe_print("")

    return 0 if best > 0 else 1


if __name__ == "__main__":
    sys.exit(main())