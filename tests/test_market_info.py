# -*- coding: utf-8 -*-
"""news / earnings 只读模块测试。"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from market_info import (
    build_earnings_rows,
    collect_focus_symbols,
    fetch_news_rows,
    NewsProviderError,
    NewsRow,
    print_earnings_rows,
    print_news_rows,
    show_earnings_overview,
    show_news_overview,
    YahooFinanceNewsProvider,
)


def schema_document() -> dict:
    return {
        "schema_version": "1.1",
        "account": {
            "account_id": "news_test",
            "account_name": "新闻测试账户",
            "broker": "test",
            "base_currency": "USD",
            "cash_status": "unknown",
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
                "transaction_id": "txn_news_001",
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


class MarketInfoTests(unittest.TestCase):
    def make_files(
        self,
        watchlist: dict | None = None,
    ) -> tuple[tempfile.TemporaryDirectory, Path, Path]:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        portfolio_path = root / "portfolio_migrated_candidate.json"
        watchlist_path = root / "watchlist.json"
        portfolio_path.write_text(
            json.dumps(schema_document(), ensure_ascii=False), encoding="utf-8"
        )
        watchlist_path.write_text(
            json.dumps(
                watchlist or {"symbols": [" NVDA ", "sofi", "AAPL", "NVDA"]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return temp_dir, portfolio_path, watchlist_path

    def test_collect_focus_symbols_merges_portfolio_and_watchlist(self) -> None:
        _, portfolio_path, watchlist_path = self.make_files()

        symbols, warnings = collect_focus_symbols(portfolio_path, watchlist_path)

        self.assertEqual(symbols, ["SOFI", "NVDA", "AAPL"])
        self.assertEqual(warnings, ())

    def test_collect_focus_symbols_warns_for_bad_watchlist_without_crashing(self) -> None:
        _, portfolio_path, watchlist_path = self.make_files({"items": ["NVDA"]})

        symbols, warnings = collect_focus_symbols(portfolio_path, watchlist_path)

        self.assertEqual(symbols, ["SOFI"])
        self.assertTrue(any("watchlist 格式错误" in warning for warning in warnings))

    def test_yahoo_news_provider_parses_legacy_yfinance_items(self) -> None:
        class FakeTicker:
            news = [
                {
                    "title": "Nvidia headline",
                    "publisher": "Yahoo Finance",
                    "providerPublishTime": 1782057600,
                    "link": "https://finance.yahoo.com/news/nvda",
                }
            ]

        provider = YahooFinanceNewsProvider(ticker_factory=lambda symbol: FakeTicker())

        rows = provider.get_news(" nvda ")

        self.assertEqual(rows[0].symbol, "NVDA")
        self.assertEqual(rows[0].title, "Nvidia headline")
        self.assertEqual(rows[0].publisher, "Yahoo Finance")
        self.assertEqual(rows[0].published_at, "2026-06-21T16:00:00Z")
        self.assertEqual(rows[0].link, "https://finance.yahoo.com/news/nvda")

    def test_yahoo_news_provider_parses_content_yfinance_items(self) -> None:
        class FakeTicker:
            news = [
                {
                    "content": {
                        "title": "Apple headline",
                        "provider": {"displayName": "Reuters"},
                        "pubDate": "2026-06-23T12:30:00Z",
                        "canonicalUrl": {"url": "https://finance.yahoo.com/news/aapl"},
                    }
                }
            ]

        provider = YahooFinanceNewsProvider(ticker_factory=lambda symbol: FakeTicker())

        rows = provider.get_news("AAPL")

        self.assertEqual(rows[0].symbol, "AAPL")
        self.assertEqual(rows[0].title, "Apple headline")
        self.assertEqual(rows[0].publisher, "Reuters")
        self.assertEqual(rows[0].published_at, "2026-06-23T12:30:00Z")
        self.assertEqual(rows[0].link, "https://finance.yahoo.com/news/aapl")

    def test_fetch_news_rows_returns_three_news_per_symbol(self) -> None:
        class FakeProvider:
            def get_news(self, symbol: str, limit: int = 3) -> list[NewsRow]:
                return [
                    NewsRow(
                        symbol=symbol,
                        title=f"{symbol} title {index}",
                        publisher="Yahoo Finance",
                        published_at="2026-06-23T12:30:00Z",
                        link=f"https://example.com/{symbol}/{index}",
                    )
                    for index in range(1, 5)
                ][:limit]

        rows, warnings = fetch_news_rows(["NVDA", "AAPL"], provider=FakeProvider())

        self.assertEqual(len(rows), 6)
        self.assertEqual([row.symbol for row in rows[:3]], ["NVDA", "NVDA", "NVDA"])
        self.assertEqual([row.symbol for row in rows[3:]], ["AAPL", "AAPL", "AAPL"])
        self.assertEqual(warnings, ())

    def test_fetch_news_rows_keeps_running_when_one_symbol_fails(self) -> None:
        class PartialProvider:
            def get_news(self, symbol: str, limit: int = 3) -> list[NewsRow]:
                if symbol == "SOFI":
                    raise NewsProviderError("fake network failure")
                return [
                    NewsRow(
                        symbol=symbol,
                        title="Nvidia headline",
                        publisher="Yahoo Finance",
                        published_at="2026-06-23T12:30:00Z",
                        link="https://example.com/nvda",
                    )
                ]

        rows, warnings = fetch_news_rows(["SOFI", "NVDA"], provider=PartialProvider())

        self.assertEqual([row.symbol for row in rows], ["NVDA"])
        self.assertTrue(any("SOFI 新闻获取失败" in warning for warning in warnings))

    def test_build_earnings_rows_returns_required_mock_fields(self) -> None:
        rows = build_earnings_rows(["NVDA", "UNKNOWN"])

        self.assertEqual(rows[0].symbol, "NVDA")
        self.assertEqual(rows[0].earnings_date, "TBD")
        self.assertEqual(rows[0].importance, "high")
        self.assertIn("AI", rows[0].note)
        self.assertEqual(rows[1].symbol, "UNKNOWN")
        self.assertEqual(rows[1].importance, "medium")

    def test_print_news_rows_outputs_read_only_notice(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            print_news_rows(
                [
                    NewsRow(
                        symbol="AAPL",
                        title="Apple headline",
                        publisher="Yahoo Finance",
                        published_at="2026-06-23T12:30:00Z",
                        link="https://example.com/aapl",
                    )
                ]
            )

        text = output.getvalue()
        self.assertIn("Yahoo Finance 股票新闻", text)
        self.assertIn("symbol", text)
        self.assertIn("title", text)
        self.assertIn("publisher", text)
        self.assertIn("published_at", text)
        self.assertIn("https://example.com/aapl", text)
        self.assertIn("只读新闻：未修改文件，未连接券商，未自动交易", text)

    def test_print_earnings_rows_outputs_read_only_notice(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            print_earnings_rows(build_earnings_rows(["AAPL"]))

        text = output.getvalue()
        self.assertIn("未来财报关注列表", text)
        self.assertIn("earnings_date", text)
        self.assertIn("importance", text)
        self.assertIn("只读财报：未修改文件，未连接券商，未自动交易", text)

    def test_show_functions_do_not_modify_json_files(self) -> None:
        _, portfolio_path, watchlist_path = self.make_files()
        before = {
            portfolio_path: portfolio_path.read_bytes(),
            watchlist_path: watchlist_path.read_bytes(),
        }

        class FakeProvider:
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

        with redirect_stdout(io.StringIO()):
            self.assertTrue(
                show_news_overview(
                    portfolio_path,
                    watchlist_path,
                    provider=FakeProvider(),
                )
            )
            self.assertTrue(show_earnings_overview(portfolio_path, watchlist_path))

        self.assertEqual(portfolio_path.read_bytes(), before[portfolio_path])
        self.assertEqual(watchlist_path.read_bytes(), before[watchlist_path])


if __name__ == "__main__":
    unittest.main()
