#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""决策记忆层 — 持久化所有 BUY / SELL / HOLD 决策记录。

每条决策包含：
- id: 唯一标识
- timestamp: 决策时间
- symbol: 股票代码
- action: BUY / SELL / HOLD
- price: 决策时的价格
- reason: 决策原因
- source: 来源 (system / manual / v37 / v39 / v40 / v41)
- strategy_type: 策略类型 (momentum / defensive / breakout / mean_reversion)
- market_regime: 当前市场状态
- pnl: 后续盈亏（回测时填写）
- tags: 标签列表

用法：
    from northstar.data.decision_memory import DecisionMemory
    dm = DecisionMemory()
    dm.record("AAPL", "BUY", price=150.0, reason="momentum signal")
    history = dm.get_all()
    by_symbol = dm.by_symbol("AAPL")
    backtest_data = dm.get_backtest_snapshot()
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_DECISION_LOG = Path(__file__).resolve().parent / "decision_log.json"


class DecisionMemory:
    """决策记忆层 — 持久化交易决策记录。"""

    def __init__(self, file_path: str | Path = "") -> None:
        self.file_path: Path = Path(file_path) if file_path else DEFAULT_DECISION_LOG
        self._entries: list[dict[str, Any]] = []
        self._ensure_file()

    def _ensure_file(self) -> None:
        """确保 JSON 文件存在，不存在则创建空列表。"""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump([], f)
        self._load()

    def _load(self) -> None:
        """从 JSON 文件加载决策记录。"""
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self._entries = data
            else:
                self._entries = []
        except (json.JSONDecodeError, IOError):
            self._entries = []

    def _save(self) -> None:
        """将决策记录持久化到 JSON 文件。"""
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(self._entries, f, ensure_ascii=False, indent=2)

    def _next_id(self) -> int:
        """生成下一个唯一 ID。"""
        if not self._entries:
            return 1
        return max(e.get("id", 0) for e in self._entries) + 1

    def record(
        self,
        symbol: str,
        action: str,
        price: float | None = None,
        reason: str = "",
        source: str = "system",
        strategy_type: str = "",
        market_regime: str = "",
        tags: list[str] | None = None,
    ) -> int:
        """记录一条决策。

        Args:
            symbol: 股票代码
            action: BUY / SELL / HOLD
            price: 决策时的价格
            reason: 决策原因
            source: 来源 (system / manual / v37 / v39 / v40 / v41)
            strategy_type: 策略类型
            market_regime: 当前市场状态
            tags: 标签列表

        Returns:
            int: 决策 ID
        """
        entry_id = self._next_id()
        entry: dict[str, Any] = {
            "id": entry_id,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": symbol.upper(),
            "action": action,
            "price": price,
            "reason": reason,
            "source": source,
            "strategy_type": strategy_type,
            "market_regime": market_regime,
            "pnl": None,
            "tags": tags or [],
        }
        self._entries.append(entry)
        self._save()
        return entry_id

    def get_all(self) -> list[dict[str, Any]]:
        """获取所有决策记录（按时间正序）。"""
        return list(self._entries)

    def get_recent(self, n: int = 10) -> list[dict[str, Any]]:
        """获取最近 n 条决策记录。"""
        recent = self._entries[-n:]
        recent.reverse()
        return recent

    def by_symbol(self, symbol: str) -> list[dict[str, Any]]:
        """按股票代码筛选。"""
        s = symbol.upper()
        return [e for e in self._entries if e.get("symbol") == s]

    def by_action(self, action: str) -> list[dict[str, Any]]:
        """按决策动作筛选。"""
        return [e for e in self._entries if e.get("action") == action]

    def by_source(self, source: str) -> list[dict[str, Any]]:
        """按来源筛选。"""
        return [e for e in self._entries if e.get("source") == source]

    def by_date_range(self, start: str, end: str) -> list[dict[str, Any]]:
        """按日期范围筛选（格式: YYYY-MM-DD）。"""
        return [
            e for e in self._entries
            if start <= (e.get("timestamp", "")[:10]) <= end
        ]

    def count(self) -> int:
        """总决策数。"""
        return len(self._entries)

    def count_by_action(self) -> dict[str, int]:
        """按决策动作统计。"""
        counts: dict[str, int] = {}
        for e in self._entries:
            a = e.get("action", "UNKNOWN")
            counts[a] = counts.get(a, 0) + 1
        return counts

    def count_by_source(self) -> dict[str, int]:
        """按来源统计。"""
        counts: dict[str, int] = {}
        for e in self._entries:
            s = e.get("source", "unknown")
            counts[s] = counts.get(s, 0) + 1
        return counts

    def update_pnl(self, entry_id: int, pnl: float) -> bool:
        """更新指定决策的盈亏。"""
        for e in self._entries:
            if e.get("id") == entry_id:
                e["pnl"] = round(pnl, 2)
                self._save()
                return True
        return False

    def get_backtest_snapshot(self) -> list[dict[str, Any]]:
        """获取用于回测的决策快照（只包含有价格的非 HOLD 决策）。"""
        snapshot = []
        for e in self._entries:
            if e.get("action") != "HOLD" and e.get("price") is not None:
                snapshot.append({
                    "symbol": e.get("symbol"),
                    "action": e.get("action"),
                    "price": e.get("price"),
                    "date": (e.get("timestamp") or "")[:10],
                    "strategy_type": e.get("strategy_type", ""),
                    "market_regime": e.get("market_regime", ""),
                })
        return snapshot

    def clear(self) -> None:
        """清空所有决策记录。"""
        self._entries = []
        self._save()

    def delete_by_id(self, entry_id: int) -> bool:
        """删除指定 ID 的决策。"""
        for i, e in enumerate(self._entries):
            if e.get("id") == entry_id:
                self._entries.pop(i)
                self._save()
                return True
        return False