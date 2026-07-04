#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""建议复盘 v1 — 计算每条建议从记录时到现在的表现。

依赖方向：
    recommendation_review.py (此文件)
    ├── price_provider_v2.py (仅复用一个独立的价格获取函数，不改动核心逻辑)
    ├── 被 northstar/ui/dashboard.py 调用
    └── 不依赖任何其他北极星引擎模块

使用方式：
    from northstar.data.recommendation_review import review_recommendations
    results = review_recommendations(recommendations_list)

安全原则：
    1. 不修改 backend.py 核心循环
    2. 不修改系统状态
    3. 不自动交易
    4. 价格获取失败时不会崩溃 UI
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# ── 安全复用 price_provider_v2 ──────────────────────────────────────
# price_provider_v2.py 是一个独立的行情获取模块，不依赖北极星引擎，
# 可以安全导入，不会影响 backend 核心循环。
_PROVIDER: Any = None


def _get_provider():
    """延迟初始化 price_provider_v2，避免 import 时加载。"""
    global _PROVIDER
    if _PROVIDER is not None:
        return _PROVIDER
    # 确保项目根目录在 sys.path 中
    root = Path(__file__).parent.parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from price_provider_v2 import get_price_provider_v2
        _PROVIDER = get_price_provider_v2(use_cache=True, timeout=10, retries=1)
    except Exception:
        _PROVIDER = None
    return _PROVIDER


# ── 辅助函数 ─────────────────────────────────────────────────────────


def _is_english_symbol(symbol: str) -> bool:
    """判断是否是标准英文字母股票代码（如 NVDA, AAPL）。"""
    if not symbol:
        return False
    # 纯英文大写字母，可选数字后缀，长度 <= 10
    return bool(re.match(r'^[A-Z][A-Z0-9.]{0,9}$', symbol.strip().upper()))


def _parse_datetime(dt_str: str | None) -> datetime | None:
    """安全解析 ISO 格式时间字符串。"""
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str)
    except (TypeError, ValueError):
        return None


def _compute_days_since(created_at: str | None) -> int | None:
    """计算从创建时间到现在经过的天数。"""
    dt = _parse_datetime(created_at)
    if dt is None:
        return None
    now = datetime.now()
    delta = now - dt
    return max(0, delta.days)


# ── 核心复盘函数 ─────────────────────────────────────────────────────


def review_recommendations(recommendations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """对每条建议计算复盘数据。

    参数：
        recommendations: 建议记录列表（来自 recommendation_store.list_recommendations）

    返回：
        enriched list，每条记录增加以下字段：
            - current_price: float | None     当前价格
            - change: float | None            涨跌金额
            - change_pct: float | None        涨跌幅百分比
            - days_since: int | None          已过天数
            - due_for_review: bool            是否达到复盘时间
            - review_status: str              复盘状态文字
            - price_fetch_error: str | None   价格获取错误信息

    安全保证：
        - 任何异常不会抛到上层，不崩溃 UI
        - 价格获取失败时，current_price=None，change 和 change_pct 不计算
        - 中文股票名不尝试获取价格，直接提示
    """
    results: list[dict[str, Any]] = []
    provider = _get_provider()

    for rec in recommendations:
        result = dict(rec)  # 复制原始数据，不修改原记录
        symbol = rec.get("symbol", "").strip().upper()
        entry_price = rec.get("price")

        # 初始化复盘字段
        result["current_price"] = None
        result["change"] = None
        result["change_pct"] = None
        result["days_since"] = _compute_days_since(rec.get("created_at"))
        result["due_for_review"] = False
        result["review_status"] = "无法计算"
        result["price_fetch_error"] = None

        # 检查创建时间
        days_since = result["days_since"]
        review_after = rec.get("review_after_days", 7)
        if isinstance(review_after, (int, float)) and days_since is not None:
            result["due_for_review"] = days_since >= review_after

        # 检查建议价格
        if entry_price is None or entry_price == 0 or (isinstance(entry_price, float) and entry_price == 0.0):
            result["review_status"] = "缺少建议价格，无法计算收益率"
            results.append(result)
            continue

        # 检查是否是英文股票代码
        if not _is_english_symbol(symbol):
            result["review_status"] = "请使用英文股票代码，例如 NVDA"
            results.append(result)
            continue

        # 获取当前价格
        if provider is None:
            result["review_status"] = "暂无当前价格"
            result["price_fetch_error"] = "价格模块未加载"
            results.append(result)
            continue

        try:
            price_result = provider.get_price(symbol)
            if price_result is not None and price_result.is_ok and price_result.price is not None:
                current_price = float(price_result.price)
                result["current_price"] = round(current_price, 2)
                result["change"] = round(current_price - float(entry_price), 2)
                if float(entry_price) != 0:
                    result["change_pct"] = round(
                        (current_price - float(entry_price)) / float(entry_price) * 100, 2
                    )

                # 判断涨跌状态
                if result["change"] > 0:
                    result["review_status"] = "上涨"
                elif result["change"] < 0:
                    result["review_status"] = "下跌"
                else:
                    result["review_status"] = "持平"
            else:
                error_msg = price_result.error_message if price_result else "未知错误"
                result["review_status"] = "价格获取失败"
                result["price_fetch_error"] = error_msg
        except Exception as exc:
            result["review_status"] = "价格获取失败"
            result["price_fetch_error"] = str(exc)

        results.append(result)

    return results


def format_change_pct(value: float | None) -> str:
    """格式化涨跌幅显示。

    返回格式：
        - 正数: +x.xx%
        - 负数: -x.xx%
        - None: N/A
    """
    if value is None:
        return "N/A"
    if value > 0:
        return f"+{value:.2f}%"
    elif value < 0:
        return f"{value:.2f}%"
    else:
        return "0.00%"


def format_change(value: float | None) -> str:
    """格式化涨跌金额显示。"""
    if value is None:
        return "N/A"
    if value > 0:
        return f"+${value:.2f}"
    elif value < 0:
        return f"-${abs(value):.2f}"
    else:
        return "$0.00"


def get_recommendation_review_stats(recommendations: list[dict]) -> dict:
    """计算建议复盘统计指标（增强版）。

    参数：
        recommendations: 完整建议记录列表（来自 get_all_recommendations）

    返回：
        dict 包含以下字段：
            total_count: int             建议总数
            reviewed_count: int          已复盘数
            pending_count: int           未复盘数
            due_count: int               到期未复盘数
            win_count: int               上涨数
            loss_count: int              下跌数
            win_rate: float | None       胜率（上涨/已复盘）
            avg_change_pct: float | None 平均涨跌幅
            best_review: dict | None     涨幅最高的一条建议（含 symbol, created_at, change_pct, review_status）
            worst_review: dict | None    跌幅最低的一条建议

    安全保证：
        - 字段缺失、旧数据、review_result=None 不会崩溃
        - 没有任何写回操作
        - recommendations.json 为空时返回全 0 / None
    """
    total_count = len(recommendations)
    if total_count == 0:
        return {
            "total_count": 0,
            "reviewed_count": 0,
            "pending_count": 0,
            "due_count": 0,
            "win_count": 0,
            "loss_count": 0,
            "win_rate": None,
            "avg_change_pct": None,
            "best_review": None,
            "worst_review": None,
        }

    reviewed_count = 0
    pending_count = 0
    win_count = 0
    loss_count = 0
    change_pcts: list[float] = []
    reviewed_recs_with_pct: list[dict] = []
    open_recs_for_due: list[dict] = []

    for rec in recommendations:
        status = rec.get("status", "open")
        review_result = rec.get("review_result")

        if status == "reviewed":
            reviewed_count += 1

            if isinstance(review_result, dict):
                rv_status = review_result.get("review_status", "")
                change_pct = review_result.get("change_pct")

                if rv_status == "上涨":
                    win_count += 1
                elif rv_status == "下跌":
                    loss_count += 1

                if change_pct is not None:
                    try:
                        val = float(change_pct)
                        change_pcts.append(val)
                        reviewed_recs_with_pct.append({
                            "symbol": rec.get("symbol", "?"),
                            "created_at": rec.get("created_at", ""),
                            "change_pct": val,
                            "review_status": rv_status,
                        })
                    except (TypeError, ValueError):
                        pass
        else:
            pending_count += 1
            open_recs_for_due.append(rec)

    # Compute due_count: open records that have passed review_after_days
    due_count = 0
    for rec in open_recs_for_due:
        review_after = rec.get("review_after_days", 7)
        created_at = rec.get("created_at")
        if created_at and isinstance(review_after, (int, float)):
            dt = _parse_datetime(created_at)
            if dt:
                days = (datetime.now() - dt).days
                if days >= review_after:
                    due_count += 1

    # Compute avg_change_pct
    avg_change_pct: float | None = None
    if change_pcts:
        avg_change_pct = round(sum(change_pcts) / len(change_pcts), 2)

    # Compute win_rate (上涨 / 已复盘)
    win_rate: float | None = None
    if reviewed_count > 0:
        win_rate = round(win_count / reviewed_count * 100, 2)

    # Find best and worst review
    best_review: dict | None = None
    worst_review: dict | None = None
    if reviewed_recs_with_pct:
        best_review = max(reviewed_recs_with_pct, key=lambda x: x["change_pct"])
        worst_review = min(reviewed_recs_with_pct, key=lambda x: x["change_pct"])

    return {
        "total_count": total_count,
        "reviewed_count": reviewed_count,
        "pending_count": pending_count,
        "due_count": due_count,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": win_rate,
        "avg_change_pct": avg_change_pct,
        "best_review": best_review,
        "worst_review": worst_review,
    }


def get_recommendation_symbol_stats(recommendations: list[dict]) -> list[dict]:
    """按股票代码统计建议表现。

    参数：
        recommendations: 完整建议记录列表（来自 get_all_recommendations）

    返回：
        list[dict]，每个元素包含：
            symbol: str                   股票代码
            total_count: int              建议总数
            reviewed_count: int           已复盘数
            pending_count: int            未复盘数
            win_count: int                上涨数
            loss_count: int               下跌数
            win_rate: float | None        胜率（上涨/已复盘）
            avg_change_pct: float | None  平均涨跌幅
            best_change_pct: float | None 最佳单条涨跌幅
            worst_change_pct: float | None 最差单条涨跌幅
            latest_date: str | None       最近建议日期
            latest_status: str | None     最近复盘状态

    安全保证：
        - 字段缺失、旧数据、review_result=None 不会崩溃
        - 没有任何写回操作
        - 缺 symbol 的记录归类为 UNKNOWN
    """
    from collections import defaultdict

    groups: dict[str, dict] = defaultdict(lambda: {
        "total_count": 0,
        "reviewed_count": 0,
        "pending_count": 0,
        "win_count": 0,
        "loss_count": 0,
        "change_pcts": [],
        "dates": [],
        "latest_status_raw": None,
    })

    for rec in recommendations:
        symbol = rec.get("symbol", "").strip().upper()
        if not symbol:
            symbol = "UNKNOWN"
        status = rec.get("status", "open")
        review_result = rec.get("review_result")
        created_at = rec.get("created_at", "")
        g = groups[symbol]
        g["total_count"] += 1

        if created_at:
            g["dates"].append(created_at)

        if status == "reviewed":
            g["reviewed_count"] += 1

            if isinstance(review_result, dict):
                rv_status = review_result.get("review_status", "")
                change_pct = review_result.get("change_pct")

                if rv_status == "上涨":
                    g["win_count"] += 1
                elif rv_status == "下跌":
                    g["loss_count"] += 1

                if change_pct is not None:
                    try:
                        val = float(change_pct)
                        g["change_pcts"].append(val)
                    except (TypeError, ValueError):
                        pass

                g["latest_status_raw"] = rv_status
            elif isinstance(review_result, str):
                g["latest_status_raw"] = review_result
            else:
                g["latest_status_raw"] = "无法计算"
        else:
            g["pending_count"] += 1

    result_rows = []
    for symbol, g in sorted(groups.items()):
        reviewed = g["reviewed_count"]

        # Win rate
        win_rate: float | None = None
        if reviewed > 0:
            win_rate = round(g["win_count"] / reviewed * 100, 2)

        # Average change_pct
        avg_change_pct: float | None = None
        best_change_pct: float | None = None
        worst_change_pct: float | None = None
        if g["change_pcts"]:
            vals = g["change_pcts"]
            avg_change_pct = round(sum(vals) / len(vals), 2)
            best_change_pct = round(max(vals), 2)
            worst_change_pct = round(min(vals), 2)

        # Latest date
        latest_date: str | None = None
        if g["dates"]:
            latest_date = max(g["dates"])[:10]

        result_rows.append({
            "symbol": symbol,
            "total_count": g["total_count"],
            "reviewed_count": reviewed,
            "pending_count": g["pending_count"],
            "win_count": g["win_count"],
            "loss_count": g["loss_count"],
            "win_rate": win_rate,
            "avg_change_pct": avg_change_pct,
            "best_change_pct": best_change_pct,
            "worst_change_pct": worst_change_pct,
            "latest_date": latest_date,
            "latest_status": g["latest_status_raw"],
        })

    result_rows.sort(key=lambda x: (-x["total_count"], x["symbol"]))
    return result_rows


# ── 按建议动作判断胜负 ───────────────────────────────────────────────


def infer_recommendation_action(record: dict) -> str:
    """从建议记录中识别建议动作，归一化为标准分类。

    返回：
        BUY / SELL / HOLD / WATCH / UNKNOWN
    """
    # 兼容多种字段名
    raw_action = None
    for key in ("action", "recommendation", "recommendation_type", "suggestion", "decision", "signal", "advice", "type"):
        val = record.get(key)
        if val is not None and isinstance(val, str) and val.strip():
            raw_action = val.strip()
            break

    if raw_action is None:
        return "UNKNOWN"

    raw_lower = raw_action.lower()

    # BUY
    buy_keywords = {"买入", "加仓", "补仓", "看多", "buy", "add", "accumulate", "bullish", "做多"}
    if raw_lower in buy_keywords or raw_action in ("买入", "加仓", "补仓", "看多", "做多"):
        return "BUY"

    # SELL
    sell_keywords = {"卖出", "减仓", "清仓", "止盈", "止损", "看空", "sell", "reduce", "exit", "bearish", "做空"}
    if raw_lower in sell_keywords or raw_action in ("卖出", "减仓", "清仓", "止盈", "止损", "看空", "做空"):
        return "SELL"

    # HOLD
    hold_keywords = {"持有", "继续持有", "hold", "holding", "hold"}
    if raw_lower in hold_keywords or raw_action in ("持有", "继续持有"):
        return "HOLD"

    # WATCH
    watch_keywords = {"观察", "观望", "等待", "watch", "wait", "observe"}
    if raw_lower in watch_keywords or raw_action in ("观察", "观望", "等待"):
        return "WATCH"

    return "UNKNOWN"


def evaluate_recommendation_outcome(record: dict) -> dict:
    """根据建议动作和涨跌幅判断复盘结果。

    返回：
        {
            "action_group": str,        BUY / SELL / HOLD / WATCH / UNKNOWN
            "raw_change_pct": float|None,
            "normalized_change_pct": float|None,
            "outcome": str              win / loss / flat / neutral / unknown
        }
    """
    action_group = infer_recommendation_action(record)

    # 从 review_result 中获取 change_pct
    review_result = record.get("review_result")
    raw_change_pct: float | None = None

    if isinstance(review_result, dict):
        cp = review_result.get("change_pct")
        if cp is not None:
            try:
                raw_change_pct = float(cp)
            except (TypeError, ValueError):
                pass

    if raw_change_pct is None:
        return {
            "action_group": action_group,
            "raw_change_pct": None,
            "normalized_change_pct": None,
            "outcome": "unknown",
        }

    if action_group == "BUY":
        if raw_change_pct > 0:
            return {"action_group": "BUY", "raw_change_pct": raw_change_pct, "normalized_change_pct": raw_change_pct, "outcome": "win"}
        elif raw_change_pct < 0:
            return {"action_group": "BUY", "raw_change_pct": raw_change_pct, "normalized_change_pct": raw_change_pct, "outcome": "loss"}
        else:
            return {"action_group": "BUY", "raw_change_pct": raw_change_pct, "normalized_change_pct": raw_change_pct, "outcome": "flat"}

    elif action_group == "SELL":
        if raw_change_pct < 0:
            return {"action_group": "SELL", "raw_change_pct": raw_change_pct, "normalized_change_pct": -raw_change_pct, "outcome": "win"}
        elif raw_change_pct > 0:
            return {"action_group": "SELL", "raw_change_pct": raw_change_pct, "normalized_change_pct": -raw_change_pct, "outcome": "loss"}
        else:
            return {"action_group": "SELL", "raw_change_pct": raw_change_pct, "normalized_change_pct": -raw_change_pct, "outcome": "flat"}

    elif action_group in ("HOLD", "WATCH"):
        return {"action_group": action_group, "raw_change_pct": raw_change_pct, "normalized_change_pct": None, "outcome": "neutral"}

    else:  # UNKNOWN
        return {"action_group": "UNKNOWN", "raw_change_pct": raw_change_pct, "normalized_change_pct": None, "outcome": "unknown"}


def get_recommendation_action_stats(recommendations: list[dict]) -> list[dict]:
    """按建议动作分组统计。

    参数：
        recommendations: 完整建议记录列表

    返回：
        list[dict]，每个元素：
            action_group: str           BUY / SELL / HOLD / WATCH / UNKNOWN
            action_display: str         展示用名称
            total_count: int
            reviewed_count: int
            pending_count: int
            win_count: int
            loss_count: int
            flat_count: int
            neutral_count: int
            unknown_count: int
            win_rate: float|None
            avg_raw_change_pct: float|None
            avg_normalized_change_pct: float|None
            best_normalized_change_pct: float|None
            worst_normalized_change_pct: float|None
    """
    from collections import defaultdict

    groups: dict[str, dict] = defaultdict(lambda: {
        "total_count": 0,
        "reviewed_count": 0,
        "pending_count": 0,
        "win_count": 0,
        "loss_count": 0,
        "flat_count": 0,
        "neutral_count": 0,
        "unknown_count": 0,
        "raw_change_pcts": [],
        "normalized_change_pcts": [],
    })

    for rec in recommendations:
        status = rec.get("status", "open")
        action_group = infer_recommendation_action(rec)
        g = groups[action_group]
        g["total_count"] += 1

        if status != "reviewed":
            g["pending_count"] += 1
            continue

        g["reviewed_count"] += 1
        outcome = evaluate_recommendation_outcome(rec)
        o = outcome["outcome"]

        if o == "win":
            g["win_count"] += 1
        elif o == "loss":
            g["loss_count"] += 1
        elif o == "flat":
            g["flat_count"] += 1
        elif o == "neutral":
            g["neutral_count"] += 1
        else:
            g["unknown_count"] += 1

        if outcome["raw_change_pct"] is not None:
            g["raw_change_pcts"].append(outcome["raw_change_pct"])
        if outcome["normalized_change_pct"] is not None:
            g["normalized_change_pcts"].append(outcome["normalized_change_pct"])

    ACTION_DISPLAY = {
        "BUY": "买入/看多",
        "SELL": "卖出/看空",
        "HOLD": "持有",
        "WATCH": "观望",
        "UNKNOWN": "未知",
    }

    result_rows = []
    order = ["BUY", "SELL", "HOLD", "WATCH", "UNKNOWN"]
    for ag in order:
        g = groups.get(ag)
        if g is None:
            continue

        # Win rate denominator: win_count + loss_count + flat_count
        denom = g["win_count"] + g["loss_count"] + g["flat_count"]
        win_rate: float | None = None
        if denom > 0:
            win_rate = round(g["win_count"] / denom * 100, 2)

        # Average raw change_pct
        avg_raw: float | None = None
        if g["raw_change_pcts"]:
            avg_raw = round(sum(g["raw_change_pcts"]) / len(g["raw_change_pcts"]), 2)

        # Average normalized change_pct
        avg_norm: float | None = None
        best_norm: float | None = None
        worst_norm: float | None = None
        if g["normalized_change_pcts"]:
            vals = g["normalized_change_pcts"]
            avg_norm = round(sum(vals) / len(vals), 2)
            best_norm = round(max(vals), 2)
            worst_norm = round(min(vals), 2)

        result_rows.append({
            "action_group": ag,
            "action_display": ACTION_DISPLAY.get(ag, ag),
            "total_count": g["total_count"],
            "reviewed_count": g["reviewed_count"],
            "pending_count": g["pending_count"],
            "win_count": g["win_count"],
            "loss_count": g["loss_count"],
            "flat_count": g["flat_count"],
            "neutral_count": g["neutral_count"],
            "unknown_count": g["unknown_count"],
            "win_rate": win_rate,
            "avg_raw_change_pct": avg_raw,
            "avg_normalized_change_pct": avg_norm,
            "best_normalized_change_pct": best_norm,
            "worst_normalized_change_pct": worst_norm,
        })

    # Sort: total_count desc
    result_rows.sort(key=lambda x: -x["total_count"])
    return result_rows


def calculate_review_stats(recommendations: list[dict]) -> dict:
    """计算建议复盘统计指标。

    参数：
        recommendations: 完整建议记录列表（来自 get_all_recommendations）

    返回：
        dict 包含以下字段：
            total: int          总建议数
            reviewed: int       已复盘数
            open: int           未复盘数
            up: int             上涨数
            down: int           下跌数
            flat: int           持平数
            unknown: int        无法计算数
            avg_change_pct: float | None  平均涨跌幅
            win_rates: dict     各动作胜率 {"买入": float|None, "持有": float|None, "卖出": float|None}

    安全保证：
        - 字段缺失、旧数据、review_result=None 不会崩溃
        - 没有任何写回操作
    """
    total = len(recommendations)
    reviewed_count = 0
    open_count = 0
    up = 0
    down = 0
    flat = 0
    unknown = 0
    change_pcts: list[float] = []
    win_groups: dict[str, dict] = {}  # action -> {"total": int, "up": int}

    for rec in recommendations:
        status = rec.get("status", "open")
        action = rec.get("action", "")
        review_result = rec.get("review_result")

        if status == "reviewed":
            reviewed_count += 1

            if isinstance(review_result, dict):
                rv_status = review_result.get("review_status", "")
                change_pct = review_result.get("change_pct")

                # Count up/down/flat/unknown
                if rv_status == "上涨":
                    up += 1
                elif rv_status == "下跌":
                    down += 1
                elif rv_status == "持平":
                    flat += 1
                elif rv_status in ("无法计算", "价格获取失败", "缺少建议价格，无法计算收益率", "请使用英文股票代码，例如 NVDA"):
                    unknown += 1
                elif rv_status:
                    unknown += 1
                else:
                    unknown += 1

                # Accumulate change_pct for average
                if change_pct is not None:
                    try:
                        val = float(change_pct)
                        change_pcts.append(val)
                    except (TypeError, ValueError):
                        pass

                # Track win rates by action
                if action:
                    if action not in win_groups:
                        win_groups[action] = {"total": 0, "up": 0}
                    win_groups[action]["total"] += 1
                    if rv_status == "上涨":
                        win_groups[action]["up"] += 1
            else:
                # review_result is not a dict (e.g., old data or string)
                unknown += 1
                if action:
                    if action not in win_groups:
                        win_groups[action] = {"total": 0, "up": 0}
                    win_groups[action]["total"] += 1
        else:
            open_count += 1

    # Compute average change_pct
    avg_change_pct: float | None = None
    if change_pcts:
        avg_change_pct = round(sum(change_pcts) / len(change_pcts), 2)

    # Compute win rates
    win_rates: dict[str, float | None] = {}
    for action_name in ("买入", "持有", "卖出"):
        group = win_groups.get(action_name)
        if group and group["total"] > 0:
            win_rates[action_name] = round(group["up"] / group["total"] * 100, 2)
        else:
            win_rates[action_name] = None

    # Remaining actions (观察, 风险提示, others)
    for action_name, group in win_groups.items():
        if action_name not in win_rates:
            if group["total"] > 0:
                win_rates[action_name] = round(group["up"] / group["total"] * 100, 2)
            else:
                win_rates[action_name] = None

    return {
        "total": total,
        "reviewed": reviewed_count,
        "open": open_count,
        "up": up,
        "down": down,
        "flat": flat,
        "unknown": unknown,
        "avg_change_pct": avg_change_pct,
        "win_rates": win_rates,
    }
