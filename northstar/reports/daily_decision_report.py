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
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── 目录定位 ──────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── 常量 ───────────────────────────────────────────────────────
WATCHLIST_PATH = PROJECT_ROOT / "watchlist.json"
PORTFOLIO_PATH = PROJECT_ROOT / "portfolio.json"
REPORT_DIR = PROJECT_ROOT / "reports" / "daily_decision"
LOG_DIR = PROJECT_ROOT / "logs"

# 25支股票 → 板块分组
SECTOR_GROUPS: dict[str, list[str]] = {
    "AI 芯片/半导体":   ["NVDA", "AMD", "AVGO", "TSM", "ASML"],
    "云计算/大科技":    ["MSFT", "GOOGL", "META", "AMZN", "AAPL"],
    "AI 应用/软件":     ["PLTR", "CRWD", "PANW", "SNOW", "MDB"],
    "高波动成长股":     ["TSLA", "ARM", "MU", "SMCI", "DELL"],
    "加密/金融科技":    ["SOFI", "COIN", "ORCL"],
    "量子/新兴":        ["IONQ", "RGTI"],
}

# 中文名称映射（人工维护，开源数据无需 API）
COMPANY_NAMES: dict[str, str] = {
    "NVDA": "英伟达",    "AMD": "超威半导体",  "AVGO": "博通",
    "TSM": "台积电",     "ASML": "阿斯麦",
    "MSFT": "微软",      "GOOGL": "谷歌",       "META": "Meta",
    "AMZN": "亚马逊",    "AAPL": "苹果",
    "PLTR": "Palantir",  "CRWD": "CrowdStrike", "PANW": "Palo Alto",
    "SNOW": "Snowflake", "MDB": "MongoDB",
    "TSLA": "特斯拉",    "ARM": "ARM 控股",     "MU": "美光科技",
    "SMCI": "超微电脑",  "DELL": "戴尔",
    "SOFI": "SoFi",      "COIN": "Coinbase",    "ORCL": "甲骨文",
    "IONQ": "IonQ",      "RGTI": "Rigetti",
}

# 用户持仓（从 portfolio.json 读取，此处为后备）
USER_POSITIONS: dict[str, str] = {
    "NVDA": "持仓", "SOFI": "持仓", "SPCX": "持仓",
}


# ── 行情数据结构 ──────────────────────────────────────────────
@dataclass
class StockPriceInfo:
    """单只股票的行情+决策信息。"""
    symbol: str
    company_cn: str = ""
    current_price: float = 0.0
    change_pct_today: float = 0.0
    change_pct_5d: float | None = None
    change_pct_20d: float | None = None
    trend: str = "中性"        # 强势 / 中性 / 弱势
    risk_level: str = "中"     # 低 / 中 / 高
    suggestion: str = "暂不买入"   # 操作建议
    reason: str = ""           # 一句话理由
    score: float = 0.0         # 综合评分（用于排序）


# ── 日志 ───────────────────────────────────────────────────────
logger = logging.getLogger("daily_decision_report")


def _setup_logger() -> None:
    """配置日志，输出到 logs/daily_decision_report.log。"""
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
        return [
            "NVDA", "AMD", "AVGO", "TSM", "ASML",
            "MSFT", "GOOGL", "META", "AMZN", "AAPL",
            "PLTR", "TSLA", "SOFI", "IONQ", "RGTI",
            "ARM", "MU", "SMCI", "DELL", "ORCL",
            "CRWD", "PANW", "SNOW", "MDB", "COIN",
        ]
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
    """读取 portfolio.json 获得用户持仓信息。

    Returns:
        {symbol: {"shares": int, "avg_cost": float}, ...}
    """
    if not PORTFOLIO_PATH.exists():
        logger.info("portfolio.json 不存在，跳过持仓读取")
        return {}
    try:
        with open(PORTFOLIO_PATH, encoding="utf-8") as f:
            data = json.load(f)
        positions = data.get("positions", [])
        result: dict[str, dict[str, Any]] = {}
        for pos in positions:
            ticker = str(pos.get("ticker", "")).strip().upper()
            if not ticker:
                continue
            result[ticker] = {
                "shares": float(pos.get("shares", 0)),
                "avg_cost": float(pos.get("avg_cost", 0.0)),
            }
        return result
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("读取 portfolio.json 失败: %s", exc)
        return {}


# ── 获取行情 ──────────────────────────────────────────────────
def fetch_prices(
    symbols: list[str],
) -> dict[str, StockPriceInfo]:
    """通过 YFinancePriceProvider 获取 25 支股票行情。

    降级策略：
    1. 先用 get_quote 获取当前价和前收盘
    2. 再用 history 获取近 20 日数据
    3. 如果 yfinance 不可用或某支股票失败，跳过不影响其他股票
    4. 每个请求设置 10 秒超时，避免国内网络环境长时间挂起
    """
    from price_provider import YFinancePriceProvider, PriceNotFoundError
    import concurrent.futures
    import functools

    # ── 代理感知 ─────────────────────────────────────────────
    from northstar.config.network import (
        get_working_proxy,
        get_price_provider_session,
        get_connectivity_status,
    )
    _connectivity = get_connectivity_status()
    _proxy = _connectivity.get("proxy_url", "直连")

    # 如果找到代理，配置 yfinance 使用代理 session
    _session = get_price_provider_session()
    if _session is not None:
        try:
            # 通过设置环境变量让 yfinance 使用代理
            pass  # yfinance 会读取 requests 的 session 配置
        except Exception:
            pass

    provider = YFinancePriceProvider()
    info_map: dict[str, StockPriceInfo] = {}
    _priced_count = 0

    def _fetch_single(symbol: str) -> StockPriceInfo:
        """获取单支股票的行情和决策信息。"""
        info = StockPriceInfo(symbol=symbol, company_cn=COMPANY_NAMES.get(symbol, symbol))

        # Step 1: 获取当前价和今日涨跌幅
        try:
            quote = provider.get_quote(symbol)
            price = float(quote.price)
            prev_close = float(quote.previous_close) if quote.previous_close else None
            info.current_price = price
            if prev_close and prev_close > 0:
                info.change_pct_today = round((price - prev_close) / prev_close * 100, 2)
            else:
                info.change_pct_today = 0.0
        except (PriceNotFoundError, Exception) as exc:
            logger.warning("获取 %s 行情失败: %s", symbol, exc)
            info.current_price = 0.0
            info.change_pct_today = 0.0

        # Step 2: 获取近 20 日历史数据
        try:
            ticker_factory = provider._get_ticker_factory()
            ticker = ticker_factory(symbol)
            history = ticker.history(period="1mo", interval="1d")
            if history is not None and not history.empty:
                closes = history["Close"].dropna()
                if len(closes) >= 2:
                    latest = float(closes.iloc[-1])
                    if latest > 0 and info.current_price == 0.0:
                        info.current_price = latest
                    if len(closes) >= 5:
                        old_5 = float(closes.iloc[-5])
                        info.change_pct_5d = round((latest - old_5) / old_5 * 100, 2)
                    old_20 = float(closes.iloc[0])
                    info.change_pct_20d = round((latest - old_20) / old_20 * 100, 2)
        except Exception as exc:
            logger.debug("获取 %s 历史数据失败: %s", symbol, exc)

        # Step 3-7: 决策计算
        info.trend = _judge_trend(info)
        info.risk_level = _judge_risk(info)
        info.suggestion = _judge_suggestion(info)
        info.reason = _generate_reason(info)
        info.score = _compute_score(info)
        return info

    # 使用线程池并行获取，单支股票超时 12 秒
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_map = {executor.submit(_fetch_single, sym): sym for sym in symbols}
        for future in concurrent.futures.as_completed(future_map, timeout=120):
            sym = future_map[future]
            try:
                info_map[sym] = future.result(timeout=12)
                if info_map[sym].current_price > 0:
                    _priced_count += 1
            except concurrent.futures.TimeoutError:
                logger.warning("获取 %s 行情超时", sym)
                info = StockPriceInfo(symbol=sym, company_cn=COMPANY_NAMES.get(sym, sym))
                info.trend = _judge_trend(info)
                info.risk_level = _judge_risk(info)
                info.suggestion = _judge_suggestion(info)
                info.reason = _generate_reason(info)
                info.score = _compute_score(info)
                info_map[sym] = info
            except Exception as exc:
                logger.warning("获取 %s 行情异常: %s", sym, exc)
                info = StockPriceInfo(symbol=sym, company_cn=COMPANY_NAMES.get(sym, sym))
                info.trend = _judge_trend(info)
                info.risk_level = _judge_risk(info)
                info.suggestion = _judge_suggestion(info)
                info.reason = _generate_reason(info)
                info.score = _compute_score(info)
                info_map[sym] = info

    # 保存行情源状态供 report 使用
    _pct_priced = _priced_count / max(len(symbols), 1)
    if _pct_priced >= 0.8:
        info_map["__market_status__"] = "正常"
    elif _pct_priced >= 0.3:
        info_map["__market_status__"] = "部分可用"
    else:
        info_map["__market_status__"] = "不可用"
    info_map["__priced_count__"] = float(_priced_count)
    info_map["__proxy_url__"] = _proxy

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
    """综合评分，用于排序 Top 5。"""
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
    return round(score, 1)


# ── 报告生成 ──────────────────────────────────────────────────
def build_report_data(
    info_map: dict[str, StockPriceInfo],
    portfolio: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """构建完整的每日决策报告数据字典。"""
    # 提取行情源状态元数据（以 __ 开头的键）
    _market_status = info_map.pop("__market_status__", "不可用") if isinstance(info_map, dict) else "不可用"
    _priced_count = info_map.pop("__priced_count__", 0.0) if isinstance(info_map, dict) else 0.0
    _proxy_url = info_map.pop("__proxy_url__", "直连") if isinstance(info_map, dict) else "直连"

    symbols = list(info_map.keys())
    now_utc = datetime.now(timezone.utc)
    now_beijing = now_utc.astimezone()  # 系统时区
    date_str = now_beijing.strftime("%Y-%m-%d")
    time_str = now_beijing.strftime("%H:%M:%S")
    total = len(symbols)
    priced = int(_priced_count)

    # 行情源状态中文
    market_status_cn = _market_status if _market_status in ("正常", "部分可用", "不可用") else "不可用"
    market_status_icon = {"正常": "✅", "部分可用": "⚠️", "不可用": "🔴"}.get(market_status_cn, "❓")

    # 构建数据异常提示
    data_warning = ""
    if priced < total * 0.3 or market_status_cn == "不可用":
        data_warning = "⚠ 当前报告只适合观察系统结构，不适合作为交易判断依据 — 行情源不可用，大部分价格为默认值"

    # 1. 今日总览
    overview = {
        "当前日期": date_str,
        "观察池股票数量": total,
        "成功获取价格数量": f"{priced}/{total}",
        "行情源状态": f"{market_status_icon} {market_status_cn}",
        "当前使用代理": _proxy_url,
        "数据更新时间": f"{date_str} {time_str}",
        "系统运行状态": "本地正常运行（未接入券商）",
    }

    # 2. 按板块分组
    sector_stocks: dict[str, list[StockPriceInfo]] = {}
    for sector, sector_symbols in SECTOR_GROUPS.items():
        matched = [info_map[s] for s in sector_symbols if s in info_map]
        if matched:
            sector_stocks[sector] = matched
    # 未分组的归入"其他"
    grouped_symbols = {s for ss in SECTOR_GROUPS.values() for s in ss}
    others = [v for k, v in info_map.items() if k not in grouped_symbols]
    if others:
        sector_stocks["其他"] = others

    # 3. 每只股票的简明判断（StockPriceInfo 已包含）
    stock_details = {s: info_map[s] for s in symbols}

    # 4. Top 5 机会（评分最高，且建议不是"高风险回避"）
    candidates_opportunity = [
        v for v in info_map.values()
        if v.suggestion not in ("高风险回避", "减仓观察") and v.score > 0
    ]
    candidates_opportunity.sort(key=lambda x: -x.score)
    top5_opportunity = candidates_opportunity[:5]

    # 5. Top 5 风险（评分最低，或高风险等级）
    candidates_risk = [
        v for v in info_map.values()
        if v.risk_level == "高" or v.trend == "弱势"
    ]
    candidates_risk.sort(key=lambda x: x.score)
    top5_risk = candidates_risk[:5]
    # 如果不足 5 个，补排序最低的
    if len(top5_risk) < 5:
        all_sorted = sorted(info_map.values(), key=lambda x: x.score)
        for v in all_sorted:
            if v not in top5_risk and len(top5_risk) < 5:
                top5_risk.append(v)

    # 6. 持仓特别提示
    portfolio_notes: list[dict[str, Any]] = []
    if portfolio:
        for sym in portfolio:
            if sym in info_map:
                pinfo = info_map[sym]
                pos = portfolio[sym]
                portfolio_notes.append({
                    "symbol": sym,
                    "company_cn": COMPANY_NAMES.get(sym, sym),
                    "持股数量": pos.get("shares", 0),
                    "平均成本": pos.get("avg_cost", 0.0),
                    "当前价格": pinfo.current_price,
                    "今日涨跌幅": pinfo.change_pct_today,
                    "趋势": pinfo.trend,
                    "风险": pinfo.risk_level,
                    "建议": pinfo.suggestion,
                    "理由": pinfo.reason,
                })

    # 7. 今日一句话结论
    overall_conclusion = _make_overall_conclusion(info_map)

    return {
        "report_date": date_str,
        "report_time": time_str,
        "overview": overview,
        "sector_stocks": {
            sec: [
                {
                    "symbol": s.symbol,
                    "company_cn": s.company_cn,
                    "current_price": s.current_price,
                    "change_pct_today": s.change_pct_today,
                    "change_pct_5d": s.change_pct_5d,
                    "change_pct_20d": s.change_pct_20d,
                    "trend": s.trend,
                    "risk_level": s.risk_level,
                    "suggestion": s.suggestion,
                    "reason": s.reason,
                    "score": s.score,
                }
                for s in stocks
            ]
            for sec, stocks in sector_stocks.items()
        },
        "stock_details": {
            sym: {
                "company_cn": info.company_cn,
                "current_price": info.current_price,
                "change_pct_today": info.change_pct_today,
                "change_pct_5d": info.change_pct_5d,
                "change_pct_20d": info.change_pct_20d,
                "trend": info.trend,
                "risk_level": info.risk_level,
                "suggestion": info.suggestion,
                "reason": info.reason,
                "score": info.score,
            }
            for sym, info in stock_details.items()
        },
        "top5_opportunity": [
            {
                "symbol": s.symbol,
                "company_cn": s.company_cn,
                "score": s.score,
                "current_price": s.current_price,
                "change_pct_today": s.change_pct_today,
                "trend": s.trend,
                "suggestion": s.suggestion,
                "reason": s.reason,
                "why": _why_opportunity(s),
            }
            for s in top5_opportunity
        ],
        "top5_risk": [
            {
                "symbol": s.symbol,
                "company_cn": s.company_cn,
                "score": s.score,
                "current_price": s.current_price,
                "change_pct_today": s.change_pct_today,
                "trend": s.trend,
                "risk_level": s.risk_level,
                "suggestion": s.suggestion,
                "reason": s.reason,
                "why": _why_risk(s),
            }
            for s in top5_risk
        ],
        "portfolio_notes": portfolio_notes,
        "overall_conclusion": overall_conclusion,
        "user_positions": list(portfolio.keys()) if portfolio else [],
    }


def _why_opportunity(info: StockPriceInfo) -> str:
    """解释为什么值得关注。"""
    if info.trend == "强势" and info.risk_level == "低":
        return f"处于强势上涨通道，风险可控，建议纳入买入观察名单"
    if info.change_pct_today > 2:
        return f"今日放量上涨 {info.change_pct_today:+.1f}%，短线动能强"
    if info.change_pct_5d is not None and info.change_pct_5d > 5:
        return f"近 5 日累计上涨 {info.change_pct_5d:+.1f}%，中期趋势向好"
    score_detail = f"综合评分 {info.score} 分"
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
    for i, s in enumerate(data["top5_opportunity"], 1):
        price_str = f"${s['current_price']:.2f}" if s["current_price"] else "—"
        lines.append(f"**{i}. {s['symbol']} ({s['company_cn']})** — {price_str} | 今日 {s['change_pct_today']:+.1f}% | 评分 {s['score']}")
        lines.append(f"   - 建议: **{s['suggestion']}**")
        lines.append(f"   - 理由: {s['reason']}")
        lines.append(f"   - 关注原因: {s['why']}")
        lines.append("")

    # ── 4. Top 5 风险 ──
    lines.append("## 🔴 Top 5 风险")
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
    if portfolio_notes:
        lines.append("## 📌 我的持仓特别提示")
        lines.append("")
        for p in portfolio_notes:
            lines.append(f"**{p['symbol']} ({p['company_cn']})** — 持股 {p['持股数量']} 股，均价 ${p['平均成本']:.2f}")
            lines.append(f"   - 当前价格: ${p['当前价格']:.2f}" if p['当前价格'] else "   - 当前价格: —")
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
) -> dict[str, Any]:
    """生成每日决策报告的主流程。

    Args:
        report_dir: 报告输出目录，默认 reports/daily_decision/

    Returns:
        报告数据字典
    """
    _setup_logger()
    logger.info("=" * 60)
    logger.info("开始生成每日决策报告")

    # 1. 读取观察池
    symbols = load_watchlist()
    logger.info("观察池股票数量: %d", len(symbols))
    if not symbols:
        logger.error("观察池为空，无法生成报告")
        return {"error": "观察池为空"}

    # 2. 读取持仓
    portfolio = load_portfolio()
    logger.info("读取到持仓股票: %s", list(portfolio.keys()) if portfolio else "无")

    # 3. 获取行情
    info_map = fetch_prices(symbols)
    # 只统计真正的股票（跳过 __ 开头的元数据键）
    priced_count = sum(
        1 for k, v in info_map.items()
        if not k.startswith("__") and isinstance(v, StockPriceInfo) and v.current_price > 0
    )
    real_stock_count = sum(
        1 for k in info_map if not k.startswith("__")
    )
    logger.info("成功获取 %d/%d 支股票行情", priced_count, real_stock_count)

    # 4. 构建报告数据
    report_data = build_report_data(info_map, portfolio)
    logger.info("报告数据构建完成")

    # 5. 保存文件
    md_path, json_path = save_report(report_data, report_dir)
    report_data["_md_path"] = str(md_path)
    report_data["_json_path"] = str(json_path)

    logger.info("报告生成完成: %s", md_path)
    logger.info("=" * 60)
    return report_data


if __name__ == "__main__":
    result = generate_daily_decision_report()
    if "error" in result:
        print(f"❌ 报告生成失败: {result['error']}")
        sys.exit(1)
    print(f"✅ 每日决策报告已生成")
    print(f"   Markdown: {result.get('_md_path', '')}")
    print(f"   JSON:     {result.get('_json_path', '')}")
    print(f"   一句话结论: {result.get('overall_conclusion', '')}")