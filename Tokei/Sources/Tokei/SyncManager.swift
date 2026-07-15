import Foundation

struct SyncConfig: Codable {
    var device_id: String
    var sync_dir: String
    var auto_sync: Bool?
    var sync_interval: Int?     // minutes
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

final class SyncManager {
    static let configPath = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent(".tokei/config.json")
    static let syncDir = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent(".tokei/sync").path

    var config: SyncConfig?

    init() { config = Self.loadConfig() }

    static func resolvedSyncDir(_ cfg: SyncConfig) -> String {
        let raw = cfg.sync_dir.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !raw.isEmpty else { return Self.syncDir }
        return (raw as NSString).expandingTildeInPath
    }

    // MARK: - Config

    static func loadConfig() -> SyncConfig? {
        guard let data = try? Data(contentsOf: configPath) else { return nil }
        return try? JSONDecoder().decode(SyncConfig.self, from: data)
    }

    func saveConfig(_ cfg: SyncConfig) {
        config = cfg
        let dir = Self.configPath.deletingLastPathComponent()
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        // 读取现有 JSON 并只更新同步相关字段,保留其他 key
        // (如 qoder_ide_enabled),避免整体覆盖导致非同步字段丢失。
        var dict: [String: Any] = [:]
        if let data = try? Data(contentsOf: Self.configPath),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            dict = obj
        }
        dict["device_id"] = cfg.device_id
        dict["sync_dir"] = cfg.sync_dir
        if let v = cfg.auto_sync { dict["auto_sync"] = v } else { dict.removeValue(forKey: "auto_sync") }
        if let v = cfg.sync_interval { dict["sync_interval"] = v } else { dict.removeValue(forKey: "sync_interval") }
        if let data = try? JSONSerialization.data(withJSONObject: dict, options: [.prettyPrinted, .sortedKeys]) {
            try? data.write(to: Self.configPath)
        }
    }

    // MARK: - Read peers

    func loadPeers() -> [PeerDevice] {
        guard let cfg = config else { return [] }
        let dir = Self.resolvedSyncDir(cfg)
        guard FileManager.default.fileExists(atPath: dir) else { return [] }
        var peers: [PeerDevice] = []
        let fm = FileManager.default
        guard let files = try? fm.contentsOfDirectory(atPath: dir) else { return [] }
        for file in files where file.hasSuffix(".json") {
            let deviceId = String(file.dropLast(5)) // remove .json
            if deviceId.caseInsensitiveCompare(cfg.device_id) == .orderedSame { continue }
            let path = (dir as NSString).appendingPathComponent(file)
            guard let data = try? Data(contentsOf: URL(fileURLWithPath: path)) else { continue }
            guard let raw = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let ts = raw["_ts"] as? Int else { continue }
            var cleaned = raw
            for key in cleaned.keys where key.hasPrefix("_") { cleaned.removeValue(forKey: key) }
            guard let cleanData = try? JSONSerialization.data(withJSONObject: cleaned),
                  let usage = try? JSONDecoder().decode(Usage.self, from: cleanData) else { continue }
            var dashboard: PeerDashboardSnapshot?
            if let rawDashboard = raw["_dashboard"],
               JSONSerialization.isValidJSONObject(rawDashboard),
               let dashboardData = try? JSONSerialization.data(withJSONObject: rawDashboard) {
                dashboard = try? JSONDecoder().decode(PeerDashboardSnapshot.self, from: dashboardData)
            }
            var rangeBounds: [String: RangeBoundary] = [:]
            if let rawBounds = raw["_range_bounds"],
               JSONSerialization.isValidJSONObject(rawBounds),
               let boundsData = try? JSONSerialization.data(withJSONObject: rawBounds) {
                rangeBounds = (try? JSONDecoder().decode([String: RangeBoundary].self, from: boundsData)) ?? [:]
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
        return peers
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
            mergeRanges(&u.workbuddy.ranges, peer.usage.workbuddy.ranges, pairs)
            mergeRanges(&u.opencode.ranges, peer.usage.opencode.ranges, pairs)
            mergeRanges(&u.qwencode.ranges, peer.usage.qwencode.ranges, pairs)
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
            d.tokens += s.tokens; d.sessions += s.sessions
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
            d.cost += s.cost; d.sessions += s.sessions
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
            if let idx = dst.firstIndex(where: { $0.name == m.name }) {
                dst[idx].in += m.in
                dst[idx].out += m.out
                dst[idx].cr += m.cr
                dst[idx].cw += m.cw
                dst[idx].reason += m.reason
                dst[idx].cost += m.cost
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

    func gitSync(completion: @escaping (Bool) -> Void) {
        guard let cfg = config else { completion(false); return }
        let dir = Self.resolvedSyncDir(cfg)
        let escapedDir = dir.replacingOccurrences(of: "'", with: "'\\''")
        let escapedDevice = cfg.device_id.replacingOccurrences(of: "'", with: "'\\''")
        DispatchQueue.global(qos: .utility).async {
            let script = """
            cd '\(escapedDir)' || exit 1
            git fetch origin main 2>/dev/null || exit 1
            device_file=$(find . -maxdepth 1 -type f -iname '\(escapedDevice).json' -print -quit)
            if [ -z "$device_file" ]; then
              device_file='./\(escapedDevice).json'
            fi
            for peer_file in ./*.json; do
              [ "$peer_file" = "$device_file" ] && continue
              git restore --staged --worktree -- "$peer_file" 2>/dev/null || true
            done
            git add -- "$device_file" || exit 1
            if ! git diff --cached --quiet; then
              git commit -m 'chore(sync): 更新 \(escapedDevice) 用量数据' || exit 1
            fi
            attempt=1
            while [ "$attempt" -le 3 ]; do
              git fetch origin main 2>/dev/null || exit 1
              if ! git rebase origin/main 2>/dev/null; then
                git rebase --abort 2>/dev/null || true
                exit 1
              fi
              if git push origin HEAD:main 2>/dev/null; then
                exit 0
              fi
              sleep "$attempt"
              attempt=$((attempt + 1))
            done
            exit 1
            """
            let proc = Process()
            proc.executableURL = URL(fileURLWithPath: "/bin/zsh")
            proc.arguments = ["-c", script]
            proc.standardOutput = Pipe()
            proc.standardError = Pipe()
            try? proc.run()
            proc.waitUntilExit()
            DispatchQueue.main.async { completion(proc.terminationStatus == 0) }
        }
    }
}
