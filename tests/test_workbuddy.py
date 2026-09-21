import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from test_codex_limits import USAGE


def workbuddy_item(item_id, timestamp, input_tokens, output_tokens, cached=0,
                   session_id="session-1", trace_id="trace-1"):
    return {
        "type": "message",
        "id": item_id,
        "sessionId": session_id,
        "timestamp": timestamp,
        "cwd": "/tmp/workbuddy-project",
        "message": {
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "cache_read_input_tokens": cached,
            },
        },
        "providerData": {
            "messageId": f"provider-{item_id}",
            "traceId": trace_id,
            "requestModelId": "hy3",
            "requestModelName": "Hy3",
            "usage": {
                "inputTokens": input_tokens,
                "outputTokens": output_tokens,
                "totalTokens": input_tokens + output_tokens,
                "inputTokensDetails": [{"cached_tokens": cached}],
                "outputTokensDetails": [{"reasoning_tokens": output_tokens // 2}],
            },
        },
    }


class WorkBuddyUsageRecordTests(unittest.TestCase):
    def test_openai_style_cache_is_split_and_reasoning_stays_in_output(self):
        item = {
            "id": "item-1",
            "sessionId": "session-1",
            "timestamp": 1_704_672_000_000,
            "providerData": {
                "requestModelName": "Hy3",
                "rawUsage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                    "prompt_tokens_details": {"cached_tokens": 40},
                    "completion_tokens_details": {"reasoning_tokens": 15},
                },
            },
        }

        record = USAGE._workbuddy_usage_record(item)

        self.assertEqual(record["in"], 60)
        self.assertEqual(record["cr"], 40)
        self.assertEqual(record["out"], 20)
        self.assertEqual(record["reason"], 0)
        self.assertEqual(USAGE.token_total(record), 120)
        self.assertEqual(USAGE._resolve_id("Hy3"), "tencent/hy3")
        self.assertEqual(USAGE._resolve_id("Hy3 preview"), "tencent/hy3-preview")

    def test_anthropic_style_cache_fields_are_disjoint_without_total(self):
        item = {
            "id": "item-2",
            "sessionId": "session-1",
            "timestamp": 1_704_672_000_000,
            "message": {
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "cache_read_input_tokens": 30,
                    "cache_creation_input_tokens": 5,
                },
            },
            "providerData": {"requestModelName": "Claude Sonnet"},
        }

        record = USAGE._workbuddy_usage_record(item)

        self.assertEqual(record["in"], 10)
        self.assertEqual(record["cr"], 30)
        self.assertEqual(record["cw"], 5)
        self.assertEqual(USAGE.token_total(record), 47)


class WorkBuddyScanTests(unittest.TestCase):
    def test_domestic_and_international_editions_are_scanned_separately(self):
        timestamp = 1_704_672_000_000
        first = workbuddy_item("item-1", timestamp, 100, 10, cached=40)
        replay = workbuddy_item("item-1", timestamp, 100, 10, cached=40)
        second = workbuddy_item("item-2", timestamp + 1_000, 80, 5, cached=20)
        international = workbuddy_item("item-3", timestamp + 2_000, 50, 5, cached=10)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domestic = root / "domestic"
            overseas = root / "international"
            (domestic / "a").mkdir(parents=True)
            (overseas / "b").mkdir(parents=True)
            (domestic / "a" / "session-1.jsonl").write_text(
                json.dumps(first) + "\n" + json.dumps(second) + "\n", encoding="utf-8")
            (overseas / "b" / "session-1.jsonl").write_text(
                json.dumps(replay) + "\n" + json.dumps(international) + "\n",
                encoding="utf-8",
            )

            local_day = USAGE._workbuddy_timestamp(timestamp).replace(
                hour=0, minute=0, second=0, microsecond=0)
            bounds = {
                "today": local_day,
                "yesterday": local_day - timedelta(days=1),
                "week": local_day - timedelta(days=local_day.weekday()),
                "last_week": local_day - timedelta(days=local_day.weekday() + 7),
                "last_week_end": local_day - timedelta(days=local_day.weekday()),
                "month": local_day.replace(day=1),
                "year": local_day.replace(month=1, day=1),
            }
            old_dir = USAGE.WORKBUDDY_DIR
            old_ai_dir = USAGE.WORKBUDDY_AI_DIR
            old_pricing_db = USAGE._PRICING_DB
            old_override_models = USAGE._OV_MODELS
            USAGE.WORKBUDDY_DIR = str(domestic)
            USAGE.WORKBUDDY_AI_DIR = str(overseas)
            USAGE._PRICING_DB = {}
            USAGE._OV_MODELS = {}
            try:
                cache = {"v": USAGE._SCAN_CACHE_VERSION}
                with mock.patch.object(USAGE, "ledger_touch"), \
                     mock.patch.object(USAGE, "ledger_reconcile",
                                       side_effect=lambda _tool, days, sources=None: days):
                    domestic_result = USAGE.scan_workbuddy(bounds, cache)
                    international_result = USAGE.scan_workbuddy_ai(bounds, cache)
            finally:
                USAGE.WORKBUDDY_DIR = old_dir
                USAGE.WORKBUDDY_AI_DIR = old_ai_dir
                USAGE._PRICING_DB = old_pricing_db
                USAGE._OV_MODELS = old_override_models

        domestic_usage = domestic_result["ranges"]["all"]
        self.assertEqual(domestic_usage["in"], 120)
        self.assertEqual(domestic_usage["cr"], 60)
        self.assertEqual(domestic_usage["out"], 15)
        self.assertEqual(domestic_usage["reason"], 0)
        self.assertEqual(len(domestic_usage["sessions"]), 1)
        self.assertEqual(USAGE.token_total(domestic_usage), 195)
        self.assertIn("Hy3", domestic_usage["models"])
        self.assertAlmostEqual(
            domestic_usage["cost"],
            (120 * 0.14 + 60 * 0.035 + 15 * 0.58) / 1_000_000,
            places=12,
        )

        international_usage = international_result["ranges"]["all"]
        self.assertEqual(international_usage["in"], 100)
        self.assertEqual(international_usage["cr"], 50)
        self.assertEqual(international_usage["out"], 15)
        self.assertEqual(len(international_usage["sessions"]), 1)
        self.assertEqual(USAGE.token_total(international_usage), 165)
        self.assertAlmostEqual(
            international_usage["cost"],
            (100 * 0.14 + 50 * 0.035 + 15 * 0.58) / 1_000_000,
            places=12,
        )


if __name__ == "__main__":
    unittest.main()
