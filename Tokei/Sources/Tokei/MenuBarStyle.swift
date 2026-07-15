import AppKit
import SwiftUI

enum MenuBarStyle: String, CaseIterable, Identifiable {
    case system
    case color
    case symbols
    case dots
    case compact
    case artistic

    static let defaultsKey = "menuBarStyle"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .system: return "单色"
        case .color: return "品牌"
        case .symbols: return "刻度"
        case .dots: return "圆点"
        case .compact: return "数字"
        case .artistic: return "星轨"
        }
    }

    static var current: MenuBarStyle {
        guard let raw = UserDefaults.standard.string(forKey: defaultsKey) else { return .system }
        return MenuBarStyle(rawValue: raw) ?? .system
    }
}

enum MenuBarDensity: String, CaseIterable, Identifiable {
    case full
    case lowest
    case icon

    static let defaultsKey = "menuBarDensity"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .full: return "双额度"
        case .lowest: return "单额度"
        case .icon: return "仅图标"
        }
    }

    static var current: MenuBarDensity {
        guard let raw = UserDefaults.standard.string(forKey: defaultsKey) else { return .full }
        return MenuBarDensity(rawValue: raw) ?? .full
    }
}

enum MenuBarMetricKind {
    case claude
    case codex
    case total
}

struct MenuBarMetric {
    var kind: MenuBarMetricKind
    var value: String
    var remaining: Double? = nil
}

enum MenuBarArtwork {
    static func brand(color: NSColor? = nil, active: Bool = false) -> NSImage {
        let size: CGFloat = 18
        let drawColor = color ?? .black
        let image = NSImage(size: NSSize(width: size, height: size), flipped: false) { _ in
            guard let context = NSGraphicsContext.current?.cgContext else { return false }
            context.setAllowsAntialiasing(true)
            context.setShouldAntialias(true)
            context.setLineCap(.round)
            context.setLineJoin(.round)
            context.setStrokeColor(drawColor.cgColor)
            context.setFillColor(drawColor.cgColor)
            context.setLineWidth(1.7)

            let center = CGPoint(x: size / 2, y: size / 2)
            let radius: CGFloat = 6.85
            context.addArc(center: center, radius: radius,
                           startAngle: 75 * .pi / 180,
                           endAngle: 395 * .pi / 180,
                           clockwise: false)
            context.strokePath()

            context.move(to: center)
            context.addLine(to: CGPoint(x: center.x, y: center.y + 4.35))
            context.move(to: center)
            context.addLine(to: CGPoint(x: center.x + 3.55, y: center.y + 2.05))
            context.strokePath()
            context.fillEllipse(in: CGRect(x: center.x - 0.75, y: center.y - 0.75,
                                           width: 1.5, height: 1.5))

            if active {
                context.fillEllipse(in: CGRect(x: 13.25, y: 13.55, width: 2.5, height: 2.5))
            }
            return true
        }
        image.isTemplate = color == nil
        return image
    }

    static func gauge(remaining: Double?, color: NSColor? = nil, active: Bool = false,
                      size: CGFloat = 11) -> NSImage {
        let drawColor = color ?? .black
        let image = NSImage(size: NSSize(width: size, height: size), flipped: false) { _ in
            guard let context = NSGraphicsContext.current?.cgContext else { return false }
            context.setAllowsAntialiasing(true)
            context.setShouldAntialias(true)
            context.setLineCap(.round)
            let scale = size / 11
            context.setLineWidth(1.45 * scale)

            let center = CGPoint(x: size / 2, y: size / 2)
            let radius: CGFloat = 4.0 * scale
            context.setStrokeColor(drawColor.withAlphaComponent(0.22).cgColor)
            context.addEllipse(in: CGRect(x: center.x - radius, y: center.y - radius,
                                          width: radius * 2, height: radius * 2))
            context.strokePath()

            let progress = min(max((remaining ?? 100) / 100, 0.04), 1)
            context.setStrokeColor(drawColor.cgColor)
            context.addArc(center: center, radius: radius,
                           startAngle: .pi / 2,
                           endAngle: .pi / 2 - CGFloat(progress) * 2 * .pi,
                           clockwise: true)
            context.strokePath()

            if active {
                context.setFillColor(drawColor.cgColor)
                context.fillEllipse(in: CGRect(x: center.x - 0.8 * scale,
                                               y: center.y - 0.8 * scale,
                                               width: 1.6 * scale, height: 1.6 * scale))
            }
            return true
        }
        image.isTemplate = color == nil
        return image
    }

    static func starTrail(active: Bool = false) -> NSImage {
        let size: CGFloat = 18
        let image = NSImage(size: NSSize(width: size, height: size), flipped: false) { _ in
            guard let context = NSGraphicsContext.current?.cgContext else { return false }
            context.setAllowsAntialiasing(true)
            context.setShouldAntialias(true)
            context.setLineCap(.round)
            context.setLineJoin(.round)
            context.setStrokeColor(NSColor.black.cgColor)
            context.setFillColor(NSColor.black.cgColor)
            context.setLineWidth(1.35)

            context.move(to: CGPoint(x: 2.55, y: 10.65))
            context.addCurve(to: CGPoint(x: 14.75, y: 5.35),
                             control1: CGPoint(x: 3.35, y: 4.15),
                             control2: CGPoint(x: 10.85, y: 1.55))
            context.strokePath()

            context.move(to: CGPoint(x: 15.55, y: 7.25))
            context.addCurve(to: CGPoint(x: 2.85, y: 11.85),
                             control1: CGPoint(x: 15.35, y: 13.35),
                             control2: CGPoint(x: 7.75, y: 16.45))
            context.strokePath()

            let star = CGMutablePath()
            star.move(to: CGPoint(x: 9, y: 4.7))
            star.addCurve(to: CGPoint(x: 13.3, y: 9),
                          control1: CGPoint(x: 9.4, y: 7.35),
                          control2: CGPoint(x: 10.65, y: 8.6))
            star.addCurve(to: CGPoint(x: 9, y: 13.3),
                          control1: CGPoint(x: 10.65, y: 9.4),
                          control2: CGPoint(x: 9.4, y: 10.65))
            star.addCurve(to: CGPoint(x: 4.7, y: 9),
                          control1: CGPoint(x: 8.6, y: 10.65),
                          control2: CGPoint(x: 7.35, y: 9.4))
            star.addCurve(to: CGPoint(x: 9, y: 4.7),
                          control1: CGPoint(x: 7.35, y: 8.6),
                          control2: CGPoint(x: 8.6, y: 7.35))
            star.closeSubpath()
            context.addPath(star)
            context.fillPath()

            let satelliteSize: CGFloat = active ? 2.9 : 2.25
            context.fillEllipse(in: CGRect(x: 15.05 - satelliteSize / 2,
                                           y: 6.25 - satelliteSize / 2,
                                           width: satelliteSize, height: satelliteSize))
            if active {
                context.fillEllipse(in: CGRect(x: 1.65, y: 10.8, width: 2.2, height: 2.2))
            }
            return true
        }
        image.isTemplate = true
        return image
    }
}

struct MenuBarPresentation {
    var image: NSImage?
    var title: NSAttributedString
}

enum MenuBarTitleRenderer {
    private static let valueFont = NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .semibold)

    static func render(style: MenuBarStyle, density: MenuBarDensity, keepAwake: Bool,
                       metrics: [MenuBarMetric], fallbackIcon: Bool = false) -> MenuBarPresentation {
        let title = NSMutableAttributedString()
        var leadingImage: NSImage?
        let focused = focusedMetric(in: metrics)
        let visibleMetrics = density == .lowest ? focused.map { [$0] } ?? Array(metrics.prefix(1)) : metrics

        if density == .icon {
            leadingImage = iconOnlyImage(style: style, metric: focused, active: keepAwake)
            if style == .dots && !keepAwake {
                appendIconOnlyDot(to: title, metric: focused)
            }
            return MenuBarPresentation(image: leadingImage, title: title)
        }

        if style == .system || style == .color {
            let markColor: NSColor? = style == .system ? nil
                : (density == .lowest ? focused.map { color(for: $0.kind) } : AppDelegate.claudeColor)
            leadingImage = MenuBarArtwork.brand(color: markColor, active: keepAwake)
            for (index, metric) in visibleMetrics.enumerated() {
                if index > 0 {
                    appendSeparator(" · ", to: title)
                }
                appendValue(metric, color: style == .system ? .labelColor : color(for: metric.kind),
                            to: title)
            }
            return MenuBarPresentation(image: leadingImage, title: title)
        }

        if style == .artistic {
            leadingImage = MenuBarArtwork.starTrail(active: keepAwake)
            for (index, metric) in visibleMetrics.enumerated() {
                if index > 0 {
                    appendSeparator(" · ", to: title)
                }
                appendValue(metric, color: .labelColor, to: title)
            }
            return MenuBarPresentation(image: leadingImage, title: title)
        }

        if keepAwake {
            leadingImage = MenuBarArtwork.brand(color: AppDelegate.claudeColor, active: true)
        }

        for (index, metric) in visibleMetrics.enumerated() {
            if title.length > 0 {
                appendSeparator(style == .compact && index > 0 ? " · " : "  ", to: title)
            }
            appendDecorated(metric, to: title, style: style)
        }

        if fallbackIcon && visibleMetrics.isEmpty {
            leadingImage = MenuBarArtwork.brand(color: nil)
        }

        return MenuBarPresentation(image: leadingImage, title: title)
    }

    private static func appendDecorated(_ metric: MenuBarMetric, to title: NSMutableAttributedString,
                                        style: MenuBarStyle) {
        let familyColor = color(for: metric.kind)
        switch style {
        case .symbols:
            appendArtwork(MenuBarArtwork.gauge(remaining: metric.remaining, color: familyColor), to: title)
            appendSpace(to: title)
            appendValue(metric, color: .labelColor, to: title)
        case .dots:
            title.append(NSAttributedString(string: "●", attributes: [
                .font: NSFont.systemFont(ofSize: 7, weight: .bold),
                .baselineOffset: 1,
                .foregroundColor: familyColor,
            ]))
            appendSpace(to: title)
            appendValue(metric, color: .labelColor, to: title)
        case .compact:
            appendValue(metric, color: familyColor, to: title)
        case .system, .color, .artistic:
            appendValue(metric, color: familyColor, to: title)
        }
    }

    private static func appendValue(_ metric: MenuBarMetric, color: NSColor,
                                    to title: NSMutableAttributedString) {
        title.append(NSAttributedString(string: metric.value, attributes: [
            .font: valueFont,
            .baselineOffset: 1,
            .foregroundColor: color,
        ]))
    }

    private static func iconOnlyImage(style: MenuBarStyle, metric: MenuBarMetric?,
                                      active: Bool) -> NSImage? {
        let tint = color(for: metric?.kind ?? .total)
        if style == .artistic {
            return MenuBarArtwork.starTrail(active: active)
        }
        if active {
            let color: NSColor? = style == .system ? nil : tint
            return MenuBarArtwork.brand(color: color, active: true)
        }
        switch style {
        case .system, .compact:
            return MenuBarArtwork.brand(color: nil)
        case .color:
            return MenuBarArtwork.brand(color: tint)
        case .symbols:
            return MenuBarArtwork.gauge(remaining: metric?.remaining, size: 16)
        case .dots:
            return nil
        case .artistic:
            return MenuBarArtwork.starTrail()
        }
    }

    private static func appendIconOnlyDot(to title: NSMutableAttributedString,
                                          metric: MenuBarMetric?) {
        title.append(NSAttributedString(string: "●", attributes: [
            .font: NSFont.systemFont(ofSize: 8, weight: .bold),
            .foregroundColor: color(for: metric?.kind ?? .total),
        ]))
    }

    private static func focusedMetric(in metrics: [MenuBarMetric]) -> MenuBarMetric? {
        let quotas = metrics.filter { $0.remaining != nil }
        if !quotas.isEmpty {
            return quotas.min { ($0.remaining ?? 0) < ($1.remaining ?? 0) }
        }
        return metrics.first
    }

    private static func appendSpace(to title: NSMutableAttributedString) {
        title.append(NSAttributedString(string: " ", attributes: [.font: valueFont]))
    }

    private static func appendSeparator(_ value: String, to title: NSMutableAttributedString) {
        title.append(NSAttributedString(string: value, attributes: [
            .font: valueFont,
            .foregroundColor: NSColor.secondaryLabelColor,
        ]))
    }

    private static func appendArtwork(_ image: NSImage, to title: NSMutableAttributedString) {
        let attachment = NSTextAttachment()
        attachment.image = image
        // NSTextAttachment 默认贴着文本基线，图标会比数字视觉中心偏高；按字体中心下移对齐。
        let y = round((valueFont.ascender + valueFont.descender - image.size.height) / 2)
        attachment.bounds = NSRect(x: 0, y: y, width: image.size.width, height: image.size.height)
        title.append(NSAttributedString(attachment: attachment))
    }

    private static func color(for kind: MenuBarMetricKind) -> NSColor {
        switch kind {
        case .claude: return AppDelegate.claudeColor
        case .codex: return AppDelegate.codexColor
        case .total: return .secondaryLabelColor
        }
    }

}

struct MenuBarStylePreview: View {
    var style: MenuBarStyle
    var density: MenuBarDensity

    var body: some View {
        HStack(spacing: style == .compact ? 5 : 6) { previewContent }
        .font(.system(size: 10, weight: .semibold, design: .monospaced))
        .frame(height: 20)
        .accessibilityLabel("\(style.label)菜单栏预览")
    }

    @ViewBuilder
    private var previewContent: some View {
        switch style {
        case .system, .color:
            brandMark
            if density == .lowest {
                value(.codex, "85")
            } else if density == .full {
                value(.claude, "98")
                Text("·").foregroundStyle(Theme.tTertiary)
                value(.codex, "85")
            }
        case .symbols:
            if density == .icon || density == .lowest {
                gauge(.codex, "85", showValue: density != .icon)
            } else {
                gauge(.claude, "98", showValue: true)
                gauge(.codex, "85", showValue: true)
            }
        case .dots:
            if density == .icon {
                Circle().fill(Theme.codex).frame(width: 6, height: 6)
            } else if density == .lowest {
                dot(.codex, "85")
            } else {
                dot(.claude, "98")
                dot(.codex, "85")
            }
        case .compact:
            if density == .icon {
                templateImage(MenuBarArtwork.brand())
            } else if density == .lowest {
                value(.codex, "85")
            } else {
                value(.claude, "98")
                Text("·").foregroundStyle(Theme.tTertiary)
                value(.codex, "85")
            }
        case .artistic:
            templateImage(MenuBarArtwork.starTrail())
            if density == .lowest {
                value(.codex, "85")
            } else if density == .full {
                value(.claude, "98")
                Text("·").foregroundStyle(Theme.tTertiary)
                value(.codex, "85")
            }
        }
    }

    @ViewBuilder
    private var brandMark: some View {
        let color = density == .full ? AppDelegate.claudeColor : AppDelegate.codexColor
        if style == .system {
            templateImage(MenuBarArtwork.brand())
        } else {
            Image(nsImage: MenuBarArtwork.brand(color: color))
        }
    }

    private func templateImage(_ image: NSImage) -> some View {
        Image(nsImage: image)
            .renderingMode(.template)
            .foregroundStyle(Theme.tSecondary)
    }

    @ViewBuilder
    private func gauge(_ kind: MenuBarMetricKind, _ value: String, showValue: Bool) -> some View {
        let tint = nsColor(kind)
        let size: CGFloat = density == .icon ? 16 : 11
        Image(nsImage: MenuBarArtwork.gauge(remaining: Double(value), color: tint, size: size))
        if showValue {
            Text(value).foregroundStyle(Theme.tSecondary)
        }
    }

    private func dot(_ kind: MenuBarMetricKind, _ value: String) -> some View {
        HStack(spacing: 4) {
            Circle().fill(swiftColor(kind)).frame(width: 5, height: 5)
            Text(value).foregroundStyle(Theme.tSecondary)
        }
    }

    @ViewBuilder
    private func value(_ kind: MenuBarMetricKind, _ value: String) -> some View {
        if style == .system || style == .artistic {
            Text(value).foregroundStyle(Theme.tSecondary)
        } else {
            Text(value).foregroundStyle(swiftColor(kind))
        }
    }

    private func nsColor(_ kind: MenuBarMetricKind) -> NSColor {
        switch kind {
        case .claude: return AppDelegate.claudeColor
        case .codex: return AppDelegate.codexColor
        case .total: return .secondaryLabelColor
        }
    }

    private func swiftColor(_ kind: MenuBarMetricKind) -> Color {
        switch kind {
        case .claude: return Theme.claude
        case .codex: return Theme.codex
        case .total: return Theme.tSecondary
        }
    }
}
