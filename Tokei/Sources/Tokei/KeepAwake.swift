import SwiftUI
import AppKit
import IOKit.ps
import IOKit.pwr_mgt

// 防休眠:macOS 原生 ProcessInfo.beginActivity 电源断言,不起子进程。
// 保持亮屏 = 防关屏+防系统睡眠;允许关屏 = 仅防系统空闲睡眠。
final class KeepAwake: ObservableObject {
    @Published var active = false
    @Published var allowDisplaySleep = false   // false=保持亮屏  true=允许关屏
    @Published var endsAt: Date? = nil

    private var displayID: IOPMAssertionID = 0
    private var systemID: IOPMAssertionID = 0
    private var timer: Timer?
    private var batteryTimer: Timer?

    private static let hm: DateFormatter = {
        let f = DateFormatter(); f.dateFormat = "HH:mm"; return f
    }()

    var lowBatteryGuard: Bool {
        get { UserDefaults.standard.object(forKey: "keepAwakeLowBattery") as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: "keepAwakeLowBattery"); objectWillChange.send() }
    }

    var statusLabel: String {
        guard active else { return "" }
        guard let e = endsAt else { return "∞" }
        return Self.hm.string(from: e)
    }

    func toggle() { active ? stop() : start(minutes: nil) }

    func start(minutes: Int?) {
        clear()
        let name = L10n.t("s044") as CFString
        let level = IOPMAssertionLevel(kIOPMAssertionLevelOn)
        // 保持亮屏 = 防关屏 + 防系统睡眠;允许关屏 = 仅防系统睡眠
        if !allowDisplaySleep {
            IOPMAssertionCreateWithName(kIOPMAssertionTypePreventUserIdleDisplaySleep as CFString,
                                        level, name, &displayID)
        }
        IOPMAssertionCreateWithName(kIOPMAssertionTypePreventUserIdleSystemSleep as CFString,
                                    level, name, &systemID)
        active = true
        if let m = minutes, m > 0 {
            endsAt = Date().addingTimeInterval(Double(m) * 60)
            timer = Timer.scheduledTimer(withTimeInterval: Double(m) * 60, repeats: false) { [weak self] _ in
                self?.stop()
            }
        } else {
            endsAt = nil
        }
        if lowBatteryGuard {
            batteryTimer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in
                self?.checkBattery()
            }
        }
        notifyMenu()
    }

    func stop() {
        clear()
        active = false
        endsAt = nil
        notifyMenu()
    }

    // 切换模式:运行中则用新选项重建断言,保留剩余时长。
    func setMode(allowDisplaySleep: Bool) {
        self.allowDisplaySleep = allowDisplaySleep
        if active {
            let mins = endsAt.map { max(1, Int($0.timeIntervalSinceNow / 60)) }
            start(minutes: mins)
        }
    }

    private func clear() {
        if displayID != 0 { IOPMAssertionRelease(displayID); displayID = 0 }
        if systemID != 0 { IOPMAssertionRelease(systemID); systemID = 0 }
        timer?.invalidate(); timer = nil
        batteryTimer?.invalidate(); batteryTimer = nil
    }

    private func checkBattery() {
        guard lowBatteryGuard, let st = Self.batteryState() else { return }
        if !st.charging && st.pct <= 20 { stop() }
    }

    private func notifyMenu() {
        (NSApp.delegate as? AppDelegate)?.updateStatusTitle()
    }

    static func batteryState() -> (pct: Int, charging: Bool)? {
        guard let snap = IOPSCopyPowerSourcesInfo()?.takeRetainedValue(),
              let list = IOPSCopyPowerSourcesList(snap)?.takeRetainedValue() as? [CFTypeRef] else { return nil }
        for ps in list {
            guard let d = IOPSGetPowerSourceDescription(snap, ps)?.takeUnretainedValue() as? [String: Any]
            else { continue }
            let cur = d[kIOPSCurrentCapacityKey] as? Int ?? 0
            let mx = d[kIOPSMaxCapacityKey] as? Int ?? 100
            let state = d[kIOPSPowerSourceStateKey] as? String ?? ""
            return (mx > 0 ? cur * 100 / mx : cur, state == kIOPSACPowerValue)
        }
        return nil
    }
}

// footer 咖啡按钮:点击一键开关,展开选时长 / 模式 / 低电保护。
struct KeepAwakeMenu: View {
    @ObservedObject var ka: KeepAwake
    var body: some View {
        Button {
            ka.toggle()
        } label: {
            HStack(spacing: 4) {
                Image(systemName: ka.active ? "cup.and.saucer.fill" : "cup.and.saucer")
                    .font(.system(size: Theme.fontSize(10), weight: .semibold))
                Text(ka.active ? ka.statusLabel : L10n.t("s532"))
                    .font(.system(size: Theme.fontSize(11), weight: .medium))
            }
            .foregroundStyle(ka.active ? AnyShapeStyle(Theme.claude) : AnyShapeStyle(.secondary))
            .padding(.horizontal, 9).padding(.vertical, 4)
            .background(RoundedRectangle(cornerRadius: 7, style: .continuous)
                .fill(ka.active ? Theme.claude.opacity(0.14) : Color.clear))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help(L10n.t("s232"))
        .contextMenu {
            Button { ka.start(minutes: nil) } label: { Label(L10n.t("s337"), systemImage: "infinity") }
            Button { ka.start(minutes: 15) }  label: { Text(L10n.t("s006")) }
            Button { ka.start(minutes: 30) }  label: { Text(L10n.t("s008")) }
            Button { ka.start(minutes: 60) }  label: { Text(L10n.t("span_1h")) }
            Button { ka.start(minutes: 120) } label: { Text(L10n.t("s007")) }
            Divider()
            Picker(L10n.t("s414"), selection: Binding(
                get: { ka.allowDisplaySleep },
                set: { ka.setMode(allowDisplaySleep: $0) })) {
                Text(L10n.t("s109")).tag(false)
                Text(L10n.t("s112")).tag(true)
            }
            Toggle(L10n.t("s105"), isOn: Binding(
                get: { ka.lowBatteryGuard }, set: { ka.lowBatteryGuard = $0 }))
            if ka.active {
                Divider()
                Button(role: .destructive) { ka.stop() } label: {
                    Label(L10n.t("s122"), systemImage: "xmark.circle")
                }
            }
        }
    }
}
