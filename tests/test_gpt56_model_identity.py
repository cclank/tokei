"""Identity vs price: unknown gpt-5.6 variants must not display as GPT-5.5."""
import unittest

from test_codex_limits import USAGE


class Gpt56ModelIdentityTests(unittest.TestCase):
    def test_known_id_preserves_luna_terra_sol(self):
        for raw, expected in (
            ("gpt-5.6-luna", "openai/gpt-5.6-luna"),
            ("gpt-5.6-terra", "openai/gpt-5.6-terra"),
            ("gpt-5.6-sol", "openai/gpt-5.6-sol"),
            ("openai/gpt-5.6-luna", "openai/gpt-5.6-luna"),
        ):
            self.assertEqual(USAGE._known_id_or_raw(raw), expected, raw)
            self.assertNotEqual(USAGE._known_id_or_raw(raw), "openai/gpt-5.5", raw)

    def test_known_priced_gpt55_still_canonical(self):
        self.assertEqual(USAGE._known_id_or_raw("gpt-5.5"), "openai/gpt-5.5")
        self.assertEqual(USAGE._known_id_or_raw("openai/gpt-5.5"), "openai/gpt-5.5")

    def test_price_fallback_does_not_rewrite_identity(self):
        # Use a codename that is not expected in pricing.json so identity
        # and price resolution stay clearly separated on any machine.
        raw = "gpt-5.6-aurora"
        identity = USAGE._known_id_or_raw(raw)
        self.assertEqual(identity, "openai/gpt-5.6-aurora")
        self.assertNotEqual(identity, "openai/gpt-5.5")
        self.assertFalse(
            USAGE._has_known_price(identity),
            "test assumes aurora is unpriced; if priced, pick another codename",
        )
        # Pricing may fall back to a known gpt-5 family row.
        resolved = USAGE._resolve_id(raw)
        self.assertEqual(resolved, "openai/gpt-5.5")
        price = USAGE._raw_price(raw)
        fallback = USAGE._raw_price("openai/gpt-5.5")
        self.assertEqual(price["in"], fallback["in"])
        self.assertEqual(price["out"], fallback["out"])
        self.assertEqual(USAGE.nice_model(identity), "GPT-5.6 Aurora")

    def test_nice_model_includes_variant_suffix(self):
        cases = {
            "gpt-5.6-luna": "GPT-5.6 Luna",
            "openai/gpt-5.6-luna": "GPT-5.6 Luna",
            "gpt-5.6-terra": "GPT-5.6 Terra",
            "gpt-5.6-sol": "GPT-5.6 Sol",
            "openai/gpt-5.5": "GPT-5.5",
            "gpt-5-mini": "GPT-5 Mini",
        }
        for raw, display in cases.items():
            self.assertEqual(USAGE.nice_model(raw), display, raw)

    def test_format_token_models_shows_luna_not_55(self):
        models = {
            "openai/gpt-5.6-luna": {
                "in": 20, "out": 10, "cr": 80, "cw": 0, "reason": 4, "cost": 0.01,
            },
        }
        rows = USAGE._format_token_models(models)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "GPT-5.6 Luna")
        self.assertNotEqual(rows[0]["name"], "GPT-5.5")


if __name__ == "__main__":
    unittest.main()
