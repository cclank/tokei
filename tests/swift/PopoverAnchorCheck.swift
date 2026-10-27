import AppKit

private enum TestFailure: Error { case assertion(String) }

@main
struct PopoverAnchorCheck {
    @MainActor
    static func main() throws {
        let app = NSApplication.shared
        app.setActivationPolicy(.prohibited)

        let primary = NSRect(x: 0, y: 0, width: 1920, height: 1080)
        let external = NSRect(x: -2560, y: -300, width: 2560, height: 1440)
        let menu: CGFloat = 24
        // 真实菜单栏窗口可高于 system.thickness，22 点按钮居中放在 33 点窗口内。
        let insetButton = NSRect(x: 933, y: 1053.5, width: 22, height: 22)
        try expect(PopoverAnchorGeometry.visibleButtonRect(insetButton, screen: primary,
                                                          menuBarHeight: 33) == insetButton,
                   "a visible inset button in a taller menu bar remains usable")
        try expect(PopoverAnchorGeometry.visibleButtonRect(
            insetButton.offsetBy(dx: 0, dy: -50), screen: primary, menuBarHeight: 33
        ) == nil, "a taller menu bar still rejects offscreen or hidden button positions")
        for screen in [primary, external] {
            let button = NSRect(x: screen.minX + 900, y: screen.maxY - menu, width: 64, height: menu)
            try expect(PopoverAnchorGeometry.visibleButtonRect(button, screen: screen,
                                                              menuBarHeight: menu) == button,
                       "negative monitor coordinates are valid")
            for invalid in [NSRect.zero,
                            NSRect(x: button.minX, y: screen.maxY + 8, width: 64, height: menu),
                            NSRect(x: screen.minX - 100, y: button.minY, width: 64, height: menu),
                            NSRect(x: button.minX, y: screen.midY, width: 64, height: menu),
                            NSRect(x: CGFloat.infinity, y: button.minY, width: 64, height: menu)] {
                try expect(PopoverAnchorGeometry.visibleButtonRect(invalid, screen: screen,
                                                                  menuBarHeight: menu) == nil,
                           "hidden or invalid status-item coordinates are ignored")
            }
        }

        guard let screen = NSScreen.screens.first else { throw TestFailure.assertion("No screen") }
        let button = NSRect(x: screen.frame.midX, y: screen.frame.maxY - menu,
                            width: 64, height: menu)
        let anchor = PopoverAnchor()
        try expect(!anchor.update(buttonRect: .zero, screenFrame: screen.frame, menuBarHeight: menu),
                   "an invalid initial position must not create a window")
        try expect(anchor.view == nil, "invalid initial coordinates leave no invisible window")
        try expect(anchor.update(buttonRect: button, screenFrame: screen.frame, menuBarHeight: menu),
                   "a visible button creates the anchor")
        guard let view = anchor.view, let anchorWindow = view.window else {
            throw TestFailure.assertion("No anchor view")
        }
        try expect(anchorWindow.isVisible && !anchorWindow.canBecomeKey && !anchorWindow.canBecomeMain,
                   "the transparent anchor stays visible without stealing focus")
        try expect(anchorWindow.ignoresMouseEvents && !anchorWindow.isOpaque,
                   "the anchor cannot intercept menu-bar clicks")

        let controller = NSViewController()
        controller.view = NSView(frame: NSRect(x: 0, y: 0, width: 320, height: 240))
        let popover = NSPopover()
        popover.contentViewController = controller
        popover.behavior = .applicationDefined
        popover.animates = false
        popover.show(relativeTo: view.bounds, of: view, preferredEdge: .minY)
        settle()
        guard let popupWindow = controller.view.window, popover.isShown else {
            throw TestFailure.assertion("Popover did not open")
        }
        let initialPopup = popupWindow.frame
        let initialAnchor = anchorWindow.frame

        // 重复菜单栏收起、坐标归零、重新出现和收起动画，覆盖视频里的来回跳动。
        for _ in 0..<12 {
            for rect in [NSRect.zero,
                         NSRect(x: button.minX, y: screen.frame.maxY + 8, width: 64, height: menu),
                         button.offsetBy(dx: 0, dy: 1), button] {
                anchor.update(buttonRect: rect, screenFrame: screen.frame, menuBarHeight: menu)
                settle()
                try expect(anchorWindow.frame == initialAnchor,
                           "menu-bar hiding keeps the anchor fixed: input=\(rect), initial=\(initialAnchor), actual=\(anchorWindow.frame)")
                try expect(popover.isShown && popupWindow.frame == initialPopup,
                           "menu-bar hiding keeps the actual popover fixed")
            }
        }

        let shifted = button.offsetBy(dx: -80, dy: 0)
        try expect(anchor.update(buttonRect: shifted, screenFrame: screen.frame, menuBarHeight: menu),
                   "quota text width changes can move the anchor horizontally")
        settle()
        try expect(anchorWindow.frame.minX == initialAnchor.minX - 80 &&
                   anchorWindow.frame.minY == initialAnchor.minY,
                   "horizontal following preserves the vertical origin")
        try expect(abs(popupWindow.frame.midX - initialPopup.midX + 80) < 1,
                   "the native popover follows the horizontal anchor")
        let beforeResize = anchorWindow.frame
        for width: CGFloat in [640, 322, 640, 322] {
            popover.contentSize = NSSize(width: width, height: 240)
            popover.show(relativeTo: view.bounds, of: view, preferredEdge: .minY)
            settle()
            try expect(popover.isShown && anchorWindow.frame == beforeResize,
                       "switching to a wider page reuses the stable anchor")
            try expect(abs(popupWindow.frame.maxY - initialPopup.maxY) < 1,
                       "page resizing stays below the same menu-bar position")
        }
        try expect(!anchor.update(buttonRect: NSRect(x: external.midX, y: external.maxY - menu,
                                                     width: 64, height: menu),
                                  screenFrame: external, menuBarHeight: menu),
                   "a shown panel cannot migrate to another monitor")

        popover.close()
        anchor.close()
        try expect(anchor.view == nil && anchor.screenFrame == nil && !anchorWindow.isVisible,
                   "closing releases the anchor window and selected monitor")
        let reopen = NSRect(x: screen.frame.midX - 100, y: screen.frame.maxY - menu, width: 48, height: menu)
        try expect(anchor.update(buttonRect: reopen, screenFrame: screen.frame, menuBarHeight: menu),
                   "reopening samples the current button position")
        try expect(anchor.view !== view, "reopening gets a fresh anchor")
        anchor.close()
        print("popover anchor checks passed: 48 native hide/show updates, horizontal follow, page resize, cleanup")
    }

    @MainActor
    private static func settle() {
        RunLoop.main.run(until: Date().addingTimeInterval(0.04))
    }

    private static func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
        if !condition() { throw TestFailure.assertion(message) }
    }
}
