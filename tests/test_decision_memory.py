# -*- coding: utf-8 -*-
"""决策记忆层测试 — DecisionMemory 的只读测试。"""

from __future__ import annotations
import sys, unittest, json, os
from pathlib import Path
from tempfile import NamedTemporaryFile

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from northstar.data.decision_memory import DecisionMemory


class TestDecisionMemory(unittest.TestCase):
    def setUp(self):
        """每个测试前创建临时文件。"""
        self.tmp = NamedTemporaryFile(delete=False, suffix=".json", mode="w")
        json.dump([], self.tmp)
        self.tmp.close()
        self.dm = DecisionMemory(self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_empty_no_crash(self):
        """空数据不崩溃"""
        self.assertEqual(self.dm.count(), 0)

    def test_record_returns_id(self):
        """record 应返回 ID"""
        eid = self.dm.record("AAPL", "BUY", price=150.0, reason="momentum signal")
        self.assertIsInstance(eid, int)
        self.assertGreater(eid, 0)

    def test_record_increments_count(self):
        """记录应该增加计数"""
        self.dm.record("AAPL", "BUY", price=150.0)
        self.dm.record("MSFT", "SELL", price=300.0)
        self.assertEqual(self.dm.count(), 2)

    def test_get_all_returns_all(self):
        """get_all 返回所有记录"""
        self.dm.record("AAPL", "BUY", price=150.0)
        self.dm.record("MSFT", "SELL", price=300.0)
        all_entries = self.dm.get_all()
        self.assertEqual(len(all_entries), 2)

    def test_get_recent_order(self):
        """get_recent 返回最近 n 条"""
        for i in range(5):
            self.dm.record("AAPL", "BUY", price=100.0 + i)
        recent = self.dm.get_recent(3)
        self.assertEqual(len(recent), 3)
        # 最近的应该在前
        self.assertGreater(recent[0]["price"], recent[-1]["price"])

    def test_by_symbol(self):
        """按 symbol 筛选正确"""
        self.dm.record("AAPL", "BUY", price=150.0)
        self.dm.record("MSFT", "BUY", price=300.0)
        aapl = self.dm.by_symbol("aapl")
        self.assertEqual(len(aapl), 1)
        self.assertEqual(aapl[0]["symbol"], "AAPL")

    def test_by_action(self):
        """按 action 筛选正确"""
        self.dm.record("AAPL", "BUY", price=150.0)
        self.dm.record("AAPL", "SELL", price=160.0)
        buys = self.dm.by_action("BUY")
        sells = self.dm.by_action("SELL")
        self.assertEqual(len(buys), 1)
        self.assertEqual(len(sells), 1)

    def test_by_source(self):
        """按 source 筛选正确"""
        self.dm.record("AAPL", "BUY", price=150.0, source="v37")
        self.dm.record("MSFT", "BUY", price=300.0, source="v40")
        v37 = self.dm.by_source("v37")
        self.assertEqual(len(v37), 1)

    def test_by_date_range(self):
        """按日期范围筛选正确"""
        # 使用固定日期
        self.dm.record("AAPL", "BUY", price=150.0)
        all_entries = self.dm.get_all()
        today = all_entries[0]["timestamp"][:10]
        result = self.dm.by_date_range(today, today)
        self.assertGreaterEqual(len(result), 1)

    def test_count_by_action(self):
        """count_by_action 统计正确"""
        self.dm.record("AAPL", "BUY", price=150.0)
        self.dm.record("MSFT", "SELL", price=300.0)
        self.dm.record("GOOG", "HOLD", price=200.0)
        counts = self.dm.count_by_action()
        self.assertEqual(counts.get("BUY"), 1)
        self.assertEqual(counts.get("SELL"), 1)
        self.assertEqual(counts.get("HOLD"), 1)

    def test_update_pnl(self):
        """update_pnl 正确更新"""
        eid = self.dm.record("AAPL", "BUY", price=150.0)
        ok = self.dm.update_pnl(eid, 5.5)
        self.assertTrue(ok)
        entry = self.dm.by_symbol("AAPL")[0]
        self.assertEqual(entry["pnl"], 5.5)

    def test_get_backtest_snapshot(self):
        """get_backtest_snapshot 返回正确结构"""
        self.dm.record("AAPL", "BUY", price=150.0, strategy_type="momentum")
        self.dm.record("AAPL", "HOLD", price=150.0)  # HOLD 应被排除
        snapshot = self.dm.get_backtest_snapshot()
        self.assertEqual(len(snapshot), 1)
        self.assertIn("symbol", snapshot[0])
        self.assertIn("action", snapshot[0])
        self.assertIn("price", snapshot[0])
        self.assertIn("date", snapshot[0])

    def test_delete_by_id(self):
        """delete_by_id 正确删除"""
        eid = self.dm.record("AAPL", "BUY", price=150.0)
        self.assertEqual(self.dm.count(), 1)
        ok = self.dm.delete_by_id(eid)
        self.assertTrue(ok)
        self.assertEqual(self.dm.count(), 0)

    def test_clear(self):
        """clear 清空所有记录"""
        self.dm.record("AAPL", "BUY", price=150.0)
        self.dm.clear()
        self.assertEqual(self.dm.count(), 0)


if __name__ == "__main__":
    unittest.main()