import Combine
import Foundation

/// 一天的 token 消耗(来自账本,权威;旧 session 被 CLI 清理也不缩水)。
struct QuotaDailyPoint: Codable, Identifiable {
    var d: String
    var c: Int
    var x: Int
    var g: Int

    var id: String { d }
    var total: Int { c + x + g }
}

/// 一个额度周期 = 两次「余量 100%」之间。token 已合并所有设备。
struct QuotaCycle: Codable, Identifiable {
    var tool: String
    var window: String?
    var start: Int
    var end: Int
    var used_pct: Double?
    var tokens: Int
    /// 按 API 价折算的美元成本；旧版脚本写的缓存没有这个字段。
    var cost: Double?
    var devices: [String: Int]
    var approx: Bool
    var current: Bool

    var id: String { "\(tool)-\(start)" }
    var isMonthly: Bool { window == "month" }

    /// 重锚会把周期截短,月窗口也有长短 —— 照实标出来。
    var durationDays: Double { Double(end - start) / 86400 }

    /// 一个满额度大约值多少 token —— 按当前进度外推。太早期外推没意义。
    var projectedTotal: Int? {
        guard let used = used_pct, used >= 3, tokens > 0 else { return nil }
        return Int(Double(tokens) / used * 100)
    }

    /// 照当前进度外推整个周期的成本，口径同 projectedTotal。
    var projectedCost: Double? {
        guard let used = used_pct, used.isFinite, used >= 3,
              let cost, cost.isFinite, cost > 0 else { return nil }
        let projected = cost / used * 100
        return projected.isFinite ? projected : nil
    }

    var costLabel: String? {
        guard let cost, cost.isFinite, cost >= 0 else { return nil }
        return String(format: "$%.2f", cost)
    }

    var deviceBreakdown: [(name: String, tokens: Int)] {
        devices.filter { $0.value > 0 }
            .sorted { $0.value > $1.value }
            .map { (name: $0.key, tokens: $0.value) }
    }
}

struct QuotaDetailPayload: Codable {
    var daily: [QuotaDailyPoint]
    var cycles: [QuotaCycle]
    var devices: [String]
    var missing: [String]
    var now: Int

    /// 与采集器的 120 秒重置抖动容差一致；过期周期仍然不能配到新读数。
    func currentCycle(for tool: String, endingAt reset: Int?,
                      at now: Int = Int(Date().timeIntervalSince1970)) -> QuotaCycle? {
        guard let reset, reset > now else { return nil }
        return cycles.first {
            $0.tool == tool && $0.current && $0.start <= now && $0.end > now &&
                abs(Double($0.end) - Double(reset)) <= 120
        }
    }
}

final class QuotaDetailRepository: ObservableObject {
    /// 离屏截图用的合成数据（`--quota-detail-json`）：只读，不跑脚本也不回写。
    static var fixtureURL: URL?
    static var fixtureMode = false
    static let shared: QuotaDetailRepository = {
        if fixtureMode {
            // 未提供周期 fixture 时显示空态，不能把本机缓存混入 --usage 截图。
            let emptyURL = FileManager.default.temporaryDirectory
                .appendingPathComponent("tokei-shot-\(UUID().uuidString)/quota_detail.json")
            return QuotaDetailRepository(fileURL: fixtureURL ?? emptyURL, readOnly: true)
        }
        return QuotaDetailRepository()
    }()

    @Published private(set) var payload: QuotaDetailPayload?
    @Published private(set) var refreshing = false

    private let fileURL: URL
    private let readOnly: Bool
    private var loadedAt: Date?
    private var forcedReloadPending = false
    private let freshness: TimeInterval = 30

    init(fileURL: URL = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".tokei/quota_detail.json"), readOnly: Bool = false) {
        self.fileURL = fileURL
        self.readOnly = readOnly
        // 脚本要跑 1~3 秒,先把上次的结果摆出来,别让人对着空面板等。
        payload = (try? Data(contentsOf: fileURL))
            .flatMap { try? JSONDecoder().decode(QuotaDetailPayload.self, from: $0) }
    }

    func load(force: Bool = false) {
        if readOnly { return }
        if !force, let loadedAt, Date().timeIntervalSince(loadedAt) < freshness {
            return
        }
        if refreshing {
            forcedReloadPending = forcedReloadPending || force
            return
        }
        refreshing = true

        DispatchQueue.global(qos: .utility).async {
            let result = DataLoader.runScriptRaw(args: ["--quota-detail"], timeout: 30)
            let data = Data(result.stdout.utf8)
            let decoded = result.exitCode == 0 && !result.timedOut
                ? try? JSONDecoder().decode(QuotaDetailPayload.self, from: data)
                : nil
            if decoded != nil {
                try? data.write(to: self.fileURL, options: .atomic)
            }
            DispatchQueue.main.async {
                self.refreshing = false
                if let decoded {
                    self.loadedAt = Date()
                    self.payload = decoded
                } else {
                    fputs("Tokei quota detail failed: exit=\(result.exitCode) "
                          + "timeout=\(result.timedOut)\n", stderr)
                }
                if self.forcedReloadPending {
                    self.forcedReloadPending = false
                    self.load(force: true)
                }
            }
        }
    }
}
