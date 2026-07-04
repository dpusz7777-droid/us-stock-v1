#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V1.8 Supervisor Layer — lightweight process management and self-healing."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import socket
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Callable
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
PID_DIR = RUNTIME / "pids"
LOG_DIR = RUNTIME / "logs"
RUNTIME_LOG = ROOT / "logs" / "runtime.log"
SUPERVISOR_PID = PID_DIR / "supervisor.pid"
LAST_REPORT_BRIDGE = RUNTIME / "last_report.json"
SUPERVISOR_LOCK = Path("/tmp/usstock_v1.lock")
API_HOST = "127.0.0.1"
API_PORT = 8000
HEALTH_INTERVAL = 10.0
MAX_RESTARTS = 3
REPORT_INTERVAL = 600.0


class Supervisor:
    """Own, observe and recover the project's three background services."""

    SERVICES = ("api", "daemon", "report")

    def __init__(
        self,
        health_interval: float = HEALTH_INTERVAL,
        max_restarts: int = MAX_RESTARTS,
    ) -> None:
        self.health_interval = health_interval
        self.max_restarts = max_restarts
        self._stopping = False
        self._lock_stream = None
        self._restart_counts = {name: 0 for name in self.SERVICES}
        self._ensure_dirs()

    @staticmethod
    def _ensure_dirs() -> None:
        PID_DIR.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        RUNTIME_LOG.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _pid_file(service: str) -> Path:
        return PID_DIR / f"{service}.pid"

    @staticmethod
    def _read_pid(path: Path) -> int | None:
        try:
            pid = int(path.read_text(encoding="utf-8").strip())
            return pid if pid > 1 else None
        except (OSError, ValueError):
            return None

    @staticmethod
    def _alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        try:
            state = subprocess.run(
                ["ps", "-p", str(pid), "-o", "stat="],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return True
        return bool(state) and "Z" not in state

    @staticmethod
    def _command(pid: int) -> str:
        try:
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return " ".join(result.stdout.split())

    @staticmethod
    def _matches(command: str, service: str | None = None) -> bool:
        signatures = {
            "api": (
                "health_server.py",
                "api_server.py",
                "uvicorn api_server:",
                "uvicorn api_server.",
            ),
            "daemon": ("daemon_runner.py", "main.py run --mode daemon"),
            "report": ("supervisor.py _report_worker",),
            "supervisor": ("supervisor.py start",),
        }
        selected = signatures.get(service, sum(signatures.values(), ()))
        return bool(command) and any(token in command for token in selected)

    def _managed_pid(self, service: str) -> int | None:
        path = self._pid_file(service)
        pid = self._read_pid(path)
        if (
            pid
            and self._alive(pid)
            and self._matches(self._command(pid), service)
            and (
                self._lock_stream is None
                or self._is_descendant(pid, os.getpid())
            )
        ):
            return pid
        path.unlink(missing_ok=True)
        return None

    @staticmethod
    def _service_command(service: str) -> list[str]:
        if service == "api":
            return [
                sys.executable,
                str(ROOT / "scripts" / "health_server.py"),
                "--host",
                API_HOST,
                "--port",
                str(API_PORT),
            ]
        if service == "daemon":
            return [sys.executable, str(ROOT / "daemon_runner.py")]
        if service == "report":
            return [
                sys.executable,
                str(Path(__file__).resolve()),
                "_report_worker",
            ]
        raise ValueError(f"unknown service: {service}")

    def _spawn(self, service: str) -> int:
        log = RUNTIME_LOG.open("ab", buffering=0)
        try:
            environment = os.environ.copy()
            environment["V1_SUPERVISED"] = "1"
            environment["V1_EXTERNAL_REPORT_WORKER"] = "1"
            environment["V1_SUPERVISOR_PID"] = str(os.getpid())
            process = subprocess.Popen(
                self._service_command(service),
                cwd=str(ROOT),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
                env=environment,
            )
        finally:
            log.close()
        self._pid_file(service).write_text(f"{process.pid}\n", encoding="utf-8")
        self._write_tree_lock()
        self._log(f"started {service} pid={process.pid}")
        return process.pid

    @staticmethod
    def _api_health() -> bool:
        try:
            with urlopen(
                f"http://{API_HOST}:{API_PORT}/health",
                timeout=2,
            ) as response:
                if response.status != 200:
                    return False
                payload = json.loads(response.read().decode("utf-8"))
                return payload.get("system_status") in {"RUNNING", "DEGRADED"}
        except (OSError, URLError, ValueError, json.JSONDecodeError):
            return False

    @staticmethod
    def _port_open() -> bool:
        try:
            with socket.create_connection((API_HOST, API_PORT), timeout=0.4):
                return True
        except OSError:
            return False

    @staticmethod
    def _log(message: str) -> None:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with RUNTIME_LOG.open("a", encoding="utf-8") as stream:
            stream.write(f"{stamp} | SUPERVISOR | {message}\n")

    def _acquire_lock(self) -> bool:
        """Hold a kernel-backed production lock for the supervisor lifetime."""
        stream = SUPERVISOR_LOCK.open("a+", encoding="utf-8")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            stream.close()
            return False
        self._lock_stream = stream
        self._write_tree_lock()
        return True

    def _write_tree_lock(self) -> None:
        """Persist the live supervisor-owned process tree in the held lock."""
        if self._lock_stream is None:
            return
        daemon_pid = self._read_pid(self._pid_file("daemon"))
        api_pid = self._read_pid(self._pid_file("api"))
        payload = {
            "supervisor_pid": os.getpid(),
            "daemon_runner_pid": (
                daemon_pid if daemon_pid and self._alive(daemon_pid) else None
            ),
            "api_server": {
                "pid": api_pid if api_pid and self._alive(api_pid) else None,
                "status": (
                    "managed"
                    if api_pid
                    and self._alive(api_pid)
                    and self._is_descendant(api_pid, os.getpid())
                    else "stopped"
                ),
            },
        }
        self._lock_stream.seek(0)
        self._lock_stream.truncate()
        json.dump(payload, self._lock_stream, ensure_ascii=False)
        self._lock_stream.write("\n")
        self._lock_stream.flush()
        os.fsync(self._lock_stream.fileno())

    def _release_lock(self) -> None:
        if self._lock_stream is not None:
            try:
                fcntl.flock(self._lock_stream.fileno(), fcntl.LOCK_UN)
            finally:
                self._lock_stream.close()
                self._lock_stream = None
        SUPERVISOR_LOCK.unlink(missing_ok=True)

    @staticmethod
    def _process_table() -> dict[int, tuple[int, str]]:
        try:
            result = subprocess.run(
                ["ps", "ax", "-o", "pid=,ppid=,command="],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return {}
        table: dict[int, tuple[int, str]] = {}
        for line in result.stdout.splitlines():
            columns = line.strip().split(None, 2)
            if len(columns) != 3:
                continue
            try:
                table[int(columns[0])] = (int(columns[1]), columns[2])
            except ValueError:
                continue
        return table

    @classmethod
    def _is_descendant(
        cls,
        pid: int,
        root_pid: int,
        table: dict[int, tuple[int, str]] | None = None,
    ) -> bool:
        processes = table if table is not None else cls._process_table()
        seen: set[int] = set()
        current = pid
        while current > 1 and current not in seen:
            if current == root_pid:
                return True
            seen.add(current)
            current = processes.get(current, (0, ""))[0]
        return False

    def _remove_orphan_workers(self) -> int:
        """Kill project workers that are not descendants of this supervisor."""
        table = self._process_table()
        signatures = (
            "daemon_runner.py",
            "scripts/health_server.py",
            "supervisor.py _report_worker",
            "api_server.py",
            "main.py run --mode daemon",
        )
        removed = 0
        for pid, (_parent, command) in table.items():
            if str(ROOT) not in command or not any(item in command for item in signatures):
                continue
            if self._is_descendant(pid, os.getpid(), table):
                continue
            try:
                os.kill(pid, signal.SIGTERM)
                removed += 1
                self._log(f"removed orphan worker pid={pid}")
            except (ProcessLookupError, PermissionError):
                continue
        if removed:
            time.sleep(0.2)
            for pid, (_parent, command) in table.items():
                if (
                    str(ROOT) in command
                    and any(item in command for item in signatures)
                    and not self._is_descendant(pid, os.getpid())
                    and self._alive(pid)
                ):
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass
            for service in self.SERVICES:
                pid = self._read_pid(self._pid_file(service))
                if pid and not self._is_descendant(pid, os.getpid()):
                    self._pid_file(service).unlink(missing_ok=True)
        return removed

    @staticmethod
    def _runtime_self_check(since: float) -> dict[str, bool]:
        signal_ok = execution_ok = queue_ok = False
        try:
            snapshot = json.loads(
                (ROOT / "state_snapshot.json").read_text(encoding="utf-8")
            )
            cycles = snapshot.get("cycles", {}).values()
            signal_ok = any(
                item.get("type") == "signal"
                and item.get("status") == "completed"
                and float(item.get("recorded_at", 0)) >= since
                for item in cycles
            )
            execution_ok = any(
                item.get("type") == "execution"
                and item.get("status") == "completed"
                and float(item.get("recorded_at", 0)) >= since
                for item in cycles
            )
            queue = json.loads(
                (ROOT / "execution_queue.json").read_text(encoding="utf-8")
            ).get("queue")
            queue_ok = isinstance(queue, list) and all(
                isinstance(item, dict)
                and item.get("status", "pending") == "pending"
                for item in queue
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
        return {
            "signal": signal_ok,
            "execution": execution_ok and queue_ok,
            "report": True,
        }

    @staticmethod
    def _wait_for(check: Callable[[], bool], timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if check():
                return True
            time.sleep(0.1)
        return check()

    def start(self) -> int:
        """Run the single production supervisor in the foreground."""
        existing_monitor = self._read_pid(SUPERVISOR_PID)
        if (
            existing_monitor
            and self._alive(existing_monitor)
            and self._matches(self._command(existing_monitor), "supervisor")
        ):
            print("✔ SUPERVISOR ALREADY ACTIVE")
            return 0
        if not self._acquire_lock():
            print("❌ SUPERVISOR ALREADY ACTIVE")
            return 1
        SUPERVISOR_PID.write_text(f"{os.getpid()}\n", encoding="utf-8")

        def request_stop(_signum: int, _frame: object) -> None:
            self._stopping = True

        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)

        started_at = time.time()
        self._remove_orphan_workers()
        failures: list[str] = []
        for service in self.SERVICES:
            if self._managed_pid(service):
                continue
            if service == "api" and self._port_open():
                failures.append("port 8000 is occupied by an unmanaged process")
                continue
            self._spawn(service)

        checks = {
            "api": self._wait_for(self._api_health),
            "daemon": self._wait_for(lambda: bool(self._managed_pid("daemon"))),
            "report": self._wait_for(lambda: bool(self._managed_pid("report"))),
        }
        for service, ok in checks.items():
            print(f"{'✔' if ok else '❌'} {service.upper()} "
                  f"{'RUNNING' if ok else 'FAILED'}")
        for failure in failures:
            print(f"❌ {failure}")
        if not all(checks.values()) or failures:
            self._shutdown_children()
            SUPERVISOR_PID.unlink(missing_ok=True)
            self._release_lock()
            print("❌ SUPERVISOR START FAILED")
            return 1

        runtime_checks = {"signal": False, "execution": False, "report": True}
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            runtime_checks = self._runtime_self_check(started_at)
            if all(runtime_checks.values()):
                break
            time.sleep(0.2)
        if not all(runtime_checks.values()):
            self._shutdown_children()
            SUPERVISOR_PID.unlink(missing_ok=True)
            self._release_lock()
            print("❌ RUNTIME SELF CHECK FAILED")
            return 1

        print("✔ SUPERVISOR ACTIVE")
        try:
            self.health_check_loop()
        except Exception:
            self._log(f"supervisor loop crash\n{traceback.format_exc()}")
            return_code = 1
        else:
            return_code = 0
        finally:
            self._shutdown_children()
            SUPERVISOR_PID.unlink(missing_ok=True)
            self._release_lock()
        return return_code

    @staticmethod
    def _ps_python() -> list[tuple[int, str]]:
        """Use `ps aux`, then apply the grep-python equivalent safely in Python."""
        try:
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        found: list[tuple[int, str]] = []
        for line in result.stdout.splitlines()[1:]:
            columns = line.split(None, 10)
            if len(columns) < 11 or "python" not in columns[10].lower():
                continue
            try:
                found.append((int(columns[1]), columns[10]))
            except ValueError:
                pass
        return found

    def _terminate(self, pid: int, service: str | None = None) -> bool:
        if not self._alive(pid):
            return True
        command = self._command(pid)
        if not command and not self._alive(pid):
            return True
        if (
            pid in {os.getpid(), os.getppid()}
            or not self._matches(command, service)
        ):
            return False
        # PID-file processes are session leaders created by _spawn. Signalling
        # their process group also cleans up a report task currently in flight.
        send_signal = (
            (lambda sig: os.killpg(pid, sig))
            if service in self.SERVICES
            else (lambda sig: os.kill(pid, sig))
        )
        try:
            send_signal(signal.SIGTERM)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if not self._alive(pid):
                return True
            time.sleep(0.1)
        try:
            send_signal(signal.SIGKILL)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        return not self._alive(pid)

    def stop(self) -> int:
        """Stop monitor first, then PID-owned services, then safe fallbacks."""
        self._stopping = True
        stopped: set[int] = set()
        failed: set[int] = set()

        supervisor_pid = self._read_pid(SUPERVISOR_PID)
        if supervisor_pid and self._alive(supervisor_pid):
            try:
                os.kill(supervisor_pid, signal.SIGTERM)
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline and self._alive(supervisor_pid):
                    time.sleep(0.1)
                if self._alive(supervisor_pid):
                    failed.add(supervisor_pid)
                else:
                    stopped.add(supervisor_pid)
            except (ProcessLookupError, PermissionError):
                if self._alive(supervisor_pid):
                    failed.add(supervisor_pid)

        for service in self.SERVICES:
            path = self._pid_file(service)
            pid = self._read_pid(path)
            if pid and self._alive(pid):
                target = stopped if self._terminate(pid, service) else failed
                target.add(pid)
            path.unlink(missing_ok=True)

        # Fallback only targets the exact project entry signatures.
        for pid, command in self._ps_python():
            if pid not in stopped and self._matches(command):
                terminated = self._terminate(pid)
                if terminated:
                    stopped.add(pid)
                elif self._alive(pid):
                    failed.add(pid)

        self._log(f"stop completed stopped={sorted(stopped)} failed={sorted(failed)}")
        print(f"✔ stopped {len(stopped)} managed process(es)")
        if failed:
            print("❌ failed to stop PID: " + ", ".join(map(str, sorted(failed))))
            return 1
        print("✔ SYSTEM STOPPED")
        return 0

    def _shutdown_children(self) -> None:
        """Terminate every owned process group before supervisor exits."""
        self._stopping = True
        for service in self.SERVICES:
            pid = self._read_pid(self._pid_file(service))
            if pid:
                self._terminate(pid, service)
            self._pid_file(service).unlink(missing_ok=True)

    def _zombies(self) -> list[tuple[int, str]]:
        try:
            result = subprocess.run(
                ["ps", "ax", "-o", "pid=,stat=,command="],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        zombies: list[tuple[int, str]] = []
        for line in result.stdout.splitlines():
            columns = line.strip().split(None, 2)
            if len(columns) == 3 and "Z" in columns[1] and self._matches(columns[2]):
                try:
                    zombies.append((int(columns[0]), columns[2]))
                except ValueError:
                    pass
        return zombies

    def status(self) -> int:
        supervisor_pid = self._read_pid(SUPERVISOR_PID)
        states = {
            "SUPERVISOR": bool(
                supervisor_pid
                and self._alive(supervisor_pid)
                and self._matches(self._command(supervisor_pid), "supervisor")
            ),
            "API": bool(self._managed_pid("api")) and self._api_health(),
            "DAEMON": bool(self._managed_pid("daemon")),
            "REPORT": bool(self._managed_pid("report")),
            "PROCESS_TREE": all(
                not (pid := self._managed_pid(service))
                or self._is_descendant(pid, supervisor_pid or 0)
                for service in self.SERVICES
            ),
        }
        for name, ok in states.items():
            print(f"{'✔' if ok else '❌'} {name}: {'healthy' if ok else 'down'}")
        zombies = self._zombies()
        if zombies:
            print(f"❌ ZOMBIES: {len(zombies)}")
            for pid, command in zombies:
                print(f"  PID {pid}: {command}")
        else:
            print("✔ ZOMBIES: none")
        return 0 if all(states.values()) and not zombies else 1

    def _restart(self, service: str) -> bool:
        count = self._restart_counts[service]
        if count >= self.max_restarts:
            self._log(f"{service} restart limit reached ({self.max_restarts})")
            return False
        delay = 2 ** count
        self._restart_counts[service] += 1
        self._log(
            f"{service} unhealthy; restart "
            f"{self._restart_counts[service]}/{self.max_restarts} in {delay}s"
        )
        time.sleep(delay)
        if self._stopping:
            return False
        pid = self._managed_pid(service)
        if pid:
            self._terminate(pid, service)
        self._pid_file(service).unlink(missing_ok=True)
        if service == "api" and self._port_open():
            self._log("api restart blocked: port 8000 occupied")
            return False
        self._spawn(service)
        check = self._api_health if service == "api" else lambda: bool(
            self._managed_pid(service)
        )
        return self._wait_for(check)

    @staticmethod
    def _heartbeat_healthy() -> bool:
        try:
            heartbeat = json.loads(
                (ROOT / "state" / "heartbeat.json").read_text(encoding="utf-8")
            )
            timestamp = str(heartbeat["timestamp"]).replace("Z", "+00:00")
            from datetime import datetime, timezone

            age = (
                datetime.now(timezone.utc)
                - datetime.fromisoformat(timestamp).astimezone(timezone.utc)
            ).total_seconds()
            return age < 180
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return False

    def health_check_loop(self) -> None:
        """Check every service and self-heal with capped exponential backoff."""
        while not self._stopping:
            self._remove_orphan_workers()
            for service in self.SERVICES:
                pid_ok = bool(self._managed_pid(service))
                healthy = pid_ok
                if service == "api":
                    healthy = healthy and self._api_health()
                elif service == "daemon":
                    healthy = healthy and self._heartbeat_healthy()
                if healthy:
                    self._restart_counts[service] = 0
                    continue
                recovered = self._restart(service)
                self._log(f"{service} recovery={'ok' if recovered else 'failed'}")
                if (
                    not recovered
                    and self._restart_counts[service] >= self.max_restarts
                ):
                    raise RuntimeError(
                        f"{service} recovery exhausted; restarting supervisor"
                    )
            self._write_tree_lock()
            time.sleep(self.health_interval)

    def logs(self, lines: int = 50) -> int:
        try:
            content = RUNTIME_LOG.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()
        except OSError as exc:
            print(f"❌ unable to read {RUNTIME_LOG}: {exc}")
            return 1
        for line in content[-lines:]:
            print(line)
        return 0


def report_worker() -> int:
    """Periodically invoke the existing report entry; calculations stay untouched."""
    if os.environ.get("V1_SUPERVISED") != "1":
        raise RuntimeError("report worker can only be started by supervisor")
    if int(os.environ.get("V1_SUPERVISOR_PID", "0")) != os.getppid():
        raise RuntimeError("report worker parent is not supervisor")
    try:
        tree_lock = json.loads(SUPERVISOR_LOCK.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("report worker missing process tree lock") from exc
    if tree_lock.get("supervisor_pid") != os.getppid():
        raise RuntimeError("report worker is outside the locked process tree")
    cycle_number = 0
    while True:
        cycle_number += 1
        cycle_id = f"REPORT-WORKER-{cycle_number:06d}"
        Supervisor._log(f"[{cycle_id}] report | started")
        try:
            result = subprocess.run(
                [sys.executable, str(ROOT / "main.py"), "report"],
                cwd=str(ROOT),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=120,
                check=False,
            )
            with RUNTIME_LOG.open("a", encoding="utf-8") as stream:
                for line in result.stdout.splitlines():
                    stream.write(f"[{cycle_id}] report | {line}\n")
            if result.returncode:
                Supervisor._log(
                    f"[{cycle_id}] report | failed | code={result.returncode}"
                )
            else:
                # ── 写入 bridge 文件 ──
                try:
                    LAST_REPORT_BRIDGE.parent.mkdir(parents=True, exist_ok=True)
                    bridge = {
                        "success": True,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "cycle_id": cycle_id,
                    }
                    tmp = LAST_REPORT_BRIDGE.with_suffix(".tmp")
                    tmp.write_text(json.dumps(bridge, ensure_ascii=False) + "\n", encoding="utf-8")
                    tmp.replace(LAST_REPORT_BRIDGE)
                except OSError:
                    Supervisor._log(f"[{cycle_id}] report | bridge write failed")

                # ── v1 loop: report → feedback ──
                try:
                    sys.path.insert(0, str(ROOT))
                    from scripts.report_feedback import update_feedback  # type: ignore[import-untyped]
                    fb = update_feedback()
                    Supervisor._log(f"[{cycle_id}] report_feedback | score={fb['report_score']}")
                except Exception as exc:
                    Supervisor._log(f"[{cycle_id}] report_feedback | failed | {exc}")

                Supervisor._log(f"[{cycle_id}] report | completed")
        except subprocess.TimeoutExpired as exc:
            Supervisor._log(
                f"[{cycle_id}] report | timeout | {exc}\n{traceback.format_exc()}"
            )
        except Exception:
            Supervisor._log(
                f"[{cycle_id}] report | crash\n{traceback.format_exc()}"
            )
        time.sleep(REPORT_INTERVAL)


def main() -> int:
    parser = argparse.ArgumentParser(description="V1.8 Supervisor Layer")
    parser.add_argument("command", metavar="{start,stop,status,logs}")
    args = parser.parse_args()
    supervisor = Supervisor()
    if args.command == "start":
        return supervisor.start()
    if args.command == "stop":
        return supervisor.stop()
    if args.command == "status":
        return supervisor.status()
    if args.command == "logs":
        return supervisor.logs()
    if args.command == "_report_worker":
        return report_worker()
    parser.error(f"invalid command: {args.command!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
