import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == "darwin", "macOS Swift integration")
class LocalOutputThroughputTests(unittest.TestCase):
    def test_concurrency_window_and_local_sources(self):
        # All-time differs from today's output: the selected date is not a live counter.
        empty = dict(hit=0, **{"in": 900000}, out=1, cached=900000, cr=900000, cw=900000,
                     reason=30, thoughts=20, cost=0, sessions=0, models=[],
                     tasks=0, completed=0, failed=0, tokens=0, requests=0, credits=0)
        ranges = {k: dict(empty) for k in ("today", "yesterday", "week", "last_week", "month", "year")}
        ranges["all"] = dict(empty, out=100)
        tools = ("claude codex gemini grok qoder qoderwork qodercli qodercli_cn hermes "
                 "openclaw zcode mimocode pi prime_agent workbuddy workbuddy_ai codebuddy "
                 "deepseek_harness opencode qwencode kimicode musecode cmdcode devin minimax").split()
        payload = {tool: {"ranges": ranges} for tool in tools}
        payload["claude"].update(session_name="", session_total=0)
        payload["codex"]["reserve_ranges"] = ranges
        for provider in ("cursor", "sub2api", "grok_bot"):
            payload[provider] = {"usage": {"ranges": ranges}, "quota": {"usage": {"ranges": ranges}}}
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / "throughput-check"
            fixture = Path(temp) / "fixture.json"
            fixture.write_text(json.dumps(payload))
            source = ROOT / "Tokei/Sources/Tokei"
            result = subprocess.run([
                "swiftc", "-parse-as-library", str(source / "Model.swift"),
                str(source / "L10n.swift"), str(source / "LocalOutputThroughput.swift"),
                str(ROOT / "tests/swift/LocalOutputThroughputCheck.swift"), "-o", str(binary),
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary), str(fixture)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("local output throughput checks passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
