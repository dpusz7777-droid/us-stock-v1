#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BrokerProvider — 只读券商数据访问层。

架构说明
--------
本模块定义统一的只读券商数据访问接口，用于获取账户资金、持仓等信息。
所有返回对象均为只读快照，不允许定义任何下单、撤单、修改订单或自动交易方法。

当前阶段只支持 MockBrokerProvider，从本地 portfolio JSON 文件读取数据。
后续可接入 UsmartBrokerProvider（盈立 OpenAPI）、IBKRProvider 等。

安全边界
---------
- 当前版本只读，不允许任何下单/撤单/交易方法
- MockBrokerProvider 不导入 requests、httpx、yfinance、券商 SDK
- 不读取 API Key、Token、密码、私钥
- 所有账户 ID 必须脱敏
- 不允许将敏感信息写入 logs/reports

BrokerProvider 与 PriceProvider 的边界
--------------------------------------
- BrokerProvider: 负责账户资金、持仓、成本、已实现盈亏等券商端数据
- PriceProvider: 负责实时行情价格数据
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

BROKER_STATUS_OK = "OK"
BROKER_STATUS_DEGRADED = "DEGRADED"
BROKER_STATUS_NOT_CONFIGURED = "NOT_CONFIGURED"
BROKER_STATUS_AUTH_REQUIRED = "AUTH_REQUIRED"
BROKER_STATUS_TIMEOUT = "TIMEOUT"
BROKER_STATUS_PROVIDER_ERROR = "PROVIDER_ERROR"
BROKER_STATUS_READ_ONLY = "READ_ONLY"
BROKER_STATUS_UNSUPPORTED = "UNSUPPORTED"
BROKER_STATUSES = {
    BROKER_STATUS_OK,
    BROKER_STATUS_DEGRADED,
    BROKER_STATUS_NOT_CONFIGURED,
    BROKER_STATUS_AUTH_REQUIRED,
    BROKER_STATUS_TIMEOUT,
    BROKER_STATUS_PROVIDER_ERROR,
    BROKER_STATUS_READ_ONLY,
    BROKER_STATUS_UNSUPPORTED,
}

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent
DEFAULT_PORTFOLIO_FILE = ROOT / "portfolio_migrated_candidate.json"

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BrokerAccountSnapshot:
    """账户快照。"""

    account_id_masked: str
    broker: str
    base_currency: str = "USD"
    cash: Decimal | None = None
    buying_power: Decimal | None = None
    total_equity: Decimal | None = None
    positions_market_value: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    realized_pnl: Decimal | None = None
    status: str = BROKER_STATUS_OK
    error_code: str | None = None
    error_message: str | None = None
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = "mock"
    read_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        dct = asdict(self)
        for key in ("cash", "buying_power", "total_equity", "positions_market_value", "unrealized_pnl", "realized_pnl"):
            if dct.get(key) is not None:
                dct[key] = str(dct[key])
        return dct


@dataclass(frozen=True)
class BrokerPosition:
    """单一持仓。"""

    symbol: str
    display_name: str = ""
    asset_type: str = "STOCK"
    currency: str = "USD"
    shares: Decimal | None = None
    avg_cost: Decimal | None = None
    last_price: Decimal | None = None
    market_value: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    unrealized_pnl_pct: Decimal | None = None
    source: str = "mock"
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        dct = asdict(self)
        for key in ("shares", "avg_cost", "last_price", "market_value", "unrealized_pnl", "unrealized_pnl_pct"):
            if dct.get(key) is not None:
                dct[key] = str(dct[key])
        return dct


@dataclass(frozen=True)
class BrokerPortfolioSnapshot:
    """完整持仓快照。"""

    account: BrokerAccountSnapshot
    positions: list[BrokerPosition]
    status: str = BROKER_STATUS_OK
    error_code: str | None = None
    error_message: str | None = None
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = "mock"
    read_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "account": self.account.to_dict(),
            "positions": [p.to_dict() for p in self.positions],
            "status": self.status,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "fetched_at": self.fetched_at,
            "source": self.source,
            "read_only": self.read_only,
        }


# ---------------------------------------------------------------------------
# Security: verify no trade methods exist in this module
# ---------------------------------------------------------------------------

_TRADE_METHOD_NAMES = {"place_order", "cancel_order", "modify_order", "trade", "auto_trade"}


def _check_no_trade_methods(cls: type) -> None:
    """Verify a class does not define any trade method names."""
    for name in dir(cls):
        if name.lower() in _TRADE_METHOD_NAMES:
            raise TypeError(
                f"{cls.__name__} defines forbidden trade method: {name}. "
                "BrokerProvider is read-only."
            )


# ---------------------------------------------------------------------------
# Base broker provider (abstract, read-only)
# ---------------------------------------------------------------------------


class BaseBrokerProvider:
    """
    只读券商数据访问基类。

    只允许定义只读方法：
    - get_account_snapshot()
    - get_positions()
    - get_portfolio_snapshot()
    - health_check()

    禁止定义：
    - place_order, cancel_order, modify_order, trade, auto_trade 等交易方法。
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        _check_no_trade_methods(cls)

    def get_account_snapshot(self) -> BrokerAccountSnapshot:
        raise NotImplementedError

    def get_positions(self) -> list[BrokerPosition]:
        raise NotImplementedError

    def get_portfolio_snapshot(self) -> BrokerPortfolioSnapshot:
        raise NotImplementedError

    def health_check(self) -> dict[str, Any]:
        raise NotImplementedError


# Verify BaseBrokerProvider itself has no trade methods
_check_no_trade_methods(BaseBrokerProvider)

# ---------------------------------------------------------------------------
# MockBrokerProvider — reads from local portfolio JSON
# ---------------------------------------------------------------------------


class MockBrokerProvider(BaseBrokerProvider):
    """
    Mock 券商提供器。

    从本地 portfolio_migrated_candidate.json 读取账户和持仓数据。
    只读，不连接外部网络，不修改任何文件，不读取敏感信息。
    """

    def __init__(self, portfolio_path: str | Path = DEFAULT_PORTFOLIO_FILE):
        self._portfolio_path = Path(portfolio_path)
        self._source = "mock"
        self._broker_name = "mock"

    def _load_portfolio(self) -> dict[str, Any]:
        """加载 portfolio JSON 文件。只读，不修改。"""
        try:
            data = json.loads(self._portfolio_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def _mask_account_id(self, raw_id: str | None) -> str:
        """脱敏账户 ID：只保留前 4 位 + ***。"""
        if not raw_id:
            return "mock***"
        raw = str(raw_id).strip()
        if len(raw) <= 4:
            return raw[:2] + "***"
        return raw[:4] + "***"

    def get_account_snapshot(self) -> BrokerAccountSnapshot:
        data = self._load_portfolio()
        if not data:
            return BrokerAccountSnapshot(
                account_id_masked="unknown***",
                broker=self._broker_name,
                status=BROKER_STATUS_DEGRADED,
                error_code="NO_PORTFOLIO",
                error_message=f"portfolio file not found or invalid: {self._portfolio_path}",
                source=self._source,
                read_only=True,
            )

        account_data = data.get("account") or {}
        raw_id = account_data.get("account_id")

        import portfolio_service
        try:
            state = portfolio_service.get_portfolio_snapshot(self._portfolio_path)
        except Exception:
            state = None

        cash = self._decimal(account_data.get("cash"))
        buying_power = self._decimal(account_data.get("buying_power"))
        total_equity = self._decimal(state.total_equity) if state is not None else None
        positions_mv = self._decimal(state.total_market_value) if state is not None else None
        unrealized = self._decimal(state.total_unrealized_pnl) if state is not None else None
        realized = self._decimal(state.realized_pnl) if state is not None else None

        return BrokerAccountSnapshot(
            account_id_masked=self._mask_account_id(raw_id),
            broker=self._broker_name,
            base_currency=account_data.get("base_currency", "USD"),
            cash=cash,
            buying_power=buying_power,
            total_equity=total_equity,
            positions_market_value=positions_mv,
            unrealized_pnl=unrealized,
            realized_pnl=realized,
            status=BROKER_STATUS_OK,
            source=self._source,
            read_only=True,
        )

    def get_positions(self) -> list[BrokerPosition]:
        import portfolio_service
        try:
            state = portfolio_service.get_portfolio_snapshot(self._portfolio_path)
        except Exception:
            return []

        positions: list[BrokerPosition] = []
        for symbol in sorted(state.positions):
            pos = state.positions[symbol]
            positions.append(BrokerPosition(
                symbol=pos.symbol,
                display_name=pos.symbol,
                asset_type="STOCK",
                currency="USD",
                shares=pos.shares,
                avg_cost=pos.avg_cost,
                last_price=pos.last_price,
                market_value=pos.market_value,
                unrealized_pnl=pos.unrealized_pnl,
                unrealized_pnl_pct=pos.unrealized_pnl_pct,
                source=self._source,
            ))
        return positions

    def get_portfolio_snapshot(self) -> BrokerPortfolioSnapshot:
        try:
            account = self.get_account_snapshot()
            positions = self.get_positions()
            return BrokerPortfolioSnapshot(
                account=account,
                positions=positions,
                status=account.status,
                error_code=account.error_code,
                error_message=account.error_message,
                source=self._source,
                read_only=True,
            )
        except Exception as exc:
            return BrokerPortfolioSnapshot(
                account=BrokerAccountSnapshot(
                    account_id_masked="unknown***",
                    broker=self._broker_name,
                    status=BROKER_STATUS_PROVIDER_ERROR,
                    error_code="READ_ERROR",
                    error_message=str(exc),
                    source=self._source,
                    read_only=True,
                ),
                positions=[],
                status=BROKER_STATUS_PROVIDER_ERROR,
                error_code="READ_ERROR",
                error_message=str(exc),
                source=self._source,
                read_only=True,
            )

    def health_check(self) -> dict[str, Any]:
        try:
            data = self._load_portfolio()
            has_data = bool(data)
            try:
                import portfolio_service
                state_ok = bool(portfolio_service.get_portfolio_snapshot(self._portfolio_path))
            except Exception:
                state_ok = False
            return {
                "ok": has_data and state_ok,
                "read_only": True,
                "connected_to_broker": False,
                "has_sensitive_data": False,
                "portfolio_exists": has_data,
                "portfolio_path": str(self._portfolio_path),
                "source": self._source,
                "broker": self._broker_name,
            }
        except Exception as exc:
            return {
                "ok": False,
                "read_only": True,
                "connected_to_broker": False,
                "has_sensitive_data": False,
                "error": str(exc),
                "source": self._source,
            }

    @staticmethod
    def _decimal(value: Any) -> Decimal | None:
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Disabled broker provider — returns NOT_CONFIGURED
# ---------------------------------------------------------------------------


class DisabledBrokerProvider(BaseBrokerProvider):
    """当 broker 未配置时使用，不抛出异常。"""

    def __init__(self, reason: str = "broker not configured"):
        self._reason = reason

    def get_account_snapshot(self) -> BrokerAccountSnapshot:
        return BrokerAccountSnapshot(
            account_id_masked="disabled***",
            broker="disabled",
            status=BROKER_STATUS_NOT_CONFIGURED,
            error_code="NOT_CONFIGURED",
            error_message=self._reason,
            source="disabled",
            read_only=True,
        )

    def get_positions(self) -> list[BrokerPosition]:
        return []

    def get_portfolio_snapshot(self) -> BrokerPortfolioSnapshot:
        return BrokerPortfolioSnapshot(
            account=self.get_account_snapshot(),
            positions=[],
            status=BROKER_STATUS_NOT_CONFIGURED,
            error_code="NOT_CONFIGURED",
            error_message=self._reason,
            source="disabled",
            read_only=True,
        )

    def health_check(self) -> dict[str, Any]:
        return {
            "ok": False,
            "read_only": True,
            "connected_to_broker": False,
            "has_sensitive_data": False,
            "error": self._reason,
            "source": "disabled",
        }


# ---------------------------------------------------------------------------
# Future provider placeholders (non-functional, for architecture reference)
# ---------------------------------------------------------------------------


class _UsmartBrokerProviderPlaceholder(BaseBrokerProvider):
    """
    盈立 OpenAPI 接入预留位置。
    当前不可用，返回 UNSUPPORTED。
    """
    def __init__(self):
        self._reason = "UsmartBrokerProvider not yet implemented. "
        "Requires: usmart OpenAPI credentials, OAuth2 flow, trade SDK."

    def get_account_snapshot(self) -> BrokerAccountSnapshot:
        return BrokerAccountSnapshot(
            account_id_masked="usmart***",
            broker="usmart",
            status=BROKER_STATUS_UNSUPPORTED,
            error_code="NOT_IMPLEMENTED",
            error_message=self._reason,
            source="usmart",
            read_only=True,
        )

    def get_positions(self) -> list[BrokerPosition]:
        return []

    def get_portfolio_snapshot(self) -> BrokerPortfolioSnapshot:
        return BrokerPortfolioSnapshot(
            account=self.get_account_snapshot(),
            positions=[],
            status=BROKER_STATUS_UNSUPPORTED,
            error_code="NOT_IMPLEMENTED",
            error_message=self._reason,
            source="usmart",
            read_only=True,
        )

    def health_check(self) -> dict[str, Any]:
        return {
            "ok": False,
            "read_only": True,
            "connected_to_broker": False,
            "has_sensitive_data": False,
            "error": self._reason,
            "source": "usmart",
        }


# ---------------------------------------------------------------------------
# BrokerProviderFactory
# ---------------------------------------------------------------------------

BROKER_TYPE_MOCK = "mock"
BROKER_TYPE_DISABLED = "disabled"
BROKER_TYPE_USMART = "usmart"  # future

DEFAULT_BROKER = BROKER_TYPE_MOCK


def create_broker_provider(
    broker_type: str = DEFAULT_BROKER,
    *,
    portfolio_path: str | Path = DEFAULT_PORTFOLIO_FILE,
) -> BaseBrokerProvider:
    """Factory method: create a BrokerProvider by type.

    Args:
        broker_type: one of 'mock', 'disabled', 'usmart' (future)
        portfolio_path: path to portfolio JSON (for mock provider)

    Returns:
        BaseBrokerProvider instance

    Raises:
        ValueError if broker_type is unknown
    """
    normalized = broker_type.strip().lower()
    if normalized == BROKER_TYPE_MOCK:
        return MockBrokerProvider(portfolio_path=portfolio_path)
    elif normalized == BROKER_TYPE_DISABLED:
        return DisabledBrokerProvider()
    elif normalized == BROKER_TYPE_USMART:
        return _UsmartBrokerProviderPlaceholder()
    else:
        raise ValueError(
            f"unknown broker_type: {broker_type!r}. "
            f"Supported: {BROKER_TYPE_MOCK}, {BROKER_TYPE_DISABLED}"
        )


# ---------------------------------------------------------------------------
# Sensitive data check
# ---------------------------------------------------------------------------


def check_broker_provider_safety(provider: BaseBrokerProvider) -> list[str]:
    """检查 BrokerProvider 的安全合规性。

    返回违反安全规则的警告列表，空列表表示安全。
    """
    warnings: list[str] = []

    # 1. Check read_only
    snapshot = provider.get_portfolio_snapshot()
    if not snapshot.read_only:
        warnings.append("BrokerPortfolioSnapshot.read_only is False")

    # 2. Check no trade methods in class
    for attr_name in dir(provider.__class__):
        attr_lower = attr_name.lower()
        if attr_lower in _TRADE_METHOD_NAMES:
            warnings.append(f"Forbidden trade method found: {attr_name}")

    # 3. Check account ID masking
    account = snapshot.account
    if account.account_id_masked and "***" not in account.account_id_masked:
        warnings.append(
            f"Account ID not masked: {account.account_id_masked!r}"
        )

    return warnings