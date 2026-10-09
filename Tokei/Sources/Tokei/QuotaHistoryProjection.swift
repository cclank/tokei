import Foundation

enum QuotaHistoryTool: String, CaseIterable, Identifiable {
    case claude = "Claude Code"
    case codex = "Codex"

    var id: String { rawValue }

    var windowNames: [String] {
        switch self {
        case .claude:
            // 数据里的窗口标识（历史记录按它存），显示时再过 L()。
            return ["5 小时", "周 · 全部", "周 · Fable"] // l10n-ignore
        case .codex:
            return ["周"] // l10n-ignore
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

/// 某个本地自然日里，一个额度窗口被用掉了多少个百分点（issue #85）。
struct QuotaDailyConsumption: Identifiable {
    var dayStart: Date
    var window: String
    /// 当天所有下降量之和。回满、滚动窗口里旧用量过期造成的上升都不抵扣。
    var consumed: Double
    /// 当天回满的次数（一次上升至少 `refillThreshold` 个百分点才算）。
    var refills: Int
    /// 这天的数说得准。采样空档跨过零点、期间又掉了额度时，说不清掉在哪天，
    /// 界面标「约」；空档里额度没动就不影响。
    var isComplete: Bool

    var id: String { "\(Int(dayStart.timeIntervalSince1970)):\(window)" }
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

    /// 按本地自然日汇总每个窗口剩余额度的下降量，新 → 旧（issue #85）。
    ///
    /// 只用本机已有的分钟快照，不多发任何请求。同一窗口相邻两个快照之间：下降记为
    /// 消耗，记在后一个快照所在的那天；上升不抵扣（Claude 周额度是滚动窗口，旧用量
    /// 过期时剩余会慢慢回升，那不是「没用」），一次升够 `refillThreshold` 才算回满。
    ///
    /// 什么时候标「约」：只有真说不清归属时。夜里不用 Claude 时它的额度读数会过期、
    /// 不留快照，这种空档里额度没动就谈不上归错天；只有空档跨过零点、期间又确实掉了
    /// 额度，并且落在离当天开头 / 结尾超过 `edgeTolerance` 的位置，才标两边中受影响的
    /// 那天。另外最早那天之前的用量本来就没记录，它开头缺采样时也标「约」。
    static func dailyConsumption(
        from points: [QuotaHistoryPoint],
        tool: QuotaHistoryTool,
        calendar: Calendar = .current,
        refillThreshold: Double = 10,
        edgeTolerance: TimeInterval = 2 * 3600
    ) -> [QuotaDailyConsumption] {
        struct Day {
            var consumed = 0.0
            var refills = 0
            var first = Int.max
            var last = Int.min
            var uncertain = false
        }
        func dayStart(_ timestamp: Int) -> Date {
            calendar.startOfDay(for: Date(timeIntervalSince1970: TimeInterval(timestamp)))
        }
        var days: [String: [Date: Day]] = [:]
        var previous: [String: (value: Double, timestamp: Int)] = [:]
        for point in points.sorted(by: { $0.timestamp < $1.timestamp }) {
            let today = dayStart(point.timestamp)
            for window in tool.windowNames {
                guard let remaining = value(for: window, point: point, tool: tool) else { continue }
                var day = days[window]?[today] ?? Day()
                day.first = min(day.first, point.timestamp)
                day.last = max(day.last, point.timestamp)
                if let prior = previous[window] {
                    if remaining < prior.value {
                        day.consumed += prior.value - remaining
                        let priorDay = dayStart(prior.timestamp)
                        if priorDay != today {
                            // 这次下降跨过了零点：离当天开头太远，可能有一部分属于前一天
                            if TimeInterval(point.timestamp) - today.timeIntervalSince1970 > edgeTolerance {
                                day.uncertain = true
                            }
                            let priorEnd = calendar.date(byAdding: .day, value: 1, to: priorDay) ?? priorDay
                            if priorEnd.timeIntervalSince1970 - TimeInterval(prior.timestamp) > edgeTolerance {
                                days[window]?[priorDay]?.uncertain = true
                            }
                        }
                    } else if remaining - prior.value >= refillThreshold {
                        day.refills += 1
                    }
                }
                days[window, default: [:]][today] = day
                previous[window] = (remaining, point.timestamp)
            }
        }
        return days.flatMap { window, byDay in
            let oldest = byDay.keys.min()
            return byDay.map { start, day in
                let missingHistory = start == oldest
                    && TimeInterval(day.first) - start.timeIntervalSince1970 > edgeTolerance
                return QuotaDailyConsumption(
                    dayStart: start,
                    window: window,
                    consumed: day.consumed,
                    refills: day.refills,
                    isComplete: !day.uncertain && !missingHistory
                )
            }
        }.sorted {
            $0.dayStart == $1.dayStart
                ? (tool.windowNames.firstIndex(of: $0.window) ?? 0)
                    < (tool.windowNames.firstIndex(of: $1.window) ?? 0)
                : $0.dayStart > $1.dayStart
        }
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
        guard tool == .claude, window == "周 · Fable" else { return all } // l10n-ignore
        return all.filter { $0.model.localizedCaseInsensitiveContains("fable") }
    }

    private static func value(
        for window: String,
        point: QuotaHistoryPoint,
        tool: QuotaHistoryTool
    ) -> Double? {
        switch (tool, window) {
        case (.claude, "5 小时"): // l10n-ignore
            return point.claudeFiveHourRemaining
        case (.claude, "周 · 全部"): // l10n-ignore
            return point.claudeWeekRemaining
        case (.claude, "周 · Fable"): // l10n-ignore
            return point.claudeFableWeekRemaining
        case (.codex, "周"): // l10n-ignore
            return point.codexWeekRemaining
        default:
            return nil
        }
    }
}
