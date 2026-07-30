import AppKit
import SwiftUI
import Combine

final class Store: ObservableObject {
    @Published var usage: Usage?
    @Published var localUsage: Usage?
    @Published var allDevicesUsage: Usage?
    @Published var lastUpdated: String = "加载中…"
    @Published var loadError: String?
    @Published var peers: [PeerDevice] = []
    @Published var syncing = false
    @Published var syncStatus = ""
    @Published var syncSucceeded: Bool?
    @Published var syncDetail = ""
    @Published var syncFailStreak = 0
    @Published var peerLoadIssues: [PeerLoadIssue] = []

    let syncManager = SyncManager()
    let quotaHistory = QuotaHistoryStore.shared
    let keepAwake = KeepAwake()
    let sitReminder = SitReminder()
    var autoSyncTimer: Timer?
    private var autoSyncStartupWorkItem: DispatchWorkItem?

    @AppStorage("showAllDevices") var showAllDevices = true
    @AppStorage("syncEnabled") var syncEnabled = false

    private var retryCount = 0
    private var refreshInFlight = false
    private var refreshPending = false
    private var dashboardPrewarmStarted = false

    func applyDisplayMode(updateStatusTitle: Bool = true) {
        usage = (syncEnabled && showAllDevices) ? (allDevicesUsage ?? localUsage) : localUsage
        if updateStatusTitle {
            (NSApp.delegate as? AppDelegate)?.updateStatusTitle()
        }
    }

    func refresh() {
        if refreshInFlight {
            refreshPending = true
            return
        }
        refreshInFlight = true
        performRefresh()
    }

    private func performRefresh() {
        DataLoader.load { [weak self] u in
            guard let self = self else { return }
            guard let local = u else {
                let hadPendingRefresh = self.refreshPending
                if self.usage == nil && self.retryCount < 3 {
                    self.retryCount += 1
                    self.lastUpdated = "加载中…(\(self.retryCount))"
                    if !hadPendingRefresh {
                        DispatchQueue.main.asyncAfter(deadline: .now() + 3) { self.refresh() }
                    }
                } else {
                    self.loadError = "读取用量失败"
                    self.lastUpdated = "加载失败"
                }
                (NSApp.delegate as? AppDelegate)?.updateStatusTitle()
                self.finishRefresh()
                return
            }
            self.retryCount = 0
            self.loadError = nil
            self.recordQuotaHistory(local)
            self.localUsage = local
            var allDevices = local
            if self.syncEnabled {
                let p: [PeerDevice]
                if self.syncing {
                    p = self.peers
                } else {
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
            self.lastUpdated = "更新 " + f.string(from: Date())
            (NSApp.delegate as? AppDelegate)?.updateStatusTitle()
            if !self.refreshPending && !self.dashboardPrewarmStarted {
                self.dashboardPrewarmStarted = true
                DashboardRepository.shared.load(.all, force: true)
            }
            self.finishRefresh()
        }
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
            guard model.name != "合成" else { return }
            totals[model.name, default: 0] += model.in + model.out + model.cr + model.cw
        }
        let codexModels = codexRange.models.reduce(into: [String: Int]()) { totals, model in
            totals[model.name, default: 0] +=
                model.in + model.out + model.cr + model.cw + model.reason
        }
        quotaHistory.record(QuotaCapture(
            claudeFiveHourRemaining: usage.claude.q5_stale == true
                ? nil : usage.claude.q5.map { 100 - $0 },
            claudeWeekRemaining: usage.claude.q7_stale == true
                ? nil : usage.claude.q7.map { 100 - $0 },
            claudeFableWeekRemaining: usage.claude.qf_stale == true
                ? nil : usage.claude.qf.map { 100 - $0 },
            codexWeekRemaining: usage.codex.pw.map { 100 - $0 },
            claudeModelTotals: claudeModels,
            codexModelTotals: codexModels
        ))
    }

    func doSync() {
        guard syncEnabled, !syncing else { return }
        guard let cfg = syncManager.config else {
            syncStatus = "同步配置不可用"
            syncSucceeded = false
            syncDetail = "请先完成多设备同步配置"
            return
        }
        syncing = true
        syncStatus = "正在同步"
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
                self.syncStatus = "已同步 " + formatter.string(from: Date())
                self.refresh()
            } else if result.code == .busy {
                self.syncSucceeded = nil
                self.syncStatus = "同步任务已在运行"
            } else {
                self.syncSucceeded = false
                self.syncFailStreak += 1
                self.syncStatus = self.syncFailStreak > 1
                    ? "同步失败（连续 \(self.syncFailStreak) 次）"
                    : "同步失败"
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

final class AppDelegate: NSObject, NSApplicationDelegate {
    let store = Store()
    var statusItem: NSStatusItem!
    var popover = NSPopover()
    lazy var statusMenu: NSMenu = {
        let menu = NSMenu()
        let quitItem = NSMenuItem(title: "退出", action: #selector(quitApp), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)
        return menu
    }()
    var timer: Timer?
    var globalMouseMonitor: Any?

    // 菜单栏额度颜色(与面板 Theme.claude/codex/grok 一致)。
    static let claudeColor = NSColor(red: 0.92, green: 0.52, blue: 0.40, alpha: 1)
    static let codexColor  = NSColor(red: 0.42, green: 0.68, blue: 0.98, alpha: 1)
    static let grokColor   = NSColor(red: 0.65, green: 0.68, blue: 0.75, alpha: 1)

    func applicationDidFinishLaunching(_ note: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let b = statusItem.button {
            b.action = #selector(handleStatusItemClick(_:))
            b.target = self
            b.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }
        updateStatusTitle()

        let host = NSHostingController(rootView: PanelView(store: store))
        host.sizingOptions = .preferredContentSize
        popover.contentViewController = host
        popover.behavior = .applicationDefined
        // The panel can be nearly screen-height and contains a full SwiftUI card tree.
        // NSPopover's native animation lays out that entire tree synchronously while
        // opening, which makes a menu-bar click feel delayed. Show it immediately;
        // lightweight in-panel transitions remain available where they add context.
        popover.animates = false

        // 启动时先把 Qoder IDE / Grok 实时额度开关落盘到 config.json,
        // 确保随后的 refresh() 触发的 Python 扫描能读到正确配置。
        PanelView.syncQoderIdeConfigOnLaunch()
        PanelView.syncGrokLiveQuotaConfigOnLaunch()
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
        store.refresh()
        store.sitReminder.updateRunning()
        Updater.shared.checkForUpdate()
        autoFetchPricing()
        timer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in
            self?.store.refresh()
        }
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
            // 菜单栏额度来源与「显示卡片」独立：卡片可开，但状态栏只显示用户勾选的来源。
            if MenuBarQuotaSource.claude.isEnabled,
               u.claude.q5_stale != true,
               let q5 = u.claude.q5 {
                let remaining = 100 - q5
                metrics.append(.init(kind: .claude, value: String(format: "%.0f", remaining),
                                     remaining: remaining))
            }
            if MenuBarQuotaSource.codex.isEnabled,
               let quota = u.codex.pw {
                let remaining = 100 - quota
                metrics.append(.init(kind: .codex, value: String(format: "%.0f", remaining),
                                     remaining: remaining))
            }
            if MenuBarQuotaSource.grok.isEnabled,
               u.grok.stale != true,
               let pct = u.grok.pct {
                let remaining = 100 - pct
                metrics.append(.init(kind: .grok, value: String(format: "%.0f", remaining),
                                     remaining: remaining))
            }
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
                    let showO = ud.object(forKey: "showOpenCode") as? Bool ?? true
                    let showQC = ud.object(forKey: "showQwenCode") as? Bool ?? true
                    let showQ = ud.object(forKey: "showQoderIde") as? Bool ?? false
                    let showZ = ud.object(forKey: "showZcode") as? Bool ?? true
                    let showM = ud.object(forKey: "showMimoCode") as? Bool ?? true
                    var total = 0
                    if showC { let r = u.claude.ranges.get(.today); total += Int(r.in + r.out + r.cr + r.cw) }
                    if showX { let r = u.codex.ranges.get(.today); total += Int(r.in + r.out + r.cached) }
                    if showP { let r = u.pi.ranges.get(.today); total += Int(r.in + r.out + r.cr + r.cw + r.reason) }
                    if showW { let r = u.workbuddy.ranges.get(.today); total += Int(r.in + r.out + r.cr + r.cw) }
                    if showO { let r = u.opencode.ranges.get(.today); total += Int(r.in + r.out + r.cr + r.cw + r.reason) }
                    if showQC { let r = u.qwencode.ranges.get(.today); total += Int(r.in + r.out + r.cr + r.reason) }
                    if showQ { let r = u.qoder.ranges.get(.today); total += Int(r.in + r.out + r.cached) }
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
            let name: String
            switch metric.kind {
            case .claude: name = "Claude"
            case .codex: name = "Codex"
            case .grok: name = "Grok"
            case .total: name = "今日"
            }
            if metric.remaining != nil {
                return "\(name) 剩余 \(metric.value)%"
            }
            return "\(name) \(metric.value)"
        }
        if store.keepAwake.active {
            summaryParts.insert("保持唤醒已开启", at: 0)
        }
        if store.syncFailStreak >= 3 {
            summaryParts.insert("多设备同步已连续失败 \(store.syncFailStreak) 次，请打开设置查看", at: 0)
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
        togglePopover()
    }

    @objc func quitApp() {
        NSApp.terminate(nil)
    }

    @objc func togglePopover() {
        guard let b = statusItem.button else { return }
        if popover.isShown {
            popover.performClose(nil)
        } else {
            store.refresh()
            popover.show(relativeTo: b.bounds, of: b, preferredEdge: .minY)
            popover.contentViewController?.view.window?.makeKey()
        }
    }
}

// 离屏截图模式:Tokei --shot /path/out.png
enum Shot {
    static func run(path: String) {
        _ = NSApplication.shared
        var usage: Usage?
        let sem = DispatchSemaphore(value: 0)
        DispatchQueue.global().async { usage = DataLoader.loadSync(); sem.signal() }
        sem.wait()
        MainActor.assumeIsolated {
            let store = Store()
            store.usage = usage
            store.lastUpdated = "预览"
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

if LoginItemCommandLine.runIfRequested() {
    exit(0)
}

if let idx = CommandLine.arguments.firstIndex(of: "--make-icon") {
    let out = CommandLine.arguments.count > idx + 1
        ? CommandLine.arguments[idx + 1] : "/tmp/tokei_icon.png"
    Icon.run(path: out)
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
