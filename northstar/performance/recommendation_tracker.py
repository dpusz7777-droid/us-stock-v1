#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""策略验证闭环 — 计算每条推荐的真实表现。

功能：
    - 读取 recommendations.json 或现有推荐数据
    - 自动拉取当前价格（复用现有 northstar.data.yahoo_quote_provider.fetch_quotes）
    - 计算每条推荐的 pnl_percent, pnl_absolute, max_drawdown, holding_days
    - 输出结构化列表 recommendation_performance_report
    - 统计函数 get_strategy_stats() 返回整体表现

依赖方向：
    recommendation_tracker.py (此文件)
    ├── northstar/data/recommendation_store.py (读取推荐数据)
    ├── northstar.data.yahoo_quote_provider (获取当前价格)
    └── 不修改券商数据 / 不生成交易指令 / 只读模式

文件位置：
    northstar/performance/recommendation_tracker.py
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# ── 内存价格缓存（批量预取优化） ──
_price_cache: dict[str, tuple[float | None, str | None]] = {}


def _clear_price_cache() -> None:
    """清空价格缓存，主要用于测试。"""
    _price_cache.clear()


def _is_valid_symbol(symbol: str) -> bool:
    """验证股票代码格式（英文字母 + 数字 + 点号，最长 10 位）。"""
    if not symbol:
        return False
    return bool(re.match(r'^[A-Z][A-Z0-9.]{0,9}$', symbol.strip().upper()))


def _parse_datetime(dt_str: str | None) -> datetime | None:
    """安全解析 ISO 格式时间字符串。"""
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _compute_holding_days(created_at: str | None) -> int | None:
    """计算从创建到现在的持有天数。"""
    dt = _parse_datetime(created_at)
    if dt is None:
        return None
    return max(0, (datetime.now() - dt).days)


def _resolve_direction(action: str) -> str:
    """根据 action 字段解析交易方向。

    返回 "LONG" / "SHORT" / "HOLD"（含未知/不可计算动作）。
    """
    if not action:
        return "LONG"  # 无动作字段默认做多
    a = action.strip()
    # 做多
    if a in ("买入", "BUY", "LONG", "bought", "加仓"):
        return "LONG"
    # 做空
    if a in ("卖出", "SELL", "SHORT", "sold", "减仓"):
        return "SHORT"
    # HOLD / 观察 / 不可计算
    if a in ("持有", "HOLD", "观察", "风险提示", "观望"):
        return "HOLD"
    # 未知动作 → 安全起见按 HOLD 处理（不计算收益）
    return "HOLD"


def _fetch_current_price(symbol: str) -> tuple[float | None, str | None]:
    """获取单只股票当前价格，返回 (价格, 错误信息)。

    通过 northstar.data.yahoo_quote_provider.fetch_quotes 获取行情。
    价格失败时返回 (None, 错误信息)，不抛异常，不下单。
    """
    from northstar.data.yahoo_quote_provider import fetch_quotes

    normalized = symbol.strip().upper()
    if not normalized:
        return None, "空股票代码"

    try:
        quotes = fetch_quotes([normalized])
        quote = quotes.get(normalized, {})
        if not isinstance(quote, dict):
            return None, "价格数据格式异常"
        error = quote.get("error")
        if error is not None:
            return None, str(error)
        price = quote.get("price")
        if price is None:
            return None, "价格为空"
        return float(price), None
    except Exception as exc:
        return None, str(exc)



def compute_recommendation_performance(
    recommendations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """计算每条推荐的表现指标。

    参数：
        recommendations: 推荐数据列表，每条应包含：
            - symbol (str): 股票代码（必需）
            - entry_price (float): 入场价格（必需）
            - timestamp (str): ISO 格式时间戳（可选，用于计算 holding_days）
            - action (str): 建议动作（买入/持有/卖出/观察/风险提示）
            - status (str): 状态（可选，如 open / closed）

    返回：
        list[dict]，每条包含：
            - symbol / entry_price / current_price / status / action
            - pnl_percent / pnl_absolute
            - max_drawdown（简化：当前回撤 = (current - entry) / entry）
            - holding_days / price_fetch_error / direction
        做多建议：当前价上涨为正收益。
        做空建议：当前价下跌为正收益。
        HOLD / 观察 / 风险提示：不计算收益，标记为"不可计算"。
    """
    results: list[dict[str, Any]] = []

    for rec in recommendations:
        # 标准化字段名称：兼容 recommendation_store schema
        symbol = (rec.get("symbol") or "").strip().upper()
        # 尝试多个可能的入场价格字段名
        entry_price = (
            rec.get("entry_price")
            or rec.get("price")
            or rec.get("recommendation_price")
            or rec.get("target_entry_price")
        )
        timestamp = (
            rec.get("timestamp")
            or rec.get("created_at")
            or rec.get("date")
        )
        status = rec.get("status", "open")
        action = rec.get("action", "")
        direction = _resolve_direction(action)

        # 构建结果行
        result: dict[str, Any] = {
            "symbol": symbol,
            "entry_price": entry_price,
            "current_price": None,
            "status": status,
            "action": action,
            "direction": direction,
            "pnl_percent": None,
            "pnl_absolute": None,
            "max_drawdown": None,
            "holding_days": _compute_holding_days(timestamp),
            "price_fetch_error": None,
        }

        # 检查必要字段
        if not symbol:
            result["price_fetch_error"] = "缺少股票代码"
            results.append(result)
            continue

        if not _is_valid_symbol(symbol):
            result["price_fetch_error"] = "请使用英文股票代码，例如 NVDA"
            results.append(result)
            continue

        # HOLD / 观察 / 风险提示：不计算收益
        if direction == "HOLD":
            result["price_fetch_error"] = "持有/观察状态不计算收益"
            results.append(result)
            continue

        if entry_price is None or entry_price == 0:
            result["price_fetch_error"] = "缺少入场价格，无法计算收益"
            results.append(result)
            continue

        # 确保 entry_price 是 float
        try:
            entry_price = float(entry_price)
        except (TypeError, ValueError):
            result["price_fetch_error"] = "入场价格格式异常"
            results.append(result)
            continue

        result["entry_price"] = round(entry_price, 2)

        # 拉取当前价格
        current_price, error = _fetch_current_price(symbol)
        if current_price is None:
            result["price_fetch_error"] = error or "价格获取失败"
            results.append(result)
            continue

        result["current_price"] = round(current_price, 2)

        # 计算 pnl（方向感知）
        if direction == "SHORT":
            pnl_absolute = entry_price - current_price
        else:
            # 做多 / 未知方向统一按做多处理
            pnl_absolute = current_price - entry_price

        pnl_percent = (pnl_absolute / entry_price) * 100

        result["pnl_absolute"] = round(pnl_absolute, 2)
        result["pnl_percent"] = round(pnl_percent, 2)

        # 简化 max_drawdown：当前回撤（负收益时等于 pnl_percent，正收益则为 0）
        if pnl_percent < 0:
            result["max_drawdown"] = round(pnl_percent, 2)
        else:
            result["max_drawdown"] = 0.0

        results.append(result)

    return results


def get_recommendation_performance_report(
    recommendations: list[dict[str, Any]] | None = None, limit: int = 10
) -> list[dict[str, Any]]:
    """获取最近 N 条推荐的真实表现报告。

    参数：
        recommendations: 推荐数据列表。如果为 None，自动从 recommendations.json 读取。
        limit: 返回前 N 条（按时间倒序），默认 10。

    返回：
        list[dict]，按创建时间倒序排列，每条包含完整表现数据。
    """
    if recommendations is None:
        # 自动从 recommendation_store 加载
        try:
            from northstar.data.recommendation_store import get_all_recommendations
            recommendations = get_all_recommendations()
        except ImportError:
            # 兜底：直接读 JSON
            data_dir = Path(__file__).resolve().parent.parent / "data"
            rec_file = data_dir / "recommendations.json"
            if rec_file.exists():
                import json
                try:
                    with open(rec_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    recommendations = data if isinstance(data, list) else []
                except (json.JSONDecodeError, OSError):
                    recommendations = []
            else:
                recommendations = []

    if not recommendations:
        return []

    # 按时间倒序排列
    def _sort_key(r):
        ts = r.get("timestamp") or r.get("created_at") or ""
        return ts

    sorted_recs = sorted(recommendations, key=_sort_key, reverse=True)
    recent = sorted_recs[:limit]

    # 计算表现
    return compute_recommendation_performance(recent)


def get_strategy_stats(
    recommendations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """计算整体策略验证统计。

    参数：
        recommendations: 推荐数据列表。如果为 None，自动从 recommendations.json 读取。

    返回：
        dict:
            - total_recommendations (int): 总推荐数
            - active_recommendations (int): 进行中推荐数
            - win_rate (float | None): 盈利建议比例（有当前价格的建议中）
            - avg_return (float | None): 平均收益率
            - avg_holding_days (float | None): 平均持有天数
            - total_pnl_absolute (float | None): 总绝对收益
            - best_performer (dict | None): 最佳表现
            - worst_performer (dict | None): 最差表现
    """
    if recommendations is None:
        try:
            from northstar.data.recommendation_store import get_all_recommendations
            recommendations = get_all_recommendations()
        except ImportError:
            data_dir = Path(__file__).resolve().parent.parent / "data"
            rec_file = data_dir / "recommendations.json"
            if rec_file.exists():
                import json
                try:
                    with open(rec_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    recommendations = data if isinstance(data, list) else []
                except (json.JSONDecodeError, OSError):
                    recommendations = []
            else:
                recommendations = []

    total = len(recommendations)
    active = sum(1 for r in recommendations if r.get("status") in ("open", "active"))

    if total == 0:
        return {
            "total_recommendations": 0,
            "active_recommendations": 0,
            "win_rate": None,
            "avg_return": None,
            "avg_holding_days": None,
            "total_pnl_absolute": None,
            "best_performer": None,
            "worst_performer": None,
        }

    # 计算每条的表现
    performance = compute_recommendation_performance(recommendations)

    # 过滤出有 pnl 数据的
    valid_pnl = [p for p in performance if p["pnl_percent"] is not None]
    win_count = sum(1 for p in valid_pnl if p["pnl_percent"] > 0)

    win_rate = round(win_count / len(valid_pnl) * 100, 2) if valid_pnl else None

    avg_return = (
        round(sum(p["pnl_percent"] for p in valid_pnl) / len(valid_pnl), 2)
        if valid_pnl
        else None
    )

    avg_days = (
        round(
            sum(p["holding_days"] for p in performance if p["holding_days"] is not None)
            / max(sum(1 for p in performance if p["holding_days"] is not None), 1),
            1,
        )
    )

    total_pnl = (
        round(sum(p["pnl_absolute"] for p in valid_pnl), 2) if valid_pnl else None
    )

    best = max(valid_pnl, key=lambda x: x["pnl_percent"]) if valid_pnl else None
    worst = min(valid_pnl, key=lambda x: x["pnl_percent"]) if valid_pnl else None

    return {
        "total_recommendations": total,
        "active_recommendations": active,
        "win_rate": win_rate,
        "avg_return": avg_return,
        "avg_holding_days": avg_days,
        "total_pnl_absolute": total_pnl,
        "best_performer": {
            "symbol": best["symbol"],
            "pnl_percent": best["pnl_percent"],
            "pnl_absolute": best["pnl_absolute"],
        }
        if best
        else None,
        "worst_performer": {
            "symbol": worst["symbol"],
            "pnl_percent": worst["pnl_percent"],
            "pnl_absolute": worst["pnl_absolute"],
        }
        if worst
        else None,
    }


def format_pnl(pnl: float | None) -> str:
    """格式化收益率显示。"""
    if pnl is None:
        return "N/A"
    if pnl > 0:
        return f"+{pnl:.2f}%"
    elif pnl < 0:
        return f"{pnl:.2f}%"
    return "0.00%"


def format_absolute(value: float | None) -> str:
    """格式化绝对收益显示。"""
    if value is None:
        return "N/A"
    if value > 0:
        return f"+${value:.2f}"
    elif value < 0:
        return f"-${abs(value):.2f}"
    return "$0.00"