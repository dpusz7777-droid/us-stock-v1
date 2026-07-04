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


def classify_recommendation_review_result(row: dict) -> dict:
    """对一条建议复盘结果进行只读分级。

    参数：
        row: review_recommendations 返回的单条记录

    返回：
        {
            "review_grade": str,        有效 / 待观察 / 失效 / 数据不足
            "review_grade_reason": str,  一句话原因
            "review_grade_score": int,   100 / 60 / 20 / 0
        }

    分级规则（简单、透明、可解释）：
        - 数据不足：缺少 action / symbol / recommendation_price / current_price / change_pct
        - 有效：
            - 买入类建议 (BUY) 且 change_pct >= +3%
            - 卖出/回避类建议 (SELL) 且 change_pct <= -3%
            - 注意：SELL 建议下跌是正确判断，所以 change_pct <= -3% 时判为有效
        - 失效：
            - 买入类建议 (BUY) 且 change_pct <= -3%
            - 卖出/回避类建议 (SELL) 且 change_pct >= +3%
        - 待观察：
            - 数据完整但涨跌幅在 -3% < x < +3%
            - 或动作类型无法明确归类但数据完整

    安全原则：
        - 只读，不写回原始建议文件
        - 任何异常不会抛到上层
    """
    try:
        # ── 检查必要字段 ──
        action = row.get("action", "").strip() if row.get("action") else ""
        symbol = row.get("symbol", "").strip() if row.get("symbol") else ""
        entry_price = row.get("price")
        current_price = row.get("current_price")
        change_pct = row.get("change_pct")

        # 数据不足检查
        missing = []
        if not action:
            missing.append("缺少建议动作")
        if not symbol:
            missing.append("缺少股票代码")
        if entry_price is None or entry_price == 0:
            missing.append("缺少建议价格")
        if current_price is None:
            missing.append("缺少当前价格(价格获取失败)")
        if change_pct is None:
            missing.append("缺少涨跌幅(无法计算收益率)")

        if missing:
            return {
                "review_grade": "数据不足",
                "review_grade_reason": "；".join(missing),
                "review_grade_score": 0,
            }

        # ── 识别动作类型 ──
        action_lower = action.lower()
        action_display = action  # 保留原始中文/英文

        # 买入类（预期上涨才正确）
        is_buy = action_lower in ("买入", "加仓", "补仓", "看多", "做多", "buy", "add", "accumulate", "bullish", "watch_buy", "strong_buy") or action in ("买入", "加仓", "补仓", "看多", "做多")

        # 卖出类（预期下跌才正确）
        is_sell = action_lower in ("卖出", "减仓", "清仓", "止盈", "止损", "看空", "做空", "sell", "reduce", "exit", "bearish", "avoid") or action in ("卖出", "减仓", "清仓", "止盈", "止损", "看空", "做空")

        # 持有/观察类（中性，不判断有效/失效）
        is_neutral = (not is_buy and not is_sell)

        # ── 判断涨跌幅阈值 ──
        try:
            cp = float(change_pct)
        except (TypeError, ValueError):
            return {
                "review_grade": "数据不足",
                "review_grade_reason": "涨跌幅格式异常，无法计算",
                "review_grade_score": 0,
            }

        THRESHOLD = 3.0  # ±3% 阈值

        # ── 中性动作 → 待观察 ──
        if is_neutral:
            return {
                "review_grade": "待观察",
                "review_grade_reason": f"建议动作为「{action_display}」，属于中性/观察类，不做有效/失效判断",
                "review_grade_score": 60,
            }

        # ── 买入类建议 ──
        if is_buy:
            if cp >= THRESHOLD:
                return {
                    "review_grade": "有效",
                    "review_grade_reason": f"买入建议后上涨 {cp:+.2f}%，超过 +3% 阈值",
                    "review_grade_score": 100,
                }
            elif cp <= -THRESHOLD:
                return {
                    "review_grade": "失效",
                    "review_grade_reason": f"买入建议后下跌 {cp:.2f}%，超过 -3% 阈值",
                    "review_grade_score": 20,
                }
            else:
                return {
                    "review_grade": "待观察",
                    "review_grade_reason": f"买入建议后涨跌幅 {cp:+.2f}%，在 ±3% 范围内，暂不判断",
                    "review_grade_score": 60,
                }

        # ── 卖出类建议 ──
        if is_sell:
            if cp <= -THRESHOLD:
                return {
                    "review_grade": "有效",
                    "review_grade_reason": f"卖出建议后下跌 {cp:.2f}%，超过 -3% 阈值（下跌=正确判断）",
                    "review_grade_score": 100,
                }
            elif cp >= THRESHOLD:
                return {
                    "review_grade": "失效",
                    "review_grade_reason": f"卖出建议后上涨 {cp:+.2f}%，超过 +3% 阈值（上涨=错误判断）",
                    "review_grade_score": 20,
                }
            else:
                return {
                    "review_grade": "待观察",
                    "review_grade_reason": f"卖出建议后涨跌幅 {cp:+.2f}%，在 ±3% 范围内，暂不判断",
                    "review_grade_score": 60,
                }

        # ── 兜底 ──
        return {
            "review_grade": "待观察",
            "review_grade_reason": "无法确定动作类型，暂不判断",
            "review_grade_score": 60,
        }

    except Exception:
        return {
            "review_grade": "数据不足",
            "review_grade_reason": "分级计算异常",
            "review_grade_score": 0,
        }


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


def get_sample_confidence_label(evaluable_count: int) -> dict:
    """根据可判断样本数返回样本量可信度标签。

    参数：
        evaluable_count: 可判断胜负的样本数量（win_count + loss_count + flat_count）

    返回：
        {
            "confidence_level": str,   NO_DATA / VERY_LOW / LOW / MEDIUM / HIGH
            "confidence_label": str,   中文展示文案
            "evaluable_count": int
        }
    """
    if evaluable_count <= 0:
        return {"confidence_level": "NO_DATA", "confidence_label": "暂无可判断样本", "evaluable_count": 0}
    elif evaluable_count <= 2:
        return {"confidence_level": "VERY_LOW", "confidence_label": "样本很少", "evaluable_count": evaluable_count}
    elif evaluable_count <= 5:
        return {"confidence_level": "LOW", "confidence_label": "样本偏少", "evaluable_count": evaluable_count}
    elif evaluable_count <= 10:
        return {"confidence_level": "MEDIUM", "confidence_label": "样本一般", "evaluable_count": evaluable_count}
    else:
        return {"confidence_level": "HIGH", "confidence_label": "样本较充分", "evaluable_count": evaluable_count}


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
    flat_count = 0
    neutral_count = 0
    unknown_count = 0
    change_pcts: list[float] = []
    normalized_change_pcts: list[float] = []
    reviewed_recs_with_norm: list[dict] = []
    open_recs_for_due: list[dict] = []

    for rec in recommendations:
        status = rec.get("status", "open")
        review_result = rec.get("review_result")

        if status == "reviewed":
            reviewed_count += 1

            # 使用 evaluate_recommendation_outcome 统一判断
            outcome = evaluate_recommendation_outcome(rec)
            o = outcome["outcome"]

            if o == "win":
                win_count += 1
            elif o == "loss":
                loss_count += 1
            elif o == "flat":
                flat_count += 1
            elif o == "neutral":
                neutral_count += 1
            else:
                unknown_count += 1

            if outcome["raw_change_pct"] is not None:
                change_pcts.append(outcome["raw_change_pct"])
            if outcome["normalized_change_pct"] is not None:
                norm_val = outcome["normalized_change_pct"]
                normalized_change_pcts.append(norm_val)
                reviewed_recs_with_norm.append({
                    "symbol": rec.get("symbol", "?"),
                    "created_at": rec.get("created_at", ""),
                    "normalized_change_pct": norm_val,
                    "outcome": o,
                })
        else:
            pending_count += 1
            open_recs_for_due.append(rec)

    # Compute due_count
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

    # Compute avg_change_pct (raw)
    avg_change_pct: float | None = None
    if change_pcts:
        avg_change_pct = round(sum(change_pcts) / len(change_pcts), 2)

    # Compute avg_normalized_change_pct
    avg_normalized_change_pct: float | None = None
    if normalized_change_pcts:
        avg_normalized_change_pct = round(sum(normalized_change_pcts) / len(normalized_change_pcts), 2)

    # Compute win_rate = win / (win + loss + flat)
    win_denom = win_count + loss_count + flat_count
    win_rate: float | None = None
    if win_denom > 0:
        win_rate = round(win_count / win_denom * 100, 2)

    # Find best and worst review based on normalized_change_pct
    best_review: dict | None = None
    worst_review: dict | None = None
    if reviewed_recs_with_norm:
        best_review = max(reviewed_recs_with_norm, key=lambda x: x["normalized_change_pct"])
        worst_review = min(reviewed_recs_with_norm, key=lambda x: x["normalized_change_pct"])

    # Sample confidence
    evaluable_count = win_count + loss_count + flat_count
    confidence = get_sample_confidence_label(evaluable_count)

    return {
        "total_count": total_count,
        "reviewed_count": reviewed_count,
        "pending_count": pending_count,
        "due_count": due_count,
        "win_count": win_count,
        "loss_count": loss_count,
        "flat_count": flat_count,
        "neutral_count": neutral_count,
        "unknown_count": unknown_count,
        "win_rate": win_rate,
        "avg_change_pct": avg_change_pct,
        "avg_normalized_change_pct": avg_normalized_change_pct,
        "best_review": best_review,
        "worst_review": worst_review,
        "evaluable_count": evaluable_count,
        "confidence_level": confidence["confidence_level"],
        "confidence_label": confidence["confidence_label"],
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
        "flat_count": 0,
        "neutral_count": 0,
        "unknown_count": 0,
        "raw_change_pcts": [],
        "normalized_change_pcts": [],
        "dates": [],
        "latest_status_raw": None,
    })

    for rec in recommendations:
        symbol = rec.get("symbol", "").strip().upper()
        if not symbol:
            symbol = "UNKNOWN"
        status = rec.get("status", "open")
        created_at = rec.get("created_at", "")
        g = groups[symbol]
        g["total_count"] += 1

        if created_at:
            g["dates"].append(created_at)

        if status == "reviewed":
            g["reviewed_count"] += 1

            # 使用 evaluate_recommendation_outcome 统一判断
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

            # latest_status from review_result
            review_result = rec.get("review_result")
            if isinstance(review_result, dict):
                g["latest_status_raw"] = review_result.get("review_status", "")
            elif isinstance(review_result, str):
                g["latest_status_raw"] = review_result
            else:
                g["latest_status_raw"] = "无法计算"
        else:
            g["pending_count"] += 1

    result_rows = []
    for symbol, g in sorted(groups.items()):

        # Win rate = win / (win + loss + flat)
        denom = g["win_count"] + g["loss_count"] + g["flat_count"]
        win_rate: float | None = None
        if denom > 0:
            win_rate = round(g["win_count"] / denom * 100, 2)

        # Average raw change_pct
        avg_change_pct: float | None = None
        best_change_pct: float | None = None
        worst_change_pct: float | None = None
        if g["raw_change_pcts"]:
            vals = g["raw_change_pcts"]
            avg_change_pct = round(sum(vals) / len(vals), 2)
            best_change_pct = round(max(vals), 2)
            worst_change_pct = round(min(vals), 2)

        # Average normalized change_pct
        avg_normalized_change_pct: float | None = None
        best_normalized_change_pct: float | None = None
        worst_normalized_change_pct: float | None = None
        if g["normalized_change_pcts"]:
            vals = g["normalized_change_pcts"]
            avg_normalized_change_pct = round(sum(vals) / len(vals), 2)
            best_normalized_change_pct = round(max(vals), 2)
            worst_normalized_change_pct = round(min(vals), 2)

        # Latest date
        latest_date: str | None = None
        if g["dates"]:
            latest_date = max(g["dates"])[:10]

        # Sample confidence
        confidence = get_sample_confidence_label(denom)

        result_rows.append({
            "symbol": symbol,
            "total_count": g["total_count"],
            "reviewed_count": g["reviewed_count"],
            "pending_count": g["pending_count"],
            "win_count": g["win_count"],
            "loss_count": g["loss_count"],
            "flat_count": g["flat_count"],
            "neutral_count": g["neutral_count"],
            "unknown_count": g["unknown_count"],
            "win_rate": win_rate,
            "avg_change_pct": avg_change_pct,
            "best_change_pct": best_change_pct,
            "worst_change_pct": worst_change_pct,
            "avg_normalized_change_pct": avg_normalized_change_pct,
            "best_normalized_change_pct": best_normalized_change_pct,
            "worst_normalized_change_pct": worst_normalized_change_pct,
            "latest_date": latest_date,
            "latest_status": g["latest_status_raw"],
            "evaluable_count": denom,
            "confidence_level": confidence["confidence_level"],
            "confidence_label": confidence["confidence_label"],
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

        confidence = get_sample_confidence_label(denom)
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
            "evaluable_count": denom,
            "confidence_level": confidence["confidence_level"],
            "confidence_label": confidence["confidence_label"],
        })

    # Sort: total_count desc
    result_rows.sort(key=lambda x: -x["total_count"])
    return result_rows


def _infer_days_elapsed(rec: dict) -> int | None:
    """从建议记录中推断已过天数。

    优先使用天数字段，否则尝试根据日期计算。
    返回 int 天数，无法推断时返回 None。
    """
    # 尝试天数字段
    days_field_keys = ("days_elapsed", "review_days", "holding_days", "days_since_recommendation", "review_after_days")
    for key in days_field_keys:
        val = rec.get(key)
        if val is not None:
            try:
                return int(float(str(val).replace(" days", "").replace(" day", "").strip()))
            except (TypeError, ValueError):
                pass

    # 尝试从日期计算
    date_field_keys_rec = ("recommendation_date", "created_at", "date")
    date_field_keys_rev = ("review_date", "reviewed_at", "current_date", "updated_at")
    rec_date = None
    rev_date = None
    for key in date_field_keys_rec:
        val = rec.get(key)
        if val:
            try:
                rec_date = datetime.fromisoformat(val.replace("Z", "+00:00"))
                break
            except (TypeError, ValueError):
                pass
    for key in date_field_keys_rev:
        val = rec.get(key)
        if val:
            try:
                rev_date = datetime.fromisoformat(val.replace("Z", "+00:00"))
                break
            except (TypeError, ValueError):
                pass
    if rec_date and rev_date:
        delta = (rev_date - rec_date).days
        return max(0, delta)

    # 尝试 last_run_time / 当前时间
    if rec_date:
        delta = (datetime.now() - rec_date).days
        return max(0, delta)

    return None


def _classify_horizon(days: int | None) -> tuple[str, str]:
    """根据天数返回 (horizon_group, label)。"""
    if days is None:
        return ("UNKNOWN", "未知")
    if days <= 1:
        return ("0-1D", "0-1天")
    elif days <= 3:
        return ("2-3D", "2-3天")
    elif days <= 7:
        return ("4-7D", "4-7天")
    elif days <= 14:
        return ("8-14D", "8-14天")
    elif days <= 30:
        return ("15-30D", "15-30天")
    else:
        return ("30D+", "30天以上")


def get_recommendation_horizon_stats(recommendations: list[dict]) -> list[dict]:
    """按复盘周期统计建议质量。

    参数：
        recommendations: 完整建议记录列表

    返回：
        list[dict]，每个元素：
            horizon_group: str       周期分组代码
            label: str               中文展示名
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

    安全保证：
        - 字段缺失、日期格式错误不会崩溃
        - 没有任何写回操作
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

    # 收集所有分组
    for rec in recommendations:
        days = _infer_days_elapsed(rec)
        group_key, _ = _classify_horizon(days)
        g = groups[group_key]
        g["total_count"] += 1

        status = rec.get("status", "open")
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

    HORIZON_ORDER = ["0-1D", "2-3D", "4-7D", "8-14D", "15-30D", "30D+", "UNKNOWN"]
    HORIZON_LABEL = {
        "0-1D": "0-1天",
        "2-3D": "2-3天",
        "4-7D": "4-7天",
        "8-14D": "8-14天",
        "15-30D": "15-30天",
        "30D+": "30天以上",
        "UNKNOWN": "未知",
    }

    result_rows = []
    for hg in HORIZON_ORDER:
        g = groups.get(hg)
        if g is None:
            continue

        denom = g["win_count"] + g["loss_count"] + g["flat_count"]
        win_rate: float | None = None
        if denom > 0:
            win_rate = round(g["win_count"] / denom * 100, 2)

        avg_raw: float | None = None
        if g["raw_change_pcts"]:
            avg_raw = round(sum(g["raw_change_pcts"]) / len(g["raw_change_pcts"]), 2)

        avg_norm: float | None = None
        best_norm: float | None = None
        worst_norm: float | None = None
        if g["normalized_change_pcts"]:
            vals = g["normalized_change_pcts"]
            avg_norm = round(sum(vals) / len(vals), 2)
            best_norm = round(max(vals), 2)
            worst_norm = round(min(vals), 2)

        confidence = get_sample_confidence_label(denom)
        result_rows.append({
            "horizon_group": hg,
            "label": HORIZON_LABEL.get(hg, hg),
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
            "evaluable_count": denom,
            "confidence_level": confidence["confidence_level"],
            "confidence_label": confidence["confidence_label"],
        })

    return result_rows


def generate_recommendation_review_summary(
    overall_stats: dict,
    symbol_stats: list[dict],
    action_stats: list[dict],
    horizon_stats: list[dict],
) -> dict:
    """生成复盘摘要结论。

    参数：
        overall_stats: get_recommendation_review_stats 返回的 dict
        symbol_stats: get_recommendation_symbol_stats 返回的 list
        action_stats: get_recommendation_action_stats 返回的 list
        horizon_stats: get_recommendation_horizon_stats 返回的 list

    返回：
        dict:
            status: str               no_data / low_confidence / ok
            headline: str             一句话headline
            bullets: list[str]       结构化bullet列表
            warnings: list[str]      警告列表
            best_symbol: dict|None   最佳股票
            best_action: dict|None   最佳建议动作
            best_horizon: dict|None  最佳复盘周期
    """
    bullets: list[str] = []
    warnings: list[str] = []

    # ── 无数据判断 ──
    total = overall_stats.get("total_count", 0)
    if total == 0:
        return {
            "status": "no_data",
            "headline": "暂无足够建议复盘数据",
            "bullets": ["当前还没有可用于复盘统计的建议记录。"],
            "warnings": [],
            "best_symbol": None,
            "best_action": None,
            "best_horizon": None,
        }

    evaluable = overall_stats.get("evaluable_count", 0)
    if evaluable == 0:
        return {
            "status": "no_data",
            "headline": "暂无可判断样本",
            "bullets": ["当前建议记录尚未形成可判断胜负的复盘样本。"],
            "warnings": ["建议先积累更多已复盘记录，再判断北极星的建议质量。"],
            "best_symbol": None,
            "best_action": None,
            "best_horizon": None,
        }

    # ── 样本量判断 ──
    conf_level = overall_stats.get("confidence_level", "NO_DATA")
    if conf_level in ("NO_DATA", "VERY_LOW", "LOW"):
        status = "low_confidence"
        warnings.append("当前可判断样本偏少，复盘结论仅供参考。")
    else:
        status = "ok"

    # ── headline ──
    win_rate = overall_stats.get("win_rate")
    if win_rate is not None:
        if win_rate >= 65.0:
            perf = "整体表现较好"
        elif win_rate >= 45.0:
            perf = "整体表现中性"
        else:
            perf = "整体表现偏弱"
        confidence_label = overall_stats.get("confidence_label", "")
        headline = (
            f"当前北极星建议方向胜率为 {win_rate:.2f}%，"
            f"{confidence_label}，{perf}。"
        )
    else:
        headline = "当前北极星建议暂无足够复盘数据判断方向胜率。"
        if status != "low_confidence" and conf_level in ("MEDIUM", "HIGH"):
            warnings.append("有已复盘记录但无法判断方向胜率，请检查建议动作字段是否完整。")

    # ── 整体 bullet ──
    if win_rate is not None:
        bullets.append(
            f"整体方向胜率 {win_rate:.2f}%，{overall_stats.get('confidence_label', '暂无数据')}（{evaluable} 条可判断样本）。"
        )
    else:
        bullets.append(f"整体暂无方向胜率数据，{overall_stats.get('confidence_label', '暂无数据')}（{evaluable} 条可判断样本）。")

    # ── best_symbol ──
    best_symbol = None
    if symbol_stats:
        eligible = [s for s in symbol_stats if s.get("evaluable_count", 0) >= 3 and s.get("win_rate") is not None]
        if eligible:
            best_symbol = max(eligible, key=lambda x: (x["win_rate"], x.get("avg_normalized_change_pct") or 0, x.get("evaluable_count", 0)))
            bullets.append(
                f"按股票看，{best_symbol['symbol']} 当前方向胜率较高，为 {best_symbol['win_rate']:.2f}%，"
                f"可判断样本 {best_symbol['evaluable_count']} 条。"
            )
        else:
            warnings.append("按股票维度暂无足够样本形成可靠结论。")
    else:
        warnings.append("按股票维度暂无足够样本形成可靠结论。")

    # ── best_action ──
    ACTION_DISPLAY_MAP = {
        "BUY": "买入/看多",
        "SELL": "卖出/看空",
        "HOLD": "持有",
        "WATCH": "观望",
        "UNKNOWN": "未知",
    }
    best_action = None
    if action_stats:
        eligible_act = [
            a for a in action_stats
            if a.get("evaluable_count", 0) >= 3
            and a.get("win_rate") is not None
            and a.get("action_group") != "UNKNOWN"
        ]
        if eligible_act:
            best_action = max(eligible_act, key=lambda x: (x["win_rate"], x.get("avg_normalized_change_pct") or 0, x.get("evaluable_count", 0)))
            act_display = ACTION_DISPLAY_MAP.get(best_action["action_group"], best_action["action_group"])
            bullets.append(
                f"按建议动作看，{act_display}类建议当前表现最好，方向胜率 {best_action['win_rate']:.2f}%。"
            )
        else:
            warnings.append("按建议动作维度暂无足够样本形成可靠结论。")
    else:
        warnings.append("按建议动作维度暂无足够样本形成可靠结论。")

    # ── best_horizon ──
    best_horizon = None
    if horizon_stats:
        eligible_hor = [
            h for h in horizon_stats
            if h.get("evaluable_count", 0) >= 3
            and h.get("win_rate") is not None
            and h.get("horizon_group") != "UNKNOWN"
        ]
        if eligible_hor:
            best_horizon = max(eligible_hor, key=lambda x: (x["win_rate"], x.get("avg_normalized_change_pct") or 0, x.get("evaluable_count", 0)))
            bullets.append(
                f"按复盘周期看，{best_horizon['label']}周期当前表现最好，方向胜率 {best_horizon['win_rate']:.2f}%。"
            )
        else:
            warnings.append("按复盘周期维度暂无足够样本形成可靠结论。")
    else:
        warnings.append("按复盘周期维度暂无足够样本形成可靠结论。")

    return {
        "status": status,
        "headline": headline,
        "bullets": bullets,
        "warnings": warnings,
        "best_symbol": best_symbol,
        "best_action": best_action,
        "best_horizon": best_horizon,
    }


def get_recommendation_review_data_health(recommendations: list[dict]) -> dict:
    """检查建议复盘数据质量，只读诊断。

    参数：
        recommendations: 完整建议记录列表

    返回：
        dict:
            status: str                  ok / warning / error
            total_count: int             总建议数
            issue_count: int             问题总数
            affected_count: int          受影响记录数
            health_score: float          数据健康分
            summary: str                 诊断摘要
            issues_by_type: dict         各类型问题计数
            issue_rows: list[dict]       问题明细

    不修改任何记录，不写回文件。
    """
    issues_by_type: dict[str, int] = {
        "missing_symbol": 0,
        "missing_action": 0,
        "unknown_action": 0,
        "missing_recommendation_price": 0,
        "missing_current_price": 0,
        "missing_change_pct": 0,
        "invalid_date": 0,
        "review_status_inconsistent": 0,
        "outcome_unknown": 0,
    }
    issue_rows: list[dict] = []
    affected_indices: set[int] = set()
    total = len(recommendations)

    if total == 0:
        return {
            "status": "ok",
            "total_count": 0,
            "issue_count": 0,
            "affected_count": 0,
            "health_score": 100.0,
            "summary": "暂无建议记录，无需体检。",
            "issues_by_type": issues_by_type,
            "issue_rows": [],
        }

    for idx, rec in enumerate(recommendations):
        issues: list[str] = []
        symbol = rec.get("symbol", "") or rec.get("ticker", "") or ""
        action_raw = None
        for key in ("action", "recommendation", "recommendation_type", "suggestion", "decision", "signal", "advice", "type"):
            val = rec.get(key)
            if val is not None and isinstance(val, str) and val.strip():
                action_raw = val.strip()
                break
        status_field = rec.get("status", "open") or rec.get("review_status", "open") or "open"
        price = rec.get("recommendation_price") or rec.get("suggested_price") or rec.get("entry_price") or rec.get("price") or rec.get("target_entry_price")
        has_price = price is not None and price != 0 and (not isinstance(price, float) or price != 0.0)
        reviewed = (status_field == "reviewed")
        review_result = rec.get("review_result")

        # 1. missing_symbol
        if not symbol:
            issues.append("missing_symbol")
            issues_by_type["missing_symbol"] += 1

        # 2. missing_action
        if not action_raw:
            issues.append("missing_action")
            issues_by_type["missing_action"] += 1

        # 3. unknown_action (only if action is present)
        if action_raw:
            action_group = infer_recommendation_action(rec)
            if action_group == "UNKNOWN":
                issues.append("unknown_action")
                issues_by_type["unknown_action"] += 1

        # 4. missing_recommendation_price
        if not has_price:
            issues.append("missing_recommendation_price")
            issues_by_type["missing_recommendation_price"] += 1

        # 5. missing_current_price (reviewed records)
        if reviewed:
            curr_price = rec.get("current_price") or (review_result.get("review_price") if isinstance(review_result, dict) else None)
            if curr_price is None:
                issues.append("missing_current_price")
                issues_by_type["missing_current_price"] += 1

        # 6. missing_change_pct (reviewed records)
        if reviewed:
            cp = rec.get("change_pct") or rec.get("pct_change") or rec.get("change_percent") or rec.get("return_pct")
            if isinstance(review_result, dict) and not cp:
                cp = review_result.get("change_pct") or review_result.get("pct_change") or review_result.get("change_percent")
            if cp is None:
                issues.append("missing_change_pct")
                issues_by_type["missing_change_pct"] += 1

        # 7. invalid_date
        date_str = rec.get("recommendation_date") or rec.get("created_at") or rec.get("date")
        if date_str:
            try:
                datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                issues.append("invalid_date")
                issues_by_type["invalid_date"] += 1

        # 8. review_status_inconsistent
        if reviewed:
            curr_price_check = rec.get("current_price") or (review_result.get("review_price") if isinstance(review_result, dict) else None)
            cp_check = rec.get("change_pct") or rec.get("pct_change") or rec.get("change_percent") or rec.get("return_pct")
            if isinstance(review_result, dict) and not cp_check:
                cp_check = review_result.get("change_pct") or review_result.get("pct_change") or review_result.get("change_percent")
            if not curr_price_check and not cp_check:
                issues.append("review_status_inconsistent")
                issues_by_type["review_status_inconsistent"] += 1
        else:
            # Not reviewed but has review_result or reviewed_at
            if rec.get("review_result") or rec.get("reviewed_at"):
                issues.append("review_status_inconsistent")
                issues_by_type["review_status_inconsistent"] += 1

        # 9. outcome_unknown (reviewed, not HOLD/WATCH neutral)
        if reviewed:
            outcome = evaluate_recommendation_outcome(rec)
            if outcome["outcome"] == "unknown" and outcome["action_group"] not in ("HOLD", "WATCH"):
                issues.append("outcome_unknown")
                issues_by_type["outcome_unknown"] += 1

        if issues:
            affected_indices.add(idx)
            issue_rows.append({
                "index": idx,
                "symbol": symbol or "—",
                "date": (date_str or "")[:10] if date_str else "—",
                "review_status": reviewed and "已复盘" or "待复盘",
                "issues": issues,
                "message": _build_issue_message(issues),
            })

    total_issues = sum(issues_by_type.values())
    affected_count = len(affected_indices)
    health_score = max(0, 100 - total_issues * 3)

    if health_score >= 90:
        status = "ok"
        summary = "建议复盘数据质量良好，当前未发现明显问题。" if total_issues == 0 else "建议复盘数据基本良好，存在少量可优化项。"
    elif health_score >= 70:
        status = "warning"
        summary = "建议复盘数据存在少量问题，可能影响部分统计结果。"
    else:
        status = "error"
        summary = "建议复盘数据存在较多问题，建议优先清理后再参考统计结论。"

    return {
        "status": status,
        "total_count": total,
        "issue_count": total_issues,
        "affected_count": affected_count,
        "health_score": health_score,
        "summary": summary,
        "issues_by_type": issues_by_type,
        "issue_rows": issue_rows[:20],
    }


def _build_issue_message(issues: list[str]) -> str:
    """根据问题列表生成中文说明。"""
    msg_map = {
        "missing_symbol": "缺少股票代码",
        "missing_action": "缺少建议动作，无法判断建议方向",
        "unknown_action": "无法识别建议动作",
        "missing_recommendation_price": "缺少建议价格，无法计算涨跌幅",
        "missing_current_price": "已复盘但缺少当前价格",
        "missing_change_pct": "已复盘但缺少涨跌幅数据",
        "invalid_date": "日期格式异常",
        "review_status_inconsistent": "复盘状态不一致",
        "outcome_unknown": "已复盘但无法判断胜负",
    }
    parts = [msg_map.get(issue, issue) for issue in issues if issue in msg_map]
    return "；".join(parts)


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


def classify_recommendation_failure_reason(row: dict) -> dict:
    """对一条建议复盘结果进行只读失效原因归类。

    参数：
        row: review_recommendations 返回的单条复盘记录

    返回：
        {
            "failure_reason": str,       失效原因分类
            "failure_reason_detail": str, 一句话解释
            "failure_severity": str,      高 / 中 / 低 / 无
            "failure_flags": list[str],   标签列表
        }

    规则（简单透明，不依赖 AI 模型）：
        - 非失效建议：failure_reason=非失效建议, severity=无
        - 缺失关键字段：数据不足导致无法判断, severity=低
        - 买入类建议后下跌：买入后下跌, severity 按跌幅分级
        - 卖出类建议后上涨：卖出后上涨, severity 按涨幅分级
        - 无法识别动作类型：动作类型无法识别, severity=低

    安全原则：
        - 只读计算，不写回任何文件
        - 字段缺失时不会崩溃
        - 不构成投资建议
    """
    try:
        # 检查是否是失效建议
        grade = row.get("review_grade", "")
        if grade and grade != "失效":
            return {
                "failure_reason": "非失效建议",
                "failure_reason_detail": "该建议不属于失效分级，无需分析失效原因。",
                "failure_severity": "无",
                "failure_flags": [],
            }

        # 检查必要字段
        action = row.get("action", "").strip() if row.get("action") else ""
        symbol = row.get("symbol", "").strip() if row.get("symbol") else ""
        entry_price = row.get("price")
        current_price = row.get("current_price")
        raw_change_pct = row.get("change_pct")

        if not action or not symbol:
            return {
                "failure_reason": "数据不足导致无法判断",
                "failure_reason_detail": "缺少建议动作或股票代码，无法归类失效原因。",
                "failure_severity": "低",
                "failure_flags": ["缺少建议动作", "缺少股票代码"],
            }

        if entry_price is None or entry_price == 0:
            return {
                "failure_reason": "数据不足导致无法判断",
                "failure_reason_detail": "缺少建议价格，无法判断失效原因。",
                "failure_severity": "低",
                "failure_flags": ["缺少建议价格"],
            }

        if current_price is None:
            return {
                "failure_reason": "数据不足导致无法判断",
                "failure_reason_detail": "缺少当前价格，无法判断失效原因。",
                "failure_severity": "低",
                "failure_flags": ["缺少当前价格"],
            }

        if raw_change_pct is None:
            return {
                "failure_reason": "数据不足导致无法判断",
                "failure_reason_detail": "缺少涨跌幅，无法判断失效原因。",
                "failure_severity": "低",
                "failure_flags": ["缺少涨跌幅"],
            }

        try:
            cp = float(raw_change_pct)
        except (TypeError, ValueError):
            return {
                "failure_reason": "数据不足导致无法判断",
                "failure_reason_detail": "涨跌幅格式异常，无法判断失效原因。",
                "failure_severity": "低",
                "failure_flags": ["涨跌幅格式异常"],
            }

        # 识别动作类型
        action_lower = action.lower()
        is_buy = action_lower in ("买入", "加仓", "补仓", "看多", "做多", "buy", "add", "accumulate", "bullish", "watch_buy", "strong_buy") or action in ("买入", "加仓", "补仓", "看多", "做多")
        is_sell = action_lower in ("卖出", "减仓", "清仓", "止盈", "止损", "看空", "做空", "sell", "reduce", "exit", "bearish", "avoid") or action in ("卖出", "减仓", "清仓", "止盈", "止损", "看空", "做空")

        # 买入类建议失效：上涨没赚到是因为没买，但这里只关心"买入后下跌"
        if is_buy:
            # 失效：买入后下跌
            if cp <= -3:
                if cp <= -10:
                    severity = "高"
                    detail = f"买入类建议后价格下跌 {cp:.1f}%，跌幅较大，需重点复盘买入时机和方向判断。"
                elif cp <= -5:
                    severity = "中"
                    detail = f"买入类建议后价格下跌 {cp:.1f}%，说明买入时机或方向需要复盘。"
                else:
                    severity = "低"
                    detail = f"买入类建议后价格小幅下跌 {cp:.1f}%，可继续观察或复盘买入逻辑。"
                return {
                    "failure_reason": "买入后下跌",
                    "failure_reason_detail": detail,
                    "failure_severity": severity,
                    "failure_flags": [f"跌幅{abs(cp):.0f}%", f"严重程度{severity}"],
                }

        if is_sell:
            # 失效：卖出后上涨
            if cp >= 3:
                if cp >= 10:
                    severity = "高"
                    detail = f"卖出/回避类建议后价格上涨 {cp:.1f}%，涨幅较大，可能错过重要上涨行情。"
                elif cp >= 5:
                    severity = "中"
                    detail = f"卖出/回避类建议后价格上涨 {cp:.1f}%，说明卖出判断偏保守。"
                else:
                    severity = "低"
                    detail = f"卖出/回避类建议后价格小幅上涨 {cp:.1f}%，可继续观察或复盘卖出逻辑。"
                return {
                    "failure_reason": "卖出后上涨",
                    "failure_reason_detail": detail,
                    "failure_severity": severity,
                    "failure_flags": [f"涨幅{cp:.0f}%", f"严重程度{severity}"],
                }

        # 动作类型无法识别
        return {
            "failure_reason": "动作类型无法识别",
            "failure_reason_detail": f"建议动作为「{action}」，无法归类到买入或卖出类，无法判断失效原因。",
            "failure_severity": "低",
            "failure_flags": ["动作类型无法识别"],
        }

    except Exception:
        return {
            "failure_reason": "其他失效原因",
            "failure_reason_detail": "分析失效原因时出现异常，请确认数据格式。",
            "failure_severity": "中",
            "failure_flags": ["分析异常"],
        }


def build_recommendation_review_quality_explanation(review_rows: list[dict]) -> dict:
    """对当前建议复盘结果进行只读质量解释。

    参数：
        review_rows: review_recommendations 返回的复盘结果列表，
                     或者包含 classify_recommendation_review_result 分级标签的记录列表

    返回：
        {
            "quality_level": str,        良好 / 一般 / 较差 / 暂无足够样本
            "main_issue": str,            当前最主要问题
            "explanation": str,           一句人话解释
            "next_action": str,           下一步建议
            "warning_flags": list[str],   问题标签列表
        }

    规则（简单透明，不依赖 AI 模型）：
        1. 总建议数 = 0 → 暂无足够样本
        2. 数据不足数量 / 总建议数 >= 50% → 较差 / 数据不足过多
        3. 有效+失效 样本数 < 3 → 一般 / 可判断样本太少
        4. 失效数量 > 有效数量 → 一般 / 失效建议多于有效建议
        5. 有效率 >= 60% 且 样本数 >= 3 → 良好
        6. 其他 → 一般 / 样本仍需积累

    安全原则：
        - 只读计算，不写回任何文件
        - 字段缺失时不会崩溃
        - 不构成投资建议
    """
    try:
        if not review_rows:
            return {
                "quality_level": "暂无足够样本",
                "main_issue": "暂无建议记录",
                "explanation": "还没有足够建议可供复盘，请先运行系统生成建议或手动新增建议。",
                "next_action": "先运行系统生成建议，再观察一段时间后查看复盘质量分析。",
                "warning_flags": ["暂无建议记录"],
            }

        total = len(review_rows)
        insufficient = 0
        valid = 0
        watch = 0
        invalid = 0

        for row in review_rows:
            # 优先使用已有分级标签，如果没有则尝试调用分级函数
            grade = row.get("review_grade")
            if grade is None:
                try:
                    from northstar.data.recommendation_review import classify_recommendation_review_result
                    grade_result = classify_recommendation_review_result(row)
                    grade = grade_result.get("review_grade", "数据不足")
                except Exception:
                    grade = "数据不足"

            if grade == "有效":
                valid += 1
            elif grade == "失效":
                invalid += 1
            elif grade == "待观察":
                watch += 1
            else:
                insufficient += 1

        effective_sample = valid + invalid

        # 规则 2：数据不足占比 >= 50%
        if total > 0 and insufficient / total >= 0.5:
            return {
                "quality_level": "较差",
                "main_issue": "数据不足过多",
                "explanation": (
                    f"当前 {total} 条建议中，{insufficient} 条存在数据不足问题"
                    f"（占比 {insufficient / total * 100:.0f}%），"
                    f"很多建议缺少价格、动作或日期，当前有效率参考价值有限。"
                ),
                "next_action": "优先补齐建议价格、当前价格、动作和日期字段，减少数据不足占比。",
                "warning_flags": ["数据不足占比过高", "建议补充建议价格和动作"],
            }

        # 规则 3：有效+失效 样本数 < 3
        if effective_sample < 3:
            return {
                "quality_level": "一般",
                "main_issue": "可判断样本太少",
                "explanation": (
                    f"当前 {total} 条建议中，可判断对错的建议仅有 {effective_sample} 条，"
                    f"有效率和复盘结论还不够稳定。"
                ),
                "next_action": "继续积累建议样本，至少达到 3 条可判断样本后再看有效率。",
                "warning_flags": ["可判断样本不足"],
            }

        # 规则 4：失效数量 > 有效数量
        if invalid > valid:
            return {
                "quality_level": "一般",
                "main_issue": "失效建议多于有效建议",
                "explanation": (
                    f"当前 {effective_sample} 条可判断样本中，"
                    f"有效 {valid} 条、失效 {invalid} 条，"
                    f"错误方向多于正确方向，需要谨慎参考。"
                ),
                "next_action": "复查失效建议集中在哪些动作、标的或市场环境，分析失效原因。",
                "warning_flags": ["失效建议多于有效建议", "建议复查失效原因"],
            }

        # 规则 5：有效率 >= 60% 且 样本数 >= 3
        rate = valid / effective_sample * 100
        if rate >= 60.0 and effective_sample >= 3:
            return {
                "quality_level": "良好",
                "main_issue": "暂无明显问题",
                "explanation": (
                    f"当前 {effective_sample} 条可判断样本中，"
                    f"有效建议占比 {rate:.1f}%，整体历史表现较好，但仍需继续观察。"
                ),
                "next_action": "继续保存复盘快照，观察有效率是否稳定，确保有足够样本支持结论。",
                "warning_flags": [],
            }

        # 规则 6：其他
        return {
            "quality_level": "一般",
            "main_issue": "样本仍需积累",
            "explanation": (
                f"当前 {effective_sample} 条可判断样本，有效率 {rate:.1f}%，"
                f"可以参考但结论还不够稳定。"
            ),
            "next_action": "继续积累建议和复盘快照，等样本增多后再做判断。",
            "warning_flags": ["样本仍需积累"],
        }

    except Exception:
        return {
            "quality_level": "暂无足够样本",
            "main_issue": "质量分析异常",
            "explanation": "分析复盘质量时出现异常，请确认建议数据格式正确。",
            "next_action": "检查建议数据格式，确保字段完整。",
            "warning_flags": ["质量分析异常"],
        }
