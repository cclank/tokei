import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from .test_codex_limits import USAGE
except ImportError:
    from test_codex_limits import USAGE


class PricingCacheTests(unittest.TestCase):
    @staticmethod
    def response(prompt="0.000001"):
        return io.BytesIO(json.dumps({
            "data": [{
                "id": "test/model",
                "name": "Test Model",
                "canonical_slug": "test/model-2026",
                "owned_by": "test-owner",
                "pricing": {
                    "prompt": prompt,
                    "completion": "0.000002",
                    "input_cache_read": "0.0000005",
                    "input_cache_write": "0.0000008",
                },
            }],
        }).encode("utf-8"))

    def test_unchanged_price_update_keeps_token_scan_cache(self):
        existing_models = {
            "test/model": {
                "in": 1.0,
                "out": 2.0,
                "cache_read": 0.5,
                "cache_write": 0.8,
                "name": "Test Model",
                "canonical_slug": "test/model-2026",
                "owned_by": "test-owner",
            },
        }

        with tempfile.TemporaryDirectory() as tmp:
            pricing = Path(tmp) / "pricing.json"
            scan_cache = Path(tmp) / "scan-cache.json"
            pricing.write_text(json.dumps({"models": existing_models}), encoding="utf-8")
            scan_cache.write_text(json.dumps({
                "v": USAGE._SCAN_CACHE_VERSION,
                "sentinel": True,
            }), encoding="utf-8")

            with mock.patch("urllib.request.urlopen", return_value=self.response()), \
                 mock.patch.object(USAGE, "PRICING_FILE", str(pricing)), \
                 mock.patch.object(USAGE, "_SCAN_CACHE_FILE", str(scan_cache)), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(USAGE.update_prices(), 0)

            self.assertTrue(scan_cache.exists())
            self.assertTrue(json.loads(scan_cache.read_text(encoding="utf-8"))["sentinel"])
            saved = json.loads(pricing.read_text(encoding="utf-8"))["models"]["test/model"]
            self.assertEqual(saved["name"], "Test Model")
            self.assertEqual(saved["canonical_slug"], "test/model-2026")
            self.assertEqual(saved["owned_by"], "test-owner")

    def test_changed_price_update_preserves_token_scan_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            pricing = Path(tmp) / "pricing.json"
            scan_cache = Path(tmp) / "scan-cache.json"
            pricing.write_text(json.dumps({"models": {
                "test/model": {"in": 1.0, "out": 2.0, "cache_read": 0.5, "cache_write": 0.8},
            }}), encoding="utf-8")
            scan_cache.write_text(json.dumps({"v": USAGE._SCAN_CACHE_VERSION}), encoding="utf-8")

            with mock.patch("urllib.request.urlopen", return_value=self.response("0.000003")), \
                 mock.patch.object(USAGE, "PRICING_FILE", str(pricing)), \
                 mock.patch.object(USAGE, "_SCAN_CACHE_FILE", str(scan_cache)), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(USAGE.update_prices(), 0)

            with mock.patch.object(USAGE, "_SCAN_CACHE_FILE", str(scan_cache)):
                saved_cache, _ = USAGE._read_scan_cache_file()
            self.assertEqual(saved_cache["v"], USAGE._SCAN_CACHE_VERSION)
            self.assertIn("test/model", saved_cache["_pricing_changed_models"])
            self.assertTrue(saved_cache["_pricing_changed"])

    def test_price_update_retains_removed_models_for_historical_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            pricing = Path(tmp) / "pricing.json"
            scan_cache = Path(tmp) / "scan-cache.json"
            historical = {
                "in": 5.0,
                "out": 20.0,
                "cache_read": 0.5,
                "cache_write": 0.0,
            }
            pricing.write_text(json.dumps({"models": {
                "historical/model": historical,
            }}), encoding="utf-8")
            scan_cache.write_text(json.dumps({
                "v": USAGE._SCAN_CACHE_VERSION,
            }), encoding="utf-8")

            with mock.patch("urllib.request.urlopen", return_value=self.response()), \
                 mock.patch.object(USAGE, "PRICING_FILE", str(pricing)), \
                 mock.patch.object(USAGE, "_SCAN_CACHE_FILE", str(scan_cache)), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(USAGE.update_prices(), 0)

            saved = json.loads(pricing.read_text(encoding="utf-8"))
            self.assertEqual(saved["_meta"]["active_count"], 1)
            self.assertEqual(saved["_meta"]["retained_count"], 1)
            self.assertEqual(saved["_meta"]["count"], 2)
            self.assertEqual(saved["models"]["historical/model"], {
                **historical,
                "retired": True,
            })
            with mock.patch.object(USAGE, "_SCAN_CACHE_FILE", str(scan_cache)):
                changed = USAGE._read_scan_cache_file()[0].get("_pricing_changed_models", [])
            self.assertNotIn("historical/model", changed)

    def test_price_fingerprint_keeps_all_token_scan_caches(self):
        with tempfile.TemporaryDirectory() as tmp:
            scan_cache = Path(tmp) / "scan-cache.json"
            scan_cache.write_text(json.dumps({
                "v": USAGE._SCAN_CACHE_VERSION,
                "_pricing_fingerprint": "old",
                "claude": {"kept": True},
                "codex": {"kept": True},
                "gemini": {"rebuild": True},
            }), encoding="utf-8")

            with mock.patch.object(USAGE, "_SCAN_CACHE_FILE", str(scan_cache)):
                loaded = USAGE._load_scan_cache()

            self.assertEqual(loaded["claude"], {"kept": True})
            self.assertEqual(loaded["codex"], {"kept": True})
            self.assertEqual(loaded["gemini"], {"rebuild": True})
            self.assertTrue(loaded["_pricing_changed"])

    def test_cached_claude_and_codex_events_are_repriced_without_source_scan(self):
        claude_event = {
            "model": "qwen3.8-max-0902",
            "in": 1_000_000,
            "out": 1_000_000,
            "cr": 1_000_000,
            "cw": 1_000_000,
            "cw5": 1_000_000,
            "cw1": 0,
            "cost": 0.0,
        }
        self.assertTrue(USAGE._reprice_claude_events({
            "session": {"events": [claude_event]},
        }, {"qwen/qwen3.8-max"}))
        self.assertAlmostEqual(claude_event["cost"], 2.0 + 6.0 + 0.25 + 2.5)

        with tempfile.TemporaryDirectory() as tmp:
            scan_cache = Path(tmp) / "scan-cache.json"
            event = [
                "2026-09-04T08:00:00+00:00", "2026-09-04",
                None, None, None, None,
                100_000, 50_000, 20_000, 5_000, 0.0, "openai/gpt-5.6-sol",
            ]
            with mock.patch.object(USAGE, "_SCAN_CACHE_FILE", str(scan_cache)):
                size = USAGE._codex_write_event_cache("rollout.jsonl", [event])
                entry = {
                    "event_count": 1,
                    "event_cache_size": size,
                    "active_model": "openai/gpt-5.6-sol",
                    "drop_count": 0,
                    "canonical": True,
                    "days": {},
                    "deduped_days": {},
                }
                self.assertTrue(USAGE._reprice_codex_event_caches(
                    {"rollout.jsonl": entry},
                    {"openai/gpt-5.6-sol"},
                ))
                saved = next(USAGE._iter_codex_cached_events("rollout.jsonl"))

            expected = USAGE._codex_estimated_cost(
                "openai/gpt-5.6-sol", 100_000, 50_000, 20_000)
            self.assertEqual(saved[10], 0.0)
            self.assertAlmostEqual(entry["days"]["2026-09-04"]["cost"], expected)

    def test_uniform_codex_price_change_scales_days_without_reading_events(self):
        day = {
            "cost": 1.0,
            "models": {
                "openai/gpt-5.6-sol": {
                    "in": 100,
                    "out": 20,
                    "cr": 10,
                    "cw": 0,
                    "reason": 5,
                    "cost": 1.0,
                },
            },
        }
        entry = {
            "active_model": "openai/gpt-5.6-sol",
            "days": {"2026-09-04": day},
            "deduped_days": {"2026-09-04": day},
        }
        with mock.patch.object(
            USAGE,
            "_iter_codex_cached_events",
            side_effect=AssertionError("event cache should not be read"),
        ):
            changed = USAGE._reprice_codex_event_caches(
                {"rollout.jsonl": entry},
                {"openai/gpt-5.6-sol"},
                {"openai/gpt-5.6-sol": 2.0},
            )

        self.assertTrue(changed)
        self.assertEqual(day["cost"], 2.0)
        self.assertEqual(day["models"]["openai/gpt-5.6-sol"]["cost"], 2.0)

    def test_shipped_official_overrides_match_runtime_baseline(self):
        override_path = Path(__file__).resolve().parents[1] / "pricing_overrides.json"
        shipped = json.loads(override_path.read_text(encoding="utf-8"))

        for model, price in USAGE._BUILTIN_OVERRIDE_MODELS.items():
            self.assertEqual(shipped["models"][model], price)
        for alias, model in USAGE._BUILTIN_OVERRIDE_ALIASES.items():
            self.assertEqual(shipped["aliases"][alias], model)

    def test_codex_model_rows_show_the_price_their_cost_used(self):
        """卡片上的单价必须就是算成本用的那个价：没有公开价的按 gpt-5.5 估算，要标出参照。"""
        rows = {row["name"]: row for row in USAGE._format_token_models({
            "gpt-6.1-sol": {"in": 1_000_000, "cost": 2.0},
            "codex-auto-review": {"in": 1_000_000, "cost": 5.0},
        }, price_model=USAGE._codex_price_model)}

        sol = rows["GPT-6.1 Sol"]
        self.assertEqual((sol["pin"], sol["pout"], sol["pcr"]), (2.0, 10.0, 0.1))
        self.assertIsNone(sol["pref"], "官方价就是它自己的价")
        # 10 万 token：避开超过 27.2 万输入时的长上下文加价
        self.assertAlmostEqual(USAGE._codex_estimated_cost("gpt-6.1-sol", 100_000, 0, 0), 0.2)

        review = rows["Codex Auto Review"]
        self.assertEqual((review["pin"], review["pout"]), (5.0, 30.0))
        self.assertEqual(review["pref"], "GPT-5.5")
        self.assertAlmostEqual(USAGE._codex_estimated_cost("codex-auto-review", 100_000, 0, 0),
                               review["pin"] / 10)

    def test_unlisted_models_use_the_previous_version_of_their_line(self):
        """价目表里没有的沿用同一版本线上一个版本的价：先找同档位，再找基础款。"""
        catalog = {
            "minimax/minimax-m3": {"in": 0.3, "out": 1.2},
            "minimax/minimax-m2.7": {"in": 0.3, "out": 1.2},
            "minimax/minimax-01": {"in": 0.2, "out": 1.1},
            "openai/gpt-6-sol": {"in": 2.0, "out": 10.0},
            "openai/gpt-6.1-sol": {"in": 2.0, "out": 10.0},
            "openai/gpt-6-astra": {"in": 10.0, "out": 50.0},
            "deepseek/deepseek-v4-pro": {"in": 0.9, "out": 1.9},
            "deepseek/deepseek-v4.1-flash": {"in": 0.3, "out": 1.2},
            "tencent/hy4-preview": {"in": 0.834, "out": 2.501},
            "vendor-a/twin-2": {"in": 1.0, "out": 1.0},
            "vendor-b/twin-2": {"in": 2.0, "out": 2.0},
        }
        with mock.patch.object(USAGE, "_PRICING_DB", catalog), \
             mock.patch.object(USAGE, "_DEFAULT_PRICES", {}), \
             mock.patch.object(USAGE, "_OV_MODELS", {}), \
             mock.patch.object(USAGE, "_CATALOG_INDEX", None):
            cases = {
                "MiniMax-M3.1-Flash-Preview": "minimax/minimax-m3",   # 没有 flash 档，退到基础款
                "gpt-6.2-sol": "openai/gpt-6.1-sol",                  # 同档位里最近的上一版
                "deepseek-v4.2-flash": "deepseek/deepseek-v4.1-flash",  # 不再被家族兜底按 pro 算
                "Hy4-dev": "tencent/hy4-preview",                     # 同版本只有 preview 也认
                "twin-3": None,                                       # 两家都有，说不清是谁
                "codex-auto-review": None,                            # 没有版本号，不猜
            }
            for model, expected in cases.items():
                with self.subTest(model=model):
                    self.assertEqual(USAGE._pricing_id(model), expected)

            rows = USAGE._format_token_models({"MiniMax-M3.1-Flash-Preview": {"in": 1000, "cost": 0.1}})
            self.assertEqual((rows[0]["pin"], rows[0]["pout"]), (0.3, 1.2))
            self.assertEqual(rows[0]["pref"], "MiniMax M3", "借来的单价要标出参照")

    def test_current_official_and_snapshot_prices_resolve_exactly(self):
        self.assertEqual(USAGE._resolve_id("gpt-5.6"), "openai/gpt-5.6-sol")
        self.assertEqual(USAGE._raw_price("gpt-5.6"), {
            "in": 4.0,
            "out": 20.0,
            "cache_read": 0.4,
            "cache_write": 5.0,
        })
        self.assertEqual(
            USAGE._resolve_id("qwen3.8-max-0902"),
            "qwen/qwen3.8-max",
        )
        self.assertEqual(
            USAGE._resolve_id("Qwen3.8-Max-0902"),
            "qwen/qwen3.8-max",
        )
        self.assertEqual(
            USAGE._resolve_id("qwen3.8-max-2026-09-02"),
            "qwen/qwen3.8-max",
        )
        self.assertEqual(
            USAGE._resolve_id("qwen3.8:27b"),
            "qwen/qwen3.8-27b",
        )

    def test_confirmed_aliases_replace_stale_generated_aliases(self):
        models, aliases = USAGE._merge_pricing_overrides({
            "models": {"openai/gpt-5.6-sol": {"in": 9.0}},
            "aliases": {"qwen3.8:27b": "qwen/qwen3.8:27b"},
        })

        self.assertEqual(models["openai/gpt-5.6-sol"]["in"], 9.0)
        self.assertEqual(aliases["qwen3.8:27b"], "qwen/qwen3.8-27b")


if __name__ == "__main__":
    unittest.main()
