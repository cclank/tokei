import AppKit
import SwiftUI

enum MenuBarStyle: String, CaseIterable, Identifiable {
    case system
    case color
    case symbols
    case dots
    case compact
    case artistic
    case palm

    static let defaultsKey = "menuBarStyle"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .system: return "经典白"
        case .color: return "彩色"
        case .symbols: return "刻度"
        case .dots: return "圆点"
        case .compact: return "数字"
        case .artistic: return "星轨"
        case .palm: return "椰影"
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

/// 额度窗口类型，决定菜单栏上画哪个符号。
enum MenuBarQuotaWindow {
    case fiveHour
    case week
}

/// 菜单栏额度来源（与面板「显示卡片」独立；只控制状态栏显示哪些剩余额度）。
/// 每一项都是一个具体窗口，`allCases` 的顺序即状态栏的显示优先级。
enum MenuBarQuotaSource: String, CaseIterable, Identifiable {
    case claude5h
    case claudeWeek
    case claudeFable
    case codex5h
    case codexWeek
    case grok

    var id: String { rawValue }

    var label: String {
        switch self {
        case .claude5h: return "Claude 5h"
        case .claudeWeek: return "Claude 周"
        case .claudeFable: return "Claude Fable"
        case .codex5h: return "Codex 5h"
        case .codexWeek: return "Codex 周"
        case .grok: return "Grok"
        }
    }

    /// `claude5h` 与 `codexWeek` 复用已发布的 key：它们存的本来就是这两个窗口，改名会丢掉老用户的开关。
    var defaultsKey: String {
        switch self {
        case .claude5h: return "menuBarQuotaClaude"
        case .claudeWeek: return "menuBarQuotaClaudeWeek"
        case .claudeFable: return "menuBarQuotaClaudeFable"
        case .codex5h: return "menuBarQuotaCodex5h"
        case .codexWeek: return "menuBarQuotaCodex"
        case .grok: return "menuBarQuotaGrok"
        }
    }

    /// 只有历史上就默认开的两项保持默认开，其余新增窗口默认关，避免抢占状态栏。
    var defaultEnabled: Bool {
        switch self {
        case .claude5h, .codexWeek: return true
        case .claudeWeek, .claudeFable, .codex5h, .grok: return false
        }
    }

    var isEnabled: Bool {
        let ud = UserDefaults.standard
        if ud.object(forKey: defaultsKey) == nil { return defaultEnabled }
        return ud.bool(forKey: defaultsKey)
    }

    /// Grok 的窗口随数据在周/月之间变，画不出确定的符号，所以不给它符号。
    var window: MenuBarQuotaWindow? {
        switch self {
        case .claude5h, .codex5h: return .fiveHour
        case .claudeWeek, .claudeFable, .codexWeek: return .week
        case .grok: return nil
        }
    }

    /// 同家族靠符号区分窗口；Fable 与 Claude 周同为周窗口，只能靠颜色分开，沿用卡片上的橙色。
    var nsColor: NSColor {
        switch self {
        case .claude5h, .claudeWeek: return AppDelegate.claudeColor
        case .claudeFable: return .systemOrange
        case .codex5h, .codexWeek: return AppDelegate.codexColor
        case .grok: return AppDelegate.grokColor
        }
    }

    var themeColor: Color {
        switch self {
        case .claude5h, .claudeWeek: return Theme.claude
        case .claudeFable: return .orange
        case .codex5h, .codexWeek: return Theme.codex
        case .grok: return Theme.grok
        }
    }

    /// 该窗口在 usage.json 里的已用百分比与过期标记；value 为 nil 表示这个账号没有这个窗口。
    func reading(in usage: Usage) -> (value: Double?, stale: Bool?) {
        switch self {
        case .claude5h: return (usage.claude.q5, usage.claude.q5_stale)
        case .claudeWeek: return (usage.claude.q7, usage.claude.q7_stale)
        case .claudeFable: return (usage.claude.qf, usage.claude.qf_stale)
        case .codex5h: return (usage.codex.p5, usage.codex.p5_stale)
        case .codexWeek: return (usage.codex.pw, usage.codex.pw_stale)
        case .grok: return (usage.grok.pct, usage.grok.stale)
        }
    }

    /// 现在能不能真在状态栏上写出一个数字：账号有这个窗口，读数也没过期。
    /// 设置页的提示语和预览必须用同一个判断，否则会描述一个状态栏没画的组合。
    func isRenderable(in usage: Usage) -> Bool {
        let reading = reading(in: usage)
        return reading.value != nil && reading.stale != true
    }

    /// 勾选中且数据新鲜的窗口，按 `allCases` 顺序排好。模型里存的是已用百分比，这里换成剩余。
    static func metrics(in usage: Usage) -> [MenuBarMetric] {
        allCases.compactMap { source in
            guard source.isEnabled, source.isRenderable(in: usage),
                  let used = source.reading(in: usage).value else { return nil }
            let remaining = 100 - used
            return MenuBarMetric(kind: .quota(source),
                                 value: String(format: "%.0f", remaining),
                                 remaining: remaining)
        }
    }
}

enum MenuBarMetricKind: Equatable {
    case quota(MenuBarQuotaSource)
    case total

    var displayName: String {
        switch self {
        case .quota(let source): return source.label
        case .total: return "今日"
        }
    }

    var window: MenuBarQuotaWindow? {
        switch self {
        case .quota(let source): return source.window
        case .total: return nil
        }
    }

    var nsColor: NSColor {
        switch self {
        case .quota(let source): return source.nsColor
        case .total: return .secondaryLabelColor
        }
    }

    var themeColor: Color {
        switch self {
        case .quota(let source): return source.themeColor
        case .total: return Theme.tSecondary
        }
    }
}

struct MenuBarMetric {
    var kind: MenuBarMetricKind
    var value: String
    var remaining: Double? = nil
}

enum MenuBarArtwork {
    private static let signatureInk = NSColor(red: 0.15, green: 0.08, blue: 0.18, alpha: 1)
    private static let signatureRose = NSColor(red: 0.91, green: 0.29, blue: 0.43, alpha: 1)
    private static let signatureStem = NSColor(red: 0.96, green: 0.68, blue: 0.22, alpha: 1)
    private static let signatureJade = NSColor(red: 0.16, green: 0.72, blue: 0.58, alpha: 1)
    private static let signatureActive = NSColor(red: 0.98, green: 0.93, blue: 0.82, alpha: 1)
    private static let palmInk = NSColor(red: 0.03, green: 0.15, blue: 0.13, alpha: 1)
    private static let palmJade = NSColor(red: 0.39, green: 0.90, blue: 0.65, alpha: 1)
    private static let palmTeal = NSColor(red: 0.13, green: 0.72, blue: 0.59, alpha: 1)
    private static let palmGold = NSColor(red: 0.99, green: 0.72, blue: 0.27, alpha: 1)
    private static let palmCopper = NSColor(red: 0.95, green: 0.41, blue: 0.31, alpha: 1)

    static func brand(color: NSColor? = nil, active: Bool = false) -> NSImage {
        ribbonT(
            ink: color ?? .black,
            crossbarColors: [color ?? .black],
            stem: color ?? .black,
            activeColor: color ?? .black,
            active: active,
            layered: false,
            template: color == nil
        )
    }

    static func signature(active: Bool = false) -> NSImage {
        ribbonT(
            ink: signatureInk,
            crossbarColors: [signatureRose, signatureStem, signatureJade],
            stem: signatureStem,
            activeColor: signatureActive,
            active: active,
            layered: true,
            template: false
        )
    }

    private static func ribbonT(ink: NSColor, crossbarColors: [NSColor], stem: NSColor,
                                activeColor: NSColor,
                                active: Bool, layered: Bool, template: Bool) -> NSImage {
        let size: CGFloat = 18
        let image = NSImage(size: NSSize(width: size, height: size), flipped: false) { _ in
            guard let context = NSGraphicsContext.current?.cgContext else { return false }
            context.setAllowsAntialiasing(true)
            context.setShouldAntialias(true)
            context.setLineCap(.round)
            context.setLineJoin(.round)

            context.saveGState()
            context.translateBy(x: 9, y: 9)
            context.scaleBy(x: 1.18, y: 1.18)
            context.translateBy(x: -9, y: -9)

            func drawStroke(_ path: CGPath, color: NSColor) {
                if layered {
                    context.setStrokeColor(ink.cgColor)
                    context.setLineWidth(3.55)
                    context.addPath(path)
                    context.strokePath()
                }
                context.setStrokeColor(color.cgColor)
                context.setLineWidth(layered ? 2.0 : 2.2)
                context.addPath(path)
                context.strokePath()
            }

            let crossbarPath = CGMutablePath()
            crossbarPath.move(to: CGPoint(x: 3.85, y: 12.55))
            crossbarPath.addCurve(to: CGPoint(x: 14.15, y: 12.55),
                                  control1: CGPoint(x: 6.0, y: 15.15),
                                  control2: CGPoint(x: 12.0, y: 15.15))
            if layered {
                context.setStrokeColor(ink.cgColor)
                context.setLineWidth(3.55)
                context.addPath(crossbarPath)
                context.strokePath()

                context.saveGState()
                context.setLineWidth(2.0)
                context.addPath(crossbarPath)
                context.replacePathWithStrokedPath()
                context.clip()
                let gradient = CGGradient(
                    colorsSpace: CGColorSpaceCreateDeviceRGB(),
                    colors: crossbarColors.map(\.cgColor) as CFArray,
                    locations: [0, 0.5, 1]
                )
                if let gradient {
                    context.drawLinearGradient(
                        gradient,
                        start: CGPoint(x: 3.85, y: 12.55),
                        end: CGPoint(x: 14.15, y: 12.55),
                        options: []
                    )
                }
                context.restoreGState()
            } else if let crossbarColor = crossbarColors.first {
                drawStroke(crossbarPath, color: crossbarColor)
            }

            let stemPath = CGMutablePath()
            stemPath.move(to: CGPoint(x: 9.15, y: 13.65))
            stemPath.addCurve(to: CGPoint(x: 8.65, y: 5.3),
                              control1: CGPoint(x: 8.65, y: 10.8),
                              control2: CGPoint(x: 9.35, y: 7.35))
            drawStroke(stemPath, color: stem)
            context.restoreGState()

            if active {
                context.setFillColor(activeColor.cgColor)
                context.fillEllipse(in: CGRect(x: 14.0, y: 1.8, width: 2.2, height: 2.2))
            }
            return true
        }
        image.isTemplate = template
        return image
    }

    static func gauge(remaining: Double?, color: NSColor? = nil, active: Bool = false,
                      window: MenuBarQuotaWindow? = nil,
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

            if let window {
                drawWindowMark(window, in: context, center: center,
                               scale: scale, color: drawColor)
            } else if active {
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

    /// 「圆点」样式用的独立窗口符号，不带圆环。
    static func windowGlyph(_ window: MenuBarQuotaWindow, color: NSColor? = nil,
                            size: CGFloat = 9) -> NSImage {
        let drawColor = color ?? .black
        let image = NSImage(size: NSSize(width: size, height: size), flipped: false) { _ in
            guard let context = NSGraphicsContext.current?.cgContext else { return false }
            context.setAllowsAntialiasing(true)
            context.setShouldAntialias(true)
            drawWindowMark(window, in: context,
                           center: CGPoint(x: size / 2, y: size / 2),
                           scale: size / 11 * 1.7, color: drawColor)
            return true
        }
        image.isTemplate = color == nil
        return image
    }

    /// 沙漏 = 5 小时窗口，横块 = 周窗口。11pt 圆环里只有约 6.5pt 内径，细节全看不见，
    /// 所以两个符号靠「竖 vs 横」的轮廓区分，而不是靠形状本身画得像不像。
    private static func drawWindowMark(_ window: MenuBarQuotaWindow, in context: CGContext,
                                       center: CGPoint, scale: CGFloat, color: NSColor) {
        context.setFillColor(color.cgColor)
        switch window {
        case .fiveHour:
            let halfWidth = 1.15 * scale
            let halfHeight = 2.3 * scale
            let waist = 0.22 * scale
            context.beginPath()
            context.move(to: CGPoint(x: center.x - halfWidth, y: center.y + halfHeight))
            context.addLine(to: CGPoint(x: center.x + halfWidth, y: center.y + halfHeight))
            context.addLine(to: CGPoint(x: center.x + waist, y: center.y))
            context.addLine(to: CGPoint(x: center.x + halfWidth, y: center.y - halfHeight))
            context.addLine(to: CGPoint(x: center.x - halfWidth, y: center.y - halfHeight))
            context.addLine(to: CGPoint(x: center.x - waist, y: center.y))
            context.closePath()
            context.fillPath()
        case .week:
            let halfWidth = 2.2 * scale
            let halfHeight = 1.35 * scale
            context.fill(CGRect(x: center.x - halfWidth, y: center.y - halfHeight,
                                width: halfWidth * 2, height: halfHeight * 2))
        }
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

    static func palm(active: Bool = false) -> NSImage {
        let size: CGFloat = 18
        let image = NSImage(size: NSSize(width: size, height: size), flipped: false) { _ in
            guard let context = NSGraphicsContext.current?.cgContext else { return false }
            context.setAllowsAntialiasing(true)
            context.setShouldAntialias(true)
            context.setLineCap(.round)
            context.setLineJoin(.round)

            func drawLeaf(_ path: CGPath, color: NSColor) {
                context.setFillColor(color.cgColor)
                context.addPath(path)
                context.fillPath()
                context.setStrokeColor(palmInk.cgColor)
                context.setLineWidth(0.6)
                context.addPath(path)
                context.strokePath()
            }

            let trunk = CGMutablePath()
            trunk.move(to: CGPoint(x: 5.9, y: 1.65))
            trunk.addCurve(to: CGPoint(x: 8.75, y: 10.45),
                           control1: CGPoint(x: 6.45, y: 4.5),
                           control2: CGPoint(x: 7.05, y: 8.05))
            trunk.addCurve(to: CGPoint(x: 10.0, y: 10.35),
                           control1: CGPoint(x: 9.2, y: 10.65),
                           control2: CGPoint(x: 9.65, y: 10.55))
            trunk.addCurve(to: CGPoint(x: 7.75, y: 1.55),
                           control1: CGPoint(x: 9.1, y: 7.65),
                           control2: CGPoint(x: 8.45, y: 4.0))
            trunk.closeSubpath()
            context.setFillColor(palmGold.cgColor)
            context.addPath(trunk)
            context.fillPath()
            context.setStrokeColor(palmInk.cgColor)
            context.setLineWidth(0.75)
            context.addPath(trunk)
            context.strokePath()

            let trunkHighlight = CGMutablePath()
            trunkHighlight.move(to: CGPoint(x: 7.1, y: 2.35))
            trunkHighlight.addCurve(to: CGPoint(x: 8.65, y: 8.75),
                                    control1: CGPoint(x: 7.35, y: 4.45),
                                    control2: CGPoint(x: 7.8, y: 7.0))
            context.setStrokeColor(signatureActive.withAlphaComponent(0.72).cgColor)
            context.setLineWidth(0.48)
            context.addPath(trunkHighlight)
            context.strokePath()

            let left = CGMutablePath()
            left.move(to: CGPoint(x: 9.25, y: 10.65))
            left.addCurve(to: CGPoint(x: 2.05, y: 10.95),
                          control1: CGPoint(x: 7.15, y: 12.9),
                          control2: CGPoint(x: 4.15, y: 13.0))
            left.addCurve(to: CGPoint(x: 9.25, y: 10.65),
                          control1: CGPoint(x: 4.25, y: 11.05),
                          control2: CGPoint(x: 7.15, y: 10.0))
            left.closeSubpath()
            drawLeaf(left, color: palmTeal)

            let upperLeft = CGMutablePath()
            upperLeft.move(to: CGPoint(x: 9.25, y: 10.65))
            upperLeft.addCurve(to: CGPoint(x: 5.15, y: 15.75),
                               control1: CGPoint(x: 7.95, y: 13.05),
                               control2: CGPoint(x: 6.0, y: 15.1))
            upperLeft.addCurve(to: CGPoint(x: 9.25, y: 10.65),
                               control1: CGPoint(x: 6.55, y: 14.1),
                               control2: CGPoint(x: 8.35, y: 11.6))
            upperLeft.closeSubpath()
            drawLeaf(upperLeft, color: palmJade)

            let upperRight = CGMutablePath()
            upperRight.move(to: CGPoint(x: 9.3, y: 10.7))
            upperRight.addCurve(to: CGPoint(x: 12.05, y: 15.7),
                                control1: CGPoint(x: 9.85, y: 13.0),
                                control2: CGPoint(x: 11.1, y: 15.25))
            upperRight.addCurve(to: CGPoint(x: 9.3, y: 10.7),
                                control1: CGPoint(x: 11.05, y: 14.0),
                                control2: CGPoint(x: 9.65, y: 11.75))
            upperRight.closeSubpath()
            drawLeaf(upperRight, color: palmTeal)

            let right = CGMutablePath()
            right.move(to: CGPoint(x: 9.35, y: 10.7))
            right.addCurve(to: CGPoint(x: 16.05, y: 11.75),
                           control1: CGPoint(x: 11.45, y: 13.15),
                           control2: CGPoint(x: 14.35, y: 13.45))
            right.addCurve(to: CGPoint(x: 9.35, y: 10.7),
                           control1: CGPoint(x: 14.15, y: 11.65),
                           control2: CGPoint(x: 11.5, y: 10.15))
            right.closeSubpath()
            drawLeaf(right, color: palmJade)

            let lowerRight = CGMutablePath()
            lowerRight.move(to: CGPoint(x: 9.4, y: 10.6))
            lowerRight.addCurve(to: CGPoint(x: 14.65, y: 8.25),
                                control1: CGPoint(x: 11.85, y: 11.0),
                                control2: CGPoint(x: 14.15, y: 9.65))
            lowerRight.addCurve(to: CGPoint(x: 9.4, y: 10.6),
                                control1: CGPoint(x: 13.35, y: 9.0),
                                control2: CGPoint(x: 11.35, y: 9.65))
            lowerRight.closeSubpath()
            drawLeaf(lowerRight, color: palmTeal)

            let coconuts = [CGPoint(x: 8.7, y: 10.25), CGPoint(x: 10.25, y: 10.05)]
            for center in coconuts {
                context.setFillColor(palmInk.cgColor)
                context.fillEllipse(in: CGRect(x: center.x - 1.13, y: center.y - 1.13,
                                               width: 2.26, height: 2.26))
                context.setFillColor(palmCopper.cgColor)
                context.fillEllipse(in: CGRect(x: center.x - 0.69, y: center.y - 0.69,
                                               width: 1.38, height: 1.38))
            }

            if active {
                context.setFillColor(signatureActive.cgColor)
                context.fillEllipse(in: CGRect(x: 14.45, y: 2.35, width: 2.15, height: 2.15))
            }
            return true
        }
        image.isTemplate = false
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
        let visibleMetrics = metricsForDisplay(metrics, density: density)

        if density == .icon {
            leadingImage = iconOnlyImage(style: style, metric: focused, active: keepAwake)
            if style == .dots && !keepAwake {
                appendIconOnlyDot(to: title, metric: focused)
            }
            return MenuBarPresentation(image: leadingImage, title: title)
        }

        if style == .system || style == .color {
            leadingImage = style == .system
                ? MenuBarArtwork.brand(color: .white, active: keepAwake)
                : MenuBarArtwork.signature(active: keepAwake)
            for (index, metric) in visibleMetrics.enumerated() {
                if index > 0 {
                    appendSeparator(" · ", to: title,
                                    color: style == .system
                                        ? NSColor.white.withAlphaComponent(0.72)
                                        : .secondaryLabelColor)
                }
                appendValue(metric, color: style == .system ? .white : metric.kind.nsColor,
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

        if style == .palm {
            leadingImage = MenuBarArtwork.palm(active: keepAwake)
            for (index, metric) in visibleMetrics.enumerated() {
                if index > 0 {
                    appendSeparator(" · ", to: title)
                }
                appendValue(metric, color: .labelColor, to: title)
            }
            return MenuBarPresentation(image: leadingImage, title: title)
        }

        if keepAwake {
            leadingImage = MenuBarArtwork.signature(active: true)
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

    static func metricsForDisplay(
        _ metrics: [MenuBarMetric],
        density: MenuBarDensity
    ) -> [MenuBarMetric] {
        switch density {
        case .full:
            return Array(metrics.prefix(2))
        case .lowest, .icon:
            return focusedMetric(in: metrics).map { [$0] } ?? Array(metrics.prefix(1))
        }
    }

    private static func appendDecorated(_ metric: MenuBarMetric, to title: NSMutableAttributedString,
                                        style: MenuBarStyle) {
        let familyColor = metric.kind.nsColor
        switch style {
        case .symbols:
            appendArtwork(MenuBarArtwork.gauge(remaining: metric.remaining, color: familyColor,
                                               window: metric.kind.window), to: title)
            appendSpace(to: title)
            appendValue(metric, color: .labelColor, to: title)
        case .dots:
            if metric.kind.window == .fiveHour {
                appendArtwork(MenuBarArtwork.windowGlyph(.fiveHour, color: familyColor), to: title)
            } else {
                title.append(NSAttributedString(string: "●", attributes: [
                    .font: NSFont.systemFont(ofSize: 7, weight: .bold),
                    .baselineOffset: 1,
                    .foregroundColor: familyColor,
                ]))
            }
            appendSpace(to: title)
            appendValue(metric, color: .labelColor, to: title)
        case .compact:
            appendValue(metric, color: familyColor, to: title)
        case .system, .color, .artistic, .palm:
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
        let kind = metric?.kind ?? .total
        let tint = kind.nsColor
        if style == .artistic {
            return MenuBarArtwork.starTrail(active: active)
        }
        if style == .palm {
            return MenuBarArtwork.palm(active: active)
        }
        if active {
            if style == .color { return MenuBarArtwork.signature(active: true) }
            let color: NSColor? = style == .system ? .white : tint
            return MenuBarArtwork.brand(color: color, active: true)
        }
        switch style {
        case .system:
            return MenuBarArtwork.brand(color: .white)
        case .compact:
            return MenuBarArtwork.brand(color: nil)
        case .color:
            return MenuBarArtwork.signature()
        case .symbols:
            return MenuBarArtwork.gauge(remaining: metric?.remaining, window: kind.window, size: 16)
        case .dots:
            return nil
        case .artistic:
            return MenuBarArtwork.starTrail()
        case .palm:
            return MenuBarArtwork.palm()
        }
    }

    private static func appendIconOnlyDot(to title: NSMutableAttributedString,
                                          metric: MenuBarMetric?) {
        let kind = metric?.kind ?? .total
        if kind.window == .fiveHour {
            appendArtwork(MenuBarArtwork.windowGlyph(.fiveHour, color: kind.nsColor, size: 10),
                          to: title)
            return
        }
        title.append(NSAttributedString(string: "●", attributes: [
            .font: NSFont.systemFont(ofSize: 8, weight: .bold),
            .foregroundColor: kind.nsColor,
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

    private static func appendSeparator(_ value: String, to title: NSMutableAttributedString,
                                        color: NSColor = .secondaryLabelColor) {
        title.append(NSAttributedString(string: value, attributes: [
            .font: valueFont,
            .foregroundColor: color,
        ]))
    }

    private static func appendArtwork(_ image: NSImage, to title: NSMutableAttributedString) {
        let attachment = NSTextAttachment()
        attachment.image = image
        let baselineOffset = round(
            (valueFont.ascender + valueFont.descender - image.size.height) / 2
        )
        attachment.bounds = NSRect(
            x: 0, y: baselineOffset,
            width: image.size.width, height: image.size.height
        )
        title.append(NSAttributedString(attachment: attachment))
    }
}

struct MenuBarStylePreview: View {
    var style: MenuBarStyle
    var density: MenuBarDensity
    var sources: [MenuBarQuotaSource] = [.claude5h, .codexWeek]

    private struct Sample: Identifiable {
        var source: MenuBarQuotaSource
        var value: String
        var id: String { source.rawValue }
    }

    /// 样本值从高到低排，最后一项就是「单额度」会挑中的那个。
    private var samples: [Sample] {
        let values = ["98", "85"]
        return Array(sources.prefix(values.count)).enumerated().map {
            Sample(source: $1, value: values[$0])
        }
    }

    private var visibleSamples: [Sample] {
        density == .full ? samples : Array(samples.suffix(1))
    }

    var body: some View {
        HStack(spacing: style == .compact ? 5 : 6) { previewContent }
        .font(.system(size: 10, weight: .semibold, design: .monospaced))
        .frame(height: 20)
        .accessibilityLabel("\(style.label)菜单栏预览")
    }

    @ViewBuilder
    private var previewContent: some View {
        if visibleSamples.isEmpty {
            fallbackMark
        } else {
            switch style {
            case .system, .color:
                brandMark
                textSamples
            case .symbols:
                ForEach(visibleSamples) { sample in
                    gauge(sample, showValue: density != .icon)
                }
            case .dots:
                if density == .icon {
                    Circle().fill(visibleSamples[0].source.themeColor).frame(width: 6, height: 6)
                } else {
                    ForEach(visibleSamples) { dot($0) }
                }
            case .compact:
                if density == .icon {
                    templateImage(MenuBarArtwork.brand())
                } else {
                    textSamples
                }
            case .artistic:
                templateImage(MenuBarArtwork.starTrail())
                textSamples
            case .palm:
                Image(nsImage: MenuBarArtwork.palm())
                textSamples
            }
        }
    }

    @ViewBuilder
    private var fallbackMark: some View {
        switch style {
        case .system, .color:
            brandMark
        case .artistic:
            templateImage(MenuBarArtwork.starTrail())
        case .palm:
            Image(nsImage: MenuBarArtwork.palm())
        case .symbols, .dots, .compact:
            templateImage(MenuBarArtwork.brand())
        }
    }

    @ViewBuilder
    private var textSamples: some View {
        if density != .icon {
            ForEach(visibleSamples.indices, id: \.self) { index in
                if index > 0 { Text("·").foregroundStyle(Theme.tTertiary) }
                value(visibleSamples[index])
            }
        }
    }

    @ViewBuilder
    private var brandMark: some View {
        if style == .system {
            Image(nsImage: MenuBarArtwork.brand(color: .white))
        } else {
            Image(nsImage: MenuBarArtwork.signature())
        }
    }

    private func templateImage(_ image: NSImage) -> some View {
        Image(nsImage: image)
            .renderingMode(.template)
            .foregroundStyle(Theme.tSecondary)
    }

    @ViewBuilder
    private func gauge(_ sample: Sample, showValue: Bool) -> some View {
        let size: CGFloat = density == .icon ? 16 : 11
        Image(nsImage: MenuBarArtwork.gauge(remaining: Double(sample.value),
                                            color: sample.source.nsColor,
                                            window: sample.source.window,
                                            size: size))
        if showValue {
            Text(sample.value).foregroundStyle(Theme.tSecondary)
        }
    }

    private func dot(_ sample: Sample) -> some View {
        HStack(spacing: 4) {
            if sample.source.window == .fiveHour {
                Image(nsImage: MenuBarArtwork.windowGlyph(.fiveHour, color: sample.source.nsColor))
            } else {
                Circle().fill(sample.source.themeColor).frame(width: 5, height: 5)
            }
            Text(sample.value).foregroundStyle(Theme.tSecondary)
        }
    }

    @ViewBuilder
    private func value(_ sample: Sample) -> some View {
        if style == .system {
            Text(sample.value).foregroundStyle(.white)
        } else if style == .artistic || style == .palm {
            Text(sample.value).foregroundStyle(Theme.tSecondary)
        } else {
            Text(sample.value).foregroundStyle(sample.source.themeColor)
        }
    }
}
