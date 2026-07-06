#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试每日决策报告模块。

测试点
------
1. watchlist 能读取 25 支股票
2. 报告生成函数能返回 dict
3. markdown 和 json 文件能被创建
4. 缺少部分价格数据时不会崩溃
5. 输出中包含 Top 5 机会、Top 5 风险、今日一句话结论
"""

from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ── 项目根目录 ────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from northstar.reports.daily_decision_report import (
    StockPriceInfo,
    load_watchlist,
    load_portfolio,
    fetch_prices,
    build_report_data,
    save_report,
    _judge_trend,
    _judge_risk,
    _judge_suggestion,
    _make_overall_conclusion,
    generate_daily_decision_report,
    WATCHLIST_PATH,
    PORTFOLIO_PATH,
    REPORT_DIR,
)


# ═══════════════════════════════════════════════════════════════
# Test 1: watchlist 能读取 25 支股票
# ═══════════════════════════════════════════════════════════════
def test_load_watchlist_returns_25_stocks() -> None:
    """确认从 watchlist.json 能读取到 25 支股票。"""
    symbols = load_watchlist()
    assert len(symbols) == 25, f"期望 25 支股票，实际 {len(symbols)}"
    # 检查关键股票都在
    key_symbols = {"NVDA", "AMD", "AVGO", "MSFT", "GOOGL", "META", "PLTR", "TSLA", "SOFI", "COIN"}
    for s in key_symbols:
        assert s in symbols, f"缺少 {s}"


def test_load_watchlist_file_not_found() -> None:
    """如果 watchlist.json 不存在，应返回默认列表（25支）。"""
    with patch.object(Path, "exists", return_value=False):
        symbols = load_watchlist()
        assert len(symbols) == 25, f"期望默认 25 支，实际 {len(symbols)}"


def test_load_watchlist_empty_json() -> None:
    """如果 watchlist.json 为空列表，应返回空列表。"""
    with patch.object(Path, "exists", return_value=True):
        with patch("builtins.open", new_callable=MagicMock) as mock_open:
            mock_file = MagicMock()
            mock_file.__enter__.return_value.read.return_value = '{"symbols": []}'
            mock_open.return_value = mock_file
            symbols = load_watchlist()
            assert symbols == []


# ═══════════════════════════════════════════════════════════════
# Test 2: 报告生成函数能返回 dict
# ═══════════════════════════════════════════════════════════════
def test_build_report_data_returns_dict() -> None:
    """确认 build_report_data 返回字典且包含必要字段。"""
    info_map = _make_test_info_map()
    result = build_report_data(info_map, portfolio={"NVDA": {"shares": 1, "avg_cost": 200.0}})

    assert isinstance(result, dict)
    assert "report_date" in result
    assert "overview" in result
    assert "sector_stocks" in result
    assert "stock_details" in result
    assert "top5_opportunity" in result
    assert "top5_risk" in result
    assert "portfolio_notes" in result
    assert "overall_conclusion" in result


def test_build_report_data_no_portfolio() -> None:
    """没有持仓数据时不应崩溃。"""
    info_map = _make_test_info_map()
    result = build_report_data(info_map)  # portfolio=None
    assert isinstance(result, dict)
    assert result.get("portfolio_notes") == []
    assert result.get("user_positions") == []


# ═══════════════════════════════════════════════════════════════
# Test 3: markdown 和 json 文件能被创建
# ═══════════════════════════════════════════════════════════════
def test_save_report_creates_files() -> None:
    """确认 save_report 能创建 markdown 和 json 文件。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        info_map = _make_test_info_map()
        data = build_report_data(info_map, portfolio={})

        md_path, json_path = save_report(data, report_dir=tmpdir)

        assert md_path.exists(), f"Markdown 文件未创建: {md_path}"
        assert json_path.exists(), f"JSON 文件未创建: {json_path}"

        # 检查文件内容非空
        assert md_path.stat().st_size > 0, "Markdown 文件为空"
        assert json_path.stat().st_size > 0, "JSON 文件为空"

        # 验证 JSON 可解析
        with open(json_path, encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded["report_date"] == data["report_date"]
        assert len(loaded["stock_details"]) == 25  # 25 支


def test_report_file_naming_convention() -> None:
    """报告文件命名必须符合 daily_decision_YYYY-MM-DD 规范。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        info_map = _make_test_info_map()
        data = build_report_data(info_map, portfolio={})
        md_path, json_path = save_report(data, report_dir=tmpdir)

        date = data["report_date"]
        assert md_path.name == f"daily_decision_{date}.md"
        assert json_path.name == f"daily_decision_{date}.json"


# ═══════════════════════════════════════════════════════════════
# Test 4: 缺少部分价格数据时不会崩溃
# ═══════════════════════════════════════════════════════════════
def test_fetch_prices_partial_failure() -> None:
    """部分股票获取失败时不应导致整个函数崩溃。"""
    import pandas as pd
    from datetime import datetime, timezone
    import numpy as np

    # 构造真实的历史 DataFrame
    dates = pd.date_range("2026-06-30", periods=5, freq="D")
    real_df = pd.DataFrame({
        "Close": [95.0, 96.0, 97.0, 98.0, 100.0],
        "Open": [94.0, 95.0, 96.0, 97.0, 99.0],
        "High": [96.0, 97.0, 98.0, 99.0, 101.0],
        "Low": [93.0, 94.0, 95.0, 96.0, 98.0],
    }, index=dates)

    # 使用 real_df 的 mock: 对成功调用的股票返回 real_df
    def mock_history(period="1mo", interval="1d"):
        return real_df

    # Mock ticker: 给每个股票一个独立的 MagicMock
    created_tickers: dict[str, MagicMock] = {}

    def make_ticker(symbol: str) -> MagicMock:
        if symbol not in created_tickers:
            t = MagicMock()
            t.history.side_effect = mock_history
            created_tickers[symbol] = t
        return created_tickers[symbol]

    # Mock YFinancePriceProvider
    with patch("price_provider.YFinancePriceProvider") as mock_provider_cls:
        instance = mock_provider_cls.return_value

        def mock_get_quote(symbol: str):
            if symbol in ("IONQ", "RGTI", "COIN"):
                from price_provider import PriceNotFoundError
                raise PriceNotFoundError(f"mock error: {symbol}")
            mock_quote = MagicMock()
            mock_quote.price = 100.0
            mock_quote.previous_close = 98.0
            return mock_quote

        instance.get_quote.side_effect = mock_get_quote
        instance._get_ticker_factory.return_value = make_ticker

        symbols = ["NVDA", "MSFT", "AAPL", "IONQ", "RGTI", "COIN"]
        info_map = fetch_prices(symbols)

        assert len(info_map) == 6  # 所有股票都有条目
        # 成功获取的股票应有正常价格
        assert info_map["NVDA"].current_price > 0
        assert info_map["NVDA"].change_pct_today != 0.0  # 今日涨跌幅非零
        # 失败的股票从历史数据降级获取价格，不会有今日涨跌（prev_close 缺失）
        assert info_map["IONQ"].current_price > 0  # 从历史数据降级获得价格
        assert info_map["IONQ"].change_pct_today == 0.0  # 今日涨跌幅为 0（无 prev_close）
        assert info_map["RGTI"].current_price > 0
        assert info_map["COIN"].current_price > 0


def test_build_report_with_zero_prices() -> None:
    """即使部分股票价格为 0，报告生成也不应崩溃。"""
    info_map = _make_test_info_map()
    # 把一半股票价格设为 0
    for i, sym in enumerate(info_map):
        if i % 2 == 0:
            info_map[sym].current_price = 0.0
            info_map[sym].change_pct_today = 0.0

    result = build_report_data(info_map)
    assert isinstance(result, dict)
    assert "top5_opportunity" in result
    assert "top5_risk" in result


# ═══════════════════════════════════════════════════════════════
# Test 5: 输出中包含 Top 5 机会、Top 5 风险、今日一句话结论
# ═══════════════════════════════════════════════════════════════
def test_top5_sections_present() -> None:
    """确认报告包含 Top 5 机会和 Top 5 风险。"""
    info_map = _make_test_info_map()
    result = build_report_data(info_map, portfolio={})

    assert "top5_opportunity" in result
    assert "top5_risk" in result

    top5_opp = result["top5_opportunity"]
    top5_risk = result["top5_risk"]

    assert len(top5_opp) == 5, f"Top 5 机会应有 5 条，实际 {len(top5_opp)}"
    assert len(top5_risk) == 5, f"Top 5 风险应有 5 条，实际 {len(top5_risk)}"

    # 检查每项都有必要字段
    for item in top5_opp:
        assert "symbol" in item
        assert "score" in item
        assert "reason" in item
        assert "why" in item

    for item in top5_risk:
        assert "symbol" in item
        assert "risk_level" in item
        assert "why" in item


def test_overall_conclusion_present() -> None:
    """确认报告包含中文的今日一句话结论。"""
    info_map = _make_test_info_map()
    result = build_report_data(info_map, portfolio={})

    conclusion = result.get("overall_conclusion", "")
    assert conclusion, "今日一句话结论不能为空"
    # 必须是中文开头
    assert any(c in conclusion for c in "适合买入适合观察适合减仓适合不动"), (
        f"结论必须是中文决策导向: {conclusion}"
    )


def test_all_reasons_are_chinese() -> None:
    """确认所有建议理由都是中文。"""
    info_map = _make_test_info_map()
    for sym, info in info_map.items():
        reason = info.reason
        assert reason, f"{sym} 的理由不能为空"
        # 不应包含明显的英文说明文字（股票代码除外）
        non_chinese = sum(1 for c in reason if ord(c) > 127)
        assert non_chinese > len(reason) * 0.3, (
            f"{sym} 的理由应该以中文为主: {reason}"
        )


def test_portfolio_notes_for_held_stocks() -> None:
    """持仓股票应在特别提示中出现。"""
    info_map = _make_test_info_map()
    portfolio = {
        "NVDA": {"shares": 1, "avg_cost": 200.0},
        "SOFI": {"shares": 59, "avg_cost": 17.5},
    }
    result = build_report_data(info_map, portfolio=portfolio)

    notes = result.get("portfolio_notes", [])
    note_symbols = [n["symbol"] for n in notes]
    assert "NVDA" in note_symbols, "持仓 NVDA 应在特别提示中"
    assert "SOFI" in note_symbols, "持仓 SOFI 应在特别提示中"
    for n in notes:
        assert "建议" in n, "持仓特别提示应包含建议"


# ═══════════════════════════════════════════════════════════════
# Test 6: 辅助函数测试
# ═══════════════════════════════════════════════════════════════
def test_judge_trend() -> None:
    """趋势判断逻辑测试。"""
    # 强势
    strong = StockPriceInfo(symbol="TEST", change_pct_20d=10.0)
    assert _judge_trend(strong) == "强势"

    # 弱势
    weak = StockPriceInfo(symbol="TEST", change_pct_20d=-10.0)
    assert _judge_trend(weak) == "弱势"

    # 中性
    neutral = StockPriceInfo(symbol="TEST", change_pct_20d=3.0)
    assert _judge_trend(neutral) == "中性"

    # 降级到 5 日
    c5_only = StockPriceInfo(symbol="TEST", change_pct_5d=6.0)
    assert _judge_trend(c5_only) == "强势"

    c5_weak = StockPriceInfo(symbol="TEST", change_pct_5d=-6.0)
    assert _judge_trend(c5_weak) == "弱势"

    # 降级到今日涨跌
    today_only = StockPriceInfo(symbol="TEST", change_pct_today=4.0)
    assert _judge_trend(today_only) == "强势"


def test_judge_risk() -> None:
    """风险等级判断测试。"""
    # 弱势 + 大跌 → 高
    high = StockPriceInfo(symbol="TEST", trend="弱势", change_pct_20d=-20.0)
    assert _judge_risk(high) == "高"

    # 弱势 → 中
    medium = StockPriceInfo(symbol="TEST", trend="弱势", change_pct_20d=-5.0)
    assert _judge_risk(medium) == "中"

    # 强势+急涨 → 高
    strong_risk = StockPriceInfo(symbol="TEST", trend="强势", change_pct_5d=15.0)
    assert _judge_risk(strong_risk) == "高"

    # 中性 → 低
    low = StockPriceInfo(symbol="TEST", trend="中性")
    assert _judge_risk(low) == "低"


def test_judge_suggestion() -> None:
    """操作建议判断测试。"""
    # 强势+低风险 → 买入观察
    assert _judge_suggestion(StockPriceInfo(symbol="TEST", trend="强势", risk_level="低")) == "买入观察"
    # 强势+中风险 → 继续持有
    assert _judge_suggestion(StockPriceInfo(symbol="TEST", trend="强势", risk_level="中")) == "继续持有"
    # 中性
    assert _judge_suggestion(StockPriceInfo(symbol="TEST", trend="中性")) == "继续持有"
    # 弱势+中风险 → 暂不买入
    assert _judge_suggestion(StockPriceInfo(symbol="TEST", trend="弱势", risk_level="中")) == "暂不买入"
    # 弱势+高风险 → 高风险回避
    assert _judge_suggestion(StockPriceInfo(symbol="TEST", trend="弱势", risk_level="高")) == "高风险回避"


def test_make_overall_conclusion() -> None:
    """今日一句话结论逻辑测试。"""
    # 强势股多 → 适合买入
    strong_map = {f"S{i}": StockPriceInfo(symbol=f"S{i}", trend="强势", risk_level="低") for i in range(15)}
    # 补充中性股
    for i in range(10):
        strong_map[f"N{i}"] = StockPriceInfo(symbol=f"N{i}", trend="中性", risk_level="低")
    conclusion = _make_overall_conclusion(strong_map)
    assert "买入" in conclusion

    # 弱势股多 → 适合减仓
    weak_map = {f"W{i}": StockPriceInfo(symbol=f"W{i}", trend="弱势", risk_level="高") for i in range(15)}
    for i in range(10):
        weak_map[f"N{i}"] = StockPriceInfo(symbol=f"N{i}", trend="中性")
    conclusion = _make_overall_conclusion(weak_map)
    assert "减仓" in conclusion

    # 空 → 适合观察
    empty_map = {}
    conclusion = _make_overall_conclusion(empty_map)
    assert conclusion


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════
def _make_test_info_map() -> dict[str, StockPriceInfo]:
    """构建包含 25 支股票的测试数据。"""
    symbols = [
        "NVDA", "AMD", "AVGO", "TSM", "ASML",
        "MSFT", "GOOGL", "META", "AMZN", "AAPL",
        "PLTR", "TSLA", "SOFI", "IONQ", "RGTI",
        "ARM", "MU", "SMCI", "DELL", "ORCL",
        "CRWD", "PANW", "SNOW", "MDB", "COIN",
    ]

    from northstar.reports.daily_decision_report import COMPANY_NAMES

    info_map: dict[str, StockPriceInfo] = {}
    for i, sym in enumerate(symbols):
        # 制造一些差异以便 Top 5 排序
        base_trend = "强势" if i < 8 else ("弱势" if i > 20 else "中性")
        base_risk = "低" if i < 5 else ("高" if i > 22 else "中")
        info = StockPriceInfo(
            symbol=sym,
            company_cn=COMPANY_NAMES.get(sym, sym),
            current_price=100.0 + i * 10,
            change_pct_today=1.0 + i * 0.3,
            change_pct_5d=3.0 + i * 0.5,
            change_pct_20d=5.0 + i * 0.8,
            trend=base_trend,
            risk_level=base_risk,
        )
        info.suggestion = _judge_suggestion(info)
        from northstar.reports.daily_decision_report import _generate_reason
        info.reason = _generate_reason(info)
        from northstar.reports.daily_decision_report import _compute_score
        info.score = _compute_score(info)
        info_map[sym] = info
    return info_map