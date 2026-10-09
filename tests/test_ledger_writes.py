"""账本不该每轮都整份重写。

活跃时采集器每 30 秒跑一轮。以前账本（约 1 MB）每轮都被认为「变了」而重写：
过了保留期的天落盘时裁掉来源明细、下一轮又加回来；来源「先减后加」差一个浮点末位；
同总量的更新（模型名规范化、补上速度字段）落盘时又被「只收更大的数」挡掉，永远收敛不了。
"""
import os
import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from test_codex_limits import USAGE as U


class LedgerWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "ledger.json"
        patch = mock.patch.object(U, "_LEDGER_FILE", str(self.path))
        patch.start()
        self.addCleanup(patch.stop)
        self.reset()
        self.addCleanup(self.reset)
        self.today = date.today().isoformat()

    def reset(self):
        U._LEDGER_CACHE.update(data=None, dirty=False, urgent=False)

    def flush_and_reload(self):
        U.ledger_flush()
        self.reset()
        return U._load_ledger()

    def test_a_change_to_today_only_waits_for_the_next_interval(self):
        U.ledger_reconcile("grok", {self.today: {"in": 10}})
        U.ledger_flush()
        written = self.path.stat().st_mtime_ns

        U.ledger_reconcile("grok", {self.today: {"in": 20}})
        U.ledger_flush()
        self.assertEqual(self.path.stat().st_mtime_ns, written, "只改了今天，十分钟内不重写")

        old = time.time() - U._LEDGER_TODAY_FLUSH_INTERVAL - 1
        os.utime(self.path, (old, old))
        U.ledger_reconcile("grok", {self.today: {"in": 30}})
        self.assertEqual(self.flush_and_reload()["tools"]["grok"][self.today]["in"], 30)

    def test_a_change_to_a_past_day_is_written_at_once(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        U.ledger_reconcile("grok", {self.today: {"in": 10}})
        U.ledger_flush()
        U.ledger_reconcile("grok", {self.today: {"in": 10}, yesterday: {"in": 5}})
        self.assertEqual(self.flush_and_reload()["tools"]["grok"][yesterday]["in"], 5)

    def test_days_past_source_retention_settle_after_one_write(self):
        old_day = (date.today() - timedelta(days=U._LEDGER_SOURCES_RETAIN_DAYS + 5)).isoformat()
        day = {"in": 100, "cost": 0.1 + 0.2}
        U.ledger_reconcile("claude", {old_day: day}, {"a": {old_day: day}, "b": {old_day: {"in": 0}}})
        self.flush_and_reload()   # 落盘时裁掉了 _sources
        U.ledger_reconcile("claude", {old_day: day}, {"a": {old_day: day}, "b": {old_day: {"in": 0}}})
        self.assertFalse(U._LEDGER_CACHE["dirty"], "只差来源明细或浮点末位，不算改动")

    def test_an_equal_total_update_is_persisted_so_it_stops_changing(self):
        U.ledger_reconcile("hermes", {self.today: {"in": 10, "models": {"grok-4.3": {"in": 10}}}})
        self.flush_and_reload()
        renamed = {"in": 10, "models": {"x-ai/grok-4.3": {"in": 10}}}
        U.ledger_reconcile("hermes", {self.today: renamed})
        U._LEDGER_CACHE["urgent"] = True
        stored = self.flush_and_reload()["tools"]["hermes"][self.today]
        self.assertEqual(stored["models"], renamed["models"], "总量一样也要写进去")
        U.ledger_reconcile("hermes", {self.today: renamed})
        self.assertFalse(U._LEDGER_CACHE["dirty"])

    def test_floats_differing_in_the_last_bit_are_the_same_day(self):
        self.assertTrue(U._ledger_same({"cost": 9.181908201215737}, {"cost": 9.181908201215736}))
        self.assertFalse(U._ledger_same({"cost": 9.18}, {"cost": 9.19}))
        self.assertTrue(U._ledger_same({"in": 1, "_sources": {"a": 1}}, {"in": 1}, ("_sources",)))


if __name__ == "__main__":
    unittest.main()
