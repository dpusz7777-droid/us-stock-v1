# -*- coding: utf-8 -*-
"""持仓决策集中配置 — 不散落在 Streamlit 页面代码中。

本模块只定义风险控制阈值与决策规则参数。
不移出交易逻辑，不做行情或持仓计算。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

D = Decimal


# ---------------------------------------------------------------------------
# 仓位与现金风险上限
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RiskLimits:
    """账户级风险上限，全部用 Decimal 表示百分比因子。

    因子含义（除以 100 后用于计算）：
        max_single_pct: 单只股票最高仓位 / 总资产
        max_total_pct: 总持仓最高比例 / 总资产
        min_cash_pct: 最低保留现金 / 总资产
        add_amount_min_pct: 单次加仓金额下限 / 总资产
        add_amount_max_pct: 单次加仓金额上限 / 总资产
        max_loss_per_trade_pct: 单笔最大亏损 / 总资产
        emergency_stop_loss_pct: 持仓成本下方紧急风险参考线比例（非技术止损）
        reward_risk_min_ratio: 最低风险收益比
    """

    max_single_pct: Decimal = D("20")
    max_total_pct: Decimal = D("70")
    min_cash_pct: Decimal = D("30")
    add_amount_min_pct: Decimal = D("5")
    add_amount_max_pct: Decimal = D("10")
    max_loss_per_trade_pct: Decimal = D("0.5")  # 0.5%
    emergency_stop_loss_pct: Decimal = D("8")  # 成本下方 8% 紧急参考线
    reward_risk_min_ratio: Decimal = D("2")

    # 用于验证建议数量的股数精度（向下取整到整数股）
    lot_size: int = 1


# ---------------------------------------------------------------------------
# ATR / MA 计算参数
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TechnicalParams:
    """技术指标参数。"""

    atr_period: int = 14
    atr_stop_multiplier: Decimal = D("2.0")  # 止损 = 当前价格 - ATR × 倍数
    atr_take_profit_multiplier: Decimal = D("1.5")  # 第一目标最小 R
    ma_fast: int = 5
    ma_medium_period: int = 20
    ma_slow: int = 50
    history_days_min: int = 60  # 最少 60 日 K 线
    swing_low_days: int = 10  # 最近 N 日低点
    swing_high_days: int = 20  # 最近 N 日高点
    # 加仓区间：价格偏离 MA20 的允许范围
    add_zone_ma20_offset_pct: Decimal = D("3")  # ±3%


# ---------------------------------------------------------------------------
# 数据新鲜度
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FreshnessParams:
    """行情数据新鲜度要求。

    在交易时段：
        stale_minutes_market_open: 超过此分钟数未更新视为过期
    在非交易时段：
        上一交易日收盘可降级使用但必须标注。
    """

    stale_minutes_market_open: int = 30  # 30 分钟
    # 非交易时段允许最近 1 个交易日的数据
    max_weekend_hours: int = 72  # 允许周末/假期最多 72 小时前的数据


# ---------------------------------------------------------------------------
# 止盈规则
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProfitRule:
    """止盈参数。

    target1_reduce_ratio: 达到第一目标时减仓比例
    target2_reduce_ratio: 达到第二目标时再减仓比例
    r_multiple_target1: 第一目标最低倍率（R 单位）
    r_multiple_target2: 第二目标最低倍率（R 单位）
    """

    target1_reduce_ratio: Decimal = D("0.33")
    target2_reduce_ratio: Decimal = D("0.33")
    r_multiple_target1: Decimal = D("1")
    r_multiple_target2: Decimal = D("2")


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 证券主数据 — 当远程身份接口不可用或返回明显错误时使用
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SecurityMasterRecord:
    """官方证券主数据。"""
    symbol: str
    issuer_name: str
    security_type: str
    exchange: str
    valid_history_start: str  # YYYY-MM-DD，早于此日期的K线无条件排除


# 已知证券主数据（按官方来源手工维护）
SECURITY_MASTER: dict[str, SecurityMasterRecord] = {
    "SPCX": SecurityMasterRecord(
        symbol="SPCX",
        issuer_name="Space Exploration Technologies Corp.",
        security_type="Class A Common Stock",
        exchange="Nasdaq",
        valid_history_start="2026-06-12",
    ),
}


def get_security_master(symbol: str) -> SecurityMasterRecord | None:
    return SECURITY_MASTER.get(symbol.upper())


# ---------------------------------------------------------------------------
# 单例工厂
# ---------------------------------------------------------------------------

_risk_limits: RiskLimits | None = None
_technical_params: TechnicalParams | None = None
_freshness_params: FreshnessParams | None = None
_profit_rule: ProfitRule | None = None


def get_risk_limits() -> RiskLimits:
    global _risk_limits
    if _risk_limits is None:
        _risk_limits = RiskLimits()
    return _risk_limits


def get_technical_params() -> TechnicalParams:
    global _technical_params
    if _technical_params is None:
        _technical_params = TechnicalParams()
    return _technical_params


def get_freshness_params() -> FreshnessParams:
    global _freshness_params
    if _freshness_params is None:
        _freshness_params = FreshnessParams()
    return _freshness_params


def get_profit_rule() -> ProfitRule:
    global _profit_rule
    if _profit_rule is None:
        _profit_rule = ProfitRule()
    return _profit_rule


# 允许测试中覆盖（仅用于测试）
def override_risk_limits(limits: RiskLimits) -> None:
    global _risk_limits
    _risk_limits = limits


def override_technical_params(params: TechnicalParams) -> None:
    global _technical_params
    _technical_params = params


def override_freshness_params(params: FreshnessParams) -> None:
    global _freshness_params
    _freshness_params = params


def override_profit_rule(rule: ProfitRule) -> None:
    global _profit_rule
    _profit_rule = rule


def reset_all_overrides() -> None:
    global _risk_limits, _technical_params, _freshness_params, _profit_rule
    _risk_limits = RiskLimits()
    _technical_params = TechnicalParams()
    _freshness_params = FreshnessParams()
    _profit_rule = ProfitRule()