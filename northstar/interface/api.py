#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API 接口层 — 未来网页/UI 接口预留。

当前仅定义接口签名，不实现具体连接。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class APIEndpoint:
    """API 端点定义。"""
    path: str
    method: str  # "GET" | "POST"
    description: str
    params: tuple[str, ...] = ()


# ── API 端点注册 ──

ENDPOINTS: tuple[APIEndpoint, ...] = (
    APIEndpoint("/api/v1/decision", "GET", "获取今日决策"),
    APIEndpoint("/api/v1/portfolio", "GET", "获取持仓状态"),
    APIEndpoint("/api/v1/signals", "GET", "获取交易信号"),
    APIEndpoint("/api/v1/risk", "GET", "获取风险评估"),
    APIEndpoint("/api/v1/history", "GET", "获取交易历史", ("limit",)),
    APIEndpoint("/api/v1/report/morning", "GET", "获取晨间报告"),
    APIEndpoint("/api/v1/report/evening", "GET", "获取晚间复盘"),
    APIEndpoint("/api/v1/simulate/execute", "POST", "提交模拟交易", ("symbol", "action", "price", "qty")),
    APIEndpoint("/api/v1/evaluate", "GET", "获取策略评估"),
)


class API:
    """API 接口类 — 预留实现。"""

    def get_decision(self) -> dict[str, Any]:
        """获取今日决策。"""
        # TODO: 集成 dashboard 的决策逻辑
        return {"status": "not_implemented"}

    def get_portfolio(self) -> dict[str, Any]:
        """获取持仓。"""
        from northstar.data.portfolio_state import PortfolioState
        ps = PortfolioState()
        summary = ps.summary()
        return {
            "total_equity": str(summary.total_equity) if summary.total_equity else None,
            "cash": str(summary.cash) if summary.cash else None,
            "positions": [
                {"symbol": p.symbol, "shares": str(p.shares), "pnl": str(p.unrealized_pnl)}
                for p in summary.positions
            ],
        }

    def list_endpoints(self) -> list[dict[str, Any]]:
        """列出所有可用端点。"""
        return [
            {"path": e.path, "method": e.method, "description": e.description}
            for e in ENDPOINTS
        ]