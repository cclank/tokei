import AppKit
import Combine

enum PanelPlacement {
    static let preferredWidth: CGFloat = 640
    static let preferredHeight: CGFloat = 840
    static let verticalMargin: CGFloat = 40
    static let minimumHeight: CGFloat = 320
    static let fallbackVisibleHeight: CGFloat = 900

    static func maximumHeight(anchorVisibleFrame: NSRect?,
                              fallbackVisibleFrame: NSRect? = nil) -> CGFloat {
        let visibleHeight = anchorVisibleFrame?.height
            ?? fallbackVisibleFrame?.height
            ?? fallbackVisibleHeight
        return max(minimumHeight, visibleHeight - verticalMargin)
    }

    static func contentSize(anchorVisibleFrame: NSRect?,
                            fallbackVisibleFrame: NSRect? = nil) -> CGSize {
        CGSize(
            width: preferredWidth,
            height: min(
                preferredHeight,
                maximumHeight(
                    anchorVisibleFrame: anchorVisibleFrame,
                    fallbackVisibleFrame: fallbackVisibleFrame
                )
            )
        )
    }
}

final class PanelLayoutContext: ObservableObject {
    @Published private(set) var contentSize: CGSize

    init(contentSize: CGSize = PanelPlacement.contentSize(anchorVisibleFrame: nil)) {
        self.contentSize = contentSize
    }

    func update(anchorVisibleFrame: NSRect?, fallbackVisibleFrame: NSRect?) {
        let nextSize = PanelPlacement.contentSize(
            anchorVisibleFrame: anchorVisibleFrame,
            fallbackVisibleFrame: fallbackVisibleFrame
        )
        guard abs(contentSize.width - nextSize.width) > 0.5
                || abs(contentSize.height - nextSize.height) > 0.5 else { return }
        contentSize = nextSize
    }
}
