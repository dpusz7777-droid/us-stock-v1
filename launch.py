#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""北极星启动器 — 唯一入口。

启动流程：
    1. PID 单例检查 (northstar/runtime/northstar.pid)
    2. 启动后台交易引擎 (子进程, 输出到 logs/backend.log)
    3. 等待 backend 就绪 (最多 15 秒, 检测 system_state.json)
    4. 启动 Streamlit UI (headless 模式)
    5. 等待 UI 就绪后单次打开浏览器
    6. 等待子进程退出后清理

安全规则:
    - 整个项目只有此处启动 Streamlit
    - 整个项目只有此处打开浏览器
    - backend 异常时输出完整 traceback 到日志
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


# ── 路径 ─────────────────────────────────────────────────────────────────────

RUNTIME_DIR = Path(__file__).resolve().parent / "northstar" / "runtime"
PID_FILE = RUNTIME_DIR / "northstar.pid"
LOGS_DIR = Path(__file__).resolve().parent / "logs"
BACKEND_LOG = LOGS_DIR / "backend.log"
SYSTEM_STATE = Path(__file__).resolve().parent / "northstar" / "data" / "system_state.json"


def _determine_project_root() -> str:
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        if os.path.basename(exe_dir) == "dist":
            return os.path.dirname(exe_dir)
        return exe_dir
    return os.path.dirname(os.path.abspath(__file__))


# ── PID 单例守卫 ────────────────────────────────────────────────────────────


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, PermissionError):
        return False
    except Exception:
        return False


def _read_pid() -> int | None:
    try:
        with open(PID_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                return int(content.split("\n")[0])
    except (FileNotFoundError, ValueError, OSError):
        return None
    return None


def _write_pid() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with open(PID_FILE, "w", encoding="utf-8") as f:
        f.write(f"{os.getpid()}\n")
        f.write(f"started_at={time.time()}\n")


def _cleanup_pid() -> None:
    try:
        if PID_FILE.exists():
            PID_FILE.unlink()
    except OSError:
        pass


def ensure_singleton() -> bool:
    """PID 单例守卫。只阻止第二个 launch.py。"""
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    if PID_FILE.exists():
        pid = _read_pid()
        if pid is not None and _is_pid_alive(pid):
            return False
        _cleanup_pid()

    _write_pid()
    return True


# ── 子进程管理 ──────────────────────────────────────────────────────────────


def _start_backend(project_root: str) -> subprocess.Popen[bytes]:
    """启动后台交易引擎，输出到 logs/backend.log。"""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    backend_log = LOGS_DIR / "backend.log"

    print(f"[1/3] 启动后台交易引擎... 日志: {backend_log}")
    environment = os.environ.copy()
    environment["NORTHSTAR_LAUNCHED"] = "1"
    proc = subprocess.Popen(
        [sys.executable, "-m", "northstar.main", "--mode", "run"],
        cwd=project_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=environment,
    )
    print(f"  Backend PID: {proc.pid}")
    return proc


def _log_backend_output(proc: subprocess.Popen[bytes]) -> None:
    """将 backend 的 stdout/stderr 写入 logs/backend.log。"""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / "backend.log"
    with open(log_path, "a", encoding="utf-8") as f:
        for raw_line in iter(proc.stdout.readline, b""):
            if raw_line:
                line = raw_line.decode("utf-8", errors="replace")
                f.write(line)
                sys.stdout.write(line)
                sys.stdout.flush()


def _wait_backend_ready(
    proc: subprocess.Popen[bytes],
    previous_state_mtime_ns: int | None,
) -> bool:
    """等待 backend 就绪：最多 15 秒，检测 system_state.json。"""
    print("  等待 backend 就绪 (最多 15 秒)...")
    for i in range(15):
        # 检查 backend 进程是否还活着
        if proc.poll() is not None:
            print(f"  [错误] Backend 已退出 (exit code={proc.returncode})", file=sys.stderr)
            log_path = LOGS_DIR / "backend.log"
            if log_path.exists():
                print(f"  请查看日志: {log_path}", file=sys.stderr)
                # 输出最后 10 行日志
                lines = log_path.read_text(encoding="utf-8").strip().split("\n")
                print(f"  日志最后 10 行:")
                for l in lines[-10:]:
                    print(f"    {l}")
            return False

        # 检查 system_state.json 是否已生成
        if (
            SYSTEM_STATE.exists()
            and SYSTEM_STATE.stat().st_mtime_ns != previous_state_mtime_ns
        ):
            import json
            try:
                data = json.loads(SYSTEM_STATE.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("system_health") == "OK":
                    print(f"  Backend 就绪 (iteration {data.get('iteration', 0)})")
                    return True
            except Exception:
                pass

        time.sleep(1)

    # 超时
    print(f"  [警告] Backend 在 15 秒内未生成 system_state.json", file=sys.stderr)
    print(f"  system_state.json 路径: {SYSTEM_STATE}", file=sys.stderr)
    return False


def _start_ui(project_root: str) -> subprocess.Popen[bytes]:
    """启动 Streamlit UI (headless 模式，不自动打开浏览器)。"""
    print("[2/3] 启动 UI 仪表盘...")
    ui_path = os.path.join(project_root, "northstar", "ui", "dashboard.py")
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            ui_path,
            "--server.headless=true",
            "--server.port=8501",
            "--server.address=127.0.0.1",
            "--browser.gatherUsageStats=false",
        ],
        cwd=project_root,
    )


def _stop_child(proc: subprocess.Popen[bytes], timeout: float = 5.0) -> None:
    """Stop and reap one child created by this launcher."""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=timeout)


def _handle_shutdown_signal(signum: int, frame: object) -> None:
    """Route Windows console break events through the normal cleanup path."""
    raise KeyboardInterrupt


# ── 浏览器打开 ──────────────────────────────────────────────────────────────

_browser_opened: bool = False


def _open_browser_once(url: str) -> None:
    """轮询 UI 就绪后单次打开浏览器。"""
    global _browser_opened

    if _browser_opened:
        return

    print("[3/3] 等待 UI 就绪...")
    for i in range(15):
        try:
            import urllib.request
            resp = urllib.request.urlopen("http://127.0.0.1:8501", timeout=2)
            if resp.status == 200:
                break
        except Exception:
            pass
        time.sleep(1)
    else:
        print("  UI 启动超时，跳过打开浏览器", file=sys.stderr)
        return

    import webbrowser
    webbrowser.open_new(url)
    _browser_opened = True
    print(f"  浏览器已打开: {url}")


# ── 主入口 ─────────────────────────────────────────────────────────────────


def main() -> None:
    """北极星唯一入口。"""
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _handle_shutdown_signal)
    if not ensure_singleton():
        print("北极星已在运行 (检测到 northstar.pid)。直接退出。")
        sys.exit(0)

    project_root = _determine_project_root()
    os.chdir(project_root)

    print(f"项目根目录: {project_root}")
    print("北极星系统启动中...")

    # 1. 启动 backend (后台交易引擎)
    previous_state_mtime_ns = (
        SYSTEM_STATE.stat().st_mtime_ns if SYSTEM_STATE.exists() else None
    )
    backend_proc = _start_backend(project_root)

    # 后台线程: 持续读取 backend 输出到日志
    log_thread = threading.Thread(
        target=_log_backend_output, args=(backend_proc,), daemon=True
    )
    log_thread.start()

    # 2. 等待 backend 就绪 (最多 15 秒)
    if not _wait_backend_ready(backend_proc, previous_state_mtime_ns):
        print("Backend 未就绪，系统退出。", file=sys.stderr)
        _cleanup_pid()
        _stop_child(backend_proc)
        sys.exit(1)

    # 3. 启动 UI
    ui_proc = _start_ui(project_root)

    # 4. 等待 UI 就绪后打开浏览器
    _open_browser_once("http://127.0.0.1:8501")

    print()
    print("系统运行中:")
    print("  Backend PID:  ", backend_proc.pid)
    print("  Backend 日志: ", LOGS_DIR / "backend.log")
    print("  UI 地址:      http://127.0.0.1:8501")
    print("  进程文件:     ", PID_FILE)
    print()
    print("按 Ctrl+C 停止所有进程。")

    # 5. 等待子进程
    try:
        while True:
            time.sleep(1)
            if backend_proc.poll() is not None:
                print(f"Backend 异常退出 (code={backend_proc.returncode})", file=sys.stderr)
                break
            if ui_proc.poll() is not None:
                print(f"UI 已退出 (code={ui_proc.returncode})", file=sys.stderr)
                break
    except KeyboardInterrupt:
        print("\n正在关闭...")
    finally:
        _cleanup_pid()
        for proc in [backend_proc, ui_proc]:
            try:
                _stop_child(proc)
            except Exception:
                pass
        print("所有进程已停止。")


if __name__ == "__main__":
    main()
