import Foundation

/// Observed output growth over wall time, so concurrent requests add together.
/// Only fresh local collector results enter this sampler; cached and peer data do not.
struct LocalOutputThroughput {
    static let window: TimeInterval = 60

    struct Reading {
        let tokensPerSecond: Double
        let seconds: TimeInterval
    }

    private struct Sample {
        let start: Date
        let end: Date
        let tokens: Double
    }

    private var previous: (at: Date, counters: [String: Int])?
    private var startedAt: Date?
    private var samples: [Sample] = []

    mutating func observe(_ counters: [String: Int], at now: Date = Date()) {
        defer { previous = (now, counters) }
        guard let previous, now > previous.at,
              now.timeIntervalSince(previous.at) <= Self.window,
              counters.keys.count == previous.counters.keys.count,
              counters.allSatisfy({ key, value in
                  value >= 0 && previous.counters[key].map { value >= $0 } == true
              }) else {
            samples.removeAll()
            startedAt = now
            return
        }
        let tokens = counters.reduce(0.0) { sum, entry in
            sum + Double(entry.value) - Double(previous.counters[entry.key]!)
        }
        samples.append(Sample(start: previous.at, end: now, tokens: tokens))
        samples.removeAll { $0.end <= now.addingTimeInterval(-Self.window) }
    }

    func reading(at now: Date = Date()) -> Reading? {
        guard let previous, let startedAt, !samples.isEmpty,
              now >= previous.at, now.timeIntervalSince(previous.at) < Self.window else { return nil }
        let seconds = min(Self.window, now.timeIntervalSince(startedAt))
        guard seconds >= 1 else { return nil }
        let start = now.addingTimeInterval(-seconds)
        // A collector snapshot has no per-token timestamps. Interpolate the boundary
        // interval, and include idle wall time rather than summing request durations.
        let tokens = samples.reduce(0.0) { sum, sample in
            let overlap = max(0, min(now, sample.end).timeIntervalSince(max(start, sample.start)))
            return sum + sample.tokens * overlap / sample.end.timeIntervalSince(sample.start)
        }
        return Reading(tokensPerSecond: tokens / seconds, seconds: seconds)
    }
}

extension Usage {
    /// Explicit local sources: provider/account totals can include other machines.
    /// Codex, OpenClaw and Muse already include reasoning in their output counters.
    var localOutputCounters: [String: Int] {
        let gemini = gemini.ranges.get(.all)
        let grok = grok.ranges.get(.all)
        let hermes = hermes.ranges.get(.all)
        var counters: [String: Int] = [
            "claude": claude.ranges.get(.all).out,
            "codex": codex.ranges.get(.all).out,
            "codex_reserve": codex.reserveRanges?.get(.all).out ?? 0,
            "gemini": gemini.out + gemini.thoughts,
            "grok": grok.out + grok.reason,
            "qoder": qoder.ranges.get(.all).out,
            "qoderwork": qoderwork.ranges.get(.all).out,
            "qodercli": qodercli.ranges.get(.all).out,
            "qodercli_cn": qodercliCN.ranges.get(.all).out,
            "hermes": hermes.out + hermes.reason,
            "openclaw": openclaw.ranges.get(.all).out,
            "musecode": musecode.ranges.get(.all).out,
        ]
        let tokenTools: [(String, TokenUsageRanges)] = [
            ("zcode", zcode.ranges), ("mimocode", mimocode.ranges),
            ("pi", pi.ranges), ("prime_agent", prime_agent.ranges),
            ("workbuddy", workbuddy.ranges), ("workbuddy_ai", workbuddyAI.ranges),
            ("codebuddy", codebuddy.ranges), ("deepseek_harness", deepseekHarness.ranges),
            ("opencode", opencode.ranges), ("qwencode", qwencode.ranges),
            ("kimicode", kimicode.ranges), ("cmdcode", cmdcode.ranges),
            ("devin", devin.ranges), ("minimax", minimax.ranges),
        ]
        for (id, ranges) in tokenTools {
            let range = ranges.get(.all)
            counters[id] = range.out + range.reason
        }
        return counters
    }
}
