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

    def test_only_a_page_of_a_different_width_reshows_the_open_panel(self):
        """卡片不超过两张时首页是窄版，进设置、额度曲线会被固定画布裁掉（issue #105）。

        开着的面板只允许在「换页且宽度变了」时重新显示一次，走和打开时同一条路径；
        切页签、刷新数据仍然不能改画布（issue #97）。
        """
        app_source = (ROOT / "Tokei/Sources/Tokei/main.swift").read_text()
        panel_source = (ROOT / "Tokei/Sources/Tokei/PanelView.swift").read_text()

        # 只有两处 show：打开面板，以及换到宽度不同的页面
        self.assertEqual(app_source.count("popover.show(relativeTo: "), 2)
        self.assertEqual(app_source.count("refitPanelForPage()"), 2, "定义一处，只由换页回调调用")
        self.assertIn("panelLayout.onPageWidthChange", app_source)
        # 关掉时停在设置页，重开也得按设置页量
        self.assertIn("PanelView.PanelMode(rawValue: panelLayout.page)", app_source)
        self.assertIn("layout.pageDidChange(next.rawValue, width: pageWidth(for: next))",
                      panel_source)

    def test_status_item_stays_visible_and_reopening_the_app_shows_the_panel(self):
        """macOS 26 上可变宽度初始化的状态栏项偶发被压没，进程在跑、图标却看不到（issue #8）。"""
        app_source = (ROOT / "Tokei/Sources/Tokei/main.swift").read_text()
        self.assertIn("statusItem(withLength: NSStatusItem.squareLength)", app_source)
        self.assertNotIn("statusItem(withLength: NSStatusItem.variableLength)", app_source)
        self.assertGreaterEqual(app_source.count("isVisible = true"), 3, "启动、下一轮、每次定宽都确认可见")
        # squareLength 是占位常量不是宽度，定宽的下限仍用菜单栏厚度
        self.assertIn("max(NSStatusBar.system.thickness, compactWidth)", app_source)
        self.assertIn("func applicationShouldHandleReopen", app_source)
        self.assertIn("button.window != nil", app_source, "按钮不在窗口里时不能硬挂弹窗")

    def test_switching_pages_never_animates_the_panel_layout(self):
        """面板挂在菜单栏按钮上，开着的时候做动画式布局会让 AppKit 重新挑选屏幕
        和锚点——全屏 Space 与外接显示器下会把面板甩到屏幕边上（issue #97）。

        高亮块可以做动画，页面切换不行。两者写在同一个闭包里时 SwiftUI 会并进
        同一个事务，所以切换必须显式关掉动画。
        """
        design = (ROOT / "Tokei/Sources/Tokei/Design.swift").read_text()
        app_source = (ROOT / "Tokei/Sources/Tokei/main.swift").read_text()

        self.assertIn("pageChange.disablesAnimations = true", design)
        self.assertIn("withTransaction(pageChange) { sel = k }", design)
        # 同一件事的另外两个入口，一并守住
        self.assertIn("host.sizingOptions = []", app_source)
        self.assertIn("popover.animates = false", app_source)

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
