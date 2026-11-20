import AppKit
import SwiftUI

enum MenuBarContent: String, CaseIterable, Identifiable {
    case quota, tokens
    static let defaultsKey = "menuBarContent"
    var id: String { rawValue }
    var label: String { self == .quota ? L("额度百分比") : L("Token 用量") }
    static var current: Self {
        Self(rawValue: UserDefaults.standard.string(forKey: defaultsKey) ?? "") ?? .quota
    }
}

enum MenuBarTokenPeriod: String, CaseIterable, Identifiable {
    case today, cycle
    static let defaultsKey = "menuBarTokenPeriod"
    var id: String { rawValue }
    var label: String { self == .today ? L("今日") : L("本周期") }
    static var current: Self {
        Self(rawValue: UserDefaults.standard.string(forKey: defaultsKey) ?? "") ?? .today
    }
}

/// Token 来源独立于额度窗口，选两个 Claude 窗口也不会重复显示同一份今日用量。
enum MenuBarTokenSource: String, CaseIterable, Identifiable {
    case claude, codex, antigravity, grok
    var id: String { rawValue }
    var defaultsKey: String { "menuBarToken" + rawValue.prefix(1).uppercased() + String(rawValue.dropFirst()) }
    var defaultEnabled: Bool { self == .claude || self == .codex }
    var isEnabled: Bool {
        UserDefaults.standard.object(forKey: defaultsKey) as? Bool ?? defaultEnabled
    }
    var label: String {
        switch self {
        case .claude: return "Claude Code"
        case .codex: return "Codex"
        case .antigravity: return "Gemini / Antigravity"
        case .grok: return "Grok"
        }
    }
    var nsColor: NSColor {
        switch self {
        case .claude: return AppDelegate.claudeColor
        case .codex: return AppDelegate.codexColor
        case .antigravity: return .systemPurple
        case .grok: return AppDelegate.grokColor
        }
    }
    var themeColor: Color {
        switch self {
        case .claude: return Theme.claude
        case .codex: return Theme.codex
        case .antigravity: return Theme.gemini
        case .grok: return Theme.grok
        }
    }

    private func todayTokens(in usage: Usage) -> Int? {
        switch self {
        case .claude:
            let r = usage.claude.ranges.get(.today)
            return Self.sum([r.in, r.out, r.cr, r.cw])
        case .codex:
            let r = usage.codex.ranges.get(.today)
            let reserve = usage.codex.reserveRanges?.get(.today) ?? CodexRange()
            // reasoning 已含在 out；ranges.in 不含缓存，缓存只加一次。
            return Self.sum([r.in, r.cached, r.out, reserve.in, reserve.cached, reserve.out])
        case .antigravity:
            let r = usage.gemini.ranges.get(.today)
            return Self.sum([r.in, r.out, r.cached, r.thoughts])
        case .grok:
            return Self.sum([usage.grok.ranges.get(.today).tokens])
        }
    }

    private static func sum(_ values: [Int]) -> Int? {
        var total = 0
        for value in values {
            guard value >= 0 else { return nil }
            let next = total.addingReportingOverflow(value)
            guard !next.overflow else { return nil }
            total = next.partialValue
        }
        return total
    }

    private func cycles(in usage: Usage, detail: QuotaDetailPayload?, at now: Int) -> [QuotaCycle]? {
        guard let detail else { return nil }
        let tool: String
        let reset: Int?
        switch self {
        case .claude: tool = "claude"; reset = usage.claude.q7_reset
        case .codex: tool = "codex"; reset = usage.codex.rw
        case .grok: tool = "grok"; reset = usage.grok.reset
        case .antigravity:
            let windows = usage.antigravity.windows.filter {
                $0.id.hasPrefix("antigravity-") && $0.id.hasSuffix("-weekly")
            }
            guard !windows.isEmpty else { return nil }
            var result: [QuotaCycle] = []
            var seen = Set<String>()
            for window in windows where seen.insert(window.id).inserted {
                guard let reset = window.reset, reset > now,
                      let cycle = detail.cycles.first(where: {
                          $0.tool == "antigravity" && $0.window_id == window.id && $0.current &&
                          $0.start <= now && $0.end > now && abs(Double($0.end) - Double(reset)) <= 120
                      }) else { return nil }
                result.append(cycle)
            }
            return result
        }
        return detail.currentCycle(for: tool, endingAt: reset, at: now).map { [$0] }
    }

    func metric(in usage: Usage, period: MenuBarTokenPeriod, detail: QuotaDetailPayload?,
                allDevices: Bool, at now: Int = Int(Date().timeIntervalSince1970)) -> MenuBarMetric {
        let count: Int?
        var approximate = false
        if period == .today {
            count = todayTokens(in: usage)
        } else if let cycles = cycles(in: usage, detail: detail, at: now) {
            // 周期缓存合并所有设备；本机模式只取本机那份，不能把合计冒充本机。
            let selfDevice = "本机" // l10n-ignore: collector's stable device identifier
            let counts: [Int?] = cycles.map { cycle in
                if allDevices || cycle.usage_scope == "local" { return cycle.tokens }
                if let local = cycle.devices[selfDevice] { return local }
                if detail?.devices.contains(selfDevice) == true,
                   Self.sum(Array(cycle.devices.values)) == cycle.tokens { return 0 }
                return nil
            }
            count = counts.allSatisfy { $0 != nil } ? Self.sum(counts.compactMap { $0 }) : nil
            approximate = cycles.contains { $0.approx }
        } else {
            count = nil
        }
        return MenuBarMetric(kind: .tokens(self, period),
                             value: count.map { (approximate ? "≈" : "") + Fmt.human($0) } ?? "—",
                             tokens: count, approximate: approximate)
    }

    static func metrics(in usage: Usage, period: MenuBarTokenPeriod, detail: QuotaDetailPayload?,
                        allDevices: Bool) -> [MenuBarMetric] {
        allCases.filter(\.isEnabled).map {
            $0.metric(in: usage, period: period, detail: detail, allDevices: allDevices)
        }
    }
}
