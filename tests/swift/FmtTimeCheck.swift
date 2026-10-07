import Foundation

private enum TestFailure: Error {
    case assertion(String)
}

private func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() { throw TestFailure.assertion(message) }
}

@main
struct FmtTimeCheck {
    static func main() throws {
        L10n.forcedLanguage = .zh
        // 2026-10-23 04:53 UTC
        let expiry = 1_792_731_180
        NSTimeZone.default = TimeZone(identifier: "America/Los_Angeles")!
        try expect(Fmt.localTime(expiry) == "10-22 21:53", "到期时间按系统时区显示，不再固定北京时间")
        NSTimeZone.default = TimeZone(identifier: "Asia/Shanghai")!
        try expect(Fmt.localTime(expiry) == "10-23 12:53", "换个时区跟着变")
        try expect(Fmt.localTimeZoneCaption().hasPrefix("本地 · "), "列表上注明是本地时区")

        let now = Date(timeIntervalSince1970: TimeInterval(expiry))
        try expect(Fmt.remaining(expiry, now: now.addingTimeInterval(-(16 * 86400 + 6 * 3600 + 120))) == "16d6h",
                   "十几天后到期按天显示")
        try expect(Fmt.remaining(expiry, now: now.addingTimeInterval(-(26 * 3600 + 5 * 60))) == "26h5m",
                   "两天以内同额度行的写法")
        try expect(Fmt.remaining(expiry, now: now.addingTimeInterval(-30)) == "1m", "不足一分钟也不显示 0m")
        try expect(Fmt.remaining(expiry, now: now.addingTimeInterval(60)) == "已到期", "过了就是已到期")
        print("fmt time checks passed")
    }
}
