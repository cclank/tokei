import Foundation
import CZstd
import TokeiUpdateSecurity

final class DataLoader {
    struct ScriptResult {
        var stdout: String
        var stderr: String
        var exitCode: Int32
        var elapsed: TimeInterval
        var timedOut: Bool
    }

    static var scriptPath: String = {
        let userScript = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".tokei/usage.30s.py").path
        if let bundled = Bundle.main.resourcePath {
            let bundledScript = (bundled as NSString).appendingPathComponent("usage.30s.py")
            if FileManager.default.fileExists(atPath: bundledScript) {
                syncToUserDir(from: bundled)
                // App 与采集逻辑随同一个安装包运行。用户目录的脚本供独立 CLI 使用，
                // 可能由其他版本安装包写入，不能用它替换当前 App 的采集逻辑。
                return bundledScript
            }
        }
        return userScript
    }()

    private static let lastUsageURL = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent(".tokei/last_usage.json")

    private static func syncToUserDir(from resourceDir: String) {
        let dest = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".tokei")
        CollectorScriptInstaller.sync(
            resourceDir: resourceDir,
            userDir: dest,
            bundledRelease: Updater.releaseTag
        )
    }

    // 首次全量定位 /usage，之后只检查变化项并复用最近一次有效候选。
    private struct ClaudeCacheRecord {
        let url: URL
        let modified: TimeInterval
        let size: Int

        var signature: String {
            "\(url.path)|\(modified.bitPattern)|\(size)"
        }
    }

    private struct ClaudeQuotaCandidate: Codable, Equatable {
        var path: String
        var modified: TimeInterval
        var size: Int
    }

    private struct ClaudeQuotaSnapshot: Codable, Equatable {
        var q5: Double?
        var q5Reset: Int?
        var q7: Double?
        var q7Reset: Int?
        var qf: Double?
        var qfReset: Int?
        var updated: Int
    }

    private struct ClaudeQuotaState: Codable, Equatable {
        var version = 3
        var candidate: ClaudeQuotaCandidate?
        var snapshot: ClaudeQuotaSnapshot?
        var scanModified: TimeInterval = -1
        var scanBoundary: [String] = []
        var lastFullScan = 0
    }

    private static let claudeQuotaStaleTTL = 30 * 60
    private static let claudeQuotaFullScanInterval = 6 * 60 * 60
    private static let claudeQuotaRetryScanInterval = 5 * 60
    private static let claudeCacheFileLimit = 16 * 1024 * 1024
    /// 水位线只认不超过当前时间的 mtime（留 5 分钟容差）；未来文件只读一次（issue #71）。
    private static let claudeQuotaFutureSkew: TimeInterval = 5 * 60
    private static let claudeQuotaScanLock = NSLock()
    private static let zstdMagic = Data([0x28, 0xb5, 0x2f, 0xfd])
    private static let deepSeekPreparationLock = NSLock()
    private static let deepSeekMaxDecompressedSize = 2 * 1024 * 1024 * 1024

    private struct DeepSeekSourceSignature: Codable, Equatable {
        var modified: TimeInterval
        var size: Int
    }

    private static var claudeQuotaStateURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".tokei/claude_quota_swift_cache.json")
    }

    private static var claudeCLIQuotaEnabled: Bool {
        UserDefaults.standard.object(forKey: "claudeCLIQuotaEnabled") as? Bool ?? false
    }

    private static func claudeCacheRecords() -> [ClaudeCacheRecord] {
        let cacheDir: URL
        if let configured = ProcessInfo.processInfo.environment["TOKEI_CLAUDE_CACHE_DIR"],
           !configured.isEmpty {
            cacheDir = URL(fileURLWithPath: NSString(string: configured).expandingTildeInPath)
        } else {
            cacheDir = FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent("Library/Application Support/Claude/Cache/Cache_Data")
        }
        let keys: Set<URLResourceKey> = [.contentModificationDateKey, .fileSizeKey]
        guard let urls = try? FileManager.default.contentsOfDirectory(
            at: cacheDir,
            includingPropertiesForKeys: Array(keys),
            options: [.skipsHiddenFiles]
        ) else { return [] }
        return urls.compactMap { url in
            guard url.lastPathComponent.hasSuffix("_0"),
                  let values = try? url.resourceValues(forKeys: keys),
                  let modified = values.contentModificationDate,
                  let size = values.fileSize else { return nil }
            return ClaudeCacheRecord(
                url: url.resolvingSymlinksInPath(),
                modified: modified.timeIntervalSince1970,
                size: size
            )
        }.sorted {
            if $0.modified == $1.modified { return $0.url.path > $1.url.path }
            return $0.modified > $1.modified
        }
    }

    private static func loadClaudeQuotaState() -> ClaudeQuotaState {
        guard let data = try? Data(contentsOf: claudeQuotaStateURL),
              let state = try? JSONDecoder().decode(ClaudeQuotaState.self, from: data),
              state.version == 3 else { return ClaudeQuotaState() }
        return state
    }

    private static func saveClaudeQuotaState(_ state: ClaudeQuotaState) {
        let directory = claudeQuotaStateURL.deletingLastPathComponent()
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            let data = try JSONEncoder().encode(state)
            try data.write(to: claudeQuotaStateURL, options: .atomic)
            try? FileManager.default.setAttributes(
                [.posixPermissions: 0o600],
                ofItemAtPath: claudeQuotaStateURL.path
            )
        } catch {
            fputs("Tokei Claude quota cache write failed: \(error)\n", stderr)
        }
    }

    private static func parseClaudeQuota(_ record: ClaudeCacheRecord) -> ClaudeQuotaSnapshot? {
        guard record.size > 0, record.size <= claudeCacheFileLimit,
              let data = try? Data(contentsOf: record.url, options: .mappedIfSafe) else { return nil }
        let organization = Data("organizations/".utf8)
        let usage = Data("/usage".utf8)
        guard data.range(of: organization) != nil,
              data.range(of: usage) != nil,
              let magicRange = data.range(of: zstdMagic) else { return nil }
        let compressed = Data(data[magicRange.lowerBound...])
        guard let decompressed = zstdDecompress(compressed),
              let json = try? JSONSerialization.jsonObject(with: decompressed) as? [String: Any]
        else { return nil }
        let fiveHour = json["five_hour"] as? [String: Any] ?? [:]
        let sevenDay = json["seven_day"] as? [String: Any] ?? [:]
        let fableLimit = (json["limits"] as? [[String: Any]])?.first { limit in
            guard limit["kind"] as? String == "weekly_scoped",
                  let scope = limit["scope"] as? [String: Any],
                  let model = scope["model"] as? [String: Any],
                  let displayName = model["display_name"] as? String
            else { return false }
            return displayName.caseInsensitiveCompare("Fable") == .orderedSame
        } ?? [:]
        let q5 = (fiveHour["utilization"] as? NSNumber)?.doubleValue
        let q7 = (sevenDay["utilization"] as? NSNumber)?.doubleValue
        let qf = (fableLimit["percent"] as? NSNumber)?.doubleValue
        guard q5 != nil || q7 != nil || qf != nil else { return nil }
        return ClaudeQuotaSnapshot(
            q5: q5,
            q5Reset: isoToEpoch(fiveHour["resets_at"] as? String),
            q7: q7,
            q7Reset: isoToEpoch(sevenDay["resets_at"] as? String),
            qf: qf,
            qfReset: isoToEpoch(fableLimit["resets_at"] as? String),
            updated: Int(record.modified)
        )
    }

    private static func claudeQuotaDictionary(
        _ snapshot: ClaudeQuotaSnapshot,
        now: Int
    ) -> [String: Any] {
        var result: [String: Any] = ["q_updated": snapshot.updated]
        if let q5 = snapshot.q5 { result["q5"] = q5 }
        if let reset = snapshot.q5Reset { result["q5_reset"] = reset }
        if let q7 = snapshot.q7 { result["q7"] = q7 }
        if let reset = snapshot.q7Reset { result["q7_reset"] = reset }
        if let qf = snapshot.qf { result["qf"] = qf }
        if let reset = snapshot.qfReset { result["qf_reset"] = reset }
        let age = now - snapshot.updated
        let sourceStale = age > claudeQuotaStaleTTL || age < -300
        result["q5_stale"] = snapshot.q5 != nil &&
            (sourceStale || (snapshot.q5Reset.map { $0 <= now } ?? false))
        result["q7_stale"] = snapshot.q7 != nil &&
            (sourceStale || (snapshot.q7Reset.map { $0 <= now } ?? false))
        result["qf_stale"] = snapshot.qf != nil &&
            (sourceStale || (snapshot.qfReset.map { $0 <= now } ?? false))
        return result
    }

    static func scanClaudeQuota(now: Date = Date()) -> [String: Any]? {
        claudeQuotaScanLock.lock()
        defer { claudeQuotaScanLock.unlock() }
        let nowEpoch = Int(now.timeIntervalSince1970)
        let records = claudeCacheRecords()
        var recordsByPath: [String: ClaudeCacheRecord] = [:]
        for record in records { recordsByPath[record.url.path] = record }
        let original = loadClaudeQuotaState()
        var state = original
        let initialScan = state.scanModified < 0
        let boundary = Set(state.scanBoundary)
        let changed = records.filter {
            $0.modified > state.scanModified ||
                ($0.modified == state.scanModified && !boundary.contains($0.signature))
        }
        var inspected = Set<String>()
        var selected: (ClaudeCacheRecord, ClaudeQuotaSnapshot)?

        func inspect(_ record: ClaudeCacheRecord) -> (ClaudeCacheRecord, ClaudeQuotaSnapshot)? {
            inspected.insert(record.url.path)
            guard let snapshot = parseClaudeQuota(record) else { return nil }
            return (record, snapshot)
        }

        let horizon = Double(nowEpoch) + claudeQuotaFutureSkew
        for record in changed {
            // 未来时间戳文件跳过内容解析：签名已在 scanBoundary，只读一次。
            if record.modified > horizon {
                inspected.insert(record.url.path)
                continue
            }
            if let value = inspect(record) {
                selected = value
                break
            }
        }

        var candidateInvalid = false
        let candidateRecord = state.candidate.flatMap { recordsByPath[$0.path] }
        if selected == nil, let candidate = state.candidate {
            if let record = candidateRecord {
                let changedCandidate = record.modified != candidate.modified || record.size != candidate.size
                if changedCandidate {
                    if !inspected.contains(record.url.path) {
                        selected = inspect(record)
                    }
                    candidateInvalid = selected == nil
                }
            } else {
                candidateInvalid = true
            }
        }

        let desktopQuota = finishClaudeQuotaScan(
            records: records,
            original: original,
            state: &state,
            selected: &selected,
            inspected: &inspected,
            candidateInvalid: candidateInvalid,
            initialScan: initialScan,
            nowEpoch: nowEpoch
        )
        guard claudeCLIQuotaEnabled,
              !hasFreshClaudeCoreQuota(desktopQuota),
              let cliQuota = ClaudeCLIQuotaBridge.fetchQuota(now: now) else {
            return desktopQuota
        }
        guard let desktopQuota else { return cliQuota }
        let desktopUpdated = intValue(desktopQuota["q_updated"]) ?? 0
        let cliUpdated = intValue(cliQuota["q_updated"]) ?? 0
        return cliUpdated >= desktopUpdated ? cliQuota : desktopQuota
    }

    private static func hasFreshClaudeCoreQuota(_ quota: [String: Any]?) -> Bool {
        guard let quota else { return false }
        return numberValue(quota["q5"]) != nil && quota["q5_stale"] as? Bool != true &&
            numberValue(quota["q7"]) != nil && quota["q7_stale"] as? Bool != true
    }

    private static func finishClaudeQuotaScan(
        records: [ClaudeCacheRecord],
        original: ClaudeQuotaState,
        state: inout ClaudeQuotaState,
        selected: inout (ClaudeCacheRecord, ClaudeQuotaSnapshot)?,
        inspected: inout Set<String>,
        candidateInvalid: Bool,
        initialScan: Bool,
        nowEpoch: Int
    ) -> [String: Any]? {
        if initialScan { state.lastFullScan = nowEpoch }
        let retryInterval = state.snapshot == nil
            ? claudeQuotaRetryScanInterval
            : claudeQuotaFullScanInterval
        let needsFullScan = candidateInvalid || nowEpoch - state.lastFullScan >= retryInterval
        if selected == nil && needsFullScan {
            for record in records where !inspected.contains(record.url.path) {
                inspected.insert(record.url.path)
                if let snapshot = parseClaudeQuota(record) {
                    selected = (record, snapshot)
                    break
                }
            }
            state.lastFullScan = nowEpoch
        }

        if let (record, snapshot) = selected {
            state.candidate = ClaudeQuotaCandidate(
                path: record.url.path,
                modified: record.modified,
                size: record.size
            )
            state.snapshot = snapshot
        } else if candidateInvalid {
            state.candidate = nil
        }

        if let newest = records.first {
            let horizon = Double(nowEpoch) + claudeQuotaFutureSkew
            let past = records.filter { $0.modified <= horizon }
            let base = past.isEmpty ? records : past
            let newestModified = base[0].modified
            state.scanModified = newestModified
            var boundary = base.prefix { $0.modified == newestModified }.map(\.signature)
            // 未来时间戳文件只读一次，不再每轮重复读取，也不参与水位线。
            boundary += records.filter { $0.modified > horizon && !inspected.contains($0.url.path) }.map(\.signature)
            state.scanBoundary = boundary
        } else {
            state.scanModified = 0
            state.scanBoundary = []
        }
        if state != original { saveClaudeQuotaState(state) }
        guard let snapshot = state.snapshot else { return nil }
        return claudeQuotaDictionary(snapshot, now: nowEpoch)
    }

    private static func zstdDecompress(_ src: Data) -> Data? {
        let bufSize = src.count
        let frameSize = src.withUnsafeBytes { ptr -> Int in
            ZSTD_findFrameCompressedSize(ptr.baseAddress, bufSize)
        }
        guard ZSTD_isError(frameSize) == 0 else { return nil }
        let bound = src.withUnsafeBytes { ptr -> UInt64 in
            ZSTD_getFrameContentSize(ptr.baseAddress, frameSize)
        }
        let dstSize = (bound == ZSTD_CONTENTSIZE_ERROR || bound == ZSTD_CONTENTSIZE_UNKNOWN)
            ? max(frameSize * 20, 4096)
            : Int(bound)
        var dst = [UInt8](repeating: 0, count: dstSize)
        let ret = src.withUnsafeBytes { srcPtr -> Int in
            ZSTD_decompress(&dst, dstSize, srcPtr.baseAddress, frameSize)
        }
        guard ZSTD_isError(ret) == 0 else { return nil }
        return Data(dst.prefix(ret))
    }

    private static func zstdDecompressFrames(_ src: Data) -> Data? {
        guard !src.isEmpty else { return Data() }
        var output = Data()
        var offset = 0
        let succeeded = src.withUnsafeBytes { srcPtr -> Bool in
            guard let base = srcPtr.baseAddress else { return false }
            while offset < src.count {
                let frame = base.advanced(by: offset)
                let remaining = src.count - offset
                let frameSize = ZSTD_findFrameCompressedSize(frame, remaining)
                guard ZSTD_isError(frameSize) == 0, frameSize > 0, frameSize <= remaining else {
                    return false
                }
                let contentSize = ZSTD_getFrameContentSize(frame, frameSize)
                let destinationSize: Int
                if contentSize == ZSTD_CONTENTSIZE_ERROR {
                    return false
                } else if contentSize == ZSTD_CONTENTSIZE_UNKNOWN {
                    destinationSize = min(max(frameSize * 64, 64 * 1024), 64 * 1024 * 1024)
                } else {
                    guard contentSize <= UInt64(deepSeekMaxDecompressedSize) else { return false }
                    destinationSize = max(Int(contentSize), 1)
                }
                guard output.count <= deepSeekMaxDecompressedSize - destinationSize else { return false }
                var destination = [UInt8](repeating: 0, count: destinationSize)
                let written = ZSTD_decompress(&destination, destinationSize, frame, frameSize)
                guard ZSTD_isError(written) == 0 else { return false }
                output.append(contentsOf: destination.prefix(written))
                offset += frameSize
            }
            return offset == src.count
        }
        return succeeded ? output : nil
    }

    private static var deepSeekCacheURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".tokei/cache/dsh-sessions", isDirectory: true)
    }

    @discardableResult
    private static func prepareDeepSeekHarnessSessions() -> URL {
        deepSeekPreparationLock.lock()
        defer { deepSeekPreparationLock.unlock() }

        let fm = FileManager.default
        let sourceRoot: URL
        if let configured = ProcessInfo.processInfo.environment["TOKEI_DSH_DIR"],
           !configured.isEmpty {
            sourceRoot = URL(fileURLWithPath: NSString(string: configured).expandingTildeInPath,
                             isDirectory: true).standardizedFileURL
        } else {
            sourceRoot = fm.homeDirectoryForCurrentUser
                .appendingPathComponent(".dsh/sessions", isDirectory: true).standardizedFileURL
        }
        let outputRoot = deepSeekCacheURL
        try? fm.createDirectory(at: outputRoot, withIntermediateDirectories: true,
                                attributes: [.posixPermissions: 0o700])
        let manifestURL = outputRoot.appendingPathComponent("manifest.json")
        let decoder = JSONDecoder()
        let oldManifest = (try? Data(contentsOf: manifestURL)).flatMap {
            try? decoder.decode([String: DeepSeekSourceSignature].self, from: $0)
        } ?? [:]

        let keys: Set<URLResourceKey> = [.isRegularFileKey, .contentModificationDateKey, .fileSizeKey]
        guard let enumerator = fm.enumerator(at: sourceRoot, includingPropertiesForKeys: Array(keys),
                                             options: [.skipsHiddenFiles]) else {
            return outputRoot
        }
        var manifest: [String: DeepSeekSourceSignature] = [:]
        let sourcePrefix = sourceRoot.path.hasSuffix("/") ? sourceRoot.path : sourceRoot.path + "/"
        for case let source as URL in enumerator {
            guard source.path.hasSuffix(".jsonl.zstd"),
                  source.standardizedFileURL.path.hasPrefix(sourcePrefix),
                  let values = try? source.resourceValues(forKeys: keys),
                  values.isRegularFile == true,
                  let modified = values.contentModificationDate,
                  let size = values.fileSize else { continue }
            let relative = String(source.standardizedFileURL.path.dropFirst(sourcePrefix.count))
            let outputRelative = String(relative.dropLast(".zstd".count))
            let output = outputRoot.appendingPathComponent(outputRelative).standardizedFileURL
            guard output.path.hasPrefix(outputRoot.path + "/") else { continue }
            let signature = DeepSeekSourceSignature(modified: modified.timeIntervalSince1970, size: size)
            if oldManifest[relative] == signature, fm.fileExists(atPath: output.path) {
                manifest[relative] = signature
                continue
            }
            guard let compressed = try? Data(contentsOf: source, options: .mappedIfSafe),
                  let decompressed = zstdDecompressFrames(compressed) else {
                continue
            }
            do {
                try fm.createDirectory(at: output.deletingLastPathComponent(),
                                       withIntermediateDirectories: true,
                                       attributes: [.posixPermissions: 0o700])
                try decompressed.write(to: output, options: .atomic)
                try fm.setAttributes([.posixPermissions: 0o600], ofItemAtPath: output.path)
                manifest[relative] = signature
            } catch {
                continue
            }
        }

        for relative in oldManifest.keys where manifest[relative] == nil {
            let outputRelative = String(relative.dropLast(".zstd".count))
            let output = outputRoot.appendingPathComponent(outputRelative).standardizedFileURL
            if output.path.hasPrefix(outputRoot.path + "/") {
                try? fm.removeItem(at: output)
            }
        }
        if manifest != oldManifest, let data = try? JSONEncoder().encode(manifest) {
            try? data.write(to: manifestURL, options: .atomic)
            try? fm.setAttributes([.posixPermissions: 0o600], ofItemAtPath: manifestURL.path)
        }
        return outputRoot
    }

    private static func isoToEpoch(_ s: String?) -> Int? {
        guard let s = s else { return nil }
        let fmt = ISO8601DateFormatter()
        fmt.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = fmt.date(from: s) { return Int(d.timeIntervalSince1970) }
        fmt.formatOptions = [.withInternetDateTime]
        if let d = fmt.date(from: s) { return Int(d.timeIntervalSince1970) }
        return nil
    }

    static func loadSync() -> Usage? { runScript() }

    static func loadCachedUsage() -> Usage? {
        var candidates = [lastUsageURL]
        if let config = SyncManager.loadConfig() {
            let deviceID = SyncManager.normalizedDeviceID(config.device_id)
            let isSafeDeviceID = !deviceID.isEmpty && deviceID != "." && deviceID != ".." &&
                deviceID.count <= 128 && !deviceID.unicodeScalars.contains {
                    $0.value < 32 || $0.value == 47 || $0.value == 92 || $0.value == 0
                }
            if isSafeDeviceID {
                candidates.append(
                    URL(fileURLWithPath: SyncManager.resolvedSyncDir(config), isDirectory: true)
                        .appendingPathComponent(deviceID)
                        .appendingPathExtension("json")
                )
            }
        }

        for url in candidates {
            guard let data = try? Data(contentsOf: url),
                  var raw = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            else { continue }
            for key in raw.keys where key.hasPrefix("_") { raw.removeValue(forKey: key) }
            if var claude = raw["claude"] as? [String: Any] {
                normalizeClaudeQuota(&claude)
                raw["claude"] = claude
            }
            guard let cleaned = try? JSONSerialization.data(withJSONObject: raw),
                  let usage = try? JSONDecoder().decode(Usage.self, from: cleaned)
            else { continue }
            return usage
        }
        return nil
    }

    static func load(_ completion: @escaping (Usage?) -> Void) {
        DispatchQueue.global(qos: .utility).async {
            let usage = runScript()
            DispatchQueue.main.async { completion(usage) }
        }
    }

    static func runScript(args: [String] = ["--json", "--no-sync-snapshot"]) -> Usage? {
        // Large first-time indexes may need several minutes; cached UI remains available.
        let result = runScriptRaw(args: args, timeout: 600)
        guard !result.timedOut, result.exitCode == 0 else {
            fputs("Tokei script failed: exit=\(result.exitCode) timeout=\(result.timedOut)\n\(result.stderr)\n", stderr)
            return nil
        }
        let data = Data(result.stdout.utf8)
        do {
            guard var raw = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
            for key in raw.keys where key.hasPrefix("_") { raw.removeValue(forKey: key) }
            if var claude = raw["claude"] as? [String: Any] {
                let scriptHasQuota = numberValue(claude["q5"]) != nil ||
                    numberValue(claude["q7"]) != nil ||
                    numberValue(claude["qf"]) != nil
                let scriptUpdated = intValue(claude["q_updated"]) ?? 0
                if let nativeQuota = scanClaudeQuota() {
                    let nativeHasQuota = numberValue(nativeQuota["q5"]) != nil ||
                        numberValue(nativeQuota["q7"]) != nil ||
                        numberValue(nativeQuota["qf"]) != nil
                    let nativeUpdated = intValue(nativeQuota["q_updated"]) ?? 0
                    if nativeHasQuota && (!scriptHasQuota || nativeUpdated >= scriptUpdated) {
                        for key in [
                            "q5", "q5_reset", "q7", "q7_reset", "qf", "qf_reset",
                            "q_updated", "q5_stale", "q7_stale", "qf_stale",
                        ] {
                            if let value = nativeQuota[key] {
                                claude[key] = value
                            } else {
                                claude.removeValue(forKey: key)
                            }
                        }
                    }
                }
                normalizeClaudeQuota(&claude)
                raw["claude"] = claude
            }
            let cleaned = try JSONSerialization.data(withJSONObject: raw)
            let usage = try JSONDecoder().decode(Usage.self, from: cleaned)
            persistCachedUsage(cleaned)
            return usage
        } catch {
            fputs("Tokei decode error: \(error)\n", stderr)
            return nil
        }
    }

    private static func persistCachedUsage(_ data: Data) {
        do {
            try FileManager.default.createDirectory(
                at: lastUsageURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try data.write(to: lastUsageURL, options: .atomic)
            try? FileManager.default.setAttributes(
                [.posixPermissions: 0o600],
                ofItemAtPath: lastUsageURL.path
            )
        } catch {
            fputs("Tokei usage cache write failed: \(error)\n", stderr)
        }
    }

    private static func numberValue(_ value: Any?) -> Double? {
        (value as? NSNumber)?.doubleValue
    }

    private static func intValue(_ value: Any?) -> Int? {
        (value as? NSNumber)?.intValue
    }

    private static func normalizeClaudeQuota(_ claude: inout [String: Any]) {
        let now = Int(Date().timeIntervalSince1970)
        let updated = intValue(claude["q_updated"]) ?? 0
        let age = now - updated
        let sourceStale = updated <= 0 || age > claudeQuotaStaleTTL || age < -300
        for (valueKey, resetKey, staleKey) in [
            ("q5", "q5_reset", "q5_stale"),
            ("q7", "q7_reset", "q7_stale"),
            ("qf", "qf_reset", "qf_stale"),
        ] {
            guard numberValue(claude[valueKey]) != nil else {
                claude.removeValue(forKey: staleKey)
                continue
            }
            let resetExpired = intValue(claude[resetKey]).map { $0 <= now } ?? false
            claude[staleKey] = sourceStale || resetExpired
        }
    }

    private static func nativeClaudeQuotaJSON() -> String? {
        guard let quota = scanClaudeQuota(),
              JSONSerialization.isValidJSONObject(quota),
              let data = try? JSONSerialization.data(
                  withJSONObject: quota,
                  options: [.sortedKeys]
              )
        else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func writeSyncSnapshot(_ completion: @escaping (Bool) -> Void) {
        DispatchQueue.global(qos: .utility).async {
            let result = runScriptRaw(args: ["--write-sync"], timeout: 120)
            let ok = !result.timedOut && result.exitCode == 0
            if !ok {
                fputs("Tokei sync snapshot failed: exit=\(result.exitCode) timeout=\(result.timedOut)\n\(result.stderr)\n", stderr)
            }
            DispatchQueue.main.async { completion(ok) }
        }
    }

    private static let pythonPath: String = {
        for p in ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"] {
            if FileManager.default.fileExists(atPath: p) { return p }
        }
        return "/usr/bin/env"
    }()

    private static let syncSnapshotPython = """
    import importlib.util
    import os
    import sys

    script_path, device_id, sync_dir, claude_quota = sys.argv[1:5]
    if claude_quota:
        os.environ["TOKEI_CLAUDE_QUOTA_JSON"] = claude_quota
    spec = importlib.util.spec_from_file_location("tokei_usage_sync", script_path)
    if spec is None or spec.loader is None:
        raise SystemExit(1)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module._load_tokei_config = lambda: {
        "device_id": device_id,
        "sync_dir": sync_dir,
    }
    raise SystemExit(module.write_sync_snapshot())
    """

    static func syncSnapshotCommand(deviceID: String, syncDir: String) -> SyncCommand {
        let claudeQuota = nativeClaudeQuotaJSON() ?? ""
        if pythonPath == "/usr/bin/env" {
            return SyncCommand(
                executable: "/usr/bin/env",
                arguments: [
                    "python3", "-c", syncSnapshotPython,
                    scriptPath, deviceID, syncDir, claudeQuota,
                ],
                supervisorExecutable: "/usr/bin/env",
                supervisorArguments: ["python3"]
            )
        }
        return SyncCommand(
            executable: pythonPath,
            arguments: [
                "-c", syncSnapshotPython,
                scriptPath, deviceID, syncDir, claudeQuota,
            ],
            supervisorExecutable: pythonPath
        )
    }

    static func runScriptRaw(args: [String] = ["--json", "--no-sync-snapshot"], timeout: TimeInterval = 8) -> ScriptResult {
        let deepSeekSessions = prepareDeepSeekHarnessSessions()
        let proc = Process()
        if pythonPath == "/usr/bin/env" {
            proc.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            proc.arguments = ["python3", scriptPath] + args
        } else {
            proc.executableURL = URL(fileURLWithPath: pythonPath)
            proc.arguments = [scriptPath] + args
        }
        var environment = ProcessInfo.processInfo.environment
        environment["TOKEI_DSH_DECOMPRESSED_DIR"] = deepSeekSessions.path
        environment["TOKEI_GROK_BOT_HELPER"] =
            GrokBotHelperManager.resolvedHelperURL()?.path ?? Bundle.main.executablePath
        if let json = nativeClaudeQuotaJSON() {
            environment["TOKEI_CLAUDE_QUOTA_JSON"] = json
        } else {
            environment.removeValue(forKey: "TOKEI_CLAUDE_QUOTA_JSON")
        }
        for (key, value) in ProviderCredentialStore.environmentOverrides() {
            environment[key] = value
        }
        proc.environment = environment
        let outPipe = Pipe()
        let errPipe = Pipe()
        proc.standardOutput = outPipe
        proc.standardError = errPipe
        let started = Date()
        do {
            try proc.run()
        } catch {
            return ScriptResult(stdout: "", stderr: error.localizedDescription, exitCode: -1,
                                elapsed: Date().timeIntervalSince(started), timedOut: false)
        }

        var timedOut = false
        let killer = DispatchWorkItem {
            if proc.isRunning {
                timedOut = true
                proc.terminate()
            }
        }
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + timeout, execute: killer)

        let outData = outPipe.fileHandleForReading.readDataToEndOfFile()
        let errData = errPipe.fileHandleForReading.readDataToEndOfFile()
        proc.waitUntilExit()
        killer.cancel()

        return ScriptResult(stdout: String(data: outData, encoding: .utf8) ?? "",
                            stderr: String(data: errData, encoding: .utf8) ?? "",
                            exitCode: proc.terminationStatus,
                            elapsed: Date().timeIntervalSince(started),
                            timedOut: timedOut)
    }
}
