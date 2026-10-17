import json
import tempfile
import unittest
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
            {"type": "session.shutdown", "data": shutdown_data},
        ]
        path = session_dir / "events.jsonl"
        path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
        return path

    def scan(self, root, cache=None):
        old = USAGE.COPILOT_DIR
        USAGE.COPILOT_DIR = str(root)
        scan_cache = cache if cache is not None else {"v": USAGE._SCAN_CACHE_VERSION}
        try:
            return USAGE.scan_copilot(USAGE.range_bounds(), scan_cache), scan_cache
        finally:
            USAGE.COPILOT_DIR = old

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
            self.assertEqual(usage["in"], 1000)
            self.assertEqual(usage["out"], 200)
            self.assertEqual(usage["cr"], 50)
            self.assertEqual(usage["cw"], 10)
            self.assertEqual(usage["reason"], 30)
            self.assertAlmostEqual(usage["credits"], 2.0)
            self.assertEqual(len(usage["models"]), 1)
            self.assertEqual(cache["copilot"][str(path)]["proj"], "/tmp/copilot-project")

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


if __name__ == "__main__":
    unittest.main()
