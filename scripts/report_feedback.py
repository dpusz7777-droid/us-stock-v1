#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
report_feedback — 从 backtest-*.md 提取指标并计算反馈分数，使 report 成为系统输入源。

最小侵入设计：
- 只读取 reports/backtest-latest.md（或最新 backtest-*.md）
- 提取总收益率、最大回撤、胜率
- 计算 report_score (0~100)
- 写入 .runtime/report_feedback.json 供其他模块消费

闭环链路：signal → execution → report → signal_adjustment
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
REPORTS_DIR = BASE_DIR / "reports"
RUNTIME_DIR = BASE_DIR / ".runtime"
FEEDBACK_FILE = RUNTIME_DIR / "report_feedback.json"

# ── report 指标提取 ─────────────────────────────────────────────────────────


def find_latest_backtest(reports_dir: str | Path = REPORTS_DIR) -> Path | None:
    """在 reports/ 下找到最新的 backtest-*.md 文件。
    
    优先使用 backtest-latest.md，否则按 mtime 找最新。
    """
    reports_path = Path(reports_dir)
    latest_symlink = reports_path / "backtest-latest.md"
    if latest_symlink.is_file():
        return latest_symlink

    candidates = sorted(reports_path.glob("backtest-*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def extract_metrics(md_text: str) -> dict[str, float | None]:
    """从 backtest 报告的 Markdown 表格中提取关键指标。

    实际报告格式：
    | | **总收益率** | **+2.54%** |
    | **最大回撤 (Max Drawdown)** | **1.18%** |
    | **胜率 (Win Rate)** | **71.4%** |
    | **盈亏比 (Profit/Loss Ratio)** | 0.00 |
    | **交易次数** | 7 |

    返回 dict，value 为 float（百分比保留原始数值，2.54 表示 2.54%）或 None。
    """
    metrics: dict[str, float | None] = {
        "total_return_pct": None,
        "max_drawdown_pct": None,
        "win_rate_pct": None,
        "profit_loss_ratio": None,
        "trade_count": None,
    }

    # 用灵活的正则匹配实际表格行
    patterns: dict[str, re.Pattern] = {
        "total_return_pct": re.compile(
            r"\|\s*\*\*总收益率\*\*\s*\|\s*\*\*?([+-]?\d+\.?\d*)%\*{0,2}\s*\|"
        ),
        "max_drawdown_pct": re.compile(
            r"\|\s*\*\*最大回撤[^|]*\*\*\s*\|\s*\*\*?(\d+\.?\d*)%\*{0,2}\s*\|"
        ),
        "win_rate_pct": re.compile(
            r"\|\s*\*\*胜率[^|]*\*\*\s*\|\s*\*\*?(\d+\.?\d*)%\*{0,2}\s*\|"
        ),
        "profit_loss_ratio": re.compile(
            r"\|\s*\*\*盈亏比[^|]*\*\*\s*\|\s*(\d+\.?\d*)\s*\|"
        ),
        "trade_count": re.compile(
            r"\|\s*\*\*交易次数\*\*\s*\|\s*(\d+)\s*\|"
        ),
    }

    for key, pattern in patterns.items():
        match = pattern.search(md_text)
        if match:
            val = float(match.group(1))
            if key.endswith("_pct") and key != "profit_loss_ratio":
                # 百分比字段存原始数值，2.54 表示 2.54%
                metrics[key] = round(val, 4)
            elif key == "trade_count":
                metrics[key] = int(val)
            else:
                metrics[key] = round(val, 4)

    return metrics


# ── 评分函数 ────────────────────────────────────────────────────────────────


def compute_score(metrics: dict[str, float | None]) -> float:
    """根据回测指标计算综合 report_score (0~100)。

    评分维度（等权）：
    1. 总收益率分：收益率每 +1% 得 20 分，最高 100 分，负收益为 0 分
    2. 最大回撤分：回撤 ≤2% 得 100 分，>10% 得 0 分，中间线性
    3. 胜率分：胜率 * 100（如 71.4% → 71.4 分）
    4. 交易次数分：≥5 次得 100 分，≤1 次得 0 分
    """
    total_return = metrics.get("total_return_pct") or 0.0
    max_dd = metrics.get("max_drawdown_pct") or 10.0
    win_rate = metrics.get("win_rate_pct") or 0.0
    trade_count = metrics.get("trade_count") or 0

    # 1. 收益率分
    return_score = min(max(total_return * 20, 0.0), 100.0)

    # 2. 回撤分
    if max_dd <= 2.0:
        dd_score = 100.0
    elif max_dd >= 10.0:
        dd_score = 0.0
    else:
        dd_score = 100.0 - (max_dd - 2.0) / 8.0 * 100.0

    # 3. 胜率分
    wr_score = min(win_rate, 100.0)

    # 4. 交易次数分（样本量足够才有统计意义）
    count_score = min(trade_count / 5.0 * 100.0, 100.0) if trade_count else 0.0

    score = round((return_score + dd_score + wr_score + count_score) / 4.0, 2)
    return max(0.0, min(score, 100.0))


# ── 主入口 ──────────────────────────────────────────────────────────────────


def read_feedback() -> dict:
    """读取当前 report_feedback.json（若存在）。"""
    try:
        return json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"report_score": 50.0, "metrics": {}, "source": "default"}


def update_feedback() -> dict:
    """扫描最新 backtest 报告，提取指标并计算分数，写入 .runtime/report_feedback.json。

    Returns: feedback dict（含 report_score 和 metrics）
    """
    report_path = find_latest_backtest()
    if report_path is None:
        # 没有报告可用，使用默认中性分数
        feedback = {
            "report_score": 50.0,
            "metrics": {},
            "source": "default_no_report",
            "report_file": None,
        }
    else:
        md_text = report_path.read_text(encoding="utf-8", errors="replace")
        metrics = extract_metrics(md_text)
        score = compute_score(metrics)
        feedback = {
            "report_score": score,
            "metrics": metrics,
            "source": str(report_path.relative_to(BASE_DIR)),
            "report_file": str(report_path.resolve()),
        }

    # 写入 .runtime/
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    tmp = FEEDBACK_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(feedback, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(FEEDBACK_FILE)

    return feedback


def get_report_adjustment() -> dict:
    """获取 report_feedback 对信号的调整权重。

    Returns {
        "weight_multiplier": float,    # signal strength 乘数 (0.8~1.2)
        "confidence_adjust": float,     # confidence 调整量 (-0.2~+0.2)
        "report_score": float,          # 原始分数
    }

    规则：
    - score >= 80 → 策略效果好，信号权重 +20%
    - score >= 60 → 效果尚可，信号权重 +10%
    - score >= 40 → 中性，不做调整
    - score >= 20 → 效果偏差，信号权重 -10%
    - score < 20  → 效果差，信号权重 -20%
    """
    feedback = read_feedback()
    score = feedback.get("report_score", 50.0)

    if score >= 80:
        weight_multiplier = 1.20
        confidence_adjust = 0.20
    elif score >= 60:
        weight_multiplier = 1.10
        confidence_adjust = 0.10
    elif score >= 40:
        weight_multiplier = 1.00
        confidence_adjust = 0.00
    elif score >= 20:
        weight_multiplier = 0.90
        confidence_adjust = -0.10
    else:
        weight_multiplier = 0.80
        confidence_adjust = -0.20

    return {
        "weight_multiplier": weight_multiplier,
        "confidence_adjust": confidence_adjust,
        "report_score": score,
    }


# ── CLI 入口 ────────────────────────────────────────────────────────────────


def main() -> None:
    """CLI：手动触发 report_feedback 更新。"""
    feedback = update_feedback()
    print(f"[report_feedback] score={feedback['report_score']}")
    if feedback.get("metrics"):
        m = feedback["metrics"]
        print(f"  总收益率={m.get('total_return_pct')}% "
              f"回撤={m.get('max_drawdown_pct')}% "
              f"胜率={m.get('win_rate_pct')}% "
              f"交易={m.get('trade_count')}")
    print(f"  来源={feedback.get('source')}")


if __name__ == "__main__":
    main()