import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from test_codex_limits import USAGE


def event(ts, day, total, last, cost):
    return [ts, day, *total, *last, cost]


class CodexDedupedDaysTests(unittest.TestCase):
    def test_legacy_model_cache_without_credits_accepts_new_events(self):
        first = event(
            "2026-07-10T00:00:00+00:00",
            "2026-07-10",
            (100, 80, 5, 2),
            (100, 80, 5, 2),
            1.0,
        ) + ["openai/gpt-5.4"]
        second = event(
            "2026-07-10T01:00:00+00:00",
            "2026-07-10",
            (150, 120, 8, 3),
            (50, 40, 3, 1),
            0.5,
        ) + ["openai/gpt-5.4"]

        days = {}
        USAGE._codex_add_event(days, first)
        days["2026-07-10"]["models"]["openai/gpt-5.4"].pop("credits")

        USAGE._codex_add_event(days, second)

        usage = days["2026-07-10"]["models"]["openai/gpt-5.4"]
        self.assertEqual(usage["in"], 30)
        self.assertEqual(usage["out"], 8)
        self.assertEqual(usage["cr"], 120)
        self.assertEqual(usage["reason"], 3)
        self.assertEqual(usage["credits"], 0.0)

    def test_replayed_parent_snapshot_is_counted_once(self):
        parent = event(
            "2026-07-10T00:00:00+00:00",
            "2026-07-10",
            (100, 80, 5, 2),
            (100, 80, 5, 2),
            1.0,
        )
        replay = event(
            "2026-07-10T01:00:00+00:00",
            "2026-07-10",
            (100, 80, 5, 2),
            (100, 80, 5, 2),
            1.0,
        )
        child_increment = event(
            "2026-07-10T01:01:00+00:00",
            "2026-07-10",
            (150, 120, 8, 3),
            (50, 40, 3, 1),
            0.5,
        )

        days = USAGE._codex_deduped_days({
            "child": {"session_id": "child", "forked_from_id": "parent",
                      "events": [replay, child_increment]},
            "parent": {"session_id": "parent", "events": [parent]},
        })

        self.assertEqual(days["parent"]["2026-07-10"]["in"], 100)
        self.assertEqual(days["child"]["2026-07-10"]["in"], 50)
        self.assertEqual(days["child"]["2026-07-10"]["out"], 3)
        parent_hour = datetime.fromisoformat(parent[0]).astimezone().hour
        child_hour = datetime.fromisoformat(child_increment[0]).astimezone().hour
        self.assertEqual(days["parent"]["2026-07-10"]["hours"][parent_hour], 105)
        self.assertEqual(days["child"]["2026-07-10"]["hours"][child_hour], 53)

    def test_matching_snapshots_in_independent_sessions_are_kept(self):
        first = event(
            "2026-07-10T00:00:00+00:00",
            "2026-07-10",
            (100, 80, 5, 2),
            (100, 80, 5, 2),
            1.0,
        )
        second = event(
            "2026-07-10T01:00:00+00:00",
            "2026-07-10",
            (100, 80, 5, 2),
            (100, 80, 5, 2),
            1.0,
        )

        days = USAGE._codex_deduped_days({
            "a": {"session_id": "a", "events": [first]},
            "b": {"session_id": "b", "events": [second]},
        })

        self.assertEqual(days["a"]["2026-07-10"]["in"], 100)
        self.assertEqual(days["b"]["2026-07-10"]["in"], 100)

    def test_long_replay_without_parent_metadata_uses_indexed_prefix(self):
        parent_first = event(
            "2026-07-10T00:00:00+00:00", "2026-07-10",
            (100, 80, 5, 2), (100, 80, 5, 2), 1.0,
        )
        parent_second = event(
            "2026-07-10T00:01:00+00:00", "2026-07-10",
            (150, 120, 8, 3), (50, 40, 3, 1), 0.5,
        )
        child_first = event(
            "2026-07-10T01:00:00+00:00", "2026-07-10",
            (100, 80, 5, 2), (100, 80, 5, 2), 1.0,
        )
        child_second = event(
            "2026-07-10T01:01:00+00:00", "2026-07-10",
            (150, 120, 8, 3), (50, 40, 3, 1), 0.5,
        )
        child_increment = event(
            "2026-07-10T01:02:00+00:00", "2026-07-10",
            (175, 140, 10, 4), (25, 20, 2, 1), 0.25,
        )

        days = USAGE._codex_deduped_days({
            "parent": {"events": [parent_first, parent_second]},
            "child": {"events": [child_first, child_second, child_increment]},
        })

        self.assertEqual(days["parent"]["2026-07-10"]["in"], 150)
        self.assertEqual(days["child"]["2026-07-10"]["in"], 25)

    def test_events_without_cumulative_total_are_kept(self):
        first = event(
            "2026-07-10T00:00:00+00:00",
            "2026-07-10",
            (None, None, None, None),
            (25, 20, 2, 1),
            0.1,
        )
        second = event(
            "2026-07-10T00:01:00+00:00",
            "2026-07-10",
            (None, None, None, None),
            (25, 20, 2, 1),
            0.1,
        )

        days = USAGE._codex_deduped_days({
            "a": {"events": [first]},
            "b": {"events": [second]},
        })

        self.assertEqual(days["a"]["2026-07-10"]["in"], 25)
        self.assertEqual(days["b"]["2026-07-10"]["in"], 25)


class CodexScanDedupTests(unittest.TestCase):
    def session_meta(self, sid, forked_from_id=None, history_base=None):
        payload = {
            "session_id": forked_from_id or sid,
            "id": sid,
            "cwd": "/tmp/project",
            "model_provider": "custom",
        }
        if forked_from_id:
            payload["forked_from_id"] = forked_from_id
        if history_base is not None:
            payload["history_base"] = history_base
        return json.dumps({
            "timestamp": "2024-01-08T00:00:00Z",
            "type": "session_meta",
            "payload": payload,
        })

    def test_session_meta_prefers_own_id_over_parent_session_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-child.jsonl"
            path.write_text(self.session_meta("child", "parent") + "\n", encoding="utf-8")
            session_id, parent_id, _ = USAGE._codex_session_meta(path)

        self.assertEqual(session_id, "child")
        self.assertEqual(parent_id, "parent")

    def test_session_meta_reads_legacy_nested_parent_id(self):
        meta = {
            "timestamp": "2024-01-08T00:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": "child",
                "source": {
                    "subagent": {
                        "thread_spawn": {"parent_thread_id": "parent"},
                    },
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-child.jsonl"
            path.write_text(json.dumps(meta) + "\n", encoding="utf-8")
            session_id, parent_id, _ = USAGE._codex_session_meta(path)

        self.assertEqual(session_id, "child")
        self.assertEqual(parent_id, "parent")

    def test_session_meta_reads_history_base(self):
        meta = {
            "timestamp": "2024-01-08T00:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": "session-A",
                "session_id": "session-A",
                "history_mode": "paginated",
                "history_base": {"thread_id": "session-A",
                                 "end_ordinal_exclusive": 20467},
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-page.jsonl"
            path.write_text(json.dumps(meta) + "\n", encoding="utf-8")
            session_id, parent_id, history_base = USAGE._codex_session_meta(path)

        self.assertEqual(session_id, "session-A")
        self.assertIsNone(parent_id)
        self.assertEqual(history_base, {"thread_id": "session-A",
                                        "end_ordinal_exclusive": 20467})

    def test_canonical_keeps_complementary_paginated_pages(self):
        """issue #96:同 session 互补续页按 response_ids 都保留,不整文件二选一。"""
        file_cache = {
            "page-A.jsonl": {
                "session_id": "session-A", "event_count": 51,
                "last_event_ts": "2026-09-20T01:00:02+00:00", "parsed_size": 1000,
                "response_ids": ["r%02d" % i for i in range(51)],
            },
            "page-B.jsonl": {
                "session_id": "session-A", "event_count": 37,
                "last_event_ts": "2026-09-20T02:00:01+00:00", "parsed_size": 500,
                "history_base": {"thread_id": "session-A",
                                 "end_ordinal_exclusive": 20467},
                "response_ids": ["s%02d" % i for i in range(37)],
            },
        }
        self.assertEqual(sorted(USAGE._codex_canonical_file_cache(file_cache)),
                         ["page-A.jsonl", "page-B.jsonl"])

    def test_canonical_still_drops_fully_covered_paginated_copy(self):
        """续页是完整副本(ids 被覆盖)时仍只保留一页,不重复计数。"""
        ids = ["r%02d" % i for i in range(51)]
        file_cache = {
            "page-A.jsonl": {
                "session_id": "session-A", "event_count": 51,
                "last_event_ts": "2026-09-20T01:00:02+00:00", "parsed_size": 1000,
                "response_ids": ids,
            },
            "page-B.jsonl": {
                "session_id": "session-A", "event_count": 51,
                "last_event_ts": "2026-09-20T02:00:01+00:00", "parsed_size": 500,
                "history_base": {"thread_id": "session-A"},
                "response_ids": list(ids),
            },
        }
        self.assertEqual(len(USAGE._codex_canonical_file_cache(file_cache)), 1)

    def test_canonical_keeps_paginated_page_without_response_ids(self):
        """续页无 ids(老解析)时不丢页;有 ids 的前页照常保留。"""
        file_cache = {
            "page-A.jsonl": {
                "session_id": "session-A", "event_count": 2,
                "last_event_ts": "2026-09-20T01:00:02+00:00", "parsed_size": 1000,
                "response_ids": ["r00", "r01"],
            },
            "page-B.jsonl": {
                "session_id": "session-A", "event_count": 1,
                "last_event_ts": "2026-09-20T02:00:01+00:00", "parsed_size": 500,
                "history_base": {"thread_id": "session-A"},
            },
        }
        self.assertEqual(sorted(USAGE._codex_canonical_file_cache(file_cache)),
                         ["page-A.jsonl", "page-B.jsonl"])

    def test_scan_counts_both_pages_of_paginated_session(self):
        """端到端:page-A 累计/增量 100/100、300/200,page-B 350/50,总量应为 350。"""
        with tempfile.TemporaryDirectory() as tmp:
            page_a = Path(tmp) / "rollout-page-a.jsonl"
            page_a.write_text("\n".join([
                self.session_meta("session-A"),
                self.turn_context("2024-01-08T00:00:00Z", "gpt-5.5"),
                self.token_count("2024-01-08T00:01:00Z", (100, 0, 0, 0), (100, 0, 0, 0)),
                self.token_count("2024-01-08T00:02:00Z", (300, 0, 0, 0), (200, 0, 0, 0)),
            ]) + "\n", encoding="utf-8")
            page_b = Path(tmp) / "rollout-page-b.jsonl"
            page_b.write_text("\n".join([
                self.session_meta("session-A", history_base={"thread_id": "session-A",
                                                             "end_ordinal_exclusive": 2}),
                self.turn_context("2024-01-08T00:03:00Z", "gpt-5.5"),
                self.token_count("2024-01-08T00:04:00Z", (350, 0, 0, 0), (50, 0, 0, 0)),
            ]) + "\n", encoding="utf-8")
            old_dir = USAGE.CODEX_DIR
            old_archive_dir = USAGE.CODEX_ARCHIVED_DIR
            USAGE.CODEX_DIR = tmp
            USAGE.CODEX_ARCHIVED_DIR = str(Path(tmp) / "archived_sessions")
            try:
                with mock.patch.object(USAGE, "fetch_codex_live_limits", return_value=None):
                    result = USAGE.scan_codex(self.bounds(), {"v": USAGE._SCAN_CACHE_VERSION})
            finally:
                USAGE.CODEX_DIR = old_dir
                USAGE.CODEX_ARCHIVED_DIR = old_archive_dir

        usage = result["ranges"]["all"]
        self.assertEqual(usage["in"], 350)
        self.assertEqual(usage["models"]["openai/gpt-5.5"]["in"], 350)

    def token_count(self, ts, total, last, ordinal=None, rate_limits=None):
        record = {"timestamp": ts}
        if ordinal is not None:
            record["ordinal"] = ordinal
        record.update({
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": total[0],
                        "cached_input_tokens": total[1],
                        "output_tokens": total[2],
                        "reasoning_output_tokens": total[3],
                    },
                    "last_token_usage": {
                        "input_tokens": last[0],
                        "cached_input_tokens": last[1],
                        "output_tokens": last[2],
                        "reasoning_output_tokens": last[3],
                    },
                },
            },
        })
        if rate_limits is not None:
            record["payload"]["rate_limits"] = rate_limits
        return json.dumps(record)

    def turn_context(self, ts, model, ordinal=None):
        record = {"timestamp": ts}
        if ordinal is not None:
            record["ordinal"] = ordinal
        record.update({
            "type": "turn_context",
            "payload": {"model": model, "cwd": "/tmp/project"},
        })
        return json.dumps(record)

    def bounds(self):
        day = datetime(2024, 1, 8, tzinfo=timezone.utc)
        return {
            "today": day,
            "yesterday": day - timedelta(days=1),
            "week": day,
            "last_week": day - timedelta(days=7),
            "last_week_end": day,
            "month": day.replace(day=1),
            "year": day.replace(month=1, day=1),
        }

    def test_scan_attributes_each_increment_to_the_active_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-models.jsonl"
            path.write_text("\n".join([
                self.session_meta("models"),
                self.turn_context("2024-01-08T00:00:00Z", "gpt-5.4"),
                self.token_count("2024-01-08T00:01:00Z", (100, 80, 10, 4), (100, 80, 10, 4)),
                self.turn_context("2024-01-08T00:02:00Z", "gpt-5.5"),
                self.token_count("2024-01-08T00:03:00Z", (150, 120, 15, 6), (50, 40, 5, 2)),
            ]) + "\n", encoding="utf-8")
            day = datetime(2024, 1, 8, tzinfo=timezone.utc)
            bounds = {
                "today": day, "yesterday": day - timedelta(days=1), "week": day,
                "last_week": day - timedelta(days=7), "last_week_end": day,
                "month": day.replace(day=1), "year": day.replace(month=1, day=1),
            }
            old_dir = USAGE.CODEX_DIR
            old_archive_dir = USAGE.CODEX_ARCHIVED_DIR
            USAGE.CODEX_DIR = tmp
            USAGE.CODEX_ARCHIVED_DIR = str(Path(tmp) / "archived_sessions")
            try:
                with mock.patch.object(USAGE, "fetch_codex_live_limits", return_value=None):
                    result = USAGE.scan_codex(bounds, {"v": USAGE._SCAN_CACHE_VERSION})
            finally:
                USAGE.CODEX_DIR = old_dir
                USAGE.CODEX_ARCHIVED_DIR = old_archive_dir

        models = result["ranges"]["all"]["models"]
        self.assertEqual(models["openai/gpt-5.4"]["in"], 20)
        self.assertEqual(models["openai/gpt-5.4"]["cr"], 80)
        self.assertEqual(models["openai/gpt-5.4"]["out"], 10)
        self.assertEqual(models["openai/gpt-5.4"]["reason"], 4)
        self.assertEqual(models["openai/gpt-5.5"]["in"], 10)
        self.assertEqual(models["openai/gpt-5.5"]["cr"], 40)

    def test_late_gpt6_model_fields_repair_cached_unknown_without_changing_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-late-models.jsonl"
            records = [self.session_meta("late-models")]
            for index, variant in enumerate(("astra", "sol", "luna")):
                records.append(json.dumps({
                    "timestamp": f"2024-01-08T00:0{index * 2}:00Z",
                    "type": "turn_context",
                    "payload": {"permission_profile": {"description": "x" * 12_000,
                                                        "model": "nested-decoy"},
                                "model": f"gpt-6-{variant}"},
                }))
                records.append(self.token_count(
                    f"2024-01-08T00:0{index * 2 + 1}:00Z",
                    (100 * (index + 1), 80 * (index + 1), 10 * (index + 1), 4 * (index + 1)),
                    (100, 80, 10, 4)))
            path.write_text("\n".join(records) + "\n", encoding="utf-8")
            cache = {"v": USAGE._SCAN_CACHE_VERSION}
            original_reader = USAGE._iter_codex_usage_records

            def old_reader(*args, **kwargs):
                return original_reader(*args, model_limit=4096, **kwargs)

            with mock.patch.object(USAGE, "CODEX_DIR", tmp), \
                 mock.patch.object(USAGE, "CODEX_ARCHIVED_DIR", str(Path(tmp) / "archive")), \
                 mock.patch.object(USAGE, "fetch_codex_live_limits", return_value=None):
                with mock.patch.object(USAGE, "_CODEX_PARSER_VERSION", 7), \
                     mock.patch.object(USAGE, "_iter_codex_usage_records", side_effect=old_reader):
                    before = USAGE.scan_codex(self.bounds(), cache)["ranges"]["all"]
                self.assertIn("unknown", before["models"])
                after = USAGE.scan_codex(self.bounds(), cache)["ranges"]["all"]
                warm = USAGE.scan_codex(self.bounds(), cache)["ranges"]["all"]

        self.assertEqual(warm, after)
        self.assertEqual(set(after["models"]), {f"openai/gpt-6-{v}" for v in ("astra", "sol", "luna")})
        for field in ("in", "out", "cached", "reason"):
            self.assertEqual(before.get(field), after.get(field))
        for model in after["models"].values():
            self.assertEqual((model["in"], model["cr"], model["out"], model["reason"]), (20, 80, 10, 4))

    def test_scan_ignores_runtime_quota_label_for_model_attribution(self):
        # rate_limits.limit_name 是额度/路由名，不是用户选的模型，
        # 不能凭空造出一个模型桶。来自 PR #51 的回归用例。
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-runtime-label.jsonl"
            path.write_text("\n".join([
                self.session_meta("runtime-label"),
                self.turn_context("2024-01-08T00:00:00Z", "gpt-5.5"),
                self.token_count(
                    "2024-01-08T00:01:00Z", (100, 80, 10, 4), (100, 80, 10, 4),
                    rate_limits={"limit_name": "GPT-5.3-Codex-Spark"},
                ),
            ]) + "\n", encoding="utf-8")
            day = datetime(2024, 1, 8, tzinfo=timezone.utc)
            bounds = {
                "today": day, "yesterday": day - timedelta(days=1), "week": day,
                "last_week": day - timedelta(days=7), "last_week_end": day,
                "month": day.replace(day=1), "year": day.replace(month=1, day=1),
            }
            old_dir = USAGE.CODEX_DIR
            old_archive_dir = USAGE.CODEX_ARCHIVED_DIR
            USAGE.CODEX_DIR = tmp
            USAGE.CODEX_ARCHIVED_DIR = str(Path(tmp) / "archived_sessions")
            try:
                with mock.patch.object(USAGE, "fetch_codex_live_limits", return_value=None):
                    result = USAGE.scan_codex(bounds, {"v": USAGE._SCAN_CACHE_VERSION})
            finally:
                USAGE.CODEX_DIR = old_dir
                USAGE.CODEX_ARCHIVED_DIR = old_archive_dir

        models = result["ranges"]["all"]["models"]
        self.assertEqual(sorted(models), ["openai/gpt-5.5"])
        self.assertEqual(models["openai/gpt-5.5"]["in"], 20)
        self.assertEqual(models["openai/gpt-5.5"]["cr"], 80)

    def test_scan_mixes_legacy_and_ordinal_records_with_model_attribution(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-mixed-formats.jsonl"
            path.write_text("\n".join([
                self.session_meta("mixed-formats"),
                self.turn_context("2024-01-08T00:00:00Z", "gpt-5.4"),
                self.token_count(
                    "2024-01-08T00:01:00Z",
                    (100, 80, 10, 4),
                    (100, 80, 10, 4),
                    ordinal=1,
                ),
                self.turn_context(
                    "2024-01-08T00:02:00Z", "gpt-5.5", ordinal=2),
                self.token_count(
                    "2024-01-08T00:03:00Z",
                    (150, 120, 15, 6),
                    (50, 40, 5, 2),
                ),
            ]) + "\n", encoding="utf-8")

            with mock.patch.object(USAGE, "CODEX_DIR", tmp), \
                 mock.patch.object(
                     USAGE, "CODEX_ARCHIVED_DIR", str(Path(tmp) / "archived_sessions")), \
                 mock.patch.object(USAGE, "fetch_codex_live_limits", return_value=None):
                result = USAGE.scan_codex(
                    self.bounds(), {"v": USAGE._SCAN_CACHE_VERSION})

        usage = result["ranges"]["all"]
        self.assertEqual(usage["in"], 150)
        self.assertEqual(usage["cached"], 120)
        self.assertEqual(usage["out"], 15)
        self.assertEqual(usage["reason"], 6)
        self.assertEqual(len(usage["sessions"]), 1)
        self.assertEqual(usage["models"]["openai/gpt-5.4"]["in"], 20)
        self.assertEqual(usage["models"]["openai/gpt-5.4"]["cr"], 80)
        self.assertEqual(usage["models"]["openai/gpt-5.4"]["out"], 10)
        self.assertEqual(usage["models"]["openai/gpt-5.4"]["reason"], 4)
        self.assertEqual(usage["models"]["openai/gpt-5.5"]["in"], 10)
        self.assertEqual(usage["models"]["openai/gpt-5.5"]["cr"], 40)
        self.assertEqual(usage["models"]["openai/gpt-5.5"]["out"], 5)
        self.assertEqual(usage["models"]["openai/gpt-5.5"]["reason"], 2)

    def test_records_without_timestamp_do_not_poison_dedup_or_model(self):
        missing_timestamp_model = json.dumps({
            "ordinal": 1,
            "type": "turn_context",
            "payload": {"model": "gpt-5.5", "cwd": "/tmp/project"},
        })
        missing_timestamp_token = json.loads(self.token_count(
            "2024-01-08T00:01:00Z",
            (100, 80, 5, 2),
            (100, 80, 5, 2),
            ordinal=2,
        ))
        missing_timestamp_token.pop("timestamp")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-missing-timestamp.jsonl"
            path.write_text("\n".join([
                self.session_meta("missing-timestamp"),
                self.turn_context("2024-01-08T00:00:00Z", "gpt-5.4"),
                missing_timestamp_model,
                json.dumps(missing_timestamp_token),
                self.token_count(
                    "2024-01-08T00:02:00Z",
                    (100, 80, 5, 2),
                    (100, 80, 5, 2),
                    ordinal=3,
                ),
            ]) + "\n", encoding="utf-8")

            with mock.patch.object(USAGE, "CODEX_DIR", tmp), \
                 mock.patch.object(
                     USAGE, "CODEX_ARCHIVED_DIR", str(Path(tmp) / "archived_sessions")), \
                 mock.patch.object(USAGE, "fetch_codex_live_limits", return_value=None):
                result = USAGE.scan_codex(
                    self.bounds(), {"v": USAGE._SCAN_CACHE_VERSION})

        usage = result["ranges"]["all"]
        self.assertEqual(usage["in"], 100)
        self.assertEqual(usage["cached"], 80)
        self.assertEqual(usage["out"], 5)
        self.assertEqual(usage["reason"], 2)
        self.assertEqual(set(usage["models"]), {"openai/gpt-5.4"})
        self.assertEqual(usage["models"]["openai/gpt-5.4"]["in"], 20)

    def test_ordinal_parser_upgrade_rescans_model_v2_cache_from_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            sessions.mkdir()
            path = sessions / "rollout-ordinal-cache.jsonl"
            path.write_text("\n".join([
                self.session_meta("ordinal-cache"),
                self.turn_context(
                    "2024-01-08T00:00:00Z", "gpt-5.4", ordinal=1),
                self.token_count(
                    "2024-01-08T00:01:00Z",
                    (100, 80, 5, 2),
                    (100, 80, 5, 2),
                    ordinal=2,
                ),
            ]) + "\n", encoding="utf-8")
            source_path = str(path.resolve())
            st = path.stat()
            complete_offset = st.st_size
            cache = {
                "v": USAGE._SCAN_CACHE_VERSION,
                "codex": {
                    source_path: {
                        "sig": f"{st.st_mtime_ns}:{st.st_size}",
                        "days": {},
                        "deduped_days": {},
                        "session_id": "ordinal-cache",
                        "forked_from_id": None,
                        "active_model": None,
                        "model_version": 2,
                        "file_id": f"{st.st_dev}:{st.st_ino}",
                        "parsed_size": complete_offset,
                        "parsed_guard": USAGE._codex_offset_guard(
                            source_path, complete_offset),
                        "event_cache_size": 0,
                        "event_count": 0,
                        "first_keys": [],
                        "first_event_ts": None,
                        "last_event_ts": None,
                        "drop_count": 0,
                        "dedupe_open": True,
                        "canonical": True,
                    },
                },
            }
            scan_cache_path = root / "scan-cache.json"

            with mock.patch.object(USAGE, "_SCAN_CACHE_FILE", str(scan_cache_path)), \
                 mock.patch.object(USAGE, "CODEX_DIR", str(sessions)), \
                 mock.patch.object(
                     USAGE, "CODEX_ARCHIVED_DIR", str(root / "archived_sessions")), \
                 mock.patch.object(USAGE, "fetch_codex_live_limits", return_value=None):
                USAGE._codex_write_event_cache(source_path, [])
                original_iterator = USAGE._iter_codex_usage_records
                with mock.patch.object(
                    USAGE, "_iter_codex_usage_records", wraps=original_iterator,
                ) as iterator:
                    result = USAGE.scan_codex(self.bounds(), cache)

        iterator.assert_called_once()
        self.assertEqual(iterator.call_args.kwargs["start_offset"], 0)
        usage = result["ranges"]["all"]
        self.assertEqual(usage["in"], 100)
        self.assertEqual(usage["cached"], 80)
        self.assertEqual(usage["out"], 5)
        self.assertEqual(usage["reason"], 2)
        self.assertEqual(usage["models"]["openai/gpt-5.4"]["in"], 20)
        self.assertEqual(
            cache["codex"][source_path]["parser_version"],
            USAGE._CODEX_PARSER_VERSION,
        )

    def test_parser_upgrade_rescans_nonempty_model_v2_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            sessions.mkdir()
            path = sessions / "rollout-cached.jsonl"
            path.write_text(self.session_meta("cached") + "\n" +
                            self.turn_context("2024-01-08T00:00:00Z", "gpt-5.4") + "\n" +
                            self.token_count("2024-01-08T00:01:00Z", (100, 80, 5, 2),
                                             (100, 80, 5, 2)) + "\n", encoding="utf-8")
            source_path = str(path.resolve())
            st = path.stat()
            cached_event = event(
                "2024-01-08T00:01:00+00:00",
                "2024-01-08",
                (100, 80, 5, 2),
                (100, 80, 5, 2),
                0.5,
            ) + ["openai/gpt-5.4"]
            days = {}
            USAGE._codex_add_event(days, cached_event)
            cache = {"v": USAGE._SCAN_CACHE_VERSION, "codex": {}}
            scan_cache_path = root / "scan-cache.json"

            with mock.patch.object(USAGE, "_SCAN_CACHE_FILE", str(scan_cache_path)), \
                 mock.patch.object(USAGE, "CODEX_DIR", str(sessions)), \
                 mock.patch.object(
                     USAGE, "CODEX_ARCHIVED_DIR", str(root / "archived_sessions")), \
                 mock.patch.object(USAGE, "fetch_codex_live_limits", return_value=None):
                cache_size = USAGE._codex_write_event_cache(source_path, [cached_event])
                cache["codex"][source_path] = {
                    "sig": f"{st.st_mtime_ns}:{st.st_size}",
                    "days": days,
                    "deduped_days": days,
                    "session_id": "cached",
                    "forked_from_id": None,
                    "active_model": "openai/gpt-5.4",
                    "model_version": 2,
                    "file_id": f"{st.st_dev}:{st.st_ino}",
                    "parsed_size": st.st_size,
                    "parsed_guard": USAGE._codex_offset_guard(source_path, st.st_size),
                    "event_cache_size": cache_size,
                    "event_count": 1,
                    "first_keys": [list(USAGE._codex_event_key(cached_event))],
                    "first_event_ts": cached_event[0],
                    "last_event_ts": cached_event[0],
                    "drop_count": 0,
                    "dedupe_open": True,
                    "canonical": True,
                }
                with mock.patch.object(USAGE, "_iter_codex_usage_records",
                                       wraps=USAGE._iter_codex_usage_records) as iterator:
                    result = USAGE.scan_codex(self.bounds(), cache)

        iterator.assert_called_once()
        usage = result["ranges"]["all"]
        self.assertEqual(usage["in"], 100)
        self.assertEqual(usage["cached"], 80)
        self.assertEqual(usage["out"], 5)
        entry = cache["codex"][source_path]
        self.assertEqual(entry["parser_version"], USAGE._CODEX_PARSER_VERSION)
        self.assertNotIn("model_version", entry)

    def test_scan_parses_only_appended_codex_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-growing.jsonl"
            path.write_text("\n".join([
                self.session_meta("growing"),
                self.turn_context("2024-01-08T00:00:00Z", "gpt-5.4"),
                self.token_count("2024-01-08T00:01:00Z", (100, 80, 5, 2), (100, 80, 5, 2)),
            ]) + "\n", encoding="utf-8")
            day = datetime(2024, 1, 8, tzinfo=timezone.utc)
            bounds = {
                "today": day, "yesterday": day - timedelta(days=1), "week": day,
                "last_week": day - timedelta(days=7), "last_week_end": day,
                "month": day.replace(day=1), "year": day.replace(month=1, day=1),
            }
            cache = {"v": USAGE._SCAN_CACHE_VERSION}
            old_dir = USAGE.CODEX_DIR
            old_archive_dir = USAGE.CODEX_ARCHIVED_DIR
            USAGE.CODEX_DIR = tmp
            USAGE.CODEX_ARCHIVED_DIR = str(Path(tmp) / "archived_sessions")
            try:
                with mock.patch.object(USAGE, "fetch_codex_live_limits", return_value=None):
                    USAGE.scan_codex(bounds, cache)
                cache_path = str(path.resolve())
                first_size = cache["codex"][cache_path]["parsed_size"]
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(self.token_count(
                        "2024-01-08T00:02:00Z", (100, 80, 5, 2), (100, 80, 5, 2)) + "\n")
                    handle.write(self.token_count(
                        "2024-01-08T00:03:00Z", (150, 120, 8, 3), (50, 40, 3, 1)) + "\n")
                original_iterator = USAGE._iter_codex_usage_records
                with mock.patch.object(
                    USAGE, "_codex_session_meta",
                    side_effect=AssertionError("append scan should reuse session metadata"),
                ), mock.patch.object(
                    USAGE, "_iter_codex_usage_records", wraps=original_iterator,
                ) as iterator, mock.patch.object(
                    USAGE, "fetch_codex_live_limits", return_value=None,
                ):
                    result = USAGE.scan_codex(bounds, cache)
            finally:
                USAGE.CODEX_DIR = old_dir
                USAGE.CODEX_ARCHIVED_DIR = old_archive_dir

        self.assertGreater(iterator.call_args.kwargs["start_offset"], 0)
        self.assertEqual(iterator.call_args.kwargs["start_offset"], first_size)
        usage = result["ranges"]["all"]
        self.assertEqual(usage["in"], 150)
        self.assertEqual(usage["cached"], 120)
        self.assertEqual(usage["out"], 8)
        self.assertEqual(cache["codex"][cache_path]["event_count"], 2)
        self.assertNotIn("events", cache["codex"][cache_path])
        self.assertEqual(usage["models"]["openai/gpt-5.4"]["in"], 30)

    def test_missing_event_sidecar_rebuilds_unchanged_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            sessions.mkdir()
            path = sessions / "rollout-rebuild.jsonl"
            path.write_text("\n".join([
                self.session_meta("rebuild"),
                self.token_count(
                    "2024-01-08T00:01:00Z",
                    (100, 80, 5, 2),
                    (100, 80, 5, 2),
                ),
            ]) + "\n", encoding="utf-8")
            cache = {"v": USAGE._SCAN_CACHE_VERSION}
            cache_path = root / "scan-cache.json"

            with mock.patch.object(USAGE, "_SCAN_CACHE_FILE", str(cache_path)), \
                 mock.patch.object(USAGE, "CODEX_DIR", str(sessions)), \
                 mock.patch.object(USAGE, "CODEX_ARCHIVED_DIR", str(root / "archived")), \
                 mock.patch.object(USAGE, "fetch_codex_live_limits", return_value=None):
                first = USAGE.scan_codex(self.bounds(), cache)
                source_path = str(path.resolve())
                Path(USAGE._codex_event_cache_path(source_path)).unlink()
                original_iterator = USAGE._iter_codex_usage_records
                with mock.patch.object(
                    USAGE, "_iter_codex_usage_records", wraps=original_iterator,
                ) as iterator:
                    second = USAGE.scan_codex(self.bounds(), cache)

        self.assertEqual(first["ranges"]["all"]["in"], 100)
        self.assertEqual(second["ranges"]["all"]["in"], 100)
        self.assertEqual(iterator.call_args.kwargs["start_offset"], 0)
        self.assertTrue(cache["codex"][source_path]["event_cache_size"] > 0)

    def test_shorter_complete_event_sidecar_repairs_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scan-cache.json"
            source_path = str((Path(tmp) / "rollout-complete.jsonl").resolve())
            cached_event = event(
                "2024-01-08T00:01:00+00:00",
                "2024-01-08",
                (100, 80, 5, 2),
                (100, 80, 5, 2),
                0.5,
            ) + ["openai/gpt-5.4"]

            with mock.patch.object(USAGE, "_SCAN_CACHE_FILE", str(cache_path)):
                actual_size = USAGE._codex_write_event_cache(
                    source_path, [cached_event])
                entry = {
                    "event_cache_size": actual_size + 17,
                    "event_count": 1,
                }
                ready = USAGE._codex_event_cache_ready(
                    source_path, entry, repair_short=True)

        self.assertTrue(ready)
        self.assertEqual(entry["event_cache_size"], actual_size)

    def test_truncated_event_sidecar_is_not_repaired(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scan-cache.json"
            source_path = str((Path(tmp) / "rollout-truncated.jsonl").resolve())
            first = event(
                "2024-01-08T00:01:00+00:00",
                "2024-01-08",
                (100, 80, 5, 2),
                (100, 80, 5, 2),
                0.5,
            ) + ["openai/gpt-5.4"]
            second = event(
                "2024-01-08T00:02:00+00:00",
                "2024-01-08",
                (150, 120, 8, 3),
                (50, 40, 3, 1),
                0.25,
            ) + ["openai/gpt-5.4"]

            with mock.patch.object(USAGE, "_SCAN_CACHE_FILE", str(cache_path)):
                full_size = USAGE._codex_write_event_cache(
                    source_path, [first, second])
                sidecar = Path(USAGE._codex_event_cache_path(source_path))
                first_line_size = sidecar.read_bytes().find(b"\n") + 1
                sidecar.write_bytes(sidecar.read_bytes()[:first_line_size])
                entry = {
                    "event_cache_size": full_size,
                    "event_count": 2,
                }
                ready = USAGE._codex_event_cache_ready(
                    source_path, entry, repair_short=True)

        self.assertFalse(ready)
        self.assertEqual(entry["event_cache_size"], full_size)

    def test_scan_keeps_child_increment_and_drops_replayed_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = root / "rollout-parent.jsonl"
            child = root / "rollout-child.jsonl"
            inherited_total = (100, 80, 5, 2)
            child_total = (150, 120, 8, 3)
            child_last = (50, 40, 3, 1)
            parent.write_text(
                "\n".join([
                    self.session_meta("parent"),
                    self.token_count("2024-01-08T00:00:00Z", inherited_total, inherited_total),
                ]) + "\n",
                encoding="utf-8",
            )
            child.write_text(
                "\n".join([
                    self.session_meta("child", "parent"),
                    self.token_count("2024-01-08T01:00:00Z", inherited_total, inherited_total),
                    self.token_count("2024-01-08T01:01:00Z", child_total, child_last),
                ]) + "\n",
                encoding="utf-8",
            )
            day = datetime(2024, 1, 8, tzinfo=timezone.utc)
            bounds = {
                "today": day,
                "yesterday": day - timedelta(days=1),
                "week": day,
                "last_week": day - timedelta(days=7),
                "last_week_end": day,
                "month": day.replace(day=1),
                "year": day.replace(month=1, day=1),
            }
            old_dir = USAGE.CODEX_DIR
            old_archive_dir = USAGE.CODEX_ARCHIVED_DIR
            USAGE.CODEX_DIR = tmp
            USAGE.CODEX_ARCHIVED_DIR = str(Path(tmp) / "archived_sessions")
            try:
                result = USAGE.scan_codex(bounds, {"v": USAGE._SCAN_CACHE_VERSION})
            finally:
                USAGE.CODEX_DIR = old_dir
                USAGE.CODEX_ARCHIVED_DIR = old_archive_dir

        all_usage = result["ranges"]["all"]
        self.assertEqual(all_usage["in"], 150)
        self.assertEqual(all_usage["cached"], 120)
        self.assertEqual(all_usage["out"], 8)
        self.assertEqual(all_usage["reason"], 3)
        self.assertEqual(len(all_usage["sessions"]), 2)

    def test_scan_keeps_independent_sessions_with_same_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "rollout-first.jsonl"
            second = root / "rollout-second.jsonl"
            usage = (100, 80, 5, 2)
            first.write_text(
                "\n".join([
                    self.session_meta("first"),
                    self.token_count("2024-01-08T00:00:00Z", usage, usage),
                ]) + "\n",
                encoding="utf-8",
            )
            second.write_text(
                "\n".join([
                    self.session_meta("second"),
                    self.token_count("2024-01-08T01:00:00Z", usage, usage),
                ]) + "\n",
                encoding="utf-8",
            )
            day = datetime(2024, 1, 8, tzinfo=timezone.utc)
            bounds = {
                "today": day,
                "yesterday": day - timedelta(days=1),
                "week": day,
                "last_week": day - timedelta(days=7),
                "last_week_end": day,
                "month": day.replace(day=1),
                "year": day.replace(month=1, day=1),
            }
            old_dir = USAGE.CODEX_DIR
            old_archive_dir = USAGE.CODEX_ARCHIVED_DIR
            USAGE.CODEX_DIR = tmp
            USAGE.CODEX_ARCHIVED_DIR = str(Path(tmp) / "archived_sessions")
            try:
                result = USAGE.scan_codex(bounds, {"v": USAGE._SCAN_CACHE_VERSION})
            finally:
                USAGE.CODEX_DIR = old_dir
                USAGE.CODEX_ARCHIVED_DIR = old_archive_dir

        all_usage = result["ranges"]["all"]
        self.assertEqual(all_usage["in"], 200)
        self.assertEqual(all_usage["cached"], 160)
        self.assertEqual(all_usage["out"], 10)
        self.assertEqual(all_usage["reason"], 4)
        self.assertEqual(len(all_usage["sessions"]), 2)

    def test_scan_includes_active_and_archived_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active_dir = root / "sessions" / "2024" / "01" / "08"
            archive_dir = root / "archived_sessions"
            active_dir.mkdir(parents=True)
            archive_dir.mkdir()
            active = active_dir / "rollout-active.jsonl"
            archived = archive_dir / "rollout-archived.jsonl"
            active_usage = (100, 80, 5, 2)
            archived_usage = (50, 40, 3, 1)
            active.write_text("\n".join([
                self.session_meta("active"),
                self.token_count("2024-01-08T00:01:00Z", active_usage, active_usage),
            ]) + "\n", encoding="utf-8")
            archived.write_text("\n".join([
                self.session_meta("archived"),
                self.token_count("2024-01-08T01:01:00Z", archived_usage, archived_usage),
            ]) + "\n", encoding="utf-8")

            with mock.patch.object(USAGE, "CODEX_DIR", str(root / "sessions")), \
                 mock.patch.object(USAGE, "CODEX_ARCHIVED_DIR", str(archive_dir)), \
                 mock.patch.object(USAGE, "fetch_codex_live_limits", return_value=None):
                result = USAGE.scan_codex(self.bounds(), {"v": USAGE._SCAN_CACHE_VERSION})

        usage = result["ranges"]["all"]
        self.assertEqual(usage["in"], 150)
        self.assertEqual(usage["cached"], 120)
        self.assertEqual(usage["out"], 8)
        self.assertEqual(usage["reason"], 3)
        self.assertEqual(len(usage["sessions"]), 2)

    def test_cross_directory_copy_uses_more_complete_session_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active_dir = root / "sessions"
            archive_dir = root / "archived_sessions"
            active_dir.mkdir()
            archive_dir.mkdir()
            active = active_dir / "rollout-shared-active.jsonl"
            archived = archive_dir / "rollout-shared-archived.jsonl"
            first = self.token_count(
                "2024-01-08T00:01:00Z", (100, 80, 5, 2), (100, 80, 5, 2))
            second = self.token_count(
                "2024-01-08T00:02:00Z", (150, 120, 8, 3), (50, 40, 3, 1))
            active.write_text("\n".join([
                self.session_meta("shared"), first,
            ]) + "\n", encoding="utf-8")
            archived.write_text("\n".join([
                self.session_meta("shared"), first, second,
            ]) + "\n", encoding="utf-8")
            cache = {"v": USAGE._SCAN_CACHE_VERSION}

            with mock.patch.object(USAGE, "CODEX_DIR", str(active_dir)), \
                 mock.patch.object(USAGE, "CODEX_ARCHIVED_DIR", str(archive_dir)), \
                 mock.patch.object(USAGE, "fetch_codex_live_limits", return_value=None):
                result = USAGE.scan_codex(self.bounds(), cache)

        usage = result["ranges"]["all"]
        self.assertEqual(usage["in"], 150)
        self.assertEqual(usage["cached"], 120)
        self.assertEqual(usage["out"], 8)
        self.assertEqual(usage["reason"], 3)
        self.assertEqual(len(usage["sessions"]), 1)
        populated = [entry for entry in cache["codex"].values() if entry.get("days")]
        self.assertEqual(len(populated), 1)
        self.assertEqual(populated[0]["event_count"], 2)
        self.assertNotIn("events", populated[0])

    def test_moving_session_to_archive_preserves_total_without_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active_dir = root / "sessions"
            archive_dir = root / "archived_sessions"
            active_dir.mkdir()
            archive_dir.mkdir()
            active = active_dir / "rollout-moved.jsonl"
            content = "\n".join([
                self.session_meta("moved"),
                self.token_count(
                    "2024-01-08T00:01:00Z", (100, 80, 5, 2), (100, 80, 5, 2)),
            ]) + "\n"
            active.write_text(content, encoding="utf-8")
            cache = {"v": USAGE._SCAN_CACHE_VERSION}

            with mock.patch.object(USAGE, "CODEX_DIR", str(active_dir)), \
                 mock.patch.object(USAGE, "CODEX_ARCHIVED_DIR", str(archive_dir)), \
                 mock.patch.object(USAGE, "fetch_codex_live_limits", return_value=None):
                before = USAGE.scan_codex(self.bounds(), cache)
                archived = archive_dir / active.name
                active.rename(archived)
                after = USAGE.scan_codex(self.bounds(), cache)

        self.assertEqual(before["ranges"]["all"]["in"], 100)
        self.assertEqual(after["ranges"]["all"]["in"], 100)
        self.assertEqual(len(after["ranges"]["all"]["sessions"]), 1)
        self.assertEqual(set(cache["codex"]), {str(archived.resolve())})


class ScanCacheMigrationTests(unittest.TestCase):
    def test_v19_codex_events_move_to_sidecar_cache(self):
        first = event(
            "2026-07-10T00:00:00+00:00",
            "2026-07-10",
            (100, 80, 5, 2),
            (100, 80, 5, 2),
            1.0,
        )
        second = event(
            "2026-07-10T00:01:00+00:00",
            "2026-07-10",
            (150, 120, 8, 3),
            (50, 40, 3, 1),
            0.5,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "rollout-migrate.jsonl"
            source.touch()
            cache_path = root / "scan-cache.json"
            cache_path.write_text(json.dumps({
                "v": 19,
                "codex": {
                    str(source): {
                        "sig": "legacy",
                        "events": [first, second],
                        "days": {},
                        "session_id": "migrate",
                        "model_version": 2,
                        "parsed_size": 0,
                    },
                },
            }), encoding="utf-8")

            with mock.patch.object(USAGE, "_SCAN_CACHE_FILE", str(cache_path)):
                cache = USAGE._load_scan_cache()
                migrated = USAGE._codex_migrate_event_cache(cache["codex"])
                cache["_dirty"] = True
                USAGE._save_scan_cache(cache)
                stored = json.loads(cache_path.read_text(encoding="utf-8"))
                sidecar = USAGE._codex_event_cache_path(str(source))
                cached_events = list(USAGE._iter_codex_cached_events(str(source)))

        entry = stored["codex"][str(source)]
        self.assertTrue(migrated)
        self.assertEqual(stored["v"], USAGE._SCAN_CACHE_VERSION)
        self.assertNotIn("events", entry)
        self.assertEqual(entry["event_count"], 2)
        self.assertEqual(entry["drop_count"], 0)
        self.assertEqual(entry["deduped_days"]["2026-07-10"]["in"], 150)
        self.assertEqual(cached_events, [first, second])
        self.assertTrue(sidecar.endswith(".jsonl"))

    def test_v13_cache_is_invalidated_for_session_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scan-cache.json"
            path.write_text(json.dumps({"v": 13, "codex": {"stale": {}}}), encoding="utf-8")
            old_path = USAGE._SCAN_CACHE_FILE
            USAGE._SCAN_CACHE_FILE = str(path)
            try:
                cache = USAGE._load_scan_cache()
            finally:
                USAGE._SCAN_CACHE_FILE = old_path

        self.assertEqual(cache["v"], USAGE._SCAN_CACHE_VERSION)
        self.assertTrue(cache["_dirty"])
        self.assertNotIn("codex", cache)


class CodexTokenLineReaderTests(unittest.TestCase):
    def test_model_after_large_permission_profile_across_chunks(self):
        context = json.dumps({"timestamp": "2026-09-23T01:00:00Z", "type": "turn_context",
                              "payload": {"permission_profile": {"entries": "x" * 12_000,
                                                                 "model": "nested-decoy"},
                                          "model": "gpt-6-astra"}}).encode()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout.jsonl"
            path.write_bytes(context + b"\n")
            self.assertEqual(list(USAGE._iter_codex_usage_records(path, chunk_size=1024)),
                             [("model", "gpt-6-astra")])

    def test_accepts_reordered_top_level_fields_and_ignores_nested_type_decoys(self):
        model = json.dumps({
            "payload": {"model": "gpt-5.5"},
            "ordinal": 4,
            "metadata": {"type": "event_msg"},
            "type": "turn_context",
            "timestamp": "2026-07-13T01:02:02Z",
        }, separators=(",", ":")).encode()
        token = json.dumps({
            "payload": {"type": "token_count", "info": {}},
            "ordinal": 5,
            "type": "event_msg",
            "timestamp": "2026-07-13T01:02:03Z",
        }, separators=(",", ":")).encode()
        decoy = json.dumps({
            "timestamp": "2026-07-13T01:02:04Z",
            "ordinal": 6,
            "type": "response_item",
            "payload": {
                "content": {
                    "type": "event_msg",
                    "payload": {"type": "token_count"},
                },
            },
        }, separators=(",", ":")).encode()

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-reordered-records.jsonl"
            path.write_bytes(b"\n".join([model, token, decoy]) + b"\n")
            records = list(USAGE._iter_codex_usage_records(path, chunk_size=7))

        self.assertEqual(records, [("model", "gpt-5.5"), ("token", token)])

    def test_accepts_mixed_legacy_and_ordinal_token_and_model_records(self):
        legacy_model = json.dumps({
            "timestamp": "2026-07-13T01:02:00Z",
            "type": "turn_context",
            "payload": {"model": "gpt-5.4"},
        }).encode()
        legacy_token = json.dumps({
            "timestamp": "2026-07-13T01:02:01Z",
            "type": "event_msg",
            "payload": {"type": "token_count", "info": {}},
        }).encode()
        ordinal_model = json.dumps({
            "timestamp": "2026-07-13T01:02:02Z",
            "ordinal": 2,
            "type": "turn_context",
            "payload": {"model": "gpt-5.5"},
        }).encode()
        ordinal_token = json.dumps({
            "timestamp": "2026-07-13T01:02:03Z",
            "ordinal": 3,
            "type": "event_msg",
            "payload": {"type": "token_count", "info": {}},
        }).encode()

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-mixed-records.jsonl"
            path.write_bytes(b"\n".join([
                legacy_model, legacy_token, ordinal_model, ordinal_token,
            ]) + b"\n")
            records = list(USAGE._iter_codex_usage_records(path, chunk_size=13))

        self.assertEqual(records, [
            ("model", "gpt-5.4"),
            ("token", legacy_token),
            ("model", "gpt-5.5"),
            ("token", ordinal_token),
        ])

    def test_skips_large_unrelated_record_and_handles_chunk_boundaries(self):
        token = json.dumps({
            "timestamp": "2026-07-13T01:02:03Z",
            "type": "event_msg",
            "payload": {"type": "token_count", "info": {}},
        }).encode()
        unrelated = (
            b'{"timestamp":"2026-07-13T01:02:02Z","type":"response_item",'
            b'"payload":{"content":"mentions \\"token_count\\" '
            + b"x" * (2 * 1024 * 1024)
            + b'"}}\n'
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-large.jsonl"
            path.write_bytes(unrelated + token)
            lines = list(USAGE._iter_codex_token_lines(
                path, chunk_size=17, header_limit=512
            ))

        self.assertEqual(lines, [token])

    def test_accepts_compact_json(self):
        token = json.dumps({
            "timestamp": "2026-07-13T01:02:03Z",
            "type": "event_msg",
            "payload": {"type": "token_count", "info": {}},
        }, separators=(",", ":")).encode()

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-compact.jsonl"
            path.write_bytes(token + b"\n")
            lines = list(USAGE._iter_codex_token_lines(path, chunk_size=11))

        self.assertEqual(lines, [token])

    def test_extracts_model_from_large_ordinal_context_without_buffering_full_line(self):
        context = (
            b'{"timestamp":"2026-07-13T01:02:02Z","ordinal":2,"type":"turn_context",'
            b'"payload":{"model":"gpt-5.4","instructions":"' + b"x" * (2 * 1024 * 1024) + b'"}}\n'
        )
        token = json.dumps({
            "timestamp": "2026-07-13T01:02:03Z",
            "type": "event_msg",
            "payload": {"type": "token_count", "info": {}},
        }, separators=(",", ":")).encode()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-model.jsonl"
            path.write_bytes(context + token)
            records = list(USAGE._iter_codex_usage_records(path, chunk_size=19))

        self.assertEqual(records, [("model", "gpt-5.4"), ("token", token)])


if __name__ == "__main__":
    unittest.main()
