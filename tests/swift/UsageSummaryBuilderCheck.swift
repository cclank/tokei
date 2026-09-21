import Foundation
import AppKit

private enum TestFailure: Error {
    case assertion(String)
}

private func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() { throw TestFailure.assertion(message) }
}

@main
struct UsageSummaryBuilderCheck {
    static func main() throws {
        // ImageRenderer needs an AppKit app instance (same as --shot).
        _ = NSApplication.shared

        let usage = try decodeFixture(Self.fixtureJSON)
        let allVisible = UsageToolVisibility.allVisible
        let staleReserveQuota = try JSONDecoder().decode(
            CodexReserveQuota.self,
            from: Data(#"{"used_percent":42,"stale":true}"#.utf8)
        )
        try expect(staleReserveQuota.usedPercent == 42 && staleReserveQuota.stale == true,
                   "reserve stale flag must decode")
        let legacyReserveQuota = try JSONDecoder().decode(
            CodexReserveQuota.self,
            from: Data(#"{"used_percent":42}"#.utf8)
        )
        try expect(legacyReserveQuota.stale == nil,
                   "reserve quota without stale must remain decoder-compatible")

        let todayText = UsageSummaryBuilder.text(
            usage: usage, range: .today, visibility: allVisible, updated: "12:34"
        )
        try expect(todayText.contains("Tokei 用量 · 今日"), "period label missing: \(todayText)")
        try expect(todayText.contains("Claude Code"), "claude line missing: \(todayText)")
        try expect(todayText.contains("$1.25"), "claude cost missing: \(todayText)")
        try expect(todayText.contains("Codex"), "codex line missing: \(todayText)")
        try expect(todayText.contains("$0.50"), "codex cost missing: \(todayText)")
        try expect(todayText.contains("Luna Reserve"), "reserve line missing: \(todayText)")
        try expect(todayText.contains("$0.25"), "reserve cost missing: \(todayText)")
        try expect(todayText.contains("合计"), "total line missing: \(todayText)")
        // Claude 1.25 + Codex 0.50 + Luna Reserve 0.25 + Gemini 0.10
        try expect(todayText.contains("$2.10"), "total cost wrong: \(todayText)")
        try expect(todayText.contains("更新于 12:34"), "updated missing: \(todayText)")
        try expect(!todayText.contains("更新于 更新"), "must not double-prefix bare time: \(todayText)")
        try expect(todayText.contains("Gemini"), "gemini should appear when visible: \(todayText)")
        try expect(todayText.contains("$0.10") || todayText.contains("$0.1"),
                   "gemini cost missing: \(todayText)")
        try expect(todayText.contains("CodeBuddy"), "codebuddy line missing: \(todayText)")
        try expect(todayText.contains("2.75 Credits"), "codebuddy credits missing: \(todayText)")

        var mixed = usage
        mixed.deepseekHarness.ranges.today.cost = 0.31
        mixed.deepseekHarness.ranges.today.cost_cny = 5.02
        mixed.deepseekHarness.ranges.today.in = 100
        let nativeText = UsageSummaryBuilder.text(usage: mixed, range: .today,
                                                 visibility: allVisible)
        try expect(nativeText.contains("¥5.02"), "native CNY missing: \(nativeText)")
        try expect(nativeMoney(0.31, 5.02) == "$0.31 + ¥5.02", "currencies must stay separate")
        let nativeTotals = UsageSummaryBuilder.totals(for: UsageSummaryBuilder.toolLines(
            usage: mixed, range: .today, visibility: allVisible))
        try expect(nativeTotals.cost_cny == 5.02, "CNY total mismatch")
        let decoded = try JSONDecoder().decode(TokenUsageRange.self, from:
            Data(#"{"cost":0.31,"cost_cny":5.02}"#.utf8))
        try expect(decoded.cost == 0.31 && decoded.cost_cny == 5.02, "currency decoding mismatch")

        // Store path uses lastUpdated = "更新 HH:mm:ss" (main.swift); strip, don't nest.
        let storeStampText = UsageSummaryBuilder.text(
            usage: usage, range: .today, visibility: allVisible, updated: "更新 21:51:18"
        )
        try expect(storeStampText.contains("更新于 21:51:18"),
                   "store stamp should normalize: \(storeStampText)")
        try expect(!storeStampText.contains("更新于 更新"),
                   "must not double-prefix store lastUpdated: \(storeStampText)")
        try expect(UsageSummaryBuilder.formatUpdatedLine("更新 21:51:18") == "更新于 21:51:18",
                   "formatUpdatedLine store stamp")
        try expect(UsageSummaryBuilder.formatUpdatedLine("更新于 09:00") == "更新于 09:00",
                   "formatUpdatedLine already-prefixed")
        try expect(UsageSummaryBuilder.formatUpdatedLine("加载中…") == nil,
                   "loading stamp omitted")

        var hideGemini = allVisible
        hideGemini.gemini = false
        hideGemini.codebuddy = false
        let hiddenText = UsageSummaryBuilder.text(
            usage: usage, range: .today, visibility: hideGemini, updated: nil
        )
        try expect(!hiddenText.contains("Gemini"),
                   "hidden gemini must be omitted: \(hiddenText)")
        try expect(hiddenText.contains("Claude Code"), "claude still required: \(hiddenText)")
        try expect(hiddenText.contains("Codex"), "codex still required: \(hiddenText)")
        try expect(hiddenText.contains("Luna Reserve"), "reserve still required: \(hiddenText)")
        try expect(hiddenText.contains("$2.00"),
                   "total without gemini should be $2.00: \(hiddenText)")

        // Empty tools (OpenCode with zeros) must not dump noise.
        try expect(!todayText.contains("OpenCode"),
                   "zero-usage tools should be omitted: \(todayText)")

        // Week range uses week numbers from fixture.
        let weekText = UsageSummaryBuilder.text(
            usage: usage, range: .week, visibility: allVisible, updated: nil
        )
        try expect(weekText.contains("Tokei 用量 · 本周"), "week label: \(weekText)")
        try expect(weekText.contains("$3.00"), "week claude cost: \(weekText)")

        let lines = UsageSummaryBuilder.toolLines(
            usage: usage, range: .today, visibility: hideGemini
        )
        try expect(lines.map(\.name) == ["Claude Code", "Codex", "Luna Reserve"],
                   "tool order/names: \(lines.map(\.name))")
        try expect(lines.map(\.id) == ["claude", "codex", "codex_reserve"],
                   "tool ids: \(lines.map(\.id))")
        try expect(lines[0].cost == 1.25, "claude cost value")
        try expect(lines[0].tokens == 1350, "claude tokens 1000+200+100+50")
        try expect(lines[0].input == 1000, "claude input detail")
        try expect(lines[0].output == 200, "claude output detail")
        try expect(lines[0].cacheRead == 100, "claude cache read")
        try expect(lines[1].cost == 0.50, "codex cost value")
        try expect(lines[1].tokens == 350, "codex tokens 100+50+200")
        try expect(lines[2].cost == 0.25, "reserve cost value")
        try expect(lines[2].tokens == 70, "reserve tokens 40+10+20")

        try expect(usage.openclaw.ranges.today.reason == 0,
                   "older OpenClaw snapshots without reason must decode as zero")
        let openClawYear = UsageSummaryBuilder.toolLines(
            usage: usage, range: .year, visibility: allVisible
        ).first(where: { $0.id == "openclaw" })
        try expect(openClawYear?.tokens == 7 && openClawYear?.reason == 7,
                   "OpenClaw reasoning tokens must survive decode and summary aggregation")

        let totals = UsageSummaryBuilder.totals(for: lines)
        try expect(totals.tools == 3, "totals tools")
        try expect(abs(totals.cost - 2.00) < 0.001, "totals cost")
        try expect(totals.input == 1140, "totals input")
        try expect(totals.output == 420, "totals output")
        try expect(hiddenText.contains("输入") || UsageSummaryBuilder.text(
            usage: usage, range: .today, visibility: hideGemini
        ).contains("输入"), "text totals include input detail")

        // Generated share images (footer + per-tool).
        try MainActor.assumeIsolated {
            guard let png = UsageShareImage.pngData(
                usage: usage, range: .today, visibility: allVisible, updated: "更新 21:51:18"
            ) else {
                throw TestFailure.assertion("pngData returned nil")
            }
            try expect(png.count > 800, "png too small: \(png.count)")
            try expect(png.starts(with: [0x89, 0x50, 0x4E, 0x47]), "not a PNG")

            guard let hiddenPng = UsageShareImage.pngData(
                usage: usage, range: .today, visibility: hideGemini, updated: nil
            ) else {
                throw TestFailure.assertion("hidden png nil")
            }
            try expect(hiddenPng.count > 800, "hidden png too small")
            try expect(hiddenPng != png, "hidden vs all-visible images should differ")

            guard let codexLine = UsageSummaryBuilder.line(
                forToolID: "codex", usage: usage, range: .today, visibility: allVisible
            ) else {
                throw TestFailure.assertion("codex line missing")
            }
            guard let singlePng = UsageShareImage.pngData(
                line: codexLine, range: .today, updated: "更新 12:00:00"
            ) else {
                throw TestFailure.assertion("single-tool png nil")
            }
            try expect(singlePng.count > 800, "single png too small")
            try expect(singlePng != png, "single-tool image should differ from overview")

            let wrote = UsageShareImage.copyToPasteboard(
                line: codexLine, range: .today, updated: "更新 12:00:00"
            )
            try expect(wrote, "single-tool copyToPasteboard failed")
            let pb = NSPasteboard.general
            let hasImage = pb.canReadObject(forClasses: [NSImage.self], options: nil)
                || pb.data(forType: .png) != nil
            try expect(hasImage, "pasteboard should contain image/png")
        }

        // 分享图按展示名取主题色；漏登记的工具会掉进默认灰（Muse/Kimi/Prime/DeepSeek 曾全灰）。
        let gray = NSColor(Theme.tTertiary)
        for name in ["Prime Agent", "DeepSeek Harness", "Kimi Code", "Muse Code"] {
            let tint = NSColor(UsageShareImage.tint(for: name))
            try expect(!tint.isEqual(gray), "\(name) share tint must not be gray")
        }

        print("usage summary builder checks passed")
    }

    private static func decodeFixture(_ json: String) throws -> Usage {
        let data = Data(json.utf8)
        do {
            return try JSONDecoder().decode(Usage.self, from: data)
        } catch {
            throw TestFailure.assertion("fixture decode failed: \(error)")
        }
    }

    /// Minimal Usage JSON: today has Claude+Codex+Gemini; week has Claude only; rest empty.
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
        "session_total": 2
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
        "reserve_ranges": {
          "today": {"hit": 20, "in": 40, "cached": 10, "out": 20, "reason": 5, "cost": 0.25, "sessions": 1, "models": []},
          "yesterday": {"hit": 0, "in": 0, "cached": 0, "out": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "week": {"hit": 0, "in": 0, "cached": 0, "out": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "last_week": {"hit": 0, "in": 0, "cached": 0, "out": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "month": {"hit": 0, "in": 0, "cached": 0, "out": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
          "year": {"hit": 0, "in": 0, "cached": 0, "out": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []}
        }
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
        }
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
          "year": {"tasks": 0, "completed": 0, "failed": 0, "reason": 7, "models": []}
        }
      },
      "codebuddy": {
        "ranges": {
          "today": {"hit": 40, "in": 60, "out": 20, "cr": 40, "cw": 0, "reason": 0, "credits": 2.75, "sessions": 1, "models": [{"model_id": "fictional-codebuddy-model", "name": "Fictional CodeBuddy Model", "in": 60, "out": 20, "cr": 40, "cw": 0, "reason": 0, "cost": 0, "credits": 2.75}]},
          "yesterday": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "credits": 0, "sessions": 0, "models": []},
          "week": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "credits": 0, "sessions": 0, "models": []},
          "last_week": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "credits": 0, "sessions": 0, "models": []},
          "month": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "credits": 0, "sessions": 0, "models": []},
          "year": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "credits": 0, "sessions": 0, "models": []}
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
