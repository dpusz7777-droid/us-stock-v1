from __future__ import annotations

import inspect
from pathlib import Path

from northstar.data.providers import usmart_sg_quote_provider as provider_mod
from northstar.data.providers.usmart_sg_quote_provider import (
    USmartSGQuoteProvider,
    mask_account,
)


class FakeContext:
    def __init__(self, response=None):
        self.response = response or {
            "code": 0,
            "msg": "success",
            "data": {
                "list": [
                    {
                        "lastPrice": "204.12",
                        "bidPrice": "204.07",
                        "askPrice": "204.10",
                        "tradeTime": "2026-07-09T10:13:05Z",
                    }
                ]
            },
        }

    def login(self):
        return "secret-token-not-returned"

    def realtime(self, secuIds):
        return self.response


class FakeTradeModule:
    def __init__(self, ctx):
        self.ctx = ctx

    def get_context_by_phonenumber(self, user_key):
        return self.ctx


def test_mask_account_masks_numeric_account():
    assert mask_account("9876504321") == "987****4321"


def test_provider_initializes_with_demo_config_path():
    provider = USmartSGQuoteProvider()
    assert provider.config_path.name == "config.json"
    assert "openapi-sg-demo-py" in str(provider.demo_root)


def test_get_quote_returns_complete_structure_without_leaking_token(tmp_path):
    provider = USmartSGQuoteProvider(
        demo_root=Path("docs/usmart_openapi_application/official_demo/python_demo/openapi-sg-demo-py"),
        trade_module=FakeTradeModule(FakeContext()),
        fallback_fetcher=lambda symbols: {},
    )
    quote = provider.get_quote("nvda")

    assert quote["symbol"] == "NVDA"
    assert quote["price"] == 204.12
    assert quote["bid"] == 204.07
    assert quote["ask"] == 204.10
    assert quote["timestamp"] == "2026-07-09T10:13:05Z"
    assert quote["source"] == "usmart_sg"
    assert quote["status"] == "ok"
    assert "secret-token" not in repr(quote)


def test_usmart_failure_uses_fallback():
    def fallback(symbols):
        return {
            "NVDA": {
                "symbol": "NVDA",
                "price": 199.5,
                "timestamp": "2026-07-09T00:00:00Z",
                "source": "yahoo_quote",
            }
        }

    provider = USmartSGQuoteProvider(
        demo_root=Path("docs/usmart_openapi_application/official_demo/python_demo/openapi-sg-demo-py"),
        trade_module=FakeTradeModule(FakeContext({"code": 500, "msg": "fail"})),
        fallback_fetcher=fallback,
    )
    quote = provider.get_quote("NVDA")

    assert quote["price"] == 199.5
    assert quote["source"] == "yahoo_quote"
    assert quote["status"] == "ok"


def test_provider_has_no_trading_action_entrypoints():
    forbidden = (
        "place_order",
        "entrust_order",
        "modify_order",
        "cancel_order",
        "withdraw",
        "transfer",
        "change_password",
        "trade_login",
    )
    public_methods = {
        name
        for name, value in inspect.getmembers(USmartSGQuoteProvider, inspect.isfunction)
        if not name.startswith("_")
    }
    assert public_methods == {"login", "get_quote", "get_quotes", "health_check"}
    source = Path(provider_mod.__file__).read_text(encoding="utf-8")
    for word in forbidden:
        assert f"def {word}" not in source
