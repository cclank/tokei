import Foundation

private final class ClaudeQuotaNoRedirectDelegate: NSObject, URLSessionTaskDelegate {
    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest,
        completionHandler: @escaping (URLRequest?) -> Void
    ) {
        completionHandler(nil)
    }
}

enum ClaudeCLIQuotaBridge {
    struct Credential: Equatable {
        let accessToken: String
        let expiresAtMilliseconds: Int64?
    }

    enum RequestResult {
        case success([String: Any])
        case rateLimited(retryAfter: Int?)
        case failure
    }

    private struct Snapshot: Codable, Equatable {
        var q5: Double?
        var q5Reset: Int?
        var q7: Double?
        var q7Reset: Int?
        var qf: Double?
        var qfReset: Int?
        var updated: Int
    }

    private struct State: Codable {
        var version = 1
        var fetchedAt = 0
        var failedAt = 0
        var blockedUntil: Int?
        var snapshot: Snapshot?
    }

    private static let lock = NSLock()
    private static let refreshInterval = 5 * 60
    // 额度耗尽、还没到重置时刻时放慢到每小时查一次。不一直睡到重置：
    // 提前重置和升级套餐要靠这次复查才看得到。
    private static let exhaustedRefreshInterval = 60 * 60
    private static let staleInterval = 30 * 60
    private static let maxCredentialBytes = 1024 * 1024
    private static let maxResponseBytes = 1024 * 1024
    private static let betaHeader = "oauth-2025-04-20"
    private static let fallbackClaudeCodeVersion = "2.1.0"
    private static let endpoint = URL(
        string: "https://api.anthropic.com/api/oauth/usage?at_wall=1&skip_spend=1"
    )!
    private static let claudeCodeVersion = detectClaudeCodeVersion() ?? fallbackClaudeCodeVersion

    private static var cacheURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".tokei/claude_cli_quota_cache.json")
    }

    static func fetchQuota(now: Date = Date()) -> [String: Any]? {
        lock.lock()
        defer { lock.unlock() }
        return fetchQuota(
            nowEpoch: Int(now.timeIntervalSince1970),
            cacheURL: cacheURL,
            credentialLoader: loadCredential,
            requester: requestQuota
        )
    }

    static func fetchQuota(
        nowEpoch: Int,
        cacheURL: URL,
        credentialLoader: () -> Credential?,
        requester: (String) -> RequestResult
    ) -> [String: Any]? {
        var state = loadState(from: cacheURL)
        if let snapshot = state.snapshot {
            let interval = isExhausted(snapshot, nowEpoch: nowEpoch)
                ? exhaustedRefreshInterval : refreshInterval
            let fetchedAge = nowEpoch - state.fetchedAt
            if -300...interval ~= fetchedAge,
               !resetReached(snapshot, nowEpoch: nowEpoch) {
                return dictionary(from: snapshot, nowEpoch: nowEpoch)
            }
        }

        if let blockedUntil = state.blockedUntil, blockedUntil > nowEpoch {
            return state.snapshot.map { dictionary(from: $0, nowEpoch: nowEpoch) }
        }

        let failedAge = nowEpoch - state.failedAt
        if state.failedAt > 0, -300...refreshInterval ~= failedAge {
            return state.snapshot.map { dictionary(from: $0, nowEpoch: nowEpoch) }
        }

        guard let credential = credentialLoader(),
              credentialIsUsable(credential, nowEpoch: nowEpoch) else {
            state.failedAt = nowEpoch
            state.blockedUntil = nil
            saveState(state, to: cacheURL)
            return state.snapshot.map { dictionary(from: $0, nowEpoch: nowEpoch) }
        }

        let requestResult = requester(credential.accessToken)
        let payload: [String: Any]
        switch requestResult {
        case let .success(value):
            payload = value
        case let .rateLimited(retryAfter):
            state.failedAt = nowEpoch
            state.blockedUntil = max(nowEpoch + refreshInterval, retryAfter ?? 0)
            saveState(state, to: cacheURL)
            return state.snapshot.map { dictionary(from: $0, nowEpoch: nowEpoch) }
        case .failure:
            state.failedAt = nowEpoch
            state.blockedUntil = nil
            saveState(state, to: cacheURL)
            return state.snapshot.map { dictionary(from: $0, nowEpoch: nowEpoch) }
        }

        guard let snapshot = snapshot(from: payload, updated: nowEpoch) else {
            state.failedAt = nowEpoch
            state.blockedUntil = nil
            saveState(state, to: cacheURL)
            return state.snapshot.map { dictionary(from: $0, nowEpoch: nowEpoch) }
        }

        state.fetchedAt = nowEpoch
        state.failedAt = 0
        state.blockedUntil = nil
        state.snapshot = snapshot
        saveState(state, to: cacheURL)
        return dictionary(from: snapshot, nowEpoch: nowEpoch)
    }

    private static func loadCredential() -> Credential? {
        let executable = "/usr/bin/security"
        guard FileManager.default.isExecutableFile(atPath: executable) else { return nil }

        let process = Process()
        let output = Pipe()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = [
            "find-generic-password", "-s", "Claude Code-credentials", "-w",
        ]
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        let finished = DispatchSemaphore(value: 0)
        process.terminationHandler = { _ in finished.signal() }
        do {
            try process.run()
        } catch {
            return nil
        }
        guard finished.wait(timeout: .now() + 3) == .success else {
            process.terminate()
            return nil
        }
        let data = output.fileHandleForReading.readDataToEndOfFile()
        guard process.terminationStatus == 0,
              !data.isEmpty,
              data.count <= maxCredentialBytes,
              let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let oauth = root["claudeAiOauth"] as? [String: Any],
              let token = oauth["accessToken"] as? String,
              !token.isEmpty,
              token.utf8.count <= 32_768,
              token.rangeOfCharacter(from: .whitespacesAndNewlines) == nil else { return nil }
        let rawExpiry = (oauth["expiresAt"] as? NSNumber)?.int64Value
        let expiry = rawExpiry.map { $0 < 10_000_000_000 ? $0 * 1000 : $0 }
        return Credential(accessToken: token, expiresAtMilliseconds: expiry)
    }

    private static func requestQuota(accessToken: String) -> RequestResult {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.urlCache = nil
        configuration.httpCookieStorage = nil
        configuration.httpShouldSetCookies = false
        configuration.timeoutIntervalForRequest = 6
        configuration.timeoutIntervalForResource = 8
        let delegate = ClaudeQuotaNoRedirectDelegate()
        let session = URLSession(
            configuration: configuration,
            delegate: delegate,
            delegateQueue: nil
        )
        defer { session.invalidateAndCancel() }

        let request = makeRequest(
            accessToken: accessToken,
            claudeVersion: claudeCodeVersion
        )

        let finished = DispatchSemaphore(value: 0)
        var responseData: Data?
        var response: HTTPURLResponse?
        let task = session.dataTask(with: request) { data, urlResponse, _ in
            responseData = data
            response = urlResponse as? HTTPURLResponse
            finished.signal()
        }
        task.resume()
        guard finished.wait(timeout: .now() + 9) == .success else {
            task.cancel()
            return .failure
        }
        guard let response,
              response.url?.scheme?.lowercased() == "https",
              response.url?.host?.lowercased() == "api.anthropic.com"
        else { return .failure }
        if response.statusCode == 429 {
            return .rateLimited(
                retryAfter: retryAfterEpoch(
                    response.value(forHTTPHeaderField: "Retry-After"),
                    nowEpoch: Int(Date().timeIntervalSince1970)
                )
            )
        }
        guard response.statusCode == 200,
              let responseData,
              !responseData.isEmpty,
              responseData.count <= maxResponseBytes,
              let payload = try? JSONSerialization.jsonObject(with: responseData) as? [String: Any]
        else { return .failure }
        return .success(payload)
    }

    static func makeRequest(accessToken: String, claudeVersion: String?) -> URLRequest {
        var request = URLRequest(url: endpoint)
        request.httpMethod = "GET"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("no-store", forHTTPHeaderField: "Cache-Control")
        request.setValue(betaHeader, forHTTPHeaderField: "anthropic-beta")
        let version = normalizedClaudeCodeVersion(claudeVersion) ?? fallbackClaudeCodeVersion
        request.setValue("claude-code/\(version)", forHTTPHeaderField: "User-Agent")
        return request
    }

    static func retryAfterEpoch(_ raw: String?, nowEpoch: Int) -> Int? {
        guard let value = raw?.trimmingCharacters(in: .whitespacesAndNewlines),
              !value.isEmpty else { return nil }
        if let seconds = TimeInterval(value), seconds >= 0 {
            return nowEpoch + Int(seconds.rounded(.up))
        }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "EEE',' dd MMM yyyy HH':'mm':'ss zzz"
        return formatter.date(from: value).map { Int($0.timeIntervalSince1970) }
    }

    private static func normalizedClaudeCodeVersion(_ raw: String?) -> String? {
        guard let raw = raw?.trimmingCharacters(in: .whitespacesAndNewlines),
              let token = raw.split(whereSeparator: \.isWhitespace).first.map(String.init),
              token.count <= 64,
              token.range(
                  of: #"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$"#,
                  options: .regularExpression
              ) != nil else { return nil }
        return token
    }

    private static func detectClaudeCodeVersion() -> String? {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let candidates = [
            "\(home)/.local/bin/claude",
            "\(home)/.claude/local/claude",
            "/opt/homebrew/bin/claude",
            "/usr/local/bin/claude",
        ]
        guard let executable = candidates.first(where: {
            FileManager.default.isExecutableFile(atPath: $0)
        }) else { return nil }

        let process = Process()
        let output = Pipe()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = ["--version"]
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        let finished = DispatchSemaphore(value: 0)
        process.terminationHandler = { _ in finished.signal() }
        do {
            try process.run()
        } catch {
            return nil
        }
        guard finished.wait(timeout: .now() + 2) == .success else {
            process.terminate()
            return nil
        }
        let data = output.fileHandleForReading.readDataToEndOfFile()
        guard process.terminationStatus == 0,
              !data.isEmpty,
              data.count <= 4096,
              let value = String(data: data, encoding: .utf8) else { return nil }
        return normalizedClaudeCodeVersion(value)
    }

    private static func credentialIsUsable(_ credential: Credential, nowEpoch: Int) -> Bool {
        guard let expiry = credential.expiresAtMilliseconds else { return true }
        return expiry > Int64(nowEpoch + 30) * 1000
    }

    private static func snapshot(from payload: [String: Any], updated: Int) -> Snapshot? {
        let fiveHour = payload["five_hour"] as? [String: Any] ?? [:]
        let sevenDay = payload["seven_day"] as? [String: Any] ?? [:]
        let fable = (payload["limits"] as? [[String: Any]])?.first { limit in
            guard limit["kind"] as? String == "weekly_scoped",
                  let scope = limit["scope"] as? [String: Any],
                  let model = scope["model"] as? [String: Any],
                  let name = model["display_name"] as? String else { return false }
            return name.caseInsensitiveCompare("Fable") == .orderedSame
        } ?? [:]
        let value = Snapshot(
            q5: percentage(fiveHour["utilization"]),
            q5Reset: isoToEpoch(fiveHour["resets_at"] as? String),
            q7: percentage(sevenDay["utilization"]),
            q7Reset: isoToEpoch(sevenDay["resets_at"] as? String),
            qf: percentage(fable["percent"]),
            qfReset: isoToEpoch(fable["resets_at"] as? String),
            updated: updated
        )
        return value.q5 != nil || value.q7 != nil || value.qf != nil ? value : nil
    }

    private static func percentage(_ raw: Any?) -> Double? {
        guard let value = (raw as? NSNumber)?.doubleValue,
              value.isFinite,
              (0...100).contains(value) else { return nil }
        return value
    }

    private static func isoToEpoch(_ raw: String?) -> Int? {
        guard let raw else { return nil }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: raw) { return Int(date.timeIntervalSince1970) }
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: raw).map { Int($0.timeIntervalSince1970) }
    }

    // 只看 5h 和周额度：模型专属窗口用尽后其他模型还能用，读数还会变。
    private static func isExhausted(_ snapshot: Snapshot, nowEpoch: Int) -> Bool {
        [(snapshot.q5, snapshot.q5Reset), (snapshot.q7, snapshot.q7Reset)]
            .contains { used, reset in
                guard let used, let reset else { return false }
                return used >= 100.0 && reset > nowEpoch
            }
    }

    private static func resetReached(_ snapshot: Snapshot, nowEpoch: Int) -> Bool {
        [snapshot.q5Reset, snapshot.q7Reset, snapshot.qfReset]
            .compactMap { $0 }
            .contains { $0 <= nowEpoch }
    }

    private static func dictionary(from snapshot: Snapshot, nowEpoch: Int) -> [String: Any] {
        var result: [String: Any] = ["q_updated": snapshot.updated]
        if let value = snapshot.q5 { result["q5"] = value }
        if let value = snapshot.q5Reset { result["q5_reset"] = value }
        if let value = snapshot.q7 { result["q7"] = value }
        if let value = snapshot.q7Reset { result["q7_reset"] = value }
        if let value = snapshot.qf { result["qf"] = value }
        if let value = snapshot.qfReset { result["qf_reset"] = value }
        let age = nowEpoch - snapshot.updated
        // 耗尽期间读数是故意放慢刷新的，过期线跟着放宽到两个复查间隔。
        let staleAfter = isExhausted(snapshot, nowEpoch: nowEpoch)
            ? 2 * exhaustedRefreshInterval : staleInterval
        let sourceStale = snapshot.updated <= 0 || age > staleAfter || age < -300
        result["q5_stale"] = snapshot.q5 != nil &&
            (sourceStale || (snapshot.q5Reset.map { $0 <= nowEpoch } ?? false))
        result["q7_stale"] = snapshot.q7 != nil &&
            (sourceStale || (snapshot.q7Reset.map { $0 <= nowEpoch } ?? false))
        result["qf_stale"] = snapshot.qf != nil &&
            (sourceStale || (snapshot.qfReset.map { $0 <= nowEpoch } ?? false))
        return result
    }

    private static func loadState(from url: URL) -> State {
        guard let data = try? Data(contentsOf: url),
              data.count <= maxResponseBytes,
              let state = try? JSONDecoder().decode(State.self, from: data),
              state.version == 1 else { return State() }
        return state
    }

    private static func saveState(_ state: State, to url: URL) {
        do {
            try FileManager.default.createDirectory(
                at: url.deletingLastPathComponent(),
                withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700]
            )
            let data = try JSONEncoder().encode(state)
            try data.write(to: url, options: .atomic)
            try FileManager.default.setAttributes(
                [.posixPermissions: 0o600],
                ofItemAtPath: url.path
            )
        } catch {
            return
        }
    }
}
