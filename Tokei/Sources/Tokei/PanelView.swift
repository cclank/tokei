import SwiftUI
import AppKit
import TokeiUpdateSecurity

struct PanelView: View {
    @ObservedObject var store: Store
    @ObservedObject var layout: PanelLayoutContext = PanelLayoutContext()
    var scrollable = true
    @State private var sel: RangeKey = .today
    @State private var claudeModelsOpen = false
    @State private var codexModelsOpen = false
    @State private var codexReserveModelsOpen = false
    @State private var codexResetCardsOpen = false
    @State private var geminiModelsOpen = false
    @State private var cursorModelsOpen = false
    @State private var zaiModelsOpen = false
    @State private var grokModelsOpen = false
    @State private var grokBotModelsOpen = false
    @State private var qoderCliModelsOpen = false
    @State private var hermesModelsOpen = false
    @State private var zcodeModelsOpen = false
    @State private var mimocodeModelsOpen = false
    @State private var piModelsOpen = false
    @State private var primeAgentModelsOpen = false
    @State private var workBuddyModelsOpen = false
    @State private var workBuddyAIModelsOpen = false
    @State private var codeBuddyModelsOpen = false
    @State private var deepSeekHarnessModelsOpen = false
    @State private var openCodeModelsOpen = false
    @State private var qwenCodeModelsOpen = false
    @State private var kimiCodeModelsOpen = false
    @State private var museCodeModelsOpen = false
    @State private var cmdCodeModelsOpen = false
    @State private var devinModelsOpen = false
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
    @AppStorage(AppLanguage.defaultsKey) private var appLanguageRaw = AppLanguage.system.rawValue
    @AppStorage("showClaude") private var showClaude = true
    @AppStorage("showCodex") private var showCodex = true
    @AppStorage("showGemini") private var showGemini = true
    @AppStorage("showCursor") private var showCursor = false
    @AppStorage("showZed") private var showZed = false
    @AppStorage("showSub2API") private var showSub2API = false
    @AppStorage("showZai") private var showZai = false
    @AppStorage("showGrok") private var showGrok = true
    @AppStorage("showGrokBot") private var showGrokBot = true
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
    @AppStorage("showWorkBuddyAI") private var showWorkBuddyAI = true
    @AppStorage("showCodeBuddy") private var showCodeBuddy = true
    @AppStorage("showDeepSeekHarness") private var showDeepSeekHarness = true
    @AppStorage("showOpenCode") private var showOpenCode = true
    @AppStorage("showQwenCode") private var showQwenCode = true
    @AppStorage("showQwenWork") private var showQwenWork = true
    @AppStorage("showKimiCode") private var showKimiCode = true
    @AppStorage("showMuseCode") private var showMuseCode = true
    @AppStorage("showCmdCode") private var showCmdCode = true
    @AppStorage("showDevin") private var showDevin = true
    /// 默认关闭：Grok 额度只读本地日志；开启后才用登录凭据请求实时账单接口。
    @AppStorage("grokLiveQuotaEnabled") private var grokLiveQuotaEnabled = false
    /// 默认关闭：显式授权后复用 Grok Bot 或 Cursor 登录态查询官方额度。
    @AppStorage("grokBotQuotaEnabled") private var grokBotQuotaEnabled = false
    /// 默认关闭：开启后仅查询千问办公桌面端暴露在本机回环地址上的额度接口。
    @AppStorage("qwenWorkQuotaEnabled") private var qwenWorkQuotaEnabled = false
    /// 默认关闭：仅在 Desktop 缓存不可用时复用 Claude Code CLI 登录态查询官方额度。
    @AppStorage("claudeCLIQuotaEnabled") private var claudeCLIQuotaEnabled = false
    @AppStorage(ActivityReporter.enabledKey) private var activityStatisticsEnabled = true
    /// 菜单栏额度来源（与显示卡片独立），每项是一个具体窗口。
    /// 只有历史上就默认开的 Claude 5h 与 Codex 周保持默认开，其余窗口默认关，避免抢占状态栏。
    @AppStorage(MenuBarQuotaSource.claude5h.defaultsKey) private var menuBarQuotaClaude5h = true
    @AppStorage(MenuBarQuotaSource.claudeWeek.defaultsKey) private var menuBarQuotaClaudeWeek = false
    @AppStorage(MenuBarQuotaSource.claudeFable.defaultsKey) private var menuBarQuotaClaudeFable = false
    @AppStorage(MenuBarQuotaSource.codex5h.defaultsKey) private var menuBarQuotaCodex5h = false
    @AppStorage(MenuBarQuotaSource.codexWeek.defaultsKey) private var menuBarQuotaCodexWeek = true
    @AppStorage(MenuBarQuotaSource.kimi5h.defaultsKey) private var menuBarQuotaKimi5h = false
    @AppStorage(MenuBarQuotaSource.kimiSubscription.defaultsKey) private var menuBarQuotaKimiSubscription = false
    @AppStorage(MenuBarQuotaSource.grok.defaultsKey) private var menuBarQuotaGrok = false
    @State private var copyFeedback = false
    @State private var copiedToolID: String?

    private var toolVisibility: UsageToolVisibility {
        UsageToolVisibility(
            claude: showClaude, codex: showCodex, gemini: showGemini, grok: showGrok,
            grokBot: showGrokBot,
            qoder: showQoder, qoderwork: showQoderWork, qodercli: showQoderCli,
            hermes: showHermes, zcode: showZcode, mimocode: showMimoCode,
            openclaw: showOpenClaw, pi: showPi, primeAgent: showPrimeAgent,
            workbuddy: showWorkBuddy, workbuddyAI: showWorkBuddyAI,
            codebuddy: showCodeBuddy,
            deepseekHarness: showDeepSeekHarness,
            opencode: showOpenCode, qwencode: showQwenCode, kimicode: showKimiCode,
            musecode: showMuseCode, cmdcode: showCmdCode,
            devin: showDevin
        )
    }

    private var visibleCount: Int {
        [showClaude, showCodex, showGemini, showCursor, showZed, showSub2API, showZai,
         showGrok, showGrokBot, showQoder, showQoderWork, showQoderCli, showHermes,
         showZcode, showMimoCode,
         showOpenClaw, showPi, showWorkBuddy, showWorkBuddyAI, showDeepSeekHarness,
         showCodeBuddy,
         showOpenCode, showQwenCode,
         showQwenWork, showKimiCode, showMuseCode, showCmdCode, showPrimeAgent, showDevin].filter { $0 }.count
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
        layout.contentSize.height
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
        Group {
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
        .frame(
            width: scrollable ? layout.contentSize.width : nil,
            height: scrollable ? layout.contentSize.height : nil,
            alignment: .top
        )
        .background {
            if scrollable { Theme.bg }
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
                QuotaHistoryView(history: store.quotaHistory, onLoad: store.loadQuotaDetail)
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
                            .font(.system(size: Theme.fontSize(12), weight: .medium))
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
                        .font(.system(size: Theme.fontSize(16), weight: .bold))
                        .foregroundStyle(Theme.brand)
                        .overlay(alignment: .topTrailing) {
                            if let e = Self.festiveEmoji() {
                                Text(e).font(.system(size: Theme.fontSize(11))).offset(x: 7, y: -7)
                            }
                        }
                    VStack(alignment: .leading, spacing: 0) {
                        Text("Tokei")
                            .font(.system(size: Theme.fontSize(15), weight: .bold, design: .rounded))
                            .tracking(0.5)
                            .lineLimit(1)
                        Text(L10n.t("s448"))
                            .font(.system(size: Theme.fontSize(9)))
                            .foregroundStyle(Theme.tTertiary)
                            .lineLimit(1)
                    }
                    .fixedSize(horizontal: true, vertical: false)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .tip(L10n.tabHome)
            updatePill
            if store.syncFailStreak >= 3 {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: Theme.fontSize(11)))
                    .foregroundStyle(.orange)
                    .help(L10n.f("s212", store.syncFailStreak, store.syncStatus, store.syncDetail))
            }
            Spacer()
            if hasMultipleDevices {
                deviceScopePicker
            }
            Text(store.lastUpdated)
                .font(.system(size: Theme.fontSize(9.5), design: .monospaced))
                .foregroundStyle(Theme.tTertiary)
            Button {
                withAnimation(.easeInOut(duration: 0.35)) { mode = mode == .projects ? .cards : .projects }
            } label: {
                Image(systemName: "folder")
                    .font(.system(size: Theme.fontSize(11), weight: .medium))
                    .foregroundStyle(mode == .projects ? Theme.claude : Theme.tTertiary)
                    .frame(width: 24, height: 24)
                    .background(Circle().fill(Color.primary.opacity(0.06)))
                    .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .tip(L10n.t("tab_projects"))
            Button {
                mode = mode == .quotaHistory ? .cards : .quotaHistory
            } label: {
                Image(systemName: "chart.xyaxis.line")
                    .font(.system(size: Theme.fontSize(11), weight: .medium))
                    .foregroundStyle(mode == .quotaHistory ? Theme.claude : Theme.tTertiary)
                    .frame(width: 24, height: 24)
                    .background(Circle().fill(Color.primary.opacity(0.06)))
                    .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .tip(L10n.t("tab_quota"))
            Button {
                withAnimation(.easeInOut(duration: 0.35)) { mode = mode == .dashboard ? .cards : .dashboard }
            } label: {
                Image(systemName: "chart.bar")
                    .font(.system(size: Theme.fontSize(11), weight: .medium))
                    .foregroundStyle(mode == .dashboard ? Theme.claude : Theme.tTertiary)
                    .frame(width: 24, height: 24)
                    .background(Circle().fill(Color.primary.opacity(0.06)))
                    .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .tip(L10n.t("tab_dashboard"))
            Button {
                withAnimation(.easeInOut(duration: 0.35)) { mode = mode == .settings ? .cards : .settings }
            } label: {
                Image(systemName: "gearshape")
                    .font(.system(size: Theme.fontSize(11), weight: .medium))
                    .foregroundStyle(mode == .settings ? Theme.claude : Theme.tTertiary)
                    .frame(width: 24, height: 24)
                    .background(Circle().fill(Color.primary.opacity(0.06)))
                    .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .tip(L10n.t("settings"))
        }
    }

    var deviceScopePicker: some View {
        Picker("", selection: $store.showAllDevices) {
            Text(L10n.scopeLocal).tag(false)
            Text(L10n.scopeAll).tag(true)
        }
        .pickerStyle(.segmented)
        .frame(width: 92)
        .controlSize(.mini)
        .onChange(of: store.showAllDevices) { _ in store.applyDisplayMode() }
        .tip(L10n.t("s291"))
    }

    private func toolCards(for u: Usage) -> [ToolCardItem] {
        let cr = u.claude.ranges.get(sel), xr = u.codex.ranges.get(sel)
        let geminiRange = u.gemini.ranges.get(sel)
        let kr = u.grok.ranges.get(sel)
        let grokBotDisplay: (key: RangeKey, range: QoderRange, usage: TokenUsageRange) = {
            let selected = u.grokBot.ranges.get(sel)
            let selectedUsage = u.grokBot.quota.usage?.ranges.get(sel) ?? TokenUsageRange()
            if selected.sessions > 0 || selected.calls > 0 || selected.turns > 0 ||
                selectedUsage.totalTokens > 0 || selectedUsage.requests > 0 {
                return (sel, selected, selectedUsage)
            }
            for key in [RangeKey.today, .yesterday, .week, .lastWeek, .month, .year, .all]
                where key != sel {
                let candidate = u.grokBot.ranges.get(key)
                let candidateUsage = u.grokBot.quota.usage?.ranges.get(key) ?? TokenUsageRange()
                if candidate.sessions > 0 || candidate.calls > 0 || candidate.turns > 0 ||
                    candidateUsage.totalTokens > 0 || candidateUsage.requests > 0 {
                    return (key, candidate, candidateUsage)
                }
            }
            return (sel, selected, selectedUsage)
        }()
        let qr = u.qoder.ranges.get(sel), qwr = u.qoderwork.ranges.get(sel)
        let qclir = u.qodercli.ranges.get(sel)
        let hr = u.hermes.ranges.get(sel)
        let zr = u.zcode.ranges.get(sel), mr = u.mimocode.ranges.get(sel)
        let lr = u.openclaw.ranges.get(sel), pr = u.pi.ranges.get(sel)
        let par = u.prime_agent.ranges.get(sel)
        let wr = u.workbuddy.ranges.get(sel), wair = u.workbuddyAI.ranges.get(sel)
        let cbr = u.codebuddy.ranges.get(sel)
        let or = u.opencode.ranges.get(sel)
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
        let mcr = u.musecode.ranges.get(sel), ccr = u.cmdcode.ranges.get(sel)
        let dvr = u.devin.ranges.get(sel)
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
                         active: geminiRange.hasUsage,
                         tint: Theme.gemini,
                         content: AnyView(geminiBlock(geminiRange, quota: u.antigravity))),
            ToolCardItem(id: "cursor", name: "Cursor", visible: showCursor,
                         active: cursorUsage.totalTokens > 0 || cursorUsage.requests > 0,
                         tint: Theme.cursor,
                         presentation: cursorUsage.totalTokens > 0 ? .standard : .compactStatus,
                         content: AnyView(providerQuotaBlock(
                            "Cursor", quota: u.cursor, usage: cursorUsage,
                            modelsOpen: $cursorModelsOpen, tint: Theme.cursor,
                            setupHint: L10n.t("s492")))),
            ToolCardItem(id: "zed", name: "Zed", visible: showZed, active: showZed,
                         tint: Theme.zed, presentation: .compactStatus,
                         content: AnyView(providerQuotaBlock(
                            "Zed", quota: u.zed, tint: Theme.zed,
                            setupHint: L10n.t("s485")))),
            ToolCardItem(id: "sub2api", name: "Sub2API", visible: showSub2API, active: showSub2API,
                         tint: Theme.sub2api, presentation: .compactStatus,
                         content: AnyView(providerQuotaBlock(
                            "Sub2API", quota: u.sub2api, tint: Theme.sub2api,
                            setupHint: L10n.t("s488")))),
            ToolCardItem(id: "zai", name: "z.ai / GLM", visible: showZai,
                         active: u.zai.available || zaiUsage.totalTokens > 0,
                         tint: Theme.zai,
                         presentation: zaiUsage.totalTokens > 0 ? .standard : .compactStatus,
                         content: AnyView(providerQuotaBlock(
                            "z.ai / GLM", quota: u.zai, usage: zaiUsage,
                            modelsOpen: $zaiModelsOpen, tint: Theme.zai,
                            setupHint: L10n.t("s489")))),
            ToolCardItem(id: "grok", name: "Grok", visible: showGrok,
                         active: kr.sessions > 0 || kr.usage_calls > 0 || u.grok.pct != nil,
                         tint: Theme.grok,
                         presentation: grokQuotaState.shouldUseCompactCard(
                            hasUsage: kr.sessions > 0 || kr.usage_calls > 0
                         ) ? .compactStatus : .standard,
                         content: AnyView(grokBlock(u.grok, kr))),
            ToolCardItem(id: "grok-bot", name: "Grok Bot", visible: showGrokBot,
                         active: grokBotDisplay.range.sessions > 0 ||
                             grokBotDisplay.range.calls > 0 ||
                             grokBotDisplay.usage.totalTokens > 0 ||
                             grokBotDisplay.usage.requests > 0 ||
                             u.grokBot.quota.available,
                         tint: Theme.grokBot,
                         presentation: grokBotDisplay.range.sessions == 0 &&
                             grokBotDisplay.range.calls == 0 &&
                             grokBotDisplay.range.turns == 0 &&
                             grokBotDisplay.usage.totalTokens == 0 &&
                             grokBotDisplay.usage.requests == 0 &&
                             u.grokBot.quota.available
                             ? .compactStatus : .standard,
                         content: AnyView(grokBotBlock(
                            u.grokBot, grokBotDisplay.range, grokBotDisplay.usage,
                            displayedRange: grokBotDisplay.key))),
            ToolCardItem(id: "qoder", name: "Qoder Desktop", visible: showQoder,
                         active: qr.calls > 0 || qr.in + qr.cached + qr.out > 0,
                         tint: Theme.qoder, content: AnyView(qoderIdeBlock(u.qoder, qr))),
            ToolCardItem(id: "qoderwork", name: "QoderWork", visible: showQoderWork,
                         active: qwr.calls > 0 || qwr.totalTokens > 0,
                         tint: Theme.qoderwork, content: AnyView(qoderworkBlock(u.qoderwork, qwr))),
            ToolCardItem(id: "qodercli", name: "Qoder CLI", visible: showQoderCli,
                         active: qclir.calls > 0 || qclir.totalTokens > 0,
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
            ToolCardItem(id: "workbuddy-ai", name: "WorkBuddy Intl.",
                         visible: showWorkBuddyAI, active: wair.sessions > 0,
                         tint: Theme.workbuddyAI,
                         content: AnyView(tokenUsageBlock(
                            title: "WorkBuddy Intl.", wair, tint: Theme.workbuddyAI,
                            modelsOpen: $workBuddyAIModelsOpen, toolID: "workbuddy-ai"))),
            ToolCardItem(id: "codebuddy", name: "CodeBuddy", visible: showCodeBuddy,
                         active: cbr.sessions > 0 || cbr.totalTokens > 0 || cbr.credits > 0,
                         tint: Theme.codebuddy,
                         content: AnyView(tokenUsageBlock(
                            title: "CodeBuddy", cbr, tint: Theme.codebuddy,
                            modelsOpen: $codeBuddyModelsOpen, showsCost: false,
                            showsCredits: true, toolID: "codebuddy"))),
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
            ToolCardItem(id: "qwenwork", name: L10n.t("s142"), visible: showQwenWork,
                         active: qwenWorkQuotaEnabled || u.qwenwork.available ||
                             u.qwenwork.remaining != nil || !u.qwenwork.segments.isEmpty ||
                             u.qwenwork.shared != nil,
                         tint: Theme.qwenwork, content: AnyView(qwenWorkBlock(u.qwenwork))),
            ToolCardItem(id: "devin", name: "Devin", visible: showDevin,
                         active: dvr.sessions > 0 || u.devin.quota.available,
                         tint: Theme.devin,
                         content: AnyView(devinBlock(dvr, quota: u.devin.quota))),
            ToolCardItem(id: "kimicode", name: "Kimi Code", visible: showKimiCode,
                         active: kcr.sessions > 0 || u.kimicode.hasQuota || u.kimicode.hasStaleQuota,
                         tint: Theme.kimicode, content: AnyView(kimiCodeBlock(u.kimicode, kcr))),
            ToolCardItem(id: "musecode", name: "Muse Code", visible: showMuseCode, active: mcr.sessions > 0,
                         tint: Theme.musecode, content: AnyView(tokenUsageBlock(title: "Muse Code", mcr, tint: Theme.musecode, modelsOpen: $museCodeModelsOpen, reasonIncludedInOutput: true, toolID: "musecode"))),
            ToolCardItem(id: "cmdcode", name: "Command Code", visible: showCmdCode, active: ccr.sessions > 0,
                         tint: Theme.cmdcode, content: AnyView(tokenUsageBlock(title: "Command Code", ccr, tint: Theme.cmdcode, modelsOpen: $cmdCodeModelsOpen, toolID: "cmdcode"))),
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
                CostHeadline(value: Fmt.human(r.in + r.out + r.cr + r.cw), caption: L10n.f("s066", sel.label), tint: Theme.claude)
                metricGrid([
                    .init("dollarsign.circle", L10n.metricCost, String(format: "$%.2f", r.cost)),
                ], hit: r.hit, extra: [
                    .init("arrow.down", L10n.metricIn, Fmt.human(r.in)),
                    .init("arrow.up", L10n.metricOut, Fmt.human(r.out)),
                    .init("bolt.fill", L10n.metricCacheRead, Fmt.human(r.cr)),
                    .init("square.stack.3d.up.fill", L10n.metricCacheWrite, Fmt.human(r.cw)),
                ], tint: Theme.claude)
                let claudeRows = r.models.filter {
                    $0.name != L10n.modelSynthetic && $0.name != L10n.legacySyntheticName && $0.name != "<synthetic>"
                }.map { m in
                    let denom = m.cr + m.cw + m.in
                    let hit = denom > 0 ? Double(m.cr) / Double(denom) * 100 : 0
                    return ModelRow(name: m.name, pin: m.pin, pout: m.pout, cost: m.cost, total: m.total, hit: hit,
                                   tokIn: m.in, tokOut: m.out, tokCR: m.cr, tokCW: m.cw)
                }
                if !claudeRows.isEmpty {
                    modelDisclosure(claudeRows, open: $claudeModelsOpen, tint: Theme.claude)
                }
            } else if !compactExpired && quotaState != .unavailable {
                usageEmptyHint(recent: recentUsageHint { key in
                    let range = c.ranges.get(key)
                    return range.in + range.out + range.cr + range.cw
                })
            }

            if compactExpired {
                quotaStateNotice(
                    title: L10n.t("s541"),
                    detail: L10n.t("s452"),
                    source: L10n.t("s015"),
                    updated: c.q_updated,
                    tint: Theme.claude,
                    warning: true
                )
            } else if quotaState != .unavailable {
                thinDivider
                if let q5 = c.q5, c.q5_stale != true {
                    quotaRow(title: L10n.t("s009"), pct: 100 - q5, reset: c.q5_reset, tint: Theme.claude)
                }
                if let q7 = c.q7, c.q7_stale != true {
                    quotaRow(title: L10n.t("s189"), pct: 100 - q7, reset: c.q7_reset, tint: Theme.claude)
                }
                if let qf = c.qf, c.qf_stale != true {
                    quotaRow(title: L10n.t("s188"), pct: 100 - qf, reset: c.qf_reset, tint: .orange)
                }
                if quotaState == .expired {
                    quotaStateNotice(
                        title: L10n.t("s541"),
                        detail: L10n.t("s256"),
                        source: L10n.t("s015"),
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
                    title: L10n.t("s353"),
                    detail: claudeCLIQuotaEnabled
                        ? L10n.t("s445")
                        : L10n.t("s100"),
                    source: L10n.t("s015"),
                    updated: c.q_updated,
                    tint: Theme.claude
                )
            }
        }
    }

    // MARK: - Codex 卡片
    @ViewBuilder
    func codexBlock(_ x: CodexStat, _ r: CodexRange) -> some View {
        let hasQuotaData = x.p5 != nil || x.pw != nil || x.reserveQuota != nil ||
            (x.reset_cards?.count ?? 0) > 0
        VStack(alignment: .leading, spacing: 11) {
            cardHead("Codex", tint: Theme.codex, sessions: r.sessions, toolID: "codex")
            if r.sessions > 0 {
                CostHeadline(value: Fmt.human(r.in + r.cached + r.out), caption: L10n.f("s066", sel.label), tint: Theme.codex)
                metricGrid([.init("dollarsign.circle", L10n.metricCost, String(format: "$%.2f", r.cost))],
                    hit: r.hit, extra: {
                    var items: [Metric] = [
                        .init("arrow.down", L10n.metricIn, Fmt.human(r.in)),
                        .init("bolt.fill", L10n.metricCacheRead, Fmt.human(r.cached)),
                        .init("arrow.up", L10n.metricOut, Fmt.human(r.out)),
                    ]
                    if r.reason > 0 { items.append(.init("brain", L10n.metricReason, Fmt.human(r.reason))) }
                    return items
                }(), tint: Theme.codex)
                if !r.models.isEmpty {
                    tokenModelDisclosure(r.models, open: $codexModelsOpen, tint: Theme.codex,
                                         reasonIncludedInOutput: true)
                }
            } else if hasQuotaData {
                usageEmptyHint(recent: recentUsageHint { key in
                    let range = x.ranges.get(key)
                    return range.in + range.out + range.reason
                })
            }
            if hasQuotaData {
                thinDivider
            }
            if let p5 = x.p5, x.p5_stale != true {
                quotaRow(title: L10n.t("s009"), pct: 100 - p5, reset: x.r5, tint: Theme.codex)
            }
            if let pw = x.pw, x.pw_stale != true {
                quotaRow(title: L10n.t("s190"), pct: 100 - pw, reset: x.rw, tint: Theme.codex)
            }
            // Reserve 常驻:额度行跟 5h/周排在一起;按模型紧跟额度行,不跟重置卡/plan隔开。
            if let q = x.reserveQuota, let pct = q.usedPercent, q.stale != true {
                quotaRow(title: L10n.t("s034"), pct: 100 - pct, detail: L10n.t("s246"), reset: q.resetsAt, tint: Theme.codex)
            } else if let q = x.reserveQuota, q.stale == true {
                quotaStateNotice(
                    title: L10n.t("s035"),
                    detail: L10n.t("s527"),
                    source: L10n.t("s018"),
                    updated: q.updated,
                    tint: Theme.codex,
                    warning: true
                )
            }
            // Reserve 用量明细:只有按模型一行,紧跟额度行。
            if let reserve = x.reserveRanges?.get(sel), reserve.sessions > 0 {
                codexReserveBlock(reserve)
            }
            if x.pw_stale == true {
                codexQuotaStatus(x)
            }
            if let cards = x.reset_cards, cards.count > 0 {
                codexResetCardsRow(cards)
            }
            if let plan = x.plan {
                HStack {
                    Text("plan").font(.system(size: Theme.fontSize(11))).foregroundStyle(Theme.tTertiary)
                    Spacer()
                    Text(plan)
                        .font(.system(size: Theme.fontSize(10), weight: .semibold, design: .monospaced))
                        .foregroundStyle(Theme.tSecondary)
                        .padding(.horizontal, 7).padding(.vertical, 2)
                        .background(Capsule().fill(Theme.codex.opacity(0.16)))
                }
            }
            if r.sessions > 0 && !hasQuotaData {
                thinDivider
                quotaStateNotice(
                    title: L10n.t("s353"),
                    detail: L10n.t("s443"),
                    source: L10n.t("s018"),
                    updated: nil,
                    tint: Theme.codex
                )
            }
        }
    }

    // MARK: - Kimi Code 卡片
    // 额度来自官方 usages 接口,登录态由 Kimi Code CLI 自己刷新(有效期很短),
    // 因此这里必须能表达"读数已过期",而不是把上一次的百分比一直显示下去。
    @ViewBuilder
    func kimiCodeBlock(_ x: KimiCodeStat, _ r: TokenUsageRange) -> some View {
        VStack(alignment: .leading, spacing: 11) {
            cardHead("Kimi Code", tint: Theme.kimicode, sessions: r.sessions, toolID: "kimicode")
            if r.sessions > 0 {
                CostHeadline(value: Fmt.human(r.in + r.out + r.cr + r.cw + r.reason),
                             caption: L10n.f("s066", sel.label), tint: Theme.kimicode)
                metricGrid([], hit: r.hit, extra: tokenUsageMetrics(r), tint: Theme.kimicode)
                if !r.models.isEmpty {
                    tokenModelDisclosure(r.models, open: $kimiCodeModelsOpen, tint: Theme.kimicode)
                }
            } else if x.hasQuota {
                usageEmptyHint(recent: recentUsageHint { key in
                    let range = x.ranges.get(key)
                    return range.in + range.out + range.cr + range.cw + range.reason
                })
            } else {
                emptyHint
            }
            if x.hasQuota || x.hasStaleQuota {
                thinDivider
            }
            if let p5 = x.p5, x.p5_stale != true {
                quotaRow(title: L10n.t("s009"), pct: 100 - p5, reset: x.r5, tint: Theme.kimicode)
            }
            if let pw = x.pw, x.pw_stale != true {
                // 接口只给了这一档的重置时刻,没有说周期是周还是月,所以标题不写周期名。
                quotaRow(title: L10n.t("s479"), pct: 100 - pw, reset: x.rw, tint: Theme.kimicode)
            }
            if x.hasStaleQuota {
                quotaStateNotice(
                    title: L10n.t("s551"),
                    detail: L10n.t("s030"),
                    source: "api.kimi.com",
                    updated: x.q_updated,
                    tint: Theme.kimicode,
                    warning: true
                )
            }
            if let plan = x.plan, !plan.isEmpty {
                HStack {
                    Text("plan").font(.system(size: Theme.fontSize(11))).foregroundStyle(Theme.tTertiary)
                    Spacer()
                    Text(plan.replacingOccurrences(of: "LEVEL_", with: ""))
                        .font(.system(size: Theme.fontSize(10), weight: .semibold, design: .monospaced))
                        .foregroundStyle(Theme.tSecondary)
                        .padding(.horizontal, 7).padding(.vertical, 2)
                        .background(Capsule().fill(Theme.kimicode.opacity(0.16)))
                }
            }
            if r.sessions > 0 && !x.hasQuota && !x.hasStaleQuota {
                thinDivider
                quotaStateNotice(
                    title: L10n.t("s353"),
                    detail: L10n.t("s444"),
                    source: L10n.t("s029"),
                    updated: nil,
                    tint: Theme.kimicode
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
                    .font(.system(size: Theme.fontSize(10)))
                    .foregroundStyle(Theme.codex)
                Text(L10n.t("s526"))
                    .font(.system(size: Theme.fontSize(11)))
                    .foregroundStyle(Theme.tSecondary)
                Text(L10n.f("s049", cards.count))
                    .font(.system(size: Theme.fontSize(10), weight: .semibold, design: .monospaced))
                    .foregroundStyle(Theme.tPrimary)
                Spacer(minLength: 6)
                if let nearest = expirations.first {
                    Text(L10n.f("s367", Fmt.beijingTime(nearest)))
                        .font(.system(size: Theme.fontSize(9.5), design: .monospaced))
                        .foregroundStyle(Theme.tTertiary)
                }
                Image(systemName: codexResetCardsOpen ? "chevron.down" : "chevron.right")
                    .font(.system(size: Theme.fontSize(8), weight: .bold))
                    .foregroundStyle(Theme.tTertiary)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help(L10n.t("s401"))

        if codexResetCardsOpen {
            VStack(alignment: .leading, spacing: 7) {
                HStack {
                    Text(L10n.t("s130"))
                        .font(.system(size: Theme.fontSize(9.5), weight: .medium))
                        .foregroundStyle(Theme.tTertiary)
                    Spacer()
                    Text(L10n.t("s140"))
                        .font(.system(size: Theme.fontSize(9), design: .monospaced))
                        .foregroundStyle(Theme.tTertiary)
                }
                ForEach(Array(expirations.enumerated()), id: \.offset) { index, expiry in
                    HStack(spacing: 7) {
                        Text("\(index + 1)")
                            .font(.system(size: Theme.fontSize(9), weight: .semibold, design: .monospaced))
                            .foregroundStyle(Theme.codex)
                            .frame(width: 16, height: 16)
                            .background(Circle().fill(Theme.codex.opacity(0.14)))
                        Text(L10n.t("s219"))
                            .font(.system(size: Theme.fontSize(10.5), weight: .medium))
                            .foregroundStyle(Theme.tSecondary)
                        Spacer()
                        Text(Fmt.beijingTime(expiry, full: true))
                            .font(.system(size: Theme.fontSize(9.5), design: .monospaced))
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

    // MARK: - Codex Luna Reserve 用量明细(额度行在上方跟 5h/周排在一起)
    // 明细只有按模型展开,没有顶层总量/成本大字:Reserve 只有 gpt-reserve 一个模型,
    // 顶层再摆一遍和按模型里完全重复。无用量时整个分区不显示(额度行常驻在上方)。
    @ViewBuilder
    func codexReserveBlock(_ r: CodexRange) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            tokenModelDisclosure(r.models, open: $codexReserveModelsOpen, tint: Theme.codex,
                                 reasonIncludedInOutput: true)
        }
    }

    // MARK: - Gemini / Antigravity 卡片
    @ViewBuilder
    func geminiBlock(
        _ r: GeminiRange,
        quota: ProviderQuotaStat
    ) -> some View {
        let usageLabel = sel.label
        VStack(alignment: .leading, spacing: 11) {
            if r.hasUsage {
                cardHead("Gemini / Antigravity", tint: Theme.gemini, sessions: r.sessions,
                         toolID: "gemini")
                CostHeadline(value: Fmt.human(r.totalTokens), caption: L10n.f("s074", usageLabel), tint: Theme.gemini)
                metricGrid([.init("dollarsign.circle", L10n.metricCost, String(format: "$%.2f", r.cost))],
                    hit: r.hit, extra: {
                    var items: [Metric] = [
                        .init("arrow.down", L10n.metricIn, Fmt.human(r.in)),
                        .init("arrow.up", L10n.metricOut, Fmt.human(r.out)),
                        .init("bolt.fill", L10n.t("s462"), Fmt.human(r.cached)),
                    ]
                    if r.thoughts > 0 { items.append(.init("brain", L10n.metricReason, Fmt.human(r.thoughts))) }
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
                if quota.available {
                    thinDivider
                    providerQuotaContent(quota, tint: Theme.gemini)
                }
            }
        }
    }

    /// Devin 的两个来源互不相干，卡片上也分开呈现：上半是 CLI 会话库里的
    /// 本地 token，下半是桌面端启动时写下的套餐额度。任何一半有数据就画那一半。
    func devinBlock(_ r: TokenUsageRange, quota: ProviderQuotaStat) -> some View {
        let hasUsage = r.sessions > 0
        return VStack(alignment: .leading, spacing: 11) {
            cardHead("Devin", tint: Theme.devin, sessions: r.sessions, toolID: "devin")
            if hasUsage {
                CostHeadline(value: Fmt.human(r.totalTokens),
                             caption: L10n.f("s066", sel.label), tint: Theme.devin)
                metricGrid([.init("dollarsign.circle", L10n.metricCost,
                                  String(format: "$%.2f", r.cost))],
                           hit: r.hit, extra: tokenUsageMetrics(r), tint: Theme.devin)
                if !r.models.isEmpty {
                    tokenModelDisclosure(r.models, open: $devinModelsOpen, tint: Theme.devin)
                }
            }
            if quota.available {
                if hasUsage { thinDivider }
                providerQuotaContent(quota, tint: Theme.devin)
            } else if !hasUsage {
                Text(L10n.t("s490")
                     + L10n.t("s045"))
                    .font(.system(size: Theme.fontSize(10)))
                    .foregroundStyle(Theme.tTertiary)
                    .fixedSize(horizontal: false, vertical: true)
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
                    .font(.system(size: Theme.fontSize(10)))
                    .foregroundStyle(Theme.tTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    func providerTokenUsageContent(
        _ r: TokenUsageRange,
        modelsOpen: Binding<Bool>?,
        tint: Color,
        periodLabel: String? = nil
    ) -> some View {
        var top: [Metric] = []
        if r.cost > 0 {
            top.append(.init("dollarsign.circle", L10n.t("s012"), String(format: "$%.2f", r.cost)))
        }
        if r.requests > 0 {
            top.append(.init("arrow.triangle.2.circlepath", L10n.t("s491"), Fmt.human(r.requests)))
        }
        var details: [Metric] = []
        if r.hasComponents {
            details = [
                .init("arrow.down", L10n.metricIn, Fmt.human(r.in)),
                .init("arrow.up", L10n.metricOut, Fmt.human(r.out)),
            ]
            if r.cr > 0 { details.append(.init("bolt.fill", L10n.metricCacheRead, Fmt.human(r.cr))) }
            if r.cw > 0 {
                details.append(.init("square.stack.3d.up.fill", L10n.metricCacheWrite, Fmt.human(r.cw)))
            }
            if r.reason > 0 { details.append(.init("brain", L10n.metricReason, Fmt.human(r.reason))) }
        }
        return VStack(alignment: .leading, spacing: 9) {
            CostHeadline(
                value: Fmt.human(r.totalTokens),
                caption: L10n.f("s061", r.coverage ?? periodLabel ?? sel.label),
                tint: tint
            )
            Text(L10n.t("s500"))
                .font(.system(size: Theme.fontSize(8.5)))
                .foregroundStyle(Theme.tTertiary)
            if !top.isEmpty || !details.isEmpty {
                metricGrid(top, hit: r.hit, extra: details, tint: tint)
            }
            if !r.models.isEmpty, let modelsOpen {
                tokenModelDisclosure(
                    r.models,
                    open: modelsOpen,
                    tint: tint,
                    periodLabel: periodLabel
                )
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
                        .font(.system(size: Theme.fontSize(9), design: .monospaced))
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
                        .font(.system(size: Theme.fontSize(11)))
                        .foregroundStyle(Theme.tSecondary)
                    Spacer(minLength: 6)
                    Text(window.detail ?? L10n.t("s549"))
                        .font(.system(size: Theme.fontSize(9.5), design: .monospaced))
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
                            .font(.system(size: Theme.fontSize(10)))
                            .foregroundStyle(Theme.tTertiary)
                        Spacer(minLength: 8)
                        VStack(alignment: .trailing, spacing: 1) {
                            Text(providerQuotaDetailValue(detail))
                                .font(.system(size: Theme.fontSize(10), weight: .semibold, design: .monospaced))
                                .foregroundStyle(Theme.tPrimary)
                            if let secondary = detail.secondary, !secondary.isEmpty {
                                Text(secondary)
                                    .font(.system(size: Theme.fontSize(8.5), design: .monospaced))
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
                title: L10n.t("s541"),
                detail: L10n.t("s252"),
                source: quota.source ?? L10n.t("s032"),
                updated: quota.updated,
                tint: tint,
                warning: true
            )
        } else if let updated = quota.updated {
            HStack(spacing: 5) {
                Image(systemName: "clock")
                    .font(.system(size: Theme.fontSize(8.5)))
                Text(L10n.f("s545", Fmt.reset(updated)))
                    .font(.system(size: Theme.fontSize(9), design: .monospaced))
                Spacer(minLength: 4)
            }
            .foregroundStyle(Theme.tTertiary)
        }
    }

    func providerQuotaPill(_ text: String, tint: Color) -> some View {
        Text(text)
            .font(.system(size: Theme.fontSize(9.5), weight: .semibold, design: .monospaced))
            .foregroundStyle(Theme.tSecondary)
            .padding(.horizontal, 7)
            .padding(.vertical, 2)
            .background(Capsule().fill(tint.opacity(0.16)))
    }

    func providerQuotaDetailValue(_ detail: ProviderQuotaDetail) -> String {
        if detail.label.contains(L10n.t("s129")), let epoch = Int(detail.value) {
            return Fmt.reset(epoch)
        }
        return detail.value
    }

    // MARK: - Grok Bot 卡片
    @ViewBuilder
    func grokBotBlock(
        _ stat: GrokBotStat,
        _ r: QoderRange,
        _ usage: TokenUsageRange,
        displayedRange: RangeKey
    ) -> some View {
        let hasActivity = r.sessions > 0 || r.calls > 0 || r.turns > 0
        let hasUsage = usage.totalTokens > 0 || usage.requests > 0
        VStack(alignment: .leading, spacing: 11) {
            cardHead("Grok Bot", tint: Theme.grokBot, sessions: r.sessions,
                     toolID: hasActivity && displayedRange == sel ? "grok-bot" : nil)
            if hasUsage {
                if displayedRange != sel {
                    Text(L10n.f("s068", sel.label, displayedRange.label))
                        .font(.system(size: Theme.fontSize(9.5)))
                        .foregroundStyle(Theme.tTertiary)
                }
                providerTokenUsageContent(
                    usage,
                    modelsOpen: $grokBotModelsOpen,
                    tint: Theme.grokBot,
                    periodLabel: displayedRange.label
                )
                if hasActivity {
                    Text(L10n.f("s388", r.turns, r.calls))
                        .font(.system(size: Theme.fontSize(8.5)))
                        .foregroundStyle(Theme.tTertiary)
                }
            } else if hasActivity {
                if displayedRange != sel {
                    Text(L10n.f("s068", sel.label, displayedRange.label))
                        .font(.system(size: Theme.fontSize(9.5)))
                        .foregroundStyle(Theme.tTertiary)
                }
                CostHeadline(
                    value: Fmt.human(r.calls > 0 ? r.calls : r.turns),
                    caption: L10n.f("s056", displayedRange.label),
                    tint: Theme.grokBot
                )
                metricGrid({
                    var items: [Metric] = [
                        .init("bubble.left", L10n.t("s106"), Fmt.human(r.turns)),
                        .init("sparkles", L10n.t("s192"), Fmt.human(r.calls)),
                    ]
                    if r.tools > 0 {
                        items.append(.init("wrench.and.screwdriver", L10n.t("s231"), Fmt.human(r.tools)))
                    }
                    if r.duration > 0 {
                        items.append(.init("clock", L10n.t("s425"), Fmt.duration(r.duration * 1000)))
                    }
                    return items
                }(), tint: Theme.grokBot)
                Text(L10n.t("s386"))
                    .font(.system(size: Theme.fontSize(8.5)))
                    .foregroundStyle(Theme.tTertiary)
            } else if !stat.quota.available {
                emptyHint
            }
            if stat.quota.available {
                if hasActivity || hasUsage { thinDivider }
                providerQuotaContent(stat.quota, tint: Theme.grokBot)
            } else if grokBotQuotaEnabled {
                Text(L10n.t("s220"))
                    .font(.system(size: Theme.fontSize(9)))
                    .foregroundStyle(Theme.tTertiary)
            }
        }
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
                             caption: r.usage_available ? L10n.f("s067", sel.label) : L10n.f("s065", sel.label),
                             tint: Theme.grok)
                let grokMetrics: [Metric] = {
                    var items: [Metric] = []
                    if r.usage_available {
                        if r.cost > 0 {
                            items.append(.init("dollarsign.circle", L10n.metricCost, String(format: "$%.2f", r.cost)))
                        }
                        items.append(.init("arrow.down", L10n.metricIn, Fmt.human(r.in)))
                        items.append(.init("bolt.fill", L10n.metricCacheRead, Fmt.human(r.cr)))
                        items.append(.init("arrow.up", L10n.metricOut, Fmt.human(r.out)))
                        if r.reason > 0 { items.append(.init("brain", L10n.metricReason, Fmt.human(r.reason))) }
                        items.append(.init("waveform", L10n.metricCalls, "\(r.usage_calls)"))
                    }
                    items.append(contentsOf: [
                        .init("arrow.triangle.2.circlepath", L10n.t("s504"), "\(r.turns ?? 0)"),
                        .init("wrench.and.screwdriver", L10n.metricTools, "\(r.tools ?? 0)"),
                    ])
                    if let duration = r.duration, duration > 0 {
                        items.append(.init("clock", L10n.t("s472"), Fmt.duration(duration * 1000)))
                    }
                    if let ctx = r.ctx, ctx > 0 {
                        items.append(.init("chart.bar.fill", L10n.t("s450"), String(format: "%.0f%%", ctx)))
                    }
                    if let ttft = r.ttft, ttft > 0 {
                        items.append(.init("timer", L10n.t("s552"), String(format: "%.1fs", Double(ttft) / 1000)))
                    }
                    if let response = r.response, response > 0 {
                        items.append(.init("speedometer", L10n.t("s192"), String(format: "%.1fs", Double(response) / 1000)))
                    }
                    if (r.errors ?? 0) > 0 {
                        items.append(.init("exclamationmark.triangle", L10n.t("s529"), "\(r.errors ?? 0)"))
                    }
                    if (r.cancellations ?? 0) > 0 {
                        items.append(.init("xmark.circle", L10n.t("s156"), "\(r.cancellations ?? 0)"))
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
                        ? L10n.t("s397")
                        : L10n.t("s396"))
                     : L10n.t("s341"))
                    .font(.system(size: Theme.fontSize(8.5)))
                    .foregroundStyle(Theme.tTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            } else if !compactExpired && quotaState != .unavailable {
                usageEmptyHint(recent: recentUsageHint { key in
                    let range = g.ranges.get(key)
                    return range.in + range.out + range.cr + range.reason
                })
            }

            if compactExpired {
                quotaStateNotice(
                    title: L10n.t("s539"),
                    detail: L10n.t("s025"),
                    source: grokQuotaSourceLabel(g.source),
                    updated: g.q_updated,
                    tint: Theme.grok,
                    warning: true
                )
            } else if let pct = g.pct, g.stale != true {
                if hasUsage { thinDivider }
                let title = (g.window == "month") ? L10n.t("s370") : L10n.t("s190")
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
                        Text("plan").font(.system(size: Theme.fontSize(11))).foregroundStyle(Theme.tTertiary)
                        Spacer()
                        Text(plan)
                            .font(.system(size: Theme.fontSize(10), weight: .semibold, design: .monospaced))
                            .foregroundStyle(Theme.tSecondary)
                            .padding(.horizontal, 7).padding(.vertical, 2)
                            .background(Capsule().fill(Theme.grok.opacity(0.16)))
                    }
                }
                grokQuotaStatus(g)
            } else if quotaState == .expired {
                if hasUsage { thinDivider }
                quotaStateNotice(
                    title: L10n.t("s539"),
                    detail: L10n.t("s255"),
                    source: grokQuotaSourceLabel(g.source),
                    updated: g.q_updated,
                    tint: Theme.grok,
                    warning: true
                )
            } else if hasUsage {
                thinDivider
                quotaStateNotice(
                    title: L10n.t("s353"),
                    detail: L10n.t("s443"),
                    source: grokQuotaSourceLabel(g.source),
                    updated: g.q_updated,
                    tint: Theme.grok
                )
            }
        }
    }

    func grokQuotaStatus(_ stat: GrokStat) -> some View {
        let sourceLabel = grokQuotaSourceLabel(stat.source)
        let updated = stat.q_updated.map { Fmt.reset($0) } ?? L10n.t("s364")
        return HStack(spacing: 5) {
            Image(systemName: "clock")
                .font(.system(size: Theme.fontSize(9)))
            Text(L10n.f("s548", sourceLabel, updated))
                .font(.system(size: Theme.fontSize(9.5), design: .monospaced))
            Spacer()
        }
        .foregroundStyle(Theme.tTertiary)
        .help(stat.source == "live"
              ? L10n.t("s238")
              : L10n.t("s556"))
    }

    private func grokQuotaSourceLabel(_ source: String?) -> String {
        switch source {
        case "live": return L10n.grokLive
        case "cache": return L10n.grokCache
        default: return L10n.grokLog
        }
    }

    /// 账单 product 字段 → 更可读的名称。
    static func grokProductLabel(_ raw: String) -> String {
        switch raw.lowercased() {
        case "grokbuild": return L10n.t("s024")
        case "api": return L10n.t("s251")
        case "grokchat": return L10n.t("s027")
        default: return raw
        }
    }

    /// 分产品占用说明（悬停 / 辅助读屏）。
    static func grokProductHelp(_ raw: String) -> String {
        switch raw.lowercased() {
        case "grokbuild":
            return L10n.t("s023")
        case "api":
            return L10n.t("s522")
        case "grokchat":
            return L10n.t("s076")
        default:
            return L10n.t("s484")
        }
    }

    /// 分产品占用：显示该产品在统一周额度里占了多少，不展示独立重置时间。
    func grokProductShareRow(name: String, usedPct: Double, tint: Color, help: String) -> some View {
        VStack(spacing: 4) {
            HStack {
                Text(name)
                    .font(.system(size: Theme.fontSize(11)))
                    .foregroundStyle(Theme.tSecondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.78)
                Spacer(minLength: 6)
                Text(String(format: L10n.t("s147"), usedPct))
                    .font(.system(size: Theme.fontSize(12), weight: .semibold, design: .monospaced))
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
            cardHeadPlain(L10n.t("s142"), tint: Theme.qwenwork)

            if quota.available || quota.remaining != nil || !quota.segments.isEmpty || quota.shared != nil {
                if quota.exceeded {
                    HStack(spacing: 6) {
                        Image(systemName: "exclamationmark.triangle.fill")
                        Text(L10n.t("s221"))
                    }
                    .font(.system(size: Theme.fontSize(10), weight: .semibold))
                    .foregroundStyle(Color.red.opacity(0.92))
                }

                if let remaining = quota.remaining {
                    CostHeadline(
                        value: Fmt.credits(remaining),
                        caption: quota.is_team ? L10n.t("s196") : L10n.t("s097"),
                        tint: Theme.qwenwork
                    )
                }

                // 有明确比例时才画进度条。部分千问办公套餐只返回绝对积分余额。
                if let remainingPct = quota.remaining_pct {
                    quotaRow(
                        title: L10n.t("s461"),
                        pct: max(0, min(100, remainingPct)),
                        reset: nil,
                        tint: Theme.qwenwork
                    )
                }

                if let expiresAt = quota.expires_at {
                    qwenWorkDateRow(L10n.t("s546"), epoch: expiresAt)
                }
                if let planExpiration = quota.plan_expiration,
                   planExpiration != quota.expires_at {
                    qwenWorkDateRow(L10n.t("s214"), epoch: planExpiration)
                }

                if !quota.segments.isEmpty {
                    thinDivider
                    Text(L10n.t("s098"))
                        .font(.system(size: Theme.fontSize(10), weight: .semibold))
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
                Text(L10n.t("s377"))
                    .font(.system(size: Theme.fontSize(10)))
                    .foregroundStyle(Theme.tTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                Text(L10n.t("s202"))
                    .font(.system(size: Theme.fontSize(10)))
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
                    .font(.system(size: Theme.fontSize(11)))
                    .foregroundStyle(Theme.tSecondary)
                    .lineLimit(1)
                Spacer(minLength: 6)
                if let remaining = segment.remaining {
                    Text(L10n.f("s133", Fmt.credits(remaining), Self.qwenWorkUnitLabel(segment.unit)))
                        .font(.system(size: Theme.fontSize(11), weight: .semibold, design: .monospaced))
                        .foregroundStyle(Theme.tPrimary)
                }
            }

            if let total = segment.total, total > 0 {
                let used = segment.used.map(Fmt.credits) ?? "?"
                Text(L10n.f("s242", used, Fmt.credits(total)))
                    .font(.system(size: Theme.fontSize(9), design: .monospaced))
                    .foregroundStyle(Theme.tTertiary)
            }

            if let remainingPct {
                HStack(spacing: 6) {
                    MiniBar(value: remainingPct, tint: remainingPct <= 15 ? .red : Theme.qwenwork)
                    Text(String(format: "%.0f%%", remainingPct))
                        .font(.system(size: Theme.fontSize(9.5), weight: .semibold, design: .monospaced))
                        .foregroundStyle(remainingPct <= 15 ? Color.red : Theme.tSecondary)
                }
            }

            if let renewsAt = segment.renews_at {
                qwenWorkDateRow(L10n.t("s460"), epoch: renewsAt)
            } else if let expiresAt = segment.expires_at {
                qwenWorkDateRow(L10n.t("s129"), epoch: expiresAt)
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
                Text(L10n.t("s195"))
                    .font(.system(size: Theme.fontSize(10), weight: .semibold))
                    .foregroundStyle(Theme.tSecondary)
                Spacer(minLength: 6)
                if let remaining = shared.remaining {
                    Text(L10n.f("s134", Fmt.credits(remaining), Self.qwenWorkUnitLabel(shared.unit)))
                        .font(.system(size: Theme.fontSize(11), weight: .semibold, design: .monospaced))
                        .foregroundStyle(Theme.tPrimary)
                }
            }
            Text(L10n.t("s120"))
                .font(.system(size: Theme.fontSize(8.5)))
                .foregroundStyle(Theme.tTertiary)
            if let total = shared.total, total > 0 {
                let used = shared.used.map(Fmt.credits) ?? "?"
                Text(L10n.f("s242", used, Fmt.credits(total)))
                    .font(.system(size: Theme.fontSize(9), design: .monospaced))
                    .foregroundStyle(Theme.tTertiary)
            }
            if let remainingPct {
                HStack(spacing: 6) {
                    MiniBar(value: remainingPct, tint: remainingPct <= 15 ? .red : Theme.qwenwork)
                    Text(String(format: "%.0f%%", remainingPct))
                        .font(.system(size: Theme.fontSize(9.5), weight: .semibold, design: .monospaced))
                        .foregroundStyle(remainingPct <= 15 ? Color.red : Theme.tSecondary)
                }
            }
            if let expiresAt = shared.expires_at {
                qwenWorkDateRow(L10n.t("s119"), epoch: expiresAt)
            }
        }
    }

    func qwenWorkDateRow(_ label: String, epoch: Int) -> some View {
        HStack(spacing: 5) {
            Image(systemName: "calendar")
                .font(.system(size: Theme.fontSize(8.5)))
            Text("\(label) · \(Fmt.reset(epoch))")
                .font(.system(size: Theme.fontSize(9.5), design: .monospaced))
            Spacer()
        }
        .foregroundStyle(Theme.tTertiary)
    }

    func qwenWorkQuotaStatus(_ quota: QwenWorkQuota) -> some View {
        let sourceLabel: String
        switch quota.source {
        case "mcp", "local_mcp": sourceLabel = L10n.t("s392")
        case "cache": sourceLabel = L10n.t("s387")
        default: sourceLabel = L10n.t("s540")
        }
        let updated = quota.updated.map { Fmt.reset($0) } ?? L10n.t("s364")
        return HStack(spacing: 5) {
            Image(systemName: quota.stale ? "exclamationmark.triangle.fill" : "clock")
                .font(.system(size: Theme.fontSize(9)))
            Text("\(quota.stale ? L10n.t("s464") : sourceLabel) · \(updated)")
                .font(.system(size: Theme.fontSize(9.5), design: .monospaced))
            Spacer()
        }
        .foregroundStyle(quota.stale ? Color.orange.opacity(0.88) : Theme.tTertiary)
        .help(L10n.t("s041"))
    }

    static func qwenWorkSegmentLabel(_ segment: QwenWorkQuotaSegment) -> String {
        let key = segment.id.isEmpty ? segment.kind : segment.id
        switch key.lowercased().replacingOccurrences(of: "-", with: "_") {
        case "plan", "plan_credits": return L10n.t("s215")
        case "addon", "add_on", "add_on_credits": return L10n.t("s136")
        case "shared_addon", "shared_add_on", "shared_add_on_credits": return L10n.t("s118")
        default: return key.isEmpty ? L10n.t("s449") : key
        }
    }

    static func qwenWorkUnitLabel(_ unit: String?) -> String {
        guard let unit, !unit.isEmpty else { return L10n.t("s449") }
        return ["credit", "credits"].contains(unit.lowercased()) ? L10n.t("s449") : unit
    }

    // MARK: - Qoder IDE 卡片
    @ViewBuilder
    func qoderIdeBlock(_ q: QoderIdeStat, _ r: QoderIdeRange) -> some View {
        VStack(alignment: .leading, spacing: 11) {
            cardHeadPlain("Qoder Desktop", tint: Theme.qoder, toolID: "qoder")
            let total = r.in + r.cached + r.out
            if r.calls > 0 || total > 0 {
                if total > 0 {
                    CostHeadline(value: Fmt.human(total), caption: L10n.f("s066", sel.label), tint: Theme.qoder)
                }
                metricGrid({
                    var items: [Metric] = [
                        .init("terminal", L10n.t("s413"), "\(r.calls)"),
                        .init("person.2", L10n.metricSessions, "\(r.sessions)"),
                    ]
                    if r.sub_agents > 0 {
                        items.append(.init("point.3.connected.trianglepath.dotted", L10n.t("s216"), "\(r.sub_agents)"))
                    }
                    if r.messages > 0 {
                        items.append(.init("bubble.left.and.bubble.right", L10n.t("s430"), Fmt.human(r.messages)))
                    }
                    if r.ctx > 0 {
                        items.append(.init("chart.bar.fill", L10n.t("s465"), String(format: "%.0f%%", r.ctx)))
                    }
                    if r.duration > 0 {
                        items.append(.init("clock", L10n.t("s472"), Fmt.duration(r.duration * 1000)))
                    }
                    if r.in > 0 {
                        items.append(.init("arrow.down", L10n.metricIn, Fmt.human(r.in)))
                    }
                    if r.out > 0 {
                        items.append(.init("arrow.up", L10n.metricOut, Fmt.human(r.out)))
                    }
                    if r.cached > 0 {
                        items.append(.init("bolt.fill", L10n.metricCacheRead, Fmt.human(r.cached)))
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
            if r.calls > 0 || r.totalTokens > 0 {
                if r.totalTokens > 0 {
                    CostHeadline(value: Fmt.human(r.totalTokens), caption: L10n.f("s066", sel.label), tint: Theme.qoderwork)
                }
                metricGrid({
                    var items: [Metric] = [
                        .init("terminal", L10n.t("s104"), "\(r.calls)"),
                        .init("person.2", L10n.metricSessions, "\(r.sessions)"),
                        .init("clock", L10n.t("s472"), Fmt.duration(r.duration)),
                    ]
                    if r.in > 0 { items.append(.init("arrow.down", L10n.metricIn, Fmt.human(r.in))) }
                    if r.out > 0 { items.append(.init("arrow.up", L10n.metricOut, Fmt.human(r.out))) }
                    if r.sub_agents > 0 {
                        items.append(.init("point.3.connected.trianglepath.dotted", L10n.t("s216"), "\(r.sub_agents)"))
                    }
                    if r.turns > 0 {
                        items.append(.init("bubble.left.and.bubble.right", L10n.t("s413"), Fmt.human(r.turns)))
                    }
                    if r.ctx > 0 {
                        items.append(.init("chart.bar.fill", L10n.t("s247"), String(format: "%.0f%%", r.ctx)))
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

    // MARK: - Qoder CLI 卡片
    @ViewBuilder
    func qodercliBlock(_ q: QoderStat, _ r: QoderRange) -> some View {
        VStack(alignment: .leading, spacing: 11) {
            cardHeadPlain("Qoder CLI", tint: Theme.qodercli, toolID: "qodercli")
            if r.calls > 0 || r.totalTokens > 0 {
                if r.usage_available && r.totalTokens > 0 {
                    CostHeadline(value: Fmt.human(r.totalTokens), caption: L10n.f("s066", sel.label), tint: Theme.qodercli)
                }
                metricGrid(r.credits > 0 ? [
                    .init("circle.hexagongrid.fill", "Credits", Fmt.credits(r.credits)),
                ] : [], hit: r.hit, extra: {
                    var items: [Metric] = [
                        .init("terminal", L10n.t("s413"), "\(r.calls)"),
                        .init("person.2", L10n.metricSessions, "\(r.sessions)"),
                        .init("bubble.left.and.bubble.right", L10n.t("s430"), Fmt.human(r.turns)),
                        .init("clock", L10n.t("s425"), Fmt.duration(r.duration)),
                    ]
                    if r.usage_available {
                        items.append(.init("arrow.down", L10n.metricIn, Fmt.human(r.in)))
                        items.append(.init("arrow.up", L10n.metricOut, Fmt.human(r.out)))
                        if r.cr > 0 { items.append(.init("bolt.fill", L10n.metricCacheRead, Fmt.human(r.cr))) }
                        if r.cw > 0 { items.append(.init("square.stack.3d.up.fill", L10n.metricCacheWrite, Fmt.human(r.cw))) }
                    }
                    if r.tools > 0 {
                        items.append(.init("wrench.and.screwdriver", L10n.t("s231"), Fmt.human(r.tools)))
                    }
                    if r.sub_agents > 0 {
                        items.append(.init("point.3.connected.trianglepath.dotted", L10n.t("s216"), "\(r.sub_agents)"))
                    }
                    return items
                }(), tint: Theme.qodercli)
                if !r.models.isEmpty {
                    tokenModelDisclosure(r.models, open: $qoderCliModelsOpen, tint: Theme.qodercli)
                } else if let model = q.model, !model.isEmpty {
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
                CostHeadline(value: Fmt.human(r.in + r.out + r.cr + r.cw + r.reason), caption: L10n.f("s066", sel.label), tint: Theme.hermes)
                metricGrid([.init("dollarsign.circle", L10n.metricCost, String(format: "$%.2f", r.cost))],
                    hit: r.hit, extra: {
                    var items: [Metric] = [
                        .init("arrow.down", L10n.metricIn, Fmt.human(r.in)),
                        .init("arrow.up", L10n.metricOut, Fmt.human(r.out)),
                        .init("bolt.fill", L10n.metricCacheRead, Fmt.human(r.cr)),
                    ]
                    if r.reason > 0 { items.append(.init("brain", L10n.metricReason, Fmt.human(r.reason))) }
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
                CostHeadline(value: Fmt.human(r.in + r.out + r.cr + r.cw), caption: L10n.f("s066", sel.label), tint: Theme.openclaw)
                metricGrid([.init("dollarsign.circle", L10n.metricCost, String(format: "$%.2f", r.cost))],
                    hit: r.hit, extra: {
                    var items: [Metric] = [
                        .init("arrow.down", L10n.metricIn, Fmt.human(r.in)),
                        .init("arrow.up", L10n.metricOut, Fmt.human(r.out)),
                        .init("bolt.fill", L10n.metricCacheRead, Fmt.human(r.cr)),
                    ]
                    if r.reason > 0 { items.append(.init("brain", L10n.metricReason, Fmt.human(r.reason))) }
                    if r.tasks > 0 { items.append(.init("checklist", L10n.t("s104"), "\(r.tasks)")) }
                    return items
                }(), tint: Theme.openclaw)
                if !r.models.isEmpty {
                    tokenModelDisclosure(r.models, open: modelsOpen, tint: Theme.openclaw,
                                         reasonIncludedInOutput: true)
                }
            } else if r.tasks > 0 {
                HStack(spacing: 16) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(L10n.t("s104")).font(.system(size: Theme.fontSize(10))).foregroundStyle(Theme.tTertiary)
                        Text("\(r.tasks)")
                            .font(.system(size: Theme.fontSize(16), weight: .bold, design: .rounded))
                            .foregroundStyle(Theme.tPrimary)
                    }
                    if r.completed > 0 {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(L10n.t("s218")).font(.system(size: Theme.fontSize(10))).foregroundStyle(Theme.tTertiary)
                            Text("\(r.completed)")
                                .font(.system(size: Theme.fontSize(16), weight: .bold, design: .rounded))
                                .foregroundStyle(.green)
                        }
                    }
                    if r.failed > 0 {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(L10n.t("s213")).font(.system(size: Theme.fontSize(10))).foregroundStyle(Theme.tTertiary)
                            Text("\(r.failed)")
                                .font(.system(size: Theme.fontSize(16), weight: .bold, design: .rounded))
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
                         showsCost: Bool = true, showsCredits: Bool = false,
                         reasonIncludedInOutput: Bool = false,
                         toolID: String? = nil) -> some View {
        VStack(alignment: .leading, spacing: 11) {
            cardHead(title, tint: tint, sessions: r.sessions, toolID: toolID)
            if r.sessions > 0 {
                let total = r.in + r.out + r.cr + r.cw + (reasonIncludedInOutput ? 0 : r.reason)
                CostHeadline(value: Fmt.human(total), caption: L10n.f("s066", sel.label), tint: tint)
                let creditMetrics: [Metric] = showsCredits && r.credits > 0
                    ? [.init("circle.hexagongrid.fill", "Credits", Fmt.credits(r.credits))]
                    : []
                metricGrid(showsCost ? [.init("dollarsign.circle", L10n.metricCost, nativeMoney(r.cost, r.cost_cny))] : [],
                    hit: r.hit, extra: creditMetrics + tokenUsageMetrics(r, inclusiveIO: inclusiveIO), tint: tint)
                if !r.models.isEmpty {
                    tokenModelDisclosure(r.models, open: modelsOpen, tint: tint,
                                         reasonIncludedInOutput: reasonIncludedInOutput,
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
                .init("arrow.down", L10n.metricIn, Fmt.human(r.in + r.cr + r.cw)),
                .init("arrow.up", L10n.metricOut, Fmt.human(r.out + r.reason)),
            ]
            if r.cr > 0 { items.append(.init("bolt.fill", L10n.t("s125"), Fmt.human(r.cr))) }
            if r.reason > 0 { items.append(.init("brain", L10n.t("s123"), Fmt.human(r.reason))) }
            if r.cw > 0 { items.append(.init("square.stack.3d.up.fill", L10n.t("s124"), Fmt.human(r.cw))) }
            return items
        }
        var items: [Metric] = [
            .init("arrow.down", L10n.metricIn, Fmt.human(r.in)),
            .init("arrow.up", L10n.metricOut, Fmt.human(r.out)),
            .init("bolt.fill", L10n.metricCacheRead, Fmt.human(r.cr)),
            .init("square.stack.3d.up.fill", L10n.metricCacheWrite, Fmt.human(r.cw)),
        ]
        if r.reason > 0 { items.append(.init("brain", L10n.metricReason, Fmt.human(r.reason))) }
        return items
    }

    @ViewBuilder
    private func inactiveToolsLine(_ cards: [ToolCardItem]) -> some View {
        let inactive = cards.filter { $0.visible && !$0.active }.map(\.name)
        if !inactive.isEmpty {
            Text(L10n.t("s375") + inactive.joined(separator: " · "))
                .font(.system(size: Theme.fontSize(9)))
                .foregroundStyle(Theme.tTertiary)
                .frame(maxWidth: .infinity)
        }
    }

    var emptyHint: some View {
        Text(L10n.t("s351"))
            .font(.system(size: Theme.fontSize(10)))
            .foregroundStyle(Theme.tTertiary)
    }

    /// 空态措辞见 `UsageEmptyState`：刷新中 / 真的没有，两者必须能分辨。
    func usageEmptyHint(recent: String? = nil) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            if store.isRefreshing {
                Text(L10n.f("s415", sel.label))
            } else {
                Text(L10n.f("s069", sel.label))
                if let recent = recent {
                    Text(L10n.f("s368", recent))
                }
            }
        }
        .font(.system(size: Theme.fontSize(10)))
        .foregroundStyle(Theme.tTertiary)
    }

    func recentUsageHint(_ tokens: (RangeKey) -> Int) -> String? {
        guard case .empty(let recent) = UsageEmptyState.resolve(
            selected: sel, refreshing: false, tokens: tokens
        ) else { return nil }
        return recent
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
        let updatedLabel = updated.map { L10n.f("s093", Fmt.reset($0)) } ?? L10n.t("s226")
        return VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Image(systemName: warning ? "exclamationmark.triangle.fill" : "info.circle.fill")
                    .font(.system(size: Theme.fontSize(10), weight: .semibold))
                Text(title)
                    .font(.system(size: Theme.fontSize(11), weight: .semibold))
                Spacer(minLength: 4)
            }
            .foregroundStyle(statusTint.opacity(0.95))

            Text(detail)
                .font(.system(size: Theme.fontSize(9.5)))
                .foregroundStyle(Theme.tSecondary)
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: 5) {
                Image(systemName: "clock")
                    .font(.system(size: Theme.fontSize(8.5)))
                Text("\(source) · \(updatedLabel)")
                    .font(.system(size: Theme.fontSize(9), design: .monospaced))
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
            Text("model").font(.system(size: Theme.fontSize(11))).foregroundStyle(Theme.tTertiary)
            Spacer()
            Text(model)
                .font(.system(size: Theme.fontSize(10), weight: .semibold, design: .monospaced))
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
            Text(title).font(.system(size: Theme.fontSize(14), weight: .bold))
            if sessions > 0 {
                Text("\(sessions)")
                    .font(.system(size: Theme.fontSize(10), weight: .bold, design: .rounded))
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
            Text(title).font(.system(size: Theme.fontSize(14), weight: .bold))
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
                .font(.system(size: Theme.fontSize(10), weight: .semibold))
                .foregroundStyle(done ? tint : Theme.tTertiary)
                .frame(width: 22, height: 22)
                .background(Circle().fill(Color.primary.opacity(done ? 0.10 : 0.06)))
                .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .tip(done ? L10n.t("s237") : L10n.t("s205"))
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
                .font(.system(size: Theme.fontSize(9))).foregroundStyle(Theme.tTertiary)
            Text(L10n.f("s379", name)).font(.system(size: Theme.fontSize(10))).foregroundStyle(Theme.tTertiary)
            Spacer()
            Text(Fmt.human(total))
                .font(.system(size: Theme.fontSize(10), weight: .medium, design: .monospaced))
                .foregroundStyle(Theme.tSecondary)
        }
    }

    var disclaimer: some View {
        Text(mode == .settings ? "Made by lank" : L10n.t("s263"))
            .font(.system(size: Theme.fontSize(9)))
            .foregroundStyle(Theme.tTertiary)
    }

    @ViewBuilder
    func tokenModelDisclosure(_ models: [TokenModelStat], open: Binding<Bool>, tint: Color,
                              reasonIncludedInOutput: Bool = false,
                              inclusiveIO: Bool = false,
                              periodLabel: String? = nil) -> some View {
        Button {
            open.wrappedValue.toggle()
        } label: {
            HStack(spacing: 5) {
                Image(systemName: "chart.pie.fill")
                    .font(.system(size: Theme.fontSize(9))).foregroundStyle(tint)
                Text(L10n.f("s273", models.count))
                    .font(.system(size: Theme.fontSize(11), weight: .medium))
                    .foregroundStyle(Theme.tSecondary)
                Image(systemName: open.wrappedValue ? "chevron.down" : "chevron.right")
                    .font(.system(size: Theme.fontSize(8), weight: .bold))
                    .foregroundStyle(Theme.tTertiary)
                Spacer()
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        if open.wrappedValue {
            VStack(alignment: .leading, spacing: 6) {
                Text(L10n.f("s274", periodLabel ?? sel.label))
                    .font(.system(size: Theme.fontSize(11), weight: .semibold))
                    .foregroundStyle(Theme.tSecondary)
                ForEach(models) { m in
                    let total = tokenModelTotal(m, reasonIncludedInOutput: reasonIncludedInOutput)
                    let hit = tokenModelHit(m)
                    let hasBreakdown = m.in + m.out + m.cr + m.cw + m.reason > 0
                        || m.cost > 0 || m.credits > 0 || m.pin > 0 || m.pout > 0
                    let isExpanded = expandedModels.contains(m.id)
                    VStack(alignment: .leading, spacing: 0) {
                        Button {
                            guard hasBreakdown else { return }
                            withAnimation(.easeInOut(duration: 0.2)) {
                                if isExpanded { expandedModels.remove(m.id) }
                                else { expandedModels.insert(m.id) }
                            }
                        } label: {
                            HStack(alignment: .top, spacing: 7) {
                                if hasBreakdown {
                                    Image(systemName: isExpanded ? "chevron.down" : "chevron.right")
                                        .font(.system(size: Theme.fontSize(7), weight: .bold))
                                        .foregroundStyle(Theme.tTertiary)
                                        .frame(width: 8, height: 16)
                                } else {
                                    Color.clear.frame(width: 8, height: 16)
                                }
                                Circle().fill(tint.opacity(0.7)).frame(width: 5, height: 5)
                                    .padding(.top, 5)
                                Text(m.name).font(.system(size: Theme.fontSize(11.5))).foregroundStyle(Theme.tPrimary)
                                    .lineLimit(2)
                                    .fixedSize(horizontal: false, vertical: true)
                                    .layoutPriority(1)
                                Spacer(minLength: 6)
                                HStack(spacing: 6) {
                                    Text(Fmt.human(total))
                                        .font(.system(size: Theme.fontSize(9.5), design: .monospaced))
                                        .foregroundStyle(Theme.tTertiary)
                                    if hit > 0 {
                                        Text(String(format: "%.0f%%", hit))
                                            .font(.system(size: Theme.fontSize(9.5), design: .monospaced))
                                            .foregroundStyle(Theme.tTertiary)
                                            .padding(.horizontal, 4).padding(.vertical, 1)
                                            .background(Capsule().fill(Color.primary.opacity(0.06)))
                                    }
                                    if m.cost > 0 || (m.cost_cny ?? 0) > 0 {
                                        Text(nativeMoney(m.cost, m.cost_cny))
                                            .font(.system(size: Theme.fontSize(11.5), weight: .semibold, design: .monospaced))
                                            .foregroundStyle(Theme.tPrimary)
                                    }
                                    if m.credits > 0 {
                                        Text("\(Fmt.credits(m.credits)) C")
                                            .font(.system(size: Theme.fontSize(11.5), weight: .semibold, design: .monospaced))
                                            .foregroundStyle(Theme.tPrimary)
                                    }
                                }
                                .fixedSize(horizontal: true, vertical: false)
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
                    .font(.system(size: Theme.fontSize(9))).foregroundStyle(tint)
                Text(L10n.f("s273", models.count))
                    .font(.system(size: Theme.fontSize(11), weight: .medium))
                    .foregroundStyle(Theme.tSecondary)
                Image(systemName: open.wrappedValue ? "chevron.down" : "chevron.right")
                    .font(.system(size: Theme.fontSize(8), weight: .bold))
                    .foregroundStyle(Theme.tTertiary)
                Spacer()
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        if open.wrappedValue {
            VStack(alignment: .leading, spacing: 6) {
                Text(L10n.f("s274", periodLabel ?? sel.label))
                    .font(.system(size: Theme.fontSize(11), weight: .semibold))
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
                            HStack(alignment: .top, spacing: 7) {
                                Image(systemName: isExpanded ? "chevron.down" : "chevron.right")
                                    .font(.system(size: Theme.fontSize(7), weight: .bold))
                                    .foregroundStyle(Theme.tTertiary)
                                    .frame(width: 8, height: 16)
                                Circle().fill(tint.opacity(0.7)).frame(width: 5, height: 5)
                                    .padding(.top, 5)
                                Text(m.name).font(.system(size: Theme.fontSize(11.5))).foregroundStyle(Theme.tPrimary)
                                    .lineLimit(2)
                                    .fixedSize(horizontal: false, vertical: true)
                                    .layoutPriority(1)
                                Spacer(minLength: 6)
                                HStack(spacing: 6) {
                                    if m.total > 0 {
                                        Text(Fmt.human(m.total))
                                            .font(.system(size: Theme.fontSize(9.5), design: .monospaced))
                                            .foregroundStyle(Theme.tTertiary)
                                    }
                                    if m.hit > 0 {
                                        Text(String(format: "%.0f%%", m.hit))
                                            .font(.system(size: Theme.fontSize(9.5), design: .monospaced))
                                            .foregroundStyle(Theme.tTertiary)
                                            .padding(.horizontal, 4).padding(.vertical, 1)
                                            .background(Capsule().fill(Color.primary.opacity(0.06)))
                                    }
                                    Text(String(format: "$%.2f", m.cost))
                                        .font(.system(size: Theme.fontSize(11.5), weight: .semibold, design: .monospaced))
                                        .foregroundStyle(Theme.tPrimary)
                                }
                                .fixedSize(horizontal: true, vertical: false)
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
                detailTag("↓ \(Fmt.human(tokIn))", label: L10n.metricIn, tagFont: tagFont, labelFont: labelFont, bg: bg, border: border)
                detailTag("↑ \(Fmt.human(tokOut))", label: L10n.metricOut, tagFont: tagFont, labelFont: labelFont, bg: bg, border: border)
                if tokCR > 0 {
                    detailTag("⚡ \(Fmt.human(tokCR))", label: componentsAreSubtotals ? L10n.t("s125") : L10n.metricCacheRead,
                              tagFont: tagFont, labelFont: labelFont, bg: bg, border: border)
                }
                if tokCW > 0 {
                    detailTag("✎ \(Fmt.human(tokCW))", label: componentsAreSubtotals ? L10n.t("s124") : L10n.metricCacheWrite,
                              tagFont: tagFont, labelFont: labelFont, bg: bg, border: border)
                }
                if tokReason > 0 {
                    detailTag("◉ \(Fmt.human(tokReason))", label: componentsAreSubtotals ? L10n.t("s123") : L10n.metricReason,
                              tagFont: tagFont, labelFont: labelFont, bg: bg, border: border)
                }
                if hit > 0 {
                    HStack(spacing: 2) {
                        Text(L10n.t("s191")).font(labelFont).foregroundStyle(Theme.tTertiary)
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
                Text(title).font(.system(size: Theme.fontSize(11))).foregroundStyle(Theme.tSecondary)
                if let d = detail {
                    Text(d)
                        .font(.system(size: Theme.fontSize(10), design: .monospaced))
                        .foregroundStyle(Theme.tTertiary)
                }
                Spacer()
                Text(SubscriptionQuotaPresentation.remainingLabel(pct))
                    .font(.system(size: Theme.fontSize(12), weight: .semibold, design: .monospaced))
                    .foregroundStyle(pct <= 15 ? AnyShapeStyle(.red) : AnyShapeStyle(Theme.tPrimary))
                // 无重置时间时不显示「· ?」，避免分产品行误导。
                if reset != nil {
                    Text("· \(Fmt.reset(reset))")
                        .font(.system(size: Theme.fontSize(9.5), design: .monospaced))
                        .foregroundStyle(Theme.tTertiary)
                }
            }
            MiniBar(value: pct, tint: pct <= 15 ? .red : tint)
        }
        .help(reset != nil ? L10n.f("s047", Fmt.countdown(reset)) : "")
    }

    func claudeQuotaStatus(_ stat: ClaudeStat) -> some View {
        let staleCount = [stat.q5_stale, stat.q7_stale, stat.qf_stale].filter { $0 == true }.count
        let hasFreshQuota = (stat.q5 != nil && stat.q5_stale != true) ||
            (stat.q7 != nil && stat.q7_stale != true) ||
            (stat.qf != nil && stat.qf_stale != true)
        let stale = staleCount > 0
        let label: String
        if stale {
            label = hasFreshQuota ? L10n.t("s523") : L10n.t("s541")
        } else {
            label = L10n.t("s544")
        }
        let updated = stat.q_updated.map { Fmt.reset($0) } ?? L10n.t("s364")
        return HStack(spacing: 5) {
            Image(systemName: stale ? "exclamationmark.triangle.fill" : "clock")
                .font(.system(size: Theme.fontSize(9)))
            Text("\(label) · \(updated)")
                .font(.system(size: Theme.fontSize(9.5), design: .monospaced))
            Spacer()
        }
        .foregroundStyle(stale ? Color.orange.opacity(0.88) : Theme.tTertiary)
        .help(stale ? L10n.t("s451") : L10n.t("s395"))
    }

    func codexQuotaStatus(_ stat: CodexStat) -> some View {
        let updated = stat.q_updated.map { Fmt.reset($0) } ?? L10n.t("s364")
        return HStack(spacing: 5) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: Theme.fontSize(9)))
            Text(L10n.f("s542", updated))
                .font(.system(size: Theme.fontSize(9.5), design: .monospaced))
            Spacer()
        }
        .foregroundStyle(Color.orange.opacity(0.88))
        .help(L10n.t("s453"))
    }

    var footer: some View {
        HStack(spacing: 4) {
            disclaimer
            Spacer()
            KeepAwakeMenu(ka: store.keepAwake)
            IconButton(
                icon: copyFeedback ? "checkmark" : "photo.on.rectangle",
                label: copyFeedback ? L10n.t("s236") : L10n.t("s204")
            ) {
                copyUsageImage()
            }
            IconButton(icon: "arrow.clockwise", label: L10n.t("s131")) { store.refresh() }
            IconButton(icon: "power", label: L10n.t("s519")) { NSApp.terminate(nil) }
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
                        .font(.system(size: Theme.fontSize(10), weight: .bold))
                        .foregroundStyle(.white)
                }
            }
            .buttonStyle(.plain)
            .tip(L10n.f("s144", tag))
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
                    .font(.system(size: Theme.fontSize(7), weight: .bold, design: .monospaced))
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
                    .font(.system(size: Theme.fontSize(9), weight: .bold))
                    .foregroundStyle(Theme.claude)
            }
        case .failed:
            Button { updater.checkForUpdate() } label: {
                Image(systemName: "exclamationmark.circle")
                    .font(.system(size: Theme.fontSize(11), weight: .medium))
                    .foregroundStyle(.red)
                    .frame(width: 26, height: 26)
            }
            .buttonStyle(.plain)
            .tip(L10n.t("s528"))
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
    @State private var grokBotAuthorizing = false
    @State private var grokBotAuthorizationResult = ""
    @State private var zedAuthorizing = false
    @State private var zedAuthorizationResult = ""
    @AppStorage("syncDir") private var syncDir = ""
    @AppStorage("deviceName") private var deviceName = ""
    @State private var configuredDeviceID: String?
    @AppStorage("autoSync") private var autoSync = false
    @AppStorage("syncInterval") private var syncInterval = SyncManager.defaultSyncInterval
    @AppStorage("sitReminderOn") private var sitReminderOn = false
    @AppStorage("sitReminderInterval") private var sitReminderInterval = 90
    @AppStorage(MenuBarStyle.defaultsKey) private var menuBarStyle = MenuBarStyle.system.rawValue
    @AppStorage(MenuBarDensity.defaultsKey) private var menuBarDensity = MenuBarDensity.full.rawValue
    @AppStorage(PanelFontSize.defaultsKey) private var panelFontSize = PanelFontSize.small.rawValue

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
                    settingsAppearanceSection
                    settingsMenuBarSection
                    settingsUpdateSection
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
        case .kimi5h: return $menuBarQuotaKimi5h
        case .kimiSubscription: return $menuBarQuotaKimiSubscription
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
        if selected.isEmpty { return L10n.t("s113") }
        let shown = selected.prefix(2).map(\.label).joined(separator: " · ")
        if selected.count > 2 {
            let hidden = selected.dropFirst(2).map(\.label).joined(separator: "、")
            return L10n.f("s151", shown, hidden)
        }
        return L10n.f("s150", shown)
    }

    var settingsAppearanceSection: some View {
        settingsSection("textformat.size", L10n.t("appearance")) {
            settingsStackedValue(L10n.t("font_size")) {
                Picker(L10n.t("font_size"), selection: $panelFontSize) {
                    ForEach(PanelFontSize.allCases) { size in
                        Text(size.label).tag(size.rawValue)
                    }
                }
                .labelsHidden()
                .pickerStyle(.segmented)
                .controlSize(.mini)
                .frame(width: settingsMenuPickerWidth)
            }
            settingsStackedValue(L10n.language) {
                Picker(L10n.language, selection: $appLanguageRaw) {
                    ForEach(AppLanguage.allCases) { lang in
                        Text(lang.label).tag(lang.rawValue)
                    }
                }
                .labelsHidden()
                .pickerStyle(.menu)
                .controlSize(.mini)
                .frame(width: settingsMenuPickerWidth)
                .onChange(of: appLanguageRaw) { _ in syncCollectorLanguage() }
            }
        }
    }

    /// 设置变更同步 collector 语言（~/.tokei/config.json 的 language）。
    private func syncCollectorLanguage() {
        let code = (AppLanguage(rawValue: appLanguageRaw) ?? .system).collectorCode
        let url = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".tokei/config.json")
        var cfg: [String: Any] = [:]
        if let data = try? Data(contentsOf: url),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            cfg = obj
        }
        if (cfg["language"] as? String) != code {
            cfg["language"] = code
            if let data = try? JSONSerialization.data(withJSONObject: cfg) {
                try? data.write(to: url, options: .atomic)
            }
        }
    }

    var settingsMenuBarSection: some View {
        settingsSection("menubar.rectangle", L10n.t("s475")) {
            settingsStackedValue(L10n.t("s402")) {
                Picker(L10n.t("s477"), selection: $menuBarStyle) {
                    ForEach(MenuBarStyle.allCases) { style in
                        Text(style.label).tag(style.rawValue)
                    }
                }
                .labelsHidden()
                .pickerStyle(.segmented)
                .controlSize(.mini)
                .font(.system(size: Theme.fontSize(9), weight: .medium))
                .frame(width: settingsMenuPickerWidth)
            }

            settingsStackedValue(L10n.t("s111")) {
                Picker(L10n.t("s476"), selection: $menuBarDensity) {
                    ForEach(MenuBarDensity.allCases) { density in
                        Text(density.label).tag(density.rawValue)
                    }
                }
                .labelsHidden()
                .pickerStyle(.segmented)
                .controlSize(.mini)
                .frame(width: settingsMenuPickerWidth)
            }

            settingsStackedValue(L10n.t("s547")) {
                LazyVGrid(columns: [GridItem(.flexible(), spacing: 7),
                                    GridItem(.flexible(), spacing: 7)], spacing: 7) {
                    ForEach(MenuBarQuotaSource.allCases) { source in
                        settingsRow(source.label, tint: source.themeColor,
                                    isOn: menuBarQuotaBinding(source))
                    }
                }
            }

            Text(menuBarQuotaHint)
                .font(.system(size: Theme.fontSize(9), weight: .medium))
                .foregroundStyle(Theme.tSecondary)
                .fixedSize(horizontal: false, vertical: true)

            Text(L10n.t("s160"))
                .font(.system(size: Theme.fontSize(8.5)))
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

    var settingsUpdateSection: some View {
        settingsSection("arrow.triangle.2.circlepath", L10n.t("s436")) {
            HStack(spacing: 8) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(L10n.f("s254", Updater.releaseTag))
                        .font(.system(size: Theme.fontSize(10), weight: .medium))
                        .foregroundStyle(Theme.tPrimary)
                    Text(Updater.isLocalBuild ? L10n.t("s390") : L10n.t("s186"))
                        .font(.system(size: Theme.fontSize(8.5)))
                        .foregroundStyle(Theme.tTertiary)
                }
                Spacer()
                if Updater.isLocalBuild {
                    Text(L10n.t("s389"))
                        .font(.system(size: Theme.fontSize(9), weight: .medium))
                        .foregroundStyle(Theme.tTertiary)
                } else {
                    switch updater.state {
                    case .idle:
                        settingsActionButton(icon: "arrow.triangle.2.circlepath", title: L10n.t("s404")) {
                            updater.checkForUpdate()
                        }
                    case .checking:
                        HStack(spacing: 5) {
                            ProgressView().controlSize(.small)
                            Text(L10n.t("s419"))
                        }
                        .font(.system(size: Theme.fontSize(9), weight: .medium))
                        .foregroundStyle(Theme.tTertiary)
                    case .upToDate:
                        Label(L10n.t("s239"), systemImage: "checkmark.circle.fill")
                            .font(.system(size: Theme.fontSize(9), weight: .medium))
                            .foregroundStyle(.green)
                    case .available(let tag, _, _):
                        settingsActionButton(icon: "arrow.down.circle.fill", title: L10n.f("s145", tag)) {
                            updater.performUpdate()
                        }
                    case .downloading(let progress):
                        Text(L10n.f("s094", Int(progress * 100)))
                            .font(.system(size: Theme.fontSize(9), weight: .medium, design: .monospaced))
                            .foregroundStyle(Theme.tSecondary)
                    case .installing:
                        HStack(spacing: 5) {
                            ProgressView().controlSize(.small)
                            Text(L10n.t("s417"))
                        }
                        .font(.system(size: Theme.fontSize(9), weight: .medium))
                        .foregroundStyle(Theme.tSecondary)
                    case .failed(let message):
                        VStack(alignment: .trailing, spacing: 3) {
                            settingsActionButton(icon: "arrow.clockwise", title: L10n.t("s528")) {
                                updater.checkForUpdate()
                            }
                            Text(message)
                                .font(.system(size: Theme.fontSize(8)))
                                .foregroundStyle(.red.opacity(0.85))
                                .lineLimit(2)
                        }
                    }
                }
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .background(RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(Color.primary.opacity(0.04)))
        }
    }

    var settingsSystemSection: some View {
        settingsSection("gearshape.2", L10n.t("s456")) {
            settingsToggleRow(
                L10n.t("s446"),
                isOn: Binding(
                    get: { loginItem.enabled },
                    set: { loginItem.setEnabled($0) }
                )
            )

            if loginItem.requiresApproval {
                HStack(spacing: 7) {
                    Text(L10n.t("s534"))
                        .font(.system(size: Theme.fontSize(8.5)))
                        .foregroundStyle(Theme.tTertiary)
                    Spacer()
                    settingsActionButton(icon: "gear", title: L10n.t("s267")) {
                        loginItem.openSystemSettings()
                    }
                }
            } else if let error = loginItem.errorMessage {
                Text(error)
                    .font(.system(size: Theme.fontSize(8.5)))
                    .foregroundStyle(.red.opacity(0.85))
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    var settingsAgentsSection: some View {
        settingsSection("square.grid.2x2", L10n.t("s349")) {
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
                settingsRow("Grok Bot", tint: Theme.grokBot, isOn: $showGrokBot)
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
                settingsRow("WorkBuddy Intl.", tint: Theme.workbuddyAI, isOn: $showWorkBuddyAI)
                settingsRow("CodeBuddy", tint: Theme.codebuddy, isOn: $showCodeBuddy)
                settingsRow("DeepSeek Harness", tint: Theme.deepseekHarness, isOn: $showDeepSeekHarness)
                settingsRow("OpenCode", tint: Theme.opencode, isOn: $showOpenCode)
                settingsRow("Qwen Code", tint: Theme.qwencode, isOn: $showQwenCode)
                settingsRow(L10n.t("s142"), tint: Theme.qwenwork, isOn: $showQwenWork)
                settingsRow("Kimi Code", tint: Theme.kimicode, isOn: $showKimiCode)
                settingsRow("Muse Code", tint: Theme.musecode, isOn: $showMuseCode)
                settingsRow("Command Code", tint: Theme.cmdcode, isOn: $showCmdCode)
                settingsRow("Devin", tint: Theme.devin, isOn: $showDevin)
            }
        }
        .onChange(of: showQoder) { enabled in
            Self.setQoderIdeEnabled(enabled)
        }
        .onChange(of: showGemini) { enabled in
            Self.setProviderQuotaEnabled("antigravity", enabled)
            store.refresh()
        }
        .onChange(of: showDevin) { enabled in
            Self.setProviderQuotaEnabled("devin", enabled)
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
        settingsSection("key.horizontal.fill", L10n.t("s033")) {
            Text(L10n.t("s020"))
                .font(.system(size: Theme.fontSize(8.5)))
                .foregroundStyle(Theme.tTertiary)
                .fixedSize(horizontal: false, vertical: true)

            if showZed {
                HStack(spacing: 8) {
                    settingsActionButton(
                        icon: "key.fill",
                        title: zedAuthorizing ? L10n.t("s455") : L10n.t("s276")
                    ) {
                        authorizeZedQuota()
                    }
                    .disabled(zedAuthorizing)
                    if zedAuthorizing { ProgressView().controlSize(.mini) }
                    if !zedAuthorizationResult.isEmpty {
                        Text(zedAuthorizationResult)
                            .font(.system(size: Theme.fontSize(8.5)))
                            .foregroundStyle(Theme.tTertiary)
                            .lineLimit(2)
                    }
                }
            }

            thinDivider

            Text("Sub2API")
                .font(.system(size: Theme.fontSize(10), weight: .semibold))
                .foregroundStyle(Theme.sub2api)
            providerSettingsField(
                label: "Base URL",
                placeholder: "https://api.example.com",
                text: $sub2APIBaseURL
            )
            providerSettingsField(
                label: "API Key",
                placeholder: sub2APIKeyStored ? L10n.t("s234") : "Group API Key",
                text: $sub2APIKey,
                secure: true
            )
            if sub2APIKeyStored {
                HStack {
                    Spacer()
                    settingsActionButton(icon: "trash", title: L10n.t("s432")) {
                        clearProviderToken(.sub2api)
                    }
                }
            }

            thinDivider

            Text("z.ai / GLM")
                .font(.system(size: Theme.fontSize(10), weight: .semibold))
                .foregroundStyle(Theme.zai)
            HStack(spacing: 8) {
                Text(L10n.t("s141"))
                    .font(.system(size: Theme.fontSize(9.5)))
                    .foregroundStyle(Theme.tTertiary)
                    .frame(width: 52, alignment: .leading)
                Picker(L10n.t("s090"), selection: $zaiRegion) {
                    Text("Global").tag("global")
                    Text("BigModel CN").tag("bigmodel-cn")
                }
                .labelsHidden()
                .pickerStyle(.segmented)
                .controlSize(.mini)
            }
            providerSettingsField(
                label: "API Key",
                placeholder: zaiKeyStored ? L10n.t("s234") : "Z_AI_API_KEY",
                text: $zaiKey,
                secure: true
            )
            if zaiKeyStored {
                HStack {
                    Spacer()
                    settingsActionButton(icon: "trash", title: L10n.t("s433")) {
                        clearProviderToken(.zai)
                    }
                }
            }

            HStack {
                settingsActionButton(icon: "checkmark.circle", title: L10n.t("s107")) {
                    saveProviderSettings()
                }
                Spacer()
                if !providerSettingsResult.isEmpty {
                    Text(providerSettingsResult)
                        .font(.system(size: Theme.fontSize(8.5)))
                        .foregroundStyle(providerSettingsResult == L10n.t("s233") ? Color.green : Color.orange)
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
                .font(.system(size: Theme.fontSize(9.5)))
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
            .font(.system(size: Theme.fontSize(9.5), design: .monospaced))
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
            providerSettingsResult = L10n.t("s036")
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
            providerSettingsResult = L10n.t("s108")
            return
        }
        sub2APIKey = ""
        zaiKey = ""
        loadProviderSettings()
        providerSettingsResult = L10n.t("s233")
        store.refresh()
    }

    private func clearProviderToken(_ provider: ProviderSecret) {
        guard ProviderCredentialStore.setToken("", for: provider) else {
            providerSettingsResult = L10n.t("s434")
            return
        }
        loadProviderSettings()
        providerSettingsResult = L10n.t("s240")
        store.refresh()
    }

    private func authorizeZedQuota() {
        guard !zedAuthorizing, let executable = Bundle.main.executableURL else { return }
        zedAuthorizing = true
        zedAuthorizationResult = ""
        DispatchQueue.global(qos: .userInitiated).async {
            func run(_ argument: String) -> Bool {
                let process = Process()
                process.executableURL = executable
                process.arguments = [argument]
                process.standardInput = FileHandle.nullDevice
                process.standardOutput = FileHandle.nullDevice
                process.standardError = FileHandle.nullDevice
                do {
                    try process.run()
                    process.waitUntilExit()
                    return process.terminationStatus == 0
                } catch {
                    return false
                }
            }
            let interactiveSucceeded = run("--zed-authorize")
            let persistentSucceeded = interactiveSucceeded && run("--zed-verify")
            DispatchQueue.main.async {
                zedAuthorizing = false
                if persistentSucceeded {
                    zedAuthorizationResult = L10n.t("s279")
                    store.refresh()
                } else if interactiveSucceeded {
                    zedAuthorizationResult = L10n.t("s101")
                } else {
                    zedAuthorizationResult = L10n.t("s374")
                }
            }
        }
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
        settingsSection("lock.shield", L10n.t("s533")) {
            settingsToggleRow(L10n.t("s249"), isOn: $activityStatisticsEnabled)
            Text(L10n.t("s440"))
                .font(.system(size: Theme.fontSize(8.5)))
                .foregroundStyle(Theme.tTertiary)
                .fixedSize(horizontal: false, vertical: true)

            thinDivider

            settingsToggleRow(L10n.t("s013"), isOn: $claudeCLIQuotaEnabled)
            Text(L10n.t("s554"))
                .font(.system(size: Theme.fontSize(8.5)))
                .foregroundStyle(Theme.tTertiary)
                .fixedSize(horizontal: false, vertical: true)

            thinDivider

            settingsToggleRow(L10n.t("s026"), isOn: $grokLiveQuotaEnabled)
            Text(L10n.t("s557"))
                .font(.system(size: Theme.fontSize(8.5)))
                .foregroundStyle(Theme.tTertiary)
                .fixedSize(horizontal: false, vertical: true)

            thinDivider

            settingsToggleRow(L10n.t("s022"), isOn: $grokBotQuotaEnabled)
            Text(L10n.t("s250"))
                .font(.system(size: Theme.fontSize(8.5)))
                .foregroundStyle(Theme.tTertiary)
                .fixedSize(horizontal: false, vertical: true)
            if grokBotQuotaEnabled {
                HStack(spacing: 8) {
                    settingsActionButton(
                        icon: "key.fill",
                        title: grokBotAuthorizing ? L10n.t("s455") : L10n.t("s275")
                    ) {
                        authorizeGrokBotQuota()
                    }
                    .disabled(grokBotAuthorizing)
                    if grokBotAuthorizing { ProgressView().controlSize(.mini) }
                    if !grokBotAuthorizationResult.isEmpty {
                        Text(grokBotAuthorizationResult)
                            .font(.system(size: Theme.fontSize(8.5)))
                            .foregroundStyle(Theme.tTertiary)
                            .lineLimit(2)
                    }
                }
            }

            thinDivider

            settingsToggleRow(L10n.t("s143"), isOn: $qwenWorkQuotaEnabled)
            Text(L10n.t("s555"))
                .font(.system(size: Theme.fontSize(8.5)))
                .foregroundStyle(Theme.tTertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .onChange(of: activityStatisticsEnabled) { _ in
            ActivityReporter.shared.preferencesChanged()
        }
        .onChange(of: claudeCLIQuotaEnabled) { _ in
            store.refresh()
        }
        .onChange(of: grokLiveQuotaEnabled) { enabled in
            Self.setGrokLiveQuotaEnabled(enabled)
            store.refresh()
        }
        .onChange(of: grokBotQuotaEnabled) { enabled in
            Self.setProviderQuotaEnabled("grok_bot", enabled)
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

    private func authorizeGrokBotQuota() {
        guard !grokBotAuthorizing else { return }
        guard let executable = GrokBotHelperManager.installIfNeeded() else {
            grokBotAuthorizationResult = L10n.t("s277")
            return
        }
        grokBotAuthorizing = true
        grokBotAuthorizationResult = ""
        DispatchQueue.global(qos: .userInitiated).async {
            func run(_ argument: String) -> Bool {
                let process = Process()
                process.executableURL = executable
                process.arguments = [argument]
                process.standardInput = FileHandle.nullDevice
                process.standardOutput = FileHandle.nullDevice
                process.standardError = FileHandle.nullDevice
                do {
                    try process.run()
                    process.waitUntilExit()
                    return process.terminationStatus == 0
                } catch {
                    return false
                }
            }
            let interactiveSucceeded = run("--grok-bot-authorize")
            let persistentSucceeded = interactiveSucceeded && run("--grok-bot-verify")
            DispatchQueue.main.async {
                grokBotAuthorizing = false
                if persistentSucceeded {
                    grokBotAuthorizationResult = L10n.t("s278")
                    store.refresh()
                } else if interactiveSucceeded {
                    grokBotAuthorizationResult = L10n.t("s101")
                } else {
                    grokBotAuthorizationResult = L10n.t("s373")
                }
            }
        }
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
            ("devin", "showDevin", true),
            ("cursor", "showCursor", false),
            ("grok_bot", "grokBotQuotaEnabled", false),
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
        settingsSection("dollarsign.circle", L10n.t("s103")) {
            HStack(spacing: 8) {
                settingsActionButton(icon: "arrow.down.circle", title: L10n.t("s114")) {
                    runPriceUpdate("--update-prices", L10n.t("s115"))
                }
                .disabled(priceUpdating)

                settingsActionButton(icon: "magnifyingglass.circle", title: L10n.t("s398")) {
                    runPriceUpdate("--update-unknown", L10n.t("s399"))
                }
                .disabled(priceUpdating)

                if priceUpdating { ProgressView().controlSize(.mini) }
            }

            if !priceResult.isEmpty && !priceUpdating {
                Text(priceResult)
                    .font(.system(size: Theme.fontSize(9)))
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
        settingsSection("stethoscope", L10n.t("s483")) {
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
                            .font(.system(size: Theme.fontSize(10)))
                            .foregroundStyle(Theme.tTertiary)
                            .frame(width: 22, height: 22)
                            .background(Circle().fill(Color.primary.opacity(0.06)))
                    }
                    .buttonStyle(.plain)
                    .tip(L10n.t("s206"))
                }
            }

            if !debugOutput.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Button {
                        withAnimation(.easeInOut(duration: 0.18)) { debugExpanded.toggle() }
                    } label: {
                        HStack(spacing: 5) {
                            Image(systemName: debugExpanded ? "chevron.down" : "chevron.right")
                                .font(.system(size: Theme.fontSize(8), weight: .semibold))
                            Text(debugSummary)
                                .font(.system(size: Theme.fontSize(9), design: .monospaced))
                                .lineLimit(1)
                            Spacer()
                        }
                        .foregroundStyle(Theme.tSecondary)
                    }
                    .buttonStyle(.plain)

                    if debugExpanded {
                        Text(debugOutput)
                            .font(.system(size: Theme.fontSize(8.5), design: .monospaced))
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
        settingsSection("figure.walk.circle", L10n.t("s099")) {
            settingsToggleRow(L10n.t("s187"), isOn: $sitReminderOn)
                .onChange(of: sitReminderOn) { _ in store.sitReminder.updateRunning() }

            if sitReminderOn {
                HStack {
                    Text(L10n.t("s531")).font(.system(size: Theme.fontSize(10))).foregroundStyle(Theme.tTertiary)
                    Spacer()
                    Picker("", selection: $sitReminderInterval) {
                        Text("45m").tag(45); Text("60m").tag(60); Text("90m").tag(90)
                    }
                    .pickerStyle(.segmented)
                    .frame(width: 130)
                    .controlSize(.mini)
                    .onChange(of: sitReminderInterval) { _ in store.sitReminder.updateRunning() }
                }

                settingsActionButton(icon: "bell.badge", title: L10n.t("s428")) {
                    store.sitReminder.testPing()
                }

                Text(L10n.t("s203"))
                    .font(.system(size: Theme.fontSize(8.5)))
                    .foregroundStyle(Theme.tTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    var settingsSyncSection: some View {
        settingsSection("arrow.triangle.2.circlepath", L10n.t("s210")) {
            settingsToggleRow(L10n.t("s187"), isOn: $store.syncEnabled)
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
                settingsValueRow(L10n.t("s480")) {
                    TextField("hostname", text: $deviceName)
                        .font(.system(size: Theme.fontSize(10), design: .monospaced))
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

                settingsValueRow(L10n.t("s447")) {
                    Text(syncDir.isEmpty ? L10n.t("s376") : (syncDir as NSString).lastPathComponent)
                        .font(.system(size: Theme.fontSize(10), design: .monospaced))
                        .foregroundStyle(syncDir.isEmpty ? Theme.tTertiary : Theme.tSecondary)
                        .lineLimit(1)
                    Button(L10n.t("s520")) { pickSyncDir() }
                        .font(.system(size: Theme.fontSize(10)))
                        .buttonStyle(.plain)
                        .foregroundStyle(Theme.claude)
                        .disabled(store.syncing)
                }

                HStack(spacing: 6) {
                    settingsActionButton(
                        icon: "arrow.triangle.2.circlepath",
                        title: store.syncing ? L10n.t("s166") : L10n.t("s165"),
                        width: 86
                    ) {
                        if saveSync() { store.doSync() }
                    }
                    .disabled(store.syncing || syncDir.isEmpty)

                    Spacer(minLength: 6)
                    Text(L10n.t("s474"))
                        .font(.system(size: Theme.fontSize(10)))
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
                    .font(.system(size: Theme.fontSize(8.5), weight: .medium))
                    .foregroundStyle(store.syncSucceeded == false ? Theme.claude : Theme.hermes)
                    .help(store.syncDetail)
                }

                if !store.peerLoadIssues.isEmpty {
                    HStack(spacing: 4) {
                        Spacer()
                        Image(systemName: "exclamationmark.triangle.fill")
                        Text(L10n.f("s371", store.peerLoadIssues.count))
                    }
                    .font(.system(size: Theme.fontSize(8.5), weight: .medium))
                    .foregroundStyle(Theme.claude)
                    .help(store.peerLoadIssues.map(\.summary).joined(separator: "\n"))
                }

                deviceStatusBlock

                if store.syncEnabled {
                    let dataRepo = cachedRemoteUrl
                    let hasRemote = !dataRepo.isEmpty && !dataRepo.contains(L10n.t("s378"))
                        && (dataRepo.hasPrefix("http") || dataRepo.hasPrefix("git@") || dataRepo.hasPrefix("ssh://"))
                    Rectangle().fill(Color.primary.opacity(0.06)).frame(height: 1)
                    VStack(alignment: .leading, spacing: 8) {
                        HStack(spacing: 5) {
                            Image(systemName: "plus.circle")
                                .font(.system(size: Theme.fontSize(10), weight: .semibold))
                                .foregroundStyle(Theme.hermes)
                            Text(L10n.t("s431"))
                                .font(.system(size: Theme.fontSize(10), weight: .semibold))
                                .foregroundStyle(Theme.tSecondary)
                        }

                        if syncDir.isEmpty {
                            Text(L10n.t("s487"))
                                .font(.system(size: Theme.fontSize(9))).foregroundStyle(Theme.tTertiary)
                                .fixedSize(horizontal: false, vertical: true)
                            copyBlock(L10n.f("s495", Self.skillPath))
                        } else if hasRemote {
                            Text(L10n.t("s158")).font(.system(size: Theme.fontSize(9), weight: .medium)).foregroundStyle(Theme.tSecondary)
                            Text(L10n.t("s217"))
                                .font(.system(size: Theme.fontSize(8.5))).foregroundStyle(Theme.tTertiary)
                                .fixedSize(horizontal: false, vertical: true)
                            Rectangle().fill(Color.primary.opacity(0.04)).frame(height: 1)
                            Text(L10n.t("s513")).font(.system(size: Theme.fontSize(9), weight: .medium)).foregroundStyle(Theme.tSecondary)
                            copyBlock(linuxSetupCommand(remote: dataRepo))
                        } else {
                            Text(L10n.t("s290"))
                                .font(.system(size: Theme.fontSize(9))).foregroundStyle(Theme.tTertiary)
                            copyBlock(L10n.f("s495", Self.skillPath))
                        }
                    }
                }
            }
        }
    }

    var settingsRemoteHintSection: some View {
        settingsSection("antenna.radiowaves.left.and.right", L10n.t("s514")) {
            Text(L10n.t("s209"))
                .font(.system(size: Theme.fontSize(9)))
                .foregroundStyle(Theme.tTertiary)
                .fixedSize(horizontal: false, vertical: true)
            copyBlock(L10n.f("s494", Self.skillPath))
        }
    }

    var deviceStatusBlock: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 5) {
                Image(systemName: "desktopcomputer")
                    .font(.system(size: Theme.fontSize(8))).foregroundStyle(.green)
                Text(deviceName.isEmpty ? L10n.scopeLocal : deviceName)
                    .font(.system(size: Theme.fontSize(10), weight: .medium)).foregroundStyle(Theme.tPrimary)
                Text(L10n.t("s005")).font(.system(size: Theme.fontSize(9))).foregroundStyle(Theme.tTertiary)
            }
            if store.peers.isEmpty {
                HStack(spacing: 5) {
                    Image(systemName: "clock")
                        .font(.system(size: Theme.fontSize(8))).foregroundStyle(Theme.tTertiary)
                    Text(L10n.t("s454"))
                        .font(.system(size: Theme.fontSize(10))).foregroundStyle(Theme.tTertiary)
                }
            } else {
                ForEach(store.peers) { p in
                    HStack(spacing: 5) {
                        Image(systemName: "laptopcomputer")
                            .font(.system(size: Theme.fontSize(8))).foregroundStyle(Theme.codex)
                        Text(p.deviceId)
                            .font(.system(size: Theme.fontSize(10), weight: .medium)).foregroundStyle(Theme.tPrimary)
                        Spacer()
                        Text(Fmt.reset(Int(p.lastSync.timeIntervalSince1970)))
                            .font(.system(size: Theme.fontSize(9), design: .monospaced)).foregroundStyle(Theme.tTertiary)
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
                    .font(.system(size: Theme.fontSize(13), weight: .semibold))
                    .foregroundStyle(Theme.claude)
            }
            .frame(width: 30, height: 30)
            VStack(alignment: .leading, spacing: 1) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(L10n.t("settings"))
                        .font(.system(size: Theme.fontSize(15), weight: .bold, design: .rounded))
                        .foregroundStyle(Theme.tPrimary)
                    Text("\(Updater.releaseTag) · \(Self.buildVersion)")
                        .font(.system(size: Theme.fontSize(8), design: .monospaced))
                        .foregroundStyle(Theme.tTertiary.opacity(0.6))
                }
                Text(L10n.t("s348"))
                    .font(.system(size: Theme.fontSize(9.5)))
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
            if Updater.isLocalBuild {
                Text(L10n.t("s389"))
                    .font(.system(size: Theme.fontSize(9)))
                    .foregroundStyle(Theme.tTertiary)
                    .tip(L10n.t("s421"))
            } else if case .idle = updater.state {
                Button { updater.checkForUpdate() } label: {
                    Image(systemName: "arrow.triangle.2.circlepath")
                        .font(.system(size: Theme.fontSize(10), weight: .semibold))
                        .foregroundStyle(Theme.tTertiary)
                        .frame(width: 24, height: 24)
                        .background(Circle().fill(Color.primary.opacity(0.06)))
                }
                .buttonStyle(.plain)
                .tip(L10n.t("s404"))
            } else if case .checking = updater.state {
                ProgressView()
                    .controlSize(.small)
                    .frame(width: 24, height: 24)
            } else if case .upToDate = updater.state {
                Image(systemName: "checkmark.circle.fill")
                    .font(.system(size: Theme.fontSize(12)))
                    .foregroundStyle(.green)
                    .frame(width: 24, height: 24)
            }
            updatePill
            Button {
                withAnimation(.easeInOut(duration: 0.25)) { mode = .cards }
            } label: {
                Image(systemName: "xmark")
                    .font(.system(size: Theme.fontSize(10), weight: .bold))
                    .foregroundStyle(Theme.tTertiary)
                    .frame(width: 24, height: 24)
                    .background(Circle().fill(Color.primary.opacity(0.06)))
            }
            .buttonStyle(.plain)
            .tip(L10n.t("s121"))
        }
        .padding(.bottom, 2)
    }

    func settingsSection<C: View>(_ icon: String, _ title: String, @ViewBuilder content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Image(systemName: icon)
                    .font(.system(size: Theme.fontSize(10), weight: .bold))
                    .foregroundStyle(Theme.claude.opacity(0.95))
                    .frame(width: 20, height: 20)
                    .background(Circle().fill(Theme.claude.opacity(0.10)))
                Text(title)
                    .font(.system(size: Theme.fontSize(12), weight: .semibold))
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
                Image(systemName: icon).font(.system(size: Theme.fontSize(9)))
                Text(title).font(.system(size: Theme.fontSize(10), weight: .medium))
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
            Text(title).font(.system(size: Theme.fontSize(11))).foregroundStyle(Theme.tPrimary)
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
            Text(title).font(.system(size: Theme.fontSize(10))).foregroundStyle(Theme.tTertiary)
            Spacer()
            value()
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
    }

    func settingsStackedValue<C: View>(_ title: String, @ViewBuilder value: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title)
                .font(.system(size: Theme.fontSize(10)))
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
            store.syncStatus = L10n.t("s481")
            store.syncDetail = L10n.t("s482")
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
            store.syncStatus = L10n.t("s182")
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
                        priceResult = count > 0 ? L10n.f("s478", count) : L10n.t("s265")
                    } else {
                        priceResult = output.trimmingCharacters(in: .whitespacesAndNewlines)
                    }
                }
                store.refresh()
            }
        }
    }

    private var debugButtonTitle: String {
        if debugRunning { return L10n.t("s403") }
        return debugOutput.isEmpty ? L10n.t("s508") : L10n.t("s288")
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
                         "sub2api", "zai", "grok", "grok_bot", "qoder", "qoderwork", "qodercli", "hermes",
                         "zcode", "mimocode", "openclaw", "pi", "workbuddy", "workbuddy_ai",
                         "codebuddy",
                         "deepseek_harness",
                         "opencode", "qwencode", "qwenwork", "kimicode", "musecode", "cmdcode", "prime_agent",
                         "devin"]
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
        Bundle.main.object(forInfoDictionaryKey: "TokeiBuildDate") as? String ?? L10n.t("s372")
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
        return url.isEmpty ? L10n.t("s011") : url
    }

    private static func shellQuote(_ s: String) -> String {
        ShellEscaping.singleQuoted(s)
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
                    print(\(Self.shellQuote(L10n.t("s037"))), file=sys.stderr)
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
                print(\(Self.shellQuote(L10n.t("s038"))),
                      file=sys.stderr)
                stop_process_group()
                sys.exit(124)
            sys.exit(return_code)
        except (OSError, ValueError, json.JSONDecodeError,
                subprocess.CalledProcessError) as error:
            print(\(Self.shellQuote(L10n.t("s039"))).format(error),
                  file=sys.stderr)
            sys.exit(20)
        PY
        fi

        [ "$#" -eq 5 ] || fail 75 \(Self.shellQuote(L10n.t("s184")))
        lock_fd="$2"
        repo="$3"
        lock_path="$4"
        device_id="$5"

        # 拒绝绕过锁直接进入事务，并确认继承的描述符指向当前仓库锁文件。
        python3 - "$lock_fd" "$lock_path" <<'PY' \
          || fail 75 \(Self.shellQuote(L10n.t("s328")))
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
        cd "$repo" || fail 20 \(Self.shellQuote(L10n.t("s336")))

        git_dir=$(sync_git rev-parse --absolute-git-dir 2>/dev/null) \
          || fail 20 \(Self.shellQuote(L10n.t("s180")))
        declared_root=$(sync_git rev-parse --show-toplevel 2>/dev/null) \
          || fail 20 \(Self.shellQuote(L10n.t("s333")))
        declared_root=$(cd -- "$declared_root" 2>/dev/null && /bin/pwd -P) \
          || fail 20 \(Self.shellQuote(L10n.t("s329")))
        current_root=$(/bin/pwd -P)
        [ "$declared_root" = "$current_root" ] \
          || fail 20 \(Self.shellQuote(L10n.t("s167")))
        [ "$git_dir/tokei-sync.lock" = "$lock_path" ] \
          || fail 75 \(Self.shellQuote(L10n.t("s168")))
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
              fail 21 \(Self.shellQuote(L10n.t("s405")))
            fi
          fi
          fail 21 \(Self.shellQuote(L10n.t("s407")))
        elif [ -f "$marker" ]; then
          validate_marker || fail 21 \(Self.shellQuote(L10n.t("s154")))
          fail 21 \(Self.shellQuote(L10n.t("s152")))
        fi

        for operation in MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD BISECT_START; do
          operation_path=$(sync_git rev-parse --git-path "$operation")
          [ ! -e "$operation_path" ] \
            || fail 21 \(Self.shellQuote(L10n.t("s408")))
        done
        sequencer_path=$(sync_git rev-parse --git-path sequencer)
        [ ! -d "$sequencer_path" ] \
          || fail 21 \(Self.shellQuote(L10n.t("s409")))
        unmerged_state=$(sync_git ls-files -u) || fail 21 \(Self.shellQuote(L10n.t("s327")))
        [ -z "$unmerged_state" ] \
          || fail 21 \(Self.shellQuote(L10n.t("s459")))

        branch=$(sync_git symbolic-ref --quiet --short HEAD 2>/dev/null) \
          || fail 22 \(Self.shellQuote(L10n.t("s171")))
        [ "$branch" = "main" ] \
          || fail 22 \(Self.shellQuote(L10n.t("s172")))

        sync_git remote get-url origin >/dev/null 2>&1 \
          || fail 20 \(Self.shellQuote(L10n.t("s173")))
        sync_git fetch origin main || fail 25 \(Self.shellQuote(L10n.t("s270")))
        sync_git show-ref --verify --quiet refs/remotes/origin/main \
          || fail 25 \(Self.shellQuote(L10n.t("s077")))
        tracked_peer_files=$(sync_git ls-files --cached -- \
          "$peer_json_pathspec" "$exclude_pathspec") \
          || fail 23 \(Self.shellQuote(L10n.t("s316")))
        if [ -n "$tracked_peer_files" ]; then
          sync_git restore --source=HEAD --staged --worktree -- \
            "$peer_json_pathspec" "$exclude_pathspec" \
            || fail 23 \(Self.shellQuote(L10n.t("s315")))
        fi
        other_changes=$(sync_git status --porcelain=v1 --untracked-files=all \
          -- . "$exclude_pathspec") \
          || fail 23 \(Self.shellQuote(L10n.t("s318")))
        [ -z "$other_changes" ] \
          || fail 23 \(Self.shellQuote(L10n.t("s169")))

        ensure_local_commits_only_device() {
          audit_base=$(sync_git rev-parse --verify "$1^{commit}") \
            || fail 23 \(Self.shellQuote(L10n.t("s300")))
          audit_target=$(sync_git rev-parse --verify "$2^{commit}") \
            || fail 23 \(Self.shellQuote(L10n.t("s301")))
          audit_commits=$(sync_git rev-list --reverse "$audit_base..$audit_target") \
            || fail 23 \(Self.shellQuote(L10n.t("s295")))
          for audit_commit in $audit_commits; do
            audit_parent_line=$(sync_git rev-list --parents -n 1 "$audit_commit") \
              || fail 23 \(Self.shellQuote(L10n.t("s334")))
            set -- $audit_parent_line
            [ "$#" -eq 2 ] \
              || fail 23 \(Self.shellQuote(L10n.t("s381")))
            audit_parent="$2"

            if sync_git diff-tree --quiet --no-renames "$audit_parent" "$audit_commit" --; then
              fail 23 \(Self.shellQuote(L10n.t("s383")))
            else
              audit_status="$?"
              [ "$audit_status" -eq 1 ] \
                || fail 23 \(Self.shellQuote(L10n.t("s312")))
            fi

            if sync_git diff-tree --quiet --no-renames "$audit_parent" "$audit_commit" \
              -- "$device_pathspec"; then
              fail 23 \(Self.shellQuote(L10n.t("s258")))
            else
              audit_status="$?"
              [ "$audit_status" -eq 1 ] \
                || fail 23 \(Self.shellQuote(L10n.t("s314")))
            fi

            if sync_git diff-tree --quiet --no-renames "$audit_parent" "$audit_commit" \
              -- . "$exclude_pathspec"; then
              :
            else
              audit_status="$?"
              [ "$audit_status" -ne 1 ] \
                || fail 23 \(Self.shellQuote(L10n.t("s259")))
              fail 23 \(Self.shellQuote(L10n.t("s313")))
            fi
          done
        }

        pre_snapshot_head=$(sync_git rev-parse --verify "HEAD^{commit}") \
          || fail 23 \(Self.shellQuote(L10n.t("s303")))
        pre_snapshot_base=$(sync_git rev-parse --verify "origin/main^{commit}") \
          || fail 23 \(Self.shellQuote(L10n.t("s304")))
        ensure_local_commits_only_device "$pre_snapshot_base" "$pre_snapshot_head"
        verified_pre_snapshot_head=$(sync_git rev-parse --verify "HEAD^{commit}") \
          || fail 23 \(Self.shellQuote(L10n.t("s310")))
        [ "$verified_pre_snapshot_head" = "$pre_snapshot_head" ] \
          || fail 23 \(Self.shellQuote(L10n.t("s260")))
        python3 - "$HOME/.tokei/usage.30s.py" "$repo" "$device_id" <<'PY' \
          || fail 24 \(Self.shellQuote(L10n.t("s438")))
        import importlib.util
        import sys

        script_path, sync_dir, device_id = sys.argv[1:]
        spec = importlib.util.spec_from_file_location("tokei_usage_sync", script_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(\(Self.shellQuote(L10n.t("s296"))))
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        module._load_tokei_config = lambda: {
            "sync_dir": sync_dir,
            "device_id": device_id,
        }
        writer = getattr(module, "write_sync_snapshot", None)
        if not callable(writer):
            raise RuntimeError(\(Self.shellQuote(L10n.t("s089"))))
        raise SystemExit(writer())
        PY

        matches=$(sync_git ls-files --cached --others --exclude-standard \
          -- "$device_pathspec") \
          || fail 24 \(Self.shellQuote(L10n.t("s325")))
        match_count=$(printf '%s\n' "$matches" \
          | awk 'NF { count++ } END { print count + 0 }')
        [ "$match_count" -eq 1 ] \
          || fail 24 \(Self.shellQuote(L10n.t("s394")))

        other_changes=$(sync_git status --porcelain=v1 --untracked-files=all \
          -- . "$exclude_pathspec") \
          || fail 23 \(Self.shellQuote(L10n.t("s326")))
        [ -z "$other_changes" ] \
          || fail 23 \(Self.shellQuote(L10n.t("s437")))

        sync_git add -- "$device_pathspec" || fail 26 \(Self.shellQuote(L10n.t("s350")))
        if ! sync_git diff --cached --quiet -- "$device_pathspec"; then
          sync_git commit --only -m "tokei sync $device_id" -- "$device_pathspec" \
            || fail 26 \(Self.shellQuote(L10n.t("s284")))
        fi
        post_commit_changes=$(sync_git status --porcelain=v1 --untracked-files=all) \
          || fail 26 \(Self.shellQuote(L10n.t("s321")))
        [ -z "$post_commit_changes" ] \
          || fail 26 \(Self.shellQuote(L10n.t("s282")))
        post_commit_head=$(sync_git rev-parse --verify "HEAD^{commit}") \
          || fail 23 \(Self.shellQuote(L10n.t("s306")))
        post_commit_base=$(sync_git rev-parse --verify "origin/main^{commit}") \
          || fail 23 \(Self.shellQuote(L10n.t("s305")))
        ensure_local_commits_only_device "$post_commit_base" "$post_commit_head"
        verified_post_commit_head=$(sync_git rev-parse --verify "HEAD^{commit}") \
          || fail 23 \(Self.shellQuote(L10n.t("s311")))
        [ "$verified_post_commit_head" = "$post_commit_head" ] \
          || fail 23 \(Self.shellQuote(L10n.t("s281")))

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
          } > "$marker_tmp" || fail 28 \(Self.shellQuote(L10n.t("s294")))
          mv -f "$marker_tmp" "$marker" || fail 28 \(Self.shellQuote(L10n.t("s293")))
        }

        rebase_onto_origin() {
          pre_rebase_head=$(sync_git rev-parse --verify "HEAD^{commit}") \
            || fail 27 \(Self.shellQuote(L10n.t("s331")))
          pre_rebase_onto=$(sync_git rev-parse --verify "origin/main^{commit}") \
            || fail 27 \(Self.shellQuote(L10n.t("s330")))
          ensure_local_commits_only_device "$pre_rebase_onto" "$pre_rebase_head"
          checked_rebase_head=$(sync_git rev-parse --verify "HEAD^{commit}") \
            || fail 27 \(Self.shellQuote(L10n.t("s309")))
          [ "$checked_rebase_head" = "$pre_rebase_head" ] \
            || fail 23 \(Self.shellQuote(L10n.t("s086")))
          if sync_git merge-base --is-ancestor "$pre_rebase_onto" "$pre_rebase_head"; then
            return 0
          fi
          write_marker "$pre_rebase_head" "$pre_rebase_onto"
          if sync_git rebase --merge "$pre_rebase_onto"; then
            rm -f "$marker"
            return 0
          fi
          if [ -d "$rebase_merge" ] || [ -d "$rebase_apply" ]; then
            fail 27 \(Self.shellQuote(L10n.t("s088")))
          fi
          rm -f "$marker"
          fail 27 \(Self.shellQuote(L10n.t("s393")))
        }

        attempt=1
        while [ "$attempt" -le 3 ]; do
          rebase_onto_origin
          candidate_head=$(sync_git rev-parse --verify "HEAD^{commit}") \
            || fail 23 \(Self.shellQuote(L10n.t("s297")))
          audit_base=$(sync_git rev-parse --verify "origin/main^{commit}") \
            || fail 23 \(Self.shellQuote(L10n.t("s298")))
          ensure_local_commits_only_device "$audit_base" "$candidate_head"
          push_changes=$(sync_git status --porcelain=v1 --untracked-files=all) \
            || fail 23 \(Self.shellQuote(L10n.t("s317")))
          [ -z "$push_changes" ] \
            || fail 23 \(Self.shellQuote(L10n.t("s078")))
          push_head=$(sync_git rev-parse --verify "HEAD^{commit}") \
            || fail 23 \(Self.shellQuote(L10n.t("s307")))
          [ "$push_head" = "$candidate_head" ] \
            || fail 23 \(Self.shellQuote(L10n.t("s223")))
          if sync_git push origin "$candidate_head:refs/heads/main"; then
            pushed_head=$(sync_git rev-parse --verify "HEAD^{commit}" 2>/dev/null || true)
            [ "$pushed_head" = "$candidate_head" ] \
              || fail 23 \(Self.shellQuote(L10n.t("s083")))
            printf '多设备同步完成\n'
            exit 0
          fi

          sync_git fetch origin main || fail 25 \(Self.shellQuote(L10n.t("s081")))
          retry_head=$(sync_git rev-parse --verify "HEAD^{commit}" 2>/dev/null || true)
          [ "$retry_head" = "$candidate_head" ] \
            || fail 23 \(Self.shellQuote(L10n.t("s085")))
          if sync_git merge-base --is-ancestor "$candidate_head" origin/main; then
            printf '远端已包含本机同步提交\n'
            exit 0
          fi
          if sync_git merge-base --is-ancestor origin/main "$candidate_head"; then
            fail 29 \(Self.shellQuote(L10n.t("s516")))
          fi
          [ "$attempt" -lt 3 ] || fail 29 \(Self.shellQuote(L10n.t("s515")))
          /bin/sleep "$attempt"
          attempt=$((attempt + 1))
          printf '检测到其他设备同时更新，正在重试 %s/3\n' "$attempt"
        done

        fail 29 \(Self.shellQuote(L10n.t("s080")))
        SH
        chmod +x ~/.tokei/tokei-sync.sh
        (crontab -l 2>/dev/null | grep -v 'tokei-sync.sh'; echo '*/30 * * * * ~/.tokei/tokei-sync.sh') | crontab -
        """
    }

    func copyBlock(_ text: String) -> some View {
        HStack(alignment: .top) {
            Text(text)
                .font(.system(size: Theme.fontSize(8), design: .monospaced))
                .foregroundStyle(Theme.tSecondary)
                .lineLimit(4)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 4)
            Button {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(text, forType: .string)
            } label: {
                Image(systemName: "doc.on.doc")
                    .font(.system(size: Theme.fontSize(9))).foregroundStyle(Theme.tTertiary)
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
        panel.prompt = L10n.t("s521")
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
                .font(.system(size: Theme.fontSize(11), weight: .medium))
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
