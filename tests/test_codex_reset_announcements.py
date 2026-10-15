import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == "darwin", "macOS Swift/Combine integration")
class CodexResetAnnouncementTests(unittest.TestCase):
    def test_feed_timing_and_network_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / "reset-check"
            source = ROOT / "Tokei/Sources/Tokei"
            result = subprocess.run([
                "swiftc", "-parse-as-library",
                str(source / "CodexResetFeed.swift"),
                str(source / "CodexResetMonitor.swift"),
                str(ROOT / "tests/swift/CodexResetAnnouncementCheck.swift"),
                "-o", str(binary),
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run(["codesign", "--force", "--sign", "-", str(binary)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary), temp], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("reset announcement checks passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
