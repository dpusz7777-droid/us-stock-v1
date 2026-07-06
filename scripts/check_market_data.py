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


def _test_yfinance_direct() -> dict[str, Any]:
    """测试直接通过 yfinance 获取行情。"""
    from northstar.reports.daily_decision_report import fetch_prices
    from northstar.reports.daily_decision_report import load_watchlist

    results: dict[str, Any] = {}
    results["test_name"] = "YFinance 直连测试"
    results["symbols_tested"] = TEST_SYMBOLS
    stock_results = []

    # 使用 fetch_prices 测试
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
                    "reason": "成功" if info.current_price > 0 else "价格为空（行情源不可用）",
                })
            else:
                stock_results.append({
                    "symbol": sym,
                    "success": False,
                    "current_price": 0.0,
                    "change_pct_today": 0.0,
                    "reason": "获取失败（无返回结果）",
                })
    except Exception as exc:
        # fetch_prices 内已有降级，不会抛出
        for sym in TEST_SYMBOLS:
            stock_results.append({
                "symbol": sym,
                "success": False,
                "current_price": 0.0,
                "change_pct_today": 0.0,
                "reason": f"异常: {exc}",
            })

    results["stock_results"] = stock_results
    success_count = sum(1 for r in stock_results if r["success"])
    results["success_count"] = success_count
    results["total_count"] = len(TEST_SYMBOLS)
    return results


def _test_proxy_connectivity() -> dict[str, Any]:
    """测试代理连通性。"""
    from northstar.config.network import (
        load_config,
        get_working_proxy,
        get_connectivity_status,
        reset_proxy_cache,
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

    # 记录每个候选代理的测试结果
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

        f.write(f"\n【YFinance 直连测试】\n")
        for sr in yfinance_result["stock_results"]:
            status = "✅ 成功" if sr["success"] else "❌ 失败"
            f.write(f"  {sr['symbol']}: {status}")
            if sr["current_price"]:
                f.write(f" 价格={sr['current_price']}")
            if sr.get("reason"):
                f.write(f" 原因={sr['reason']}")
            f.write("\n")

        f.write(f"\n【代理测试】\n")
        f.write(f"  自动检测: {proxy_result['auto_try_enabled']}\n")
        f.write(f"  工作代理: {proxy_result['working_proxy']}\n")
        for cr in proxy_result.get("candidate_results", []):
            status = "✅" if cr["available"] else "❌"
            f.write(f"  {cr['proxy']}: {status}\n")

        f.write(f"\n【结论】\n")
        sy = yfinance_result["success_count"]
        st = yfinance_result["total_count"]
        if sy == st:
            f.write("  行情源正常\n")
        elif sy >= st * 0.3:
            f.write("  行情源部分可用\n")
        else:
            f.write("  行情源不可用\n")
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

    _print_separator("第一步: 代理连通性检测")
    start = time.time()
    proxy_result = _test_proxy_connectivity()
    elapsed = time.time() - start

    if proxy_result["proxy_found"]:
        _safe_print(f"  可用代理: {proxy_result['working_proxy']}")
    else:
        _safe_print("  未检测到可用代理，将使用直连")
    _safe_print(f"  耗时: {elapsed:.1f}s")

    _print_separator("第二步: YFinance 行情测试")
    _safe_print(f"  测试股票: {', '.join(TEST_SYMBOLS)}")
    start = time.time()
    yfinance_result = _test_yfinance_direct()
    elapsed = time.time() - start

    for sr in yfinance_result["stock_results"]:
        icon = "✅" if sr["success"] else "❌"
        price_str = f"${sr['current_price']:.2f}" if sr["current_price"] else "—"
        change_str = f"{sr['change_pct_today']:+.1f}%" if sr["current_price"] else "—"
        _safe_print(f"  {icon} {sr['symbol']}: 价格={price_str} 涨跌={change_str}")
    _safe_print(f"  耗时: {elapsed:.1f}s")

    _print_separator("第三步: 诊断结论")
    sy = yfinance_result["success_count"]
    st = yfinance_result["total_count"]
    if sy == st:
        conclusion = "行情源正常"
        icon = "✅"
    elif sy >= st * 0.3:
        conclusion = "行情源部分可用"
        icon = "⚠️"
    else:
        conclusion = "行情源不可用"
        icon = "🔴"

    _safe_print(f"  {icon} {conclusion}")
    _safe_print(f"  成功获取: {sy}/{st}")
    _safe_print(f"  当前代理: {proxy_result['working_proxy']}")
    if sy < st:
        _safe_print("")
        _safe_print("  💡 建议:")
        _safe_print("    - 检查 northstar/config/network_config.json 中的代理配置")
        _safe_print("    - 如果开启了 VPN/代理，确保端口与配置文件匹配")
        _safe_print("    - 如果没有代理，可暂时跳过行情数据，报告仍能生成")
        _safe_print("    - 如需修改代理，编辑 network_config.json 后重新运行诊断")

    # 保存日志
    _save_diagnosis_log(yfinance_result, proxy_result)
    _safe_print("")
    _safe_print("  诊断日志已保存: logs/market_data_check.log")
    _safe_print("")

    return 0 if sy > 0 else 1


if __name__ == "__main__":
    sys.exit(main())