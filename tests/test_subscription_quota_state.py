import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SubscriptionQuotaStateTests(unittest.TestCase):
    def test_swift_state_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "subscription-quota-state-check"
            result = subprocess.run(
                [
                    "swiftc",
                    str(ROOT / "Tokei/Sources/Tokei/SubscriptionQuotaState.swift"),
                    str(ROOT / "Tokei/Sources/Tokei/L10n.swift"),
                    str(ROOT / "tests/swift/SubscriptionQuotaStateCheck.swift"),
                    "-o",
                    str(binary),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("subscription quota state checks passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
