#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""uSMART 持仓 Excel 导入到 Schema 1.1。

本模块只读取本地 Excel 并更新本地持仓 JSON；不连接券商、不下单。
"""

from __future__ import annotations

import argparse
import json
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from portfolio_service import PortfolioError, get_portfolio_snapshot, load_portfolio


DEFAULT_EXCEL_FILE = Path(__file__).parent / "position-information-20260623.xlsx"
DEFAULT_SCHEMA_PORTFOLIO_FILE = Path(__file__).parent / "portfolio_migrated_candidate.json"
DEFAULT_LEGACY_PORTFOLIO_FILE = Path(__file__).parent / "portfolio.json"
DEFAULT_CASH = Decimal("2688.96")
SUPPORTED_COLUMNS = {
    "Stock Name",
    "Symbol",
    "QTY",
    "Currency",
    "Latest Market Value",
    "Average Traded Price",
    "The Latest Price",
}
NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


class USmartSyncError(Exception):
    """uSMART 导入错误。"""


@dataclass(frozen=True)
class USmartPosition:
    name: str
    symbol: str
    shares: Decimal
    avg_cost: Decimal
    currency: str
    latest_market_value: Decimal | None = None
    latest_price: Decimal | None = None


def _parse_decimal(value: Any, field_name: str, *, allow_zero: bool = False) -> Decimal:
    if value is None or isinstance(value, bool):
        raise USmartSyncError(f"{field_name} 不能为空。")
    text = str(value).strip().replace(",", "")
    if text.startswith("+"):
        text = text[1:]
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise USmartSyncError(f"{field_name} 不是有效数字：{value!r}") from exc
    if number < 0 or (number == 0 and not allow_zero):
        comparison = "大于或等于 0" if allow_zero else "大于 0"
        raise USmartSyncError(f"{field_name} 必须{comparison}。")
    return number


def _xlsx_shared_strings(zip_file: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zip_file.namelist():
        return []
    root = ET.fromstring(zip_file.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for item in root.findall("a:si", NS):
        strings.append("".join(text.text or "" for text in item.findall(".//a:t", NS)))
    return strings


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    value_type = cell.attrib.get("t")
    if value_type == "inlineStr":
        return "".join(text.text or "" for text in cell.findall(".//a:t", NS)).strip()
    value = cell.find("a:v", NS)
    if value is None or value.text is None:
        return ""
    if value_type == "s":
        try:
            return shared_strings[int(value.text)].strip()
        except (IndexError, ValueError) as exc:
            raise USmartSyncError("Excel sharedStrings 索引无效。") from exc
    return value.text.strip()


def _read_first_sheet_rows(path: str | Path) -> list[list[str]]:
    excel_path = Path(path)
    if not excel_path.is_file():
        raise USmartSyncError(f"Excel 文件不存在：{excel_path}")
    try:
        with ZipFile(excel_path) as zip_file:
            shared_strings = _xlsx_shared_strings(zip_file)
            worksheet_names = [
                name
                for name in zip_file.namelist()
                if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
            ]
            if not worksheet_names:
                raise USmartSyncError("Excel 中没有 worksheet。")
            root = ET.fromstring(zip_file.read(sorted(worksheet_names)[0]))
    except BadZipFile as exc:
        raise USmartSyncError(f"Excel 文件无法读取：{excel_path}") from exc
    except ET.ParseError as exc:
        raise USmartSyncError("Excel XML 结构无效。") from exc

    rows: list[list[str]] = []
    for row in root.findall(".//a:sheetData/a:row", NS):
        values = [_cell_value(cell, shared_strings) for cell in row.findall("a:c", NS)]
        if any(value for value in values):
            rows.append(values)
    return rows


def parse_usmart_positions(path: str | Path) -> list[USmartPosition]:
    """解析 uSMART 导出的持仓 Excel。"""

    rows = _read_first_sheet_rows(path)
    if not rows:
        raise USmartSyncError("Excel 没有可导入的内容。")
    headers = rows[0]
    missing = SUPPORTED_COLUMNS - set(headers)
    if missing:
        raise USmartSyncError(f"Excel 缺少必要列：{', '.join(sorted(missing))}")
    indexes = {header: headers.index(header) for header in headers}

    positions: list[USmartPosition] = []
    seen_symbols: set[str] = set()
    for row_number, row in enumerate(rows[1:], start=2):
        padded = row + [""] * (len(headers) - len(row))
        symbol = padded[indexes["Symbol"]].strip().upper()
        if not symbol:
            continue
        if symbol in seen_symbols:
            raise USmartSyncError(f"Excel 第 {row_number} 行重复股票代码：{symbol}")
        seen_symbols.add(symbol)
        currency = padded[indexes["Currency"]].strip().upper()
        if currency != "USD":
            raise USmartSyncError(f"{symbol} 币种不是 USD：{currency}")
        positions.append(
            USmartPosition(
                name=padded[indexes["Stock Name"]].strip(),
                symbol=symbol,
                shares=_parse_decimal(padded[indexes["QTY"]], f"{symbol}.QTY"),
                avg_cost=_parse_decimal(
                    padded[indexes["Average Traded Price"]],
                    f"{symbol}.Average Traded Price",
                ),
                currency=currency,
                latest_market_value=_parse_decimal(
                    padded[indexes["Latest Market Value"]],
                    f"{symbol}.Latest Market Value",
                    allow_zero=True,
                ),
                latest_price=_parse_decimal(
                    padded[indexes["The Latest Price"]],
                    f"{symbol}.The Latest Price",
                    allow_zero=True,
                ),
            )
        )
    if not positions:
        raise USmartSyncError("Excel 中没有持仓行。")
    return positions


def _json_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _json_compatible(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _json_number(value)
    if isinstance(value, dict):
        return {key: _json_compatible(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_compatible(item) for item in value]
    if isinstance(value, tuple):
        return [_json_compatible(item) for item in value]
    return value


def _load_existing_document(path: Path) -> dict[str, Any]:
    if path.is_file():
        try:
            document = load_portfolio(path)
        except PortfolioError as exc:
            raise USmartSyncError(f"现有持仓文件无法读取：{exc}") from exc
        return document
    return {
        "schema_version": "1.1",
        "account": {
            "account_id": "usmart_account_001",
            "account_name": "盈立真实持仓账户",
            "broker": "usmart",
            "base_currency": "USD",
            "cash_status": "known",
        },
        "settings": {
            "stop_loss_pct": 8.0,
            "target_profit_pct": 25.0,
            "max_single_position_pct": 20.0,
        },
        "transactions": [],
    }


def build_schema_document(
    positions: list[USmartPosition],
    *,
    existing_document: dict[str, Any],
    cash: Decimal,
    buying_power: Decimal | None = None,
    imported_at: datetime | None = None,
) -> dict[str, Any]:
    """把 uSMART 持仓快照转换为 Schema 1.1 文档。"""

    timestamp = (imported_at or datetime.now(timezone.utc)).replace(microsecond=0)
    timestamp_text = timestamp.isoformat().replace("+00:00", "Z")
    account = dict(existing_document.get("account") or {})
    account.update(
        {
            "broker": "usmart",
            "base_currency": account.get("base_currency", "USD"),
            "cash_status": "known",
            "cash": _json_number(cash),
            "buying_power": _json_number(
                buying_power if buying_power is not None else cash
            ),
            "updated_at": timestamp_text,
        }
    )
    account.setdefault("account_id", "usmart_account_001")
    account.setdefault("account_name", "盈立真实持仓账户")
    account.setdefault("created_at", timestamp_text)

    transactions = []
    for index, position in enumerate(sorted(positions, key=lambda item: item.symbol), start=1):
        transactions.append(
            {
                "transaction_id": f"txn_usmart_snapshot_{timestamp:%Y%m%d}_{index:06d}",
                "external_id": None,
                "transaction_type": "OPENING_POSITION",
                "symbol": position.symbol,
                "shares": _json_number(position.shares),
                "price": _json_number(position.avg_cost),
                "amount": None,
                "fees": 0.0,
                "executed_at": None,
                "effective_at": timestamp_text,
                "recorded_at": timestamp_text,
                "source": "legacy_migration",
                "note": (
                    "根据 uSMART 持仓 Excel 快照生成的初始化交易，"
                    "不代表原始逐笔成交记录。"
                ),
            }
        )

    return {
        "schema_version": "1.1",
        "account": _json_compatible(account),
        "settings": _json_compatible(existing_document.get("settings"))
        or {
            "stop_loss_pct": 8.0,
            "target_profit_pct": 25.0,
            "max_single_position_pct": 20.0,
        },
        "transactions": transactions,
    }


def backup_file(path: str | Path, *, timestamp: datetime | None = None) -> Path:
    """导入前备份目标文件。"""

    target = Path(path)
    if not target.is_file():
        raise USmartSyncError(f"备份失败，目标文件不存在：{target}")
    stamp = (timestamp or datetime.now()).strftime("%Y%m%d-%H%M%S")
    backup_path = target.with_name(f"{target.stem}.backup-{stamp}{target.suffix}")
    counter = 2
    while backup_path.exists():
        backup_path = target.with_name(
            f"{target.stem}.backup-{stamp}-{counter}{target.suffix}"
        )
        counter += 1
    shutil.copy2(target, backup_path)
    return backup_path


def write_schema_document(path: str | Path, document: dict[str, Any]) -> None:
    target = Path(path)
    serializable_document = _json_compatible(document)
    target.write_text(
        json.dumps(serializable_document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    get_portfolio_snapshot(target)


def sync_usmart_excel(
    excel_path: str | Path = DEFAULT_EXCEL_FILE,
    portfolio_path: str | Path = DEFAULT_SCHEMA_PORTFOLIO_FILE,
    *,
    cash: Decimal = DEFAULT_CASH,
    buying_power: Decimal | None = None,
    legacy_portfolio_path: str | Path | None = DEFAULT_LEGACY_PORTFOLIO_FILE,
) -> tuple[list[USmartPosition], Path]:
    """导入 uSMART Excel，返回持仓与备份路径。"""

    target = Path(portfolio_path)
    positions = parse_usmart_positions(excel_path)
    existing_document = _load_existing_document(target)
    if buying_power is None:
        existing_buying_power = (existing_document.get("account") or {}).get("buying_power")
        if existing_buying_power is not None:
            buying_power = _parse_decimal(
                existing_buying_power,
                "account.buying_power",
                allow_zero=True,
            )
    document = build_schema_document(
        positions,
        existing_document=existing_document,
        cash=cash,
        buying_power=buying_power,
    )
    backup_path = backup_file(target)
    write_schema_document(target, document)

    if legacy_portfolio_path is not None:
        write_legacy_portfolio_snapshot(
            legacy_portfolio_path,
            positions,
            cash=cash,
            imported_at=datetime.now(timezone.utc),
        )
    return positions, backup_path


def write_legacy_portfolio_snapshot(
    path: str | Path,
    positions: list[USmartPosition],
    *,
    cash: Decimal,
    imported_at: datetime | None = None,
) -> None:
    timestamp = (imported_at or datetime.now(timezone.utc)).replace(microsecond=0)
    timestamp_text = timestamp.isoformat().replace("+00:00", "Z")
    document = {
        "positions": [
            {
                "ticker": position.symbol,
                "shares": _json_number(position.shares),
                "avg_cost": _json_number(position.avg_cost),
                "added": timestamp_text,
            }
            for position in sorted(positions, key=lambda item: item.symbol)
        ],
        "cash": _json_number(cash),
        "transactions": [],
        "created": timestamp_text,
    }
    Path(path).write_text(
        json.dumps(_json_compatible(document), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def print_sync_summary(positions: list[USmartPosition], backup_path: Path, cash: Decimal) -> None:
    print("\n=== uSMART 持仓导入完成 ===")
    print(f"导入前备份: {backup_path}")
    print(f"现金: ${cash:,.2f}")
    print("\n持仓:")
    for position in sorted(positions, key=lambda item: item.symbol):
        print(
            f"- {position.symbol}: {position.shares} 股，"
            f"平均成本 ${position.avg_cost:,.2f}"
        )
    print("\n只更新本地持仓数据文件；未连接券商，未自动交易，未下单。")


def main() -> None:
    parser = argparse.ArgumentParser(description="从 uSMART Excel 导入本地持仓")
    parser.add_argument("excel_path", nargs="?", help="uSMART Excel 文件")
    parser.add_argument("--excel", help="uSMART Excel 文件")
    parser.add_argument(
        "--portfolio-file",
        default=str(DEFAULT_SCHEMA_PORTFOLIO_FILE),
        help="Schema 1.1 持仓 JSON 文件",
    )
    parser.add_argument("--cash", default=str(DEFAULT_CASH), help="可用现金")
    parser.add_argument("--buying-power", help="购买力；不填则保留现有值或使用现金")
    parser.add_argument(
        "--no-legacy-sync",
        action="store_true",
        help="不同步更新旧版 portfolio.json",
    )
    args = parser.parse_args()

    cash = _parse_decimal(args.cash, "--cash", allow_zero=True)
    buying_power = (
        _parse_decimal(args.buying_power, "--buying-power", allow_zero=True)
        if args.buying_power is not None
        else None
    )
    try:
        positions, backup_path = sync_usmart_excel(
            args.excel or args.excel_path or DEFAULT_EXCEL_FILE,
            args.portfolio_file,
            cash=cash,
            buying_power=buying_power,
            legacy_portfolio_path=None if args.no_legacy_sync else DEFAULT_LEGACY_PORTFOLIO_FILE,
        )
    except USmartSyncError as exc:
        print(f"\n[错误] uSMART 导入失败：{exc}")
        raise SystemExit(1) from exc
    print_sync_summary(positions, backup_path, cash)


if __name__ == "__main__":
    main()
