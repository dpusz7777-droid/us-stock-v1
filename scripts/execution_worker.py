#!/usr/bin/env python3
"""
Execution Worker — 基础模拟交易引擎 V1.2 (Paper Trading) — Daemon Mode

每 1 秒循环：
1. 读取 runtime/signals.json → 获取最新 signal（action + symbol + score）
2. 根据 action 执行模拟交易（BUY/SELL/HOLD）
3. 写入 runtime/portfolio.json（现金 + 持仓 + 浮动盈亏）
4. 写入 runtime/executed_log.json（执行历史）
5. 仅从未执行过的 cycle_id 生成交易（幂等性）

交易规则（纯模拟 paper trading）：
- 初始资金: 100,000 USD
- BUY:  固定金额 1000 USD，价格 = 100 + score * 0.1
- SELL: 卖出当前持仓的 50%
- HOLD: 不操作

幂等保证：
- 使用 executed_cycles set 记录已处理 cycle_id
- 同一 cycle_id 永不重复执行
- HOLD 不产生交易但记录已消费

不依赖 daemon / signal worker / report / backtest。
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── 路径 ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parents[1]
SIGNALS_FILE = BASE_DIR / "runtime" / "signals.json"
PORTFOLIO_FILE = BASE_DIR / "runtime" / "portfolio.json"
EXECUTED_LOG_FILE = BASE_DIR / "runtime" / "executed_log.json"
CYCLE = 1  # seconds
INITIAL_CASH = 100000.0  # 初始虚拟资金
BUY_FIXED_USD = 1000.0   # 每笔 BUY 固定投入金额


# ── 工具函数 ───────────────────────────────────────────────────────────────

def read_json(path: Path, default=None):
    """安全读取 JSON 文件。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default if default is not None else {}


def write_json(path: Path, data) -> None:
    """原子写入 JSON 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_portfolio() -> dict:
    """加载虚拟账户。
    
    Returns:
        dict: {"cash": float, "positions": {symbol: {qty, avg_price}}, ...}
    """
    data = read_json(PORTFOLIO_FILE, default={})
    if not isinstance(data, dict) or not data:
        return {"cash": INITIAL_CASH, "positions": {}}
    if "cash" not in data:
        data["cash"] = INITIAL_CASH
    if "positions" not in data:
        data["positions"] = {}
    return data


def save_portfolio(portfolio: dict) -> None:
    """保存虚拟账户（现金 + 持仓 + 浮动盈亏）。"""
    # 计算浮动盈亏
    unrealized_pnl = 0.0
    positions = portfolio.get("positions", {})
    for sym, pos in positions.items():
        qty = pos.get("qty", 0)
        avg_price = pos.get("avg_price", 0)
        # 用 score 映射的当前价格估算最新市值
        current_price = _current_price_for(sym, avg_price)
        unrealized_pnl += round((current_price - avg_price) * qty, 2)
    
    payload = {
        "cash": round(portfolio.get("cash", INITIAL_CASH), 2),
        "positions": positions,
        "unrealized_pnl": round(unrealized_pnl, 2),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(PORTFOLIO_FILE, payload)


def _latest_score() -> float:
    """从 signals.json 读取最新 score，用于模拟价格映射。"""
    try:
        data = read_json(SIGNALS_FILE, default={})
        signals = data.get("signals", [])
        if signals and isinstance(signals, list):
            return float(signals[0].get("score", 50))
    except Exception:
        pass
    return 50.0


def _current_price_for(symbol: str, fallback_price: float = 100.0) -> float:
    """模拟当前价格: price = 100 + score * 0.1
    
    当没有 score 时使用 fallback_price。
    """
    score = _latest_score()
    return round(100.0 + score * 0.1, 2)


def load_executed_log() -> list:
    """加载执行历史。"""
    data = read_json(EXECUTED_LOG_FILE, default={"trades": []})
    if not isinstance(data, dict):
        return []
    return data.get("trades", [])


def save_executed_log(trades: list) -> None:
    """保存执行历史。"""
    write_json(EXECUTED_LOG_FILE, {
        "trades": trades,
    })


def execute_trade(task: dict, portfolio: dict, trades: list) -> tuple[dict, list]:
    """执行一笔模拟交易。返回 (更新后的 portfolio, 更新后的 trades)。
    
    交易规则（Paper Trading V1.2）:
        - BUY:  固定 1000 USD，price = 100 + score * 0.1
        - SELL: 卖出当前持仓的 50%
        - HOLD: 不操作
    """
    action = task.get("action", "HOLD")
    symbol = task.get("symbol", "")
    cycle_id = task.get("cycle_id", "")

    cash = portfolio.get("cash", INITIAL_CASH)
    positions = portfolio.get("positions", {})

    if not symbol or action == "HOLD":
        return portfolio, trades

    # ── v1 loop: read report_feedback score for tag ──
    _fb_tag: str = "neutral"
    try:
        _fb_path = BASE_DIR / ".runtime" / "report_feedback.json"
        if _fb_path.is_file():
            _fb_data = json.loads(_fb_path.read_text(encoding="utf-8"))
            _score = _fb_data.get("report_score", 50.0)
            if _score >= 80:
                _fb_tag = "strong"
            elif _score >= 60:
                _fb_tag = "positive"
            elif _score >= 40:
                _fb_tag = "neutral"
            elif _score >= 20:
                _fb_tag = "negative"
            else:
                _fb_tag = "poor"
    except Exception:
        _fb_tag = "neutral"

    trade_record = {
        "cycle_id": cycle_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "action": action,
        "report_feedback_tag": _fb_tag,
    }

    if action == "BUY":
        # ── 买入逻辑 ──
        # 检查现金是否足够
        if cash < BUY_FIXED_USD:
            trade_record["result"] = "skipped_insufficient_cash"
            trade_record["cash_before"] = round(cash, 2)
            trades.append(trade_record)
            return portfolio, trades

        price = _current_price_for(symbol)
        shares = int(BUY_FIXED_USD / price)  # 向下取整
        if shares <= 0:
            trade_record["result"] = "skipped_zero_shares"
            trades.append(trade_record)
            return portfolio, trades

        cost = round(shares * price, 2)
        cash -= cost

        if symbol in positions:
            pos = positions[symbol]
            total_qty = pos["qty"] + shares
            total_cost = pos["avg_price"] * pos["qty"] + cost
            avg_price = round(total_cost / total_qty, 2)
            positions[symbol] = {"qty": total_qty, "avg_price": avg_price}
        else:
            positions[symbol] = {"qty": shares, "avg_price": price}

        trade_record["shares"] = shares
        trade_record["price"] = price
        trade_record["cost"] = cost
        trade_record["cash_after"] = round(cash, 2)
        trade_record["result"] = "filled"

        print(f"[ACTION] BUY {symbol} | qty={shares} | price={price} | cash={round(cash, 2)}", flush=True)

    elif action == "SELL":
        # ── 卖出逻辑 ──
        if symbol in positions and positions[symbol]["qty"] > 0:
            pos = positions[symbol]
            current_qty = pos["qty"]
            # 卖出 50%（至少 1 股）
            sell_qty = max(1, int(current_qty * 0.5))
            # 确保不超卖
            if sell_qty > current_qty:
                sell_qty = current_qty

            price = _current_price_for(symbol)
            proceeds = round(sell_qty * price, 2)
            cost_basis = round(sell_qty * pos["avg_price"], 2)
            pnl = round(proceeds - cost_basis, 2)
            cash += proceeds

            remaining = current_qty - sell_qty
            if remaining <= 0:
                del positions[symbol]
            else:
                positions[symbol] = {"qty": remaining, "avg_price": pos["avg_price"]}

            trade_record["shares"] = sell_qty
            trade_record["price"] = price
            trade_record["proceeds"] = proceeds
            trade_record["cost_basis"] = cost_basis
            trade_record["pnl"] = pnl
            trade_record["cash_after"] = round(cash, 2)
            trade_record["result"] = "filled"

            print(f"[ACTION] SELL {symbol} | qty={sell_qty} | pnl={pnl} | cash={round(cash, 2)}", flush=True)
        else:
            trade_record["result"] = "skipped_no_position"
            print(f"[ACTION] SELL {symbol} | skipped (no position)", flush=True)

    trades.append(trade_record)

    # 更新 portfolio
    portfolio["cash"] = cash
    portfolio["positions"] = positions
    return portfolio, trades


# ── 主循环 ─────────────────────────────────────────────────────────────────

def main() -> None:
    # 确保目录存在
    PORTFOLIO_FILE.parent.mkdir(parents=True, exist_ok=True)

    print(f"[ExecutionWorker] 启动 (daemon) | 周期={CYCLE}s | 读取: {SIGNALS_FILE.name}")

    # 从持久化执行历史恢复已执行 cycle_id，重启后仍保持幂等。
    executed_cycles: set[str] = {
        str(trade.get("cycle_id"))
        for trade in load_executed_log()
        if trade.get("cycle_id")
    }

    while True:
        try:
            print("[ExecutionWorker] heartbeat", flush=True)

            # 1. 读取 signals.json
            signals_data = read_json(SIGNALS_FILE, default={"signals": []})
            cycle_id = signals_data.get("cycle_id", "")
            signals = signals_data.get("signals", [])

            # 2. 幂等检查：同一 cycle 已处理则跳过
            if not cycle_id or cycle_id in executed_cycles or not signals:
                time.sleep(CYCLE)
                continue

            # 3. 加载虚拟账户和执行历史
            portfolio = load_portfolio()
            trades = load_executed_log()

            changed = False

            for sig in signals:
                action = sig.get("action", "HOLD")
                symbol = sig.get("symbol", "")

                # 构造与 execute_trade 兼容的 task dict
                task = {
                    "cycle_id": cycle_id,
                    "symbol": symbol,
                    "action": action,
                }

                # 执行交易
                portfolio, trades = execute_trade(task, portfolio, trades)

                if action != "HOLD":
                    changed = True

                print(f"[{cycle_id}] {action} {symbol} | cash={round(portfolio.get('cash', 0), 2)} | positions={len(portfolio.get('positions', {}))}", flush=True)

            # 4. 持久化
            if changed:
                save_portfolio(portfolio)
                save_executed_log(trades)

            # 5. 记录已处理
            executed_cycles.add(cycle_id)

        except KeyboardInterrupt:
            print("\n[ExecutionWorker] 停止")
            sys.exit(0)
        except Exception as e:
            print(f"[ExecutionWorker] error: {e}", flush=True)

        time.sleep(CYCLE)


if __name__ == "__main__":
    main()
