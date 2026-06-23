# -*- coding: utf-8 -*-
"""briefing 统一简报测试。"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from ai_briefing import LLMClientError
from briefing import (
    build_ai_briefing_markdown,
    build_briefing_data,
    save_ai_briefing_report,
    show_ai_briefing,
    show_briefing,
)
from market_info import NewsProviderError, NewsRow
from price_provider import PriceProviderError, PriceQuote


def schema_document() -> dict:
    return {
        "schema_version": "1.1",
        "account": {
            "account_id": "briefing_test",
            "account_name": "简报测试账户",
            "broker": "test",
            "base_currency": "USD",
            "cash_status": "known",
            "cash": 100,
            "buying_power": 80,
            "created_at": "2026-06-22T17:00:00Z",
            "updated_at": "2026-06-22T17:00:00Z",
        },
        "settings": {
            "stop_loss_pct": 8,
            "target_profit_pct": 25,
            "max_single_position_pct": 20,
        },
        "transactions": [
            {
                "transaction_id": "txn_briefing_001",
                "external_id": None,
                "transaction_type": "OPENING_POSITION",
                "symbol": "SOFI",
                "shares": 2,
                "price": 10,
                "amount": None,
                "fees": 0,
                "executed_at": None,
                "effective_at": "2026-06-22T17:15:41Z",
                "recorded_at": "2026-06-22T17:15:41Z",
                "source": "legacy_migration",
                "note": "测试期初持仓。",
            }
        ],
    }


class BriefingTests(unittest.TestCase):
    def make_files(self) -> tuple[tempfile.TemporaryDirectory, Path, Path]:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        portfolio_path = root / "portfolio_migrated_candidate.json"
        watchlist_path = root / "watchlist.json"
        portfolio_path.write_text(
            json.dumps(schema_document(), ensure_ascii=False), encoding="utf-8"
        )
        watchlist_path.write_text(
            json.dumps({"symbols": ["NVDA", "AAPL"]}, ensure_ascii=False),
            encoding="utf-8",
        )
        return temp_dir, portfolio_path, watchlist_path

    def test_show_briefing_outputs_unified_sections_without_writing_files(self) -> None:
        _, portfolio_path, watchlist_path = self.make_files()
        before = {
            portfolio_path: portfolio_path.read_bytes(),
            watchlist_path: watchlist_path.read_bytes(),
        }

        class FakePriceProvider:
            prices = {
                "SOFI": Decimal("12.50"),
                "NVDA": Decimal("100.00"),
                "AAPL": Decimal("200.00"),
            }

            def get_quote(self, symbol: str) -> PriceQuote:
                return PriceQuote(
                    symbol=symbol,
                    price=self.prices[symbol],
                    previous_close=self.prices[symbol] - Decimal("1"),
                    source="fake",
                    price_as_of="2026-06-23T12:30:00Z",
                )

        class FakeNewsProvider:
            def get_news(self, symbol: str, limit: int = 3) -> list[NewsRow]:
                return [
                    NewsRow(
                        symbol=symbol,
                        title=f"{symbol} headline {index}",
                        publisher="Yahoo Finance",
                        published_at="2026-06-23T12:30:00Z",
                        link=f"https://example.com/{symbol.lower()}/{index}",
                    )
                    for index in range(1, limit + 1)
                ]

        output = io.StringIO()
        with redirect_stdout(output):
            result = show_briefing(
                portfolio_path,
                watchlist_path,
                price_provider=FakePriceProvider(),
                news_provider=FakeNewsProvider(),
            )

        text = output.getvalue()
        self.assertTrue(result)
        self.assertIn("每日统一简报", text)
        self.assertIn("[账户摘要]", text)
        self.assertIn("总资产: $125.00", text)
        self.assertIn("[持仓概览]", text)
        self.assertIn("SOFI", text)
        self.assertIn("[新闻速览]", text)
        self.assertIn("NVDA headline 1", text)
        self.assertIn("[财报关注]", text)
        self.assertIn("[观察池异动]", text)
        self.assertIn("只读简报：未修改文件，未连接券商，未自动交易", text)
        self.assertEqual(portfolio_path.read_bytes(), before[portfolio_path])
        self.assertEqual(watchlist_path.read_bytes(), before[watchlist_path])

    def test_show_briefing_keeps_running_when_news_or_price_fails(self) -> None:
        _, portfolio_path, watchlist_path = self.make_files()

        class PartialPriceProvider:
            def get_quote(self, symbol: str) -> PriceQuote:
                if symbol == "SOFI":
                    raise PriceProviderError("fake price failure")
                return PriceQuote(
                    symbol=symbol,
                    price=Decimal("100"),
                    previous_close=Decimal("99"),
                    source="fake",
                    price_as_of="2026-06-23T12:30:00Z",
                )

        class FailingNewsProvider:
            def get_news(self, symbol: str, limit: int = 3) -> list[NewsRow]:
                raise NewsProviderError("fake news failure")

        output = io.StringIO()
        with redirect_stdout(output):
            result = show_briefing(
                portfolio_path,
                watchlist_path,
                price_provider=PartialPriceProvider(),
                news_provider=FailingNewsProvider(),
            )

        text = output.getvalue()
        self.assertTrue(result)
        self.assertIn("SOFI 行情获取失败", text)
        self.assertIn("新闻获取失败", text)
        self.assertIn("只读简报", text)
        self.assertNotIn("Traceback", text)

    def test_build_briefing_data_returns_structured_ai_input(self) -> None:
        _, portfolio_path, watchlist_path = self.make_files()

        class FakePriceProvider:
            prices = {
                "SOFI": Decimal("12.50"),
                "NVDA": Decimal("100.00"),
                "AAPL": Decimal("200.00"),
            }

            def get_quote(self, symbol: str) -> PriceQuote:
                return PriceQuote(
                    symbol=symbol,
                    price=self.prices[symbol],
                    previous_close=self.prices[symbol] - Decimal("1"),
                    source="fake",
                    price_as_of="2026-06-23T12:30:00Z",
                )

        class FakeNewsProvider:
            def get_news(self, symbol: str, limit: int = 3) -> list[NewsRow]:
                return [
                    NewsRow(
                        symbol=symbol,
                        title=f"{symbol} headline",
                        publisher="Yahoo Finance",
                        published_at="2026-06-23T12:30:00Z",
                        link=f"https://example.com/{symbol.lower()}",
                    )
                ]

        data = build_briefing_data(
            portfolio_path,
            watchlist_path,
            price_provider=FakePriceProvider(),
            news_provider=FakeNewsProvider(),
        )

        self.assertEqual(data["account"]["total_equity"], "125.00")
        self.assertEqual(data["positions"][0]["symbol"], "SOFI")
        self.assertIn("NVDA", data["watchlist"])
        self.assertTrue(data["news"])
        self.assertTrue(data["earnings"])
        self.assertTrue(data["screener"])
        self.assertTrue(data["read_only"])
        self.assertFalse(data["auto_trade"])

    def test_show_ai_briefing_prints_json_fields_using_briefing_format(self) -> None:
        _, portfolio_path, watchlist_path = self.make_files()

        class FakeLLMClient:
            def generate_json(self, prompt: str) -> dict[str, str]:
                return {
                    "account_summary": "账户摘要内容",
                    "portfolio_analysis": "持仓分析内容",
                    "watchlist_analysis": "观察池分析内容",
                    "risk_warning": "风险提示内容",
                    "action_items": "今日操作建议内容",
                }

        output = io.StringIO()
        with redirect_stdout(output):
            result = show_ai_briefing(
                portfolio_path,
                watchlist_path,
                price_provider=FailingPriceProvider(),
                news_provider=EmptyNewsProvider(),
                llm_client=FakeLLMClient(),
            )

        text = output.getvalue()
        self.assertTrue(result)
        self.assertIn("AI 每日简报", text)
        self.assertIn("[账户摘要]", text)
        self.assertIn("账户摘要内容", text)
        self.assertIn("[持仓分析]", text)
        self.assertIn("[观察池分析]", text)
        self.assertIn("[风险提示]", text)
        self.assertIn("[今日操作建议]", text)
        self.assertIn("只读 AI 简报：未修改文件，未连接券商，未自动交易", text)

    def test_build_ai_briefing_markdown_contains_required_sections(self) -> None:
        markdown = build_ai_briefing_markdown(
            ai_result(),
            generated_at=datetime(2026, 6, 23, 9, 30, 0),
        )

        self.assertIn("# AI 每日简报", markdown)
        self.assertIn("生成时间: 2026-06-23T09:30:00", markdown)
        self.assertIn("数据源说明", markdown)
        self.assertIn("## 账户摘要", markdown)
        self.assertIn("## 持仓分析", markdown)
        self.assertIn("## 观察池分析", markdown)
        self.assertIn("## 风险提示", markdown)
        self.assertIn("## 今日操作建议", markdown)

    def test_save_ai_briefing_report_creates_reports_dir_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir) / "reports"
            saved_path = save_ai_briefing_report(
                ai_result(),
                reports_dir=reports_dir,
                generated_at=datetime(2026, 6, 23, 9, 30, 0),
            )

            self.assertEqual(
                saved_path,
                reports_dir / "2026-06-23-ai-briefing.md",
            )
            self.assertTrue(saved_path.is_file())
            text = saved_path.read_text(encoding="utf-8")
            self.assertIn("账户摘要内容", text)
            self.assertIn("数据源说明", text)

    def test_save_ai_briefing_report_appends_timestamp_when_file_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir) / "reports"
            reports_dir.mkdir()
            existing = reports_dir / "2026-06-23-ai-briefing.md"
            existing.write_text("old report", encoding="utf-8")

            saved_path = save_ai_briefing_report(
                ai_result(),
                reports_dir=reports_dir,
                generated_at=datetime(2026, 6, 23, 9, 30, 5),
            )

            self.assertEqual(
                saved_path,
                reports_dir / "2026-06-23-ai-briefing-093005.md",
            )
            self.assertEqual(existing.read_text(encoding="utf-8"), "old report")
            self.assertTrue(saved_path.is_file())

    def test_show_ai_briefing_save_writes_report_after_success(self) -> None:
        _, portfolio_path, watchlist_path = self.make_files()
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir) / "reports"

            class FakeLLMClient:
                def generate_json(self, prompt: str) -> dict[str, str]:
                    return ai_result()

            output = io.StringIO()
            with redirect_stdout(output):
                result = show_ai_briefing(
                    portfolio_path,
                    watchlist_path,
                    price_provider=FailingPriceProvider(),
                    news_provider=EmptyNewsProvider(),
                    llm_client=FakeLLMClient(),
                    save_report=True,
                    reports_dir=reports_dir,
                )

            text = output.getvalue()
            self.assertTrue(result)
            self.assertIn("已保存 Markdown 报告", text)
            files = list(reports_dir.glob("*-ai-briefing*.md"))
            self.assertEqual(len(files), 1)
            self.assertIn("账户摘要内容", files[0].read_text(encoding="utf-8"))

    def test_show_ai_briefing_handles_llm_failure_without_crashing(self) -> None:
        _, portfolio_path, watchlist_path = self.make_files()
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir) / "reports"

            class FailingLLMClient:
                def generate_json(self, prompt: str) -> dict[str, str]:
                    raise LLMClientError("fake llm failure")

            output = io.StringIO()
            with redirect_stdout(output):
                result = show_ai_briefing(
                    portfolio_path,
                    watchlist_path,
                    price_provider=FailingPriceProvider(),
                    news_provider=EmptyNewsProvider(),
                    llm_client=FailingLLMClient(),
                    save_report=True,
                    reports_dir=reports_dir,
                )

            text = output.getvalue()
            self.assertFalse(result)
            self.assertIn("AI 简报生成失败", text)
            self.assertIn("fake llm failure", text)
            self.assertIn("只读 AI 简报", text)
            self.assertNotIn("Traceback", text)
            self.assertFalse(reports_dir.exists())


class FailingPriceProvider:
    def get_quote(self, symbol: str) -> PriceQuote:
        raise PriceProviderError("fake price failure")


class EmptyNewsProvider:
    def get_news(self, symbol: str, limit: int = 3) -> list[NewsRow]:
        return []


def ai_result() -> dict[str, str]:
    return {
        "account_summary": "账户摘要内容",
        "portfolio_analysis": "持仓分析内容",
        "watchlist_analysis": "观察池分析内容",
        "risk_warning": "风险提示内容",
        "action_items": "今日操作建议内容",
    }


if __name__ == "__main__":
    unittest.main()
