import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from urllib.parse import quote

from test_codex_limits import USAGE


def write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def append_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record) + "\n")


def usage_line(sid, timestamp, loop, prompt, cached, completion, reasoning):
    return {
        "ts": timestamp,
        "msg": "shell.turn.inference_done",
        "sid": sid,
        "ctx": {
            "loop_index": loop,
            "prompt_tokens": prompt,
            "cached_prompt_tokens": cached,
            "completion_tokens": completion,
            "reasoning_tokens": reasoning,
        },
    }


class GrokUsageTests(unittest.TestCase):
    def setUp(self):
        self.old_home = USAGE.GROK_HOME
        self.old_dir = USAGE.GROK_DIR
        self.old_log = USAGE.GROK_LOG
        self.old_cache = USAGE._SCAN_CACHE_FILE

    def tearDown(self):
        USAGE.GROK_HOME = self.old_home
        USAGE.GROK_DIR = self.old_dir
        USAGE.GROK_LOG = self.old_log
        USAGE._SCAN_CACHE_FILE = self.old_cache

    def configure(self, root):
        USAGE.GROK_HOME = str(root)
        USAGE.GROK_DIR = str(root / "sessions")
        USAGE.GROK_LOG = str(root / "logs" / "unified.jsonl")
        USAGE._SCAN_CACHE_FILE = str(root / "scan-cache.json")

    def create_session(self, root, sid, project, timestamp, with_signals=True):
        session = root / "sessions" / quote(project, safe="") / sid
        session.mkdir(parents=True)
        write_json(session / "summary.json", {
            "info": {"id": sid},
            "created_at": timestamp,
            "updated_at": timestamp,
            "current_model_id": "grok-4.5",
        })
        if with_signals:
            write_json(session / "signals.json", {
                "turnCount": 3,
                "toolCallCount": 2,
                "sessionDurationSeconds": 60,
                "contextTokensUsed": 1000,
                "contextWindowTokens": 10000,
                "errorCount": 0,
                "toolFailureCount": 0,
                "cancellationCount": 0,
                "latencySampleCount": 2,
                "avgTimeToFirstTokenMs": 500,
                "avgResponseTimeMs": 1500,
            })
        append_jsonl(session / "events.jsonl", [
            {"type": "turn_started"},
            {"type": "turn_ended", "outcome": "completed"},
            {"type": "turn_ended", "outcome": "cancelled"},
            {"type": "turn_ended", "outcome": "error"},
        ])
        return session

    def test_real_usage_is_split_deduplicated_and_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".grok"
            self.configure(root)
            now = datetime.now().astimezone().replace(microsecond=0).isoformat()
            sid = "019f-test-session"
            self.create_session(root, sid, "/tmp/grok-project", now)
            log = root / "logs" / "unified.jsonl"
            first = usage_line(sid, now, 1, 1000, 800, 100, 30)
            second = usage_line(sid, now, 2, 500, 100, 50, 10)
            append_jsonl(log, [first, first, second])

            cache = {"v": USAGE._SCAN_CACHE_VERSION}
            result = USAGE.scan_grok(USAGE.range_bounds(), cache)
            with mock.patch.object(
                USAGE, "_grok_usage_record",
                side_effect=AssertionError("unchanged Grok log was reparsed"),
            ):
                cached = USAGE.scan_grok(USAGE.range_bounds(), cache)

            later = (datetime.now().astimezone() + timedelta(seconds=1)).replace(microsecond=0).isoformat()
            append_jsonl(log, [usage_line(sid, later, 3, 200, 150, 20, 5)])
            appended = USAGE.scan_grok(USAGE.range_bounds(), cache)

        usage = result["ranges"]["all"]
        self.assertEqual(usage["in"], 600)
        self.assertEqual(usage["cr"], 900)
        self.assertEqual(usage["out"], 110)
        self.assertEqual(usage["reason"], 40)
        self.assertEqual(usage["usage_calls"], 2)
        self.assertEqual(usage["usage_sessions"], {sid})
        self.assertEqual(usage["sessions"], {sid})
        self.assertEqual(usage["errors"], 1)
        self.assertEqual(usage["cancellations"], 1)
        self.assertEqual(cached["ranges"]["all"]["usage_calls"], 2)
        self.assertEqual(appended["ranges"]["all"]["usage_calls"], 3)
        self.assertEqual(len(cache["grok_usage"]["entries"]), 3)
        self.assertEqual(usage["models"]["grok-4.5"]["in"], 600)

    def test_daily_wrapped_and_projects_use_real_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".grok"
            self.configure(root)
            now = datetime.now().astimezone().replace(microsecond=0)
            timestamp = now.isoformat()
            day = now.date().isoformat()
            sid = "019f-project-session"
            project = "/tmp/grok-build-project"
            self.create_session(root, sid, project, timestamp, with_signals=False)
            entry = USAGE._grok_usage_record(usage_line(sid, timestamp, 1, 1000, 800, 100, 30))
            cache = {
                "v": USAGE._SCAN_CACHE_VERSION,
                "grok_usage": {"entries": [entry]},
            }
            Path(USAGE._SCAN_CACHE_FILE).write_text(json.dumps(cache), encoding="utf-8")

            daily = USAGE.build_daily_costs("all", refresh=False)
            wrapped = USAGE.build_wrapped("all", refresh=False)
            output = io.StringIO()
            with mock.patch.object(USAGE, "compute"), contextlib.redirect_stdout(output):
                USAGE.projects()
            projects = json.loads(output.getvalue())

        self.assertEqual(daily["daily"][0]["date"], day)
        self.assertEqual(daily["daily"][0]["g_in"], 200)
        self.assertEqual(daily["daily"][0]["g_cr"], 800)
        self.assertEqual(daily["daily"][0]["g_out"], 70)
        self.assertEqual(daily["daily"][0]["g_reason"], 30)
        self.assertEqual(daily["daily"][0]["tokens"], 1100)
        self.assertEqual(daily["models"][0]["tool"], "grok")
        self.assertEqual(wrapped["total_tokens"], 1100)
        self.assertEqual(wrapped["hours"][now.hour], 1100)
        project_row = next(row for row in projects if row["path"] == project)
        self.assertEqual(project_row["sessions"], 1)
        self.assertEqual(project_row["tokens"], 1100)
        self.assertEqual(project_row["top_model"], "Grok 4.5 (Grok Build)")

    def test_usage_is_classified_by_inference_timestamp_not_session_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".grok"
            self.configure(root)
            now = datetime.now().astimezone().replace(microsecond=0)
            yesterday = now - timedelta(days=1)
            sid = "019f-cross-day-session"
            self.create_session(root, sid, "/tmp/cross-day", now.isoformat(), with_signals=False)
            append_jsonl(root / "logs" / "unified.jsonl", [
                usage_line(sid, yesterday.isoformat(), 1, 2000, 1000, 200, 50),
                usage_line(sid, now.isoformat(), 2, 1000, 800, 100, 30),
            ])

            result = USAGE.scan_grok(USAGE.range_bounds(), {"v": USAGE._SCAN_CACHE_VERSION})

        today = result["ranges"]["today"]
        previous = result["ranges"]["yesterday"]
        self.assertEqual(today["in"] + today["cr"] + today["out"] + today["reason"], 1100)
        self.assertEqual(previous["in"] + previous["cr"] + previous["out"] + previous["reason"], 2200)
        self.assertEqual(today["usage_sessions"], {sid})
        self.assertEqual(previous["usage_sessions"], {sid})
        self.assertEqual(today["sessions"], {sid})
        self.assertEqual(previous["sessions"], {sid})


if __name__ == "__main__":
    unittest.main()
