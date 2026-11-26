import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

try:
    from .test_codex_limits import USAGE
except ImportError:
    from test_codex_limits import USAGE


class DashboardCacheTests(unittest.TestCase):
    def test_store_prewarms_once_after_pending_refreshes_finish(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "Tokei" / "Sources" / "Tokei" / "main.swift").read_text()

        self.assertRegex(
            source,
            r"if !(?:self\.)?refreshPending && !(?:self\.)?dashboardPrewarmStarted\s*\{\s*"
            r"(?:self\.)?dashboardPrewarmStarted = true\s*"
            r"DashboardRepository\.shared\.load\(\.all, force: true\)",
        )

    def test_dashboard_days_are_cached_only_when_changed(self):
        cache = {"_dirty": False}
        days = {"2026-07-16": {"tokens": 321, "sessions": {"session-1"}}}

        USAGE._cache_dashboard_days(cache, USAGE._GROK_DAYS_CACHE_KEY, days)
        self.assertEqual(cache[USAGE._GROK_DAYS_CACHE_KEY]["2026-07-16"]["tokens"], 321)
        self.assertEqual(cache[USAGE._GROK_DAYS_CACHE_KEY]["2026-07-16"]["sessions"], ["session-1"])
        self.assertTrue(cache["_dirty"])

        cache["_dirty"] = False
        USAGE._cache_dashboard_days(cache, USAGE._GROK_DAYS_CACHE_KEY, days)
        self.assertFalse(cache["_dirty"])

    def test_grok_bot_provider_days_are_merged_without_deleting_history(self):
        cache = {
            "_dirty": False,
            USAGE._GROK_BOT_PROVIDER_DAYS_CACHE_KEY: {
                "2025-12-31": {"tokens": 100},
                "2026-09-01": {"tokens": 200},
            },
        }

        USAGE._merge_dashboard_days(
            cache,
            USAGE._GROK_BOT_PROVIDER_DAYS_CACHE_KEY,
            {"2026-09-01": {"tokens": 250}},
        )

        self.assertEqual(
            cache[USAGE._GROK_BOT_PROVIDER_DAYS_CACHE_KEY],
            {
                "2025-12-31": {"tokens": 100},
                "2026-09-01": {"tokens": 250},
            },
        )
        self.assertTrue(cache["_dirty"])

    def test_wrapped_uses_cached_grok_days(self):
        today = date.today().isoformat()
        cache = {
            "v": USAGE._SCAN_CACHE_VERSION,
            "_dirty": False,
            USAGE._GROK_DAYS_CACHE_KEY: {
                today: {"in": 21, "out": 20, "cr": 270, "cw": 0, "reason": 10,
                        "tokens": 321, "hours": [321] + [0] * 23,
                        "models": {"grok-4": {
                            "in": 21, "out": 20, "cr": 270, "cw": 0,
                            "reason": 10, "cost": 0}},
                        "sessions": ["session-1"]},
            },
        }
        wrapped = USAGE.build_wrapped("all", refresh=False, _cache=cache)

        self.assertEqual(wrapped["total_tokens"], 321)
        self.assertEqual(sum(wrapped["hours"]), 321)
        self.assertEqual(wrapped["top_model"]["tokens"], 321)

    def test_grok_files_are_incrementally_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "project" / "session"
            session_dir.mkdir(parents=True)
            now = datetime.now().astimezone().replace(microsecond=0).isoformat()
            (session_dir / "summary.json").write_text(json.dumps({
                "updated_at": now,
                "current_model_id": "grok-4",
                "info": {"id": "session-1"},
            }), encoding="utf-8")
            signals = session_dir / "signals.json"
            signals.write_text(json.dumps({
                "contextTokensUsed": 321,
                "turnCount": 2,
                "toolCallCount": 1,
            }), encoding="utf-8")
            (session_dir / "events.jsonl").write_text("", encoding="utf-8")
            (session_dir / "updates.jsonl").write_text("", encoding="utf-8")
            cache = {"v": USAGE._SCAN_CACHE_VERSION}

            with mock.patch.object(USAGE, "GROK_DIR", tmp), \
                 mock.patch.object(USAGE, "GROK_LOG", str(Path(tmp) / "missing.jsonl")):
                first = USAGE.scan_grok(USAGE.range_bounds(), cache)
                cache["_dirty"] = False
                with mock.patch.object(
                    USAGE, "_load_grok_session",
                    side_effect=AssertionError("unchanged Grok session was reparsed"),
                ):
                    second = USAGE.scan_grok(USAGE.range_bounds(), cache)
                signals.write_text(json.dumps({
                    "contextTokensUsed": 654,
                    "turnCount": 2,
                    "toolCallCount": 1,
                }), encoding="utf-8")
                changed = USAGE.scan_grok(USAGE.range_bounds(), cache)

        self.assertEqual(first["ranges"]["all"]["tokens"], 321)
        self.assertEqual(second["ranges"]["all"]["tokens"], 321)
        self.assertEqual(changed["ranges"]["all"]["tokens"], 654)
        self.assertEqual(changed["model"], "grok-4")

    def test_daily_and_wrapped_cover_gemini_grok_hermes_and_openclaw(self):
        today = date.today().isoformat()
        gemini = {"in": 100, "out": 20, "cached": 30, "thoughts": 10,
                  "cost": 1.25, "hours": [130] + [0] * 23,
                  "models": {"gemini-3.5-flash": {
                      "in": 100, "out": 20, "cached": 30, "thoughts": 10, "cost": 1.25}}}
        hermes = {"in": 1, "out": 2, "cr": 3, "cw": 4, "reason": 5,
                  "cost": 2.5, "hours": [0, 15] + [0] * 22,
                  "models": {"gpt-5.5": {
                      "in": 1, "out": 2, "cr": 3, "cw": 4, "reason": 5, "cost": 2.5}}}
        openclaw = {"in": 6, "out": 7, "cr": 8, "cw": 9, "reason": 6,
                    "cost": 3.5, "hours": [0, 0, 30] + [0] * 21,
                    "models": {"claude-sonnet-4.6": {
                        "in": 6, "out": 7, "cr": 8, "cw": 9, "reason": 6, "cost": 3.5}}}
        qoderwork = {"in": 19, "out": 11, "hours": [0, 0, 0, 0, 30] + [0] * 19}
        cache = {
            "v": USAGE._SCAN_CACHE_VERSION,
            "_dirty": False,
            USAGE._GEMINI_DAYS_CACHE_KEY: {today: gemini},
            USAGE._GROK_DAYS_CACHE_KEY: {today: {
                "in": 10, "out": 10, "cr": 20, "cw": 0, "reason": 10,
                "tokens": 50, "hours": [0, 0, 0, 50] + [0] * 20,
                "models": {"grok-4": {
                    "in": 10, "out": 10, "cr": 20, "cw": 0,
                    "reason": 10, "cost": 0}},
                "sessions": ["session-1"]}},
            "hermes": {"db": {"days": {today: hermes}}},
            "openclaw": {"_selected_days": {today: openclaw}},
            "qoder": {"db": {"model": "performance", "days": {today: qoderwork}}},
        }

        daily = USAGE.build_daily_costs("1d", refresh=False, _cache=cache)
        wrapped = USAGE.build_wrapped("1d", refresh=False, _cache=cache)

        self.assertEqual(len(daily["daily"]), 1)
        self.assertEqual(daily["daily"][0]["tokens"], 255)
        self.assertEqual(sum(model["tokens"] for model in daily["models"]), 255)
        self.assertEqual(
            next(model["tokens"] for model in daily["models"] if model["tool"] == "qoderwork"),
            30,
        )
        self.assertEqual(daily["daily"][0]["total"], 7.25)
        self.assertEqual(wrapped["total_tokens"], 255)
        self.assertEqual(wrapped["total_cost"], 7.25)
        self.assertEqual(sum(wrapped["hours"]), 255)

    def test_qodercli_exact_usage_is_included_once_in_dashboard_and_wrapped(self):
        today = date.today().isoformat()
        first = {
            "id": "request-1", "day": today, "model": "ultimate",
            "in": 60, "out": 20, "cr": 30, "cw": 10,
            "credits": 1.5, "usage_available": True, "est": 999,
        }
        second = {
            "id": "request-2", "day": today, "model": "cmodel",
            "in": 30, "out": 8, "cr": 20, "cw": 0,
            "credits": 0.4, "usage_available": True, "est": 999,
        }
        cache = {
            "v": USAGE._SCAN_CACHE_VERSION,
            "_dirty": False,
            "qodercli": {
                "/tmp/main.jsonl": {"responses": [first, second], "days": {}},
                "/tmp/child.jsonl": {"responses": [first], "days": {}, "sub": True},
            },
        }

        daily = USAGE.build_daily_costs("1d", refresh=False, _cache=cache)
        wrapped = USAGE.build_wrapped("1d", refresh=False, _cache=cache)

        self.assertEqual(daily["daily"][0]["tokens"], 178)
        cli_models = [model for model in daily["models"] if model["tool"] == "qodercli"]
        self.assertEqual(sum(model["tokens"] for model in cli_models), 178)
        self.assertEqual(daily["daily"][0]["total"], 0)
        self.assertEqual(wrapped["total_tokens"], 178)
        self.assertEqual(wrapped["total_cost"], 0)

    def test_account_provider_models_are_reported_without_double_counting_local_totals(self):
        today = date.today().isoformat()
        cache = {
            "v": USAGE._SCAN_CACHE_VERSION,
            "_dirty": False,
            USAGE._CURSOR_PROVIDER_DAYS_CACHE_KEY: {
                today: {
                    "tokens": 160, "in": 100, "out": 20, "cr": 30, "cw": 10,
                    "cost": 0.25, "requests": 2, "hours": [160] + [0] * 23,
                    "models": {"gpt-5.6-sol-medium": {
                        "tokens": 160, "in": 100, "out": 20, "cr": 30, "cw": 10,
                        "reason": 0, "cost": 0.25,
                    }},
                },
            },
            USAGE._ZAI_PROVIDER_DAYS_CACHE_KEY: {
                today: {
                    "tokens": 500, "hours": [0] * 24,
                    "models": {"glm-5.3": {"tokens": 500}},
                },
            },
            USAGE._GROK_BOT_PROVIDER_DAYS_CACHE_KEY: {
                today: {
                    "tokens": 340, "in": 40, "out": 20, "cr": 280,
                    "cost": 0.75, "hours": [0] * 24,
                    "models": {"grok-code-fast-1": {
                        "tokens": 340, "in": 40, "out": 20, "cr": 280,
                        "cost": 0.75,
                    }},
                },
            },
        }

        with mock.patch.object(USAGE, "_grok_bot_provider_days_cache_key",
                               return_value=USAGE._GROK_BOT_PROVIDER_DAYS_CACHE_KEY):
            result = USAGE.build_daily_costs("1d", refresh=False, _cache=cache)

        self.assertEqual(result["daily"], [])
        self.assertEqual(sum(model["tokens"] for model in result["provider_models"]), 660)
        self.assertEqual(
            {model["tool"] for model in result["provider_models"]},
            {"cursor", "zai"},
        )

        grok_bot = next(
            model for model in result["models"] if model["tool"] == "grok_bot"
        )
        self.assertEqual(grok_bot["name"], "Grok Code Fast 1")
        self.assertEqual(grok_bot["cost"], 0.75)

    def test_swift_dashboard_uses_synced_grok_bot_provider_data(self):
        root = Path(__file__).resolve().parents[1]
        dashboard = (root / "Tokei/Sources/Tokei/DashboardView.swift").read_text()
        sync = (root / "Tokei/Sources/Tokei/SyncManager.swift").read_text()

        self.assertNotIn('(\"grok_bot\", \"Grok Bot\", usage.grokBot.quota', dashboard)
        self.assertIn('case \"grok_bot\": return Theme.grokBot', dashboard)
        self.assertIn('grokBotModelsForCurrentScope(usage:', dashboard)
        self.assertIn('u.grokBot.quota = peer.usage.grokBot.quota', sync)

    def test_swift_all_device_qoderwork_tokens_are_preserved(self):
        root = Path(__file__).resolve().parents[1]
        model = (root / "Tokei/Sources/Tokei/Model.swift").read_text()
        sync = (root / "Tokei/Sources/Tokei/SyncManager.swift").read_text()
        dashboard = (root / "Tokei/Sources/Tokei/DashboardView.swift").read_text()

        self.assertIn("var `in`: Int = 0", model)
        self.assertIn("d.in += s.in; d.out += s.out", sync)
        self.assertIn("+ qoderwork.in + qoderwork.out", dashboard)

    def test_valid_cache_is_loaded_once_without_rescanning(self):
        cache = {"v": USAGE._SCAN_CACHE_VERSION, "_dirty": False}
        with mock.patch.object(USAGE, "_load_scan_cache", return_value=cache) as loader, \
             mock.patch.object(USAGE, "compute") as compute:
            payload = USAGE.build_dashboard("all")

        loader.assert_called_once()
        compute.assert_not_called()
        self.assertEqual(payload["daily"], [])
        self.assertEqual(payload["models"], [])
        self.assertEqual(payload["wrapped"]["period"], "all")

    def test_missing_cache_triggers_one_fallback_scan(self):
        missing = {"v": USAGE._SCAN_CACHE_VERSION, "_dirty": True}
        ready = {"v": USAGE._SCAN_CACHE_VERSION, "_dirty": False}
        with mock.patch.object(USAGE, "_load_scan_cache", side_effect=[missing, ready]) as loader, \
             mock.patch.object(USAGE, "compute") as compute:
            payload = USAGE.build_dashboard("30d")

        self.assertEqual(loader.call_count, 2)
        compute.assert_called_once_with()
        self.assertEqual(payload["daily"], [])
        self.assertEqual(payload["wrapped"]["period"], "30d")

    def test_scan_cache_is_written_atomically_as_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scan-cache.json"
            cache = {
                "v": USAGE._SCAN_CACHE_VERSION,
                "_keys": set(),
                "_dirty": True,
                "sentinel": "x" * 100_000,
            }
            with mock.patch.object(USAGE, "_SCAN_CACHE_FILE", str(cache_path)), \
                 mock.patch.object(
                     USAGE.json, "dump",
                     side_effect=AssertionError("cache should use one encoded write"),
                 ):
                USAGE._save_scan_cache(cache)
                stored, _ = USAGE._read_scan_cache_file()
                leftovers = [p.name for p in Path(USAGE._scan_shard_dir()).iterdir()
                             if p.name.startswith(".")]

        self.assertEqual(stored["v"], USAGE._SCAN_CACHE_VERSION)
        self.assertEqual(len(stored["sentinel"]), 100_000)
        self.assertEqual(leftovers, [], "临时文件都应已原子替换或清理")


if __name__ == "__main__":
    unittest.main()
