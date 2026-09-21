import AppKit

private enum TestFailure: Error {
    case assertion(String)
}

@main
struct PopoverPlacementCheck {
    static func main() throws {
        let external = NSRect(x: 1920, y: 0, width: 1920, height: 1040)
        let focused = NSRect(x: 0, y: 0, width: 1512, height: 900)

        try expect(
            PanelPlacement.maximumHeight(
                anchorVisibleFrame: external,
                fallbackVisibleFrame: focused
            ) == 1000,
            "the status-item screen must take precedence over the focused screen"
        )
        try expect(
            PanelPlacement.maximumHeight(
                anchorVisibleFrame: nil,
                fallbackVisibleFrame: focused
            ) == 860,
            "the fallback screen should be used only when the anchor screen is unavailable"
        )
        try expect(
            PanelPlacement.maximumHeight(
                anchorVisibleFrame: NSRect(x: 0, y: 0, width: 800, height: 300),
                fallbackVisibleFrame: nil
            ) == PanelPlacement.minimumHeight,
            "small screens should retain a usable minimum panel height"
        )
        try expect(
            PanelPlacement.contentSize(
                anchorVisibleFrame: external,
                fallbackVisibleFrame: focused
            ) == CGSize(width: 640, height: 840),
            "the popover frame should remain fixed while switching pages"
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
