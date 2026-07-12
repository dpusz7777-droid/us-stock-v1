#!/usr/bin/env python3
"""Credential-safe Yahoo connectivity matrix for the Northstar market chain."""

from __future__ import annotations

import json
import socket
import ssl
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
REPORT_DIR = PROJECT_ROOT / "reports"
SYMBOLS = ("NVDA", "SOFI", "SPCX")
HOST = "query1.finance.yahoo.com"


def _local_proxy(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}:
            return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
    except (TypeError, ValueError):
        return None
    return None


def _network_probe() -> dict[str, Any]:
    result: dict[str, Any] = {"dns": {"ok": False, "addresses": []}, "tls": {"ok": False}}
    try:
        addresses = sorted({row[4][0] for row in socket.getaddrinfo(HOST, 443, type=socket.SOCK_STREAM)})
        result["dns"] = {"ok": bool(addresses), "addresses": addresses}
    except Exception as exc:
        result["dns"] = {"ok": False, "exception_type": type(exc).__name__}
    try:
        context = ssl.create_default_context()
        with socket.create_connection((HOST, 443), timeout=3) as raw:
            with context.wrap_socket(raw, server_hostname=HOST) as wrapped:
                result["tls"] = {
                    "ok": True,
                    "version": wrapped.version(),
                    "peer_subject_present": bool(wrapped.getpeercert().get("subject")),
                }
    except Exception as exc:
        result["tls"] = {"ok": False, "exception_type": type(exc).__name__}
    return result


def _safe_prefix(text: str) -> str:
    return " ".join((text or "").split())[:300]


def _request_result(
    mode: str,
    symbol: str,
    request: Callable[[str], Any],
    *,
    proxy: str | None,
    network: dict[str, Any],
    retries: int = 1,
) -> dict[str, Any]:
    endpoint = f"https://{HOST}/v8/finance/chart/{symbol}"
    started = time.perf_counter()
    last_error: Exception | None = None
    response = None
    attempts = 0
    for attempt in range(retries + 1):
        attempts = attempt + 1
        try:
            response = request(endpoint)
            if getattr(response, "status_code", None) not in {429, 500, 502, 503, 504}:
                break
        except Exception as exc:
            last_error = exc
            if attempt >= retries:
                break
    status_code = getattr(response, "status_code", None)
    text = getattr(response, "text", "") if response is not None else ""
    exception_type = type(last_error).__name__ if last_error is not None else None
    return {
        "mode": mode,
        "symbol": symbol,
        "endpoint": endpoint,
        "proxy_used": bool(proxy),
        "proxy": _local_proxy(proxy),
        "http_status": status_code,
        "dns_result": network["dns"] if not proxy else {"ok": True, "resolution": "handled_by_local_proxy"},
        "tls_result": network["tls"] if not proxy else {"ok": response is not None, "evidence": "HTTPS_response"},
        "exception_type": exception_type,
        "response_prefix": _safe_prefix(text),
        "is_403": status_code == 403,
        "is_429": status_code == 429,
        "timed_out": exception_type is not None and "timeout" in exception_type.lower(),
        "retry_count": max(0, attempts - 1),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def main() -> int:
    import requests
    from northstar.config.network import get_price_provider_session, get_working_proxy, reset_proxy_cache

    reset_proxy_cache()
    project_proxy = _local_proxy(get_working_proxy())
    network = _network_probe()
    results: list[dict[str, Any]] = []

    direct = requests.Session()
    direct.trust_env = False
    direct.headers["User-Agent"] = "Mozilla/5.0 NorthstarConnectivityAudit/1.0"
    for symbol in SYMBOLS:
        results.append(_request_result(
            "requests_direct", symbol,
            lambda url, s=direct: s.get(url, params={"range": "5d", "interval": "1d"}, timeout=(3, 8)),
            proxy=None, network=network,
        ))

    if project_proxy:
        proxied = requests.Session()
        proxied.trust_env = False
        proxied.proxies.update({"http": project_proxy, "https": project_proxy})
        proxied.headers["User-Agent"] = direct.headers["User-Agent"]
        for symbol in SYMBOLS:
            results.append(_request_result(
                "requests_http_proxy", symbol,
                lambda url, s=proxied: s.get(url, params={"range": "5d", "interval": "1d"}, timeout=(3, 8)),
                proxy=project_proxy, network=network,
            ))

    project_session = get_price_provider_session()
    for symbol in SYMBOLS:
        results.append(_request_result(
            "project_shared_requests_session", symbol,
            lambda url, s=project_session: s.get(url, params={"range": "5d", "interval": "1d"}, timeout=(3, 8)),
            proxy=project_proxy, network=network,
        ))

    try:
        import httpx
        for mode, proxy in (("httpx_direct", None), ("httpx_http_proxy", project_proxy)):
            if mode.endswith("proxy") and not proxy:
                continue
            with httpx.Client(proxy=proxy, trust_env=False, timeout=httpx.Timeout(8, connect=3)) as client:
                for symbol in SYMBOLS:
                    results.append(_request_result(
                        mode, symbol,
                        lambda url, c=client: c.get(url, params={"range": "5d", "interval": "1d"}),
                        proxy=proxy, network=network,
                    ))
    except ImportError:
        pass

    socks_supported = False
    try:
        import socks  # type: ignore  # noqa: F401
        socks_supported = True
    except ImportError:
        pass

    # yfinance 1.5 uses curl_cffi internally; test it independently from requests/httpx.
    yfinance_results: list[dict[str, Any]] = []
    try:
        import yfinance as yf
        for mode, proxy in (("yfinance_direct", None), ("yfinance_http_proxy", project_proxy)):
            if mode.endswith("proxy") and not proxy:
                continue
            yf.set_config(proxy=proxy, retries=1)
            for symbol in SYMBOLS:
                started = time.perf_counter()
                try:
                    frame = yf.download(symbol, period="5d", interval="1d", progress=False, threads=False, timeout=8)
                    ok = frame is not None and not frame.empty
                    error_type = None
                except Exception as exc:
                    ok = False
                    error_type = type(exc).__name__
                yfinance_results.append({
                    "mode": mode, "symbol": symbol, "endpoint": "Yahoo endpoints managed by yfinance",
                    "proxy_used": bool(proxy), "proxy": _local_proxy(proxy), "success": ok,
                    "exception_type": error_type, "retry_count": 1,
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                })
    except ImportError:
        pass

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scope": list(SYMBOLS),
        "target_host": HOST,
        "detected_proxy": project_proxy,
        "socks_dependency_supported": socks_supported,
        "socks_test_status": "not_run_missing_dependency" if not socks_supported else "no_detected_socks_listener",
        "direct_network_probe": network,
        "results": results,
        "yfinance_results": yfinance_results,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "yahoo_proxy_connectivity_audit.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# Yahoo 代理连通性审计",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- 检测到的本地 HTTP 代理：{project_proxy or '无'}",
        f"- SOCKS 测试：{payload['socks_test_status']}",
        "",
        "| 模式 | 股票 | 代理 | HTTP | DNS | TLS | 403 | 429 | 超时 | 重试 | 耗时(s) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in results:
        lines.append(
            f"| {row['mode']} | {row['symbol']} | {'是' if row['proxy_used'] else '否'} | "
            f"{row['http_status'] if row['http_status'] is not None else '—'} | "
            f"{'成功' if row['dns_result'].get('ok') else '失败'} | "
            f"{'成功' if row['tls_result'].get('ok') else '失败'} | "
            f"{'是' if row['is_403'] else '否'} | {'是' if row['is_429'] else '否'} | "
            f"{'是' if row['timed_out'] else '否'} | {row['retry_count']} | {row['elapsed_seconds']} |"
        )
    lines.extend(["", "## yfinance 独立会话", "", "| 模式 | 股票 | 成功 | 代理 | 耗时(s) |", "|---|---|---:|---:|---:|"])
    for row in yfinance_results:
        lines.append(
            f"| {row['mode']} | {row['symbol']} | {'是' if row['success'] else '否'} | "
            f"{'是' if row['proxy_used'] else '否'} | {row['elapsed_seconds']} |"
        )
    lines.extend([
        "", "## 结论", "",
        "直连与本地代理结果必须分别判断；本报告不包含订阅、节点、密码、Token 或远程代理信息。",
    ])
    (REPORT_DIR / "yahoo_proxy_connectivity_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
