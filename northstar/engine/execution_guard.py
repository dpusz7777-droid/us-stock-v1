#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""执行安全保护模块。

对即将下达的交易信号执行多项安全检查，阻止不符合条件的信号执行。
当前只做只读判断，不修改账户、不下单、不连接券商。

安全检查顺序（优先级从高到低）：
    1. 治理锁定（标的级别）— 被锁定的标的任何操作都被阻止
    2. 策略锁定（策略级别）— 被锁定的策略全部阻止
    3. 漂移保护 — 检测到策略漂移时阻止非卖出操作
    4. 高波动率保护 — 波动率超过阈值阻止买入
    5. 持仓上限保护 — 持仓占比超过阈值阻止买入
    6. 最低置信度门槛 — 低于阈值的任何操作被阻止
    7. 横盘行情抑制 — 横盘状态下抑制动量策略
    8. 熊市仓位调整 — 熊市中自动降低买入仓位

安全原则：
    - 默认安全：异常、缺失字段、非法输入均不放行
    - 只读检查：不修改原始信号对象（复制后处理）
    - 无交易执行：本模块不调用任何 broker 下单接口
    - 无凭证操作：不读取也不输出任何账户凭证
    - 可审计：每条被阻止的信号都有明确的 blocked_reasons
"""

from __future__ import annotations

from typing import Any

# ── 阈值常量 ──────────────────────────────────────────────────
# 波动率（VIX 或类似指标）超过此值时阻止买入
_VOLATILITY_CAP: float = 0.30
# 持仓市值占总资产比例超过此值时阻止买入
_EXPOSURE_CAP: float = 0.65
# 信号置信度低于此值时阻止执行（买入 / 卖出均阻止）
_CONFIDENCE_FLOOR: float = 0.55
# 熊市中买入仓位比例上限
_BEAR_POSITION_SIZING: float = 0.1


def guard_execution(
    signals: list[dict[str, Any]],
    portfolio_snapshot: dict[str, Any],
    market_context: dict[str, Any],
    governance_state: dict[str, Any],
) -> list[dict[str, Any]]:
    """对信号列表依次执行安全检查，返回带安全标注的信号列表。

    Parameters
    ----------
    signals : list[dict]
        待检查的信号列表。每个信号应包含 symbol、recalibrated_action（或 action）、
        confidence、position_sizing、strategy_source 等字段。
        空列表直接返回 []。
    portfolio_snapshot : dict
        投资组合快照，支持 position_value、total_value、cash、exposure 等字段。
    market_context : dict
        市场环境，支持 market_regime、volatility 等字段。
    governance_state : dict
        治理状态，支持 locked_strategies（list[str | dict]）、drift_detected、
        risk_level 等字段。

    Returns
    -------
    list[dict]
        每个信号新增以下字段：
        - original_action : str      进入安全检查前的原始动作
        - final_action : str         安全检查后的最终动作（BUY / SELL / HOLD）
        - blocked_reasons : list[str] 被阻止的原因列表（空列表表示未被阻止）
        - position_sizing : float    可能被调整后的仓位比例
        原有字段均保留。
    """
    if not signals:
        return []

    volatility = _safe_float(market_context, "volatility")
    market_regime = str(market_context.get("market_regime", "")).lower()
    drift_detected = bool(governance_state.get("drift_detected"))
    exposure = _calc_exposure(portfolio_snapshot)

    result: list[dict[str, Any]] = []

    for sig in signals:
        # 不修改原始信号对象
        signal_out = dict(sig)

        # 确定原始动作（向后兼容：优先 recalibrated_action，其次 action）
        original_action = _resolve_action(signal_out)
        if not original_action:
            original_action = "HOLD"

        blocked_reasons: list[str] = []

        # ── 检查 1：治理锁定（标的级别）────────────────────────
        if _check_governance_lock(signal_out, governance_state):
            blocked_reasons.append("governance lock override")

        # ── 检查 2：策略锁定 ──────────────────────────────────
        if not blocked_reasons and _check_strategy_lock(
            signal_out, governance_state
        ):
            blocked_reasons.append("strategy locked by governance")

        # ── 检查 3：漂移保护（仅阻止非卖出操作）────────────────
        if (
            not blocked_reasons
            and drift_detected
            and original_action != "SELL"
        ):
            blocked_reasons.append("governance drift protection")

        # ── 检查 4：高波动率保护（仅阻止买入）─────────────────
        if (
            not blocked_reasons
            and original_action == "BUY"
            and volatility is not None
            and volatility > _VOLATILITY_CAP
        ):
            blocked_reasons.append("high volatility market")

        # ── 检查 5：持仓上限保护（仅阻止买入）─────────────────
        if (
            not blocked_reasons
            and original_action == "BUY"
            and exposure is not None
            and exposure > _EXPOSURE_CAP
        ):
            blocked_reasons.append("exposure cap reached")

        # ── 检查 6：最低置信度门槛（买入 / 卖出均检查）────────
        if not blocked_reasons and _check_confidence_fails(
            signal_out, original_action
        ):
            blocked_reasons.append("confidence below execution floor")

        # ── 检查 7：横盘行情抑制高风险策略 ────────────────────
        if not blocked_reasons and _check_sideways_suppression(
            signal_out, market_regime
        ):
            blocked_reasons.append(
                "sideways regime suppresses high-risk strategy"
            )

        # ── 决定最终动作 ──────────────────────────────────────
        if blocked_reasons:
            final_action = "HOLD"
        else:
            final_action = original_action

        # ── 检查 8：熊市仓位调整 ─────────────────────────────
        if (
            not blocked_reasons
            and final_action == "BUY"
            and market_regime == "bear"
        ):
            signal_out["position_sizing"] = _BEAR_POSITION_SIZING

        # ── 写入审计字段（向后兼容扩展）──────────────────────
        signal_out["original_action"] = original_action
        signal_out["final_action"] = final_action
        signal_out["blocked_reasons"] = blocked_reasons

        result.append(signal_out)

    return result


# ── 内部工具函数 ──────────────────────────────────────────────


def _safe_float(d: dict[str, Any], key: str) -> float | None:
    """安全提取浮点值，异常或缺失时返回 None。"""
    v = d.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _calc_exposure(portfolio: dict[str, Any]) -> float | None:
    """计算当前持仓占比。

    优先使用预计算的 exposure 字段；否则从 position_value / total_value 计算。
    """
    exp = _safe_float(portfolio, "exposure")
    if exp is not None:
        return exp
    pv = _safe_float(portfolio, "position_value")
    tv = _safe_float(portfolio, "total_value")
    if pv is not None and tv is not None and tv > 0:
        return pv / tv
    return None


def _resolve_action(signal_out: dict[str, Any]) -> str | None:
    """向后兼容：优先 recalibrated_action，其次 action。"""
    action = signal_out.get("recalibrated_action")
    if action:
        return str(action).upper()
    action = signal_out.get("action")
    if action:
        return str(action).upper()
    return None


def _check_governance_lock(
    signal_out: dict[str, Any],
    governance_state: dict[str, Any],
) -> bool:
    """检查交易标的是否被治理锁定。

    locked_strategies 支持两种格式：
        - ["NVDA", "AAPL"]   （纯标的代码列表）
        - [{"symbol": "NVDA"}] （对象格式）
    """
    symbol = str(signal_out.get("symbol", "")).upper()
    if not symbol:
        return False
    locked = governance_state.get("locked_strategies")
    if not locked or not isinstance(locked, list):
        return False
    for entry in locked:
        if isinstance(entry, str) and entry.upper() == symbol:
            return True
        if isinstance(entry, dict) and str(entry.get("symbol", "")).upper() == symbol:
            return True
    return False


def _check_strategy_lock(
    signal_out: dict[str, Any],
    governance_state: dict[str, Any],
) -> bool:
    """检查策略是否被治理锁定。

    locked_strategies 支持 dict 格式 [{"strategy": "momentum"}]，
    通过策略名称匹配 signal 的 strategy_source 字段。
    """
    strategy_source = str(signal_out.get("strategy_source", ""))
    if not strategy_source:
        return False
    locked = governance_state.get("locked_strategies")
    if not locked or not isinstance(locked, list):
        return False
    search_text = strategy_source.lower()
    for entry in locked:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("strategy", "")).lower()
        if name and (name in search_text):
            return True
    return False


def _check_confidence_fails(
    signal_out: dict[str, Any],
    original_action: str,
) -> bool:
    """检查置信度是否低于执行下限。

    缺失 confidence 字段视为低于下限，以保证安全。
    """
    if original_action not in ("BUY", "SELL"):
        return False
    confidence = _safe_float(signal_out, "confidence")
    if confidence is None:
        return True
    return confidence < _CONFIDENCE_FLOOR


def _check_sideways_suppression(
    signal_out: dict[str, Any],
    market_regime: str,
) -> bool:
    """横盘行情下抑制动量等高风险策略。"""
    if market_regime != "sideways":
        return False
    strategy_source = str(signal_out.get("strategy_source", "")).lower()
    return "momentum" in strategy_source

