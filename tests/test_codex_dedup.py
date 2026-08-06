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
    def session_meta(self, sid, forked_from_id=None):
        payload = {
            "session_id": forked_from_id or sid,
            "id": sid,
            "cwd": "/tmp/project",
            "model_provider": "custom",
        }
        if forked_from_id:
            payload["forked_from_id"] = forked_from_id
        return json.dumps({
            "timestamp": "2024-01-08T00:00:00Z",
            "type": "session_meta",
            "payload": payload,
        })

    def test_session_meta_prefers_own_id_over_parent_session_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-child.jsonl"
            path.write_text(self.session_meta("child", "parent") + "\n", encoding="utf-8")
            session_id, parent_id = USAGE._codex_session_meta(path)

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
            session_id, parent_id = USAGE._codex_session_meta(path)

        self.assertEqual(session_id, "child")
        self.assertEqual(parent_id, "parent")

    def token_count(self, ts, total, last, rate_limits=None):
        payload = {
            "timestamp": ts,
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
        }
        if rate_limits is not None:
            payload["payload"]["rate_limits"] = rate_limits
        return json.dumps(payload)

    def turn_context(self, ts, model):
        return json.dumps({
            "timestamp": ts,
            "type": "turn_context",
            "payload": {"model": model, "cwd": "/tmp/project"},
        })

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

    def test_scan_ignores_runtime_quota_label_for_model_attribution(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-runtime-label.jsonl"
            path.write_text("\n".join([
                self.session_meta("runtime-label"),
                self.turn_context("2024-01-08T00:00:00Z", "gpt-5.5"),
                self.token_count(
                    "2024-01-08T00:01:00Z",
                    (100, 80, 10, 4),
                    (100, 80, 10, 4),
                    {"limit_name": "GPT-5.3-Codex-Spark"},
                ),
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

        models = result["ranges"]["all"]["models"]
        self.assertIn("openai/gpt-5.5", models)
        self.assertNotIn("codex-runtime/gpt-5-3-codex-spark", models)

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

    def test_extracts_model_without_buffering_following_large_content(self):
        context = (
            b'{"timestamp":"2026-07-13T01:02:02Z","type":"turn_context",'
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
