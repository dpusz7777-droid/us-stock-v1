#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""北极星 V1 保守反馈模块 — 策略评分 + 权重调整 + 持久化。

本模块为基础设施，不修改原始信号生成条件，不改变已有策略含义。

功能：
    - load_feedback()               : 读取策略反馈 JSON
    - save_feedback(score, report)  : 保存策略反馈 JSON (原子写入)
    - compute_adjusted_weight(score): 根据评分计算保守权重调整系数
    - compute_strategy_score(...)    : 评估已完成交易并计算策略评分

依赖的数据：
    - northstar/data/strategy_feedback.json
    - TradeRecord.pnl (从 trade_history.json 读取)

本文件是 V1 版新建实现，不是历史恢复。
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "load_feedback",
    "save_feedback",
    "compute_adjusted_weight",
    "compute_strategy_score",
    "StrategyFeedback",
    "FEEDBACK_PATH",
]

# ── 文件路径 (基于源码目录的绝对路径) ──────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "northstar" / "data"
FEEDBACK_PATH = DATA_DIR / "strategy_feedback.json"


# ── 数据结构 ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StrategyFeedback:
    """策略反馈评分 (V1 schema)。"""
    strategy_score: float = 50.0
    win_rate: float = 0.0
    profit_factor: float = 1.0
    max_drawdown: float = 0.0
    trend_accuracy: float | None = None
    risk_level: str = "medium"
    adaptability: float = 1.0
    summary: str = "暂无足够数据。"


# ── 中性反馈 (文件不存在或损坏时的默认值) ────────────────────────────────

_NEUTRAL_FEEDBACK: dict[str, Any] = {
    "schema_version": 1,
    "score": 50.0,
    "adjusted_weight": 1.0,
    "sample_size": 0,
    "sufficient_sample": False,
    "metrics": {
        "win_rate": None,
        "profit_factor": None,
        "prediction_accuracy": None,
        "raw_score": 50.0,
        "reliability": 0.0,
    },
    "report": {},
    "updated_at": None,
}


# ── 工具函数 ────────────────────────────────────────────────────────────────


def _clamp(value: float, low: float, high: float) -> float:
    """限制值在 [low, high] 范围内。"""
    return max(low, min(high, value))


def _safe_float(value: Any, default: float = 50.0) -> float:
    """安全转换为 float，非法值返回默认值。"""
    if value is None:
        return default
    try:
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except (ValueError, TypeError):
        return default


# ── load_feedback ──────────────────────────────────────────────────────────


def load_feedback() -> dict[str, Any]:
    """加载策略反馈。

    规则：
        - 文件不存在 → 返回中性反馈 (score=50, weight=1.0)
        - JSON 损坏 → 记录错误，返回中性反馈
        - 字段缺失 → 中性默认值补齐
        - schema_version 不匹配 → 返回中性反馈

    Returns:
        dict: {
            "strategy_score": float (0-100),
            "adjusted_weight": float (0.90-1.10),
            "sample_size": int,
            "sufficient_sample": bool,
            "metrics": dict,
        }
    """
    if not FEEDBACK_PATH.exists():
        return dict(_NEUTRAL_FEEDBACK)

    try:
        with open(FEEDBACK_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        import sys
        print(f"[strategy_feedback] 警告: JSON 解析失败: {FEEDBACK_PATH}", file=sys.stderr)
        raise
    except (FileNotFoundError, PermissionError, OSError) as e:
        import sys
        print(f"[strategy_feedback] 警告: 读取失败 ({type(e).__name__}): {e}", file=sys.stderr)
        raise

    if not isinstance(data, dict):
        raise ValueError(f"strategy feedback must be a JSON object: {FEEDBACK_PATH}")

    if data.get("schema_version") != 1:
        raise ValueError(
            f"unsupported strategy feedback schema: {data.get('schema_version')!r}"
        )

    score = _safe_float(data.get("score", 50.0), 50.0)
    score = _clamp(score, 0.0, 100.0)

    weight = _safe_float(data.get("adjusted_weight", 1.0), 1.0)
    weight = _clamp(weight, 0.90, 1.10)

    sample_size = int(_safe_float(data.get("sample_size", 0), 0))
    sufficient = data.get("sufficient_sample", False) if sample_size >= 10 else False

    metrics = data.get("metrics", {})
    if not isinstance(metrics, dict):
        metrics = {}

    return {
        "schema_version": 1,
        "score": score,
        "adjusted_weight": weight,
        "strategy_score": int(round(score)),
        "sample_size": sample_size,
        "sufficient_sample": sufficient,
        "metrics": {
            "win_rate": metrics.get("win_rate"),
            "profit_factor": metrics.get("profit_factor"),
            "prediction_accuracy": metrics.get("prediction_accuracy"),
            "raw_score": metrics.get("raw_score", 50.0),
            "reliability": metrics.get("reliability", 0.0),
        },
        "report": data.get("report", {}),
        "updated_at": data.get("updated_at"),
    }


# ── compute_adjusted_weight ────────────────────────────────────────────────


def compute_adjusted_weight(score: float | int | None) -> float:
    """根据策略评分计算保守权重调整系数。

    权重范围: 0.90 ~ 1.10 (保守)
    线性映射: score(0) → 0.90, score(50) → 1.00, score(100) → 1.10

    Args:
        score: 策略评分 (0-100), None 或非法值返回 1.0

    Returns:
        float: 权重系数 (0.90 ~ 1.10)
    """
    safe_score = _safe_float(score, 50.0)
    normalized = _clamp(safe_score, 0.0, 100.0)

    # 线性插值: 0.90 + normalized / 100 * 0.20
    adjusted = 0.90 + normalized / 100.0 * 0.20
    return round(_clamp(adjusted, 0.90, 1.10), 4)


# ── compute_strategy_score ────────────────────────────────────────────────


def compute_strategy_score(
    win_rate: float = 0.0,
    profit_factor: float = 1.0,
    max_drawdown: float = 0.0,
    total_return_pct: float = 0.0,
    num_trades: int = 0,
) -> StrategyFeedback:
    """评估策略表现并计算综合评分。

    适配 evaluator.py 的调用契约：接收来自 EvaluationReport 的数值。

    第一步：有效交易门槛
        - num_trades < 10: score=50, 不改变权重

    第二步：核心指标计算 (仅 num_trades >= 10)

    指标分解：
        A. win_rate_score = win_rate * 100 (0-100)
        B. profit_factor_score (保守映射):
           - <=0 → 0, 0.5 → 25, 1.0 → 50, 1.5 → 75, >=2.0 → 100
        C. prediction_score: 无 prediction 数据时 = 50

    原始评分:
        raw = win_rate*0.40 + profit_factor*0.40 + prediction*0.20

    样本可靠度收缩:
        reliability = min(num_trades / 30.0, 1.0)
        final = 50 + (raw - 50) * reliability

    Returns:
        StrategyFeedback dataclass
    """
    # 安全处理输入
    wr = _clamp(_safe_float(win_rate, 0.0), 0.0, 1.0)
    pf = _safe_float(profit_factor, 1.0)
    nt = max(0, int(num_trades))

    # 不足最小样本
    if nt < 10:
        return StrategyFeedback(
            strategy_score=50.0,
            win_rate=round(wr, 4),
            profit_factor=round(pf, 2),
            max_drawdown=round(_safe_float(max_drawdown, 0.0), 2),
            trend_accuracy=None,
            risk_level="low",
            adaptability=1.0,
            summary=f"样本不足 (n={nt} < 10)，使用中性评分 50。",
        )

    # A. 胜率评分
    win_rate_score = wr * 100.0

    # B. profit factor 评分 (保守映射)
    if pf <= 0:
        pf_score = 0.0
    elif pf >= 2.0:
        pf_score = 100.0
    else:
        # 线性映射: 0→0, 0.5→25, 1.0→50, 1.5→75, 2.0→100
        pf_score = pf / 2.0 * 100.0

    pf_score = _clamp(pf_score, 0.0, 100.0)

    # C. prediction score — 无 prediction 数据时使用中性值 50
    prediction_score = 50.0

    # 原始评分
    raw_score = win_rate_score * 0.40 + pf_score * 0.40 + prediction_score * 0.20
    raw_score = _clamp(raw_score, 0.0, 100.0)

    # 样本可靠度收缩
    reliability = _clamp(nt / 30.0, 0.0, 1.0)
    final_score = 50.0 + (raw_score - 50.0) * reliability
    final_score = round(_clamp(final_score, 0.0, 100.0), 2)

    # 风险等级判定
    dd = _safe_float(max_drawdown, 0.0)
    if dd <= -15:
        risk_level = "high"
    elif dd <= -8:
        risk_level = "medium"
    else:
        risk_level = "low"

    # 适应性 (基于样本量)
    adaptability = round(0.5 + reliability * 0.5, 2)

    # 摘要
    if final_score >= 60:
        summary = f"策略表现良好：评分 {final_score:.0f}/100，样本数 {nt}。"
    elif final_score >= 40:
        summary = f"策略表现中等：评分 {final_score:.0f}/100，样本数 {nt}。"
    else:
        summary = f"策略表现偏弱：评分 {final_score:.0f}/100，样本数 {nt}，建议关注风险。"

    return StrategyFeedback(
        strategy_score=final_score,
        win_rate=round(wr, 4),
        profit_factor=round(pf, 2),
        max_drawdown=round(dd, 2),
        trend_accuracy=None,
        risk_level=risk_level,
        adaptability=adaptability,
        summary=summary,
    )


# ── save_feedback ──────────────────────────────────────────────────────────


def save_feedback(
    feedback: StrategyFeedback | dict[str, Any] | Any,
) -> None:
    """以原子写入方式保存策略反馈。

    支持 evaluator.py 传入 StrategyFeedback dataclass 对象。

    Args:
        feedback: StrategyFeedback dataclass 或兼容字典
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 解析输入
    if isinstance(feedback, StrategyFeedback):
        d = asdict(feedback)
        score = _safe_float(d.get("strategy_score", 50.0), 50.0)
        wr = _safe_float(d.get("win_rate", 0.0), 0.0)
        pf = _safe_float(d.get("profit_factor", 1.0), 1.0)
    elif isinstance(feedback, dict):
        score = _safe_float(feedback.get("strategy_score", 50.0), 50.0)
        wr = _safe_float(feedback.get("win_rate", 0.0), 0.0)
        pf = _safe_float(feedback.get("profit_factor", 1.0), 1.0)
    else:
        score = 50.0
        wr = 0.0
        pf = 1.0

    score = _clamp(score, 0.0, 100.0)
    weight = compute_adjusted_weight(score)

    sample_size = 0
    if isinstance(feedback, StrategyFeedback):
        pass  # sample_size 不由 dataclass 直接提供
    elif isinstance(feedback, dict):
        sample_size = int(_safe_float(feedback.get("sample_size", 0), 0))

    # 计算 reliable 指标
    wr_clamped = _clamp(wr, 0.0, 1.0)
    if pf is not None and not (math.isnan(pf) or math.isinf(pf)):
        pf_clamped = _clamp(pf, 0.0, 100.0)
    else:
        pf_clamped = 1.0
    if pf_clamped <= 0:
        pf_score = 0.0
    elif pf_clamped >= 2.0:
        pf_score = 100.0
    else:
        pf_score = pf_clamped / 2.0 * 100.0
    pf_score = _clamp(pf_score, 0.0, 100.0)
    raw_score = _clamp(wr_clamped * 100 * 0.40 + pf_score * 0.40 + 50.0 * 0.20, 0.0, 100.0)
    reliability = _clamp(sample_size / 30.0, 0.0, 1.0)

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    payload: dict[str, Any] = {
        "schema_version": 1,
        "score": score,
        "adjusted_weight": weight,
        "sample_size": sample_size,
        "sufficient_sample": sample_size >= 10,
        "metrics": {
            "win_rate": round(wr_clamped, 4),
            "profit_factor": round(pf_clamped, 2),
            "prediction_accuracy": None,
            "raw_score": round(raw_score, 2),
            "reliability": round(reliability, 4),
        },
        "report": {},
        "updated_at": now_utc,
    }

    # 原子写入: .tmp → fsync → replace
    tmp_path = FEEDBACK_PATH.with_suffix(".json.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, FEEDBACK_PATH)
    except OSError as e:
        import sys
        print(f"[strategy_feedback] 保存失败: {e}", file=sys.stderr)
        # 清理 tmp 文件
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise
