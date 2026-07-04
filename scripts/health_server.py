#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V1.9 local API server with production health telemetry."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from http.server import HTTPServer
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api_server import QuantAPIHandler  # noqa: E402


PID_DIR = ROOT / ".runtime" / "pids"


def _process_alive(name: str, signature: str) -> bool:
    try:
        pid = int((PID_DIR / f"{name}.pid").read_text(encoding="utf-8").strip())
        os.kill(pid, 0)
        command = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        ).stdout
        return signature in command
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def _read_json(path: Path, fallback: dict) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else fallback
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return fallback


def health_payload() -> dict:
    queue = _read_json(ROOT / "execution_queue.json", {"queue": []}).get("queue", [])
    if not isinstance(queue, list):
        queue = []
        queue_valid = False
    else:
        queue_valid = all(
            isinstance(item, dict)
            and item.get("status", "pending") == "pending"
            for item in queue
        )

    snapshot = _read_json(
        ROOT / "state_snapshot.json",
        {"cycles": {}, "last_health": {}},
    )
    health = snapshot.get("last_health", {})
    if not isinstance(health, dict):
        health = {}
    watchdog = health.get("watchdog", {})
    if not isinstance(watchdog, dict):
        watchdog = {}

    heartbeat = _read_json(
        ROOT / "state" / "heartbeat.json",
        {},
    )
    try:
        heartbeat_time = datetime.fromisoformat(
            str(heartbeat["timestamp"]).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        heartbeat_age = max(
            0.0,
            (datetime.now(timezone.utc) - heartbeat_time).total_seconds(),
        )
    except (ValueError, TypeError, KeyError):
        heartbeat_age = float("inf")

    daemon_alive = _process_alive("daemon", "daemon_runner.py")
    supervisor_alive = _process_alive("supervisor", "supervisor.py start")
    degraded = (
        health.get("runtime_mode") == "degraded"
        or int(watchdog.get("consecutive_skips", 0) or 0) >= 3
    )
    if not daemon_alive and not supervisor_alive:
        system_status = "STOPPED"
    elif (
        not daemon_alive
        or not supervisor_alive
        or not queue_valid
        or heartbeat_age > 180
        or degraded
    ):
        system_status = "DEGRADED"
    else:
        system_status = "RUNNING"

    return {
        "system_status": system_status,
        "daemon_alive": daemon_alive,
        "supervisor_alive": supervisor_alive,
        "queue_length": len(queue),
        "last_signal_time": health.get("last_signal_time", "N/A"),
        "last_execution_time": health.get("last_execution_time", "N/A"),
        "heartbeat_age": None if heartbeat_age == float("inf") else round(heartbeat_age, 1),
        "watchdog_status": (
            "DEGRADED"
            if degraded
            else "HEALTHY"
            if heartbeat_age <= 180
            else "STALE"
        ),
        "execution_state": "PENDING" if queue else "IDLE",
    }


class HealthAPIHandler(QuantAPIHandler):
    def do_GET(self) -> None:
        if urlsplit(self.path).path == "/health":
            self._send_json(200, health_payload())
            return
        super().do_GET()


def create_server(host: str = "127.0.0.1", port: int = 8000) -> HTTPServer:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("health server may only bind to loopback")
    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    return HTTPServer((host, port), HealthAPIHandler)


def main() -> None:
    if os.environ.get("V1_SUPERVISED") != "1":
        raise RuntimeError("health_server can only be started by supervisor")
    if int(os.environ.get("V1_SUPERVISOR_PID", "0")) != os.getppid():
        raise RuntimeError("health_server parent is not supervisor")
    tree_lock = _read_json(Path("/tmp/usstock_v1.lock"), {})
    if tree_lock.get("supervisor_pid") != os.getppid():
        raise RuntimeError("health_server is outside the locked process tree")
    parser = argparse.ArgumentParser(description="V1.9 health API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = create_server(args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
