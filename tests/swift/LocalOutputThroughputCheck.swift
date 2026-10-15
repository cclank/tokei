import Foundation

private func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() { throw NSError(domain: message, code: 1) }
}

@main
struct LocalOutputThroughputCheck {
    static func main() throws {
        let t0 = Date(timeIntervalSince1970: 1_000)
        func at(_ seconds: Double) -> Date { t0.addingTimeInterval(seconds) }
        var sampler = LocalOutputThroughput()
        sampler.observe(["codex": 10_000, "claude": 20_000], at: at(0))
        try expect(sampler.reading(at: at(0)) == nil, "startup history is only a baseline")
        sampler.observe(["codex": 10_500, "claude": 20_500], at: at(10))
        try expect(sampler.reading(at: at(10))?.tokensPerSecond == 100, "two concurrent 50 tok/s tasks add to 100")
        sampler.observe(["codex": 11_000, "claude": 20_500], at: at(20))
        try expect(sampler.reading(at: at(20))?.tokensPerSecond == 75, "one idle task does not inflate the denominator")
        sampler.observe(["codex": 11_000, "claude": 20_500], at: at(60))
        try expect(sampler.reading(at: at(60))?.tokensPerSecond == 25, "idle wall time remains in the window")
        sampler.observe(["codex": 11_000, "claude": 20_500], at: at(65))
        try expect(abs(sampler.reading(at: at(65))!.tokensPerSecond - 1000.0 / 60) < 0.001, "partial oldest interval is clipped")
        sampler.observe(["codex": 11_000, "claude": 20_500], at: at(80))
        try expect(sampler.reading(at: at(80))?.tokensPerSecond == 0, "old output ages out")
        try expect(sampler.reading(at: at(140)) == nil, "stale sampler does not keep showing a live rate")
        sampler.observe(["codex": 30_000, "claude": 20_500], at: at(150))
        try expect(sampler.reading(at: at(150)) == nil, "long gaps rebaseline instead of reporting a wake spike")
        sampler.observe(["codex": 30_100, "claude": 20_500], at: at(160))
        try expect(sampler.reading(at: at(160))?.tokensPerSecond == 10, "sampling resumes after a gap")
        sampler.observe(["codex": 0, "claude": 40_500], at: at(170))
        try expect(sampler.reading(at: at(170)) == nil, "a source reset cannot be masked by another source's growth")
        sampler.observe(["codex": 100, "claude": 40_500], at: at(180))
        sampler.observe(["codex": 100, "claude": 40_500], at: at(180))
        try expect(sampler.reading(at: at(180)) == nil, "duplicate timestamps reset without division by zero")
        sampler.observe(["codex": 200, "claude": 40_500], at: at(179))
        try expect(sampler.reading(at: at(179)) == nil, "backward clocks rebaseline")
        sampler.observe(["codex": 300], at: at(190))
        try expect(sampler.reading(at: at(190)) == nil, "changed source coverage rebaselines")

        let usage = try Usage.decode(from: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1])))
        let counters = usage.localOutputCounters
        try expect(counters["codex"] == 100 && counters["codex_reserve"] == 100,
                   "reserve counted separately; Codex reasoning not counted twice")
        try expect(counters["openclaw"] == 100 && counters["musecode"] == 100, "inclusive reasoning is not doubled")
        try expect(counters["gemini"] == 120 && counters["opencode"] == 130 && counters["deepseek_harness"] == 130,
                   "separate reasoning contributes once")
        try expect(counters.count == 26, "all 25 local tools plus reserve are included")
        try expect(counters["cursor"] == nil && counters["grok_bot"] == nil && counters["sub2api"] == nil,
                   "account-wide provider totals excluded")
        print("local output throughput checks passed")
    }
}
