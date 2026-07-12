from types import SimpleNamespace

from northstar.analysis.news_provider import NO_EVENT_MESSAGE
from northstar.analysis.technical_analysis import TechnicalIndicators, _compute_scores
from northstar.reports.daily_decision_html import (
    SHORT_WATCHLIST_ENABLED, _apply_context_scores, _build_html, _cn_count,
    _ordinary_analysis, _select_top5, _top_analysis,
)
from northstar.reports.daily_decision_report import AI_WATCHLIST


def _technical(symbol: str = "NVDA") -> TechnicalIndicators:
    t = TechnicalIndicators(
        symbol=symbol, company_cn=symbol, current_price=150, change_pct_today=1.8,
        ma5=147, ma20=140, ma60=130, above_ma20=True, above_ma60=True,
        rsi14=58, volume_ratio=1.45, high_20d=155, low_20d=125,
        change_pct_5d=4.2, change_pct_20d=9.5, tech_status="强势", tech_risk="低",
        data_complete=True, history_rows=63, data_source="mock",
    )
    scores = _compute_scores(t)
    t.trend_score = scores["trend"]
    t.momentum_score = scores["momentum"]
    t.technical_position_score = scores["technical_position"]
    return t


def _missing(symbol: str) -> dict:
    return {
        "symbol": symbol, "news_status": "未获取", "source": None,
        "main_event": NO_EVENT_MESSAGE, "event_type": "暂无有效事件",
        "sentiment": "暂无有效事件", "impact": "事件数据不参与判断。",
        "participates_in_score": False, "event_score": 0.0,
    }


def test_ai_watchlist_is_exact_core_pool():
    assert len(AI_WATCHLIST) == 25
    assert len(set(AI_WATCHLIST)) == 25
    assert not {"AAPL", "AMZN", "COIN"} & set(AI_WATCHLIST)
    required = {"NVDA", "AMD", "AVGO", "TSM", "ASML", "ARM", "MSFT", "GOOGL",
                "META", "PLTR", "VRT", "SMCI", "DELL"}
    assert required <= set(AI_WATCHLIST)


def test_five_part_score_and_safe_missing_news():
    t = _technical()
    events = {"NVDA": _missing("NVDA")}
    _apply_context_scores({"NVDA": t}, events, {"NVDA"})
    assert 0 <= t.trend_score <= 25
    assert 0 <= t.momentum_score <= 20
    assert 0 <= t.technical_position_score <= 20
    assert t.event_sentiment_score == 0
    assert 0 <= t.user_context_score <= 15
    assert 0 <= t.long_actionability_score <= 100
    assert NO_EVENT_MESSAGE in _ordinary_analysis(t, events["NVDA"], True)


def test_analysis_lengths_and_labels():
    t = _technical()
    event = _missing("NVDA")
    _apply_context_scores({"NVDA": t}, {"NVDA": event}, set())
    ordinary = _ordinary_analysis(t, event)
    enhanced = _top_analysis(t, event, 1)
    assert _cn_count(ordinary) >= 220
    assert _cn_count(enhanced) >= 500
    assert "做多可操作分" in ordinary
    assert "不构成投资建议" not in ordinary + enhanced
    assert SHORT_WATCHLIST_ENABLED is False


def test_missing_data_is_capped_and_excluded():
    missing = _technical("AMD")
    missing.data_complete = False
    valid = [_technical(f"S{i}") for i in range(5)]
    all_data = {"AMD": missing, **{item.symbol: item for item in valid}}
    events = {symbol: _missing(symbol) for symbol in all_data}
    _apply_context_scores(all_data, events, {"AMD"})
    assert missing.long_actionability_score <= 20
    candidates = [item for item in all_data.values() if item.data_complete]
    assert missing not in candidates
    top5, complete_count, abnormal = _select_top5(all_data)
    assert top5 == []
    assert complete_count == 5
    assert abnormal is True


def test_complete_mock_chart_calculates_all_indicators(monkeypatch):
    import numpy as np
    from northstar.data.yahoo_chart_provider import ChartHistory
    from northstar.analysis.technical_analysis import fetch_technical_data

    closes = [100 + i * .5 for i in range(63)]
    volumes = [1_000_000 + i * 10_000 for i in range(63)]
    chart = ChartHistory(
        symbol="NVDA", timestamps=list(range(63)), open=closes,
        high=[value + 1 for value in closes], low=[value - 1 for value in closes],
        close=closes, volume=volumes, source="mock",
    )
    monkeypatch.setattr(
        "northstar.data.yahoo_chart_provider.fetch_chart_history",
        lambda *args, **kwargs: chart,
    )
    result = fetch_technical_data(["NVDA"])["NVDA"]
    assert result.data_complete
    assert result.current_price > 0
    assert result.ma5 and result.ma20 and result.ma60
    assert result.rsi14 is not None
    assert result.high_20d and result.low_20d
    assert result.volume_ratio is not None


def test_all_missing_html_enters_abnormal_mode():
    from datetime import datetime

    symbols = list(AI_WATCHLIST)
    technical = {
        symbol: TechnicalIndicators(symbol=symbol, company_cn=symbol)
        for symbol in symbols
    }
    events = {symbol: _missing(symbol) for symbol in symbols}
    _apply_context_scores(technical, events, set())
    top5, complete_count, abnormal = _select_top5(technical)
    output = _build_html(
        datetime.now(), symbols, technical, technical, events, {}, set(), top5,
        {}, "大盘数据缺失", {"status": "未获取", "note": "未获取"},
        {"status": "未接入", "note": "未接入"}, {"proxy_url": "测试"},
        0, complete_count, abnormal, "数据异常", "暂停操作",
        "行情数据不足，今日不生成买入推荐",
    )
    assert "行情数据不足，本报告不可用于今日操作" in output
    assert "数据不足，今日不生成可操作推荐" in output
    assert "今日总策略</small><b>数据异常" in output
    assert "今日操作方向</small><b>暂停操作" in output
    assert 'class="card top"' not in output
    assert all(item.long_actionability_score <= 20 for item in technical.values())
