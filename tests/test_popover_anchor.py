"""The native popover keeps its screen position while a menu-bar anchor hides."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == "darwin", "AppKit popovers require macOS")
class PopoverAnchorTests(unittest.TestCase):
    def test_menu_bar_motion_cannot_move_the_open_panel_to_invalid_coordinates(self):
        env = os.environ.copy()
        sdk = Path("/Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk")
        if "SDKROOT" not in env and sdk.is_dir():
            env["SDKROOT"] = str(sdk)
        with tempfile.TemporaryDirectory(prefix="tokei-popover-anchor-") as tmp:
            binary = Path(tmp) / "check"
            command = ["swiftc", "-parse-as-library", "-module-cache-path",
                       env.get("SWIFT_MODULECACHE_PATH", str(Path(tmp) / "modules"))]
            if env.get("SDKROOT"):
                command += ["-sdk", env["SDKROOT"]]
            command += [
                 str(ROOT / "Tokei/Sources/Tokei/PopoverAnchor.swift"),
                 str(ROOT / "tests/swift/PopoverAnchorCheck.swift"), "-o", str(binary)]
            # A cold SDK import can exceed a minute. Bound compilation time and
            # clean up the front end before deleting its temporary cache.
            compiler = subprocess.Popen(command, env=env, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, start_new_session=True)
            try:
                stdout, stderr = compiler.communicate(timeout=180)
            except subprocess.TimeoutExpired:
                # The Swift driver can give its front end another process group.
                subprocess.run(["pkill", "-KILL", "-P", str(compiler.pid)],
                               capture_output=True, check=False)
                try:
                    os.killpg(compiler.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                stdout, stderr = compiler.communicate()
                self.fail("Swift compilation timed out before native assertions: " + stdout + stderr)
            self.assertEqual(compiler.returncode, 0, stdout + stderr)
            result = subprocess.run([str(binary)], env=env, capture_output=True,
                                    text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("popover anchor checks passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
