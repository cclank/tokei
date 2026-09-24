import Foundation

enum SubscriptionQuotaState: Equatable {
    case unavailable
    case available
    case partiallyStale
    case expired

    static func resolve(_ windows: [(value: Double?, stale: Bool?)]) -> Self {
        let availableWindows = windows.filter { $0.value != nil }
        guard !availableWindows.isEmpty else { return .unavailable }

        let staleCount = availableWindows.filter { $0.stale == true }.count
        if staleCount == 0 { return .available }
        if staleCount == availableWindows.count { return .expired }
        return .partiallyStale
    }

    func shouldUseCompactCard(hasUsage: Bool) -> Bool {
        self == .expired && !hasUsage
    }
}

enum SubscriptionQuotaPresentation {
    static func remainingLabel(_ remaining: Double) -> String {
        let clamped = min(100, max(0, remaining))
        return clamped < 0.5 ? L10n.exhausted : String(format: "%.0f%%", clamped)
    }
}
