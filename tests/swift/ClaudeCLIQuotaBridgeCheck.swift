import Foundation

private enum TestFailure: Error {
    case assertion(String)
}

@main
struct ClaudeCLIQuotaBridgeCheck {
    static func main() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("tokei-claude-cli-quota-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }

        try testSuccessAndCache(root: root)
        try testResetForcesRefresh(root: root)
        try testExhaustedQuotaSleepsUntilReset(root: root)
        try testFailureKeepsSnapshotAndBacksOff(root: root)
        try testRateLimitHonorsRetryAfter(root: root)
        try testExpiredCredentialIsRejected(root: root)
        try testRequestHeaders()
        print("claude cli quota bridge checks passed")
    }

    private static func testSuccessAndCache(root: URL) throws {
        let cache = root.appendingPathComponent("success.json")
        let now = 1_800_000_000
        let token = "test-access-token-never-persist"
        let credential = ClaudeCLIQuotaBridge.Credential(
            accessToken: token,
            expiresAtMilliseconds: Int64(now + 3600) * 1000
        )
        var credentialReads = 0
        var requests = 0
        var receivedToken: String?
        let first = ClaudeCLIQuotaBridge.fetchQuota(
            nowEpoch: now,
            cacheURL: cache,
            credentialLoader: {
                credentialReads += 1
                return credential
            },
            requester: { tokenValue in
                requests += 1
                receivedToken = tokenValue
                return .success(payload(now: now, q5: 12.5, q7: 34, qf: 56))
            }
        )
        try expect(number(first?["q5"]) == 12.5, "five-hour quota should be parsed")
        try expect(number(first?["q7"]) == 34, "weekly quota should be parsed")
        try expect(number(first?["qf"]) == 56, "Fable quota should be parsed")
        try expect(receivedToken == token, "request must use the access token in memory")

        let second = ClaudeCLIQuotaBridge.fetchQuota(
            nowEpoch: now + 60,
            cacheURL: cache,
            credentialLoader: {
                credentialReads += 1
                return credential
            },
            requester: { _ in
                requests += 1
                return .failure
            }
        )
        try expect(number(second?["q7"]) == 34, "fresh cache should be reused")
        try expect(credentialReads == 1, "fresh cache should avoid another Keychain read")
        try expect(requests == 1, "fresh cache should avoid another network request")

        let cacheText = try String(contentsOf: cache, encoding: .utf8)
        try expect(!cacheText.contains(token), "cache must not contain the access token")
        let mode = try FileManager.default.attributesOfItem(atPath: cache.path)[.posixPermissions]
        try expect((mode as? NSNumber)?.intValue == 0o600, "quota cache must be owner-only")
    }

    private static func testResetForcesRefresh(root: URL) throws {
        let cache = root.appendingPathComponent("reset.json")
        let now = 1_800_100_000
        let credential = validCredential(now: now)
        var requests = 0
        let firstPayload = payload(now: now, q5: 90, q7: 20, qf: nil, resetOffset: 20)
        let secondPayload = payload(now: now, q5: 2, q7: 20, qf: nil, resetOffset: 3600)
        _ = ClaudeCLIQuotaBridge.fetchQuota(
            nowEpoch: now,
            cacheURL: cache,
            credentialLoader: { credential },
            requester: { _ in
                requests += 1
                return .success(firstPayload)
            }
        )
        let refreshed = ClaudeCLIQuotaBridge.fetchQuota(
            nowEpoch: now + 21,
            cacheURL: cache,
            credentialLoader: { credential },
            requester: { _ in
                requests += 1
                return .success(secondPayload)
            }
        )
        try expect(number(refreshed?["q5"]) == 2, "a reached reset must bypass the TTL")
        try expect(requests == 2, "reset should trigger one immediate refresh")
    }

    private static func testExhaustedQuotaSleepsUntilReset(root: URL) throws {
        let cache = root.appendingPathComponent("exhausted.json")
        let now = 1_800_150_000
        let credential = validCredential(now: now)
        var requests = 0
        let exhaustedPayload = payload(now: now, q5: 100, q7: 50, qf: nil, resetOffset: 3600)
        _ = ClaudeCLIQuotaBridge.fetchQuota(
            nowEpoch: now,
            cacheURL: cache,
            credentialLoader: { credential },
            requester: { _ in
                requests += 1
                return .success(exhaustedPayload)
            }
        )
        try expect(requests == 1, "initial fetch should make request")

        let sleeping = ClaudeCLIQuotaBridge.fetchQuota(
            nowEpoch: now + 600,
            cacheURL: cache,
            credentialLoader: { credential },
            requester: { _ in
                requests += 1
                return .failure
            }
        )
        try expect(number(sleeping?["q5"]) == 100, "exhausted cache should be reused")
        try expect(sleeping?["q5_stale"] as? Bool == false, "reused exhausted cache must not look stale")
        try expect(requests == 1, "exhausted quota must sleep until reset and avoid network requests")

        let stillSleeping = ClaudeCLIQuotaBridge.fetchQuota(
            nowEpoch: now + 3000,
            cacheURL: cache,
            credentialLoader: { credential },
            requester: { _ in
                requests += 1
                return .failure
            }
        )
        try expect(requests == 1, "exhausted quota must keep sleeping past the stale interval")
        try expect(stillSleeping?["q5_stale"] as? Bool == false, "sleeping snapshot must not look stale")
        try expect(stillSleeping?["q7_stale"] as? Bool == false, "sleeping snapshot must not look stale")

        let freshPayload = payload(now: now + 3601, q5: 10, q7: 50, qf: nil, resetOffset: 3600)
        let renewedCredential = validCredential(now: now + 3601)
        let resetRefreshed = ClaudeCLIQuotaBridge.fetchQuota(
            nowEpoch: now + 3601,
            cacheURL: cache,
            credentialLoader: { renewedCredential },
            requester: { _ in
                requests += 1
                return .success(freshPayload)
            }
        )
        try expect(number(resetRefreshed?["q5"]) == 10, "reset should trigger fresh request")
        try expect(requests == 2, "must query once reset is reached")
    }

    private static func testFailureKeepsSnapshotAndBacksOff(root: URL) throws {
        let cache = root.appendingPathComponent("failure.json")
        let now = 1_800_200_000
        let credential = validCredential(now: now)
        _ = ClaudeCLIQuotaBridge.fetchQuota(
            nowEpoch: now,
            cacheURL: cache,
            credentialLoader: { credential },
            requester: { _ in .success(payload(now: now, q5: 7, q7: 19, qf: nil)) }
        )

        var failedRequests = 0
        let fallback = ClaudeCLIQuotaBridge.fetchQuota(
            nowEpoch: now + 301,
            cacheURL: cache,
            credentialLoader: { credential },
            requester: { _ in
                failedRequests += 1
                return .failure
            }
        )
        let backedOff = ClaudeCLIQuotaBridge.fetchQuota(
            nowEpoch: now + 310,
            cacheURL: cache,
            credentialLoader: { credential },
            requester: { _ in
                failedRequests += 1
                return .failure
            }
        )
        try expect(number(fallback?["q7"]) == 19, "a failed request must retain prior quota")
        try expect(number(backedOff?["q7"]) == 19, "backoff must retain prior quota")
        try expect(failedRequests == 1, "failed requests should be backed off for five minutes")
    }

    private static func testRateLimitHonorsRetryAfter(root: URL) throws {
        let cache = root.appendingPathComponent("rate-limit.json")
        let now = 1_800_250_000
        let credential = validCredential(now: now)
        _ = ClaudeCLIQuotaBridge.fetchQuota(
            nowEpoch: now,
            cacheURL: cache,
            credentialLoader: { credential },
            requester: { _ in .success(payload(now: now, q5: 8, q7: 21, qf: nil)) }
        )

        var requests = 0
        let retryAfter = now + 1_200
        _ = ClaudeCLIQuotaBridge.fetchQuota(
            nowEpoch: now + 301,
            cacheURL: cache,
            credentialLoader: { credential },
            requester: { _ in
                requests += 1
                return .rateLimited(retryAfter: retryAfter)
            }
        )
        let blocked = ClaudeCLIQuotaBridge.fetchQuota(
            nowEpoch: now + 900,
            cacheURL: cache,
            credentialLoader: { credential },
            requester: { _ in
                requests += 1
                return .failure
            }
        )
        let refreshed = ClaudeCLIQuotaBridge.fetchQuota(
            nowEpoch: retryAfter + 1,
            cacheURL: cache,
            credentialLoader: { credential },
            requester: { _ in
                requests += 1
                return .success(payload(now: now, q5: 3, q7: 9, qf: nil))
            }
        )
        try expect(number(blocked?["q7"]) == 21, "rate limiting must retain prior quota")
        try expect(number(refreshed?["q7"]) == 9, "request should resume after Retry-After")
        try expect(requests == 2, "Retry-After should suppress intermediate requests")
    }

    private static func testExpiredCredentialIsRejected(root: URL) throws {
        let cache = root.appendingPathComponent("expired.json")
        let now = 1_800_300_000
        var requests = 0
        let result = ClaudeCLIQuotaBridge.fetchQuota(
            nowEpoch: now,
            cacheURL: cache,
            credentialLoader: {
                ClaudeCLIQuotaBridge.Credential(
                    accessToken: "expired",
                    expiresAtMilliseconds: Int64(now - 1) * 1000
                )
            },
            requester: { _ in
                requests += 1
                return .success(payload(now: now, q5: 1, q7: 1, qf: nil))
            }
        )
        try expect(result == nil, "expired credentials should not produce quota")
        try expect(requests == 0, "expired credentials should not reach the network")
    }

    private static func testRequestHeaders() throws {
        let request = ClaudeCLIQuotaBridge.makeRequest(
            accessToken: "header-test-token",
            claudeVersion: "2.1.258 (Claude Code)"
        )
        try expect(
            request.value(forHTTPHeaderField: "anthropic-beta") == "oauth-2025-04-20",
            "OAuth usage request must include the current beta header"
        )
        try expect(
            request.value(forHTTPHeaderField: "User-Agent") == "claude-code/2.1.258",
            "OAuth usage request should identify the installed Claude Code version"
        )
        let fallback = ClaudeCLIQuotaBridge.makeRequest(
            accessToken: "header-test-token",
            claudeVersion: "invalid version"
        )
        try expect(
            fallback.value(forHTTPHeaderField: "User-Agent") == "claude-code/2.1.0",
            "invalid or missing versions should use the conservative fallback"
        )
        try expect(
            ClaudeCLIQuotaBridge.retryAfterEpoch("120", nowEpoch: 1_800_000_000) == 1_800_000_120,
            "Retry-After seconds should be parsed"
        )
    }

    private static func validCredential(now: Int) -> ClaudeCLIQuotaBridge.Credential {
        ClaudeCLIQuotaBridge.Credential(
            accessToken: "valid-test-token",
            expiresAtMilliseconds: Int64(now + 3600) * 1000
        )
    }

    private static func payload(
        now: Int,
        q5: Double,
        q7: Double,
        qf: Double?,
        resetOffset: Int = 3600
    ) -> [String: Any] {
        let reset = ISO8601DateFormatter().string(
            from: Date(timeIntervalSince1970: TimeInterval(now + resetOffset))
        )
        var limits: [[String: Any]] = []
        if let qf {
            limits.append([
                "kind": "weekly_scoped",
                "percent": qf,
                "resets_at": reset,
                "scope": ["model": ["display_name": "Fable"]],
            ])
        }
        return [
            "five_hour": ["utilization": q5, "resets_at": reset],
            "seven_day": ["utilization": q7, "resets_at": reset],
            "limits": limits,
        ]
    }

    private static func number(_ value: Any?) -> Double? {
        (value as? NSNumber)?.doubleValue
    }

    private static func expect(
        _ condition: @autoclosure () throws -> Bool,
        _ message: String
    ) throws {
        if try !condition() {
            throw TestFailure.assertion(message)
        }
    }
}
