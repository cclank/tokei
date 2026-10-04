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
        let now = Int(Date().timeIntervalSince1970)
        let compact = Fmt.localTime(now)
        try expect(compact.contains(":"), "localTime compact should include clock time")
        let full = Fmt.localTime(now, full: true)
        try expect(full.count > compact.count, "full localTime should be longer than compact")
        let caption = Fmt.localTimeZoneCaption()
        try expect(caption.hasPrefix("本地"), "timezone caption should mention local")
        try expect(Fmt.countdown(now + 7200).contains("h"), "future countdown should include hours")
        try expect(Fmt.countdown(now - 3600) == "即将重置", "past countdown should show imminent reset")
        print("fmt time checks passed")
    }
}
