import AppKit
import Combine

enum PanelPlacement {
    static let verticalMargin: CGFloat = 40
    /// 面板最多占屏幕可见高度的多少。
    ///
    /// 内容天然比任何屏幕都长（实测约 1569 点），所以"贴合内容"如果不封顶，
    /// 等于每次都顶满屏幕，看着很压抑。按比例封顶才是跟着屏幕走的做法：
    /// 之前写死的 840 在 1112 高的屏幕上正好约 3/4，换到 13 寸上却会顶满。
    /// 面板占屏幕的份额固定，无论哪块屏幕看起来都是同一个观感。
    /// 实测取值：0.618 / 0.718 / 0.8 依次偏短，0.88 在 1122 高的屏幕上约 987 点，
    /// 距离顶满（1082）仍留约 95 点余量，不至于贴边。
    static let heightRatio: CGFloat = 0.88
    static let minimumHeight: CGFloat = 320
    static let minimumWidth: CGFloat = 322
    static let fallbackVisibleHeight: CGFloat = 900
    /// 还没量到内容时用的尺寸（启动那一刻）。面板真正打开前一定会按内容重量一次，
    /// 所以这只是个不至于太离谱的起点，不是目标尺寸。
    static let provisionalSize = CGSize(width: 640, height: 640)

    /// 这块屏幕上面板最高能有多少：按比例取，再留出上下边距，并保住最小可用高度。
    static func maximumHeight(anchorVisibleFrame: NSRect?,
                              fallbackVisibleFrame: NSRect? = nil) -> CGFloat {
        let visibleHeight = anchorVisibleFrame?.height
            ?? fallbackVisibleFrame?.height
            ?? fallbackVisibleHeight
        let room = visibleHeight - verticalMargin
        return max(minimumHeight, min(room, visibleHeight * heightRatio))
    }

    /// 面板该有多大：内容要多少给多少，再夹进这块屏幕装得下的范围。
    ///
    /// 不写死高度。写死的值对某一台机器也许刚好，换一块屏幕不是浪费就是超出——
    /// 之前的 840 在 1152 高的屏幕上白白少用了两百多点，而在 13 寸上又偏高。
    ///
    /// 在面板打开**之前**调用；开着的时候只在换到宽度不同的页面时调用一次，并像打开时
    /// 一样挂到菜单栏按钮下重新显示（issue #105）。其余时候开着改尺寸会让 NSPopover 重新
    /// 挑选屏幕和锚点（全屏 Space、外接显示器下尤其明显），那正是固定画布要挡掉的事。
    static func contentSize(fitting contentSize: CGSize,
                            anchorVisibleFrame: NSRect?,
                            fallbackVisibleFrame: NSRect? = nil) -> CGSize {
        let ceiling = maximumHeight(anchorVisibleFrame: anchorVisibleFrame,
                                    fallbackVisibleFrame: fallbackVisibleFrame)
        let height = contentSize.height > 0
            ? min(max(contentSize.height, minimumHeight), ceiling)
            : min(provisionalSize.height, ceiling)
        let width = contentSize.width > 0
            ? max(contentSize.width, minimumWidth)
            : provisionalSize.width
        return CGSize(width: width.rounded(.up), height: height.rounded(.up))
    }
}

final class PanelLayoutContext: ObservableObject {
    @Published private(set) var contentSize: CGSize

    /// 面板当前停在哪一页（PanelView 报告，值由 App 解释）。
    ///
    /// 卡片不超过两张时首页是 322 的窄版，而设置、额度曲线要 640，数据面板、项目要 420。
    /// 画布在打开前按当前页量好；开着的时候只有「换页并且宽度变了」才需要重新摆放
    /// 弹窗（issue #105）。切页签、刷新数据宽度都不变，照旧是固定画布（issue #97）。
    private(set) var page = "cards"
    var onPageWidthChange: (() -> Void)?

    init(contentSize: CGSize = PanelPlacement.provisionalSize) {
        self.contentSize = contentSize
    }

    func pageDidChange(_ page: String, width: CGFloat) {
        guard page != self.page else { return }
        self.page = page
        guard abs(width - contentSize.width) > 0.5 else { return }
        onPageWidthChange?()
    }

    func update(fitting fittingSize: CGSize,
                anchorVisibleFrame: NSRect?,
                fallbackVisibleFrame: NSRect?) {
        let nextSize = PanelPlacement.contentSize(
            fitting: fittingSize,
            anchorVisibleFrame: anchorVisibleFrame,
            fallbackVisibleFrame: fallbackVisibleFrame
        )
        guard abs(contentSize.width - nextSize.width) > 0.5
                || abs(contentSize.height - nextSize.height) > 0.5 else { return }
        contentSize = nextSize
    }
}
