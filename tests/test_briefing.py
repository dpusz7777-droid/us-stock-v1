# -*- coding: utf-8 -*-
"""briefing 统一简报测试。"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from decimal import Decimal
from pathlib import Path

from briefing import show_briefing
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


if __name__ == "__main__":
    unittest.main()
