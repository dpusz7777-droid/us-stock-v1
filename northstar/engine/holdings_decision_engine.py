# -*- coding: utf-8 -*-
"""持仓决策引擎 — 针对每一只真实持仓输出操作建议。

本模块：
- 只处理真实持仓（不选股）
- 从 Yahoo Chart 获取 60 日 K 线计算 MA/ATR
- 按决策优先级输出持有/加仓候选/减仓/清仓/数据不足
- 配置集中在 holdings_decision_config.py
- 不连接券商、不自动下单、不修改真实持仓
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Mapping

from northstar.config.holdings_decision_config import (
    FreshnessParams,
    ProfitRule,
    RiskLimits,
    TechnicalParams,
    get_freshness_params,
    get_risk_limits,
    get_security_master,
    get_technical_params,
)

D = Decimal
ZERO = D("0")
ONE_HUNDRED = D("100")


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SecurityIdentity:
    """证券身份信息。"""

    symbol: str
    long_name: str | None = None
    short_name: str | None = None
    quote_type: str | None = None
    exchange: str | None = None
    currency: str | None = None
    first_trade_date: str | None = None
    data_start_date: str | None = None  # 实际有效 K 线起点
    is_identity_verified: bool = False
    identity_notes: str = ""


@dataclass(frozen=True)
class TechnicalIndicators:
    """K 线计算出的技术指标。"""

    symbol: str
    ma5: Decimal | None = None
    ma10: Decimal | None = None
    ma20: Decimal | None = None
    ma50: Decimal | None = None
    ma50_available: bool = False
    atr14: Decimal | None = None
    swing_low_10: Decimal | None = None
    swing_high_10: Decimal | None = None
    swing_high_20: Decimal | None = None
    price_vs_ma20_pct: Decimal | None = None
    price_vs_ma50_pct: Decimal | None = None
    data_count: int = 0
    last_data_time: str | None = None
    calculation_notes: tuple[str, ...] = ()

    @property
    def is_complete(self) -> bool:
        return self.data_count >= 60 and self.atr14 is not None


@dataclass(frozen=True)
class PriceLevel:
    """价格与数据新鲜度。

    is_realtime: 是否为实时/延迟行情（交易时段内）
    """

    price: Decimal
    previous_close: Decimal | None
    price_as_of: str
    source: str
    is_trading_hours: bool
    is_stale: bool
    is_realtime: bool = False
    market_data_note: str = ""


@dataclass(frozen=True)
class PositionInfo:
    """持仓信息。"""

    symbol: str
    shares: Decimal
    avg_cost: Decimal
    cost_basis: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal
    unrealized_pnl_pct: Decimal
    position_pct: Decimal


@dataclass(frozen=True)
class HoldingsDecision:
    """单只持仓的完整操作建议。"""

    symbol: str
    action: str
    need_action_today: bool
    need_action_today_reason: str

    shares: Decimal
    avg_cost: Decimal
    current_price: Decimal | None
    market_value: Decimal | None
    unrealized_pnl: Decimal | None
    unrealized_pnl_pct: Decimal | None

    suggested_shares: int | None
    suggested_pct: Decimal | None

    stop_loss_price: Decimal | None
    emergency_stop_price: Decimal | None
    target1_price: Decimal | None
    target2_price: Decimal | None

    hold_condition: str
    add_condition: str
    reduce_condition: str
    exit_condition: str

    reason: str
    main_risk: str

    data_updated_at: str
    data_integrity: str
    market_data_note: str = ""

    stop_loss_formula: str = ""
    target_price_formula: str = ""
    sizing_formula: str = ""
    position_pct: Decimal | None = None

    # 风控限制明细
    risk_constraints_detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "action": self.action,
            "need_action_today": self.need_action_today,
            "need_action_today_reason": self.need_action_today_reason,
            "shares": str(self.shares),
            "avg_cost": str(self.avg_cost),
            "current_price": str(self.current_price) if self.current_price is not None else None,
            "market_value": str(self.market_value) if self.market_value is not None else None,
            "unrealized_pnl": str(self.unrealized_pnl) if self.unrealized_pnl is not None else None,
            "unrealized_pnl_pct": str(self.unrealized_pnl_pct) if self.unrealized_pnl_pct is not None else None,
            "suggested_shares": self.suggested_shares,
            "suggested_pct": str(self.suggested_pct) if self.suggested_pct is not None else None,
            "stop_loss_price": str(self.stop_loss_price) if self.stop_loss_price is not None else None,
            "emergency_stop_price": str(self.emergency_stop_price) if self.emergency_stop_price is not None else None,
            "target1_price": str(self.target1_price) if self.target1_price is not None else None,
            "target2_price": str(self.target2_price) if self.target2_price is not None else None,
            "hold_condition": self.hold_condition,
            "add_condition": self.add_condition,
            "reduce_condition": self.reduce_condition,
            "exit_condition": self.exit_condition,
            "reason": self.reason,
            "main_risk": self.main_risk,
            "data_updated_at": self.data_updated_at,
            "data_integrity": self.data_integrity,
            "market_data_note": self.market_data_note,
            "stop_loss_formula": self.stop_loss_formula,
            "target_price_formula": self.target_price_formula,
            "sizing_formula": self.sizing_formula,
            "position_pct": str(self.position_pct) if self.position_pct is not None else None,
            "risk_constraints_detail": self.risk_constraints_detail,
        }


# ---------------------------------------------------------------------------
# 美股时区（使用 zoneinfo 处理夏令时）
# ---------------------------------------------------------------------------


def _ny_time() -> datetime:
    """返回当前纽约时区时间。"""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York"))
    except ImportError:
        utc_now = datetime.now(timezone.utc)
        # 回退到固定 EDT(UTC-4) 并注明
        from datetime import timedelta
        return utc_now - timedelta(hours=4)


def _is_us_market_hours() -> bool:
    ny = _ny_time()
    if ny.weekday() >= 5:
        return False
    total_minutes = ny.hour * 60 + ny.minute
    return 570 <= total_minutes < 960  # 9:30-16:00


def _market_data_label(price_as_of_str: str | None) -> tuple[str, bool]:
    """返回 (label, is_realtime)。"""
    if not price_as_of_str:
        return ("未知", False)
    try:
        price_dt = datetime.fromisoformat(price_as_of_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return ("未知", False)
    ny_now = _ny_time()
    ny_tz = ny_now.tzinfo
    if ny_tz is None:
        try:
            from zoneinfo import ZoneInfo
            ny_tz = ZoneInfo("America/New_York")
        except ImportError:
            ny_tz = timezone.utc
    price_ny = price_dt.astimezone(ny_tz)
    delta = ny_now - price_ny
    delta_minutes = delta.total_seconds() / 60
    is_market = _is_us_market_hours()
    if is_market and delta_minutes < 60:
        return (f"约{delta_minutes:.0f}分钟前（{price_ny.strftime('%H:%M ET')}）", True)
    if not is_market and delta_minutes < 1440:
        return (f"上一交易日 {price_ny.strftime('%m-%d %H:%M ET')}（非实时价格）", False)
    return (f"最近有效数据 {price_ny.strftime('%m-%d %H:%M ET')}（非实时价格）", False)


# ---------------------------------------------------------------------------
# K 线获取与指标计算
# ---------------------------------------------------------------------------


def _fetch_history(symbol: str) -> tuple[Any | None, str | None]:
    try:
        from northstar.data.yahoo_chart_provider import fetch_chart_history
        return fetch_chart_history(symbol, period="6mo", interval="1d"), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _fetch_identity(symbol: str, history: Any | None = None) -> SecurityIdentity:
    """获取证券身份信息（从 Yahoo 端点）。"""
    meta = getattr(history, "meta", None)
    if isinstance(meta, Mapping):
        timestamps = getattr(history, "timestamps", None) or []
        data_start = (
            datetime.fromtimestamp(timestamps[0], tz=timezone.utc).strftime("%Y-%m-%d")
            if timestamps else None
        )
        return SecurityIdentity(
            symbol=symbol.strip().upper(),
            long_name=meta.get("longName"),
            short_name=meta.get("shortName"),
            quote_type=meta.get("instrumentType") or meta.get("quoteType"),
            exchange=meta.get("exchangeName") or meta.get("fullExchangeName"),
            currency=meta.get("currency"),
            first_trade_date=(
                datetime.fromtimestamp(meta["firstTradeDate"], tz=timezone.utc).strftime("%Y-%m-%d")
                if meta.get("firstTradeDate") else None
            ),
            data_start_date=data_start,
            is_identity_verified=True,
        )
    try:
        from northstar.config.network import get_price_provider_session, get_request_timeout
        session = get_price_provider_session()
        timeout = get_request_timeout()
        encoded = __import__('urllib.parse', fromlist=['quote']).quote(symbol.strip().upper(), safe="")
        for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
            try:
                url = f"https://{host}/v8/finance/chart/{encoded}"
                resp = session.get(url, params={"range": "6mo", "interval": "1d"}, timeout=timeout)
                if resp.status_code != 200:
                    continue
                payload = resp.json().get("chart", {})
                if payload.get("error"):
                    continue
                results = payload.get("result") or []
                if not results:
                    continue
                item = results[0]
                meta = item.get("meta", {})
                timestamps = item.get("timestamp") or []
                data_start = (
                    datetime.fromtimestamp(timestamps[0], tz=timezone.utc).strftime("%Y-%m-%d")
                    if timestamps else None
                )
                return SecurityIdentity(
                    symbol=symbol.strip().upper(),
                    long_name=meta.get("longName"),
                    short_name=meta.get("shortName"),
                    quote_type=meta.get("instrumentType") or meta.get("quoteType"),
                    exchange=meta.get("exchangeName") or meta.get("fullExchangeName"),
                    currency=meta.get("currency"),
                    first_trade_date=(
                        datetime.fromtimestamp(meta["firstTradeDate"], tz=timezone.utc).strftime("%Y-%m-%d")
                        if meta.get("firstTradeDate") else None
                    ),
                    data_start_date=data_start,
                    is_identity_verified=True,
                )
            except Exception:
                continue
    except Exception:
        pass
    return SecurityIdentity(
        symbol=symbol.strip().upper(),
        identity_notes="无法获取证券身份信息。",
    )


def _filter_valid_history(history: Any, min_date: str | None) -> Any | None:
    """过滤掉某日期之前的旧数据。"""
    if history is None or min_date is None:
        return history
    import copy
    try:
        cutoff = datetime.fromisoformat(min_date).replace(tzinfo=timezone.utc).timestamp()
        filtered = copy.copy(history)
        new_ts = []
        new_o = []
        new_h = []
        new_l = []
        new_c = []
        new_v = []
        for i, ts in enumerate(history.timestamps):
            if ts >= cutoff:
                new_ts.append(ts)
                new_o.append(history.open[i] if i < len(history.open) else None)
                new_h.append(history.high[i] if i < len(history.high) else None)
                new_l.append(history.low[i] if i < len(history.low) else None)
                new_c.append(history.close[i] if i < len(history.close) else None)
                new_v.append(history.volume[i] if i < len(history.volume) else None)
        filtered.timestamps = new_ts
        filtered.open = new_o
        filtered.high = new_h
        filtered.low = new_l
        filtered.close = new_c
        filtered.volume = new_v
        return filtered
    except Exception:
        return history


def _sma(values: list[Decimal], period: int) -> Decimal | None:
    subset = [v for v in values if v is not None and v > ZERO]
    if len(subset) < period:
        return None
    return sum(subset[-period:], start=ZERO) / D(str(period))


def _true_range(high: Decimal, low: Decimal, prev_close: Decimal | None) -> Decimal:
    if high < ZERO or low < ZERO:
        return ZERO
    h_l = high - low
    candidates = [h_l]
    if prev_close is not None:
        candidates.append(abs(high - prev_close))
        candidates.append(abs(low - prev_close))
    return max(filter(lambda x: x >= ZERO, candidates), default=h_l)


def _atr(highs: list[Decimal], lows: list[Decimal], closes: list[Decimal], period: int) -> Decimal | None:
    if len(highs) < period + 1 or len(lows) < period + 1:
        return None
    tr_values: list[Decimal] = []
    for i in range(1, len(highs)):
        prev_close = closes[i - 1] if i > 0 and closes[i - 1] is not None else None
        tr_values.append(_true_range(highs[i], lows[i], prev_close))
    if len(tr_values) < period:
        return None
    relevant = [t for t in tr_values[-period:] if t is not None]
    if not relevant:
        return None
    return sum(relevant, start=ZERO) / D(str(len(relevant)))


def _calculate_indicators(
    symbol: str,
    current_price: Decimal,
    history: Any,
    params: TechnicalParams,
    identity: SecurityIdentity | None = None,
) -> tuple[TechnicalIndicators, SecurityIdentity | None]:
    identity = identity or _fetch_identity(symbol, history)

    if history is None:
        return TechnicalIndicators(
            symbol=symbol,
            calculation_notes=("无法获取历史 K 线数据",),
        ), identity

    try:
        closes_raw = history.close
        highs_raw = history.high
        lows_raw = history.low
    except (AttributeError, TypeError):
        return TechnicalIndicators(
            symbol=symbol,
            calculation_notes=("K 线数据格式异常",),
        ), identity

    closes = [D(str(v)) if v is not None else None for v in closes_raw]
    highs = [D(str(v)) if v is not None else None for v in highs_raw]
    lows = [D(str(v)) if v is not None else None for v in lows_raw]

    valid_count = sum(1 for v in closes if v is not None and v > ZERO)
    notes: list[str] = []

    if valid_count < params.history_days_min:
        notes.append(f"有效 K 线不足 {params.history_days_min} 日（仅 {valid_count} 日）")

    ma5 = _sma(closes, 5)
    ma10 = _sma(closes, 10) if valid_count >= 10 else None
    ma20 = _sma(closes, 20) if valid_count >= 20 else None
    ma50 = _sma(closes, 50) if valid_count >= 50 else None
    ma50_available = ma50 is not None

    if not ma50_available and valid_count >= 50:
        notes.append("MA50 数据过滤后不足 50 个有效收盘价")

    atr14 = _atr(highs, lows, closes, params.atr_period)

    valid_lows = [v for v in lows[-params.swing_low_days:] if v is not None and v > ZERO]
    valid_highs_10 = [v for v in highs[-params.swing_low_days:] if v is not None and v > ZERO]
    valid_highs_20 = [v for v in highs[-params.swing_high_days:] if v is not None and v > ZERO]
    swing_low_10 = min(valid_lows) if valid_lows else None
    swing_high_10 = max(valid_highs_10) if valid_highs_10 else None
    swing_high_20 = max(valid_highs_20) if valid_highs_20 else None

    price_vs_ma20_pct = ((current_price - ma20) / ma20 * ONE_HUNDRED) if ma20 is not None and ma20 > ZERO else None
    price_vs_ma50_pct = ((current_price - ma50) / ma50 * ONE_HUNDRED) if ma50 is not None and ma50 > ZERO else None

    try:
        last_ts = history.timestamps[-1] if history.timestamps else None
        last_data_time = (
            datetime.fromtimestamp(last_ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
            if last_ts else None
        )
    except Exception:
        last_data_time = None

    return TechnicalIndicators(
        symbol=symbol,
        ma5=ma5, ma10=ma10, ma20=ma20, ma50=ma50,
        ma50_available=ma50_available,
        atr14=atr14,
        swing_low_10=swing_low_10, swing_high_10=swing_high_10, swing_high_20=swing_high_20,
        price_vs_ma20_pct=price_vs_ma20_pct,
        price_vs_ma50_pct=price_vs_ma50_pct,
        data_count=valid_count,
        last_data_time=last_data_time,
        calculation_notes=tuple(notes),
    ), identity


# ---------------------------------------------------------------------------
# 目标价计算
# ---------------------------------------------------------------------------


def _calculate_targets(
    entry_price: Decimal,
    stop_loss: Decimal,
    swing_high_10: Decimal | None,
    swing_high_20: Decimal | None,
    r_multiple_1: Decimal,
    r_multiple_2: Decimal,
) -> tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None, str]:
    """计算目标价。

    返回 (t1_r1, t2_r2, t_near_resist, t_far_resist, formula)。
    """
    risk_per_share = entry_price - stop_loss
    if risk_per_share <= ZERO:
        return None, None, None, None, "止损价高于/等于入场价，无法计算目标。"

    t1_r = entry_price + risk_per_share * r_multiple_1
    t2_r = entry_price + risk_per_share * r_multiple_2

    t_near = None
    t_far = None
    resist_parts = []

    if swing_high_10 is not None:
        if swing_high_10 > entry_price:
            t_near = swing_high_10
            resist_parts.append(f"10日高点={swing_high_10:.2f}")

    if swing_high_20 is not None:
        if swing_high_20 > entry_price and (t_near is None or swing_high_20 > t_near):
            t_far = swing_high_20
            resist_parts.append(f"20日高点={swing_high_20:.2f}")

    formula = f"R={risk_per_share:.2f}; T1(1R)={t1_r:.2f}; T2(2R)={t2_r:.2f}"
    if resist_parts:
        formula += "; 近期阻力: " + " | ".join(resist_parts)

    return t1_r, t2_r, t_near, t_far, formula


# ---------------------------------------------------------------------------
# 建议数量计算
# ---------------------------------------------------------------------------


def _calculate_suggested_shares(
    current_price: Decimal,
    stop_loss_price: Decimal,
    total_equity: Decimal,
    current_position_value: Decimal,
    current_position_pct: Decimal,
    cash: Decimal,
    total_position_pct: Decimal,
    limits: RiskLimits,
) -> tuple[int | None, str]:
    if current_price <= ZERO or stop_loss_price >= current_price:
        return None, "止损价不低于当前价，无法计算风险。"

    risk_per_share = current_price - stop_loss_price
    max_loss_amount = total_equity * limits.max_loss_per_trade_pct / ONE_HUNDRED
    risk_shares = int(math.floor(max_loss_amount / risk_per_share))

    max_single_value = total_equity * limits.max_single_pct / ONE_HUNDRED
    remaining_value = max_single_value - current_position_value
    if remaining_value <= ZERO:
        return None, "当前持仓已达单票上限。"
    position_limit_shares = int(math.floor(remaining_value / current_price))

    # 仅使用实际现金（不含 buying_power）
    min_cash = total_equity * limits.min_cash_pct / ONE_HUNDRED
    usable_cash = max(ZERO, cash - min_cash)
    max_total_position_value = total_equity * limits.max_total_pct / ONE_HUNDRED
    current_total_position_value = total_equity * total_position_pct / ONE_HUNDRED
    available_for_new = min(
        usable_cash,
        max(ZERO, max_total_position_value - current_total_position_value),
    )
    if available_for_new <= ZERO:
        return None, f"可用现金不足(usd={usable_cash:.2f})或总仓位已达上限。"

    cash_shares = int(math.floor(available_for_new / current_price))
    min_shares = min(risk_shares, position_limit_shares, cash_shares)
    if min_shares < limits.lot_size:
        return None, (
            f"风险允许{risk_shares}股×仓位上限{position_limit_shares}股×现金允许{cash_shares}股，"
            f"最小{min_shares}<{limits.lot_size}股，不支持加仓。"
        )

    formula = (
        f"单股风险={risk_per_share:.2f}; 允许亏损={max_loss_amount:.2f}; "
        f"风险允许={risk_shares}股; 仓位上限={position_limit_shares}股; "
        f"现金允许={cash_shares}股(可用现金={usable_cash:.2f}); 取最小值={min_shares}股"
    )
    return min_shares, formula


# ---------------------------------------------------------------------------
# 数据新鲜度校验
# ---------------------------------------------------------------------------


def _check_freshness(price_as_of_str: str, freshness: FreshnessParams) -> tuple[bool, str]:
    try:
        price_time = datetime.fromisoformat(price_as_of_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return True, "行情时间格式无效。"
    now = datetime.now(timezone.utc)
    delta_minutes = (now - price_time).total_seconds() / 60
    is_market = _is_us_market_hours()
    if is_market and delta_minutes > freshness.stale_minutes_market_open:
        return True, f"交易时段行情已过期({delta_minutes:.0f}分钟前)。"
    if not is_market:
        delta_hours = delta_minutes / 60
        if delta_hours > freshness.max_weekend_hours:
            return True, f"非交易时段行情过期({delta_hours:.0f}小时前)。"
        return False, f"非交易时段·{_market_data_label(price_as_of_str)[0]}"
    return False, f"交易时段·{_market_data_label(price_as_of_str)[0]}"


# ---------------------------------------------------------------------------
# 止损价计算
# ---------------------------------------------------------------------------


def _calculate_stop_loss(
    current_price: Decimal,
    indicators: TechnicalIndicators,
    params: TechnicalParams,
) -> tuple[Decimal | None, str]:
    components: list[tuple[str, Decimal]] = []

    if indicators.swing_low_10 is not None:
        components.append(("最近10日低点", indicators.swing_low_10))

    if indicators.atr14 is not None:
        atr_stop = current_price - indicators.atr14 * params.atr_stop_multiplier
        if atr_stop > ZERO:
            components.append((f"ATR14止损(当前价-{params.atr_stop_multiplier}×ATR)", atr_stop))

    if not components:
        return None, "缺少 swing_low_10 和 ATR14，无法计算技术止损。"

    best_name, best_price = components[0]
    for name, price in components[1:]:
        if price > best_price:
            best_name, best_price = name, price

    formula = f"候选: " + "; ".join(f"{n}={p:.2f}" for n, p in components)
    if best_price >= current_price:
        formula += f" | 止损={best_name}={best_price:.2f} ≥ 当前价{current_price}（支撑已破）"
        return D(str(best_price)).quantize(D("0.01")), formula
    formula += f" | 选取最高值: {best_name}={best_price:.2f}"
    return best_price.quantize(D("0.01")), formula


# ---------------------------------------------------------------------------
# 主决策逻辑
# ---------------------------------------------------------------------------


class HoldingsDecisionEngine:

    def __init__(
        self,
        risk_limits: RiskLimits | None = None,
        tech_params: TechnicalParams | None = None,
        freshness: FreshnessParams | None = None,
        profit_rule: ProfitRule | None = None,
    ) -> None:
        self.risk_limits = risk_limits or get_risk_limits()
        self.tech_params = tech_params or get_technical_params()
        self.freshness = freshness or get_freshness_params()
        self.profit_rule = profit_rule or ProfitRule()

    def decide(
        self,
        symbol: str,
        position: PositionInfo,
        price_level: PriceLevel,
        indicators: TechnicalIndicators,
        total_equity: Decimal,
        cash: Decimal,
        total_position_pct: Decimal,
    ) -> HoldingsDecision:
        """决策优先级：
        1. 数据缺失/过期 → 数据不足
        2. 跌破止损 → 清仓/止损
        3. 仓位超上限 → 减仓
        4. 达第二目标 → 分批止盈
        5. 达第一目标 → 减仓1/3
        6. 满足全部加仓条件 → 加仓候选
        7. 趋势正常 → 持有
        8. 其他 → 持有
        """
        return self._decide_impl(symbol, position, price_level, indicators, total_equity, cash, total_position_pct)

    def _decide_impl(
        self,
        symbol: str,
        position: PositionInfo,
        price_level: PriceLevel,
        indicators: TechnicalIndicators,
        total_equity: Decimal,
        cash: Decimal,
        total_position_pct: Decimal,
    ) -> HoldingsDecision:
        price = price_level.price
        now_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        market_label, is_realtime = _market_data_label(price_level.price_as_of)

        emergency_stop = position.avg_cost * (ONE_HUNDRED - self.risk_limits.emergency_stop_loss_pct) / ONE_HUNDRED
        emergency_stop = emergency_stop.quantize(D("0.01"))

        # --- P1: 数据缺失 ---
        if not indicators.is_complete:
            missing = "历史 K 线不足 60 日" if indicators.data_count < 60 else "ATR 无法计算"
            return HoldingsDecision(
                symbol=symbol, action="数据不足", need_action_today=False,
                need_action_today_reason=f"数据不足：{missing}。",
                shares=position.shares, avg_cost=position.avg_cost,
                current_price=price, market_value=position.market_value,
                unrealized_pnl=position.unrealized_pnl, unrealized_pnl_pct=position.unrealized_pnl_pct,
                suggested_shares=None, suggested_pct=None,
                stop_loss_price=None, emergency_stop_price=emergency_stop,
                target1_price=None, target2_price=None,
                hold_condition=f"等待至少 60 日 K 线和完整 ATR 数据（当前仅 {indicators.data_count} 日）。",
                add_condition="数据不足，禁止加仓。",
                reduce_condition="数据恢复后根据止损和目标判断。",
                exit_condition=f"数据不足时无法判断。成本紧急参考线 ${emergency_stop} 仅供参考，非技术止损。",
                reason=f"历史 K 线不足：{indicators.data_count} 日。{'; '.join(indicators.calculation_notes)}",
                main_risk="缺乏足够历史数据，无法评估技术支撑和趋势。",
                data_updated_at=now_utc, data_integrity=f"历史不足({indicators.data_count}日)",
                market_data_note=market_label,
                stop_loss_formula="N/A", target_price_formula="N/A", sizing_formula="N/A",
                position_pct=position.position_pct,
            )

        # --- P1b: 价格过期 ---
        if price_level.is_stale:
            return HoldingsDecision(
                symbol=symbol, action="数据不足", need_action_today=False,
                need_action_today_reason="行情数据过期。",
                shares=position.shares, avg_cost=position.avg_cost,
                current_price=price, market_value=position.market_value,
                unrealized_pnl=position.unrealized_pnl, unrealized_pnl_pct=position.unrealized_pnl_pct,
                suggested_shares=None, suggested_pct=None,
                stop_loss_price=None, emergency_stop_price=emergency_stop,
                target1_price=None, target2_price=None,
                hold_condition="等待行情数据更新。",
                add_condition="价格过期，禁止加仓。",
                reduce_condition="数据刷新后根据技术止损判断。",
                exit_condition=f"成本紧急参考线 ${emergency_stop} 仅供仓位监控，非技术止损。",
                reason="行情数据过期，无法生成可执行建议。",
                main_risk="价格数据过期，无法判断当前市场状况。",
                data_updated_at=now_utc, data_integrity="价格过期",
                market_data_note=market_label,
                stop_loss_formula="N/A", target_price_formula="N/A", sizing_formula="N/A",
                position_pct=position.position_pct,
            )

        # --- 计算技术止损 ---
        stop_loss_price, stop_loss_formula = _calculate_stop_loss(price, indicators, self.tech_params)
        if stop_loss_price is None:
            return HoldingsDecision(
                symbol=symbol, action="数据不足", need_action_today=False,
                need_action_today_reason="无法计算技术止损。",
                shares=position.shares, avg_cost=position.avg_cost,
                current_price=price, market_value=position.market_value,
                unrealized_pnl=position.unrealized_pnl, unrealized_pnl_pct=position.unrealized_pnl_pct,
                suggested_shares=None, suggested_pct=None,
                stop_loss_price=None, emergency_stop_price=emergency_stop,
                target1_price=None, target2_price=None,
                hold_condition="缺少 swing_low_10 或 ATR14，无法计算技术止损。",
                add_condition="止损无法计算，禁止加仓。",
                reduce_condition="无法判断减仓标准。",
                exit_condition=f"成本紧急参考线 ${emergency_stop} 仅供仓位监控，非技术止损。",
                reason=stop_loss_formula,
                main_risk="缺少技术支撑参考，无法设置止损。",
                data_updated_at=now_utc, data_integrity="止损计算失败",
                market_data_note=market_label,
                stop_loss_formula=stop_loss_formula, target_price_formula="N/A", sizing_formula="N/A",
                position_pct=position.position_pct,
            )

        # --- 计算目标价 ---
        t1_r, t2_r, t_near, t_far, target_formula = _calculate_targets(
            price, stop_loss_price, indicators.swing_high_10, indicators.swing_high_20,
            self.profit_rule.r_multiple_target1,
            self.profit_rule.r_multiple_target2,
        )
        target1 = t1_r
        target2 = t2_r

        # --- P2: 跌破止损 ---
        if price <= stop_loss_price:
            return HoldingsDecision(
                symbol=symbol, action="清仓", need_action_today=True,
                need_action_today_reason="当前价格已跌破保护性止损，建议立即止损。",
                shares=position.shares, avg_cost=position.avg_cost,
                current_price=price, market_value=position.market_value,
                unrealized_pnl=position.unrealized_pnl, unrealized_pnl_pct=position.unrealized_pnl_pct,
                suggested_shares=int(position.shares), suggested_pct=D("1.0"),
                stop_loss_price=stop_loss_price, emergency_stop_price=emergency_stop,
                target1_price=target1, target2_price=target2,
                hold_condition="已触发止损，不适用。",
                add_condition="已触发止损，禁止加仓。",
                reduce_condition="已触发止损，建议全部清仓。",
                exit_condition=f"收盘有效跌破 ${stop_loss_price}，或原始交易逻辑失效。",
                reason=f"当前价格 ${price} ≤ 保护性止损 ${stop_loss_price}（{stop_loss_formula}）。",
                main_risk="继续下跌可能导致更大亏损。",
                data_updated_at=now_utc, data_integrity="完整",
                market_data_note=market_label,
                stop_loss_formula=stop_loss_formula, target_price_formula=target_formula,
                sizing_formula=f"建议清仓全部 {position.shares} 股。",
                position_pct=position.position_pct,
            )

        # --- P3: 仓位超上限 ---
        if position.position_pct >= self.risk_limits.max_single_pct:
            return HoldingsDecision(
                symbol=symbol, action="减仓", need_action_today=True,
                need_action_today_reason="当前仓位超过单票上限，建议减仓。",
                shares=position.shares, avg_cost=position.avg_cost,
                current_price=price, market_value=position.market_value,
                unrealized_pnl=position.unrealized_pnl, unrealized_pnl_pct=position.unrealized_pnl_pct,
                suggested_shares=None, suggested_pct=D("0.33"),
                stop_loss_price=stop_loss_price, emergency_stop_price=emergency_stop,
                target1_price=target1, target2_price=target2,
                hold_condition=f"必须将仓位降至 {self.risk_limits.max_single_pct}% 以下。",
                add_condition="仓位超限，禁止加仓。",
                reduce_condition=f"当前仓位 {position.position_pct}%>{self.risk_limits.max_single_pct}%。",
                exit_condition=f"如继续上涨至 ${target2 or 'N/A'} 或跌破 ${stop_loss_price}，全部清仓。",
                reason=f"仓位 {position.position_pct:.1f}% 超过单票 {self.risk_limits.max_single_pct}% 上限。",
                main_risk="过度集中风险。",
                data_updated_at=now_utc, data_integrity="完整",
                market_data_note=market_label,
                stop_loss_formula=stop_loss_formula, target_price_formula=target_formula,
                sizing_formula=f"建议减仓约三分之一(约{int(float(position.shares) * 0.33)}股)。",
                position_pct=position.position_pct,
            )

        # --- P4: 达第二目标 ---
        if target2 is not None and price >= target2:
            return HoldingsDecision(
                symbol=symbol, action="减仓", need_action_today=True,
                need_action_today_reason="已接近第二目标价，建议分批止盈并移动止损。",
                shares=position.shares, avg_cost=position.avg_cost,
                current_price=price, market_value=position.market_value,
                unrealized_pnl=position.unrealized_pnl, unrealized_pnl_pct=position.unrealized_pnl_pct,
                suggested_shares=int(float(position.shares) * 0.33),
                suggested_pct=self.profit_rule.target2_reduce_ratio,
                stop_loss_price=stop_loss_price, emergency_stop_price=emergency_stop,
                target1_price=target1, target2_price=target2,
                hold_condition="剩余仓位采用移动止损管理。",
                add_condition="已达第二目标，不建议加仓。",
                reduce_condition=f"上涨至 ${target2} 附近后，再减仓约三分之一。",
                exit_condition="趋势失效、跌破移动止损或出现明确风险时清仓。",
                reason=f"价格 ${price} 已达第二目标 ${target2}。建议分批止盈并移动止损。",
                main_risk="趋势可能加速但波动加大。",
                data_updated_at=now_utc, data_integrity="完整",
                market_data_note=market_label,
                stop_loss_formula=stop_loss_formula, target_price_formula=target_formula,
                sizing_formula=f"建议再减仓约 {int(float(position.shares) * 0.33)} 股。",
                position_pct=position.position_pct,
            )

        # --- P5: 达第一目标 ---
        if target1 is not None and price >= target1:
            return HoldingsDecision(
                symbol=symbol, action="减仓", need_action_today=True,
                need_action_today_reason="已达到第一目标价，建议减仓三分之一并提高止损。",
                shares=position.shares, avg_cost=position.avg_cost,
                current_price=price, market_value=position.market_value,
                unrealized_pnl=position.unrealized_pnl, unrealized_pnl_pct=position.unrealized_pnl_pct,
                suggested_shares=int(float(position.shares) * 0.33),
                suggested_pct=self.profit_rule.target1_reduce_ratio,
                stop_loss_price=stop_loss_price, emergency_stop_price=emergency_stop,
                target1_price=target1, target2_price=target2,
                hold_condition="剩余仓位持有，止损提高至盈亏平衡或近期支撑。",
                add_condition="已达第一目标，不建议加仓。",
                reduce_condition=f"上涨至 ${target1} 附近后，减仓约三分之一。",
                exit_condition=f"如跌回 ${stop_loss_price} 下方或趋势恶化，清仓。",
                reason=f"价格 ${price} 已达第一目标 ${target1}。减仓三分之一锁定部分利润。",
                main_risk="趋势可能延续但短期回调风险增加。",
                data_updated_at=now_utc, data_integrity="完整",
                market_data_note=market_label,
                stop_loss_formula=stop_loss_formula, target_price_formula=target_formula,
                sizing_formula=f"建议减仓约 {int(float(position.shares) * 0.33)} 股。",
                position_pct=position.position_pct,
            )

        # --- P6: 加仓候选（先于持有）---
        can_add, add_reason = self._check_add_conditions(
            price, indicators, total_equity, cash, total_position_pct, position, stop_loss_price, target2,
        )
        add_suggested: int | None = None
        sizing_formula = ""
        risk_detail = ""

        if can_add:
            add_suggested, sizing_formula = _calculate_suggested_shares(
                price, stop_loss_price, total_equity,
                position.market_value, position.position_pct,
                cash, total_position_pct, self.risk_limits,
            )
            if add_suggested is None:
                return HoldingsDecision(
                    symbol=symbol, action="持有", need_action_today=False,
                    need_action_today_reason=f"满足加仓技术条件但 {sizing_formula or '资金不足'}。",
                    shares=position.shares, avg_cost=position.avg_cost,
                    current_price=price, market_value=position.market_value,
                    unrealized_pnl=position.unrealized_pnl, unrealized_pnl_pct=position.unrealized_pnl_pct,
                    suggested_shares=None, suggested_pct=None,
                    stop_loss_price=stop_loss_price, emergency_stop_price=emergency_stop,
                    target1_price=target1, target2_price=target2,
                    hold_condition=self._hold_condition(stop_loss_price, target1, indicators),
                    add_condition=f"满足加仓技术条件但 {sizing_formula or '资金不足'}。",
                    reduce_condition=f"上涨至 ${target1 or 'N/A'} 附近后可减仓约三分之一。",
                    exit_condition=self._exit_condition(stop_loss_price, emergency_stop),
                    reason="加仓条件满足但资金/仓位不支持。" + (" " + add_reason),
                    main_risk=self._default_risk(indicators),
                    data_updated_at=now_utc, data_integrity="完整",
                    market_data_note=market_label,
                    stop_loss_formula=stop_loss_formula, target_price_formula=target_formula,
                    sizing_formula=sizing_formula or "N/A",
                    position_pct=position.position_pct,
                    risk_constraints_detail=risk_detail,
                )
            return HoldingsDecision(
                symbol=symbol, action="加仓候选", need_action_today=False,
                need_action_today_reason=f"加仓候选（建议{add_suggested}股），触发条件：{add_reason}",
                shares=position.shares, avg_cost=position.avg_cost,
                current_price=price, market_value=position.market_value,
                unrealized_pnl=position.unrealized_pnl, unrealized_pnl_pct=position.unrealized_pnl_pct,
                suggested_shares=add_suggested,
                suggested_pct=D(str(add_suggested)) / position.shares if position.shares > ZERO else None,
                stop_loss_price=stop_loss_price, emergency_stop_price=emergency_stop,
                target1_price=target1, target2_price=target2,
                hold_condition=self._hold_condition(stop_loss_price, target1, indicators),
                add_condition=f"加仓触发: {add_reason}。建议加仓 {add_suggested} 股。",
                reduce_condition=f"上涨至 ${target1 or 'N/A'} 附近后可减仓约三分之一。",
                exit_condition=self._exit_condition(stop_loss_price, emergency_stop),
                reason="全部加仓条件满足。" + f" {add_reason}",
                main_risk=self._default_risk(indicators),
                data_updated_at=now_utc, data_integrity="完整",
                market_data_note=market_label,
                stop_loss_formula=stop_loss_formula, target_price_formula=target_formula,
                sizing_formula=sizing_formula,
                position_pct=position.position_pct,
                risk_constraints_detail=risk_detail,
            )

        # --- P7: 持有 ---
        return HoldingsDecision(
            symbol=symbol, action="持有", need_action_today=False,
            need_action_today_reason="",
            shares=position.shares, avg_cost=position.avg_cost,
            current_price=price, market_value=position.market_value,
            unrealized_pnl=position.unrealized_pnl, unrealized_pnl_pct=position.unrealized_pnl_pct,
            suggested_shares=None, suggested_pct=None,
            stop_loss_price=stop_loss_price, emergency_stop_price=emergency_stop,
            target1_price=target1, target2_price=target2,
            hold_condition=self._hold_condition(stop_loss_price, target1, indicators),
            add_condition=add_reason or "当前条件不满足加仓要求。",
            reduce_condition=f"上涨至 ${target1 or 'N/A'} 附近后可减仓约三分之一。",
            exit_condition=self._exit_condition(stop_loss_price, emergency_stop),
            reason=f"保护性止损 ${stop_loss_price} ({stop_loss_formula})",
            main_risk=self._default_risk(indicators),
            data_updated_at=now_utc, data_integrity="完整",
            market_data_note=market_label,
            stop_loss_formula=stop_loss_formula, target_price_formula=target_formula,
            sizing_formula="N/A",
            position_pct=position.position_pct,
        )

    def _hold_condition(self, sl, t1, ind) -> str:
        c = f"价格保持在保护性止损 ${sl} 上方，且未触发第一目标 ${t1 or 'N/A'}。"
        if ind.ma20 is not None:
            c += f" MA20={ind.ma20:.2f},偏离{ind.price_vs_ma20_pct or '?'}%。"
        return c

    def _exit_condition(self, sl, es) -> str:
        c = f"收盘有效跌破保护性止损 ${sl}，或原始交易逻辑失效。"
        if es is not None:
            c += f" 成本紧急参考线 ${es}（成本-{self.risk_limits.emergency_stop_loss_pct}%）非技术止损，仅供仓位监控。"
        return c

    def _default_risk(self, indicators) -> str:
        if indicators.ma20 is not None and indicators.ma50 is not None:
            if indicators.ma20 < indicators.ma50:
                return "MA20 低于 MA50，中期趋势偏弱。"
        return "市场正常波动风险。"

    def _check_add_conditions(
        self, price, indicators, total_equity, cash, total_position_pct, position, stop_loss, target2,
    ) -> tuple[bool, str]:
        limits = self.risk_limits
        tech = self.tech_params
        checks: list[tuple[bool, str]] = []

        # 1. 价格高于 MA20
        if indicators.ma20 is None:
            checks.append((False, "缺少 MA20 数据。"))
        else:
            above = price > indicators.ma20
            checks.append((above, f"价格{'高于' if above else '低于'} MA20({indicators.ma20:.2f})。"))

        # 2. MA20 >= MA50
        if indicators.ma20 is not None and indicators.ma50 is not None:
            checks.append((indicators.ma20 >= indicators.ma50, f"MA20≥MA50={indicators.ma20 >= indicators.ma50}。"))
        elif indicators.ma20 is not None:
            checks.append((False, "缺少 MA50 数据。"))
        else:
            checks.append((False, "缺少趋势判断数据。"))

        # 3. 价格没有明显偏离 MA20
        if indicators.price_vs_ma20_pct is not None:
            within = abs(indicators.price_vs_ma20_pct) <= tech.add_zone_ma20_offset_pct
            checks.append((within, f"价格偏离 MA20 {indicators.price_vs_ma20_pct:.1f}%（±{tech.add_zone_ma20_offset_pct}%）。"))
        else:
            checks.append((False, "无法计算价格偏离。"))

        # 4. 没有跌破止损
        checks.append((price > stop_loss, f"价格{'高于' if price > stop_loss else '低于'}止损 ${stop_loss}。"))

        # 5. 仓位未超上限
        checks.append((position.position_pct < limits.max_single_pct, f"仓位{position.position_pct:.1f}%<{limits.max_single_pct}%。"))

        # 6. 现金 >= 30%（仅用实际现金）
        min_cash = total_equity * limits.min_cash_pct / ONE_HUNDRED
        checks.append((cash >= min_cash, f"现金{cash:.2f}≥最低保留{min_cash:.2f}。"))

        # 7. 总持仓 <= 70%
        checks.append((total_position_pct <= limits.max_total_pct, f"总持仓{total_position_pct:.1f}%≤{limits.max_total_pct}%。"))

        # 8. 风险收益比 >= 2
        risk_per_share = price - stop_loss
        if risk_per_share > ZERO:
            potential = risk_per_share * self.profit_rule.r_multiple_target2
            rr = potential / risk_per_share
            checks.append((rr >= limits.reward_risk_min_ratio, f"风险收益比(T2)={rr:.1f}≥{limits.reward_risk_min_ratio}。"))
        else:
            checks.append((False, "风险 ≤ 0。"))

        # 9. 上方空间充足（T2 足够）
        if target2 is not None and risk_per_share > ZERO:
            margin = (target2 - price) / price * ONE_HUNDRED
            checks.append((margin >= D("2"), f"上方空间{margin:.1f}%≥2%。"))
        else:
            checks.append((False, f"上方空间不足: 缺少T2或R≤0。"))

        all_pass = all(r for r, _ in checks)
        if all_pass:
            return True, "全部条件满足|" + "|".join(d for _, d in checks)
        return False, "加仓条件不满足: " + " | ".join(d for r, d in checks if not r)


# ---------------------------------------------------------------------------
# 便捷入口
# ---------------------------------------------------------------------------


def _forbidden_formal_source(source: str, is_mock: bool = False) -> bool:
    lowered = str(source or "").lower()
    return is_mock or any(token in lowered for token in ("mock", "fixture", "demo", "synthetic"))


def _history_dates(history: Any | None) -> tuple[str | None, str | None]:
    timestamps = getattr(history, "timestamps", None) or []
    if not timestamps:
        return None, None
    return (
        datetime.fromtimestamp(timestamps[0], tz=timezone.utc).strftime("%Y-%m-%d"),
        datetime.fromtimestamp(timestamps[-1], tz=timezone.utc).strftime("%Y-%m-%d"),
    )


def _data_insufficient_decision(
    position: PositionInfo,
    *,
    current_price: Decimal | None,
    reason: str,
    price_source: str,
    price_timestamp: str | None,
    market_data_note: str,
) -> dict[str, Any]:
    disclaimer = "人工价格仅用于账户估值，不构成完整交易建议" if price_source == "manual_broker_input" else ""
    return {
        "symbol": position.symbol,
        "action": "数据不足",
        "today_action": "禁止加仓",
        "need_action_today": False,
        "need_action_today_reason": reason,
        "shares": str(position.shares),
        "avg_cost": str(position.avg_cost),
        "current_price": str(current_price) if current_price is not None else None,
        "market_value": str(position.market_value) if current_price is not None else None,
        "unrealized_pnl": str(position.unrealized_pnl) if current_price is not None else None,
        "unrealized_pnl_pct": str(position.unrealized_pnl_pct) if current_price is not None else None,
        "position_pct": str(position.position_pct) if current_price is not None else None,
        "suggested_shares": None,
        "suggested_pct": None,
        "stop_loss_price": None,
        "emergency_stop_price": None,
        "target1_price": None,
        "target2_price": None,
        "hold_condition": "等待真实行情与完整历史数据恢复。",
        "add_condition": "数据不足，禁止加仓。",
        "reduce_condition": "不可用",
        "exit_condition": "不可用",
        "reason": reason,
        "main_risk": "缺少可验证的正式行情链，禁止生成技术交易建议。",
        "data_updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "data_integrity": "数据不足",
        "market_data_note": " | ".join(item for item in (market_data_note, disclaimer) if item),
        "stop_loss_formula": "N/A",
        "target_price_formula": "N/A",
        "sizing_formula": "N/A",
        "risk_constraints_detail": reason,
        "price_source": price_source,
        "price_timestamp": price_timestamp,
        "price_status": "manual_valuation_only" if price_source == "manual_broker_input" else "unavailable",
        "manual_price_disclaimer": disclaimer,
        "blocking_rules": ["FORMAL_PRICE_UNAVAILABLE", "NO_ADD_WITH_INSUFFICIENT_DATA"],
    }


def generate_holdings_decisions(
    portfolio_path: str = "",
    *,
    manual_prices: Mapping[str, Decimal | str | float] | None = None,
    price_provider: Any | None = None,
    history_fetcher: Callable[[str], tuple[Any | None, str | None]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Generate read-only decisions from the formal portfolio and one real market chain.

    Manual prices are valuation-only. They never enter indicator, stop, target or sizing
    calculations and can never make a quote formally decision eligible.
    """
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from northstar.data.portfolio_snapshot import PortfolioRepository
    from northstar.data.market_snapshot import build_market_snapshot
    from price_provider_v2 import YFinanceProviderV2

    repo = PortfolioRepository(portfolio_path or project_root / "portfolio_migrated_candidate.json")
    portfolio_state = repo.load()
    provider = price_provider or YFinanceProviderV2()
    requested = list(portfolio_state.position_symbols)
    market_snapshot = build_market_snapshot(requested, provider)

    normalized_manual: dict[str, Decimal] = {}
    for raw_symbol, raw_price in (manual_prices or {}).items():
        try:
            value = raw_price if isinstance(raw_price, Decimal) else D(str(raw_price))
        except Exception:
            continue
        if value.is_finite() and value > ZERO:
            normalized_manual[str(raw_symbol).strip().upper()] = value

    # Manual and stale prices may value an account, but only eligible real quotes may drive advice.
    valuation_prices: dict[str, tuple[Decimal, str, str | None]] = {}
    for position in portfolio_state.positions:
        quote = market_snapshot.quotes.get(position.symbol)
        if position.symbol in normalized_manual:
            valuation_prices[position.symbol] = (
                normalized_manual[position.symbol],
                "manual_broker_input",
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            )
        elif (
            quote is not None and quote.price is not None and quote.price > 0
            and not _forbidden_formal_source(quote.source, quote.is_mock)
        ):
            valuation_prices[position.symbol] = (D(str(quote.price)), quote.source, quote.as_of)

    cash = portfolio_state.cash
    valuation_complete = len(valuation_prices) == len(portfolio_state.positions)
    partial_market_value = sum(
        (position.quantity * valuation_prices[position.symbol][0]
         for position in portfolio_state.positions if position.symbol in valuation_prices),
        start=ZERO,
    )
    total_equity = cash + partial_market_value if valuation_complete else ZERO
    total_pos_pct = (partial_market_value / total_equity * ONE_HUNDRED) if total_equity > ZERO else ZERO

    position_map: dict[str, PositionInfo] = {}
    for position in portfolio_state.positions:
        price_info = valuation_prices.get(position.symbol)
        price = price_info[0] if price_info else None
        market_value = position.quantity * price if price is not None else ZERO
        unrealized = market_value - position.cost_basis if price is not None else ZERO
        pnl_pct = unrealized / position.cost_basis * ONE_HUNDRED if price is not None and position.cost_basis > ZERO else ZERO
        pos_pct = market_value / total_equity * ONE_HUNDRED if total_equity > ZERO else ZERO
        position_map[position.symbol] = PositionInfo(
            symbol=position.symbol,
            shares=position.quantity,
            avg_cost=position.average_cost,
            cost_basis=position.cost_basis,
            market_value=market_value,
            unrealized_pnl=unrealized,
            unrealized_pnl_pct=pnl_pct,
            position_pct=pos_pct,
        )

    engine = HoldingsDecisionEngine()
    now = datetime.now(timezone.utc)
    is_market = _is_us_market_hours()
    fetch_history = history_fetcher or _fetch_history
    decisions: list[dict[str, Any]] = []

    for symbol in requested:
        position = position_map[symbol]
        quote = market_snapshot.quotes.get(symbol)
        manual_price = normalized_manual.get(symbol)
        formal_quote = (
            quote is not None and quote.decision_eligible
            and not _forbidden_formal_source(quote.source, quote.is_mock)
        )

        history, history_error = fetch_history(symbol)
        identity = _fetch_identity(symbol, history)
        master = get_security_master(symbol)
        filter_date = (
            master.valid_history_start if master is not None and master.valid_history_start
            else identity.data_start_date if identity.is_identity_verified and master is None
            else None
        )
        if filter_date:
            history = _filter_valid_history(history, filter_date)

        identity_issues: list[str] = []
        if master is not None and identity.is_identity_verified:
            remote_names = [name for name in (identity.long_name, identity.short_name) if name]
            if remote_names and not any(master.issuer_name.lower() in str(name).lower() for name in remote_names):
                identity_issues.append("远程证券名称与本地主数据不匹配")

        historical_close = next(
            (D(str(value)) for value in reversed(getattr(history, "close", None) or []) if value is not None and D(str(value)) > ZERO),
            None,
        )
        indicator_reference = historical_close or (D(str(quote.price)) if formal_quote else D("1"))
        indicators, _ = _calculate_indicators(
            symbol, indicator_reference, history, get_technical_params(), identity=identity,
        )
        if identity_issues:
            indicators = TechnicalIndicators(
                symbol=symbol,
                data_count=indicators.data_count,
                calculation_notes=tuple(identity_issues + list(indicators.calculation_notes)),
            )

        first_bar, last_bar = _history_dates(history)
        valuation_source = valuation_prices.get(symbol, (None, "unavailable", None))[1]
        valuation_timestamp = valuation_prices.get(symbol, (None, "unavailable", None))[2]

        if manual_price is not None:
            d = _data_insufficient_decision(
                position,
                current_price=manual_price,
                reason=("人工价格仅用于账户估值，不构成完整交易建议。" + (f" 历史行情失败：{history_error}" if history_error else "")),
                price_source="manual_broker_input",
                price_timestamp=valuation_timestamp,
                market_data_note="人工价格（非实时接口行情）",
            )
        elif not formal_quote:
            provider_error = quote.error_message if quote is not None else "行情结果缺失"
            d = _data_insufficient_decision(
                position,
                current_price=None,
                reason=f"正式行情不可用：{provider_error}",
                price_source=quote.source if quote is not None else "unavailable",
                price_timestamp=quote.as_of if quote is not None else None,
                market_data_note="正式模式未回退 mock/fixture/demo/synthetic 或成本价",
            )
        else:
            price = D(str(quote.price))
            price_as_of = str(quote.as_of or "")
            stale, freshness_note = _check_freshness(price_as_of, get_freshness_params())
            price_level = PriceLevel(
                price=price,
                previous_close=D(str(quote.previous_close)) if quote.previous_close is not None else None,
                price_as_of=price_as_of,
                source=quote.source,
                is_trading_hours=is_market,
                is_stale=stale,
                is_realtime=_market_data_label(price_as_of)[1],
                market_data_note=freshness_note,
            )
            d = engine.decide(
                symbol, position, price_level, indicators,
                total_equity, cash if valuation_complete else ZERO, total_pos_pct,
            ).to_dict()
            d.update(
                today_action=d["action"],
                price_source=quote.source,
                price_timestamp=price_as_of,
                price_status="realtime" if price_level.is_realtime else "latest_close_non_realtime",
                blocking_rules=[] if d["action"] != "数据不足" else ["INSUFFICIENT_HISTORY_OR_FRESHNESS"],
            )
            if not valuation_complete and d["action"] == "加仓候选":
                d["action"] = "数据不足"
                d["today_action"] = "禁止加仓"
                d["suggested_shares"] = None
                d["suggested_pct"] = None
                d["blocking_rules"].append("PORTFOLIO_VALUATION_INCOMPLETE")

        crossings: list[str] = []
        if manual_price is not None:
            for label, level in (
                ("MA20", indicators.ma20), ("MA50", indicators.ma50),
                ("10日高点", indicators.swing_high_10), ("20日高点", indicators.swing_high_20),
            ):
                if level is not None:
                    crossings.append(f"人工价{'高于或等于' if manual_price >= level else '低于'}{label}")

        d["security_name"] = (master.issuer_name if master else None) or identity.long_name or identity.short_name or symbol
        d["provider"] = quote.source if quote is not None else "unavailable"
        d["provider_error"] = (quote.error_message if quote is not None else None) or history_error
        d["first_valid_bar_date"] = first_bar
        d["last_valid_bar_date"] = last_bar
        d["valid_bar_count"] = indicators.data_count
        d["valid_history_start"] = filter_date
        d["is_mock"] = False
        d["is_synthetic"] = False
        d["stop_loss"] = d.get("stop_loss_price")
        d["target_1"] = d.get("target1_price")
        d["target_2"] = d.get("target2_price")
        d["manual_price_crossings"] = crossings
        d["indicators_summary"] = {
            "ma5": str(indicators.ma5) if indicators.ma5 is not None else None,
            "ma10": str(indicators.ma10) if indicators.ma10 is not None else None,
            "ma20": str(indicators.ma20) if indicators.ma20 is not None else None,
            "ma50": str(indicators.ma50) if indicators.ma50 is not None else None,
            "atr14": str(indicators.atr14) if indicators.atr14 is not None else None,
            "swing_high_10": str(indicators.swing_high_10) if indicators.swing_high_10 is not None else None,
            "swing_high_20": str(indicators.swing_high_20) if indicators.swing_high_20 is not None else None,
        }
        d["data_quality"] = {
            "formal_quote_eligible": bool(formal_quote),
            "history_available": history is not None,
            "identity_verified": identity.is_identity_verified and not identity_issues,
            "valuation_source": valuation_source,
            "manual_price_used_for_indicators": False,
            "history_error": history_error,
        }
        decisions.append(d)

    summary = {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "portfolio_source": Path(repo.path).name,
        "market_snapshot_id": market_snapshot.snapshot_id,
        "market_status": market_snapshot.market_status,
        "total_equity": str(total_equity) if valuation_complete else None,
        "cash": str(cash),
        "total_position_pct": str(total_pos_pct) if valuation_complete else None,
        "valuation_complete": valuation_complete,
        "is_market_hours": is_market,
        "is_mock": False,
        "is_synthetic": False,
        "position_count": len(decisions),
        "actions": {d["symbol"]: d["action"] for d in decisions},
    }
    return decisions, summary
