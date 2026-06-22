#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Schema 1.1 持仓的只读加载与计算服务。

第一阶段只解析 OPENING_POSITION、BUY 和 SELL，不访问网络、不写入文件。
所有股数、价格、成本和盈亏计算均使用 Decimal。
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping


SUPPORTED_SCHEMA_VERSION = "1.1"
SUPPORTED_TRANSACTION_TYPES = {"OPENING_POSITION", "BUY", "SELL"}
SUPPORTED_CASH_STATUSES = {"known", "unknown"}
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]+(?:[.-][A-Z0-9]+)*$")
ZERO = Decimal("0")


class PortfolioError(Exception):
    """持仓服务异常基类。"""


class PortfolioLoadError(PortfolioError):
    """文件不存在、无法读取或 JSON 无效。"""


class PortfolioValidationError(PortfolioError):
    """Schema 或字段不符合规范。"""


class UnsupportedTransactionError(PortfolioError):
    """交易类型尚未被第一阶段支持。"""


class PortfolioCalculationError(PortfolioError):
    """交易顺序或持仓计算不合法。"""


@dataclass(frozen=True)
class PositionState:
    """一只股票的运行时持仓，不会写回 JSON。"""

    symbol: str
    shares: Decimal
    cost_basis: Decimal
    avg_cost: Decimal
    realized_pnl: Decimal = ZERO
    last_price: Decimal | None = None
    price_as_of: str | None = None
    market_value: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    unrealized_pnl_pct: Decimal | None = None


@dataclass(frozen=True)
class PortfolioState:
    """供 monitor 和 portfolio_tracker 共用的统一运行时结果。"""

    schema_version: str
    cash_status: str
    positions: Mapping[str, PositionState]
    realized_pnl: Decimal
    cash_change_since_tracking: Decimal
    cash: Decimal | None
    total_cost_basis: Decimal
    total_market_value: Decimal | None
    total_unrealized_pnl: Decimal | None
    total_equity: Decimal | None
    buying_power: Decimal | None
    prices_complete: bool
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _to_decimal(value: Any, field_name: str, *, allow_zero: bool) -> Decimal:
    """把 JSON 数字安全转换为 Decimal，并校验范围。"""

    if isinstance(value, bool) or value is None:
        raise PortfolioValidationError(f"{field_name} 必须是有效数字。")
    if isinstance(value, (str, float)):
        raise PortfolioValidationError(
            f"{field_name} 必须是 JSON 数字，不能使用字符串或 float。"
        )
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise PortfolioValidationError(f"{field_name} 不是有效 Decimal 数字。") from exc
    if not number.is_finite():
        raise PortfolioValidationError(f"{field_name} 不能是 NaN 或无穷大。")
    if number < ZERO or (not allow_zero and number == ZERO):
        comparison = "大于或等于 0" if allow_zero else "大于 0"
        raise PortfolioValidationError(f"{field_name} 必须{comparison}。")
    return number


def _require_string(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise PortfolioValidationError(f"{field_name} 必须是字符串。")
    if not allow_empty and not value.strip():
        raise PortfolioValidationError(f"{field_name} 不能为空。")
    return value


def _normalize_symbol(value: Any, field_name: str) -> str:
    symbol = _require_string(value, field_name).strip().upper()
    if not SYMBOL_PATTERN.fullmatch(symbol):
        raise PortfolioValidationError(f"{field_name} 股票代码格式无效：{value!r}")
    return symbol


def load_portfolio(path: str | Path) -> dict[str, Any]:
    """只读加载 Schema JSON，JSON 数字直接解析为 Decimal。"""

    portfolio_path = Path(path)
    if not portfolio_path.is_file():
        raise PortfolioLoadError(f"持仓文件不存在：{portfolio_path}")
    try:
        with portfolio_path.open("r", encoding="utf-8") as file:
            document = json.load(file, parse_float=Decimal, parse_int=Decimal)
    except json.JSONDecodeError as exc:
        raise PortfolioLoadError(
            f"持仓文件不是有效 JSON：第 {exc.lineno} 行，第 {exc.colno} 列，{exc.msg}"
        ) from exc
    except (OSError, UnicodeError) as exc:
        raise PortfolioLoadError(f"无法读取持仓文件 {portfolio_path}：{exc}") from exc
    if not isinstance(document, dict):
        raise PortfolioLoadError("持仓 JSON 顶层必须是对象。")
    return document


def validate_portfolio(document: Mapping[str, Any]) -> None:
    """校验第一阶段需要的 Schema 1.1 字段。"""

    if not isinstance(document, Mapping):
        raise PortfolioValidationError("持仓文档必须是对象。")
    version = document.get("schema_version")
    if version != SUPPORTED_SCHEMA_VERSION:
        raise PortfolioValidationError(
            f"不支持 schema_version={version!r}；当前只支持 {SUPPORTED_SCHEMA_VERSION}。"
        )

    account = document.get("account")
    if not isinstance(account, Mapping):
        raise PortfolioValidationError("account 缺失或不是对象。")
    cash_status = account.get("cash_status")
    if cash_status not in SUPPORTED_CASH_STATUSES:
        raise PortfolioValidationError(
            "account.cash_status 必须是 'known' 或 'unknown'。"
        )

    transactions = document.get("transactions")
    if not isinstance(transactions, list):
        raise PortfolioValidationError("transactions 缺失或不是数组。")

    seen_ids: set[str] = set()
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
        if not isinstance(transaction, Mapping):
            raise PortfolioValidationError(f"{location} 必须是对象。")
        missing = required_fields - set(transaction)
        if missing:
            raise PortfolioValidationError(
                f"{location} 缺少字段：{', '.join(sorted(missing))}"
            )

        transaction_id = _require_string(
            transaction.get("transaction_id"), f"{location}.transaction_id"
        )
        if transaction_id in seen_ids:
            raise PortfolioValidationError(f"transaction_id 重复：{transaction_id}")
        seen_ids.add(transaction_id)

        transaction_type = _require_string(
            transaction.get("transaction_type"), f"{location}.transaction_type"
        )
        if transaction_type not in SUPPORTED_TRANSACTION_TYPES:
            raise UnsupportedTransactionError(
                f"{location} 的交易类型 {transaction_type!r} 暂未支持；"
                "第一阶段只支持 OPENING_POSITION、BUY、SELL。"
            )

        external_id = transaction.get("external_id")
        if external_id is not None and not isinstance(external_id, str):
            raise PortfolioValidationError(
                f"{location}.external_id 必须是字符串或 null。"
            )
        _require_string(transaction.get("note"), f"{location}.note", allow_empty=True)

        _normalize_symbol(transaction.get("symbol"), f"{location}.symbol")
        _to_decimal(transaction.get("shares"), f"{location}.shares", allow_zero=False)
        _to_decimal(transaction.get("price"), f"{location}.price", allow_zero=False)
        fees = _to_decimal(
            transaction.get("fees"), f"{location}.fees", allow_zero=True
        )
        if transaction.get("amount") is not None:
            raise PortfolioValidationError(f"{location}.amount 必须为 null。")

        recorded_at = _require_string(
            transaction.get("recorded_at"), f"{location}.recorded_at"
        )
        if not recorded_at.endswith("Z"):
            raise PortfolioValidationError(f"{location}.recorded_at 必须是 UTC 时间。")

        if transaction_type == "OPENING_POSITION":
            if transaction.get("source") != "legacy_migration":
                raise PortfolioValidationError(
                    f"{location} 的 OPENING_POSITION source 必须为 legacy_migration。"
                )
            if fees != ZERO:
                raise PortfolioValidationError(
                    f"{location} 的 OPENING_POSITION fees 必须为 0。"
                )
            if transaction.get("executed_at") is not None:
                raise PortfolioValidationError(
                    f"{location} 的 OPENING_POSITION executed_at 必须为 null。"
                )
            effective_at = _require_string(
                transaction.get("effective_at"), f"{location}.effective_at"
            )
            if not effective_at.endswith("Z"):
                raise PortfolioValidationError(
                    f"{location}.effective_at 必须是 UTC 时间。"
                )
        else:
            executed_at = _require_string(
                transaction.get("executed_at"), f"{location}.executed_at"
            )
            if not executed_at.endswith("Z"):
                raise PortfolioValidationError(
                    f"{location}.executed_at 必须是 UTC 时间。"
                )
            if transaction.get("effective_at") is not None:
                raise PortfolioValidationError(
                    f"{location}.effective_at 必须为 null。"
                )


def _transaction_sort_key(transaction: Mapping[str, Any]) -> tuple[str, str, str]:
    """以生效/成交时间、记录时间、交易编号形成稳定排序。"""

    event_time = transaction.get("effective_at") or transaction.get("executed_at")
    return (
        str(event_time),
        str(transaction.get("recorded_at")),
        str(transaction.get("transaction_id")),
    )


def build_portfolio_state(document: Mapping[str, Any]) -> PortfolioState:
    """从唯一事实来源 transactions 重建只读运行时持仓。"""

    validate_portfolio(document)
    source_copy = copy.deepcopy(document)
    account = source_copy["account"]
    cash_status = account["cash_status"]
    transactions = sorted(source_copy["transactions"], key=_transaction_sort_key)

    mutable_positions: dict[str, dict[str, Decimal]] = {}
    total_realized = ZERO
    cash_change = ZERO

    for transaction in transactions:
        transaction_id = transaction["transaction_id"]
        transaction_type = transaction["transaction_type"]
        symbol = _normalize_symbol(transaction["symbol"], f"{transaction_id}.symbol")
        shares = _to_decimal(
            transaction["shares"], f"{transaction_id}.shares", allow_zero=False
        )
        price = _to_decimal(
            transaction["price"], f"{transaction_id}.price", allow_zero=False
        )
        fees = _to_decimal(
            transaction["fees"], f"{transaction_id}.fees", allow_zero=True
        )

        position = mutable_positions.setdefault(
            symbol,
            {"shares": ZERO, "cost_basis": ZERO, "realized_pnl": ZERO},
        )

        if transaction_type == "OPENING_POSITION":
            position["shares"] += shares
            position["cost_basis"] += shares * price
        elif transaction_type == "BUY":
            buy_cost = shares * price + fees
            position["shares"] += shares
            position["cost_basis"] += buy_cost
            cash_change -= buy_cost
        elif transaction_type == "SELL":
            current_shares = position["shares"]
            if current_shares == ZERO:
                raise PortfolioCalculationError(
                    f"交易 {transaction_id} 尝试卖出不存在的持仓 {symbol}。"
                )
            if shares > current_shares:
                raise PortfolioCalculationError(
                    f"交易 {transaction_id} 卖出 {shares} 股 {symbol}，"
                    f"超过当前持股 {current_shares} 股。"
                )
            avg_cost = position["cost_basis"] / current_shares
            cost_basis_sold = shares * avg_cost
            net_proceeds = shares * price - fees
            realized = net_proceeds - cost_basis_sold
            position["shares"] -= shares
            position["cost_basis"] -= cost_basis_sold
            position["realized_pnl"] += realized
            total_realized += realized
            cash_change += net_proceeds
            if position["shares"] == ZERO:
                position["cost_basis"] = ZERO
        else:  # validate_portfolio 已经阻止未知类型，这里是防御性保护。
            raise UnsupportedTransactionError(
                f"交易 {transaction_id} 的类型 {transaction_type!r} 暂未支持。"
            )

    positions: dict[str, PositionState] = {}
    for symbol, values in mutable_positions.items():
        if values["shares"] == ZERO:
            continue
        avg_cost = values["cost_basis"] / values["shares"]
        positions[symbol] = PositionState(
            symbol=symbol,
            shares=values["shares"],
            cost_basis=values["cost_basis"],
            avg_cost=avg_cost,
            realized_pnl=values["realized_pnl"],
        )

    total_cost_basis = sum(
        (position.cost_basis for position in positions.values()), start=ZERO
    )
    warnings: tuple[str, ...] = ()
    if cash_status == "unknown":
        warnings = (
            "现金基线未知，cash、total_equity 和 buying_power 不可计算。",
        )

    cash = cash_change if cash_status == "known" else None
    return PortfolioState(
        schema_version=SUPPORTED_SCHEMA_VERSION,
        cash_status=cash_status,
        positions=positions,
        realized_pnl=total_realized,
        cash_change_since_tracking=cash_change,
        cash=cash,
        total_cost_basis=total_cost_basis,
        total_market_value=None,
        total_unrealized_pnl=None,
        total_equity=None,
        buying_power=cash if cash_status == "known" else None,
        prices_complete=False,
        warnings=warnings,
    )


def apply_market_prices(
    state: PortfolioState,
    prices: Mapping[str, Mapping[str, Any] | Decimal],
) -> PortfolioState:
    """把调用方提供的外部行情应用到持仓；本函数不访问网络。"""

    updated_positions: dict[str, PositionState] = {}
    prices_complete = True

    for symbol, position in state.positions.items():
        price_data = prices.get(symbol)
        if price_data is None:
            updated_positions[symbol] = position
            prices_complete = False
            continue

        if isinstance(price_data, Mapping):
            last_price_value = price_data.get("price")
            price_as_of_value = price_data.get("price_as_of")
            price_as_of = (
                _require_string(price_as_of_value, f"prices.{symbol}.price_as_of")
                if price_as_of_value is not None
                else None
            )
        else:
            last_price_value = price_data
            price_as_of = None

        last_price = _to_decimal(
            last_price_value, f"prices.{symbol}.price", allow_zero=False
        )
        market_value = position.shares * last_price
        unrealized_pnl = market_value - position.cost_basis
        unrealized_pnl_pct = (
            unrealized_pnl / position.cost_basis * Decimal("100")
            if position.cost_basis != ZERO
            else None
        )
        updated_positions[symbol] = replace(
            position,
            last_price=last_price,
            price_as_of=price_as_of,
            market_value=market_value,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
        )

    if prices_complete:
        total_market_value = sum(
            (position.market_value for position in updated_positions.values()),
            start=ZERO,
        )
        total_unrealized = sum(
            (position.unrealized_pnl for position in updated_positions.values()),
            start=ZERO,
        )
    else:
        total_market_value = None
        total_unrealized = None

    total_equity = (
        state.cash + total_market_value
        if state.cash_status == "known"
        and state.cash is not None
        and total_market_value is not None
        else None
    )
    return replace(
        state,
        positions=updated_positions,
        total_market_value=total_market_value,
        total_unrealized_pnl=total_unrealized,
        total_equity=total_equity,
        buying_power=state.cash if state.cash_status == "known" else None,
        prices_complete=prices_complete,
    )


def get_portfolio_snapshot(
    path: str | Path,
    prices: Mapping[str, Mapping[str, Any] | Decimal] | None = None,
) -> PortfolioState:
    """供其他模块调用的一站式只读入口。"""

    document = load_portfolio(path)
    state = build_portfolio_state(document)
    return apply_market_prices(state, prices) if prices is not None else state
