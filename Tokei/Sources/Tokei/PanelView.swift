import SwiftUI
import AppKit
import TokeiUpdateSecurity

struct PanelView: View {
    @ObservedObject var store: Store
    var scrollable = true
    @State private var sel: RangeKey = .today
    @State private var claudeModelsOpen = false
    @State private var codexModelsOpen = false
    @State private var codexResetCardsOpen = false
    @State private var geminiModelsOpen = false
    @State private var cursorModelsOpen = false
    @State private var zaiModelsOpen = false
    @State private var grokModelsOpen = false
    @State private var hermesModelsOpen = false
    @State private var zcodeModelsOpen = false
    @State private var mimocodeModelsOpen = false
    @State private var piModelsOpen = false
    @State private var primeAgentModelsOpen = false
    @State private var workBuddyModelsOpen = false
    @State private var deepSeekHarnessModelsOpen = false
    @State private var openCodeModelsOpen = false
    @State private var qwenCodeModelsOpen = false
    @State private var kimiCodeModelsOpen = false
    @State private var openClawModelsOpen = false
    @State private var expandedModels: Set<String> = []
    @State private var mode: PanelMode = .cards
    @State private var trailProjects: [TrailProject]?
    enum PanelMode { case cards, quotaHistory, dashboard, projects, settings }
    private enum ToolCardPresentation: Equatable {
        case standard
        case compactStatus
    }
    private struct ToolCardItem: Identifiable {
        let id: String
        let name: String
        let visible: Bool
        let active: Bool
        let tint: Color
        var presentation: ToolCardPresentation = .standard
        let content: AnyView
    }
    @AppStorage("showClaude") private var showClaude = true
    @AppStorage("showCodex") private var showCodex = true
    @AppStorage("showGemini") private var showGemini = true
    @AppStorage("showCursor") private var showCursor = false
    @AppStorage("showZed") private var showZed = false
    @AppStorage("showSub2API") private var showSub2API = false
    @AppStorage("showZai") private var showZai = false
    @AppStorage("showGrok") private var showGrok = true
    @AppStorage("showQoderIde") private var showQoder = true
    @AppStorage("showQoderWork") private var showQoderWork = true
    @AppStorage("showQoderCli") private var showQoderCli = true
    @AppStorage("showHermes") private var showHermes = true
    @AppStorage("showZcode") private var showZcode = true
    @AppStorage("showMimoCode") private var showMimoCode = true
    @AppStorage("showOpenClaw") private var showOpenClaw = true
    @AppStorage("showPi") private var showPi = true
    @AppStorage("showPrimeAgent") private var showPrimeAgent = true
    @AppStorage("showWorkBuddy") private var showWorkBuddy = true
    @AppStorage("showDeepSeekHarness") private var showDeepSeekHarness = true
    @AppStorage("showOpenCode") private var showOpenCode = true
    @AppStorage("showQwenCode") private var showQwenCode = true
    @AppStorage("showQwenWork") private var showQwenWork = true
    @AppStorage("showKimiCode") private var showKimiCode = true
    /// 默认关闭：Grok 额度只读本地日志；开启后才用登录凭据请求实时账单接口。
    @AppStorage("grokLiveQuotaEnabled") private var grokLiveQuotaEnabled = false
    /// 默认关闭：开启后仅查询千问办公桌面端暴露在本机回环地址上的额度接口。
    @AppStorage("qwenWorkQuotaEnabled") private var qwenWorkQuotaEnabled = false
    /// 菜单栏额度来源（与显示卡片独立），每项是一个具体窗口。
    /// 只有历史上就默认开的 Claude 5h 与 Codex 周保持默认开，其余窗口默认关，避免抢占状态栏。
    @AppStorage(MenuBarQuotaSource.claude5h.defaultsKey) private var menuBarQuotaClaude5h = true
    @AppStorage(MenuBarQuotaSource.claudeWeek.defaultsKey) private var menuBarQuotaClaudeWeek = false
    @AppStorage(MenuBarQuotaSource.claudeFable.defaultsKey) private var menuBarQuotaClaudeFable = false
    @AppStorage(MenuBarQuotaSource.codex5h.defaultsKey) private var menuBarQuotaCodex5h = false
    @AppStorage(MenuBarQuotaSource.codexWeek.defaultsKey) private var menuBarQuotaCodexWeek = true
    @AppStorage(MenuBarQuotaSource.grok.defaultsKey) private var menuBarQuotaGrok = false
    @State private var copyFeedback = false
    @State private var copiedToolID: String?

    private var toolVisibility: UsageToolVisibility {
        UsageToolVisibility(
            claude: showClaude, codex: showCodex, gemini: showGemini, grok: showGrok,
            qoder: showQoder, qoderwork: showQoderWork, qodercli: showQoderCli,
            hermes: showHermes, zcode: showZcode, mimocode: showMimoCode,
            openclaw: showOpenClaw, pi: showPi, primeAgent: showPrimeAgent,
            workbuddy: showWorkBuddy, deepseekHarness: showDeepSeekHarness,
            opencode: showOpenCode, qwencode: showQwenCode, kimicode: showKimiCode
        )
    }

    private var visibleCount: Int {
        [showClaude, showCodex, showGemini, showCursor, showZed, showSub2API, showZai,
         showGrok, showQoder, showQoderWork, showQoderCli, showHermes, showZcode, showMimoCode,
         showOpenClaw, showPi, showWorkBuddy, showDeepSeekHarness, showOpenCode, showQwenCode,
         showQwenWork, showKimiCode, showPrimeAgent].filter { $0 }.count
    }
    private var hasMultipleDevices: Bool { store.syncEnabled && !store.peers.isEmpty }
    private var useWide: Bool { visibleCount > 2 }
    private var panelWidth: CGFloat { useWide ? 640 : Theme.panelWidth }
    private var settingsPanelWidth: CGFloat { 640 }
    private var settingsColumnWidth: CGFloat {
        (settingsPanelWidth - Theme.outerPad * 2 - 11) / 2
    }
    private var settingsMenuPickerWidth: CGFloat { settingsColumnWidth - 40 }

    private var maxPanelHeight: CGFloat {
        (NSScreen.main?.visibleFrame.height ?? 900) - 40
    }

    private var projectPanelHeight: CGFloat {
        let visibleRows = min(trailProjects?.count ?? 5, 7)
        return min(maxPanelHeight, min(720, max(360, 150 + CGFloat(visibleRows) * 84)))
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
        let w = (mode == .settings || mode == .quotaHistory)
            ? settingsPanelWidth
            : (mode == .cards ? panelWidth : max(panelWidth, 420))
        if scrollable {
            if mode == .projects {
                projectPanelContent
                    .frame(width: w, height: projectPanelHeight)
                    .background(Theme.bg)
                    .background(VisualEffect())
                    .environment(\.colorScheme, .dark)
            } else {
                ScrollView(.vertical, showsIndicators: false) { panelContent }
                    .frame(width: w)
                    .frame(maxHeight: maxPanelHeight)
                    .background(Theme.bg)
                    .background(VisualEffect())
                    .environment(\.colorScheme, .dark)
            }
        } else {
            panelContent
                .frame(width: w, alignment: .top)
                .background(Theme.bg)
                .background(VisualEffect())
                .environment(\.colorScheme, .dark)
        }
    }

    private var projectPanelContent: some View {
        VStack(alignment: .leading, spacing: 13) {
            header
            ScrollView(.vertical, showsIndicators: true) {
                ProjectTrailView(cached: $trailProjects)
                    .frame(maxWidth: .infinity, alignment: .topLeading)
            }
            footer
        }
        .padding(Theme.outerPad)
    }

    private var panelContent: some View {
        VStack(alignment: .leading, spacing: 13) {
            header
            if mode == .quotaHistory {
                QuotaHistoryView(history: store.quotaHistory)
            } else if mode == .dashboard {
                DashboardView(store: store)
            } else if mode == .projects {
                ProjectTrailView(cached: $trailProjects)
            } else if mode == .settings {
                settingsContent
            } else if let u = store.usage {
                let cards = toolCards(for: u)
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
                            .lineLimit(1)
                        Text("知度 · AI 用量")
                            .font(.system(size: 9))
                            .foregroundStyle(Theme.tTertiary)
                            .lineLimit(1)
                    }
                    .fixedSize(horizontal: true, vertical: false)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .tip("主页")
            updatePill
            if store.syncFailStreak >= 3 {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 11))
                    .foregroundStyle(.orange)
                    .help("多设备同步已连续失败 \(store.syncFailStreak) 次：\(store.syncStatus)\n\(store.syncDetail)")
            }
            Spacer()
            if hasMultipleDevices {
                deviceScopePicker
            }
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
                mode = mode == .quotaHistory ? .cards : .quotaHistory
            } label: {
                Image(systemName: "chart.xyaxis.line")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(mode == .quotaHistory ? Theme.claude : Theme.tTertiary)
                    .frame(width: 24, height: 24)
                    .background(Circle().fill(Color.primary.opacity(0.06)))
                    .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .tip("额度曲线")
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

    var deviceScopePicker: some View {
        Picker("", selection: $store.showAllDevices) {
            Text("本机").tag(false)
            Text("全部").tag(true)
        }
        .pickerStyle(.segmented)
        .frame(width: 92)
        .controlSize(.mini)
        .onChange(of: store.showAllDevices) { _ in store.applyDisplayMode() }
        .tip("数据范围")
    }

    private func toolCards(for u: Usage) -> [ToolCardItem] {
        let cr = u.claude.ranges.get(sel), xr = u.codex.ranges.get(sel)
        let geminiDisplay = u.gemini.ranges.displayRange(for: sel)
        let kr = u.grok.ranges.get(sel)
        let qr = u.qoder.ranges.get(sel), qwr = u.qoderwork.ranges.get(sel)
        let qclir = u.qodercli.ranges.get(sel)
        let hr = u.hermes.ranges.get(sel)
        let zr = u.zcode.ranges.get(sel), mr = u.mimocode.ranges.get(sel)
        let lr = u.openclaw.ranges.get(sel), pr = u.pi.ranges.get(sel)
        let par = u.prime_agent.ranges.get(sel)
        let wr = u.workbuddy.ranges.get(sel), or = u.opencode.ranges.get(sel)
        let dshr = u.deepseekHarness.ranges.get(sel)
        let claudeQuotaState = SubscriptionQuotaState.resolve([
            (value: u.claude.q5, stale: u.claude.q5_stale),
            (value: u.claude.q7, stale: u.claude.q7_stale),
            (value: u.claude.qf, stale: u.claude.qf_stale),
        ])
        let grokQuotaState = SubscriptionQuotaState.resolve([
            (value: u.grok.pct, stale: u.grok.stale),
        ])
        let cursorUsage = u.cursor.usage?.ranges.get(sel) ?? TokenUsageRange()
        let zaiUsage = u.zai.usage?.ranges.get(sel) ?? TokenUsageRange()
        let qcr = u.qwencode.ranges.get(sel), kcr = u.kimicode.ranges.get(sel)
        return [
            ToolCardItem(id: "claude", name: "Claude", visible: showClaude,
                         active: cr.sessions > 0 || u.claude.q5 != nil ||
                             u.claude.q7 != nil || u.claude.qf != nil,
                         tint: Theme.claude,
                         presentation: claudeQuotaState.shouldUseCompactCard(hasUsage: cr.sessions > 0)
                             ? .compactStatus : .standard,
                         content: AnyView(claudeBlock(u.claude, cr))),
            ToolCardItem(id: "codex", name: "Codex", visible: showCodex,
                         active: xr.sessions > 0 || u.codex.p5 != nil || u.codex.pw != nil ||
                             (u.codex.reset_cards?.count ?? 0) > 0,
                         tint: Theme.codex, content: AnyView(codexBlock(u.codex, xr))),
            ToolCardItem(id: "gemini", name: "Gemini", visible: showGemini,
                         active: geminiDisplay.range.hasUsage || u.antigravity.available,
                         tint: Theme.gemini,
                         presentation: !geminiDisplay.range.hasUsage && u.antigravity.available
                             ? .compactStatus : .standard,
                         content: AnyView(geminiBlock(
                            geminiDisplay.range,
                            quota: u.antigravity,
                            displayedRange: geminiDisplay.key
                         ))),
            ToolCardItem(id: "cursor", name: "Cursor", visible: showCursor,
                         active: u.cursor.available || cursorUsage.totalTokens > 0,
                         tint: Theme.cursor,
                         presentation: cursorUsage.totalTokens > 0 ? .standard : .compactStatus,
                         content: AnyView(providerQuotaBlock(
                            "Cursor", quota: u.cursor, usage: cursorUsage,
                            modelsOpen: $cursorModelsOpen, tint: Theme.cursor,
                            setupHint: "请确认 Cursor.app 已登录；Tokei 会复用其本地登录态读取额度。"))),
            ToolCardItem(id: "zed", name: "Zed", visible: showZed, active: showZed,
                         tint: Theme.zed, presentation: .compactStatus,
                         content: AnyView(providerQuotaBlock(
                            "Zed", quota: u.zed, tint: Theme.zed,
                            setupHint: "请先在 Zed 中登录 GitHub；Tokei 会无弹窗读取现有 Keychain 登录态。"))),
            ToolCardItem(id: "sub2api", name: "Sub2API", visible: showSub2API, active: showSub2API,
                         tint: Theme.sub2api, presentation: .compactStatus,
                         content: AnyView(providerQuotaBlock(
                            "Sub2API", quota: u.sub2api, tint: Theme.sub2api,
                            setupHint: "请在设置的「Provider 额度」中保存 Base URL 与 Group API Key。"))),
            ToolCardItem(id: "zai", name: "z.ai / GLM", visible: showZai,
                         active: u.zai.available || zaiUsage.totalTokens > 0,
                         tint: Theme.zai,
                         presentation: zaiUsage.totalTokens > 0 ? .standard : .compactStatus,
                         content: AnyView(providerQuotaBlock(
                            "z.ai / GLM", quota: u.zai, usage: zaiUsage,
                            modelsOpen: $zaiModelsOpen, tint: Theme.zai,
                            setupHint: "请在设置的「Provider 额度」中选择区域并保存 API Key。"))),
            ToolCardItem(id: "grok", name: "Grok", visible: showGrok,
                         active: kr.sessions > 0 || kr.usage_calls > 0 || u.grok.pct != nil,
                         tint: Theme.grok,
                         presentation: grokQuotaState.shouldUseCompactCard(
                            hasUsage: kr.sessions > 0 || kr.usage_calls > 0
                         ) ? .compactStatus : .standard,
                         content: AnyView(grokBlock(u.grok, kr))),
            ToolCardItem(id: "qoder", name: "Qoder Desktop", visible: showQoder, active: qr.calls > 0,
                         tint: Theme.qoder, content: AnyView(qoderIdeBlock(u.qoder, qr))),
            ToolCardItem(id: "qoderwork", name: "QoderWork", visible: showQoderWork, active: qwr.calls > 0,
                         tint: Theme.qoderwork, content: AnyView(qoderworkBlock(u.qoderwork, qwr))),
            ToolCardItem(id: "qodercli", name: "Qoder CLI", visible: showQoderCli, active: qclir.calls > 0,
                         tint: Theme.qodercli, content: AnyView(qodercliBlock(u.qodercli, qclir))),
            ToolCardItem(id: "hermes", name: "Hermes", visible: showHermes, active: hr.sessions > 0,
                         tint: Theme.hermes, content: AnyView(hermesBlock(hr, modelsOpen: $hermesModelsOpen))),
            ToolCardItem(id: "zcode", name: "ZCode", visible: showZcode, active: zr.sessions > 0,
                         tint: Theme.zcode, content: AnyView(tokenUsageBlock(title: "ZCode", zr, tint: Theme.zcode, modelsOpen: $zcodeModelsOpen, toolID: "zcode"))),
            ToolCardItem(id: "mimocode", name: "MiMoCode", visible: showMimoCode, active: mr.sessions > 0,
                         tint: Theme.mimocode, content: AnyView(tokenUsageBlock(title: "MiMoCode", mr, tint: Theme.mimocode, modelsOpen: $mimocodeModelsOpen, toolID: "mimocode"))),
            ToolCardItem(id: "openclaw", name: "OpenClaw", visible: showOpenClaw,
                         active: lr.tasks > 0 || lr.in + lr.out + lr.cr + lr.cw + lr.reason > 0,
                         tint: Theme.openclaw, content: AnyView(openclawBlock(lr, modelsOpen: $openClawModelsOpen))),
            ToolCardItem(id: "pi", name: "Pi", visible: showPi, active: pr.sessions > 0,
                         tint: Theme.pi, content: AnyView(tokenUsageBlock(title: "Pi Coding Agent", pr, tint: Theme.pi, modelsOpen: $piModelsOpen, toolID: "pi"))),
            ToolCardItem(id: "prime_agent", name: "Prime Agent", visible: showPrimeAgent, active: par.sessions > 0,
                         tint: Theme.primeAgent, content: AnyView(tokenUsageBlock(title: "Prime Agent", par, tint: Theme.primeAgent, modelsOpen: $primeAgentModelsOpen, toolID: "prime_agent"))),
            ToolCardItem(id: "workbuddy", name: "WorkBuddy", visible: showWorkBuddy, active: wr.sessions > 0,
                         tint: Theme.workbuddy, content: AnyView(tokenUsageBlock(title: "WorkBuddy", wr, tint: Theme.workbuddy, modelsOpen: $workBuddyModelsOpen, toolID: "workbuddy"))),
            ToolCardItem(id: "deepseek_harness", name: "DeepSeek Harness", visible: showDeepSeekHarness,
                         active: dshr.sessions > 0, tint: Theme.deepseekHarness,
                         content: AnyView(tokenUsageBlock(title: "DeepSeek Harness", dshr,
                                                          tint: Theme.deepseekHarness,
                                                          modelsOpen: $deepSeekHarnessModelsOpen,
                                                          inclusiveIO: true,
                                                          toolID: "deepseek_harness"))),
            ToolCardItem(id: "opencode", name: "OpenCode", visible: showOpenCode, active: or.sessions > 0,
                         tint: Theme.opencode, content: AnyView(tokenUsageBlock(title: "OpenCode", or, tint: Theme.opencode, modelsOpen: $openCodeModelsOpen, toolID: "opencode"))),
            ToolCardItem(id: "qwencode", name: "Qwen Code", visible: showQwenCode, active: qcr.sessions > 0,
                         tint: Theme.qwencode, content: AnyView(tokenUsageBlock(title: "Qwen Code", qcr, tint: Theme.qwencode, modelsOpen: $qwenCodeModelsOpen, toolID: "qwencode"))),
            ToolCardItem(id: "qwenwork", name: "千问办公", visible: showQwenWork,
                         active: qwenWorkQuotaEnabled || u.qwenwork.available ||
                             u.qwenwork.remaining != nil || !u.qwenwork.segments.isEmpty ||
                             u.qwenwork.shared != nil,
                         tint: Theme.qwenwork, content: AnyView(qwenWorkBlock(u.qwenwork))),
            ToolCardItem(id: "kimicode", name: "Kimi Code", visible: showKimiCode, active: kcr.sessions > 0,
                         tint: Theme.kimicode, content: AnyView(tokenUsageBlock(title: "Kimi Code", kcr, tint: Theme.kimicode, modelsOpen: $kimiCodeModelsOpen, showsCost: false, toolID: "kimicode"))),
        ]
    }

    @ViewBuilder
    private func toolCardsLayout(_ cards: [ToolCardItem]) -> some View {
        let compactCards = cards.filter { $0.presentation == .compactStatus }
        let standardCards = cards.filter { $0.presentation == .standard }
        if useWide {
            VStack(spacing: 13) {
                if !compactCards.isEmpty {
                    EqualHeightGrid(columns: compactCards.count == 1 ? 1 : 2) {
                        ForEach(compactCards) { item in
                            Card(tint: item.tint) { item.content }
                                .id(cardContentIdentity(for: item))
                        }
                    }
                }
                if !standardCards.isEmpty {
                    EqualHeightGrid() {
                        ForEach(standardCards) { item in
                            Card(tint: item.tint) { item.content }
                                .id(cardContentIdentity(for: item))
                        }
                    }
                }
            }
        } else {
            VStack(spacing: 13) {
                ForEach(compactCards + standardCards) { item in
                    Card(tint: item.tint) { item.content }
                        .id(cardContentIdentity(for: item))
                }
            }
        }
    }

    private func cardContentIdentity(for item: ToolCardItem) -> String {
        let presentation = item.presentation == .compactStatus ? "compact" : "standard"
        return "\(item.id):\(presentation):\(sel.rawValue):\(store.syncEnabled):\(store.showAllDevices)"
    }

    // MARK: - Claude 卡片
    @ViewBuilder
    func claudeBlock(_ c: ClaudeStat, _ r: ClaudeRange) -> some View {
        let quotaState = SubscriptionQuotaState.resolve([
            (value: c.q5, stale: c.q5_stale),
            (value: c.q7, stale: c.q7_stale),
            (value: c.qf, stale: c.qf_stale),
        ])
        let compactExpired = quotaState.shouldUseCompactCard(hasUsage: r.sessions > 0)
        VStack(alignment: .leading, spacing: 11) {
            cardHead("Claude Code", tint: Theme.claude, sessions: r.sessions, toolID: "claude")
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
                    return ModelRow(name: m.name, pin: m.pin, pout: m.pout, cost: m.cost, total: m.total, hit: hit,
                                   tokIn: m.in, tokOut: m.out, tokCR: m.cr, tokCW: m.cw)
                }
                if !claudeRows.isEmpty {
                    modelDisclosure(claudeRows, open: $claudeModelsOpen, tint: Theme.claude)
                }
            } else if !compactExpired && quotaState != .unavailable {
                usageEmptyHint
            }

            if compactExpired {
                quotaStateNotice(
                    title: "额度数据已过期",
                    detail: "等待 Claude Code 写入新的额度缓存，恢复后将自动展示。",
                    source: "Claude Code 本地缓存",
                    updated: c.q_updated,
                    tint: Theme.claude,
                    warning: true
                )
            } else if quotaState != .unavailable {
                thinDivider
                if let q5 = c.q5, c.q5_stale != true {
                    quotaRow(title: "5h 剩余", pct: 100 - q5, reset: c.q5_reset, tint: Theme.claude)
                }
                if let q7 = c.q7, c.q7_stale != true {
                    quotaRow(title: "周 · 全部剩余", pct: 100 - q7, reset: c.q7_reset, tint: Theme.claude)
                }
                if let qf = c.qf, c.qf_stale != true {
                    quotaRow(title: "周 · Fable 剩余", pct: 100 - qf, reset: c.qf_reset, tint: .orange)
                }
                if quotaState == .expired {
                    quotaStateNotice(
                        title: "额度数据已过期",
                        detail: "当前用量仍可查看；新额度缓存写入后会自动恢复。",
                        source: "Claude Code 本地缓存",
                        updated: c.q_updated,
                        tint: Theme.claude,
                        warning: true
                    )
                } else {
                    claudeQuotaStatus(c)
                }
            } else if r.sessions > 0 {
                thinDivider
                quotaStateNotice(
                    title: "暂未获取到额度数据",
                    detail: "用量统计不受影响；检测到订阅额度后会自动展示。",
                    source: "Claude Code 本地缓存",
                    updated: c.q_updated,
                    tint: Theme.claude
                )
            }
        }
    }

    // MARK: - Codex 卡片
    @ViewBuilder
    func codexBlock(_ x: CodexStat, _ r: CodexRange) -> some View {
        let hasQuotaData = x.p5 != nil || x.pw != nil || (x.reset_cards?.count ?? 0) > 0
        VStack(alignment: .leading, spacing: 11) {
            cardHead("Codex", tint: Theme.codex, sessions: r.sessions, toolID: "codex")
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
                if !r.models.isEmpty {
                    tokenModelDisclosure(r.models, open: $codexModelsOpen, tint: Theme.codex,
                                         reasonIncludedInOutput: true)
                }
            } else if hasQuotaData {
                usageEmptyHint
            }
            if hasQuotaData {
                thinDivider
            }
            if let p5 = x.p5, x.p5_stale != true {
                quotaRow(title: "5h 剩余", pct: 100 - p5, reset: x.r5, tint: Theme.codex)
            }
            if let pw = x.pw, x.pw_stale != true {
                quotaRow(title: "周剩余", pct: 100 - pw, reset: x.rw, tint: Theme.codex)
            }
            if x.pw_stale == true {
                codexQuotaStatus(x)
            }
            if let cards = x.reset_cards, cards.count > 0 {
                codexResetCardsRow(cards)
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
            if r.sessions > 0 && !hasQuotaData {
                thinDivider
                quotaStateNotice(
                    title: "暂未获取到额度数据",
                    detail: "用量统计不受影响；检测到订阅周期后会自动展示。",
                    source: "Codex 本地状态",
                    updated: nil,
                    tint: Theme.codex
                )
            }
        }
    }

    @ViewBuilder
    func codexResetCardsRow(_ cards: CodexResetCards) -> some View {
        let expirations = cards.expires.sorted()
        Button {
            withAnimation(.easeInOut(duration: 0.2)) {
                codexResetCardsOpen.toggle()
            }
        } label: {
            HStack(spacing: 6) {
                Image(systemName: "arrow.clockwise.circle.fill")
                    .font(.system(size: 10))
                    .foregroundStyle(Theme.codex)
                Text("重置卡")
                    .font(.system(size: 11))
                    .foregroundStyle(Theme.tSecondary)
                Text("\(cards.count) 张")
                    .font(.system(size: 10, weight: .semibold, design: .monospaced))
                    .foregroundStyle(Theme.tPrimary)
                Spacer(minLength: 6)
                if let nearest = expirations.first {
                    Text("最近 \(Fmt.beijingTime(nearest)) · 北京时间")
                        .font(.system(size: 9.5, design: .monospaced))
                        .foregroundStyle(Theme.tTertiary)
                }
                Image(systemName: codexResetCardsOpen ? "chevron.down" : "chevron.right")
                    .font(.system(size: 8, weight: .bold))
                    .foregroundStyle(Theme.tTertiary)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help("查看重置卡到期时间")

        if codexResetCardsOpen {
            VStack(alignment: .leading, spacing: 7) {
                HStack {
                    Text("到期时间")
                        .font(.system(size: 9.5, weight: .medium))
                        .foregroundStyle(Theme.tTertiary)
                    Spacer()
                    Text("北京时间 UTC+8")
                        .font(.system(size: 9, design: .monospaced))
                        .foregroundStyle(Theme.tTertiary)
                }
                ForEach(Array(expirations.enumerated()), id: \.offset) { index, expiry in
                    HStack(spacing: 7) {
                        Text("\(index + 1)")
                            .font(.system(size: 9, weight: .semibold, design: .monospaced))
                            .foregroundStyle(Theme.codex)
                            .frame(width: 16, height: 16)
                            .background(Circle().fill(Theme.codex.opacity(0.14)))
                        Text("完整重置")
                            .font(.system(size: 10.5, weight: .medium))
                            .foregroundStyle(Theme.tSecondary)
                        Spacer()
                        Text(Fmt.beijingTime(expiry, full: true))
                            .font(.system(size: 9.5, design: .monospaced))
                            .foregroundStyle(Theme.tPrimary)
                    }
                }
            }
            .padding(9)
            .background(
                RoundedRectangle(cornerRadius: 7, style: .continuous)
                    .fill(Color.primary.opacity(0.05))
            )
        }
    }

    // MARK: - Gemini / Antigravity 卡片
    @ViewBuilder
    func geminiBlock(
        _ r: GeminiRange,
        quota: ProviderQuotaStat,
        displayedRange: RangeKey? = nil
    ) -> some View {
        let usageLabel = (displayedRange ?? sel).label
        VStack(alignment: .leading, spacing: 11) {
            cardHead("Gemini / Antigravity", tint: Theme.gemini, sessions: r.sessions,
                     toolID: r.hasUsage ? "gemini" : nil)
            if r.hasUsage {
                if let displayedRange, displayedRange != sel {
                    Text("\(sel.label)暂无用量，显示\(displayedRange.label)最近用量")
                        .font(.system(size: 9.5))
                        .foregroundStyle(Theme.tTertiary)
                }
                CostHeadline(value: Fmt.human(r.totalTokens), caption: "\(usageLabel) 总量", tint: Theme.gemini)
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
                        return ModelRow(name: m.name, pin: m.pin, pout: m.pout, cost: m.cost, total: total, hit: hit,
                                        tokIn: m.in, tokOut: m.out, tokCR: m.cached, tokCW: m.thoughts)
                    }
                    modelDisclosure(geminiRows, open: $geminiModelsOpen, tint: Theme.gemini,
                                    periodLabel: usageLabel)
                }
            } else {
                quota.available ? AnyView(usageEmptyHint) : AnyView(emptyHint)
            }
            if quota.available {
                if r.hasUsage { thinDivider }
                providerQuotaContent(quota, tint: Theme.gemini)
            }
        }
    }

    // MARK: - CodexBar-compatible quota providers
    @ViewBuilder
    func providerQuotaBlock(
        _ title: String,
        quota: ProviderQuotaStat,
        usage: TokenUsageRange? = nil,
        modelsOpen: Binding<Bool>? = nil,
        tint: Color,
        setupHint: String
    ) -> some View {
        let range = usage ?? TokenUsageRange()
        let hasUsage = range.totalTokens > 0 || range.requests > 0
        VStack(alignment: .leading, spacing: 11) {
            cardHeadPlain(title, tint: tint)
            if hasUsage {
                providerTokenUsageContent(range, modelsOpen: modelsOpen, tint: tint)
            }
            if quota.available {
                if hasUsage { thinDivider }
                providerQuotaContent(quota, tint: tint)
            } else if !hasUsage {
                Text(setupHint)
                    .font(.system(size: 10))
                    .foregroundStyle(Theme.tTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    func providerTokenUsageContent(
        _ r: TokenUsageRange,
        modelsOpen: Binding<Bool>?,
        tint: Color
    ) -> some View {
        var top: [Metric] = []
        if r.cost > 0 {
            top.append(.init("dollarsign.circle", "API 价", String(format: "$%.2f", r.cost)))
        }
        if r.requests > 0 {
            top.append(.init("arrow.triangle.2.circlepath", "请求", Fmt.human(r.requests)))
        }
        var details: [Metric] = []
        if r.hasComponents {
            details = [
                .init("arrow.down", "输入", Fmt.human(r.in)),
                .init("arrow.up", "输出", Fmt.human(r.out)),
            ]
            if r.cr > 0 { details.append(.init("bolt.fill", "缓存读", Fmt.human(r.cr))) }
            if r.cw > 0 {
                details.append(.init("square.stack.3d.up.fill", "缓存写", Fmt.human(r.cw)))
            }
            if r.reason > 0 { details.append(.init("brain", "推理", Fmt.human(r.reason))) }
        }
        return VStack(alignment: .leading, spacing: 9) {
            CostHeadline(
                value: Fmt.human(r.totalTokens),
                caption: "\(r.coverage ?? sel.label) 账号总量",
                tint: tint
            )
            Text("账号级用量 · 单列统计，避免与本地工具日志重复计算")
                .font(.system(size: 8.5))
                .foregroundStyle(Theme.tTertiary)
            if !top.isEmpty || !details.isEmpty {
                metricGrid(top, hit: r.hit, extra: details, tint: tint)
            }
            if !r.models.isEmpty, let modelsOpen {
                tokenModelDisclosure(r.models, open: modelsOpen, tint: tint)
            }
        }
    }

    @ViewBuilder
    func providerQuotaContent(_ quota: ProviderQuotaStat, tint: Color) -> some View {
        if quota.plan != nil || quota.account != nil {
            HStack(spacing: 6) {
                if let plan = quota.plan, !plan.isEmpty {
                    providerQuotaPill(plan, tint: tint)
                }
                if let account = quota.account, !account.isEmpty {
                    Text(account)
                        .font(.system(size: 9, design: .monospaced))
                        .foregroundStyle(Theme.tTertiary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
                Spacer(minLength: 0)
            }
        }

        ForEach(quota.windows) { window in
            if window.usage_known, let used = window.used_pct {
                quotaRow(
                    title: window.title,
                    pct: max(0, min(100, 100 - used)),
                    detail: window.detail,
                    reset: window.reset,
                    tint: tint
                )
            } else {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(window.title)
                        .font(.system(size: 11))
                        .foregroundStyle(Theme.tSecondary)
                    Spacer(minLength: 6)
                    Text(window.detail ?? "额度比例未知")
                        .font(.system(size: 9.5, design: .monospaced))
                        .foregroundStyle(Theme.tTertiary)
                        .multilineTextAlignment(.trailing)
                }
            }
        }

        if !quota.details.isEmpty {
            thinDivider
            VStack(spacing: 6) {
                ForEach(Array(quota.details.prefix(12).enumerated()), id: \.offset) { item in
                    let detail = item.element
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(detail.label)
                            .font(.system(size: 10))
                            .foregroundStyle(Theme.tTertiary)
                        Spacer(minLength: 8)
                        VStack(alignment: .trailing, spacing: 1) {
                            Text(providerQuotaDetailValue(detail))
                                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                                .foregroundStyle(Theme.tPrimary)
                            if let secondary = detail.secondary, !secondary.isEmpty {
                                Text(secondary)
                                    .font(.system(size: 8.5, design: .monospaced))
                                    .foregroundStyle(Theme.tTertiary)
                                    .multilineTextAlignment(.trailing)
                            }
                        }
                    }
                }
            }
        }

        if quota.stale {
            quotaStateNotice(
                title: "额度数据已过期",
                detail: "当前展示最近一次成功结果；登录态或网络恢复后会自动刷新。",
                source: quota.source ?? "Provider 缓存",
                updated: quota.updated,
                tint: tint,
                warning: true
            )
        } else if let updated = quota.updated {
            HStack(spacing: 5) {
                Image(systemName: "clock")
                    .font(.system(size: 8.5))
                Text("额度更新于 \(Fmt.reset(updated))")
                    .font(.system(size: 9, design: .monospaced))
                Spacer(minLength: 4)
            }
            .foregroundStyle(Theme.tTertiary)
        }
    }

    func providerQuotaPill(_ text: String, tint: Color) -> some View {
        Text(text)
            .font(.system(size: 9.5, weight: .semibold, design: .monospaced))
            .foregroundStyle(Theme.tSecondary)
            .padding(.horizontal, 7)
            .padding(.vertical, 2)
            .background(Capsule().fill(tint.opacity(0.16)))
    }

    func providerQuotaDetailValue(_ detail: ProviderQuotaDetail) -> String {
        if detail.label.contains("到期"), let epoch = Int(detail.value) {
            return Fmt.reset(epoch)
        }
        return detail.value
    }

    // MARK: - Grok 卡片
    @ViewBuilder
    func grokBlock(_ g: GrokStat, _ r: GrokRange) -> some View {
        let hasUsage = r.sessions > 0 || r.usage_calls > 0
        let quotaState = SubscriptionQuotaState.resolve([
            (value: g.pct, stale: g.stale),
        ])
        let compactExpired = quotaState.shouldUseCompactCard(hasUsage: hasUsage)
        VStack(alignment: .leading, spacing: 11) {
            cardHead("Grok", tint: Theme.grok, sessions: r.sessions, toolID: "grok")
            if hasUsage {
                CostHeadline(value: Fmt.human(r.tokens),
                             caption: r.usage_available ? "\(sel.label) 真实用量" : "\(sel.label) 上下文快照",
                             tint: Theme.grok)
                let grokMetrics: [Metric] = {
                    var items: [Metric] = []
                    if r.usage_available {
                        if r.cost > 0 {
                            items.append(.init("dollarsign.circle", "≈成本", String(format: "$%.2f", r.cost)))
                        }
                        items.append(.init("arrow.down", "输入", Fmt.human(r.in)))
                        items.append(.init("bolt.fill", "缓存读", Fmt.human(r.cr)))
                        items.append(.init("arrow.up", "输出", Fmt.human(r.out)))
                        if r.reason > 0 { items.append(.init("brain", "推理", Fmt.human(r.reason))) }
                        items.append(.init("waveform", "调用", "\(r.usage_calls)"))
                    }
                    items.append(contentsOf: [
                        .init("arrow.triangle.2.circlepath", "轮次", "\(r.turns ?? 0)"),
                        .init("wrench.and.screwdriver", "工具", "\(r.tools ?? 0)"),
                    ])
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
                }()
                metricGrid([], hit: r.usage_available ? r.hit : 0,
                           extra: grokMetrics, tint: Theme.grok)
                if r.usage_available && !r.models.isEmpty {
                    tokenModelDisclosure(r.models, open: $grokModelsOpen, tint: Theme.grok)
                } else if let model = g.model, !model.isEmpty {
                    modelBadge(model, tint: Theme.grok)
                }
                Text(r.usage_available
                     ? (r.cost > 0
                        ? "来自 Grok Build 本地推理日志；成本按 API 价估算，订阅实付不按此。"
                        : "来自 Grok Build 本地推理日志；当前模型未匹配到公开价格。")
                     : "旧版日志未保存真实用量，当前仅展示上下文与执行指标。")
                    .font(.system(size: 8.5))
                    .foregroundStyle(Theme.tTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            } else if !compactExpired && quotaState != .unavailable {
                usageEmptyHint
            }

            if compactExpired {
                quotaStateNotice(
                    title: "额度周期已结束",
                    detail: "Grok 写入新周期日志后，将自动恢复额度展示。",
                    source: grokQuotaSourceLabel(g.source),
                    updated: g.q_updated,
                    tint: Theme.grok,
                    warning: true
                )
            } else if let pct = g.pct, g.stale != true {
                if hasUsage { thinDivider }
                let title = (g.window == "month") ? "月剩余" : "周剩余"
                // 总剩余：同一周额度池。分产品 usagePercent 是该产品在池内的占用占比，不是独立额度剩余。
                quotaRow(title: title, pct: 100 - pct, reset: g.reset, tint: Theme.grok)
                ForEach(g.products.filter { $0.pct != nil }) { product in
                    if let used = product.pct {
                        grokProductShareRow(
                            name: Self.grokProductLabel(product.name),
                            usedPct: used,
                            tint: Theme.grok,
                            help: Self.grokProductHelp(product.name)
                        )
                    }
                }
                if let plan = g.plan, !plan.isEmpty {
                    HStack {
                        Text("plan").font(.system(size: 11)).foregroundStyle(Theme.tTertiary)
                        Spacer()
                        Text(plan)
                            .font(.system(size: 10, weight: .semibold, design: .monospaced))
                            .foregroundStyle(Theme.tSecondary)
                            .padding(.horizontal, 7).padding(.vertical, 2)
                            .background(Capsule().fill(Theme.grok.opacity(0.16)))
                    }
                }
                grokQuotaStatus(g)
            } else if quotaState == .expired {
                if hasUsage { thinDivider }
                quotaStateNotice(
                    title: "额度周期已结束",
                    detail: "当前用量仍可查看；新周期日志写入后会自动恢复。",
                    source: grokQuotaSourceLabel(g.source),
                    updated: g.q_updated,
                    tint: Theme.grok,
                    warning: true
                )
            } else if hasUsage {
                thinDivider
                quotaStateNotice(
                    title: "暂未获取到额度数据",
                    detail: "用量统计不受影响；检测到订阅周期后会自动展示。",
                    source: grokQuotaSourceLabel(g.source),
                    updated: g.q_updated,
                    tint: Theme.grok
                )
            }
        }
    }

    func grokQuotaStatus(_ stat: GrokStat) -> some View {
        let sourceLabel = grokQuotaSourceLabel(stat.source)
        let updated = stat.q_updated.map { Fmt.reset($0) } ?? "更新时间未知"
        return HStack(spacing: 5) {
            Image(systemName: "clock")
                .font(.system(size: 9))
            Text("额度来源 \(sourceLabel) · \(updated)")
                .font(.system(size: 9.5, design: .monospaced))
            Spacer()
        }
        .foregroundStyle(Theme.tTertiary)
        .help(stat.source == "live"
              ? "已开启 Grok 实时额度查询。Grok Build / API 等为同一周额度池内的占用拆分，共享上方重置时间。"
              : "默认只读 ~/.grok 本地日志，不访问网络")
    }

    private func grokQuotaSourceLabel(_ source: String?) -> String {
        switch source {
        case "live": return "Grok 实时接口"
        case "cache": return "Grok 本地缓存"
        default: return "Grok 本地日志"
        }
    }

    /// 账单 product 字段 → 更可读的名称。
    static func grokProductLabel(_ raw: String) -> String {
        switch raw.lowercased() {
        case "grokbuild": return "Grok Build（本机 CLI）"
        case "api": return "开放 API（api.x.ai）"
        case "grokchat": return "Grok 网页聊天"
        default: return raw
        }
    }

    /// 分产品占用说明（悬停 / 辅助读屏）。
    static func grokProductHelp(_ raw: String) -> String {
        switch raw.lowercased() {
        case "grokbuild":
            return "Grok Build / 本机 CLI 编程消耗，占用本周统一额度池的比例。"
        case "api":
            return "通过 xAI 开放 API（api.x.ai / Console 密钥）调用模型的消耗，与 CLI 共用同一周额度池。"
        case "grokchat":
            return "grok.com 网页聊天消耗，与 CLI / 开放 API 共用同一周额度池。"
        default:
            return "该产品在本周统一额度池中的占用比例（与周剩余共用同一重置时间）。"
        }
    }

    /// 分产品占用：显示该产品在统一周额度里占了多少，不展示独立重置时间。
    func grokProductShareRow(name: String, usedPct: Double, tint: Color, help: String) -> some View {
        VStack(spacing: 4) {
            HStack {
                Text(name)
                    .font(.system(size: 11))
                    .foregroundStyle(Theme.tSecondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.78)
                Spacer(minLength: 6)
                Text(String(format: "占用 %.0f%%", usedPct))
                    .font(.system(size: 12, weight: .semibold, design: .monospaced))
                    .foregroundStyle(Theme.tPrimary)
            }
            MiniBar(value: max(0, min(100, 100 - usedPct)), tint: tint.opacity(0.75))
        }
        .help(help)
    }

    // MARK: - 千问办公额度卡片
    @ViewBuilder
    func qwenWorkBlock(_ quota: QwenWorkQuota) -> some View {
        VStack(alignment: .leading, spacing: 11) {
            cardHeadPlain("千问办公", tint: Theme.qwenwork)

            if quota.available || quota.remaining != nil || !quota.segments.isEmpty || quota.shared != nil {
                if quota.exceeded {
                    HStack(spacing: 6) {
                        Image(systemName: "exclamationmark.triangle.fill")
                        Text("官方额度状态：已用尽")
                    }
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(Color.red.opacity(0.92))
                }

                if let remaining = quota.remaining {
                    CostHeadline(
                        value: Fmt.credits(remaining),
                        caption: quota.is_team ? "团队账号个人可用积分" : "个人可用积分",
                        tint: Theme.qwenwork
                    )
                }

                // 有明确比例时才画进度条。部分千问办公套餐只返回绝对积分余额。
                if let remainingPct = quota.remaining_pct {
                    quotaRow(
                        title: "综合剩余比例",
                        pct: max(0, min(100, remainingPct)),
                        reset: nil,
                        tint: Theme.qwenwork
                    )
                }

                if let expiresAt = quota.expires_at {
                    qwenWorkDateRow("额度有效期", epoch: expiresAt)
                }
                if let planExpiration = quota.plan_expiration,
                   planExpiration != quota.expires_at {
                    qwenWorkDateRow("套餐有效期", epoch: planExpiration)
                }

                if !quota.segments.isEmpty {
                    thinDivider
                    Text("个人积分明细")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(Theme.tSecondary)
                    ForEach(Array(quota.segments.enumerated()), id: \.offset) { item in
                        qwenWorkSegmentRow(item.element)
                    }
                }

                if let shared = quota.shared {
                    thinDivider
                    qwenWorkSharedBlock(shared)
                }

                qwenWorkQuotaStatus(quota)
            } else if qwenWorkQuotaEnabled {
                Text("未读取到额度。请确认千问办公已登录并保持运行。")
                    .font(.system(size: 10))
                    .foregroundStyle(Theme.tTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                Text("在设置的「隐私与额度」中开启查询后显示。")
                    .font(.system(size: 10))
                    .foregroundStyle(Theme.tTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    func qwenWorkSegmentRow(_ segment: QwenWorkQuotaSegment) -> some View {
        let remainingPct = ((segment.total ?? 0) > 0)
            ? segment.percentage_used.map { max(0, min(100, 100 - $0)) }
            : nil
        return VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(Self.qwenWorkSegmentLabel(segment))
                    .font(.system(size: 11))
                    .foregroundStyle(Theme.tSecondary)
                    .lineLimit(1)
                Spacer(minLength: 6)
                if let remaining = segment.remaining {
                    Text("剩余 \(Fmt.credits(remaining)) \(Self.qwenWorkUnitLabel(segment.unit))")
                        .font(.system(size: 11, weight: .semibold, design: .monospaced))
                        .foregroundStyle(Theme.tPrimary)
                }
            }

            if let total = segment.total, total > 0 {
                let used = segment.used.map(Fmt.credits) ?? "?"
                Text("已用 \(used) / 总量 \(Fmt.credits(total))")
                    .font(.system(size: 9, design: .monospaced))
                    .foregroundStyle(Theme.tTertiary)
            }

            if let remainingPct {
                HStack(spacing: 6) {
                    MiniBar(value: remainingPct, tint: remainingPct <= 15 ? .red : Theme.qwenwork)
                    Text(String(format: "%.0f%%", remainingPct))
                        .font(.system(size: 9.5, weight: .semibold, design: .monospaced))
                        .foregroundStyle(remainingPct <= 15 ? Color.red : Theme.tSecondary)
                }
            }

            if let renewsAt = segment.renews_at {
                qwenWorkDateRow("续期", epoch: renewsAt)
            } else if let expiresAt = segment.expires_at {
                qwenWorkDateRow("到期", epoch: expiresAt)
            }
        }
        .padding(.vertical, 1)
    }

    func qwenWorkSharedBlock(_ shared: QwenWorkSharedQuota) -> some View {
        let remainingPct = ((shared.total ?? 0) > 0)
            ? shared.percentage_used.map { max(0, min(100, 100 - $0)) }
            : nil
        return VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text("团队共享资源包")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(Theme.tSecondary)
                Spacer(minLength: 6)
                if let remaining = shared.remaining {
                    Text("剩余 \(Fmt.credits(remaining)) \(Self.qwenWorkUnitLabel(shared.unit))")
                        .font(.system(size: 11, weight: .semibold, design: .monospaced))
                        .foregroundStyle(Theme.tPrimary)
                }
            }
            Text("共享包独立展示，不计入上方个人积分")
                .font(.system(size: 8.5))
                .foregroundStyle(Theme.tTertiary)
            if let total = shared.total, total > 0 {
                let used = shared.used.map(Fmt.credits) ?? "?"
                Text("已用 \(used) / 总量 \(Fmt.credits(total))")
                    .font(.system(size: 9, design: .monospaced))
                    .foregroundStyle(Theme.tTertiary)
            }
            if let remainingPct {
                HStack(spacing: 6) {
                    MiniBar(value: remainingPct, tint: remainingPct <= 15 ? .red : Theme.qwenwork)
                    Text(String(format: "%.0f%%", remainingPct))
                        .font(.system(size: 9.5, weight: .semibold, design: .monospaced))
                        .foregroundStyle(remainingPct <= 15 ? Color.red : Theme.tSecondary)
                }
            }
            if let expiresAt = shared.expires_at {
                qwenWorkDateRow("共享包到期", epoch: expiresAt)
            }
        }
    }

    func qwenWorkDateRow(_ label: String, epoch: Int) -> some View {
        HStack(spacing: 5) {
            Image(systemName: "calendar")
                .font(.system(size: 8.5))
            Text("\(label) · \(Fmt.reset(epoch))")
                .font(.system(size: 9.5, design: .monospaced))
            Spacer()
        }
        .foregroundStyle(Theme.tTertiary)
    }

    func qwenWorkQuotaStatus(_ quota: QwenWorkQuota) -> some View {
        let sourceLabel: String
        switch quota.source {
        case "mcp", "local_mcp": sourceLabel = "本机 QwenWork 接口"
        case "cache": sourceLabel = "本地缓存"
        default: sourceLabel = "额度数据"
        }
        let updated = quota.updated.map { Fmt.reset($0) } ?? "更新时间未知"
        return HStack(spacing: 5) {
            Image(systemName: quota.stale ? "exclamationmark.triangle.fill" : "clock")
                .font(.system(size: 9))
            Text("\(quota.stale ? "缓存可能已过期" : sourceLabel) · \(updated)")
                .font(.system(size: 9.5, design: .monospaced))
            Spacer()
        }
        .foregroundStyle(quota.stale ? Color.orange.opacity(0.88) : Theme.tTertiary)
        .help("Tokei 仅通过千问办公桌面端的本机 QwenWork 接口读取额度，不读取或保存登录凭据。")
    }

    static func qwenWorkSegmentLabel(_ segment: QwenWorkQuotaSegment) -> String {
        let key = segment.id.isEmpty ? segment.kind : segment.id
        switch key.lowercased().replacingOccurrences(of: "-", with: "_") {
        case "plan", "plan_credits": return "套餐积分"
        case "addon", "add_on", "add_on_credits": return "加购积分"
        case "shared_addon", "shared_add_on", "shared_add_on_credits": return "共享加购积分"
        default: return key.isEmpty ? "积分" : key
        }
    }

    static func qwenWorkUnitLabel(_ unit: String?) -> String {
        guard let unit, !unit.isEmpty else { return "积分" }
        return ["credit", "credits"].contains(unit.lowercased()) ? "积分" : unit
    }

    // MARK: - Qoder IDE 卡片
    @ViewBuilder
    func qoderIdeBlock(_ q: QoderIdeStat, _ r: QoderIdeRange) -> some View {
        VStack(alignment: .leading, spacing: 11) {
            cardHeadPlain("Qoder Desktop", tint: Theme.qoder, toolID: "qoder")
            if r.calls > 0 {
                let total = r.in + r.cached + r.out
                if total > 0 {
                    CostHeadline(value: Fmt.human(total), caption: "\(sel.label) 总量", tint: Theme.qoder)
                }
                metricGrid({
                    var items: [Metric] = [
                        .init("terminal", "模型调用", "\(r.calls)"),
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
            cardHeadPlain("QoderWork", tint: Theme.qoderwork, toolID: "qoderwork")
            if r.calls > 0 {
                metricGrid({
                    var items: [Metric] = [
                        .init("terminal", "任务", "\(r.calls)"),
                        .init("person.2", "会话", "\(r.sessions)"),
                        .init("clock", "耗时", Fmt.duration(r.duration)),
                    ]
                    if r.sub_agents > 0 {
                        items.append(.init("point.3.connected.trianglepath.dotted", "子agent", "\(r.sub_agents)"))
                    }
                    if r.turns > 0 {
                        items.append(.init("bubble.left.and.bubble.right", "模型调用", Fmt.human(r.turns)))
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

    // MARK: - Qoder CLI 卡片(仅活跃维度:qodercli 本地不落 token 数)
    @ViewBuilder
    func qodercliBlock(_ q: QoderStat, _ r: QoderRange) -> some View {
        VStack(alignment: .leading, spacing: 11) {
            cardHeadPlain("Qoder CLI", tint: Theme.qodercli, toolID: "qodercli")
            if r.calls > 0 {
                metricGrid({
                    var items: [Metric] = [
                        .init("terminal", "模型调用", "\(r.calls)"),
                        .init("person.2", "会话", "\(r.sessions)"),
                        .init("bubble.left.and.bubble.right", "消息数", Fmt.human(r.turns)),
                        .init("clock", "活跃", Fmt.duration(r.duration)),
                    ]
                    if r.tools > 0 {
                        items.append(.init("wrench.and.screwdriver", "工具调用", Fmt.human(r.tools)))
                    }
                    if r.sub_agents > 0 {
                        items.append(.init("point.3.connected.trianglepath.dotted", "子agent", "\(r.sub_agents)"))
                    }
                    return items
                }(), tint: Theme.qodercli)
                if let model = q.model, !model.isEmpty {
                    modelBadge(model, tint: Theme.qodercli)
                }
            } else {
                emptyHint
            }
        }
    }

    // MARK: - Hermes 卡片
    @ViewBuilder
    func hermesBlock(_ r: HermesRange, modelsOpen: Binding<Bool>) -> some View {
        VStack(alignment: .leading, spacing: 11) {
            cardHead("Hermes", tint: Theme.hermes, sessions: r.sessions, toolID: "hermes")
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
                if !r.models.isEmpty {
                    tokenModelDisclosure(r.models, open: modelsOpen, tint: Theme.hermes)
                }
            } else {
                emptyHint
            }
        }
    }

    // MARK: - OpenClaw 卡片
    @ViewBuilder
    func openclawBlock(_ r: OpenClawRange, modelsOpen: Binding<Bool>) -> some View {
        VStack(alignment: .leading, spacing: 11) {
            cardHead("OpenClaw", tint: Theme.openclaw, sessions: r.sessions, toolID: "openclaw")
            if r.in + r.out + r.cr + r.cw + r.reason > 0 {
                CostHeadline(value: Fmt.human(r.in + r.out + r.cr + r.cw + r.reason), caption: "\(sel.label) 总量", tint: Theme.openclaw)
                metricGrid([.init("dollarsign.circle", "≈成本", String(format: "$%.2f", r.cost))],
                    hit: r.hit, extra: {
                    var items: [Metric] = [
                        .init("arrow.down", "输入", Fmt.human(r.in)),
                        .init("arrow.up", "输出", Fmt.human(r.out)),
                        .init("bolt.fill", "缓存读", Fmt.human(r.cr)),
                    ]
                    if r.reason > 0 { items.append(.init("brain", "推理", Fmt.human(r.reason))) }
                    if r.tasks > 0 { items.append(.init("checklist", "任务", "\(r.tasks)")) }
                    return items
                }(), tint: Theme.openclaw)
                if !r.models.isEmpty {
                    tokenModelDisclosure(r.models, open: modelsOpen, tint: Theme.openclaw)
                }
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
    func tokenUsageBlock(title: String, _ r: TokenUsageRange, tint: Color,
                         modelsOpen: Binding<Bool>, inclusiveIO: Bool = false,
                         showsCost: Bool = true, toolID: String? = nil) -> some View {
        VStack(alignment: .leading, spacing: 11) {
            cardHead(title, tint: tint, sessions: r.sessions, toolID: toolID)
            if r.sessions > 0 {
                CostHeadline(value: Fmt.human(r.in + r.out + r.cr + r.cw + r.reason), caption: "\(sel.label) 总量", tint: tint)
                metricGrid(showsCost ? [.init("dollarsign.circle", "≈成本", String(format: "$%.2f", r.cost))] : [],
                    hit: r.hit, extra: tokenUsageMetrics(r, inclusiveIO: inclusiveIO), tint: tint)
                if !r.models.isEmpty {
                    tokenModelDisclosure(r.models, open: modelsOpen, tint: tint,
                                         inclusiveIO: inclusiveIO)
                }
            } else {
                emptyHint
            }
        }
    }

    func tokenUsageMetrics(_ r: TokenUsageRange, inclusiveIO: Bool = false) -> [Metric] {
        if inclusiveIO {
            var items: [Metric] = [
                .init("arrow.down", "输入", Fmt.human(r.in + r.cr + r.cw)),
                .init("arrow.up", "输出", Fmt.human(r.out + r.reason)),
            ]
            if r.cr > 0 { items.append(.init("bolt.fill", "其中缓存读", Fmt.human(r.cr))) }
            if r.reason > 0 { items.append(.init("brain", "其中推理", Fmt.human(r.reason))) }
            if r.cw > 0 { items.append(.init("square.stack.3d.up.fill", "其中缓存写", Fmt.human(r.cw))) }
            return items
        }
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

    var usageEmptyHint: some View {
        Text("\(sel.label)暂无用量，额度状态如下")
            .font(.system(size: 10))
            .foregroundStyle(Theme.tTertiary)
    }

    func quotaStateNotice(
        title: String,
        detail: String,
        source: String,
        updated: Int?,
        tint: Color,
        warning: Bool = false
    ) -> some View {
        let statusTint = warning ? Color.orange : tint
        let updatedLabel = updated.map { "上次更新 \(Fmt.reset($0))" } ?? "尚无更新时间"
        return VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Image(systemName: warning ? "exclamationmark.triangle.fill" : "info.circle.fill")
                    .font(.system(size: 10, weight: .semibold))
                Text(title)
                    .font(.system(size: 11, weight: .semibold))
                Spacer(minLength: 4)
            }
            .foregroundStyle(statusTint.opacity(0.95))

            Text(detail)
                .font(.system(size: 9.5))
                .foregroundStyle(Theme.tSecondary)
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: 5) {
                Image(systemName: "clock")
                    .font(.system(size: 8.5))
                Text("\(source) · \(updatedLabel)")
                    .font(.system(size: 9, design: .monospaced))
                Spacer(minLength: 4)
            }
            .foregroundStyle(Theme.tTertiary)
        }
        .padding(9)
        .background(
            RoundedRectangle(cornerRadius: 9, style: .continuous)
                .fill(statusTint.opacity(0.07))
                .overlay(
                    RoundedRectangle(cornerRadius: 9, style: .continuous)
                        .strokeBorder(statusTint.opacity(0.16), lineWidth: 0.5)
                )
        )
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
        var tokIn: Int = 0
        var tokOut: Int = 0
        var tokCR: Int = 0
        var tokCW: Int = 0
        var id: String { name }
    }

    func tokenModelTotal(_ m: TokenModelStat, reasonIncludedInOutput: Bool = false) -> Int {
        if let tokens = m.tokens, tokens > 0 { return tokens }
        return m.in + m.out + m.cr + m.cw + (reasonIncludedInOutput ? 0 : m.reason)
    }

    func tokenModelHit(_ m: TokenModelStat) -> Double {
        let denom = m.cr + m.cw + m.in
        return denom > 0 ? Double(m.cr) / Double(denom) * 100 : 0
    }

    func cardHead(_ title: String, tint: Color, sessions: Int = 0, toolID: String? = nil) -> some View {
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
            if let toolID {
                cardCopyButton(toolID: toolID, tint: tint)
            }
        }
    }

    // 无命中环的卡头(Grok 无缓存命中数据)。
    func cardHeadPlain(_ title: String, tint: Color, toolID: String? = nil) -> some View {
        HStack(spacing: 7) {
            Circle().fill(tint.gradient).frame(width: 8, height: 8)
                .shadow(color: tint.opacity(0.6), radius: 3)
            Text(title).font(.system(size: 14, weight: .bold))
            Spacer()
            if let toolID {
                cardCopyButton(toolID: toolID, tint: tint)
            }
        }
    }

    @ViewBuilder
    private func cardCopyButton(toolID: String, tint: Color) -> some View {
        let done = copiedToolID == toolID
        Button {
            copySingleToolImage(id: toolID)
        } label: {
            Image(systemName: done ? "checkmark" : "photo.on.rectangle")
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(done ? tint : Theme.tTertiary)
                .frame(width: 22, height: 22)
                .background(Circle().fill(Color.primary.opacity(done ? 0.10 : 0.06)))
                .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .tip(done ? "已复制图片" : "复制此工具用量图")
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
    func tokenModelDisclosure(_ models: [TokenModelStat], open: Binding<Bool>, tint: Color,
                              reasonIncludedInOutput: Bool = false,
                              inclusiveIO: Bool = false) -> some View {
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
            VStack(alignment: .leading, spacing: 6) {
                Text("按模型 · \(sel.label)")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(Theme.tSecondary)
                ForEach(models) { m in
                    let total = tokenModelTotal(m, reasonIncludedInOutput: reasonIncludedInOutput)
                    let hit = tokenModelHit(m)
                    let hasBreakdown = m.in + m.out + m.cr + m.cw + m.reason > 0
                        || m.cost > 0 || m.pin > 0 || m.pout > 0
                    let isExpanded = expandedModels.contains(m.id)
                    VStack(alignment: .leading, spacing: 0) {
                        Button {
                            guard hasBreakdown else { return }
                            withAnimation(.easeInOut(duration: 0.2)) {
                                if isExpanded { expandedModels.remove(m.id) }
                                else { expandedModels.insert(m.id) }
                            }
                        } label: {
                            HStack(spacing: 7) {
                                if hasBreakdown {
                                    Image(systemName: isExpanded ? "chevron.down" : "chevron.right")
                                        .font(.system(size: 7, weight: .bold))
                                        .foregroundStyle(Theme.tTertiary)
                                        .frame(width: 8)
                                } else {
                                    Color.clear.frame(width: 8, height: 8)
                                }
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
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        if isExpanded && hasBreakdown {
                            modelDetailRow(tokIn: inclusiveIO ? m.in + m.cr + m.cw : m.in,
                                           tokOut: inclusiveIO ? m.out + m.reason : m.out,
                                           tokCR: m.cr, tokCW: m.cw,
                                           tokReason: m.reason,
                                           pin: m.pin, pout: m.pout, hit: hit, tint: tint,
                                           componentsAreSubtotals: inclusiveIO)
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
    func modelDisclosure(
        _ models: [ModelRow],
        open: Binding<Bool>,
        tint: Color,
        periodLabel: String? = nil
    ) -> some View {
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
            VStack(alignment: .leading, spacing: 6) {
                Text("按模型 · \(periodLabel ?? sel.label)")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(Theme.tSecondary)
                ForEach(models) { m in
                    let isExpanded = expandedModels.contains(m.id)
                    VStack(alignment: .leading, spacing: 0) {
                        Button {
                            withAnimation(.easeInOut(duration: 0.2)) {
                                if isExpanded { expandedModels.remove(m.id) }
                                else { expandedModels.insert(m.id) }
                            }
                        } label: {
                            HStack(spacing: 7) {
                                Image(systemName: isExpanded ? "chevron.down" : "chevron.right")
                                    .font(.system(size: 7, weight: .bold))
                                    .foregroundStyle(Theme.tTertiary)
                                    .frame(width: 8)
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
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        if isExpanded {
                            modelDetailRow(tokIn: m.tokIn, tokOut: m.tokOut, tokCR: m.tokCR, tokCW: m.tokCW,
                                           pin: m.pin, pout: m.pout, hit: m.hit, tint: tint)
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
    func modelDetailRow(tokIn: Int, tokOut: Int, tokCR: Int, tokCW: Int, tokReason: Int = 0,
                         pin: Double, pout: Double, hit: Double = 0, tint: Color,
                         componentsAreSubtotals: Bool = false) -> some View {
        let tagFont = Font.system(size: 9, weight: .medium, design: .monospaced)
        let labelFont = Font.system(size: 8.5)
        let bg = tint.opacity(0.08)
        let border = tint.opacity(0.18)
        HStack(spacing: 0) {
            Spacer().frame(width: 20)
            FlowLayout(spacing: 4) {
                detailTag("↓ \(Fmt.human(tokIn))", label: "输入", tagFont: tagFont, labelFont: labelFont, bg: bg, border: border)
                detailTag("↑ \(Fmt.human(tokOut))", label: "输出", tagFont: tagFont, labelFont: labelFont, bg: bg, border: border)
                if tokCR > 0 {
                    detailTag("⚡ \(Fmt.human(tokCR))", label: componentsAreSubtotals ? "其中缓存读" : "缓存读",
                              tagFont: tagFont, labelFont: labelFont, bg: bg, border: border)
                }
                if tokCW > 0 {
                    detailTag("✎ \(Fmt.human(tokCW))", label: componentsAreSubtotals ? "其中缓存写" : "缓存写",
                              tagFont: tagFont, labelFont: labelFont, bg: bg, border: border)
                }
                if tokReason > 0 {
                    detailTag("◉ \(Fmt.human(tokReason))", label: componentsAreSubtotals ? "其中推理" : "推理",
                              tagFont: tagFont, labelFont: labelFont, bg: bg, border: border)
                }
                if hit > 0 {
                    HStack(spacing: 2) {
                        Text("命中").font(labelFont).foregroundStyle(Theme.tTertiary)
                        Text(String(format: "%.0f%%", hit)).font(tagFont).foregroundStyle(tint)
                    }
                    .padding(.horizontal, 6).padding(.vertical, 2.5)
                    .background(Capsule().fill(bg))
                    .overlay(Capsule().strokeBorder(border, lineWidth: 0.5))
                }
                if pin > 0 || pout > 0 {
                    HStack(spacing: 2) {
                        Text("$").font(tagFont).foregroundStyle(tint)
                        Text("\(String(format: "%.2g", pin))/\(String(format: "%.2g", pout))")
                            .font(tagFont).foregroundStyle(tint)
                    }
                    .padding(.horizontal, 6).padding(.vertical, 2.5)
                    .background(Capsule().fill(tint.opacity(0.12)))
                    .overlay(Capsule().strokeBorder(tint.opacity(0.25), lineWidth: 0.5))
                }
            }
        }
        .padding(.top, 5).padding(.bottom, 2)
        .transition(.opacity.combined(with: .move(edge: .top)))
    }

    func detailTag(_ value: String, label: String, tagFont: Font, labelFont: Font,
                    bg: Color, border: Color) -> some View {
        HStack(spacing: 3) {
            Text(label).font(labelFont).foregroundStyle(Theme.tTertiary)
            Text(value).font(tagFont).foregroundStyle(Theme.tSecondary)
        }
        .padding(.horizontal, 6).padding(.vertical, 2.5)
        .background(Capsule().fill(bg))
        .overlay(Capsule().strokeBorder(border, lineWidth: 0.5))
    }

    struct FlowLayout: Layout {
        var spacing: CGFloat = 4
        func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
            let rows = computeRows(proposal: proposal, subviews: subviews)
            let height = rows.enumerated().reduce(CGFloat(0)) { acc, pair in
                let rowHeight = pair.element.map { $0.size.height }.max() ?? 0
                return acc + rowHeight + (pair.offset > 0 ? spacing : 0)
            }
            return CGSize(width: proposal.width ?? 0, height: height)
        }
        func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
            let rows = computeRows(proposal: proposal, subviews: subviews)
            var y = bounds.minY
            for row in rows {
                let rowHeight = row.map { $0.size.height }.max() ?? 0
                var x = bounds.minX
                for item in row {
                    item.subview.place(at: CGPoint(x: x, y: y + (rowHeight - item.size.height) / 2),
                                       proposal: ProposedViewSize(item.size))
                    x += item.size.width + spacing
                }
                y += rowHeight + spacing
            }
        }
        private struct RowItem {
            let subview: LayoutSubview
            let size: CGSize
        }
        private func computeRows(proposal: ProposedViewSize, subviews: Subviews) -> [[RowItem]] {
            let maxW = proposal.width ?? .infinity
            var rows: [[RowItem]] = [[]]
            var x: CGFloat = 0
            for sv in subviews {
                let size = sv.sizeThatFits(.unspecified)
                if !rows[rows.count - 1].isEmpty && x + size.width > maxW {
                    rows.append([])
                    x = 0
                }
                rows[rows.count - 1].append(RowItem(subview: sv, size: size))
                x += size.width + spacing
            }
            return rows
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
                Text(SubscriptionQuotaPresentation.remainingLabel(pct))
                    .font(.system(size: 12, weight: .semibold, design: .monospaced))
                    .foregroundStyle(pct <= 15 ? AnyShapeStyle(.red) : AnyShapeStyle(Theme.tPrimary))
                // 无重置时间时不显示「· ?」，避免分产品行误导。
                if reset != nil {
                    Text("· \(Fmt.reset(reset))")
                        .font(.system(size: 9.5, design: .monospaced))
                        .foregroundStyle(Theme.tTertiary)
                }
            }
            MiniBar(value: pct, tint: pct <= 15 ? .red : tint)
        }
        .help(reset != nil ? "\(Fmt.countdown(reset)) 后重置" : "")
    }

    func claudeQuotaStatus(_ stat: ClaudeStat) -> some View {
        let staleCount = [stat.q5_stale, stat.q7_stale, stat.qf_stale].filter { $0 == true }.count
        let hasFreshQuota = (stat.q5 != nil && stat.q5_stale != true) ||
            (stat.q7 != nil && stat.q7_stale != true) ||
            (stat.qf != nil && stat.qf_stale != true)
        let stale = staleCount > 0
        let label: String
        if stale {
            label = hasFreshQuota ? "部分额度待更新" : "额度数据已过期"
        } else {
            label = "额度更新"
        }
        let updated = stat.q_updated.map { Fmt.reset($0) } ?? "更新时间未知"
        return HStack(spacing: 5) {
            Image(systemName: stale ? "exclamationmark.triangle.fill" : "clock")
                .font(.system(size: 9))
            Text("\(label) · \(updated)")
                .font(.system(size: 9.5, design: .monospaced))
            Spacer()
        }
        .foregroundStyle(stale ? Color.orange.opacity(0.88) : Theme.tTertiary)
        .help(stale ? "等待 Claude Desktop 写入新的额度缓存" : "来自 Claude Desktop 本地缓存")
    }

    func codexQuotaStatus(_ stat: CodexStat) -> some View {
        let updated = stat.q_updated.map { Fmt.reset($0) } ?? "更新时间未知"
        return HStack(spacing: 5) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 9))
            Text("额度数据已过期 · 更新于 \(updated)")
                .font(.system(size: 9.5, design: .monospaced))
            Spacer()
        }
        .foregroundStyle(Color.orange.opacity(0.88))
        .help("等待 Codex 写入新的额度读数")
    }

    var footer: some View {
        HStack(spacing: 4) {
            disclaimer
            Spacer()
            KeepAwakeMenu(ka: store.keepAwake)
            IconButton(
                icon: copyFeedback ? "checkmark" : "photo.on.rectangle",
                label: copyFeedback ? "已复制" : "复制"
            ) {
                copyUsageImage()
            }
            IconButton(icon: "arrow.clockwise", label: "刷新") { store.refresh() }
            IconButton(icon: "power", label: "退出") { NSApp.terminate(nil) }
        }
    }

    /// Generate a multi-tool share card image for the current range.
    private func copyUsageImage() {
        guard let usage = store.usage else { return }
        let ok = UsageShareImage.copyToPasteboard(
            usage: usage,
            range: sel,
            visibility: toolVisibility,
            updated: store.lastUpdated
        )
        guard ok else { return }
        copiedToolID = nil
        copyFeedback = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.6) {
            copyFeedback = false
        }
    }

    /// Generate a single-tool share card (native-style) for one agent/card.
    private func copySingleToolImage(id: String) {
        guard let usage = store.usage,
              let line = UsageSummaryBuilder.line(
                forToolID: id, usage: usage, range: sel, visibility: toolVisibility
              ) else { return }
        let ok = UsageShareImage.copyToPasteboard(
            line: line, range: sel, updated: store.lastUpdated
        )
        guard ok else { return }
        copyFeedback = false
        copiedToolID = id
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.6) {
            if copiedToolID == id { copiedToolID = nil }
        }
    }

    @State private var updateSpin = false

    private var updateRing: some View {
        Circle()
            .strokeBorder(
                AngularGradient(colors: [.cyan, .blue, .purple, .cyan],
                               center: .center),
                lineWidth: 2
            )
            .frame(width: 26, height: 26)
    }

    @ViewBuilder
    private var updatePill: some View {
        switch updater.state {
        case .available(let tag, _, _):
            Button { updater.performUpdate() } label: {
                ZStack {
                    // 面板关着时退化成静态圆环。这棵视图树永不释放,
                    // repeatForever 会一直驱动 CoreAnimation 显示周期空烧 CPU。
                    if store.popoverVisible {
                        updateRing
                            .rotationEffect(.degrees(updateSpin ? 360 : 0))
                            .onAppear {
                                withAnimation(.linear(duration: 2.5).repeatForever(autoreverses: false)) {
                                    updateSpin = true
                                }
                            }
                            .onDisappear { updateSpin = false }
                    } else {
                        updateRing
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
    @ObservedObject private var loginItem = LoginItemManager.shared
    @State private var priceUpdating = false
    @State private var priceResult = ""
    @State private var debugRunning = false
    @State private var debugOutput = ""
    @State private var debugExpanded = false
    @State private var cachedRemoteUrl = ""
    @State private var sub2APIBaseURL = ""
    @State private var sub2APIKey = ""
    @State private var sub2APIKeyStored = false
    @State private var zaiRegion = "global"
    @State private var zaiKey = ""
    @State private var zaiKeyStored = false
    @State private var providerSettingsResult = ""
    @AppStorage("syncDir") private var syncDir = ""
    @AppStorage("deviceName") private var deviceName = ""
    @State private var configuredDeviceID: String?
    @AppStorage("autoSync") private var autoSync = false
    @AppStorage("syncInterval") private var syncInterval = SyncManager.defaultSyncInterval
    @AppStorage("sitReminderOn") private var sitReminderOn = false
    @AppStorage("sitReminderInterval") private var sitReminderInterval = 90
    @AppStorage(MenuBarStyle.defaultsKey) private var menuBarStyle = MenuBarStyle.system.rawValue
    @AppStorage(MenuBarDensity.defaultsKey) private var menuBarDensity = MenuBarDensity.full.rawValue

    var settingsContent: some View {
        VStack(alignment: .leading, spacing: 12) {
            settingsHeader

            HStack(alignment: .top, spacing: 11) {
                VStack(alignment: .leading, spacing: 11) {
                    settingsAgentsSection
                    settingsProviderQuotaSection
                    settingsDiagnosticsSection
                    settingsPricingSection
                }
                .frame(width: settingsColumnWidth, alignment: .top)

                VStack(alignment: .leading, spacing: 11) {
                    settingsMenuBarSection
                    settingsPrivacySection
                    settingsSystemSection
                    settingsReminderSection
                    settingsSyncSection
                    if !store.syncEnabled { settingsRemoteHintSection }
                }
                .frame(width: settingsColumnWidth, alignment: .top)
            }

        }
        .onAppear {
            loginItem.refresh()
            loadProviderSettings()
            if let cfg = SyncManager.loadConfig() {
                if let persistedID = Self.validSyncDeviceID(cfg.device_id) {
                    configuredDeviceID = persistedID
                    deviceName = persistedID
                    store.syncManager.config = cfg
                }
                if syncDir.isEmpty && !cfg.sync_dir.isEmpty {
                    let expanded = (cfg.sync_dir as NSString).expandingTildeInPath
                    if FileManager.default.fileExists(atPath: expanded) {
                        syncDir = expanded
                    }
                }
                if UserDefaults.standard.object(forKey: "syncEnabled") == nil,
                   !cfg.sync_dir.isEmpty {
                    let expanded = (cfg.sync_dir as NSString).expandingTildeInPath
                    if FileManager.default.fileExists(atPath: expanded) {
                        store.syncEnabled = true
                    }
                }
                if let auto = cfg.auto_sync { autoSync = auto }
                syncInterval = SyncManager.normalizedSyncInterval(cfg.sync_interval)
                if store.syncEnabled && autoSync {
                    store.startAutoSync(minutes: syncInterval)
                }
            }
            if !syncDir.isEmpty {
                DispatchQueue.global(qos: .userInitiated).async {
                    let url = Self.gitRemoteUrl(syncDir)
                    DispatchQueue.main.async { cachedRemoteUrl = url }
                }
            }
        }
    }

    /// 窗口 → 开关的唯一映射。@AppStorage 只能是独立属性，所有读写都从这里走。
    private func menuBarQuotaBinding(_ source: MenuBarQuotaSource) -> Binding<Bool> {
        switch source {
        case .claude5h: return $menuBarQuotaClaude5h
        case .claudeWeek: return $menuBarQuotaClaudeWeek
        case .claudeFable: return $menuBarQuotaClaudeFable
        case .codex5h: return $menuBarQuotaCodex5h
        case .codexWeek: return $menuBarQuotaCodexWeek
        case .grok: return $menuBarQuotaGrok
        }
    }

    /// 状态栏真会画出来的那几项。和 `metrics(in:)` 共用一个谓词，
    /// 提示语和预览才不会宣布一个状态栏根本没画的组合。
    private var menuBarQuotaSelectedSources: [MenuBarQuotaSource] {
        MenuBarQuotaSource.allCases.filter {
            guard menuBarQuotaBinding($0).wrappedValue else { return false }
            guard let usage = store.usage else { return true }
            return $0.isRenderable(in: usage)
        }
    }

    /// 6 个开关拼成一个值，菜单栏刷新只挂一个 onChange。
    private var menuBarQuotaDigest: String {
        MenuBarQuotaSource.allCases
            .map { menuBarQuotaBinding($0).wrappedValue ? "1" : "0" }
            .joined()
    }

    private var menuBarQuotaHint: String {
        let selected = menuBarQuotaSelectedSources
        if selected.isEmpty { return "全部关闭，状态栏只留图标。" }
        let shown = selected.prefix(2).map(\.label).joined(separator: " · ")
        if selected.count > 2 {
            let hidden = selected.dropFirst(2).map(\.label).joined(separator: "、")
            return "双额度显示：\(shown)；\(hidden) 放不下。"
        }
        return "双额度显示：\(shown)。"
    }

    var settingsMenuBarSection: some View {
        settingsSection("menubar.rectangle", "菜单栏") {
            settingsStackedValue("样式") {
                Picker("菜单栏样式", selection: $menuBarStyle) {
                    ForEach(MenuBarStyle.allCases) { style in
                        Text(style.label).tag(style.rawValue)
                    }
                }
                .labelsHidden()
                .pickerStyle(.segmented)
                .controlSize(.mini)
                .font(.system(size: 9, weight: .medium))
                .frame(width: settingsMenuPickerWidth)
            }

            settingsStackedValue("信息") {
                Picker("菜单栏信息量", selection: $menuBarDensity) {
                    ForEach(MenuBarDensity.allCases) { density in
                        Text(density.label).tag(density.rawValue)
                    }
                }
                .labelsHidden()
                .pickerStyle(.segmented)
                .controlSize(.mini)
                .frame(width: settingsMenuPickerWidth)
            }

            settingsStackedValue("额度来源") {
                LazyVGrid(columns: [GridItem(.flexible(), spacing: 7),
                                    GridItem(.flexible(), spacing: 7)], spacing: 7) {
                    ForEach(MenuBarQuotaSource.allCases) { source in
                        settingsRow(source.label, tint: source.themeColor,
                                    isOn: menuBarQuotaBinding(source))
                    }
                }
            }

            Text(menuBarQuotaHint)
                .font(.system(size: 9, weight: .medium))
                .foregroundStyle(Theme.tSecondary)
                .fixedSize(horizontal: false, vertical: true)

            Text("只影响状态栏剩余额度，与「显示卡片」无关。每项都是一个具体窗口：5h 是滚动的 5 小时窗口，周是本周配额。双额度按上面的顺序取前两项，单额度只显示剩得最少的那项。「符号」「圆点」两种样式会用沙漏标 5h、横块标周；其余样式只有数字，鼠标放到状态栏上能看到窗口全名。勾了但你的账号没有这个窗口、或者读数已过期，状态栏会跳过它。")
                .font(.system(size: 8.5))
                .foregroundStyle(Theme.tTertiary)
                .fixedSize(horizontal: false, vertical: true)

            HStack {
                Spacer()
                MenuBarStylePreview(
                    style: MenuBarStyle(rawValue: menuBarStyle) ?? .system,
                    density: MenuBarDensity(rawValue: menuBarDensity) ?? .full,
                    sources: Array(menuBarQuotaSelectedSources.prefix(2))
                )
                Spacer()
            }
        }
        .onChange(of: menuBarStyle) { _ in
            (NSApp.delegate as? AppDelegate)?.updateStatusTitle()
        }
        .onChange(of: menuBarDensity) { _ in
            (NSApp.delegate as? AppDelegate)?.updateStatusTitle()
        }
        .onChange(of: menuBarQuotaDigest) { _ in
            (NSApp.delegate as? AppDelegate)?.updateStatusTitle()
        }
    }

    var settingsSystemSection: some View {
        settingsSection("gearshape.2", "系统") {
            settingsToggleRow(
                "登录时启动",
                isOn: Binding(
                    get: { loginItem.enabled },
                    set: { loginItem.setEnabled($0) }
                )
            )

            if loginItem.requiresApproval {
                HStack(spacing: 7) {
                    Text("需要在系统设置中允许")
                        .font(.system(size: 8.5))
                        .foregroundStyle(Theme.tTertiary)
                    Spacer()
                    settingsActionButton(icon: "gear", title: "打开设置") {
                        loginItem.openSystemSettings()
                    }
                }
            } else if let error = loginItem.errorMessage {
                Text(error)
                    .font(.system(size: 8.5))
                    .foregroundStyle(.red.opacity(0.85))
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    var settingsAgentsSection: some View {
        settingsSection("square.grid.2x2", "显示卡片") {
            LazyVGrid(columns: [GridItem(.flexible(), spacing: 7),
                                GridItem(.flexible(), spacing: 7)], spacing: 7) {
                settingsRow("Claude", tint: Theme.claude, isOn: $showClaude)
                settingsRow("Codex", tint: Theme.codex, isOn: $showCodex)
                settingsRow("Gemini / Antigravity", tint: Theme.gemini, isOn: $showGemini)
                settingsRow("Cursor", tint: Theme.cursor, isOn: $showCursor)
                settingsRow("Zed", tint: Theme.zed, isOn: $showZed)
                settingsRow("Sub2API", tint: Theme.sub2api, isOn: $showSub2API)
                settingsRow("z.ai / GLM", tint: Theme.zai, isOn: $showZai)
                settingsRow("Grok", tint: Theme.grok, isOn: $showGrok)
                settingsRow("Qoder Desktop", tint: Theme.qoder, isOn: $showQoder)
                settingsRow("QoderWork", tint: Theme.qoderwork, isOn: $showQoderWork)
                settingsRow("Qoder CLI", tint: Theme.qodercli, isOn: $showQoderCli)
                settingsRow("Hermes", tint: Theme.hermes, isOn: $showHermes)
                settingsRow("ZCode", tint: Theme.zcode, isOn: $showZcode)
                settingsRow("MiMoCode", tint: Theme.mimocode, isOn: $showMimoCode)
                settingsRow("OpenClaw", tint: Theme.openclaw, isOn: $showOpenClaw)
                settingsRow("Pi", tint: Theme.pi, isOn: $showPi)
                settingsRow("Prime Agent", tint: Theme.primeAgent, isOn: $showPrimeAgent)
                settingsRow("WorkBuddy", tint: Theme.workbuddy, isOn: $showWorkBuddy)
                settingsRow("DeepSeek Harness", tint: Theme.deepseekHarness, isOn: $showDeepSeekHarness)
                settingsRow("OpenCode", tint: Theme.opencode, isOn: $showOpenCode)
                settingsRow("Qwen Code", tint: Theme.qwencode, isOn: $showQwenCode)
                settingsRow("千问办公", tint: Theme.qwenwork, isOn: $showQwenWork)
                settingsRow("Kimi Code", tint: Theme.kimicode, isOn: $showKimiCode)
            }
        }
        .onChange(of: showQoder) { enabled in
            Self.setQoderIdeEnabled(enabled)
        }
        .onChange(of: showGemini) { enabled in
            Self.setProviderQuotaEnabled("antigravity", enabled)
            store.refresh()
        }
        .onChange(of: showCursor) { enabled in
            Self.setProviderQuotaEnabled("cursor", enabled)
            store.refresh()
        }
        .onChange(of: showZed) { enabled in
            Self.setProviderQuotaEnabled("zed", enabled)
            store.refresh()
        }
        .onChange(of: showSub2API) { enabled in
            Self.setProviderQuotaEnabled("sub2api", enabled)
            store.refresh()
        }
        .onChange(of: showZai) { enabled in
            Self.setProviderQuotaEnabled("zai", enabled)
            store.refresh()
        }
    }

    var settingsProviderQuotaSection: some View {
        settingsSection("key.horizontal.fill", "Provider 额度") {
            Text("Cursor 复用 Cursor.app 登录态，Zed 复用 Zed Keychain；两者无需在 Tokei 中保存密钥。显示对应卡片即允许查询。")
                .font(.system(size: 8.5))
                .foregroundStyle(Theme.tTertiary)
                .fixedSize(horizontal: false, vertical: true)

            thinDivider

            Text("Sub2API")
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(Theme.sub2api)
            providerSettingsField(
                label: "Base URL",
                placeholder: "https://api.example.com",
                text: $sub2APIBaseURL
            )
            providerSettingsField(
                label: "API Key",
                placeholder: sub2APIKeyStored ? "已保存，留空不修改" : "Group API Key",
                text: $sub2APIKey,
                secure: true
            )
            if sub2APIKeyStored {
                HStack {
                    Spacer()
                    settingsActionButton(icon: "trash", title: "清除 Sub2API 密钥") {
                        clearProviderToken(.sub2api)
                    }
                }
            }

            thinDivider

            Text("z.ai / GLM")
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(Theme.zai)
            HStack(spacing: 8) {
                Text("区域")
                    .font(.system(size: 9.5))
                    .foregroundStyle(Theme.tTertiary)
                    .frame(width: 52, alignment: .leading)
                Picker("z.ai 区域", selection: $zaiRegion) {
                    Text("Global").tag("global")
                    Text("BigModel CN").tag("bigmodel-cn")
                }
                .labelsHidden()
                .pickerStyle(.segmented)
                .controlSize(.mini)
            }
            providerSettingsField(
                label: "API Key",
                placeholder: zaiKeyStored ? "已保存，留空不修改" : "Z_AI_API_KEY",
                text: $zaiKey,
                secure: true
            )
            if zaiKeyStored {
                HStack {
                    Spacer()
                    settingsActionButton(icon: "trash", title: "清除 z.ai 密钥") {
                        clearProviderToken(.zai)
                    }
                }
            }

            HStack {
                settingsActionButton(icon: "checkmark.circle", title: "保存 Provider 设置") {
                    saveProviderSettings()
                }
                Spacer()
                if !providerSettingsResult.isEmpty {
                    Text(providerSettingsResult)
                        .font(.system(size: 8.5))
                        .foregroundStyle(providerSettingsResult == "已保存" ? Color.green : Color.orange)
                }
            }
        }
    }

    @ViewBuilder
    private func providerSettingsField(
        label: String,
        placeholder: String,
        text: Binding<String>,
        secure: Bool = false
    ) -> some View {
        HStack(spacing: 8) {
            Text(label)
                .font(.system(size: 9.5))
                .foregroundStyle(Theme.tTertiary)
                .frame(width: 52, alignment: .leading)
            Group {
                if secure {
                    SecureField(placeholder, text: text)
                } else {
                    TextField(placeholder, text: text)
                }
            }
            .textFieldStyle(.plain)
            .font(.system(size: 9.5, design: .monospaced))
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
            .background(
                RoundedRectangle(cornerRadius: 6, style: .continuous)
                    .fill(Color.primary.opacity(0.05))
            )
        }
    }

    private func loadProviderSettings() {
        sub2APIBaseURL = SyncManager.providerSetting("sub2api_base_url") ?? ""
        zaiRegion = SyncManager.providerSetting("zai_region") ?? "global"
        sub2APIKeyStored = ProviderCredentialStore.token(for: .sub2api) != nil
        zaiKeyStored = ProviderCredentialStore.token(for: .zai) != nil
    }

    private func saveProviderSettings() {
        let baseURL = sub2APIBaseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard baseURL.isEmpty || Self.validSub2APIBaseURL(baseURL) else {
            providerSettingsResult = "Sub2API URL 仅支持 HTTPS 或本机 HTTP"
            return
        }
        let savedURL = SyncManager.setProviderSetting(
            baseURL.isEmpty ? nil : baseURL,
            forKey: "sub2api_base_url"
        )
        let savedRegion = SyncManager.setProviderSetting(zaiRegion, forKey: "zai_region")
        let savedSub2APIKey = sub2APIKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || ProviderCredentialStore.setToken(sub2APIKey, for: .sub2api)
        let savedZaiKey = zaiKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || ProviderCredentialStore.setToken(zaiKey, for: .zai)
        guard savedURL, savedRegion, savedSub2APIKey, savedZaiKey else {
            providerSettingsResult = "保存失败"
            return
        }
        sub2APIKey = ""
        zaiKey = ""
        loadProviderSettings()
        providerSettingsResult = "已保存"
        store.refresh()
    }

    private func clearProviderToken(_ provider: ProviderSecret) {
        guard ProviderCredentialStore.setToken("", for: provider) else {
            providerSettingsResult = "清除失败"
            return
        }
        loadProviderSettings()
        providerSettingsResult = "已清除"
        store.refresh()
    }

    private static func validSub2APIBaseURL(_ value: String) -> Bool {
        guard let components = URLComponents(string: value),
              let scheme = components.scheme?.lowercased(),
              let host = components.host?.lowercased(),
              components.user == nil, components.password == nil,
              components.query == nil, components.fragment == nil else { return false }
        if scheme == "https" { return true }
        guard scheme == "http" else { return false }
        return host == "localhost" || host == "127.0.0.1" || host == "::1"
    }

    var settingsPrivacySection: some View {
        settingsSection("lock.shield", "隐私与额度") {
            settingsToggleRow("Grok 实时额度查询", isOn: $grokLiveQuotaEnabled)
            Text("默认只读本机 Grok 日志中的额度快照，不访问网络。开启后才会用本地登录凭据请求 Grok 账单接口，以便拿到最新剩余额度。")
                .font(.system(size: 8.5))
                .foregroundStyle(Theme.tTertiary)
                .fixedSize(horizontal: false, vertical: true)

            thinDivider

            settingsToggleRow("千问办公额度查询", isOn: $qwenWorkQuotaEnabled)
            Text("默认关闭。开启后，Tokei 仅连接千问办公桌面端在本机 127.0.0.1 提供的受保护接口；千问办公可能随之向官方服务刷新额度。Tokei 不读取或保存登录凭据，需保持千问办公已登录并运行。")
                .font(.system(size: 8.5))
                .foregroundStyle(Theme.tTertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .onChange(of: grokLiveQuotaEnabled) { enabled in
            Self.setGrokLiveQuotaEnabled(enabled)
            store.refresh()
        }
        .onChange(of: qwenWorkQuotaEnabled) { enabled in
            Self.setQwenWorkQuotaEnabled(enabled)
            store.refresh()
        }
    }

    private static func setQoderIdeEnabled(_ enabled: Bool) {
        SyncManager.setQoderIdeEnabled(enabled)
    }

    private static func setGrokLiveQuotaEnabled(_ enabled: Bool) {
        SyncManager.setGrokLiveQuotaEnabled(enabled)
    }

    private static func setQwenWorkQuotaEnabled(_ enabled: Bool) {
        SyncManager.setQwenWorkQuotaEnabled(enabled)
    }

    private static func setProviderQuotaEnabled(_ provider: String, _ enabled: Bool) {
        SyncManager.setProviderQuotaEnabled(provider, enabled: enabled)
    }

    /// 启动时把 UI 开关(showQoderIde)的当前值落盘到 config.json。
    /// 修复:showQoder 默认开启,但 .onChange 不会在启动时触发,
    /// 导致 qoder_ide_enabled 从未写入、Python 端一直不采集 Qoder IDE 数据。
    static func syncQoderIdeConfigOnLaunch() {
        let enabled = UserDefaults.standard.object(forKey: "showQoderIde") as? Bool ?? true
        setQoderIdeEnabled(enabled)
    }

    /// 启动时同步 Grok 实时额度开关（默认关）。
    static func syncGrokLiveQuotaConfigOnLaunch() {
        let enabled = UserDefaults.standard.object(forKey: "grokLiveQuotaEnabled") as? Bool ?? false
        setGrokLiveQuotaEnabled(enabled)
    }

    /// 启动时同步千问办公额度开关（默认关）。
    static func syncQwenWorkQuotaConfigOnLaunch() {
        let enabled = UserDefaults.standard.object(forKey: "qwenWorkQuotaEnabled") as? Bool ?? false
        setQwenWorkQuotaEnabled(enabled)
    }

    /// 新 Provider 默认关闭；Antigravity 跟随现有 Gemini / Antigravity 卡片开关。
    static func syncProviderQuotaConfigOnLaunch() {
        let defaults = UserDefaults.standard
        let settings: [(String, String, Bool)] = [
            ("antigravity", "showGemini", true),
            ("cursor", "showCursor", false),
            ("zed", "showZed", false),
            ("sub2api", "showSub2API", false),
            ("zai", "showZai", false),
        ]
        for (provider, key, fallback) in settings {
            let enabled = defaults.object(forKey: key) as? Bool ?? fallback
            setProviderQuotaEnabled(provider, enabled)
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
                    if on {
                        if setupSync() {
                            store.refresh()
                            if autoSync {
                                store.startAutoSync(minutes: syncInterval)
                            }
                        }
                    } else {
                        autoSync = false
                        if configuredDeviceID != nil { saveSync() }
                        store.stopAutoSync()
                        store.applyDisplayMode()
                    }
                }

            if store.syncEnabled {
                settingsValueRow("设备名") {
                    TextField("hostname", text: $deviceName)
                        .font(.system(size: 10, design: .monospaced))
                        .textFieldStyle(.plain)
                        .frame(width: 110)
                        .multilineTextAlignment(.trailing)
                        .disabled(store.syncing || configuredDeviceID != nil)
                        .onChange(of: deviceName) { value in
                            if let configuredDeviceID, value != configuredDeviceID {
                                deviceName = configuredDeviceID
                            }
                        }
                        .onSubmit {
                            if saveSync() {
                                store.refresh()
                                if autoSync {
                                    store.startAutoSync(minutes: syncInterval)
                                }
                            }
                        }
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
                        .disabled(store.syncing)
                }

                HStack(spacing: 6) {
                    settingsActionButton(
                        icon: "arrow.triangle.2.circlepath",
                        title: store.syncing ? "同步中" : "同步",
                        width: 86
                    ) {
                        if saveSync() { store.doSync() }
                    }
                    .disabled(store.syncing || syncDir.isEmpty)

                    Spacer(minLength: 6)
                    Text("自动")
                        .font(.system(size: 10))
                        .foregroundStyle(Theme.tTertiary)
                        .fixedSize(horizontal: true, vertical: false)
                    Toggle("", isOn: $autoSync)
                        .toggleStyle(.switch).controlSize(.mini).labelsHidden()
                        .disabled(store.syncing)
                        .onChange(of: autoSync) { on in
                            saveSync()
                            if on { store.startAutoSync(minutes: syncInterval) }
                            else { store.stopAutoSync() }
                        }
                    if autoSync {
                        Picker("", selection: $syncInterval) {
                            ForEach(SyncManager.supportedSyncIntervals, id: \.self) { minutes in
                                Text("\(minutes)m").tag(minutes)
                            }
                        }
                        .pickerStyle(.segmented)
                        .frame(width: 104)
                        .controlSize(.mini)
                        .disabled(store.syncing)
                        .onChange(of: syncInterval) { v in
                            saveSync()
                            if autoSync { store.startAutoSync(minutes: v) }
                        }
                    }
                }

                if !store.syncStatus.isEmpty {
                    HStack(spacing: 4) {
                        Spacer()
                        Image(systemName: store.syncSucceeded == false
                              ? "exclamationmark.circle.fill"
                              : (store.syncSucceeded == true ? "checkmark.circle.fill" : "arrow.triangle.2.circlepath"))
                        Text(store.syncStatus)
                    }
                    .font(.system(size: 8.5, weight: .medium))
                    .foregroundStyle(store.syncSucceeded == false ? Theme.claude : Theme.hermes)
                    .help(store.syncDetail)
                }

                if !store.peerLoadIssues.isEmpty {
                    HStack(spacing: 4) {
                        Spacer()
                        Image(systemName: "exclamationmark.triangle.fill")
                        Text("有 \(store.peerLoadIssues.count) 个设备快照读取异常")
                    }
                    .font(.system(size: 8.5, weight: .medium))
                    .foregroundStyle(Theme.claude)
                    .help(store.peerLoadIssues.map(\.summary).joined(separator: "\n"))
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
                            copyBlock(linuxSetupCommand(remote: dataRepo))
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
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
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

    func settingsActionButton(
        icon: String,
        title: String,
        width: CGFloat? = nil,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack(spacing: 4) {
                Image(systemName: icon).font(.system(size: 9))
                Text(title).font(.system(size: 10, weight: .medium))
            }
            .foregroundStyle(Theme.tPrimary)
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .frame(width: width)
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

    func settingsStackedValue<C: View>(_ title: String, @ViewBuilder value: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title)
                .font(.system(size: 10))
                .foregroundStyle(Theme.tTertiary)
            value()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
    }

    static func validSyncDeviceID(_ value: String) -> String? {
        let normalized = SyncManager.normalizedDeviceID(value)
        guard !normalized.isEmpty,
              normalized != ".",
              normalized != "..",
              normalized.count <= 128,
              !normalized.unicodeScalars.contains(where: {
                  $0.value < 32 || $0.value == 47 || $0.value == 92 || $0.value == 0
              }) else {
            return nil
        }
        return normalized
    }

    @discardableResult
    func setupSync() -> Bool {
        if let cfg = SyncManager.loadConfig(),
           let persistedID = Self.validSyncDeviceID(cfg.device_id) {
            configuredDeviceID = persistedID
            deviceName = persistedID
            store.syncManager.config = cfg
            return saveSync()
        }
        if deviceName.isEmpty {
            var buf = [CChar](repeating: 0, count: 256)
            gethostname(&buf, buf.count)
            let raw = String(cString: buf)
            deviceName = raw.components(separatedBy: ".").first ?? "mac"
        }
        return false
    }

    @discardableResult
    func saveSync() -> Bool {
        let priorLockedID = configuredDeviceID
        let persistedID = SyncManager.loadConfig().flatMap {
            Self.validSyncDeviceID($0.device_id)
        }
        if let persistedID {
            configuredDeviceID = persistedID
            deviceName = persistedID
        }
        guard let effectiveDeviceID = persistedID
                ?? priorLockedID
                ?? Self.validSyncDeviceID(deviceName) else {
            if let priorLockedID { deviceName = priorLockedID }
            store.syncSucceeded = false
            store.syncStatus = "设备名不合法"
            store.syncDetail = "设备名不能为空，且不能包含斜杠或控制字符"
            return false
        }
        let interval = SyncManager.normalizedSyncInterval(syncInterval)
        syncInterval = interval
        let cfg = SyncConfig(device_id: effectiveDeviceID, sync_dir: syncDir,
                             auto_sync: autoSync, sync_interval: interval)
        if store.syncManager.saveConfig(cfg) {
            configuredDeviceID = effectiveDeviceID
            deviceName = effectiveDeviceID
            return true
        } else {
            let fallbackID = SyncManager.loadConfig().flatMap {
                Self.validSyncDeviceID($0.device_id)
            } ?? persistedID ?? priorLockedID
            if let fallbackID {
                configuredDeviceID = fallbackID
                deviceName = fallbackID
            }
            store.syncSucceeded = false
            store.syncStatus = "同步配置保存失败"
            store.syncDetail = SyncManager.configPath.path
            return false
        }
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
            let tools = ["claude", "codex", "gemini", "antigravity", "cursor", "zed",
                         "sub2api", "zai", "grok", "qoder", "qoderwork", "hermes",
                         "zcode", "mimocode", "openclaw", "pi", "workbuddy", "deepseek_harness",
                         "opencode", "qwencode", "qwenwork", "kimicode", "prime_agent"]
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

    static var buildVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "TokeiBuildDate") as? String ?? "未打包"
    }

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

    func linuxSetupCommand(remote: String) -> String {
        let quotedRemote = ShellEscaping.singleQuoted(remote)
        return """
        unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR GIT_INDEX_FILE \
          GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_NAMESPACE \
          GIT_PREFIX GIT_EXEC_PATH GIT_SHALLOW_FILE GIT_GRAFT_FILE \
          GIT_QUARANTINE_PATH GIT_CEILING_DIRECTORIES \
          GIT_DISCOVERY_ACROSS_FILESYSTEM GIT_CONFIG GIT_CONFIG_COUNT \
          GIT_CONFIG_PARAMETERS GIT_CONFIG_SYSTEM GIT_CONFIG_GLOBAL \
          GIT_CONFIG_NOSYSTEM GIT_ASKPASS SSH_ASKPASS
        export GIT_NO_REPLACE_OBJECTS=1
        mkdir -p ~/.tokei
        if [ ! -d ~/.tokei/sync/.git ]; then
          /usr/bin/git -c core.hooksPath=/dev/null -c commit.gpgSign=false \
            -c core.fsmonitor=false \
            clone \(quotedRemote) ~/.tokei/sync
        fi
        curl -fsSL https://dl.lanshuagent.com/tokei/usage.30s.py -o ~/.tokei/usage.30s.py
        cat > ~/.tokei/config.json <<JSON
        {"sync_dir":"~/.tokei/sync","device_id":"$(hostname -s)","auto_sync":true,"sync_interval":30}
        JSON
        cat > ~/.tokei/tokei-sync.sh <<'SH'
        #!/bin/sh
        set -u

        unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR GIT_INDEX_FILE \
          GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_NAMESPACE \
          GIT_PREFIX GIT_EXEC_PATH GIT_SHALLOW_FILE GIT_GRAFT_FILE \
          GIT_QUARANTINE_PATH GIT_CEILING_DIRECTORIES \
          GIT_DISCOVERY_ACROSS_FILESYSTEM GIT_CONFIG GIT_CONFIG_COUNT \
          GIT_CONFIG_PARAMETERS GIT_CONFIG_SYSTEM GIT_CONFIG_GLOBAL \
          GIT_CONFIG_NOSYSTEM GIT_ASKPASS SSH_ASKPASS
        export GIT_NO_REPLACE_OBJECTS=1

        fail() {
          code="$1"
          shift
          printf 'Tokei sync error: %s\n' "$*" >&2
          exit "$code"
        }

        sync_git() {
          /usr/bin/git -c core.hooksPath=/dev/null -c commit.gpgSign=false \
            -c core.fsmonitor=false -c rebase.updateRefs=false \
            -c rebase.autoStash=false -c push.gpgSign=false \
            -c push.followTags=false -c remote.origin.mirror=false "$@"
        }

        # fcntl 锁由父 Python 进程持有，覆盖预检、快照、提交、rebase 和 push。
        if [ "${1:-}" != "__tokei_locked__" ]; then
          exec python3 - "$0" <<'PY'
        import errno
        import fcntl
        import json
        import os
        import signal
        import subprocess
        import sys
        import time

        script = os.path.realpath(sys.argv[1])
        config_path = os.path.expanduser("~/.tokei/config.json")
        try:
            blocked_environment = {
                "GIT_DIR",
                "GIT_WORK_TREE",
                "GIT_COMMON_DIR",
                "GIT_INDEX_FILE",
                "GIT_OBJECT_DIRECTORY",
                "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                "GIT_NAMESPACE",
                "GIT_PREFIX",
                "GIT_EXEC_PATH",
                "GIT_SHALLOW_FILE",
                "GIT_GRAFT_FILE",
                "GIT_QUARANTINE_PATH",
                "GIT_CEILING_DIRECTORIES",
                "GIT_DISCOVERY_ACROSS_FILESYSTEM",
                "GIT_ASKPASS",
                "SSH_ASKPASS",
                "ENV",
                "BASH_ENV",
            }
            child_env = {
                key: value
                for key, value in os.environ.items()
                if key not in blocked_environment and not key.startswith("GIT_CONFIG")
            }
            child_env["GIT_NO_REPLACE_OBJECTS"] = "1"
            child_env["GIT_SSH_VARIANT"] = "ssh"
            child_env["GIT_ASKPASS"] = "/usr/bin/false"
            child_env["SSH_ASKPASS"] = "/usr/bin/false"
            child_env["GCM_INTERACTIVE"] = "Never"
            child_env["GIT_TERMINAL_PROMPT"] = "0"
            child_env["SSH_ASKPASS_REQUIRE"] = "never"
            with open(config_path, encoding="utf-8") as handle:
                config = json.load(handle)
            device_id = config.get("device_id", "")
            if not isinstance(device_id, str):
                raise ValueError("device_id must be a string")
            device_id = device_id.strip()
            if (not device_id or device_id in (".", "..") or len(device_id) > 128
                    or any(ord(ch) < 32 or ord(ch) in (47, 92) for ch in device_id)):
                raise ValueError("invalid device_id")
            sync_dir = config.get("sync_dir", "") or "~/.tokei/sync"
            if not isinstance(sync_dir, str):
                raise ValueError("sync_dir must be a string")
            repo = os.path.realpath(os.path.expanduser(sync_dir))
            git_dir = subprocess.check_output(
                ["/usr/bin/git", "-c", "core.hooksPath=/dev/null",
                 "-c", "commit.gpgSign=false", "-c", "core.fsmonitor=false",
                 "-C", repo, "rev-parse", "--absolute-git-dir"],
                universal_newlines=True,
                stderr=subprocess.DEVNULL,
                env=child_env,
            ).strip()
            lock_path = os.path.join(git_dir, "tokei-sync.lock")
            lock_flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
            lock_fd = os.open(lock_path, lock_flags, 0o600)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                if error.errno in (errno.EACCES, errno.EAGAIN):
                    print("Tokei sync error: 另一同步任务正在运行", file=sys.stderr)
                    sys.exit(75)
                raise
            os.set_inheritable(lock_fd, True)
            process = None

            def process_group_exists():
                if process is None:
                    return False
                try:
                    os.killpg(process.pid, 0)
                except ProcessLookupError:
                    return False
                except PermissionError:
                    return True
                return True

            def stop_process_group():
                if process is None:
                    return
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    process.poll()
                    if not process_group_exists():
                        break
                    time.sleep(0.05)
                if process_group_exists():
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    process.poll()
                    if not process_group_exists():
                        break
                    time.sleep(0.05)
                if process.poll() is None:
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass

            def handle_signal(signum, _frame):
                print("Tokei sync error: supervisor received signal {}".format(signum),
                      file=sys.stderr)
                stop_process_group()
                sys.exit(124)

            signal.signal(signal.SIGTERM, handle_signal)
            signal.signal(signal.SIGINT, handle_signal)
            process = subprocess.Popen(
                ["/bin/sh", script, "__tokei_locked__", str(lock_fd),
                 repo, lock_path, device_id],
                pass_fds=(lock_fd,),
                start_new_session=True,
                env=child_env,
            )
            try:
                return_code = process.wait(timeout=240)
            except subprocess.TimeoutExpired:
                print("Tokei sync error: 同步事务超过 240 秒，已终止进程组",
                      file=sys.stderr)
                stop_process_group()
                sys.exit(124)
            sys.exit(return_code)
        except (OSError, ValueError, json.JSONDecodeError,
                subprocess.CalledProcessError) as error:
            print("Tokei sync error: 同步配置或仓库不可用: {}".format(error),
                  file=sys.stderr)
            sys.exit(20)
        PY
        fi

        [ "$#" -eq 5 ] || fail 75 "同步锁参数不完整"
        lock_fd="$2"
        repo="$3"
        lock_path="$4"
        device_id="$5"

        # 拒绝绕过锁直接进入事务，并确认继承的描述符指向当前仓库锁文件。
        python3 - "$lock_fd" "$lock_path" <<'PY' \
          || fail 75 "无法确认同步锁"
        import fcntl
        import os
        import sys

        try:
            descriptor = int(sys.argv[1])
            expected = os.stat(sys.argv[2])
            actual = os.fstat(descriptor)
            if (expected.st_dev, expected.st_ino) != (actual.st_dev, actual.st_ino):
                raise OSError("lock descriptor mismatch")
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, ValueError):
            sys.exit(1)
        PY

        export GIT_TERMINAL_PROMPT=0
        export GIT_EDITOR=true
        export GIT_SEQUENCE_EDITOR=true
        export GIT_SSH_COMMAND='/usr/bin/ssh -o BatchMode=yes -o ConnectTimeout=15 -o ConnectionAttempts=2 -o ServerAliveInterval=15 -o ServerAliveCountMax=2'
        export GIT_SSH_VARIANT=ssh
        export GIT_ASKPASS=/usr/bin/false
        export SSH_ASKPASS=/usr/bin/false
        export GCM_INTERACTIVE=Never
        export SSH_ASKPASS_REQUIRE=never
        cd "$repo" || fail 20 "无法进入同步目录"

        git_dir=$(sync_git rev-parse --absolute-git-dir 2>/dev/null) \
          || fail 20 "同步目录不是有效的 Git 仓库"
        declared_root=$(sync_git rev-parse --show-toplevel 2>/dev/null) \
          || fail 20 "无法读取同步仓库工作树"
        declared_root=$(cd -- "$declared_root" 2>/dev/null && /bin/pwd -P) \
          || fail 20 "无法解析同步仓库工作树"
        current_root=$(/bin/pwd -P)
        [ "$declared_root" = "$current_root" ] \
          || fail 20 "同步仓库 core.worktree 指向其他目录，已停止"
        [ "$git_dir/tokei-sync.lock" = "$lock_path" ] \
          || fail 75 "同步仓库与锁文件不匹配"
        marker="$git_dir/tokei-sync-rebase"
        rebase_merge="$git_dir/rebase-merge"
        rebase_apply="$git_dir/rebase-apply"
        device_pathspec=":(icase,literal)$device_id.json"
        exclude_pathspec=":(exclude,icase,literal)$device_id.json"
        peer_json_pathspec=":(top,glob)*.json"

        validate_marker() {
          [ -f "$marker" ] || return 1
          [ "$(sed -n '1p' "$marker" 2>/dev/null)" = "tokei-sync-rebase-v2" ] \
            || return 1
          [ "$(sed -n '2p' "$marker" 2>/dev/null)" = "refs/heads/main" ] \
            || return 1
          [ "$(sed -n '4p' "$marker" 2>/dev/null)" = "origin/main" ] \
            || return 1
          marker_onto=$(sed -n '5p' "$marker" 2>/dev/null)
          [ -n "$marker_onto" ] || return 1
          resolved_onto=$(sync_git rev-parse --verify "$marker_onto^{commit}" 2>/dev/null) \
            || return 1
          [ "$resolved_onto" = "$marker_onto" ] || return 1
        }

        if [ -d "$rebase_merge" ] || [ -d "$rebase_apply" ]; then
          if [ -d "$rebase_merge" ] && [ ! -d "$rebase_apply" ] \
            && validate_marker; then
            expected_head=$(sed -n '3p' "$marker")
            expected_onto=$(sed -n '5p' "$marker")
            actual_head=$(cat "$rebase_merge/orig-head" 2>/dev/null || true)
            actual_branch=$(cat "$rebase_merge/head-name" 2>/dev/null || true)
            actual_onto=$(cat "$rebase_merge/onto" 2>/dev/null || true)
            if [ "$actual_head" = "$expected_head" ] \
              && [ "$actual_branch" = "refs/heads/main" ] \
              && [ "$actual_onto" = "$expected_onto" ]; then
              fail 21 "检测到 Tokei 上次遗留的 rebase，现场已保留，请人工确认"
            fi
          fi
          fail 21 "检测到未完成或无法确认归属的 rebase，现场已保留"
        elif [ -f "$marker" ]; then
          validate_marker || fail 21 "发现格式异常的 Tokei rebase 标记，现场已保留"
          fail 21 "发现 Tokei 遗留的 rebase 标记，现场已保留，请人工确认"
        fi

        for operation in MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD BISECT_START; do
          operation_path=$(sync_git rev-parse --git-path "$operation")
          [ ! -e "$operation_path" ] \
            || fail 21 "检测到未完成的 $operation，已停止且未改动仓库"
        done
        sequencer_path=$(sync_git rev-parse --git-path sequencer)
        [ ! -d "$sequencer_path" ] \
          || fail 21 "检测到未完成的 Git sequencer 操作，已停止且未改动仓库"
        unmerged_state=$(sync_git ls-files -u) || fail 21 "无法检查索引冲突状态"
        [ -z "$unmerged_state" ] \
          || fail 21 "索引包含未解决冲突，已停止且未改动仓库"

        branch=$(sync_git symbolic-ref --quiet --short HEAD 2>/dev/null) \
          || fail 22 "同步仓库处于 detached HEAD，已停止"
        [ "$branch" = "main" ] \
          || fail 22 "同步仓库必须位于 main 分支，当前为 $branch"

        sync_git remote get-url origin >/dev/null 2>&1 \
          || fail 20 "同步仓库缺少 origin 远端"
        sync_git fetch origin main || fail 25 "拉取 origin/main 失败"
        sync_git show-ref --verify --quiet refs/remotes/origin/main \
          || fail 25 "origin/main 不存在"
        tracked_peer_files=$(sync_git ls-files --cached -- \
          "$peer_json_pathspec" "$exclude_pathspec") \
          || fail 23 "无法枚举其他设备快照"
        if [ -n "$tracked_peer_files" ]; then
          sync_git restore --source=HEAD --staged --worktree -- \
            "$peer_json_pathspec" "$exclude_pathspec" \
            || fail 23 "无法恢复其他设备快照"
        fi
        other_changes=$(sync_git status --porcelain=v1 --untracked-files=all \
          -- . "$exclude_pathspec") \
          || fail 23 "无法检查同步仓库工作区状态"
        [ -z "$other_changes" ] \
          || fail 23 "同步仓库包含本机快照以外的未提交改动"

        ensure_local_commits_only_device() {
          audit_base=$(sync_git rev-parse --verify "$1^{commit}") \
            || fail 23 "无法固定待审计基线"
          audit_target=$(sync_git rev-parse --verify "$2^{commit}") \
            || fail 23 "无法固定待审计提交"
          audit_commits=$(sync_git rev-list --reverse "$audit_base..$audit_target") \
            || fail 23 "无法列出本地待推送提交"
          for audit_commit in $audit_commits; do
            audit_parent_line=$(sync_git rev-list --parents -n 1 "$audit_commit") \
              || fail 23 "无法读取待推送提交的父提交"
            set -- $audit_parent_line
            [ "$#" -eq 2 ] \
              || fail 23 "本地待推送历史包含 merge 或 root 提交"
            audit_parent="$2"

            if sync_git diff-tree --quiet --no-renames "$audit_parent" "$audit_commit" --; then
              fail 23 "本地待推送历史包含空提交"
            else
              audit_status="$?"
              [ "$audit_status" -eq 1 ] \
                || fail 23 "无法审计待推送提交内容"
            fi

            if sync_git diff-tree --quiet --no-renames "$audit_parent" "$audit_commit" \
              -- "$device_pathspec"; then
              fail 23 "待推送提交没有修改本机设备快照"
            else
              audit_status="$?"
              [ "$audit_status" -eq 1 ] \
                || fail 23 "无法审计本机设备快照提交"
            fi

            if sync_git diff-tree --quiet --no-renames "$audit_parent" "$audit_commit" \
              -- . "$exclude_pathspec"; then
              :
            else
              audit_status="$?"
              [ "$audit_status" -ne 1 ] \
                || fail 23 "待推送提交触碰了其他设备或非快照文件"
              fail 23 "无法审计待推送提交的其他路径"
            fi
          done
        }

        pre_snapshot_head=$(sync_git rev-parse --verify "HEAD^{commit}") \
          || fail 23 "无法固定快照前本地提交"
        pre_snapshot_base=$(sync_git rev-parse --verify "origin/main^{commit}") \
          || fail 23 "无法固定快照前远端提交"
        ensure_local_commits_only_device "$pre_snapshot_base" "$pre_snapshot_head"
        verified_pre_snapshot_head=$(sync_git rev-parse --verify "HEAD^{commit}") \
          || fail 23 "无法复核快照前本地提交"
        [ "$verified_pre_snapshot_head" = "$pre_snapshot_head" ] \
          || fail 23 "快照前历史审计期间 HEAD 已被其他进程修改"
        python3 - "$HOME/.tokei/usage.30s.py" "$repo" "$device_id" <<'PY' \
          || fail 24 "生成本机数据快照失败"
        import importlib.util
        import sys

        script_path, sync_dir, device_id = sys.argv[1:]
        spec = importlib.util.spec_from_file_location("tokei_usage_sync", script_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("无法加载 usage 脚本")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        module._load_tokei_config = lambda: {
            "sync_dir": sync_dir,
            "device_id": device_id,
        }
        writer = getattr(module, "write_sync_snapshot", None)
        if not callable(writer):
            raise RuntimeError("usage 脚本缺少 write_sync_snapshot")
        raise SystemExit(writer())
        PY

        matches=$(sync_git ls-files --cached --others --exclude-standard \
          -- "$device_pathspec") \
          || fail 24 "无法检查本机设备快照"
        match_count=$(printf '%s\n' "$matches" \
          | awk 'NF { count++ } END { print count + 0 }')
        [ "$match_count" -eq 1 ] \
          || fail 24 "本机设备快照缺失或存在大小写重名文件"

        other_changes=$(sync_git status --porcelain=v1 --untracked-files=all \
          -- . "$exclude_pathspec") \
          || fail 23 "无法检查生成快照后的工作区状态"
        [ -z "$other_changes" ] \
          || fail 23 "生成快照时检测到其他文件被修改"

        sync_git add -- "$device_pathspec" || fail 26 "暂存本机快照失败"
        if ! sync_git diff --cached --quiet -- "$device_pathspec"; then
          sync_git commit --only -m "tokei sync $device_id" -- "$device_pathspec" \
            || fail 26 "提交本机快照失败"
        fi
        post_commit_changes=$(sync_git status --porcelain=v1 --untracked-files=all) \
          || fail 26 "无法检查提交后的工作区状态"
        [ -z "$post_commit_changes" ] \
          || fail 26 "提交后同步仓库仍有未提交改动"
        post_commit_head=$(sync_git rev-parse --verify "HEAD^{commit}") \
          || fail 23 "无法固定提交后的本地提交"
        post_commit_base=$(sync_git rev-parse --verify "origin/main^{commit}") \
          || fail 23 "无法固定提交后的审计基线"
        ensure_local_commits_only_device "$post_commit_base" "$post_commit_head"
        verified_post_commit_head=$(sync_git rev-parse --verify "HEAD^{commit}") \
          || fail 23 "无法复核提交后的本地提交"
        [ "$verified_post_commit_head" = "$post_commit_head" ] \
          || fail 23 "提交后历史审计期间 HEAD 已被其他进程修改"

        write_marker() {
          marker_head="$1"
          marker_onto="$2"
          marker_tmp="$marker.tmp.$$"
          umask 077
          {
            printf 'tokei-sync-rebase-v2\n'
            printf 'refs/heads/main\n'
            printf '%s\n' "$marker_head"
            printf 'origin/main\n'
            printf '%s\n' "$marker_onto"
            printf 'pid=%s\n' "$$"
            date -u '+started_at=%Y-%m-%dT%H:%M:%SZ'
          } > "$marker_tmp" || fail 28 "无法写入 rebase 恢复标记"
          mv -f "$marker_tmp" "$marker" || fail 28 "无法保存 rebase 恢复标记"
        }

        rebase_onto_origin() {
          pre_rebase_head=$(sync_git rev-parse --verify "HEAD^{commit}") \
            || fail 27 "无法读取 rebase 前提交"
          pre_rebase_onto=$(sync_git rev-parse --verify "origin/main^{commit}") \
            || fail 27 "无法读取 rebase 上游提交"
          ensure_local_commits_only_device "$pre_rebase_onto" "$pre_rebase_head"
          checked_rebase_head=$(sync_git rev-parse --verify "HEAD^{commit}") \
            || fail 27 "无法复核 rebase 前提交"
          [ "$checked_rebase_head" = "$pre_rebase_head" ] \
            || fail 23 "rebase 前 HEAD 已被其他进程修改"
          if sync_git merge-base --is-ancestor "$pre_rebase_onto" "$pre_rebase_head"; then
            return 0
          fi
          write_marker "$pre_rebase_head" "$pre_rebase_onto"
          if sync_git rebase --merge "$pre_rebase_onto"; then
            rm -f "$marker"
            return 0
          fi
          if [ -d "$rebase_merge" ] || [ -d "$rebase_apply" ]; then
            fail 27 "rebase 未完成，现场与恢复标记已保留，请人工检查同步仓库"
          fi
          rm -f "$marker"
          fail 27 "本机快照无法安全 rebase 到 origin/main"
        }

        attempt=1
        while [ "$attempt" -le 3 ]; do
          rebase_onto_origin
          candidate_head=$(sync_git rev-parse --verify "HEAD^{commit}") \
            || fail 23 "无法固定 push 候选提交"
          audit_base=$(sync_git rev-parse --verify "origin/main^{commit}") \
            || fail 23 "无法固定 push 审计基线"
          ensure_local_commits_only_device "$audit_base" "$candidate_head"
          push_changes=$(sync_git status --porcelain=v1 --untracked-files=all) \
            || fail 23 "无法检查 push 前的工作区状态"
          [ -z "$push_changes" ] \
            || fail 23 "push 前同步仓库出现未提交改动"
          push_head=$(sync_git rev-parse --verify "HEAD^{commit}") \
            || fail 23 "无法复核 push 前 HEAD"
          [ "$push_head" = "$candidate_head" ] \
            || fail 23 "审计后 HEAD 已被其他进程修改"
          if sync_git push origin "$candidate_head:refs/heads/main"; then
            pushed_head=$(sync_git rev-parse --verify "HEAD^{commit}" 2>/dev/null || true)
            [ "$pushed_head" = "$candidate_head" ] \
              || fail 23 "push 期间 HEAD 已被其他进程修改"
            printf '多设备同步完成\n'
            exit 0
          fi

          sync_git fetch origin main || fail 25 "push 失败后重新拉取 origin/main 失败"
          retry_head=$(sync_git rev-parse --verify "HEAD^{commit}" 2>/dev/null || true)
          [ "$retry_head" = "$candidate_head" ] \
            || fail 23 "push 重试前 HEAD 已被其他进程修改"
          if sync_git merge-base --is-ancestor "$candidate_head" origin/main; then
            printf '远端已包含本机同步提交\n'
            exit 0
          fi
          if sync_git merge-base --is-ancestor origin/main "$candidate_head"; then
            fail 29 "远端没有竞争更新，push 仍失败，请检查认证或分支权限"
          fi
          [ "$attempt" -lt 3 ] || fail 29 "远端持续更新，三次同步重试均失败"
          /bin/sleep "$attempt"
          attempt=$((attempt + 1))
          printf '检测到其他设备同时更新，正在重试 %s/3\n' "$attempt"
        done

        fail 29 "push 失败"
        SH
        chmod +x ~/.tokei/tokei-sync.sh
        (crontab -l 2>/dev/null | grep -v 'tokei-sync.sh'; echo '*/30 * * * * ~/.tokei/tokei-sync.sh') | crontab -
        """
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
        HStack(spacing: 6) {
            Circle().fill(tint.gradient).frame(width: 6, height: 6)
                .shadow(color: tint.opacity(0.4), radius: 2)
            Text(name)
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(Theme.tPrimary)
                .lineLimit(1)
                .minimumScaleFactor(0.72)
                .allowsTightening(true)
                .layoutPriority(1)
            Spacer(minLength: 4)
            Toggle("", isOn: isOn)
                .toggleStyle(.switch)
                .controlSize(.mini)
                .labelsHidden()
                .fixedSize()
        }
        .padding(.horizontal, 8)
        .frame(height: 34)
        .background(
            RoundedRectangle(cornerRadius: 7, style: .continuous)
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
