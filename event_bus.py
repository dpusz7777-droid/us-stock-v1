#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EventBus — 轻量进程内事件系统。

架构说明
--------
纯 Python 内存实现，同步执行，无线程、无网络、无外部依赖。
用于解耦各模块之间的直接调用关系。

使用方式
--------
from event_bus import event_bus
from events import MARKET_DATA_UPDATED

# 订阅
def on_market_update(data):
    print(f"Market updated: {data}")

event_bus.subscribe(MARKET_DATA_UPDATED, on_market_update)

# 发布
event_bus.publish(MARKET_DATA_UPDATED, {"symbols": ["AAPL"]})

安全要求
---------
1. 不允许调用网络
2. 不允许访问 API Key
3. 不允许写文件
4. 不允许影响交易逻辑
5. 出错不能影响主流程（handler 异常被捕获）
"""

from __future__ import annotations

import traceback
from datetime import datetime, timezone
from typing import Any, Callable

from events import ALL_EVENTS

# 日志记录类型
EventHandler = Callable[[Any], None]


@staticmethod
def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class EventLogEntry:
    """单条事件日志。"""

    __slots__ = ("timestamp", "event_name", "payload_summary", "handler_count", "success_count", "fail_count", "error_messages")

    def __init__(
        self,
        timestamp: str,
        event_name: str,
        payload_summary: str,
        handler_count: int,
        success_count: int,
        fail_count: int,
        error_messages: list[str],
    ):
        self.timestamp = timestamp
        self.event_name = event_name
        self.payload_summary = payload_summary
        self.handler_count = handler_count
        self.success_count = success_count
        self.fail_count = fail_count
        self.error_messages = error_messages

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "event_name": self.event_name,
            "payload_summary": self.payload_summary,
            "handler_count": self.handler_count,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "error_messages": list(self.error_messages),
        }

    def __repr__(self) -> str:
        return (
            f"EventLogEntry(event={self.event_name}, "
            f"handlers={self.handler_count}, "
            f"success={self.success_count}, "
            f"fail={self.fail_count})"
        )


class EventBus:
    """轻量同步事件总线。

    特性：
    - 纯 Python 内存实现
    - 同步执行（不使用线程池）
    - handler 异常被 try/except 包裹，不影响其他 handler
    - 维护内存 event_log，不写文件
    - 单例模式：使用 event_bus 全局实例
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}
        self._event_log: list[EventLogEntry] = []
        self._max_log_size = 1000

    # ------------------------------------------------------------------
    # 核心 API
    # ------------------------------------------------------------------

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        """订阅事件。handler 必须是可调用对象。"""
        if not callable(handler):
            raise TypeError(f"handler must be callable, got {type(handler)}")
        if event_name not in self._handlers:
            self._handlers[event_name] = []
        if handler not in self._handlers[event_name]:
            self._handlers[event_name].append(handler)

    def publish(self, event_name: str, data: Any = None) -> None:
        """发布事件。同步执行所有已注册 handler。

        handler 异常被捕获并记录到 event_log，不影响其他 handler 执行。
        """
        handlers = list(self._handlers.get(event_name, []))
        success_count = 0
        fail_count = 0
        error_messages: list[str] = []

        for handler in handlers:
            try:
                handler(data)
                success_count += 1
            except Exception as exc:
                fail_count += 1
                tb = traceback.format_exception_only(type(exc), exc)
                error_messages.append(f"{handler.__name__}: {''.join(tb).strip()}")
            except BaseException as exc:
                # Also catch SystemExit/KeyboardInterrupt for safety
                fail_count += 1
                error_messages.append(f"{handler.__name__}: {exc}")

        self._log_entry(
            event_name=event_name,
            data=data,
            handler_count=len(handlers),
            success_count=success_count,
            fail_count=fail_count,
            error_messages=error_messages,
        )

    def unsubscribe(self, event_name: str, handler: EventHandler) -> None:
        """取消订阅。如果 handler 不在列表中，静默忽略。"""
        handlers = self._handlers.get(event_name)
        if handlers is None:
            return
        try:
            handlers.remove(handler)
        except ValueError:
            pass
        # 清理空列表
        if not handlers:
            del self._handlers[event_name]

    def clear(self, event_name: str | None = None) -> None:
        """清除指定事件的所有 handler。如果不指定事件，清除所有。"""
        if event_name is None:
            self._handlers.clear()
        else:
            self._handlers.pop(event_name, None)

    def list_events(self) -> list[str]:
        """返回当前有订阅的事件名称列表。"""
        return sorted(self._handlers.keys())

    # ------------------------------------------------------------------
    # 日志
    # ------------------------------------------------------------------

    @property
    def event_log(self) -> list[EventLogEntry]:
        """返回事件日志（只读视图）。"""
        return list(self._event_log)

    def clear_log(self) -> None:
        """清除事件日志。"""
        self._event_log.clear()

    def _log_entry(
        self,
        event_name: str,
        data: Any,
        handler_count: int,
        success_count: int,
        fail_count: int,
        error_messages: list[str],
    ) -> None:
        """写入单条事件日志。"""
        payload_summary = self._summarize_payload(data)
        entry = EventLogEntry(
            timestamp=_now_iso(),
            event_name=event_name,
            payload_summary=payload_summary,
            handler_count=handler_count,
            success_count=success_count,
            fail_count=fail_count,
            error_messages=error_messages,
        )
        self._event_log.append(entry)
        # 限制日志大小
        if len(self._event_log) > self._max_log_size:
            self._event_log = self._event_log[-self._max_log_size:]

    @staticmethod
    def _summarize_payload(data: Any) -> str:
        """生成 payload 摘要（避免记录敏感信息）。"""
        if data is None:
            return "None"
        if isinstance(data, dict):
            keys = list(data.keys())
            return f"dict(keys={keys[:5]})"
        if isinstance(data, (list, tuple)):
            return f"{type(data).__name__}(len={len(data)})"
        text = str(data)
        if len(text) > 80:
            return text[:77] + "..."
        return text


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

event_bus = EventBus()

# ---------------------------------------------------------------------------
# Dashboard 监听器（只读，记录最新事件时间）
# ---------------------------------------------------------------------------


class _DashboardEventListener:
    """Dashboard 事件监听器。

    仅记录最新的各事件触发时间，不强制刷新 UI，不修改原输出逻辑。
    """

    def __init__(self) -> None:
        self._last_event_times: dict[str, str] = {}

    def on_event(self, data: Any = None) -> None:
        """通用事件监听回调。从调用栈推断事件名。"""
        # 无法从 data 推断事件名，需要外部注册时指定
        pass

    def make_handler(self, event_name: str) -> EventHandler:
        """创建针对特定事件的 handler。"""
        def handler(data: Any = None) -> None:
            self._last_event_times[event_name] = _now_iso()
        handler.__name__ = f"dashboard_listener_{event_name.lower()}"
        return handler

    def last_event_time(self, event_name: str) -> str | None:
        """返回指定事件的最新触发时间。"""
        return self._last_event_times.get(event_name)

    @property
    def all_times(self) -> dict[str, str]:
        """返回所有已记录事件的最新时间。"""
        return dict(self._last_event_times)

    def subscribe_all(self, bus: EventBus) -> None:
        """订阅所有标准事件。"""
        for event_name in ALL_EVENTS:
            bus.subscribe(event_name, self.make_handler(event_name))


# 全局 Dashboard 监听器实例
dashboard_listener = _DashboardEventListener()