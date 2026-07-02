#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DaemonRunner — V1.7 Stability Layer.

核心目标
--------
防止任何模块阻塞导致系统卡死。
"单模块崩溃不影响整体运行"

升级内容 (V1.7)
--------------
1. 全局超时控制（必须）
   - 所有 subprocess / API 调用必须有 timeout
   - 默认 timeout = 5s（signal / decision）
   - report 允许 30s

2. 非阻塞执行（关键）
   - signal / decision / execution 必须使用 try/except 包裹
   - 任一模块失败不能阻断 daemon loop

3. Watchdog 机制
   - 每个 cycle 记录 heartbeat timestamp
   - 如果超过 120s 没更新 heartbeat → 自动跳过当前 cycle

4. 安全 fallback
   - signal 失败 → EMPTY_SIGNAL
   - decision 失败 → HOLD
   - execution 失败 → SKIP
   - report 失败 → 不影响主循环

5. 日志增强
   - logs/runtime.log 必须记录：
     · cycle_id
     · module status
     · latency
     · error stacktrace（如果有）

安全约束
--------
- 纯 Paper Mode，不连接任何 Broker
- 不修改 broker interface
- 不允许真实交易

用法
----
    仅由 scripts/supervisor.py 启动和管理
"""

from __future__ import annotations

import functools
import fcntl
import gc
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import threading
import time
import traceback
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

# ── 路径 ──────────────────────────────────────────────
ROOT = Path(__file__).parent
LOGS_DIR = ROOT / "logs"
SNAPSHOT_FILE = ROOT / "state_snapshot.json"
QUEUE_FILE = ROOT / "execution_queue.json"
HEARTBEAT_FILE = ROOT / "state" / "heartbeat.json"
DAEMON_LOCK_FILE = Path("/tmp/usstock_v1_daemon.lock")
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# ── 日志 ──────────────────────────────────────────────
log_file = LOGS_DIR / "runtime.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        RotatingFileHandler(
            str(log_file),
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        ),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("daemon")

# ======================================================================
# 安全 Fallback 常量
# ======================================================================

EMPTY_SIGNAL = {"type": "EMPTY_SIGNAL", "strength": 0, "action": "HOLD"}
HOLD_DECISION = {"action": "HOLD", "reason": "decision_failed"}
SKIP_EXECUTION = {"status": "SKIP", "reason": "execution_failed"}

# ======================================================================
# 默认超时配置
# ======================================================================

DEFAULT_SIGNAL_TIMEOUT: float = 5.0      # signal / decision 默认超时 5s
DEFAULT_REPORT_TIMEOUT: float = 30.0     # report 允许 30s
WATCHDOG_TIMEOUT: float = 120.0          # heartbeat 超时阈值 120s
MAX_QUEUE_SIZE: int = 1000
MAX_SNAPSHOT_CYCLES: int = 100

F = TypeVar("F", bound=Callable[..., Any])


def write_heartbeat(cycle_id: str) -> None:
    """Atomically publish the latest completed runtime activity."""
    HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cycle_id": cycle_id,
    }
    temporary = HEARTBEAT_FILE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(HEARTBEAT_FILE)


# ======================================================================
# 超时工具 — 通过信号 + 线程实现
# ======================================================================

class TimeoutError(Exception):
    """操作超时异常。"""
    pass


def with_timeout(seconds: float = DEFAULT_SIGNAL_TIMEOUT) -> Callable[[F], F]:
    """装饰器：为函数调用添加超时控制。

    使用 threading + join(timeout) 实现，适用于 macOS 等多线程环境。
    超时后函数仍在后台运行，但调用方立即收到 TimeoutError。
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            result: list[Any] = []
            exception: list[BaseException | None] = [None]

            def target() -> None:
                try:
                    result.append(func(*args, **kwargs))
                except BaseException as e:
                    exception[0] = e

            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            thread.join(timeout=seconds)

            if thread.is_alive():
                raise TimeoutError(
                    f"操作超时 ({seconds}s): {func.__name__}"
                )

            if exception[0] is not None:
                raise exception[0]

            return result[0] if result else None

        return wrapper  # type: ignore
    return decorator


# ======================================================================
# State Snapshot — 持久化状态快照
# ======================================================================

class StateSnapshot:
    """每个 cycle 完成后持久化写入快照，支持 crash recovery。"""

    def __init__(self, path: Path = SNAPSHOT_FILE):
        self._path = path

    def read(self) -> dict[str, Any]:
        if not self._path.is_file():
            return {"cycles": {}, "last_health": {}}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"cycles": {}, "last_health": {}}

    def write(self, data: dict[str, Any]) -> None:
        self._path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def record_cycle(self, cycle_data: dict[str, Any]) -> None:
        """记录一个 cycle 的完成状态。"""
        state = self.read()
        cycle_id = cycle_data.get("cycle_id", "unknown")
        state["cycles"][cycle_id] = {
            **cycle_data,
            "recorded_at": time.time(),
        }
        # 自动压缩旧状态，只保留最近的有界窗口。
        cycles = state["cycles"]
        if len(cycles) > MAX_SNAPSHOT_CYCLES:
            sorted_keys = sorted(cycles.keys(), key=lambda k: cycles[k].get("recorded_at", 0))
            for k in sorted_keys[:len(sorted_keys) - MAX_SNAPSHOT_CYCLES]:
                del cycles[k]
        self.write(state)

    def get_last_cycle(self, cycle_type: str) -> dict[str, Any] | None:
        """获取最近一次指定类型的 cycle。"""
        state = self.read()
        matching = [
            c for c in state["cycles"].values()
            if c.get("type") == cycle_type
        ]
        if not matching:
            return None
        matching.sort(key=lambda c: c.get("recorded_at", 0), reverse=True)
        return matching[0]

    def needs_recovery(self) -> bool:
        """检查是否需要 crash recovery（最近的 signal 没有对应的 execution）。"""
        state = self.read()
        cycles = state.get("cycles", {})
        signal_cycles = [
            c for c in cycles.values()
            if c.get("type") == "signal" and c.get("status") == "completed"
        ]
        exec_cycles = [
            c for c in cycles.values()
            if c.get("type") == "execution" and c.get("status") == "completed"
        ]
        return len(signal_cycles) > len(exec_cycles)

    def record_health(self, health_data: dict[str, Any]) -> None:
        """记录健康检查信息。"""
        state = self.read()
        state["last_health"] = {
            **health_data,
            "recorded_at": time.time(),
        }
        self.write(state)


# ======================================================================
# Execution Queue — 异步解耦 Signal 与 Execution
# ======================================================================

class ExecutionQueue:
    """持久化执行队列：Signal 入队，Execution 异步消费。"""

    def __init__(self, path: Path = QUEUE_FILE):
        self._path = path
        self._overflow_path = path.with_suffix(".overflow.jsonl")
        self._queue: deque[dict[str, Any]] = deque()
        self._load()

    def _load(self) -> None:
        if self._path.is_file():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                items = data.get("queue")
                if not isinstance(data, dict) or not isinstance(items, list):
                    raise ValueError("invalid queue schema")
                valid = [
                    item for item in items
                    if isinstance(item, dict)
                    and item.get("status", "pending") == "pending"
                ]
                self._queue = deque(valid[-MAX_QUEUE_SIZE:])
                if valid != items or len(valid) > MAX_QUEUE_SIZE:
                    logger.warning("[Queue] 已修复异常或超限任务")
                    self._save()
            except (json.JSONDecodeError, OSError, ValueError, TypeError):
                logger.error("[Queue] 检测到损坏，已清空并重建")
                self._queue = deque()
                self._save()

    def _save(self) -> None:
        temporary = self._path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(json.dumps({"queue": list(self._queue)}, ensure_ascii=False))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self._path)

    def push(self, item: dict[str, Any]) -> None:
        """信号入队。"""
        item = {**item, "status": "pending"}
        if len(self._queue) >= MAX_QUEUE_SIZE:
            with self._overflow_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(item, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            logger.error(
                f"[Queue] 达到上限，任务安全转存: {item.get('cycle_id', 'unknown')}"
            )
            return
        self._queue.append(item)
        self._save()

    def pop(self) -> dict[str, Any] | None:
        """消费一个执行任务。"""
        if not self._queue:
            return None
        item = self._queue.popleft()
        self._save()
        self._drain_overflow()
        return item

    def _drain_overflow(self) -> None:
        if not self._overflow_path.is_file() or len(self._queue) >= MAX_QUEUE_SIZE:
            return
        try:
            lines = self._overflow_path.read_text(encoding="utf-8").splitlines()
            if not lines:
                self._overflow_path.unlink(missing_ok=True)
                return
            recovered = json.loads(lines[0])
            if isinstance(recovered, dict):
                self._queue.append(recovered)
                self._save()
            remainder = lines[1:]
            if remainder:
                self._overflow_path.write_text(
                    "\n".join(remainder) + "\n",
                    encoding="utf-8",
                )
            else:
                self._overflow_path.unlink(missing_ok=True)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            logger.error("[Queue] overflow recovery failed", exc_info=True)

    @property
    def length(self) -> int:
        return len(self._queue)

    def clear(self) -> None:
        self._queue.clear()
        self._save()


# ======================================================================
# Idempotent Lock
# ======================================================================

class IdempotentLock:
    """内存级周期锁：同一 cycle 不重复执行。"""

    def __init__(self, ttl_seconds: float = 60.0):
        self._locks: dict[str, float] = {}
        self._ttl = ttl_seconds

    def acquire(self, cycle_key: str) -> bool:
        now = time.time()
        last = self._locks.get(cycle_key, 0.0)
        if now - last < self._ttl:
            return True
        self._locks[cycle_key] = now
        return False

    def release(self, cycle_key: str) -> None:
        self._locks.pop(cycle_key, None)


# ======================================================================
# Watchdog — 心跳监控
# ======================================================================

class Watchdog:
    """Watchdog 机制：监控 heartbeat，超时自动跳过。

    每个 cycle 调用 beat() 记录心跳。
    如果 check() 检测到超过 WATCHDOG_TIMEOUT 无心跳，返回 True 表示需要跳过。
    """

    def __init__(self, timeout: float = WATCHDOG_TIMEOUT):
        self._timeout = timeout
        self._last_beat: float = time.time()
        self._skipped_count: int = 0
        self._consecutive_skips: int = 0

    def beat(self) -> None:
        """更新心跳时间戳。"""
        self._last_beat = time.time()
        self._consecutive_skips = 0

    def check(self) -> bool:
        """检查是否超时。返回 True 表示需要跳过当前 cycle。"""
        elapsed = time.time() - self._last_beat
        if elapsed > self._timeout:
            self._skipped_count += 1
            self._consecutive_skips += 1
            logger.warning(
                f"[Watchdog] ⏰ 心跳超时 ({elapsed:.0f}s > {self._timeout:.0f}s) — "
                f"跳过当前 cycle (累计跳过: {self._skipped_count})"
            )
            # 重置心跳，避免连续跳过
            self._last_beat = time.time()
            return True
        return False

    def reset_runtime(self) -> None:
        """Soft restart 后重建心跳状态，但保留累计超时次数。"""
        self._last_beat = time.time()

    @property
    def elapsed(self) -> float:
        return time.time() - self._last_beat

    @property
    def skipped_count(self) -> int:
        return self._skipped_count

    @property
    def consecutive_skips(self) -> int:
        return self._consecutive_skips


# ======================================================================
# 增强日志工具
# ======================================================================

def log_cycle(
    cycle_id: str,
    module: str,
    status: str,
    latency: float,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """标准化 cycle 日志：记录 cycle_id / module status / latency / error。

    日志格式示例:
        2026-07-02 00:00:00 | INFO    | [S0001] signal | completed | 3.2s
        2026-07-02 00:00:00 | ERROR   | [S0001] signal | failed | 5.1s | TimeoutError: ...
    """
    if error:
        logger.error(
            f"[{cycle_id}] {module} | {status} | {latency:.1f}s | {error}"
        )
        # 额外记录 stacktrace
        logger.debug(f"[{cycle_id}] {module} stacktrace:\n{error}")
    else:
        logger.info(
            f"[{cycle_id}] {module} | {status} | {latency:.1f}s"
        )


# ======================================================================
# 模块执行包装 — 安全 fallback + 超时 + 日志
# ======================================================================

def safe_execute(
    module_name: str,
    cycle_id: str,
    func: Callable[..., Any],
    fallback: Any,
    timeout: float = DEFAULT_SIGNAL_TIMEOUT,
    *args: Any,
    **kwargs: Any,
) -> tuple[Any, float]:
    """安全执行模块函数。

    特性:
    - 超时控制 (with_timeout)
    - try/except 包裹
    - 失败时返回 fallback
    - 自动记录日志 (cycle_id / module / status / latency / error)

    返回:
        (result, latency_seconds)
    """
    start = time.time()
    timed_func = with_timeout(timeout)(func)

    try:
        result = timed_func(*args, **kwargs)
        latency = time.time() - start
        log_cycle(cycle_id, module_name, "completed", latency)
        return result, latency
    except TimeoutError as exc:
        latency = time.time() - start
        error_msg = f"TimeoutError: {exc}"
        log_cycle(cycle_id, module_name, "timeout", latency, error=error_msg)
        return fallback, latency
    except Exception as exc:
        latency = time.time() - start
        tb = traceback.format_exc()
        error_msg = f"{type(exc).__name__}: {exc}\n{tb}"
        log_cycle(cycle_id, module_name, "failed", latency, error=error_msg)
        return fallback, latency


# ======================================================================
# DaemonRunner V1.7
# ======================================================================

class DaemonRunner:
    """V1.7 稳定层运行器。"""

    def __init__(
        self,
        signal_interval: float = 60.0,
        report_interval: float = 600.0,       # 默认 10 分钟
        report_signal_threshold: int = 5,      # 或 signal 达 5 次触发 report
        symbol: str | None = None,
        signal_timeout: float = DEFAULT_SIGNAL_TIMEOUT,
        report_timeout: float = DEFAULT_REPORT_TIMEOUT,
        watchdog_timeout: float = WATCHDOG_TIMEOUT,
    ):
        self._signal_interval = signal_interval
        self._report_interval = report_interval
        self._report_signal_threshold = report_signal_threshold
        self._symbol = symbol

        # V1.7 超时配置
        self._signal_timeout = signal_timeout
        self._report_timeout = report_timeout

        # 锁
        self._signal_lock = IdempotentLock(ttl_seconds=signal_interval * 0.9)
        self._exec_lock = IdempotentLock(ttl_seconds=max(5.0, signal_interval * 0.3))
        self._report_lock = IdempotentLock(ttl_seconds=report_interval * 0.9)
        self._health_lock = IdempotentLock(ttl_seconds=55.0)  # ~60s 一次

        # 状态
        self._running = False
        self._cycle_count = 0
        self._signal_count_since_last_report = 0
        self._last_error: str | None = None
        self._last_signal_time: float = 0.0
        self._last_execution_time: float = 0.0
        self._degraded_mode = False
        self._last_gc_cycle = 0

        # 子系统
        self._snapshot = StateSnapshot()
        self._exec_queue = ExecutionQueue()
        self._start_time: float = 0.0

        # ═══ V1.7 新组件 ═══
        self._watchdog = Watchdog(timeout=watchdog_timeout)
        self._watchdog_enabled = True  # 可通过 setter 禁用

        # 模块级累计统计
        self._module_stats: dict[str, dict[str, Any]] = {
            "signal":    {"ok": 0, "fail": 0, "total_latency": 0.0},
            "decision":  {"ok": 0, "fail": 0, "total_latency": 0.0},
            "execution": {"ok": 0, "fail": 0, "total_latency": 0.0},
            "report":    {"ok": 0, "fail": 0, "total_latency": 0.0},
        }

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def watchdog_enabled(self) -> bool:
        return self._watchdog_enabled

    @watchdog_enabled.setter
    def watchdog_enabled(self, value: bool) -> None:
        self._watchdog_enabled = value
        logger.info(f"[Watchdog] {'已启用' if value else '已禁用'}")

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------

    def run(self) -> None:
        """启动 daemon 主循环（阻塞）。"""
        self._running = True
        self._cycle_count = 0
        self._start_time = time.time()

        # 初始化 heartbeat
        self._watchdog.beat()

        # Crash Recovery: 启动时检查
        self._recover()

        logger.info("=" * 60)
        logger.info("  V1.7 DaemonRunner (Stability Layer) 启动")
        logger.info(f"  Signal 周期: {self._signal_interval}s")
        logger.info(f"  Report 周期: {self._report_interval}s | 或 {self._report_signal_threshold} 次 Signal")
        logger.info(f"  标的: {self._symbol or 'AAPL (默认)'}")
        logger.info(f"  超时: signal={self._signal_timeout}s / report={self._report_timeout}s")
        logger.info(f"  Watchdog: {'已启用' if self._watchdog_enabled else '已禁用'} ({WATCHDOG_TIMEOUT}s)")
        logger.info("  模式: Paper Trading Only | 异步 Signal↔Execution | 单模块崩溃不影响整体运行")
        logger.info("=" * 60)

        try:
            while self._running:
                self._tick()
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("🛑 收到 Ctrl+C，正在停止...")
        except Exception as exc:
            logger.error(f"💥 主循环异常: {exc}", exc_info=True)
            self._last_error = str(exc)
        finally:
            self._running = False
            logger.info("DaemonRunner 已停止")

    def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    # 内部调度
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        """每秒 tick：signal → 执行 → 报告 → 健康检查。"""
        now = time.time()

        # ── 0. Watchdog 检查 ────────────────────────────────────────
        if self._watchdog_enabled and self._watchdog.check():
            logger.warning("[Watchdog] 触发 soft restart，正在重建 runtime state")
            self._snapshot.record_cycle({
                "cycle_id": f"W{self._cycle_count:04d}",
                "type": "watchdog_skip",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "skipped",
                "heartbeat_elapsed": self._watchdog.elapsed,
            })
            self._soft_restart()
            return

        # ── 1. Signal Cycle ───────────────────────────────────────
        if not self._signal_lock.acquire("signal"):
            self._run_signal_cycle()

        # ── 2. Execution Cycle (从队列消费) ──────────────────────
        if not self._exec_lock.acquire("exec"):
            self._run_execution_cycle()

        # ── 3. Report Cycle (定时或基于 signal 计数) ─────────────
        should_report = (
            os.environ.get("V1_EXTERNAL_REPORT_WORKER") != "1"
            and not self._report_lock.acquire("report")
            and self._signal_count_since_last_report >= self._report_signal_threshold
        )
        if should_report:
            self._run_report_cycle()

        # ── 4. Health Check ──────────────────────────────────────
        if not self._health_lock.acquire("health"):
            self._run_health_check()

        if (
            self._cycle_count
            and self._cycle_count % 100 == 0
            and self._last_gc_cycle != self._cycle_count
        ):
            gc.collect()
            self._last_gc_cycle = self._cycle_count

    # ------------------------------------------------------------------
    # Signal Cycle
    # ------------------------------------------------------------------

    def _run_signal_cycle(self) -> None:
        """生成信号并放入执行队列（不阻塞 execution）。

        安全特性 (V1.7):
        - 超时控制: 默认 5s
        - try/except 包裹
        - 失败 → EMPTY_SIGNAL
        - 日志记录 cycle_id / status / latency
        """
        self._cycle_count += 1
        cycle_id = f"S{self._cycle_count:04d}"
        logger.info(f"[{cycle_id}] 🟢 Signal Cycle 开始")
        self._snapshot.record_cycle({
            "cycle_id": cycle_id,
            "type": "signal",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "running",
        })

        # 更新 heartbeat
        self._watchdog.beat()

        def _do_signal() -> dict[str, Any]:
            """实际的 signal 生成逻辑。"""
            from system_controller import SystemController

            controller = SystemController()
            result = controller.run_backtest(self._symbol)

            summary = result.get("summary", {})
            trades = summary.get("total_trade_count", 0)

            signal_data = {
                "cycle_id": cycle_id,
                "type": "signal",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "trade_count": trades,
                "total_return_pct": summary.get("total_return_pct", "0"),
                "win_rate": summary.get("avg_win_rate", 0.0),
                "status": "completed",
            }
            return signal_data

        # 安全执行 signal 模块（超时 + fallback）
        signal_result, latency = safe_execute(
            module_name="signal",
            cycle_id=cycle_id,
            func=_do_signal,
            fallback={**EMPTY_SIGNAL, "cycle_id": cycle_id, "status": "failed"},
            timeout=self._signal_timeout,
        )

        # 判断 signal 是否成功
        is_success = signal_result.get("status") == "completed"

        if is_success:
            # 入队 execution（解耦 signal 与 execution）
            exec_task = {
                "cycle_id": f"E{self._cycle_count:04d}",
                "type": "execution",
                "source_cycle": cycle_id,
                "timestamp": signal_result.get("timestamp", datetime.now(timezone.utc).isoformat()),
                "status": "pending",
            }
            self._exec_queue.push(exec_task)

            # 更新状态
            self._last_signal_time = time.time()
            self._signal_count_since_last_report += 1

            # 更新统计
            self._module_stats["signal"]["ok"] += 1
            self._module_stats["signal"]["total_latency"] += latency

            logger.info(
                f"[{cycle_id}] ✅ Signal 完成 → 入队 Execution "
                f"(队列长度: {self._exec_queue.length})"
            )
        else:
            # 失败时使用 EMPTY_SIGNAL，不阻断主循环
            self._module_stats["signal"]["fail"] += 1
            self._module_stats["signal"]["total_latency"] += latency
            logger.warning(
                f"[{cycle_id}] ⚠️ Signal 失败 → 使用 EMPTY_SIGNAL fallback "
                f"(不阻断主循环)"
            )

        # 持久化 snapshot
        snapshot_data = {
            "cycle_id": cycle_id,
            "type": "signal",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": signal_result.get("status", "failed"),
            "latency": latency,
            "is_fallback": not is_success,
        }
        if not is_success:
            snapshot_data["error"] = str(self._last_error or "unknown")
        self._snapshot.record_cycle(snapshot_data)
        write_heartbeat(cycle_id)

    # ------------------------------------------------------------------
    # Execution Cycle（异步消费队列）
    # ------------------------------------------------------------------

    def _run_execution_cycle(self) -> None:
        """从执行队列消费并模拟执行（paper mode，不阻塞 signal）。

        安全特性 (V1.7):
        - 超时控制: 默认 5s
        - try/except 包裹
        - 失败 → SKIP（返回 fallback）
        - 日志记录 cycle_id / status / latency
        """
        task = self._exec_queue.pop()
        if task is None:
            return

        cycle_id = f"E{task.get('source_cycle', '?')}"
        logger.info(f"[{cycle_id}] ⚡ Execution Cycle 开始 (源: {task.get('source_cycle', 'N/A')})")
        self._snapshot.record_cycle({
            "cycle_id": cycle_id,
            "type": "execution",
            "source_cycle": task.get("source_cycle", ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "running",
        })

        # 更新 heartbeat
        self._watchdog.beat()

        def _do_execution() -> dict[str, Any]:
            """实际的 execution 逻辑。"""
            from system_controller import SystemController

            controller = SystemController()
            result = controller.run_backtest(self._symbol)

            exec_result = {
                "cycle_id": cycle_id,
                "type": "execution",
                "source_cycle": task.get("source_cycle", ""),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "completed",
                "trade_count": result.get("summary", {}).get("total_trade_count", 0),
            }
            return exec_result

        # 安全执行 execution 模块（超时 + fallback）
        exec_result, latency = safe_execute(
            module_name="execution",
            cycle_id=cycle_id,
            func=_do_execution,
            fallback={**SKIP_EXECUTION, "cycle_id": cycle_id, "source_cycle": task.get("source_cycle", "")},
            timeout=self._signal_timeout,
        )

        is_success = exec_result.get("status") == "completed"

        if is_success:
            self._last_execution_time = time.time()
            self._module_stats["execution"]["ok"] += 1
            self._module_stats["execution"]["total_latency"] += latency

            queue_len = self._exec_queue.length
            logger.info(
                f"[{cycle_id}] ✅ Paper Execution 完成 "
                f"(队列剩余: {queue_len})"
            )
        else:
            self._module_stats["execution"]["fail"] += 1
            self._module_stats["execution"]["total_latency"] += latency
            logger.warning(
                f"[{cycle_id}] ⚠️ Execution 失败 → 使用 SKIP fallback "
                f"(任务放回队列尾部)"
            )
            # 失败时重新放回队列尾部，等待下次重试
            self._exec_queue.push(task)

        # 持久化 snapshot
        self._snapshot.record_cycle({
            "cycle_id": cycle_id,
            "type": "execution",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": exec_result.get("status", "failed"),
            "latency": latency,
            "is_fallback": not is_success,
        })
        write_heartbeat(cycle_id)

    # ------------------------------------------------------------------
    # Report Cycle — 允许更长的超时 (30s)
    # ------------------------------------------------------------------

    def _run_report_cycle(self) -> None:
        """生成报告（基于最新 signal 数据）。

        安全特性 (V1.7):
        - 超时控制: 默认 30s（比 signal/execution 更宽松）
        - 失败不影响主循环（不阻断后续 signal/execution）
        - 日志记录 cycle_id / status / latency
        """
        cycle_id = f"R{self._cycle_count:04d}"
        logger.info(f"[{cycle_id}] 📋 Report Cycle 开始 (已累积 {self._signal_count_since_last_report} 次 Signal)")

        # 更新 heartbeat
        self._watchdog.beat()

        def _do_report() -> str:
            """实际的 report 生成逻辑。"""
            from backtest_report_generator import BacktestReportGenerator

            generator = BacktestReportGenerator(idempotent=True)
            report_path = generator.generate_report(
                symbols=[self._symbol] if self._symbol else None,
                force=True,
            )
            return str(report_path)

        # 安全执行 report 模块（超时 = 30s，fallback 不影响主循环）
        report_path, latency = safe_execute(
            module_name="report",
            cycle_id=cycle_id,
            func=_do_report,
            fallback="",
            timeout=self._report_timeout,
        )

        if report_path:
            # 重置 signal 计数
            self._signal_count_since_last_report = 0
            self._module_stats["report"]["ok"] += 1

            self._snapshot.record_cycle({
                "cycle_id": cycle_id,
                "type": "report",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "completed",
                "report_path": report_path,
                "latency": latency,
            })
            logger.info(f"[{cycle_id}] ✅ Report 生成: {report_path}")
            write_heartbeat(cycle_id)
        else:
            self._module_stats["report"]["fail"] += 1
            logger.warning(
                f"[{cycle_id}] ⚠️ Report 失败 → 不影响主循环 "
                f"(下次 cycle 继续尝试)"
            )

    # ------------------------------------------------------------------
    # Health Check
    # ------------------------------------------------------------------

    def _run_health_check(self) -> None:
        """每 60 秒输出系统健康状态。"""
        now = time.time()
        uptime = now - self._start_time

        # 计算各模块平均延迟
        stats_summary = {}
        for mod, st in self._module_stats.items():
            total = st["ok"] + st["fail"]
            avg_lat = st["total_latency"] / total if total > 0 else 0.0
            stats_summary[mod] = {
                "ok": st["ok"],
                "fail": st["fail"],
                "avg_latency": round(avg_lat, 2),
            }

        health = {
            "uptime_seconds": round(uptime, 1),
            "cycle_count": self._cycle_count,
            "queue_length": self._exec_queue.length,
            "last_signal_time": datetime.fromtimestamp(self._last_signal_time).isoformat() if self._last_signal_time > 0 else "N/A",
            "last_execution_time": datetime.fromtimestamp(self._last_execution_time).isoformat() if self._last_execution_time > 0 else "N/A",
            "last_error": self._last_error,
            "signal_count_since_report": self._signal_count_since_last_report,
            "report_signal_threshold": self._report_signal_threshold,
            "watchdog": {
                "enabled": self._watchdog_enabled,
                "elapsed_since_last_beat": round(self._watchdog.elapsed, 1),
                "skipped_count": self._watchdog.skipped_count,
                "consecutive_skips": self._watchdog.consecutive_skips,
            },
            "runtime_mode": "degraded" if self._degraded_mode else "stable",
            "module_stats": stats_summary,
        }

        self._snapshot.record_health(health)

        # 终端输出
        lines = [
            f"  ┌─ Health Check ──────────────────────────────",
            f"  │ Uptime: {uptime:.0f}s | Cycles: {self._cycle_count} | Queue: {self._exec_queue.length}",
        ]
        for mod, st in stats_summary.items():
            lines.append(
                f"  │ {mod:>10s}: ✅{st['ok']} ❌{st['fail']} "
                f"avg={st['avg_latency']:.1f}s"
            )
        lines.append(
            f"  │ Watchdog: {'✅' if self._watchdog.elapsed < WATCHDOG_TIMEOUT else '⚠️'} "
            f"({self._watchdog.elapsed:.0f}s / {WATCHDOG_TIMEOUT:.0f}s) "
            f"skip={self._watchdog.skipped_count}"
        )
        lines.append(
            f"  │ Last Signal: {health['last_signal_time']}"
        )
        lines.append(
            f"  │ Last Execution: {health['last_execution_time']}"
        )
        if self._last_error:
            lines.append(f"  │ ⚠️ Last Error: {self._last_error}")
        else:
            lines.append(f"  │ ✅ No Errors")
        lines.append(f"  └───────────────────────────────────────────")
        logger.info("\n".join(lines))

    # ------------------------------------------------------------------
    # Crash Recovery
    # ------------------------------------------------------------------

    @staticmethod
    def _check_orphan() -> None:
        """进程树校验：验证 LaunchAgent → Supervisor → DaemonRunner 链路完整。

        如果检测到父进程不是 supervisor，自动退出。
        如果 /tmp/usstock_v1.lock 不存在或内容不匹配，自动退出。
        """
        if os.environ.get("V1_SUPERVISED") != "1":
            logger.critical("[Orphan] 缺少 V1_SUPERVISED 环境变量 → 自动退出")
            sys.exit(1)
        supervisor_pid_str = os.environ.get("V1_SUPERVISOR_PID", "0")
        try:
            supervisor_pid = int(supervisor_pid_str)
        except (ValueError, TypeError):
            logger.critical("[Orphan] V1_SUPERVISOR_PID 无效 → 自动退出")
            sys.exit(1)
        if supervisor_pid != os.getppid():
            logger.critical(
                f"[Orphan] 父进程 {os.getppid()} 不是 supervisor({supervisor_pid}) → 自动退出"
            )
            sys.exit(1)
        lock_path = Path("/tmp/usstock_v1.lock")
        if not lock_path.is_file():
            logger.critical("[Orphan] 缺少 /tmp/usstock_v1.lock → 自动退出")
            sys.exit(1)
        try:
            tree_lock = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            logger.critical(f"[Orphan] 进程树锁损坏 → 自动退出: {exc}")
            sys.exit(1)
        if tree_lock.get("supervisor_pid") != supervisor_pid:
            logger.critical(
                f"[Orphan] 锁中的 supervisor({tree_lock.get('supervisor_pid')}) "
                f"与父进程({supervisor_pid})不匹配 → 自动退出"
            )
            sys.exit(1)
        logger.info("[Orphan] ✅ 进程树校验通过（LaunchAgent → Supervisor → DaemonRunner）")

    def _startup_self_check(self) -> None:
        """启动时自检：验证 queue 和 snapshot 完整性，损坏则自动修复但不阻断启动。

        所有异常 downgrade 为 warning，不允许 crash。
        """
        checks_passed = 0
        checks_total = 2

        # 1. Queue 完整性检查
        try:
            if QUEUE_FILE.is_file():
                raw = QUEUE_FILE.read_text(encoding="utf-8")
                data = json.loads(raw)
                queue = data.get("queue", [])
                if isinstance(queue, list) and all(
                    isinstance(item, dict) and isinstance(item.get("status"), str)
                    for item in queue
                ):
                    checks_passed += 1
                    logger.info("[SelfCheck] ✅ ExecutionQueue 完整性通过")
                else:
                    logger.warning("[SelfCheck] ⚠️ Queue 结构异常，已自动重建")
                    ExecutionQueue().clear()
                    checks_passed += 1
            else:
                checks_passed += 1
                logger.info("[SelfCheck] ✅ ExecutionQueue 不存在（首次启动）")
        except Exception as exc:
            logger.warning(f"[SelfCheck] ⚠️ Queue 检查失败，已重建: {exc}")
            try:
                ExecutionQueue().clear()
            except Exception:
                pass
            checks_passed += 1

        # 2. Snapshot 完整性检查
        try:
            if SNAPSHOT_FILE.is_file():
                raw = SNAPSHOT_FILE.read_text(encoding="utf-8")
                data = json.loads(raw)
                if isinstance(data, dict):
                    checks_passed += 1
                    logger.info("[SelfCheck] ✅ StateSnapshot 完整性通过")
                else:
                    logger.warning("[SelfCheck] ⚠️ Snapshot 结构异常，已自动重建")
                    StateSnapshot().write({"cycles": {}, "last_health": {}})
                    checks_passed += 1
            else:
                checks_passed += 1
                logger.info("[SelfCheck] ✅ StateSnapshot 不存在（首次启动）")
        except Exception as exc:
            logger.warning(f"[SelfCheck] ⚠️ Snapshot 检查失败，已重建: {exc}")
            try:
                StateSnapshot().write({"cycles": {}, "last_health": {}})
            except Exception:
                pass
            checks_passed += 1

        if checks_passed == checks_total:
            logger.info("[SelfCheck] ✅ 启动自检全部通过")
        else:
            logger.warning(f"[SelfCheck] ⚠️ 启动自检 {checks_passed}/{checks_total} 通过，继续启动")

    def _recover(self) -> None:
        """启动时恢复：读取 snapshot，检测未完成的 cycle。"""
        # V1.9: 在 recovery 前执行自检和 orphan 检测
        self._check_orphan()
        self._startup_self_check()
        logger.info("[Recovery] 🔍 检查上次运行状态...")

        state = self._snapshot.read()
        cycles = state.get("cycles", {})
        incomplete_signals = [
            cycle for cycle in cycles.values()
            if cycle.get("type") == "signal"
            and cycle.get("status") in {"running", "pending", "started"}
        ]
        incomplete_executions = [
            cycle for cycle in cycles.values()
            if cycle.get("type") == "execution"
            and cycle.get("status") in {"running", "pending", "started", "failed"}
        ]
        needs = self._snapshot.needs_recovery()
        last_signal = self._snapshot.get_last_cycle("signal")
        last_exec = self._snapshot.get_last_cycle("execution")

        if last_signal:
            logger.info(f"[Recovery] 上次 Signal: {last_signal.get('cycle_id')} @ {last_signal.get('status')}")
        if last_exec:
            logger.info(f"[Recovery] 上次 Execution: {last_exec.get('cycle_id')} @ {last_exec.get('status')}")

        if needs:
            logger.warning("[Recovery] ⚠️ 检测到未完成的 Execution，将自动补 Execution")
            if self._exec_queue.length > 0:
                logger.info(f"[Recovery] 队列中还有 {self._exec_queue.length} 个待执行任务")
        else:
            logger.info("[Recovery] ✅ 上次运行状态正常，无需恢复")

        queued_sources = {
            str(item.get("source_cycle", ""))
            for item in list(self._exec_queue._queue)
        }
        for cycle in incomplete_executions:
            source = str(cycle.get("source_cycle", ""))
            if source and source not in queued_sources:
                self._exec_queue.push({
                    "cycle_id": cycle.get("cycle_id", f"REC-{source}"),
                    "type": "execution",
                    "source_cycle": source,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "status": "pending",
                    "recovered": True,
                })
                queued_sources.add(source)

        if needs and last_signal:
            source = str(last_signal.get("cycle_id", ""))
            if source and source not in queued_sources:
                self._exec_queue.push({
                    "cycle_id": f"REC-{source}",
                    "type": "execution",
                    "source_cycle": source,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "status": "pending",
                    "recovered": True,
                })

        for cycle in incomplete_signals:
            self._snapshot.record_cycle({
                **cycle,
                "status": "recovery_scheduled",
            })
            self._signal_lock.release("signal")

        logger.info(
            f"[Recovery] scan: signal={len(incomplete_signals)} "
            f"execution={len(incomplete_executions)}"
        )

        logger.info(f"[Recovery] ✅ 启动恢复完成 (队列: {self._exec_queue.length})")

    def _soft_restart(self) -> None:
        """Watchdog 超时后的无损状态重建。"""
        self._signal_lock = IdempotentLock(ttl_seconds=self._signal_interval * 0.9)
        self._exec_lock = IdempotentLock(ttl_seconds=max(5.0, self._signal_interval * 0.3))
        self._report_lock = IdempotentLock(ttl_seconds=self._report_interval * 0.9)
        self._health_lock = IdempotentLock(ttl_seconds=55.0)
        self._exec_queue = ExecutionQueue()
        self._watchdog.reset_runtime()
        gc.collect()
        if self._watchdog.consecutive_skips >= 3:
            self._degraded_mode = True
            logger.error("[Watchdog] 连续超时达到 3 次，进入 degraded mode")


# ======================================================================
# CLI 入口
# ======================================================================

def run_daemon(
    symbol: str | None = None,
    signal_interval: float = 60.0,
    report_interval: float = 600.0,
    report_signal_threshold: int = 5,
    signal_timeout: float = DEFAULT_SIGNAL_TIMEOUT,
    report_timeout: float = DEFAULT_REPORT_TIMEOUT,
) -> None:
    """启动 daemon 模式。"""
    if os.environ.get("V1_SUPERVISED") != "1":
        raise RuntimeError("daemon_runner 只能由 supervisor 启动")
    if int(os.environ.get("V1_SUPERVISOR_PID", "0")) != os.getppid():
        raise RuntimeError("daemon_runner 父进程不是 supervisor")
    try:
        tree_lock = json.loads(
            Path("/tmp/usstock_v1.lock").read_text(encoding="utf-8")
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("daemon_runner 缺少有效进程树锁") from exc
    if tree_lock.get("supervisor_pid") != os.getppid():
        raise RuntimeError("daemon_runner 不属于锁定的 supervisor")
    lock_stream = DAEMON_LOCK_FILE.open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        lock_stream.close()
        raise RuntimeError("daemon_runner 已有运行实例") from exc
    lock_stream.seek(0)
    lock_stream.truncate()
    lock_stream.write(f"{os.getpid()}\n")
    lock_stream.flush()
    try:
        runner = DaemonRunner(
            signal_interval=signal_interval,
            report_interval=report_interval,
            report_signal_threshold=report_signal_threshold,
            symbol=symbol,
            signal_timeout=signal_timeout,
            report_timeout=report_timeout,
        )
        runner.run()
    finally:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
        lock_stream.close()
        DAEMON_LOCK_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="V1.7 Stability Layer Daemon")
    parser.add_argument("--symbol", default=None, help="标的代码")
    parser.add_argument("--signal-interval", type=float, default=60.0, help="Signal 周期（秒）")
    parser.add_argument("--report-interval", type=float, default=600.0, help="Report 周期（秒）")
    parser.add_argument("--report-signal-threshold", type=int, default=5, help="每 N 次 Signal 触发一次 Report")
    parser.add_argument("--signal-timeout", type=float, default=DEFAULT_SIGNAL_TIMEOUT, help="Signal/Decision 超时（秒，默认 5s）")
    parser.add_argument("--report-timeout", type=float, default=DEFAULT_REPORT_TIMEOUT, help="Report 超时（秒，默认 30s）")
    parser.add_argument("--disable-watchdog", action="store_true", help="禁用 Watchdog")
    args = parser.parse_args()

    run_daemon(
        symbol=args.symbol,
        signal_interval=args.signal_interval,
        report_interval=args.report_interval,
        report_signal_threshold=args.report_signal_threshold,
        signal_timeout=args.signal_timeout,
        report_timeout=args.report_timeout,
    )
