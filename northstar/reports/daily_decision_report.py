#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""25支观察池每日决策报告生成模块。

功能说明
--------
1. 读取 watchlist.json 获得 25 支观察池股票
2. 通过 YFinancePriceProvider 获取实时行情
3. 计算趋势判断、风险等级、操作建议
4. 按板块分组展示
5. 筛选 Top 5 机会 + Top 5 风险
6. 输出 markdown 和 json 两种格式报告
7. 读取 portfolio.json 识别用户持仓，做持仓特别提示

设计原则
--------
- 不接入真实交易，不自动下单
- 所有面向用户的文字均为中文（除股票代码外）
- 数据源降级处理，不崩溃
- 纯本地运行
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from northstar.data.market_snapshot import (
    MarketSnapshot,
    QuoteSnapshot,
    build_market_snapshot,
)
from northstar.data.portfolio_snapshot import (
    FORMAL_PORTFOLIO_PATH,
    PortfolioSnapshot,
    PortfolioState,
    load_portfolio_state,
    portfolio_state_from_mapping,
    requested_market_symbols,
    value_portfolio,
)

# ── 目录定位 ──────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── 常量 ───────────────────────────────────────────────────────
WATCHLIST_PATH = PROJECT_ROOT / "watchlist.json"
PORTFOLIO_PATH = FORMAL_PORTFOLIO_PATH
REPORT_DIR = PROJECT_ROOT / "reports" / "daily_decision"
LOG_DIR = PROJECT_ROOT / "logs"

# 25支股票 → 板块分组
SECTOR_GROUPS: dict[str, list[str]] = {
    "AI算力芯片与半导体": ["NVDA", "AMD", "AVGO", "TSM", "ASML", "ARM", "MRVL", "MU", "AMAT", "LRCX"],
    "AI云与大模型平台": ["MSFT", "GOOGL", "META", "ORCL"],
    "AI软件、数据、网络安全与企业应用": ["PLTR", "SNOW", "MDB", "CRWD", "DDOG", "NET", "NOW"],
    "AI数据中心、服务器、电力与基础设施": ["VRT", "ETN", "SMCI", "DELL"],
}
AI_WATCHLIST = [symbol for group in SECTOR_GROUPS.values() for symbol in group]

# 中文名称映射（人工维护，开源数据无需 API）
COMPANY_NAMES: dict[str, str] = {
    "NVDA": "英伟达",    "AMD": "超威半导体",  "AVGO": "博通",
    "TSM": "台积电",     "ASML": "阿斯麦",
    "MSFT": "微软",      "GOOGL": "谷歌",       "META": "Meta",
    "MRVL": "迈威尔科技", "AMAT": "应用材料", "LRCX": "泛林集团",
    "PLTR": "Palantir",  "CRWD": "CrowdStrike", "DDOG": "Datadog",
    "SNOW": "Snowflake", "MDB": "MongoDB",
    "NET": "Cloudflare", "NOW": "ServiceNow", "ARM": "ARM 控股", "MU": "美光科技",
    "SMCI": "超微电脑",  "DELL": "戴尔",
    "VRT": "维谛技术", "ETN": "伊顿", "SOFI": "SoFi", "SPCX": "SPCX", "ORCL": "甲骨文",
}

# ── 行情数据结构 ──────────────────────────────────────────────
@dataclass
class StockPriceInfo:
    """单只股票的行情+决策信息。"""
    symbol: str
    company_cn: str = ""
    current_price: float | None = None
    change_pct_today: float = 0.0
    change_pct_5d: float | None = None
    change_pct_20d: float | None = None
    trend: str = "中性"        # 强势 / 中性 / 弱势
    risk_level: str = "中"     # 低 / 中 / 高
    suggestion: str = "暂不买入"   # 操作建议
    reason: str = ""           # 一句话理由
    score: float = 0.0         # 综合评分（用于排序）
    data_source: str = "unavailable"
    as_of: str | None = None
    status: str = "missing"
    is_stale: bool = False
    is_mock: bool = False
    error_code: str | None = None
    error_message: str | None = None

    @property
    def decision_eligible(self) -> bool:
        return (
            self.status == "valid"
            and self.current_price is not None
            and self.current_price > 0
            and bool(self.data_source)
            and bool(self.as_of)
            and not self.is_stale
            and not self.is_mock
        )


# ── 日志 ───────────────────────────────────────────────────────
logger = logging.getLogger("daily_decision_report")


def _setup_logger() -> None:
    """配置日志，输出到 logs/daily_decision_report.log。"""
    if logger.handlers:
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "daily_decision_report.log"
    handler = logging.FileHandler(str(log_path), encoding="utf-8", mode="a")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    # 同时输出到 stderr
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(console)


# ── 读取观察池 ────────────────────────────────────────────────
def load_watchlist() -> list[str]:
    """从 watchlist.json 读取观察池股票列表。"""
    if not WATCHLIST_PATH.exists():
        logger.warning("watchlist.json 不存在，使用默认 25 支股票")
        return list(AI_WATCHLIST)
    try:
        with open(WATCHLIST_PATH, encoding="utf-8") as f:
            data = json.load(f)
        symbols = data.get("symbols", [])
        if not isinstance(symbols, list) or len(symbols) == 0:
            logger.warning("watchlist.json 中 symbols 为空或格式错误")
            return []
        return [s.strip().upper() for s in symbols if isinstance(s, str) and s.strip()]
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.error("读取 watchlist.json 失败: %s", exc)
        return []


def load_portfolio() -> dict[str, dict[str, Any]]:
    """Deprecated compatibility view backed by the canonical repository."""
    state = load_portfolio_state()
    return {
        position.symbol: {
            "shares": str(position.quantity),
            "avg_cost": str(position.average_cost),
            "currency": position.currency,
        }
        for position in state.positions
    }


# ── 获取行情 ──────────────────────────────────────────────────
def _stock_info_from_quote(quote: QuoteSnapshot) -> StockPriceInfo:
    """Convert one frozen quote into score input without performing I/O."""
    info = StockPriceInfo(
        symbol=quote.symbol,
        company_cn=COMPANY_NAMES.get(quote.symbol, quote.symbol),
        current_price=quote.price,
        change_pct_today=float(quote.change_pct_today or 0.0),
        change_pct_5d=quote.change_pct_5d,
        change_pct_20d=quote.change_pct_20d,
        data_source=quote.source,
        as_of=quote.as_of,
        status=quote.status,
        is_stale=quote.is_stale,
        is_mock=quote.is_mock,
        error_code=quote.error_code,
        error_message=quote.error_message,
    )
    if info.decision_eligible:
        info.trend = _judge_trend(info)
        info.risk_level = _judge_risk(info)
        info.suggestion = _judge_suggestion(info)
        info.reason = _generate_reason(info)
        info.score = _compute_score(info)
    else:
        info.trend = "数据不足"
        info.risk_level = "未知"
        info.suggestion = "无建议"
        info.reason = info.error_message or f"行情状态为 {info.status}，禁止参与评分"
        info.score = 0.0
    return info


def fetch_prices(
    symbols: list[str],
    *,
    provider: Any | None = None,
) -> dict[str, StockPriceInfo]:
    """Compatibility wrapper: build exactly one snapshot and expose its rows."""
    from northstar.data.market_data_provider import MarketDataProvider

    snapshot = build_market_snapshot(symbols, provider or MarketDataProvider())
    info_map = {symbol: _stock_info_from_quote(snapshot.quote(symbol)) for symbol in snapshot.requested_symbols}
    info_map["__snapshot__"] = snapshot  # type: ignore[assignment]
    return info_map


def _judge_trend(info: StockPriceInfo) -> str:
    """根据涨跌幅判断趋势状态。"""
    # 用近 20 日判断中期趋势
    c20 = info.change_pct_20d
    if c20 is not None:
        if c20 > 8:
            return "强势"
        if c20 < -8:
            return "弱势"
        return "中性"
    # 降级到近 5 日
    c5 = info.change_pct_5d
    if c5 is not None:
        if c5 > 5:
            return "强势"
        if c5 < -5:
            return "弱势"
        return "中性"
    # 降级到今日涨跌幅
    if info.change_pct_today > 3:
        return "强势"
    if info.change_pct_today < -3:
        return "弱势"
    return "中性"


def _judge_risk(info: StockPriceInfo) -> str:
    """根据波动和趋势判断风险等级。"""
    # 弱势 + 大跌 → 高风险
    if info.trend == "弱势" and info.change_pct_20d is not None and info.change_pct_20d < -15:
        return "高"
    # 弱势逐步降 → 中风险
    if info.trend == "弱势":
        return "中"
    # 强势上涨 → 追高风险
    if info.trend == "强势" and info.change_pct_5d is not None and info.change_pct_5d > 10:
        return "高"
    # 中性 → 低风险
    if info.trend == "中性":
        return "低"
    return "中"


def _judge_suggestion(info: StockPriceInfo) -> str:
    """给出操作建议。"""
    if info.trend == "强势" and info.risk_level == "低":
        return "买入观察"
    if info.trend == "强势" and info.risk_level == "中":
        return "继续持有"
    if info.trend == "中性":
        return "继续持有"
    if info.trend == "弱势" and info.risk_level == "中":
        return "暂不买入"
    if info.trend == "弱势" and info.risk_level == "高":
        return "高风险回避"
    if info.trend == "弱势":
        return "减仓观察"
    return "暂不买入"


def _generate_reason(info: StockPriceInfo) -> str:
    """生成一句话理由，必须中文。"""
    trend_cn = info.trend
    risk_cn = info.risk_level
    symbol = info.symbol
    name = info.company_cn or symbol

    reasons: dict[str, str] = {
        "NVDA": f"AI 芯片龙头，{trend_cn}趋势，风险{risk_cn}，关注财报和 Blackwell 出货节奏",
        "AMD": f"GPU 追赶者，{trend_cn}趋势，风险{risk_cn}，关注 MI 系列市场份额变化",
        "AVGO": f"网络芯片+VMware 双轮驱动，{trend_cn}趋势，风险{risk_cn}",
        "TSM": f"全球芯片代工龙头，{trend_cn}趋势，风险{risk_cn}，关注产能利用率",
        "ASML": f"光刻机绝对垄断，{trend_cn}趋势，风险{risk_cn}，关注中国出口管制影响",
        "MSFT": f"云+AI 双引擎，{trend_cn}趋势，风险{risk_cn}，Azure 增速是核心指标",
        "GOOGL": f"搜索+云+AI 布局，{trend_cn}趋势，风险{risk_cn}，关注 Gemini 进展",
        "META": f"广告+元宇宙双线，{trend_cn}趋势，风险{risk_cn}，关注资本开支节奏",
        "AMZN": f"电商+AWS 双支柱，{trend_cn}趋势，风险{risk_cn}，关注 AWS 增速",
        "AAPL": f"消费电子之王，{trend_cn}趋势，风险{risk_cn}，关注 iPhone 换机周期",
        "PLTR": f"政府+企业 AI 数据分析，{trend_cn}趋势，风险{risk_cn}，关注 AIP 客户增长",
        "TSLA": f"电动车+机器人+储能，{trend_cn}趋势，风险{risk_cn}，高波动注意仓位",
        "SOFI": f"金融科技新贵，{trend_cn}趋势，风险{risk_cn}，关注用户增长和利润率",
        "IONQ": f"量子计算前沿，{trend_cn}趋势，风险{risk_cn}，商业化尚早，高波动",
        "RGTI": f"量子计算概念股，{trend_cn}趋势，风险{risk_cn}，投机性强注意风险",
        "ARM": f"芯片架构授权龙头，{trend_cn}趋势，风险{risk_cn}，关注 AI 端侧渗透",
        "MU": f"存储芯片龙头，{trend_cn}趋势，风险{risk_cn}，关注 HBM 和 DDR5 需求",
        "SMCI": f"AI 服务器黑马，{trend_cn}趋势，风险{risk_cn}，关注液冷方案进展",
        "DELL": f"传统 PC+AI 服务器转型，{trend_cn}趋势，风险{risk_cn}",
        "ORCL": f"企业级数据库+云，{trend_cn}趋势，风险{risk_cn}，关注 OCI 增速",
        "CRWD": f"网络安全龙头，{trend_cn}趋势，风险{risk_cn}，关注平台化进展",
        "PANW": f"网络安全领军，{trend_cn}趋势，风险{risk_cn}，关注平台整合",
        "SNOW": f"云数据仓库，{trend_cn}趋势，风险{risk_cn}，关注消费模式转变",
        "MDB": f"文档数据库标杆，{trend_cn}趋势，风险{risk_cn}，关注 Atlas 增速",
        "COIN": f"加密交易所龙头，{trend_cn}趋势，风险{risk_cn}，高度关联 BTC 走势",
    }

    if symbol in reasons:
        return reasons[symbol]

    # 通用理由
    return f"{name} 当前{trend_cn}趋势，风险等级{risk_cn}"


def _compute_score(info: StockPriceInfo) -> float:
    """兼容 Markdown 报告的做多可操作分（0-100）。"""
    score = 0.0
    # 趋势加分
    if info.trend == "强势":
        score += 30
    elif info.trend == "中性":
        score += 15
    # 风险减分
    if info.risk_level == "低":
        score += 10
    elif info.risk_level == "高":
        score -= 20
    # 今日涨跌贡献
    score += max(-15, min(15, info.change_pct_today))
    # 近 5 日涨跌贡献
    if info.change_pct_5d is not None:
        score += max(-20, min(20, info.change_pct_5d * 0.5))
    return round(max(0, min(100, score + 35)), 1)


# ── 报告生成 ──────────────────────────────────────────────────
def _snapshot_from_info_map(info_map: dict[str, StockPriceInfo]) -> MarketSnapshot:
    """Build a no-I/O snapshot from explicitly attributed rows (mainly tests)."""
    now = datetime.now(timezone.utc)
    quotes: dict[str, QuoteSnapshot] = {}
    symbols = [symbol for symbol in info_map if not symbol.startswith("__")]
    for symbol in symbols:
        info = info_map[symbol]
        status = "valid" if info.decision_eligible else info.status
        if status == "valid" and (info.current_price is None or info.current_price <= 0):
            status = "missing"
        quotes[symbol] = QuoteSnapshot(
            symbol=symbol,
            price=info.current_price if info.current_price and info.current_price > 0 else None,
            currency="USD",
            source=info.data_source,
            as_of=info.as_of,
            status=status,
            is_stale=info.is_stale,
            is_mock=info.is_mock,
            error_code=info.error_code,
            error_message=info.error_message,
            change_pct_today=info.change_pct_today,
            change_pct_5d=info.change_pct_5d,
            change_pct_20d=info.change_pct_20d,
        )
    valid = tuple(symbol for symbol, quote in quotes.items() if quote.decision_eligible)
    invalid = tuple(symbol for symbol in symbols if symbol not in set(valid))
    coverage = len(valid) / len(symbols) if symbols else 0.0
    return MarketSnapshot(
        snapshot_id=f"local_{now.strftime('%Y%m%dT%H%M%S%fZ')}",
        generated_at_utc=now.isoformat().replace("+00:00", "Z"),
        generated_at_local=now.astimezone().isoformat(),
        market_status="NORMAL" if coverage >= 0.9 else "DEGRADED" if valid else "UNAVAILABLE",
        requested_symbols=tuple(symbols),
        valid_symbols=valid,
        invalid_symbols=invalid,
        coverage_ratio=coverage,
        provider_summary={},
        quotes=quotes,
    )


def _stock_dict(info: StockPriceInfo) -> dict[str, Any]:
    return {
        "symbol": info.symbol,
        "company_cn": info.company_cn,
        "current_price": info.current_price,
        "change_pct_today": info.change_pct_today if info.decision_eligible else None,
        "change_pct_5d": info.change_pct_5d,
        "change_pct_20d": info.change_pct_20d,
        "trend": info.trend,
        "risk_level": info.risk_level,
        "suggestion": info.suggestion,
        "reason": info.reason,
        "score": info.score if info.decision_eligible else None,
        "source": info.data_source,
        "as_of": info.as_of,
        "status": info.status,
        "is_stale": info.is_stale,
        "is_mock": info.is_mock,
        "error_code": info.error_code,
        "error_message": info.error_message,
        "error": info.error_message,
    }


def build_report_data(
    info_map: dict[str, StockPriceInfo],
    portfolio: dict[str, dict[str, Any]] | None = None,
    *,
    snapshot: MarketSnapshot | None = None,
    requested_symbols: list[str] | tuple[str, ...] | None = None,
    portfolio_state: PortfolioState | None = None,
    portfolio_snapshot: PortfolioSnapshot | None = None,
) -> dict[str, Any]:
    """Build report data exclusively from one already-frozen snapshot."""
    embedded = info_map.get("__snapshot__")
    if snapshot is None and isinstance(embedded, MarketSnapshot):
        snapshot = embedded
    clean_map = {key: value for key, value in info_map.items() if not key.startswith("__")}
    snapshot = snapshot or _snapshot_from_info_map(clean_map)
    symbols = list(dict.fromkeys(requested_symbols or clean_map.keys()))
    now_local = datetime.fromisoformat(snapshot.generated_at_local.replace("Z", "+00:00"))
    date_str = now_local.strftime("%Y-%m-%d")
    time_str = now_local.strftime("%H:%M:%S")

    for symbol in symbols:
        if symbol not in clean_map:
            quote = snapshot.quotes.get(symbol)
            if quote is not None:
                clean_map[symbol] = _stock_info_from_quote(quote)
            else:
                clean_map[symbol] = StockPriceInfo(
                    symbol=symbol,
                    company_cn=COMPANY_NAMES.get(symbol, symbol),
                    status="missing",
                    error_code="SNAPSHOT_SYMBOL_MISSING",
                    error_message="symbol not present in supplied snapshot",
                    reason="快照缺少该股票，禁止参与评分",
                    suggestion="无建议",
                    trend="数据不足",
                    risk_level="未知",
                )

    stock_details = {symbol: clean_map[symbol] for symbol in symbols}
    eligible = [info for info in stock_details.values() if info.decision_eligible]
    coverage = len(eligible) / len(symbols) if symbols else 0.0
    if coverage < 0.9:
        recommendation_status = "DATA_INSUFFICIENT"
    elif len(eligible) < 5:
        recommendation_status = "NO_RECOMMENDATION"
    else:
        recommendation_status = "OK"

    sector_stocks: dict[str, list[StockPriceInfo]] = {}
    for sector, sector_symbols in SECTOR_GROUPS.items():
        matched = [stock_details[symbol] for symbol in sector_symbols if symbol in stock_details]
        if matched:
            sector_stocks[sector] = matched
    grouped_symbols = {symbol for values in SECTOR_GROUPS.values() for symbol in values}
    others = [info for symbol, info in stock_details.items() if symbol not in grouped_symbols]
    if others:
        sector_stocks["其他"] = others

    top5_opportunity: list[StockPriceInfo] = []
    top5_risk: list[StockPriceInfo] = []
    if recommendation_status == "OK":
        opportunity = [
            info for info in eligible
            if info.suggestion not in ("高风险回避", "减仓观察") and info.score > 0
        ]
        opportunity.sort(key=lambda item: -item.score)
        top5_opportunity = opportunity[:5] if len(opportunity) >= 5 else []
        risk = [info for info in eligible if info.risk_level == "高" or info.trend == "弱势"]
        risk.sort(key=lambda item: item.score)
        top5_risk = risk[:5]

    if portfolio_snapshot is None:
        if portfolio_state is None:
            portfolio_state = portfolio_state_from_mapping(
                portfolio or {},
                cash=None,
                updated_at=snapshot.generated_at_utc,
            )
        portfolio_snapshot = value_portfolio(portfolio_state, snapshot)
    if portfolio_snapshot.market_snapshot_id != snapshot.snapshot_id:
        raise ValueError("PortfolioSnapshot and MarketSnapshot IDs do not match")

    holding_symbols = [position.symbol for position in portfolio_snapshot.positions]
    missing_holdings = list(portfolio_snapshot.missing_symbols)
    valuation_status = portfolio_snapshot.valuation_status
    valuation_positions = [position.to_dict() for position in portfolio_snapshot.positions]

    portfolio_notes: list[dict[str, Any]] = []
    valuations_by_symbol = {position.symbol: position for position in portfolio_snapshot.positions}
    for symbol in holding_symbols:
        info = clean_map.get(symbol)
        valuation = valuations_by_symbol[symbol]
        if info is None or not info.decision_eligible or valuation.valuation_status != "complete":
            continue
        portfolio_notes.append({
            "symbol": symbol,
            "company_cn": COMPANY_NAMES.get(symbol, symbol),
            "持股数量": str(valuation.quantity),
            "平均成本": str(valuation.average_cost),
            "当前价格": str(valuation.current_price),
            "今日涨跌幅": info.change_pct_today,
            "趋势": info.trend,
            "风险": info.risk_level,
            "建议": info.suggestion,
            "理由": info.reason,
            "source": info.data_source,
            "as_of": info.as_of,
            "snapshot_id": snapshot.snapshot_id,
        })

    invalid_rows = [
        {
            "symbol": symbol,
            "status": stock_details[symbol].status,
            "source": stock_details[symbol].data_source,
            "as_of": stock_details[symbol].as_of,
            "is_stale": stock_details[symbol].is_stale,
            "is_mock": stock_details[symbol].is_mock,
            "error_code": stock_details[symbol].error_code,
            "error_message": stock_details[symbol].error_message,
        }
        for symbol in symbols if not stock_details[symbol].decision_eligible
    ]
    issue_counts = {
        status: sum(1 for row in invalid_rows if row["status"] == status)
        for status in ("stale", "missing", "error", "mock")
    }
    if recommendation_status == "OK":
        overall_conclusion = _make_overall_conclusion({info.symbol: info for info in eligible})
        data_warning = ""
    else:
        overall_conclusion = "数据不足，今日不生成正式投资建议"
        data_warning = "行情覆盖率或有效候选数量未达到门槛，Top 5 已关闭。"

    overview = {
        "当前日期": date_str,
        "观察池股票数量": len(symbols),
        "有效价格数量": f"{len(eligible)}/{len(symbols)}",
        "有效覆盖率": f"{coverage:.1%}",
        "行情源状态": snapshot.market_status,
        "快照编号": snapshot.snapshot_id,
        "行情生成时间": snapshot.generated_at_local,
        "推荐状态": recommendation_status,
        "持仓估值状态": valuation_status,
        "持仓行情覆盖率": f"{portfolio_snapshot.coverage_ratio:.1%}",
        "持仓快照编号": portfolio_snapshot.portfolio_snapshot_id,
    }
    return {
        "report_date": date_str,
        "report_time": time_str,
        "generated_at": snapshot.generated_at_utc,
        "snapshot_id": snapshot.snapshot_id,
        "portfolio_snapshot_id": portfolio_snapshot.portfolio_snapshot_id,
        "market_snapshot_id": portfolio_snapshot.market_snapshot_id,
        "market_status": snapshot.market_status,
        "coverage_ratio": round(coverage, 6),
        "recommendation_status": recommendation_status,
        "provider_summary": dict(snapshot.provider_summary),
        "market_snapshot": snapshot.to_dict(),
        "watchlist_symbols": symbols,
        "portfolio_symbols": holding_symbols,
        "requested_symbols": list(snapshot.requested_symbols),
        "data_quality": {
            "status": recommendation_status,
            "coverage_ratio": round(coverage, 6),
            "valid_count": len(eligible),
            "requested_count": len(symbols),
            "invalid_count": len(invalid_rows),
            "issue_counts": issue_counts,
            "invalid_symbols": invalid_rows,
            "warning": data_warning,
        },
        "overview": overview,
        "sector_stocks": {sector: [_stock_dict(info) for info in values] for sector, values in sector_stocks.items()},
        "stock_details": {symbol: _stock_dict(info) for symbol, info in stock_details.items()},
        "top5_opportunity": [
            {**_stock_dict(info), "why": _why_opportunity(info), "snapshot_id": snapshot.snapshot_id}
            for info in top5_opportunity
        ],
        "top5_risk": [
            {**_stock_dict(info), "why": _why_risk(info), "snapshot_id": snapshot.snapshot_id}
            for info in top5_risk
        ],
        "portfolio_notes": portfolio_notes,
        "portfolio_snapshot": portfolio_snapshot.to_dict(),
        "portfolio_valuation": {
            **portfolio_snapshot.to_dict(),
            "snapshot_id": snapshot.snapshot_id,
            "holding_coverage_ratio": portfolio_snapshot.coverage_ratio,
        },
        "valuation_status": valuation_status,
        "portfolio_coverage_ratio": portfolio_snapshot.coverage_ratio,
        "missing_symbols": missing_holdings,
        "cash": str(portfolio_snapshot.cash) if portfolio_snapshot.cash is not None else None,
        "base_currency": portfolio_snapshot.base_currency,
        "position_valuations": valuation_positions,
        "total_market_value": str(portfolio_snapshot.total_market_value) if portfolio_snapshot.total_market_value is not None else None,
        "total_cost_basis": str(portfolio_snapshot.total_cost_basis) if portfolio_snapshot.total_cost_basis is not None else None,
        "total_unrealized_pnl": str(portfolio_snapshot.total_unrealized_pnl) if portfolio_snapshot.total_unrealized_pnl is not None else None,
        "total_asset_value": str(portfolio_snapshot.total_asset_value) if portfolio_snapshot.total_asset_value is not None else None,
        "overall_conclusion": overall_conclusion,
        "user_positions": holding_symbols,
    }


def _why_opportunity(info: StockPriceInfo) -> str:
    """解释为什么值得关注。"""
    if info.trend == "强势" and info.risk_level == "低":
        return f"处于强势上涨通道，风险可控，建议纳入买入观察名单"
    if info.change_pct_today > 2:
        return f"今日放量上涨 {info.change_pct_today:+.1f}%，短线动能强"
    if info.change_pct_5d is not None and info.change_pct_5d > 5:
        return f"近 5 日累计上涨 {info.change_pct_5d:+.1f}%，中期趋势向好"
    score_detail = f"做多可操作分 {info.score} 分"
    if info.risk_level == "低":
        return f"风险较低，{score_detail}，适合关注"
    return f"{score_detail}，趋势偏强，但需注意仓位控制"


def _why_risk(info: StockPriceInfo) -> str:
    """解释风险来源。"""
    parts = []
    if info.risk_level == "高":
        parts.append("风险等级高")
    if info.trend == "弱势":
        parts.append("处于弱势下跌通道")
    if info.change_pct_20d is not None and info.change_pct_20d < -10:
        parts.append(f"近 20 日跌幅达 {info.change_pct_20d:.1f}%")
    if info.change_pct_5d is not None and info.change_pct_5d < -5:
        parts.append(f"近 5 日下跌 {info.change_pct_5d:.1f}%")
    if info.change_pct_today < -3:
        parts.append(f"今日大跌 {info.change_pct_today:.1f}%")
    if not parts:
        parts.append("综合评分偏低，建议暂时回避")
    return "，".join(parts)


def _make_overall_conclusion(info_map: dict[str, StockPriceInfo]) -> str:
    """生成今日一句话结论。"""
    strong_count = sum(1 for v in info_map.values() if v.trend == "强势")
    weak_count = sum(1 for v in info_map.values() if v.trend == "弱势")
    high_risk_count = sum(1 for v in info_map.values() if v.risk_level == "高")
    total = len(info_map) or 1

    if strong_count / total > 0.4 and high_risk_count / total < 0.15:
        return "适合买入 — 观察池整体强势，风险可控，可适度建仓"
    if strong_count / total > 0.25 and weak_count / total < 0.2:
        return "适合观察 — 市场分化，强势股可关注，弱势股等待信号"
    if weak_count / total > 0.4 or high_risk_count / total > 0.3:
        return "适合减仓 — 弱势股比例较高，整体风险偏大，降低仓位为主"
    if weak_count > strong_count:
        return "适合观望 — 空头力量偏强，不宜冒进，等待企稳信号"
    return "适合观察 — 市场表现中性，精选个股为主"


# ── 输出文件 ──────────────────────────────────────────────────
def save_report(
    report_data: dict[str, Any],
    report_dir: str | Path | None = None,
) -> tuple[Path, Path]:
    """保存 markdown 和 json 报告文件。

    Returns:
        (markdown_path, json_path)
    """
    output_dir = Path(report_dir) if report_dir else REPORT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    date_str = report_data["report_date"]
    md_path = output_dir / f"daily_decision_{date_str}.md"
    json_path = output_dir / f"daily_decision_{date_str}.json"

    # 写 Markdown
    md_content = _build_markdown(report_data)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    # 写 JSON
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)

    logger.info("报告已生成: %s", md_path)
    logger.info("报告已生成: %s", json_path)
    return md_path, json_path


def _build_markdown(data: dict[str, Any]) -> str:
    """将报告数据渲染为 Markdown 格式。"""
    lines: list[str] = []
    overview = data["overview"]

    # ── 标题 ──
    lines.append(f"# 北极星每日决策报告 — {data['report_date']}")
    lines.append("")

    # ── 1. 今日总览 ──
    lines.append("## 📊 今日总览")
    lines.append("")
    for key, val in overview.items():
        lines.append(f"- **{key}**: {val}")
    lines.append("")

    quality = data.get("data_quality", {})
    lines.append("## 🛡️ 行情数据质量")
    lines.append("")
    lines.append(f"- **snapshot_id**: `{data.get('snapshot_id', '—')}`")
    lines.append(f"- **行情生成时间**: {data.get('generated_at', '—')}")
    lines.append(f"- **有效覆盖率**: {float(data.get('coverage_ratio', 0)):.1%}")
    lines.append(f"- **报告状态**: **{data.get('recommendation_status', 'DATA_INSUFFICIENT')}**")
    lines.append(f"- **数据源汇总**: {data.get('provider_summary', {})}")
    if quality.get("warning"):
        lines.append(f"- ⚠️ **警告**: {quality['warning']}")
    invalid = quality.get("invalid_symbols", [])
    if invalid:
        lines.append("")
        lines.append("| 无效标的 | 状态 | 来源 | as_of | 原因 |")
        lines.append("|---|---|---|---|---|")
        for item in invalid:
            lines.append(
                f"| {item.get('symbol')} | {item.get('status')} | {item.get('source')} "
                f"| {item.get('as_of') or '—'} | {item.get('error_code') or item.get('error_message') or '—'} |"
            )
    lines.append("")

    # ── 2. 市场分组 ──
    lines.append("## 📂 市场分组")
    lines.append("")
    for sector, stocks in data["sector_stocks"].items():
        lines.append(f"### {sector}")
        lines.append("")
        lines.append("| 股票代码 | 公司名称 | 当前价格 | 今日涨跌 | 近5日涨跌 | 近20日涨跌 | 趋势 | 风险 | 建议 |")
        lines.append("|---------|---------|---------:|--------:|----------:|-----------:|:----:|:----:|:------|")
        for s in stocks:
            c5 = f"{s['change_pct_5d']:+.1f}%" if s["change_pct_5d"] is not None else "—"
            c20 = f"{s['change_pct_20d']:+.1f}%" if s["change_pct_20d"] is not None else "—"
            price_str = f"${s['current_price']:.2f}" if s["current_price"] else "—"
            lines.append(
                f"| {s['symbol']} | {s['company_cn']} | {price_str} "
                f"| {s['change_pct_today']:+.1f}% | {c5} | {c20} "
                f"| {s['trend']} | {s['risk_level']} | {s['suggestion']} |"
            )
        lines.append("")

    # ── 3. Top 5 机会 ──
    lines.append("## 🟢 Top 5 机会")
    lines.append("")
    if not data["top5_opportunity"]:
        lines.append(f"**{data.get('recommendation_status', 'NO_RECOMMENDATION')}：数据质量未达门槛，不生成正式 Top 5。**")
        lines.append("")
    for i, s in enumerate(data["top5_opportunity"], 1):
        price_str = f"${s['current_price']:.2f}" if s["current_price"] else "—"
        lines.append(f"**{i}. {s['symbol']} ({s['company_cn']})** — {price_str} | 今日 {s['change_pct_today']:+.1f}% | 做多可操作分 {s['score']}")
        lines.append(f"   - 建议: **{s['suggestion']}**")
        lines.append(f"   - 理由: {s['reason']}")
        lines.append(f"   - 关注原因: {s['why']}")
        lines.append("")

    # ── 4. Top 5 风险 ──
    lines.append("## 🔴 Top 5 风险")
    lines.append("")
    if not data["top5_risk"]:
        lines.append("当前不生成伪装完整的 Top 5 风险列表。")
        lines.append("")
    for i, s in enumerate(data["top5_risk"], 1):
        price_str = f"${s['current_price']:.2f}" if s["current_price"] else "—"
        lines.append(f"**{i}. {s['symbol']} ({s['company_cn']})** — {price_str} | 今日 {s['change_pct_today']:+.1f}% | 风险 {s['risk_level']}")
        lines.append(f"   - 建议: **{s['suggestion']}**")
        lines.append(f"   - 理由: {s['reason']}")
        lines.append(f"   - 风险来源: {s['why']}")
        lines.append("")

    # ── 5. 持仓特别提示 ──
    portfolio_notes = data.get("portfolio_notes", [])
    valuation = data.get("portfolio_valuation", {})
    lines.append("## 💼 持仓估值质量")
    lines.append("")
    lines.append(f"- **portfolio_snapshot_id**: `{valuation.get('portfolio_snapshot_id', '—')}`")
    lines.append(f"- **market_snapshot_id**: `{valuation.get('market_snapshot_id', '—')}`")
    lines.append(f"- **估值时间**: {valuation.get('generated_at', '—')}")
    lines.append(f"- **估值状态**: {valuation.get('valuation_status', 'incomplete')}")
    lines.append(f"- **持仓覆盖率**: {float(valuation.get('holding_coverage_ratio', 0)):.1%}")
    if valuation.get("missing_symbols"):
        lines.append(f"- **缺失标的**: {', '.join(valuation['missing_symbols'])}")
        lines.append("- 总市值、总盈亏和总资产已关闭，避免展示伪精确结果。")
    lines.append("")
    lines.append("| 股票 | 数量 | 成本价 | 当前价 | 行情来源 | 行情时间 | 市值 | 未实现盈亏 | 收益率 | 状态 |")
    lines.append("|------|-----:|------:|------:|---------|---------|-----:|-----------:|------:|------|")
    for position in valuation.get("positions", []):
        def money(field: str) -> str:
            value = position.get(field)
            return f"${float(value):,.2f}" if value is not None else "—"
        pct_value = position.get("unrealized_pnl_percent")
        pct = f"{float(pct_value):+.2f}%" if pct_value is not None else "—"
        lines.append(
            f"| {position.get('symbol', '—')} | {position.get('quantity', '—')} "
            f"| {money('average_cost')} | {money('current_price')} "
            f"| {position.get('price_source') or '—'} | {position.get('price_as_of') or '—'} "
            f"| {money('market_value')} | {money('unrealized_pnl')} | {pct} "
            f"| {position.get('valuation_status', '—')} |"
        )
    lines.append("")
    if valuation.get("valuation_status") in {"complete", "no_positions"}:
        lines.append(f"- **现金**: ${float(valuation['cash']):,.2f} {valuation.get('cash_currency', '')}")
        lines.append(f"- **持仓总市值**: ${float(valuation['total_market_value']):,.2f}")
        lines.append(f"- **持仓总成本**: ${float(valuation['total_cost_basis']):,.2f}")
        lines.append(f"- **总未实现盈亏**: ${float(valuation['total_unrealized_pnl']):,.2f}")
        lines.append(f"- **总资产**: ${float(valuation['total_asset_value']):,.2f}")
    else:
        lines.append("- **可信总资产/总盈亏**: 不可用（估值不完整）")
        if valuation.get("partial_market_value") is not None:
            lines.append(f"- **部分已定价市值（非总值）**: ${float(valuation['partial_market_value']):,.2f}")
    lines.append("")
    if portfolio_notes:
        lines.append("## 📌 我的持仓特别提示")
        lines.append("")
        for p in portfolio_notes:
            lines.append(f"**{p['symbol']} ({p['company_cn']})** — 持股 {p['持股数量']} 股，均价 ${float(p['平均成本']):.2f}")
            lines.append(f"   - 当前价格: ${float(p['当前价格']):.2f}" if p['当前价格'] else "   - 当前价格: —")
            lines.append(f"   - 今日涨跌: {p['今日涨跌幅']:+.1f}%")
            lines.append(f"   - 趋势: {p['趋势']} | 风险: {p['风险']} | 建议: **{p['建议']}**")
            lines.append(f"   - {p['理由']}")
            lines.append("")

    # ── 6. 今日一句话结论 ──
    lines.append("## 💡 今日一句话结论")
    lines.append("")
    lines.append(f"> **{data['overall_conclusion']}**")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"*报告生成时间: {data['report_date']} {data['report_time']}*")
    lines.append("*本报告仅供决策参考，不构成投资建议。系统未接入券商，不执行自动交易。*")

    return "\n".join(lines)


# ── 主入口 ──────────────────────────────────────────────────
def generate_daily_decision_report(
    report_dir: str | Path | None = None,
    *,
    snapshot: MarketSnapshot | None = None,
    symbols: list[str] | None = None,
    portfolio: dict[str, dict[str, Any]] | None = None,
    portfolio_state: PortfolioState | None = None,
    portfolio_snapshot: PortfolioSnapshot | None = None,
    provider: Any | None = None,
    save: bool = True,
) -> dict[str, Any]:
    """生成每日决策报告的主流程。

    Args:
        report_dir: 报告输出目录，默认 reports/daily_decision/
        snapshot: 已冻结的唯一行情快照；传入后绝不再次访问 provider

    Returns:
        报告数据字典
    """
    if save and report_dir is None:
        _setup_logger()
    logger.info("=" * 60)
    logger.info("开始生成每日决策报告")

    # 1. 读取观察池
    symbols = list(symbols) if symbols is not None else load_watchlist()
    logger.info("观察池股票数量: %d", len(symbols))
    if not symbols:
        logger.error("观察池为空，无法生成报告")
        return {"error": "观察池为空"}

    # 2. 只通过统一 Repository 读取原始持仓；兼容 mapping 不得虚构现金。
    if portfolio_state is None and portfolio_snapshot is None:
        portfolio_state = (
            portfolio_state_from_mapping(
                portfolio,
                cash=None,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
            if portfolio is not None
            else load_portfolio_state()
        )
    portfolio_symbols = (
        list(portfolio_state.position_symbols)
        if portfolio_state is not None
        else [position.symbol for position in portfolio_snapshot.positions]
    )
    logger.info("统一持仓来源股票: %s", portfolio_symbols or "无")

    # 3. 正式入口只创建一次快照；传入快照时严禁再次获取行情。
    if snapshot is None:
        from northstar.data.market_data_provider import MarketDataProvider

        requested = (
            list(requested_market_symbols(symbols, portfolio_state))
            if portfolio_state is not None
            else list(dict.fromkeys(symbols + portfolio_symbols))
        )
        snapshot = build_market_snapshot(requested, provider or MarketDataProvider())
    if portfolio_snapshot is None:
        if portfolio_state is None:
            raise ValueError("portfolio_state is required to create PortfolioSnapshot")
        portfolio_snapshot = value_portfolio(portfolio_state, snapshot)
    if portfolio_snapshot.market_snapshot_id != snapshot.snapshot_id:
        raise ValueError("PortfolioSnapshot and MarketSnapshot IDs do not match")
    info_map = {
        symbol: _stock_info_from_quote(snapshot.quote(symbol))
        for symbol in snapshot.requested_symbols
    }
    logger.info("快照 %s 有效行情 %d/%d", snapshot.snapshot_id, len(snapshot.valid_symbols), len(snapshot.requested_symbols))

    # 4. 构建报告数据
    report_data = build_report_data(
        info_map,
        snapshot=snapshot,
        requested_symbols=symbols,
        portfolio_state=portfolio_state,
        portfolio_snapshot=portfolio_snapshot,
    )
    logger.info("报告数据构建完成")

    # 5. 保存文件（测试可 save=False；UI 永不调用本函数）
    if save:
        md_path, json_path = save_report(report_data, report_dir)
        report_data["_md_path"] = str(md_path)
        report_data["_json_path"] = str(json_path)
        logger.info("报告生成完成: %s", md_path)
    logger.info("=" * 60)
    return report_data


if __name__ == "__main__":
    from northstar.data.market_data_provider import MarketDataProvider

    _symbols = load_watchlist()
    _portfolio_state = load_portfolio_state()
    _requested = list(requested_market_symbols(_symbols, _portfolio_state))
    _snapshot = build_market_snapshot(_requested, MarketDataProvider())
    _portfolio_snapshot = value_portfolio(_portfolio_state, _snapshot)
    result = generate_daily_decision_report(
        snapshot=_snapshot,
        symbols=_symbols,
        portfolio_state=_portfolio_state,
        portfolio_snapshot=_portfolio_snapshot,
    )
    if "error" in result:
        print(f"❌ 报告生成失败: {result['error']}")
        sys.exit(1)
    print(f"✅ 每日决策报告已生成")
    print(f"   Markdown: {result.get('_md_path', '')}")
    print(f"   JSON:     {result.get('_json_path', '')}")
    print(f"   一句话结论: {result.get('overall_conclusion', '')}")
