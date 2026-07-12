#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地报告索引。

索引只记录本地文件元数据和持仓快照 hash，不连接任何外部系统。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_REPORTS_DIR = Path(__file__).parent / "reports"
DEFAULT_INDEX_FILE = DEFAULT_REPORTS_DIR / "index.json"
DEFAULT_PORTFOLIO_FILE = Path(__file__).parent / "portfolio_migrated_candidate.json"

REPORT_STATUS_PASS = "PASS"
REPORT_STATUS_SKIPPED = "SKIPPED"
REPORT_STATUS_DEGRADED = "DEGRADED"
REPORT_STATUS_FAIL = "FAIL"


def audit_report_index(
    reports_dir: str | Path = DEFAULT_REPORTS_DIR,
    *,
    index_path: str | Path = DEFAULT_INDEX_FILE,
) -> dict[str, Any]:
    """Return non-fatal local index integrity findings for stability checks."""
    directory = Path(reports_dir)
    data = _read_index(index_path)
    findings: list[str] = []
    for item in data.get("reports", []):
        if not isinstance(item, dict):
            findings.append("报告索引包含非对象记录。")
            continue
        raw_path = item.get("file_path")
        if not raw_path:
            findings.append("报告索引记录缺少 file_path。")
            continue
        path = Path(str(raw_path))
        candidates = (path, directory / path.name)
        if not any(candidate.is_file() for candidate in candidates):
            findings.append(f"索引文件不存在：{path.as_posix()}")
    return {"status": REPORT_STATUS_PASS if not findings else REPORT_STATUS_DEGRADED, "warnings": findings}


def flatten_report_audit(audit: dict[str, Any]) -> list[str]:
    """Normalize an audit payload into user-facing continuity warnings."""
    return [str(item) for item in audit.get("warnings", []) if str(item).strip()]


def portfolio_snapshot_hash(portfolio_path: str | Path = DEFAULT_PORTFOLIO_FILE) -> str:
    path = Path(portfolio_path)
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_index(index_path: str | Path = DEFAULT_INDEX_FILE) -> dict[str, Any]:
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


def _infer_type(path: Path) -> str:
    name = path.name.lower()
    if "morning" in name:
        return "morning"
    if "evening" in name:
        return "evening"
    if "sync" in name or "migration" in name:
        return "sync"
    return "report"


def _infer_date(path: Path, generated_at: datetime | None = None) -> str:
    if generated_at is not None:
        return generated_at.date().isoformat()
    parts = path.name.split("-")
    if len(parts) >= 3 and all(part.isdigit() for part in parts[:3]):
        return "-".join(parts[:3])
    return datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()


def _portable_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def record_report(
    file_path: str | Path,
    report_type: str,
    *,
    portfolio_path: str | Path = DEFAULT_PORTFOLIO_FILE,
    index_path: str | Path | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """把一份报告写入 index.json，按 file_path 去重更新。"""

    report_path = Path(file_path)
    index_file = Path(index_path) if index_path is not None else report_path.parent / "index.json"
    index_file.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "date": _infer_date(report_path, generated_at),
        "type": report_type,
        "file_path": _portable_path(report_path),
        "portfolio_snapshot": portfolio_snapshot_hash(portfolio_path),
    }
    data = _read_index(index_file)
    reports = [
        item
        for item in data.get("reports", [])
        if isinstance(item, dict) and item.get("file_path") != entry["file_path"]
    ]
    reports.append(entry)
    reports.sort(key=lambda item: (item.get("date", ""), item.get("file_path", "")))
    data = {"schema_version": "1.0", "reports": reports}
    index_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return entry


def rebuild_report_index(
    reports_dir: str | Path = DEFAULT_REPORTS_DIR,
    *,
    portfolio_path: str | Path = DEFAULT_PORTFOLIO_FILE,
    index_path: str | Path = DEFAULT_INDEX_FILE,
) -> dict[str, Any]:
    """扫描 reports/*.md 重建索引。"""

    report_dir = Path(reports_dir)
    data = {"schema_version": "1.0", "reports": []}
    for path in sorted(report_dir.glob("*.md")):
        data["reports"].append(
            {
                "date": _infer_date(path),
                "type": _infer_type(path),
                "file_path": _portable_path(path),
                "portfolio_snapshot": portfolio_snapshot_hash(portfolio_path),
            }
        )
    Path(index_path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return data


def recent_reports(
    limit: int = 3,
    *,
    index_path: str | Path = DEFAULT_INDEX_FILE,
) -> list[dict[str, Any]]:
    data = _read_index(index_path)
    reports = [item for item in data.get("reports", []) if isinstance(item, dict)]

    def sort_key(item: dict[str, Any]) -> tuple[float, str, str]:
        path = Path(str(item.get("file_path", "")))
        mtime = path.stat().st_mtime if path.is_file() else 0.0
        return (mtime, item.get("date", ""), item.get("file_path", ""))

    return sorted(
        reports,
        key=sort_key,
        reverse=True,
    )[:limit]
