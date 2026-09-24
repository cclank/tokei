import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ActivityReporterTests(unittest.TestCase):
    def test_default_on_saved_opt_out_payload_persistence_once_per_launch_and_cancellation(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = str(Path(tmp) / "activity-reporter-check")
            result = subprocess.run([
                "swiftc", str(ROOT / "Tokei/Sources/Tokei/ActivityReporter.swift"),
                str(ROOT / "Tokei/Sources/Tokei/L10n.swift"),
                str(ROOT / "tests/swift/ActivityReporterCheck.swift"), "-o", binary,
            ], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([binary], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Activity reporter checks passed", result.stdout)
