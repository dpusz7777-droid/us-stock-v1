#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Yahoo Finance 备用行情源 — 直接使用 HTTP requests 访问 Yahoo Finance Quote API。

设计原则
--------
1. 作为 YFinancePriceProvider 的降级备用源，不替代它
2. 使用与 network_config.json 相同的代理配置
3. 批量请求，超时 12 秒
4. 所有失败静默降级，不会崩溃
5. 返回统一结构：{symbol: {price, change_pct, source, timestamp, error}}

使用方式
--------
from northstar.data.yahoo_quote_provider import fetch_quotes

result = fetch_quotes(["NVDA", "SOFI", "MSFT"])
# result = {
#     "NVDA": {"symbol": "NVDA", "price": 100.0, "change_pct": 2.5,
#              "source": "yahoo_quote", "timestamp": "...", "error": None},
#     ...
# }
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# ── 日志 ───────────────────────────────────────────────────────
logger = logging.getLogger("yahoo_quote_provider")
_DIAG_LOG_PATH = _PROJECT_ROOT / "logs" / "market_data_check.log"


def _ensure_logger() -> None:
    if logger.handlers:
        return
    _DIAG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(str(_DIAG_LOG_PATH), encoding="utf-8", mode="a")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _build_session() -> Any:
    """构建一个已配置代理的 requests Session。"""
    import requests
    from northstar.config.network import get_working_proxy

    session = requests.Session()
    proxy = get_working_proxy()
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
    })
    session.timeout = 12
    return session


def fetch_quotes(
    symbols: list[str],
) -> dict[str, dict[str, Any]]:
    """通过 Yahoo Finance Quote API 获取多支股票行情。

    使用 YQL 风格: https://query1.finance.yahoo.com/v7/finance/quote?symbols=NVDA,SOFI

    Args:
        symbols: 股票代码列表

    Returns:
        {symbol: {symbol, price, change_pct, source, timestamp, error}, ...}
    """
    _ensure_logger()
    from northstar.config.network import apply_proxy_environment

    # 确保代理环境变量已设置
    proxy = apply_proxy_environment()

    result: dict[str, dict[str, Any]] = {}
    for sym in symbols:
        normalized = sym.strip().upper()
        if not normalized:
            continue
        result[normalized] = {
            "symbol": normalized,
            "price": None,
            "change_pct": None,
            "source": "yahoo_quote",
            "timestamp": None,
            "error": "未获取",
        }

    if not symbols:
        return result

    try:
        session = _build_session()
        comma_sep = ",".join(symbols)
        url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={comma_sep}"

        resp = session.get(url, timeout=12)
        if resp.status_code != 200:
            err_msg = f"HTTP {resp.status_code}"
            logger.warning("YahooQuoteProvider 请求失败: %s", err_msg)
            for sym in symbols:
                normalized = sym.strip().upper()
                if normalized in result:
                    result[normalized]["error"] = err_msg
            return result

        data = resp.json()
        quote_results = data.get("quoteResponse", {})
        quotes = quote_results.get("result", [])
        error_info = quote_results.get("error", None)

        if error_info:
            logger.warning("YahooQuoteProvider API 返回错误: %s", error_info)
            for sym in symbols:
                normalized = sym.strip().upper()
                if normalized in result:
                    result[normalized]["error"] = str(error_info)

        # 处理每支股票的报价
        now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for q in quotes:
            sym = str(q.get("symbol", "")).strip().upper()
            if not sym or sym not in result:
                continue

            price = q.get("regularMarketPrice") or q.get("marketPrice")
            prev_close = q.get("regularMarketPreviousClose") or q.get("previousClose")
            change_pct = None
            if price is not None and prev_close and prev_close > 0:
                change_pct = round((float(price) - float(prev_close)) / float(prev_close) * 100, 2)

            result[sym] = {
                "symbol": sym,
                "price": float(price) if price is not None else None,
                "change_pct": change_pct,
                "source": "yahoo_quote",
                "timestamp": str(q.get("regularMarketTime", now_ts)),
                "error": None,
            }

        # 未从返回结果中找到的股票标记为失败
        returned_symbols = {str(q.get("symbol", "")).strip().upper() for q in quotes}
        for sym in symbols:
            normalized = sym.strip().upper()
            if normalized not in returned_symbols and normalized in result and result[normalized]["error"] == "未获取":
                result[normalized]["error"] = "API 未返回该股票数据"

    except Exception as exc:
        logger.warning("YahooQuoteProvider 异常: %s", exc)
        for sym in symbols:
            normalized = sym.strip().upper()
            if normalized in result:
                result[normalized]["error"] = f"异常: {exc}"

    return result