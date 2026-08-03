import unittest

try:
    from .test_codex_limits import USAGE
except ImportError:
    from test_codex_limits import USAGE


class ModelNameTests(unittest.TestCase):
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
        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()
