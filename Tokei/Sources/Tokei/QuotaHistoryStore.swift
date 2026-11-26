import Combine
import Foundation

struct QuotaModelActivity: Codable, Equatable, Identifiable {
    var model: String
    var tokenDelta: Int

    var id: String { model }
}

struct QuotaHistoryPoint: Codable, Equatable, Identifiable {
    var timestamp: Int
    var claudeFiveHourRemaining: Double?
    var claudeWeekRemaining: Double?
    var claudeFableWeekRemaining: Double?
    var codexWeekRemaining: Double?
    var claudeActivity: [QuotaModelActivity] = []
    var codexActivity: [QuotaModelActivity] = []
    /// Provider window IDs stay stable across display-language changes.
    var antigravityRemaining: [String: Double]?

    var id: Int { timestamp }
}

struct QuotaCapture {
    var claudeFiveHourRemaining: Double?
    var claudeWeekRemaining: Double?
    var claudeFableWeekRemaining: Double?
    var codexWeekRemaining: Double?
    var claudeModelTotals: [String: Int]
    var codexModelTotals: [String: Int]
    var antigravityRemaining: [String: Double]

    init(
        claudeFiveHourRemaining: Double? = nil,
        claudeWeekRemaining: Double? = nil,
        claudeFableWeekRemaining: Double? = nil,
        codexWeekRemaining: Double? = nil,
        claudeModelTotals: [String: Int] = [:],
        codexModelTotals: [String: Int] = [:],
        antigravityRemaining: [String: Double] = [:]
    ) {
        self.claudeFiveHourRemaining = claudeFiveHourRemaining
        self.claudeWeekRemaining = claudeWeekRemaining
        self.claudeFableWeekRemaining = claudeFableWeekRemaining
        self.codexWeekRemaining = codexWeekRemaining
        self.claudeModelTotals = claudeModelTotals
        self.codexModelTotals = codexModelTotals
        self.antigravityRemaining = antigravityRemaining
    }
}

private struct QuotaHistoryState: Codable {
    var version = 1
    var points: [QuotaHistoryPoint] = []
    var lastClaudeModelTotals: [String: Int] = [:]
    var lastCodexModelTotals: [String: Int] = [:]
    var hasClaudeBaseline = false
    var hasCodexBaseline = false
    var claudeBaselineDay: Int?
    var codexBaselineDay: Int?
}

final class QuotaHistoryStore: ObservableObject {
    static let shared = QuotaHistoryStore()

    @Published private(set) var points: [QuotaHistoryPoint]

    private let fileURL: URL
    private let retentionSeconds: Int
    private let persistenceQueue = DispatchQueue(label: "tokei.quotaHistory.persistence", qos: .utility)
    private var state: QuotaHistoryState

    init(
        fileURL: URL = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".tokei/quota_history.json"),
        retentionHours: Int = 24 * 7
    ) {
        self.fileURL = fileURL
        retentionSeconds = max(24, retentionHours) * 60 * 60
        state = Self.loadState(from: fileURL)
        points = state.points.sorted { $0.timestamp < $1.timestamp }
    }

    func record(_ capture: QuotaCapture, at date: Date = Date()) {
        let minute = Int(date.timeIntervalSince1970 / 60) * 60
        let day = Int(Calendar.current.startOfDay(for: date).timeIntervalSince1970)
        let cutoff = minute - retentionSeconds
        var changed = false

        let retained = points.filter { $0.timestamp >= cutoff }
        if retained.count != points.count {
            points = retained
            changed = true
        }

        let claudeBaseline = prepareBaseline(
            previous: state.lastClaudeModelTotals,
            hasBaseline: state.hasClaudeBaseline,
            baselineDay: state.claudeBaselineDay,
            currentDay: day
        )
        let codexBaseline = prepareBaseline(
            previous: state.lastCodexModelTotals,
            hasBaseline: state.hasCodexBaseline,
            baselineDay: state.codexBaselineDay,
            currentDay: day
        )
        let claudeActivity = activity(
            current: capture.claudeModelTotals,
            previous: claudeBaseline.previous,
            hasBaseline: claudeBaseline.hasBaseline
        )
        let codexActivity = activity(
            current: capture.codexModelTotals,
            previous: codexBaseline.previous,
            hasBaseline: codexBaseline.hasBaseline
        )

        let nextClaudeBaseline = updatedBaseline(
            current: capture.claudeModelTotals,
            prepared: claudeBaseline,
            existingDay: state.claudeBaselineDay,
            currentDay: day
        )
        state.lastClaudeModelTotals = nextClaudeBaseline.totals
        state.hasClaudeBaseline = nextClaudeBaseline.hasBaseline
        state.claudeBaselineDay = nextClaudeBaseline.day

        let nextCodexBaseline = updatedBaseline(
            current: capture.codexModelTotals,
            prepared: codexBaseline,
            existingDay: state.codexBaselineDay,
            currentDay: day
        )
        state.lastCodexModelTotals = nextCodexBaseline.totals
        state.hasCodexBaseline = nextCodexBaseline.hasBaseline
        state.codexBaselineDay = nextCodexBaseline.day

        let incoming = QuotaHistoryPoint(
            timestamp: minute,
            claudeFiveHourRemaining: normalized(capture.claudeFiveHourRemaining),
            claudeWeekRemaining: normalized(capture.claudeWeekRemaining),
            claudeFableWeekRemaining: normalized(capture.claudeFableWeekRemaining),
            codexWeekRemaining: normalized(capture.codexWeekRemaining),
            claudeActivity: claudeActivity,
            codexActivity: codexActivity,
            antigravityRemaining: normalizedWindows(capture.antigravityRemaining)
        )

        let hasUsefulData = incoming.claudeFiveHourRemaining != nil ||
            incoming.claudeWeekRemaining != nil ||
            incoming.claudeFableWeekRemaining != nil ||
            incoming.codexWeekRemaining != nil ||
            incoming.antigravityRemaining != nil ||
            !incoming.claudeActivity.isEmpty ||
            !incoming.codexActivity.isEmpty

        if hasUsefulData {
            if let lastIndex = points.indices.last, points[lastIndex].timestamp == minute {
                let merged = merge(points[lastIndex], with: incoming)
                if merged != points[lastIndex] {
                    points[lastIndex] = merged
                    changed = true
                }
            } else {
                points.append(incoming)
                changed = true
            }
        }

        if changed || nextClaudeBaseline.changed || nextCodexBaseline.changed {
            state.points = points
            saveState()
        }
    }

    func points(since date: Date) -> [QuotaHistoryPoint] {
        let cutoff = Int(date.timeIntervalSince1970)
        return points.filter { $0.timestamp >= cutoff }
    }

    func flushPendingWrites() {
        persistenceQueue.sync {}
    }

    private static func loadState(from fileURL: URL) -> QuotaHistoryState {
        guard FileManager.default.fileExists(atPath: fileURL.path) else {
            return QuotaHistoryState()
        }
        do {
            let data = try Data(contentsOf: fileURL)
            let decoded = try JSONDecoder().decode(QuotaHistoryState.self, from: data)
            guard decoded.version == 1 else {
                fputs("Tokei quota history version is unsupported: \(decoded.version)\n", stderr)
                return QuotaHistoryState()
            }
            return decoded
        } catch {
            fputs("Tokei quota history load failed: \(error)\n", stderr)
            return QuotaHistoryState()
        }
    }

    private func saveState() {
        // Publish points immediately and write immutable snapshots in capture order.
        persistenceQueue.async { [fileURL, state] in
            do {
                try FileManager.default.createDirectory(
                    at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true
                )
                let data = try JSONEncoder().encode(state)
                try data.write(to: fileURL, options: .atomic)
                try? FileManager.default.setAttributes(
                    [.posixPermissions: 0o600], ofItemAtPath: fileURL.path
                )
            } catch {
                fputs("Tokei quota history write failed: \(error)\n", stderr)
            }
        }
    }

    private func normalized(_ value: Double?) -> Double? {
        guard let value, value.isFinite else { return nil }
        return min(100, max(0, value))
    }

    private func normalizedWindows(_ windows: [String: Double]) -> [String: Double]? {
        let valid = windows.filter { !$0.key.isEmpty && $0.value.isFinite && (0...100).contains($0.value) }
        return valid.isEmpty ? nil : valid
    }

    private func activity(
        current: [String: Int],
        previous: [String: Int],
        hasBaseline: Bool
    ) -> [QuotaModelActivity] {
        guard hasBaseline else { return [] }
        return current.compactMap { model, total in
            let delta = total - (previous[model] ?? 0)
            guard delta > 0 else { return nil }
            return QuotaModelActivity(model: model, tokenDelta: delta)
        }.sorted {
            if $0.tokenDelta == $1.tokenDelta { return $0.model < $1.model }
            return $0.tokenDelta > $1.tokenDelta
        }
    }

    private func prepareBaseline(
        previous: [String: Int],
        hasBaseline: Bool,
        baselineDay: Int?,
        currentDay: Int
    ) -> (previous: [String: Int], hasBaseline: Bool, dayChanged: Bool) {
        let dayChanged = baselineDay != nil && baselineDay != currentDay
        if dayChanged {
            return ([:], false, true)
        }
        return (previous, hasBaseline, false)
    }

    private func updatedBaseline(
        current: [String: Int],
        prepared: (previous: [String: Int], hasBaseline: Bool, dayChanged: Bool),
        existingDay: Int?,
        currentDay: Int
    ) -> (totals: [String: Int], hasBaseline: Bool, day: Int?, changed: Bool) {
        // A successful top-level refresh can still contain an empty tool range when one
        // scanner fails. Preserve a non-empty same-day baseline so recovery does not
        // attribute the whole day to one minute.
        let shouldReplace = prepared.dayChanged || !prepared.hasBaseline ||
            !current.isEmpty || prepared.previous.isEmpty
        guard shouldReplace else {
            return (prepared.previous, prepared.hasBaseline, existingDay, false)
        }
        let changed = prepared.previous != current ||
            !prepared.hasBaseline || existingDay != currentDay
        return (current, true, currentDay, changed)
    }

    private func merge(
        _ existing: QuotaHistoryPoint,
        with incoming: QuotaHistoryPoint
    ) -> QuotaHistoryPoint {
        var merged = existing
        merged.claudeFiveHourRemaining =
            incoming.claudeFiveHourRemaining ?? existing.claudeFiveHourRemaining
        merged.claudeWeekRemaining =
            incoming.claudeWeekRemaining ?? existing.claudeWeekRemaining
        merged.claudeFableWeekRemaining =
            incoming.claudeFableWeekRemaining ?? existing.claudeFableWeekRemaining
        merged.codexWeekRemaining =
            incoming.codexWeekRemaining ?? existing.codexWeekRemaining
        if let windows = incoming.antigravityRemaining {
            merged.antigravityRemaining = (existing.antigravityRemaining ?? [:])
                .merging(windows) { _, latest in latest }
        }
        merged.claudeActivity = mergeActivity(existing.claudeActivity, incoming.claudeActivity)
        merged.codexActivity = mergeActivity(existing.codexActivity, incoming.codexActivity)
        return merged
    }

    private func mergeActivity(
        _ existing: [QuotaModelActivity],
        _ incoming: [QuotaModelActivity]
    ) -> [QuotaModelActivity] {
        var totals = Dictionary(uniqueKeysWithValues: existing.map { ($0.model, $0.tokenDelta) })
        for activity in incoming {
            totals[activity.model, default: 0] += activity.tokenDelta
        }
        return totals.map { QuotaModelActivity(model: $0.key, tokenDelta: $0.value) }
            .sorted {
                if $0.tokenDelta == $1.tokenDelta { return $0.model < $1.model }
                return $0.tokenDelta > $1.tokenDelta
            }
    }
}
