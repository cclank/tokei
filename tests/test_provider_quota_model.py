import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProviderQuotaModelTests(unittest.TestCase):
    def test_swift_model_decodes_provider_quota(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "provider-quota-model-check"
            result = subprocess.run(
                [
                    "swiftc",
                    "-parse-as-library",
                    str(ROOT / "Tokei/Sources/Tokei/Model.swift"),
                    str(ROOT / "Tokei/Sources/Tokei/L10n.swift"),
                    str(ROOT / "tests/swift/ProviderQuotaModelCheck.swift"),
                    "-o",
                    str(binary),
                ],
                capture_output=True,
                text=True,
                cwd=ROOT,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("provider quota model checks passed", result.stdout)

    def test_gemini_card_requires_selected_range_usage(self):
        source = (ROOT / "Tokei/Sources/Tokei/PanelView.swift").read_text()
        start = source.index('ToolCardItem(id: "gemini"')
        end = source.index('ToolCardItem(id: "cursor"', start)
        gemini_card = source[start:end]

        self.assertIn("active: geminiRange.hasUsage", gemini_card)
        self.assertNotIn("antigravity.available", gemini_card)
        self.assertNotIn("displayRange", source)

    def test_cursor_card_requires_selected_range_usage(self):
        source = (ROOT / "Tokei/Sources/Tokei/PanelView.swift").read_text()
        start = source.index('ToolCardItem(id: "cursor"')
        end = source.index('ToolCardItem(id: "zed"', start)
        cursor_card = source[start:end]

        self.assertIn("active: cursorUsage.totalTokens > 0 || cursorUsage.requests > 0", cursor_card)
        self.assertNotIn("u.cursor.available", cursor_card)

    def test_sync_manager_provider_config_typechecks(self):
        result = subprocess.run(
            [
                "swiftc",
                "-typecheck",
                str(ROOT / "Tokei/Sources/Tokei/L10n.swift"),
                str(ROOT / "Tokei/Sources/Tokei/Model.swift"),
                str(ROOT / "Tokei/Sources/Tokei/SyncManager.swift"),
                str(ROOT / "tests/swift/SyncManagerProviderConfigTypes.swift"),
            ],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
