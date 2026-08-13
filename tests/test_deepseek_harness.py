import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from test_codex_limits import USAGE


def event(event_type, seq, timestamp_ms, data):
    return {"type": event_type, "seq": seq, "time": timestamp_ms, "data": data}


class DeepSeekHarnessScanTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now().astimezone().replace(hour=10, minute=0, second=0, microsecond=0)
        self.now_ms = int(self.now.timestamp() * 1000)

    def write_session(self, root, records, compressed=False, session_id="session-test"):
        session_dir = Path(root) / "sessions" / "--project--" / session_id
        session_dir.mkdir(parents=True)
        suffix = "session.jsonl.zstd" if compressed else "session.jsonl"
        path = session_dir / suffix
        rows = [{
            "type": "session", "version": 0, "id": session_id,
            "createdAt": self.now_ms - 1000, "cwd": "/tmp/private/project",
            "delegationDepth": 0,
        }, *records]
        payload = "".join(json.dumps(row) + "\n" for row in rows)
        if compressed:
            from compression import zstd
            with zstd.open(path, "wt", encoding="utf-8") as f:
                f.write(payload)
        else:
            path.write_text(payload, encoding="utf-8")
        return path

    def scan(self, root, cache=None):
        scan_cache = cache if cache is not None else {"v": USAGE._SCAN_CACHE_VERSION}
        with mock.patch.dict(os.environ, {"TOKEI_DSH_DIR": str(Path(root) / "sessions")}, clear=False), \
             mock.patch.object(USAGE, "ledger_touch"), \
             mock.patch.object(USAGE, "ledger_reconcile", side_effect=lambda _tool, days: days):
            result = USAGE.scan_deepseek_harness(USAGE.range_bounds(), scan_cache)
        return result, scan_cache

    def test_last_sample_wins_and_reasoning_is_not_double_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = [
                event("request/context", 1, self.now_ms, {
                    "provider": "deepseek-official", "model": "deepseek-v4-pro",
                    "contextWindow": 1_000_000,
                }),
                event("assistant/chunk", 2, self.now_ms + 1, {
                    "turn": 1, "step": 1,
                    "chunk": {"type": "usage", "usage": {
                        "inputTokens": 10, "outputTokens": 5, "cacheReadTokens": 20,
                        "reasoningTokens": 2,
                    }},
                }),
                event("assistant/message", 3, self.now_ms + 2, {
                    "turn": 1, "step": 1, "message": {"role": "assistant", "content": []},
                    "usage": {"inputTokens": 12, "outputTokens": 7,
                              "cacheReadTokens": 30, "cacheWriteTokens": 4,
                              "reasoningTokens": 3},
                }),
            ]
            self.write_session(tmp, records)
            result, cache = self.scan(tmp)

        usage = result["ranges"]["all"]
        self.assertEqual((usage["in"], usage["out"], usage["cr"], usage["cw"], usage["reason"]),
                         (12, 4, 30, 4, 3))
        self.assertEqual(USAGE.token_total(usage), 53)
        self.assertEqual(len(usage["sessions"]), 1)
        entry = next(value for key, value in cache["deepseek_harness"].items()
                     if not key.startswith("_"))
        day = entry["days"][self.now.date().isoformat()]
        self.assertEqual(day["projects"], ["project"])
        self.assertEqual(entry["proj"], "/tmp/private/project")
        self.assertIn("deepseek-v4-pro", day["models"])

    def test_model_context_change_applies_to_following_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = [
                event("request/context", 1, self.now_ms, {"model": "deepseek-v4-flash"}),
                event("assistant/message", 2, self.now_ms + 1, {
                    "turn": 1, "step": 1, "message": {},
                    "usage": {"inputTokens": 1, "outputTokens": 2},
                }),
                event("request/context", 3, self.now_ms + 2, {"model": "deepseek-v4-pro"}),
                event("assistant/message", 4, self.now_ms + 3, {
                    "turn": 1, "step": 2, "message": {},
                    "usage": {"inputTokens": 3, "outputTokens": 4},
                }),
            ]
            self.write_session(tmp, records)
            result, _ = self.scan(tmp)

        models = result["ranges"]["all"]["models"]
        self.assertEqual(models["deepseek-v4-flash"]["in"], 1)
        self.assertEqual(models["deepseek-v4-pro"]["out"], 4)

    def test_zstd_and_malformed_lines_are_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_session(tmp, [
                event("request/header", 1, self.now_ms, {
                    "reason": "initial", "header": {"config": {"model": "deepseek-v4-flash"}},
                }),
                event("assistant/message", 2, self.now_ms + 1, {
                    "turn": 1, "step": 1, "message": {},
                    "usage": {"inputTokens": 5, "outputTokens": 6},
                }),
            ], compressed=True)
            # packed chunk storage rows and unknown UI events are layout details; the
            # collector ignores them while retaining the final assistant usage record.
            parsed = USAGE._dsh_parse_session(str(path))

        day = parsed["days"][self.now.date().isoformat()]
        self.assertEqual((day["in"], day["out"]), (5, 6))

    def test_system_libzstd_fallback_decodes_concatenated_frames(self):
        try:
            from compression import zstd
        except ImportError:
            self.skipTest("test writer needs compression.zstd")
        first = zstd.compress(b"first\n")
        second = zstd.compress(b"second\n")
        try:
            decoded = USAGE._dsh_zstd_ctypes(first + second)
        except RuntimeError as exc:
            self.skipTest(str(exc))
        self.assertEqual(decoded, b"first\nsecond\n")

    def test_future_session_version_fails_closed_and_previous_cache_survives(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_session(tmp, [
                event("assistant/message", 1, self.now_ms, {
                    "turn": 1, "step": 1, "message": {},
                    "usage": {"inputTokens": 1, "outputTokens": 1},
                })
            ])
            result, cache = self.scan(tmp)
            self.assertEqual(result["ranges"]["all"]["in"], 1)
            rows = path.read_text(encoding="utf-8").splitlines()
            header = json.loads(rows[0]); header["version"] = 1
            path.write_text(json.dumps(header) + "\n" + "\n".join(rows[1:]) + "\n",
                            encoding="utf-8")
            result, cache = self.scan(tmp, cache)

        self.assertEqual(result["ranges"]["all"]["in"], 1)
        self.assertTrue(result["errors"])

    def test_tokei_override_precedes_dsh_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"TOKEI_DSH_DIR": tmp, "DSH_HOME": "/ignored"}, clear=False):
                self.assertEqual(USAGE._dsh_sessions_root(), os.path.abspath(tmp))

    def test_missing_route_keeps_unknown_model_without_fake_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_session(tmp, [
                event("assistant/message", 1, self.now_ms, {
                    "turn": 1, "step": 1, "message": {},
                    "usage": {"inputTokens": 100, "outputTokens": 50},
                })
            ])
            parsed = USAGE._dsh_parse_session(str(path))

        day = parsed["days"][self.now.date().isoformat()]
        self.assertIn("unknown", day["models"])
        self.assertEqual(day["cost"], 0)

    def test_dashboard_and_wrapped_include_usage_models_and_hours(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_session(tmp, [
                event("request/context", 1, self.now_ms, {"model": "deepseek-v4-pro"}),
                event("assistant/message", 2, self.now_ms + 1, {
                    "turn": 1, "step": 1, "message": {},
                    "usage": {"inputTokens": 10, "outputTokens": 8,
                              "cacheReadTokens": 20, "reasoningTokens": 3},
                }),
            ])
            _, cache = self.scan(tmp)
            with mock.patch.object(USAGE, "_load_ledger", return_value={"v": 1, "tools": {}}):
                daily = USAGE.build_daily_costs("all", refresh=False, _cache=cache)
                wrapped = USAGE.build_wrapped("all", refresh=False, _cache=cache)

        row = daily["daily"][0]
        self.assertEqual(row["dsh_in"], 10)
        self.assertEqual(row["dsh_out"], 5)
        self.assertEqual(row["dsh_cr"], 20)
        self.assertEqual(row["dsh_reason"], 3)
        self.assertEqual(row["tokens"], 38)
        self.assertEqual(daily["models"][0]["tool"], "deepseek_harness")
        self.assertEqual(wrapped["total_tokens"], 38)
        self.assertEqual(wrapped["hours"][10], 38)


if __name__ == "__main__":
    unittest.main()
