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


def compute_grade_stats_from_overall(overall_stats: dict) -> dict:
    """（公开版本）从 overall_stats 中计算建议复盘分级统计（只读）。

    返回值兼容旧快照：旧快照没有这些字段时显示为 None / 0。

    返回：
        {
            "grade_valid_count": int | None,
            "grade_watch_count": int | None,
            "grade_invalid_count": int | None,
            "grade_insufficient_count": int | None,
            "grade_effective_rate": float | None,  有效/(有效+失效)
            "grade_sample_count": int,             有效+失效（分母）
        }
    """
    valid = overall_stats.get("grade_valid_count")
    watch = overall_stats.get("grade_watch_count")
    invalid = overall_stats.get("grade_invalid_count")
    insufficient = overall_stats.get("grade_insufficient_count")

    # 如果新增字段还不存在（旧系统），返回空值，让快照记录 None
    # 这样旧快照不会崩溃，新快照会记录实际值
    if valid is None:
        return {
            "grade_valid_count": None,
            "grade_watch_count": None,
            "grade_invalid_count": None,
            "grade_insufficient_count": None,
            "grade_effective_rate": None,
            "grade_sample_count": 0,
        }

    sample_count = (valid or 0) + (invalid or 0)
    effective_rate = None
    if sample_count > 0:
        effective_rate = round((valid or 0) / sample_count * 100, 1)

    return {
        "grade_valid_count": valid or 0,
        "grade_watch_count": watch or 0,
        "grade_invalid_count": invalid or 0,
        "grade_insufficient_count": insufficient or 0,
        "grade_effective_rate": effective_rate,
        "grade_sample_count": sample_count,
    }


def _compute_grade_stats_from_overall(overall_stats: dict) -> dict:
    """（内部版本）从 overall_stats 中计算建议复盘分级统计（只读）。

    返回值兼容旧快照：旧快照没有这些字段时显示为 None / 0。

    返回：
        {
            "grade_valid_count": int,
            "grade_watch_count": int,
            "grade_invalid_count": int,
            "grade_insufficient_count": int,
            "grade_effective_rate": float | None,
            "grade_sample_count": int,
        }
    """
    return compute_grade_stats_from_overall(overall_stats)


def save_recommendation_review_snapshot(
    overall_stats: dict,
    symbol_stats: list[dict],
    action_stats: list[dict],
    horizon_stats: list[dict],
    summary: dict | None = None,
    grade_stats: dict | None = None,
) -> dict:
    """保存一条新复盘快照。

    参数：
        overall_stats: get_recommendation_review_stats 返回的 dict
        symbol_stats: get_recommendation_symbol_stats 返回的 list
        action_stats: get_recommendation_action_stats 返回的 list
        horizon_stats: get_recommendation_horizon_stats 返回的 list
        summary: generate_recommendation_review_summary 返回的 dict（可选）
        grade_stats: 建议复盘分级统计 dict（v16 新增，可选，向下兼容）

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

    # ── 分级统计（v16 新增，向下兼容） ──
    grade_stats = _compute_grade_stats_from_overall(overall_stats)

    # ── v20: 失效原因统计（如果提供了则存储，否则尝试从 overall 提取） ──
    if grade_stats is None:
        failure_stats_for_snapshot = None
    else:
        failure_stats_for_snapshot = grade_stats.get("failure_stats")

    snapshot = {
        "snapshot_id": snapshot_id,
        "created_at": created_at,
        "overall": overall_stats,
        "summary": summary or {},
        "top_symbols": top_symbols,
        "top_actions": top_actions,
        "top_horizons": top_horizons,
        "grade_stats": grade_stats,
        "failure_stats": failure_stats_for_snapshot,
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


def get_recommendation_review_snapshot_trend(limit: int = 30) -> list[dict]:
    """读取最近 limit 条快照，按 created_at 从旧到新排序，用于趋势展示。

    每条包含：
        created_at, display_time, win_rate, avg_normalized_change_pct,
        evaluable_count, confidence_level, confidence_label, headline,
        grade_valid_count, grade_watch_count, grade_invalid_count,
        grade_insufficient_count, grade_effective_rate, grade_sample_count

    参数：
        limit: 最多读取的快照数量

    返回：
        list[dict]，按时间从旧到新排序。无快照时返回 []。
    """
    snapshots = _read_raw()
    if not snapshots:
        return []

    # 按 created_at 从新到旧取 limit 条
    snapshots.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    recent = snapshots[:limit]

    # 反转成从旧到新
    recent.reverse()

    trend_data = []
    for snap in recent:
        overall = snap.get("overall", {}) or {}
        summary = snap.get("summary", {}) or {}
        created_at = snap.get("created_at", "") or ""
        grade_stats = snap.get("grade_stats", {}) or {}

        # Format display_time
        display_time = created_at
        if created_at and len(created_at) >= 16:
            try:
                dt = datetime.fromisoformat(created_at)
                display_time = dt.strftime("%m-%d %H:%M")
            except (TypeError, ValueError):
                display_time = created_at[-11:] if len(created_at) >= 11 else created_at
        elif created_at:
            display_time = created_at

        trend_data.append({
            "created_at": created_at,
            "display_time": display_time,
            "win_rate": overall.get("win_rate"),
            "avg_normalized_change_pct": overall.get("avg_normalized_change_pct"),
            "evaluable_count": overall.get("evaluable_count", 0),
            "confidence_level": overall.get("confidence_level", ""),
            "confidence_label": overall.get("confidence_label", ""),
            "headline": summary.get("headline", ""),
            # ── v16 分级趋势字段（兼容旧快照，缺字段时 None/0） ──
            "grade_valid_count": grade_stats.get("grade_valid_count"),
            "grade_watch_count": grade_stats.get("grade_watch_count"),
            "grade_invalid_count": grade_stats.get("grade_invalid_count"),
            "grade_insufficient_count": grade_stats.get("grade_insufficient_count"),
            "grade_effective_rate": grade_stats.get("grade_effective_rate"),
            "grade_sample_count": grade_stats.get("grade_sample_count", 0),
        })

    return trend_data


def generate_recommendation_review_trend_summary(trend_data: list[dict]) -> str:
    """根据趋势数据生成简短的中文趋势结论。

    参数：
        trend_data: get_recommendation_review_snapshot_trend 返回的数据

    返回：
        str，一段简洁中文描述
    """
    if len(trend_data) < 2:
        return "复盘快照不足，暂时无法判断趋势。"

    first = trend_data[0]
    last = trend_data[-1]
    parts: list[str] = []

    # win_rate 对比
    first_wr = first.get("win_rate")
    last_wr = last.get("win_rate")
    if first_wr is not None and last_wr is not None:
        diff = last_wr - first_wr
        if diff > 5:
            parts.append("方向胜率有所提升")
        elif diff < -5:
            parts.append("方向胜率有所下降")
        else:
            parts.append("方向胜率基本稳定")
    else:
        parts.append("方向胜率暂无可比数据")

    # avg_normalized_change_pct 对比
    first_an = first.get("avg_normalized_change_pct")
    last_an = last.get("avg_normalized_change_pct")
    if first_an is not None and last_an is not None:
        diff_n = last_an - first_an
        if diff_n > 1:
            parts.append("平均方向涨跌幅有所改善")
        elif diff_n < -1:
            parts.append("平均方向涨跌幅有所回落")
        else:
            parts.append("平均方向涨跌幅基本稳定")
    else:
        parts.append("平均方向涨跌幅暂无可比数据")

    # evaluable_count 对比
    first_ec = first.get("evaluable_count", 0)
    last_ec = last.get("evaluable_count", 0)
    if last_ec > first_ec:
        parts.append("可判断样本正在积累")
    elif last_ec < first_ec:
        parts.append("可判断样本有所减少")
    else:
        parts.append("可判断样本数量未明显变化")

    return "相比最早快照，" + "，".join(parts) + "。"
