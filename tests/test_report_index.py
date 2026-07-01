# -*- coding: utf-8 -*-
"""报告索引测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from report_index import (
    portfolio_snapshot_hash,
    rebuild_report_index,
    record_report,
    recent_reports,
)


class ReportIndexTests(unittest.TestCase):
    def test_record_report_writes_index_with_portfolio_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            portfolio = root / "portfolio_migrated_candidate.json"
            report = root / "reports" / "2026-06-24-morning.md"
            report.parent.mkdir()
            portfolio.write_text('{"schema_version":"1.1"}', encoding="utf-8")
            report.write_text("# report", encoding="utf-8")

            entry = record_report(
                report,
                "morning",
                portfolio_path=portfolio,
                generated_at=datetime(2026, 6, 24, 8, 0, 0),
            )
            data = json.loads((report.parent / "index.json").read_text(encoding="utf-8"))
            expected_hash = portfolio_snapshot_hash(portfolio)

        self.assertEqual(entry["date"], "2026-06-24")
        self.assertEqual(data["reports"][0]["type"], "morning")
        self.assertEqual(data["reports"][0]["portfolio_snapshot"], expected_hash)

    def test_record_report_updates_existing_file_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            portfolio = root / "portfolio.json"
            report = root / "reports" / "2026-06-24-sync.md"
            report.parent.mkdir()
            portfolio.write_text("one", encoding="utf-8")
            report.write_text("sync", encoding="utf-8")

            record_report(report, "sync", portfolio_path=portfolio)
            record_report(report, "sync", portfolio_path=portfolio)
            data = json.loads((report.parent / "index.json").read_text(encoding="utf-8"))

        self.assertEqual(len(data["reports"]), 1)

    def test_rebuild_and_recent_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reports = root / "reports"
            portfolio = root / "portfolio.json"
            reports.mkdir()
            portfolio.write_text("snapshot", encoding="utf-8")
            for name in (
                "2026-06-22-report.md",
                "2026-06-23-morning.md",
                "2026-06-24-evening.md",
            ):
                (reports / name).write_text(name, encoding="utf-8")

            rebuild_report_index(reports, portfolio_path=portfolio, index_path=reports / "index.json")
            recent = recent_reports(2, index_path=reports / "index.json")

        self.assertEqual([item["type"] for item in recent], ["evening", "morning"])


if __name__ == "__main__":
    unittest.main()
