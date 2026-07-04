#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""建议留痕 — 读取/写入/管理北极星建议记录。

依赖方向：
    recommendation_store.py (此文件)
    ├── 被 northstar/ui/dashboard.py 调用
    └── 不依赖任何其他北极星模块

文件：
    northstar/data/recommendations.json
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent
RECOMMENDATIONS_FILE = DATA_DIR / "recommendations.json"

RECOMMENDATION_ACTIONS = {"买入", "持有", "卖出", "观察", "风险提示"}
CONFIDENCE_LEVELS = {"低", "中", "高"}


def _ensure_file() -> None:
    """如果文件不存在，自动创建空数组 []。"""
    if not RECOMMENDATIONS_FILE.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _write_raw([])


def _read_raw() -> list[dict[str, Any]]:
    """读取 JSON 文件，损坏时安全返回空列表。"""
    _ensure_file()
    try:
        with open(RECOMMENDATIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, FileNotFoundError, OSError):
        return []


def _write_raw(records: list[dict[str, Any]]) -> None:
    """原子写入 JSON。"""
    temporary = RECOMMENDATIONS_FILE.with_suffix(".json.tmp")
    try:
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, RECOMMENDATIONS_FILE)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def list_recommendations(limit: int = 20) -> list[dict[str, Any]]:
    """按创建时间倒序返回最近建议记录。"""
    records = _read_raw()
    records.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return records[:limit]


def add_recommendation(
    symbol: str,
    action: str,
    price: float | None = None,
    confidence: str = "中",
    reason: str = "",
    source: str = "manual",
    notes: str = "",
) -> dict[str, Any] | None:
    """新增一条建议记录，写入 recommendations.json。

    参数：
        symbol: 股票代码（必需）
        action: 建议动作（买入/持有/卖出/观察/风险提示）
        price: 当时价格（可选）
        confidence: 置信度（低/中/高，默认中）
        reason: 建议理由（可选）
        source: 来源（默认 manual）
        notes: 备注（可选）

    返回：
        新建的记录 dict，如果参数无效返回 None
    """
    symbol = symbol.strip().upper()
    action = action.strip()
    confidence = confidence.strip()

    if not symbol:
        return None
    if action not in RECOMMENDATION_ACTIONS:
        return None
    if confidence not in CONFIDENCE_LEVELS:
        return None

    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%S")
    record_id = f"rec_{now.strftime('%Y%m%d%H%M%S')}_{symbol}"

    record: dict[str, Any] = {
        "id": record_id,
        "created_at": timestamp,
        "symbol": symbol,
        "action": action,
        "price": round(float(price), 2) if price is not None else None,
        "confidence": confidence,
        "reason": reason.strip(),
        "source": source,
        "status": "open",
        "review_after_days": 7,
        "review_result": None,
        "notes": notes.strip(),
    }

    records = _read_raw()
    records.append(record)
    _write_raw(records)
    return record


def update_review_status(record_id: str, result: str, notes: str = "") -> bool:
    """更新一条建议的验证状态。"""
    records = _read_raw()
    for rec in records:
        if rec.get("id") == record_id:
            rec["status"] = "reviewed"
            rec["review_result"] = result.strip()
            if notes:
                rec["notes"] = notes.strip()
            _write_raw(records)
            return True
    return False


def count_open() -> int:
    """返回待验证的建议数量。"""
    records = _read_raw()
    return sum(1 for r in records if r.get("status") == "open")