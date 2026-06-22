# -*- coding: utf-8 -*-
"""main.py 的 Schema 1.1 持仓概览接入测试。"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
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
        ):
            output = self.run_main("portfolio", "--portfolio-file", str(path))

        service.assert_called_once_with(str(path))
        run_script.assert_not_called()
        subprocess_run.assert_not_called()
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


if __name__ == "__main__":
    unittest.main()
