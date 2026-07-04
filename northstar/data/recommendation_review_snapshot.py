#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""建议复盘快照 — 保存/读取北极星复盘统计历史快照。

依赖方向：
    recommendation_review_snapshot.py (此文件)
    ├── 被 northstar/ui/dashboard.py 调用
    └── 不依赖任何其他北极星模块

文件：
    northstar/data/recommendation_review_snapshots.json
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent
SNAPSHOTS_FILE = DATA_DIR / "recommendation_review_snapshots.json"


def _ensure_file() -> None:
    """如果文件不存在，自动创建空数组 []。"""
    if not SNAPSHOTS_FILE.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _write_raw([])


def _read_raw() -> list[dict[str, Any]]:
    """读取 JSON 文件，损坏时安全返回空列表。"""
    _ensure_file()
    try:
        with open(SNAPSHOTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, FileNotFoundError, OSError):
        return []


def _write_raw(snapshots: list[dict[str, Any]]) -> None:
    """原子写入 JSON。"""
    temporary = SNAPSHOTS_FILE.with_suffix(".json.tmp")
    try:
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump(snapshots, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, SNAPSHOTS_FILE)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def load_recommendation_review_snapshots() -> list[dict]:
    """读取全部快照记录。文件不存在或损坏时返回 []。"""
    return _read_raw()


def save_recommendation_review_snapshot(
    overall_stats: dict,
    symbol_stats: list[dict],
    action_stats: list[dict],
    horizon_stats: list[dict],
    summary: dict | None = None,
) -> dict:
    """保存一条新复盘快照。

    参数：
        overall_stats: get_recommendation_review_stats 返回的 dict
        symbol_stats: get_recommendation_symbol_stats 返回的 list
        action_stats: get_recommendation_action_stats 返回的 list
        horizon_stats: get_recommendation_horizon_stats 返回的 list
        summary: generate_recommendation_review_summary 返回的 dict（可选）

    返回：
        新保存的快照对象 dict
    """
    now = datetime.now()
    snapshot_id = now.strftime("%Y-%m-%dT%H:%M:%S")
    created_at = now.strftime("%Y-%m-%dT%H:%M:%S")

    # top_symbols: filter by win_rate not None, sort by win_rate desc, then avg_normalized desc
    top_symbols = []
    if symbol_stats:
        eligible_sym = [s for s in symbol_stats if s.get("win_rate") is not None]
        eligible_sym.sort(
            key=lambda x: (x["win_rate"], x.get("avg_normalized_change_pct") or 0, x.get("evaluable_count", 0)),
            reverse=True,
        )
        top_symbols = eligible_sym[:5]

    # top_actions: filter by win_rate not None and not UNKNOWN
    top_actions = []
    if action_stats:
        eligible_act = [
            a for a in action_stats
            if a.get("win_rate") is not None and a.get("action_group") != "UNKNOWN"
        ]
        eligible_act.sort(
            key=lambda x: (x["win_rate"], x.get("avg_normalized_change_pct") or 0, x.get("evaluable_count", 0)),
            reverse=True,
        )
        top_actions = eligible_act[:5]

    # top_horizons: filter by win_rate not None and not UNKNOWN
    top_horizons = []
    if horizon_stats:
        eligible_hor = [
            h for h in horizon_stats
            if h.get("win_rate") is not None and h.get("horizon_group") != "UNKNOWN"
        ]
        eligible_hor.sort(
            key=lambda x: (x["win_rate"], x.get("avg_normalized_change_pct") or 0, x.get("evaluable_count", 0)),
            reverse=True,
        )
        top_horizons = eligible_hor[:5]

    snapshot = {
        "snapshot_id": snapshot_id,
        "created_at": created_at,
        "overall": overall_stats,
        "summary": summary or {},
        "top_symbols": top_symbols,
        "top_actions": top_actions,
        "top_horizons": top_horizons,
    }

    snapshots = _read_raw()
    snapshots.append(snapshot)
    _write_raw(snapshots)
    return snapshot


def get_latest_recommendation_review_snapshot() -> dict | None:
    """返回最新一条快照。没有快照时返回 None。"""
    snapshots = _read_raw()
    if not snapshots:
        return None
    # 按 created_at 从新到旧排序，第一个即为最新
    snapshots.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return snapshots[0]


def get_recommendation_review_snapshot_history(limit: int = 20) -> list[dict]:
    """返回最近 limit 条快照，按 created_at 从新到旧排序。"""
    snapshots = _read_raw()
    snapshots.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return snapshots[:limit]