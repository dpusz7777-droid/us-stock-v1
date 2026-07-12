#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Yahoo Chart K 线提供器。

复用项目 network.py 的代理配置，直接访问已被代理探测逻辑验证的
v8/finance/chart 端点，避开 yfinance 的本地缓存数据库与 crumb 限流。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

logger = logging.getLogger("yahoo_chart_provider")


@dataclass
class ChartHistory:
    symbol: str
    timestamps: list[int]
    open: list[float | None]
    high: list[float | None]
    low: list[float | None]
    close: list[float | None]
    volume: list[float | None]
    source: str = "yahoo-chart-v8"
    meta: dict[str, Any] | None = None

    @property
    def row_count(self) -> int:
        return len(self.timestamps)


class YahooChartError(RuntimeError):
    pass


def _numbers(values: list[Any] | None) -> list[float | None]:
    result: list[float | None] = []
    for value in values or []:
        try:
            result.append(float(value) if value is not None else None)
        except (TypeError, ValueError):
            result.append(None)
    return result


def fetch_chart_history(
    symbol: str,
    *,
    period: str = "3mo",
    interval: str = "1d",
    timeout: int | None = None,
) -> ChartHistory:
    """获取单支证券 K 线；失败时抛出包含具体原因的异常。"""
    from northstar.config.network import get_price_provider_session, get_request_timeout, load_config

    session = get_price_provider_session()
    request_timeout: int | tuple[float, float] = timeout or get_request_timeout()
    retries = max(0, min(2, int(load_config().get("max_retries", 1) or 1)))
    encoded = quote(symbol.strip().upper(), safe="")
    errors: list[str] = []
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        for attempt in range(retries + 1):
            url = f"https://{host}/v8/finance/chart/{encoded}"
            try:
                response = session.get(
                    url,
                    params={"range": period, "interval": interval, "events": "div,splits"},
                    timeout=request_timeout,
                )
                if response.status_code != 200:
                    errors.append(f"{host} HTTP {response.status_code} attempt={attempt + 1}")
                    if response.status_code in {429, 500, 502, 503, 504} and attempt < retries:
                        continue
                    break
                payload = response.json().get("chart", {})
                if payload.get("error"):
                    errors.append(f"{host} {payload['error']}")
                    break
                results = payload.get("result") or []
                if not results:
                    errors.append(f"{host} 返回空 result")
                    break
                item = results[0]
                timestamps = [int(value) for value in item.get("timestamp") or []]
                quote_data = ((item.get("indicators") or {}).get("quote") or [{}])[0]
                history = ChartHistory(
                    symbol=symbol.strip().upper(),
                    timestamps=timestamps,
                    open=_numbers(quote_data.get("open")),
                    high=_numbers(quote_data.get("high")),
                    low=_numbers(quote_data.get("low")),
                    close=_numbers(quote_data.get("close")),
                    volume=_numbers(quote_data.get("volume")),
                    meta=dict(item.get("meta") or {}),
                )
                valid_closes = sum(value is not None and value > 0 for value in history.close)
                if history.row_count < 1 or valid_closes < 1:
                    errors.append(f"{host} K线为空: rows={history.row_count}, valid_close={valid_closes}")
                    break
                logger.info("%s K线成功: %d rows via %s", history.symbol, history.row_count, host)
                return history
            except Exception as exc:
                errors.append(f"{host} {type(exc).__name__}: {exc} attempt={attempt + 1}")
                if attempt < retries:
                    continue
    message = "; ".join(errors) or "未知错误"
    logger.error("%s K线失败: %s", symbol, message)
    raise YahooChartError(f"{symbol} K线获取失败: {message}")
