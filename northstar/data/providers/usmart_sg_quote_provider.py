"""uSMART SG quote-only provider for Northstar.

Scope is intentionally narrow:
- login to obtain a quote token;
- read US stock quotes through the official demo quote API;
- optionally fall back to the existing Yahoo quote provider.

This module must not expose trading, order placement, modification,
cancellation, withdrawal, password-change, account-asset, or position APIs.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DEMO_ROOT = (
    PROJECT_ROOT
    / "docs"
    / "usmart_openapi_application"
    / "official_demo"
    / "python_demo"
    / "openapi-sg-demo-py"
)


class USmartSGQuoteError(RuntimeError):
    """Raised when uSMART SG quote-only access fails."""


def mask_account(value: str | None) -> str:
    text = str(value or "")
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 7 and digits == text:
        return f"{digits[:3]}****{digits[-4:]}"
    if len(text) <= 6:
        return "*" * len(text)
    return f"{text[:3]}***{text[-3:]}"


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _normalize_symbol(symbol: str) -> str:
    if not isinstance(symbol, str):
        raise ValueError("symbol must be a string")
    normalized = symbol.strip().upper()
    if not normalized:
        raise ValueError("symbol must not be empty")
    return normalized


def _to_usmart_secu_id(symbol: str) -> str:
    normalized = _normalize_symbol(symbol)
    if normalized.startswith("US") and len(normalized) > 2:
        return normalized
    return f"us{normalized}"


def _extract_first_quote_payload(response: Any) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    data = response.get("data")
    if isinstance(data, dict):
        for key in ("list", "items", "quotes", "data", "secuRealTimeMap"):
            value = data.get(key)
            if isinstance(value, list) and value:
                return value[0] if isinstance(value[0], dict) else {}
            if isinstance(value, dict) and value:
                first = next(iter(value.values()))
                return first if isinstance(first, dict) else {}
        return data
    if isinstance(data, list) and data:
        return data[0] if isinstance(data[0], dict) else {}
    return {}


def _first_number(payload: dict[str, Any], keys: Iterable[str]) -> float | None:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return None


def _timestamp_from_payload(payload: dict[str, Any]) -> str:
    for key in ("timestamp", "time", "tradeTime", "updateTime", "quoteTime"):
        value = payload.get(key)
        if value:
            return str(value)
    return _now_iso()


@dataclass
class USmartSGQuoteProvider:
    """Quote-only adapter around the official uSMART SG Python demo."""

    demo_root: Path = DEFAULT_DEMO_ROOT
    user_key: str = "default_user"
    fallback_fetcher: Callable[[list[str]], dict[str, dict[str, Any]]] | None = None
    trade_module: Any | None = None

    source = "usmart_sg"

    def __post_init__(self) -> None:
        self.demo_root = Path(self.demo_root)
        self.config_path = self.demo_root / "conf" / "config.json"
        self._token: str | None = None
        self._ctx: Any | None = None
        if self.fallback_fetcher is None:
            from northstar.data.yahoo_quote_provider import fetch_quotes

            self.fallback_fetcher = fetch_quotes

    def _load_config(self) -> dict[str, Any]:
        return json.loads(self.config_path.read_text(encoding="utf-8-sig"))

    def _masked_default_account(self) -> str:
        try:
            config = self._load_config()
            user = config.get(self.user_key, {})
            if isinstance(user, dict):
                return mask_account(user.get("phoneNumber"))
        except Exception:
            return "***"
        return "***"

    def _load_trade_module(self) -> Any:
        if self.trade_module is not None:
            return self.trade_module
        os.environ["API_DEMO_HOMEPATH"] = str(self.demo_root)
        demo_root_str = str(self.demo_root)
        if demo_root_str not in sys.path:
            sys.path.insert(0, demo_root_str)
        return importlib.import_module("api.trade")

    def login(self) -> bool:
        """Login through the official demo and cache token/context."""
        trade = self._load_trade_module()
        ctx = trade.get_context_by_phonenumber(self.user_key)
        token = ctx.login()
        if not token:
            logger.warning(
                "uSMART SG login failed for account=%s",
                self._masked_default_account(),
            )
            self._token = None
            self._ctx = None
            return False
        self._token = token
        self._ctx = ctx
        logger.info("uSMART SG login ok for account=%s", self._masked_default_account())
        return True

    def _ensure_context(self) -> Any:
        if self._ctx is None or self._token is None:
            if not self.login():
                raise USmartSGQuoteError("uSMART SG login failed")
        return self._ctx

    def _fallback_quote(self, symbol: str, error: str) -> dict[str, Any]:
        if self.fallback_fetcher is None:
            return {
                "symbol": symbol,
                "price": None,
                "bid": None,
                "ask": None,
                "timestamp": _now_iso(),
                "source": self.source,
                "status": "error",
                "error": error,
            }
        fallback = self.fallback_fetcher([symbol]).get(symbol, {})
        price = fallback.get("price")
        return {
            "symbol": symbol,
            "price": price,
            "bid": None,
            "ask": None,
            "timestamp": fallback.get("timestamp") or _now_iso(),
            "source": fallback.get("source") or "fallback",
            "status": "ok" if price else "fallback_failed",
            "error": None if price else error,
        }

    def get_quote(self, symbol: str) -> dict[str, Any]:
        normalized = _normalize_symbol(symbol)
        try:
            ctx = self._ensure_context()
            response = ctx.realtime(secuIds=[_to_usmart_secu_id(normalized)])
            if not isinstance(response, dict) or response.get("code") != 0:
                raise USmartSGQuoteError(f"realtime failed: {response}")
            payload = _extract_first_quote_payload(response)
            price = _first_number(
                payload,
                (
                    "price",
                    "lastPrice",
                    "latestPrice",
                    "currentPrice",
                    "marketPrice",
                    "close",
                    "last",
                    "now",
                ),
            )
            bid = _first_number(payload, ("bid", "bidPrice", "buyPrice", "b1"))
            ask = _first_number(payload, ("ask", "askPrice", "sellPrice", "a1"))
            if price is None:
                raise USmartSGQuoteError("realtime response has no price field")
            return {
                "symbol": normalized,
                "price": price,
                "bid": bid,
                "ask": ask,
                "timestamp": _timestamp_from_payload(payload),
                "source": self.source,
                "status": "ok",
                "error": None,
            }
        except Exception as exc:
            logger.warning("uSMART SG quote failed for %s: %s", normalized, exc)
            return self._fallback_quote(normalized, str(exc))

    def get_quotes(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        return { _normalize_symbol(symbol): self.get_quote(symbol) for symbol in symbols }

    def health_check(self) -> dict[str, Any]:
        login_ok = self.login()
        quote = self.get_quote("NVDA") if login_ok else None
        return {
            "source": self.source,
            "login": "ok" if login_ok else "failed",
            "quote": "ok" if quote and quote.get("status") == "ok" else "failed",
            "account": self._masked_default_account(),
        }

