import AppKit
import SwiftUI
import IOKit

// 久坐提醒:基于系统空闲(HIDIdleTime)判断"是否离开电脑"。
// 连续用机(无长空闲)达设定时长 → 弹自绘浮窗提醒起身;离开后自动清零。
// 用自绘 HUD 而非系统通知:ad-hoc 签名的 app 通知常被系统拒,HUD 不挑签名、必弹。
// 注:测的是"连续用机",非真实坐姿——看视频/开会不操作会被当作离开。
final class SitReminder: ObservableObject {
    private var timer: Timer?
    private var workStart: Date?
    private let idleAwayThreshold: Double = 300   // 空闲 ≥5 分钟 = 离开,计时清零

    var enabled: Bool { UserDefaults.standard.bool(forKey: "sitReminderOn") }
    var intervalMin: Int {
        let v = UserDefaults.standard.integer(forKey: "sitReminderInterval")
        return v == 0 ? 90 : v
    }

    func updateRunning() { enabled ? start() : stop() }

    func start() {
        stop()
        workStart = Date()
        timer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in self?.tick() }
    }

    func stop() {
        timer?.invalidate(); timer = nil
        workStart = nil
    }

    private func tick() {
        let idle = Self.idleSeconds()
        if idle >= idleAwayThreshold {           // 离开了 → 清零
            workStart = nil
        } else {
            if workStart == nil {
                workStart = Date()
            } else if let ws = workStart, Date().timeIntervalSince(ws) >= Double(intervalMin) * 60 {
                ping(L10n.f("s244", intervalMin))
                workStart = Date()
            }
        }
    }

    func testPing() { ping(L10n.t("s429")) }

    private static let tipCount = 6

    private func ping(_ body: String) {
        DispatchQueue.main.async {
            NSSound(named: "Blow")?.play()
            let i = Int.random(in: 0..<Self.tipCount)
            if let url = Bundle.main.url(forResource: "tip_\(i)", withExtension: "mp3", subdirectory: "sit") {
                NSSound(contentsOf: url, byReference: true)?.play()
            }
            ReminderHUD.show(title: L10n.t("s099"), body: body)
        }
    }

    // 系统空闲秒数:读 IOHIDSystem 的 HIDIdleTime(纳秒)。
    static func idleSeconds() -> Double {
        var iter: io_iterator_t = 0
        guard IOServiceGetMatchingServices(kIOMainPortDefault,
                                           IOServiceMatching("IOHIDSystem"), &iter) == KERN_SUCCESS else { return 0 }
        defer { IOObjectRelease(iter) }
        let entry = IOIteratorNext(iter)
        guard entry != 0 else { return 0 }
        defer { IOObjectRelease(entry) }
        var props: Unmanaged<CFMutableDictionary>?
        guard IORegistryEntryCreateCFProperties(entry, &props, kCFAllocatorDefault, 0) == KERN_SUCCESS,
              let dict = props?.takeRetainedValue() as? [String: Any],
              let ns = dict["HIDIdleTime"] as? UInt64 else { return 0 }
        return Double(ns) / 1_000_000_000.0
    }
}

// 屏幕右上角浮窗提醒(无边框 NSPanel + SwiftUI),4.5 秒后自动淡出。
enum ReminderHUD {
    private static var panel: NSPanel?

    static func show(title: String, body: String) {
        panel?.close()
        let w: CGFloat = 320, h: CGFloat = 80
        let host = NSHostingView(rootView: ReminderHUDView(title: title, message: body))
        host.frame = NSRect(x: 0, y: 0, width: w, height: h)
        let p = NSPanel(contentRect: host.frame,
                        styleMask: [.borderless, .nonactivatingPanel],
                        backing: .buffered, defer: false)
        p.isOpaque = false
        p.backgroundColor = .clear
        p.hasShadow = true
        p.level = .statusBar
        p.contentView = host
        if let screen = NSScreen.main {
            let vf = screen.visibleFrame
            p.setFrameOrigin(NSPoint(x: vf.maxX - w - 16, y: vf.maxY - h - 16))
        }
        p.alphaValue = 0
        p.orderFrontRegardless()
        panel = p
        NSAnimationContext.runAnimationGroup { ctx in
            ctx.duration = 0.25
            p.animator().alphaValue = 1
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 4.5) {
            NSAnimationContext.runAnimationGroup({ ctx in
                ctx.duration = 0.4
                p.animator().alphaValue = 0
            }, completionHandler: {
                p.close()
                if panel === p { panel = nil }
            })
        }
    }
}

struct ReminderHUDView: View {
    var title: String
    var message: String
    var body: some View {
        HStack(spacing: 11) {
            ZStack {
                RoundedRectangle(cornerRadius: 11, style: .continuous)
                    .fill(LinearGradient(colors: [Theme.claude, Theme.claude.opacity(0.7)],
                                         startPoint: .topLeading, endPoint: .bottomTrailing))
                Image(systemName: "timer").font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(.white)
            }
            .frame(width: 44, height: 44)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.system(size: 13, weight: .bold)).foregroundStyle(Theme.tPrimary)
                Text(message).font(.system(size: 11)).foregroundStyle(Theme.tSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
        .padding(12)
        .frame(width: 320, height: 80, alignment: .leading)
        .background(VisualEffect())
        .background(Theme.bg)
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous)
            .strokeBorder(Theme.claude.opacity(0.3), lineWidth: 0.75))
        .environment(\.colorScheme, .dark)
    }
}
