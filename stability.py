#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行稳定性工具：本地日志、重复执行护栏和报告索引检查。"""

from __future__ import annotations

import json
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from report_index import (
    REPORT_STATUS_DEGRADED,
    REPORT_STATUS_FAIL,
    REPORT_STATUS_PASS,
    REPORT_STATUS_SKIPPED,
    audit_report_index,
    flatten_report_audit,
)

ROOT = Path(__file__).parent
DEFAULT_LOG_FILE = ROOT / "logs" / "system.log"
DEFAULT_REPORT_INDEX = ROOT / "reports" / "index.json"

SYNC_STATUS_PASS = REPORT_STATUS_PASS
SYNC_STATUS_SKIPPED = REPORT_STATUS_SKIPPED
SYNC_STATUS_DEGRADED = REPORT_STATUS_DEGRADED
SYNC_STATUS_WARNING = REPORT_STATUS_DEGRADED
SYNC_STATUS_FAIL = REPORT_STATUS_FAIL

RUN_GUARD_KEYWORDS = (
    "已阻止",
    "当前时间窗口执行过",
    "run_guard",
    "重复执行",
)


def log_event(
    event: str,
    message: str = "",
    *,
    exc: BaseException | None = None,
    log_path: str | Path = DEFAULT_LOG_FILE,
    enabled: bool = True,
) -> None:
    """写入本地系统日志；safe mode 可通过 enabled=False 禁用。"""

    if not enabled:
        return
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().replace(microsecond=0).isoformat()
    lines = [f"{timestamp} [{event}] {message}".rstrip()]
    if exc is not None:
        lines.extend(traceback.format_exception(type(exc), exc, exc.__traceback__))
    with path.open("a", encoding="utf-8") as file:
        file.write("\n".join(line.rstrip("\n") for line in lines))
        file.write("\n")


def read_report_index(index_path: str | Path = DEFAULT_REPORT_INDEX) -> dict[str, Any]:
    path = Path(index_path)
    if not path.is_file():
        return {"schema_version": "1.0", "reports": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"schema_version": "1.0", "reports": []}
    if not isinstance(data, dict) or not isinstance(data.get("reports"), list):
        return {"schema_version": "1.0", "reports": []}
    return data


def has_run_today(
    report_type: str,
    *,
    index_path: str | Path = DEFAULT_REPORT_INDEX,
    today: date | None = None,
    run_mode: str | None = None,
) -> bool:
    """用 reports/index.json 判断某类任务今天是否已运行。"""

    current_date = (today or datetime.now().astimezone().date()).isoformat()
    for item in read_report_index(index_path).get("reports", []):
        if not isinstance(item, dict):
            continue
        if item.get("type") != report_type or item.get("date") != current_date:
            continue
        if run_mode is not None and item.get("run_mode") != run_mode:
            continue
        if item.get("status") == REPORT_STATUS_SKIPPED:
            continue
        return True
    return False


def run_guard_message(report_type: str) -> str:
    return (
        f"[已阻止] {report_type} 已在当前时间窗口执行过。"
        " 如确需重新执行，请使用 --force。"
    )


def report_index_warnings(
    index_path: str | Path = DEFAULT_REPORT_INDEX,
    *,
    today: date | None = None,
) -> list[str]:
    """检查 reports/index.json 是否存在日期断层和 morning/evening 缺失。"""

    index_file = Path(index_path)
    reports_dir = index_file.parent
    audit_warnings = flatten_report_audit(
        audit_report_index(reports_dir, index_path=index_file)
    )
    data = read_report_index(index_path)
    by_date: dict[date, set[str]] = {}
    for item in data.get("reports", []):
        if not isinstance(item, dict):
            continue
        raw_date = item.get("date")
        raw_type = item.get("type")
        if not isinstance(raw_date, str) or not isinstance(raw_type, str):
            continue
        try:
            report_date = date.fromisoformat(raw_date)
        except ValueError:
            continue
        by_date.setdefault(report_date, set()).add(raw_type)

    if not by_date:
        return [*audit_warnings, "reports/index.json 暂无报告记录。"]

    current_date = today or datetime.now().astimezone().date()
    start = min(by_date)
    end = max(max(by_date), current_date)
    warnings: list[str] = list(audit_warnings)
    cursor = start
    while cursor <= end:
        types = by_date.get(cursor)
        date_text = cursor.isoformat()
        if types is None:
            warnings.append(f"{date_text} 缺少所有报告记录。")
        else:
            if "morning" not in types:
                warnings.append(f"{date_text} 缺少 morning 报告。")
            if "evening" not in types:
                warnings.append(f"{date_text} 缺少 evening 报告。")
        cursor += timedelta(days=1)
    return warnings


def classify_sync_usmart_status(log_text: str) -> dict[str, str]:
    """Classify the latest sync-usmart log entry for system health reports."""

    lines = [
        line.strip()
        for line in log_text.splitlines()
        if line.strip() and "sync-usmart" in line.lower()
    ]
    if not lines:
        return {
            "status": SYNC_STATUS_DEGRADED,
            "detail": "No sync-usmart log entry found.",
        }

    latest = lines[-1]
    latest_lower = latest.lower()
    if any(keyword in latest for keyword in RUN_GUARD_KEYWORDS):
        return {
            "status": SYNC_STATUS_SKIPPED,
            "detail": latest,
        }
    if "done" in latest_lower or "success" in latest_lower or "完成" in latest:
        return {
            "status": SYNC_STATUS_PASS,
            "detail": latest,
        }
    if any(
        token in latest_lower
        for token in ("failed", "error", "exception", "traceback", "exited with errorlevel")
    ) or any(token in latest for token in ("失败", "错误", "异常")):
        return {
            "status": SYNC_STATUS_FAIL,
            "detail": latest,
        }
    return {
        "status": SYNC_STATUS_DEGRADED,
        "detail": latest,
    }


def sync_usmart_status_from_log(
    log_path: str | Path = DEFAULT_LOG_FILE,
) -> dict[str, str]:
    path = Path(log_path)
    if not path.is_file():
        return {
            "status": SYNC_STATUS_DEGRADED,
            "detail": f"Log file not found: {path}",
        }
    return classify_sync_usmart_status(path.read_text(encoding="utf-8", errors="replace"))
