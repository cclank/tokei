import Foundation
import Darwin

struct SyncConfig: Codable {
    var device_id: String
    var sync_dir: String
    var auto_sync: Bool?
    var sync_interval: Int?     // minutes
}

struct SyncCommand {
    var executable: String
    var arguments: [String]
    var supervisorExecutable: String? = nil
    var supervisorArguments: [String] = []
    var transactionTimeout: TimeInterval = 240
}

enum GitSyncCode: String {
    case success
    case busy
    case invalidConfiguration
    case invalidRepository
    case foreignOperation
    case detachedHead
    case dirtyRepository
    case snapshotFailed
    case fetchFailed
    case commitFailed
    case rebaseFailed
    case recoveryFailed
    case pushFailed
    case timedOut
    case unknown
}

struct GitSyncResult {
    var code: GitSyncCode
    var output: String

    var succeeded: Bool { code == .success }
}

struct PeerDevice: Identifiable {
    var id: String { deviceId }
    var deviceId: String
    var lastSync: Date
    var usage: Usage
    var dashboard: PeerDashboardSnapshot?
    var rangeBounds: [String: RangeBoundary]
}

struct PeerDashboardSnapshot: Codable {
    var daily: [DailyCost] = []
    var wrapped: [String: WrappedData] = [:]
}

struct RangeBoundary: Codable, Equatable {
    var start: String?
    var end: String?
}

enum PeerLoadStage: String {
    case configuration = "配置"
    case read = "读取"
    case json = "JSON"
    case timestamp = "时间戳"
    case usage = "用量结构"
    case dashboard = "面板数据"
    case rangeBounds = "时间范围"
}

struct PeerLoadIssue: Identifiable {
    var id: String { "\(file)|\(stage.rawValue)|\(detail)" }
    var file: String
    var stage: PeerLoadStage
    var detail: String

    var summary: String { "\(file)：\(stage.rawValue)失败，\(detail)" }
}

struct PeerLoadReport {
    var peers: [PeerDevice]
    var issues: [PeerLoadIssue]
}

final class SyncManager {
    static let supportedSyncIntervals = [30, 60, 120]
    static let defaultSyncInterval = 30
    static let configPath = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent(".tokei/config.json")
    private static let configLockPath = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent(".tokei/config.lock")
    static let syncDir = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent(".tokei/sync").path

    var config: SyncConfig?

    init() { config = Self.loadConfig() }

    static func normalizedSyncInterval(_ value: Int?) -> Int {
        guard let value, supportedSyncIntervals.contains(value) else {
            return defaultSyncInterval
        }
        return value
    }

    static func resolvedSyncDir(_ cfg: SyncConfig) -> String {
        let raw = cfg.sync_dir.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !raw.isEmpty else { return Self.syncDir }
        return (raw as NSString).expandingTildeInPath
    }

    // MARK: - Config

    static func normalizedDeviceID(_ value: String) -> String {
        value.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    static func loadConfig() -> SyncConfig? {
        guard let data = try? Data(contentsOf: configPath) else { return nil }
        guard var cfg = try? JSONDecoder().decode(SyncConfig.self, from: data) else { return nil }
        cfg.device_id = normalizedDeviceID(cfg.device_id)
        return cfg
    }

    private static func withConfigLock<T>(_ body: () throws -> T) -> T? {
        let directory = configPath.deletingLastPathComponent()
        do {
            try FileManager.default.createDirectory(
                at: directory,
                withIntermediateDirectories: true
            )
        } catch {
            return nil
        }
        let descriptor = Darwin.open(
            configLockPath.path,
            O_CREAT | O_RDWR,
            mode_t(0o600)
        )
        guard descriptor >= 0 else { return nil }
        defer { Darwin.close(descriptor) }
        _ = Darwin.fchmod(descriptor, mode_t(0o600))
        guard Darwin.lockf(descriptor, F_LOCK, 0) == 0 else { return nil }
        defer { _ = Darwin.lockf(descriptor, F_ULOCK, 0) }
        return try? body()
    }

    private static func writeConfigDictionary(_ dictionary: [String: Any]) throws {
        let data = try JSONSerialization.data(
            withJSONObject: dictionary,
            options: [.prettyPrinted, .sortedKeys]
        )
        try data.write(to: configPath, options: .atomic)
        try? FileManager.default.setAttributes(
            [.posixPermissions: 0o600],
            ofItemAtPath: configPath.path
        )
    }

    @discardableResult
    func saveConfig(_ cfg: SyncConfig) -> Bool {
        var normalized = cfg
        normalized.device_id = Self.normalizedDeviceID(cfg.device_id)
        guard Self.validDeviceID(normalized.device_id) != nil else {
            return false
        }
        let memoryDeviceID = config.flatMap {
            Self.validDeviceID(Self.normalizedDeviceID($0.device_id))
        }
        let saved: SyncConfig? = Self.withConfigLock {
            // 锁内重读磁盘，保证多个 Tokei 进程无法覆盖已经绑定的合法设备标识。
            var dictionary: [String: Any] = [:]
            if let data = try? Data(contentsOf: Self.configPath),
               let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                dictionary = object
            }
            let diskDeviceID = (dictionary["device_id"] as? String).flatMap {
                Self.validDeviceID(Self.normalizedDeviceID($0))
            }
            if let stableDeviceID = diskDeviceID ?? memoryDeviceID,
               normalized.device_id != stableDeviceID {
                throw CocoaError(.fileWriteNoPermission)
            }
            dictionary["device_id"] = normalized.device_id
            dictionary["sync_dir"] = normalized.sync_dir
            if let value = normalized.auto_sync {
                dictionary["auto_sync"] = value
            } else {
                dictionary.removeValue(forKey: "auto_sync")
            }
            if let value = normalized.sync_interval {
                dictionary["sync_interval"] = value
            } else {
                dictionary.removeValue(forKey: "sync_interval")
            }
            try Self.writeConfigDictionary(dictionary)
            return normalized
        }
        guard let saved else { return false }
        config = saved
        return true
    }

    @discardableResult
    static func setQoderIdeEnabled(_ enabled: Bool) -> Bool {
        withConfigLock {
            var dictionary: [String: Any] = [:]
            if FileManager.default.fileExists(atPath: configPath.path) {
                let data = try Data(contentsOf: configPath)
                guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                    throw CocoaError(.fileReadCorruptFile)
                }
                dictionary = object
            }
            dictionary["qoder_ide_enabled"] = enabled
            try writeConfigDictionary(dictionary)
            return true
        } ?? false
    }

    /// Grok 实时额度：默认关闭，只写 config 字段，不改动同步相关配置。
    @discardableResult
    static func setGrokLiveQuotaEnabled(_ enabled: Bool) -> Bool {
        withConfigLock {
            var dictionary: [String: Any] = [:]
            if FileManager.default.fileExists(atPath: configPath.path) {
                let data = try Data(contentsOf: configPath)
                guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                    throw CocoaError(.fileReadCorruptFile)
                }
                dictionary = object
            }
            dictionary["grok_live_quota_enabled"] = enabled
            try writeConfigDictionary(dictionary)
            return true
        } ?? false
    }

    /// 千问办公额度：默认关闭，只允许 Python 采集器查询本机 QwenWork MCP 适配器。
    @discardableResult
    static func setQwenWorkQuotaEnabled(_ enabled: Bool) -> Bool {
        withConfigLock {
            var dictionary: [String: Any] = [:]
            if FileManager.default.fileExists(atPath: configPath.path) {
                let data = try Data(contentsOf: configPath)
                guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                    throw CocoaError(.fileReadCorruptFile)
                }
                dictionary = object
            }
            dictionary["qwenwork_quota_enabled"] = enabled
            try writeConfigDictionary(dictionary)
            return true
        } ?? false
    }

    private static let providerQuotaIDs: Set<String> = [
        "cursor", "zed", "sub2api", "zai", "antigravity",
    ]
    private static let providerSettingKeys: Set<String> = [
        "sub2api_base_url", "zai_region", "zai_usage_scope",
        "zai_organization", "zai_project",
    ]

    @discardableResult
    static func setProviderQuotaEnabled(_ provider: String, enabled: Bool) -> Bool {
        guard providerQuotaIDs.contains(provider) else { return false }
        return setConfigValue(enabled, forKey: "\(provider)_quota_enabled")
    }

    static func providerSetting(_ key: String) -> String? {
        guard providerSettingKeys.contains(key),
              let data = try? Data(contentsOf: configPath),
              let dictionary = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let value = dictionary[key] as? String else { return nil }
        let cleaned = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return cleaned.isEmpty ? nil : cleaned
    }

    @discardableResult
    static func setProviderSetting(_ value: String?, forKey key: String) -> Bool {
        guard providerSettingKeys.contains(key) else { return false }
        let cleaned = value?.trimmingCharacters(in: .whitespacesAndNewlines)
        let stored = (cleaned?.isEmpty == false) ? cleaned : nil
        return setConfigValue(stored, forKey: key)
    }

    private static func setConfigValue(_ value: Any?, forKey key: String) -> Bool {
        withConfigLock {
            var dictionary: [String: Any] = [:]
            if FileManager.default.fileExists(atPath: configPath.path) {
                let data = try Data(contentsOf: configPath)
                guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                    throw CocoaError(.fileReadCorruptFile)
                }
                dictionary = object
            }
            if let value {
                dictionary[key] = value
            } else {
                dictionary.removeValue(forKey: key)
            }
            try writeConfigDictionary(dictionary)
            return true
        } ?? false
    }

    // MARK: - Read peers

    func loadPeers() -> PeerLoadReport {
        guard let cfg = config else {
            return PeerLoadReport(
                peers: [],
                issues: [PeerLoadIssue(
                    file: Self.configPath.path,
                    stage: .configuration,
                    detail: "同步配置缺失或无法解析"
                )]
            )
        }
        let dir = Self.resolvedSyncDir(cfg)
        guard FileManager.default.fileExists(atPath: dir) else {
            return PeerLoadReport(
                peers: [],
                issues: [PeerLoadIssue(file: dir, stage: .read, detail: "同步目录不存在")]
            )
        }
        var peers: [PeerDevice] = []
        var issues: [PeerLoadIssue] = []
        let fm = FileManager.default
        let files: [String]
        do {
            files = try fm.contentsOfDirectory(atPath: dir).sorted()
        } catch {
            return PeerLoadReport(
                peers: [],
                issues: [PeerLoadIssue(file: dir, stage: .read, detail: error.localizedDescription)]
            )
        }
        for file in files where file.hasSuffix(".json") {
            let deviceId = String(file.dropLast(5)) // remove .json
            if deviceId.caseInsensitiveCompare(Self.normalizedDeviceID(cfg.device_id)) == .orderedSame {
                continue
            }
            let path = (dir as NSString).appendingPathComponent(file)
            let data: Data
            do {
                data = try Data(contentsOf: URL(fileURLWithPath: path))
            } catch {
                issues.append(PeerLoadIssue(file: file, stage: .read, detail: error.localizedDescription))
                continue
            }
            let raw: [String: Any]
            do {
                guard let value = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                    issues.append(PeerLoadIssue(file: file, stage: .json, detail: "顶层不是对象"))
                    continue
                }
                raw = value
            } catch {
                issues.append(PeerLoadIssue(file: file, stage: .json, detail: error.localizedDescription))
                continue
            }
            guard let ts = raw["_ts"] as? Int else {
                issues.append(PeerLoadIssue(file: file, stage: .timestamp, detail: "缺少 _ts"))
                continue
            }
            var cleaned = raw
            for key in cleaned.keys where key.hasPrefix("_") { cleaned.removeValue(forKey: key) }
            let usage: Usage
            do {
                let cleanData = try JSONSerialization.data(withJSONObject: cleaned)
                usage = try JSONDecoder().decode(Usage.self, from: cleanData)
            } catch {
                issues.append(PeerLoadIssue(file: file, stage: .usage, detail: error.localizedDescription))
                continue
            }
            var dashboard: PeerDashboardSnapshot?
            if let rawDashboard = raw["_dashboard"] {
                do {
                    guard JSONSerialization.isValidJSONObject(rawDashboard) else {
                        throw NSError(domain: "TokeiPeer", code: 1,
                                      userInfo: [NSLocalizedDescriptionKey: "不是有效 JSON 对象"])
                    }
                    let dashboardData = try JSONSerialization.data(withJSONObject: rawDashboard)
                    dashboard = try JSONDecoder().decode(PeerDashboardSnapshot.self, from: dashboardData)
                } catch {
                    issues.append(PeerLoadIssue(file: file, stage: .dashboard,
                                                detail: error.localizedDescription))
                }
            }
            var rangeBounds: [String: RangeBoundary] = [:]
            if let rawBounds = raw["_range_bounds"] {
                do {
                    guard JSONSerialization.isValidJSONObject(rawBounds) else {
                        throw NSError(domain: "TokeiPeer", code: 2,
                                      userInfo: [NSLocalizedDescriptionKey: "不是有效 JSON 对象"])
                    }
                    let boundsData = try JSONSerialization.data(withJSONObject: rawBounds)
                    rangeBounds = try JSONDecoder().decode([String: RangeBoundary].self, from: boundsData)
                } catch {
                    issues.append(PeerLoadIssue(file: file, stage: .rangeBounds,
                                                detail: error.localizedDescription))
                }
            }
            if rangeBounds.isEmpty {
                rangeBounds = Self.currentRangeBounds(now: Date(timeIntervalSince1970: TimeInterval(ts)))
                    .reduce(into: [String: RangeBoundary]()) { out, item in
                        out[item.key.rawValue] = item.value
                    }
            }
            peers.append(PeerDevice(
                deviceId: deviceId,
                lastSync: Date(timeIntervalSince1970: TimeInterval(ts)),
                usage: usage,
                dashboard: dashboard,
                rangeBounds: rangeBounds
            ))
        }
        return PeerLoadReport(peers: peers, issues: issues)
    }

    // MARK: - Merge

    static func merge(local: Usage, peers: [PeerDevice]) -> Usage {
        var u = local
        for peer in peers {
            let pairs = rangePairs(for: peer)
            mergeRanges(&u.claude.ranges, peer.usage.claude.ranges, pairs)
            mergeRanges(&u.codex.ranges, peer.usage.codex.ranges, pairs)
            mergeRanges(&u.gemini.ranges, peer.usage.gemini.ranges, pairs)
            mergeRanges(&u.grok.ranges, peer.usage.grok.ranges, pairs)
            u.grok.model = mergeModelName(u.grok.model, peer.usage.grok.model)
            mergeRanges(&u.qoderwork.ranges, peer.usage.qoderwork.ranges, pairs)
            mergeRanges(&u.qoder.ranges, peer.usage.qoder.ranges, pairs)
            mergeRanges(&u.hermes.ranges, peer.usage.hermes.ranges, pairs)
            mergeRanges(&u.zcode.ranges, peer.usage.zcode.ranges, pairs)
            mergeRanges(&u.mimocode.ranges, peer.usage.mimocode.ranges, pairs)
            mergeRanges(&u.openclaw.ranges, peer.usage.openclaw.ranges, pairs)
            mergeRanges(&u.pi.ranges, peer.usage.pi.ranges, pairs)
            mergeRanges(&u.prime_agent.ranges, peer.usage.prime_agent.ranges, pairs)
            mergeRanges(&u.workbuddy.ranges, peer.usage.workbuddy.ranges, pairs)
            mergeRanges(&u.deepseekHarness.ranges, peer.usage.deepseekHarness.ranges, pairs)
            mergeRanges(&u.opencode.ranges, peer.usage.opencode.ranges, pairs)
            mergeRanges(&u.qwencode.ranges, peer.usage.qwencode.ranges, pairs)
            mergeRanges(&u.kimicode.ranges, peer.usage.kimicode.ranges, pairs)
        }
        return u
    }

    private static func rangePairs(for peer: PeerDevice, now: Date = Date()) -> [(src: RangeKey, dst: RangeKey)] {
        let local = currentRangeBounds(now: now)
        var pairs: [(src: RangeKey, dst: RangeKey)] = []
        for src in RangeKey.allCases {
            guard let peerBoundary = peer.rangeBounds[src.rawValue] else { continue }
            if src == .all {
                pairs.append((.all, .all))
                continue
            }
            if let dst = RangeKey.allCases.first(where: { local[$0] == peerBoundary }) {
                pairs.append((src, dst))
            }
        }
        return pairs
    }

    static func currentRangeBounds(now: Date = Date()) -> [RangeKey: RangeBoundary] {
        let cal = Calendar.current
        let today = cal.startOfDay(for: now)
        let yesterday = cal.date(byAdding: .day, value: -1, to: today) ?? today
        let localWeek = weekStart(for: today, calendar: cal)
        let localLastWeek = cal.date(byAdding: .day, value: -7, to: localWeek) ?? localWeek
        let monthStart = cal.date(from: cal.dateComponents([.year, .month], from: today)) ?? today
        let nextMonth = cal.date(byAdding: DateComponents(month: 1), to: monthStart) ?? monthStart
        let yearStart = cal.date(from: cal.dateComponents([.year], from: today)) ?? today
        let nextYear = cal.date(byAdding: DateComponents(year: 1), to: yearStart) ?? yearStart

        return [
            .today: RangeBoundary(start: dayString(today), end: dayString(cal.date(byAdding: .day, value: 1, to: today) ?? today)),
            .yesterday: RangeBoundary(start: dayString(yesterday), end: dayString(today)),
            .week: RangeBoundary(start: dayString(localWeek), end: dayString(cal.date(byAdding: .day, value: 7, to: localWeek) ?? localWeek)),
            .lastWeek: RangeBoundary(start: dayString(localLastWeek), end: dayString(localWeek)),
            .month: RangeBoundary(start: dayString(monthStart), end: dayString(nextMonth)),
            .year: RangeBoundary(start: dayString(yearStart), end: dayString(nextYear)),
            .all: RangeBoundary(start: nil, end: nil),
        ]
    }

    private static func weekStart(for date: Date, calendar cal: Calendar) -> Date {
        let weekday = cal.component(.weekday, from: date)
        let daysFromMonday = (weekday + 5) % 7
        return cal.date(byAdding: .day, value: -daysFromMonday, to: date) ?? date
    }

    private static func dayString(_ date: Date) -> String {
        let fmt = DateFormatter()
        fmt.calendar = Calendar.current
        fmt.locale = Locale(identifier: "en_US_POSIX")
        fmt.dateFormat = "yyyy-MM-dd"
        return fmt.string(from: date)
    }

    private static func mergeRanges(_ dst: inout ClaudeRanges, _ src: ClaudeRanges, _ pairs: [(src: RangeKey, dst: RangeKey)]) {
        for pair in pairs {
            var d = dst.get(pair.dst), s = src.get(pair.src)
            d.in += s.in; d.out += s.out; d.cr += s.cr; d.cw += s.cw
            d.cost += s.cost; d.sessions += s.sessions
            d.hit = hitRate(cached: d.cr, input: d.in, cacheWrite: d.cw)
            mergeClaudeModels(&d.models, s.models)
            dst.set(pair.dst, d)
        }
    }

    private static func mergeRanges(_ dst: inout CodexRanges, _ src: CodexRanges, _ pairs: [(src: RangeKey, dst: RangeKey)]) {
        for pair in pairs {
            var d = dst.get(pair.dst), s = src.get(pair.src)
            d.in += s.in; d.out += s.out; d.cached += s.cached
            d.reason += s.reason; d.cost += s.cost; d.sessions += s.sessions
            d.hit = hitRate(cached: d.cached, input: d.in)
            mergeTokenModels(&d.models, s.models)
            dst.set(pair.dst, d)
        }
    }

    private static func mergeRanges(_ dst: inout GeminiRanges, _ src: GeminiRanges, _ pairs: [(src: RangeKey, dst: RangeKey)]) {
        for pair in pairs {
            var d = dst.get(pair.dst), s = src.get(pair.src)
            d.in += s.in; d.out += s.out; d.cached += s.cached
            d.thoughts += s.thoughts; d.cost += s.cost; d.sessions += s.sessions
            d.hit = hitRate(cached: d.cached, input: d.in)
            mergeGeminiModels(&d.models, s.models)
            dst.set(pair.dst, d)
        }
    }

    private static func mergeRanges(_ dst: inout GrokRanges, _ src: GrokRanges, _ pairs: [(src: RangeKey, dst: RangeKey)]) {
        for pair in pairs {
            var d = dst.get(pair.dst), s = src.get(pair.src)
            let originalLatencyWeight = max(d.turns ?? 0, d.sessions)
            let sourceLatencyWeight = max(s.turns ?? 0, s.sessions)
            let hadRealUsage = d.usage_available
            d.in += s.in; d.out += s.out; d.cr += s.cr; d.reason += s.reason
            d.cost += s.cost
            d.usage_available = d.usage_available || s.usage_available
            d.usage_calls += s.usage_calls; d.usage_sessions += s.usage_sessions
            if d.usage_available {
                d.tokens = d.in + d.out + d.cr + d.reason
            } else if !hadRealUsage {
                d.tokens += s.tokens
            }
            d.hit = hitRate(cached: d.cr, input: d.in)
            mergeTokenModels(&d.models, s.models)
            d.sessions += s.sessions
            d.turns = add(d.turns, s.turns)
            d.tools = add(d.tools, s.tools)
            d.duration = add(d.duration, s.duration)
            d.ctx_used = add(d.ctx_used, s.ctx_used)
            d.ctx_window = add(d.ctx_window, s.ctx_window)
            d.errors = add(d.errors, s.errors)
            d.cancellations = add(d.cancellations, s.cancellations)
            d.ttft = weightedAverage(d.ttft, originalLatencyWeight, s.ttft, sourceLatencyWeight)
            d.response = weightedAverage(d.response, originalLatencyWeight, s.response, sourceLatencyWeight)
            let ctxUsed = d.ctx_used ?? 0
            let ctxWindow = d.ctx_window ?? 0
            d.ctx = ctxWindow > 0 ? Double(ctxUsed) / Double(ctxWindow) * 100 : 0
            dst.set(pair.dst, d)
        }
    }

    private static func mergeRanges(_ dst: inout QoderRanges, _ src: QoderRanges, _ pairs: [(src: RangeKey, dst: RangeKey)]) {
        for pair in pairs {
            var d = dst.get(pair.dst), s = src.get(pair.src)
            let originalSessions = d.sessions
            d.in += s.in; d.out += s.out
            d.sessions += s.sessions
            d.calls += s.calls; d.sub_agents += s.sub_agents
            d.turns += s.turns; d.duration += s.duration
            d.ctx = weightedAverage(d.ctx, originalSessions, s.ctx, s.sessions)
            dst.set(pair.dst, d)
        }
    }

    private static func mergeRanges(_ dst: inout QoderIdeRanges, _ src: QoderIdeRanges, _ pairs: [(src: RangeKey, dst: RangeKey)]) {
        for pair in pairs {
            var d = dst.get(pair.dst), s = src.get(pair.src)
            let originalSessions = d.sessions
            d.in += s.in; d.out += s.out; d.cached += s.cached
            d.sessions += s.sessions
            d.sub_agents += s.sub_agents; d.calls += s.calls
            d.messages += s.messages; d.duration += s.duration
            d.ctx = weightedAverage(d.ctx, originalSessions, s.ctx, s.sessions)
            dst.set(pair.dst, d)
        }
    }

    private static func mergeRanges(_ dst: inout HermesRanges, _ src: HermesRanges, _ pairs: [(src: RangeKey, dst: RangeKey)]) {
        for pair in pairs {
            var d = dst.get(pair.dst), s = src.get(pair.src)
            d.in += s.in; d.out += s.out; d.cr += s.cr; d.cw += s.cw
            d.reason += s.reason; d.cost += s.cost; d.sessions += s.sessions
            d.hit = hitRate(cached: d.cr, input: d.in, cacheWrite: d.cw)
            mergeTokenModels(&d.models, s.models)
            dst.set(pair.dst, d)
        }
    }

    private static func mergeRanges(_ dst: inout OpenClawRanges, _ src: OpenClawRanges, _ pairs: [(src: RangeKey, dst: RangeKey)]) {
        for pair in pairs {
            var d = dst.get(pair.dst), s = src.get(pair.src)
            d.tasks += s.tasks; d.completed += s.completed; d.failed += s.failed
            d.in += s.in; d.out += s.out; d.cr += s.cr; d.cw += s.cw
            d.reason += s.reason; d.cost += s.cost; d.sessions += s.sessions
            d.hit = hitRate(cached: d.cr, input: d.in, cacheWrite: d.cw)
            mergeTokenModels(&d.models, s.models)
            dst.set(pair.dst, d)
        }
    }

    private static func mergeRanges(_ dst: inout TokenUsageRanges, _ src: TokenUsageRanges, _ pairs: [(src: RangeKey, dst: RangeKey)]) {
        for pair in pairs {
            var d = dst.get(pair.dst), s = src.get(pair.src)
            d.in += s.in; d.out += s.out; d.cr += s.cr; d.cw += s.cw
            d.reason += s.reason; d.cost += s.cost; d.sessions += s.sessions
            d.hit = hitRate(cached: d.cr, input: d.in, cacheWrite: d.cw)
            mergeTokenModels(&d.models, s.models)
            dst.set(pair.dst, d)
        }
    }

    private static func hitRate(cached: Int, input: Int, cacheWrite: Int = 0) -> Double {
        let denom = cached + input + cacheWrite
        return denom > 0 ? Double(cached) / Double(denom) * 100 : 0
    }

    private static func add(_ lhs: Int?, _ rhs: Int?) -> Int? {
        let sum = (lhs ?? 0) + (rhs ?? 0)
        return sum > 0 ? sum : 0
    }

    private static func weightedAverage(_ lhs: Int?, _ lhsWeight: Int, _ rhs: Int?, _ rhsWeight: Int) -> Int? {
        let totalWeight = lhsWeight + rhsWeight
        guard totalWeight > 0 else { return 0 }
        return (((lhs ?? 0) * lhsWeight) + ((rhs ?? 0) * rhsWeight)) / totalWeight
    }

    private static func weightedAverage(_ lhs: Double, _ lhsWeight: Int, _ rhs: Double, _ rhsWeight: Int) -> Double {
        let totalWeight = lhsWeight + rhsWeight
        guard totalWeight > 0 else { return 0 }
        return ((lhs * Double(lhsWeight)) + (rhs * Double(rhsWeight))) / Double(totalWeight)
    }

    private static func mergeClaudeModels(_ dst: inout [ClaudeModelStat], _ src: [ClaudeModelStat]) {
        for m in src {
            if let idx = dst.firstIndex(where: { $0.name == m.name }) {
                dst[idx].in += m.in
                dst[idx].out += m.out
                dst[idx].cr += m.cr
                dst[idx].cw += m.cw
                dst[idx].cost += m.cost
            } else {
                dst.append(m)
            }
        }
        dst.sort { $0.cost > $1.cost }
    }

    private static func mergeGeminiModels(_ dst: inout [GeminiModelStat], _ src: [GeminiModelStat]) {
        for m in src {
            if let idx = dst.firstIndex(where: { $0.name == m.name }) {
                dst[idx].in += m.in
                dst[idx].out += m.out
                dst[idx].cached += m.cached
                dst[idx].thoughts += m.thoughts
                dst[idx].cost += m.cost
            } else {
                dst.append(m)
            }
        }
        dst.sort { $0.cost > $1.cost }
    }

    private static func mergeTokenModels(_ dst: inout [TokenModelStat], _ src: [TokenModelStat]) {
        for m in src {
            let index: Int?
            if let modelId = m.modelId {
                index = dst.firstIndex { $0.modelId == modelId }
            } else {
                index = dst.firstIndex { $0.modelId == nil && $0.name == m.name }
            }
            if let idx = index {
                dst[idx].in += m.in
                dst[idx].out += m.out
                dst[idx].cr += m.cr
                dst[idx].cw += m.cw
                dst[idx].reason += m.reason
                dst[idx].cost += m.cost
                if dst[idx].name == "未知" && m.name != "未知" {
                    dst[idx].name = m.name
                }
            } else {
                dst.append(m)
            }
        }
        dst.sort { $0.cost > $1.cost }
    }

    private static func mergeModelName(_ lhs: String?, _ rhs: String?) -> String? {
        var names: [String] = []
        for value in [lhs, rhs] {
            guard let value else { continue }
            for part in value.split(separator: ",") {
                let name = part.trimmingCharacters(in: .whitespacesAndNewlines)
                if !name.isEmpty && !names.contains(name) {
                    names.append(name)
                }
            }
        }
        return names.isEmpty ? nil : names.joined(separator: ", ")
    }

    // MARK: - Git sync

    private static func shellQuote(_ value: String) -> String {
        "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }

    private static func validDeviceID(_ value: String) -> String? {
        let trimmed = normalizedDeviceID(value)
        guard !trimmed.isEmpty, trimmed != ".", trimmed != "..", trimmed.count <= 128 else {
            return nil
        }
        guard !trimmed.unicodeScalars.contains(where: {
            $0.value < 32 || $0.value == 47 || $0.value == 92 || $0.value == 0
        }) else {
            return nil
        }
        return trimmed
    }

    static func transactionScript(snapshotCommand: SyncCommand, deviceID: String) -> String {
        let snapshot = ([snapshotCommand.executable] + snapshotCommand.arguments)
            .map(Self.shellQuote)
            .joined(separator: " ")
        let quotedDevice = Self.shellQuote(deviceID)
        return """
        set -u
        set -o pipefail

        fail() {
          code="$1"
          shift
          printf 'Tokei sync error: %s\\n' "$*" >&2
          exit "$code"
        }

        sync_git() {
          /usr/bin/git \
            -c core.hooksPath=/dev/null \
            -c core.fsmonitor=false \
            -c commit.gpgSign=false \
            -c rebase.updateRefs=false \
            -c rebase.autoStash=false \
            -c push.gpgSign=false \
            -c push.followTags=false \
            -c remote.origin.mirror=false \
            "$@"
        }

        git_dir=$(sync_git rev-parse --absolute-git-dir 2>/dev/null) \
          || fail 20 "同步目录不是有效的 Git 仓库"
        declared_root=$(sync_git rev-parse --show-toplevel 2>/dev/null) \
          || fail 20 "无法读取同步仓库工作树"
        declared_root=$(cd -- "$declared_root" 2>/dev/null && /bin/pwd -P) \
          || fail 20 "无法解析同步仓库工作树"
        current_root=$(/bin/pwd -P)
        [ "$declared_root" = "$current_root" ] \
          || fail 20 "同步仓库 core.worktree 指向其他目录，已停止"
        marker="$git_dir/tokei-sync-rebase"
        rebase_merge="$git_dir/rebase-merge"
        rebase_apply="$git_dir/rebase-apply"
        audit_commits="$git_dir/tokei-sync-audit.$$"
        device_id=\(quotedDevice)
        device_pathspec=":(icase,literal)$device_id.json"
        exclude_pathspec=":(exclude,icase,literal)$device_id.json"
        junk_pathspec=":(exclude,icase)*.ds_store"
        peer_json_pathspec=":(top,glob)*.json"

        cleanup_temporary_files() {
          /bin/rm -f "$audit_commits"
        }
        trap cleanup_temporary_files EXIT

        validate_marker() {
          [ -f "$marker" ] || return 1
          [ "$(/usr/bin/sed -n '1p' "$marker" 2>/dev/null)" = "tokei-sync-rebase-v2" ] || return 1
          [ "$(/usr/bin/sed -n '2p' "$marker" 2>/dev/null)" = "refs/heads/main" ] || return 1
          [ "$(/usr/bin/sed -n '4p' "$marker" 2>/dev/null)" = "origin/main" ] || return 1
          marker_onto=$(/usr/bin/sed -n '5p' "$marker" 2>/dev/null)
          case "$marker_onto" in
            ''|*[!0-9a-f]*) return 1 ;;
          esac
          [ "${#marker_onto}" -eq 40 ] || [ "${#marker_onto}" -eq 64 ] || return 1
        }

        if [ -d "$rebase_merge" ] || [ -d "$rebase_apply" ]; then
          if validate_marker; then
            fail 21 "检测到上次 Tokei 遗留的 rebase，已保留现场且禁止跨进程自动 abort"
          fi
          fail 21 "检测到未完成的外部 rebase，已停止且未改动仓库"
        elif [ -f "$marker" ]; then
          validate_marker || fail 21 "发现格式异常的 Tokei rebase 标记，已停止"
          current_branch=$(sync_git symbolic-ref --quiet --short HEAD 2>/dev/null || true)
          [ "$current_branch" = "main" ] \
            || fail 21 "发现遗留 rebase 标记且当前分支异常，已停止"
          /bin/rm -f "$marker"
        fi

        for operation in MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD BISECT_START; do
          operation_path=$(sync_git rev-parse --git-path "$operation")
          [ ! -e "$operation_path" ] \
            || fail 21 "检测到未完成的 $operation，已停止且未改动仓库"
        done
        sequencer_path=$(sync_git rev-parse --git-path sequencer)
        [ ! -d "$sequencer_path" ] \
          || fail 21 "检测到未完成的 Git sequencer 操作，已停止且未改动仓库"
        unmerged_state=$(sync_git ls-files -u) \
          || fail 21 "无法检查同步仓库的冲突状态"
        [ -z "$unmerged_state" ] \
          || fail 21 "同步仓库含有未解决冲突，已停止且未改动仓库"

        branch=$(sync_git symbolic-ref --quiet --short HEAD 2>/dev/null) \
          || fail 22 "同步仓库处于 detached HEAD，已停止"
        [ "$branch" = "main" ] || fail 22 "同步仓库必须位于 main 分支，当前为 $branch"

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
          -- . "$exclude_pathspec" "$junk_pathspec") \
          || fail 23 "无法检查同步仓库的工作区状态"
        [ -z "$other_changes" ] \
          || fail 23 "同步仓库包含本机快照以外的未提交改动"

        audit_local_history() {
          audit_base="$1"
          audit_head="$2"
          sync_git rev-list --reverse "$audit_base..$audit_head" > "$audit_commits" \
            || fail 23 "无法读取本地待推送提交"
          while IFS= read -r commit; do
            [ -n "$commit" ] || continue
            parent_count=$(sync_git rev-list --parents -n 1 "$commit" \
              | /usr/bin/awk '{ print NF - 1 }') \
              || fail 23 "无法检查本地提交 $commit"
            [ "$parent_count" -eq 1 ] \
              || fail 23 "本地待推送历史包含 merge 或根提交，已停止"
            own_history_changes=$(sync_git diff-tree --no-commit-id --name-only -r \
              "$commit" -- "$device_pathspec") \
              || fail 23 "无法检查本地提交 $commit 的本机快照"
            [ -n "$own_history_changes" ] \
              || fail 23 "本地待推送提交未修改本机快照，已停止"
            other_history_changes=$(sync_git diff-tree --no-commit-id --name-only -r \
              "$commit" -- . "$exclude_pathspec") \
              || fail 23 "无法检查本地提交 $commit 的文件范围"
            [ -z "$other_history_changes" ] \
              || fail 23 "本地待推送提交修改了其他设备数据，已停止"
          done < "$audit_commits"
          /bin/rm -f "$audit_commits"
        }

        pre_snapshot_base=$(sync_git rev-parse origin/main) \
          || fail 23 "无法固定快照前远端提交"
        pre_snapshot_head=$(sync_git rev-parse HEAD) \
          || fail 23 "无法固定快照前本地提交"
        audit_local_history "$pre_snapshot_base" "$pre_snapshot_head"
        verified_pre_snapshot_head=$(sync_git rev-parse HEAD 2>/dev/null || true)
        [ "$verified_pre_snapshot_head" = "$pre_snapshot_head" ] \
          || fail 23 "历史审计期间 HEAD 发生变化，已停止"

        \(snapshot) || fail 24 "生成本机数据快照失败"

        matches=$(sync_git ls-files --cached --others --exclude-standard -- "$device_pathspec")
        match_count=$(printf '%s\\n' "$matches" | /usr/bin/awk 'NF { count++ } END { print count + 0 }')
        [ "$match_count" -eq 1 ] \
          || fail 24 "本机设备快照缺失或存在大小写重名文件"

        other_changes=$(sync_git status --porcelain=v1 --untracked-files=all \
          -- . "$exclude_pathspec" "$junk_pathspec") \
          || fail 23 "无法检查生成快照后的工作区状态"
        [ -z "$other_changes" ] \
          || fail 23 "生成快照时检测到其他文件被修改"

        sync_git add -- "$device_pathspec" || fail 26 "暂存本机快照失败"
        if ! sync_git diff --cached --quiet -- "$device_pathspec"; then
          sync_git commit --no-gpg-sign --only -m "tokei sync $device_id" -- "$device_pathspec" \
            || fail 26 "提交本机快照失败"
        fi
        post_commit_changes=$(sync_git status --porcelain=v1 --untracked-files=all \
          -- . "$junk_pathspec") \
          || fail 23 "无法检查提交后的工作区状态"
        [ -z "$post_commit_changes" ] \
          || fail 23 "提交后工作区仍有改动，已停止"

        write_marker() {
          marker_head="$1"
          marker_onto="$2"
          marker_tmp="$marker.tmp.$$"
          umask 077
          {
            printf 'tokei-sync-rebase-v2\\n'
            printf 'refs/heads/main\\n'
            printf '%s\\n' "$marker_head"
            printf 'origin/main\\n'
            printf '%s\\n' "$marker_onto"
            printf 'pid=%s\\n' "$$"
            /bin/date -u '+started_at=%Y-%m-%dT%H:%M:%SZ'
          } > "$marker_tmp" || fail 28 "无法写入 rebase 恢复标记"
          /bin/mv -f "$marker_tmp" "$marker" || fail 28 "无法保存 rebase 恢复标记"
        }

        rebase_onto_origin() {
          if sync_git merge-base --is-ancestor origin/main HEAD; then
            return 0
          fi
          pre_rebase_head=$(sync_git rev-parse HEAD) \
            || fail 27 "无法读取 rebase 前提交"
          pre_rebase_onto=$(sync_git rev-parse origin/main) \
            || fail 27 "无法读取 rebase 目标提交"
          write_marker "$pre_rebase_head" "$pre_rebase_onto"
          if sync_git rebase --merge origin/main; then
            /bin/rm -f "$marker"
            return 0
          fi
          if [ -d "$rebase_merge" ] || [ -d "$rebase_apply" ]; then
            fail 27 "rebase 未完成，已保留现场且禁止自动 abort，请人工检查同步仓库"
          fi
          /bin/rm -f "$marker"
          fail 27 "本机快照无法安全 rebase 到 origin/main"
        }

        attempt=1
        while [ "$attempt" -le 3 ]; do
          rebase_onto_origin
          audit_base=$(sync_git rev-parse origin/main) \
            || fail 23 "无法固定审计基线"
          candidate_head=$(sync_git rev-parse HEAD) \
            || fail 23 "无法固定待审计的本地提交"
          audit_local_history "$audit_base" "$candidate_head"
          verified_candidate_head=$(sync_git rev-parse HEAD 2>/dev/null || true)
          [ "$verified_candidate_head" = "$candidate_head" ] \
            || fail 23 "历史审计期间 HEAD 发生变化，已停止"
          audited_head="$candidate_head"
          audited_branch=$(sync_git symbolic-ref --quiet --short HEAD 2>/dev/null || true)
          [ "$audited_branch" = "main" ] \
            || fail 23 "审计后 main 分支发生变化，已停止"
          push_changes=$(sync_git status --porcelain=v1 --untracked-files=all \
            -- . "$junk_pathspec") \
            || fail 23 "无法检查 push 前的工作区状态"
          [ -z "$push_changes" ] \
            || fail 23 "push 前工作区出现改动，已停止"
          current_head=$(sync_git rev-parse HEAD) \
            || fail 23 "无法复核 push 前提交"
          [ "$current_head" = "$audited_head" ] \
            || fail 23 "审计后 HEAD 发生变化，已停止"
          if sync_git push origin "${audited_head}:refs/heads/main"; then
            pushed_head=$(sync_git rev-parse HEAD 2>/dev/null || true)
            [ "$pushed_head" = "$audited_head" ] \
              || fail 23 "push 期间 HEAD 发生变化，请检查外部 Git 操作"
            printf '多设备同步完成\\n'
            exit 0
          fi

          sync_git fetch origin main || fail 25 "push 失败后重新拉取 origin/main 失败"
          retry_head=$(sync_git rev-parse HEAD 2>/dev/null || true)
          [ "$retry_head" = "$audited_head" ] \
            || fail 23 "push 重试前 HEAD 发生变化，已停止"
          if sync_git merge-base --is-ancestor "$audited_head" origin/main; then
            printf '远端已包含本机同步提交\\n'
            exit 0
          fi
          if sync_git merge-base --is-ancestor origin/main "$audited_head"; then
            fail 29 "远端没有竞争更新，push 仍失败，请检查认证或分支权限"
          fi
          [ "$attempt" -lt 3 ] || fail 29 "远端持续更新，三次同步重试均失败"
          /bin/sleep "$attempt"
          attempt=$((attempt + 1))
          printf '检测到其他设备同时更新，正在重试 %s/3\\n' "$attempt"
        done

        fail 29 "push 失败"
        """
    }

    private static let transactionSupervisorScript = """
    import errno
    import fcntl
    import os
    import signal
    import subprocess
    import sys
    import time

    lock_path = sys.argv[1]
    timeout = float(sys.argv[2])
    command = sys.argv[3:]
    lock_fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        if error.errno in (errno.EACCES, errno.EAGAIN):
            print("Tokei sync busy: another transaction holds the repository lock", file=sys.stderr)
            raise SystemExit(75)
        raise

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
        while process_group_exists() and time.monotonic() < deadline:
            process.poll()
            time.sleep(0.05)
        if process_group_exists():
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 3
        while process_group_exists() and time.monotonic() < deadline:
            process.poll()
            time.sleep(0.05)
        if process.poll() is None:
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass

    def handle_signal(signum, _frame):
        print(f"Tokei sync error: supervisor received signal {signum}", file=sys.stderr)
        stop_process_group()
        raise SystemExit(30)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    process = subprocess.Popen(
        command,
        start_new_session=True,
        pass_fds=(lock_fd,),
    )
    try:
        raise SystemExit(process.wait(timeout=timeout))
    except subprocess.TimeoutExpired:
        print(f"Tokei sync error: transaction timed out after {int(timeout)} seconds", file=sys.stderr)
        stop_process_group()
        raise SystemExit(30)
    """

    private static func resultCode(for status: Int32) -> GitSyncCode {
        switch status {
        case 0: return .success
        case 20: return .invalidRepository
        case 21: return .foreignOperation
        case 22: return .detachedHead
        case 23: return .dirtyRepository
        case 24: return .snapshotFailed
        case 25: return .fetchFailed
        case 26: return .commitFailed
        case 27: return .rebaseFailed
        case 28: return .recoveryFailed
        case 29: return .pushFailed
        case 30: return .timedOut
        case 75: return .busy
        default: return .unknown
        }
    }

    func synchronize(snapshotCommand: SyncCommand,
                     completion: @escaping (GitSyncResult) -> Void) {
        guard let cfg = config else {
            completion(GitSyncResult(code: .invalidConfiguration, output: "同步配置不可用"))
            return
        }
        guard let deviceID = Self.validDeviceID(cfg.device_id) else {
            completion(GitSyncResult(code: .invalidConfiguration, output: "设备名不合法"))
            return
        }
        let dir = Self.resolvedSyncDir(cfg)
        let gitDirectory = (dir as NSString).appendingPathComponent(".git")
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: gitDirectory, isDirectory: &isDirectory),
              isDirectory.boolValue else {
            completion(GitSyncResult(
                code: .invalidRepository,
                output: "同步目录不是普通 Git 仓库：\(dir)"
            ))
            return
        }
        let lockPath = (gitDirectory as NSString).appendingPathComponent("tokei-sync.lock")
        let script = Self.transactionScript(snapshotCommand: snapshotCommand, deviceID: deviceID)
        let transactionTimeout = String(Int(max(1, min(snapshotCommand.transactionTimeout, 3600))))
        DispatchQueue.global(qos: .utility).async {
            let proc = Process()
            let outputPipe = Pipe()
            if let supervisorExecutable = snapshotCommand.supervisorExecutable {
                proc.executableURL = URL(fileURLWithPath: supervisorExecutable)
                proc.arguments = snapshotCommand.supervisorArguments + [
                    "-c", Self.transactionSupervisorScript,
                    lockPath, transactionTimeout, "/bin/zsh", "-f", "-c", script,
                ]
            } else {
                proc.executableURL = URL(fileURLWithPath: "/usr/bin/lockf")
                proc.arguments = ["-k", "-t", "0", lockPath, "/bin/zsh", "-f", "-c", script]
            }
            proc.currentDirectoryURL = URL(fileURLWithPath: dir, isDirectory: true)
            proc.standardOutput = outputPipe
            proc.standardError = outputPipe
            proc.standardInput = FileHandle.nullDevice
            var environment = ProcessInfo.processInfo.environment
            let redirectedGitEnvironmentKeys = [
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
                "GIT_CONFIG",
                "GIT_CONFIG_GLOBAL",
                "GIT_CONFIG_SYSTEM",
                "GIT_CONFIG_NOSYSTEM",
                "GIT_CONFIG_PARAMETERS",
                "GIT_ASKPASS",
                "SSH_ASKPASS",
                "GIT_SSH_VARIANT",
                "ZDOTDIR",
            ]
            for key in redirectedGitEnvironmentKeys {
                environment.removeValue(forKey: key)
            }
            for key in Array(environment.keys)
                where key == "GIT_CONFIG_COUNT"
                    || key.hasPrefix("GIT_CONFIG_KEY_")
                    || key.hasPrefix("GIT_CONFIG_VALUE_") {
                environment.removeValue(forKey: key)
            }
            environment["GIT_TERMINAL_PROMPT"] = "0"
            environment["GIT_ASKPASS"] = "/usr/bin/false"
            environment["SSH_ASKPASS"] = "/usr/bin/false"
            environment["GCM_INTERACTIVE"] = "Never"
            environment["GIT_EDITOR"] = "true"
            environment["GIT_SEQUENCE_EDITOR"] = "true"
            environment["GIT_NO_REPLACE_OBJECTS"] = "1"
            environment["GIT_SSH_COMMAND"] = "/usr/bin/ssh -o BatchMode=yes -o ConnectTimeout=15 -o ConnectionAttempts=2 -o ServerAliveInterval=15 -o ServerAliveCountMax=2"
            environment["GIT_SSH_VARIANT"] = "ssh"
            environment["SSH_ASKPASS_REQUIRE"] = "never"
            proc.environment = environment
            do {
                try proc.run()
            } catch {
                DispatchQueue.main.async {
                    completion(GitSyncResult(code: .unknown, output: error.localizedDescription))
                }
                return
            }
            let outputData = outputPipe.fileHandleForReading.readDataToEndOfFile()
            proc.waitUntilExit()
            let output = String(data: outputData, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            let code = Self.resultCode(for: proc.terminationStatus)
            let fallback: String
            switch code {
            case .success: fallback = "GitHub 已同步"
            case .busy: fallback = "另一同步任务正在运行"
            default: fallback = "同步失败，退出码 \(proc.terminationStatus)"
            }
            let result = GitSyncResult(
                code: code,
                output: output.isEmpty ? fallback : output
            )
            DispatchQueue.main.async { completion(result) }
        }
    }
}
