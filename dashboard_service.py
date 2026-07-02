#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DashboardService — 只读聚合看板层。

职责
----
- 从多个数据源聚合信息，只读不写
- 支持 terminal 表格 + Markdown 双格式输出
- 不修改任何 BacktestEngine / PortfolioService 等核心模块

聚合内容
--------
1. 最新 Backtest Report（从 reports/index.json + Markdown 解析）
2. 当前 Portfolio 持仓列表
3. Cash / PnL / Return 摘要
4. 最近 N 份 Reports 列表
5. System Status 信息板

用法
----
    from dashboard_service import DashboardService

    service = DashboardService()
    dashboard = service.generate()          # → dict
    service.print_terminal(dashboard)       # → terminal tables
    md = service.to_markdown(dashboard)     # → markdown string
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from report_index import recent_reports
from backtest_report_generator import LATEST_FILENAME


ROOT = Path(__file__).parent
REPORTS_DIR = ROOT / "reports"
DEFAULT_PORTFOLIO_FILE = ROOT / "portfolio_migrated_candidate.json"
REPORT_STALENESS_DAYS = 3  # 超过 N 天的报告视为"陈旧"


class DashboardService:
    """只读聚合看板，不修改任何数据源。"""

    def __init__(
        self,
        portfolio_path: str | Path = DEFAULT_PORTFOLIO_FILE,
        reports_dir: str | Path = REPORTS_DIR,
    ):
        self._portfolio_path = Path(portfolio_path)
        self._reports_dir = Path(reports_dir)

    # ------------------------------------------------------------------
    # 核心：生成聚合数据
    # ------------------------------------------------------------------

    def generate(self) -> dict[str, Any]:
        """聚合所有数据源，返回结构化 dict。"""
        return {
            "report": self._get_latest_backtest_report(),
            "portfolio": self._get_portfolio_summary(),
            "cash": self._get_cash_info(),
            "recent_reports": self._get_recent_reports(3),
            "system_status": self._get_system_status(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Terminal 表格输出
    # ------------------------------------------------------------------

    def print_terminal(self, dashboard: dict[str, Any] | None = None) -> None:
        """终端输出表格化 Dashboard。"""
        data = dashboard if dashboard is not None else self.generate()

        print("\n" + "=" * 64)
        print("  📊 投资 Dashboard  (只读聚合层)")
        print("=" * 64)

        # ── 1. System Status ──────────────────────────────────────
        self._print_section_header("System Status")
        status = data.get("system_status", {})
        checks = status.get("checks", {})
        print(f"  Portfolio Data:   {'✅ 正常' if checks.get('portfolio_exists', False) else '❌ 缺失'}")
        print(f"  Report Index:     {'✅ 正常' if checks.get('index_exists', False) else '❌ 缺失'}")
        print(f"  Latest Backtest:  {'✅ 正常' if checks.get('report_exists', False) else '❌ 缺失'}")
        if checks.get("report_stale", False):
            print(f"  Report 陈旧度:    ⚠️  最新报告已超过 {checks.get('report_age_days', 0):.0f} 天")
        else:
            age = checks.get("report_age_days", 0)
            print(f"  Report 陈旧度:    ✅ {age:.0f} 天内的报告")

        # ── 2. Latest Backtest Report ─────────────────────────────
        self._print_section_header("最新回测报告")
        report = data.get("report")
        if report:
            s = report.get("summary", {})
            print(f"  日期:        {report.get('date', 'N/A')}")
            print(f"  文件:        {report.get('file_path', 'N/A')}")
            print(f"  策略:        {s.get('strategy', report.get('strategy', 'BacktestEngine V2'))}")
            print(f"  回测区间:    {s.get('time_range', 'N/A')}")
            print(f"  总收益率:    {s.get('total_return', 'N/A')}")
            print(f"  最大回撤:    {s.get('max_drawdown', 'N/A')}")
            print(f"  胜率:        {s.get('win_rate', 'N/A')}")
            print(f"  盈亏比:      {s.get('profit_loss_ratio', 'N/A')}")
            print(f"  交易次数:    {s.get('trade_count', 'N/A')}")
            print(f"  初始资金:    {s.get('initial_cash', 'N/A')}")
            print(f"  最终净值:    {s.get('final_equity', 'N/A')}")
        else:
            print("  (暂无回测报告，请先运行 python main.py report)")

        # ── 3. Portfolio ──────────────────────────────────────────
        self._print_section_header("持仓概览")
        portfolio = data.get("portfolio")
        if portfolio:
            positions = portfolio.get("positions", {})
            print(f"  持仓数量:    {len(positions)} 只")
            pnl = self._safe_float(portfolio.get("total_unrealized_pnl"))
            cost = self._safe_float(portfolio.get("total_cost_basis"))
            mval = self._safe_float(portfolio.get("total_market_value"))
            print(f"  总成本:      ${cost:,.2f}" if cost else "  总成本:      N/A")
            print(f"  当前市值:    ${mval:,.2f}" if mval else "  当前市值:    N/A")
            print(f"  未实现PnL:   ${pnl:+,.2f}" if pnl else "  未实现PnL:   N/A")
            if cost and mval:
                ret = (mval - cost) / cost * 100
                print(f"  组合收益率:  {ret:+.2f}%")

            # 持仓明细表
            if positions:
                self._print_positions_table(positions)
        else:
            print("  (无法读取持仓信息)")

        # ── 4. Cash / PnL Summary ────────────────────────────────
        self._print_section_header("Cash & PnL 摘要")
        cash_info = data.get("cash")
        if cash_info:
            if cash_info.get("status") == "unknown":
                print("  现金状态:   未知")
            else:
                cash = self._safe_float(cash_info.get("cash"))
                equity = self._safe_float(cash_info.get("total_equity"))
                bp = self._safe_float(cash_info.get("buying_power"))
                print(f"  现金:       ${cash:,.2f}" if cash else "  现金:       N/A")
                print(f"  总资产:     ${equity:,.2f}" if equity else "  总资产:     N/A")
                print(f"  购买力:     ${bp:,.2f}" if bp else "  购买力:     N/A")
        else:
            print("  (无法读取现金信息)")

        # ── 5. Recent Reports ────────────────────────────────────
        self._print_section_header("最近 3 份 Reports")
        reports = data.get("recent_reports", [])
        if reports:
            print(f"  {'日期':>12} {'类型':>12} {'文件':>40}")
            print(f"  {'-' * 66}")
            for item in reports:
                d = str(item.get("date", ""))
                t = str(item.get("type", ""))
                f = str(item.get("file_path", ""))
                print(f"  {d:>12} {t:>12} {f:>40}")
        else:
            print("  (暂无报告索引)")

        print(f"\n  🕐 生成时间: {data.get('generated_at', 'N/A')}")
        print(f"  📝 只读看板：未访问网络，未修改任何文件")
        print("=" * 64 + "\n")

    # ------------------------------------------------------------------
    # Markdown 输出
    # ------------------------------------------------------------------

    def to_markdown(self, dashboard: dict[str, Any] | None = None) -> str:
        """生成 Markdown 格式 Dashboard。"""
        data = dashboard if dashboard is not None else self.generate()

        parts: list[str] = [
            "# 📊 投资 Dashboard",
            "",
            f"> **只读聚合层** · 生成时间: {data.get('generated_at', 'N/A')}",
            "",
        ]

        # ── 1. System Status ──────────────────────────────────────
        parts.append("## 🔧 System Status")
        parts.append("")
        status = data.get("system_status", {})
        checks = status.get("checks", {})
        parts.append(f"| 检查项 | 状态 |")
        parts.append(f"|--------|------|")
        parts.append(f"| Portfolio 数据 | {'✅ 正常' if checks.get('portfolio_exists', False) else '❌ 缺失'} |")
        parts.append(f"| Report 索引 | {'✅ 正常' if checks.get('index_exists', False) else '❌ 缺失'} |")
        parts.append(f"| 最新 Backtest | {'✅ 正常' if checks.get('report_exists', False) else '❌ 缺失'} |")
        if checks.get("report_stale", False):
            age = checks.get("report_age_days", 0)
            parts.append(f"| Report 陈旧度 | ⚠️  最新报告已超过 {age:.0f} 天 |")
        else:
            age = checks.get("report_age_days", 0)
            parts.append(f"| Report 陈旧度 | ✅ {age:.0f} 天内报告 |")
        parts.append("")

        # ── 2. Latest Backtest Report ─────────────────────────────
        parts.append("## 📋 最新回测报告")
        parts.append("")
        report = data.get("report")
        if report:
            s = report.get("summary", {})
            parts.append(f"| 指标 | 数值 |")
            parts.append(f"|------|------|")
            parts.append(f"| **日期** | {report.get('date', 'N/A')} |")
            parts.append(f"| **策略** | {s.get('strategy', report.get('strategy', 'BacktestEngine V2'))} |")
            parts.append(f"| **回测区间** | {s.get('time_range', 'N/A')} |")
            parts.append(f"| **总收益率** | {s.get('total_return', 'N/A')} |")
            parts.append(f"| **最大回撤** | {s.get('max_drawdown', 'N/A')} |")
            parts.append(f"| **胜率** | {s.get('win_rate', 'N/A')} |")
            parts.append(f"| **盈亏比** | {s.get('profit_loss_ratio', 'N/A')} |")
            parts.append(f"| **交易次数** | {s.get('trade_count', 'N/A')} |")
            parts.append(f"| **初始资金** | {s.get('initial_cash', 'N/A')} |")
            parts.append(f"| **最终净值** | {s.get('final_equity', 'N/A')} |")
            parts.append(f"| **文件** | `{report.get('file_path', 'N/A')}` |")
        else:
            parts.append("*(暂无回测报告)*")
        parts.append("")

        # ── 3. Portfolio ──────────────────────────────────────────
        parts.append("## 💼 持仓概览")
        parts.append("")
        portfolio = data.get("portfolio")
        if portfolio:
            positions = portfolio.get("positions", {})
            pnl = self._safe_float(portfolio.get("total_unrealized_pnl"))
            cost = self._safe_float(portfolio.get("total_cost_basis"))
            mval = self._safe_float(portfolio.get("total_market_value"))
            parts.append(f"- **持仓数量**: {len(positions)} 只")
            parts.append(f"- **总成本**: {'$' + f'{cost:,.2f}' if cost else 'N/A'}")
            parts.append(f"- **当前市值**: {'$' + f'{mval:,.2f}' if mval else 'N/A'}")
            parts.append(f"- **未实现 PnL**: {'$' + f'{pnl:+,.2f}' if pnl else 'N/A'}")
            if cost and mval:
                ret = (mval - cost) / cost * 100
                parts.append(f"- **组合收益率**: {ret:+.2f}%")
            parts.append("")

            if positions:
                parts.append(f"| {'标的':>8} | {'股数':>8} | {'成本':>12} | {'现价':>12} | {'市值':>12} | {'PnL':>12} |")
                parts.append(f"|{'-' * 10}|{'-' * 10}|{'-' * 14}|{'-' * 14}|{'-' * 14}|{'-' * 14}|")
                for sym in sorted(positions):
                    pos = positions[sym]
                    shares = pos.get("shares", 0)
                    avg_cost = self._safe_float(pos.get("avg_cost"))
                    last_price = self._safe_float(pos.get("last_price"))
                    market_value = self._safe_float(pos.get("market_value"))
                    unrealized = self._safe_float(pos.get("unrealized_pnl"))
                    parts.append(
                        f"| {sym:>8} | {str(shares):>8} "
                        f"| {'$' + f'{avg_cost:>,.2f}' if avg_cost else 'N/A':>12} "
                        f"| {'$' + f'{last_price:>,.2f}' if last_price else 'N/A':>12} "
                        f"| {'$' + f'{market_value:>,.2f}' if market_value else 'N/A':>12} "
                        f"| {'$' + f'{unrealized:+,.2f}' if unrealized else 'N/A':>12} |"
                    )
                parts.append("")
        else:
            parts.append("*(无法读取持仓信息)*")
            parts.append("")

        # ── 4. Cash & PnL ────────────────────────────────────────
        parts.append("## 💰 Cash & PnL 摘要")
        parts.append("")
        cash_info = data.get("cash")
        if cash_info:
            if cash_info.get("status") == "unknown":
                parts.append("- **现金状态**: 未知")
            else:
                cash = self._safe_float(cash_info.get("cash"))
                equity = self._safe_float(cash_info.get("total_equity"))
                bp = self._safe_float(cash_info.get("buying_power"))
                parts.append(f"- **现金**: {'$' + f'{cash:,.2f}' if cash else 'N/A'}")
                parts.append(f"- **总资产**: {'$' + f'{equity:,.2f}' if equity else 'N/A'}")
                parts.append(f"- **购买力**: {'$' + f'{bp:,.2f}' if bp else 'N/A'}")
        else:
            parts.append("*(无法读取现金信息)*")
        parts.append("")

        # ── 5. Recent Reports ────────────────────────────────────
        parts.append("## 📄 最近 3 份 Reports")
        parts.append("")
        reports = data.get("recent_reports", [])
        if reports:
            parts.append(f"| {'日期':>12} | {'类型':>12} | {'文件':>50} |")
            parts.append(f"|{'-' * 14}|{'-' * 14}|{'-' * 52}|")
            for item in reports:
                d = str(item.get("date", ""))
                t = str(item.get("type", ""))
                f = str(item.get("file_path", ""))
                parts.append(f"| {d:>12} | {t:>12} | {f:>50} |")
            parts.append("")
        else:
            parts.append("*(暂无报告索引)*")
            parts.append("")

        parts.append("---")
        parts.append("")
        parts.append("*报告由 DashboardService 自动生成（只读聚合层）*  ")
        parts.append("*不修改任何核心模块，不访问网络*")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # 内部数据源读取
    # ------------------------------------------------------------------

    def _get_latest_backtest_report(self) -> dict[str, Any] | None:
        """从 backtest-latest.md 文件直接读取最新报告摘要。"""
        latest_file = self._reports_dir / LATEST_FILENAME
        if not latest_file.is_file():
            return None

        summary = self._extract_summary(latest_file)

        # 尝试从 index.json 获取日期信息
        index_path = self._reports_dir / "index.json"
        date_str = ""
        if index_path.is_file():
            try:
                data = json.loads(index_path.read_text(encoding="utf-8"))
                reports = data.get("reports", [])
                latest_entries = [
                    r for r in reports
                    if isinstance(r, dict) and r.get("type") == "backtest_latest"
                ]
                if latest_entries:
                    date_str = latest_entries[0].get("date", "")
            except (json.JSONDecodeError, OSError):
                pass

        return {
            "date": date_str,
            "file_path": LATEST_FILENAME,
            "portfolio_snapshot": "",
            "summary": summary,
        }

    def _extract_summary(self, md_path: Path) -> dict[str, Any]:
        """从 Markdown 报告表格中提取关键指标。"""
        text = md_path.read_text(encoding="utf-8")
        result: dict[str, Any] = {}

        patterns = {
            "总收益率": "total_return",
            "最大回撤 (Max Drawdown)": "max_drawdown",
            "最大回撤": "max_drawdown",
            "胜率 (Win Rate)": "win_rate",
            "胜率": "win_rate",
            "盈亏比 (Profit/Loss Ratio)": "profit_loss_ratio",
            "盈亏比": "profit_loss_ratio",
            "交易次数": "trade_count",
            "回测时间区间": "time_range",
            "初始资金": "initial_cash",
            "最终净值": "final_equity",
            "策略名称": "strategy",
        }

        for cn_label, en_key in patterns.items():
            match = re.search(
                rf"\|\s*\*\*{cn_label}\*\*\s*\|\s*(.+?)\s*\|",
                text,
            )
            if match:
                value = match.group(1).strip().replace("**", "").strip()
                if en_key not in result:
                    result[en_key] = value

        return result

    def _get_portfolio_summary(self) -> dict[str, Any] | None:
        """读取持仓文件获取概览与明细。"""
        try:
            from portfolio_service import get_portfolio_snapshot
            state = get_portfolio_snapshot(self._portfolio_path)
        except Exception:
            return None

        positions: dict[str, Any] = {}
        for symbol, pos in state.positions.items():
            positions[symbol] = {
                "shares": float(pos.shares) if pos.shares else 0,
                "avg_cost": float(pos.avg_cost) if pos.avg_cost else None,
                "last_price": float(pos.last_price) if pos.last_price else None,
                "market_value": float(pos.market_value) if pos.market_value else None,
                "unrealized_pnl": float(pos.unrealized_pnl) if pos.unrealized_pnl else None,
                "unrealized_pnl_pct": float(pos.unrealized_pnl_pct) if pos.unrealized_pnl_pct else None,
                "cost_basis": float(pos.cost_basis) if pos.cost_basis else None,
            }

        return {
            "position_count": len(state.positions),
            "total_cost_basis": float(state.total_cost_basis) if state.total_cost_basis is not None else None,
            "total_market_value": float(state.total_market_value) if state.total_market_value is not None else None,
            "total_unrealized_pnl": float(state.total_unrealized_pnl) if state.total_unrealized_pnl is not None else None,
            "positions": positions,
        }

    def _get_cash_info(self) -> dict[str, Any] | None:
        """读取持仓文件获取现金信息。"""
        try:
            from portfolio_service import get_portfolio_snapshot
            state = get_portfolio_snapshot(self._portfolio_path)
        except Exception:
            return None

        if state.cash_status == "unknown":
            return {"status": "unknown", "cash": None, "buying_power": None, "total_equity": None}

        bp = None
        if hasattr(state, "buying_power") and state.buying_power is not None:
            bp = float(state.buying_power)

        return {
            "status": state.cash_status,
            "cash": float(state.cash) if state.cash is not None else None,
            "buying_power": bp,
            "total_equity": float(state.total_equity) if state.total_equity is not None else None,
        }

    def _get_recent_reports(self, limit: int = 3) -> list[dict[str, Any]]:
        """获取最近 N 份报告（从 report_index）。"""
        try:
            return recent_reports(limit)
        except Exception:
            return []

    def _get_system_status(self) -> dict[str, Any]:
        """检测系统各组件状态。"""
        checks: dict[str, Any] = {}

        # Portfolio 数据
        checks["portfolio_exists"] = self._portfolio_path.is_file()

        # Report 索引
        index_path = self._reports_dir / "index.json"
        checks["index_exists"] = index_path.is_file()

        # 最新 Backtest Report（从 backtest-latest.md 文件 mtime 判断）
        latest_file = self._reports_dir / LATEST_FILENAME
        checks["report_exists"] = latest_file.is_file()

        # 报告陈旧度（使用文件修改时间）
        if latest_file.is_file():
            age = (time.time() - latest_file.stat().st_mtime) / 86400
            checks["report_age_days"] = age
            checks["report_stale"] = age > REPORT_STALENESS_DAYS
        else:
            checks["report_age_days"] = None
            checks["report_stale"] = True

        return {
            "checks": checks,
            "stale_threshold_days": REPORT_STALENESS_DAYS,
        }

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _print_section_header(self, title: str) -> None:
        print(f"\n  {'─' * 56}")
        print(f"  [{title}]")

    def _print_positions_table(self, positions: dict[str, Any]) -> None:
        """逐行打印持仓表格。"""
        try:
            has_data = any(
                p.get("avg_cost") or p.get("last_price") or p.get("market_value") or p.get("unrealized_pnl")
                for p in positions.values()
            )
        except Exception:
            has_data = False

        if not has_data:
            print(f"  (无详细持仓数据)")
            return

        print(f"  {'标的':>8} {'股数':>8} {'成本':>12} {'现价':>12} {'市值':>12} {'PnL':>12}")
        print(f"  {'-' * 64}")
        for sym in sorted(positions):
            pos = positions[sym]
            shares = pos.get("shares", 0)
            avg_cost = self._safe_float(pos.get("avg_cost"))
            last_price = self._safe_float(pos.get("last_price"))
            market_value = self._safe_float(pos.get("market_value"))
            unrealized = self._safe_float(pos.get("unrealized_pnl"))
            shares_str = f"{shares:.0f}" if shares else "-"
            cost_str = f"${avg_cost:>9,.2f}" if avg_cost else f"{'N/A':>12}"
            price_str = f"${last_price:>9,.2f}" if last_price else f"{'N/A':>12}"
            mv_str = f"${market_value:>9,.2f}" if market_value else f"{'N/A':>12}"
            pnl_str = f"${unrealized:>+9,.2f}" if unrealized else f"{'N/A':>12}"
            print(f"  {sym:>8} {shares_str:>8} {cost_str:>12} {price_str:>12} {mv_str:>12} {pnl_str:>12}")

    @staticmethod
    def _safe_float(value: Any, default: float | None = None) -> float | None:
        """安全转换为 float，失败返回 None。"""
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None


# ---------------------------------------------------------------------------
# CLI 快速入口
# ---------------------------------------------------------------------------

def run_dashboard() -> dict[str, Any]:
    """CLI: python main.py dashboard 的底层实现。"""
    service = DashboardService()
    data = service.generate()
    service.print_terminal(data)
    return data


def run_dashboard_markdown() -> str:
    """CLI: 输出 Markdown 格式 Dashboard。"""
    service = DashboardService()
    return service.to_markdown()


if __name__ == "__main__":
    import sys

    if "--markdown" in sys.argv:
        print(run_dashboard_markdown())
    else:
        run_dashboard()