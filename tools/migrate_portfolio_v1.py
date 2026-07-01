#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""安全地把旧版持仓快照转换为 v1 候选交易文件。

默认只进行校验和预览，不写入任何文件。只有明确传入 ``--write``，
并且全部校验通过后，才会创建候选 JSON 和迁移报告。

本脚本绝不修改或覆盖 portfolio.json、portfolio_config.json。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_FILE = PROJECT_ROOT / "docs" / "portfolio_schema.md"
OLD_PORTFOLIO_FILE = PROJECT_ROOT / "portfolio.json"
OLD_CONFIG_FILE = PROJECT_ROOT / "portfolio_config.json"
CANDIDATE_FILE = PROJECT_ROOT / "portfolio_migrated_candidate.json"
REPORT_FILE = PROJECT_ROOT / "reports" / "portfolio_migration_report.md"

SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]+(?:[.-][A-Z0-9]+)*$")
SUPPORTED_CURRENCY = "USD"
TARGET_SCHEMA_VERSION = "1.1"
DEFAULT_MAX_SINGLE_POSITION_PCT = 20.0
# 仅允许迁移已经由用户根据盈立真实账户截图人工确认的当前持仓。
CONFIRMED_OPENING_POSITIONS = {
    "SOFI": {"shares": 59.0, "avg_cost": 17.50},
    "SPCX": {"shares": 2.0, "avg_cost": 202.00},
}
EXCLUDED_CLOSED_POSITIONS = {
    "ECO": "历史已平仓但缺少完整成交记录，暂未迁移",
}


class MigrationError(Exception):
    """表示迁移无法安全继续。"""


@dataclass
class ValidationResult:
    """集中保存错误、警告和迁移假设。"""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def utc_now() -> str:
    """返回不带微秒的 ISO 8601 UTC 时间。"""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def parse_args() -> argparse.Namespace:
    """解析命令行参数；默认行为等同于 --dry-run。"""

    parser = argparse.ArgumentParser(
        description="只读校验旧持仓，并按需生成 v1 候选文件"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="只校验并预览，不写入文件（默认）",
    )
    mode.add_argument(
        "--write",
        action="store_true",
        help="校验通过后创建候选 JSON 和迁移报告",
    )
    return parser.parse_args()


def read_text_file(path: Path, label: str) -> str:
    """安全读取 UTF-8 文本，不尝试修改或修复源文件。"""

    if not path.is_file():
        raise MigrationError(f"缺少{label}：{path}")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise MigrationError(f"无法读取{label} {path}：{exc}") from exc


def read_json_file(path: Path, label: str) -> dict[str, Any]:
    """读取并验证 JSON 顶层必须是对象。"""

    raw = read_text_file(path, label)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MigrationError(
            f"{label}不是有效 JSON：第 {exc.lineno} 行，第 {exc.colno} 列，{exc.msg}"
        ) from exc
    if not isinstance(data, dict):
        raise MigrationError(f"{label}顶层必须是 JSON 对象。")
    return data


def validate_schema_document() -> str:
    """确认迁移所依据的 schema 文档存在且包含关键约束。"""

    text = read_text_file(SCHEMA_FILE, "schema 文档")
    required_fragments = (
        "schema_version",
        "transactions",
        "唯一事实来源",
        "DEPOSIT",
        "BUY",
        "OPENING_POSITION",
        "cash_status",
        "legacy_migration",
        TARGET_SCHEMA_VERSION,
    )
    missing = [item for item in required_fragments if item not in text]
    if missing:
        raise MigrationError(
            "schema 文档缺少迁移所需的关键内容：" + "、".join(missing)
        )
    return text


def is_finite_number(value: Any, *, allow_zero: bool) -> bool:
    """排除布尔值、字符串、NaN、无穷大和不允许的零值。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    number = float(value)
    if not math.isfinite(number):
        return False
    return number >= 0 if allow_zero else number > 0


def normalize_symbol(value: Any) -> str | None:
    """校验并标准化股票代码。"""

    if not isinstance(value, str):
        return None
    symbol = value.strip().upper()
    if not symbol or not SYMBOL_PATTERN.fullmatch(symbol):
        return None
    return symbol


def validate_old_data(
    portfolio: dict[str, Any], config: dict[str, Any]
) -> tuple[ValidationResult, list[dict[str, Any]], float]:
    """只提取人工确认的当前持仓，不推断任何资金流水。"""

    result = ValidationResult()
    normalized_positions: list[dict[str, Any]] = []

    positions = portfolio.get("positions")
    if not isinstance(positions, list):
        result.errors.append("portfolio.positions 缺失或不是数组。")
        positions = []

    transactions = portfolio.get("transactions")
    if not isinstance(transactions, list):
        result.errors.append("portfolio.transactions 缺失或不是数组。")
    elif transactions:
        result.errors.append(
            "旧 portfolio.transactions 非空；脚本不能同时推断旧交易和初始化交易。"
        )

    seen_symbols: set[str] = set()
    old_positions_by_symbol: dict[str, dict[str, Any]] = {}
    for index, position in enumerate(positions, start=1):
        location = f"positions[{index - 1}]"
        if not isinstance(position, dict):
            result.errors.append(f"{location} 不是 JSON 对象。")
            continue

        symbol = normalize_symbol(position.get("ticker"))
        if symbol is None:
            result.errors.append(f"{location}.ticker 缺失或股票代码格式无效。")
            continue
        if symbol in seen_symbols:
            result.errors.append(f"股票代码 {symbol} 在旧持仓中重复。")
            continue
        seen_symbols.add(symbol)

        old_positions_by_symbol[symbol] = position

    cash = portfolio.get("cash")
    if not is_finite_number(cash, allow_zero=True):
        result.errors.append("portfolio.cash 必须是大于或等于 0 的有限数字。")
        cash_value = 0.0
    else:
        cash_value = float(cash)

    currency = config.get("currency")
    if currency != SUPPORTED_CURRENCY:
        result.errors.append(
            f"portfolio_config.currency 必须为 {SUPPORTED_CURRENCY}，当前为 {currency!r}。"
        )

    for field_name in ("stop_loss_pct", "target_profit_pct"):
        value = config.get(field_name)
        if not is_finite_number(value, allow_zero=False) or float(value) > 100:
            result.errors.append(f"portfolio_config.{field_name} 必须在 (0, 100] 范围内。")

    total_capital = config.get("total_capital")
    if not is_finite_number(total_capital, allow_zero=True):
        result.errors.append(
            "portfolio_config.total_capital 必须是大于或等于 0 的有限数字。"
        )

    for symbol, confirmed in CONFIRMED_OPENING_POSITIONS.items():
        old_position = old_positions_by_symbol.get(symbol)
        if old_position is None:
            result.errors.append(f"人工确认的持仓 {symbol} 在旧 positions 中不存在。")
            continue

        shares = old_position.get("shares")
        avg_cost = old_position.get("avg_cost")
        if not is_finite_number(shares, allow_zero=False):
            result.errors.append(f"{symbol}.shares 必须是大于 0 的有限数字。")
            continue
        if not is_finite_number(avg_cost, allow_zero=False):
            result.errors.append(f"{symbol}.avg_cost 必须是大于 0 的有限数字。")
            continue
        if abs(float(shares) - confirmed["shares"]) > 1e-9:
            result.errors.append(
                f"{symbol} 股数冲突：旧数据为 {shares}，人工确认为 {confirmed['shares']}。"
            )
            continue
        if abs(float(avg_cost) - confirmed["avg_cost"]) > 1e-9:
            result.errors.append(
                f"{symbol} 平均成本冲突：旧数据为 {avg_cost}，"
                f"人工确认为 {confirmed['avg_cost']} USD。"
            )
            continue

        # SOFI 的 pending 已由用户根据真实账户截图确认过时，不能再阻止迁移。
        status = old_position.get("status")
        if symbol != "SOFI" and status not in (None, "", "confirmed"):
            result.errors.append(f"{symbol} 存在未确认状态 status={status!r}。")
            continue

        normalized_positions.append(
            {
                "symbol": symbol,
                "shares": confirmed["shares"],
                "avg_cost": confirmed["avg_cost"],
                "initialization_cost": confirmed["shares"] * confirmed["avg_cost"],
            }
        )

    for symbol, reason in EXCLUDED_CLOSED_POSITIONS.items():
        if symbol in old_positions_by_symbol:
            result.warnings.append(f"{symbol}：{reason}。")

    known_symbols = set(CONFIRMED_OPENING_POSITIONS) | set(EXCLUDED_CLOSED_POSITIONS)
    for symbol in sorted(set(old_positions_by_symbol) - known_symbols):
        result.warnings.append(
            f"{symbol} 未包含在本次人工确认名单中，未自动迁移，必须另行核实。"
        )

    positions_cost = sum(item["initialization_cost"] for item in normalized_positions)

    result.assumptions.extend(
        [
            "仅 SOFI 和 SPCX 已由用户根据盈立真实账户截图确认为当前持仓。",
            "确认持仓只能转换为 OPENING_POSITION，不代表真实逐笔成交历史。",
            "OPENING_POSITION 的手续费统一为 0，且不影响现金。",
            "旧 added 字段没有可靠时区，使用迁移时间作为 effective_at，executed_at 保持 null。",
            "没有可靠初始入金记录，因此不生成 DEPOSIT，也不重建现金。",
            "max_single_position_pct 在旧配置中缺失，候选文件使用 20.0%。",
        ]
    )
    result.warnings.extend(
        [
            "无法恢复真实入金、买卖、分红、税费、拆股和已实现盈亏历史。",
            "source=legacy_migration 表示记录来自旧快照转换，不是券商原始成交记录。",
            "未成交订单、条件单、撤销订单和当前市值快照均不写入 transactions。",
            "候选文件没有 DEPOSIT，现金和账户总值无法完整重建。",
        ]
    )

    return result, normalized_positions, positions_cost


def build_candidate(
    config: dict[str, Any],
    positions: list[dict[str, Any]],
    migration_time: str,
) -> dict[str, Any]:
    """建立只含人工确认期初持仓的候选数据，不推断 DEPOSIT。"""

    transactions: list[dict[str, Any]] = []
    for sequence, position in enumerate(positions, start=1):
        transactions.append(
            {
                "transaction_id": f"txn_legacy_{sequence:06d}",
                "external_id": None,
                "transaction_type": "OPENING_POSITION",
                "symbol": position["symbol"],
                "shares": position["shares"],
                "price": position["avg_cost"],
                "amount": None,
                "fees": 0.0,
                "executed_at": None,
                "effective_at": migration_time,
                "recorded_at": migration_time,
                "source": "legacy_migration",
                "note": (
                    "根据当前真实持仓快照生成的初始化交易，不代表原始逐笔成交记录；"
                    "旧数据没有可靠成交日期，因此使用迁移时间。"
                ),
            }
        )

    return {
        "schema_version": TARGET_SCHEMA_VERSION,
        "account": {
            "account_id": "account_legacy_001",
            "account_name": "旧持仓迁移候选账户",
            "broker": "legacy",
            "base_currency": SUPPORTED_CURRENCY,
            "cash_status": "unknown",
            "created_at": migration_time,
            "updated_at": migration_time,
        },
        "settings": {
            "stop_loss_pct": float(config["stop_loss_pct"]),
            "target_profit_pct": float(config["target_profit_pct"]),
            "max_single_position_pct": DEFAULT_MAX_SINGLE_POSITION_PCT,
        },
        "transactions": transactions,
    }


def validate_candidate(candidate: dict[str, Any]) -> list[str]:
    """写入前再次验证候选 JSON、编号、交易字段和计算结果。"""

    errors: list[str] = []

    try:
        encoded = json.dumps(candidate, ensure_ascii=False, indent=2, allow_nan=False)
        decoded = json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return [f"候选数据无法通过标准 JSON 校验：{exc}"]

    if decoded.get("schema_version") != TARGET_SCHEMA_VERSION:
        errors.append("候选文件 schema_version 不正确。")

    account = decoded.get("account")
    if not isinstance(account, dict) or account.get("cash_status") != "unknown":
        errors.append("迁移候选账户 cash_status 必须为 unknown。")

    transactions = decoded.get("transactions")
    if not isinstance(transactions, list) or not transactions:
        return errors + ["候选文件 transactions 必须是非空数组。"]

    transaction_ids: set[str] = set()
    holdings: dict[str, float] = {}

    required_fields = {
        "transaction_id",
        "external_id",
        "transaction_type",
        "symbol",
        "shares",
        "price",
        "amount",
        "fees",
        "executed_at",
        "effective_at",
        "recorded_at",
        "source",
        "note",
    }

    for index, transaction in enumerate(transactions):
        location = f"transactions[{index}]"
        if not isinstance(transaction, dict):
            errors.append(f"{location} 不是对象。")
            continue
        missing = required_fields - set(transaction)
        if missing:
            errors.append(f"{location} 缺少字段：{', '.join(sorted(missing))}")
            continue

        transaction_id = transaction["transaction_id"]
        if not isinstance(transaction_id, str) or not transaction_id:
            errors.append(f"{location}.transaction_id 无效。")
        elif transaction_id in transaction_ids:
            errors.append(f"交易编号重复：{transaction_id}")
        else:
            transaction_ids.add(transaction_id)

        if transaction["source"] != "legacy_migration":
            errors.append(f"{location}.source 必须为 legacy_migration。")

        transaction_type = transaction["transaction_type"]
        fees = transaction["fees"]
        if not is_finite_number(fees, allow_zero=True):
            errors.append(f"{location}.fees 无效。")
            continue

        if transaction_type == "OPENING_POSITION":
            symbol = normalize_symbol(transaction["symbol"])
            shares = transaction["shares"]
            price = transaction["price"]
            if symbol is None:
                errors.append(f"{location}.symbol 无效。")
                continue
            if not is_finite_number(shares, allow_zero=False):
                errors.append(f"{location}.shares 无效。")
                continue
            if not is_finite_number(price, allow_zero=False):
                errors.append(f"{location}.price 无效。")
                continue
            if transaction["amount"] is not None:
                errors.append(f"{location} 的 OPENING_POSITION amount 必须为 null。")
                continue
            if float(fees) != 0.0:
                errors.append(f"{location} 的 OPENING_POSITION fees 必须为 0。")
                continue
            if transaction["executed_at"] is not None:
                errors.append(f"{location} 的 OPENING_POSITION executed_at 必须为 null。")
                continue
            effective_at = transaction["effective_at"]
            if not isinstance(effective_at, str) or not effective_at.endswith("Z"):
                errors.append(f"{location}.effective_at 不是 UTC ISO 8601 时间。")
                continue
            holdings[symbol] = holdings.get(symbol, 0.0) + float(shares)
        else:
            errors.append(
                f"{location} 只能包含人工确认持仓生成的 OPENING_POSITION，"
                f"当前类型为 {transaction_type!r}。"
            )

        recorded_at = transaction["recorded_at"]
        if not isinstance(recorded_at, str) or not recorded_at.endswith("Z"):
            errors.append(f"{location}.recorded_at 不是 UTC ISO 8601 时间。")

    if set(holdings) != set(CONFIRMED_OPENING_POSITIONS):
        errors.append("候选持仓代码与人工确认名单不一致。")
    else:
        for symbol, confirmed in CONFIRMED_OPENING_POSITIONS.items():
            if abs(holdings[symbol] - confirmed["shares"]) > 1e-9:
                errors.append(f"候选持仓 {symbol} 的股数与人工确认值不一致。")

    return errors


def build_report(
    result: ValidationResult,
    positions: list[dict[str, Any]],
    old_cash: float,
    configured_capital: float,
    initialization_cost: float,
    migration_time: str,
) -> str:
    """生成 Markdown 迁移报告内容。"""

    converted = [
        "`portfolio_config.currency` → `account.base_currency`",
        "`portfolio_config.stop_loss_pct` → `settings.stop_loss_pct`",
        "`portfolio_config.target_profit_pct` → `settings.target_profit_pct`",
        "旧 `ticker` → OPENING_POSITION 的 `symbol`",
        "旧 `shares` → OPENING_POSITION 的 `shares`",
        "旧 `avg_cost` → OPENING_POSITION 的 `price`（期初平均成本）",
        "人工确认的 SOFI 和 SPCX → OPENING_POSITION",
        "无法确认现金基线 → account.cash_status=unknown",
    ]
    unavailable = [
        "真实逐笔成交历史",
        "真实入金和出金日期",
        "手续费历史",
        "已实现盈亏历史",
        "分红、税费和拆股历史",
        "券商原始交易编号",
        "旧时间字段的可靠时区",
    ]

    lines = [
        "# 旧持仓迁移报告",
        "",
        f"- 迁移时间：`{migration_time}`",
        f"- 目标 schema：`{TARGET_SCHEMA_VERSION}`",
        f"- 转换持仓数量：{len(positions)}",
        "- 结果：校验通过并生成不含资金流水的 OPENING_POSITION 候选事件",
        "",
        "## 成功转换的字段",
        "",
        *[f"- {item}" for item in converted],
        "",
        "## 无法转换的字段",
        "",
        *[f"- {item}" for item in unavailable],
        "",
        "## 所有假设",
        "",
        *[f"- {item}" for item in result.assumptions],
        "",
        "## 警告",
        "",
        *[f"- {item}" for item in result.warnings],
        "",
        "## 未迁移项目",
        "",
        "- ECO：历史已平仓但缺少完整成交记录，暂未迁移。",
        "- 未成交订单、条件单和撤销订单：不是已成交交易，未迁移。",
        "- 当前市值快照：不是历史交易，未迁移。",
        "- 初始 DEPOSIT：缺少可靠入金记录，未生成。",
        "",
        "## 新旧账户金额对比",
        "",
        "| 项目 | 金额（USD） |",
        "|---|---:|",
        f"| 旧配置 total_capital | {configured_capital:.5f} |",
        f"| 旧 cash 快照（仅供参考，未迁移） | {old_cash:.5f} |",
        f"| SOFI 初始化成本 | {59 * 17.50:.5f} |",
        f"| SPCX 初始化成本 | {2 * 202.00:.5f} |",
        f"| 合计初始化持仓成本 | {initialization_cost:.5f} |",
        "| 候选 DEPOSIT | 未生成 |",
        "",
        "## 人工确认要求",
        "",
        "候选文件不能自动替换正式数据。由于未生成 DEPOSIT，现金和账户总值无法完整重建。",
        "请先补充可靠资金流水并核对持仓、时间和迁移假设，再决定后续处理。",
        "",
    ]
    return "\n".join(lines)


def print_validation(result: ValidationResult) -> None:
    """在终端输出清晰的中文校验结果。"""

    if result.errors:
        print("\n迁移已停止，发现以下错误：", file=sys.stderr)
        for error in result.errors:
            print(f"  - {error}", file=sys.stderr)
    if result.warnings:
        print("\n警告：")
        for warning in result.warnings:
            print(f"  - {warning}")
    if result.assumptions:
        print("\n迁移假设：")
        for assumption in result.assumptions:
            print(f"  - {assumption}")


def write_temp_file(path: Path, content: str) -> None:
    """独占写入临时文件，并把内容刷新到磁盘。"""

    try:
        with path.open("x", encoding="utf-8", newline="\n") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
    except FileExistsError as exc:
        raise MigrationError(f"临时文件已存在，拒绝覆盖：{path}") from exc
    except OSError as exc:
        raise MigrationError(f"无法写入临时文件 {path}：{exc}") from exc


def validate_temp_files(
    candidate_temp: Path,
    report_temp: Path,
    expected_candidate: dict[str, Any],
) -> None:
    """重新读取两份临时文件，确认写入完整且内容正确。"""

    candidate_from_disk = read_json_file(candidate_temp, "候选 JSON 临时文件")
    if candidate_from_disk != expected_candidate:
        raise MigrationError("候选 JSON 临时文件与内存中的已验证数据不一致。")

    report_text = read_text_file(report_temp, "迁移报告临时文件")
    required_report_sections = (
        "# 旧持仓迁移报告",
        "## 成功转换的字段",
        "## 无法转换的字段",
        "## 所有假设",
        "## 警告",
        "## 新旧账户金额对比",
    )
    missing = [section for section in required_report_sections if section not in report_text]
    if missing:
        raise MigrationError("迁移报告临时文件不完整，缺少：" + "、".join(missing))


def publish_outputs(
    candidate_json: str,
    report: str,
    expected_candidate: dict[str, Any],
) -> None:
    """先写入并验证两份临时文件，再发布正式输出。

    正式文件发布期间如果任一步失败，会删除本次已经发布的正式文件，
    并清理两份临时文件，避免留下半成品迁移结果。
    """

    if CANDIDATE_FILE.exists():
        raise MigrationError(f"候选文件已存在，拒绝覆盖：{CANDIDATE_FILE}")
    if REPORT_FILE.exists():
        raise MigrationError(f"迁移报告已存在，拒绝覆盖：{REPORT_FILE}")

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    candidate_temp = CANDIDATE_FILE.with_name(f".{CANDIDATE_FILE.name}.{token}.tmp")
    report_temp = REPORT_FILE.with_name(f".{REPORT_FILE.name}.{token}.tmp")
    published: list[Path] = []

    try:
        write_temp_file(candidate_temp, candidate_json)
        write_temp_file(report_temp, report)
        validate_temp_files(candidate_temp, report_temp, expected_candidate)

        # 发布前再次检查，降低检查和重命名之间的并发覆盖风险。
        if CANDIDATE_FILE.exists():
            raise MigrationError(f"候选文件已存在，拒绝覆盖：{CANDIDATE_FILE}")
        if REPORT_FILE.exists():
            raise MigrationError(f"迁移报告已存在，拒绝覆盖：{REPORT_FILE}")

        candidate_temp.rename(CANDIDATE_FILE)
        published.append(CANDIDATE_FILE)
        report_temp.rename(REPORT_FILE)
        published.append(REPORT_FILE)
    except BaseException as exc:
        cleanup_errors: list[str] = []
        for path in (candidate_temp, report_temp, *reversed(published)):
            try:
                path.unlink(missing_ok=True)
            except OSError as cleanup_exc:
                cleanup_errors.append(f"{path}: {cleanup_exc}")

        if cleanup_errors:
            detail = "；".join(cleanup_errors)
            raise MigrationError(f"写入失败且清理不完整：{detail}") from exc
        if isinstance(exc, MigrationError):
            raise
        raise MigrationError(f"发布迁移输出失败，已清理临时和半成品文件：{exc}") from exc


def main() -> int:
    """执行只读预览，或在 --write 下安全创建候选输出。"""

    args = parse_args()
    migration_time = utc_now()

    try:
        validate_schema_document()
        portfolio = read_json_file(OLD_PORTFOLIO_FILE, "旧持仓文件")
        config = read_json_file(OLD_CONFIG_FILE, "旧配置文件")

        result, positions, initialization_cost = validate_old_data(portfolio, config)
        print_validation(result)
        if not result.ok:
            return 1

        candidate = build_candidate(
            config,
            positions,
            migration_time,
        )
        candidate_errors = validate_candidate(candidate)
        if candidate_errors:
            print("\n候选数据校验失败，迁移已停止：", file=sys.stderr)
            for error in candidate_errors:
                print(f"  - {error}", file=sys.stderr)
            return 1

        candidate_json = json.dumps(
            candidate, ensure_ascii=False, indent=2, allow_nan=False
        ) + "\n"
        configured_capital = float(config["total_capital"])
        report = build_report(
            result,
            positions,
            float(portfolio["cash"]),
            configured_capital,
            initialization_cost,
            migration_time,
        )

        print("\n校验通过。")
        print(f"  旧持仓数量：{len(positions)}")
        print(f"  SOFI 初始化成本：{59 * 17.50:.2f} USD")
        print(f"  SPCX 初始化成本：{2 * 202.00:.2f} USD")
        print(f"  合计初始化持仓成本：{initialization_cost:.2f} USD")
        print("  交易类型：OPENING_POSITION（不影响现金）")
        print("  cash_status：unknown")
        print("  ECO：历史已平仓但缺少完整成交记录，暂未迁移")
        print("  DEPOSIT：缺少可靠初始入金记录，未生成")
        print("  现金和账户总值无法通过本次迁移完整重建")

        if not args.write:
            print("\n当前为 dry-run：没有写入任何文件。")
            print("如确认要创建候选文件，请明确使用 --write。")
            print("\n候选 JSON 预览：")
            print(candidate_json)
            return 0

        publish_outputs(candidate_json, report, candidate)
        print("\n已创建：")
        print(f"  {CANDIDATE_FILE}")
        print(f"  {REPORT_FILE}")
        print("原始 portfolio.json 和 portfolio_config.json 未被修改。")
        return 0

    except MigrationError as exc:
        print(f"\n迁移已停止：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
