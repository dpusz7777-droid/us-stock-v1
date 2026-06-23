# -*- coding: utf-8 -*-
"""uSMART Excel 导入测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from xml.sax.saxutils import escape
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile

from portfolio_service import get_portfolio_snapshot
from usmart_sync import (
    USmartSyncError,
    backup_file,
    build_schema_document,
    parse_usmart_positions,
    sync_usmart_excel,
)


def write_xlsx(path: Path, rows: list[list[str]]) -> None:
    shared_strings: list[str] = []
    indexes: dict[str, int] = {}

    def shared_index(value: str) -> int:
        if value not in indexes:
            indexes[value] = len(shared_strings)
            shared_strings.append(value)
        return indexes[value]

    def column_name(index: int) -> str:
        name = ""
        while index:
            index, remainder = divmod(index - 1, 26)
            name = chr(65 + remainder) + name
        return name

    row_xml = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            ref = f"{column_name(col_index)}{row_index}"
            cells.append(f'<c r="{ref}" t="s"><v>{shared_index(value)}</v></c>')
        row_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        + "".join(f"<si><t>{escape(value)}</t></si>" for value in shared_strings)
        + "</sst>"
    )
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(row_xml)}</sheetData></worksheet>'
    )
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", shared_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)


def usmart_rows() -> list[list[str]]:
    return [
        [
            "Stock Name",
            "Symbol",
            "QTY",
            "Position P&L",
            "P&L Ratio",
            "Daily P&L",
            "Currency",
            "Latest Market Value",
            "Average Traded Price",
            "The Latest Price",
        ],
        [
            "NVIDIA Corp.",
            "NVDA",
            "1",
            "-0.090",
            "-0.04%",
            "-0.090",
            "USD",
            "202.060",
            "202.150",
            "202.060",
        ],
        [
            "SoFi Technologies, Inc.",
            "SOFI",
            "59",
            "+2.655",
            "+0.26%",
            "+26.255",
            "USD",
            "1035.155",
            "17.500",
            "17.545",
        ],
        [
            "SpaceX",
            "SPCX",
            "2",
            "-85.560",
            "-21.18%",
            "+9.240",
            "USD",
            "318.440",
            "202.000",
            "159.220",
        ],
    ]


def existing_schema() -> dict:
    return {
        "schema_version": "1.1",
        "account": {
            "account_id": "main",
            "account_name": "测试账户",
            "broker": "legacy",
            "base_currency": "USD",
            "cash_status": "known",
            "cash": 100,
            "buying_power": 900,
            "created_at": "2026-06-22T00:00:00Z",
            "updated_at": "2026-06-22T00:00:00Z",
        },
        "settings": {
            "stop_loss_pct": 8,
            "target_profit_pct": 25,
            "max_single_position_pct": 20,
        },
        "transactions": [
            {
                "transaction_id": "old",
                "external_id": None,
                "transaction_type": "OPENING_POSITION",
                "symbol": "ECO",
                "shares": 20,
                "price": 50,
                "amount": None,
                "fees": 0,
                "executed_at": None,
                "effective_at": "2026-06-22T00:00:00Z",
                "recorded_at": "2026-06-22T00:00:00Z",
                "source": "legacy_migration",
                "note": "old",
            }
        ],
    }


class USmartSyncTests(unittest.TestCase):
    def test_parse_usmart_positions_reads_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            excel_path = Path(temp_dir) / "position.xlsx"
            write_xlsx(excel_path, usmart_rows())

            positions = parse_usmart_positions(excel_path)

        self.assertEqual([position.symbol for position in positions], ["NVDA", "SOFI", "SPCX"])
        self.assertEqual(positions[0].shares, Decimal("1"))
        self.assertEqual(positions[0].avg_cost, Decimal("202.150"))
        self.assertEqual(positions[1].latest_market_value, Decimal("1035.155"))

    def test_parse_usmart_positions_requires_known_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            excel_path = Path(temp_dir) / "position.xlsx"
            write_xlsx(excel_path, [["Symbol"], ["NVDA"]])

            with self.assertRaisesRegex(USmartSyncError, "缺少必要列"):
                parse_usmart_positions(excel_path)

    def test_build_schema_document_removes_old_positions_and_sets_cash(self) -> None:
        positions = [
            position
            for position in [
                *parse_usmart_positions_from_rows_for_test(usmart_rows()),
            ]
        ]
        document = build_schema_document(
            positions,
            existing_document=existing_schema(),
            cash=Decimal("2688.96"),
            buying_power=Decimal("7585.18"),
            imported_at=datetime(2026, 6, 24, 0, 0, 0, tzinfo=timezone.utc),
        )

        symbols = [transaction["symbol"] for transaction in document["transactions"]]
        self.assertEqual(symbols, ["NVDA", "SOFI", "SPCX"])
        self.assertNotIn("ECO", symbols)
        self.assertEqual(document["account"]["cash"], 2688.96)
        self.assertEqual(document["account"]["buying_power"], 7585.18)
        self.assertEqual(document["account"]["cash_status"], "known")

    def test_sync_usmart_excel_backs_up_and_updates_schema_and_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            excel_path = root / "position.xlsx"
            portfolio_path = root / "portfolio_migrated_candidate.json"
            legacy_path = root / "portfolio.json"
            write_xlsx(excel_path, usmart_rows())
            portfolio_path.write_text(
                json.dumps(existing_schema(), ensure_ascii=False),
                encoding="utf-8",
            )

            positions, backup_path = sync_usmart_excel(
                excel_path,
                portfolio_path,
                cash=Decimal("2688.96"),
                buying_power=Decimal("7585.18"),
                legacy_portfolio_path=legacy_path,
            )

            state = get_portfolio_snapshot(portfolio_path)
            legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
            backup_exists = backup_path.is_file()

        self.assertEqual([position.symbol for position in positions], ["NVDA", "SOFI", "SPCX"])
        self.assertTrue(backup_exists)
        self.assertEqual(sorted(state.positions), ["NVDA", "SOFI", "SPCX"])
        self.assertEqual(state.cash, Decimal("2688.96"))
        self.assertEqual(state.buying_power, Decimal("7585.18"))
        self.assertEqual(
            [position["ticker"] for position in legacy["positions"]],
            ["NVDA", "SOFI", "SPCX"],
        )
        self.assertEqual(Decimal(str(legacy["cash"])), Decimal("2688.96"))

    def test_backup_file_avoids_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "portfolio_migrated_candidate.json"
            target.write_text("one", encoding="utf-8")
            timestamp = datetime(2026, 6, 24, 0, 0, 0)

            first = backup_file(target, timestamp=timestamp)
            second = backup_file(target, timestamp=timestamp)

        self.assertEqual(first.name, "portfolio_migrated_candidate.backup-20260624-000000.json")
        self.assertEqual(second.name, "portfolio_migrated_candidate.backup-20260624-000000-2.json")


def parse_usmart_positions_from_rows_for_test(rows: list[list[str]]):
    with tempfile.TemporaryDirectory() as temp_dir:
        excel_path = Path(temp_dir) / "position.xlsx"
        write_xlsx(excel_path, rows)
        return parse_usmart_positions(excel_path)


if __name__ == "__main__":
    unittest.main()
