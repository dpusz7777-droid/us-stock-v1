#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""历史操作记录 — 持久化交易日志。

使用 JSON 文件本地持久化，不连数据库。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


TRADE_LOG_FILE = Path(__file__).parent / "trade_history.json"


@dataclass(frozen=True)
class TradeRecord:
    """一条交易记录。"""
    timestamp: str
    symbol: str
    action: str  # "buy" | "sell" | "hold"
    price: float | None
    quantity: int
    reason: str
    source: str  # "system" | "manual"
    pnl: float | None = None
    tags: tuple[str, ...] = ()


class TradeHistory:
    """交易历史记录。

    用法：
        th = TradeHistory()
        th.record("NVDA", "buy", price=195.0, qty=10, reason="信号触发")
        recent = th.recent(5)
    """

    def __init__(self, path: Path = TRADE_LOG_FILE) -> None:
        self._path = path
        self._entries: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                raise ValueError(f"trade history must be a JSON list: {self._path}")
            self._entries = data

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._entries, f, ensure_ascii=False, indent=2)

    def save(self) -> Path:
        """Persist the current records, including a legitimate empty history."""
        self._save()
        return self._path

    def all(self) -> list[TradeRecord]:
        """Return all records in chronological order."""
        return [TradeRecord(**entry) for entry in self._entries]

    def record(
        self,
        symbol: str,
        action: str,
        price: float | None = None,
        quantity: int = 0,
        reason: str = "",
        source: str = "system",
        tags: tuple[str, ...] = (),
    ) -> None:
        """记录一条新交易。"""
        self._entries.append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": symbol.upper(),
            "action": action,
            "price": price,
            "quantity": quantity,
            "reason": reason,
            "source": source,
            "pnl": None,
            "tags": list(tags),
        })
        self._save()

    def recent(self, n: int = 10) -> list[TradeRecord]:
        """获取最近 n 条记录。"""
        recent = self._entries[-n:]
        recent.reverse()
        return [TradeRecord(**e) for e in recent]

    def by_symbol(self, symbol: str) -> list[TradeRecord]:
        """按标的筛选。"""
        return [
            TradeRecord(**e)
            for e in self._entries
            if e.get("symbol", "").upper() == symbol.upper()
        ]

    def by_action(self, action: str) -> list[TradeRecord]:
        """按操作类型筛选。"""
        return [TradeRecord(**e) for e in self._entries if e.get("action") == action]

    def count(self) -> int:
        """总记录数。"""
        return len(self._entries)

    def clear(self) -> None:
        """清空记录。"""
        self._entries = []
        self._save()
