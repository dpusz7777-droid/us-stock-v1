#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify uSMART SG quote-only provider.

Read-only only: login + quote for NVDA/AAPL/TSLA. No account, position, order,
or trading calls.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from northstar.data.providers.usmart_sg_quote_provider import (  # noqa: E402
    USmartSGQuoteProvider,
)


def main() -> int:
    provider = USmartSGQuoteProvider()
    login_ok = provider.login()
    print(json.dumps({"login": "TOKEN_OK" if login_ok else "TOKEN_FAIL"}, ensure_ascii=False))
    quotes = provider.get_quotes(["NVDA", "AAPL", "TSLA"]) if login_ok else {}
    safe = {
        symbol: {
            "symbol": quote.get("symbol"),
            "price": quote.get("price"),
            "bid": quote.get("bid"),
            "ask": quote.get("ask"),
            "timestamp": quote.get("timestamp"),
            "source": quote.get("source"),
            "status": quote.get("status"),
        }
        for symbol, quote in quotes.items()
    }
    print(json.dumps(safe, ensure_ascii=False, indent=2))
    return 0 if login_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
