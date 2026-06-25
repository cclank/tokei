import SwiftUI
import AppKit

struct PanelView: View {
    @ObservedObject var store: Store
    var scrollable = true
    @State private var sel: RangeKey = .today
    @State private var claudeModelsOpen = false
    @State private var geminiModelsOpen = false
    @State private var piModelsOpen = false
    @State private var openCodeModelsOpen = false
    @State private var mode: PanelMode = .cards
    @State private var trailProjects: [TrailProject]?
    enum PanelMode { case cards, dashboard, projects, settings }
    private struct ToolCardItem: Identifiable {
        let id: String
        let name: String
        let visible: Bool
        let active: Bool
        let tint: Color
        let content: AnyView
    }
    @AppStorage("showClaude") private var showClaude = true
    @AppStorage("showCodex") private var showCodex = true
    @AppStorage("showGemini") private var showGemini = true
    @AppStorage("showGrok") private var showGrok = true
    @AppStorage("showQoderIde") private var showQoder = false
    @AppStorage("showQoderWork") private var showQoderWork = true
    @AppStorage("showHermes") private var showHermes = true
    @AppStorage("showOpenClaw") private var showOpenClaw = true
    @AppStorage("showPi") private var showPi = true
    @AppStorage("showOpenCode") private var showOpenCode = true

    private var visibleCount: Int {
        [showClaude, showCodex, showGemini, showGrok, showQoder, showQoderWork, showHermes, showOpenClaw, showPi, showOpenCode].filter { $0 }.count
    }
    private var useWide: Bool { visibleCount > 2 }
    private var panelWidth: CGFloat { useWide ? 640 : Theme.panelWidth }

    private var maxPanelHeight: CGFloat {
        (NSScreen.main?.visibleFrame.height ?? 900) - 40
    }

    private var debugSummary: String {
        guard !debugOutput.isEmpty else { return "" }
        let lines = debugOutput.components(separatedBy: .newlines)
        let exit = lines.first(where: { $0.hasPrefix("exit:") }) ?? ""
        let json = lines.first(where: { $0.hasPrefix("json:") }) ?? ""
        let errors = lines.first(where: { $0.hasPrefix("errors:") }) ?? ""
        return [exit, json, errors].filter { !$0.isEmpty }.joined(separator: " · ")
    }

    var body: some View {
        let w = mode == .settings ? max(panelWidth, 560) : (mode == .cards ? panelWidth : max(panelWidth, 420))
        if scrollable {
            ScrollView(.vertical, showsIndicators: false) { panelContent }
                .frame(width: w)
                .frame(maxHeight: maxPanelHeight)
                .background(Theme.bg)
                .background(VisualEffect())
                .environment(\.colorScheme, .dark)
        } else {
            panelContent
                .frame(width: w, alignment: .top)
                .background(Theme.bg)
                .background(VisualEffect())
                .environment(\.colorScheme, .dark)
        }
    }

    private var panelContent: some View {
        VStack(alignment: .leading, spacing: 13) {
            header
            if mode == .dashboard {
                DashboardView()
            } else if mode == .projects {
                ProjectTrailView(cached: $trailProjects)
            } else if mode == .settings {
                settingsContent
            } else if let u = store.usage {
                let cards = toolCards(for: u, localUsage: store.localUsage)
                SegmentedTabs(sel: $sel)
                toolCardsLayout(cards.filter { $0.visible && $0.active })
                inactiveToolsLine(cards)
            } else {
                HStack(spacing: 8) {
                    Spacer()
                    if let error = store.loadError {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .foregroundStyle(Theme.claude)
                        Text(error)
                            .font(.system(size: 12, weight: .medium))
                            .foregroundStyle(Theme.tSecondary)
                    } else {
                        ProgressView().controlSize(.small)
                    }
                    Spacer()
                }
                .frame(height: 90)
            }
            footer
        }
        .padding(Theme.outerPad)
    }

    // MARK: - 品牌头部
    // 节日皮肤:特定日期 logo 旁挂个小角标。
    static func festiveEmoji() -> String? {
        let c = Calendar.current.dateComponents([.month, .day], from: Date())
        switch (c.month ?? 0, c.day ?? 0) {
        case (12, 24), (12, 25): return "🎄"
        case (1, 1):             return "🎉"
        case (10, 31):           return "🎃"
        case (2, 14):            return "❤️"
        case (2, 16), (2, 17), (2, 18): return "🧧"   // 2026 春节
        default:                 return nil
        }
    }

    var header: some View {
        HStack(spacing: 9) {
            Button {
                if mode != .cards { withAnimation(.easeInOut(duration: 0.35)) { mode = .cards } }
            } label: {
                HStack(spacing: 9) {
                    Image(systemName: "timer")
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(Theme.brand)
                        .overlay(alignment: .topTrailing) {
                            if let e = Self.festiveEmoji() {
                                Text(e).font(.system(size: 11)).offset(x: 7, y: -7)
                            }
                        }
                    VStack(alignment: .leading, spacing: 0) {
                        Text("Tokei")
                            .font(.system(size: 15, weight: .bold, design: .rounded))
                            .tracking(0.5)
                        Text("知度 · AI 用量")
                            .font(.system(size: 9))
                            .foregroundStyle(Theme.tTertiary)
                    }
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .tip("主页")
            updatePill
            Spacer()
            Text(store.lastUpdated)
                .font(.system(size: 9.5, design: .monospaced))
                .foregroundStyle(Theme.tTertiary)
            Button {
                withAnimation(.easeInOut(duration: 0.35)) { mode = mode == .projects ? .cards : .projects }
            } label: {
                Image(systemName: "folder")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(mode == .projects ? Theme.claude : Theme.tTertiary)
                    .frame(width: 24, height: 24)
                    .background(Circle().fill(Color.primary.opacity(0.06)))
                    .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .tip("项目足迹")
            Button {
                withAnimation(.easeInOut(duration: 0.35)) { mode = mode == .dashboard ? .cards : .dashboard }
            } label: {
                Image(systemName: "chart.bar")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(mode == .dashboard ? Theme.claude : Theme.tTertiary)
                    .frame(width: 24, height: 24)
                    .background(Circle().fill(Color.primary.opacity(0.06)))
                    .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .tip("数据面板")
            Button {
                withAnimation(.easeInOut(duration: 0.35)) { mode = mode == .settings ? .cards : .settings }
            } label: {
                Image(systemName: "gearshape")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(mode == .settings ? Theme.claude : Theme.tTertiary)
                    .frame(width: 24, height: 24)
                    .background(Circle().fill(Color.primary.opacity(0.06)))
                    .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .tip("设置")
        }
    }

    private func toolCards(for u: Usage, localUsage: Usage?) -> [ToolCardItem] {
        // 使用合并后的数据显示内容
        let cr = u.claude.ranges.get(sel), xr = u.codex.ranges.get(sel)
        let gr = u.gemini.ranges.get(sel), kr = u.grok.ranges.get(sel)
        let qr = u.qoder.ranges.get(sel), qwr = u.qoderwork.ranges.get(sel)
        let hr = u.hermes.ranges.get(sel)
        let lr = u.openclaw.ranges.get(sel), pr = u.pi.ranges.get(sel), or = u.opencode.ranges.get(sel)

        // 根据"展示全部设备"开关决定 active 判断依据
        // 本机模式：使用本机数据；全部设备模式：使用合并后数据
        let activeUsage = store.showAllDevices ? u : (localUsage ?? u)
        let lcr = activeUsage.claude.ranges.get(sel), lxr = activeUsage.codex.ranges.get(sel)
        let lgr = activeUsage.gemini.ranges.get(sel), lkr = activeUsage.grok.ranges.get(sel)
        let lqr = activeUsage.qoder.ranges.get(sel), lqwr = activeUsage.qoderwork.ranges.get(sel), lhr = activeUsage.hermes.ranges.get(sel)
        let llr = activeUsage.openclaw.ranges.get(sel), lpr = activeUsage.pi.ranges.get(sel), lor = activeUsage.opencode.ranges.get(sel)

        return [
            ToolCardItem(id: "claude", name: "Claude", visible: showClaude, active: lcr.sessions > 0,
                         tint: Theme.claude, content: AnyView(claudeBlock(u.claude, cr))),
            ToolCardItem(id: "codex", name: "Codex", visible: showCodex, active: lxr.sessions > 0,
                         tint: Theme.codex, content: AnyView(codexBlock(u.codex, xr))),
            ToolCardItem(id: "gemini", name: "Gemini", visible: showGemini, active: lgr.sessions > 0,
                         tint: Theme.gemini, content: AnyView(geminiBlock(gr))),
            ToolCardItem(id: "grok", name: "Grok", visible: showGrok, active: lkr.sessions > 0,
                         tint: Theme.grok, content: AnyView(grokBlock(kr, model: u.grok.model))),
            ToolCardItem(id: "qoder", name: "Qoder", visible: showQoder, active: lqr.calls > 0,
                         tint: Theme.qoder, content: AnyView(qoderIdeBlock(u.qoder, qr))),
            ToolCardItem(id: "qoderwork", name: "QoderWork", visible: showQoderWork, active: lqwr.calls > 0,
                         tint: Theme.qoderwork, content: AnyView(qoderworkBlock(u.qoderwork, qwr))),
            ToolCardItem(id: "hermes", name: "Hermes", visible: showHermes, active: lhr.sessions > 0,
                         tint: Theme.hermes, content: AnyView(hermesBlock(hr))),
            ToolCardItem(id: "openclaw", name: "OpenClaw", visible: showOpenClaw, active: llr.tasks > 0 || llr.in + llr.out > 0,
                         tint: Theme.openclaw, content: AnyView(openclawBlock(lr))),
            ToolCardItem(id: "pi", name: "Pi", visible: showPi, active: lpr.sessions > 0,
                         tint: Theme.pi, content: AnyView(tokenUsageBlock(title: "Pi Coding Agent", pr, tint: Theme.pi, modelsOpen: $piModelsOpen))),
            ToolCardItem(id: "opencode", name: "OpenCode", visible: showOpenCode, active: lor.sessions > 0,
                         tint: Theme.opencode, content: AnyView(tokenUsageBlock(title: "OpenCode", or, tint: Theme.opencode, modelsOpen: $openCodeModelsOpen))),
        ]
    }

    @ViewBuilder
    private func toolCardsLayout(_ cards: [ToolCardItem]) -> some View {
        if useWide {
            EqualHeightGrid() {
                ForEach(cards) { item in
                    Card(tint: item.tint) { item.content }
                }
            }
        } else {
            ForEach(cards) { item in
                Card(tint: item.tint) { item.content }
            }
        }
    }

    // MARK: - Claude 卡片
    @ViewBuilder
    func claudeBlock(_ c: ClaudeStat, _ r: ClaudeRange) -> some View {
        VStack(alignment: .leading, spacing: 11) {
            cardHead("Claude Code", tint: Theme.claude, sessions: r.sessions)
            if r.sessions > 0 {
                CostHeadline(value: Fmt.human(r.in + r.out + r.cr + r.cw), caption: "\(sel.label) 总量", tint: Theme.claude)
                metricGrid([
                    .init("dollarsign.circle", "≈成本", String(format: "$%.2f", r.cost)),
                ], hit: r.hit, extra: [
                    .init("arrow.down", "输入", Fmt.human(r.in)),
                    .init("arrow.up", "输出", Fmt.human(r.out)),
                    .init("bolt.fill", "缓存读", Fmt.human(r.cr)),
                    .init("square.stack.3d.up.fill", "缓存写", Fmt.human(r.cw)),
                ], tint: Theme.claude)
                let claudeRows = r.models.filter { $0.name != "合成" }.map { m in
                    let denom = m.cr + m.cw + m.in
                    let hit = denom > 0 ? Double(m.cr) / Double(denom) * 100 : 0
                    return ModelRow(name: m.name, pin: m.pin, pout: m.pout, cost: m.cost, total: m.total, hit: hit)
                }
                if !claudeRows.isEmpty {
                    modelDisclosure(claudeRows, open: $claudeModelsOpen, tint: Theme.claude)
                }
                if c.q5 != nil || c.q7 != nil {
                    thinDivider
                    if let q5 = c.q5 {
                        quotaRow(title: "5h 剩余", pct: 100 - q5, reset: c.q5_reset, tint: Theme.claude)
                    }
                    if let q7 = c.q7 {
                        quotaRow(title: "周剩余", pct: 100 - q7, reset: c.q7_reset, tint: Theme.claude)
                    }
                }
            } else {
                emptyHint
            }
        }
    }

    // MARK: - Codex 卡片
    @ViewBuilder
    func codexBlock(_ x: CodexStat, _ r: CodexRange) -> some View {
        VStack(alignment: .leading, spacing: 11) {
            cardHead("Codex", tint: Theme.codex, sessions: r.sessions)
            if r.sessions > 0 {
                CostHeadline(value: Fmt.human(r.in + r.cached + r.out), caption: "\(sel.label) 总量", tint: Theme.codex)
                metricGrid([.init("dollarsign.circle", "≈成本", String(format: "$%.2f", r.cost))],
                    hit: r.hit, extra: {
                    var items: [Metric] = [
                        .init("arrow.down", "输入", Fmt.human(r.in)),
                        .init("bolt.fill", "缓存读", Fmt.human(r.cached)),
                        .init("arrow.up", "输出", Fmt.human(r.out)),
                    ]
                    if r.reason > 0 { items.append(.init("brain", "推理", Fmt.human(r.reason))) }
                    return items
                }(), tint: Theme.codex)
                if x.p5 != nil || x.pw != nil { thinDivider }
                if let p5 = x.p5 {
                    quotaRow(title: "5h 剩余", pct: 100 - p5, reset: x.r5, tint: Theme.codex)
                }
                if let pw = x.pw {
                    quotaRow(title: "周剩余", pct: 100 - pw, reset: x.rw, tint: Theme.codex)
                }
                if let plan = x.plan {
                    HStack {
                        Text("plan").font(.system(size: 11)).foregroundStyle(Theme.tTertiary)
                        Spacer()
                        Text(plan)
                            .font(.system(size: 10, weight: .semibold, design: .monospaced))
                            .foregroundStyle(Theme.tSecondary)
                            .padding(.horizontal, 7).padding(.vertical, 2)
                            .background(Capsule().fill(Theme.codex.opacity(0.16)))
                    }
                }
            } else {
                emptyHint
            }
        }
    }

    // MARK: - Gemini 卡片
    @ViewBuilder
    func geminiBlock(_ r: GeminiRange) -> some View {
        VStack(alignment: .leading, spacing: 11) {
            cardHead("Gemini CLI", tint: Theme.gemini, sessions: r.sessions)
            if r.sessions > 0 {
                CostHeadline(value: Fmt.human(r.in + r.cached + r.out + r.thoughts), caption: "\(sel.label) 总量", tint: Theme.gemini)
                metricGrid([.init("dollarsign.circle", "≈成本", String(format: "$%.2f", r.cost))],
                    hit: r.hit, extra: {
                    var items: [Metric] = [
                        .init("arrow.down", "输入", Fmt.human(r.in)),
                        .init("arrow.up", "输出", Fmt.human(r.out)),
                        .init("bolt.fill", "缓存", Fmt.human(r.cached)),
                    ]
                    if r.thoughts > 0 { items.append(.init("brain", "推理", Fmt.human(r.thoughts))) }
                    return items
                }(), tint: Theme.gemini)
                if !r.models.isEmpty {
                    let geminiRows = r.models.map { m in
                        let total = m.in + m.out + m.cached + m.thoughts
                        let denom = m.cached + m.in
                        let hit = denom > 0 ? Double(m.cached) / Double(denom) * 100 : 0
                        return ModelRow(name: m.name, pin: m.pin, pout: m.pout, cost: m.cost, total: total, hit: hit)
                    }
                    modelDisclosure(geminiRows, open: $geminiModelsOpen, tint: Theme.gemini)
                }
            } else {
                emptyHint
            }
        }
    }

    // MARK: - Grok 卡片
    @ViewBuilder
    func grokBlock(_ r: GrokRange, model: String?) -> some View {
        VStack(alignment: .leading, spacing: 11) {
            cardHeadPlain("Grok CLI", tint: Theme.grok)
            if r.sessions > 0 {
                CostHeadline(value: Fmt.human(r.ctx_used ?? r.tokens), caption: "\(sel.label) 上下文", tint: Theme.grok)
                metricGrid({
                    var items: [Metric] = [
                        .init("arrow.triangle.2.circlepath", "轮次", "\(r.turns ?? 0)"),
                        .init("wrench.and.screwdriver", "工具", "\(r.tools ?? 0)"),
                    ]
                    if let duration = r.duration, duration > 0 {
                        items.append(.init("clock", "耗时", Fmt.duration(duration * 1000)))
                    }
                    if let ctx = r.ctx, ctx > 0 {
                        items.append(.init("chart.bar.fill", "窗口", String(format: "%.0f%%", ctx)))
                    }
                    if let ttft = r.ttft, ttft > 0 {
                        items.append(.init("timer", "首字", String(format: "%.1fs", Double(ttft) / 1000)))
                    }
                    if let response = r.response, response > 0 {
                        items.append(.init("speedometer", "响应", String(format: "%.1fs", Double(response) / 1000)))
                    }
                    if (r.errors ?? 0) > 0 {
                        items.append(.init("exclamationmark.triangle", "错误", "\(r.errors ?? 0)"))
                    }
                    if (r.cancellations ?? 0) > 0 {
                        items.append(.init("xmark.circle", "取消", "\(r.cancellations ?? 0)"))
                    }
                    return items
                }(), tint: Theme.grok)
                if let model, !model.isEmpty {
                    modelBadge(model, tint: Theme.grok)
                }
                Text("Grok CLI 本地日志没有保存 input/output usage,这里展示上下文与执行指标。")
                    .font(.system(size: 8.5))
                    .foregroundStyle(Theme.tTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                emptyHint
            }
        }
    }

    // MARK: - Qoder IDE 卡片
    @ViewBuilder
    func qoderIdeBlock(_ q: QoderIdeStat, _ r: QoderIdeRange) -> some View {
        VStack(alignment: .leading, spacing: 11) {
            cardHeadPlain("Qoder", tint: Theme.qoder)
            if r.calls > 0 {
                let total = r.in + r.cached + r.out
                if total > 0 {
                    CostHeadline(value: Fmt.human(total), caption: "\(sel.label) 总量", tint: Theme.qoder)
                }
                metricGrid({
                    var items: [Metric] = [
                        .init("terminal", "调用", "\(r.calls)"),
                        .init("person.2", "会话", "\(r.sessions)"),
                    ]
                    if r.sub_agents > 0 {
                        items.append(.init("point.3.connected.trianglepath.dotted", "子agent", "\(r.sub_agents)"))
                    }
                    if r.messages > 0 {
                        items.append(.init("bubble.left.and.bubble.right", "消息数", Fmt.human(r.messages)))
                    }
                    if r.ctx > 0 {
                        items.append(.init("chart.bar.fill", "缓存命中", String(format: "%.0f%%", r.ctx)))
                    }
                    if r.duration > 0 {
                        items.append(.init("clock", "耗时", Fmt.duration(r.duration * 1000)))
                    }
                    if r.in > 0 {
                        items.append(.init("arrow.down", "输入", Fmt.human(r.in)))
                    }
                    if r.out > 0 {
                        items.append(.init("arrow.up", "输出", Fmt.human(r.out)))
                    }
                    if r.cached > 0 {
                        items.append(.init("bolt.fill", "缓存读", Fmt.human(r.cached)))
                    }
                    return items
                }(), tint: Theme.qoder)
                if let model = q.model, !model.isEmpty {
                    modelBadge(model, tint: Theme.qoder)
                }
            } else {
                emptyHint
            }
        }
    }

    // MARK: - QoderWork 卡片
    @ViewBuilder
    func qoderworkBlock(_ q: QoderStat, _ r: QoderRange) -> some View {
        VStack(alignment: .leading, spacing: 11) {
            cardHeadPlain("QoderWork", tint: Theme.qoderwork)
            if r.calls > 0 {
                metricGrid({
                    var items: [Metric] = [
                        .init("terminal", "调用", "\(r.calls)"),
                        .init("person.2", "会话", "\(r.sessions)"),
                        .init("clock", "耗时", Fmt.duration(r.duration)),
                    ]
                    if r.sub_agents > 0 {
                        items.append(.init("point.3.connected.trianglepath.dotted", "子agent", "\(r.sub_agents)"))
                    }
                    if r.turns > 0 {
                        items.append(.init("bubble.left.and.bubble.right", "消息数", Fmt.human(r.turns)))
                    }
                    if r.ctx > 0 {
                        items.append(.init("chart.bar.fill", "平均深度", String(format: "%.0f%%", r.ctx)))
                    }
                    return items
                }(), tint: Theme.qoderwork)
                if let model = q.model, !model.isEmpty {
                    modelBadge(model, tint: Theme.qoderwork)
                }
            } else {
                emptyHint
            }
        }
    }

    // MARK: - Hermes 卡片
    @ViewBuilder
    func hermesBlock(_ r: HermesRange) -> some View {
        VStack(alignment: .leading, spacing: 11) {
            cardHead("Hermes", tint: Theme.hermes, sessions: r.sessions)
            if r.sessions > 0 {
                CostHeadline(value: Fmt.human(r.in + r.out + r.cr + r.cw + r.reason), caption: "\(sel.label) 总量", tint: Theme.hermes)
                metricGrid([.init("dollarsign.circle", "≈成本", String(format: "$%.2f", r.cost))],
                    hit: r.hit, extra: {
                    var items: [Metric] = [
                        .init("arrow.down", "输入", Fmt.human(r.in)),
                        .init("arrow.up", "输出", Fmt.human(r.out)),
                        .init("bolt.fill", "缓存读", Fmt.human(r.cr)),
                    ]
                    if r.reason > 0 { items.append(.init("brain", "推理", Fmt.human(r.reason))) }
                    return items
                }(), tint: Theme.hermes)
            } else {
                emptyHint
            }
        }
    }

    // MARK: - OpenClaw 卡片
    @ViewBuilder
    func openclawBlock(_ r: OpenClawRange) -> some View {
        VStack(alignment: .leading, spacing: 11) {
            cardHead("OpenClaw", tint: Theme.openclaw, sessions: r.sessions)
            if r.in + r.out > 0 {
                CostHeadline(value: Fmt.human(r.in + r.out + r.cr + r.cw), caption: "\(sel.label) 总量", tint: Theme.openclaw)
                metricGrid([.init("dollarsign.circle", "≈成本", String(format: "$%.2f", r.cost))],
                    hit: r.hit, extra: {
                    var items: [Metric] = [
                        .init("arrow.down", "输入", Fmt.human(r.in)),
                        .init("arrow.up", "输出", Fmt.human(r.out)),
                        .init("bolt.fill", "缓存读", Fmt.human(r.cr)),
                    ]
                    if r.tasks > 0 { items.append(.init("checklist", "任务", "\(r.tasks)")) }
                    return items
                }(), tint: Theme.openclaw)
            } else if r.tasks > 0 {
                HStack(spacing: 16) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("任务").font(.system(size: 10)).foregroundStyle(Theme.tTertiary)
                        Text("\(r.tasks)")
                            .font(.system(size: 16, weight: .bold, design: .rounded))
                            .foregroundStyle(Theme.tPrimary)
                    }
                    if r.completed > 0 {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("完成").font(.system(size: 10)).foregroundStyle(Theme.tTertiary)
                            Text("\(r.completed)")
                                .font(.system(size: 16, weight: .bold, design: .rounded))
                                .foregroundStyle(.green)
                        }
                    }
                    if r.failed > 0 {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("失败").font(.system(size: 10)).foregroundStyle(Theme.tTertiary)
                            Text("\(r.failed)")
                                .font(.system(size: 16, weight: .bold, design: .rounded))
                                .foregroundStyle(.red.opacity(0.8))
                        }
                    }
                    Spacer()
                }
            } else {
                emptyHint
            }
        }
    }

    // MARK: - Token usage cards
    @ViewBuilder
    func tokenUsageBlock(title: String, _ r: TokenUsageRange, tint: Color, modelsOpen: Binding<Bool>) -> some View {
        VStack(alignment: .leading, spacing: 11) {
            cardHead(title, tint: tint, sessions: r.sessions)
            if r.sessions > 0 {
                CostHeadline(value: Fmt.human(r.in + r.out + r.cr + r.cw + r.reason), caption: "\(sel.label) 总量", tint: tint)
                metricGrid([.init("dollarsign.circle", "≈成本", String(format: "$%.2f", r.cost))],
                    hit: r.hit, extra: tokenUsageMetrics(r), tint: tint)
                if !r.models.isEmpty {
                    tokenModelDisclosure(r.models, open: modelsOpen, tint: tint)
                }
            } else {
                emptyHint
            }
        }
    }

    func tokenUsageMetrics(_ r: TokenUsageRange) -> [Metric] {
        var items: [Metric] = [
            .init("arrow.down", "输入", Fmt.human(r.in)),
            .init("arrow.up", "输出", Fmt.human(r.out)),
            .init("bolt.fill", "缓存读", Fmt.human(r.cr)),
            .init("square.stack.3d.up.fill", "缓存写", Fmt.human(r.cw)),
        ]
        if r.reason > 0 { items.append(.init("brain", "推理", Fmt.human(r.reason))) }
        return items
    }

    @ViewBuilder
    private func inactiveToolsLine(_ cards: [ToolCardItem]) -> some View {
        let inactive = cards.filter { $0.visible && !$0.active }.map(\.name)
        if !inactive.isEmpty {
            Text("未检测到本地数据: " + inactive.joined(separator: " · "))
                .font(.system(size: 9))
                .foregroundStyle(Theme.tTertiary)
                .frame(maxWidth: .infinity)
        }
    }

    var emptyHint: some View {
        Text("暂无数据")
            .font(.system(size: 10))
            .foregroundStyle(Theme.tTertiary)
    }

    func modelBadge(_ model: String, tint: Color) -> some View {
        HStack {
            Text("model").font(.system(size: 11)).foregroundStyle(Theme.tTertiary)
            Spacer()
            Text(model)
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(Theme.tSecondary)
                .padding(.horizontal, 7).padding(.vertical, 2)
                .background(Capsule().fill(tint.opacity(0.16)))
        }
    }

    // MARK: - 复用片段
    struct Metric { var icon, label, value: String
        init(_ i: String, _ l: String, _ v: String) { icon = i; label = l; value = v } }

    // 模型明细行(Claude / Gemini 共用)。
    struct ModelRow: Identifiable {
        var name: String
        var pin: Double
        var pout: Double
        var cost: Double
        var total: Int = 0
        var hit: Double = 0
        var id: String { name }
    }

    func tokenModelTotal(_ m: TokenModelStat) -> Int {
        m.in + m.out + m.cr + m.cw + m.reason
    }

    func tokenModelHit(_ m: TokenModelStat) -> Double {
        let denom = m.cr + m.cw + m.in
        return denom > 0 ? Double(m.cr) / Double(denom) * 100 : 0
    }

    func cardHead(_ title: String, tint: Color, sessions: Int = 0) -> some View {
        HStack(spacing: 7) {
            Circle().fill(tint.gradient).frame(width: 8, height: 8)
                .shadow(color: tint.opacity(0.6), radius: 3)
            Text(title).font(.system(size: 14, weight: .bold))
            if sessions > 0 {
                Text("\(sessions)")
                    .font(.system(size: 10, weight: .bold, design: .rounded))
                    .foregroundStyle(tint)
                    .padding(.horizontal, 5).padding(.vertical, 1.5)
                    .background(Capsule().fill(tint.opacity(0.12)))
            }
            Spacer()
        }
    }

    // 无命中环的卡头(Grok 无缓存命中数据)。
    func cardHeadPlain(_ title: String, tint: Color) -> some View {
        HStack(spacing: 7) {
            Circle().fill(tint.gradient).frame(width: 8, height: 8)
                .shadow(color: tint.opacity(0.6), radius: 3)
            Text(title).font(.system(size: 14, weight: .bold))
            Spacer()
        }
    }

    @ViewBuilder
    func metricGrid(_ top: [Metric], hit: Double = 0, extra: [Metric] = [], tint: Color) -> some View {
        LazyVGrid(columns: [GridItem(.flexible(), spacing: 10),
                            GridItem(.flexible(), spacing: 10)],
                  alignment: .leading, spacing: 9) {
            ForEach(top.indices, id: \.self) { i in
                MetricCell(icon: top[i].icon, label: top[i].label,
                           value: top[i].value, tint: tint)
            }
            if hit > 0 {
                RingMetricCell(value: hit, label: "Cache Hit", tint: tint)
            }
            let offset = top.count + (hit > 0 ? 1 : 0)
            ForEach(extra.indices, id: \.self) { i in
                MetricCell(icon: extra[i].icon, label: extra[i].label,
                           value: extra[i].value, tint: tint)
                    .id(offset + i)
            }
        }
    }

    var thinDivider: some View {
        Rectangle().fill(Color.primary.opacity(0.08)).frame(height: 1)
    }

    func sessionRow(_ name: String, _ total: Int) -> some View {
        HStack {
            Image(systemName: "dot.radiowaves.left.and.right")
                .font(.system(size: 9)).foregroundStyle(Theme.tTertiary)
            Text("本会话 \(name)").font(.system(size: 10)).foregroundStyle(Theme.tTertiary)
            Spacer()
            Text(Fmt.human(total))
                .font(.system(size: 10, weight: .medium, design: .monospaced))
                .foregroundStyle(Theme.tSecondary)
        }
    }

    var disclaimer: some View {
        Text(mode == .settings ? "Made by lank" : "成本按 API 价估算,非订阅实付")
            .font(.system(size: 9))
            .foregroundStyle(Theme.tTertiary)
    }

    @ViewBuilder
    func tokenModelDisclosure(_ models: [TokenModelStat], open: Binding<Bool>, tint: Color) -> some View {
        Button {
            open.wrappedValue.toggle()
        } label: {
            HStack(spacing: 5) {
                Image(systemName: "chart.pie.fill")
                    .font(.system(size: 9)).foregroundStyle(tint)
                Text("按模型 (\(models.count))")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(Theme.tSecondary)
                Image(systemName: open.wrappedValue ? "chevron.down" : "chevron.right")
                    .font(.system(size: 8, weight: .bold))
                    .foregroundStyle(Theme.tTertiary)
                Spacer()
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        if open.wrappedValue {
            VStack(alignment: .leading, spacing: 9) {
                Text("按模型 · \(sel.label)")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(Theme.tSecondary)
                ForEach(models) { m in
                    let total = tokenModelTotal(m)
                    let hit = tokenModelHit(m)
                    HStack(spacing: 7) {
                        Circle().fill(tint.opacity(0.7)).frame(width: 5, height: 5)
                        Text(m.name).font(.system(size: 11.5)).foregroundStyle(Theme.tPrimary)
                            .lineLimit(1)
                        Spacer(minLength: 4)
                        Text(Fmt.human(total))
                            .font(.system(size: 9.5, design: .monospaced))
                            .foregroundStyle(Theme.tTertiary)
                        if hit > 0 {
                            Text(String(format: "%.0f%%", hit))
                                .font(.system(size: 9.5, design: .monospaced))
                                .foregroundStyle(Theme.tTertiary)
                                .padding(.horizontal, 4).padding(.vertical, 1)
                                .background(Capsule().fill(Color.primary.opacity(0.06)))
                        }
                        if m.cost > 0 {
                            Text(String(format: "$%.2f", m.cost))
                                .font(.system(size: 11.5, weight: .semibold, design: .monospaced))
                                .foregroundStyle(Theme.tPrimary)
                        }
                    }
                }
            }
            .padding(10)
            .background(RoundedRectangle(cornerRadius: 7, style: .continuous)
                .fill(Color.primary.opacity(0.05)))
        }
    }

    @ViewBuilder
    func modelDisclosure(_ models: [ModelRow], open: Binding<Bool>, tint: Color) -> some View {
        Button {
            open.wrappedValue.toggle()
        } label: {
            HStack(spacing: 5) {
                Image(systemName: "chart.pie.fill")
                    .font(.system(size: 9)).foregroundStyle(tint)
                Text("按模型 (\(models.count))")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(Theme.tSecondary)
                Image(systemName: open.wrappedValue ? "chevron.down" : "chevron.right")
                    .font(.system(size: 8, weight: .bold))
                    .foregroundStyle(Theme.tTertiary)
                Spacer()
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        if open.wrappedValue {
            VStack(alignment: .leading, spacing: 9) {
                Text("按模型 · \(sel.label)")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(Theme.tSecondary)
                ForEach(models) { m in
                    HStack(spacing: 7) {
                        Circle().fill(tint.opacity(0.7)).frame(width: 5, height: 5)
                        Text(m.name).font(.system(size: 11.5)).foregroundStyle(Theme.tPrimary)
                            .lineLimit(1)
                        Spacer(minLength: 4)
                        if m.total > 0 {
                            Text(Fmt.human(m.total))
                                .font(.system(size: 9.5, design: .monospaced))
                                .foregroundStyle(Theme.tTertiary)
                        }
                        if m.hit > 0 {
                            Text(String(format: "%.0f%%", m.hit))
                                .font(.system(size: 9.5, design: .monospaced))
                                .foregroundStyle(Theme.tTertiary)
                                .padding(.horizontal, 4).padding(.vertical, 1)
                                .background(Capsule().fill(Color.primary.opacity(0.06)))
                        }
                        Text(String(format: "$%.2f", m.cost))
                            .font(.system(size: 11.5, weight: .semibold, design: .monospaced))
                            .foregroundStyle(Theme.tPrimary)
                    }
                }
            }
            .padding(10)
            .background(RoundedRectangle(cornerRadius: 7, style: .continuous)
                .fill(Color.primary.opacity(0.05)))
        }
    }

    func quotaRow(title: String, pct: Double, detail: String? = nil, reset: Int?, tint: Color) -> some View {
        VStack(spacing: 4) {
            HStack {
                Text(title).font(.system(size: 11)).foregroundStyle(Theme.tSecondary)
                if let d = detail {
                    Text(d)
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(Theme.tTertiary)
                }
                Spacer()
                Text(String(format: "%.0f%%", pct))
                    .font(.system(size: 12, weight: .semibold, design: .monospaced))
                    .foregroundStyle(pct <= 15 ? AnyShapeStyle(.red) : AnyShapeStyle(Theme.tPrimary))
                Text("· \(Fmt.reset(reset))")
                    .font(.system(size: 9.5, design: .monospaced))
                    .foregroundStyle(Theme.tTertiary)
            }
            MiniBar(value: pct, tint: pct <= 15 ? .red : tint)
        }
        .help(reset != nil ? "\(Fmt.countdown(reset)) 后重置" : "")
    }

    var footer: some View {
        HStack(spacing: 4) {
            disclaimer
            Spacer()
            KeepAwakeMenu(ka: store.keepAwake)
            IconButton(icon: "arrow.clockwise", label: "刷新") { store.refresh() }
            IconButton(icon: "power", label: "退出") { NSApp.terminate(nil) }
        }
    }

    @State private var updateSpin = false

    @ViewBuilder
    private var updatePill: some View {
        switch updater.state {
        case .available(let tag, _):
            Button { updater.performUpdate() } label: {
                ZStack {
                    Circle()
                        .strokeBorder(
                            AngularGradient(colors: [.cyan, .blue, .purple, .cyan],
                                           center: .center),
                            lineWidth: 2
                        )
                        .frame(width: 26, height: 26)
                        .rotationEffect(.degrees(updateSpin ? 360 : 0))
                        .onAppear {
                            withAnimation(.linear(duration: 2.5).repeatForever(autoreverses: false)) {
                                updateSpin = true
                            }
                        }
                    Image(systemName: "arrow.up")
                        .font(.system(size: 10, weight: .bold))
                        .foregroundStyle(.white)
                }
            }
            .buttonStyle(.plain)
            .tip("升级 \(tag)")
        case .downloading(let p):
            ZStack {
                Circle()
                    .stroke(Color.primary.opacity(0.1), lineWidth: 2)
                    .frame(width: 26, height: 26)
                Circle()
                    .trim(from: 0, to: p)
                    .stroke(Color.cyan, style: StrokeStyle(lineWidth: 2, lineCap: .round))
                    .frame(width: 26, height: 26)
                    .rotationEffect(.degrees(-90))
                Text("\(Int(p * 100))")
                    .font(.system(size: 7, weight: .bold, design: .monospaced))
                    .foregroundStyle(Theme.tSecondary)
            }
        case .installing:
            ZStack {
                Circle()
                    .strokeBorder(
                        AngularGradient(colors: [.clear, Theme.claude], center: .center),
                        lineWidth: 2
                    )
                    .frame(width: 26, height: 26)
                    .rotationEffect(.degrees(updateSpin ? 360 : 0))
                Image(systemName: "square.and.arrow.up")
                    .font(.system(size: 9, weight: .bold))
                    .foregroundStyle(Theme.claude)
            }
        case .failed:
            Button { updater.checkForUpdate() } label: {
                Image(systemName: "exclamationmark.circle")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(.red)
                    .frame(width: 26, height: 26)
            }
            .buttonStyle(.plain)
            .tip("重试")
        default:
            EmptyView()
        }
    }

    @ObservedObject private var updater = Updater.shared
    @State private var priceUpdating = false
    @State private var priceResult = ""
    @State private var debugRunning = false
    @State private var debugOutput = ""
    @State private var debugExpanded = false
    @State private var cachedRemoteUrl = ""
    @AppStorage("syncDir") private var syncDir = ""
    @AppStorage("deviceName") private var deviceName = ""
    @AppStorage("autoSync") private var autoSync = false
    @AppStorage("syncInterval") private var syncInterval = 5
    @AppStorage("sitReminderOn") private var sitReminderOn = false
    @AppStorage("sitReminderInterval") private var sitReminderInterval = 90

    var settingsContent: some View {
        VStack(alignment: .leading, spacing: 12) {
            settingsHeader

            HStack(alignment: .top, spacing: 11) {
                VStack(alignment: .leading, spacing: 11) {
                    settingsAgentsSection
                    settingsDiagnosticsSection
                    settingsPricingSection
                }
                .frame(maxWidth: .infinity, alignment: .top)

                VStack(alignment: .leading, spacing: 11) {
                    settingsReminderSection
                    settingsSyncSection
                    if !store.syncEnabled { settingsRemoteHintSection }
                }
                .frame(maxWidth: .infinity, alignment: .top)
            }

        }
        .onAppear {
            if let cfg = SyncManager.loadConfig() {
                if syncDir.isEmpty && !cfg.sync_dir.isEmpty {
                    let expanded = (cfg.sync_dir as NSString).expandingTildeInPath
                    if FileManager.default.fileExists(atPath: expanded) {
                        syncDir = expanded
                    }
                }
                if deviceName.isEmpty && !cfg.device_id.isEmpty {
                    deviceName = cfg.device_id
                }
                if !store.syncEnabled && !cfg.sync_dir.isEmpty {
                    let expanded = (cfg.sync_dir as NSString).expandingTildeInPath
                    if FileManager.default.fileExists(atPath: expanded) {
                        store.syncEnabled = true
                    }
                }
                if let auto = cfg.auto_sync { autoSync = auto }
                if let interval = cfg.sync_interval { syncInterval = interval }
            }
            if !syncDir.isEmpty {
                DispatchQueue.global(qos: .userInitiated).async {
                    let url = Self.gitRemoteUrl(syncDir)
                    DispatchQueue.main.async { cachedRemoteUrl = url }
                }
            }
        }
    }

    var settingsAgentsSection: some View {
        settingsSection("square.grid.2x2", "显示卡片") {
            LazyVGrid(columns: [GridItem(.flexible(), spacing: 7),
                                GridItem(.flexible(), spacing: 7)], spacing: 7) {
                settingsRow("Claude", tint: Theme.claude, isOn: $showClaude)
                settingsRow("Codex", tint: Theme.codex, isOn: $showCodex)
                settingsRow("Gemini", tint: Theme.gemini, isOn: $showGemini)
                settingsRow("Grok", tint: Theme.grok, isOn: $showGrok)
                settingsRow("Qoder", tint: Theme.qoder, isOn: $showQoder)
                settingsRow("QoderWork", tint: Theme.qoderwork, isOn: $showQoderWork)
                settingsRow("Hermes", tint: Theme.hermes, isOn: $showHermes)
                settingsRow("OpenClaw", tint: Theme.openclaw, isOn: $showOpenClaw)
                settingsRow("Pi", tint: Theme.pi, isOn: $showPi)
                settingsRow("OpenCode", tint: Theme.opencode, isOn: $showOpenCode)
            }
        }
        .onChange(of: showQoder) { enabled in
            Self.setQoderIdeEnabled(enabled)
        }
    }

    private static func setQoderIdeEnabled(_ enabled: Bool) {
        let configURL = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".tokei/config.json")
        var dict: [String: Any] = [:]
        if let data = try? Data(contentsOf: configURL),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            dict = obj
        }
        dict["qoder_ide_enabled"] = enabled
        if let data = try? JSONSerialization.data(withJSONObject: dict, options: [.prettyPrinted, .sortedKeys]) {
            try? data.write(to: configURL)
        }
    }

    var settingsPricingSection: some View {
        settingsSection("dollarsign.circle", "价格表") {
            HStack(spacing: 8) {
                settingsActionButton(icon: "arrow.down.circle", title: "全量更新") {
                    runPriceUpdate("--update-prices", "全量更新中…")
                }
                .disabled(priceUpdating)

                settingsActionButton(icon: "magnifyingglass.circle", title: "查漏补缺") {
                    runPriceUpdate("--update-unknown", "查漏补缺中…")
                }
                .disabled(priceUpdating)

                if priceUpdating { ProgressView().controlSize(.mini) }
            }

            if !priceResult.isEmpty && !priceUpdating {
                Text(priceResult)
                    .font(.system(size: 9))
                    .foregroundStyle(Theme.tTertiary)
                    .lineLimit(2)
                    .onTapGesture { priceResult = "" }
                    .onAppear {
                        DispatchQueue.main.asyncAfter(deadline: .now() + 30) {
                            priceResult = ""
                        }
                    }
            }
        }
    }

    var settingsDiagnosticsSection: some View {
        settingsSection("stethoscope", "诊断") {
            HStack(spacing: 8) {
                settingsActionButton(
                    icon: debugOutput.isEmpty || debugRunning ? "ladybug" : "chevron.up.circle",
                    title: debugButtonTitle
                ) {
                    toggleDiagnostics()
                }
                .disabled(debugRunning)

                if debugRunning { ProgressView().controlSize(.mini) }

                Spacer()

                if !debugOutput.isEmpty {
                    Button {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(debugOutput, forType: .string)
                    } label: {
                        Image(systemName: "doc.on.doc")
                            .font(.system(size: 10))
                            .foregroundStyle(Theme.tTertiary)
                            .frame(width: 22, height: 22)
                            .background(Circle().fill(Color.primary.opacity(0.06)))
                    }
                    .buttonStyle(.plain)
                    .tip("复制诊断")
                }
            }

            if !debugOutput.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Button {
                        withAnimation(.easeInOut(duration: 0.18)) { debugExpanded.toggle() }
                    } label: {
                        HStack(spacing: 5) {
                            Image(systemName: debugExpanded ? "chevron.down" : "chevron.right")
                                .font(.system(size: 8, weight: .semibold))
                            Text(debugSummary)
                                .font(.system(size: 9, design: .monospaced))
                                .lineLimit(1)
                            Spacer()
                        }
                        .foregroundStyle(Theme.tSecondary)
                    }
                    .buttonStyle(.plain)

                    if debugExpanded {
                        Text(debugOutput)
                            .font(.system(size: 8.5, design: .monospaced))
                            .foregroundStyle(Theme.tSecondary)
                            .lineLimit(16)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(8)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: 6, style: .continuous)
                    .fill(Color.primary.opacity(0.05)))
            }
        }
    }

    var settingsReminderSection: some View {
        settingsSection("figure.walk.circle", "久坐提醒") {
            settingsToggleRow("启用", isOn: $sitReminderOn)
                .onChange(of: sitReminderOn) { _ in store.sitReminder.updateRunning() }

            if sitReminderOn {
                HStack {
                    Text("间隔").font(.system(size: 10)).foregroundStyle(Theme.tTertiary)
                    Spacer()
                    Picker("", selection: $sitReminderInterval) {
                        Text("45m").tag(45); Text("60m").tag(60); Text("90m").tag(90)
                    }
                    .pickerStyle(.segmented)
                    .frame(width: 130)
                    .controlSize(.mini)
                    .onChange(of: sitReminderInterval) { _ in store.sitReminder.updateRunning() }
                }

                settingsActionButton(icon: "bell.badge", title: "测试提醒") {
                    store.sitReminder.testPing()
                }

                Text("基于系统空闲判断连续用机时长,看视频或开会不操作会被当作离开。")
                    .font(.system(size: 8.5))
                    .foregroundStyle(Theme.tTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    var settingsSyncSection: some View {
        settingsSection("arrow.triangle.2.circlepath", "多设备同步") {
            settingsToggleRow("启用", isOn: $store.syncEnabled)
                .onChange(of: store.syncEnabled) { on in
                    if on { setupSync() } else { store.stopAutoSync() }
                }

            if store.syncEnabled {
                settingsValueRow("设备名") {
                    TextField("hostname", text: $deviceName)
                        .font(.system(size: 10, design: .monospaced))
                        .textFieldStyle(.plain)
                        .frame(width: 110)
                        .multilineTextAlignment(.trailing)
                        .onChange(of: deviceName) { _ in saveSync() }
                }

                settingsValueRow("目录") {
                    Text(syncDir.isEmpty ? "未设置" : (syncDir as NSString).lastPathComponent)
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(syncDir.isEmpty ? Theme.tTertiary : Theme.tSecondary)
                        .lineLimit(1)
                    Button("选择") { pickSyncDir() }
                        .font(.system(size: 10))
                        .buttonStyle(.plain)
                        .foregroundStyle(Theme.claude)
                }

                HStack(spacing: 8) {
                    settingsActionButton(icon: "arrow.triangle.2.circlepath", title: store.syncing ? "同步中" : "同步") {
                        store.doSync()
                    }
                    .disabled(store.syncing || syncDir.isEmpty)

                    Spacer()
                    Text("自动").font(.system(size: 10)).foregroundStyle(Theme.tTertiary)
                    Toggle("", isOn: $autoSync)
                        .toggleStyle(.switch).controlSize(.mini).labelsHidden()
                        .onChange(of: autoSync) { on in
                            if on { store.startAutoSync(minutes: syncInterval) }
                            else { store.stopAutoSync() }
                        }
                    if autoSync {
                        Picker("", selection: $syncInterval) {
                            Text("1m").tag(1); Text("5m").tag(5); Text("15m").tag(15)
                        }
                        .pickerStyle(.segmented)
                        .frame(width: 90)
                        .controlSize(.mini)
                        .onChange(of: syncInterval) { v in store.startAutoSync(minutes: v) }
                    }
                }

                settingsValueRow("展示") {
                    Picker("", selection: $store.showAllDevices) {
                        Text("本机").tag(false); Text("全部设备").tag(true)
                    }
                    .pickerStyle(.segmented)
                    .frame(width: 120)
                    .controlSize(.mini)
                }

                deviceStatusBlock

                if store.syncEnabled {
                    let dataRepo = cachedRemoteUrl
                    let hasRemote = !dataRepo.isEmpty && !dataRepo.contains("未配置")
                        && (dataRepo.hasPrefix("http") || dataRepo.hasPrefix("git@") || dataRepo.hasPrefix("ssh://"))
                    Rectangle().fill(Color.primary.opacity(0.06)).frame(height: 1)
                    VStack(alignment: .leading, spacing: 8) {
                        HStack(spacing: 5) {
                            Image(systemName: "plus.circle")
                                .font(.system(size: 10, weight: .semibold))
                                .foregroundStyle(Theme.hermes)
                            Text("添加设备")
                                .font(.system(size: 10, weight: .semibold))
                                .foregroundStyle(Theme.tSecondary)
                        }

                        if syncDir.isEmpty {
                            Text("请先点击「选择」设置同步目录(需为 Git 仓库)")
                                .font(.system(size: 9)).foregroundStyle(Theme.tTertiary)
                                .fixedSize(horizontal: false, vertical: true)
                            copyBlock("读取 \(Self.skillPath) 并帮我创建 Tokei 私有数据仓库,配置多设备同步")
                        } else if hasRemote {
                            Text("另一台 Mac").font(.system(size: 9, weight: .medium)).foregroundStyle(Theme.tSecondary)
                            Text("安装 Tokei.app 后选择同一个数据仓库")
                                .font(.system(size: 8.5)).foregroundStyle(Theme.tTertiary)
                                .fixedSize(horizontal: false, vertical: true)
                            Rectangle().fill(Color.primary.opacity(0.04)).frame(height: 1)
                            Text("远程 Linux").font(.system(size: 9, weight: .medium)).foregroundStyle(Theme.tSecondary)
                            copyBlock("git clone \(dataRepo) ~/.tokei/sync && curl -fsSL https://dl.lanshuagent.com/tokei/usage.30s.py -o ~/.tokei/usage.30s.py && echo '{\"sync_dir\":\"~/.tokei/sync\",\"device_id\":\"'$(hostname -s)'\"}' > ~/.tokei/config.json && (crontab -l 2>/dev/null; echo '*/5 * * * * cd ~/.tokei/sync && python3 ~/.tokei/usage.30s.py --json >/dev/null && git pull -q && git add -A && git diff --cached --quiet || git commit -qm sync && git push -q') | crontab -")
                        } else {
                            Text("数据目录未关联 Git 仓库")
                                .font(.system(size: 9)).foregroundStyle(Theme.tTertiary)
                            copyBlock("读取 \(Self.skillPath) 并帮我创建 Tokei 私有数据仓库,配置多设备同步")
                        }
                    }
                }
            }
        }
    }

    var settingsRemoteHintSection: some View {
        settingsSection("antenna.radiowaves.left.and.right", "远程采集") {
            Text("多台 Mac 或远程服务器的数据可通过私有 Git 仓库同步,每台设备独立采集、自动加和。")
                .font(.system(size: 9))
                .foregroundStyle(Theme.tTertiary)
                .fixedSize(horizontal: false, vertical: true)
            copyBlock("读取 \(Self.skillPath) 帮我配置 Tokei 多设备同步")
        }
    }

    var deviceStatusBlock: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 5) {
                Image(systemName: "desktopcomputer")
                    .font(.system(size: 8)).foregroundStyle(.green)
                Text(deviceName.isEmpty ? "本机" : deviceName)
                    .font(.system(size: 10, weight: .medium)).foregroundStyle(Theme.tPrimary)
                Text("(本机)").font(.system(size: 9)).foregroundStyle(Theme.tTertiary)
            }
            if store.peers.isEmpty {
                HStack(spacing: 5) {
                    Image(systemName: "clock")
                        .font(.system(size: 8)).foregroundStyle(Theme.tTertiary)
                    Text("等待其他设备…")
                        .font(.system(size: 10)).foregroundStyle(Theme.tTertiary)
                }
            } else {
                ForEach(store.peers) { p in
                    HStack(spacing: 5) {
                        Image(systemName: "laptopcomputer")
                            .font(.system(size: 8)).foregroundStyle(Theme.codex)
                        Text(p.deviceId)
                            .font(.system(size: 10, weight: .medium)).foregroundStyle(Theme.tPrimary)
                        Spacer()
                        Text(Fmt.reset(Int(p.lastSync.timeIntervalSince1970)))
                            .font(.system(size: 9, design: .monospaced)).foregroundStyle(Theme.tTertiary)
                    }
                }
            }
        }
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 7, style: .continuous)
            .fill(Color.primary.opacity(0.04)))
    }

    var settingsHeader: some View {
        HStack(spacing: 10) {
            ZStack {
                Circle().fill(Theme.claude.opacity(0.16))
                Image(systemName: "gearshape.fill")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(Theme.claude)
            }
            .frame(width: 30, height: 30)
            VStack(alignment: .leading, spacing: 1) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text("设置")
                        .font(.system(size: 15, weight: .bold, design: .rounded))
                        .foregroundStyle(Theme.tPrimary)
                    Text("\(Updater.releaseTag) · \(Self.buildVersion)")
                        .font(.system(size: 8, design: .monospaced))
                        .foregroundStyle(Theme.tTertiary.opacity(0.6))
                }
                Text("显示、同步和诊断")
                    .font(.system(size: 9.5))
                    .foregroundStyle(Theme.tTertiary)
            }
            Spacer()
            Button {
                NSWorkspace.shared.open(URL(string: "https://github.com/cclank/tokei")!)
            } label: {
                GitHubIcon(size: 13)
                    .foregroundStyle(Theme.tTertiary)
                    .frame(width: 24, height: 24)
                    .background(Circle().fill(Color.primary.opacity(0.06)))
            }
            .buttonStyle(.plain)
            .tip("GitHub")
            if case .idle = updater.state {
                Button { updater.checkForUpdate() } label: {
                    Image(systemName: "arrow.triangle.2.circlepath")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(Theme.tTertiary)
                        .frame(width: 24, height: 24)
                        .background(Circle().fill(Color.primary.opacity(0.06)))
                }
                .buttonStyle(.plain)
                .tip("检查更新")
            } else if case .checking = updater.state {
                ProgressView()
                    .controlSize(.small)
                    .frame(width: 24, height: 24)
            } else if case .upToDate = updater.state {
                Image(systemName: "checkmark.circle.fill")
                    .font(.system(size: 12))
                    .foregroundStyle(.green)
                    .frame(width: 24, height: 24)
            }
            updatePill
            Button {
                withAnimation(.easeInOut(duration: 0.25)) { mode = .cards }
            } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(Theme.tTertiary)
                    .frame(width: 24, height: 24)
                    .background(Circle().fill(Color.primary.opacity(0.06)))
            }
            .buttonStyle(.plain)
            .tip("关闭设置")
        }
        .padding(.bottom, 2)
    }

    func settingsSection<C: View>(_ icon: String, _ title: String, @ViewBuilder content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Image(systemName: icon)
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(Theme.claude.opacity(0.95))
                    .frame(width: 20, height: 20)
                    .background(Circle().fill(Theme.claude.opacity(0.10)))
                Text(title)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Theme.tSecondary)
            }
            VStack(spacing: 6) { content() }
        }
        .padding(10)
        .background(
            RoundedRectangle(cornerRadius: 9, style: .continuous)
                .fill(Color.black.opacity(0.16))
                .overlay(
                    RoundedRectangle(cornerRadius: 9, style: .continuous)
                        .strokeBorder(Color.white.opacity(0.06), lineWidth: 0.7)
                )
        )
    }

    func settingsActionButton(icon: String, title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 4) {
                Image(systemName: icon).font(.system(size: 9))
                Text(title).font(.system(size: 10, weight: .medium))
            }
            .foregroundStyle(Theme.tPrimary)
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(RoundedRectangle(cornerRadius: 6, style: .continuous)
                .fill(Color.primary.opacity(0.08)))
        }
        .buttonStyle(.plain)
    }

    func settingsToggleRow(_ title: String, isOn: Binding<Bool>) -> some View {
        HStack {
            Text(title).font(.system(size: 11)).foregroundStyle(Theme.tPrimary)
            Spacer()
            Toggle("", isOn: isOn)
                .toggleStyle(.switch)
                .controlSize(.mini)
                .labelsHidden()
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .background(RoundedRectangle(cornerRadius: 8, style: .continuous)
            .fill(Color.primary.opacity(0.04)))
    }

    func settingsValueRow<C: View>(_ title: String, @ViewBuilder value: () -> C) -> some View {
        HStack(spacing: 8) {
            Text(title).font(.system(size: 10)).foregroundStyle(Theme.tTertiary)
            Spacer()
            value()
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
    }

    func setupSync() {
        if deviceName.isEmpty {
            var buf = [CChar](repeating: 0, count: 256)
            gethostname(&buf, buf.count)
            let raw = String(cString: buf)
            deviceName = raw.components(separatedBy: ".").first ?? "mac"
        }
        saveSync()
    }

    func saveSync() {
        let cfg = SyncConfig(device_id: deviceName, sync_dir: syncDir,
                             auto_sync: autoSync, sync_interval: syncInterval)
        store.syncManager.saveConfig(cfg)
    }

    func runPriceUpdate(_ flag: String, _ msg: String) {
        priceUpdating = true
        priceResult = msg
        DispatchQueue.global(qos: .utility).async {
            let proc = Process()
            proc.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            proc.arguments = ["python3", DataLoader.scriptPath, flag]
            let pipe = Pipe()
            proc.standardOutput = pipe
            proc.standardError = Pipe()
            try? proc.run()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            proc.waitUntilExit()
            let output = String(data: data, encoding: .utf8) ?? ""
            DispatchQueue.main.async {
                priceUpdating = false
                if flag == "--update-prices" {
                    priceResult = output.trimmingCharacters(in: .whitespacesAndNewlines)
                } else {
                    if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                       let count = json["count"] as? Int {
                        priceResult = count > 0 ? "补全 \(count) 个模型" : "所有模型已匹配 ✓"
                    } else {
                        priceResult = output.trimmingCharacters(in: .whitespacesAndNewlines)
                    }
                }
                store.refresh()
            }
        }
    }

    private var debugButtonTitle: String {
        if debugRunning { return "检查中…" }
        return debugOutput.isEmpty ? "运行诊断" : "收起诊断"
    }

    func toggleDiagnostics() {
        if !debugRunning && !debugOutput.isEmpty {
            withAnimation(.easeInOut(duration: 0.18)) {
                debugOutput = ""
                debugExpanded = false
            }
            return
        }
        runDiagnostics()
    }

    func runDiagnostics() {
        debugRunning = true
        debugOutput = "running..."
        debugExpanded = false
        DispatchQueue.global(qos: .utility).async {
            let result = DataLoader.runScriptRaw(args: ["--json"], timeout: 8)
            let report = Self.formatDiagnostics(result)
            DispatchQueue.main.async {
                debugRunning = false
                debugOutput = report
            }
        }
    }

    static func formatDiagnostics(_ result: DataLoader.ScriptResult) -> String {
        let fm = FileManager.default
        let script = DataLoader.scriptPath
        let exists = fm.fileExists(atPath: script)
        let size = ((try? fm.attributesOfItem(atPath: script)[.size] as? NSNumber)?.intValue) ?? 0
        var lines = [
            "script: \(script)",
            "exists: \(exists) size: \(size)B",
            String(format: "exit: %d timeout: %@ elapsed: %.2fs",
                   result.exitCode, result.timedOut ? "yes" : "no", result.elapsed),
            "stdout: \(result.stdout.count)B stderr: \(result.stderr.count)B",
        ]

        if let data = result.stdout.data(using: .utf8),
           let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            let tools = ["claude", "codex", "gemini", "grok", "qoder", "qoderwork", "hermes", "openclaw", "pi", "opencode"]
                .filter { json[$0] != nil }
                .joined(separator: ",")
            lines.append("json: ok tools: \(tools)")
            if let pricing = json["_pricing"] as? [String: Any] {
                lines.append("pricing: \(pricing["count"] ?? "?") \(pricing["updated_at"] ?? "")")
            }
            if let errors = json["_errors"] as? [String: Any], !errors.isEmpty {
                lines.append("errors:")
                for key in errors.keys.sorted() {
                    lines.append("- \(key): \(errors[key] ?? "")")
                }
            } else {
                lines.append("errors: none")
            }
        } else if !result.stdout.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            lines.append("json: invalid")
            lines.append(result.stdout.prefix(600).description)
        }

        if !result.stderr.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            lines.append("stderr:")
            lines.append(result.stderr.prefix(600).description)
        }
        return lines.joined(separator: "\n")
    }

    static let buildVersion = "2026.0615"

    static var skillPath: String {
        return "https://raw.githubusercontent.com/cclank/tokei/main/skills/tokei-setup.md"
    }

    static func gitRemoteUrl(_ dir: String) -> String {
        let expanded = (dir as NSString).expandingTildeInPath
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/usr/bin/git")
        proc.arguments = ["-C", expanded, "remote", "get-url", "origin"]
        let pipe = Pipe()
        proc.standardOutput = pipe
        proc.standardError = Pipe()
        try? proc.run()
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        proc.waitUntilExit()
        let url = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return url.isEmpty ? "<未配置 git remote>" : url
    }

    func copyBlock(_ text: String) -> some View {
        HStack(alignment: .top) {
            Text(text)
                .font(.system(size: 8, design: .monospaced))
                .foregroundStyle(Theme.tSecondary)
                .lineLimit(4)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 4)
            Button {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(text, forType: .string)
            } label: {
                Image(systemName: "doc.on.doc")
                    .font(.system(size: 9)).foregroundStyle(Theme.tTertiary)
            }
            .buttonStyle(.plain)
        }
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 6, style: .continuous)
            .fill(Color.primary.opacity(0.04)))
    }

    func pickSyncDir() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.prompt = "选择同步目录"
        if panel.runModal() == .OK, let url = panel.url {
            syncDir = url.path
            saveSync()
        }
    }

    func settingsRow(_ name: String, tint: Color, isOn: Binding<Bool>) -> some View {
        HStack(spacing: 8) {
            Circle().fill(tint.gradient).frame(width: 6, height: 6)
                .shadow(color: tint.opacity(0.4), radius: 2)
            Text(name)
                .font(.system(size: 11.5, weight: .medium))
                .foregroundStyle(Theme.tPrimary)
            Spacer()
            Toggle("", isOn: isOn)
                .toggleStyle(.switch)
                .controlSize(.mini)
                .labelsHidden()
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(Color.primary.opacity(0.04))
        )
    }
}

struct GitHubIcon: View {
    var size: CGFloat = 16
    private static let icon: NSImage? = {
        guard let url = Bundle.main.url(forResource: "github-mark", withExtension: "png"),
              let img = NSImage(contentsOf: url) else { return nil }
        img.isTemplate = true
        return img
    }()
    var body: some View {
        if let img = Self.icon {
            Image(nsImage: img)
                .resizable()
                .aspectRatio(contentMode: .fit)
                .frame(width: size, height: size)
        } else {
            Image(systemName: "link")
                .font(.system(size: size * 0.7, weight: .bold))
        }
    }
}
