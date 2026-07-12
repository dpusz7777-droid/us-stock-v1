# -*- coding: utf-8 -*-
"""Streamlit Dashboard 模块测试。

测试目标：
    验证当前正式 Dashboard 入口（northstar/ui/dashboard.py）可以正常导入、
    持仓决策渲染入口存在、根 dashboard.py 是有效重定向、
    不依赖真实后端。

当前正式入口：
    - northstar.ui.dashboard.run() — Streamlit 主页
    - northstar.ui.dashboard._render_holdings_decisions() — 持仓操作建议
    - northstar.ui.holdings_decision_ui.render_holdings_decision_cards() — 渲染决策卡片
    - root dashboard.py — 重定向到 northstar.ui.dashboard.run
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def portfolio_document() -> dict:
    return {
        "schema_version": "1.1",
        "account": {
            "cash_status": "known",
            "cash": 1000,
            "buying_power": 750,
            "base_currency": "USD",
            "updated_at": "2026-01-01T00:00:00Z",
        },
        "transactions": [
            {
                "transaction_id": "opening-aapl",
                "external_id": None,
                "transaction_type": "OPENING_POSITION",
                "symbol": "AAPL",
                "shares": 2,
                "price": 100,
                "amount": None,
                "fees": 0,
                "executed_at": None,
                "effective_at": "2026-01-01T00:00:00Z",
                "recorded_at": "2026-01-01T00:00:00Z",
                "source": "legacy_migration",
                "note": "",
            }
        ],
    }


class TestDashboardEntryPoints(unittest.TestCase):
    """验证当前正式 Dashboard 入口可以正常导入。"""

    def test_import_root_dashboard_redirects(self) -> None:
        """root dashboard.py 可以导入，是有效重定向"""
        try:
            import dashboard
            self.assertTrue(hasattr(dashboard, "run"))
        except Exception as e:
            self.fail(f"导入 root dashboard.py 失败: {e}")

    def test_import_northstar_dashboard(self) -> None:
        """northstar.ui.dashboard 可以正常导入"""
        try:
            import northstar.ui.dashboard
            self.assertTrue(hasattr(northstar.ui.dashboard, "run"))
            self.assertTrue(hasattr(northstar.ui.dashboard, "_render_holdings_decisions"))
        except Exception as e:
            self.fail(f"导入 northstar.ui.dashboard 失败: {e}")

    def test_import_holdings_decision_ui(self) -> None:
        """northstar.ui.holdings_decision_ui 可以导入且有 render 入口"""
        try:
            from northstar.ui.holdings_decision_ui import render_holdings_decision_cards
            self.assertIsNotNone(render_holdings_decision_cards)
            self.assertTrue(callable(render_holdings_decision_cards))
        except Exception as e:
            self.fail(f"导入 holdings_decision_ui 失败: {e}")

    def test_dashboard_has_holdings_section(self) -> None:
        """dashboard.run() 中引用持仓决策模块（holdings_decision）"""
        import inspect
        import northstar.ui.dashboard
        source = inspect.getsource(northstar.ui.dashboard)
        self.assertIn("_render_holdings_decisions", source,
                       "dashboard.py 应包含 _render_holdings_decisions 函数")
        self.assertIn("holdings_decision", source,
                       "dashboard.py 应引用 holdings_decision 模块")

    def test_root_dashboard_imports_match_northstar(self) -> None:
        """root dashboard.run 和 northstar.ui.dashboard.run 是同一个对象"""
        import dashboard
        import northstar.ui.dashboard as nd
        self.assertIs(dashboard.run, nd.run,
                       "root dashboard.py 应重定向到 northstar.ui.dashboard.run")


class TestPortfolioLoading(unittest.TestCase):
    """验证真实持仓文件加载与错误处理。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "portfolio.json"
        self.path.write_text(json.dumps(portfolio_document()), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_portfolio_loads_without_crash(self) -> None:
        """真实持仓文件加载不崩溃"""
        try:
            from northstar.data.portfolio_snapshot import PortfolioRepository
            repo = PortfolioRepository(self.path)
            state = repo.load()
            self.assertIsNotNone(state)
            self.assertTrue(hasattr(state, "position_symbols"))
        except Exception as e:
            self.fail(f"持仓文件加载失败: {e}")

    def test_empty_portfolio_file_handled(self) -> None:
        """空持仓文件不崩溃，产生可理解的验证异常"""
        self.path.write_text("{}", encoding="utf-8")
        from northstar.data.portfolio_snapshot import PortfolioRepository
        from portfolio_service import PortfolioValidationError
        repo = PortfolioRepository(self.path)
        # 空文件应抛出验证异常但不崩溃
        with self.assertRaises(PortfolioValidationError):
            repo.load()


class TestHoldingsDecisionImport(unittest.TestCase):
    """持仓决策引擎导入测试。"""

    def test_engine_importable(self) -> None:
        """HoldingsDecisionEngine 可以正常导入"""
        from northstar.engine.holdings_decision_engine import HoldingsDecisionEngine
        engine = HoldingsDecisionEngine()
        self.assertIsNotNone(engine)

    def test_generate_holdings_decisions_function_exists(self) -> None:
        """generate_holdings_decisions 函数存在"""
        from northstar.engine.holdings_decision_engine import generate_holdings_decisions
        self.assertTrue(callable(generate_holdings_decisions))


class _MetricColumn:
    def __init__(self, owner):
        self.owner = owner

    def metric(self, label, value, *args, **kwargs):
        self.owner.metrics.append((label, value))


class _CaptureStreamlit:
    def __init__(self):
        self.markdowns = []
        self.captions = []
        self.warnings = []
        self.errors = []
        self.frames = []
        self.metrics = []

    def markdown(self, value, **kwargs): self.markdowns.append(str(value))
    def caption(self, value): self.captions.append(str(value))
    def warning(self, value): self.warnings.append(str(value))
    def error(self, value): self.errors.append(str(value))
    def dataframe(self, value, **kwargs): self.frames.append(value)
    def columns(self, count): return [_MetricColumn(self) for _ in range(count)]


class TestDashboardBusinessBehavior(unittest.TestCase):
    """Business-equivalent assertions retained after the single-dashboard migration."""

    def test_portfolio_block_renders_holdings_valuation_and_pnl(self):
        from northstar.ui.dashboard import _render_portfolio_snapshot_block
        st = _CaptureStreamlit()
        report = {"portfolio_snapshot": {
            "portfolio_snapshot_id": "p1", "market_snapshot_id": "m1",
            "generated_at": "2026-07-10T00:00:00Z", "valuation_status": "complete",
            "coverage_ratio": 1.0, "missing_symbols": [], "base_currency": "USD",
            "cash": "1000", "total_market_value": "240", "total_unrealized_pnl": "40",
            "total_asset_value": "1240", "partial_market_value": "240",
            "positions": [{"symbol": "AAPL", "quantity": "2", "average_cost": "100",
                           "current_price": "120", "price_source": "test-real",
                           "price_as_of": "2026-07-10T00:00:00Z", "market_value": "240",
                           "unrealized_pnl": "40", "unrealized_pnl_percent": "20",
                           "valuation_status": "valued"}],
        }}
        _render_portfolio_snapshot_block(st, report)
        self.assertEqual(st.frames[0][0]["股票"], "AAPL")
        self.assertEqual(st.frames[0][0]["当前价"], "120")
        self.assertEqual(st.frames[0][0]["未实现盈亏"], "40")
        self.assertIn(("总资产", "1240 USD"), st.metrics)

    def test_incomplete_portfolio_hides_totals_and_explains_error(self):
        from northstar.ui.dashboard import _render_portfolio_snapshot_block
        st = _CaptureStreamlit()
        _render_portfolio_snapshot_block(st, {"portfolio_snapshot": {
            "valuation_status": "incomplete", "coverage_ratio": 0.5,
            "missing_symbols": ["AAPL"], "positions": [], "partial_market_value": "100",
            "base_currency": "USD",
        }})
        self.assertTrue(any("估值不完整" in item for item in st.warnings))
        self.assertTrue(any("AAPL" in item for item in st.errors))
        self.assertFalse(any(label == "总资产" for label, _ in st.metrics))

    def test_daily_report_remains_renderable(self):
        from northstar.ui.dashboard import _render_daily_decision_report_block
        st = _CaptureStreamlit()
        report = {
            "recommendation_status": "OK", "data_quality": {"issue_counts": {}},
            "overview": {"当前日期": "2026-07-10", "观察池股票数量": 3, "数据更新时间": "now"},
            "top5_opportunity": [{"symbol": "NVDA"}], "top5_risk": [{"symbol": "SOFI"}],
            "overall_conclusion": "观望", "_md_path": "reports/example.md",
        }
        _render_daily_decision_report_block(st, report)
        rendered = "\n".join(st.markdowns)
        self.assertIn("每日决策报告", rendered)
        self.assertIn("NVDA", rendered)
        self.assertIn("SOFI", rendered)

    def test_manual_items_are_passed_into_engine_not_posthoc_display_mutation(self):
        from northstar.ui.dashboard import _generate_holdings_for_dashboard
        with patch("northstar.engine.holdings_decision_engine.generate_holdings_decisions") as generate:
            generate.return_value = ([], {})
            _generate_holdings_for_dashboard((("NVDA", "250.50"),))
        kwargs = generate.call_args.kwargs
        self.assertEqual(kwargs["manual_prices"]["NVDA"], Decimal("250.50"))

    def test_homepage_keeps_review_daily_report_and_holdings(self):
        import inspect
        from northstar.ui import dashboard as module
        source = inspect.getsource(module.run)
        self.assertIn("_render_holdings_decisions(st)", source)
        self.assertIn("_render_daily_decision_report_block(st, report)", source)
        self.assertIn("_render_recommendation_review(st)", source)
        self.assertLess(source.index("_render_holdings_decisions(st)"), source.index("_render_portfolio_snapshot_block(st, report)"))


if __name__ == "__main__":
    unittest.main()
