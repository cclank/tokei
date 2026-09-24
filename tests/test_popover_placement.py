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
                    str(ROOT / "Tokei/Sources/Tokei/L10n.swift"),
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

    def test_panel_size_follows_content_and_screen_not_a_hardcoded_constant(self):
        """面板高度不能是写死的数：对某台机器合适的值，换块屏幕不是浪费就是超出。

        之前 preferredHeight = 840，在 1152 高的屏幕上白白少用两百多点。
        """
        placement = (ROOT / "Tokei/Sources/Tokei/PanelPlacement.swift").read_text()
        app_source = (ROOT / "Tokei/Sources/Tokei/main.swift").read_text()

        self.assertNotIn("preferredHeight", placement, "高度不得写死")
        self.assertNotIn("preferredWidth", placement, "宽度不得写死")
        self.assertIn("fitting contentSize: CGSize", placement, "尺寸须由内容算出")
        self.assertIn("maximumHeight(", placement, "仍须被屏幕夹住")
        # 封顶按屏幕比例，不是绝对值——否则换块屏幕不是顶满就是浪费
        self.assertIn("heightRatio", placement, "上限须按屏幕比例")
        self.assertIn("visibleHeight * heightRatio", placement)
        # 量内容必须发生在打开之前：开着的时候改尺寸会让 NSPopover 重挑锚点
        self.assertIn("measuredPanelSize()", app_source)
        self.assertIn("scrollable: false", app_source, "量的是不套滚动视图的那份")


if __name__ == "__main__":
    unittest.main()
