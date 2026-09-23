import Foundation

private enum TestFailure: Error {
    case assertion(String)
}

@main
struct QuotaHistoryStoreCheck {
    static func main() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("tokei-quota-history-\(UUID().uuidString)")
        let fileURL = directory.appendingPathComponent("quota_history.json")
        defer { try? FileManager.default.removeItem(at: directory) }

        let base = Date(timeIntervalSince1970: 1_800_000_000)
        let store = QuotaHistoryStore(fileURL: fileURL)
        store.record(
            QuotaCapture(
                claudeFiveHourRemaining: 82,
                claudeWeekRemaining: 61,
                claudeFableWeekRemaining: 17,
                codexWeekRemaining: 49,
                claudeModelTotals: ["claude-opus": 100],
                codexModelTotals: ["gpt-5": 200]
            ),
            at: base
        )
        try expect(store.points.count == 1, "first capture should create one point")
        try expect(store.points[0].claudeActivity.isEmpty, "first capture should establish a baseline")

        store.record(
            QuotaCapture(
                claudeFiveHourRemaining: 80.5,
                claudeWeekRemaining: 60.5,
                claudeFableWeekRemaining: 16.5,
                codexWeekRemaining: 48.5,
                claudeModelTotals: ["claude-opus": 130],
                codexModelTotals: ["gpt-5": 225]
            ),
            at: base.addingTimeInterval(30)
        )
        try expect(store.points.count == 1, "captures in one minute should merge")
        try expect(store.points[0].claudeFiveHourRemaining == 80.5, "same-minute quota should use latest value")
        try expect(store.points[0].claudeFableWeekRemaining == 16.5, "Fable quota should use latest value")
        try expect(store.points[0].claudeActivity == [
            QuotaModelActivity(model: "claude-opus", tokenDelta: 30),
        ], "same-minute model delta should be recorded")

        store.record(
            QuotaCapture(
                claudeFiveHourRemaining: 79,
                claudeWeekRemaining: 60,
                claudeFableWeekRemaining: 16,
                codexWeekRemaining: 48,
                claudeModelTotals: ["claude-opus": 150, "claude-sonnet": 10],
                codexModelTotals: ["gpt-5": 240]
            ),
            at: base.addingTimeInterval(65)
        )
        try expect(store.points.count == 2, "next minute should append a point")
        try expect(store.points[1].claudeActivity.map(\.model) == [
            "claude-opus", "claude-sonnet",
        ], "new and growing models should both be attributed")

        store.record(
            QuotaCapture(
                claudeFiveHourRemaining: 78,
                claudeWeekRemaining: 59,
                codexWeekRemaining: 47
            ),
            at: base.addingTimeInterval(125)
        )
        store.record(
            QuotaCapture(
                claudeFiveHourRemaining: 77,
                claudeWeekRemaining: 58,
                codexWeekRemaining: 46,
                claudeModelTotals: ["claude-opus": 170, "claude-sonnet": 10],
                codexModelTotals: ["gpt-5": 260]
            ),
            at: base.addingTimeInterval(185)
        )
        try expect(store.points.last?.claudeActivity == [
            QuotaModelActivity(model: "claude-opus", tokenDelta: 20),
        ], "a transient empty scan should not reset the activity baseline")

        let reloaded = QuotaHistoryStore(fileURL: fileURL)
        try expect(reloaded.points == store.points, "history should survive a reload")

        reloaded.record(
            QuotaCapture(
                claudeFiveHourRemaining: 100,
                claudeWeekRemaining: 100,
                claudeFableWeekRemaining: 100,
                codexWeekRemaining: 100
            ),
            at: base.addingTimeInterval(8 * 24 * 60 * 60)
        )
        try expect(reloaded.points.count == 1, "points outside retention should be pruned")

        try checkProjection()
        try checkDailyConsumption()
        print("quota history store checks passed")
    }

    private static func checkDailyConsumption() throws {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0) ?? calendar.timeZone
        // 两天：day1 82→75（耗 7pp），day2 75→72 再回满到 97（耗 3pp + 1 次 reset）。
        let day1 = 1_800_000_000 - (1_800_000_000 % 86_400)
        let points = [
            codexPoint(day1 + 3600, 82),
            codexPoint(day1 + 7200, 80),
            codexPoint(day1 + 10800, 75),
            codexPoint(day1 + 86_400 + 3600, 75),
            codexPoint(day1 + 86_400 + 7200, 72),
            codexPoint(day1 + 86_400 + 10800, 97),
        ]
        let rows = QuotaHistoryProjection.dailyConsumption(
            from: points, tool: .codex, calendar: calendar, completeCoverageHours: 1)
        try expect(rows.count == 2, "two calendar days should produce two rows")
        try expect(rows[0].consumed == 3.0, "latest day should consume 3pp (75→72, refill excluded)")
        try expect(rows[0].resets == 1, "refill should count as one reset")
        try expect(rows[0].isComplete, "3h coverage should clear a 1h bar")
        try expect(rows[1].consumed == 7.0, "first day should consume 7pp (82→75)")
        try expect(rows[1].resets == 0, "no refill on the first day")

        // 上升不抵扣下降：100→90→95→80 计 10+15=25pp。
        let sawtooth = [
            codexPoint(day1 + 100, 100),
            codexPoint(day1 + 200, 90),
            codexPoint(day1 + 300, 95),
            codexPoint(day1 + 400, 80),
        ]
        let single = QuotaHistoryProjection.dailyConsumption(
            from: sawtooth, tool: .codex, calendar: calendar)
        try expect(single.count == 1, "same-day points should merge into one row")
        try expect(single[0].consumed == 25.0, "refills must not offset consumption")
        try expect(single[0].resets == 1, "one refill should be counted")

        // 采样不足标不完整。
        let sparse = [codexPoint(day1 + 100, 90), codexPoint(day1 + 200, 85)]
        let sparseRows = QuotaHistoryProjection.dailyConsumption(
            from: sparse, tool: .codex, calendar: calendar)
        try expect(!sparseRows[0].isComplete, "minutes-apart samples must flag incomplete")

        // 排序：新→旧。
        try expect(rows[0].dayStart > rows[1].dayStart, "rows should sort newest first")
    }

    private static func codexPoint(_ timestamp: Int, _ remaining: Double) -> QuotaHistoryPoint {
        QuotaHistoryPoint(
            timestamp: timestamp,
            claudeFiveHourRemaining: nil,
            claudeWeekRemaining: nil,
            claudeFableWeekRemaining: nil,
            codexWeekRemaining: remaining,
            claudeActivity: [],
            codexActivity: []
        )
    }

    private static func checkProjection() throws {
        try expect(
            QuotaHistoryTool.claude.rawValue == "Claude Code",
            "Claude quota history should use the full product name"
        )
        let base = 1_800_000_000
        let points = [
            historyPoint(base, 80, 60, 20, activity: []),
            historyPoint(base + 60, 80, 60, 20, activity: []),
            historyPoint(base + 120, 80, 60, 20, activity: []),
            historyPoint(
                base + 180,
                79,
                59.5,
                19.5,
                activity: [
                    QuotaModelActivity(model: "Claude Opus", tokenDelta: 300),
                    QuotaModelActivity(model: "Claude Fable", tokenDelta: 100),
                ]
            ),
            historyPoint(
                base + 240,
                79,
                59.5,
                19.5,
                activity: [
                    QuotaModelActivity(model: "Claude Fable", tokenDelta: 200),
                    QuotaModelActivity(model: "Claude Opus", tokenDelta: 600),
                ]
            ),
            historyPoint(base + 300, 79, 59.5, 19.5, activity: []),
        ]
        let projection = QuotaHistoryProjection(points: points, tool: .claude)

        try expect(projection.latestValues["5 小时"] == 79, "projection should keep the latest value")
        try expect(projection.latestDatumIDs.count == 3, "each series should have one latest marker")
        try expect(projection.lineData.count == 12, "flat plateaus should compact to transition edges")
        try expect(projection.markerData.count == 6, "activity and latest markers should be preserved")
        try expect(projection.dropEvents.count == 3, "drops should be detected for every Claude window")
        try expect(projection.activityEvents.count == 2, "detailed model activity should remain visible")
        try expect(projection.hoverSamples.count == 6, "every sampled minute should remain hoverable")
        let nearest = projection.nearestHoverSample(
            to: Date(timeIntervalSince1970: TimeInterval(base + 250))
        )
        try expect(nearest?.timestamp.timeIntervalSince1970 == TimeInterval(base + 240),
                   "hover should find the nearest sampled minute")
        try expect(nearest?.rows.map(\.window) == ["5 小时", "周 · 全部", "周 · Fable"],
                   "hover should include every available quota window")
        try expect(nearest?.activity.map(\.model) == ["Claude Fable", "Claude Opus"],
                   "hover should retain activity for the selected minute")

        let fableMarker = projection.markerData.first {
            $0.window == "周 · Fable" && !$0.activity.isEmpty
        }
        try expect(
            fableMarker?.activity.map(\.model) == ["Claude Fable"],
            "Fable markers should only include Fable activity"
        )
    }

    private static func historyPoint(
        _ timestamp: Int,
        _ fiveHour: Double,
        _ week: Double,
        _ fable: Double,
        activity: [QuotaModelActivity]
    ) -> QuotaHistoryPoint {
        QuotaHistoryPoint(
            timestamp: timestamp,
            claudeFiveHourRemaining: fiveHour,
            claudeWeekRemaining: week,
            claudeFableWeekRemaining: fable,
            codexWeekRemaining: 50,
            claudeActivity: activity,
            codexActivity: []
        )
    }

    private static func expect(
        _ condition: @autoclosure () -> Bool,
        _ message: String
    ) throws {
        if !condition() {
            throw TestFailure.assertion(message)
        }
    }
}
