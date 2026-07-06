#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""北极星每日决策报告 — 安装前健康检查。

检查项
------
1. 当前目录是否正确
2. watchlist 是否存在
3. network_config.json 是否存在
4. 代理配置是否能读取
5. reports/daily_decision 目录是否可写
6. logs 目录是否可写
7. 能否 import daily_decision_report
8. 能否 import price_provider
9. 能否 import yfinance
10. 给出中文结论

用法
----
python scripts/check_daily_decision_ready.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        safe = text.encode("gbk", errors="replace").decode("gbk", errors="replace")
        print(safe)


def _check(ok: bool, label: str, detail: str = "") -> bool:
    icon = "✅" if ok else "❌"
    _safe_print(f"  {icon} {label}")
    if detail:
        _safe_print(f"      {detail}")
    return ok


def main() -> int:
    _safe_print("")
    _safe_print("=" * 60)
    _safe_print("  北极星每日决策报告 — 安装前健康检查")
    _safe_print("=" * 60)
    _safe_print("")

    results: list[bool] = []
    warnings: list[str] = []

    # 1. 检查当前目录
    # ────────────────────────────────────────────
    if PROJECT_ROOT.name == "美股V1":
        results.append(_check(True, "项目目录", str(PROJECT_ROOT)))
    else:
        results.append(_check(False, "项目目录",
                        f"当前目录 {PROJECT_ROOT} 不是 美股V1"))

    # 2. watchlist
    watchlist_path = PROJECT_ROOT / "watchlist.json"
    if watchlist_path.exists():
        import json
        try:
            with open(watchlist_path) as f:
                data = json.load(f)
            symbols = data.get("symbols", [])
            results.append(_check(len(symbols) > 0, "观察池配置文件",
                            f"{watchlist_path} ({len(symbols)} 支股票)"))
        except Exception as exc:
            results.append(_check(False, "观察池配置文件", str(exc)))
    else:
        results.append(_check(False, "观察池配置文件", "文件不存在"))

    # 3. network_config.json
    net_cfg = PROJECT_ROOT / "northstar" / "config" / "network_config.json"
    if net_cfg.exists():
        import json
        try:
            with open(net_cfg) as f:
                data = json.load(f)
            use_proxy = data.get("use_proxy", False)
            proxy_url = data.get("proxy_url", "")
            results.append(_check(True, "网络配置",
                            f"{net_cfg} (代理{'已启用: '+proxy_url if use_proxy else '未启用'})"))
        except Exception as exc:
            results.append(_check(False, "网络配置", str(exc)))
    else:
        results.append(_check(False, "网络配置", "文件不存在"))

    # 4. 代理配置可读
    from northstar.config.network import load_config, get_working_proxy, reset_proxy_cache
    reset_proxy_cache()
    try:
        cfg = load_config()
        proxy = get_working_proxy()
        proxy_str = proxy if proxy else "直连"
        results.append(_check(True, "代理配置",
                        f"当前使用：{proxy_str}"))
    except Exception as exc:
        results.append(_check(False, "代理配置", str(exc)))

    # 5. 报告目录可写
    report_dir = PROJECT_ROOT / "reports" / "daily_decision"
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        test_file = report_dir / ".write_test"
        test_file.touch()
        test_file.unlink()
        results.append(_check(True, "报告输出目录", str(report_dir)))
    except Exception as exc:
        results.append(_check(False, "报告输出目录", str(exc)))

    # 6. logs 目录可写
    log_dir = PROJECT_ROOT / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        results.append(_check(True, "日志目录", str(log_dir)))
    except Exception as exc:
        results.append(_check(False, "日志目录", str(exc)))

    # 7. import daily_decision_report
    try:
        from northstar.reports import daily_decision_report
        results.append(_check(True, "决策报告模块", "from northstar.reports.daily_decision_report"))
    except Exception as exc:
        results.append(_check(False, "决策报告模块", str(exc)))

    # 8. import price_provider
    try:
        from price_provider import YFinancePriceProvider
        results.append(_check(True, "行情源模块(YFinance)", "from price_provider import YFinancePriceProvider"))
    except Exception as exc:
        results.append(_check(False, "行情源模块(YFinance)", str(exc)))

    # 9. yfinance
    try:
        import yfinance as yf
        v = getattr(yf, "__version__", "未知")
        results.append(_check(v is not None and len(str(v)) > 0,
                         "yfinance 库", f"版本: {v}"))
    except ImportError:
        results.append(_check(False, "yfinance 库", "未安装，请执行: pip install yfinance"))
    except Exception as exc:
        results.append(_check(False, "yfinance 库", str(exc)))

    # ── 汇总 ────────────────────────────────────
    _safe_print("")
    _safe_print("-" * 60)
    passed = sum(1 for r in results if r)
    total = len(results)
    _safe_print(f"  检查结果: {passed}/{total} 通过")

    if passed == total:
        _safe_print("")
        _safe_print("  ✅ 结论：可以安装 Windows 定时任务")
        _safe_print("")
        _safe_print("  安装命令（管理员 PowerShell）：")
        _safe_print("    powershell -ExecutionPolicy Bypass scripts\\windows\\install_daily_decision_task.ps1")
        _safe_print("")
        _safe_print("  手动运行测试：")
        _safe_print("    python scripts/run_daily_decision_report.py")
        _safe_print("")
        return 0
    else:
        _safe_print("")
        _safe_print("  ❌ 结论：不建议安装，原因如上")
        _safe_print("")
        for i, r in enumerate(results):
            if not r:
                _safe_print(f"     未通过: 检查项 {i+1}")
        _safe_print("")
        return 1


if __name__ == "__main__":
    sys.exit(main())