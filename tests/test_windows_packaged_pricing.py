import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from .test_codex_limits import USAGE
except ImportError:
    from test_codex_limits import USAGE


ROOT = Path(__file__).resolve().parents[1]


class WindowsPackagedPricingTests(unittest.TestCase):
    def test_fresh_bundle_preserves_default_prices_and_model_aliases(self):
        config_path = ROOT / "windows/src-tauri/tauri.conf.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        expected = json.loads((ROOT / "pricing_overrides.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp)
            for source, destination in config["bundle"]["resources"].items():
                target = bundle / destination
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(config_path.parent / source, target)
            collector_dir = bundle / "collector"
            overrides_path = collector_dir / "pricing_overrides.json"
            overrides = json.loads(overrides_path.read_text(encoding="utf-8")) if overrides_path.exists() else {}
            models, aliases = USAGE._merge_pricing_overrides(overrides, official={})
            catalog = json.loads((collector_dir / "pricing.json").read_text(encoding="utf-8"))["models"]
            with mock.patch.object(USAGE, "_OV_MODELS", models), \
                 mock.patch.object(USAGE, "_OV_ALIASES", aliases), \
                 mock.patch.object(USAGE, "_PRICING_DB", catalog):
                for alias, canonical in expected["aliases"].items():
                    with self.subTest(alias=alias):
                        self.assertEqual(USAGE._model_identity_id(alias), canonical)
                for model, rates in expected["models"].items():
                    with self.subTest(model=model):
                        actual = USAGE.price_for(model)
                        for field in ("in", "out", "cache_read"):
                            self.assertEqual(actual[field], rates[field])


if __name__ == "__main__":
    unittest.main()
