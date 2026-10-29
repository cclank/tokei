import sys
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GrokBotQuotaBridgeTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "darwin", "Native Swift app tests require macOS")
    def test_electron_safe_storage_fixture(self):
        swiftc = shutil.which("swiftc")
        if swiftc is None:
            self.skipTest("swiftc is required")
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "grok-bot-bridge-check"
            subprocess.run([
                swiftc,
                "-D", "TOKEI_GROK_BOT_KEYCHAIN_TEST",
                str(ROOT / "Tokei/Sources/GrokBotBridge/GrokBotQuotaBridge.swift"),
                str(ROOT / "tests/swift/GrokBotQuotaBridgeCheck.swift"),
                "-o", str(binary),
            ], check=True, capture_output=True, text=True)
            result = subprocess.run(
                [str(binary)], check=True, capture_output=True, text=True)
            version = subprocess.run(
                [str(binary), "--grok-bot-helper-version"],
                check=True, capture_output=True, text=True)

        self.assertEqual(result.stdout.strip(), "ok")
        self.assertEqual(version.stdout.strip(), "5")

    def test_same_path_authorization_replaces_stale_code_requirement(self):
        source = (ROOT / "Tokei/Sources/GrokBotBridge/GrokBotQuotaBridge.swift").read_text()
        self.assertIn(
            "applications.removeAll { trustedApplicationPath($0) == executablePath }",
            source,
        )
        self.assertNotIn(
            "applications.contains(where: { trustedApplicationPath($0) == executablePath })",
            source,
        )


if __name__ == "__main__":
    unittest.main()
