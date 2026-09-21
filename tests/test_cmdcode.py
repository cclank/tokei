import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from test_codex_limits import USAGE


def _ts(amount):
    return amount.astimezone().isoformat()


def assistant_record(mid, model, usage, timestamp):
    return {
        "type": "message",
        "id": mid,
        "parentId": None,
        "timestamp": timestamp,
        "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
        "usage": usage,
        "model": model,
    }


def usage_record(inp, out, cr, cw, cost):
    return {"inputTokens": inp, "outputTokens": out,
            "cacheReadTokens": cr, "cacheWriteTokens": cw, "costUsd": cost}


class CommandCodeScanTests(unittest.TestCase):
    def create_session(self, root):
        project = "/tmp/cmdcode-project"
        sid = "sess-cmd-1"
        slug = "users-tmp-cmdcode-project"
        session_file = Path(root) / "projects" / slug / f"{sid}.jsonl"
        session_file.parent.mkdir(parents=True)
        now = datetime.now().astimezone().replace(minute=0, second=0, microsecond=0)
        timestamp = _ts(now)
        records = [
            {"type": "session", "id": sid, "timestamp": timestamp, "cwd": project},
            assistant_record("msg-1", "meta/muse-spark-1.3-contributor",
                             usage_record(20000, 500, 15000, 100, 0.01), timestamp),
            # 同一条 message.id 是重放,必须去重。
            assistant_record("msg-1", "meta/muse-spark-1.3-contributor",
                             usage_record(11111, 111, 0, 0, 9.99), timestamp),
            assistant_record("msg-2", "meta/muse-spark-1.3-contributor",
                             usage_record(10000, 200, 1000, 50, 0.005), timestamp),
            # user 消息没有用量,不能计入。
            {"type": "message", "id": "msg-user", "timestamp": timestamp,
             "message": {"role": "user", "content": "hi"}},
        ]
        session_file.write_text(
            "\n".join(json.dumps(record) for record in records) + "\n{broken\n",
            encoding="utf-8",
        )
        return session_file, now, project, sid

    def scan(self, root, cache=None):
        old_root = USAGE.CMDCODE_DIR
        USAGE.CMDCODE_DIR = str(root)
        scan_cache = cache if cache is not None else {"v": USAGE._SCAN_CACHE_VERSION}
        try:
            result = USAGE.scan_cmdcode(USAGE.range_bounds(), scan_cache)
        finally:
            USAGE.CMDCODE_DIR = old_root
        return result, scan_cache

    def test_assistant_usage_splits_cache_and_dedupes_replays(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_file, now, project, sid = self.create_session(tmp)
            result, cache = self.scan(tmp)

            with mock.patch.object(
                USAGE, "_scan_cmdcode_session",
                side_effect=AssertionError("unchanged session was rescanned"),
            ):
                self.scan(tmp, cache=cache)

        usage = result["ranges"]["all"]
        self.assertEqual(usage["in"], 30000)
        self.assertEqual(usage["out"], 700)
        self.assertEqual(usage["cr"], 16000)
        self.assertEqual(usage["cw"], 150)
        self.assertEqual(USAGE.token_total(usage), 46850)
        self.assertEqual(usage["sessions"], {sid})
        self.assertAlmostEqual(usage["cost"], 0.015, places=9)
        models = usage["models"]
        self.assertEqual(set(models), {"meta/muse-spark-1.3-contributor"})
        self.assertEqual(models["meta/muse-spark-1.3-contributor"]["in"], 30000)
        self.assertAlmostEqual(models["meta/muse-spark-1.3-contributor"]["cost"], 0.015, places=9)
        entry = cache["cmdcode"][str(session_file)]
        self.assertEqual(entry["sid"], sid)
        self.assertEqual(entry["proj"], project)
        self.assertEqual(entry["parser_version"], USAGE._CMDCODE_PARSER_VERSION)
        self.assertEqual(entry["days"][now.date().isoformat()]["hours"][now.hour],
                         46850)

    def test_missing_source_clears_stale_cache(self):
        stale = {
            "v": USAGE._SCAN_CACHE_VERSION,
            "cmdcode": {"/old/session.jsonl": {"sig": "old", "days": {}}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            result, cache = self.scan(tmp, cache=stale)

        self.assertEqual(result["ranges"]["all"]["in"], 0)
        self.assertEqual(cache["cmdcode"], {})
        self.assertTrue(cache["_dirty"])

    def test_utc_zulu_timestamp_parses(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid = "sess-zulu"
            session_file = Path(tmp) / "projects" / "slug" / f"{sid}.jsonl"
            session_file.parent.mkdir(parents=True)
            now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
            session_file.write_text("\n".join(json.dumps(record) for record in [
                {"type": "session", "id": sid,
                 "timestamp": now.isoformat().replace("+00:00", "Z"),
                 "cwd": "/tmp/zulu-project"},
                assistant_record(
                    "msg-z", "meta/muse-spark-1.3-contributor",
                    usage_record(2000, 100, 500, 10, 0.001),
                    now.isoformat().replace("+00:00", "Z")),
            ]) + "\n", encoding="utf-8")
            result, cache = self.scan(tmp)

        usage = result["ranges"]["all"]
        self.assertEqual(usage["in"], 2000)
        self.assertEqual(usage["cr"], 500)
        self.assertEqual(usage["sessions"], {sid})
        self.assertEqual(cache["cmdcode"][str(session_file)]["proj"], "/tmp/zulu-project")

    def test_sidecars_are_not_read_as_transcripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "slug"
            project.mkdir(parents=True)
            transcript = project / "session-1.jsonl"
            sidecars = [
                project / "session-1.checkpoints.jsonl",
                project / "session-1.prompts.jsonl",
                project / "hooks-audit-session-1.jsonl",
            ]
            transcript.write_text("{}\n")
            for path in sidecars:
                path.write_text("{}\n")
            with mock.patch.object(USAGE, "CMDCODE_DIR", tmp):
                self.assertEqual(USAGE._cmdcode_session_files(), [str(transcript)])

    def test_cloned_transcript_events_are_counted_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_file, _, _, sid = self.create_session(tmp)
            clone = session_file.with_name("sess-clone.jsonl")
            clone.write_text(session_file.read_text().replace(sid, "sess-clone", 1))
            result, cache = self.scan(tmp)

        usage = result["ranges"]["all"]
        self.assertEqual(USAGE.token_total(usage), 46850)
        self.assertEqual(len(usage["sessions"]), 1)
        self.assertEqual(len(cache["cmdcode"]), 2)

    def test_flat_messages_and_model_changes_are_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "projects" / "slug" / "legacy.jsonl"
            path.parent.mkdir(parents=True)
            timestamp = datetime.now().astimezone().replace(microsecond=0).isoformat()
            records = [
                {"type": "session", "sessionId": "legacy-session", "cwd": "/tmp/legacy"},
                {"type": "model_change", "model": "deepseek/deepseek-chat", "timestamp": timestamp},
                {"role": "assistant", "id": "legacy-message", "sessionId": "legacy-session",
                 "timestamp": timestamp, "usage": usage_record(10, 2, 3, 4, 0.1)},
            ]
            path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
            result, cache = self.scan(tmp)

        usage = result["ranges"]["all"]
        self.assertEqual(USAGE.token_total(usage), 19)
        self.assertEqual(usage["sessions"], {"legacy-session"})
        self.assertEqual(set(usage["models"]), {"deepseek/deepseek-chat"})
        self.assertEqual(cache["cmdcode"][str(path)]["proj"], "/tmp/legacy")

    def test_cost_only_is_kept_and_non_finite_cost_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "projects" / "slug" / "costs.jsonl"
            path.parent.mkdir(parents=True)
            timestamp = datetime.now().astimezone().replace(microsecond=0).isoformat()
            records = [
                {"type": "session", "id": "costs", "cwd": "/tmp/costs"},
                assistant_record("cost-only", "model-a", usage_record(0, 0, 0, 0, 0.25), timestamp),
                assistant_record("nan", "model-a", usage_record(1, 0, 0, 0, "NaN"), timestamp),
                assistant_record("infinite", "model-a", usage_record(1, 0, 0, 0, "Infinity"), timestamp),
            ]
            path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
            result, _ = self.scan(tmp)

        usage = result["ranges"]["all"]
        self.assertEqual(usage["in"], 2)
        self.assertAlmostEqual(usage["cost"], 0.25, places=9)
        self.assertTrue(usage["cost"] < 1)

    def test_ledger_retains_cmdcode_cost_after_source_deletion(self):
        original_ledger = USAGE._LEDGER_CACHE.copy()
        try:
            USAGE._LEDGER_CACHE.update({
                "data": {"v": USAGE._LEDGER_VERSION, "tools": {}}, "dirty": False,
            })
            with tempfile.TemporaryDirectory() as tmp:
                session_file, now, _, _ = self.create_session(tmp)
                _, cache = self.scan(tmp)
                session_file.unlink()
                result, cache = self.scan(tmp, cache=cache)
                daily = USAGE.build_daily_costs(refresh=False, _cache=cache)

            day = now.date().isoformat()
            self.assertAlmostEqual(result["ranges"]["all"]["cost"], 0.015, places=9)
            self.assertEqual(
                next(item for item in daily["daily"] if item["date"] == day)["cmdcode"],
                round(0.015, 2),
            )
        finally:
            USAGE._LEDGER_CACHE.clear()
            USAGE._LEDGER_CACHE.update(original_ledger)


if __name__ == "__main__":
    unittest.main()
