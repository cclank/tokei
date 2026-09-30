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

    def test_models_without_a_public_price_are_not_given_a_guessed_dollar_cost(self):
        """以前查不到价就按 Opus 兜底价算，混元、Step 这类模型被多算几百美元。"""
        def item(model):
            return {
                "id": f"item-{model}", "sessionId": "session-1",
                "timestamp": 1_704_672_000_000,
                "providerData": {"requestModelName": model,
                                 "rawUsage": {"prompt_tokens": 1_000_000,
                                              "completion_tokens": 100_000}},
            }

        unknown = USAGE._workbuddy_usage_record(item("made-up-model-x"))
        self.assertIsNone(USAGE._pricing_id("made-up-model-x"))
        self.assertEqual(unknown["cost"], 0.0)
        self.assertEqual(unknown["in"], 1_000_000, "token 照常计入")

        priced = USAGE._workbuddy_usage_record(item("Hy3"))
        self.assertGreater(priced["cost"], 0, "有公开价的模型照常估算")

    def test_pi_and_qwen_do_not_guess_a_price_for_unknown_models(self):
        usage = {"input": 1_000_000, "output": 100_000}
        self.assertEqual(USAGE._pi_usage_cost(usage, "made-up-model-x"), 0.0)
        self.assertGreater(USAGE._pi_usage_cost(usage, "claude-sonnet-5"), 0)
        *_tokens, cost = USAGE._qwen_usage_parts(
            "made-up-model-x", {"inputTokens": 1_000_000, "outputTokens": 100_000})
        self.assertEqual(cost, 0.0)

    def test_bare_model_names_are_priced_from_the_catalog(self):
        """不带厂商前缀的名字按名字到价目表（OpenRouter）里找，只认唯一匹配。"""
        catalog = {
            "tencent/hy4-preview": {"in": 0.834, "out": 2.501, "cache_read": 0.042},
            "openrouter/auto": {"in": -1_000_000, "out": -1_000_000},
            "vendor-a/twin": {"in": 1.0, "out": 2.0},
            "vendor-b/twin": {"in": 3.0, "out": 4.0},
            "vendor-a/solo:batch": {"in": 0.5, "out": 1.0},
        }
        with mock.patch.object(USAGE, "_PRICING_DB", catalog), \
             mock.patch.object(USAGE, "_CATALOG_INDEX", None):
            self.assertEqual(USAGE._normalize("Hy4 preview"), "tencent/hy4-preview")
            self.assertEqual(USAGE._normalize("custom-local:hy4-preview"), "tencent/hy4-preview")
            self.assertEqual(USAGE._normalize("auto"), "auto", "路由占位不算价")
            self.assertEqual(USAGE._normalize("twin"), "twin", "两家同名说不清是哪家")
            self.assertEqual(USAGE._normalize("solo"), "solo", ":batch 变体不参与")
        # 阶跃还没有官方价、OpenRouter 也未上架：内置第三方网关价兜底
        self.assertEqual(USAGE._pricing_id("step-5-preview"), "stepfun/step-5-preview")
        self.assertEqual(USAGE.nice_model("Hy4 preview"), USAGE.nice_model("tencent/hy4-preview"))

    def test_ledger_costs_are_repriced_from_tokens(self):
        """账本迁移：没有公开价的清零；查得到价的按 token × 现价重算（旧版按 Opus 猜的、
        上一版清零的都改对）；来源和当天合计一起调整，token 不动。"""
        def model(inp, out, cost):
            return {"in": inp, "out": out, "cost": cost}

        def day():
            return {"in": 3_000_000, "out": 300_000, "cost": 20.0,
                    "models": {"made-up-model-x": model(1_000_000, 100_000, 10.0),
                               "Hy4 preview": model(1_000_000, 100_000, 0.0),
                               "Hy3": model(1_000_000, 100_000, 10.0)},
                    "_sources": {
                        "legacy": {"in": 2_000_000, "out": 200_000, "cost": 20.0,
                                   "models": {"made-up-model-x": model(1_000_000, 100_000, 10.0),
                                              "Hy3": model(1_000_000, 100_000, 10.0)}},
                        "abc": {"in": 1_000_000, "out": 100_000, "cost": 0.0,
                                "models": {"Hy4 preview": model(1_000_000, 100_000, 0.0)}},
                    }}

        def expected(name):
            p = USAGE._raw_price(USAGE._pricing_id(name))
            return (1_000_000 * p["in"] + 100_000 * p["out"]) / 1e6

        saved = {}
        USAGE._LEDGER_CACHE["data"] = {"v": USAGE._LEDGER_VERSION,
                                       "tools": {"workbuddy_ai": {"2026-09-01": day()}}}
        USAGE._LEDGER_CACHE["dirty"] = False
        try:
            with mock.patch.object(USAGE, "_load_ledger_from_disk", return_value={
                    "v": USAGE._LEDGER_VERSION,
                    "tools": {"workbuddy_ai": {"2026-09-01": day()}}}), \
                 mock.patch.object(USAGE, "_save_ledger",
                                   side_effect=lambda value: saved.update(value)):
                USAGE._prepare_unpriced_cost_ledger("workbuddy_ai")
                USAGE._prepare_unpriced_cost_ledger("workbuddy_ai")  # 只迁一次
                USAGE.ledger_flush()
        finally:
            USAGE._LEDGER_CACHE["data"] = None
            USAGE._LEDGER_CACHE["dirty"] = False

        stored = saved["tools"]["workbuddy_ai"]["2026-09-01"]
        hy4, hy3 = expected("Hy4 preview"), expected("Hy3")
        self.assertEqual(stored["models"]["made-up-model-x"]["cost"], 0.0)
        self.assertAlmostEqual(stored["models"]["Hy4 preview"]["cost"], hy4)
        self.assertAlmostEqual(stored["models"]["Hy3"]["cost"], hy3)
        self.assertAlmostEqual(stored["cost"], hy4 + hy3, msg="磁盘上的旧高水位不能合并回来")
        self.assertAlmostEqual(stored["_sources"]["legacy"]["cost"], hy3)
        self.assertAlmostEqual(stored["_sources"]["abc"]["cost"], hy4)
        self.assertEqual((stored["in"], stored["out"]), (3_000_000, 300_000))
        self.assertEqual(saved["workbuddy_ai_unpriced_schema"], USAGE._UNPRICED_COST_SCHEMA)

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
