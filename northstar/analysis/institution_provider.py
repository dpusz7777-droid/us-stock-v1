#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""机构分析模块 — 接口占位。

当前状态：未接入
后续可接入：SEC 13F 持仓数据、分析师评级、目标价变化、机构增减持等。

设计原则：
- 不允许编造机构数据
- 明确标明未接入状态
- 预留统一接口供后续开发
"""

from __future__ import annotations

from typing import Any


INSTITUTION_SOURCE_STATUS = "未接入"
"""当前机构数据源接入状态。"""


def get_institution_status() -> dict[str, Any]:
    """返回机构数据源接入状态。"""
    return {
        "status": INSTITUTION_SOURCE_STATUS,
        "source": None,
        "note": "当前版本暂未接入 13F、评级、目标价、机构持仓变化等数据。"
                "后续可接入 SEC EDGAR 13F、分析师评级、目标价变化等数据源。",
        "available_sources": [
            {"name": "SEC 13F 持仓数据", "status": "未接入", "api_type": "EDGAR"},
            {"name": "分析师评级", "status": "未接入", "api_type": "REST"},
            {"name": "目标价变化", "status": "未接入", "api_type": "REST"},
            {"name": "机构增减持", "status": "未接入", "api_type": "REST"},
        ],
    }