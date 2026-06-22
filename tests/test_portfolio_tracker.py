# -*- coding: utf-8 -*-
"""portfolio_tracker.py 的 Schema 1.1 最小只读测试。"""

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

import portfolio_tracker


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OLD_PORTFOLIO_FILE = PROJECT_ROOT / "portfolio.json"
CANDIDATE_FILE = PROJECT_ROOT / "portfolio_migrated_candidate.json"


def opening_position(
    transaction_id: str = "txn_test_001",
    symbol: object = "SOFI",
    shares: object = 59,
    price: object = 17.5,
) -> dict:
    return {
        "transaction_id": transaction_id,
        "external_id": None,
        "transaction_type": "OPENING_POSITION",
        "symbol": symbol,
        "shares": shares,
        "price": price,
        "amount": None,
        "fees": 0,
        "executed_at": None,
        "effective_at": "2026-06-22T17:15:41Z",
        "recorded_at": "2026-06-22T17:15:41Z",
        "source": "legacy_migration",
        "note": "测试期初持仓，不代表原始逐笔成交记录。",
    }


def schema_document(transactions: list[dict] | None = None) -> dict:
    return {
        "schema_version": "1.1",
        "account": {
            "account_id": "boundary_test",
            "account_name": "边界测试账户",
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
        "transactions": [] if transactions is None else transactions,
    }


class PortfolioTrackerReadOnlyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.before_contents = {
            OLD_PORTFOLIO_FILE: OLD_PORTFOLIO_FILE.read_bytes(),
            CANDIDATE_FILE: CANDIDATE_FILE.read_bytes(),
        }

    def tearDown(self) -> None:
        for path, expected in self.before_contents.items():
            self.assertTrue(path.is_file(), f"测试过程中数据文件消失：{path}")
            self.assertEqual(
                path.read_bytes(),
                expected,
                f"测试过程中数据文件发生变化：{path}",
            )

    def make_temp_file(self, content: str, filename: str = "portfolio.json") -> Path:
        """在系统临时目录创建隔离文件，并在测试结束时自动清理。"""

        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = Path(temp_dir.name) / filename
        path.write_text(content, encoding="utf-8")
        return path

    def make_temp_json(self, data: dict, filename: str = "portfolio.json") -> Path:
        return self.make_temp_file(
            json.dumps(data, ensure_ascii=False, indent=2), filename=filename
        )

    def run_tracker(self, *arguments: str) -> str:
        """捕获输出，并确保旧联网及保存逻辑没有被调用。"""

        output = io.StringIO()
        argv = ["portfolio_tracker.py", *arguments]
        with (
            patch.object(sys, "argv", argv),
            patch.object(portfolio_tracker, "fetch_prices") as fetch_prices,
            patch.object(portfolio_tracker, "save_portfolio") as save_portfolio,
            patch.object(portfolio_tracker, "save_config") as save_config,
            patch.object(portfolio_tracker, "add_position") as add_position,
            patch.object(portfolio_tracker, "remove_position") as remove_position,
            patch.object(portfolio_tracker, "interactive_add") as interactive_add,
            patch.object(portfolio_tracker, "interactive_config") as interactive_config,
            redirect_stdout(output),
        ):
            portfolio_tracker.main()

        fetch_prices.assert_not_called()
        save_portfolio.assert_not_called()
        save_config.assert_not_called()
        add_position.assert_not_called()
        remove_position.assert_not_called()
        interactive_add.assert_not_called()
        interactive_config.assert_not_called()
        return output.getvalue()

    def test_candidate_displays_schema_positions_costs_and_realized_pnl(self) -> None:
        output = self.run_tracker("--portfolio-file", str(CANDIDATE_FILE))

        self.assertIn("Schema 版本: 1.1", output)
        self.assertIn("持仓数量: 2", output)
        self.assertIn("持仓总成本: $1,436.50", output)
        self.assertIn("追踪期内已实现盈亏: $0.00", output)
        self.assertIn("SOFI", output)
        self.assertIn("SPCX", output)
        self.assertIn("59.0", output)
        self.assertIn("2.0", output)
        self.assertIn("17.50", output)
        self.assertIn("202.00", output)
        self.assertIn("1,032.50", output)
        self.assertIn("404.00", output)

    def test_unknown_cash_is_not_displayed_as_zero(self) -> None:
        output = self.run_tracker("--portfolio-file", str(CANDIDATE_FILE))

        self.assertIn("现金: 未知", output)
        self.assertIn("总资产: 无法计算", output)
        self.assertIn("购买力: 无法计算", output)
        self.assertNotIn("现金: $0.00", output)
        self.assertNotIn("总资产: $0.00", output)
        self.assertNotIn("购买力: $0.00", output)

    def test_old_schema_prints_clear_incompatibility_error(self) -> None:
        output = self.run_tracker("--portfolio-file", str(OLD_PORTFOLIO_FILE))

        self.assertIn("[错误] 持仓数据无法读取", output)
        self.assertIn("不支持 schema_version=None", output)
        self.assertIn("当前只支持 1.1", output)
        self.assertIn("请使用 Schema 1.1 文件", output)

    def test_legacy_operations_are_rejected(self) -> None:
        commands = (
            ("--add",),
            ("--sell", "SOFI"),
            ("--sync",),
            ("--config",),
        )

        for arguments in commands:
            with self.subTest(arguments=arguments):
                output = self.run_tracker(*arguments)
                self.assertIn("[已阻止]", output)
                self.assertIn("仅支持只读查看", output)
                self.assertIn("没有修改任何持仓或配置数据", output)

    def test_json_files_remain_byte_for_byte_unchanged(self) -> None:
        self.run_tracker("--portfolio-file", str(CANDIDATE_FILE))

        for path, expected in self.before_contents.items():
            self.assertEqual(path.read_bytes(), expected)

    def test_formal_portfolio_file_does_not_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "portfolio.json"
            output = self.run_tracker("--portfolio-file", str(missing))

        self.assertIn("[错误] 持仓数据无法读取", output)
        self.assertIn("持仓文件不存在", output)

    def test_candidate_portfolio_file_does_not_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "portfolio_migrated_candidate.json"
            output = self.run_tracker("--portfolio-file", str(missing))

        self.assertIn("[错误] 持仓数据无法读取", output)
        self.assertIn("portfolio_migrated_candidate.json", output)

    def test_formal_and_candidate_files_both_do_not_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            formal = Path(temp_dir) / "portfolio.json"
            candidate = Path(temp_dir) / "portfolio_migrated_candidate.json"
            formal_output = self.run_tracker("--portfolio-file", str(formal))
            candidate_output = self.run_tracker("--portfolio-file", str(candidate))

        for output in (formal_output, candidate_output):
            self.assertIn("[错误] 持仓数据无法读取", output)
            self.assertIn("持仓文件不存在", output)

    def test_empty_file_prints_clear_error(self) -> None:
        output = self.run_tracker(
            "--portfolio-file", str(self.make_temp_file(""))
        )

        self.assertIn("[错误] 持仓数据无法读取", output)
        self.assertIn("不是有效 JSON", output)

    def test_invalid_json_prints_clear_error(self) -> None:
        output = self.run_tracker(
            "--portfolio-file", str(self.make_temp_file('{"schema_version":'))
        )

        self.assertIn("[错误] 持仓数据无法读取", output)
        self.assertIn("不是有效 JSON", output)
        self.assertIn("第 1 行", output)

    def test_empty_positions_are_reported_without_crashing(self) -> None:
        output = self.run_tracker(
            "--portfolio-file", str(self.make_temp_json(schema_document()))
        )

        self.assertIn("持仓数量: 0", output)
        self.assertIn("持仓总成本: $0.00", output)
        self.assertIn("暂无持仓", output)
        self.assertIn("现金: 未知", output)

    def test_missing_required_field_prints_clear_error(self) -> None:
        transaction = opening_position()
        del transaction["shares"]
        output = self.run_tracker(
            "--portfolio-file",
            str(self.make_temp_json(schema_document([transaction]))),
        )

        self.assertIn("[错误] 持仓数据无法读取", output)
        self.assertIn("缺少字段", output)
        self.assertIn("shares", output)

    def test_symbol_whitespace_is_normalized(self) -> None:
        transaction = opening_position(symbol="  SOFI  ")
        path = self.make_temp_json(schema_document([transaction]))

        state = portfolio_tracker.get_portfolio_snapshot(path)
        output = self.run_tracker("--portfolio-file", str(path))

        self.assertEqual(tuple(state.positions), ("SOFI",))
        self.assertIn("SOFI", output)

    def test_symbol_case_is_normalized(self) -> None:
        transaction = opening_position(symbol="sofi")
        state = portfolio_tracker.get_portfolio_snapshot(
            self.make_temp_json(schema_document([transaction]))
        )

        self.assertEqual(state.positions["SOFI"].symbol, "SOFI")
        self.assertNotIn("sofi", state.positions)

    def test_duplicate_symbols_are_merged(self) -> None:
        data = schema_document(
            [
                opening_position("txn_test_001", "SOFI", 2, 10),
                opening_position("txn_test_002", " sofi ", 3, 20),
            ]
        )
        state = portfolio_tracker.get_portfolio_snapshot(self.make_temp_json(data))

        self.assertEqual(tuple(state.positions), ("SOFI",))
        self.assertEqual(state.positions["SOFI"].shares, Decimal("5"))
        self.assertEqual(state.positions["SOFI"].cost_basis, Decimal("80"))
        self.assertEqual(state.positions["SOFI"].avg_cost, Decimal("16"))

    def test_invalid_shares_values_print_clear_error(self) -> None:
        invalid_values = ("59", True, [], -1, 0, None)

        for value in invalid_values:
            with self.subTest(shares=value):
                transaction = opening_position(shares=value)
                output = self.run_tracker(
                    "--portfolio-file",
                    str(self.make_temp_json(schema_document([transaction]))),
                )
                self.assertIn("[错误] 持仓数据无法读取", output)
                self.assertIn("shares", output)

    def test_invalid_average_cost_values_print_clear_error(self) -> None:
        # Schema 1.1 用 transaction.price 重建运行时 average_cost/avg_cost。
        invalid_values = ("17.5", True, [], -1, None)

        for value in invalid_values:
            with self.subTest(average_cost=value):
                transaction = opening_position(price=value)
                output = self.run_tracker(
                    "--portfolio-file",
                    str(self.make_temp_json(schema_document([transaction]))),
                )
                self.assertIn("[错误] 持仓数据无法读取", output)
                self.assertIn("price", output)

    def test_one_invalid_symbol_returns_safely_without_partial_report(self) -> None:
        data = schema_document(
            [
                opening_position("txn_test_001", "SOFI", 2, 10),
                opening_position("txn_test_002", "BAD SYMBOL!", 1, 20),
            ]
        )

        output = self.run_tracker(
            "--portfolio-file", str(self.make_temp_json(data))
        )

        self.assertIn("[错误] 持仓数据无法读取", output)
        self.assertIn("股票代码格式无效", output)
        self.assertNotIn("Schema 1.1 持仓只读报告", output)
        self.assertNotIn("Traceback", output)

    def test_snapshot_return_structure_and_key_fields(self) -> None:
        state = portfolio_tracker.get_portfolio_snapshot(
            self.make_temp_json(
                schema_document([opening_position("txn_test_001", "SOFI", 2, 10)])
            )
        )

        self.assertEqual(state.schema_version, "1.1")
        self.assertEqual(state.cash_status, "unknown")
        self.assertEqual(state.total_cost_basis, Decimal("20"))
        self.assertEqual(state.realized_pnl, Decimal("0"))
        self.assertIsNone(state.cash)
        self.assertIsNone(state.total_equity)
        self.assertIsNone(state.buying_power)
        self.assertFalse(state.prices_complete)
        self.assertEqual(state.positions["SOFI"].shares, Decimal("2"))
        self.assertEqual(state.positions["SOFI"].avg_cost, Decimal("10"))

    def test_each_legacy_argument_remains_rejected_before_file_loading(self) -> None:
        commands = (
            ("--add",),
            ("--sell", "SOFI"),
            ("--sync",),
            ("--config",),
        )

        for arguments in commands:
            with self.subTest(arguments=arguments):
                with patch.object(
                    portfolio_tracker, "get_portfolio_snapshot"
                ) as get_snapshot:
                    output = self.run_tracker(*arguments)
                get_snapshot.assert_not_called()
                self.assertIn("[已阻止]", output)
                self.assertIn("仅支持只读查看", output)
                self.assertIn("没有访问网络", output)
                self.assertIn("没有修改任何持仓或配置数据", output)


if __name__ == "__main__":
    unittest.main()
