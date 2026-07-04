#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""北极星 v2.5 全局状态管理。

browser_state 结构：
    browser_state = {
        "opened": False,   # 浏览器是否已打开
        "count": 0,        # 打开次数计数器
    }

event_state 结构：记录已调度的事件，用于重放保护 (dedup key)
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Any

__all__ = [
    "get_browser_state",
    "set_browser_opened",
    "get_event_record",
    "record_event",
    "reset_all",
]

# ── 线程锁 (多线程安全) ────────────────────────────────────────────────────
_lock = threading.Lock()

# ── 浏览器状态 ──────────────────────────────────────────────────────────────
_browser_state: dict[str, Any] = {
    "opened": False,
    "count": 0,
}

# ── 事件调度记录 (dedup key → True) ──────────────────────────────────────
_event_record: dict[str, bool] = {}


def get_browser_state() -> dict[str, Any]:
    """获取浏览器状态副本。"""
    with _lock:
        return dict(_browser_state)


def set_browser_opened() -> None:
    """标记浏览器已打开：opened=true, count+=1。
    
    规则：
        - count >= 1 → 永不再打开
        - opened=true → 阻止任何重复触发
    """
    with _lock:
        _browser_state["opened"] = True
        _browser_state["count"] += 1
        # 持久化到文件，供跨进程恢复
        try:
            from northstar.core.singleton import RUNTIME_DIR
            flag_path = os.path.join(RUNTIME_DIR, "browser_opened.flag")
            with open(flag_path, "w", encoding="utf-8") as f:
                f.write(f"1\ncount={_browser_state['count']}\n")
        except Exception:
            pass


def get_event_record(event: str) -> bool:
    """检查事件是否已调度过 (dedup)。"""
    with _lock:
        return _event_record.get(event, False)


def record_event(event: str) -> None:
    """记录事件已调度。"""
    with _lock:
        _event_record[event] = True


def reset_all() -> None:
    """重置所有状态 (测试用)。"""
    global _browser_state, _event_record
    with _lock:
        _browser_state = {"opened": False, "count": 0}
        _event_record = {}
    # 清理标记文件
    try:
        from northstar.core.singleton import RUNTIME_DIR
        flag_path = os.path.join(RUNTIME_DIR, "browser_opened.flag")
        if os.path.exists(flag_path):
            os.remove(flag_path)
    except Exception:
        pass