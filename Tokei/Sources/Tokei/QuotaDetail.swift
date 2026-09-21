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

/// 一个周额度周期 = 两次「余量 100%」之间。token 已合并所有设备。
struct QuotaCycle: Codable, Identifiable {
    var tool: String
    var start: Int
    var end: Int
    var used_pct: Double?
    var tokens: Int
    var devices: [String: Int]
    var approx: Bool
    var current: Bool

    var id: String { "\(tool)-\(start)" }

    /// 重锚会把周期截短,所以长度不一定是 7 天 —— 照实标出来,别当成整周比较。
    var durationDays: Double { Double(end - start) / 86400 }

    /// 一个满额度大约值多少 token —— 按当前进度外推。太早期外推没意义。
    var projectedTotal: Int? {
        guard let used = used_pct, used >= 3, tokens > 0 else { return nil }
        return Int(Double(tokens) / used * 100)
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
}

final class QuotaDetailRepository: ObservableObject {
    static let shared = QuotaDetailRepository()

    @Published private(set) var payload: QuotaDetailPayload?
    @Published private(set) var refreshing = false

    private let fileURL: URL
    private var loadedAt: Date?
    private var forcedReloadPending = false
    private let freshness: TimeInterval = 30

    init(fileURL: URL = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".tokei/quota_detail.json")) {
        self.fileURL = fileURL
        // 脚本要跑 1~3 秒,先把上次的结果摆出来,别让人对着空面板等。
        payload = (try? Data(contentsOf: fileURL))
            .flatMap { try? JSONDecoder().decode(QuotaDetailPayload.self, from: $0) }
    }

    func load(force: Bool = false) {
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
