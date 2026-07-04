#!/usr/bin/env python3
"""
US Stock V1.9 — System Monitor (CLI Dashboard)

Read-only observer that displays a real-time system status panel.
Refreshes every 1 second. Uses only Python standard library.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HEARTBEAT_FILE = os.path.join(BASE_DIR, "state", "heartbeat.json")
STATE_SNAPSHOT_FILE = os.path.join(BASE_DIR, "state_snapshot.json")
EXECUTION_QUEUE_FILE = os.path.join(BASE_DIR, "execution_queue.json")


# ── Helpers ────────────────────────────────────────────────────────────────

def read_json(path, default=None):
    """Read a JSON file safely. Returns *default* on any failure."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default if default is not None else {}


def parse_iso_timestamp(ts_str):
    """Parse an ISO-8601 timestamp string -> datetime (UTC)."""
    if not ts_str:
        return None
    # Handle both 'Z' suffix and '+00:00' suffix
    ts_str = ts_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return None


def seconds_since(ts_str):
    """Return seconds from the given ISO timestamp to now (float)."""
    dt = parse_iso_timestamp(ts_str)
    if dt is None:
        return None
    now = datetime.now(timezone.utc)
    return (now - dt).total_seconds()


def find_last_cycle(cycles, prefix):
    """Find the most recent cycle whose cycle_id starts with *prefix*."""
    candidates = []
    for cid, info in cycles.items():
        if cid.startswith(prefix):
            candidates.append((cid, info))
    if not candidates:
        return None, None
    # Sort by recorded_at descending
    candidates.sort(key=lambda x: x[1].get("recorded_at", 0), reverse=True)
    return candidates[0]


def clear_screen():
    """Clear the terminal (ANSI escape – works on macOS / Linux)."""
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


# ── Main Loop ──────────────────────────────────────────────────────────────

def main():
    # Detect terminal width for the horizontal lines
    term_width = 80
    try:
        term_width = os.get_terminal_size().columns
    except OSError:
        pass
    rule = "═" * term_width

    while True:
        try:
            # 1. Read state files ───────────────────────────────────────────
            heartbeat = read_json(HEARTBEAT_FILE)
            snapshot = read_json(STATE_SNAPSHOT_FILE)
            exec_queue = read_json(EXECUTION_QUEUE_FILE, default={"queue": []})

            cycles = snapshot.get("cycles", {})
            health = snapshot.get("last_health", {})

            # 2. Heartbeat ──────────────────────────────────────────────────
            hb_ts = heartbeat.get("timestamp", "")
            hb_seconds = seconds_since(hb_ts)
            hb_cycle = heartbeat.get("cycle_id", "N/A")

            if hb_seconds is None:
                daemon_status = "IDLE"
                hb_display = "N/A"
            elif hb_seconds < 10:
                daemon_status = "RUNNING"
                hb_display = f"{hb_seconds:.0f}s"
            elif hb_seconds <= 60:
                daemon_status = "IDLE"
                hb_display = f"{hb_seconds:.0f}s"
            else:
                daemon_status = "STUCK"
                hb_display = f"{hb_seconds:.0f}s"

            # 3. Signal Engine ──────────────────────────────────────────────
            last_sig_id, last_sig_info = find_last_cycle(cycles, "S")
            last_signal_cycle = last_sig_id if last_sig_id else "N/A"
            # Active = signal cycle exists and heartbeat is RUNNING/IDLE
            signal_active = "YES" if last_sig_id and daemon_status != "STUCK" else "NO"

            # 4. Execution Queue ────────────────────────────────────────────
            queue = exec_queue.get("queue", [])
            queue_size = len(queue)

            last_exec_id, last_exec_info = find_last_cycle(cycles, "ES")
            last_exec_cycle = last_exec_id if last_exec_id else "N/A"

            # 5. Report ─────────────────────────────────────────────────────
            # Look for report cycles (Rxxxx) in the cycles dict
            last_report_id, _ = find_last_cycle(cycles, "R")
            report_pending = "NO"
            if health.get("module_stats", {}).get("report", {}).get("ok", 0) > 0:
                report_pending = "YES"
            # If signal_count_since_report > threshold, report is pending
            sig_since_report = health.get("signal_count_since_report", 0)
            threshold = health.get("report_signal_threshold", 5)
            if sig_since_report >= threshold:
                report_pending = "YES"

            # 6. Watchdog ───────────────────────────────────────────────────
            wd = health.get("watchdog", {})
            consecutive_skips = wd.get("consecutive_skips", 0)
            elapsed_since_beat = wd.get("elapsed_since_last_beat", 0)
            if consecutive_skips > 2 or elapsed_since_beat > 120:
                watchdog_status = "WARNING"
            else:
                watchdog_status = "OK"

            # ── Render Dashboard ───────────────────────────────────────────
            clear_screen()

            # Title
            print(rule)
            print("  🟢  US STOCK V1.9  SYSTEM MONITOR")
            print(rule)

            # Daemon Status
            print()
            print("  Daemon Status:")
            print(f"    - Last Heartbeat:    {hb_display} ago  [{hb_cycle}]")
            status_icon = {"RUNNING": "🟢", "IDLE": "🟡", "STUCK": "🔴"}
            print(f"    - Status:            {status_icon.get(daemon_status, '⚪')} {daemon_status}")

            # Signal Engine
            print()
            print("  Signal Engine:")
            print(f"    - Last Signal Cycle: {last_signal_cycle}")
            active_icon = {"YES": "✅", "NO": "❌"}
            print(f"    - Active:            {active_icon.get(signal_active, '❌')} {signal_active}")

            # Execution Queue
            print()
            print("  Execution Queue:")
            print(f"    - Queue Size:        {queue_size}")
            print(f"    - Last Execution:    {last_exec_cycle}")

            # Report
            print()
            print("  Report:")
            print(f"    - Last Report:       {last_report_id if last_report_id else 'N/A'}")
            pending_icon = {"YES": "⚠️  YES", "NO": "✅ NO"}
            print(f"    - Pending:           {pending_icon.get(report_pending, '❌ NO')}")

            # Watchdog
            print()
            print("  Watchdog:")
            wd_icon = {"OK": "✅", "WARNING": "⚠️"}
            print(f"    - Status:            {wd_icon.get(watchdog_status, '⚠️')} {watchdog_status}")
            print(f"    - Consecutive Skips: {consecutive_skips}")

            # Footer
            print()
            print(rule)
            print(f"  🔄 Refreshing every 1s  |  Press Ctrl+C to exit")
            print(rule)

        except KeyboardInterrupt:
            print("\n\n  System monitor stopped.\n")
            sys.exit(0)
        except Exception:
            # Silent catch: never crash the monitor, just retry
            pass

        time.sleep(1)


if __name__ == "__main__":
    main()
