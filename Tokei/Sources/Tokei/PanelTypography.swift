import Foundation
import CoreGraphics

enum PanelFontSize: String, CaseIterable, Identifiable {
    case small
    case large

    static let defaultsKey = "panelFontSize"

    var id: String { rawValue }
    var label: String { self == .small ? L10n.sizeSmall : L10n.sizeLarge }
    var scale: CGFloat { self == .small ? 1 : 1.12 }

    static var current: PanelFontSize {
        let raw = UserDefaults.standard.string(forKey: defaultsKey) ?? small.rawValue
        return PanelFontSize(rawValue: raw) ?? .small
    }

    static func scaled(_ points: CGFloat) -> CGFloat {
        points * current.scale
    }
}
