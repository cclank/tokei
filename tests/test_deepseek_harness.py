import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

try:
    from .test_codex_limits import USAGE
except ImportError:
    from test_codex_limits import USAGE


def harness_event(event_type, timestamp, turn, step, usage, model=None, served=None):
    data = {"turn": turn, "step": step}
    if event_type == "assistant/chunk":
        data["chunk"] = {"type": "usage", "usage": usage}
    else:
        data["usage"] = usage
        source = {"kind": "model", "provider": "deepseek-official",
                  "model": model or "deepseek-v4-pro"}
        if served is not None:
            source["replayState"] = {"response": {
                "kind": "pi-ai", "version": 2,
                "model": model or "deepseek-v4-pro", "responseModel": served}}
        data["message"] = {"source": source}
    return {"type": event_type, "time": timestamp, "data": data}


class DeepSeekHarnessTests(unittest.TestCase):
    def test_official_price_uses_historical_and_peak_windows(self):
        before_change = datetime(2026, 8, 16, 15, 59, tzinfo=timezone.utc)
        weekday_peak = datetime(2026, 8, 17, 2, 0, tzinfo=timezone.utc)
        weekday_off_peak = datetime(2026, 8, 17, 5, 0, tzinfo=timezone.utc)
        weekend = datetime(2026, 8, 22, 2, 0, tzinfo=timezone.utc)

        self.assertEqual(USAGE._deepseek_official_price("deepseek-v4-pro", before_change), {
            "in": 3.0, "out": 6.0, "cache_read": 0.025, "cache_write": 0.0,
        })
        self.assertEqual(USAGE._deepseek_official_price("deepseek-v4-pro-0813", weekday_peak), {
            "in": 9.0, "out": 27.0, "cache_read": 0.30, "cache_write": 0.0,
        })
        self.assertEqual(USAGE._deepseek_official_price("deepseek-v4-pro", weekday_off_peak), {
            "in": 4.5, "out": 13.5, "cache_read": 0.15, "cache_write": 0.0,
        })
        self.assertEqual(
            USAGE._deepseek_official_price("deepseek-v4-flash-vision-exp", weekend),
            {"in": 1.5, "out": 4.5, "cache_read": 0.05, "cache_write": 0.0},
        )

    def test_usage_record_prices_the_request_at_its_utc_timestamp(self):
        peak = datetime(2026, 8, 17, 2, 0, tzinfo=timezone.utc)
        event = harness_event(
            "assistant/message",
            int(peak.timestamp() * 1000),
            1,
            1,
            {"inputTokens": 1_000_000, "outputTokens": 1_000_000,
             "cacheReadTokens": 1_000_000},
        )

        record = USAGE._deepseek_harness_usage_record(event)

        self.assertAlmostEqual(record["cost_cny"], 9.0 + 27.0 + 0.30, places=12)

    def test_card_uses_harness_inclusive_input_and_output_labels(self):
        source = (Path(__file__).resolve().parents[1] / "Tokei" / "Sources" / "Tokei"
                  / "PanelView.swift").read_text(encoding="utf-8")

        self.assertIn("inclusiveIO: true", source)
        self.assertIn('L("输入"), Fmt.human(r.in + r.cr + r.cw)', source)
        self.assertIn('L("输出"), Fmt.human(r.out + r.reason)', source)
        self.assertIn('componentsAreSubtotals ? L("其中缓存读") : L("缓存读")', source)
        self.assertIn('componentsAreSubtotals ? L("其中推理") : L("推理")', source)

    def test_final_message_replaces_usage_chunk_and_splits_reasoning(self):
        timestamp = 1_704_672_000_000
        usage = {
            "inputTokens": 100,
            "outputTokens": 40,
            "cacheReadTokens": 1_000,
            "cacheWriteTokens": 5,
            "reasoningTokens": 15,
        }
        chunk = harness_event("assistant/chunk", timestamp, 1, 2, usage)
        message = harness_event("assistant/message", timestamp + 1, 1, 2, usage)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = root / "project" / "session-1"
            session_dir.mkdir(parents=True)
            path = session_dir / "session.jsonl"
            path.write_text("\n".join(json.dumps(item) for item in [
                {"type": "session", "id": "session-1", "cwd": "/tmp/deepseek-project",
                 "createdAt": timestamp},
                {"type": "request/header", "time": timestamp - 1,
                 "data": {"header": {"config": {"provider": "deepseek-official",
                                                   "model": "deepseek-v4-pro"}}}},
                chunk,
                message,
            ]) + "\n", encoding="utf-8")

            local_day = datetime.fromtimestamp(timestamp / 1000).astimezone().replace(
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
            cache = {"v": USAGE._SCAN_CACHE_VERSION}
            with mock.patch.object(USAGE, "DEEPSEEK_HARNESS_DIR", tmp), \
                 mock.patch.object(USAGE, "ledger_reconcile", side_effect=lambda _tool, days, sources=None: days):
                result = USAGE.scan_deepseek_harness(bounds, cache)
                with mock.patch.object(
                    USAGE, "_deepseek_harness_usage_record",
                    side_effect=AssertionError("unchanged log was reparsed"),
                ):
                    cached = USAGE.scan_deepseek_harness(bounds, cache)

        all_usage = result["ranges"]["all"]
        self.assertEqual(all_usage["in"], 100)
        self.assertEqual(all_usage["out"], 25)
        self.assertEqual(all_usage["reason"], 15)
        self.assertEqual(all_usage["cr"], 1_000)
        self.assertEqual(all_usage["cw"], 5)
        self.assertEqual(USAGE.token_total(all_usage), 1_145)
        self.assertEqual(len(all_usage["sessions"]), 1)
        self.assertEqual(cached["ranges"]["all"]["in"], 100)
        self.assertIn("deepseek-v4-pro", all_usage["models"])
        price = USAGE._deepseek_official_price(
            "deepseek-v4-pro",
            datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc),
        )
        self.assertAlmostEqual(
            all_usage["cost_cny"],
            (100 * price["in"] + 40 * price["out"] + 1_000 * price["cache_read"]
             + 5 * price["cache_write"]) / 1_000_000,
            places=12,
        )

    def test_official_route_does_not_use_openrouter_channel_price(self):
        event = harness_event(
            "assistant/message", 1_704_672_000_000, 1, 1,
            {"inputTokens": 100, "outputTokens": 40, "cacheReadTokens": 1_000},
        )
        with mock.patch.dict(USAGE._PRICING_DB, {
            "deepseek/deepseek-v4-pro": {
                "in": 99, "out": 99, "cache_read": 99, "cache_write": 99,
            },
        }):
            record = USAGE._deepseek_harness_usage_record(event)

        self.assertAlmostEqual(
            record["cost_cny"],
            (100 * 3 + 40 * 6 + 1_000 * 0.025) / 1_000_000,
            places=12,
        )

    def test_new_cost_version_replaces_equal_token_ledger_day(self):
        old = {"in": 100, "out": 20, "cr": 30, "cost": 9.0}
        new = {"in": 100, "out": 20, "cr": 30, "cost": 0.1,
               "_cost_version": USAGE._DEEPSEEK_HARNESS_COST_VERSION}
        ledger = {"v": USAGE._LEDGER_VERSION,
                  "tools": {"deepseek_harness": {"2026-08-13": old}}}
        original_cache = USAGE._LEDGER_CACHE.copy()
        try:
            USAGE._LEDGER_CACHE.update({"data": ledger, "dirty": False})
            merged = USAGE.ledger_reconcile("deepseek_harness", {"2026-08-13": new})
        finally:
            USAGE._LEDGER_CACHE.clear()
            USAGE._LEDGER_CACHE.update(original_cache)

        self.assertEqual(merged["2026-08-13"]["cost"], 0.1)

    def test_interrupted_call_uses_usage_chunk(self):
        record = USAGE._deepseek_harness_usage_record(harness_event(
            "assistant/chunk", 1_704_672_000_000, 3, 4,
            {"inputTokens": 7, "outputTokens": 9, "cacheReadTokens": 11,
             "reasoningTokens": 5},
        ), "deepseek-v4-pro")

        self.assertEqual(record["priority"], 1)
        self.assertEqual(record["out"], 4)
        self.assertEqual(record["reason"], 5)
        self.assertEqual(USAGE.token_total(record), 27)

    def test_replay_response_model_is_used_when_the_request_was_a_group(self):
        # 经网关选路由组时 source.model 是 group/<id>，它不是一个模型；
        # 真正作答的成员记在 replayState.response.responseModel 里。
        record = USAGE._deepseek_harness_usage_record(harness_event(
            "assistant/message", 1_704_672_000_000, 1, 1,
            {"inputTokens": 10, "outputTokens": 5},
            model="group/auto-glm-5-3-flash", served="zcode/GLM-5.3-Flash",
        ))

        self.assertEqual(record["model"], "zcode/GLM-5.3-Flash")

    def test_request_model_is_kept_when_the_reply_names_no_member(self):
        record = USAGE._deepseek_harness_usage_record(harness_event(
            "assistant/message", 1_704_672_000_000, 1, 1,
            {"inputTokens": 10, "outputTokens": 5},
            model="workbuddy/deepseek-v4-pro",
        ))

        self.assertEqual(record["model"], "workbuddy/deepseek-v4-pro")

    def test_placeholder_served_model_falls_back_to_the_request(self):
        # 厂商把真实名报成 auto（「我自己挑了一个」）时，它说不出是哪个模型，
        # 采用它会比请求名更没有信息量。
        record = USAGE._deepseek_harness_usage_record(harness_event(
            "assistant/message", 1_704_672_000_000, 1, 1,
            {"inputTokens": 10, "outputTokens": 5},
            model="qoder/Qwen3.8-Flash", served="auto",
        ))

        self.assertEqual(record["model"], "qoder/Qwen3.8-Flash")

    def test_slug_spellings_of_one_model_merge_into_one_row(self):
        # 网关修好之前记的是裸名、之后记的是 provider/model，两者是同一个模型。
        merged = USAGE._merge_model_identities({
            "glm-5.3-flash": {"in": 10, "out": 1},
            "zcode/GLM-5.3-Flash": {"in": 20, "out": 2},
        })

        self.assertEqual(list(merged), ["zcode/GLM-5.3-Flash"])
        self.assertEqual(merged["zcode/GLM-5.3-Flash"], {"in": 30, "out": 3})

    def test_a_release_date_is_not_absorbed_by_the_merge(self):
        # 带日期的版本与基础版是两个模型，不能被归并成一行。
        merged = USAGE._merge_model_identities({
            "deepseek/deepseek-v4-pro": {"in": 10},
            "deepseek/deepseek-v4-pro-202606": {"in": 20},
        })

        self.assertEqual(len(merged), 2)

    def test_a_routing_group_is_not_treated_as_a_model(self):
        self.assertFalse(USAGE._names_model("group/auto-glm-5-3-flash"))
        self.assertFalse(USAGE._names_model("qoder/auto"))
        self.assertTrue(USAGE._names_model("zcode/GLM-5.3-Flash"))


if __name__ == "__main__":
    unittest.main()
