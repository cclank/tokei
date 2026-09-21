import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PopoverPlacementTests(unittest.TestCase):
    def test_anchor_screen_takes_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "popover-placement-check"
            subprocess.run(
                [
                    "swiftc",
                    "-parse-as-library",
                    "-module-cache-path", str(Path(tmp) / "module-cache"),
                    "-framework", "AppKit",
                    str(ROOT / "Tokei/Sources/Tokei/PanelPlacement.swift"),
                    str(ROOT / "tests/swift/PopoverPlacementCheck.swift"),
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
            self.assertIn("popover placement checks passed", result.stdout)

    def test_app_uses_a_fixed_frame_without_reshowing_while_open(self):
        app_source = (ROOT / "Tokei/Sources/Tokei/main.swift").read_text()
        panel_source = (ROOT / "Tokei/Sources/Tokei/PanelView.swift").read_text()

        self.assertIn("popoverAnchorButton = sender", app_source)
        self.assertIn("button.window?.screen?.visibleFrame", app_source)
        self.assertIn("host.sizingOptions = []", app_source)
        self.assertIn("popover.contentSize = panelLayout.contentSize", app_source)
        self.assertNotIn("reanchorPopover", app_source)
        self.assertNotIn("PanelContentSizeKey", panel_source)
        self.assertNotIn("NSScreen.main?.visibleFrame", panel_source)


if __name__ == "__main__":
    unittest.main()
