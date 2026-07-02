#!/usr/bin/env python3
"""
Realtime Signal Worker — 实时信号生成模块 v1.2 (Real-time Sim)

每 1 秒循环：
1. 独立实时 tick：使用内部计数器模拟 signal_count_since_report
2. 产生 BUILD/SELL/HOLD 信号
3. 写入 runtime/signals.json

信号逻辑 (轻度活跃模式)：
- compute_action: ≥80=SELL, 65-80=HOLD, <65=BUY
- 连续 3 次 HOLD 后注入 1 次 exploratory signal
- 无去重：每次 loop 都使用最新 state_snapshot.json 的 cycle_id

cycle_id 由 state_clock 写入的 state_snapshot.json 提供。
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── 路径 ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from providers import MarketTick, RealtimeSimProvider, SignalProvider
from strategies import BaseStrategy, MeanReversionStrategy, MomentumStrategy, StrategyResult

SIGNALS_FILE = BASE_DIR / "runtime" / "signals.json"
SNAPSHOT_FILE = BASE_DIR / "runtime" / "state_snapshot.json"
HEARTBEAT_FILE = BASE_DIR / "state" / "heartbeat.json"
CYCLE = 1  # seconds


def read_json(path: Path, default: dict | list | None = None):
    """安全读取 JSON 文件，不存在或损坏返回 default。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default if default is not None else {}


def write_json(path: Path, data, *, atomic: bool = True) -> None:
    """原子写入 JSON 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if atomic:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    else:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def vote(results: list[StrategyResult]) -> str:
    """Fuse strategy actions using BUY/SELL majority voting."""
    buy_count = sum(result["action"] == "BUY" for result in results)
    sell_count = sum(result["action"] == "SELL" for result in results)
    if buy_count > sell_count:
        return "BUY"
    if sell_count > buy_count:
        return "SELL"
    return "HOLD"


def weighted_average(results: list[StrategyResult]) -> int:
    """Return the equal-weight average score for all strategy opinions."""
    if not results:
        return 0
    return int(round(sum(result["score"] for result in results) / len(results)))


class TickSignalConverter:
    """Run strategies in parallel and fuse them into a compatible signal."""

    def __init__(self, strategies: list[BaseStrategy]) -> None:
        if len(strategies) < 2:
            raise ValueError("at least two strategies are required")
        self.strategies = strategies
        self.sim_cycle_count = 0

    def convert(self, tick: MarketTick) -> dict:
        self.sim_cycle_count += 1
        results = [strategy.generate(tick) for strategy in self.strategies]
        action = vote(results)
        score = weighted_average(results)
        signal = {
            "symbol": tick["symbol"],
            "price": tick["price"],
            "volume": tick["volume"],
            "timestamp": tick["timestamp"],
            "action": action,
            "score": score,
            "source": tick["source"],
            "signal_ok": self.sim_cycle_count,
            "exec_ok": self.sim_cycle_count,
            "delta": 1,
        }
        return signal


# ── 主循环 ─────────────────────────────────────────────────────────────────

def main() -> None:
    provider: SignalProvider = RealtimeSimProvider()
    strategies: list[BaseStrategy] = [
        MomentumStrategy(),
        MeanReversionStrategy(),
    ]
    converter = TickSignalConverter(strategies)

    # 确保 runtime/ 目录存在
    SIGNALS_FILE.parent.mkdir(parents=True, exist_ok=True)

    print(f"[RealtimeSignalWorker] 启动 | 周期={CYCLE}s | cycle 源={SNAPSHOT_FILE.name}")
    print(f"[RealtimeSignalWorker] Provider={provider.__class__.__name__} | source={provider.source}")
    print(f"[RealtimeSignalWorker] Strategies={','.join(type(strategy).__name__ for strategy in strategies)}")
    print(f"[RealtimeSignalWorker] 无去重 | 每轮读取最新 snapshot | 仅此进程写入 signals.json")

    while True:
        try:
            # 1. 每轮重新读取，不缓存 snapshot 或 cycle_id
            snapshot = read_json(SNAPSHOT_FILE, default={})
            cycle_id_str = snapshot.get("cycle_id")
            if not cycle_id_str:
                raise ValueError(f"{SNAPSHOT_FILE.name} 缺少有效 cycle_id")

            # 2. Provider 生成 MarketTick，worker 转换为兼容 signal
            tick = provider.next_tick()
            signal = converter.convert(tick)
            signals = [signal]

            # 5. 写入 runtime/signals.json（唯一写入源）
            payload = {
                "cycle_id": cycle_id_str,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": provider.source,
                "signals": signals,
            }
            write_json(SIGNALS_FILE, payload)

            # 6. 终端输出
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            for s in signals:
                extra = " [exploratory]" if s.get("exploratory") else ""
                print(
                    f"[MarketTick] {tick['symbol']} price={tick['price']} volume={tick['volume']} ts={tick['timestamp']}",
                    flush=True,
                )
                print(f"[RealtimeTick] cycle={cycle_id_str} ts={now_str} {s['symbol']}:{s['action']} score={s['score']} sim_cycle={s['signal_ok']}{extra}", flush=True)
            print(f"[WRITE] cycle_id={cycle_id_str} ts={now_str} action={signals[0]['action']} score={signals[0]['score']}", flush=True)

        except KeyboardInterrupt:
            print("\n[RealtimeSignalWorker] 停止")
            sys.exit(0)
        except Exception as e:
            print(f"[RealtimeSignalWorker] error: {e}", flush=True)

        time.sleep(CYCLE)


if __name__ == "__main__":
    main()
