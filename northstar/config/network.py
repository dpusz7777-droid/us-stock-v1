#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网络配置管理模块。

功能
----
1. 读取 northstar/config/network_config.json
2. 提供代理自动检测和复用能力
3. 给 yfinance 提供 session 级别的代理配置
4. 记录代理诊断日志

使用方式
--------
from northstar.config.network import get_price_provider_session

session = get_price_provider_session()
# session 是一个 requests.Session，已配置好代理
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

# ── 目录定位 ──────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_CONFIG_PATH = Path(__file__).resolve().parent / "network_config.json"
_DIAG_LOG_PATH = _PROJECT_ROOT / "logs" / "market_data_check.log"

# ── 日志 ───────────────────────────────────────────────────────
logger = logging.getLogger("network_config")


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
    # console mirror
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(console)


# ── 默认配置 ──────────────────────────────────────────────────
_DEFAULT_CONFIG: dict[str, Any] = {
    "use_proxy": False,
    "proxy_url": "",
    "auto_try_local_proxy": True,
    "candidate_proxies": [
        "http://127.0.0.1:7890",
        "http://127.0.0.1:7897",
        "http://127.0.0.1:10808",
        "socks5://127.0.0.1:7890",
        "socks5://127.0.0.1:7897",
        "socks5://127.0.0.1:10808",
    ],
    "timeout_seconds": 12,
}

# ── 运行时状态（跨模块共享） ───────────────────────────────────
_working_proxy: str | None = None
_config_loaded: dict[str, Any] | None = None
_proxy_tested: bool = False


# ── 公共 API ──────────────────────────────────────────────────
def load_config() -> dict[str, Any]:
    """读取 network_config.json，失败时返回默认配置。"""
    global _config_loaded
    if _config_loaded is not None:
        return _config_loaded

    if not _CONFIG_PATH.exists():
        logger.info("network_config.json 不存在，使用默认配置")
        _config_loaded = dict(_DEFAULT_CONFIG)
        return _config_loaded

    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            raise ValueError("配置文件不是 JSON 对象")
        _config_loaded = cfg
        return cfg
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("读取 network_config.json 失败: %s，使用默认配置", exc)
        _config_loaded = dict(_DEFAULT_CONFIG)
        return _config_loaded


def get_working_proxy() -> str | None:
    """获取当前可用的代理地址。

    自动检测逻辑：
    1. 如果 use_proxy=true 且 proxy_url 非空，直接返回 proxy_url
    2. 如果 auto_try_local_proxy=true，逐个尝试 candidates
    3. 找到可用代理后缓存，后续调用直接返回
    4. 都没找到返回 None（直连）

    Returns:
        代理地址字符串，或 None（直连）
    """
    global _working_proxy, _proxy_tested

    if _proxy_tested:
        return _working_proxy

    cfg = load_config()
    timeout = cfg.get("timeout_seconds", 12)
    _ensure_logger()

    # 情况 1: 明确指定代理
    if cfg.get("use_proxy") and cfg.get("proxy_url"):
        proxy = str(cfg["proxy_url"]).strip()
        if proxy:
            logger.info("使用配置文件指定代理: %s", proxy)
            _working_proxy = proxy
            _proxy_tested = True
            return proxy

    # 情况 2: 自动检测本地代理
    if cfg.get("auto_try_local_proxy"):
        candidates = cfg.get("candidate_proxies", [])
        for candidate in candidates:
            if not candidate or not isinstance(candidate, str):
                continue
            candidate = candidate.strip()
            if not candidate:
                continue
            if _test_proxy(candidate, timeout):
                logger.info("自动检测到可用代理: %s", candidate)
                _working_proxy = candidate
                _proxy_tested = True
                return candidate

    # 情况 3: 直连
    logger.info("未找到可用代理，使用直连")
    _working_proxy = None
    _proxy_tested = True
    return None


def reset_proxy_cache() -> None:
    """重置代理缓存和配置缓存，下次调用会重新加载配置和检测代理。"""
    global _working_proxy, _proxy_tested, _config_loaded
    _working_proxy = None
    _proxy_tested = False
    _config_loaded = None


def _test_proxy(proxy_url: str, timeout: int) -> bool:
    """测试代理是否可用（是否能连接到 Yahoo Finance）。"""
    import requests

    proxies = {"http": proxy_url, "https": proxy_url}
    test_url = "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"
    try:
        resp = requests.get(
            test_url,
            proxies=proxies,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if resp.status_code == 200:
            return True
        logger.debug("代理 %s 返回状态码 %d", proxy_url, resp.status_code)
        return False
    except requests.exceptions.ConnectTimeout:
        logger.debug("代理 %s 连接超时", proxy_url)
        return False
    except requests.exceptions.ProxyError as exc:
        logger.debug("代理 %s 错误: %s", proxy_url, exc)
        return False
    except requests.exceptions.SSLError:
        logger.debug("代理 %s SSL 握手失败", proxy_url)
        return False
    except Exception as exc:
        logger.debug("代理 %s 测试异常: %s", proxy_url, exc)
        return False


def get_price_provider_session() -> Any | None:
    """获取配置好代理的 requests.Session。

    如果找到了可用代理，返回配置好的 session；
    如果直连，返回 None（调用方保持默认）。

    Returns:
        requests.Session 或 None
    """
    proxy = get_working_proxy()
    if proxy is None:
        return None

    import requests
    session = requests.Session()
    session.proxies = {"http": proxy, "https": proxy}
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })
    return session


# ── 诊断信息 ──────────────────────────────────────────────────
def get_connectivity_status() -> dict[str, Any]:
    """返回当前网络连接诊断状态。"""
    cfg = load_config()
    proxy = get_working_proxy()
    return {
        "proxy_url": proxy or "直连",
        "proxy_configured": bool(cfg.get("use_proxy") and cfg.get("proxy_url")),
        "auto_try_enabled": bool(cfg.get("auto_try_local_proxy")),
        "timeout_seconds": cfg.get("timeout_seconds", 12),
        "proxy_working": proxy is not None,
    }