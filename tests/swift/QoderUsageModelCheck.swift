import Foundation

private enum TestFailure: Error {
    case assertion(String)
}

private func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() { throw TestFailure.assertion(message) }
}

@main
struct QoderUsageModelCheck {
    static func main() throws {
        // 断言的是中文输出，不能随跑测试那台机器的系统语言变化。
        L10n.forcedLanguage = .zh
        let cli = try JSONDecoder().decode(QoderRange.self, from: Data("""
        {
          "in": 115,
          "out": 35,
          "cr": 60,
          "cw": 15,
          "credits": 5.2,
          "usage_calls": 3,
          "usage_available": true,
          "sessions": 1,
          "calls": 4,
          "sub_agents": 1,
          "turns": 2,
          "tools": 6,
          "est": 99
        }
        """.utf8))
        try expect(cli.in == 115, "Qoder CLI non-cache input")
        try expect(cli.cr == 60, "Qoder CLI cache read")
        try expect(cli.cw == 15, "Qoder CLI cache write")
        try expect(cli.out == 35, "Qoder CLI output")
        try expect(cli.totalTokens == 225, "Qoder CLI exact total")
        try expect(cli.usage_available, "Qoder CLI exact usage flag")
        try expect(cli.usage_calls == 3, "Qoder CLI exact usage calls")
        try expect(abs(cli.credits - 5.2) < 0.000_001, "Qoder CLI credits")

        let work = try JSONDecoder().decode(QoderRange.self, from: Data("""
        {"in": 19, "out": 11, "sessions": 2, "calls": 3}
        """.utf8))
        try expect(work.totalTokens == 30, "QoderWork token total")
        try expect(work.cr == 0 && work.cw == 0, "QoderWork must not inherit CLI cache tokens")
        try expect(work.credits == 0, "QoderWork must not inherit CLI credits")

        let desktop = try JSONDecoder().decode(QoderIdeRange.self, from: Data("""
        {"in": 90, "cached": 10, "out": 5, "calls": 1}
        """.utf8))
        try expect(desktop.in + desktop.cached + desktop.out == 105,
                   "Qoder Desktop keeps its own token contract")

        print("qoder usage model checks passed")
    }
}
