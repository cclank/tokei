import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

@unittest.skipUnless(sys.platform == "darwin", "macOS native login item test")
class LaunchAgentCommandTests(unittest.TestCase):
    def test_large_output_stderr_and_exit_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "command-check"
            subprocess.run([
                "swiftc", "-parse-as-library", "-module-cache-path",
                os.environ.get("SWIFT_MODULECACHE_PATH", str(Path(tmp) / "modules")),
                str(ROOT / "Tokei/Sources/Tokei/LoginItemManager.swift"),
                str(ROOT / "Tokei/Sources/Tokei/L10n.swift"),
                str(ROOT / "tests/swift/LaunchAgentCommandCheck.swift"),
                "-o", str(binary),
            ], check=True, timeout=180)
            process = subprocess.Popen([str(binary)], stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, start_new_session=True)
            try:
                stdout, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                self.fail("Command output blocked app startup/settings for over 10 seconds")
            self.assertEqual(process.returncode, 0, stdout + stderr)
            self.assertIn("launch agent command checks passed", stdout)

if __name__ == "__main__":
    unittest.main()
