#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日决策报告执行入口脚本。

用途
----
- 可被 Windows 任务计划程序定时调用
- 也可手动运行：python scripts/run_daily_decision_report.py
- 运行日志写入 logs/daily_decision_report.log

用法
----
python scripts/run_daily_decision_report.py

输出
----
- reports/daily_decision/daily_decision_YYYY-MM-DD.md
- reports/daily_decision/daily_decision_YYYY-MM-DD.json
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

# ── 项目根目录 ────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _safe_print(text: str) -> None:
    """安全输出到 Windows 控制台（处理 GBK 编码无法打印的字符）。"""
    try:
        print(text)
    except UnicodeEncodeError:
        # 替换无法显示的字符
        safe = text.encode("gbk", errors="replace").decode("gbk", errors="replace")
        print(safe)


def main() -> int:
    """执行每日决策报告生成，返回退出码。"""
    from northstar.reports.daily_decision_report import generate_daily_decision_report

    now_str = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    _safe_print(f"[{now_str}] 开始生成每日决策报告...")

    try:
        result = generate_daily_decision_report()
    except Exception as exc:
        _safe_print(f"[失败] 报告生成异常: {exc}")
        traceback.print_exc()
        # 写入错误日志
        log_path = PROJECT_ROOT / "logs" / "daily_decision_report.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{now_str}] ERROR: {exc}\n")
            f.write(traceback.format_exc())
            f.write("\n")
        return 1

    if "error" in result:
        _safe_print(f"[失败] 报告生成失败: {result['error']}")
        return 1

    md_path = result.get("_md_path", "未知")
    json_path = result.get("_json_path", "未知")
    conclusion = result.get("overall_conclusion", "未知")

    _safe_print(f"[完成] 每日决策报告已生成")
    _safe_print(f"   Markdown: {md_path}")
    _safe_print(f"   JSON:     {json_path}")
    _safe_print(f"   今日结论: {conclusion}")
    return 0


if __name__ == "__main__":
    sys.exit(main())