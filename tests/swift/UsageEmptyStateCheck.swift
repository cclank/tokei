import Foundation

private enum TestFailure: Error {
    case assertion(String)
}

private func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() { throw TestFailure.assertion(message) }
}

@main
struct UsageEmptyStateCheck {
    static func main() throws {
        let none: (RangeKey) -> Int = { _ in 0 }

        // 正在刷新时先说自己在刷：这一刻「空」还不是结论。
        try expect(
            UsageEmptyState.resolve(selected: .today, refreshing: true, tokens: none) == .refreshing,
            "refreshing wins over an empty range"
        )
        // 即使别的区间有数，刷新中也不能抢先下结论。
        try expect(
            UsageEmptyState.resolve(
                selected: .today, refreshing: true,
                tokens: { $0 == .yesterday ? 999 : 0 }
            ) == .refreshing,
            "refreshing wins even when a recent range has usage"
        )

        // 今日为空、昨日有量：拿昨日作证，证明统计是活的。
        try expect(
            UsageEmptyState.resolve(
                selected: .today, refreshing: false,
                tokens: { $0 == .yesterday ? 12_300_000 : 0 }
            ) == .empty(recent: L10n.rangeYesterday + " 12.3M"),
            "yesterday is the first witness"
        )
        // 数量级跟着 Fmt.human 走，不自己另造一套写法。
        try expect(
            UsageEmptyState.resolve(
                selected: .today, refreshing: false,
                tokens: { $0 == .yesterday ? 104_000_000 : 0 }
            ) == .empty(recent: L10n.rangeYesterday + " " + Fmt.human(104_000_000)),
            "hundred-million scale follows Fmt.human"
        )
        // 昨日也没有就往外找，本周优先于本月。
        try expect(
            UsageEmptyState.resolve(
                selected: .today, refreshing: false,
                tokens: { key in key == .week ? 2_000 : (key == .month ? 9_000 : 0) }
            ) == .empty(recent: L10n.weekThis + " " + Fmt.human(2_000)),
            "week outranks month"
        )
        // 谁都没有就不给旁证，而不是编一个。
        try expect(
            UsageEmptyState.resolve(selected: .today, refreshing: false, tokens: none)
                == .empty(recent: nil),
            "no witness is better than an invented one"
        )

        // 今日其实有量时不该走空态旁证——那是调用方的判断，这里也不越俎代庖。
        try expect(
            UsageEmptyState.resolve(
                selected: .today, refreshing: false,
                tokens: { $0 == .today ? 5 : 100 }
            ) == .empty(recent: nil),
            "a non-empty today carries no witness"
        )

        // 只有「今日」给旁证：其它区间为空不会让人怀疑统计坏了。
        for key in [RangeKey.yesterday, .week, .month, .year, .all] {
            try expect(
                UsageEmptyState.resolve(
                    selected: key, refreshing: false,
                    tokens: { $0 == .yesterday ? 500 : 0 }
                ) == .empty(recent: nil),
                "only today gets a witness, not \(key.rawValue)"
            )
        }

        print("usage empty state checks passed")
    }
}
