import AppKit

/// 菜单栏收起时，系统按钮的窗口可能移到屏幕外或暂时报出零坐标。
/// 只接受屏幕顶边的有效按钮位置，供独立锚点跟随横向位置变化。
enum PopoverAnchorGeometry {
    static func visibleButtonRect(_ rect: NSRect, screen: NSRect,
                                  menuBarHeight: CGFloat) -> NSRect? {
        let values = [rect.minX, rect.minY, rect.width, rect.height,
                      screen.minX, screen.minY, screen.width, screen.height, menuBarHeight]
        guard values.allSatisfy(\.isFinite), rect.width > 0, rect.height > 0,
              screen.width > 0, screen.height > 0, menuBarHeight > 0,
              rect.midX >= screen.minX, rect.midX <= screen.maxX,
              rect.maxY <= screen.maxY + 1,
              rect.minY >= screen.maxY - max(menuBarHeight, rect.height) - 1 else {
            return nil
        }
        return rect
    }
}

/// 由 AppDelegate 的主线程事件入口调用，与现有 AppKit 生命周期保持一致。
final class PopoverAnchor {
    private final class AnchorPanel: NSPanel {
        override var canBecomeKey: Bool { false }
        override var canBecomeMain: Bool { false }
    }

    private var panel: NSPanel?
    private var buttonMidX: CGFloat?
    private(set) var screenFrame: NSRect?
    var view: NSView? { panel?.contentView }

    @discardableResult
    func update(from button: NSStatusBarButton) -> Bool {
        precondition(Thread.isMainThread)
        guard let window = button.window, window.isVisible, let screen = window.screen else {
            return false
        }
        // 大菜单栏等布局下，按钮会居中放在比 system.thickness 更高的窗口里。
        // 用实际状态栏窗口高度覆盖这段留白，避免把仍可见的按钮误判为收起。
        let menuBarHeight = max(NSStatusBar.system.thickness, window.frame.height)
        return update(buttonRect: window.convertToScreen(button.convert(button.bounds, to: nil)),
                      screenFrame: screen.frame, menuBarHeight: menuBarHeight)
    }

    @discardableResult
    func update(buttonRect: NSRect, screenFrame: NSRect, menuBarHeight: CGFloat) -> Bool {
        precondition(Thread.isMainThread)
        guard let rect = PopoverAnchorGeometry.visibleButtonRect(
            buttonRect, screen: screenFrame, menuBarHeight: menuBarHeight
        ), self.screenFrame == nil || self.screenFrame == screenFrame else { return false }

        // 一次打开期间保持纵向位置。按钮的额度文字变宽时，锚点仍能横向跟随。
        if let panel {
            if let previousX = buttonMidX, previousX != rect.midX {
                // AppKit 会把新窗口对齐到屏幕像素，1 点窗口可能落成 2 点宽。
                // 沿用实际尺寸，避免重复测量把锚点宽度改小，引起弹窗重新定位。
                var frame = panel.frame
                frame.origin.x += rect.midX - previousX
                panel.setFrame(frame, display: false)
            }
        } else {
            let frame = NSRect(x: rect.midX - 0.5, y: rect.minY, width: 1, height: 1)
            let anchor = AnchorPanel(contentRect: frame,
                                     styleMask: [.borderless, .nonactivatingPanel],
                                     backing: .buffered, defer: false)
            anchor.isReleasedWhenClosed = false
            anchor.isOpaque = false
            anchor.backgroundColor = .clear
            anchor.hasShadow = false
            anchor.ignoresMouseEvents = true
            anchor.hidesOnDeactivate = false
            anchor.isExcludedFromWindowsMenu = true
            anchor.level = .statusBar
            anchor.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
            anchor.contentView = NSView(frame: NSRect(origin: .zero, size: frame.size))
            self.screenFrame = screenFrame
            panel = anchor
            // 保持窗口可见且内容透明，使 NSPopover 的公开定位 API 始终拿到有效视图。
            anchor.orderFrontRegardless()
        }
        buttonMidX = rect.midX
        return true
    }

    func close() {
        precondition(Thread.isMainThread)
        panel?.close()
        panel = nil
        buttonMidX = nil
        screenFrame = nil
    }
}
