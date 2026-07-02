#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B6: 基于标准库 http.server 的本地量化 API。"""

from __future__ import annotations

import argparse
import json
import math
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import urlsplit

from system_controller import SystemController
from ui_service import UIDataService
from report_generator import ReportGenerator


MAX_REQUEST_BYTES = 1_000_000
ROUTES = {"/backtest", "/optimize", "/report", "/analyze"}
UI_ROUTES = {"/ui/backtest_data", "/ui/optimizer_data", "/ui/report_data", "/ui/strategy_list"}


def _json_safe(value: Any) -> Any:
    """递归转换为严格 JSON 可编码值。"""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class QuantAPIHandler(BaseHTTPRequestHandler):
    """无状态 JSON API handler；所有计算仅保存在内存中。"""

    controller_factory = SystemController

    def log_message(self, format: str, *args: Any) -> None:
        """关闭包含当前时间的默认访问日志，保持输出确定性。"""
        return None

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(
            _json_safe(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_payload(self) -> dict:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Invalid Content-Length.") from exc
        if length < 0 or length > MAX_REQUEST_BYTES:
            raise ValueError("Request body is too large.")
        if length == 0:
            return {}
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Request body must be valid UTF-8 JSON.") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object.")
        return payload

    def _dispatch(self, path: str, payload: dict) -> dict:
        if path in UI_ROUTES:
            return self._dispatch_ui(path, payload)
        if path not in ROUTES:
            raise LookupError(f"Unknown endpoint: {path}")

        controller = self.controller_factory(
            historical_data=payload.get("historical_data"),
            initial_cash=payload.get("initial_cash", "100000"),
        )
        symbol = payload.get("symbol")
        if symbol is not None and not isinstance(symbol, str):
            raise ValueError("symbol must be a string.")

        if path == "/backtest":
            return controller.run_backtest(symbol)
        if path == "/analyze":
            return controller.run_analysis(symbol)
        if path == "/optimize":
            return controller.run_optimization(symbol)
        if path == "/report":
            bt_result = controller.run_backtest(symbol)
            return ReportGenerator.build_report(bt_result)
        if symbol is not None:
            return controller.run_symbol(symbol)["report"]
        return controller.run_daily_report()

    def _dispatch_ui(self, path: str, payload: dict) -> dict:
        """UI 数据接口：通过 UIDataService 返回结构化 UI 数据。

        禁止：
          - 在此方法中直接调用 engine
          - 执行策略计算
        """
        # 优先从 query string 获取 symbol（GET 请求）
        from urllib.parse import parse_qs
        query_string = urlsplit(self.path).query
        query_params = parse_qs(query_string)
        symbol = (
            query_params.get("symbol", [None])[0]
            or payload.get("symbol")
            or "NVDA"
        )
        if not isinstance(symbol, str):
            symbol = "NVDA"
        ui_service = UIDataService(
            controller=self.controller_factory(
                historical_data=payload.get("historical_data"),
                initial_cash=payload.get("initial_cash", "100000"),
            )
        )

        if path == "/ui/backtest_data":
            return ui_service.get_backtest_data(symbol)
        if path == "/ui/optimizer_data":
            return ui_service.get_optimizer_data(symbol)
        if path == "/ui/report_data":
            return ui_service.get_report_data(symbol)
        if path == "/ui/strategy_list":
            return {"strategies": ui_service.get_strategy_list(symbol)}
        raise LookupError(f"Unknown UI endpoint: {path}")

    def _handle(self, payload: dict) -> None:
        path = urlsplit(self.path).path
        try:
            result = self._dispatch(path, payload)
        except LookupError as exc:
            self._send_json(404, {"error": str(exc)})
        except (TypeError, ValueError) as exc:
            self._send_json(400, {"error": str(exc)})
        except Exception as exc:
            traceback.print_exc()
            self._send_json(500, {
                "error": "Internal server error",
                "detail": str(exc),
            })
        else:
            self._send_json(200, {"result": result})

    def do_GET(self) -> None:
        self._handle({})

    def do_POST(self) -> None:
        try:
            payload = self._read_payload()
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._handle(payload)


def create_server(
    host: str = "127.0.0.1",
    port: int = 8000,
) -> HTTPServer:
    """创建仅绑定本机回环地址的 HTTPServer。"""
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("API server may only bind to the local loopback host.")
    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535.")
    return HTTPServer((host, port), QuantAPIHandler)


def main() -> None:
    raise RuntimeError("api_server 不能独立启动，请使用 scripts/supervisor.py")


if __name__ == "__main__":
    main()
