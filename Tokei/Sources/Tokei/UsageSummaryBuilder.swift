import Foundation

/// Which tool cards the user has enabled in settings (matches `@AppStorage("show…")` flags).
struct UsageToolVisibility: Equatable {
    var claude = true
    var codex = true
    var gemini = true
    var cursor = true
    var zed = true
    var sub2api = true
    var zai = true
    var grok = true
    var grokBot = true
    var doubaoWork = true
    var qoder = true
    var qoderwork = true
    var qodercli = true
    var qodercliCN = true
    var hermes = true
    var zcode = true
    var mimocode = true
    var openclaw = true
    var pi = true
    var primeAgent = true
    var workbuddy = true
    var workbuddyAI = true
    var codebuddy = true
    var deepseekHarness = true
    var opencode = true
    var qwencode = true
    var kimicode = true
    var musecode = true
    var cmdcode = true
    var copilot = true
    var devin = true
    var minimax = true

    static let allVisible = UsageToolVisibility()
}

/// Pure summary builder for copy/share payloads.
enum UsageSummaryBuilder {
    /// One tool's usage for a selected range (mirrors card-level metrics).
    struct Line: Equatable, Identifiable {
        var id: String
        var name: String
        var cost_cny: Double? = nil
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
        /// Activity-only headline, including a valid zero for the selected period.
        var activityLabel: String? = nil
        var sourceCaption: String? = nil

        var isEmpty: Bool {
            let tok = tokens ?? 0
            let ses = sessions ?? 0
            let cal = calls ?? 0
            let cst = cost ?? 0
            let parts = (input ?? 0) + (output ?? 0) + (cacheRead ?? 0) + (cacheWrite ?? 0) + (reason ?? 0)
            return tok <= 0 && ses <= 0 && cal <= 0 && cst <= 0 && parts <= 0
                && (extra == nil || extra?.isEmpty == true)
                && activityLabel == nil
        }
    }

    struct Totals: Equatable {
        var cost_cny: Double = 0
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
        // Provider account aggregates may overlap the local tool records.
        let lines = lines.filter { $0.id != "cursor" && $0.id != "zai" }
        return Totals(
            cost_cny: lines.compactMap(\.cost_cny).reduce(0, +),
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
        var out: [String] = [L("Tokei 用量 · %@", range.label)]
        if lines.isEmpty {
            out.append(L("（当前范围无可复制的用量）"))
        } else {
            for line in lines {
                out.append(formatLine(line))
            }
            let t = totals(for: lines)
            var totalParts: [String] = []
            if t.cost > 0 || t.cost_cny > 0 { totalParts.append(nativeMoney(t.cost, t.cost_cny)) }
            if t.tokens > 0 { totalParts.append("\(Fmt.human(t.tokens)) tok") }
            if t.sessions > 0 { totalParts.append(L("%@ 会话", t.sessions)) }
            if t.tools > 0 { totalParts.append(L("%@ 工具", t.tools)) }
            if !totalParts.isEmpty {
                out.append(L("合计  %@", totalParts.joined(separator: " · ")))
            }
            var detail: [String] = []
            if t.input > 0 { detail.append(L("输入 %@", Fmt.human(t.input))) }
            if t.output > 0 { detail.append(L("输出 %@", Fmt.human(t.output))) }
            if t.cacheRead > 0 { detail.append(L("缓存读 %@", Fmt.human(t.cacheRead))) }
            if t.cacheWrite > 0 { detail.append(L("缓存写 %@", Fmt.human(t.cacheWrite))) }
            if t.reason > 0 { detail.append(L("推理 %@", Fmt.human(t.reason))) }
            if t.calls > 0 { detail.append(L("调用 %@", t.calls)) }
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
        // 状态文字是按当前语言写进去的，这里也按当前语言认。
        if [L("加载失败"), L("预览")].contains(trimmed) || trimmed.hasPrefix(L("加载中")) {
            return nil
        }
        var body = trimmed
        for template in ["更新于 %@", "更新 %@"] { // l10n-ignore
            let prefix = L(template, "").trimmingCharacters(in: .whitespaces)
            if !prefix.isEmpty, body.hasPrefix(prefix) {
                body = String(body.dropFirst(prefix.count)).trimmingCharacters(in: .whitespaces)
                break
            }
        }
        guard !body.isEmpty else { return nil }
        return L("更新于 %@", body)
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
                tokens: r.tokens, sessions: r.sessions, calls: nil,
                input: r.in, output: r.out, cacheRead: r.cached, cacheWrite: nil,
                reason: r.reason > 0 ? r.reason : nil,
                hit: r.hit > 0 ? r.hit : nil, extra: nil
            )
            if !line.isEmpty { lines.append(line) }
            if let r = usage.codex.reserveRanges?.get(range) {
                let reserve = Line(
                    id: "codex_reserve", name: "Luna Reserve", cost: r.cost,
                    tokens: r.tokens, sessions: r.sessions, calls: nil,
                    input: r.in, output: r.out, cacheRead: r.cached, cacheWrite: nil,
                    reason: r.reason > 0 ? r.reason : nil,
                    hit: r.hit > 0 ? r.hit : nil, extra: nil
                )
                if !reserve.isEmpty { lines.append(reserve) }
            }
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
        if visibility.cursor, let r = usage.cursor.usage?.ranges.get(range) {
            let total = r.totalTokens
            let line = Line(
                id: "cursor", name: "Cursor",
                cost_cny: (r.cost_cny ?? 0) > 0 ? r.cost_cny : nil,
                cost: r.cost > 0 ? r.cost : nil,
                tokens: total > 0 ? total : nil,
                sessions: r.sessions > 0 ? r.sessions : nil,
                calls: r.requests > 0 ? r.requests : nil,
                input: r.hasComponents ? r.in : nil,
                output: r.hasComponents ? r.out : nil,
                cacheRead: r.cr > 0 ? r.cr : nil,
                cacheWrite: r.cw > 0 ? r.cw : nil,
                reason: r.reason > 0 ? r.reason : nil,
                hit: r.hit > 0 ? r.hit : nil,
                extra: nil
            )
            if !line.isEmpty { lines.append(line) }
        }
        if visibility.zai, let r = usage.zai.usage?.ranges.get(range) {
            let total = r.totalTokens
            let line = Line(
                id: "zai", name: "z.ai",
                cost_cny: (r.cost_cny ?? 0) > 0 ? r.cost_cny : nil,
                cost: r.cost > 0 ? r.cost : nil,
                tokens: total > 0 ? total : nil,
                sessions: r.sessions > 0 ? r.sessions : nil,
                calls: r.requests > 0 ? r.requests : nil,
                input: r.hasComponents ? r.in : nil,
                output: r.hasComponents ? r.out : nil,
                cacheRead: r.cr > 0 ? r.cr : nil,
                cacheWrite: r.cw > 0 ? r.cw : nil,
                reason: r.reason > 0 ? r.reason : nil,
                hit: r.hit > 0 ? r.hit : nil,
                extra: nil
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
            let total = accountUsage.totalTokens
            let line = Line(
                id: "grok-bot", name: "Grok Bot",
                cost_cny: (accountUsage.cost_cny ?? 0) > 0 ? accountUsage.cost_cny : nil,
                cost: accountUsage.cost > 0 ? accountUsage.cost : nil,
                tokens: total > 0 ? total : nil,
                sessions: r.sessions > 0 ? r.sessions : (accountUsage.sessions > 0 ? accountUsage.sessions : nil),
                calls: accountUsage.requests > 0
                    ? accountUsage.requests
                    : (r.calls > 0 ? r.calls : (r.turns > 0 ? r.turns : nil)),
                input: accountUsage.hasComponents ? accountUsage.in : nil,
                output: accountUsage.hasComponents ? accountUsage.out : nil,
                cacheRead: accountUsage.cr > 0 ? accountUsage.cr : nil,
                cacheWrite: accountUsage.cw > 0 ? accountUsage.cw : nil,
                reason: accountUsage.reason > 0 ? accountUsage.reason : nil,
                hit: accountUsage.hit > 0 ? accountUsage.hit : nil,
                extra: r.turns > 0 ? L("%@ 条消息", r.turns) : nil
            )
            if !line.isEmpty { lines.append(line) }
        }
        if visibility.doubaoWork && usage.doubaoWork.hasActivity {
            lines.append(Line(
                id: "doubaowork", name: "Doubao Work", cost: nil, tokens: nil,
                sessions: usage.doubaoWork.ranges.get(range).sessions,
                calls: nil, input: nil, output: nil, cacheRead: nil, cacheWrite: nil,
                reason: nil, hit: nil, extra: usage.doubaoWork.quota?.summary,
                activityLabel: DoubaoWorkStat.activityLabel(for: range),
                sourceCaption: usage.doubaoWork.displaySourceCaption
            ))
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
            appendQoderCli(&lines, id: "qodercli", name: "Qoder CLI",
                           range: usage.qodercli.ranges.get(range))
        }
        if visibility.qodercliCN {
            appendQoderCli(&lines, id: "qodercli_cn", name: "Qoder CN",
                           range: usage.qodercliCN.ranges.get(range))
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
        if visibility.codebuddy {
            appendTokenTool(&lines, id: "codebuddy", name: "CodeBuddy",
                            range: usage.codebuddy.ranges.get(range),
                            includesCost: false, includesCredits: true)
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
        if visibility.musecode {
            appendTokenTool(&lines, id: "musecode", name: "Muse Code",
                            range: usage.musecode.ranges.get(range), reasonIncludedInOutput: true)
        }
        if visibility.cmdcode {
            appendTokenTool(&lines, id: "cmdcode", name: "Command Code",
                            range: usage.cmdcode.ranges.get(range))
        }
        if visibility.copilot {
            appendTokenTool(&lines, id: "copilot", name: "GitHub Copilot",
                            range: usage.copilot.ranges.get(range), includesCredits: true)
        }
        if visibility.devin {
            appendTokenTool(&lines, id: "devin", name: "Devin",
                            range: usage.devin.ranges.get(range))
        }
        if visibility.minimax {
            appendTokenTool(&lines, id: "minimax", name: "MiniMax Code",
                            range: usage.minimax.ranges.get(range))
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

    private static func appendQoderCli(_ lines: inout [Line], id: String, name: String,
                                       range r: QoderRange) {
        let line = Line(
            id: id, name: name, cost: nil,
            tokens: r.totalTokens, sessions: r.sessions, calls: r.calls,
            input: r.in, output: r.out, cacheRead: r.cr, cacheWrite: r.cw,
            reason: nil, hit: r.hit > 0 ? r.hit : nil,
            extra: r.credits > 0 ? "\(Fmt.credits(r.credits)) Credits" : nil
        )
        if !line.isEmpty { lines.append(line) }
    }

    private static func appendTokenTool(
        _ lines: inout [Line], id: String, name: String, range r: TokenUsageRange,
        includesCost: Bool = true, includesCredits: Bool = false,
        reasonIncludedInOutput: Bool = false
    ) {
        let outputOnly = id == "copilot"
        let includesCost = includesCost && !outputOnly
        let total = outputOnly ? r.out + r.reason : r.in + r.out + r.cr + r.cw + (reasonIncludedInOutput ? 0 : r.reason)
        if outputOnly && total == 0 && r.sessions == 0 && r.credits == 0 { return }
        let extra = outputOnly ? L("仅输出") + (r.credits > 0 ? " · \(Fmt.credits(r.credits)) Premium Requests" : "") : includesCredits && r.credits > 0
            ? "\(Fmt.credits(r.credits)) Credits" : nil
        let line = Line(
            id: id, name: name, cost_cny: includesCost ? r.cost_cny : nil,
            cost: includesCost ? r.cost : nil,
            tokens: total, sessions: r.sessions, calls: nil,
            input: outputOnly ? nil : r.in, output: r.out, cacheRead: outputOnly ? nil : r.cr, cacheWrite: outputOnly ? nil : r.cw,
            reason: r.reason > 0 ? r.reason : nil,
            hit: !outputOnly && r.hit > 0 ? r.hit : nil, extra: extra
        )
        if !line.isEmpty { lines.append(line) }
    }

    private static func formatLine(_ line: Line) -> String {
        var parts: [String] = []
        if let label = line.activityLabel {
            parts.append("\(Fmt.human(line.sessions ?? 0)) \(label)")
            if let caption = line.sourceCaption { parts.append(caption) }
            return "\(line.name)  " + parts.joined(separator: " · ")
        }
        if (line.cost ?? 0) > 0 || (line.cost_cny ?? 0) > 0 {
            parts.append(nativeMoney(line.cost ?? 0, line.cost_cny))
        }
        if let tokens = line.tokens, tokens > 0 {
            parts.append("\(Fmt.human(tokens)) tok")
        }
        if let sessions = line.sessions, sessions > 0 {
            parts.append(L("%@ 会话", sessions))
        }
        if let calls = line.calls, calls > 0 {
            parts.append(L("%@ 次调用", calls))
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
