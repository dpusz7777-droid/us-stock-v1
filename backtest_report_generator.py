#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BacktestReportGenerator — 外部封装 BacktestEngine 生成回测报告。

设计原则
---------
- 不修改 BacktestEngine 核心逻辑，只做外部封装
- 所有回测调用通过 SystemController 进行
- 生成 Markdown 报告：backtest-latest.md（最新指针）+ 历史归档
- 自动更新 reports/index.json（只保留 latest + recent 3）
- 幂等设计：同周期防重复运行

用法
----
    from backtest_report_generator import BacktestReportGenerator

    generator = BacktestReportGenerator()
    report_path = generator.generate_report()     # 生成归档 + latest
    latest_path = generator.get_latest_path()      # 获取 latest 指针

看板聚合请使用 dashboard_service.DashboardService。
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from report_index import record_report
from system_controller import SystemController


ROOT = Path(__file__).parent
REPORTS_DIR = ROOT / "reports"
DEFAULT_PORTFOLIO_FILE = ROOT / "portfolio_migrated_candidate.json"
STRATEGY_NAME = "BacktestEngine V2"
LATEST_FILENAME = "backtest-latest.md"

# 幂等锁文件：同一小时不重复运行（跨进程持久化）
_LOCK_DIR = Path(__file__).parent / ".run_locks"
LOCK_TTL_SECONDS = 3600  # 1 小时


def _check_lock(period_key: str) -> bool:
    """检查是否已在此周期运行过（幂等锁，文件持久化）。"""
    _LOCK_DIR.mkdir(parents=True, exist_ok=True)
    lock_file = _LOCK_DIR / f"report_{period_key}.lock"
    if lock_file.is_file():
        age = time.time() - lock_file.stat().st_mtime
        if age < LOCK_TTL_SECONDS:
            return True  # 锁定中
    # 更新锁
    lock_file.write_text(str(time.time()), encoding="utf-8")
    return False  # 未锁定


class BacktestReportGenerator:
    """外部封装 BacktestEngine，生成每日回测报告 Markdown 文件。"""

    def __init__(
        self,
        portfolio_path: str | Path = DEFAULT_PORTFOLIO_FILE,
        reports_dir: str | Path = REPORTS_DIR,
        initial_cash: Decimal | float | str = Decimal("100000"),
        idempotent: bool = True,
    ):
        self._portfolio_path = Path(portfolio_path)
        self._reports_dir = Path(reports_dir)
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        self._controller = SystemController(initial_cash=initial_cash)
        self._idempotent = idempotent

    # ------------------------------------------------------------------
    # 核心：生成最新回测报告
    # ------------------------------------------------------------------

    def generate_report(
        self,
        symbols: list[str] | None = None,
        *,
        force: bool = False,
    ) -> Path:
        """运行回测并生成 Markdown 报告（归档 + latest 指针）。

        幂等策略：同一自然小时内不重复运行（force=True 跳过检查）。

        Args:
            symbols: 可选，指定回测标的列表。
            force: 跳过幂等锁检查。

        Returns:
            生成的归档报告文件路径。
        """
        # 幂等检查
        now = datetime.now(timezone.utc)
        period_key = now.strftime("%Y-%m-%d-%H")  # 按小时锁
        if self._idempotent and not force:
            if _check_lock(period_key):
                # 已有同周期最新报告则返回
                latest = self.get_latest_path()
                if latest and latest.exists():
                    print(f"[Report] 跳过重复运行（周期 {period_key} 已有报告）")
                    return latest

        # 运行回测（外部封装，不修改 BacktestEngine）
        backtest_result = self._controller.run_backtest(
            symbol=symbols[0] if symbols else None
        )

        # 运行后无论是否 force 都写入锁（阻止后续同周期运行）
        if self._idempotent:
            _check_lock(period_key)  # 确保锁文件存在

        # 生成 Markdown 内容
        md_content = self._build_markdown(backtest_result)

        # --- 写入归档文件: backtest-YYYYMMDD-HHMMSS.md ---
        archive_name = f"backtest-{now.strftime('%Y%m%d-%H%M%S')}.md"
        archive_path = self._reports_dir / archive_name
        archive_path.write_text(md_content, encoding="utf-8")

        # --- 写入 latest 指针: backtest-latest.md（总是覆盖）---
        latest_path = self._reports_dir / LATEST_FILENAME
        latest_path.write_text(md_content, encoding="utf-8")

        # --- 更新 index.json ---
        # 只记录 latest 指针 + 最近 3 条归档
        # 先记录最新的归档
        record_report(
            file_path=archive_path,
            report_type="backtest",
            portfolio_path=self._portfolio_path,
            index_path=self._reports_dir / "index.json",
            generated_at=now,
        )
        # 再确保 latest 指针也在索引中
        record_report(
            file_path=latest_path,
            report_type="backtest_latest",
            portfolio_path=self._portfolio_path,
            index_path=self._reports_dir / "index.json",
            generated_at=now,
        )

        # 裁剪 index.json，只保留 backtest_latest + 最近 3 条其他 backtest
        self._trim_index(keep_recent=3)

        print(f"\n[Report] 回测报告已生成")
        print(f"   归档: {archive_path.resolve()}")
        print(f"   最新: {latest_path.resolve()}")
        return archive_path

    def get_latest_path(self) -> Path:
        """返回 latest 指针文件路径（不保证存在）。"""
        return self._reports_dir / LATEST_FILENAME

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _trim_index(self, keep_recent: int = 3) -> None:
        """裁剪 index.json：保留 backtest_latest + 最近 N 条 backtest。"""
        index_path = self._reports_dir / "index.json"
        if not index_path.is_file():
            return

        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return

        reports = data.get("reports", [])
        if not isinstance(reports, list):
            return

        # 分离 latest 和其他
        latest_entries = [r for r in reports if isinstance(r, dict) and r.get("type") == "backtest_latest"]
        other_backtest = [r for r in reports if isinstance(r, dict) and r.get("type") == "backtest"]
        other_types = [r for r in reports if isinstance(r, dict) and r.get("type") not in ("backtest", "backtest_latest")]

        # 其他 backtest 按日期降序取最近 keep_recent 条
        other_backtest.sort(key=lambda r: r.get("date", ""), reverse=True)
        other_backtest = other_backtest[:keep_recent]

        data["reports"] = latest_entries + other_backtest + other_types
        index_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _build_markdown(self, backtest_result: dict) -> str:
        """将回测结果转为可读 Markdown。"""
        summary = backtest_result.get("summary", {})
        symbols_data = backtest_result.get("symbols", {})
        equity_curve = backtest_result.get("equity_curve", [])

        total_return_pct = self._safe_float(summary.get("total_return_pct", "0"))
        win_rate = self._safe_float(summary.get("avg_win_rate", 0.0))
        trade_count = int(summary.get("total_trade_count", 0))

        max_drawdown = 0.0
        total_trades_list: list[dict] = []
        start_date = ""
        end_date = ""
        initial_cash = 100000.0

        for sym_name, sym_result in symbols_data.items():
            dd = self._safe_float(sym_result.get("max_drawdown", "0"))
            if dd > max_drawdown:
                max_drawdown = dd
            sym_trades = sym_result.get("trades", [])
            total_trades_list.extend(sym_trades)
            timestamps = sym_result.get("timestamps", [])
            if timestamps:
                if not start_date or timestamps[0] < start_date:
                    start_date = timestamps[0]
                if not end_date or timestamps[-1] > end_date:
                    end_date = timestamps[-1]
            ic = self._safe_float(sym_result.get("initial_cash", "100000"))
            if ic > 0:
                initial_cash = ic

        pnl_values = []
        total_wins = 0.0
        total_losses = 0.0
        win_trade_count = 0
        lose_trade_count = 0
        for t in total_trades_list:
            pnl = self._safe_float(t.get("pnl", 0))
            action = str(t.get("action", ""))
            if action in ("BUY", "buy", "Buy"):
                continue
            pnl_values.append(pnl)
            if pnl > 0:
                total_wins += pnl
                win_trade_count += 1
            elif pnl < 0:
                total_losses += abs(pnl)
                lose_trade_count += 1

        profit_loss_ratio = (
            (total_wins / win_trade_count) / (total_losses / lose_trade_count)
            if win_trade_count > 0 and lose_trade_count > 0 and total_losses > 0
            else 0.0
        )

        time_range = f"{start_date} → {end_date}" if start_date and end_date else "N/A"

        win_pct = (win_trade_count / len(total_trades_list) * 100) if total_trades_list else 0.0
        lose_pct = (lose_trade_count / len(total_trades_list) * 100) if total_trades_list else 0.0

        max_win = max(pnl_values) if pnl_values else 0.0
        max_loss = min(pnl_values) if pnl_values else 0.0
        equity_end = equity_curve[-1] if equity_curve else 0.0

        parts = [
            "# 每日回测报告",
            "",
            f"**生成时间**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"**策略名称**: {STRATEGY_NAME}",
            "",
            "---",
            "",
            "## 回测概览",
            "",
            "| 指标 | 数值 |",
            "|------|------|",
            f"| **回测时间区间** | {time_range} |",
            f"| **初始资金** | ${initial_cash:,.2f} |",
            f"| **最终净值** | ${equity_end:,.2f} |",
            f"| **总收益率** | **{total_return_pct:+.2f}%** |",
            f"| **最大回撤 (Max Drawdown)** | **{max_drawdown:.2f}%** |",
            f"| **胜率 (Win Rate)** | **{win_rate:.1%}** |",
            f"| **盈亏比 (Profit/Loss Ratio)** | {profit_loss_ratio:.2f} |",
            f"| **交易次数** | {trade_count} |",
            "",
            "---",
            "",
            "## 交易统计",
            "",
            "| 统计项 | 数值 |",
            "|--------|------|",
            f"| **盈利交易** | {win_trade_count} ({win_pct:.1f}%) |",
            f"| **亏损交易** | {lose_trade_count} ({lose_pct:.1f}%) |",
            f"| **最大单笔盈利** | ${max_win:+.2f} |",
            f"| **最大单笔亏损** | ${max_loss:+.2f} |",
            "",
        ]

        if symbols_data:
            parts.append("---")
            parts.append("")
            parts.append("## 各标的明细")
            parts.append("")
            parts.append(f"{'标的':>8} {'收益率':>12} {'胜率':>10} {'回撤':>10} {'交易数':>8}")
            parts.append(f"{'-' * 52}")
            for sym_name in sorted(symbols_data):
                sr = symbols_data[sym_name]
                sr_ret = self._safe_float(sr.get("total_return_pct", "0"))
                sr_wr = self._safe_float(sr.get("win_rate", 0.0))
                sr_dd = self._safe_float(sr.get("max_drawdown", "0"))
                sr_tc = int(sr.get("trade_count", 0))
                parts.append(
                    f"{sym_name:>8} {sr_ret:>+10.2f}% "
                    f"{sr_wr:>8.1%} {sr_dd:>8.2f}% {sr_tc:>8}"
                )
            parts.append("")

        if total_trades_list:
            parts.append("---")
            parts.append("")
            parts.append("## 交易明细")
            parts.append("")
            parts.append(
                f"{'日期':>24} {'操作':>12} {'标的':>8} "
                f"{'数量':>8} {'价格':>12} {'盈亏':>14} {'盈亏率':>10}"
            )
            parts.append(f"{'-' * 92}")
            for t in total_trades_list:
                date = str(t.get("date", ""))[:19]
                action = str(t.get("action", ""))
                symbol = str(t.get("symbol", ""))
                qty = str(t.get("qty", ""))
                price = str(t.get("price", ""))
                pnl = self._safe_float(t.get("pnl", 0))
                pnl_pct = self._safe_float(t.get("pnl_pct", 0))
                parts.append(
                    f"{date:>24} {action:>12} {symbol:>8} "
                    f"{qty:>8} {price:>12} ${pnl:>+11.2f} {pnl_pct:>+8.2f}%"
                )
            parts.append("")

        parts.append("---")
        parts.append("")
        parts.append("*报告由 BacktestReportGenerator 自动生成*  ")
        parts.append("*核心回测引擎: BacktestEngine V2（未修改核心逻辑）*  ")
        parts.append(f"*报告文件: {Path(__file__).name}*")

        return "\n".join(parts)

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        if value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def run_report(symbols: list[str] | None = None, *, force: bool = False) -> Path:
    """CLI: python main.py report 的底层实现。"""
    generator = BacktestReportGenerator(idempotent=True)
    return generator.generate_report(symbols=symbols, force=force)


if __name__ == "__main__":
    import sys
    symbols = sys.argv[1:] if len(sys.argv) > 1 else None
    run_report(symbols=symbols)