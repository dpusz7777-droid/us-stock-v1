# -*- coding: utf-8 -*-
"""选股系统测试 — generate_stock_signals 的只读测试。"""

from __future__ import annotations
import sys, unittest, os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.ai.stock_selector import generate_stock_signals


class TestStockSelector(unittest.TestCase):
    def setUp(self):
        self.market_bull = {
            "date": "2026-07-05",
            "market_trend": "bullish",
            "sector_strength": {"ai": 8.5, "semiconductors": 5.2, "software": 4.0, "energy": 5.0},
            "risk_level": "low",
        }
        self.market_bear = {
            "date": "2026-07-05",
            "market_trend": "bearish",
            "sector_strength": {"ai": -5.0, "semiconductors": -3.0, "software": -2.0, "energy": -1.0},
            "risk_level": "high",
        }
        self.price_bull = {
            "NVDA": [800.0, 820.0, 830.0, 850.0, 870.0],
            "MSFT": [300.0, 305.0, 310.0, 315.0, 320.0],
        }
        self.price_bear = {
            "NVDA": [870.0, 850.0, 830.0, 810.0, 790.0],
            "MSFT": [320.0, 315.0, 310.0, 305.0, 300.0],
        }

    def test_empty_no_crash(self):
        """空数据不崩溃"""
        signals = generate_stock_signals({}, [], {})
        self.assertIsInstance(signals, list)

    def test_bull_market_buy_signals(self):
        """牛市应产生 BUY 信号"""
        signals = generate_stock_signals(self.market_bull, ["NVDA", "MSFT"], self.price_bull)
        for s in signals:
            if s["symbol"] == "NVDA":
                self.assertEqual(s["signal"], "BUY")

    def test_bear_market_avoid_signals(self):
        """熊市应产生 AVOID 信号"""
        signals = generate_stock_signals(self.market_bear, ["NVDA", "MSFT"], self.price_bear)
        for s in signals:
            self.assertEqual(s["signal"], "AVOID")

    def test_signal_has_fields(self):
        """信号应包含所需字段"""
        signals = generate_stock_signals(self.market_bull, ["NVDA"], self.price_bull)
        for s in signals:
            self.assertIn("symbol", s)
            self.assertIn("signal", s)
            self.assertIn("confidence", s)
            self.assertIn("reason", s)
            self.assertIn("expected_horizon", s)

    def test_signal_valid_values(self):
        """信号值应有效"""
        signals = generate_stock_signals(self.market_bull, ["NVDA"], self.price_bull)
        for s in signals:
            self.assertIn(s["signal"], ["BUY", "WATCH", "AVOID"])
            self.assertGreaterEqual(s["confidence"], 0.0)
            self.assertLessEqual(s["confidence"], 1.0)

    def test_confidence_in_range(self):
        """confidence 应在 0~1 之间"""
        signals = generate_stock_signals(self.market_bear, ["NVDA"], self.price_bear)
        for s in signals:
            self.assertGreaterEqual(s["confidence"], 0.0)
            self.assertLessEqual(s["confidence"], 1.0)

    def test_reason_non_empty(self):
        """reason 应非空"""
        signals = generate_stock_signals(self.market_bull, ["NVDA"], self.price_bull)
        for s in signals:
            self.assertGreater(len(s["reason"]), 0)

    def test_file_output(self):
        """应生成 JSON 文件"""
        today = __import__("datetime").date.today().isoformat().replace("-", "")
        report_file = Path(__file__).parent.parent / "reports" / f"stock_signals_{today}.json"
        if report_file.exists():
            os.unlink(report_file)
        signals = generate_stock_signals(self.market_bull, ["NVDA"], self.price_bull)
        self.assertTrue(report_file.exists())


if __name__ == "__main__":
    unittest.main()