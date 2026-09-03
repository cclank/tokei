import Foundation

/// Which tool cards the user has enabled in settings (matches `@AppStorage("show…")` flags).
struct UsageToolVisibility: Equatable {
    var claude = true
    var codex = true
    var gemini = true
    var grok = true
    var grokBot = true
    var qoder = true
    var qoderwork = true
    var qodercli = true
    var hermes = true
    var zcode = true
    var mimocode = true
    var openclaw = true
    var pi = true
    var primeAgent = true
    var workbuddy = true
    var workbuddyAI = true
    var deepseekHarness = true
    var opencode = true
    var qwencode = true
    var kimicode = true

    static let allVisible = UsageToolVisibility()
}

/// Pure summary builder for copy/share payloads.
enum UsageSummaryBuilder {
    /// One tool's usage for a selected range (mirrors card-level metrics).
    struct Line: Equatable, Identifiable {
        var id: String
        var name: String
        var cost: Double?
        /// Primary total tokens shown as headline (same basis as cards when possible).
        var tokens: Int?
        var sessions: Int?
        var calls: Int?
        var input: Int?
        var output: Int?
        var cacheRead: Int?
        var cacheWrite: Int?
        var reason: Int?
        /// Cache hit percent 0–100 when available.
        var hit: Double?
        var extra: String?

        var isEmpty: Bool {
            let tok = tokens ?? 0
            let ses = sessions ?? 0
            let cal = calls ?? 0
            let cst = cost ?? 0
            let parts = (input ?? 0) + (output ?? 0) + (cacheRead ?? 0) + (cacheWrite ?? 0) + (reason ?? 0)
            return tok <= 0 && ses <= 0 && cal <= 0 && cst <= 0 && parts <= 0
                && (extra == nil || extra?.isEmpty == true)
        }
    }

    struct Totals: Equatable {
        var cost: Double
        var tokens: Int
        var sessions: Int
        var calls: Int
        var tools: Int
        var input: Int
        var output: Int
        var cacheRead: Int
        var cacheWrite: Int
        var reason: Int
    }

    static func totals(for lines: [Line]) -> Totals {
        Totals(
            cost: lines.compactMap(\.cost).reduce(0, +),
            tokens: lines.compactMap(\.tokens).reduce(0, +),
            sessions: lines.compactMap(\.sessions).reduce(0, +),
            calls: lines.compactMap(\.calls).reduce(0, +),
            tools: lines.count,
            input: lines.compactMap(\.input).reduce(0, +),
            output: lines.compactMap(\.output).reduce(0, +),
            cacheRead: lines.compactMap(\.cacheRead).reduce(0, +),
            cacheWrite: lines.compactMap(\.cacheWrite).reduce(0, +),
            reason: lines.compactMap(\.reason).reduce(0, +)
        )
    }

    /// Human-readable plain-text summary for the selected range and visible tools.
    static func text(
        usage: Usage,
        range: RangeKey,
        visibility: UsageToolVisibility,
        updated: String? = nil
    ) -> String {
        let lines = toolLines(usage: usage, range: range, visibility: visibility)
        var out: [String] = ["Tokei 用量 · \(range.label)"]
        if lines.isEmpty {
            out.append("（当前范围无可复制的用量）")
        } else {
            for line in lines {
                out.append(formatLine(line))
            }
            let t = totals(for: lines)
            var totalParts: [String] = []
            if t.cost > 0 { totalParts.append(String(format: "$%.2f", t.cost)) }
            if t.tokens > 0 { totalParts.append("\(Fmt.human(t.tokens)) tok") }
            if t.sessions > 0 { totalParts.append("\(t.sessions) 会话") }
            if t.tools > 0 { totalParts.append("\(t.tools) 工具") }
            if !totalParts.isEmpty {
                out.append("合计  " + totalParts.joined(separator: " · "))
            }
            var detail: [String] = []
            if t.input > 0 { detail.append("输入 \(Fmt.human(t.input))") }
            if t.output > 0 { detail.append("输出 \(Fmt.human(t.output))") }
            if t.cacheRead > 0 { detail.append("缓存读 \(Fmt.human(t.cacheRead))") }
            if t.cacheWrite > 0 { detail.append("缓存写 \(Fmt.human(t.cacheWrite))") }
            if t.reason > 0 { detail.append("推理 \(Fmt.human(t.reason))") }
            if t.calls > 0 { detail.append("调用 \(t.calls)") }
            if !detail.isEmpty {
                out.append(detail.joined(separator: " · "))
            }
        }
        if let line = formatUpdatedLine(updated) {
            out.append(line)
        }
        return out.joined(separator: "\n")
    }

    /// Normalize store timestamps like `"更新 HH:mm:ss"` so we never emit `"更新于 更新 …"`.
    static func formatUpdatedLine(_ updated: String?) -> String? {
        guard let updated else { return nil }
        let trimmed = updated.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        if trimmed == "加载中…" || trimmed.hasPrefix("加载中")
            || trimmed == "加载失败" || trimmed == "预览" {
            return nil
        }
        var body = trimmed
        if body.hasPrefix("更新于") {
            body = String(body.dropFirst(3)).trimmingCharacters(in: .whitespaces)
        } else if body.hasPrefix("更新") {
            body = String(body.dropFirst(2)).trimmingCharacters(in: .whitespaces)
        }
        guard !body.isEmpty else { return nil }
        return "更新于 \(body)"
    }

    static func toolLines(
        usage: Usage,
        range: RangeKey,
        visibility: UsageToolVisibility
    ) -> [Line] {
        var lines: [Line] = []

        if visibility.claude {
            let r = usage.claude.ranges.get(range)
            let line = Line(
                id: "claude", name: "Claude Code", cost: r.cost,
                tokens: r.in + r.out + r.cr + r.cw, sessions: r.sessions, calls: nil,
                input: r.in, output: r.out, cacheRead: r.cr, cacheWrite: r.cw, reason: nil,
                hit: r.hit > 0 ? r.hit : nil, extra: nil
            )
            if !line.isEmpty { lines.append(line) }
        }
        if visibility.codex {
            let r = usage.codex.ranges.get(range)
            let line = Line(
                id: "codex", name: "Codex", cost: r.cost,
                tokens: r.in + r.cached + r.out, sessions: r.sessions, calls: nil,
                input: r.in, output: r.out, cacheRead: r.cached, cacheWrite: nil,
                reason: r.reason > 0 ? r.reason : nil,
                hit: r.hit > 0 ? r.hit : nil, extra: nil
            )
            if !line.isEmpty { lines.append(line) }
        }
        if visibility.gemini {
            let r = usage.gemini.ranges.get(range)
            let line = Line(
                id: "gemini", name: "Gemini", cost: r.cost,
                tokens: r.in + r.cached + r.out + r.thoughts, sessions: r.sessions, calls: nil,
                input: r.in, output: r.out, cacheRead: r.cached, cacheWrite: nil,
                reason: r.thoughts > 0 ? r.thoughts : nil,
                hit: r.hit > 0 ? r.hit : nil, extra: nil
            )
            if !line.isEmpty { lines.append(line) }
        }
        if visibility.grok {
            let r = usage.grok.ranges.get(range)
            let tokens = r.usage_available ? (r.in + r.out + r.cr + r.reason) : r.tokens
            let sessions = max(r.sessions, r.usage_sessions)
            let line = Line(
                id: "grok", name: "Grok",
                cost: r.cost > 0 ? r.cost : nil,
                tokens: tokens, sessions: sessions,
                calls: r.usage_calls > 0 ? r.usage_calls : nil,
                input: r.usage_available ? r.in : nil,
                output: r.usage_available ? r.out : nil,
                cacheRead: r.usage_available ? r.cr : nil,
                cacheWrite: nil,
                reason: r.usage_available && r.reason > 0 ? r.reason : nil,
                hit: r.usage_available && r.hit > 0 ? r.hit : nil,
                extra: nil
            )
            if !line.isEmpty { lines.append(line) }
        }
        if visibility.grokBot {
            let r = usage.grokBot.ranges.get(range)
            let accountUsage = usage.grokBot.quota.usage?.ranges.get(range)
                ?? TokenUsageRange()
            let line = Line(
                id: "grok-bot", name: "Grok Bot",
                cost: accountUsage.cost > 0 ? accountUsage.cost : nil,
                tokens: accountUsage.totalTokens > 0 ? accountUsage.totalTokens : nil,
                sessions: r.sessions,
                calls: accountUsage.requests > 0
                    ? accountUsage.requests
                    : (r.calls > 0 ? r.calls : nil),
                input: accountUsage.hasComponents ? accountUsage.in : nil,
                output: accountUsage.hasComponents ? accountUsage.out : nil,
                cacheRead: accountUsage.cr > 0 ? accountUsage.cr : nil,
                cacheWrite: accountUsage.cw > 0 ? accountUsage.cw : nil,
                reason: nil, hit: nil,
                extra: r.turns > 0 ? "\(r.turns) 条消息" : nil
            )
            if !line.isEmpty { lines.append(line) }
        }
        if visibility.qoder {
            let r = usage.qoder.ranges.get(range)
            let line = Line(
                id: "qoder", name: "Qoder Desktop", cost: nil,
                tokens: r.in + r.cached + r.out, sessions: r.sessions, calls: r.calls,
                input: r.in, output: r.out, cacheRead: r.cached, cacheWrite: nil,
                reason: nil, hit: r.ctx > 0 ? r.ctx : nil, extra: nil
            )
            if !line.isEmpty { lines.append(line) }
        }
        if visibility.qoderwork {
            let r = usage.qoderwork.ranges.get(range)
            let line = Line(
                id: "qoderwork", name: "QoderWork", cost: nil,
                tokens: r.in + r.out, sessions: r.sessions, calls: r.calls,
                input: r.in, output: r.out, cacheRead: nil, cacheWrite: nil,
                reason: nil, hit: nil, extra: nil
            )
            if !line.isEmpty { lines.append(line) }
        }
        if visibility.qodercli {
            let r = usage.qodercli.ranges.get(range)
            let line = Line(
                id: "qodercli", name: "Qoder CLI", cost: nil,
                tokens: nil, sessions: r.sessions, calls: r.calls,
                input: nil, output: nil, cacheRead: nil, cacheWrite: nil,
                reason: nil, hit: nil, extra: nil
            )
            if !line.isEmpty { lines.append(line) }
        }
        if visibility.hermes {
            let r = usage.hermes.ranges.get(range)
            let line = Line(
                id: "hermes", name: "Hermes", cost: r.cost,
                tokens: r.in + r.out + r.cr + r.cw + r.reason, sessions: r.sessions, calls: nil,
                input: r.in, output: r.out, cacheRead: r.cr, cacheWrite: r.cw,
                reason: r.reason > 0 ? r.reason : nil,
                hit: r.hit > 0 ? r.hit : nil, extra: nil
            )
            if !line.isEmpty { lines.append(line) }
        }
        if visibility.zcode {
            appendTokenTool(&lines, id: "zcode", name: "ZCode", range: usage.zcode.ranges.get(range))
        }
        if visibility.mimocode {
            appendTokenTool(&lines, id: "mimocode", name: "MiMoCode", range: usage.mimocode.ranges.get(range))
        }
        if visibility.openclaw {
            let r = usage.openclaw.ranges.get(range)
            let line = Line(
                id: "openclaw", name: "OpenClaw", cost: r.cost,
                tokens: r.in + r.out + r.cr + r.cw + r.reason, sessions: r.sessions,
                calls: r.tasks > 0 ? r.tasks : nil,
                input: r.in, output: r.out, cacheRead: r.cr, cacheWrite: r.cw,
                reason: r.reason > 0 ? r.reason : nil,
                hit: r.hit > 0 ? r.hit : nil, extra: nil
            )
            if !line.isEmpty { lines.append(line) }
        }
        if visibility.pi {
            appendTokenTool(&lines, id: "pi", name: "Pi", range: usage.pi.ranges.get(range))
        }
        if visibility.primeAgent {
            appendTokenTool(&lines, id: "prime_agent", name: "Prime Agent",
                            range: usage.prime_agent.ranges.get(range))
        }
        if visibility.workbuddy {
            appendTokenTool(&lines, id: "workbuddy", name: "WorkBuddy", range: usage.workbuddy.ranges.get(range))
        }
        if visibility.workbuddyAI {
            appendTokenTool(&lines, id: "workbuddy-ai", name: "WorkBuddy Intl.",
                            range: usage.workbuddyAI.ranges.get(range))
        }
        if visibility.deepseekHarness {
            appendTokenTool(&lines, id: "deepseek_harness", name: "DeepSeek Harness",
                            range: usage.deepseekHarness.ranges.get(range))
        }
        if visibility.opencode {
            appendTokenTool(&lines, id: "opencode", name: "OpenCode", range: usage.opencode.ranges.get(range))
        }
        if visibility.qwencode {
            appendTokenTool(&lines, id: "qwencode", name: "Qwen Code", range: usage.qwencode.ranges.get(range))
        }
        if visibility.kimicode {
            // 卡片刻意不显示 Kimi 的成本,分享图里也不能凭空冒出来一个数。
            appendTokenTool(&lines, id: "kimicode", name: "Kimi Code",
                            range: usage.kimicode.ranges.get(range), includesCost: false)
        }
        return lines
    }

    static func line(
        forToolID id: String,
        usage: Usage,
        range: RangeKey,
        visibility: UsageToolVisibility
    ) -> Line? {
        toolLines(usage: usage, range: range, visibility: visibility)
            .first { $0.id == id }
    }

    private static func appendTokenTool(
        _ lines: inout [Line], id: String, name: String, range r: TokenUsageRange,
        includesCost: Bool = true
    ) {
        let line = Line(
            id: id, name: name, cost: includesCost ? r.cost : nil,
            tokens: r.in + r.out + r.cr + r.cw + r.reason, sessions: r.sessions, calls: nil,
            input: r.in, output: r.out, cacheRead: r.cr, cacheWrite: r.cw,
            reason: r.reason > 0 ? r.reason : nil,
            hit: r.hit > 0 ? r.hit : nil, extra: nil
        )
        if !line.isEmpty { lines.append(line) }
    }

    private static func formatLine(_ line: Line) -> String {
        var parts: [String] = []
        if let cost = line.cost, cost > 0 {
            parts.append(String(format: "$%.2f", cost))
        }
        if let tokens = line.tokens, tokens > 0 {
            parts.append("\(Fmt.human(tokens)) tok")
        }
        if let sessions = line.sessions, sessions > 0 {
            parts.append("\(sessions) 会话")
        }
        if let calls = line.calls, calls > 0 {
            parts.append("\(calls) 次调用")
        }
        if let extra = line.extra, !extra.isEmpty {
            parts.append(extra)
        }
        if parts.isEmpty {
            return line.name
        }
        return "\(line.name)  " + parts.joined(separator: " · ")
    }
}
