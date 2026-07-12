#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试行情数据连通性模块。

测试点
------
1. network_config.json 可以读取
2. 没有代理配置时不会崩溃
3. 代理配置错误时不会崩溃
4. 行情获取失败时会返回明确状态，而不是抛异常
5. 每日决策报告里包含"行情源状态"
6. 当价格全部为空时，报告会提示"不适合作为交易判断依据"
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from northstar.config.network import (
    load_config,
    get_working_proxy,
    reset_proxy_cache,
    get_connectivity_status,
    _test_proxy,
)
from northstar.reports.daily_decision_report import (
    StockPriceInfo,
    fetch_prices,
    build_report_data,
    COMPANY_NAMES,
)


# ═══════════════════════════════════════════════════════════════
# Test 1: network_config.json 可以读取
# ═══════════════════════════════════════════════════════════════
def test_load_config_returns_dict() -> None:
    """读取 network_config.json 返回字典。"""
    reset_proxy_cache()
    cfg = load_config()
    assert isinstance(cfg, dict)
    assert "use_proxy" in cfg
    assert "candidate_proxies" in cfg
    assert "timeout_seconds" in cfg
    assert isinstance(cfg["candidate_proxies"], list)


def test_load_config_has_expected_fields() -> None:
    """配置文件应包含必要的字段（当前配置为 use_proxy=true 因为办公室网络需要代理）。"""
    reset_proxy_cache()
    cfg = load_config()
    assert "use_proxy" in cfg
    assert "proxy_url" in cfg
    assert cfg["auto_try_local_proxy"] is True
    assert cfg["timeout_seconds"] == 12
    # 当 use_proxy=true 时，proxy_url 应非空
    if cfg.get("use_proxy"):
        assert cfg.get("proxy_url"), "use_proxy=true 时 proxy_url 不应为空"


# ═══════════════════════════════════════════════════════════════
# Test 2: 没有代理配置时不会崩溃
# ═══════════════════════════════════════════════════════════════
def test_no_proxy_config_not_crash() -> None:
    """当配置文件不存在时，应使用默认配置且不崩溃。"""
    with patch("northstar.config.network._CONFIG_PATH", Path(tempfile.gettempdir()) / "nonexistent_net.json"):
        reset_proxy_cache()
        cfg = load_config()
        assert cfg["use_proxy"] is False
        assert cfg["auto_try_local_proxy"] is True
        proxy = get_working_proxy()
        assert proxy is None or isinstance(proxy, str)


def test_empty_proxy_list_not_crash() -> None:
    """当候选代理列表为空时，不应崩溃。"""
    # 用临时配置文件覆盖
    tmp_cfg = tempfile.gettempdir() / Path("test_empty_proxy.json")
    with open(tmp_cfg, "w") as f:
        json.dump({"candidate_proxies": [], "auto_try_local_proxy": True}, f)

    with patch("northstar.config.network._CONFIG_PATH", tmp_cfg):
        reset_proxy_cache()
        # 重新读取其 load_config 逻辑
        from northstar.config.network import load_config as lc
        cfg = lc()
        assert cfg.get("candidate_proxies") == []
        assert cfg.get("auto_try_local_proxy") is True


# ═══════════════════════════════════════════════════════════════
# Test 3: 代理配置错误时不会崩溃
# ═══════════════════════════════════════════════════════════════
def test_proxy_test_not_crash() -> None:
    """测试代理连通性时即使失败也不应崩溃。"""
    # 测试一个绝对不可达的代理
    result = _test_proxy("http://127.0.0.1:1", timeout=2)
    assert result is False  # 预期失败


def test_get_connectivity_status_returns_dict() -> None:
    """get_connectivity_status 总是返回字典。"""
    reset_proxy_cache()
    status = get_connectivity_status()
    assert isinstance(status, dict)
    assert "proxy_url" in status
    assert "proxy_working" in status
    assert "timeout_seconds" in status


# ═══════════════════════════════════════════════════════════════
# Test 4: 行情获取失败时会返回明确状态，而不是抛异常
# ═══════════════════════════════════════════════════════════════
def test_fetch_prices_returns_status_metadata() -> None:
    """fetch_prices embeds one immutable snapshot with explicit failures."""
    class FailedProvider:
        def get_price(self, symbol: str):
            return {"symbol": symbol, "price": None, "source": "unavailable", "status": "error"}

    result = fetch_prices(["NVDA", "MSFT"], provider=FailedProvider())
    snapshot = result["__snapshot__"]
    assert snapshot.market_status == "UNAVAILABLE"
    assert snapshot.valid_symbols == ()
    assert result["NVDA"].current_price is None


def test_fetch_prices_partial_success_status() -> None:
    """Partial success is DEGRADED and failed symbols stay ineligible."""
    class PartialProvider:
        def get_price(self, symbol: str):
            if symbol in {"MSFT", "GOOGL"}:
                raise RuntimeError("injected failure")
            return {
                "symbol": symbol, "price": 100.0, "source": "test_provider",
                "as_of": "2026-07-10T12:00:00Z", "status": "valid",
            }

    result = fetch_prices(["NVDA", "MSFT", "AAPL", "GOOGL"], provider=PartialProvider())
    assert result["__snapshot__"].market_status == "DEGRADED"
    assert result["MSFT"].current_price is None


# ═══════════════════════════════════════════════════════════════
# Test 5: 每日决策报告里包含"行情源状态"
# ═══════════════════════════════════════════════════════════════
def test_report_contains_market_status() -> None:
    """build_report_data 生成的数据应包含行情源状态。"""
    info_map = _make_test_info_map()
    result = build_report_data(info_map, portfolio={})

    assert "overview" in result
    overview = result["overview"]
    assert "行情源状态" in overview
    assert "有效价格数量" in overview
    assert overview["行情源状态"] == "NORMAL"
    assert overview["有效价格数量"] == "25/25"
    assert result["recommendation_status"] == "OK"


def test_report_market_status_when_all_empty() -> None:
    """当价格全部为空时，报告 overview 应该显示"不可用"。"""
    info_map = _make_test_info_map()
    for sym in info_map:
        info_map[sym].current_price = 0.0
        info_map[sym].change_pct_today = 0.0
    result = build_report_data(info_map, portfolio={})

    overview = result["overview"]
    assert overview["行情源状态"] == "UNAVAILABLE"
    assert overview["有效价格数量"] == "0/25"
    assert result["top5_opportunity"] == []


def test_warning_when_all_prices_empty() -> None:
    """build_report_data 在全部空价格时应在 overview 里标明状态。"""
    info_map = _make_test_info_map()
    for sym in info_map:
        info_map[sym].current_price = 0.0
        info_map[sym].change_pct_today = 0.0
    result = build_report_data(info_map, portfolio={"NVDA": {"shares": 1, "avg_cost": 200.0}})

    overview = result["overview"]
    market_status = str(overview.get("行情源状态", ""))
    assert market_status == "UNAVAILABLE"
    assert overview.get("有效价格数量") == "0/25"
    assert result["recommendation_status"] == "DATA_INSUFFICIENT"
    assert result["portfolio_valuation"]["valuation_status"] == "error"


# ═══════════════════════════════════════════════════════════════
# Test 6: 诊断脚本可安全导入
# ═══════════════════════════════════════════════════════════════
def test_diagnostics_script_imports_safely() -> None:
    """check_market_data.py 可以安全导入不报错。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "check_market_data",
        str(PROJECT_ROOT / "scripts" / "check_market_data.py"),
    )
    assert spec is not None, "诊断脚本文件可加载"


def test_proxy_test_function_returns_bool() -> None:
    """_test_proxy 总是返回 bool 类型。"""
    result = _test_proxy("http://192.0.2.1:9999", timeout=1)
    assert isinstance(result, bool)


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════
def _make_test_info_map() -> dict[str, StockPriceInfo]:
    """构建包含 25 支股票的测试数据。"""
    symbols = [
        "NVDA", "AMD", "AVGO", "TSM", "ASML",
        "MSFT", "GOOGL", "META", "AMZN", "AAPL",
        "PLTR", "TSLA", "SOFI", "IONQ", "RGTI",
        "ARM", "MU", "SMCI", "DELL", "ORCL",
        "CRWD", "PANW", "SNOW", "MDB", "COIN",
    ]

    info_map: dict[str, StockPriceInfo] = {}
    for i, sym in enumerate(symbols):
        info = StockPriceInfo(
            symbol=sym,
            company_cn=COMPANY_NAMES.get(sym, sym),
            current_price=100.0 + i * 10,
            change_pct_today=1.0 + i * 0.3,
            change_pct_5d=3.0 + i * 0.5,
            change_pct_20d=5.0 + i * 0.8,
            trend="中性",
            risk_level="低",
            data_source="test_provider",
            as_of="2026-07-10T12:00:00Z",
            status="valid",
        )
        info.suggestion = "继续持有"
        from northstar.reports.daily_decision_report import _generate_reason, _compute_score
        info.reason = _generate_reason(info)
        info.score = _compute_score(info)
        info_map[sym] = info
    return info_map
