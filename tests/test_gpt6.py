import unittest

try:
    from .test_codex_limits import USAGE
except ImportError:
    from test_codex_limits import USAGE


class GPT6SupportTests(unittest.TestCase):
    def test_normalize_gpt6_variants(self):
        self.assertEqual(USAGE._normalize("gpt-6-sol"), "openai/gpt-6-sol")
        self.assertEqual(USAGE._normalize("gpt-6-luna"), "openai/gpt-6-luna")
        self.assertEqual(USAGE._normalize("gpt-6-astra"), "openai/gpt-6-astra")

    def test_resolve_gpt6_to_catalog_ids(self):
        self.assertEqual(USAGE._resolve_id("gpt-6-sol"), "openai/gpt-6-sol")
        self.assertEqual(USAGE._resolve_id("gpt-6-luna"), "openai/gpt-6-luna")
        self.assertEqual(USAGE._known_id_or_raw("gpt-6-sol"), "openai/gpt-6-sol")
        self.assertEqual(USAGE._known_id_or_raw("gpt-6-luna"), "openai/gpt-6-luna")

    def test_aliases_resolve_to_base_models(self):
        self.assertEqual(USAGE._resolve_id("gpt-6-sol"), "openai/gpt-6-sol")
        self.assertEqual(USAGE._resolve_id("gpt-6-luna"), "openai/gpt-6-luna")

    def test_pro_variants_have_same_price_as_base(self):
        sol = USAGE._raw_price("openai/gpt-6-sol")
        sol_pro = USAGE._raw_price("openai/gpt-6-sol-pro")
        self.assertEqual(
            (sol_pro["in"], sol_pro["out"], sol_pro["cache_read"]),
            (sol["in"], sol["out"], sol["cache_read"]),
        )
        luna = USAGE._raw_price("openai/gpt-6-luna")
        luna_pro = USAGE._raw_price("openai/gpt-6-luna-pro")
        self.assertEqual(
            (luna_pro["in"], luna_pro["out"], luna_pro["cache_read"]),
            (luna["in"], luna["out"], luna["cache_read"]),
        )

    def test_official_direct_prices(self):
        sol = USAGE._raw_price("openai/gpt-6-sol")
        self.assertEqual((sol["in"], sol["out"], sol["cache_read"], sol["cache_write"]),
                         (2.0, 10.0, 0.2, 2.5))
        luna = USAGE._raw_price("openai/gpt-6-luna")
        self.assertEqual((luna["in"], luna["out"], luna["cache_read"], luna["cache_write"]),
                         (0.1, 0.5, 0.01, 0.125))

    def test_codex_cost_uses_gpt6_price_not_gpt55_fallback(self):
        # 高上下文加价(inp > 272K 时输入/缓存价 ×2、输出 ×1.5)。
        sol = USAGE._codex_estimated_cost("openai/gpt-6-sol", 1_000_000, 500_000, 1_000_000)
        self.assertAlmostEqual(sol, 0.5 * 4.0 + 0.5 * 0.4 + 15.0, places=9)
        sol_small = USAGE._codex_estimated_cost("openai/gpt-6-sol", 200_000, 100_000, 100_000)
        self.assertAlmostEqual(sol_small, 0.1 * 2.0 + 0.1 * 0.2 + 0.1 * 10.0, places=9)
        luna_small = USAGE._codex_estimated_cost("openai/gpt-6-luna", 200_000, 100_000, 100_000)
        self.assertAlmostEqual(luna_small, 0.1 * 0.1 + 0.1 * 0.01 + 0.1 * 0.5, places=9)
        gpt55 = USAGE._codex_estimated_cost("openai/gpt-5.5", 200_000, 100_000, 100_000)
        self.assertGreater(gpt55, sol_small * 2)

    def test_display_names(self):
        self.assertEqual(USAGE.nice_model("openai/gpt-6-sol"), "GPT-6 Sol")
        self.assertEqual(USAGE.nice_model("openai/gpt-6-luna"), "GPT-6 Luna")
        self.assertEqual(USAGE.nice_model("openai/gpt-6-astra"), "GPT-6 Astra")

    def test_gpt56_prices_unchanged(self):
        sol = USAGE._raw_price("openai/gpt-5.6-sol")
        self.assertEqual((sol["in"], sol["out"]), (4.0, 20.0))


if __name__ == "__main__":
    unittest.main()
