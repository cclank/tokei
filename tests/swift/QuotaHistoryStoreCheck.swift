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
        print("quota history store checks passed")
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

        try expect(projection.latestValues[L10n.quota5h] == 79, "projection should keep the latest value")
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
        try expect(nearest?.rows.map(\.window) == [L10n.quota5h, L10n.quotaWeekAll, L10n.quotaWeekFable],
                   "hover should include every available quota window")
        try expect(nearest?.activity.map(\.model) == ["Claude Fable", "Claude Opus"],
                   "hover should retain activity for the selected minute")

        let fableMarker = projection.markerData.first {
            $0.window == L10n.quotaWeekFable && !$0.activity.isEmpty
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
