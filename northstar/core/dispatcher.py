#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""北极星 v2.5 安全事件调度器 — Safe Event Dispatcher。

所有外部行为必须通过 dispatcher，禁止直接调用。

事件类型：
    - "OPEN_BROWSER"  — 打开浏览器
    - "START_UI"      — 启动 UI (保留)
    - "START_BACKEND" — 启动 Backend (保留)

调度规则：
    1. 所有外部行为必须通过 safe_dispatch()
    2. event 类型必须明确 (OPEN_BROWSER / START_UI / START_BACKEND)
    3. dispatcher 内部必须检查：
       - 是否已执行过 (dedup key)
       - 是否超过 max_count=1
       - 是否已初始化完成

UI/dashboard 模块：
    - 禁止调用 safe_dispatch()
    - 禁止触发任何副作用
    - 只能 render data / show reports
"""

from __future__ import annotations

import sys
from typing import Callable, Any

from northstar.core.state import get_browser_state, set_browser_opened
from northstar.core.state import get_event_record, record_event

__all__ = [
    "safe_dispatch",
    "EventType",
]

# ── 事件类型常量 ────────────────────────────────────────────────────────────

class EventType:
    """支持的事件类型。"""
    OPEN_BROWSER = "OPEN_BROWSER"
    START_UI = "START_UI"
    START_BACKEND = "START_BACKEND"

    _MAX_COUNT: dict[str, int] = {
        "OPEN_BROWSER": 1,
        "START_UI": 1,
        "START_BACKEND": 1,
    }

    @classmethod
    def max_count(cls, event: str) -> int:
        return cls._MAX_COUNT.get(event, 1)


# ── 错误日志 ──────────────────────────────────────────────────────────────

def _write_error_log(message: str) -> None:
    """将崩溃信息写入日志。"""
    import os, time
    from northstar.core.singleton import RUNTIME_DIR
    log_dir = os.path.join(os.path.dirname(RUNTIME_DIR), "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "crash.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] CRASH: {message}\n")
    except Exception:
        pass


def _fatal_exit(message: str) -> None:
    """安全退出：写日志 → 清理 → sys.exit(1)。"""
    _write_error_log(message)
    # 清理 PID & LOCK
    try:
        from northstar.core.singleton import force_release_lock
        force_release_lock()
    except Exception:
        pass
    print(f"\n[北极星系统崩溃] {message}", file=sys.stderr)
    print("系统已安全退出。", file=sys.stderr)
    sys.exit(1)


# ── 安全调度器 ─────────────────────────────────────────────────────────────


def safe_dispatch(event: str, action: Callable[[], Any] | None = None) -> Any:
    """安全事件调度器 — 所有 open_browser 等外部行为必须经过此函数。
    
    Args:
        event: 事件类型，必须是 EventType 中定义的常量
        action: 执行动作的可调用对象 (如 webbrowser.open)
    
    Returns:
        action 的返回值，或 None 如果被拒绝
    
    Raises:
        不会抛出异常；异常情况下调用 _fatal_exit()
    """
    # ── 验证 event 类型 ──
    valid_events = [EventType.OPEN_BROWSER, EventType.START_UI, EventType.START_BACKEND]
    if event not in valid_events:
        _fatal_exit(f"非法事件类型: {event} (允许: {valid_events})")
        return None

    # ── 检查 1: 是否已执行过 (dedup) ──
    if get_event_record(event):
        _fatal_exit(
            f"事件重复调度被拦截: {event} "
            f"(原因: dedup key 已存在, 事件已执行过)"
        )
        return None

    # ── 检查 2: 浏览器特殊保护 ──
    if event == EventType.OPEN_BROWSER:
        bs = get_browser_state()
        if bs["opened"]:
            _fatal_exit(
                f"OPEN_BROWSER 被拦截: browser_state.opened={bs['opened']}, "
                f"count={bs['count']} (max=1)"
            )
            return None
        if bs["count"] >= EventType.max_count(event):
            _fatal_exit(
                f"OPEN_BROWSER 被拦截: 超过最大执行次数 "
                f"(count={bs['count']}, max={EventType.max_count(event)})"
            )
            return None
        # 检查持久化标记文件
        try:
            import os
            from northstar.core.singleton import RUNTIME_DIR
            flag_path = os.path.join(RUNTIME_DIR, "browser_opened.flag")
            if os.path.exists(flag_path):
                _fatal_exit(
                    f"OPEN_BROWSER 被拦截: 持久化标记文件已存在 ({flag_path})"
                )
                return None
        except Exception:
            pass

    # ── 检查 3: 最大执行次数 (通用) ──
    max_n = EventType.max_count(event)
    # 对于浏览器，额外检查 state 中的 count
    if event == EventType.OPEN_BROWSER:
        current_count = get_browser_state()["count"]
        if current_count >= max_n:
            _fatal_exit(
                f"{event} 被拦截: 当前计数 {current_count} >= 最大次数 {max_n}"
            )
            return None

    # ── 通过检查，执行 action ──
    result = None
    try:
        if action is not None:
            result = action()
    except Exception as e:
        _fatal_exit(f"{event} 执行失败: {e}")
        return None

    # ── 执行后置处理 ──
    record_event(event)

    if event == EventType.OPEN_BROWSER:
        set_browser_opened()  # browser_state.opened=true, count+=1

    return result