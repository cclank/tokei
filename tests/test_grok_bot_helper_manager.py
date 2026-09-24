import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GrokBotHelperManagerTests(unittest.TestCase):
    def test_persistent_helper_is_installed_once_and_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "grok-bot-helper-manager-check"
            subprocess.run(
                [
                    "swiftc",
                    "-parse-as-library",
                    str(ROOT / "Tokei/Sources/Tokei/GrokBotHelperManager.swift"),
                    str(ROOT / "Tokei/Sources/Tokei/L10n.swift"),
                    str(ROOT / "tests/swift/GrokBotHelperManagerCheck.swift"),
                    "-o",
                    str(binary),
                ],
                check=True,
                cwd=ROOT,
            )
            result = subprocess.run(
                [str(binary)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("grok bot helper manager checks passed", result.stdout)

    def test_release_package_contains_the_helper(self):
        package = (ROOT / "Tokei/Package.swift").read_text()
        script = (ROOT / "Tokei/package.sh").read_text()
        loader = (ROOT / "Tokei/Sources/Tokei/DataLoader.swift").read_text()
        self.assertIn('name: "TokeiGrokBotHelper"', package)
        self.assertIn('Contents/Helpers/TokeiGrokBotHelper', script)
        self.assertIn("GrokBotHelperManager.resolvedHelperURL()", loader)


if __name__ == "__main__":
    unittest.main()
