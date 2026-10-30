import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from test_codex_limits import USAGE


def _ts(dt):
    return dt.astimezone().isoformat().replace("+00:00", "Z")


class CopilotScanTests(unittest.TestCase):
    def _write_session(self, root, sid, start_iso, shutdown_data):
        session_dir = Path(root) / "session-state" / sid
        session_dir.mkdir(parents=True)
        events = [
            {"type": "session.start", "data": {
                "sessionId": sid,
                "startTime": start_iso,
                "context": {"cwd": "/tmp/copilot-project"},
            }},
            {"type": "assistant.message", "data": {"content": "PRIVATE_COPILOT_TEST_SENTINEL"}},
            {"type": "session.shutdown", "data": shutdown_data},
        ]
        path = session_dir / "events.jsonl"
        path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
        return path

    def scan(self, root, cache=None):
        scan_cache = cache if cache is not None else {"v": USAGE._SCAN_CACHE_VERSION}
        aliases = ("COPILOT_DIR", "COPILOT_CLI_DIR", "GITHUB_COPILOT_DIR",
                   "COPILOT_HOME", "GITHUB_COPILOT_HOME")
        env = ("TOKEI_COPILOT_DIR", "TOKEI_COPILOT_CLI_DIR", "COPILOT_HOME",
               "GITHUB_COPILOT_HOME", "TOKEI_COPILOT_HOME")
        with mock.patch.multiple(USAGE, **{key: str(root) for key in aliases}), \
             mock.patch.dict(os.environ, {key: str(root) for key in env}):
            return USAGE.scan_copilot(USAGE.range_bounds(), scan_cache), scan_cache

    def _shutdown(self, premium=2):
        return {
            "sessionStartTime": _ts(datetime.now(timezone.utc)),
            "totalPremiumRequests": premium,
            "modelMetrics": {"gpt-5-mini": {"usage": {
                "inputTokens": 100, "outputTokens": 20, "reasoningTokens": 7}}},
        }

    def test_mirrored_jsonl_counts_once_in_ranges_and_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = self._shutdown()
            path = self._write_session(tmp, "same", data["sessionStartTime"], data)
            (Path(tmp) / "mirror.jsonl").write_bytes(path.read_bytes())
            result, cache = self.scan(tmp)
            self.assertEqual(result["ranges"]["all"]["out"], 13)
            self.assertEqual(result["ranges"]["all"]["sessions"], {"same"})
            hits = list(USAGE._project_contributions(cache))
            self.assertEqual(sum(hit["tokens"] for hit in hits), 20)
            self.assertEqual(result["ranges"]["all"]["credits"], 2)
            self.assertNotIn("PRIVATE_COPILOT_TEST_SENTINEL", json.dumps(cache))
            cache = json.loads(json.dumps(cache))
            again, _ = self.scan(tmp, cache)
            self.assertEqual(again["ranges"]["all"]["out"], 13)

    def test_identified_partial_mirrors_union_distinct_equal_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = self._shutdown()
            path = self._write_session(tmp, "same", data["sessionStartTime"], data)
            start = json.loads(path.read_text().splitlines()[0])
            def write(file, ids):
                records = [start] + [{"id": event_id, "type": "session.shutdown", "data": data}
                                     for event_id in ids]
                file.write_text("\n".join(json.dumps(item) for item in records) + "\n")
            write(path, ["request-1", "request-2", "request-2"])
            write(Path(tmp) / "mirror.jsonl", ["request-1", "request-3"])
            result, cache = self.scan(tmp)
            self.assertEqual(result["ranges"]["all"]["out"], 39)
            self.assertEqual(result["ranges"]["all"]["out"], 39)
            self.assertEqual(result["ranges"]["all"]["reason"], 21)
            self.assertEqual(result["ranges"]["all"]["credits"], 6)
            self.assertEqual(sum(hit["tokens"] for hit in USAGE._project_contributions(cache)), 60)

    def test_idless_canonical_session_preserves_repeated_equal_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = self._shutdown()
            path = self._write_session(tmp, "same", data["sessionStartTime"], data)
            (Path(tmp) / "short-mirror.jsonl").write_bytes(path.read_bytes())
            with path.open("a") as fh:
                fh.write(json.dumps({"type": "session.shutdown", "data": data}) + "\n")
            result, cache = self.scan(tmp)
            self.assertEqual(result["ranges"]["all"]["out"], 26)
            self.assertEqual(result["ranges"]["all"]["credits"], 4)
            self.assertEqual(sum(hit["tokens"] for hit in USAGE._project_contributions(cache)), 40)

    def test_event_identity_is_scoped_to_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = self._shutdown()
            for sid in ("one", "two"):
                path = self._write_session(tmp, sid, data["sessionStartTime"], data)
                records = [json.loads(line) for line in path.read_text().splitlines()]
                records[-1]["id"] = "same-id-different-session"
                path.write_text("\n".join(json.dumps(item) for item in records) + "\n")
            result, _ = self.scan(tmp)
            self.assertEqual(result["ranges"]["all"]["out"], 26)
            self.assertEqual(result["ranges"]["all"]["sessions"], {"one", "two"})

    def test_invalid_premium_is_finite_nonnegative_and_raw_reasoning_is_normalized(self):
        for premium in ("NaN", "Infinity", -2, 10 ** 1000):
            with self.subTest(premium=str(premium)[:20]), tempfile.TemporaryDirectory() as tmp:
                data = self._shutdown(premium)
                self._write_session(tmp, "one", data["sessionStartTime"], data)
                result, _ = self.scan(tmp)
                day = result["ranges"]["all"]
                self.assertEqual(day["credits"], 0)
                self.assertEqual((day["out"], day["reason"]), (13, 7))
                json.dumps(day["credits"], allow_nan=False)

    def test_sqlite_keeps_each_session_project_and_observes_wal(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "usage.db"
            with closing(sqlite3.connect(db)) as connection:
                connection.executescript("""
                    CREATE TABLE sessions(id TEXT, cwd TEXT);
                    CREATE TABLE assistant_usage_events(
                        session_id TEXT, model TEXT, input_tokens INTEGER,
                        output_tokens INTEGER, cache_read_tokens INTEGER,
                        cache_write_tokens INTEGER, reasoning_tokens INTEGER,
                        created_at TEXT);
                """)
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA wal_autocheckpoint=0")
                ts = _ts(datetime.now(timezone.utc))
                connection.executemany("INSERT INTO sessions VALUES (?, ?)",
                                       [("a", "/synthetic/a"), ("b", "/synthetic/b")])
                connection.executemany("INSERT INTO assistant_usage_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [(sid, "gpt-5-mini", 999, count, 4, 5, 0, ts) for sid, count in (("a", 100), ("b", 200))])
                connection.commit()
                result, cache = self.scan(tmp)
                self.assertEqual(result["ranges"]["all"]["sessions"], {"a", "b"})
                self.assertEqual({hit["path"]: hit["tokens"] for hit in USAGE._project_contributions(cache)},
                                 {"/synthetic/a": 100, "/synthetic/b": 200})
                signature = (db.stat().st_mtime_ns, db.stat().st_size)
                connection.execute("INSERT INTO assistant_usage_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                   ("b", "gpt-5-mini", 999, 300, 4, 5, 0, ts))
                connection.commit()
                self.assertEqual(signature, (db.stat().st_mtime_ns, db.stat().st_size))
                result, _ = self.scan(tmp, cache)
                self.assertEqual(result["ranges"]["all"]["out"], 600)


    def _write_records(self, root, name, records):
        path = Path(root) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(row) for row in records) + "\n")
        return path

    def test_database_sessions_override_json_mirrors_but_keep_independent_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "session-store.db"
            now = datetime.now(timezone.utc)
            yesterday = now - USAGE.timedelta(days=1)
            with closing(sqlite3.connect(db)) as connection:
                connection.executescript("""
                    CREATE TABLE sessions(id TEXT, cwd TEXT);
                    CREATE TABLE assistant_usage_events(
                        session_id TEXT, model TEXT, input_tokens INTEGER, output_tokens INTEGER,
                        cache_read_tokens INTEGER, cache_write_tokens INTEGER, reasoning_tokens INTEGER,
                        created_at TEXT);
                """)
                connection.executemany("INSERT INTO sessions VALUES (?, ?)",
                                       [(sid, "/synthetic/" + sid) for sid in ("A", "B", "C")])
                connection.executemany("INSERT INTO assistant_usage_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
                    ("A", "model-a", 100, 20, 50, 10, 7, _ts(now)),
                    ("B", "model-b", 200, 50, 60, 20, 10, _ts(yesterday)),
                    # An invalid DB row must not claim JSON fallback C.
                    ("C", "invalid-model", 999, 999, 999, 999, 0, "invalid-timestamp"),
                ])
                connection.commit()
            for sid, model, output, reason in (("A", "model-a", 20, 7), ("B", "model-b", 50, 10), ("C", "model-c", 40, 8)):
                self._write_records(tmp, "session-state/" + sid + "/events.jsonl", [self._generic(
                    "json-" + sid, _ts(now), sessionId=sid, cwd="/synthetic/" + sid, model=model,
                    usage={"inputTokens": 300, "outputTokens": output, "reasoningTokens": reason})])
            # A previous version may already have persisted DB+JSON duplicates.
            key = now.astimezone().date().isoformat()
            old = USAGE._empty_token_day()
            old.update({"out": 999, "_ledger_version": 6})
            USAGE._load_ledger()["tools"]["copilot"] = {key: old}
            result, cache = self.scan(tmp)
            def check(result, cache):
                day = result["ranges"]["all"]
                self.assertEqual(day["sessions"], {"A", "B", "C"})
                self.assertEqual((day["out"], day["reason"], USAGE.token_total(day)), (85, 25, 110))
                self.assertEqual(day["coverage"], "output_only")
                self.assertEqual({model: USAGE.token_total(value) for model, value in day["models"].items()},
                                 {"model-a": 20, "model-b": 50, "model-c": 40})
                hits = list(USAGE._project_contributions(cache))
                self.assertEqual({hit["path"]: hit["tokens"] for hit in hits},
                                 {"/synthetic/A": 20, "/synthetic/B": 50, "/synthetic/C": 40})
                self.assertEqual(sum(hit["cost"] for hit in hits), 0)
            check(result, cache)
            kept = USAGE._load_ledger()["tools"]["copilot"][key]
            self.assertEqual((USAGE.token_total(kept), kept["_ledger_version"]), (60, 7))
            with mock.patch.object(USAGE, "_scan_copilot_session", side_effect=AssertionError("warm source was rescanned")):
                warm, warm_cache = self.scan(tmp, json.loads(json.dumps(cache)))
            check(warm, warm_cache)

    def test_physical_database_aliases_are_counted_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "session-store.db"
            db.touch()
            alias = Path(tmp) / "alias.sqlite"
            try:
                alias.symlink_to(db)
            except (OSError, NotImplementedError) as error:
                self.skipTest("This runtime cannot create fixture symlinks: " + str(error))
            day = USAGE._empty_token_day()
            USAGE._add_token_usage(day, out=13, reason=7, model="model")
            day["sessions"] = ["A"]
            with mock.patch.object(USAGE, "_copilot_roots", return_value=[tmp, str(Path(tmp) / ".")]):
                self.assertEqual(USAGE._copilot_session_files(), [str(db.resolve())])
            # Defensive reconciliation also handles legacy aliases in a cache.
            canonical = USAGE._copilot_canonical_days({
                str(db): {"days": {"2026-10-10": day}},
                str(alias): {"days": {"2026-10-10": day}},
            })
            self.assertEqual(sum(USAGE.token_total(day) for days in canonical.values() for day in days.values()), 20)

    def _generic(self, identity=None, timestamp=None, **extra):
        row = {
            "type": "assistant.usage", "sessionId": "generic-session",
            "timestamp": timestamp or _ts(datetime.now(timezone.utc)),
            "cwd": "/synthetic/generic", "model": "gpt-5-mini",
            "usage": {"inputTokens": 100, "outputTokens": 20, "reasoningTokens": 7},
        }
        if identity is not None:
            row["id"] = identity
        row.update(extra)
        return row

    def test_generic_nested_usage_aliases_without_shutdown(self):
        variants = [
            {"inputTokens": 100, "outputTokens": 20, "reasoningTokens": 7},
            {"input_tokens": 100, "output_tokens": 20, "reasoning_tokens": 7},
            {"prompt_tokens": 100, "completion_tokens": 20, "reasoning_tokens": 7},
            {"input": 100, "output": 20, "reasoningTokens": 7},
            {"input": {"inputTokens": 100, "outputTokens": 20, "reasoningTokens": 7}},
        ]
        for usage in variants:
            with self.subTest(usage=usage), tempfile.TemporaryDirectory() as tmp:
                self._write_records(tmp, "generic.jsonl", [self._generic("request", usage=usage)])
                prices = {"in": 1, "out": 10, "cache_read": 2, "cache_write": 3}
                with mock.patch.object(USAGE, "_pricing_id", return_value="test"), \
                     mock.patch.object(USAGE, "_raw_price", return_value=prices):
                    result, cache = self.scan(tmp)
                day = result["ranges"]["all"]
                self.assertEqual((day["in"], day["out"], day["reason"]), (0, 13, 7))
                self.assertEqual(day["cost"], 0)
                self.assertEqual(day["sessions"], {"generic-session"})
                self.assertEqual(sum(hit["tokens"] for hit in USAGE._project_contributions(cache)), 20)

    def test_generic_data_usage_keeps_timestamp_project_and_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            ts = "2026-10-10T23:30:00-05:00"
            row = {"type": "assistant.usage", "data": {
                "requestId": "data-request", "session_id": "data-session",
                "created_at": ts, "workspace": "/synthetic/data", "modelId": "gpt-5-mini",
                "usage": {"input_tokens": 100, "output_tokens": 20,
                          "reasoning_tokens": 7, "cache_read_tokens": 3, "cache_write_tokens": 2},
            }}
            path = self._write_records(tmp, "data.jsonl", [row])
            result, cache = self.scan(tmp)
            day = result["ranges"]["all"]
            self.assertEqual((day["in"], day["out"], day["reason"], day["cr"], day["cw"]), (0, 13, 7, 0, 0))
            self.assertEqual(day["sessions"], {"data-session"})
            cached_day = next(iter(cache["copilot"][str(path.resolve())]["canonical_days"].values()))
            self.assertEqual((cached_day["_reported_in"], cached_day["_reported_cr"], cached_day["_reported_cw"]), (100, 3, 2))
            self.assertEqual(day["coverage"], "output_only")
            expected_day = datetime.fromisoformat(ts).astimezone().date().isoformat()
            self.assertIn(expected_day, cache["copilot"][str(path.resolve())]["canonical_days"])
            hits = list(USAGE._project_contributions(cache))
            self.assertEqual([(hit["path"], hit["tokens"]) for hit in hits], [("/synthetic/data", 20)])

    def test_generic_top_level_fields_survive_missing_or_non_dict_data(self):
        for malformed_data in (None, [], "not-an-object"):
            with self.subTest(data=malformed_data), tempfile.TemporaryDirectory() as tmp:
                row = {"type": "usage", "data": malformed_data, "createdAt": _ts(datetime.now(timezone.utc)),
                       "session_id": "top-session", "gitRoot": "/synthetic/top", "model_id": "gpt-5-mini",
                       "request_id": "top-request", "input_tokens": 100, "output_tokens": 20,
                       "reasoning_tokens": 7}
                self._write_records(tmp, "top.jsonl", [row])
                result, cache = self.scan(tmp)
                day = result["ranges"]["all"]
                self.assertEqual((day["in"], day["out"], day["reason"]), (0, 13, 7))
                self.assertEqual(day["sessions"], {"top-session"})
                self.assertEqual(next(USAGE._project_contributions(cache))["path"], "/synthetic/top")

    def test_generic_stable_ids_deduplicate_mirrors_but_keep_equal_distinct_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            ts = _ts(datetime.now(timezone.utc))
            one, two, three = [self._generic(identity, ts) for identity in ("one", "two", "three")]
            self._write_records(tmp, "a.jsonl", [one, two, two])
            self._write_records(tmp, "b.jsonl", [one, three])
            result, cache = self.scan(tmp)
            self.assertEqual(result["ranges"]["all"]["out"], 39)
            self.assertEqual(result["ranges"]["all"]["out"] + result["ranges"]["all"]["reason"], 60)
            self.assertEqual(sum(hit["tokens"] for hit in USAGE._project_contributions(cache)), 60)

    def test_idless_timestamped_segments_union_and_exact_mirror_multiplicity_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = datetime.now(timezone.utc).replace(microsecond=0)
            one = self._generic(timestamp=_ts(base))
            two = self._generic(timestamp=_ts(base + USAGE.timedelta(seconds=1)))
            # Two legitimate indistinguishable rows within one file remain two.
            a = self._write_records(tmp, "a.jsonl", [one, one])
            (Path(tmp) / "mirror.jsonl").write_bytes(a.read_bytes())
            self._write_records(tmp, "disjoint.jsonl", [two])
            result, cache = self.scan(tmp)
            self.assertEqual(result["ranges"]["all"]["out"], 39)
            self.assertEqual(sum(hit["tokens"] for hit in USAGE._project_contributions(cache)), 60)
            again, _ = self.scan(tmp, json.loads(json.dumps(cache)))
            self.assertEqual(again["ranges"]["all"]["out"], 39)

    def test_generic_records_keep_per_row_session_and_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [self._generic("same-id", sessionId=sid, cwd="/synthetic/" + sid)
                    for sid in ("session-a", "session-b")]
            self._write_records(tmp, "multi.jsonl", rows)
            result, cache = self.scan(tmp)
            self.assertEqual(result["ranges"]["all"]["sessions"], {"session-a", "session-b"})
            self.assertEqual({hit["path"]: hit["tokens"] for hit in USAGE._project_contributions(cache)},
                             {"/synthetic/session-a": 20, "/synthetic/session-b": 20})

    def test_authoritative_shutdown_wins_over_generic_rows_in_same_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = self._shutdown()
            path = self._write_session(tmp, "generic-session", data["sessionStartTime"], data)
            with path.open("a") as fh:
                fh.write(json.dumps(self._generic("detail")) + "\n")
            result, _ = self.scan(tmp)
            day = result["ranges"]["all"]
            self.assertEqual((day["in"], day["out"], day["reason"], day["credits"]), (0, 13, 7, 2))

    def test_authoritative_shutdown_wins_across_files_and_all_days_of_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = self._shutdown()
            self._write_session(tmp, "generic-session", data["sessionStartTime"], data)
            row = self._generic("detail", _ts(datetime.now(timezone.utc) - USAGE.timedelta(days=1)))
            self._write_records(tmp, "request-segment.jsonl", [row])
            result, cache = self.scan(tmp)
            self.assertEqual(result["ranges"]["all"]["out"], 13)
            self.assertEqual(sum(hit["tokens"] for hit in USAGE._project_contributions(cache)), 20)

    def test_shutdown_without_usable_model_metrics_does_not_hide_fallback(self):
        for metrics in ({}, {"gpt-5-mini": {"usage": {}}}, {"gpt-5-mini": {"usage": {"inputTokens": 999}}},
                        {"gpt-5-mini": {"usage": {"inputTokens": None, "outputTokens": "unavailable"}}}):
            with self.subTest(metrics=metrics), tempfile.TemporaryDirectory() as tmp:
                self._write_records(tmp, "usage.jsonl", [
                    self._generic("detail"),
                    {"type": "session.shutdown", "data": {
                        "sessionId": "generic-session", "modelMetrics": metrics,
                        "totalPremiumRequests": 2, "sessionStartTime": _ts(datetime.now(timezone.utc))}},
                ])
                result, _ = self.scan(tmp)
                day = result["ranges"]["all"]
                self.assertEqual((day["in"], day["out"], day["reason"], day["credits"]), (0, 13, 7, 2))

    def test_explicit_zero_shutdown_is_authoritative(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = self._shutdown()
            data["modelMetrics"]["gpt-5-mini"]["usage"] = {"inputTokens": 0, "outputTokens": 0}
            self._write_session(tmp, "generic-session", data["sessionStartTime"], data)
            self._write_records(tmp, "details.jsonl", [self._generic("detail")])
            result, _ = self.scan(tmp)
            self.assertEqual(result["ranges"]["all"]["in"], 0)
            self.assertEqual(result["ranges"]["all"]["out"], 0)

    def test_raw_reasoning_is_clamped_and_ambiguous_cost_is_deferred(self):
        prices = {"in": 1, "out": 10, "cache_read": 2, "cache_write": 3}
        for reasoning, expected in ((7, (13, 7)), (30, (0, 20)), (-1, (20, 0))):
            with self.subTest(reasoning=reasoning), tempfile.TemporaryDirectory() as tmp:
                data = self._shutdown()
                data["modelMetrics"]["gpt-5-mini"]["usage"]["reasoningTokens"] = reasoning
                self._write_session(tmp, "one", data["sessionStartTime"], data)
                with mock.patch.object(USAGE, "_pricing_id", return_value="test"), \
                     mock.patch.object(USAGE, "_raw_price", return_value=prices):
                    result, _ = self.scan(tmp)
                day = result["ranges"]["all"]
                self.assertEqual((day["out"], day["reason"]), expected)
                self.assertEqual(day["out"] + day["reason"], 20)
                self.assertEqual(day["cost"], 0)

    def test_accounting_version_corrects_old_live_day_but_keeps_archived_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = self._shutdown()
            self._write_session(tmp, "one", data["sessionStartTime"], data)
            current = datetime.now().astimezone().date().isoformat()
            archived = (datetime.now().astimezone().date() - USAGE.timedelta(days=3)).isoformat()
            old = USAGE._empty_token_day()
            old.update({"in": 100, "out": 20, "reason": 7})
            history = USAGE._empty_token_day()
            history.update({"in": 999, "cr": 50, "cw": 10, "cost": 4, "out": 500, "reason": 30})
            ledger = USAGE._load_ledger()
            ledger["tools"]["copilot"] = {current: old, archived: history.copy()}
            result, _ = self.scan(tmp)
            day = result["ranges"]["today"]
            self.assertEqual((day["out"], day["reason"]), (13, 7))
            self.assertEqual(ledger["tools"]["copilot"][current]["_ledger_version"],
                             USAGE._COPILOT_PARSER_VERSION)
            archived_day = ledger["tools"]["copilot"][archived]
            self.assertEqual((archived_day["in"], archived_day["cr"], archived_day["cw"], archived_day["cost"]), (0, 0, 0, 0))
            self.assertEqual((archived_day["out"], archived_day["reason"]), (470, 30))
            self.assertEqual(USAGE._ledger_token_sum(archived_day, "copilot"), 500)

    def test_sqlite_raw_output_reasoning_normalization_and_deferred_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "usage.db"
            with closing(sqlite3.connect(db)) as connection:
                connection.executescript("""
                    CREATE TABLE sessions(id TEXT, cwd TEXT);
                    CREATE TABLE assistant_usage_events(
                        session_id TEXT, model TEXT, input_tokens INTEGER, output_tokens INTEGER,
                        cache_read_tokens INTEGER, cache_write_tokens INTEGER, reasoning_tokens INTEGER,
                        created_at TEXT);
                """)
                connection.execute("INSERT INTO sessions VALUES (?, ?)", ("db-session", "/synthetic/db"))
                connection.execute("INSERT INTO assistant_usage_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                   ("db-session", "gpt-5-mini", 100, 20, 0, 0, 7, _ts(datetime.now(timezone.utc))))
                connection.commit()
                prices = {"in": 1, "out": 10, "cache_read": 2, "cache_write": 3}
                with mock.patch.object(USAGE, "_pricing_id", return_value="test"), \
                     mock.patch.object(USAGE, "_raw_price", return_value=prices):
                    result, cache = self.scan(tmp)
                day = result["ranges"]["all"]
                self.assertEqual((day["out"], day["reason"]), (13, 7))
                self.assertEqual(day["cost"], 0)
                self.assertEqual(next(USAGE._project_contributions(cache))["tokens"], 20)

    def test_shutdown_model_metrics_and_premium_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime.now(timezone.utc).astimezone().replace(minute=0, second=0, microsecond=0)
            start = _ts(now)
            shutdown = {
                "sessionStartTime": start,
                "totalPremiumRequests": 2,
                "modelMetrics": {
                    "gpt-5-mini": {
                        "usage": {
                            "inputTokens": 1000,
                            "outputTokens": 200,
                            "cacheReadTokens": 50,
                            "cacheWriteTokens": 10,
                            "reasoningTokens": 30,
                        }
                    }
                },
            }
            path = self._write_session(tmp, "sess-1", start, shutdown)
            result, cache = self.scan(tmp)
            usage = result["ranges"]["all"]
            self.assertEqual(usage["sessions"], {"sess-1"})
            self.assertEqual(usage["in"], 0)
            self.assertEqual(usage["out"], 170)
            self.assertEqual(usage["cr"], 0)
            self.assertEqual(usage["cw"], 0)
            self.assertEqual(usage["reason"], 30)
            self.assertAlmostEqual(usage["credits"], 2.0)
            self.assertEqual(len(usage["models"]), 1)
            self.assertEqual(usage["coverage"], "output_only")
            self.assertEqual(USAGE.token_total(usage), 200)
            self.assertEqual(usage["cost"], 0)
            model = next(iter(usage["models"].values()))
            self.assertEqual(USAGE.token_total(model), 200)
            cached_day = next(iter(cache["copilot"][str(path.resolve())]["canonical_days"].values()))
            self.assertEqual((cached_day["_reported_in"], cached_day["_reported_cr"], cached_day["_reported_cw"]), (1000, 50, 10))
            self.assertEqual(cache["copilot"][str(path.resolve())]["proj"], "/tmp/copilot-project")

            with mock.patch.object(
                USAGE, "_scan_copilot_session",
                side_effect=AssertionError("unchanged session was rescanned"),
            ):
                self.scan(tmp, cache=cache)

    def test_stale_cache_entry_removed_when_file_gone(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = {
                "v": USAGE._SCAN_CACHE_VERSION,
                "copilot": {"/old/events.jsonl": {"sig": "old", "days": {}}},
            }
            self.scan(tmp, cache=cache)
            self.assertEqual(cache["copilot"], {})

    def test_github_copilot_alias(self):
        self.assertIs(USAGE.scan_github_copilot, USAGE.scan_copilot)

    def test_public_range_is_output_only_without_raw_metadata_or_prices(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = self._shutdown()
            data["modelMetrics"]["gpt-5-mini"]["usage"].update({"cacheReadTokens": 50, "cacheWriteTokens": 10})
            self._write_session(tmp, "known", data["sessionStartTime"], data)
            result, _ = self.scan(tmp)
            public = USAGE._copilot_public_range(result["ranges"]["all"])
            self.assertEqual(public["coverage"], "output_only")
            self.assertEqual((public["out"], public["reason"], public["credits"], public["sessions"]), (13, 7, 2, 1))
            self.assertEqual(USAGE.token_total(public), 20)
            self.assertEqual((public["in"], public["cr"], public["cw"], public["cost"]), (0, 0, 0, 0))
            self.assertNotIn("_reported", json.dumps(public))
            model = public["models"][0]
            self.assertEqual(USAGE.token_total(model), 20)
            self.assertEqual((model["pin"], model["pout"], model["pcr"], model["cost"]), (0, 0, 0, 0))

    def test_output_only_top_level_event_needs_no_input_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_records(tmp, "output.jsonl", [{
                "id": "output-only", "sessionId": "known", "timestamp": _ts(datetime.now(timezone.utc)),
                "outputTokens": 20, "reasoningTokens": 7, "model": "gpt-5-mini"}])
            result, _ = self.scan(tmp)
            self.assertEqual((result["ranges"]["all"]["out"], result["ranges"]["all"]["reason"]), (13, 7))

    def test_archived_output_scope_migration_survives_disk_high_water(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            today = datetime.now().astimezone().date()
            days = {}
            for age, version, output in ((2, 0, 20), (3, 5, 13)):
                key = (today - USAGE.timedelta(days=age)).isoformat()
                day = USAGE._empty_token_day()
                day.update({"in": 100, "cr": 50, "cw": 10, "out": output, "reason": 7,
                            "cost": 0.5, "sessions": ["archived-" + str(age)], "_ledger_version": version})
                day["models"] = {"gpt-5-mini": {key: day[key] for key in ("in", "cr", "cw", "out", "reason", "cost")}}
                days[key] = day
            path.write_text(json.dumps({"v": USAGE._LEDGER_VERSION, "tools": {"copilot": days}}))
            memo = {"data": None, "dirty": False, "urgent": False}
            with mock.patch.object(USAGE, "_LEDGER_FILE", str(path)), mock.patch.object(USAGE, "_LEDGER_CACHE", memo):
                result, _ = self.scan(Path(tmp) / "no-source-logs")
                self.assertEqual(USAGE.token_total(result["ranges"]["all"]), 40)
                self.assertEqual(result["ranges"]["all"]["sessions"], {"archived-2", "archived-3"})
                USAGE.ledger_flush()
            for day in json.loads(path.read_text())["tools"]["copilot"].values():
                self.assertEqual((day["out"], day["reason"], day["in"], day["cr"], day["cw"], day["cost"]), (13, 7, 0, 0, 0, 0))
                self.assertEqual(USAGE.token_total(day["models"]["gpt-5-mini"]), 20)


class CopilotDailyCostsTests(unittest.TestCase):
    def test_zero_cost_copilot_activity_is_included(self):
        today = datetime.now().astimezone().date().isoformat()
        for activity, tokens in (({"out": 13, "reason": 7}, 20),
                                 ({"credits": 2}, 0)):
            with self.subTest(activity=activity):
                ledger = {"tools": {"copilot": {today: {"cost": 0, **activity}}}}
                with mock.patch.object(USAGE, "_load_ledger", return_value=ledger):
                    daily = USAGE.build_daily_costs("all", refresh=False, _cache={})["daily"]
                self.assertEqual(len(daily), 1)
                self.assertEqual(daily[0]["copilot"], 0)
                self.assertEqual(daily[0]["total"], 0)
                self.assertEqual(daily[0]["tokens"], tokens)

    def test_copilot_cost_is_included_in_mixed_tool_total(self):
        today = datetime.now().astimezone().date().isoformat()
        ledger = {"tools": {"copilot": {today: {"out": 20, "cost": 1.25}}}}
        cache = {"claude": {"session": {"days": {
            today: {"in": 100, "out": 50, "cost": 2.5}}}}}
        with mock.patch.object(USAGE, "_load_ledger", return_value=ledger):
            daily = USAGE.build_daily_costs("all", refresh=False, _cache=cache)["daily"]
        self.assertEqual(len(daily), 1)
        self.assertEqual(daily[0]["copilot"], 1.25)
        self.assertEqual(daily[0]["claude"], 2.5)
        self.assertEqual(daily[0]["total"], 3.75)
        self.assertEqual(daily[0]["tokens"], 170)

    def test_day_without_copilot_has_zero_copilot_cost(self):
        today = datetime.now().astimezone().date().isoformat()
        ledger = {"tools": {"claude": {today: {"out": 20, "cost": 2.5}}}}
        with mock.patch.object(USAGE, "_load_ledger", return_value=ledger):
            daily = USAGE.build_daily_costs("all", refresh=False, _cache={})["daily"]
        self.assertEqual(len(daily), 1)
        self.assertEqual(daily[0]["copilot"], 0)
        self.assertEqual(daily[0]["total"], 2.5)


if __name__ == "__main__":
    unittest.main()
