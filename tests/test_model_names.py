import unittest
from copy import deepcopy
from unittest import mock

try:
    from .test_codex_limits import USAGE
except ImportError:
    from test_codex_limits import USAGE


class ModelNameTests(unittest.TestCase):
    def test_alias_buckets_merge_without_changing_usage_or_cost(self):
        models = {
            "gpt-6-astra": {"in": 100, "out": 10, "cr": 900, "cw": 2, "reason": 4, "cost": 6.2},
            "openai/gpt-6-astra": {"in": 200, "out": 20, "cr": 1800, "cw": 3, "reason": 8, "cost": 206.1},
            "openai/gpt-6-astra-20260903": {"in": 30, "out": 3, "cost": 1.5},
            "codex-auto-review": {"in": 4000, "out": 40, "cost": 16.9},
        }
        original = deepcopy(models)
        catalog = {"openai/gpt-6-astra": {
            "canonical_slug": "openai/gpt-6-astra-20260903",
            "in": 10, "out": 50, "cache_read": 1, "cache_write": 12.5,
        }}
        with mock.patch.object(USAGE, "_PRICING_DB", catalog):
            for include_prices in (True, False):
                with self.subTest(include_prices=include_prices):
                    rows = USAGE._format_token_models(models, include_prices=include_prices)
                    self.assertEqual(len(rows), 2)
                    self.assertEqual(len({row["model_id"] for row in rows}), len(rows))
                    merged = next(row for row in rows if row["model_id"] == "openai/gpt-6-astra")
                    for field in ("in", "out", "cr", "cw", "reason", "cost"):
                        self.assertAlmostEqual(merged[field], sum(v.get(field, 0) for k, v in models.items() if k != "codex-auto-review"))
                        self.assertAlmostEqual(sum(row[field] for row in rows), sum(v.get(field, 0) for v in models.values()))
                    self.assertEqual(rows[0]["model_id"], "openai/gpt-6-astra" if include_prices else "codex-auto-review")
        self.assertEqual(models, original)

    def test_gpt_variants_keep_distinct_display_names(self):
        self.assertEqual(USAGE.nice_model("openai/gpt-5.6-sol"), "GPT-5.6 Sol")
        self.assertEqual(USAGE.nice_model("openai/gpt-5.6-luna"), "GPT-5.6 Luna")
        self.assertEqual(USAGE.nice_model("openai/gpt-5.6-terra-pro"), "GPT-5.6 Terra Pro")

    def test_existing_gpt_names_remain_compact(self):
        self.assertEqual(USAGE.nice_model("openai/gpt-5.5"), "GPT-5.5")
        self.assertEqual(USAGE.nice_model("openai/gpt-5-mini"), "GPT-5 Mini")

    def test_formatted_variants_have_unique_row_ids(self):
        models = {
            "openai/gpt-5.6-sol": {"in": 100, "out": 10},
            "openai/gpt-5.6-luna": {"in": 20, "out": 2},
        }

        formatted = USAGE._format_token_models(models, include_prices=False)
        names = [model["name"] for model in formatted]

        self.assertEqual(names, ["GPT-5.6 Sol", "GPT-5.6 Luna"])
        self.assertEqual(
            [model["model_id"] for model in formatted],
            ["openai/gpt-5.6-sol", "openai/gpt-5.6-luna"],
        )
        self.assertEqual(len(names), len(set(names)))

    def test_catalog_canonical_slug_resolves_without_family_guessing(self):
        old_pricing = USAGE._PRICING_DB
        try:
            USAGE._PRICING_DB = {
                "provider/model": {
                    "canonical_slug": "provider/model-2026",
                    "in": 1.0,
                    "out": 2.0,
                },
            }
            model_id = USAGE._model_identity_id("provider/model-2026")
            self.assertEqual(model_id, "provider/model")
            self.assertEqual(
                USAGE._exact_pricing_id(model_id),
                "provider/model",
            )
        finally:
            USAGE._PRICING_DB = old_pricing

    def test_gateway_prefixed_muse_models_resolve_to_meta_pricing(self):
        self.assertEqual(USAGE._normalize("muse-spark-1.3-contributor"),
                         "meta/muse-spark-1.3-contributor")
        self.assertEqual(USAGE._normalize("vercel/meta/muse-spark-1.3-contributor"),
                         "meta/muse-spark-1.3-contributor")
        self.assertEqual(USAGE._pricing_id("vercel/meta/muse-spark-1.3-contributor"),
                         "meta/muse-spark-1.3-contributor")

    def test_unknown_model_identity_is_preserved(self):
        old_pricing = USAGE._PRICING_DB
        old_override_models = USAGE._OV_MODELS
        try:
            USAGE._PRICING_DB = {}
            USAGE._OV_MODELS = {}
            model = "private-provider/model-variant"
            self.assertEqual(USAGE._model_identity_id(model), model)
            self.assertIsNone(USAGE._exact_pricing_id(model))
        finally:
            USAGE._PRICING_DB = old_pricing
            USAGE._OV_MODELS = old_override_models


if __name__ == "__main__":
    unittest.main()
