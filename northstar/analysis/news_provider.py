#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Yahoo Finance 实时事件提供器；失败时只返回明确的未获取状态。"""

from __future__ import annotations

import concurrent.futures
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

NO_EVENT_MESSAGE = "当前未获取到该股票的实时新闻事件，因此事件情绪暂不参与最终判断。"

POSITIVE = {
    "order": "大订单", "contract": "大订单", "ai deal": "AI订单",
    "data center": "数据中心订单", "earnings beat": "财报公布",
    "raises guidance": "业绩指引", "new product": "新产品发布",
    "upgrade": "机构评级变化", "price target raised": "目标价上调",
    "cloud growth": "云服务增长",
}
NEGATIVE = {
    "cuts guidance": "业绩指引", "downgrade": "机构评级变化",
    "price target cut": "目标价下调", "regulator": "监管风险",
    "lawsuit": "诉讼风险", "export control": "地缘政治/出口管制",
    "interest rate": "宏观利率冲击", "supply chain": "芯片供应链消息",
}


@dataclass
class EventAnalysis:
    symbol: str
    news_status: str = "未获取"
    source: str | None = None
    main_event: str = NO_EVENT_MESSAGE
    event_type: str = "暂无有效事件"
    sentiment: str = "暂无有效事件"
    impact: str = "事件数据不参与判断，避免用未经验证的信息影响操作。"
    participates_in_score: bool = False
    event_score: float = 0.0
    published_at: str | None = None
    url: str | None = None


def _classify(text: str) -> tuple[str, str, float]:
    lowered = text.lower()
    for keyword, event_type in NEGATIVE.items():
        if keyword in lowered:
            return event_type, "利空", 3.0
    for keyword, event_type in POSITIVE.items():
        if keyword in lowered:
            return event_type, "利好", 16.0
    return "其他已验证事件", "中性", 9.0


def _fetch_one(symbol: str) -> EventAnalysis:
    try:
        import yfinance as yf
        items = yf.Ticker(symbol).news or []
        cutoff = datetime.now(timezone.utc) - timedelta(days=3)
        for raw in items:
            content = raw.get("content", raw)
            title = str(content.get("title") or raw.get("title") or "").strip()
            timestamp = content.get("pubDate") or raw.get("providerPublishTime")
            if not title:
                continue
            published: datetime | None = None
            try:
                published = (
                    datetime.fromtimestamp(float(timestamp), timezone.utc)
                    if isinstance(timestamp, (int, float))
                    else datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
                )
            except (TypeError, ValueError, OSError):
                pass
            if published and published < cutoff:
                continue
            event_type, sentiment, score = _classify(title)
            link = content.get("canonicalUrl") or content.get("clickThroughUrl") or raw.get("link")
            if isinstance(link, dict):
                link = link.get("url")
            impact = {
                "利好": "若后续被成交量与价格确认，可能增强做多资金关注。",
                "利空": "可能压制估值与风险偏好，需等待价格止跌确认。",
                "中性": "事件方向尚不明确，应以价格和成交量确认结果。",
            }[sentiment]
            return EventAnalysis(
                symbol=symbol, news_status="已获取", source="Yahoo Finance",
                main_event=title, event_type=event_type, sentiment=sentiment,
                impact=impact, participates_in_score=True, event_score=score,
                published_at=published.isoformat() if published else None,
                url=str(link) if link else None,
            )
    except Exception:
        pass
    return EventAnalysis(symbol=symbol)


def fetch_events(symbols: list[str], max_workers: int = 6) -> dict[str, dict[str, Any]]:
    """并行抓取真实新闻；任何失败均安全降级，绝不构造事件。"""
    result: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_one, symbol): symbol for symbol in symbols}
        for future, symbol in [(f, s) for f, s in futures.items()]:
            try:
                result[symbol] = asdict(future.result(timeout=12))
            except Exception:
                result[symbol] = asdict(EventAnalysis(symbol=symbol))
    return result


def get_news_status(events: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    acquired = sum(1 for event in (events or {}).values() if event.get("news_status") == "已获取")
    return {
        "status": "已接入" if acquired else "未获取",
        "source": "Yahoo Finance" if acquired else None,
        "acquired_count": acquired,
        "note": (
            f"Yahoo Finance 已返回 {acquired} 支股票的近期真实事件。"
            if acquired else "已尝试 Yahoo Finance，但当前未获取到可验证的实时事件。"
        ),
    }
