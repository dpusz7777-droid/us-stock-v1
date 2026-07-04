#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""北极星系统级稳定性守卫。

功能：
    1. Lock 文件机制 (northstar.lock) — 防止多实例
    2. Browser 单次打开守卫 — 全局变量 browser_opened + 持久化标记
    3. safe_execute() — 安全执行控制层，所有外部行为必须经过此函数
    4. 崩溃保护 — 检测异常状态后自动退出 + 写 error log

依赖方向：
    northstar/_singleton.py (此文件)
    └── 被 launch.py 调用
    └── 不被任何其他模块调用 (dashboard/report/signal 都不引用此模块)
"""

from __future__ import annotations

import atexit
import os
import sys
import time
from typing import Callable, TypeVar, Any

__all__ = [
    "ensure_singleton",
    "force_release_lock",
    "safe_execute_browser_open",
    "reset_browser_guard",
    "get_browser_opened_count",
    "crash_protect",
    "LOCK_FILENAME",
    "ERROR_LOG_NAME",
]

# ── 常量 ───────────────────────────────────────────────────────────────────────
LOCK_FILENAME = "northstar.lock"
ERROR_LOG_NAME = "northstar_crash.log"
BROWSER_FLAG_NAME = "northstar.browser_opened"

# 安全执行控制 (进程级)
_browser_opened: bool = False      # 全局变量：browser_opened = false
_browser_open_count: int = 0       # 浏览器打开次数计数
_lock_held: bool = False
_lock_file_path: str | None = None
_MAX_BROWSER_OPEN: int = 1         # 最大执行次数 max=1


# ── 路径工具 ──────────────────────────────────────────────────────────────────


def _project_root() -> str:
    """确定项目根目录。"""
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        if os.path.basename(exe_dir) == "dist":
            return os.path.dirname(exe_dir)
        return exe_dir
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.isfile(os.path.join(base, "launch.py")):
        return os.getcwd()
    return base


def _lock_path() -> str:
    return os.path.join(_project_root(), LOCK_FILENAME)


def _browser_flag_path() -> str:
    return os.path.join(_project_root(), BROWSER_FLAG_NAME)


def _error_log_path() -> str:
    return os.path.join(_project_root(), ERROR_LOG_NAME)


# ── Lock 文件 (进程级单例) ─────────────────────────────────────────────────


def _is_pid_alive(pid: int) -> bool:
    """检查 PID 是否仍在运行。"""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, PermissionError):
        return False
    except Exception:
        return False


def _read_pid(path: str) -> int | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                return int(content.split("\n")[0])
    except (FileNotFoundError, ValueError, OSError):
        return None
    return None


def _cleanup_lock() -> None:
    """退出时删除 lock 文件 (注册 atexit)。"""
    global _lock_held, _lock_file_path
    if _lock_held and _lock_file_path:
        try:
            if os.path.exists(_lock_file_path):
                os.remove(_lock_file_path)
        except OSError:
            pass
        _lock_held = False
        _lock_file_path = None


def ensure_singleton() -> bool:
    """进程级单例守卫。
    
    规则：
        - lock 不存在 → 创建 lock 并继续
        - lock 存在但 PID 已死 → 覆盖 lock 并继续
        - lock 存在且 PID 存活 → 直接退出 (返回 False)
    
    Returns:
        True  = 当前实例唯一，可继续执行
        False = 另一个实例已在运行，调用方应 sys.exit(0)
    """
    global _lock_held, _lock_file_path

    if _lock_held:
        return True

    lock_path = _lock_path()
    _lock_file_path = lock_path

    try:
        if os.path.exists(lock_path):
            pid = _read_pid(lock_path)
            if pid is not None and _is_pid_alive(pid):
                return False
            os.remove(lock_path)

        with open(lock_path, "w", encoding="utf-8") as f:
            f.write(f"{os.getpid()}\n")
            f.write(f"started_at={time.time()}\n")

        _lock_held = True
        atexit.register(_cleanup_lock)
        return True

    except OSError:
        return True  # 降级策略


def force_release_lock() -> None:
    """强制释放锁 (测试/清理用)。"""
    _cleanup_lock()


# ── 安全执行控制层 ───────────────────────────────────────────────────────


def get_browser_opened_count() -> int:
    """返回当前进程浏览器打开次数。"""
    return _browser_open_count


def _check_anomaly_and_crash(message: str) -> None:
    """崩溃保护：检测异常后自动退出 + 写 error log + 删 lock。"""
    log_path = _error_log_path()
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] CRASH: {message}\n")
    except OSError:
        pass

    # 删除 lock 文件
    _cleanup_lock()

    # 写入 stderr 后退出
    print(f"\n[北极星崩溃] {message}", file=sys.stderr)
    print(f"详情请查看: {log_path}", file=sys.stderr)

    # 强制退出，不扩散影响
    sys.exit(1)


def safe_execute_browser_open(action: Callable[[], Any]) -> Any:
    """安全执行控制层 — 所有 open_browser 调用必须经过此函数。
    
    规则：
        1. 检查是否已执行过 browser_open (browser_opened == true)
        2. 检查是否超过最大执行次数 (_browser_open_count >= max=1)
        3. 不满足条件直接拒绝执行，写入崩溃日志
        4. 执行后立即设置 browser_opened = true，增加计数
    
    Args:
        action: 执行 webbrowser.open 的可调用对象
    
    Returns:
        action 的返回值，或 None 如果被拒绝
    
    Raises:
        不会触发崩溃退出 (异常被捕获并写入日志后返回 None)
    """
    global _browser_opened, _browser_open_count

    # 检查 1: browser_opened 全局变量
    if _browser_opened:
        _check_anomaly_and_crash(
            f"浏览器重复打开被拦截 (原因: browser_opened==true, "
            f"已打开次数={_browser_open_count})"
        )
        return None  # 不会执行到这里，_check_anomaly_and_crash 会 sys.exit(1)

    # 检查 2: 最大执行次数
    if _browser_open_count >= _MAX_BROWSER_OPEN:
        _check_anomaly_and_crash(
            f"浏览器重复打开被拦截 (原因: 超过最大执行次数 {_MAX_BROWSER_OPEN}, "
            f"当前次数={_browser_open_count})"
        )
        return None  # 同上

    # 检查 3: 持久化标记
    try:
        if os.path.exists(_browser_flag_path()):
            _check_anomaly_and_crash(
                f"浏览器重复打开被拦截 (原因: 持久化标记文件存在, "
                f"路径={_browser_flag_path()})"
            )
            return None
    except OSError:
        pass

    # ── 通过检查，执行 action ──
    try:
        result = action()
    except Exception as e:
        _check_anomaly_and_crash(
            f"浏览器打开操作失败 (异常: {e})"
        )
        return None

    # ── 执行后置处理 ──
    _browser_opened = True          # 立即设置 browser_opened = true
    _browser_open_count += 1        # 增加计数

    # 写入持久化标记
    try:
        flag_path = _browser_flag_path()
        with open(flag_path, "w", encoding="utf-8") as f:
            f.write(f"1\nopened_at={time.time()}\n")
    except OSError:
        pass

    # 再次确认异常：如果计数 > 1，触发崩溃保护
    if _browser_open_count > _MAX_BROWSER_OPEN:
        _check_anomaly_and_crash(
            f"浏览器打开次数异常 (count={_browser_open_count}, max={_MAX_BROWSER_OPEN})"
        )

    return result


# ── 崩溃保护检测 ────────────────────────────────────────────────────────


def crash_protect() -> None:
    """主动崩溃检测：检查是否已有异常状态，如有则自动退出。
    
    检测项：
        1. browser_opened 计数异常 (_browser_open_count > 1)
        2. 持久化标记文件已存在 (说明非首次启动)
        3. 进程数量异常 (lock 文件存在且 PID 与当前不同)
    
    注意：此函数应在主流程开始时调用。
    """
    # 检测 1: 进程级计数
    if _browser_open_count > _MAX_BROWSER_OPEN:
        _check_anomaly_and_crash(
            f"崩溃保护触发: 浏览器打开次数异常 (count={_browser_open_count})"
        )

    # 检测 2: 持久化标记 (在未标记的情况下)
    try:
        bf = _browser_flag_path()
        if os.path.exists(bf):
            _check_anomaly_and_crash(
                f"崩溃保护触发: 浏览器标记文件在启动前已存在 ({bf})"
            )
    except OSError:
        pass

    # 检测 3: 进程数量 (多个 lock)
    try:
        lf = _lock_path()
        if os.path.exists(lf):
            pid = _read_pid(lf)
            if pid is not None and pid != os.getpid() and _is_pid_alive(pid):
                _check_anomaly_and_crash(
                    f"崩溃保护触发: 检测到其他运行实例 (PID={pid})"
                )
    except OSError:
        pass


# ── 测试/重置工具 ───────────────────────────────────────────────────────


def reset_browser_guard() -> None:
    """重置浏览器守卫 (测试用)。"""
    global _browser_opened, _browser_open_count
    _browser_opened = False
    _browser_open_count = 0
    try:
        bf = _browser_flag_path()
        if os.path.exists(bf):
            os.remove(bf)
    except OSError:
        pass