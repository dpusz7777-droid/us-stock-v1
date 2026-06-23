# -*- coding: utf-8 -*-
"""screener.py 单元测试。"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from decimal import Decimal
from pathlib import Path

import screener
from price_provider import PriceProviderError, PriceQuote


class FakeProvider:
    def __init__(self, quotes: dict[str, PriceQuote]):
        self.quotes = quotes
        self.requested: list[str] = []

    def get_quote(self, symbol: str) -> PriceQuote:
        self.requested.append(symbol)
        if symbol == "FAIL":
            raise PriceProviderError("fake failure")
        return self.quotes[symbol]


class ScreenerTests(unittest.TestCase):
    def make_quote(
        self,
        symbol: str,
        price: str,
        previous_close: str,
    ) -> PriceQuote:
        return PriceQuote(
            symbol=symbol,
            price=Decimal(price),
            previous_close=Decimal(previous_close),
            source="fake",
            price_as_of="2026-06-23T15:30:00Z",
        )

    def test_screen_stocks_returns_required_fields_and_sorts_large_moves(self) -> None:
        provider = FakeProvider(
            {
                "UP": self.make_quote("UP", "105", "100"),
                "DOWN": self.make_quote("DOWN", "94", "100"),
                "FLAT": self.make_quote("FLAT", "100.5", "100"),
            }
        )

        rows = screener.screen_stocks(["flat", "up", "down"], provider=provider)

        self.assertEqual(provider.requested, ["FLAT", "UP", "DOWN"])
        self.assertEqual([row.symbol for row in rows], ["DOWN", "UP", "FLAT"])
        self.assertEqual(rows[0].price, Decimal("94"))
        self.assertEqual(rows[0].previous_close, Decimal("100"))
        self.assertEqual(rows[0].change_pct, Decimal("-6.00"))
        self.assertIn("跌幅较大", rows[0].reason)
        self.assertIn("波动较大", rows[0].risk_note)
        self.assertEqual(rows[0].source, "fake")
        self.assertEqual(rows[1].change_pct, Decimal("5.00"))
        self.assertIn("涨幅较大", rows[1].reason)
        self.assertEqual(rows[2].change_pct, Decimal("0.500"))
        self.assertIn("持续观察", rows[2].reason)

    def test_screen_stocks_keeps_failed_quotes_without_crashing(self) -> None:
        provider = FakeProvider({"OK": self.make_quote("OK", "101", "100")})

        rows = screener.screen_stocks(["OK", "FAIL"], provider=provider)

        failed = next(row for row in rows if row.symbol == "FAIL")
        self.assertIsNone(failed.price)
        self.assertIsNone(failed.previous_close)
        self.assertIsNone(failed.change_pct)
        self.assertIn("行情获取失败", failed.reason)
        self.assertIn("fake failure", failed.risk_note)
        self.assertEqual(failed.source, "unknown")

    def test_normalize_symbols_strips_uppercases_and_deduplicates(self) -> None:
        symbols, warnings = screener.normalize_symbols(
            [" nvda ", "NVDA", "pltr", "", 123]
        )

        self.assertEqual(symbols, ["NVDA", "PLTR"])
        self.assertEqual(len(warnings), 2)
        self.assertIn("非法 symbol", warnings[0])

    def test_load_watchlist_symbols_from_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "watchlist.json"
            path.write_text(
                json.dumps({"symbols": [" nvda ", "pltr", "NVDA", "sofi"]}),
                encoding="utf-8",
            )

            symbols, warnings = screener.load_watchlist_symbols(path)

        self.assertEqual(symbols, ["NVDA", "PLTR", "SOFI"])
        self.assertEqual(warnings, ())

    def test_resolve_candidate_symbols_falls_back_for_missing_watchlist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.json"

            symbols, warnings = screener.resolve_candidate_symbols(
                missing,
                fallback_symbols=["NVDA", "AAPL"],
            )

        self.assertEqual(symbols, ["NVDA", "AAPL"])
        self.assertIn("watchlist 不存在", warnings[0])

    def test_resolve_candidate_symbols_falls_back_for_invalid_format(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "watchlist.json"
            path.write_text(json.dumps({"bad": ["NVDA"]}), encoding="utf-8")

            symbols, warnings = screener.resolve_candidate_symbols(
                path,
                fallback_symbols=["NVDA"],
            )

        self.assertEqual(symbols, ["NVDA"])
        self.assertIn("watchlist 格式错误", warnings[0])
        self.assertIn("symbols 数组", warnings[0])

    def test_print_screener_results_outputs_today_watchlist(self) -> None:
        rows = [
            screener.ScreenerRow(
                symbol="UP",
                price=Decimal("105"),
                previous_close=Decimal("100"),
                change_pct=Decimal("5"),
                reason="当日涨幅较大，可能有资金关注或消息催化，需人工复核。",
                risk_note="第一版筛选仅基于价格异动，不构成投资建议。",
                source="fake",
            )
        ]

        output = io.StringIO()
        with redirect_stdout(output):
            screener.print_screener_results(rows)

        text = output.getvalue()
        self.assertIn("今日关注股票列表", text)
        self.assertIn("symbol", text)
        self.assertIn("price", text)
        self.assertIn("previous_close", text)
        self.assertIn("change_pct", text)
        self.assertIn("reason", text)
        self.assertIn("risk_note", text)
        self.assertIn("source", text)
        self.assertIn("UP", text)
        self.assertIn("+5.00%", text)
        self.assertIn("只读筛选：未修改文件，未连接券商，未自动交易", text)


if __name__ == "__main__":
    unittest.main()
