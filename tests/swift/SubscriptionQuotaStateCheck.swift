import Foundation

@main
struct SubscriptionQuotaStateCheck {
    static func main() throws {
        try expect(
            SubscriptionQuotaState.resolve([
                (value: nil, stale: nil),
                (value: nil, stale: true),
            ]) == .unavailable,
            "missing quota windows should be unavailable"
        )
        try expect(
            SubscriptionQuotaState.resolve([
                (value: 42, stale: false),
                (value: 73, stale: nil),
            ]) == .available,
            "fresh quota windows should be available"
        )
        try expect(
            SubscriptionQuotaState.resolve([
                (value: 42, stale: false),
                (value: 73, stale: true),
            ]) == .partiallyStale,
            "mixed freshness should be partially stale"
        )

        let expired = SubscriptionQuotaState.resolve([
            (value: 100, stale: true),
            (value: 73, stale: true),
        ])
        try expect(expired == .expired, "all stale quota windows should be expired")
        try expect(expired.shouldUseCompactCard(hasUsage: false),
                   "expired quota-only cards should be compact")
        try expect(!expired.shouldUseCompactCard(hasUsage: true),
                   "cards with usage should keep their full presentation")

        try expect(SubscriptionQuotaPresentation.remainingLabel(0) == L10n.exhausted,
                   "zero remaining should use an explicit exhausted label")
        try expect(SubscriptionQuotaPresentation.remainingLabel(-4) == L10n.exhausted,
                   "negative remaining should be clamped")
        try expect(SubscriptionQuotaPresentation.remainingLabel(42.4) == "42%",
                   "positive remaining should stay numeric")
        try expect(SubscriptionQuotaPresentation.remainingLabel(120) == "100%",
                   "remaining percentage should not exceed 100 percent")

        print("subscription quota state checks passed")
    }

    private static func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
        guard condition() else {
            throw NSError(domain: "SubscriptionQuotaStateCheck", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: message])
        }
    }
}
