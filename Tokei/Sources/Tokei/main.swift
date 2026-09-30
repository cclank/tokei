import AppKit
import SwiftUI
import Combine
import GrokBotBridge

final class Store: ObservableObject {
    @Published var usage: Usage?
    @Published var localUsage: Usage?
    @Published var allDevicesUsage: Usage?
    @Published var lastUpdated: String = L("加载中…")
    @Published var loadError: String?
    @Published var peers: [PeerDevice] = []
    @Published var syncing = false
    @Published var syncStatus = ""
    @Published var syncSucceeded: Bool?
    @Published var syncDetail = ""
    @Published var syncFailStreak = 0
    @Published var peerLoadIssues: [PeerLoadIssue] = []
    // popover 的视图树启动时建好后就不再释放,面板关上也还活着。
    // 动画类视图得靠这个标志判断自己是不是真的能被看见。
    @Published var popoverVisible = false
    /// 正在跑刷新。空态卡片靠它区分「这个区间真没用量」和「还没刷出来」——
    /// 两者长得一模一样，但一个是结论，一个只是还没轮到。
    @Published var isRefreshing = false

    let syncManager = SyncManager()
    let quotaHistory = QuotaHistoryStore.shared
    let keepAwake = KeepAwake()
    let sitReminder = SitReminder()
    var autoSyncTimer: Timer?
    private var autoSyncStartupWorkItem: DispatchWorkItem?

    @AppStorage("showAllDevices") var showAllDevices = true
    @AppStorage("syncEnabled") var syncEnabled = false

    private var retryCount = 0
    private var refreshInFlight = false { didSet { isRefreshing = refreshInFlight } }
    private var refreshPending = false
    private var dashboardPrewarmStarted = false
    private var quotaDetailPrewarmPending = false
    /// 上一次刷新开跑的时刻。调度按它算间隔，所以「面板打开顺手刷的那次」
    /// 也算数，不会开完面板立刻又被定时器刷一遍。
    private(set) var lastRefreshStartedAt = Date.distantPast
    /// 上一次刷新实际耗时。间隔要按它退避——扫描在数据量大的机器上可能十几秒，
    /// 固定 10 秒会让刷新首尾相接，还会和自己抢扫描缓存的文件锁，越刷越慢。
    private(set) var lastRefreshDuration: TimeInterval = 0

    func applyDisplayMode(updateStatusTitle: Bool = true) {
        usage = (syncEnabled && showAllDevices) ? (allDevicesUsage ?? localUsage) : localUsage
        if updateStatusTitle {
            (NSApp.delegate as? AppDelegate)?.updateStatusTitle()
        }
    }

    func primeCachedUsage() {
        guard usage == nil, let local = DataLoader.loadCachedUsage() else { return }
        localUsage = local
        var allDevices = local
        if syncEnabled {
            let report = syncManager.loadPeers()
            peers = report.peers
            peerLoadIssues = report.issues
            if !peers.isEmpty {
                allDevices = SyncManager.merge(local: local, peers: peers)
            }
        }
        allDevicesUsage = allDevices
        applyDisplayMode()
        lastUpdated = L("缓存数据 · 后台更新中")
    }

    func refresh(prewarmQuotaDetail: Bool = false) {
        quotaDetailPrewarmPending = quotaDetailPrewarmPending || prewarmQuotaDetail
        if refreshInFlight {
            refreshPending = true
            return
        }
        refreshInFlight = true
        performRefresh()
    }

    /// 打开额度曲线页时立刻取数。
    ///
    /// 原本在主刷新进行中会改为「等刷新完再说」，可那个延后链路有两个漏口：
    /// prewarmQuotaDetailIfReady 见到还有排队的刷新就直接返回，而刷新失败的分支
    /// 压根不会走到它。面板开着时刷新变密之后，这两个口子叠起来足以让页面一天
    /// 都不取一次数，只对着上次的缓存。
    ///
    /// 取数本身很便宜——脚本会复用 60 秒内的 last_usage.json，实测 3 秒出头，
    /// 而且 QuotaDetailRepository 自己有 refreshing 门闩挡重入，不需要外面再挡一层。
    func loadQuotaDetail() {
        QuotaDetailRepository.shared.load(force: true)
    }

    private func performRefresh() {
        lastRefreshStartedAt = Date()
        let startedAt = lastRefreshStartedAt
        DataLoader.load { [weak self] u in
            guard let self = self else { return }
            guard let local = u else {
                let hadPendingRefresh = self.refreshPending
                let willRetry = self.usage == nil && self.retryCount < 3
                if willRetry {
                    self.retryCount += 1
                    self.lastUpdated = L("加载中…(%@)", self.retryCount)
                    if !hadPendingRefresh {
                        DispatchQueue.main.asyncAfter(deadline: .now() + 3) { self.refresh() }
                    }
                } else if self.usage == nil {
                    self.loadError = L("读取用量失败")
                    self.lastUpdated = L("加载失败")
                } else {
                    self.loadError = nil
                    self.lastUpdated = L("缓存数据 · 等待刷新")
                }
                (NSApp.delegate as? AppDelegate)?.updateStatusTitle()
                if !willRetry { self.prewarmQuotaDetailIfReady() }
                self.finishRefresh()
                return
            }
            self.lastRefreshDuration = Date().timeIntervalSince(startedAt)
            self.retryCount = 0
            self.loadError = nil
            self.recordQuotaHistory(local)
            self.localUsage = local
            var allDevices = local
            if self.syncEnabled {
                let p: [PeerDevice]
                if self.syncing && !self.peers.isEmpty {
                    p = self.peers
                } else {
                    // 同步进行中若内存 peers 为空(如启动初期),仍从磁盘读快照,
                    // 避免首次刷新只显示本机数据造成"暂无数据→过一会才有"的闪变
                    let report = self.syncManager.loadPeers()
                    p = report.peers
                    self.peerLoadIssues = report.issues
                }
                self.peers = p
                if !p.isEmpty { allDevices = SyncManager.merge(local: local, peers: p) }
            } else {
                self.peers = []
                self.peerLoadIssues = []
            }
            self.allDevicesUsage = allDevices
            self.applyDisplayMode(updateStatusTitle: false)
            let f = DateFormatter(); f.dateFormat = "HH:mm:ss"
            self.lastUpdated = L("更新 %@", f.string(from: Date()))
            (NSApp.delegate as? AppDelegate)?.updateStatusTitle()
            if !self.refreshPending && !self.dashboardPrewarmStarted {
                self.dashboardPrewarmStarted = true
                DashboardRepository.shared.load(.all, force: true)
            }
            self.prewarmQuotaDetailIfReady()
            self.finishRefresh()
        }
    }

    private func prewarmQuotaDetailIfReady() {
        // 不再要求「没有排队中的刷新」：面板开着时刷新很密，那个条件几乎总为真，
        // 预热就一直轮空。重入由 QuotaDetailRepository 自己的门闩挡。
        guard quotaDetailPrewarmPending, popoverVisible else { return }
        quotaDetailPrewarmPending = false
        QuotaDetailRepository.shared.load(force: true)
    }

    private func finishRefresh() {
        if refreshPending {
            refreshPending = false
            performRefresh()
        } else {
            refreshInFlight = false
        }
    }

    private func recordQuotaHistory(_ usage: Usage) {
        let claudeRange = usage.claude.ranges.get(.today)
        let codexRange = usage.codex.ranges.get(.today)
        let claudeModels = claudeRange.models.reduce(into: [String: Int]()) { totals, model in
            guard model.name != "合成" else { return } // l10n-ignore
            totals[model.name, default: 0] += model.in + model.out + model.cr + model.cw
        }
        let codexModels = codexRange.models.reduce(into: [String: Int]()) { totals, model in
            totals[model.name, default: 0] +=
                model.in + model.out + model.cr + model.cw
        }
        quotaHistory.record(QuotaCapture(
            claudeFiveHourRemaining: usage.claude.q5_stale == true
                ? nil : usage.claude.q5.map { 100 - $0 },
            claudeWeekRemaining: usage.claude.q7_stale == true
                ? nil : usage.claude.q7.map { 100 - $0 },
            claudeFableWeekRemaining: usage.claude.qf_stale == true
                ? nil : usage.claude.qf.map { 100 - $0 },
            codexWeekRemaining: usage.codex.pw_stale == true
                ? nil : usage.codex.pw.map { 100 - $0 },
            claudeModelTotals: claudeModels,
            codexModelTotals: codexModels
        ))
    }

    func doSync() {
        guard syncEnabled, !syncing else { return }
        guard let cfg = syncManager.config else {
            syncStatus = L("同步配置不可用")
            syncSucceeded = false
            syncDetail = L("请先完成多设备同步配置")
            return
        }
        syncing = true
        syncStatus = L("正在同步")
        syncSucceeded = nil
        syncDetail = ""
        let deviceID = SyncManager.normalizedDeviceID(cfg.device_id)
        let syncDir = SyncManager.resolvedSyncDir(cfg)
        let snapshotCommand = DataLoader.syncSnapshotCommand(deviceID: deviceID, syncDir: syncDir)
        syncManager.synchronize(snapshotCommand: snapshotCommand) { [weak self] result in
            guard let self else { return }
            self.syncing = false
            self.syncDetail = result.output
            if result.succeeded {
                self.syncSucceeded = true
                self.syncFailStreak = 0
                let formatter = DateFormatter()
                formatter.dateFormat = "HH:mm"
                self.syncStatus = L("已同步 %@", formatter.string(from: Date()))
                self.refresh()
            } else if result.code == .busy {
                self.syncSucceeded = nil
                self.syncStatus = L("同步任务已在运行")
            } else {
                self.syncSucceeded = false
                self.syncFailStreak += 1
                self.syncStatus = self.syncFailStreak > 1
                    ? L("同步失败（连续 %@ 次）", self.syncFailStreak)
                    : L("同步失败")
            }
            (NSApp.delegate as? AppDelegate)?.updateStatusTitle()
        }
    }

    func startAutoSync(minutes: Int) {
        stopAutoSync()
        guard syncEnabled else { return }
        autoSyncTimer = Timer.scheduledTimer(withTimeInterval: TimeInterval(minutes * 60),
                                             repeats: true) { [weak self] _ in self?.doSync() }
        let startupWorkItem = DispatchWorkItem { [weak self] in
            self?.autoSyncStartupWorkItem = nil
            self?.doSync()
        }
        autoSyncStartupWorkItem = startupWorkItem
        DispatchQueue.main.asyncAfter(deadline: .now() + 5, execute: startupWorkItem)
    }

    func stopAutoSync() {
        autoSyncStartupWorkItem?.cancel()
        autoSyncStartupWorkItem = nil
        autoSyncTimer?.invalidate()
        autoSyncTimer = nil
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSPopoverDelegate {
    let store = Store()
    let panelLayout = PanelLayoutContext()
    var statusItem: NSStatusItem!
    var popover = NSPopover()
    /// 每次右键现建，跟随当前界面语言。
    var statusMenu: NSMenu {
        let menu = NSMenu()
        let quitItem = NSMenuItem(title: L("退出"), action: #selector(quitApp), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)
        return menu
    }
    var timer: Timer?
    /// 面板关着时按 30 秒刷；开着时用户正盯着看，30 秒的空窗会让人以为统计坏了，
    /// 所以加密到 10 秒。关上就退回去，免得白白每 10 秒拉起一次 Python。
    static let idleRefreshInterval: TimeInterval = 30
    static let visibleRefreshInterval: TimeInterval = 10
    var globalMouseMonitor: Any?
    weak var popoverAnchorButton: NSStatusBarButton?

    // 菜单栏额度颜色(与面板 Theme.claude/codex/grok 一致)。
    static let claudeColor = NSColor(red: 0.92, green: 0.52, blue: 0.40, alpha: 1)
    static let codexColor  = NSColor(red: 0.42, green: 0.68, blue: 0.98, alpha: 1)
    static let grokColor   = NSColor(red: 0.65, green: 0.68, blue: 0.75, alpha: 1)
    static let kimicodeColor = NSColor(red: 0.20, green: 0.78, blue: 0.66, alpha: 1)

    func applicationDidFinishLaunching(_ note: Notification) {
        // macOS 26 上用可变宽度初始化时，状态栏项偶发在按钮拿到标题、图标之前就被压没，
        // 进程在跑、菜单栏却看不到图标（issue #8，用户在 26.5 上复现并验证了这套处理）。
        // 先按正方形占位并显式设为可见；拿到内容后 fitStatusItemWidth 再按内容定宽。
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        statusItem.isVisible = true
        if let b = statusItem.button {
            b.action = #selector(handleStatusItemClick(_:))
            b.target = self
            b.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }
        updateStatusTitle()
        DispatchQueue.main.async { [weak self] in
            self?.statusItem?.isVisible = true
            self?.updateStatusTitle()
        }
        NotificationCenter.default.addObserver(
            forName: L10n.languageDidChange, object: nil, queue: .main
        ) { [weak self] _ in
            // 菜单栏标题与「更新于」这类状态文字是按旧语言写好的，换语言后重来一遍。
            self?.updateStatusTitle()
            self?.store.refresh()
        }

        let host = NSHostingController(rootView: PanelView(
            store: store,
            layout: panelLayout
        ))
        // 页面切换只改变固定画布内部内容，禁止 preferredContentSize 驱动
        // NSPopover 在全屏 Space 中重新选择屏幕和锚点。
        host.sizingOptions = []
        popover.contentViewController = host
        popover.contentSize = panelLayout.contentSize
        panelLayout.onPageWidthChange = { [weak self] in
            // 等这一轮视图更新结束再动弹窗。
            DispatchQueue.main.async { self?.refitPanelForPage() }
        }
        popover.behavior = .applicationDefined
        // SwiftUI 页面切换本身已有动画。禁用 NSPopover 的尺寸动画，避免 AppKit
        // 在外接显示器的全屏 Space 中按错误屏幕重新计算锚点。
        popover.animates = false
        popover.delegate = self

        // 启动时先把 Qoder IDE / Grok / 千问办公额度开关落盘到 config.json,
        // 确保随后的 refresh() 触发的 Python 扫描能读到正确配置。
        PanelView.syncQoderIdeConfigOnLaunch()
        PanelView.syncGrokLiveQuotaConfigOnLaunch()
        PanelView.syncQwenWorkQuotaConfigOnLaunch()
        PanelView.syncProviderQuotaConfigOnLaunch()
        if var syncConfig = store.syncManager.config {
            let interval = SyncManager.normalizedSyncInterval(syncConfig.sync_interval)
            if syncConfig.sync_interval != interval {
                syncConfig.sync_interval = interval
                store.syncManager.saveConfig(syncConfig)
            }
            if store.syncEnabled && syncConfig.auto_sync == true {
                store.startAutoSync(minutes: interval)
            }
        }
        store.primeCachedUsage()
        store.refresh()
        store.sitReminder.updateRunning()
        Updater.shared.checkForUpdate()
        ActivityReporter.shared.reportLaunchIfNeeded(appVersion: Updater.releaseTag)
        autoFetchPricing()
        // 用 .common 模式而不是 Timer.scheduledTimer 的默认 .default：
        // 后者在你滚动或拖动面板时 runloop 进入 .eventTracking，定时器直接停摆——
        // 越是盯着面板翻看越不更新。这里每 2 秒空转一次，到点了才真去刷。
        let tick = Timer(timeInterval: 2, repeats: true) { [weak self] _ in
            guard let self = self else { return }
            // 想要的节奏，再按上次耗时退避：一次刷新至少要留出同样长的空闲，
            // 否则扫描慢的机器上刷新会连成一片。快的机器不受影响。
            let wanted = self.store.popoverVisible
                ? Self.visibleRefreshInterval : Self.idleRefreshInterval
            let due = max(wanted, self.store.lastRefreshDuration * 2)
            guard Date().timeIntervalSince(self.store.lastRefreshStartedAt) >= due else { return }
            self.store.refresh()
        }
        RunLoop.main.add(tick, forMode: .common)
        timer = tick
        Timer.scheduledTimer(withTimeInterval: Updater.automaticCheckInterval, repeats: true) { _ in
            Updater.shared.checkForUpdate()
        }

        globalMouseMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] event in
            guard let self = self, self.popover.isShown else { return }
            if let popoverWindow = self.popover.contentViewController?.view.window,
               popoverWindow == event.window { return }
            self.popover.close()
        }

        if CommandLine.arguments.contains("--autoshow") {
            DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in
                self?.togglePopover()
            }
        }
    }

    func updateStatusTitle() {
        guard let b = statusItem?.button else { return }
        let style = MenuBarStyle.current
        let density = MenuBarDensity.current
        var metrics: [MenuBarMetric] = []
        var fallbackIcon = false

        if let u = store.usage {
            let ud = UserDefaults.standard
            // 菜单栏额度来源与「显示卡片」独立：卡片可开，但状态栏只显示用户勾选的窗口。
            metrics = MenuBarQuotaSource.metrics(in: u)
            if metrics.isEmpty {
                // 用户把额度来源全部关掉时：只保留图标，不再回退显示今日 token 总量。
                let anyQuotaSourceOn = MenuBarQuotaSource.allCases.contains { $0.isEnabled }
                if !anyQuotaSourceOn {
                    fallbackIcon = true
                } else {
                    let showC = ud.object(forKey: "showClaude") as? Bool ?? true
                    let showX = ud.object(forKey: "showCodex") as? Bool ?? true
                    let showP = ud.object(forKey: "showPi") as? Bool ?? true
                    let showW = ud.object(forKey: "showWorkBuddy") as? Bool ?? true
                    let showWAI = ud.object(forKey: "showWorkBuddyAI") as? Bool ?? true
                    let showCB = ud.object(forKey: "showCodeBuddy") as? Bool ?? true
                    let showD = ud.object(forKey: "showDeepSeekHarness") as? Bool ?? true
                    let showO = ud.object(forKey: "showOpenCode") as? Bool ?? true
                    let showQC = ud.object(forKey: "showQwenCode") as? Bool ?? true
                    let showQ = ud.object(forKey: "showQoderIde") as? Bool ?? false
                    let showQW = ud.object(forKey: "showQoderWork") as? Bool ?? true
                    let showQoderCli = ud.object(forKey: "showQoderCli") as? Bool ?? true
                    let showQoderCliCN = ud.object(forKey: "showQoderCliCN") as? Bool ?? true
                    let showZ = ud.object(forKey: "showZcode") as? Bool ?? true
                    let showM = ud.object(forKey: "showMimoCode") as? Bool ?? true
                    var total = 0
                    if showC { let r = u.claude.ranges.get(.today); total += Int(r.in + r.out + r.cr + r.cw) }
                    if showX {
                        let r = u.codex.ranges.get(.today)
                        let reserve = u.codex.reserveRanges?.get(.today) ?? CodexRange()
                        total += r.tokens + reserve.tokens
                    }
                    if showP { let r = u.pi.ranges.get(.today); total += Int(r.in + r.out + r.cr + r.cw + r.reason) }
                    if showW { let r = u.workbuddy.ranges.get(.today); total += Int(r.in + r.out + r.cr + r.cw) }
                    if showWAI { let r = u.workbuddyAI.ranges.get(.today); total += Int(r.in + r.out + r.cr + r.cw) }
                    if showCB { let r = u.codebuddy.ranges.get(.today); total += Int(r.in + r.out + r.cr + r.cw + r.reason) }
                    if showD { let r = u.deepseekHarness.ranges.get(.today); total += Int(r.in + r.out + r.cr + r.cw + r.reason) }
                    if showO { let r = u.opencode.ranges.get(.today); total += Int(r.in + r.out + r.cr + r.cw + r.reason) }
                    if showQC { let r = u.qwencode.ranges.get(.today); total += Int(r.in + r.out + r.cr + r.reason) }
                    if showQ { let r = u.qoder.ranges.get(.today); total += Int(r.in + r.out + r.cached) }
                    if showQW { let r = u.qoderwork.ranges.get(.today); total += r.totalTokens }
                    if showQoderCli { let r = u.qodercli.ranges.get(.today); total += r.totalTokens }
                    if showQoderCliCN { let r = u.qodercliCN.ranges.get(.today); total += r.totalTokens }
                    if showZ { let r = u.zcode.ranges.get(.today); total += Int(r.in + r.out + r.cr + r.cw + r.reason) }
                    if showM { let r = u.mimocode.ranges.get(.today); total += Int(r.in + r.out + r.cr + r.cw + r.reason) }
                    if total > 0 {
                        metrics.append(.init(kind: .total, value: Fmt.human(total)))
                    } else {
                        fallbackIcon = true
                    }
                }
            }
        } else {
            metrics.append(.init(kind: .total, value: "…"))
        }
        let presentation = MenuBarTitleRenderer.render(
            style: style,
            density: density,
            keepAwake: store.keepAwake.active,
            metrics: metrics,
            fallbackIcon: fallbackIcon
        )
        let displayedMetrics = MenuBarTitleRenderer.metricsForDisplay(metrics, density: density)
        b.image = presentation.image
        b.imageScaling = .scaleNone
        b.imagePosition = presentation.image == nil
            ? .noImage
            : (presentation.title.length == 0 ? .imageOnly : .imageLeading)
        if store.syncFailStreak >= 3 {
            let warned = NSMutableAttributedString(attributedString: presentation.title)
            warned.append(NSAttributedString(
                string: (warned.length > 0 ? " " : "") + "⚠",
                attributes: [
                    .font: NSFont.systemFont(ofSize: 11, weight: .semibold),
                    .foregroundColor: NSColor.systemOrange,
                    .baselineOffset: 1,
                ]))
            b.attributedTitle = warned
        } else {
            b.attributedTitle = presentation.title
        }
        b.contentTintColor = nil
        fitStatusItemWidth(b)
        var summaryParts = displayedMetrics.map { metric in
            let name = metric.kind.displayName
            if metric.stale && metric.remaining == nil {
                return L("%@ 已重置，等下一次读数", name)
            }
            if metric.remaining != nil {
                return metric.stale ? L("%@ 上次读到剩余 %@%%", name, metric.value)
                                    : L("%@ 剩余 %@%%", name, metric.value)
            }
            return "\(name) \(metric.value)"
        }
        if store.keepAwake.active {
            summaryParts.insert(L("保持唤醒已开启"), at: 0)
        }
        if store.syncFailStreak >= 3 {
            summaryParts.insert(L("多设备同步已连续失败 %@ 次，请打开设置查看", store.syncFailStreak), at: 0)
        }
        let summary = summaryParts.joined(separator: " · ")
        let accessibility = summary.isEmpty ? "Tokei" : "Tokei · \(summary)"
        b.toolTip = accessibility
        b.setAccessibilityLabel(accessibility)
    }

    private func fitStatusItemWidth(_ button: NSStatusBarButton) {
        button.invalidateIntrinsicContentSize()
        let compactWidth = ceil(button.intrinsicContentSize.width) + 4
        statusItem.length = max(NSStatusBar.system.thickness, compactWidth)
        // 菜单栏图标是唯一入口，每次定宽都确认一次可见（issue #8）。
        statusItem.isVisible = true
    }

    /// 已经在运行时，再从访达、启动台或 Spotlight 打开 Tokei 就直接唤出面板。
    /// 菜单栏图标被挤掉或系统没显示出来时（issue #8），这是唯一还能进来的入口。
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        statusItem?.isVisible = true
        DispatchQueue.main.async { [weak self] in
            guard let self, !self.popover.isShown,
                  let button = self.statusItem?.button, button.window != nil else { return }
            self.popoverAnchorButton = button
            self.togglePopover(anchorButton: button)
        }
        return false
    }

    func autoFetchPricing() {
        let pricingURL = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".tokei/pricing.json")
        if let attributes = try? FileManager.default.attributesOfItem(atPath: pricingURL.path),
           let modifiedAt = attributes[.modificationDate] as? Date,
           Date().timeIntervalSince(modifiedAt) < 24 * 3600 {
            return
        }
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let proc = Process()
            proc.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            proc.arguments = ["python3", DataLoader.scriptPath, "--update-prices"]
            proc.standardOutput = FileHandle.nullDevice
            proc.standardError = FileHandle.nullDevice
            try? proc.run()
            proc.waitUntilExit()
            DispatchQueue.main.async { self?.store.refresh() }
        }
    }

    @objc func handleStatusItemClick(_ sender: NSStatusBarButton) {
        if NSApp.currentEvent?.type == .rightMouseUp,
           let event = NSApp.currentEvent {
            if popover.isShown { popover.performClose(nil) }
            NSMenu.popUpContextMenu(statusMenu, with: event, for: sender)
            return
        }
        popoverAnchorButton = sender
        togglePopover(anchorButton: sender)
    }

    @objc func quitApp() {
        NSApp.terminate(nil)
    }

    @objc func togglePopover() {
        guard let b = statusItem.button else { return }
        popoverAnchorButton = b
        togglePopover(anchorButton: b)
    }

    private func togglePopover(anchorButton b: NSStatusBarButton) {
        if popover.isShown {
            popover.performClose(nil)
        } else {
            store.refresh(prewarmQuotaDetail: true)
            updatePanelLayout(for: b)
            popover.contentSize = panelLayout.contentSize
            popover.show(relativeTo: b.bounds, of: b, preferredEdge: .minY)
            popover.contentViewController?.view.window?.makeKey()
        }
    }

    /// 换到宽度不同的页面（issue #105）：卡片不超过两张时首页是窄版，进设置、额度曲线
    /// 要更宽，固定画布会把内容裁掉。按新页面重新量，再像打开时一样挂到菜单栏按钮下显示。
    ///
    /// 只有 PanelLayoutContext 判断宽度真的变了才会走到这里；切页签、刷新数据、宽版用户
    /// 换页都不经过这里，画布照旧固定，不会重新挑选屏幕和锚点（issue #97）。
    private func refitPanelForPage() {
        guard popover.isShown, let button = popoverAnchorButton ?? statusItem.button else { return }
        updatePanelLayout(for: button)
        popover.contentSize = panelLayout.contentSize
        popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
    }

    private func updatePanelLayout(for button: NSStatusBarButton) {
        panelLayout.update(
            fitting: measuredPanelSize(),
            anchorVisibleFrame: button.window?.screen?.visibleFrame,
            fallbackVisibleFrame: NSScreen.screens.first?.visibleFrame
        )
    }

    /// 量一次面板内容的自然尺寸。
    ///
    /// 用一个一次性的 host 渲染 `scrollable: false` 的同一个视图——那个分支不套
    /// 滚动视图、也不把自己钉到 layout 的尺寸上，所以报出来的就是内容本身要多大。
    /// 直接问正在显示的 host 是问不出来的：它被固定画布钉死，只会回答画布的尺寸。
    ///
    /// 只在打开之前调用，开着的时候绝不重量——见 `PanelPlacement.contentSize`。
    private func measuredPanelSize() -> CGSize {
        // 按面板当前停留的页面量：关掉时停在设置页，重开时也得按设置页的宽度来（issue #105）。
        let previous = PanelView.initialMode
        PanelView.initialMode = PanelView.PanelMode(rawValue: panelLayout.page) ?? .cards
        defer { PanelView.initialMode = previous }
        let probe = NSHostingController(
            rootView: PanelView(store: store, layout: panelLayout, scrollable: false))
        probe.view.layoutSubtreeIfNeeded()
        let size = probe.sizeThatFits(in: CGSize(width: CGFloat.greatestFiniteMagnitude,
                                                 height: CGFloat.greatestFiniteMagnitude))
        return size.width > 0 && size.height > 0 ? size : .zero
    }

    func popoverDidShow(_ notification: Notification) {
        store.popoverVisible = true
    }

    func popoverDidClose(_ notification: Notification) {
        store.popoverVisible = false
    }
}

// 离屏截图模式:Tokei --shot /path/out.png
// 加 --usage /path/usage.json 时直接渲染这份数据，不跑采集器——用来看过期、空态这类
// 平时不好凑出来的状态。
enum Shot {
    static func run(path: String) {
        _ = NSApplication.shared
        var usage: Usage?
        if let idx = CommandLine.arguments.firstIndex(of: "--usage"),
           CommandLine.arguments.count > idx + 1 {
            let url = URL(fileURLWithPath: CommandLine.arguments[idx + 1])
            do {
                usage = try JSONDecoder().decode(Usage.self, from: Data(contentsOf: url))
            } catch {
                fputs("Tokei --usage: \(error)\n", stderr)
            }
        } else {
            let sem = DispatchSemaphore(value: 0)
            DispatchQueue.global().async { usage = DataLoader.loadSync(); sem.signal() }
            sem.wait()
        }
        MainActor.assumeIsolated {
            let store = Store()
            store.usage = usage
            store.lastUpdated = L("预览")
            let content = PanelView(store: store, scrollable: false)
                .background(Color(red: 0.22, green: 0.23, blue: 0.26))
            let renderer = ImageRenderer(content: content)
            renderer.scale = 2
            if let cg = renderer.cgImage {
                let rep = NSBitmapImageRep(cgImage: cg)
                if let png = rep.representation(using: .png, properties: [:]) {
                    try? png.write(to: URL(fileURLWithPath: path))
                }
            }
        }
        exit(0)
    }
}

// 品牌 Logo(用于 app icon / 通知图标):珊瑚渐变 squircle + 白色知度符号。
struct LogoView: View {
    var body: some View {
        ZStack {
            ZStack {
                RoundedRectangle(cornerRadius: 185, style: .continuous)
                    .fill(LinearGradient(colors: [
                        Color(red: 0.97, green: 0.64, blue: 0.50),
                        Color(red: 0.90, green: 0.46, blue: 0.37),
                        Color(red: 0.82, green: 0.38, blue: 0.33)],
                        startPoint: .top, endPoint: .bottom))
                RoundedRectangle(cornerRadius: 185, style: .continuous)
                    .fill(LinearGradient(colors: [.white.opacity(0.28), .clear],
                        startPoint: .top, endPoint: .center))
                Image(systemName: "timer")
                    .font(.system(size: 440, weight: .semibold))
                    .foregroundStyle(.white)
                    .shadow(color: .black.opacity(0.20), radius: 22, y: 10)
            }
            .frame(width: 824, height: 824)
            .shadow(color: .black.opacity(0.28), radius: 34, y: 20)
        }
        .frame(width: 1024, height: 1024)
    }
}

enum Icon {
    static func run(path: String) {
        _ = NSApplication.shared
        MainActor.assumeIsolated {
            let r = ImageRenderer(content: LogoView())
            r.scale = 1
            if let cg = r.cgImage {
                let rep = NSBitmapImageRep(cgImage: cg)
                if let png = rep.representation(using: .png, properties: [:]) {
                    try? png.write(to: URL(fileURLWithPath: path))
                }
            }
        }
        exit(0)
    }
}

if GrokBotQuotaBridge.runIfRequested() {
    exit(0)
}

if ProviderCredentialStore.runIfRequested() {
    exit(0)
}

if LoginItemCommandLine.runIfRequested() {
    exit(0)
}

if let idx = CommandLine.arguments.firstIndex(of: "--make-icon") {
    let out = CommandLine.arguments.count > idx + 1
        ? CommandLine.arguments[idx + 1] : "/tmp/tokei_icon.png"
    Icon.run(path: out)
}

if let idx = CommandLine.arguments.firstIndex(of: "--lang"),
   CommandLine.arguments.count > idx + 1 {
    // 离屏截图检查各语言排版用：Tokei --lang en --shot /tmp/en.png
    L10n.forcedLanguage = AppLanguage(rawValue: CommandLine.arguments[idx + 1])
}

if let idx = CommandLine.arguments.firstIndex(of: "--mode"),
   CommandLine.arguments.count > idx + 1 {
    let modes: [String: PanelView.PanelMode] = [
        "cards": .cards, "settings": .settings, "dashboard": .dashboard,
        "quota": .quotaHistory, "projects": .projects,
    ]
    PanelView.initialMode = modes[CommandLine.arguments[idx + 1]] ?? .cards
}

if CommandLine.arguments.contains("--expand-models") {
    PanelView.expandModelsForShot = true
}

if let idx = CommandLine.arguments.firstIndex(of: "--shot") {
    let out = CommandLine.arguments.count > idx + 1
        ? CommandLine.arguments[idx + 1] : "/tmp/tokei_shot.png"
    Shot.run(path: out)
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
