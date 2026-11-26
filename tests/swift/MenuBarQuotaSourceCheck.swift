import AppKit
import Foundation

private enum TestFailure: Error {
    case assertion(String)
}

private func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() { throw TestFailure.assertion(message) }
}

/// main.swift 有顶层语句，无法 -parse-as-library 编入；这里只补 MenuBarStyle 用到的颜色常量。
final class AppDelegate {
    static let claudeColor = NSColor(red: 0.92, green: 0.52, blue: 0.40, alpha: 1)
    static let codexColor  = NSColor(red: 0.42, green: 0.68, blue: 0.98, alpha: 1)
    static let grokColor   = NSColor(red: 0.65, green: 0.68, blue: 0.75, alpha: 1)
    static let kimicodeColor = NSColor(red: 0.20, green: 0.78, blue: 0.66, alpha: 1)
}

enum DataLoader {
    static func runScriptRaw(args: [String], timeout: Double) -> (stdout: String, exitCode: Int32, timedOut: Bool) {
        fatalError("Menu bar model checks must never invoke the collector")
    }
}

@main
struct MenuBarQuotaSourceCheck {
    static func main() throws {
        // 断言的是中文输出，不能随跑测试那台机器的系统语言变化。
        L10n.forcedLanguage = .zh
        _ = NSApplication.shared

        try checkSourceIdentity()
        try checkDefaults()
        try checkDefaultMetricsUnchanged()
        try checkReading()
        try checkAntigravity()
        try checkRenderable()
        try checkDensity()
        try checkWindowGlyphsAreDistinct()
        try checkRenderedColor()
        try checkMenuBarAppearanceChanges()
        try checkTokenUsage()

        print("menu bar quota source checks passed")
    }

    private static func checkTokenUsage() throws {
        let ud = UserDefaults.standard
        let keys = [MenuBarContent.defaultsKey, MenuBarTokenPeriod.defaultsKey] + MenuBarTokenSource.allCases.map(\.defaultsKey)
        defer { keys.forEach { ud.removeObject(forKey: $0) } }
        keys.forEach { ud.removeObject(forKey: $0) }
        try expect(MenuBarContent.current == .quota, "existing users retain quota mode")
        try expect(MenuBarTokenPeriod.current == .today, "token mode starts with today")
        try expect(MenuBarTokenSource.allCases.filter(\.isEnabled) == [.claude, .codex], "default token sources")
        ud.set("invalid", forKey: MenuBarContent.defaultsKey)
        try expect(MenuBarContent.current == .quota, "unknown content preference falls back safely")
        ud.set("tokens", forKey: MenuBarContent.defaultsKey)
        ud.set("cycle", forKey: MenuBarTokenPeriod.defaultsKey)
        try expect(MenuBarContent.current == .tokens && MenuBarTokenPeriod.current == .cycle, "preferences persist independently")

        var usage = try decodeFixture(fixtureJSON)
        usage.claude.ranges.today.in = 100
        usage.claude.ranges.today.out = 20
        usage.claude.ranges.today.cr = 30
        usage.claude.ranges.today.cw = 40
        usage.codex.ranges.today = CodexRange(in: 100, cached: 200, out: 50, reason: 40)
        usage.codex.reserveRanges = usage.codex.ranges
        usage.codex.reserveRanges?.today = CodexRange(in: 10, cached: 20, out: 30, reason: 25)
        let claude = MenuBarTokenSource.claude.metric(in: usage, period: .today, detail: nil, allDevices: false)
        let codex = MenuBarTokenSource.codex.metric(in: usage, period: .today, detail: nil, allDevices: false)
        try expect(claude.tokens == 190, "Claude input, output, cache read and write counted once")
        try expect(codex.tokens == 410, "Codex reserve included, reasoning never counted twice")
        try expect(codex.accessibilitySummary.contains("Codex 今日 410 Token"), "tooltip identifies tool, period and exact count")
        let single = MenuBarTitleRenderer.metricsForDisplay([claude, codex], density: .lowest)
        try expect(single.first?.tokens == 410, "single token view picks the largest usage")
        for style in MenuBarStyle.allCases {
            let title = MenuBarTitleRenderer.render(style: style, density: .full, keepAwake: false, metrics: [claude, codex]).title.string
            try expect(title.contains("190") && title.contains("410") && !title.contains("%"), "token rendering for \(style)")
        }

        usage.claude.q7_reset = 2000
        let json = #"{"daily":[],"cycles":[{"tool":"claude","start":500,"end":2000,"tokens":1000,"devices":{"本机":300,"peer":700},"approx":false,"current":true}],"devices":["本机","peer"],"missing":[],"now":1000}"#
        var detail = try JSONDecoder().decode(QuotaDetailPayload.self, from: Data(json.utf8))
        func current(_ value: QuotaDetailPayload?, all: Bool = false, at: Int = 1000) -> MenuBarMetric {
            MenuBarTokenSource.claude.metric(in: usage, period: .cycle, detail: value, allDevices: all, at: at)
        }
        try expect(current(detail).tokens == 300 && current(detail, all: true).tokens == 1000, "cycle respects local/all-device scope")
        try expect(current(nil).value == "—" && !current(nil).accessibilitySummary.contains("已重置"), "missing cycles never masquerade as zero or quota reset")
        try expect(current(detail, at: 2000).tokens == nil, "expired cycle cannot leak into a new period")
        detail.cycles[0].end = 2120
        try expect(current(detail).tokens == 300, "120-second reset jitter accepted")
        detail.cycles[0].end = 2121
        try expect(current(detail).tokens == nil, "different reset rejected")
        detail.cycles[0].end = 2000
        detail.cycles[0].approx = true
        try expect(current(detail).value == "≈300", "approximate period counts are labeled")
        detail.cycles[0].devices = ["peer": 1000]
        try expect(current(detail).tokens == 0, "zero local usage remains zero")
        detail.cycles[0].devices = [:]
        try expect(current(detail).tokens == nil, "legacy unknown scope cannot use all-device count")

        usage.antigravity = try JSONDecoder().decode(ProviderQuotaStat.self, from: Data(#"{"windows":[{"id":"antigravity-gemini-weekly","reset":2000},{"id":"antigravity-3p-weekly","reset":2500},{"id":"antigravity-gemini-5h","reset":1100}]}"#.utf8))
        let ag = #"{"daily":[],"cycles":[{"tool":"antigravity","window_id":"antigravity-gemini-weekly","start":500,"end":2000,"tokens":100,"devices":{"本机":100},"usage_scope":"local","approx":false,"current":true},{"tool":"antigravity","window_id":"antigravity-3p-weekly","start":500,"end":2500,"tokens":200,"devices":{"本机":200},"usage_scope":"local","approx":true,"current":true},{"tool":"antigravity","window_id":"antigravity-gemini-5h","start":500,"end":1100,"tokens":9999,"devices":{"本机":9999},"approx":false,"current":true}],"devices":["本机"],"missing":[],"now":1000}"#
        var agDetail = try JSONDecoder().decode(QuotaDetailPayload.self, from: Data(ag.utf8))
        let agMetric = MenuBarTokenSource.antigravity.metric(in: usage, period: .cycle, detail: agDetail, allDevices: true, at: 1000)
        try expect(agMetric.tokens == 300 && agMetric.approximate, "Antigravity sums weekly pools once, never the 5h window")
        agDetail.cycles.remove(at: 1)
        try expect(MenuBarTokenSource.antigravity.metric(in: usage, period: .cycle, detail: agDetail, allDevices: false, at: 1000).tokens == nil,
                   "missing Antigravity pool cannot silently undercount the tool")
    }

    private static func checkSourceIdentity() throws {
        let order = MenuBarQuotaSource.allCases.map(\.rawValue)
        try expect(order == ["claude5h", "claudeWeek", "claudeFable",
                             "codex5h", "codexWeek", "kimi5h", "kimiSubscription", "grok",
                             "antigravityGeminiWeek", "antigravityGemini5h", "antigravityClaudeGPTWeek",
                             "antigravityClaudeGPT5h", "antigravityArgonWeek"],
                   "quota source order changed: \(order)")

        // 这两个 key 已经发布过，存的本来就是这两个窗口的开关。
        // 改名等于把老用户的选择抹掉，所以在这里钉死。
        try expect(MenuBarQuotaSource.claude5h.defaultsKey == "menuBarQuotaClaude",
                   "claude5h must keep the published key: \(MenuBarQuotaSource.claude5h.defaultsKey)")
        try expect(MenuBarQuotaSource.codexWeek.defaultsKey == "menuBarQuotaCodex",
                   "codexWeek must keep the published key: \(MenuBarQuotaSource.codexWeek.defaultsKey)")
        try expect(MenuBarQuotaSource.codex5h.defaultsKey == "menuBarQuotaCodex5h",
                   "codex5h key wrong: \(MenuBarQuotaSource.codex5h.defaultsKey)")

        let keys = Set(MenuBarQuotaSource.allCases.map(\.defaultsKey))
        try expect(keys.count == MenuBarQuotaSource.allCases.count, "duplicate defaults key")

        // 标签必须写清是哪个窗口，这是用户能分辨谁是谁的前提。
        let labels = MenuBarQuotaSource.allCases.map(\.label)
        try expect(labels == ["Claude 5h", "Claude 周", "Claude Fable",
                              "Codex 5h", "Codex 周", "Kimi 5h", "Kimi 订阅", "Grok",
                              "Antigravity Gemini 周", "Antigravity Gemini 5h", "Antigravity Claude/GPT 周",
                              "Antigravity Claude/GPT 5h", "Antigravity Gemini 4 Argon 周"],
                   "window labels changed: \(labels)")

        let defaultOn = MenuBarQuotaSource.allCases.filter(\.defaultEnabled).map(\.rawValue)
        try expect(defaultOn == ["claude5h", "codexWeek"],
                   "only the two historically-on windows may default on: \(defaultOn)")

        let windows = MenuBarQuotaSource.allCases.map(\.window)
        try expect(windows == [.fiveHour, .week, .week, .fiveHour, .week, .fiveHour, nil, nil,
                               .week, .fiveHour, .week, .fiveHour, .week],
                   "window kinds changed")
    }

    private static func checkDefaults() throws {
        let ud = UserDefaults.standard
        let keys = MenuBarQuotaSource.allCases.map(\.defaultsKey)
        defer { keys.forEach { ud.removeObject(forKey: $0) } }

        keys.forEach { ud.removeObject(forKey: $0) }
        for source in MenuBarQuotaSource.allCases {
            try expect(source.isEnabled == source.defaultEnabled,
                       "unset key must fall back to default: \(source.rawValue)")
        }

        ud.set(true, forKey: MenuBarQuotaSource.claudeWeek.defaultsKey)
        try expect(MenuBarQuotaSource.claudeWeek.isEnabled, "claudeWeek opt-in ignored")
        try expect(MenuBarQuotaSource.claude5h.isEnabled,
                   "opting into the weekly window must not affect Claude 5h")

        ud.set(false, forKey: MenuBarQuotaSource.codexWeek.defaultsKey)
        try expect(!MenuBarQuotaSource.codexWeek.isEnabled, "codexWeek opt-out ignored")
        try expect(!MenuBarQuotaSource.codex5h.isEnabled,
                   "codex5h must stay off on its own key")
    }

    /// 没碰过设置的用户，状态栏必须和改动前一模一样。
    private static func checkDefaultMetricsUnchanged() throws {
        let ud = UserDefaults.standard
        let keys = MenuBarQuotaSource.allCases.map(\.defaultsKey)
        defer { keys.forEach { ud.removeObject(forKey: $0) } }
        keys.forEach { ud.removeObject(forKey: $0) }

        let usage = try decodeFixture(fixtureJSON)
        let metrics = MenuBarQuotaSource.metrics(in: usage)
        try expect(metrics.map(\.kind.displayName) == ["Claude 5h", "Codex 周"],
                   "default pair changed: \(metrics.map(\.kind.displayName))")
        try expect(metrics.map(\.value) == ["80", "65"],
                   "default values changed: \(metrics.map(\.value))")

        let full = MenuBarTitleRenderer.metricsForDisplay(metrics, density: .full)
        try expect(full.map(\.value) == ["80", "65"], "default full layout changed")
        try expect(full.map(\.kind.nsColor) == [AppDelegate.claudeColor, AppDelegate.codexColor],
                   "default colors changed")
    }

    private static func checkReading() throws {
        let ud = UserDefaults.standard
        let keys = MenuBarQuotaSource.allCases.map(\.defaultsKey)
        defer { keys.forEach { ud.removeObject(forKey: $0) } }
        keys.forEach { ud.set(true, forKey: $0) }

        let usage = try decodeFixture(fixtureJSON)
        let used = MenuBarQuotaSource.allCases.map { $0.reading(in: usage).value }
        try expect(used == [20, 40, 10, 88, 35, 15, 55, 25, 17, 19, 23, 29, 31], "reading mapped to the wrong field: \(used)")

        // 模型里存已用百分比，状态栏显示剩余，别把 100-x 丢了。
        let metrics = MenuBarQuotaSource.metrics(in: usage)
        try expect(metrics.map(\.value) == ["80", "60", "90", "12", "65", "85", "45", "75", "83", "81", "77", "71", "69"],
                   "remaining conversion or order wrong: \(metrics.map(\.value))")

        // 账号没有这个窗口 → 整项不出现。
        var missingFable = usage
        missingFable.claude.qf = nil
        try expect(MenuBarQuotaSource.metrics(in: missingFable).map(\.kind.displayName)
                    == ["Claude 5h", "Claude 周", "Codex 5h", "Codex 周",
                        "Kimi 5h", "Kimi 订阅", "Grok", "Antigravity Gemini 周",
                        "Antigravity Gemini 5h", "Antigravity Claude/GPT 周",
                        "Antigravity Claude/GPT 5h", "Antigravity Gemini 4 Argon 周"],
                   "a nil window must drop out entirely")

        // 数据过期 → 照常显示上次读到的数（标记 stale，状态栏变淡），不再整项消失。
        var staleCodex5h = usage
        staleCodex5h.codex.p5_stale = true
        let stale = MenuBarQuotaSource.metrics(in: staleCodex5h)
            .first { $0.kind.displayName == "Codex 5h" }
        try expect(stale?.value == "12" && stale?.stale == true && stale?.remaining == 12,
                   "a stale window keeps its last reading, marked stale")

        // 窗口已经重置：上一个窗口的数不能冒充，写「—」
        staleCodex5h.codex.r5 = Int(Date().timeIntervalSince1970) - 60
        let reset = MenuBarQuotaSource.metrics(in: staleCodex5h)
            .first { $0.kind.displayName == "Codex 5h" }
        try expect(reset?.value == "—" && reset?.remaining == nil && reset?.stale == true,
                   "a window that reset since the reading shows a dash")
    }

    private static func checkAntigravity() throws {
        let ud = UserDefaults.standard
        let keys = MenuBarQuotaSource.allCases.map(\.defaultsKey)
        defer { keys.forEach { ud.removeObject(forKey: $0) } }
        keys.forEach { ud.set(false, forKey: $0) }
        ud.set(true, forKey: MenuBarQuotaSource.codexWeek.defaultsKey)
        let gemini = MenuBarQuotaSource.antigravityGeminiWeek
        ud.set(true, forKey: gemini.defaultsKey)

        var usage = try decodeFixture(fixtureJSON)
        let metrics = MenuBarQuotaSource.metrics(in: usage)
        let displayed = MenuBarTitleRenderer.metricsForDisplay(metrics, density: .full)
        try expect(displayed.map(\.kind.displayName) == ["Codex 周", "Antigravity Gemini 周"]
            && displayed.map(\.value) == ["65", "83"], "Antigravity should fill the second slot next to Codex")
        try expect(displayed[1].accessibilitySummary.contains("Antigravity Gemini 周")
            && displayed[1].accessibilitySummary.contains("83%"), "status item exposes the provider and real quota")
        for style in MenuBarStyle.allCases {
            let title = MenuBarTitleRenderer.render(style: style, density: .full, keepAwake: false, metrics: metrics).title.string
            try expect(title.contains("65") && title.contains("83"), "both values rendered for \(style)")
        }

        usage.antigravity.windows[0].used_pct = 100
        try expect(MenuBarQuotaSource.metrics(in: usage).last?.remaining == 0,
                   "exhausted Antigravity still renders as 0% remaining")
        usage.antigravity.windows[0].usage_known = false
        try expect(!gemini.isRenderable(in: usage) && MenuBarQuotaSource.metrics(in: usage).count == 1,
                   "unknown Antigravity value cannot be displayed even if used_pct exists")
        usage.antigravity.windows[0].usage_known = true
        usage.antigravity.windows[0].used_pct = 17
        usage.antigravity.stale = true
        let old = MenuBarQuotaSource.metrics(in: usage).last
        try expect(old?.value == "83" && old?.stale == true,
                   "stale Antigravity quota keeps its last known reading")
        usage.antigravity.stale = false
        usage.antigravity.windows[0].reset = Int(Date().timeIntervalSince1970) - 60
        let reset = MenuBarQuotaSource.metrics(in: usage).last
        try expect(reset?.value == "—" && reset?.stale == true,
                   "expired reset cannot show an old reading during the cache TTL")
        usage.antigravity.available = false
        try expect(!gemini.isRenderable(in: usage), "unavailable Antigravity must stay hidden")
    }

    private static func checkRenderable() throws {
        let ud = UserDefaults.standard
        let keys = MenuBarQuotaSource.allCases.map(\.defaultsKey)
        defer { keys.forEach { ud.removeObject(forKey: $0) } }
        keys.forEach { ud.set(true, forKey: $0) }

        let usage = try decodeFixture(fixtureJSON)

        // 过期的窗口照常占位。设置页的提示语和预览走这个谓词，
        // 必须和 metrics(in:) 完全一致，否则又会宣布状态栏没画的组合。
        var staleFable = usage
        staleFable.claude.qf_stale = true
        try expect(MenuBarQuotaSource.claudeFable.isRenderable(in: staleFable),
                   "a stale window keeps its place in the menu bar")
        for source in MenuBarQuotaSource.allCases {
            let rendered = MenuBarQuotaSource.metrics(in: staleFable)
                .contains { $0.kind == .quota(source) }
            try expect(rendered == source.isRenderable(in: staleFable),
                       "isRenderable disagrees with metrics for \(source.rawValue)")
        }

        // 用户的真实 Pro 账号：服务端只下发 7 天窗口，5h 那项压根不存在，
        // 但设置页照样列出开关，只是状态栏跳过它。
        var weeklyOnlyCodex = usage
        weeklyOnlyCodex.codex.p5 = nil
        try expect(!MenuBarQuotaSource.codex5h.isRenderable(in: weeklyOnlyCodex),
                   "codex5h cannot render when the server sends no 5h window")
        try expect(MenuBarQuotaSource.codexWeek.isRenderable(in: weeklyOnlyCodex),
                   "the weekly window must survive a missing 5h window")
    }

    private static func checkDensity() throws {
        let metrics = [
            MenuBarMetric(kind: .quota(.claude5h), value: "80", remaining: 80),
            MenuBarMetric(kind: .quota(.claudeWeek), value: "60", remaining: 60),
            MenuBarMetric(kind: .quota(.codex5h), value: "12", remaining: 12),
            MenuBarMetric(kind: .quota(.grok), value: "90", remaining: 90),
        ]

        let full = MenuBarTitleRenderer.metricsForDisplay(metrics, density: .full)
        try expect(full.map(\.value) == ["80", "60"],
                   "full density must stay capped at the first two: \(full.map(\.value))")

        let lowest = MenuBarTitleRenderer.metricsForDisplay(metrics, density: .lowest)
        try expect(lowest.map(\.value) == ["12"], "lowest must pick the smallest remaining")

        let icon = MenuBarTitleRenderer.metricsForDisplay(metrics, density: .icon)
        try expect(icon.map(\.value) == ["12"], "icon density must track the lowest metric")

        // 单额度先在新鲜读数里挑：过期的旧数字再低也不抢位置
        var withStale = metrics
        withStale[2].stale = true
        let freshFirst = MenuBarTitleRenderer.metricsForDisplay(withStale, density: .lowest)
        try expect(freshFirst.map(\.value) == ["60"],
                   "lowest prefers fresh readings over a stale one: \(freshFirst.map(\.value))")
    }

    /// 同家族的两个窗口同色，只能靠符号区分——这里就是在守那个符号。
    private static func checkWindowGlyphsAreDistinct() throws {
        try expect(MenuBarQuotaSource.claude5h.nsColor == MenuBarQuotaSource.claudeWeek.nsColor,
                   "claude windows are expected to share one family color")

        let fiveHour = try symbolsGlyph(.claude5h)
        let week = try symbolsGlyph(.claudeWeek)
        try expect(fiveHour != week,
                   "5h and weekly must not render the same gauge, otherwise they are unreadable")

        // 「圆点」样式：只有 5h 换成手绘沙漏，周窗口保留原来的文字圆点。
        try expect(dotsTitle(.claude5h).contains("\u{FFFC}"),
                   "dots style must draw a glyph attachment for the 5h window")
        try expect(dotsTitle(.claudeWeek).contains("●"),
                   "dots style must keep the plain bullet for weekly windows")
    }

    private static func checkRenderedColor() throws {
        let rendered = MenuBarTitleRenderer.render(
            style: .compact, density: .full, keepAwake: false,
            metrics: [MenuBarMetric(kind: .quota(.codex5h), value: "37", remaining: 37)]
        )
        try expect(rendered.title.string == "37", "unexpected title: \(rendered.title.string)")
        let color = rendered.title.attribute(.foregroundColor, at: 0, effectiveRange: nil) as? NSColor
        try expect(color == AppDelegate.codexColor,
                   "codex5h must render in the Codex color, got \(String(describing: color))")

        // Fable 和 Claude 周同为周窗口、符号一样，只能靠颜色分开。
        try expect(MenuBarQuotaSource.claudeFable.nsColor != MenuBarQuotaSource.claudeWeek.nsColor,
                   "Fable needs its own color, the weekly glyph alone cannot separate them")
    }

    private static func checkMenuBarAppearanceChanges() throws {
        let light = NSAppearance(named: .vibrantLight)!
        let dark = NSAppearance(named: .vibrantDark)!
        let fresh = MenuBarMetric(kind: .quota(.claude5h), value: "80", remaining: 80)
        let stale = MenuBarMetric(kind: .quota(.codexWeek), value: "65", remaining: 65, stale: true)
        let color = MenuBarTitleRenderer.render(
            style: .color, density: .full, keepAwake: false, metrics: [fresh, stale]
        ).title
        let palm = MenuBarTitleRenderer.render(
            style: .palm, density: .full, keepAwake: false, metrics: [stale]
        ).title

        func resolve(_ title: NSAttributedString, at index: Int, in appearance: NSAppearance) -> NSColor? {
            var resolved: NSColor?
            appearance.performAsCurrentDrawingAppearance {
                resolved = (title.attribute(.foregroundColor, at: index, effectiveRange: nil) as? NSColor)?
                    .usingColorSpace(.sRGB)
            }
            return resolved
        }

        // Keep the exact attributed title across the appearance change, as the
        // system does when the same status item moves onto a lighter material.
        for (title, index) in [(color, 3), (palm, 0)] {
            let day = resolve(title, at: index, in: light)
            let night = resolve(title, at: index, in: dark)
            try expect((day?.redComponent ?? 1) < 0.25 && (night?.redComponent ?? 0) > 0.75,
                       "separator and stale label must adapt to the menu bar without a title refresh")
        }
    }

    private static func symbolsGlyph(_ source: MenuBarQuotaSource) throws -> Data {
        let rendered = MenuBarTitleRenderer.render(
            style: .symbols, density: .full, keepAwake: false,
            metrics: [MenuBarMetric(kind: .quota(source), value: "50", remaining: 50)]
        )
        var found: Data?
        rendered.title.enumerateAttribute(
            .attachment,
            in: NSRange(location: 0, length: rendered.title.length),
            options: []
        ) { value, _, _ in
            if let image = (value as? NSTextAttachment)?.image, let tiff = image.tiffRepresentation {
                found = tiff
            }
        }
        guard let found else {
            throw TestFailure.assertion("no gauge image rendered for \(source.rawValue)")
        }
        return found
    }

    private static func dotsTitle(_ source: MenuBarQuotaSource) -> String {
        MenuBarTitleRenderer.render(
            style: .dots, density: .full, keepAwake: false,
            metrics: [MenuBarMetric(kind: .quota(source), value: "50", remaining: 50)]
        ).title.string
    }

    private static func decodeFixture(_ json: String) throws -> Usage {
        do {
            return try JSONDecoder().decode(Usage.self, from: Data(json.utf8))
        } catch {
            throw TestFailure.assertion("fixture decode failed: \(error)")
        }
    }

    /// 一个把六个窗口都发全了的账号：Claude q5/q7/qf、Codex p5/pw、Grok pct，用量互不相同便于定位串线。
    private static let fixtureJSON = """
    {
      "claude": {
        "ranges": {
          "today": {"hit": 40, "in": 1000, "out": 200, "cr": 100, "cw": 50, "cost": 1.25, "sessions": 2, "models": []},
          "yesterday": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "cost": 0, "sessions": 0, "models": []},
          "week": {"hit": 40, "in": 3000, "out": 600, "cr": 300, "cw": 100, "cost": 3.0, "sessions": 5, "models": []},
          "last_week": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "cost": 0, "sessions": 0, "models": []},
          "month": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "cost": 0, "sessions": 0, "models": []},
          "year": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "cost": 0, "sessions": 0, "models": []}
        },
        "session_name": "demo",
        "session_total": 2,
        "q5": 20,
        "q7": 40,
        "qf": 10
      },
      "codex": {
        "ranges": {
          "today": {"hit": 20, "in": 100, "cached": 50, "out": 200, "reason": 10, "cost": 0.5, "sessions": 1, "models": []},
          "yesterday": {"hit": 0, "in": 0, "cached": 0, "out": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "week": {"hit": 0, "in": 0, "cached": 0, "out": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "last_week": {"hit": 0, "in": 0, "cached": 0, "out": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "month": {"hit": 0, "in": 0, "cached": 0, "out": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "year": {"hit": 0, "in": 0, "cached": 0, "out": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []}
        },
        "p5": 88,
        "pw": 35
      },
      "gemini": {
        "ranges": {
          "today": {"hit": 10, "in": 80, "out": 20, "cached": 10, "thoughts": 5, "cost": 0.1, "sessions": 1, "models": []},
          "yesterday": {"hit": 0, "in": 0, "out": 0, "cached": 0, "thoughts": 0, "cost": 0, "sessions": 0, "models": []},
          "week": {"hit": 0, "in": 0, "out": 0, "cached": 0, "thoughts": 0, "cost": 0, "sessions": 0, "models": []},
          "last_week": {"hit": 0, "in": 0, "out": 0, "cached": 0, "thoughts": 0, "cost": 0, "sessions": 0, "models": []},
          "month": {"hit": 0, "in": 0, "out": 0, "cached": 0, "thoughts": 0, "cost": 0, "sessions": 0, "models": []},
          "year": {"hit": 0, "in": 0, "out": 0, "cached": 0, "thoughts": 0, "cost": 0, "sessions": 0, "models": []}
        }
      },
      "grok": {
        "ranges": {
          "today": {"tokens": 0, "sessions": 0},
          "yesterday": {"tokens": 0},
          "week": {"tokens": 0},
          "last_week": {"tokens": 0},
          "month": {"tokens": 0},
          "year": {"tokens": 0}
        },
        "pct": 25,
        "window": "week"
      },
      "antigravity": {
        "available": true,
        "windows": [
          {"id": "antigravity-gemini-weekly", "used_pct": 17},
          {"id": "antigravity-gemini-5h", "used_pct": 19},
          {"id": "antigravity-3p-weekly", "used_pct": 23},
          {"id": "antigravity-3p-5h", "used_pct": 29},
          {"id": "antigravity-gemini-argon-weekly", "used_pct": 31}
        ]
      },
      "hermes": {
        "ranges": {
          "today": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "yesterday": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "week": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "last_week": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "month": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "year": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []}
        }
      },
      "openclaw": {
        "ranges": {
          "today": {"tasks": 0, "completed": 0, "failed": 0, "hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "cost": 0, "sessions": 0, "models": []},
          "yesterday": {"tasks": 0, "completed": 0, "failed": 0, "models": []},
          "week": {"tasks": 0, "completed": 0, "failed": 0, "models": []},
          "last_week": {"tasks": 0, "completed": 0, "failed": 0, "models": []},
          "month": {"tasks": 0, "completed": 0, "failed": 0, "models": []},
          "year": {"tasks": 0, "completed": 0, "failed": 0, "models": []}
        }
      },
      "opencode": {
        "ranges": {
          "today": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "yesterday": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "week": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "last_week": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "month": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "year": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []}
        }
      },
      "kimicode": {
        "ranges": {
          "today": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "yesterday": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "week": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "last_week": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "month": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "year": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []}
        },
        "p5": 15,
        "pw": 55,
        "plan": "LEVEL_INTERMEDIATE"
      }
    }
    """
}
