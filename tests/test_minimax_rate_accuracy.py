"""MiniMax request matching, generation timing and durable cache upgrades."""
import copy
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from test_codex_limits import USAGE as U
from test_minimax import MiniMaxHome


class MiniMaxRateAccuracyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="tokei-minimax-rate-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = MiniMaxHome(self.root / "v2")
        self.start = int(datetime.now().replace(hour=8, minute=0, second=0,
                                                microsecond=0).timestamp() * 1000)
        self.day = datetime.fromtimestamp(self.start / 1000).date().isoformat()
        with sqlite3.connect(self.home.db) as connection:
            connection.execute("""CREATE TABLE local_runtime_message_rows (
                id INTEGER PRIMARY KEY, session_id TEXT, turn_id TEXT,
                role TEXT, created_at_ms INTEGER, data_json TEXT)""")
        for patcher in (
            mock.patch.object(U, "MINIMAX_DB_PATHS", [str(self.home.db)]),
            mock.patch.object(U, "_LEDGER_FILE", str(self.root / "ledger.json")),
            mock.patch.object(U, "_LEDGER_TODAY_FLUSH_INTERVAL", 0),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(lambda: U._LEDGER_CACHE.update(data=None, dirty=False, urgent=False))

    def message(self, session="s", turn="t", *, end=12, out=600, usage=None,
                raw=None, role="assistant", **timing):
        if usage is None:
            usage = {"input_tokens": 100, "output_tokens": out, "cache_read": 0}
        usage = dict(usage, **timing)
        data = json.dumps({"usage": usage}) if raw is None else raw
        with sqlite3.connect(self.home.db) as connection:
            connection.execute("INSERT INTO local_runtime_message_rows "
                               "(session_id, turn_id, role, created_at_ms, data_json) "
                               "VALUES (?, ?, ?, ?, ?)",
                               (session, turn, role, self.start + end * 1000, data))

    def request(self, session="s", turn="t", *, start=0, out=600, end=12,
                usage=None, **timing):
        self.home.usage(session, turn, ts=self.start + start * 1000, out=out,
                        model="MiniMax-M3")
        self.message(session, turn, out=out, end=end, usage=usage, **timing)

    def raw(self):
        days, *_ = U._scan_minimax_database(str(self.home.db), {}, [], 0)
        day = days[self.day]
        return U._perf_summary(day.get("perf")), day

    def scan(self, cache=None):
        result = U.scan_minimax(U.range_bounds(), {} if cache is None else cache)
        day = result["ranges"]["all"]
        return U._perf_summary(day.get("perf")), day

    def test_multiple_model_calls_in_one_turn_use_their_own_timing(self):
        self.request(out=100, decode_duration_ms=2000, request_duration_ms=3000)
        # A minute of tool execution between calls must not enter generation time.
        self.request(start=72, end=90, out=500,
                     decode_duration_ms=10000, request_duration_ms=12000)
        perf, day = self.raw()
        self.assertIsNotNone(perf)
        self.assertEqual((perf["o"], perf["g"], perf["n"], perf["tps"]), (600, 12, 2, 50))
        self.assertEqual((perf["en"], perf["tn"]), (0, 2))
        self.assertEqual(U.token_total(day), 800)

    def test_session_identity_prevents_turn_id_collisions(self):
        self.request(session="a", decode_duration_ms=10000, request_duration_ms=12000)
        self.request(session="b", decode_duration_ms=20000, request_duration_ms=22000)
        perf, _ = self.raw()
        self.assertIsNotNone(perf)
        self.assertEqual((perf["o"], perf["g"], perf["n"]), (1200, 30, 2))

    def test_recorded_generation_time_ignores_delayed_message_persistence(self):
        self.request(end=60, decode_duration_ms=10000, request_duration_ms=12000)
        perf, _ = self.raw()
        self.assertEqual((perf["g"], perf["tps"], perf["en"]), (10, 60, 0))
        self.assertAlmostEqual(perf["ttft"], 2, delta=0.05)

    def test_recorded_total_without_decode_time_is_marked_including_wait(self):
        self.request(end=60, request_duration_ms=12000)
        perf, _ = self.raw()
        self.assertEqual((perf["g"], perf["tps"], perf["en"]), (12, 50, 1))
        self.assertIsNone(perf["ttft"])

    def test_decode_time_without_total_still_supports_generation_speed(self):
        self.request(end=60, decode_duration_ms=10000)
        perf, _ = self.raw()
        self.assertEqual((perf["g"], perf["tps"], perf["en"]), (10, 60, 0))
        self.assertIsNone(perf["ttft"])

    def test_legacy_timestamps_are_marked_including_wait(self):
        self.request(end=30, usage={})
        perf, _ = self.raw()
        self.assertEqual((perf["g"], perf["tps"], perf["en"]), (30, 20, 1))
        self.assertIsNone(perf["ttft"])

    def test_legacy_multi_call_persistence_is_not_mistaken_for_model_completion(self):
        self.request(out=200, end=10)
        self.request(start=100, out=600, end=112)
        perf, day = self.raw()
        self.assertIsNone(perf)
        self.assertEqual(U.token_total(day), 1000)

    def test_multiple_calls_with_only_request_totals_still_exclude_tool_time(self):
        self.request(out=200, end=90, request_duration_ms=10000)
        self.request(start=100, out=600, end=200, request_duration_ms=12000)
        perf, _ = self.raw()
        self.assertEqual((perf["o"], perf["g"], perf["n"], perf["en"]), (800, 22, 2, 2))

    def test_legacy_tool_completion_is_not_used_as_model_end_time(self):
        self.home.usage("s", "t", ts=self.start, out=600, model="MiniMax-M3")
        self.message(end=60, raw=json.dumps({
            "usage": {"input_tokens": 100, "output_tokens": 600},
            "tool_calls": [{"tool_call_id": "fixture", "status": "completed"}],
        }))
        perf, day = self.raw()
        self.assertIsNone(perf)
        self.assertEqual(U.token_total(day), 700)

    def test_recorded_timing_remains_valid_when_completion_waited_for_tools(self):
        self.home.usage("s", "t", ts=self.start, out=600, model="MiniMax-M3")
        self.message(end=60, raw=json.dumps({
            "usage": {"input_tokens": 100, "output_tokens": 600,
                      "decode_duration_ms": 10000, "request_duration_ms": 12000},
            "tool_calls": [{"tool_call_id": "fixture", "status": "completed"}],
        }))
        perf, _ = self.raw()
        self.assertEqual((perf["g"], perf["tps"], perf["en"]), (10, 60, 0))

    def test_aggregate_turn_usage_is_not_paired_with_individual_calls(self):
        self.home.usage("s", "t", ts=self.start, inp=200, out=600, model="MiniMax-M3")
        self.message(out=100, decode_duration_ms=2000)
        self.message(out=500, end=30, decode_duration_ms=10000)
        perf, day = self.raw()
        self.assertIsNone(perf)
        self.assertEqual(U.token_total(day), 800)

    def test_token_mismatch_does_not_fall_back_to_an_unrelated_message(self):
        self.home.usage("s", "t", ts=self.start, out=600, model="MiniMax-M3")
        self.message(out=900, decode_duration_ms=10000, request_duration_ms=12000)
        self.assertIsNone(self.raw()[0])

    def test_legacy_messages_without_token_fingerprints_are_not_guessed_in_multi_call_turns(self):
        self.request(out=100, usage={}, decode_duration_ms=1000)
        self.request(out=500, usage={}, decode_duration_ms=10000)
        self.assertIsNone(self.raw()[0])

    def test_repeated_token_counts_can_use_non_overlapping_request_windows(self):
        self.request(end=12, decode_duration_ms=10000, request_duration_ms=12000)
        self.request(start=100, end=122, decode_duration_ms=20000, request_duration_ms=22000)
        perf, _ = self.raw()
        self.assertIsNotNone(perf)
        self.assertEqual((perf["o"], perf["g"], perf["n"]), (1200, 30, 2))

    def test_overlapping_identical_requests_are_not_guessed(self):
        self.request(end=12, decode_duration_ms=10000, request_duration_ms=12000)
        self.request(start=5, end=17, decode_duration_ms=10000, request_duration_ms=12000)
        self.assertIsNone(self.raw()[0])

    def test_a_message_is_never_reused_for_duplicate_usage_rows(self):
        self.request(decode_duration_ms=10000, request_duration_ms=12000)
        self.home.usage("s", "t", ts=self.start, out=600, model="MiniMax-M3")
        self.assertIsNone(self.raw()[0])

    def test_malformed_json_does_not_discard_other_valid_request_timings(self):
        self.request(turn="bad", out=100)
        with sqlite3.connect(self.home.db) as connection:
            connection.execute("UPDATE local_runtime_message_rows SET data_json='{' WHERE turn_id='bad'")
        self.request(turn="ok", decode_duration_ms=10000, request_duration_ms=12000)
        perf, day = self.raw()
        self.assertIsNotNone(perf)
        self.assertEqual((perf["n"], perf["o"], perf["g"]), (1, 600, 10))
        self.assertEqual(U.token_total(day), 900)

    def test_invalid_timing_values_cannot_inflate_generation_speed(self):
        for value in (True, -1, 10 ** 400, "10000", {}, []):
            with self.subTest(value=value):
                with sqlite3.connect(self.home.db) as connection:
                    connection.execute("DELETE FROM local_runtime_token_usage")
                    connection.execute("DELETE FROM local_runtime_message_rows")
                self.request(end=60, decode_duration_ms=value, request_duration_ms=12000)
                perf, _ = self.raw()
                self.assertEqual((perf["g"], perf["tps"], perf["en"]), (12, 50, 1))

    def test_non_finite_json_timing_does_not_discard_other_valid_requests(self):
        self.request(turn="nan", decode_duration_ms=float("nan"), request_duration_ms=12000)
        self.request(turn="infinity", decode_duration_ms=float("inf"), request_duration_ms=12000)
        self.request(turn="ok", decode_duration_ms=10000, request_duration_ms=12000)
        perf, _ = self.raw()
        self.assertEqual((perf["g"], perf["tps"], perf["n"]), (10, 60, 1))

    def test_inconsistent_durations_use_total_and_mark_wait(self):
        self.request(end=60, decode_duration_ms=15000, request_duration_ms=12000)
        perf, _ = self.raw()
        self.assertEqual((perf["g"], perf["en"]), (12, 1))
        self.assertIsNone(perf["ttft"])

    def test_outlier_generation_timing_is_filtered_without_switching_basis(self):
        self.request(decode_duration_ms=5, request_duration_ms=12000)
        self.assertIsNone(self.raw()[0])

    def test_long_wait_does_not_reduce_valid_generation_speed(self):
        self.request(end=240, decode_duration_ms=10000, request_duration_ms=210000)
        perf, _ = self.raw()
        self.assertEqual((perf["g"], perf["tps"], perf["en"], perf["tn"]), (10, 60, 0, 0))

    def test_reading_timings_does_not_modify_the_database(self):
        self.request(decode_duration_ms=10000, request_duration_ms=12000)
        before = self.home.db.read_bytes()
        self.raw()
        self.assertEqual(self.home.db.read_bytes(), before)

    def test_parser_upgrade_replaces_cached_and_persisted_rates_once(self):
        self.request(out=100, decode_duration_ms=2000, request_duration_ms=3000)
        self.request(start=72, end=90, out=500,
                     decode_duration_ms=10000, request_duration_ms=12000)
        old_day = {"in": 200, "out": 600, "cr": 0, "cw": 0, "reason": 0,
                   "cost": 0, "models": {}, "hours": [0] * 24, "sessions": ["s"],
                   "_cost_version": 2,
                   "perf": {"minimax/minimax-m3": {"o": 100, "g": 90, "n": 1}}}
        key = "db:" + str(self.home.db.resolve())
        cache = {"minimax": {key: {"version": 2, "sig": U._sqlite_signature(str(self.home.db)),
                                    "days": {self.day: copy.deepcopy(old_day)}, "logs": {},
                                    "runs": [[1, "MiniMax-M3"]], "through": 2}}}
        U.ledger_reconcile("minimax", {self.day: old_day})
        U.ledger_flush()
        U._LEDGER_CACHE.update(data=None, dirty=False, urgent=False)
        perf, result = self.scan(cache)
        self.assertEqual((perf["tps"], perf["o"], perf["g"], perf["n"]), (50, 600, 12, 2))
        self.assertEqual(U.token_total(result), 800)
        self.assertEqual(cache["minimax"][key]["runs"], [[1, "MiniMax-M3"]])
        U.ledger_flush()
        U._LEDGER_CACHE.update(data=None, dirty=False, urgent=False)
        self.assertEqual(self.scan(cache)[0], perf)

    def test_rate_parser_upgrade_preserves_archived_tokens_after_partial_cleanup(self):
        self.request(decode_duration_ms=10000, request_duration_ms=12000)
        archived = {"in": 1000, "out": 6000, "cr": 0, "cw": 0, "reason": 0,
                    "cost": 1, "_cost_version": 2, "sessions": ["old"], "hours": [0] * 24}
        U.ledger_reconcile("minimax", {self.day: archived})
        U.ledger_flush()
        U._LEDGER_CACHE.update(data=None, dirty=False, urgent=False)
        _, result = self.scan()
        self.assertEqual(U.token_total(result), 7000)
        self.assertEqual(result["cost"], 1)


if __name__ == "__main__":
    unittest.main()
