import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class QuotaHistoryTests(unittest.TestCase):
    def test_minute_aggregation_activity_and_retention(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "quota-history-check"
            subprocess.run(
                [
                    "swiftc",
                    "-parse-as-library",
                    "-framework", "Combine",
                    str(ROOT / "Tokei/Sources/Tokei/QuotaHistoryStore.swift"),
                    str(ROOT / "Tokei/Sources/Tokei/L10n.swift"),
                    str(ROOT / "Tokei/Sources/Tokei/QuotaHistoryProjection.swift"),
                    str(ROOT / "tests/swift/QuotaHistoryStoreCheck.swift"),
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
            self.assertIn("quota history store checks passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
