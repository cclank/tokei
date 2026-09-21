import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from test_codex_limits import USAGE


MODEL = "qwen3-coder-plus"


def request_record(record_id, session_id, input_tokens, cached=0, output=0, thoughts=0,
                   timestamp=None):
    dt = timestamp or datetime.now().astimezone().replace(hour=8, minute=0, second=0, microsecond=0)
    return {
        "schemaVersion": 1,
        "id": record_id,
        "timestamp": dt.isoformat(),
        "localDate": dt.date().isoformat(),
        "localMonth": dt.strftime("%Y-%m"),
        "sessionId": session_id,
        "model": MODEL,
        "authType": "openai",
        "source": "main",
        "inputTokens": input_tokens,
        "outputTokens": output,
        "cachedTokens": cached,
        "thoughtsTokens": thoughts,
        "totalTokens": input_tokens + output + thoughts,
        "apiDurationMs": 100,
    }


def summary_record(session_id, input_tokens, cached=0, output=0, thoughts=0, timestamp=None):
    dt = timestamp or datetime.now().astimezone().replace(hour=9, minute=0, second=0, microsecond=0)
    return {
        "version": 1,
        "sessionId": session_id,
        "timestamp": int(dt.timestamp() * 1000),
        "startTime": int(dt.timestamp() * 1000) - 1000,
        "project": "/tmp/qwen-project",
        "durationMs": 1000,
        "models": {
            MODEL: {
                "requests": 1,
                "inputTokens": input_tokens,
                "outputTokens": output,
                "cachedTokens": cached,
                "thoughtsTokens": thoughts,
                "totalTokens": input_tokens + output + thoughts,
            }
        },
        "tools": {"totalCalls": 0, "totalSuccess": 0, "totalFail": 0, "byName": {}},
        "files": {"linesAdded": 0, "linesRemoved": 0},
    }


class QwenCodeScanTests(unittest.TestCase):
    def scan(self, root, summary_records=None, request_records=None, cache=None):
        root = Path(root)
        usage_dir = root / "usage"
        usage_dir.mkdir(parents=True, exist_ok=True)
        if request_records is not None:
            month = datetime.now().astimezone().strftime("%Y-%m")
            (usage_dir / f"token-usage-{month}.jsonl").write_text(
                "\n".join(json.dumps(record) for record in request_records) + "\n",
                encoding="utf-8",
            )
        summary_path = root / "usage_record.jsonl"
        if summary_records is not None:
            summary_path.write_text(
                "\n".join(json.dumps(record) for record in summary_records) + "\n",
                encoding="utf-8",
            )

        old_summary = USAGE.QWEN_CODE_USAGE
        old_runtime_dirs = USAGE._qwen_runtime_dirs
        USAGE.QWEN_CODE_USAGE = str(summary_path)
        USAGE._qwen_runtime_dirs = lambda: [str(root)]
        scan_cache = cache if cache is not None else {"v": USAGE._SCAN_CACHE_VERSION}
        try:
            result = USAGE.scan_qwencode(USAGE.range_bounds(), scan_cache)
        finally:
            USAGE.QWEN_CODE_USAGE = old_summary
            USAGE._qwen_runtime_dirs = old_runtime_dirs
        return result, scan_cache

    def test_request_log_splits_cache_and_prices_thoughts_as_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, cache = self.scan(
                tmp,
                request_records=[request_record("request-1", "session-1", 100, 60, 10, 5)],
            )

        usage = result["ranges"]["all"]
        price = USAGE._raw_price(MODEL)
        expected_cost = (40 * price["in"] + 60 * price["cache_read"]
                         + 15 * price["out"]) / 1_000_000
        self.assertEqual(usage["in"], 40)
        self.assertEqual(usage["cr"], 60)
        self.assertEqual(usage["out"], 10)
        self.assertEqual(usage["reason"], 5)
        self.assertEqual(USAGE.token_total(usage), 115)
        self.assertEqual(len(usage["sessions"]), 1)
        self.assertAlmostEqual(usage["cost"], expected_cost, places=12)
        self.assertEqual(cache["qwencode"]["entries"][0]["hour"], 8)
        self.assertEqual(USAGE._resolve_id("Qwen3 Coder Plus"), "qwen/qwen3-coder-plus")

    def test_runtime_env_has_priority_over_default_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("QWEN_RUNTIME_DIR")
            os.environ["QWEN_RUNTIME_DIR"] = tmp
            try:
                self.assertEqual(USAGE._qwen_runtime_dirs(), [os.path.abspath(tmp)])
            finally:
                if old is None:
                    os.environ.pop("QWEN_RUNTIME_DIR", None)
                else:
                    os.environ["QWEN_RUNTIME_DIR"] = old

    def test_cost_recalculation_uses_exact_pretty_model_name(self):
        model = {
            "name": "Qwen3 Coder Plus",
            "in": 40,
            "out": 10,
            "cr": 60,
            "cw": 0,
            "reason": 5,
            "cost": 0.0,
        }
        result = {"qwencode": {"ranges": {"today": {"models": [model], "cost": 0.0}}}}

        USAGE._recalc_costs(result)

        price = USAGE._raw_price(MODEL)
        expected = (40 * price["in"] + 60 * price["cache_read"]
                    + 15 * price["out"]) / 1_000_000
        self.assertAlmostEqual(model["cost"], expected, places=6)
        self.assertEqual(model["pin"], price["in"])
        self.assertEqual(model["pout"], price["out"])

    def test_request_ids_are_deduped_but_distinct_calls_are_kept(self):
        records = [
            request_record("request-1", "session-1", 100),
            request_record("request-1", "session-1", 150),
            request_record("request-2", "session-1", 50),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            result, _ = self.scan(tmp, request_records=records)

        usage = result["ranges"]["all"]
        self.assertEqual(usage["in"], 200)
        self.assertEqual(len(usage["sessions"]), 1)

    def test_latest_summary_fills_missing_requests_without_double_counting_cache(self):
        summaries = [
            summary_record("session-1", 100),
            summary_record("session-1", 500),
            summary_record("session-2", 70),
            summary_record("session-2", 90),
        ]
        requests = [request_record("request-1", "session-1", 120, 20)]
        with tempfile.TemporaryDirectory() as tmp:
            result, _ = self.scan(tmp, summary_records=summaries, request_records=requests)

        usage = result["ranges"]["all"]
        self.assertEqual(usage["in"], 570)
        self.assertEqual(usage["cr"], 20)
        self.assertEqual(USAGE.token_total(usage), 590)
        self.assertEqual(len(usage["sessions"]), 2)

    def test_missing_sources_clear_stale_cache(self):
        stale = {
            "v": USAGE._SCAN_CACHE_VERSION,
            "qwencode": {"sig": "old", "entries": [{"date": "2020-01-01", "in": 99}]},
        }
        with tempfile.TemporaryDirectory() as tmp:
            result, cache = self.scan(tmp, cache=stale)

        self.assertEqual(result["ranges"]["all"]["in"], 0)
        self.assertEqual(cache["qwencode"], {})
        self.assertTrue(cache["_dirty"])

    def test_daily_and_wrapped_include_qwen_cost_models_and_hours(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, cache = self.scan(
                tmp,
                request_records=[request_record("request-1", "session-1", 100, 60, 10, 5)],
            )
            self.assertEqual(USAGE.token_total(result["ranges"]["all"]), 115)

            cache_path = Path(tmp) / "scan-cache.json"
            cache_path.write_text(json.dumps({
                "v": USAGE._SCAN_CACHE_VERSION,
                "qwencode": cache["qwencode"],
            }), encoding="utf-8")
            old_cache_file = USAGE._SCAN_CACHE_FILE
            USAGE._SCAN_CACHE_FILE = str(cache_path)
            try:
                daily = USAGE.build_daily_costs("30d", refresh=False)
                wrapped = USAGE.build_wrapped("30d", refresh=False)
            finally:
                USAGE._SCAN_CACHE_FILE = old_cache_file

        self.assertEqual(len(daily["daily"]), 1)
        self.assertEqual(daily["daily"][0]["q_in"], 40)
        self.assertEqual(daily["daily"][0]["q_cr"], 60)
        self.assertEqual(daily["daily"][0]["q_reason"], 5)
        self.assertEqual(daily["models"][0]["tool"], "qwencode")
        self.assertEqual(daily["models"][0]["tokens"], 115)
        self.assertEqual(wrapped["total_tokens"], 115)
        self.assertEqual(wrapped["hours"][8], 115)


if __name__ == "__main__":
    unittest.main()
