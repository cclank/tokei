"""Antigravity cycle attribution, retention and forecasts use synthetic data only."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from test_codex_limits import USAGE


class AntigravityQuotaCycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1_800_000_000
        for name, file in [("_QUOTA_ANCHOR_FILE", "cycles.json"),
                           ("_ANTIGRAVITY_QUOTA_USAGE_FILE", "events.json")]:
            patcher = mock.patch.object(USAGE, name, str(Path(self.tmp.name) / file))
            patcher.start(); self.addCleanup(patcher.stop)

    def event(self, identity, amount=100, model="gemini-flash-worker-agy", offset=-60):
        return {"id": identity, "timestamp": datetime.fromtimestamp(self.now + offset, timezone.utc).isoformat(),
                "model": model, "tokens": {"input": amount, "output": 20, "cached": amount // 2, "thoughts": 5}}

    def cache(self, events, signature="one"):
        entry = {"sid": "ag-session", "rank": 3, "v": USAGE._GEMINI_PARSE_VERSION,
                 "sig": signature, "updated": "2027-01-15", "mtime": 1, "events": events}
        return {"gemini": {"/synthetic/conversations/session.db": entry}}

    def payload(self, argon=False):
        windows = [
            {"id": "antigravity-gemini-weekly", "used_pct": 10, "reset": self.now + 6 * 86400 + 23 * 3600},
            {"id": "antigravity-gemini-5h", "used_pct": 40, "reset": self.now + 4 * 3600},
            {"id": "antigravity-3p-weekly", "used_pct": 20, "reset": self.now + 6 * 86400 + 23 * 3600},
            {"id": "antigravity-3p-5h", "used_pct": 80, "reset": self.now + 4 * 3600},
        ]
        if argon:
            windows.append({"id": "antigravity-gemini-argon-weekly", "used_pct": 30,
                            "reset": self.now + 6 * 86400 + 23 * 3600})
        return {"antigravity": {"available": True, "stale": False, "windows": windows}}

    def cycles(self, payload, cache):
        devices = [(USAGE._QUOTA_SELF_DEVICE, {}, None, {})]
        with mock.patch.object(USAGE, "_quota_detail_inputs", return_value=(payload, cache)), \
             mock.patch.object(USAGE, "_quota_device_ledgers", return_value=(devices, [])), \
             mock.patch.object(USAGE, "datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime.fromtimestamp(self.now, timezone.utc)
            result = USAGE.build_quota_detail()
        return {cycle["window_id"]: cycle for cycle in result["cycles"] if cycle["tool"] == "antigravity"}

    def test_gemini_cli_and_duplicate_db_copies_are_excluded(self):
        events = [self.event("ag"), self.event("claude", 200, "claude-sonnet-4-6")]
        cache = self.cache(events)
        entry = next(iter(cache["gemini"].values()))
        cache["gemini"]["/copied/session.db"] = dict(entry, mtime=2)
        cache["gemini"]["/gemini/chats/cli.jsonl"] = dict(entry, rank=2, sid="cli", events=[self.event("cli", 9_000_000)])
        cycles = self.cycles(self.payload(), cache)
        self.assertEqual(len(cycles), 2)
        for key in ("antigravity-gemini-weekly",):
            self.assertEqual(cycles[key]["tokens"], 125, "cached tokens are already part of input")
            self.assertEqual(cycles[key]["usage_scope"], "local")
            self.assertTrue(cycles[key]["projection_available"])
        self.assertEqual(cycles["antigravity-3p-weekly"]["tokens"], 225)
        self.assertEqual(cycles["antigravity-gemini-weekly"]["used_pct"], 10)
        self.assertNotIn("antigravity-gemini-5h", cycles)
        self.assertNotIn("antigravity-3p-5h", cycles)
        self.assertTrue(all(cycle["window"] == "week" for cycle in cycles.values()))

    def test_explicit_argon_pool_is_not_double_counted_as_shared_gemini(self):
        cache = self.cache([self.event("worker"), self.event("argon", 200, "gemini-pro-orchestrator-g1-pro")])
        cycles = self.cycles(self.payload(argon=True), cache)
        self.assertEqual(cycles["antigravity-gemini-weekly"]["tokens"], 125)
        self.assertEqual(cycles["antigravity-gemini-argon-weekly"]["tokens"], 225)
        self.assertEqual(sum(cycles[key]["tokens"] for key in ("antigravity-gemini-weekly", "antigravity-gemini-argon-weekly")), 350)

    def test_deleted_logs_retain_usage_and_current_prices_are_reapplied(self):
        cache = self.cache([self.event("one")])
        first = self.cycles(self.payload(), cache)
        with mock.patch.object(USAGE, "_gemini_event_cost", return_value=.42):
            after = self.cycles(self.payload(), {})
        key = "antigravity-gemini-weekly"
        self.assertEqual(first[key]["tokens"], after[key]["tokens"])
        self.assertEqual(after[key]["cost"], .42)
        saved = json.loads(Path(USAGE._ANTIGRAVITY_QUOTA_USAGE_FILE).read_text())
        self.assertEqual(len(saved["events"]), 1)
        self.assertNotIn("/synthetic", json.dumps(saved), "retain metrics, not source paths or conversation text")

    def test_cycle_boundaries_and_now_are_exact(self):
        cache = self.cache([self.event("before", offset=-3601), self.event("start", offset=-3600),
                            self.event("now", offset=0), self.event("future", offset=1)])
        cycles = self.cycles(self.payload(), cache)
        self.assertEqual(cycles["antigravity-gemini-weekly"]["tokens"], 250)

    def test_stale_unknown_and_expired_readings_do_not_become_live_forecasts(self):
        cache = self.cache([self.event("one")])
        payload = self.payload()
        self.cycles(payload, cache)
        payload["antigravity"]["stale"] = True
        cycles = self.cycles(payload, cache)
        self.assertTrue(all(cycle["used_pct"] is None for cycle in cycles.values()))
        self.assertTrue(all(not cycle["projection_available"] for cycle in cycles.values()))
        self.assertEqual(cycles["antigravity-gemini-weekly"]["tokens"], 125)
        payload["antigravity"]["stale"] = False
        for window in payload["antigravity"]["windows"]:
            window["reset"] = self.now
        self.assertEqual(USAGE._quota_antigravity_readings(payload, self.now), {})
        payload = self.payload()
        for window in payload["antigravity"]["windows"]:
            window["usage_known"] = False
        self.assertEqual(USAGE._quota_antigravity_readings(payload, self.now), {})

    def test_unassigned_models_keep_approximate_forecasts_for_known_usage(self):
        cache = self.cache([self.event("known"), self.event("unknown", model="unassigned")])
        cycles = self.cycles(self.payload(), cache)
        self.assertEqual(cycles["antigravity-gemini-weekly"]["tokens"], 125)
        self.assertTrue(cycles["antigravity-gemini-weekly"]["projection_available"])
        self.assertTrue(cycles["antigravity-gemini-weekly"]["approx"])

    def test_zero_token_unknown_record_does_not_disable_other_pools(self):
        empty = self.event("zero", 0, "unknown")
        empty["tokens"].update(output=0, thoughts=0)
        cycles = self.cycles(self.payload(), self.cache([self.event("known"), empty]))
        self.assertEqual(cycles["antigravity-gemini-weekly"]["tokens"], 125)
        self.assertTrue(cycles["antigravity-gemini-weekly"]["projection_available"])
        self.assertFalse(cycles["antigravity-gemini-weekly"]["approx"])

    def test_small_positive_weekly_usage_is_ready_for_direct_projection(self):
        payload = self.payload()
        payload["antigravity"]["windows"][0]["used_pct"] = .5
        cycles = self.cycles(payload, self.cache([self.event("known")]))
        self.assertEqual(cycles["antigravity-gemini-weekly"]["used_pct"], .5)
        self.assertTrue(cycles["antigravity-gemini-weekly"]["projection_available"])

    def test_delayed_snapshot_cannot_replace_a_newer_event_but_can_backfill_missing_ids(self):
        latest = self.cache([self.event("same", 200)], "latest")["gemini"]
        next(iter(latest.values()))["mtime"] = 2
        USAGE._remember_antigravity_quota_usage(latest, self.now)
        older = self.cache([self.event("same", 100), self.event("backfill", 300)], "older")["gemini"]
        rows = USAGE._remember_antigravity_quota_usage(older, self.now)
        self.assertEqual(sorted(row[2] for row in rows.values()), [200, 300])

    def test_newer_source_corrections_can_reduce_an_event_without_double_counting(self):
        original = self.cache([self.event("same", 200)], "original")["gemini"]
        USAGE._remember_antigravity_quota_usage(original, self.now)
        corrected = self.cache([self.event("same", 100)], "corrected")["gemini"]
        next(iter(corrected.values()))["mtime"] = 2
        rows = USAGE._remember_antigravity_quota_usage(corrected, self.now)
        self.assertEqual(len(rows), 1)
        self.assertEqual(next(iter(rows.values()))[2], 100)


if __name__ == "__main__":
    unittest.main()
