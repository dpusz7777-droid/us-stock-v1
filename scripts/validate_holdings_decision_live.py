#!/usr/bin/env python3
"""Generate the read-only live acceptance artifact for the formal holdings chain."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    from northstar.engine.holdings_decision_engine import generate_holdings_decisions

    decisions, summary = generate_holdings_decisions(
        portfolio_path=str(PROJECT_ROOT / "portfolio_migrated_candidate.json")
    )
    fields = (
        "symbol", "security_name", "current_price", "price_timestamp", "price_status",
        "provider", "provider_error", "first_valid_bar_date", "last_valid_bar_date",
        "valid_bar_count", "valid_history_start", "stop_loss", "target_1", "target_2",
        "action", "today_action", "suggested_shares", "blocking_rules", "data_quality",
        "is_mock", "is_synthetic",
    )
    rows = []
    for decision in decisions:
        row = {field: decision.get(field) for field in fields}
        indicators = decision.get("indicators_summary") or {}
        row.update({
            "MA5": indicators.get("ma5"),
            "MA10": indicators.get("ma10"),
            "MA20": indicators.get("ma20"),
            "MA50": indicators.get("ma50"),
            "ATR14": indicators.get("atr14"),
            "swing_high_10": indicators.get("swing_high_10"),
            "swing_high_20": indicators.get("swing_high_20"),
        })
        rows.append(row)

    spcx = next((row for row in rows if row["symbol"] == "SPCX"), None)
    acceptance = {
        "formal_portfolio_source": summary.get("portfolio_source") == "portfolio_migrated_candidate.json",
        "is_mock_false": summary.get("is_mock") is False and all(row.get("is_mock") is False for row in rows),
        "is_synthetic_false": summary.get("is_synthetic") is False and all(row.get("is_synthetic") is False for row in rows),
        "nvda_real_price": any(row["symbol"] == "NVDA" and row["current_price"] and row["provider"] == "yahoo-chart-v8" for row in rows),
        "sofi_real_price": any(row["symbol"] == "SOFI" and row["current_price"] and row["provider"] == "yahoo-chart-v8" for row in rows),
        "spcx_old_history_isolated": bool(
            spcx and spcx.get("first_valid_bar_date") and spcx["first_valid_bar_date"] >= "2026-06-12"
        ),
        "spcx_ma50_unavailable_under_50_bars": bool(
            spcx and spcx.get("valid_bar_count", 0) < 50 and spcx.get("MA50") is None
        ),
        "spcx_add_blocked": bool(spcx and spcx.get("action") != "加仓候选" and spcx.get("suggested_shares") is None),
    }
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": summary,
        "acceptance": acceptance,
        "decisions": rows,
    }
    report_dir = PROJECT_ROOT / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "holdings_decision_live_validation.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# 持仓决策正式行情验收",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- 正式持仓：{summary.get('portfolio_source')}",
        f"- MarketSnapshot：{summary.get('market_snapshot_id')}",
        f"- 行情状态：{summary.get('market_status')}",
        f"- is_mock：{summary.get('is_mock')}",
        f"- is_synthetic：{summary.get('is_synthetic')}",
        "",
        "| 股票 | 价格 | 状态 | Provider | 首根有效K线 | 末根有效K线 | 有效根数 | MA50 | 动作 | 建议股数 |",
        "|---|---:|---|---|---|---|---:|---:|---|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['symbol']} | {row['current_price'] or '—'} | {row['price_status']} | "
            f"{row['provider']} | {row['first_valid_bar_date'] or '—'} | {row['last_valid_bar_date'] or '—'} | "
            f"{row['valid_bar_count']} | {row['MA50'] or '—'} | {row['action']} | "
            f"{row['suggested_shares'] if row['suggested_shares'] is not None else '—'} |"
        )
    lines.extend(["", "## 验收门", ""])
    for key, value in acceptance.items():
        lines.append(f"- {'通过' if value else '失败'}：{key}")
    (report_dir / "holdings_decision_live_validation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if all(acceptance.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
