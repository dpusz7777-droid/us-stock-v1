#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模拟交易引擎 — 基于 stock_selector 的 StockSignal 进行历史回测，不连接券商API，不执行真实交易。

用法：
    from northstar.backtest.paper_trading_engine import PaperTradingEngine
    engine = PaperTradingEngine(initial_capital=100000)
    engine.execute_signals(signals, price_data)
    report = engine.get_report()
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


class PaperTradingEngine:
    """模拟交易引擎。

    交易规则：
    - BUY信号开多仓
    - WATCH仅观察不交易
    - AVOID不交易
    - 默认持仓周期5天
    - 盈利+8%止盈
    - 亏损-5%止损
    """

    def __init__(self, initial_capital: float = 100000.0) -> None:
        self.initial_capital: float = initial_capital
        self.capital: float = initial_capital
        self.positions: list[dict[str, Any]] = []
        self.closed_trades: list[dict[str, Any]] = []
        self._position_id: int = 0

    def _next_position_id(self) -> int:
        self._position_id += 1
        return self._position_id

    def open_position(
        self,
        symbol: str,
        date: str,
        price: float,
        signal: dict[str, Any],
    ) -> dict[str, Any] | None:
        """根据信号开仓。

        Args:
            symbol: 股票代码
            date: 开仓日期
            price: 开仓价格
            signal: 信号字典

        Returns:
            position dict or None
        """
        signal_type = signal.get("signal", "WATCH")
        if signal_type != "BUY":
            return None

        position_size = min(self.capital * 0.2, self.capital)
        if position_size <= 0:
            return None

        pos = {
            "id": self._next_position_id(),
            "symbol": symbol,
            "entry_date": date,
            "entry_price": price,
            "exit_date": None,
            "exit_price": None,
            "position_size": round(position_size, 2),
            "signal_type": signal_type,
            "pnl_pct": 0.0,
            "pnl_abs": 0.0,
            "status": "OPEN",
            "confidence": signal.get("confidence", 0.0),
            "days_held": 0,
        }
        self.capital -= position_size
        self.positions.append(pos)
        return pos

    def close_position(
        self,
        position: dict[str, Any],
        date: str,
        price: float,
    ) -> dict[str, Any]:
        """平仓。

        Args:
            position: 持仓字典
            date: 平仓日期
            price: 平仓价格

        Returns:
            已平仓交易记录
        """
        entry_price = position["entry_price"]
        pos_size = position["position_size"]

        if entry_price > 0:
            pnl_pct = round((price - entry_price) / entry_price * 100, 2)
        else:
            pnl_pct = 0.0

        pnl_abs = round(pnl_pct / 100 * pos_size, 2)

        closed = {
            "id": position["id"],
            "symbol": position["symbol"],
            "entry_date": position["entry_date"],
            "entry_price": position["entry_price"],
            "exit_date": date,
            "exit_price": price,
            "position_size": pos_size,
            "signal_type": position["signal_type"],
            "pnl_pct": pnl_pct,
            "pnl_abs": pnl_abs,
            "status": "CLOSED",
            "confidence": position.get("confidence", 0.0),
            "days_held": 0,
        }

        # 计算持仓天数
        try:
            ed = datetime.strptime(position["entry_date"], "%Y-%m-%d")
            xd = datetime.strptime(date, "%Y-%m-%d")
            closed["days_held"] = (xd - ed).days
        except (ValueError, TypeError):
            closed["days_held"] = 0

        self.capital += pos_size + pnl_abs
        self.closed_trades.append(closed)
        self.positions.remove(position)
        return closed

    def update_positions(self, price_data: dict[str, list[float]]) -> None:
        """更新所有持仓的浮动盈亏。"""
        for pos in self.positions:
            symbol = pos["symbol"]
            prices = price_data.get(symbol, [])
            if prices:
                latest_price = prices[-1]
                pos["current_price"] = latest_price
                if pos["entry_price"] > 0:
                    pos["unrealized_pnl_pct"] = round(
                        (latest_price - pos["entry_price"]) / pos["entry_price"] * 100, 2
                    )
                    pos["unrealized_pnl_abs"] = round(
                        pos["unrealized_pnl_pct"] / 100 * pos["position_size"], 2
                    )

    def execute_signals(
        self,
        signals: list[dict[str, Any]],
        price_data: dict[str, list[float]],
    ) -> list[dict[str, Any]]:
        """执行模拟交易，支持止盈止损和自动平仓。

        Args:
            signals: stock_selector 生成的信号列表
            price_data: 历史价格数据 {symbol: [price1, ..., priceN]}

        Returns:
            执行记录列表
        """
        executed = []

        for signal in signals:
            symbol = signal.get("symbol", "")
            signal_type = signal.get("signal", "WATCH")

            # AVOID 和 WATCH 不交易
            if signal_type in ("AVOID", "WATCH"):
                executed.append({
                    "symbol": symbol,
                    "signal": signal_type,
                    "action": "SKIP",
                    "reason": signal.get("reason", ""),
                })
                continue

            if signal_type != "BUY":
                executed.append({
                    "symbol": symbol,
                    "signal": signal_type,
                    "action": "SKIP",
                    "reason": f"不支持的信号类型: {signal_type}",
                })
                continue

            # BUY 信号：开仓
            prices = price_data.get(symbol, [])
            if len(prices) < 2:
                executed.append({
                    "symbol": symbol,
                    "signal": "BUY",
                    "action": "FAILED",
                    "reason": "价格数据不足",
                })
                continue

            entry_price = prices[0]
            today = date.today().isoformat()

            pos = self.open_position(symbol, today, entry_price, signal)
            if pos is None:
                executed.append({
                    "symbol": symbol,
                    "signal": "BUY",
                    "action": "FAILED",
                    "reason": "开仓失败（资金不足）",
                })
                continue

            # 模拟持仓5天，检查止盈止损
            max_days = min(5, len(prices) - 1)
            closed_early = False
            exit_price = entry_price
            exit_date = today

            for day in range(1, max_days + 1):
                current_price = prices[day]
                pnl = (current_price - entry_price) / entry_price * 100

                # 止盈 +8%
                if pnl >= 8.0:
                    exit_price = current_price
                    exit_date = (date.today() + timedelta(days=day)).isoformat()
                    closed_early = True
                    break

                # 止损 -5%
                if pnl <= -5.0:
                    exit_price = current_price
                    exit_date = (date.today() + timedelta(days=day)).isoformat()
                    closed_early = True
                    break

                exit_price = current_price
                exit_date = (date.today() + timedelta(days=day)).isoformat()

            # 平仓
            closed = self.close_position(pos, exit_date, exit_price)
            executed.append({
                "symbol": symbol,
                "signal": "BUY",
                "action": "CLOSED",
                "reason": f"平仓 {symbol}，收益 {closed['pnl_pct']:+.2f}%{' (止盈)' if closed['pnl_pct'] >= 8 else ' (止损)' if closed['pnl_pct'] <= -5 else ''}",
            })

        # 输出报告
        self._save_report()
        return executed

    def calculate_portfolio_return(self) -> float:
        """计算组合收益率（所有已平仓交易平均收益）。"""
        if not self.closed_trades:
            return 0.0
        total_pnl = sum(t["pnl_pct"] for t in self.closed_trades)
        return round(total_pnl / len(self.closed_trades), 2)

    def get_report(self) -> dict[str, Any]:
        """获取交易报告。"""
        total_trades = len(self.closed_trades)
        wins = sum(1 for t in self.closed_trades if t["pnl_pct"] > 0)
        losses = sum(1 for t in self.closed_trades if t["pnl_pct"] < 0)
        win_rate = round(wins / total_trades, 2) if total_trades > 0 else 0.0
        avg_return = self.calculate_portfolio_return()

        # 最大回撤
        max_drawdown = 0.0
        peak = self.initial_capital
        running_capital = self.initial_capital
        for t in self.closed_trades:
            running_capital += t["pnl_abs"]
            if running_capital > peak:
                peak = running_capital
            dd = round((peak - running_capital) / peak * 100, 2) if peak > 0 else 0.0
            if dd > max_drawdown:
                max_drawdown = dd

        total_pnl_abs = sum(t["pnl_abs"] for t in self.closed_trades)

        return {
            "initial_capital": self.initial_capital,
            "current_capital": round(self.capital, 2),
            "total_return_pct": round(total_pnl_abs / self.initial_capital * 100, 2) if self.initial_capital > 0 else 0.0,
            "total_closed_trades": total_trades,
            "win_rate": win_rate,
            "avg_return_pct": avg_return,
            "max_drawdown_pct": max_drawdown,
            "wins": wins,
            "losses": losses,
            "open_positions": len(self.positions),
            "closed_trades": self.closed_trades[-10:][::-1],  # 最近10条
        }

    def _save_report(self) -> None:
        """保存报告到JSON文件。"""
        today = date.today().isoformat().replace("-", "")
        reports_dir = Path(__file__).parent.parent.parent / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        report = self.get_report()
        # 只保存关键字段，避免trade列表过长
        summary = {
            "date": date.today().isoformat(),
            "initial_capital": report["initial_capital"],
            "current_capital": report["current_capital"],
            "total_return_pct": report["total_return_pct"],
            "total_closed_trades": report["total_closed_trades"],
            "win_rate": report["win_rate"],
            "avg_return_pct": report["avg_return_pct"],
            "max_drawdown_pct": report["max_drawdown_pct"],
            "wins": report["wins"],
            "losses": report["losses"],
            "open_positions": report["open_positions"],
            "recent_trades": [
                {
                    "symbol": t["symbol"],
                    "entry_date": t["entry_date"],
                    "exit_date": t["exit_date"],
                    "pnl_pct": t["pnl_pct"],
                    "status": t["status"],
                }
                for t in report["closed_trades"][:5]
            ],
        }
        report_file = reports_dir / f"paper_trading_{today}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

    def reset(self) -> None:
        """重置引擎。"""
        self.capital = self.initial_capital
        self.positions = []
        self.closed_trades = []
        self._position_id = 0