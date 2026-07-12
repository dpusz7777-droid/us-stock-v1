#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试策略验证闭环模块（Recommendation Performance Loop）。

    测试目标：
        1. compute_recommendation_performance() 的正确性
        2. get_strategy_stats() 的汇总统计
        3. get_recommendation_performance_report() 的排序与限流
        4. 字段兼容性（symbol/entry_price/timestamp/status）
        5. 边界情况（空列表、缺少字段、价格获取失败）
"""

from __future__ import annotations

import sys
from pathlib import Path

# 确保能导入 northstar 模块
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


# ===== Fixtures =====

@pytest.fixture
def mock_recommendations():
    """生成一组模拟推荐数据。"""
    now = datetime.now()
    return [
        {
            "symbol": "AAPL",
            "price": 150.0,
            "created_at": (now - timedelta(days=10)).isoformat(),
            "status": "open",
            "action": "买入",
            "id": "rec_001",
        },
        {
            "symbol": "NVDA",
            "price": 120.0,
            "created_at": (now - timedelta(days=7)).isoformat(),
            "status": "open",
            "action": "买入",
            "id": "rec_002",
        },
        {
            "symbol": "TSLA",
            "price": 200.0,
            "created_at": (now - timedelta(days=3)).isoformat(),
            "status": "open",
            "action": "买入",
            "id": "rec_003",
        },
        {
            "symbol": "MSFT",
            "price": 380.0,
            "created_at": (now - timedelta(days=1)).isoformat(),
            "status": "open",
            "action": "卖出",
            "id": "rec_004",
        },
    ]


@pytest.fixture
def mock_provider():
    """模拟价格提供者，返回固定的当前价格。"""
    from decimal import Decimal
    from price_provider_v2 import PriceResultV2, PRICE_STATUS_OK

    def fake_get_price(symbol):
        prices = {
            "AAPL": PriceResultV2(symbol="AAPL", price=Decimal("165.0"), status=PRICE_STATUS_OK),
            "NVDA": PriceResultV2(symbol="NVDA", price=Decimal("110.0"), status=PRICE_STATUS_OK),
            "TSLA": PriceResultV2(symbol="TSLA", price=Decimal("210.0"), status=PRICE_STATUS_OK),
            "MSFT": PriceResultV2(symbol="MSFT", price=Decimal("370.0"), status=PRICE_STATUS_OK),
        }
        return prices.get(symbol.upper(), PriceResultV2(symbol=symbol.upper(), price=None, status="not_found", error_message="symbol not found"))

    provider = MagicMock()
    provider.get_price.side_effect = fake_get_price
    return provider


# ===== 测试 compute_recommendation_performance =====

class TestComputeRecommendationPerformance:
    """测试 compute_recommendation_performance 函数。"""

    def test_returns_list(self, mock_recommendations):
        from northstar.performance.recommendation_tracker import compute_recommendation_performance
        result = compute_recommendation_performance(mock_recommendations)
        assert isinstance(result, list)
        assert len(result) == len(mock_recommendations)

    def test_each_result_has_required_fields(self, mock_recommendations):
        from northstar.performance.recommendation_tracker import compute_recommendation_performance
        result = compute_recommendation_performance(mock_recommendations)
        required = {"symbol", "entry_price", "current_price", "status",
                    "pnl_percent", "pnl_absolute", "max_drawdown", "holding_days"}
        for r in result:
            assert required.issubset(r.keys()), f"Missing fields in {r}"

    def test_symbol_normalization(self, mock_recommendations):
        """测试股票代码被自动转为大写。"""
        recs = [{"symbol": "aapl", "price": 100.0}]
        from northstar.performance.recommendation_tracker import compute_recommendation_performance
        result = compute_recommendation_performance(recs)
        assert result[0]["symbol"] == "AAPL"

    def test_entry_price_from_price_field(self, mock_recommendations):
        """测试 entry_price 从 price 字段正确映射。"""
        from northstar.performance.recommendation_tracker import compute_recommendation_performance
        result = compute_recommendation_performance(mock_recommendations)
        assert result[0]["entry_price"] == 150.0

    def test_empty_list(self):
        """测试空列表返回空。"""
        from northstar.performance.recommendation_tracker import compute_recommendation_performance
        result = compute_recommendation_performance([])
        assert result == []

    def test_missing_symbol(self):
        """测试缺少 symbol 的情况。"""
        recs = [{"price": 100.0}]
        from northstar.performance.recommendation_tracker import compute_recommendation_performance
        result = compute_recommendation_performance(recs)
        assert result[0]["price_fetch_error"] is not None
        assert result[0]["symbol"] == ""

    def test_missing_entry_price(self):
        """测试缺少 entry_price 的情况。"""
        recs = [{"symbol": "AAPL"}]
        from northstar.performance.recommendation_tracker import compute_recommendation_performance
        result = compute_recommendation_performance(recs)
        assert result[0]["price_fetch_error"] is not None

    def test_invalid_symbol_format(self):
        """测试无效的股票代码格式。"""
        recs = [{"symbol": "12345", "price": 100.0}]
        from northstar.performance.recommendation_tracker import compute_recommendation_performance
        result = compute_recommendation_performance(recs)
        assert "请使用英文股票代码" in (result[0]["price_fetch_error"] or "")

    def test_zero_entry_price(self):
        """测试入场价为 0 的情况。"""
        recs = [{"symbol": "AAPL", "price": 0}]
        from northstar.performance.recommendation_tracker import compute_recommendation_performance
        result = compute_recommendation_performance(recs)
        assert result[0]["price_fetch_error"] is not None

    def test_holding_days_computation(self):
        """测试持有天数计算。"""
        from northstar.performance.recommendation_tracker import _compute_holding_days
        now = datetime.now()
        days_ago_5 = (now - timedelta(days=5)).isoformat()
        days = _compute_holding_days(days_ago_5)
        assert days == 5

    def test_holding_days_none(self):
        """测试缺少时间戳时 holding_days 为 None。"""
        from northstar.performance.recommendation_tracker import _compute_holding_days
        assert _compute_holding_days(None) is None
        assert _compute_holding_days("") is None


# ===== 测试 get_strategy_stats =====

class TestGetStrategyStats:
    """测试 get_strategy_stats 函数。"""

    def test_returns_dict_with_expected_keys(self, mock_recommendations):
        from northstar.performance.recommendation_tracker import get_strategy_stats
        stats = get_strategy_stats(mock_recommendations)
        expected = {"total_recommendations", "active_recommendations", "win_rate",
                    "avg_return", "avg_holding_days", "total_pnl_absolute",
                    "best_performer", "worst_performer"}
        assert expected.issubset(stats.keys())

    def test_total_recommendations_count(self, mock_recommendations):
        from northstar.performance.recommendation_tracker import get_strategy_stats
        stats = get_strategy_stats(mock_recommendations)
        assert stats["total_recommendations"] == 4

    def test_active_recommendations(self, mock_recommendations):
        from northstar.performance.recommendation_tracker import get_strategy_stats
        stats = get_strategy_stats(mock_recommendations)
        # All fixtures have status "open"
        assert stats["active_recommendations"] == 4

    def test_empty_recommendations(self):
        from northstar.performance.recommendation_tracker import get_strategy_stats
        stats = get_strategy_stats([])
        assert stats["total_recommendations"] == 0
        assert stats["active_recommendations"] == 0
        assert stats["win_rate"] is None
        assert stats["avg_return"] is None

    def test_all_none_when_no_data(self):
        from northstar.performance.recommendation_tracker import get_strategy_stats
        stats = get_strategy_stats([])
        assert stats["best_performer"] is None
        assert stats["worst_performer"] is None


# ===== 测试 get_recommendation_performance_report =====

class TestGetRecommendationPerformanceReport:
    """测试 get_recommendation_performance_report 函数。"""

    def test_returns_limited_results(self, mock_recommendations):
        from northstar.performance.recommendation_tracker import get_recommendation_performance_report
        report = get_recommendation_performance_report(mock_recommendations, limit=2)
        assert len(report) <= 2

    def test_default_limit_is_10(self, mock_recommendations):
        from northstar.performance.recommendation_tracker import get_recommendation_performance_report
        # Generate more than 10 recs
        many_recs = []
        for i in range(15):
            many_recs.append({"symbol": "AAPL", "price": 100.0, "created_at": f"2026-01-{15-i:02d}T00:00:00"})
        report = get_recommendation_performance_report(many_recs)
        assert len(report) == 10

    def test_empty_when_no_recommendations(self):
        from northstar.performance.recommendation_tracker import get_recommendation_performance_report
        report = get_recommendation_performance_report([])
        assert report == []

    def test_sorted_by_recency(self):
        """测试按时间倒序排列。"""
        recs = [
            {"symbol": "AAPL", "price": 100.0, "created_at": "2026-01-01T00:00:00"},
            {"symbol": "NVDA", "price": 200.0, "created_at": "2026-01-03T00:00:00"},
            {"symbol": "TSLA", "price": 300.0, "created_at": "2026-01-02T00:00:00"},
        ]
        from northstar.performance.recommendation_tracker import get_recommendation_performance_report
        report = get_recommendation_performance_report(recs, limit=3)
        # Should be sorted by created_at descending: NVDA, TSLA, AAPL
        symbols = [r["symbol"] for r in report]
        assert symbols == ["NVDA", "TSLA", "AAPL"]


# ===== 测试格式化函数 =====

class TestFormatFunctions:
    """测试 format_pnl 和 format_absolute。"""

    def test_format_pnl_positive(self):
        from northstar.performance.recommendation_tracker import format_pnl
        assert format_pnl(5.5) == "+5.50%"

    def test_format_pnl_negative(self):
        from northstar.performance.recommendation_tracker import format_pnl
        assert format_pnl(-3.2) == "-3.20%"

    def test_format_pnl_zero(self):
        from northstar.performance.recommendation_tracker import format_pnl
        assert format_pnl(0.0) == "0.00%"

    def test_format_pnl_none(self):
        from northstar.performance.recommendation_tracker import format_pnl
        assert format_pnl(None) == "N/A"

    def test_format_absolute_positive(self):
        from northstar.performance.recommendation_tracker import format_absolute
        assert format_absolute(150.0) == "+$150.00"

    def test_format_absolute_negative(self):
        from northstar.performance.recommendation_tracker import format_absolute
        assert format_absolute(-50.5) == "-$50.50"

    def test_format_absolute_zero(self):
        from northstar.performance.recommendation_tracker import format_absolute
        assert format_absolute(0.0) == "$0.00"

    def test_format_absolute_none(self):
        from northstar.performance.recommendation_tracker import format_absolute
        assert format_absolute(None) == "N/A"


# ===== 测试模块导入 =====

class TestRecommendationTrackerImports:
    """测试模块导入是否正常。"""

    def test_import_performance_module(self):
        import northstar.performance
        assert hasattr(northstar.performance, "compute_recommendation_performance")
        assert hasattr(northstar.performance, "get_strategy_stats")
        assert hasattr(northstar.performance, "get_recommendation_performance_report")

    def test_direct_import(self):
        from northstar.performance.recommendation_tracker import (
            compute_recommendation_performance,
            get_strategy_stats,
            get_recommendation_performance_report,
            format_pnl,
            format_absolute,
        )
        assert callable(compute_recommendation_performance)
        assert callable(get_strategy_stats)
        assert callable(get_recommendation_performance_report)
        assert callable(format_pnl)
        assert callable(format_absolute)


# ===== 测试 schema 兼容性 =====

class TestSchemaCompatibility:
    """测试兼容现有 recommendation_store schema。"""

    def test_entry_price_compatibility(self):
        """测试支持 entry_price 字段。"""
        recs = [{"symbol": "AAPL", "entry_price": 150.0, "created_at": "2026-01-01T00:00:00"}]
        from northstar.performance.recommendation_tracker import compute_recommendation_performance
        result = compute_recommendation_performance(recs)
        assert result[0]["entry_price"] == 150.0

    def test_multiple_price_fields_priority(self):
        """测试 entry_price > price > recommendation_price 的优先级。"""
        recs = [{
            "symbol": "AAPL",
            "entry_price": 100.0,
            "price": 150.0,
            "recommendation_price": 200.0,
            "created_at": "2026-01-01T00:00:00",
        }]
        from northstar.performance.recommendation_tracker import compute_recommendation_performance
        result = compute_recommendation_performance(recs)
        # entry_price should take priority
        assert result[0]["entry_price"] == 100.0

    def test_timestamp_compatibility(self):
        """测试支持 timestamp 字段。"""
        recs = [{"symbol": "AAPL", "price": 150.0, "timestamp": "2026-01-01T00:00:00"}]
        from northstar.performance.recommendation_tracker import compute_recommendation_performance
        result = compute_recommendation_performance(recs)
        assert result[0]["holding_days"] is not None


# ===== 测试回撤计算 =====

class TestMaxDrawdown:
    """测试 max_drawdown 简化计算。"""

    def test_positive_pnl_has_zero_drawdown(self):
        """正收益时最大回撤为 0。"""
        recs = [{"symbol": "AAPL", "price": 100.0, "created_at": "2026-01-01T00:00:00"}]
        from northstar.performance.recommendation_tracker import compute_recommendation_performance
        with patch.object(
            sys.modules.get("northstar.performance.recommendation_tracker", None) or __import__("northstar.performance.recommendation_tracker"),
            "_fetch_current_price",
            return_value=(120.0, None),
        ):
            pass  # We'll test this through the actual module
        # The test above is just structural; we'll verify in the mock integration test

    def test_negative_pnl_has_drawdown_equal_to_pnl(self):
        """负收益时 max_drawdown = pnl_percent。"""
        recs = [{"symbol": "AAPL", "price": 100.0, "created_at": "2026-01-01T00:00:00"}]
        from northstar.performance.recommendation_tracker import compute_recommendation_performance
        # We need to test this by mocking the price provider
        # This will be tested in the integration test below


# ===== 集成测试（模拟价格提供者） =====

class TestIntegrationWithMockProvider:
    """集成测试：通过 mock 价格提供者验证完整计算流程。"""

    def test_pnl_calculation_correctness(self, mock_recommendations, mock_provider):
        """验证 PnL 计算准确性。

        AAPL: entry=150, current=165 → pnl% = 10%, pnl_abs = +15
        NVDA: entry=120, current=110 → pnl% = -8.33%, pnl_abs = -10
        TSLA: entry=200, current=210 → pnl% = 5%, pnl_abs = +10
        MSFT: entry=380, current=370 → pnl% = -2.63%, pnl_abs = -10
        """
        from northstar.performance.recommendation_tracker import _fetch_current_price, compute_recommendation_performance

        # 手动模拟价格
        with patch("northstar.performance.recommendation_tracker._fetch_current_price") as mock_fetch:
            def fake_fetch(symbol):
                prices = {
                    "AAPL": (165.0, None),
                    "NVDA": (110.0, None),
                    "TSLA": (210.0, None),
                    "MSFT": (370.0, None),
                }
                return prices.get(symbol.upper(), (None, "not found"))

            mock_fetch.side_effect = fake_fetch
            result = compute_recommendation_performance(mock_recommendations)

        # AAPL
        aapl = next(r for r in result if r["symbol"] == "AAPL")
        assert aapl["pnl_percent"] == 10.0  # (165-150)/150*100
        assert aapl["pnl_absolute"] == 15.0
        assert aapl["max_drawdown"] == 0.0  # positive pnl

        # NVDA
        nvda = next(r for r in result if r["symbol"] == "NVDA")
        assert nvda["pnl_percent"] == -8.33  # (110-120)/120*100
        assert nvda["pnl_absolute"] == -10.0
        assert nvda["max_drawdown"] == -8.33  # negative pnl

        # TSLA
        tsla = next(r for r in result if r["symbol"] == "TSLA")
        assert tsla["pnl_percent"] == 5.0
        assert tsla["pnl_absolute"] == 10.0
        assert tsla["max_drawdown"] == 0.0

        # MSFT (SHORT: 卖出入场价380 > 当前价370 → 盈利)
        msft = next(r for r in result if r["symbol"] == "MSFT")
        assert msft["pnl_percent"] == 2.63  # (380-370)/380*100 = +2.63%
        assert msft["pnl_absolute"] == 10.0
        assert msft["max_drawdown"] == 0.0  # positive pnl

    def test_strategy_stats_with_mock_price(self, mock_recommendations):
        """验证 get_strategy_stats 在模拟价格下的结果。

        4 条推荐（MSFT 做空），3 正 1 负：
        AAPL LONG:  (165-150)/150 = +10.00%
        NVDA LONG:  (110-120)/120 = -8.33%
        TSLA LONG:  (210-200)/200 = +5.00%
        MSFT SHORT: (380-370)/380 = +2.63%
        win_rate = 3/4 = 75%
        avg_return = (10 - 8.33 + 5 + 2.63) / 4 = 2.33%
        """
        from northstar.performance.recommendation_tracker import get_strategy_stats

        with patch("northstar.performance.recommendation_tracker._fetch_current_price") as mock_fetch:
            def fake_fetch(symbol):
                prices = {
                    "AAPL": (165.0, None),
                    "NVDA": (110.0, None),
                    "TSLA": (210.0, None),
                    "MSFT": (370.0, None),
                }
                return prices.get(symbol.upper(), (None, "not found"))
            mock_fetch.side_effect = fake_fetch

            stats = get_strategy_stats(mock_recommendations)

        assert stats["total_recommendations"] == 4
        assert stats["win_rate"] == 75.0  # 3/4 (MSFT short also profitable)
        assert stats["avg_return"] == 2.33  # (10 - 8.33 + 5 + 2.63) / 4
        assert stats["best_performer"]["symbol"] == "AAPL"  # +10%
        assert stats["worst_performer"]["symbol"] == "NVDA"  # -8.33%

class TestDirectionAwarePnL:
    """测试方向感知的 PnL 计算。"""

    def test_long_profit(self):
        from northstar.performance.recommendation_tracker import compute_recommendation_performance
        with patch("northstar.performance.recommendation_tracker._fetch_current_price", return_value=(120.0, None)):
            r = compute_recommendation_performance([{"symbol": "AAPL", "price": 100.0, "action": "买入"}])
        assert r[0]["pnl_percent"] == 20.0
        assert r[0]["direction"] == "LONG"

    def test_long_loss(self):
        from northstar.performance.recommendation_tracker import compute_recommendation_performance
        with patch("northstar.performance.recommendation_tracker._fetch_current_price", return_value=(80.0, None)):
            r = compute_recommendation_performance([{"symbol": "AAPL", "price": 100.0, "action": "BUY"}])
        assert r[0]["pnl_percent"] == -20.0

    def test_short_profit(self):
        from northstar.performance.recommendation_tracker import compute_recommendation_performance
        with patch("northstar.performance.recommendation_tracker._fetch_current_price", return_value=(80.0, None)):
            r = compute_recommendation_performance([{"symbol": "AAPL", "price": 100.0, "action": "卖出"}])
        assert r[0]["pnl_percent"] == 20.0
        assert r[0]["direction"] == "SHORT"

    def test_short_loss(self):
        from northstar.performance.recommendation_tracker import compute_recommendation_performance
        with patch("northstar.performance.recommendation_tracker._fetch_current_price", return_value=(120.0, None)):
            r = compute_recommendation_performance([{"symbol": "AAPL", "price": 100.0, "action": "SHORT"}])
        assert r[0]["pnl_percent"] == -20.0

    def test_hold_does_not_compute_pnl(self):
        from northstar.performance.recommendation_tracker import compute_recommendation_performance
        r = compute_recommendation_performance([{"symbol": "AAPL", "price": 100.0, "action": "持有"}])
        assert r[0]["pnl_percent"] is None
        assert "不计算收益" in (r[0]["price_fetch_error"] or "")

    def test_input_not_modified(self):
        from northstar.performance.recommendation_tracker import compute_recommendation_performance
        import copy
        orig = [{"symbol": "AAPL", "price": 100.0, "action": "买入"}]
        before = copy.deepcopy(orig)
        with patch("northstar.performance.recommendation_tracker._fetch_current_price", return_value=(120.0, None)):
            compute_recommendation_performance(orig)
        assert orig == before

    def test_idempotent(self):
        from northstar.performance.recommendation_tracker import compute_recommendation_performance
        with patch("northstar.performance.recommendation_tracker._fetch_current_price", return_value=(120.0, None)):
            r1 = compute_recommendation_performance([{"symbol": "AAPL", "price": 100.0, "action": "买入"}])
            r2 = compute_recommendation_performance([{"symbol": "AAPL", "price": 100.0, "action": "买入"}])
        assert r1 == r2

    def test_price_source_failure(self):
        from northstar.performance.recommendation_tracker import compute_recommendation_performance
        with patch("northstar.performance.recommendation_tracker._fetch_current_price", return_value=(None, "failed")):
            r = compute_recommendation_performance([{"symbol": "AAPL", "price": 100.0, "action": "买入"}])
        assert r[0]["pnl_percent"] is None
        assert r[0]["price_fetch_error"] is not None

    def test_missing_current_price(self):
        from northstar.performance.recommendation_tracker import compute_recommendation_performance
        with patch("northstar.performance.recommendation_tracker._fetch_current_price", return_value=(None, None)):
            r = compute_recommendation_performance([{"symbol": "AAPL", "price": 100.0, "action": "买入"}])
        assert r[0]["pnl_percent"] is None

    def test_unknown_action_treated_as_hold(self):
        from northstar.performance.recommendation_tracker import compute_recommendation_performance
        r = compute_recommendation_performance([{"symbol": "AAPL", "price": 100.0, "action": "unknown_xyz"}])
        assert r[0]["pnl_percent"] is None

    def test_watch_action_treated_as_hold(self):
        from northstar.performance.recommendation_tracker import compute_recommendation_performance
        r = compute_recommendation_performance([{"symbol": "AAPL", "price": 100.0, "action": "观察"}])
        assert r[0]["pnl_percent"] is None

    def test_risk_warning_treated_as_hold(self):
        from northstar.performance.recommendation_tracker import compute_recommendation_performance
        r = compute_recommendation_performance([{"symbol": "AAPL", "price": 100.0, "action": "风险提示"}])
        assert r[0]["pnl_percent"] is None
