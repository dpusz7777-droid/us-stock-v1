#!/usr/bin/env python3
"""
State Clock — 全局 cycle 时钟源（独立 daemon 进程）

每 1 秒执行一次：
1. cycle_id +1（从 000001 开始递增）
2. 写入 runtime/state_snapshot.json

供 realtime_signal_worker / execution_worker 作为统一时钟源。
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
SNAPSHOT_FILE = BASE_DIR / "runtime" / "state_snapshot.json"
CYCLE = 1  # seconds


def write_json(path: Path, data, *, atomic: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if atomic:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    else:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    # 确保 runtime/ 目录存在
    SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)

    # 重启时续接最后一个已发布的 cycle，避免复用历史 cycle_id。
    cycle_id = 0
    try:
        snapshot = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
        cycle_id = int(snapshot.get("cycle_id", 0))
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, ValueError):
        cycle_id = 0

    print(f"[StateClock] 启动 | 周期={CYCLE}s | 写入: {SNAPSHOT_FILE.name}")

    while True:
        try:
            cycle_id += 1
            cycle_id_str = str(cycle_id).zfill(6)
            now_str = datetime.now(timezone.utc).isoformat()

            payload = {
                "cycle_id": cycle_id_str,
                "timestamp": now_str,
            }
            write_json(SNAPSHOT_FILE, payload)

            print(f"[StateClock] cycle={cycle_id_str} ts={now_str}", flush=True)

        except KeyboardInterrupt:
            print("\n[StateClock] 停止")
            sys.exit(0)
        except Exception as e:
            print(f"[StateClock] error: {e}", flush=True)

        time.sleep(CYCLE)


if __name__ == "__main__":
    main()
