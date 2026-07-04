#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""北极星 v2.5 进程守护层 — PID 单例守卫。

功能：
    - northstar.pid 文件记录当前运行进程 PID
    - northstar.lock 文件作为二级互斥锁
    - 启动时检查 PID 是否存在且存活
    - 若已存在 → 直接退出
    - 强制单进程模型

路径：
    northstar/runtime/northstar.pid
    northstar/runtime/northstar.lock
"""

from __future__ import annotations

import atexit
import os
import sys
import time

__all__ = [
    "ensure_singleton",
    "force_release_lock",
    "RUNTIME_DIR",
    "PID_FILE",
    "LOCK_FILE",
]

# ── 目录 / 文件路径 ──────────────────────────────────────────────────────────

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNTIME_DIR = os.path.join(PROJECT_ROOT, "northstar", "runtime")
PID_FILE = os.path.join(RUNTIME_DIR, "northstar.pid")
LOCK_FILE = os.path.join(RUNTIME_DIR, "northstar.lock")

_lock_held: bool = False


def _ensure_runtime_dir() -> None:
    """确保 runtime 目录存在。"""
    try:
        os.makedirs(RUNTIME_DIR, exist_ok=True)
    except OSError:
        pass


def _is_pid_alive(pid: int) -> bool:
    """检查 PID 是否仍在运行 (跨平台)。"""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, PermissionError):
        return False
    except Exception:
        return False


def _read_pid() -> int | None:
    """从 northstar.pid 读取 PID。"""
    try:
        with open(PID_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                return int(content.split("\n")[0])
    except (FileNotFoundError, ValueError, OSError):
        return None
    return None


def _write_pid() -> None:
    """写入 northstar.pid + northstar.lock。"""
    _ensure_runtime_dir()
    pid = os.getpid()
    timestamp = time.time()
    # PID 文件
    with open(PID_FILE, "w", encoding="utf-8") as f:
        f.write(f"{pid}\n")
        f.write(f"started_at={timestamp}\n")
    # Lock 文件
    with open(LOCK_FILE, "w", encoding="utf-8") as f:
        f.write(f"{pid}\n")
        f.write(f"started_at={timestamp}\n")


def _cleanup() -> None:
    """退出时清理 PID 和 LOCK 文件 (注册 atexit)。"""
    global _lock_held
    for path in [PID_FILE, LOCK_FILE]:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
    _lock_held = False


def ensure_singleton() -> bool:
    """进程级单例守卫。
    
    规则：
        - PID 文件不存在 → 创建 PID 文件 + LOCK 文件 → 返回 True
        - PID 文件存在且 PID 存活 → 返回 False (另一个实例运行中)
        - PID 文件存在但 PID 已死 → 覆盖 PID 文件 → 返回 True

    Returns:
        True  = 当前实例是唯一运行实例，继续执行
        False = 另一个实例已在运行，调用方应 sys.exit(0)
    """
    global _lock_held

    if _lock_held:
        return True

    _ensure_runtime_dir()

    if os.path.exists(PID_FILE):
        pid = _read_pid()
        if pid is not None and _is_pid_alive(pid):
            return False
        # PID 已死 → 清理旧文件后重新创建
        _cleanup()

    _write_pid()
    _lock_held = True
    atexit.register(_cleanup)
    return True


def force_release_lock() -> None:
    """强制释放锁 (测试/清理用)。"""
    _cleanup()