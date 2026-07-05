#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多策略组合系统 — 管理多个策略版本并通过投票机制生成组合信号。

用法：
    from northstar.ensemble.strategy_ensemble import StrategyEnsemble
    ensemble = StrategyEnsemble()
    ensemble.add_strategy("baseline", signals_baseline)
    combined = ensemble.combine_signals()
"""

from __future__ import annotations

from typing import Any

SIGNAL_PRIORITY = {"BUY": 3, "WATCH": 2, "AVOID": 1}


class StrategyEnsemble:
    """策略组合层 — 管理多个策略版本，通过投票生成最终信号。"""

    def __init__(self) -> None:
        self._strategies: dict[str, list[dict[str, Any]]] = {}

    def add_strategy(self, name: str, signals: list[dict[str, Any]]) -> None:
        """添加一个策略版本的信号。"""
        self._strategies[name] = signals

    def get_active_strategies(self) -> list[str]:
        """获取所有已注册的策略名称。"""
        return list(self._strategies.keys())

    def _vote(self, symbol_signals: list[dict[str, Any]]) -> dict[str, Any]:
        """对同一股票的所有策略信号进行投票。"""
        if not symbol_signals:
            return {"symbol": "?", "final_signal": "WATCH", "confidence": 0.0, "vote_distribution": {}}

        symbol = symbol_signals[0].get("symbol", "?")
        votes: dict[str, int] = {"BUY": 0, "WATCH": 0, "AVOID": 0}
        confidences: list[float] = []

        for s in symbol_signals:
            sig = s.get("signal", "WATCH")
            if sig in votes:
                votes[sig] += 1
            conf = s.get("confidence", 0.5)
            confidences.append(conf)

        # 按优先级选择最终信号
        best_signal = "WATCH"
        best_priority = 0
        for sig, count in votes.items():
            if count > 0 and SIGNAL_PRIORITY.get(sig, 0) > best_priority:
                best_priority = SIGNAL_PRIORITY[sig]
                best_signal = sig

        avg_confidence = round(sum(confidences) / len(confidences), 2) if confidences else 0.5
        total_votes = sum(votes.values())
        distribution = {k: round(v / total_votes, 2) if total_votes > 0 else 0.0 for k, v in votes.items()}

        return {
            "symbol": symbol,
            "final_signal": best_signal,
            "confidence": avg_confidence,
            "vote_distribution": distribution,
        }

    def combine_signals(self) -> list[dict[str, Any]]:
        """对所有策略进行信号组合与投票。

        Returns:
            组合后的 EnsembleSignal 列表
        """
        if not self._strategies:
            return []

        # 按 symbol 分组所有信号
        symbol_groups: dict[str, list[dict]] = {}
        for name, signals in self._strategies.items():
            for s in signals:
                sym = s.get("symbol", "")
                if sym not in symbol_groups:
                    symbol_groups[sym] = []
                symbol_groups[sym].append(s)

        results = []
        for symbol, group in sorted(symbol_groups.items()):
            result = self._vote(group)
            results.append(result)

        return results

    def get_strategy_count(self) -> int:
        """获取策略数量。"""
        return len(self._strategies)

    def clear(self) -> None:
        """清空所有策略。"""
        self._strategies = {}