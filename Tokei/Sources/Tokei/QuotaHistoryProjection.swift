import Foundation

enum QuotaHistoryTool: String, CaseIterable, Identifiable {
    case claude = "Claude Code"
    case codex = "Codex"

    var id: String { rawValue }

    var windowNames: [String] {
        switch self {
        case .claude:
            return [L10n.quota5h, L10n.quotaWeekAll, L10n.quotaWeekFable]
        case .codex:
            return [L10n.quotaWeek]
        }
    }
}

struct QuotaChartDatum: Identifiable {
    var timestamp: Date
    var remaining: Double
    var window: String
    var activity: [QuotaModelActivity]

    var id: String { "\(Int(timestamp.timeIntervalSince1970)):\(window)" }
}

struct QuotaDropEvent: Identifiable {
    var timestamp: Date
    var durationMinutes: Int
    var window: String
    var drop: Double
    var activity: [QuotaModelActivity]

    var id: String { "\(Int(timestamp.timeIntervalSince1970)):\(window)" }
}

struct QuotaActivityEvent: Identifiable {
    var timestamp: Int
    var activity: [QuotaModelActivity]

    var id: Int { timestamp }
}

struct QuotaHoverRow: Identifiable {
    var window: String
    var remaining: Double

    var id: String { window }
}

struct QuotaHoverSample: Identifiable {
    var timestamp: Date
    var rows: [QuotaHoverRow]
    var activity: [QuotaModelActivity]

    var id: Int { Int(timestamp.timeIntervalSince1970) / 60 }
}

/// Precomputes all chart inputs once per SwiftUI body evaluation.
///
/// This keeps rendering linear in the number of history points. Flat line
/// segments and continuous activity runs are compacted without removing quota
/// changes, detailed events, or minute-level hover data.
struct QuotaHistoryProjection {
    var points: [QuotaHistoryPoint]
    var windowNames: [String]
    var lineData: [QuotaChartDatum]
    var markerData: [QuotaChartDatum]
    var latestValues: [String: Double]
    var latestDatumIDs: Set<String>
    var dropEvents: [QuotaDropEvent]
    var activityEvents: [QuotaActivityEvent]
    var hoverSamples: [QuotaHoverSample]

    init(points: [QuotaHistoryPoint], tool: QuotaHistoryTool) {
        let windows = tool.windowNames
        self.points = points
        windowNames = windows

        var seriesByWindow = Dictionary(
            uniqueKeysWithValues: windows.map { ($0, [QuotaChartDatum]()) }
        )
        var latestValues: [String: Double] = [:]
        var latestByWindow: [String: QuotaChartDatum] = [:]
        var drops: [QuotaDropEvent] = []
        var previousByWindow: [String: (point: QuotaHistoryPoint, remaining: Double)] = [:]
        var activityEvents: [QuotaActivityEvent] = []
        var hoverSamples: [QuotaHoverSample] = []
        hoverSamples.reserveCapacity(points.count)

        for point in points {
            let pointActivity = Self.activity(for: point, tool: tool)
            if !pointActivity.isEmpty {
                activityEvents.append(.init(timestamp: point.timestamp, activity: pointActivity))
            }

            let date = Date(timeIntervalSince1970: TimeInterval(point.timestamp))
            var hoverRows: [QuotaHoverRow] = []
            hoverRows.reserveCapacity(windows.count)
            for window in windows {
                guard let remaining = Self.value(for: window, point: point, tool: tool) else {
                    continue
                }
                let windowActivity = Self.activity(for: point, window: window, tool: tool)
                let datum = QuotaChartDatum(
                    timestamp: date,
                    remaining: remaining,
                    window: window,
                    activity: windowActivity
                )
                seriesByWindow[window, default: []].append(datum)
                latestValues[window] = remaining
                latestByWindow[window] = datum
                hoverRows.append(.init(window: window, remaining: remaining))

                if let previous = previousByWindow[window] {
                    let drop = previous.remaining - remaining
                    if drop >= 0.05 {
                        drops.append(.init(
                            timestamp: date,
                            durationMinutes: max(1, (point.timestamp - previous.point.timestamp) / 60),
                            window: window,
                            drop: drop,
                            activity: windowActivity
                        ))
                    }
                }
                previousByWindow[window] = (point, remaining)
            }
            if !hoverRows.isEmpty {
                hoverSamples.append(.init(
                    timestamp: date,
                    rows: hoverRows,
                    activity: pointActivity
                ))
            }
        }

        let latestDatumIDs = Set(latestByWindow.values.map(\.id))
        var markerByID = Dictionary(
            uniqueKeysWithValues: latestByWindow.values.map { ($0.id, $0) }
        )
        var lineData: [QuotaChartDatum] = []
        for window in windows {
            let series = seriesByWindow[window] ?? []
            lineData.append(contentsOf: Self.compactFlatSegments(series))

            var previousActivitySignature: String?
            for datum in series {
                let signature = Self.activitySignature(datum.activity)
                if let signature, signature != previousActivitySignature {
                    markerByID[datum.id] = datum
                }
                previousActivitySignature = signature
            }
        }

        self.latestValues = latestValues
        self.latestDatumIDs = latestDatumIDs
        self.lineData = lineData
        markerData = markerByID.values.sorted {
            if $0.timestamp == $1.timestamp {
                return (windows.firstIndex(of: $0.window) ?? Int.max) <
                    (windows.firstIndex(of: $1.window) ?? Int.max)
            }
            return $0.timestamp < $1.timestamp
        }
        dropEvents = drops.sorted { $0.timestamp > $1.timestamp }
        self.activityEvents = activityEvents.reversed()
        self.hoverSamples = hoverSamples
    }

    func nearestHoverSample(to date: Date) -> QuotaHoverSample? {
        guard !hoverSamples.isEmpty else { return nil }
        var lower = 0
        var upper = hoverSamples.count
        while lower < upper {
            let middle = (lower + upper) / 2
            if hoverSamples[middle].timestamp < date {
                lower = middle + 1
            } else {
                upper = middle
            }
        }
        if lower == 0 { return hoverSamples[0] }
        if lower == hoverSamples.count { return hoverSamples[hoverSamples.count - 1] }
        let before = hoverSamples[lower - 1]
        let after = hoverSamples[lower]
        return abs(before.timestamp.timeIntervalSince(date))
            <= abs(after.timestamp.timeIntervalSince(date)) ? before : after
    }

    /// Keeps both sides of every value transition, plus the first and last
    /// samples, so a step chart remains visually exact while flat minute-by-
    /// minute plateaus no longer create hundreds of redundant marks.
    private static func compactFlatSegments(
        _ series: [QuotaChartDatum]
    ) -> [QuotaChartDatum] {
        guard series.count > 2 else { return series }

        var compacted: [QuotaChartDatum] = [series[0]]
        compacted.reserveCapacity(min(series.count, 128))
        for index in 1 ..< series.count - 1 {
            let previous = series[index - 1]
            let current = series[index]
            let next = series[index + 1]
            if current.remaining != previous.remaining ||
                current.remaining != next.remaining {
                compacted.append(current)
            }
        }
        compacted.append(series[series.count - 1])
        return compacted
    }

    private static func activitySignature(
        _ activity: [QuotaModelActivity]
    ) -> String? {
        guard !activity.isEmpty else { return nil }
        let models = activity
            .map { $0.model.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }
            .filter { !$0.isEmpty }
            .sorted()
        guard !models.isEmpty else { return nil }
        return models.joined(separator: "\u{1F}")
    }

    private static func activity(
        for point: QuotaHistoryPoint,
        tool: QuotaHistoryTool
    ) -> [QuotaModelActivity] {
        tool == .claude ? point.claudeActivity : point.codexActivity
    }

    private static func activity(
        for point: QuotaHistoryPoint,
        window: String,
        tool: QuotaHistoryTool
    ) -> [QuotaModelActivity] {
        let all = activity(for: point, tool: tool)
        guard tool == .claude, window == L10n.quotaWeekFable else { return all }
        return all.filter { $0.model.localizedCaseInsensitiveContains("fable") }
    }

    private static func value(
        for window: String,
        point: QuotaHistoryPoint,
        tool: QuotaHistoryTool
    ) -> Double? {
        switch (tool, window) {
        case (.claude, L10n.quota5h):
            return point.claudeFiveHourRemaining
        case (.claude, L10n.quotaWeekAll):
            return point.claudeWeekRemaining
        case (.claude, L10n.quotaWeekFable):
            return point.claudeFableWeekRemaining
        case (.codex, L10n.quotaWeek):
            return point.codexWeekRemaining
        default:
            return nil
        }
    }
}
