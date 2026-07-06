#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新闻分析模块 — 接口占位。

当前状态：未接入
后续可接入：Yahoo Finance News、Finnhub、Benzinga、SeekingAlpha、SEC EDGAR 等。

设计原则：
- 不允许编造新闻数据
- 明确标明未接入状态
- 预留统一接口供后续开发
"""

from __future__ import annotations

from typing import Any


NEWS_SOURCE_STATUS = "未接入"
"""当前新闻源接入状态。"""


def get_news_status() -> dict[str, Any]:
    """返回新闻源接入状态。"""
    return {
        "status": NEWS_SOURCE_STATUS,
        "source": None,
        "note": "当前版本暂未接入实时新闻源，因此新闻分析不参与最终评分。"
                "后续可接入 Yahoo Finance News、Finnhub、Benzinga 等数据源。",
        "available_sources": [
            {"name": "Yahoo Finance News", "status": "未接入", "api_type": "REST"},
            {"name": "Finnhub News", "status": "未接入", "api_type": "REST"},
            {"name": "Benzinga", "status": "未接入", "api_type": "REST"},
            {"name": "SeekingAlpha", "status": "未接入", "api_type": "REST"},
            {"name": "SEC EDGAR", "status": "未接入", "api_type": "REST"},
        ],
    }