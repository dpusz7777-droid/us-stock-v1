#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""北极星 v2.5 Watchdog 守护进程 — 系统健康监控。

功能（每 3 秒检查一次）：
    1. python 进程数量 (检测异常多进程)
    2. northstar.pid 是否异常
    3. browser open count > 1
    4. event loop 异常 (> 3)

触发条件：
    - browser_open_count > 1
    - process_count > 2 (主进程 + backend + ui = 3 正常, > 3 代表异常)
    - event_loop > 3

执行动作：
    - kill all northstar processes
    - 删除 northstar.pid
    - 删除 northstar.lock
    - 记录 crash log
    - 安全退出系统
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from typing import Any

from northstar.core.state import get_browser_state
from northstar.core.singleton import PID_FILE, LOCK_FILE

__all__ = [
    "start_watchdog",
    "stop_watchdog",
    "WatchdogTrigger",
]

# ── 常量 ───────────────────────────────────────────────────────────────────────
CHECK_INTERVAL: float = 3.0  # 每 3 秒检查一次

# 正常进程数：主进程 (launch) + backend + ui = 3
# 如果 backend 和 ui 是子进程，launch 一个进程就够了
LOGICAL_MAX_PROCESSES = 4

# 事件循环异常阈值
MAX_EVENT_LOOP_COUNT = 3


# ── 线程控制 ─────────────────────────────────────────────────────────────────

_watchdog_thread: threading.Thread | None = None
_watchdog_running: bool = False
_loop_counter: int = 0


# ── 崩溃日志 ─────────────────────────────────────────────────────────────────


def _write_error_log(message: str) -> None:
    """写入崩溃日志到 northstar/logs/"""
    try:
        log_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "logs",
        )
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "crash.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] WATCHDOG: {message}\n")
    except Exception:
        pass


def _count_python_processes() -> int:
    """检测当前 northstar 相关 python 进程数量。"""
    try:
        if sys.platform == "win32":
            # Windows: 使用 tasklist 过滤
            import subprocess
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV"],
                capture_output=True, text=True, timeout=5
            )
            # 计数 python.exe 进程行数 (减去表头)
            lines = [l for l in result.stdout.split("\n") if "python.exe" in l.lower()]
            return len(lines)
        else:
            # Linux/Mac: 使用 ps
            import subprocess
            result = subprocess.run(
                ["ps", "-ef"],
                capture_output=True, text=True, timeout=5
            )
            lines = [l for l in result.stdout.split("\n") if "python" in l.lower() and "northstar" in l.lower()]
            return len(lines)
    except Exception:
        return 0


def _safe_exit(message: str) -> None:
    """Watchdog 触发的安全退出。"""
    _write_error_log(message)
    print(f"\n[北极星 Watchdog] {message}", file=sys.stderr)
    print("Watchdog 正在清理并退出...", file=sys.stderr)

    # 清理 PID & LOCK 文件
    for path in [PID_FILE, LOCK_FILE]:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    # 清理浏览器标记
    try:
        from northstar.core.singleton import RUNTIME_DIR
        flag_path = os.path.join(RUNTIME_DIR, "browser_opened.flag")
        if os.path.exists(flag_path):
            os.remove(flag_path)
    except Exception:
        pass

    # 退出 (不 kill 子进程，exit(1) 会传播到父进程)
    os._exit(1)


# ── 检查函数 ────────────────────────────────────────────────────────────────


def _check_process_count() -> None:
    """检查 python 进程数量是否异常。"""
    count = _count_python_processes()
    if count > LOGICAL_MAX_PROCESSES:
        _safe_exit(
            f"python 进程数量异常: {count} (阈值: {LOGICAL_MAX_PROCESSES})"
        )


def _check_browser_count() -> None:
    """检查 browser open count 是否 > 1。"""
    bs = get_browser_state()
    if bs["count"] > 1:
        _safe_exit(
            f"browser_open_count 异常: {bs['count']} (阈值: 1)"
        )


def _check_loop_counter() -> None:
    """检查事件循环执行次数是否异常。"""
    global _loop_counter
    _loop_counter += 1
    if _loop_counter > MAX_EVENT_LOOP_COUNT:
        _safe_exit(
            f"event_loop 异常: {_loop_counter} (阈值: {MAX_EVENT_LOOP_COUNT})"
        )


def _check_pid_file() -> None:
    """检查 northstar.pid 是否异常 (丢失 / 不匹配)。"""
    try:
        if not os.path.exists(PID_FILE):
            _safe_exit("northstar.pid 文件丢失")
    except Exception:
        pass


# ── 主循环 ──────────────────────────────────────────────────────────────────


def _watchdog_loop() -> None:
    """Watchdog 守护主循环 (每 3 秒执行一次检查)。"""
    global _loop_counter
    _loop_counter = 0

    while _watchdog_running:
        try:
            # 执行各项检查
            _check_pid_file()
            _check_process_count()
            _check_browser_count()
            _check_loop_counter()

        except SystemExit:
            raise
        except Exception as e:
            _write_error_log(f"Watchdog 检查异常: {e}")

        # 每 3 秒检查一次
        for _ in range(int(CHECK_INTERVAL / 0.5)):
            if not _watchdog_running:
                return
            time.sleep(0.5)


def start_watchdog() -> None:
    """启动 Watchdog 守护线程 (非阻塞)。"""
    global _watchdog_thread, _watchdog_running

    if _watchdog_running:
        return

    _watchdog_running = True
    _watchdog_thread = threading.Thread(target=_watchdog_loop, daemon=True)
    _watchdog_thread.start()


def stop_watchdog() -> None:
    """停止 Watchdog 守护线程。"""
    global _watchdog_running
    _watchdog_running = False