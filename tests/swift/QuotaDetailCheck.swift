import Foundation

enum DataLoader {
    static var calls = 0
    static func runScriptRaw(args: [String], timeout: Double) -> (stdout: String, exitCode: Int32, timedOut: Bool) {
        calls += 1
        return ("", 1, false)
    }
}

@main
struct QuotaDetailCheck {
    static func main() throws {
        func expect(_ value: @autoclosure () -> Bool, _ label: String) {
            precondition(value(), label)
        }
        let json = #"{"tool":"claude","start":900,"end":1100,"used_pct":25,"tokens":100,"devices":{"synthetic":100},"approx":true,"current":true}"#
        let legacy = try JSONDecoder().decode(QuotaCycle.self, from: Data(json.utf8))
        expect(legacy.window == nil && !legacy.isMonthly, "legacy weekly cycle without window")
        let monthly = try JSONDecoder().decode(QuotaCycle.self, from: Data(String(json.dropLast()).appending(#","window":"month","cost":12.5}"#).utf8))
        expect(monthly.isMonthly && monthly.costLabel == "$12.50", "monthly window preserves cost")
        let monthlyRoundTrip = try JSONDecoder().decode(QuotaCycle.self, from: JSONEncoder().encode(monthly))
        expect(monthlyRoundTrip.window == "month", "monthly window survives cache round trip")
        expect(legacy.cost == nil && legacy.costLabel == nil && legacy.projectedCost == nil, "legacy missing cost")
        let null = try JSONDecoder().decode(QuotaCycle.self, from: Data(String(json.dropLast()).appending(#","cost":null}"#).utf8))
        expect(null.cost == nil, "null cost compatibility")
        var numeric = try JSONDecoder().decode(QuotaCycle.self, from: Data(String(json.dropLast()).appending(#","cost":12.5}"#).utf8))
        expect(numeric.costLabel == "$12.50" && numeric.projectedCost == 50, "scalar cost and projection")
        for invalid in ["true", #""12.5""#, "1e400", "NaN", "Infinity"] {
            let data = Data(String(json.dropLast()).appending(#","cost":"# + invalid + "}").utf8)
            expect((try? JSONDecoder().decode(QuotaCycle.self, from: data)) == nil, "reject invalid cost \(invalid)")
        }
        numeric.cost = 0
        expect(numeric.costLabel == "$0.00" && numeric.projectedCost == nil, "zero remains visible without projection")
        for invalid in [-1.0, Double.nan, Double.infinity] {
            numeric.cost = invalid
            expect(numeric.costLabel == nil && numeric.projectedCost == nil, "no invalid cost display")
        }
        numeric.cost = Double.greatestFiniteMagnitude
        numeric.used_pct = 3
        expect(numeric.projectedCost == nil, "overflowing projection hidden")
        let p = QuotaDetailPayload(daily: [], cycles: [legacy], devices: [], missing: [], now: 1000)
        expect(p.currentCycle(for: "claude", endingAt: 1100, at: 1000) != nil, "matching reset")
        expect(p.currentCycle(for: "claude", endingAt: 1160, at: 1000) != nil, "tolerate positive 60-second drift")
        expect(p.currentCycle(for: "claude", endingAt: 1040, at: 1000) != nil, "tolerate negative 60-second drift")
        expect(p.currentCycle(for: "claude", endingAt: 1220, at: 1000) != nil, "tolerate 120-second boundary")
        expect(p.currentCycle(for: "claude", endingAt: 1221, at: 1000) == nil, "reject more than 120-second drift")
        expect(p.currentCycle(for: "claude", endingAt: 1300, at: 1000) == nil, "reject different reset")
        expect(p.currentCycle(for: "claude", endingAt: 1160, at: 1120) == nil, "expired cycle cannot match a live reset within tolerance")
        expect(p.currentCycle(for: "claude", endingAt: nil, at: 1000) == nil, "missing reset")
        expect(p.currentCycle(for: "claude", endingAt: 1100, at: 1100) == nil, "expired reset")
        expect(p.currentCycle(for: "claude", endingAt: 1100, at: 899) == nil, "future cycle")
        expect(p.currentCycle(for: "codex", endingAt: 1100, at: 1000) == nil, "other tool")
        let url = URL(fileURLWithPath: CommandLine.arguments[1])
        let before = try Data(contentsOf: url)
        QuotaDetailRepository.fixtureMode = true
        if CommandLine.arguments.count > 2 && CommandLine.arguments[2] == "no-fixture" {
            QuotaDetailRepository.fixtureURL = nil
            let repository = QuotaDetailRepository.shared
            repository.load()
            repository.load(force: true)
            expect(repository.payload == nil && DataLoader.calls == 0 && !repository.refreshing,
                   "offline shared repository cannot read a synthetic live home cache or collect")
            let after = try Data(contentsOf: url)
            expect(after == before, "no-fixture path never writes")
            print("quota detail checks passed: no-fixture offline isolation")
            return
        }
        QuotaDetailRepository.fixtureURL = url
        let repository = QuotaDetailRepository.shared
        expect(repository.payload != nil, "shared fixture loads")
        repository.load()
        repository.load(force: true)
        expect(DataLoader.calls == 0 && !repository.refreshing, "read-only fixture cannot collect")
        let after = try Data(contentsOf: url)
        expect(after == before, "fixture never overwritten")
        let absent = QuotaDetailRepository(fileURL: url.appendingPathComponent("missing"), readOnly: true)
        absent.load(force: true)
        expect(absent.payload == nil && DataLoader.calls == 0, "absent fixture does not fall back")
        print("quota detail checks passed: optional scalar compatibility, malformed costs, finite display, 120-second live reset matching, read-only repository")
    }
}
