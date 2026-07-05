# -*- coding: utf-8 -*-
"""市场洞察测试 — build_market_summary 的只读测试。"""

from __future__ import annotations
import sys, unittest, os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.ai.market_intelligence import build_market_summary


class TestMarketIntelligence(unittest.TestCase):
    def setUp(self):
        self.price_data_bull = {
            "SPY": [500.0, 505.0, 510.0, 515.0, 520.0],
            "QQQ": [400.0, 405.0, 410.0, 415.0, 420.0],
            "NVDA": [800.0, 820.0, 830.0, 850.0, 870.0],
            "MSFT": [300.0, 305.0, 310.0, 315.0, 320.0],
            "META": [200.0, 202.0, 205.0, 208.0, 210.0],
            "AMD": [150.0, 152.0, 155.0, 158.0, 160.0],
            "TSM": [100.0, 102.0, 104.0, 106.0, 108.0],
            "AVGO": [500.0, 510.0, 520.0, 530.0, 540.0],
            "PLTR": [50.0, 51.0, 52.0, 53.0, 54.0],
            "CRM": [200.0, 202.0, 204.0, 206.0, 208.0],
            "XLE": [80.0, 81.0, 82.0, 83.0, 84.0],
        }

    def test_empty_no_crash(self):
        """空数据不崩溃"""
        r = build_market_summary({})
        self.assertIn("date", r)
        self.assertIn("market_trend", r)
        self.assertIn("sector_strength", r)
        self.assertIn("key_drivers", r)
        self.assertIn("risk_level", r)

    def test_market_trend_bullish(self):
        """上涨数据应判断为 bullish"""
        r = build_market_summary(self.price_data_bull)
        self.assertEqual(r["market_trend"], "bullish")

    def test_market_trend_bearish(self):
        """下跌数据应判断为 bearish"""
        bear_data = {k: [v[0], v[0]*0.98, v[0]*0.96, v[0]*0.94, v[0]*0.92] for k, v in self.price_data_bull.items()}
        r = build_market_summary(bear_data)
        self.assertEqual(r["market_trend"], "bearish")

    def test_sector_strength_has_keys(self):
        """sector_strength 应包含所有行业"""
        r = build_market_summary(self.price_data_bull)
        for sector in ("ai", "semiconductors", "software", "energy"):
            self.assertIn(sector, r["sector_strength"])

    def test_key_drivers_non_empty(self):
        """key_drivers 应非空"""
        r = build_market_summary(self.price_data_bull)
        self.assertGreater(len(r["key_drivers"]), 0)

    def test_risk_level_valid(self):
        """risk_level 应有效"""
        r = build_market_summary(self.price_data_bull)
        self.assertIn(r["risk_level"], ["low", "medium", "high"])

    def test_file_output(self):
        """应生成 JSON 文件"""
        today = __import__("datetime").date.today().isoformat().replace("-", "")
        report_file = Path(__file__).parent.parent / "reports" / f"market_intelligence_{today}.json"
        if report_file.exists():
            os.unlink(report_file)
        r = build_market_summary(self.price_data_bull)
        self.assertTrue(report_file.exists())


if __name__ == "__main__":
    unittest.main()