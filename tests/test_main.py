# -*- coding: utf-8 -*-
"""main.py 的 Schema 1.1 持仓概览接入测试。"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import main


def schema_document() -> dict:
    return {
        "schema_version": "1.1",
        "account": {
            "account_id": "main_test",
            "account_name": "主程序测试账户",
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
                "transaction_id": "txn_main_001",
                "external_id": None,
                "transaction_type": "OPENING_POSITION",
                "symbol": " sofi ",
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


class MainPortfolioOverviewTests(unittest.TestCase):
    def make_portfolio_file(self) -> tuple[tempfile.TemporaryDirectory, Path]:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = Path(temp_dir.name) / "portfolio.json"
        path.write_text(
            json.dumps(schema_document(), ensure_ascii=False), encoding="utf-8"
        )
        return temp_dir, path

    def run_main(self, *arguments: str) -> str:
        output = io.StringIO()
        with patch.object(sys, "argv", ["main.py", *arguments]), redirect_stdout(output):
            main.main()
        return output.getvalue()

    def test_portfolio_command_outputs_summary_and_positions(self) -> None:
        _, path = self.make_portfolio_file()

        output = self.run_main("portfolio", "--portfolio-file", str(path))

        self.assertIn("持仓概览（Schema 1.1，只读）", output)
        self.assertIn("持仓数量: 1", output)
        self.assertIn("持仓总成本: $20.00", output)
        self.assertIn("SOFI", output)
        self.assertIn("$       10.00", output)
        self.assertIn("现金: 未知", output)
        self.assertNotIn("现金: $0.00", output)

    def test_portfolio_command_calls_service_without_subprocess_or_network(self) -> None:
        _, path = self.make_portfolio_file()

        with (
            patch.object(main, "get_portfolio_snapshot", wraps=main.get_portfolio_snapshot) as service,
            patch.object(main, "run_script") as run_script,
            patch.object(main.subprocess, "run") as subprocess_run,
            patch.object(main, "YFinancePriceProvider") as provider_class,
        ):
            output = self.run_main("portfolio", "--portfolio-file", str(path))

        service.assert_called_once_with(str(path))
        run_script.assert_not_called()
        subprocess_run.assert_not_called()
        provider_class.assert_not_called()
        self.assertIn("未访问网络", output)

    def test_missing_file_returns_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.json"
            output = self.run_main("portfolio", "--portfolio-file", str(missing))

        self.assertIn("[错误] 持仓概览无法读取", output)
        self.assertIn("持仓文件不存在", output)
        self.assertNotIn("Traceback", output)

    def test_legacy_portfolio_operations_remain_blocked(self) -> None:
        for arguments in (("--add",), ("--sell", "SOFI"), ("--sync",), ("--config",)):
            with self.subTest(arguments=arguments):
                with patch.object(main, "get_portfolio_snapshot") as service:
                    output = self.run_main("portfolio", *arguments)
                service.assert_not_called()
                self.assertIn("[已阻止]", output)
                self.assertIn("没有连接券商、访问网络或修改持仓文件", output)

    def test_portfolio_with_price_fetches_quotes_and_outputs_market_values(self) -> None:
        _, path = self.make_portfolio_file()

        class FakeProvider:
            def get_quote(self, symbol: str) -> main.PriceQuote:
                self.requested_symbol = symbol
                return main.PriceQuote(
                    symbol=symbol,
                    price=Decimal("12.50"),
                    previous_close=Decimal("12.00"),
                    source="fake",
                    price_as_of="2026-06-23T15:30:00Z",
                )

        provider = FakeProvider()
        with patch.object(main, "YFinancePriceProvider", return_value=provider):
            output = self.run_main("portfolio", "--portfolio-file", str(path), "--with-price")

        self.assertEqual(provider.requested_symbol, "SOFI")
        self.assertIn("当前价格", output)
        self.assertIn("当前市值", output)
        self.assertIn("未实现盈亏", output)
        self.assertIn("盈亏率", output)
        self.assertIn("fake", output)
        self.assertIn("2026-06-23T15:30:00Z", output)
        self.assertIn("$12.50", output)
        self.assertIn("$25.00", output)
        self.assertIn("$5.00", output)
        self.assertIn("+25.00%", output)
        self.assertIn("已按 --with-price 请求行情", output)
        self.assertNotIn("未访问网络", output)

    def test_portfolio_with_price_keeps_positions_when_quote_fails(self) -> None:
        _, path = self.make_portfolio_file()

        class FailingProvider:
            def get_quote(self, symbol: str) -> main.PriceQuote:
                raise main.PriceProviderError("fake failure")

        with patch.object(main, "YFinancePriceProvider", return_value=FailingProvider()):
            output = self.run_main("portfolio", "--portfolio-file", str(path), "--with-price")

        self.assertIn("SOFI", output)
        self.assertIn("$       10.00", output)
        self.assertIn("价格未知", output)
        self.assertIn("[行情提示] SOFI 行情获取失败：fake failure", output)
        self.assertNotIn("Traceback", output)

    def test_monitor_alert_routes_to_monitor_script(self) -> None:
        with patch.object(main, "run_script") as run_script:
            self.run_main("monitor", "--alert")

        run_script.assert_called_once_with(
            "monitor.py",
            ["--portfolio-file", str(main.DEFAULT_SCHEMA_PORTFOLIO_FILE), "--alert"],
        )

    def test_daily_report_outputs_summary_positions_alerts_and_focus_items(self) -> None:
        _, path = self.make_portfolio_file()

        class FakeProvider:
            def get_quote(self, symbol: str) -> main.PriceQuote:
                return main.PriceQuote(
                    symbol=symbol,
                    price=Decimal("12.50"),
                    previous_close=Decimal("12.00"),
                    source="fake",
                    price_as_of="2026-06-23T15:30:00Z",
                )

        with (
            patch.object(main, "YFinancePriceProvider", return_value=FakeProvider()) as provider_class,
            patch.object(main, "run_script") as run_script,
            patch.object(main.subprocess, "run") as subprocess_run,
        ):
            output = self.run_main("report", "--daily", "--portfolio-file", str(path))

        provider_class.assert_called_once()
        run_script.assert_not_called()
        subprocess_run.assert_not_called()
        self.assertIn("每日持仓报告", output)
        self.assertIn("[账户摘要]", output)
        self.assertIn("当前市值: $25.00", output)
        self.assertIn("未实现盈亏: $5.00", output)
        self.assertIn("盈亏率: +25.00%", output)
        self.assertIn("[当前持仓列表]", output)
        self.assertIn("SOFI", output)
        self.assertIn("$12.50", output)
        self.assertIn("[止盈/止损预警摘要]", output)
        self.assertIn("达到止盈: SOFI +25.00%", output)
        self.assertIn("达到止损: 无", output)
        self.assertIn("[今日关注事项]", output)
        self.assertIn("收益管理", output)
        self.assertIn("只读日报：未修改文件，未连接券商，未自动交易", output)

    def test_daily_report_keeps_running_when_price_fetch_fails(self) -> None:
        _, path = self.make_portfolio_file()

        class FailingProvider:
            def get_quote(self, symbol: str) -> main.PriceQuote:
                raise main.PriceProviderError("fake failure")

        with patch.object(main, "YFinancePriceProvider", return_value=FailingProvider()):
            output = self.run_main("report", "--daily", "--portfolio-file", str(path))

        self.assertIn("每日持仓报告", output)
        self.assertIn("SOFI", output)
        self.assertIn("价格未知", output)
        self.assertIn("行情检查: SOFI 行情获取失败：fake failure", output)
        self.assertIn("只读日报", output)
        self.assertNotIn("Traceback", output)

    def test_report_without_daily_prints_usage_hint(self) -> None:
        output = self.run_main("report")

        self.assertIn("请使用: python main.py report --daily", output)

    def test_screener_routes_to_screener_script(self) -> None:
        with patch.object(main, "run_script") as run_script:
            self.run_main("screener")

        run_script.assert_called_once_with("screener.py")


if __name__ == "__main__":
    unittest.main()
