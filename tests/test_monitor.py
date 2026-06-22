# -*- coding: utf-8 -*-
"""monitor.py 的 Schema 1.1 最小只读测试。

测试不访问网络、不调用 yfinance，并在每个测试前后逐字节核对两份 JSON。
"""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import monitor


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OLD_PORTFOLIO_FILE = PROJECT_ROOT / "portfolio.json"
CANDIDATE_FILE = PROJECT_ROOT / "portfolio_migrated_candidate.json"


class MonitorReadOnlyTests(unittest.TestCase):
    """验证 monitor 的候选读取、错误提示和旧写入拦截。"""

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

    def run_monitor(self, *arguments: str) -> str:
        """运行 monitor.main 并捕获输出，同时禁止调用旧网络与写入函数。"""

        output = io.StringIO()
        argv = ["monitor.py", *arguments]
        with (
            patch.object(sys, "argv", argv),
            patch.object(monitor, "fetch_prices") as fetch_prices,
            patch.object(monitor, "print_market_context") as market_context,
            patch.object(monitor, "save_portfolio") as save_portfolio,
            patch.object(monitor, "save_daily_snapshot") as save_snapshot,
            patch.object(monitor, "cmd_buy") as cmd_buy,
            patch.object(monitor, "cmd_sell") as cmd_sell,
            patch.object(monitor, "cmd_import_usmart") as import_usmart,
            patch.object(monitor, "init_sample_portfolio") as init_sample,
            redirect_stdout(output),
        ):
            monitor.main()

        fetch_prices.assert_not_called()
        market_context.assert_not_called()
        save_portfolio.assert_not_called()
        save_snapshot.assert_not_called()
        cmd_buy.assert_not_called()
        cmd_sell.assert_not_called()
        import_usmart.assert_not_called()
        init_sample.assert_not_called()
        return output.getvalue()

    def test_candidate_displays_schema_positions_and_unknown_cash(self) -> None:
        output = self.run_monitor("--portfolio-file", str(CANDIDATE_FILE))

        self.assertIn("Schema 版本: 1.1", output)
        self.assertIn("持仓数量: 2", output)
        self.assertIn("持仓总成本: $1,436.50", output)
        self.assertIn("SOFI", output)
        self.assertIn("SPCX", output)
        self.assertIn("59.0", output)
        self.assertIn("2.0", output)
        self.assertIn("$       17.50", output)
        self.assertIn("$      202.00", output)
        self.assertIn("$      1,032.50", output)
        self.assertIn("$        404.00", output)
        self.assertIn("现金: 未知", output)
        self.assertIn("总资产: 无法计算", output)
        self.assertIn("购买力: 无法计算", output)
        self.assertNotIn("现金: $0.00", output)
        self.assertNotIn("总资产: $0.00", output)
        self.assertNotIn("购买力: $0.00", output)

    def test_old_schema_prints_clear_incompatibility_error(self) -> None:
        output = self.run_monitor("--portfolio-file", str(OLD_PORTFOLIO_FILE))

        self.assertIn("[错误] 持仓数据无法读取", output)
        self.assertIn("不支持 schema_version=None", output)
        self.assertIn("当前只支持 1.1", output)
        self.assertIn("请使用 Schema 1.1 文件", output)

    def test_legacy_write_commands_are_rejected(self) -> None:
        commands = (
            ("--add",),
            ("--sell", "SOFI"),
            ("--import-usmart",),
            ("--init",),
        )

        for arguments in commands:
            with self.subTest(arguments=arguments):
                output = self.run_monitor(*arguments)
                self.assertIn("[已阻止]", output)
                self.assertIn("仅支持只读查看", output)
                self.assertIn("没有修改任何持仓数据", output)

    def test_json_files_are_unchanged_during_read_only_display(self) -> None:
        self.run_monitor("--portfolio-file", str(CANDIDATE_FILE))

        for path, expected in self.before_contents.items():
            self.assertEqual(path.read_bytes(), expected)


if __name__ == "__main__":
    unittest.main()
