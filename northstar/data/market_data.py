#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""市场数据统一层 — 所有外部数据入口。

封装 price_provider.py + price_provider_v2.py。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from price_provider import PriceProvider as _YFProvider
from price_provider_v2 import V1CompatibleBridge as _V2Bridge


@dataclass(frozen=True)
class Price:
    """标准化价格数据。"""
    symbol: str
    price: Decimal | None
    source: str  # "yfinance" | "v2" | "cache"
    timestamp: str | None = None
    change_pct: float | None = None


@dataclass(frozen=True)
class MarketSnapshot:
    """市场快照。"""
    prices: tuple[Price, ...]
    timestamp: str


class MarketData:
    """统一市场数据入口。

    用法：
        md = MarketData()
        prices = md.get_prices(["NVDA", "SOFI"])
        snap = md.snapshot()
    """

    def __init__(self) -> None:
        self._v2 = _V2Bridge()
        self._yf = _YFProvider()

    def get_price(self, symbol: str) -> Price:
        """获取单个标的价格（V2优先，YF fallback）。"""
        try:
            v2_price = self._v2.get_price(symbol)
            if v2_price is not None:
                return Price(symbol=symbol, price=v2_price, source="v2")
        except Exception:
            pass

        try:
            yf_price = self._yf.get_price(symbol)
            if yf_price is not None:
                return Price(symbol=symbol, price=yf_price, source="yfinance")
        except Exception:
            pass

        return Price(symbol=symbol, price=None, source="cache")

    def get_prices(self, symbols: list[str]) -> list[Price]:
        """批量获取价格。"""
        return [self.get_price(sym) for sym in symbols]

    def snapshot(self) -> MarketSnapshot:
        """获取完整市场快照。"""
        from datetime import datetime
        from core.data_layer import get_market_status

        items = get_market_status()
        prices = []
        for item in items:
            prices.append(Price(
                symbol=item.symbol,
                price=item.price.value,
                source=item.price.source,
                timestamp=str(item.price.as_of) if item.price.as_of else None,
            ))
        return MarketSnapshot(
            prices=tuple(prices),
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )