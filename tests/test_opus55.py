import unittest

try:
    from .test_codex_limits import USAGE
except ImportError:
    from test_codex_limits import USAGE


class Opus55SupportTests(unittest.TestCase):
    def test_official_price_matches_anthropic_docs(self):
        # https://platform.claude.com/docs/en/models/opus-5-5/overview
        # in 4.0 / out 20.0 / 5m-write 5.0 / 1h-write 8.0 / read 0.20。
        opus = USAGE._raw_price("anthropic/claude-opus-5.5")
        self.assertEqual(
            (opus["in"], opus["out"], opus["cache_read"], opus["cache_write"]),
            (4.0, 20.0, 0.2, 5.0),
        )
        self.assertEqual(opus.get("write1h"), 8.0)

    def test_normalize_variants(self):
        self.assertEqual(USAGE._normalize("claude-opus-5-5"), "anthropic/claude-opus-5.5")
        self.assertEqual(USAGE._normalize("claude-opus-5.5"), "anthropic/claude-opus-5.5")
        self.assertEqual(
            USAGE._normalize("claude-opus-5-5-20260921"), "anthropic/claude-opus-5.5-20260921")

    def test_identity_and_pricing_cover_snapshots(self):
        for variant in ("claude-opus-5-5", "claude-opus-5.5",
                        "claude-opus-5-5-20260921", "claude-opus-5.5-20260921",
                        "anthropic/claude-opus-5.5-20260921",
                        "claude-opus-5.5-latest"):
            self.assertEqual(USAGE._model_identity_id(variant), "anthropic/claude-opus-5.5")
            self.assertEqual(USAGE._pricing_id(variant), "anthropic/claude-opus-5.5")

    def test_snapshot_not_mispriced_as_opus48(self):
        price = USAGE._raw_price("anthropic/claude-opus-5.5-20260921")
        self.assertEqual(price["in"], 4.0)
        self.assertNotEqual(price["in"], USAGE._raw_price("anthropic/claude-opus-4.8")["in"])

    def test_display_names(self):
        self.assertEqual(USAGE.nice_model("anthropic/claude-opus-5.5"), "Opus 5.5")
        self.assertEqual(USAGE.nice_model("claude-opus-5-5"), "Opus 5.5")
        self.assertEqual(USAGE.nice_model("anthropic/claude-opus-5.5-20260921"), "Opus 5.5")
        self.assertEqual(USAGE.nice_model("claude-opus-5-5-20260921"), "Opus 5.5")

    def test_older_opus_names_unchanged(self):
        self.assertEqual(USAGE.nice_model("claude-opus-4-8"), "Opus 4.8")
        self.assertEqual(USAGE.nice_model("anthropic/claude-opus-4.5"), "Opus 4.5")
        self.assertEqual(USAGE._pricing_id("anthropic/claude-opus-5"), "anthropic/claude-opus-5")

    def test_unknown_models_still_preserved(self):
        self.assertEqual(
            USAGE._model_identity_id("private-provider/model-variant"),
            "private-provider/model-variant",
        )
        self.assertIsNone(USAGE._pricing_id("private-provider/model-variant"))


if __name__ == "__main__":
    unittest.main()
