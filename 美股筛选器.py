# -*- coding: utf-8 -*-
"""
美股安全筛选器

用途：
- 筛选近 30 天成交量温和放大、估值低于同行、财务质量较好、资金指标偏强的美股
- 输出 CSV 和 Excel 文件，方便继续人工复核

说明：
- 美股没有“北向资金”概念，本脚本用 OBV/CMF 等量价资金指标做近 10 日资金流代理
- 数据来自 yfinance，适合初筛，不等同于投研终审或投资建议
"""

import argparse
import csv
import math
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile


try:
    import numpy as np
    import pandas as pd
    import yfinance as yf
except ImportError as exc:
    print("缺少依赖。请先运行：")
    print("python -m pip install yfinance pandas numpy")
    print(f"原始错误：{exc}")
    sys.exit(1)


DEFAULT_TICKERS = [
    # 大型科技 / 平台
    "AAPL", "MSFT", "GOOGL", "GOOG", "META", "AMZN", "NFLX", "UBER", "ABNB",
    # AI / 半导体 / 硬件
    "NVDA", "AMD", "AVGO", "TSM", "ASML", "AMAT", "LRCX", "KLAC", "MU", "QCOM",
    "ARM", "MRVL", "ON", "ADI", "TXN", "MPWR",
    # 软件 / 网络安全 / 数据
    "PLTR", "CRWD", "PANW", "NET", "DDOG", "SNOW", "MDB", "NOW", "CRM", "ADBE",
    "TEAM", "ZS", "OKTA", "INTU",
    # 工业 / 电力 / 数据中心链
    "ETN", "VRT", "GE", "GEV", "EMR", "HON", "ROK", "PH", "PWR", "CEG", "NEE",
    "BWXT", "SMR", "CAT", "DE",
    # 医疗 / 药品
    "LLY", "NVO", "UNH", "ABBV", "MRK", "JNJ", "TMO", "ISRG", "VRTX", "REGN",
    "AMGN", "GILD", "BSX", "SYK",
    # 金融 / 支付
    "JPM", "BAC", "WFC", "GS", "MS", "BLK", "V", "MA", "AXP", "COF",
    # 消费 / 零售
    "COST", "WMT", "HD", "LOW", "MCD", "SBUX", "NKE", "LULU",
    # 能源 / 资源
    "XOM", "CVX", "COP", "SLB", "EOG", "FCX", "NEM",
]


HEADERS = [
    "入选",
    "综合分",
    "股票代码",
    "公司名",
    "行业",
    "赛道判断",
    "最新价",
    "市值",
    "PE",
    "行业PE中位数",
    "近30日放量倍数",
    "近30日平均成交额",
    "近10日OBV趋势",
    "近10日CMF",
    "近三年净利润",
    "ROE",
    "债务/权益",
    "近90日最大回撤",
    "风险提示",
    "原始判定",
]


GROWTH_TRACK_KEYWORDS = {
    "半导体/AI算力": ["semiconductor", "semiconductors", "chips", "electronic components"],
    "软件/SaaS/网络安全": ["software", "cybersecurity", "application", "infrastructure"],
    "数据中心/电力设备": ["electrical", "power", "utilities", "infrastructure", "engineering"],
    "医疗创新": ["biotechnology", "drug", "medical", "healthcare", "diagnostics"],
    "国防/工业自动化": ["aerospace", "defense", "industrial", "automation", "machinery"],
    "金融/支付": ["credit", "payment", "financial", "banks", "capital markets"],
}


def parse_tickers(args):
    tickers = []

    if args.tickers:
        tickers.extend(args.tickers.replace(" ", "").split(","))

    if args.tickers_file:
        path = Path(args.tickers_file)
        if not path.exists():
            raise FileNotFoundError(f"找不到股票列表文件：{path}")
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                tickers.extend(line.replace(",", " ").split())

    if not tickers:
        tickers = DEFAULT_TICKERS

    normalized = []
    seen = set()
    for ticker in tickers:
        ticker = ticker.strip().upper()
        if not ticker or ticker in seen:
            continue
        if ticker.endswith(".WS") or ticker.endswith(".U"):
            continue
        normalized.append(ticker)
        seen.add(ticker)

    return normalized


def safe_float(value):
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def fmt_number(value, digits=2):
    value = safe_float(value)
    if value is None:
        return ""
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.{digits}f}B"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.{digits}f}M"
    return f"{value:.{digits}f}"


def fmt_percent(value, digits=2):
    value = safe_float(value)
    if value is None:
        return ""
    return f"{value * 100:.{digits}f}%"


def pick_row(df, names):
    if df is None or df.empty:
        return []
    for name in names:
        if name in df.index:
            values = []
            for value in df.loc[name].tolist():
                value = safe_float(value)
                if value is not None:
                    values.append(value)
            return values
    return []


def get_info(ticker_obj):
    try:
        return ticker_obj.get_info()
    except Exception:
        try:
            return ticker_obj.info or {}
        except Exception:
            return {}


def get_history(symbol):
    try:
        data = yf.download(
            symbol,
            period="120d",
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
        )
    except Exception:
        return pd.DataFrame()

    if data is None or data.empty:
        return pd.DataFrame()

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    return data.dropna(how="all")


def calc_volume_ratio(history):
    if history.empty or len(history) < 60:
        return None
    volume = history["Volume"].dropna()
    if len(volume) < 60:
        return None
    recent = volume.tail(30).mean()
    previous = volume.iloc[-60:-30].mean()
    if previous <= 0:
        return None
    return recent / previous


def calc_avg_dollar_volume(history):
    if history.empty or len(history) < 30:
        return None
    close = history["Close"].tail(30)
    volume = history["Volume"].tail(30)
    return safe_float((close * volume).mean())


def calc_max_drawdown(history, days=90):
    if history.empty:
        return None
    close = history["Close"].dropna().tail(days)
    if close.empty:
        return None
    rolling_high = close.cummax()
    drawdown = close / rolling_high - 1
    return safe_float(drawdown.min())


def calc_obv_trend(history, days=10):
    if history.empty or len(history) < days + 2:
        return None
    close = history["Close"].dropna()
    volume = history["Volume"].reindex(close.index).fillna(0)
    direction = np.sign(close.diff()).fillna(0)
    obv = (direction * volume).cumsum()
    if len(obv) < days + 1:
        return None
    return safe_float(obv.iloc[-1] - obv.iloc[-days])


def calc_cmf(history, days=10):
    if history.empty or len(history) < days:
        return None
    recent = history.tail(days).copy()
    high = recent["High"]
    low = recent["Low"]
    close = recent["Close"]
    volume = recent["Volume"]
    denominator = (high - low).replace(0, np.nan)
    mfm = ((close - low) - (high - close)) / denominator
    mfv = mfm.fillna(0) * volume
    total_volume = volume.sum()
    if total_volume <= 0:
        return None
    return safe_float(mfv.sum() / total_volume)


def detect_growth_track(sector, industry):
    text = f"{sector or ''} {industry or ''}".lower()
    matched = []
    for track, keywords in GROWTH_TRACK_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            matched.append(track)
    return " / ".join(matched) if matched else "普通行业/需人工判断"


def collect_one(symbol):
    ticker_obj = yf.Ticker(symbol)
    info = get_info(ticker_obj)
    history = get_history(symbol)

    latest_price = None
    if not history.empty and "Close" in history:
        latest_price = safe_float(history["Close"].dropna().iloc[-1])

    market_cap = safe_float(info.get("marketCap"))
    pe = safe_float(info.get("trailingPE"))
    company_name = info.get("shortName") or info.get("longName") or symbol
    sector = info.get("sector") or ""
    industry = info.get("industry") or "未知行业"
    quote_type = info.get("quoteType") or ""
    exchange = info.get("exchange") or info.get("fullExchangeName") or ""

    try:
        financials = ticker_obj.financials
    except Exception:
        financials = pd.DataFrame()

    try:
        balance_sheet = ticker_obj.balance_sheet
    except Exception:
        balance_sheet = pd.DataFrame()

    net_income_values = pick_row(
        financials,
        ["Net Income", "Net Income Common Stockholders", "Net Income From Continuing Operation Net Minority Interest"],
    )
    equity_values = pick_row(
        balance_sheet,
        ["Stockholders Equity", "Total Equity Gross Minority Interest", "Common Stock Equity"],
    )
    debt_values = pick_row(balance_sheet, ["Total Debt", "Net Debt"])

    latest_net_income = net_income_values[0] if net_income_values else None
    oldest_net_income = net_income_values[2] if len(net_income_values) >= 3 else None
    latest_equity = equity_values[0] if equity_values else None
    latest_debt = debt_values[0] if debt_values else None

    roe = safe_float(info.get("returnOnEquity"))
    if roe is None and latest_net_income is not None and latest_equity and latest_equity > 0:
        roe = latest_net_income / latest_equity

    debt_to_equity = safe_float(info.get("debtToEquity"))
    if debt_to_equity is not None:
        debt_to_equity = debt_to_equity / 100 if debt_to_equity > 10 else debt_to_equity
    elif latest_debt is not None and latest_equity and latest_equity > 0:
        debt_to_equity = latest_debt / latest_equity

    volume_ratio = calc_volume_ratio(history)
    avg_dollar_volume = calc_avg_dollar_volume(history)
    max_drawdown = calc_max_drawdown(history, days=90)
    obv_trend = calc_obv_trend(history, days=10)
    cmf_10 = calc_cmf(history, days=10)

    net_income_down = False
    if latest_net_income is not None:
        if latest_net_income <= 0:
            net_income_down = True
        if oldest_net_income is not None and latest_net_income < oldest_net_income:
            net_income_down = True

    return {
        "symbol": symbol,
        "company_name": company_name,
        "sector": sector,
        "industry": industry,
        "growth_track": detect_growth_track(sector, industry),
        "quote_type": quote_type,
        "exchange": exchange,
        "latest_price": latest_price,
        "market_cap": market_cap,
        "pe": pe,
        "volume_ratio": volume_ratio,
        "avg_dollar_volume": avg_dollar_volume,
        "obv_trend": obv_trend,
        "cmf_10": cmf_10,
        "net_income_values": net_income_values[:3],
        "roe": roe,
        "debt_to_equity": debt_to_equity,
        "max_drawdown": max_drawdown,
        "net_income_down": net_income_down,
        "raw_reasons": [],
    }


def build_industry_pe_medians(records):
    grouped = {}
    for record in records:
        pe = safe_float(record.get("pe"))
        industry = record.get("industry") or "未知行业"
        if pe is not None and pe > 0:
            grouped.setdefault(industry, []).append(pe)

    medians = {}
    for industry, values in grouped.items():
        if values:
            medians[industry] = statistics.median(values)
    return medians


def score_record(record, industry_medians, args):
    reasons = []
    score = 0

    price = safe_float(record.get("latest_price"))
    market_cap = safe_float(record.get("market_cap"))
    pe = safe_float(record.get("pe"))
    volume_ratio = safe_float(record.get("volume_ratio"))
    avg_dollar_volume = safe_float(record.get("avg_dollar_volume"))
    roe = safe_float(record.get("roe"))
    debt_to_equity = safe_float(record.get("debt_to_equity"))
    max_drawdown = safe_float(record.get("max_drawdown"))
    obv_trend = safe_float(record.get("obv_trend"))
    cmf_10 = safe_float(record.get("cmf_10"))
    industry = record.get("industry") or "未知行业"
    industry_pe = industry_medians.get(industry)

    if price is None or price < args.min_price:
        reasons.append("股价过低/数据缺失")
    else:
        score += 8

    if market_cap is None or market_cap < args.min_market_cap:
        reasons.append("市值过小/退市风险偏高")
    else:
        score += 10

    if avg_dollar_volume is None or avg_dollar_volume < args.min_avg_dollar_volume:
        reasons.append("流动性不足")
    else:
        score += 10

    if volume_ratio is None:
        reasons.append("成交量数据不足")
    elif args.min_volume_ratio <= volume_ratio <= args.max_volume_ratio:
        score += 12
    else:
        reasons.append("不是温和放量")

    if pe is None or pe <= 0:
        reasons.append("PE 缺失或为负")
    elif industry_pe is not None and pe <= industry_pe:
        score += 12
    elif industry_pe is None:
        reasons.append("行业 PE 中位数不足")
        score += 4
    else:
        reasons.append("PE 高于行业中位数")

    if record.get("net_income_down"):
        reasons.append("近三年净利润下滑或亏损")
    else:
        score += 12

    if roe is None:
        reasons.append("ROE 缺失")
    elif roe >= args.min_roe:
        score += 12
    else:
        reasons.append("ROE 偏低")

    if debt_to_equity is not None and debt_to_equity > args.max_debt_to_equity:
        reasons.append("债务/权益偏高")
    else:
        score += 8

    if obv_trend is not None and obv_trend > 0 and cmf_10 is not None and cmf_10 >= args.min_cmf:
        score += 12
    else:
        reasons.append("近10日资金指标不够强")

    if max_drawdown is None:
        reasons.append("回撤数据不足")
    elif max_drawdown >= -args.max_drawdown:
        score += 12
    else:
        reasons.append("近90日回撤过大")

    if record.get("growth_track") != "普通行业/需人工判断":
        score += 4

    selected = score >= args.min_score and not any(
        key in "；".join(reasons)
        for key in ["退市风险", "流动性不足", "净利润下滑", "回撤过大", "债务/权益偏高"]
    )

    record["industry_pe_median"] = industry_pe
    record["score"] = score
    record["selected"] = selected
    record["reasons"] = reasons
    return record


def record_to_row(record):
    net_income = record.get("net_income_values") or []
    net_income_text = " / ".join(fmt_number(x) for x in net_income)
    reasons = "；".join(record.get("reasons") or [])

    return {
        "入选": "是" if record.get("selected") else "否",
        "综合分": record.get("score", 0),
        "股票代码": record.get("symbol", ""),
        "公司名": record.get("company_name", ""),
        "行业": record.get("industry", ""),
        "赛道判断": record.get("growth_track", ""),
        "最新价": fmt_number(record.get("latest_price")),
        "市值": fmt_number(record.get("market_cap")),
        "PE": fmt_number(record.get("pe")),
        "行业PE中位数": fmt_number(record.get("industry_pe_median")),
        "近30日放量倍数": fmt_number(record.get("volume_ratio")),
        "近30日平均成交额": fmt_number(record.get("avg_dollar_volume")),
        "近10日OBV趋势": fmt_number(record.get("obv_trend")),
        "近10日CMF": fmt_number(record.get("cmf_10"), digits=4),
        "近三年净利润": net_income_text,
        "ROE": fmt_percent(record.get("roe")),
        "债务/权益": fmt_number(record.get("debt_to_equity")),
        "近90日最大回撤": fmt_percent(record.get("max_drawdown")),
        "风险提示": reasons if reasons else "暂无明显硬伤",
        "原始判定": "初筛通过，仍需人工复核" if record.get("selected") else "未通过",
    }


def save_csv(rows, path):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def excel_column_name(index):
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def excel_cell(row, column, value):
    ref = f"{excel_column_name(column)}{row}"
    if value is None:
        value = ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}"><v>{value}</v></c>'
    text = escape(str(value))
    return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'


def save_xlsx(rows, path):
    all_rows = [HEADERS]
    for row in rows:
        all_rows.append([row.get(header, "") for header in HEADERS])

    sheet_rows = []
    for row_index, row_values in enumerate(all_rows, start=1):
        cells = [
            excel_cell(row_index, column_index, value)
            for column_index, value in enumerate(row_values, start=1)
        ]
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    sheet_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
  <sheetFormatPr defaultRowHeight="15"/>
  <cols>
    <col min="1" max="1" width="8" customWidth="1"/>
    <col min="2" max="2" width="10" customWidth="1"/>
    <col min="3" max="3" width="12" customWidth="1"/>
    <col min="4" max="5" width="28" customWidth="1"/>
    <col min="6" max="20" width="20" customWidth="1"/>
  </cols>
  <sheetData>{"".join(sheet_rows)}</sheetData>
</worksheet>'''

    workbook_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="美股筛选结果" sheetId="1" r:id="rId1"/></sheets>
</workbook>'''

    workbook_rels_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>'''

    root_rels_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>'''

    content_types_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>'''

    with ZipFile(path, "w", ZIP_DEFLATED) as workbook:
        workbook.writestr("[Content_Types].xml", content_types_xml)
        workbook.writestr("_rels/.rels", root_rels_xml)
        workbook.writestr("xl/workbook.xml", workbook_xml)
        workbook.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        workbook.writestr("xl/worksheets/sheet1.xml", sheet_xml)


def main():
    parser = argparse.ArgumentParser(description="按财务、估值、量能、资金代理指标筛选美股")
    parser.add_argument("--tickers", default="", help="逗号分隔股票代码，例如：NVDA,MSFT,GOOGL")
    parser.add_argument("--tickers-file", default="", help="股票代码文件，每行一个或用空格/逗号分隔")
    parser.add_argument("--out-prefix", default="美股筛选结果", help="输出文件前缀")
    parser.add_argument("--sleep", type=float, default=0.2, help="每只股票之间暂停秒数，避免请求过快")
    parser.add_argument("--min-price", type=float, default=5, help="最低股价")
    parser.add_argument("--min-market-cap", type=float, default=1_000_000_000, help="最低市值，默认 10 亿美元")
    parser.add_argument("--min-avg-dollar-volume", type=float, default=20_000_000, help="近30日最低平均成交额")
    parser.add_argument("--min-volume-ratio", type=float, default=1.1, help="温和放量下限")
    parser.add_argument("--max-volume-ratio", type=float, default=1.8, help="温和放量上限")
    parser.add_argument("--min-roe", type=float, default=0.08, help="最低 ROE，0.08 表示 8%")
    parser.add_argument("--max-debt-to-equity", type=float, default=2.0, help="最高债务/权益")
    parser.add_argument("--max-drawdown", type=float, default=0.30, help="近90日最大允许回撤，0.30 表示 30%")
    parser.add_argument("--min-cmf", type=float, default=0.02, help="近10日 CMF 下限")
    parser.add_argument("--min-score", type=int, default=72, help="入选最低综合分")
    args = parser.parse_args()

    tickers = parse_tickers(args)
    print(f"开始筛选 {len(tickers)} 只美股。数据源：yfinance。")
    print("提示：这是初筛，不是投资建议；结果仍需人工复核财报、公告和新闻。")

    records = []
    for index, symbol in enumerate(tickers, start=1):
        print(f"[{index}/{len(tickers)}] {symbol}")
        try:
            records.append(collect_one(symbol))
        except Exception as exc:
            records.append(
                {
                    "symbol": symbol,
                    "company_name": symbol,
                    "industry": "数据抓取失败",
                    "growth_track": "",
                    "score": 0,
                    "selected": False,
                    "reasons": [f"抓取失败：{exc}"],
                }
            )
        time.sleep(args.sleep)

    industry_medians = build_industry_pe_medians(records)
    scored = [score_record(record, industry_medians, args) for record in records]
    scored.sort(key=lambda item: (item.get("selected", False), item.get("score", 0)), reverse=True)
    rows = [record_to_row(record) for record in scored]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = f"{args.out_prefix}_{timestamp}.csv"
    xlsx_path = f"{args.out_prefix}_{timestamp}.xlsx"
    save_csv(rows, csv_path)
    save_xlsx(rows, xlsx_path)

    selected = [row for row in rows if row["入选"] == "是"]
    print("")
    print(f"完成。初筛入选 {len(selected)} / {len(rows)} 只。")
    print(f"CSV：{csv_path}")
    print(f"Excel：{xlsx_path}")
    if selected:
        print("入选标的：")
        for row in selected[:20]:
            print(f"- {row['股票代码']}｜{row['公司名']}｜分数 {row['综合分']}｜{row['赛道判断']}")


if __name__ == "__main__":
    main()
