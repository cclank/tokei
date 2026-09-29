import AppKit

private enum TestFailure: Error {
    case assertion(String)
}

@main
struct PopoverPlacementCheck {
    static func main() throws {
        // 换页只在宽度真的变了时才请 App 重新摆放弹窗（issue #105），其余一律不动（issue #97）。
        let layout = PanelLayoutContext(contentSize: CGSize(width: 322, height: 600))
        var refits = 0
        layout.onPageWidthChange = { refits += 1 }
        layout.pageDidChange("cards", width: 322)
        try expect(refits == 0, "reporting the current page again must not refit")
        layout.pageDidChange("settings", width: 640)
        try expect(refits == 1 && layout.page == "settings", "a wider page must refit once")
        layout.pageDidChange("settings", width: 640)
        try expect(refits == 1, "staying on the same page must not refit")
        let wide = PanelLayoutContext(contentSize: CGSize(width: 640, height: 600))
        var wideRefits = 0
        wide.onPageWidthChange = { wideRefits += 1 }
        wide.pageDidChange("settings", width: 640)
        wide.pageDidChange("dashboard", width: 640)
        wide.pageDidChange("cards", width: 640)
        try expect(wideRefits == 0 && wide.page == "cards",
                   "pages with the same width keep the fixed frame")

        let external = NSRect(x: 1920, y: 0, width: 1920, height: 1040)
        let focused = NSRect(x: 0, y: 0, width: 1512, height: 900)

        try expect(
            PanelPlacement.maximumHeight(
                anchorVisibleFrame: external,
                fallbackVisibleFrame: focused
            ) == 1040 * PanelPlacement.heightRatio,
            "the status-item screen must take precedence over the focused screen"
        )
        try expect(
            PanelPlacement.maximumHeight(
                anchorVisibleFrame: nil,
                fallbackVisibleFrame: focused
            ) == 900 * PanelPlacement.heightRatio,
            "the fallback screen should be used only when the anchor screen is unavailable"
        )
        try expect(
            PanelPlacement.maximumHeight(
                anchorVisibleFrame: NSRect(x: 0, y: 0, width: 800, height: 300),
                fallbackVisibleFrame: nil
            ) == PanelPlacement.minimumHeight,
            "small screens should retain a usable minimum panel height"
        )
        // 内容要多少给多少：以前写死 840，在 1040 高的屏幕上白白少用一百多点。
        try expect(
            PanelPlacement.contentSize(
                fitting: CGSize(width: 322, height: 400),
                anchorVisibleFrame: external,
                fallbackVisibleFrame: focused
            ) == CGSize(width: 322, height: 400),
            "a panel shorter than the ceiling should keep its own height"
        )
        // 但不能超出这块屏幕装得下的范围。
        try expect(
            PanelPlacement.contentSize(
                fitting: CGSize(width: 640, height: 5000),
                anchorVisibleFrame: external,
                fallbackVisibleFrame: focused
            ) == CGSize(width: 640, height: (1040 * PanelPlacement.heightRatio).rounded(.up)),
            "content taller than the screen must be clamped to a share of it"
        )
        // 换一块屏幕就是另一个上限——没有哪台机器的数字被写死。
        try expect(
            PanelPlacement.contentSize(
                fitting: CGSize(width: 640, height: 5000),
                anchorVisibleFrame: focused
            ).height == (900 * PanelPlacement.heightRatio).rounded(.up),
            "the ceiling follows the screen, not a hardcoded constant"
        )
        // 小屏也要留住可用的最小高度。
        try expect(
            PanelPlacement.contentSize(
                fitting: CGSize(width: 322, height: 100),
                anchorVisibleFrame: NSRect(x: 0, y: 0, width: 800, height: 300)
            ).height == PanelPlacement.minimumHeight,
            "tiny content still gets a usable minimum height"
        )
        // 还没量到内容时给一个不离谱的起点，而不是 0。
        try expect(
            PanelPlacement.contentSize(
                fitting: .zero,
                anchorVisibleFrame: external
            ) == PanelPlacement.provisionalSize,
            "an unmeasured panel falls back to the provisional size"
        )

        print("popover placement checks passed")
    }

    private static func expect(_ condition: @autoclosure () -> Bool,
                               _ message: String) throws {
        if !condition() {
            throw TestFailure.assertion(message)
        }
    }
}
