import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LoginItemManagerTests(unittest.TestCase):
    def test_registration_intent_and_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "login-item-check"
            subprocess.run(
                [
                    "swiftc",
                    "-parse-as-library",
                    "-framework", "Combine",
                    "-framework", "ServiceManagement",
                    str(ROOT / "Tokei/Sources/Tokei/LoginItemManager.swift"),
                    str(ROOT / "Tokei/Sources/Tokei/L10n.swift"),
                    str(ROOT / "tests/swift/LoginItemManagerCheck.swift"),
                    "-o", str(binary),
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
            self.assertIn("login item manager checks passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
