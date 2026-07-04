# -*- coding: utf-8 -*-
"""Phase 17 稳定性与运行安全测试。"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import main
from stability import (
    classify_sync_usmart_status,
    has_run_today,
    log_event,
    report_index_warnings,
)


class StabilityTests(unittest.TestCase):
    def run_main(self, *arguments: str) -> str:
        output = io.StringIO()
        with patch.object(sys, "argv", ["main.py", *arguments]), redirect_stdout(output):
            main.main()
        return output.getvalue()

    def test_duplicate_morning_does_not_write_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir) / "reports"
            reports_dir.mkdir()
            index_path = reports_dir / "index.json"
            today = datetime.now().astimezone().date().isoformat()
            index_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "reports": [
                            {
                                "date": today,
                                "type": "morning",
                                "file_path": f"reports/{today}-morning.md",
                                "portfolio_snapshot": "abc",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            self.assertTrue(has_run_today("morning", index_path=index_path))
            with (
                patch.object(main, "should_block_duplicate_run", return_value=True),
                patch.object(main, "show_morning_briefing") as show_morning,
                patch.object(main, "log_event"),
            ):
                output = self.run_main("morning", "--save")

            show_morning.assert_not_called()
            self.assertIn("[已阻止] morning", output)
            self.assertEqual(list(reports_dir.glob("*.md")), [])

    def test_has_run_today_respects_run_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "index.json"
            today = datetime.now().astimezone().date().isoformat()
            index_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0.1",
                        "reports": [
                            {
                                "date": today,
                                "type": "morning",
                                "file_path": f"reports/{today}-morning.md",
                                "portfolio_snapshot": "abc",
                                "generated_at": f"{today}T08:00:00",
                                "file_hash": "abc",
                                "file_size": 1,
                                "run_mode": "scheduled",
                                "status": "PASS",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            self.assertTrue(has_run_today("morning", index_path=index_path, run_mode="scheduled"))
            self.assertFalse(has_run_today("morning", index_path=index_path, run_mode="manual"))

    def test_sync_usmart_crash_does_not_pollute_legacy_portfolio(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            legacy_path = Path(temp_dir) / "portfolio.json"
            original = {"cash": 123.45, "positions": [{"ticker": "SOFI"}]}
            legacy_path.write_text(
                json.dumps(original, ensure_ascii=False),
                encoding="utf-8",
            )

            with (
                patch.object(main, "should_block_duplicate_run", return_value=False),
                patch.object(main, "log_event"),
                patch.object(main, "ROOT", Path(temp_dir)),
                patch.object(main, "sync_usmart_excel", side_effect=RuntimeError("boom")),
            ):
                output = self.run_main(
                    "sync-usmart",
                    "--force",
                    "--excel",
                    "position.xlsx",
                    "--portfolio-file",
                    str(Path(temp_dir) / "portfolio_migrated_candidate.json"),
                )

            current = json.loads(legacy_path.read_text(encoding="utf-8"))
            self.assertEqual(current, original)
            self.assertIn("uSMART 导入失败", output)

    def test_safe_mode_does_not_write_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
            with (
                patch.object(main, "sync_usmart_excel") as sync_usmart,
                patch.object(main, "log_event") as log_event_mock,
            ):
                output = self.run_main(
                    "--safe",
                    "sync-usmart",
                    "--excel",
                    str(root / "position.xlsx"),
                    "--portfolio-file",
                    str(root / "portfolio_migrated_candidate.json"),
                )
            after = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))

        sync_usmart.assert_not_called()
        log_event_mock.assert_not_called()
        self.assertEqual(after, before)
        self.assertIn("[SAFE]", output)

    def test_report_index_warnings_are_non_fatal_continuity_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "index.json"
            index_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "reports": [
                            {
                                "date": "2026-06-22",
                                "type": "morning",
                                "file_path": "reports/2026-06-22-morning.md",
                                "portfolio_snapshot": "abc",
                            },
                            {
                                "date": "2026-06-24",
                                "type": "evening",
                                "file_path": "reports/2026-06-24-evening.md",
                                "portfolio_snapshot": "abc",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            warnings = report_index_warnings(index_path)

        self.assertTrue(any("2026-06-23 缺少所有报告记录" in item for item in warnings))
        self.assertTrue(any("缺少 evening 报告" in item for item in warnings))

    def test_log_event_writes_stack_trace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "logs" / "system.log"
            try:
                raise ValueError("bad")
            except ValueError as exc:
                log_event("unit-test", "failed", exc=exc, log_path=log_path)

            text = log_path.read_text(encoding="utf-8")

        self.assertIn("[unit-test] failed", text)
        self.assertIn("ValueError: bad", text)

    def test_sync_usmart_status_success_is_pass(self) -> None:
        result = classify_sync_usmart_status(
            "2026-06-25T09:00:00+08:00 [sync-usmart] start\n"
            "2026-06-25T09:00:02+08:00 [sync-usmart] done\n"
        )

        self.assertEqual(result["status"], "PASS")

    def test_sync_usmart_status_run_guard_is_skipped(self) -> None:
        result = classify_sync_usmart_status(
            "2026-06-25T09:00:00+08:00 [sync-usmart] [已阻止] "
            "sync 已在当前时间窗口执行过。 如确需重新执行，请使用 --force。\n"
        )

        self.assertEqual(result["status"], "SKIPPED")

    def test_sync_usmart_status_failure_is_fail(self) -> None:
        result = classify_sync_usmart_status(
            "2026-06-25T09:00:00+08:00 [sync-usmart] failed\n"
        )

        self.assertEqual(result["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
