import Foundation

enum UsageCardOrdering {
    /// Equal totals retain the input order, including quota-only cards.
    static func sorted<T>(_ cards: [T], tokens: (T) -> Int) -> [T] {
        let ranked: [(index: Int, card: T, total: Int)] = cards.enumerated().map { index, card in
            (index, card, max(0, tokens(card)))
        }
        let ordered = ranked.sorted { lhs, rhs in
            lhs.total == rhs.total ? lhs.index < rhs.index : lhs.total > rhs.total
        }
        return ordered.map { $0.card }
    }
    /// Use the selected display snapshot and the same token accounting as each card.
    /// Quota percentages, credits and context-window sizes are not token usage.
    static func tokens(for id: String, usage u: Usage, range: RangeKey) -> Int {
        switch id {
        case "claude": return u.claude.ranges.get(range).tokens
        case "codex":
            return u.codex.ranges.get(range).tokens + (u.codex.reserveRanges?.get(range).tokens ?? 0)
        case "gemini": return u.gemini.ranges.get(range).totalTokens
        case "cursor": return u.cursor.usage?.ranges.get(range).totalTokens ?? 0
        case "zai": return u.zai.usage?.ranges.get(range).totalTokens ?? 0
        case "grok":
            let r = u.grok.ranges.get(range)
            return r.usage_available ? r.tokens : 0
        case "grok-bot": return u.grokBot.quota.usage?.ranges.get(range).totalTokens ?? 0
        case "qoder":
            let r = u.qoder.ranges.get(range)
            return r.in + r.cached + r.out
        case "qoderwork": return u.qoderwork.ranges.get(range).totalTokens
        case "qodercli": return u.qodercli.ranges.get(range).totalTokens
        case "qodercli_cn": return u.qodercliCN.ranges.get(range).totalTokens
        case "hermes":
            let r = u.hermes.ranges.get(range)
            return r.in + r.out + r.cr + r.cw + r.reason
        case "openclaw":
            let r = u.openclaw.ranges.get(range)
            return r.in + r.out + r.cr + r.cw
        case "devin": return u.devin.ranges.get(range).totalTokens
        case "minimax": return u.minimax.ranges.get(range).totalTokens
        case "copilot":
            let r = u.copilot.ranges.get(range)
            return r.out + r.reason
        case "musecode":
            let r = u.musecode.ranges.get(range)
            return r.in + r.out + r.cr + r.cw
        default: break
        }
        let r: TokenUsageRange
        switch id {
        case "zcode": r = u.zcode.ranges.get(range)
        case "mimocode": r = u.mimocode.ranges.get(range)
        case "pi": r = u.pi.ranges.get(range)
        case "prime_agent": r = u.prime_agent.ranges.get(range)
        case "workbuddy": r = u.workbuddy.ranges.get(range)
        case "workbuddy-ai": r = u.workbuddyAI.ranges.get(range)
        case "codebuddy": r = u.codebuddy.ranges.get(range)
        case "deepseek_harness": r = u.deepseekHarness.ranges.get(range)
        case "opencode": r = u.opencode.ranges.get(range)
        case "qwencode": r = u.qwencode.ranges.get(range)
        case "kimicode": r = u.kimicode.ranges.get(range)
        case "cmdcode": r = u.cmdcode.ranges.get(range)
        default: return 0
        }
        return r.in + r.out + r.cr + r.cw + r.reason
    }
}
