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
import market_info


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

    def make_portfolio_file_from_document(
        self, data: dict
    ) -> tuple[tempfile.TemporaryDirectory, Path]:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = Path(temp_dir.name) / "portfolio.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return temp_dir, path

    def make_candidate_with_legacy_cash(
        self, legacy_cash: float = 2000.0
    ) -> tuple[tempfile.TemporaryDirectory, Path]:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        candidate_path = root / "portfolio_migrated_candidate.json"
        candidate_path.write_text(
            json.dumps(schema_document(), ensure_ascii=False), encoding="utf-8"
        )
        (root / "portfolio.json").write_text(
            json.dumps({"positions": [], "cash": legacy_cash}, ensure_ascii=False),
            encoding="utf-8",
        )
        return temp_dir, candidate_path

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

    def test_portfolio_with_price_uses_legacy_cash_for_total_equity(self) -> None:
        _, path = self.make_candidate_with_legacy_cash(legacy_cash=100.0)

        class FakeProvider:
            def get_quote(self, symbol: str) -> main.PriceQuote:
                return main.PriceQuote(
                    symbol=symbol,
                    price=Decimal("12.50"),
                    previous_close=Decimal("12.00"),
                    source="fake",
                    price_as_of="2026-06-23T15:30:00Z",
                )

        with patch.object(main, "YFinancePriceProvider", return_value=FakeProvider()):
            output = self.run_main("portfolio", "--portfolio-file", str(path), "--with-price")

        self.assertIn("现金: $100.00", output)
        self.assertIn("总资产: $125.00", output)

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

    def test_dashboard_outputs_local_portfolio_and_recent_reports(self) -> None:
        data = schema_document()
        data["account"]["cash_status"] = "known"
        data["account"]["cash"] = 100
        data["account"]["buying_power"] = 80
        _, path = self.make_portfolio_file_from_document(data)

        class FakeProvider:
            def get_quote(self, symbol: str) -> main.PriceQuote:
                return main.PriceQuote(
                    symbol=symbol,
                    price=Decimal("12.50"),
                    previous_close=Decimal("12.00"),
                    source="fake",
                    price_as_of="2026-06-24T12:00:00Z",
                )

        with (
            patch.object(main, "YFinancePriceProvider", return_value=FakeProvider()),
            patch.object(
                main,
                "recent_reports",
                return_value=[
                    {
                        "date": "2026-06-24",
                        "type": "sync",
                        "file_path": "reports/2026-06-24-sync.md",
                    }
                ],
            ),
        ):
            output = self.run_main("dashboard", "--portfolio-file", str(path))

        self.assertIn("本地投资助手 Dashboard", output)
        self.assertIn("最新持仓", output)
        self.assertIn("SOFI", output)
        self.assertIn("现金: $100.00", output)
        self.assertIn("今日盈亏", output)
        self.assertIn("reports/2026-06-24-sync.md", output)
        self.assertIn("未连接券商，未自动交易，未下单", output)

    def test_doctor_outputs_health_checks_without_network(self) -> None:
        with (
            patch.object(main, "_check_excel_latest", return_value=(True, "excel ok")),
            patch.object(main, "_check_portfolio_synced", return_value=(True, "sync ok")),
            patch.object(main, "_check_json_valid", return_value=(True, "json ok")),
            patch.object(main, "_check_tests_pass", return_value=(True, "tests ok")),
        ):
            output = self.run_main(
                "doctor",
                "--portfolio-file",
                "portfolio_migrated_candidate.json",
                "--excel",
                "position-information-20260623.xlsx",
            )

        self.assertIn("System Doctor", output)
        self.assertIn("[OK] Excel 是否最新: excel ok", output)
        self.assertIn("[OK] portfolio 是否同步: sync ok", output)
        self.assertIn("[OK] JSON 是否损坏: json ok", output)
        self.assertIn("[OK] tests 是否通过: tests ok", output)

    def test_doctor_skip_tests_does_not_run_unittest(self) -> None:
        with (
            patch.object(main, "_check_excel_latest", return_value=(True, "excel ok")),
            patch.object(main, "_check_portfolio_synced", return_value=(True, "sync ok")),
            patch.object(main, "_check_json_valid", return_value=(True, "json ok")),
            patch.object(main, "_check_tests_pass") as check_tests,
        ):
            output = self.run_main("doctor", "--skip-tests")

        check_tests.assert_not_called()
        self.assertNotIn("tests 是否通过", output)

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

    def test_daily_report_outputs_cash_buying_power_and_allocation(self) -> None:
        data = schema_document()
        data["account"]["cash_status"] = "known"
        data["account"]["cash"] = 100
        data["account"]["buying_power"] = 80
        _, path = self.make_portfolio_file_from_document(data)

        class FakeProvider:
            def get_quote(self, symbol: str) -> main.PriceQuote:
                return main.PriceQuote(
                    symbol=symbol,
                    price=Decimal("12.50"),
                    previous_close=Decimal("12.00"),
                    source="fake",
                    price_as_of="2026-06-23T15:30:00Z",
                )

        with patch.object(main, "YFinancePriceProvider", return_value=FakeProvider()):
            output = self.run_main("report", "--daily", "--portfolio-file", str(path))

        self.assertIn("现金: $100.00", output)
        self.assertIn("总资产: $125.00", output)
        self.assertIn("购买力: $80.00", output)
        self.assertIn("仓位占比", output)
        self.assertIn("+20.00%", output)

    def test_daily_report_uses_legacy_cash_when_account_cash_is_missing(self) -> None:
        _, path = self.make_candidate_with_legacy_cash(legacy_cash=100.0)

        class FakeProvider:
            def get_quote(self, symbol: str) -> main.PriceQuote:
                return main.PriceQuote(
                    symbol=symbol,
                    price=Decimal("12.50"),
                    previous_close=Decimal("12.00"),
                    source="fake",
                    price_as_of="2026-06-23T15:30:00Z",
                )

        with patch.object(main, "YFinancePriceProvider", return_value=FakeProvider()):
            output = self.run_main("report", "--daily", "--portfolio-file", str(path))

        self.assertIn("现金: $100.00", output)
        self.assertIn("总资产: $125.00", output)
        self.assertIn("购买力: $100.00", output)
        self.assertIn("+20.00%", output)

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

        run_script.assert_called_once_with("screener.py", [])

    def test_screener_watchlist_argument_routes_to_screener_script(self) -> None:
        with patch.object(main, "run_script") as run_script:
            self.run_main("screener", "--watchlist", "watchlist.json")

        run_script.assert_called_once_with(
            "screener.py",
            ["--watchlist", "watchlist.json"],
        )

    def test_news_command_outputs_yahoo_rows_without_subprocess(self) -> None:
        _, portfolio_path = self.make_portfolio_file()
        watchlist_path = portfolio_path.with_name("watchlist.json")
        watchlist_path.write_text(
            json.dumps({"symbols": ["NVDA", "AAPL"]}, ensure_ascii=False),
            encoding="utf-8",
        )

        class FakeNewsProvider:
            def get_news(
                self, symbol: str, limit: int = 3
            ) -> list[market_info.NewsRow]:
                return [
                    market_info.NewsRow(
                        symbol=symbol,
                        title=f"{symbol} headline {index}",
                        publisher="Yahoo Finance",
                        published_at="2026-06-23T12:30:00Z",
                        link=f"https://example.com/{symbol.lower()}/{index}",
                    )
                    for index in range(1, limit + 1)
                ]

        with (
            patch.object(main, "run_script") as run_script,
            patch.object(main.subprocess, "run") as subprocess_run,
            patch.object(main, "YFinancePriceProvider") as provider_class,
            patch.object(
                market_info,
                "YahooFinanceNewsProvider",
                return_value=FakeNewsProvider(),
            ) as news_provider_class,
        ):
            output = self.run_main(
                "news",
                "--portfolio-file",
                str(portfolio_path),
                "--watchlist",
                str(watchlist_path),
            )

        run_script.assert_not_called()
        subprocess_run.assert_not_called()
        provider_class.assert_not_called()
        news_provider_class.assert_called_once()
        self.assertIn("Yahoo Finance 股票新闻", output)
        self.assertIn("SOFI", output)
        self.assertIn("NVDA", output)
        self.assertIn("title", output)
        self.assertIn("publisher", output)
        self.assertIn("https://example.com/nvda/1", output)
        self.assertIn("只读新闻：未修改文件，未连接券商，未自动交易", output)

    def test_earnings_command_outputs_mock_rows_without_subprocess(self) -> None:
        _, portfolio_path = self.make_portfolio_file()
        watchlist_path = portfolio_path.with_name("watchlist.json")
        watchlist_path.write_text(
            json.dumps({"symbols": ["NVDA", "AAPL"]}, ensure_ascii=False),
            encoding="utf-8",
        )

        with (
            patch.object(main, "run_script") as run_script,
            patch.object(main.subprocess, "run") as subprocess_run,
            patch.object(main, "YFinancePriceProvider") as provider_class,
        ):
            output = self.run_main(
                "earnings",
                "--portfolio-file",
                str(portfolio_path),
                "--watchlist",
                str(watchlist_path),
            )

        run_script.assert_not_called()
        subprocess_run.assert_not_called()
        provider_class.assert_not_called()
        self.assertIn("未来财报关注列表", output)
        self.assertIn("SOFI", output)
        self.assertIn("NVDA", output)
        self.assertIn("earnings_date", output)
        self.assertIn("只读财报：未修改文件，未连接券商，未自动交易", output)

    def test_briefing_command_routes_to_unified_briefing(self) -> None:
        with patch.object(main, "show_briefing", return_value=True) as show_briefing:
            self.run_main(
                "briefing",
                "--portfolio-file",
                "portfolio_migrated_candidate.json",
                "--watchlist",
                "watchlist.json",
            )

        show_briefing.assert_called_once_with(
            "portfolio_migrated_candidate.json",
            "watchlist.json",
        )

    def test_briefing_ai_command_routes_to_ai_briefing(self) -> None:
        with patch.object(
            main,
            "show_ai_briefing",
            return_value=True,
        ) as show_ai_briefing:
            self.run_main(
                "briefing",
                "--ai",
                "--portfolio-file",
                "portfolio_migrated_candidate.json",
                "--watchlist",
                "watchlist.json",
            )

        show_ai_briefing.assert_called_once_with(
            "portfolio_migrated_candidate.json",
            "watchlist.json",
            save_report=False,
        )

    def test_briefing_ai_save_command_routes_to_ai_briefing_save(self) -> None:
        with patch.object(
            main,
            "show_ai_briefing",
            return_value=True,
        ) as show_ai_briefing:
            self.run_main(
                "briefing",
                "--ai",
                "--save",
                "--portfolio-file",
                "portfolio_migrated_candidate.json",
                "--watchlist",
                "watchlist.json",
            )

        show_ai_briefing.assert_called_once_with(
            "portfolio_migrated_candidate.json",
            "watchlist.json",
            save_report=True,
        )

    def test_morning_command_routes_to_morning_briefing(self) -> None:
        with patch.object(
            main,
            "show_morning_briefing",
            return_value=True,
        ) as show_morning:
            self.run_main(
                "morning",
                "--portfolio-file",
                "portfolio_migrated_candidate.json",
                "--watchlist",
                "watchlist.json",
            )

        show_morning.assert_called_once_with(
            "portfolio_migrated_candidate.json",
            "watchlist.json",
            save_report=False,
        )

    def test_morning_save_command_routes_to_morning_briefing_save(self) -> None:
        with patch.object(
            main,
            "show_morning_briefing",
            return_value=True,
        ) as show_morning:
            self.run_main(
                "morning",
                "--save",
                "--portfolio-file",
                "portfolio_migrated_candidate.json",
                "--watchlist",
                "watchlist.json",
            )

        show_morning.assert_called_once_with(
            "portfolio_migrated_candidate.json",
            "watchlist.json",
            save_report=True,
        )

    def test_evening_command_routes_to_evening_briefing(self) -> None:
        with patch.object(
            main,
            "show_evening_briefing",
            return_value=True,
        ) as show_evening:
            self.run_main(
                "evening",
                "--portfolio-file",
                "portfolio_migrated_candidate.json",
                "--watchlist",
                "watchlist.json",
            )

        show_evening.assert_called_once_with(
            "portfolio_migrated_candidate.json",
            "watchlist.json",
            save_report=False,
        )

    def test_evening_save_command_routes_to_evening_briefing_save(self) -> None:
        with patch.object(
            main,
            "show_evening_briefing",
            return_value=True,
        ) as show_evening:
            self.run_main(
                "evening",
                "--save",
                "--portfolio-file",
                "portfolio_migrated_candidate.json",
                "--watchlist",
                "watchlist.json",
            )

        show_evening.assert_called_once_with(
            "portfolio_migrated_candidate.json",
            "watchlist.json",
            save_report=True,
        )

    def test_sync_usmart_command_imports_excel_and_prints_summary(self) -> None:
        class FakePosition:
            symbol = "NVDA"
            shares = Decimal("1")
            avg_cost = Decimal("202.15")

        with patch.object(
            main,
            "sync_usmart_excel",
            return_value=([FakePosition()], Path("backup.json"), Path("sync.md")),
        ) as sync_usmart:
            output = self.run_main(
                "sync-usmart",
                "--excel",
                "position.xlsx",
                "--portfolio-file",
                "portfolio_migrated_candidate.json",
                "--cash",
                "2688.96",
                "--buying-power",
                "7585.18",
            )

        sync_usmart.assert_called_once_with(
            "position.xlsx",
            "portfolio_migrated_candidate.json",
            cash=Decimal("2688.96"),
            buying_power=Decimal("7585.18"),
            legacy_portfolio_path=main.ROOT / "portfolio.json",
            reports_dir=main.ROOT / "reports",
        )
        self.assertIn("uSMART 持仓导入完成", output)
        self.assertIn("NVDA", output)
        self.assertIn("$2,688.96", output)
        self.assertIn("同步报告", output)

    def test_sync_usmart_no_legacy_sync_skips_legacy_file(self) -> None:
        with patch.object(
            main,
            "sync_usmart_excel",
            return_value=([], Path("backup.json"), Path("sync.md")),
        ) as sync_usmart:
            self.run_main(
                "sync-usmart",
                "--excel",
                "position.xlsx",
                "--portfolio-file",
                "portfolio_migrated_candidate.json",
                "--no-legacy-sync",
            )

        self.assertIsNone(sync_usmart.call_args.kwargs["legacy_portfolio_path"])


if __name__ == "__main__":
    unittest.main()
