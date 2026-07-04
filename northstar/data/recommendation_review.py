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