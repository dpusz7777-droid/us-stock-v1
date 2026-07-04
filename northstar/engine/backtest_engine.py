#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""北极星回测引擎 — 验证 BUY/SELL/HOLD 决策在历史上的真实表现。

用法：
    from northstar.engine.backtest_engine import run_backtest
    result = run_backtest(positions_history, decision_history, price_data)
"""

from __future__ import annotations

from typing import Any


def _compute_trade_outcome(
    decision: dict,
    price_data: dict[str, list[dict]],
) -> dict:
    """计算单笔交易的结果。"""
    symbol = decision.get("symbol", "")
    action = decision.get("action", "HOLD")
    entry_price = decision.get("price", 0.0)
    entry_date = decision.get("date", "")

    result = {
        "symbol": symbol,
        "action": action,
        "entry_price": entry_price,
        "exit_price": entry_price,
        "return_pct": 0.0,
        "is_win": None,
    }

    if action == "HOLD" or not symbol or not price_data.get(symbol):
        return result

    prices = price_data.get(symbol, [])
    if not prices:
        return result

    # 找到 entry_date 后的第一个价格作为 exit
    exit_price = entry_price
    for p in prices:
        if p.get("date", "") > entry_date:
            exit_price = p.get("close", entry_price)
            break
    if exit_price == entry_price and len(prices) > 0:
        exit_price = prices[-1].get("close", entry_price)

    if entry_price > 0:
        if action == "BUY":
            ret = (exit_price - entry_price) / entry_price * 100
        elif action == "SELL":
            ret = (entry_price - exit_price) / entry_price * 100
        else:
            ret = 0.0
    else:
        ret = 0.0

    result["exit_price"] = round(exit_price, 2)
    result["return_pct"] = round(ret, 2)
    result["is_win"] = ret > 0 if ret != 0 else None
    return result


def _classify_strategy(action: str) -> str:
    """将 action 映射为策略类型。"""
    if action in ("BUY", "STRONG_BUY"):
        return "momentum"
    if action in ("SELL", "STRONG_SELL"):
        return "defensive"
    return "unknown"


def run_backtest(
    positions_history: list[dict] | None = None,
    decision_history: list[dict] | None = None,
    price_data: dict[str, list[dict]] | None = None,
) -> dict[str, Any]:
    """回测验证北极星决策的历史表现。

    Args:
        positions_history: 历史持仓列表 [{"symbol": str, "qty": float, "avg_price": float, ...}]
        decision_history: 历史决策列表 [{"symbol": str, "action": str, "price": float, "date": str, ...}]
        price_data: 历史价格数据 {"AAPL": [{"date": "2024-01-01", "close": 150.0}, ...]}

    Returns:
        {
            "total_return": float,
            "win_rate": float,
            "avg_return_per_trade": float,
            "strategy_performance": dict,
            "regime_performance": dict,
            "decision_accuracy": dict,
        }
    """
    # 默认空结果
    empty_result: dict[str, Any] = {
        "total_return": 0.0,
        "win_rate": 0.0,
        "avg_return_per_trade": 0.0,
        "strategy_performance": {},
        "regime_performance": {},
        "decision_accuracy": {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0},
    }

    if not decision_history:
        return empty_result

    # 计算每笔交易的结果
    trade_results = []
    for d in decision_history:
        outcome = _compute_trade_outcome(d, price_data or {})
        if outcome["return_pct"] != 0 or outcome["action"] != "HOLD":
            trade_results.append(outcome)

    if not trade_results:
        return empty_result

    # 总收益
    total_return = sum(t["return_pct"] for t in trade_results)
    avg_return = total_return / len(trade_results) if trade_results else 0.0

    # 胜率
    wins = sum(1 for t in trade_results if t["is_win"] is True)
    losses = sum(1 for t in trade_results if t["is_win"] is False)
    win_rate = wins / (wins + losses) if (wins + losses) > 0 else 0.0

    # 按策略统计
    strategy_perf: dict[str, dict] = {}
    for t in trade_results:
        st = _classify_strategy(t["action"])
        if st not in strategy_perf:
            strategy_perf[st] = {"win_rate": 0.0, "avg_return": 0.0, "trades": 0, "wins": 0}
        s = strategy_perf[st]
        s["trades"] += 1
        s["avg_return"] += t["return_pct"]
        if t["is_win"] is True:
            s["wins"] += 1

    for st, data in strategy_perf.items():
        data["avg_return"] = round(data["avg_return"] / data["trades"], 2) if data["trades"] > 0 else 0.0
        data["win_rate"] = round(data["wins"] / data["trades"], 2) if data["trades"] > 0 else 0.0
        del data["trades"]
        del data["wins"]

    # 按决策动作统计准确率
    decision_acc: dict[str, dict] = {"BUY": {"total": 0, "wins": 0, "accuracy": 0.0},
                                      "SELL": {"total": 0, "wins": 0, "accuracy": 0.0},
                                      "HOLD": {"total": 0, "wins": 0, "accuracy": 0.0}}
    for t in trade_results:
        a = t["action"]
        if a in decision_acc:
            decision_acc[a]["total"] += 1
            if t["is_win"] is True:
                decision_acc[a]["wins"] += 1

    decision_accuracy = {}
    for a, data in decision_acc.items():
        decision_accuracy[a] = round(data["wins"] / data["total"], 2) if data["total"] > 0 else 0.0

    # regime_performance 需要 regime 数据才能填充
    regime_perf: dict[str, dict] = {}

    return {
        "total_return": round(total_return, 2),
        "win_rate": round(win_rate, 2),
        "avg_return_per_trade": round(avg_return, 2),
        "strategy_performance": strategy_perf,
        "regime_performance": regime_perf,
        "decision_accuracy": decision_accuracy,
    }


def run_backtest_with_regime(
    positions_history: list[dict] | None = None,
    decision_history: list[dict] | None = None,
    price_data: dict[str, list[dict]] | None = None,
    regime_history: list[dict] | None = None,
) -> dict[str, Any]:
    """带市场状态的回测（扩展版）。"""
    result = run_backtest(positions_history, decision_history, price_data)

    # 如果提供了 regime 数据，按 regime 分组计算
    if regime_history and decision_history:
        regime_map: dict[str, list[dict]] = {}
        # 简单的映射：把每个日期映射到 regime
        date_to_regime = {}
        for r_entry in regime_history:
            dt = r_entry.get("date", "")
            rg = r_entry.get("regime", "unknown")
            date_to_regime[dt] = rg

        for d in decision_history:
            dt = d.get("date", "")
            rg = date_to_regime.get(dt, "unknown")
            if rg not in regime_map:
                regime_map[rg] = []
            outcome = _compute_trade_outcome(d, price_data or {})
            if outcome["return_pct"] != 0 or outcome["action"] != "HOLD":
                regime_map[rg].append(outcome)

        regime_perf: dict[str, dict] = {}
        for rg, trades in regime_map.items():
            if not trades:
                continue
            total_ret = sum(t["return_pct"] for t in trades)
            avg_ret = total_ret / len(trades)
            wins = sum(1 for t in trades if t["is_win"] is True)
            wr = wins / len(trades) if trades else 0.0
            regime_perf[rg] = {
                "win_rate": round(wr, 2),
                "avg_return": round(avg_ret, 2),
                "trade_count": len(trades),
            }
        result["regime_performance"] = regime_perf

    return result