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
}

@main
struct MenuBarQuotaSourceCheck {
    static func main() throws {
        _ = NSApplication.shared

        try checkSourceIdentity()
        try checkDefaults()
        try checkDefaultMetricsUnchanged()
        try checkReading()
        try checkRenderable()
        try checkDensity()
        try checkWindowGlyphsAreDistinct()
        try checkRenderedColor()

        print("menu bar quota source checks passed")
    }

    private static func checkSourceIdentity() throws {
        let order = MenuBarQuotaSource.allCases.map(\.rawValue)
        try expect(order == ["claude5h", "claudeWeek", "claudeFable",
                             "codex5h", "codexWeek", "grok"],
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
                              "Codex 5h", "Codex 周", "Grok"],
                   "window labels changed: \(labels)")

        let defaultOn = MenuBarQuotaSource.allCases.filter(\.defaultEnabled).map(\.rawValue)
        try expect(defaultOn == ["claude5h", "codexWeek"],
                   "only the two historically-on windows may default on: \(defaultOn)")

        let windows = MenuBarQuotaSource.allCases.map(\.window)
        try expect(windows == [.fiveHour, .week, .week, .fiveHour, .week, nil],
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
        try expect(used == [20, 40, 10, 88, 35, 25], "reading mapped to the wrong field: \(used)")

        // 模型里存已用百分比，状态栏显示剩余，别把 100-x 丢了。
        let metrics = MenuBarQuotaSource.metrics(in: usage)
        try expect(metrics.map(\.value) == ["80", "60", "90", "12", "65", "75"],
                   "remaining conversion or order wrong: \(metrics.map(\.value))")

        // 账号没有这个窗口 → 整项不出现。
        var missingFable = usage
        missingFable.claude.qf = nil
        try expect(MenuBarQuotaSource.metrics(in: missingFable).map(\.kind.displayName)
                    == ["Claude 5h", "Claude 周", "Codex 5h", "Codex 周", "Grok"],
                   "a nil window must drop out entirely")

        // 数据过期 → 也不出现，别在状态栏上挂个陈旧数字。
        var staleCodex5h = usage
        staleCodex5h.codex.p5_stale = true
        try expect(!MenuBarQuotaSource.metrics(in: staleCodex5h)
                    .contains { $0.kind.displayName == "Codex 5h" },
                   "stale window must be excluded")
    }

    private static func checkRenderable() throws {
        let ud = UserDefaults.standard
        let keys = MenuBarQuotaSource.allCases.map(\.defaultsKey)
        defer { keys.forEach { ud.removeObject(forKey: $0) } }
        keys.forEach { ud.set(true, forKey: $0) }

        let usage = try decodeFixture(fixtureJSON)

        // 过期的窗口画不出数字。设置页的提示语和预览走这个谓词，
        // 必须和 metrics(in:) 完全一致，否则又会宣布状态栏没画的组合。
        var staleFable = usage
        staleFable.claude.qf_stale = true
        try expect(!MenuBarQuotaSource.claudeFable.isRenderable(in: staleFable),
                   "a stale window cannot render a number")
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
      }
    }
    """
}
