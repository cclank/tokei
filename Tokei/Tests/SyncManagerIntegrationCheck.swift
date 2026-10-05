import Foundation
import Darwin

// SyncManager's peer dashboard payload references Codable types defined by the UI.
// The standalone integration binary only needs their decoding shape names.
struct DailyCost: Codable {}
struct WrappedData: Codable {}

private enum CheckError: Error, CustomStringConvertible {
    case failed(String)

    var description: String {
        switch self {
        case .failed(let message): return message
        }
    }
}

private final class ResultBox {
    var value: GitSyncResult?
}

@main
private enum SyncManagerIntegrationCheck {
    private struct CommandResult {
        var status: Int32
        var output: String
    }

    private struct ConflictedRebase {
        var originalHead: String
        var onto: String
    }

    private static var roots: [URL] = []

    static func main() throws {
        if CommandLine.arguments.count == 2,
           CommandLine.arguments[1] == "--isolated-config-identity-parent-check" {
            try testSaveConfigRejectsDeviceIdentityChangeInIsolatedHome()
            print("isolated config identity parent check passed")
            return
        }
        if CommandLine.arguments.count == 3,
           CommandLine.arguments[1] == "--isolated-config-identity-check" {
            try runIsolatedConfigIdentityCheck(
                expectedHome: URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
            )
            return
        }
        defer {
            for root in roots {
                try? FileManager.default.removeItem(at: root)
            }
        }
        try testQwenWorkAbsoluteQuotaDecoding()
        try testPeerClaudeQuotaAdoptionAndPrecedence()
        try testPeerClaudeQuotaFreshnessIsRecomputedAtMergeTime()
        try testPeerClaudeQuotaIsReplacedAsOneGroup()
        try testPeerClaudeQuotaTieBreakAndMultiplePeers()
        try testForeignRebaseStopsBeforeSnapshotOrCommit()
        try testDetachedHeadStopsBeforeSnapshot()
        try testSecondTransactionCannotEnterLockedRepository()
        try testPushRaceRetriesAndPreservesBothDevices()
        try testAheadCommitChangingPeerIsRejectedBeforeSnapshot()
        try testMismatchedOwnedMarkerPreservesRealRebaseState()
        try testMatchingOwnedMarkerPreservesRealRebaseState()
        try testPythonSupervisorTimesOutAndTerminatesSnapshot()
        try testConfiguredPrePushHookDoesNotRunDuringSync()
        try testReferenceTransactionHookDoesNotRunDuringSync()
        try testRequiredCommitSigningDoesNotRunDuringSync()
        try testPostAuditHeadDriftCannotPushUnauditedCommit()
        try testSupervisorKillsTermIgnoringGrandchildAfterLeaderExit()
        try testSaveConfigRejectsDeviceIdentityChangeInIsolatedHome()
        try testInheritedGitDirectoryCannotRedirectSync()
        try testPeerLoaderReportsBadFilesIndependently()
        print("SyncManager integration checks passed: 21")
    }

    private static func testQwenWorkAbsoluteQuotaDecoding() throws {
        let payload = #"""
        {
          "available": true,
          "remaining": 2100,
          "remaining_pct": null,
          "exceeded": false,
          "is_team": false,
          "segments": [{
            "id": "plan",
            "kind": "plan_credits",
            "total": 0,
            "used": 0,
            "remaining": 2100,
            "percentage_used": null,
            "unit": "credits"
          }],
          "source": "mcp",
          "updated": 1786650000,
          "stale": false
        }
        """#
        let quota = try JSONDecoder().decode(QwenWorkQuota.self, from: Data(payload.utf8))
        try expect(quota.available, "QwenWork absolute quota did not decode as available")
        try expect(quota.remaining == 2100, "QwenWork remaining credits changed during decode")
        try expect(quota.remaining_pct == nil, "missing QwenWork percentage became a value")
        try expect(quota.segments.count == 1 && quota.segments[0].total == 0
                       && quota.segments[0].percentage_used == nil,
                   "QwenWork total=0 absolute-balance contract changed")
    }

    // MARK: - Peer Claude quota
    //
    // 这几条检查先按"会怎么坏"来写：
    //   本机没有额度却没采用 peer 的；peer 更旧却盖掉了本机更新的；peer 更新却没采用；
    //   peer 无额度却把本机的额度清成空；沿用 peer 快照写入时算好的过期标记；
    //   reset 时刻已过却没标过期；两个来源的字段混在一起；多个 peer 的结果依赖顺序；
    //   采用额度的同时把 token 合并弄丢。

    private static let quotaNow = Date(timeIntervalSince1970: 1_800_000_000)
    private static var quotaNowSeconds: Int { Int(quotaNow.timeIntervalSince1970) }

    private static func testPeerClaudeQuotaAdoptionAndPrecedence() throws {
        let fresh = quotaNowSeconds - 60
        let local = try usage(input: 100) { _ in }
        let peerUsage = try usage(input: 50) {
            $0.q5 = 40; $0.q5_reset = quotaNowSeconds + 3600
            $0.q7 = 60; $0.q7_reset = quotaNowSeconds + 86400
            $0.qf = 20; $0.qf_reset = quotaNowSeconds + 86400
            $0.q_updated = fresh
        }

        // 本机没有额度：采用 peer 的；token 照常相加。
        let adopted = SyncManager.merge(local: local, peers: [peer("cloud", peerUsage)], now: quotaNow)
        try expect(adopted.claude.q5 == 40 && adopted.claude.q7 == 60 && adopted.claude.qf == 20,
                   "local without quota did not adopt the peer quota")
        try expect(adopted.claude.q_updated == fresh, "adopted quota lost its q_updated")
        try expect(adopted.claude.q5_stale == false && adopted.claude.q7_stale == false
                       && adopted.claude.qf_stale == false,
                   "fresh peer quota was flagged stale")
        try expect(adopted.claude.ranges.today.in == 150,
                   "adopting the quota broke token merging: \(adopted.claude.ranges.today.in)")

        // peer 没有任何额度：不采用，也不能把本机的清空。
        let localWithQuota = try usage { $0.q5 = 10; $0.q7 = 20; $0.q_updated = fresh }
        let noQuotaPeer = try usage { $0.q_updated = fresh + 100 } // 更新，但三个额度都没有值
        let kept = SyncManager.merge(local: localWithQuota, peers: [peer("cloud", noQuotaPeer)], now: quotaNow)
        try expect(kept.claude.q5 == 10 && kept.claude.q7 == 20 && kept.claude.q_updated == fresh,
                   "peer without quota overwrote the local quota")

        // peer 更新：采用。
        let olderLocal = try usage { $0.q5 = 10; $0.q7 = 20; $0.q_updated = fresh - 600 }
        let newerPeer = SyncManager.merge(local: olderLocal, peers: [peer("cloud", peerUsage)], now: quotaNow)
        try expect(newerPeer.claude.q5 == 40 && newerPeer.claude.q_updated == fresh,
                   "newer peer quota was not adopted")

        // peer 更旧：不采用。
        let newerLocal = try usage { $0.q5 = 10; $0.q7 = 20; $0.q_updated = fresh + 30 }
        let olderPeer = SyncManager.merge(local: newerLocal, peers: [peer("cloud", peerUsage)], now: quotaNow)
        try expect(olderPeer.claude.q5 == 10 && olderPeer.claude.q7 == 20
                       && olderPeer.claude.q_updated == fresh + 30,
                   "older peer quota replaced the newer local quota")
    }

    private static func testPeerClaudeQuotaFreshnessIsRecomputedAtMergeTime() throws {
        let local = try usage { _ in }

        // 快照写入时标的是"没过期"，但已经是 31 分钟前的数据：合并时按现在重算成过期。
        let aged = try usage {
            $0.q5 = 40; $0.q5_reset = quotaNowSeconds + 3600; $0.q5_stale = false
            $0.q7 = 60; $0.q7_reset = quotaNowSeconds + 86400; $0.q7_stale = false
            $0.qf = nil; $0.qf_stale = false
            $0.q_updated = quotaNowSeconds - 31 * 60
        }
        let old = SyncManager.merge(local: local, peers: [peer("cloud", aged)], now: quotaNow)
        try expect(old.claude.q5 == 40, "stale peer quota was not adopted when local had none")
        try expect(old.claude.q5_stale == true && old.claude.q7_stale == true,
                   "peer quota older than 30 minutes was not flagged stale")
        try expect(old.claude.qf_stale == false, "a window without a value was flagged stale")

        // 29 分钟前：还算新。
        let almost = try usage {
            $0.q5 = 40; $0.q5_reset = quotaNowSeconds + 3600
            $0.q_updated = quotaNowSeconds - 29 * 60
        }
        let notYet = SyncManager.merge(local: local, peers: [peer("cloud", almost)], now: quotaNow)
        try expect(notYet.claude.q5_stale == false, "29-minute-old peer quota was flagged stale")

        // 快照里标了"过期"，现在看其实在 TTL 内：以现在为准，不沿用旧标记。
        let mislabeled = try usage {
            $0.q5 = 40; $0.q5_reset = quotaNowSeconds + 3600; $0.q5_stale = true
            $0.q_updated = quotaNowSeconds - 60
        }
        let relabeled = SyncManager.merge(local: local, peers: [peer("cloud", mislabeled)], now: quotaNow)
        try expect(relabeled.claude.q5_stale == false, "the peer's own stale flag was carried over")

        // 数据是新的，但 5 小时窗口的 reset 时刻已过：只有这个窗口过期。
        let resetPassed = try usage {
            $0.q5 = 90; $0.q5_reset = quotaNowSeconds - 1
            $0.q7 = 60; $0.q7_reset = quotaNowSeconds + 86400
            $0.q_updated = quotaNowSeconds - 60
        }
        let reset = SyncManager.merge(local: local, peers: [peer("cloud", resetPassed)], now: quotaNow)
        try expect(reset.claude.q5_stale == true, "q5 with a passed reset time was not flagged stale")
        try expect(reset.claude.q7_stale == false, "q7 was flagged stale by q5's reset time")

        // 没有 q_updated 的 peer 额度当作过期（和 Python 端一致）。
        let undated = try usage { $0.q5 = 40; $0.q5_reset = quotaNowSeconds + 3600 }
        let undatedMerged = SyncManager.merge(local: local, peers: [peer("cloud", undated)], now: quotaNow)
        try expect(undatedMerged.claude.q5_stale == true, "peer quota without q_updated was not flagged stale")
    }

    private static func testPeerClaudeQuotaIsReplacedAsOneGroup() throws {
        let fresh = quotaNowSeconds - 60
        // 本机：q5/q7/qf 都有，更旧。peer：只有 q7，更新。
        let local = try usage {
            $0.q5 = 11; $0.q5_reset = quotaNowSeconds + 111; $0.q5_stale = false
            $0.q7 = 22; $0.q7_reset = quotaNowSeconds + 222; $0.q7_stale = false
            $0.qf = 33; $0.qf_reset = quotaNowSeconds + 333; $0.qf_stale = false
            $0.q_updated = fresh - 300
        }
        let peerUsage = try usage {
            $0.q7 = 77; $0.q7_reset = quotaNowSeconds + 7777
            $0.q_updated = fresh
        }
        let merged = SyncManager.merge(local: local, peers: [peer("cloud", peerUsage)], now: quotaNow)
        let c = merged.claude
        try expect(c.q7 == 77 && c.q7_reset == quotaNowSeconds + 7777 && c.q_updated == fresh,
                   "peer quota group was not adopted")
        try expect(c.q5 == nil && c.q5_reset == nil && c.qf == nil && c.qf_reset == nil,
                   "local-only q5/qf fields were mixed into the adopted peer group: "
                       + "q5=\(String(describing: c.q5)) qf=\(String(describing: c.qf))")
        try expect(c.q5_stale == false && c.qf_stale == false,
                   "adopted group kept stale flags for windows it no longer has")
    }

    private static func testPeerClaudeQuotaTieBreakAndMultiplePeers() throws {
        let t = quotaNowSeconds - 60

        // q_updated 相同：本机已过期（reset 已过）、peer 没过期，才采用 peer。
        let staleLocal = try usage {
            $0.q5 = 10; $0.q5_reset = quotaNowSeconds - 10; $0.q5_stale = true; $0.q_updated = t
        }
        let freshPeer = try usage {
            $0.q5 = 55; $0.q5_reset = quotaNowSeconds + 3600; $0.q_updated = t
        }
        let swapped = SyncManager.merge(local: staleLocal, peers: [peer("cloud", freshPeer)], now: quotaNow)
        try expect(swapped.claude.q5 == 55, "tie with a stale local quota did not adopt the fresh peer")

        // q_updated 相同：本机没过期，不换。
        let freshLocal = try usage {
            $0.q5 = 10; $0.q5_reset = quotaNowSeconds + 3600; $0.q5_stale = false; $0.q_updated = t
        }
        let kept = SyncManager.merge(local: freshLocal, peers: [peer("cloud", freshPeer)], now: quotaNow)
        try expect(kept.claude.q5 == 10, "tie with a fresh local quota was replaced by the peer")

        // q_updated 相同：peer 自己已过期（reset 已过），也不换。
        let stalePeer = try usage {
            $0.q5 = 99; $0.q5_reset = quotaNowSeconds - 10; $0.q_updated = t
        }
        let keptAgain = SyncManager.merge(local: staleLocal, peers: [peer("cloud", stalePeer)], now: quotaNow)
        try expect(keptAgain.claude.q5 == 10, "tie with a stale peer replaced the local quota")

        // 多个 peer：谁最新用谁，和顺序无关。
        let oldest = try usage { $0.q5 = 1; $0.q_updated = t - 200 }
        let newest = try usage { $0.q5 = 2; $0.q_updated = t }
        let middle = try usage { $0.q5 = 3; $0.q_updated = t - 100 }
        let none = try usage { _ in }
        let forward = SyncManager.merge(local: none, peers: [peer("a", oldest), peer("b", newest), peer("c", middle)],
                                        now: quotaNow)
        let backward = SyncManager.merge(local: none, peers: [peer("c", middle), peer("b", newest), peer("a", oldest)],
                                         now: quotaNow)
        try expect(forward.claude.q5 == 2 && backward.claude.q5 == 2,
                   "multiple peers did not resolve to the newest quota: "
                       + "\(String(describing: forward.claude.q5)) / \(String(describing: backward.claude.q5))")
    }

    private static func peer(_ id: String, _ usage: Usage) -> PeerDevice {
        let bounds = SyncManager.currentRangeBounds(now: quotaNow)
            .reduce(into: [String: RangeBoundary]()) { out, item in out[item.key.rawValue] = item.value }
        return PeerDevice(deviceId: id, lastSync: quotaNow, usage: usage, dashboard: nil, rangeBounds: bounds)
    }

    private static func usage(input: Int = 0, claude edit: (inout ClaudeStat) -> Void) throws -> Usage {
        var value = try JSONDecoder().decode(Usage.self, from: Data(usageFixtureJSON(claudeInput: input).utf8))
        edit(&value.claude)
        return value
    }

    /// 只含 Usage 必填的 7 个工具，所有区间为零；Claude 的 today.in 可调，用来确认 token 仍在合并。
    private static func usageFixtureJSON(claudeInput: Int) -> String {
        func ranges(_ zero: String, today: String? = nil) -> String {
            let keys = ["today", "yesterday", "week", "last_week", "month", "year", "all"]
            let body = keys.map { "\"\($0)\": \($0 == "today" ? (today ?? zero) : zero)" }
            return "{" + body.joined(separator: ", ") + "}"
        }
        let claudeZero = #"{"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "cost": 0, "sessions": 0, "models": []}"#
        let claudeToday = #"{"hit": 0, "in": \#(claudeInput), "out": 0, "cr": 0, "cw": 0, "cost": 0, "sessions": 0, "models": []}"#
        let codexZero = #"{"hit": 0, "in": 0, "cached": 0, "out": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []}"#
        let geminiZero = #"{"hit": 0, "in": 0, "out": 0, "cached": 0, "thoughts": 0, "cost": 0, "sessions": 0, "models": []}"#
        let grokZero = #"{"tokens": 0, "sessions": 0}"#
        let hermesZero = #"{"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []}"#
        let openclawZero = #"{"tasks": 0, "completed": 0, "failed": 0, "models": []}"#
        let tokenZero = hermesZero
        return """
        {
          "claude": {"ranges": \(ranges(claudeZero, today: claudeToday)), "session_name": "", "session_total": 0},
          "codex": {"ranges": \(ranges(codexZero))},
          "gemini": {"ranges": \(ranges(geminiZero))},
          "grok": {"ranges": \(ranges(grokZero))},
          "hermes": {"ranges": \(ranges(hermesZero))},
          "openclaw": {"ranges": \(ranges(openclawZero))},
          "opencode": {"ranges": \(ranges(tokenZero))}
        }
        """
    }

    private static func testForeignRebaseStopsBeforeSnapshotOrCommit() throws {
        let fixture = try makeFixture(clones: ["client"])
        let repo = fixture.clones["client"]!
        let before = try git(["rev-parse", "HEAD"], at: repo).output
            .trimmingCharacters(in: .whitespacesAndNewlines)
        try FileManager.default.createDirectory(
            at: repo.appendingPathComponent(".git/rebase-merge"),
            withIntermediateDirectories: false
        )
        let sentinel = fixture.root.appendingPathComponent("foreign-snapshot-ran")

        let result = try synchronize(
            repo: repo,
            deviceID: "device-a",
            shell: "touch \(quote(sentinel.path)); printf '{}' > device-a.json"
        )

        try expect(result.code == .foreignOperation, "foreign rebase should be rejected: \(result.output)")
        try expect(!FileManager.default.fileExists(atPath: sentinel.path),
                   "snapshot ran before foreign rebase rejection")
        let after = try git(["rev-parse", "HEAD"], at: repo).output
            .trimmingCharacters(in: .whitespacesAndNewlines)
        try expect(after == before, "foreign rebase rejection changed HEAD")
    }

    private static func testDetachedHeadStopsBeforeSnapshot() throws {
        let fixture = try makeFixture(clones: ["client"])
        let repo = fixture.clones["client"]!
        _ = try git(["checkout", "--detach"], at: repo)
        let sentinel = fixture.root.appendingPathComponent("detached-snapshot-ran")

        let result = try synchronize(
            repo: repo,
            deviceID: "device-a",
            shell: "touch \(quote(sentinel.path)); printf '{}' > device-a.json"
        )

        try expect(result.code == .detachedHead, "detached HEAD should be rejected: \(result.output)")
        try expect(!FileManager.default.fileExists(atPath: sentinel.path),
                   "snapshot ran before detached HEAD rejection")
    }

    private static func testSecondTransactionCannotEnterLockedRepository() throws {
        let fixture = try makeFixture(clones: ["client"])
        let repo = fixture.clones["client"]!
        let started = fixture.root.appendingPathComponent("first-started")
        let release = fixture.root.appendingPathComponent("first-release")
        let secondRan = fixture.root.appendingPathComponent("second-ran")
        let first = ResultBox()
        let firstManager = manager(repo: repo, deviceID: "device-a")

        firstManager.synchronize(snapshotCommand: SyncCommand(
            executable: "/bin/sh",
            arguments: ["-c", "touch \(quote(started.path)); while [ ! -f \(quote(release.path)) ]; do sleep 0.05; done; printf '{\"_device\":\"device-a\",\"_ts\":1}' > device-a.json"],
            supervisorExecutable: "/usr/bin/python3"
        )) { first.value = $0 }
        try waitForFile(started)

        let second = try synchronize(
            repo: repo,
            deviceID: "device-a",
            shell: "touch \(quote(secondRan.path)); printf '{}' > device-a.json"
        )

        try expect(second.code == .busy, "second transaction should report busy: \(second.output)")
        try expect(!FileManager.default.fileExists(atPath: secondRan.path),
                   "second snapshot ran without acquiring the lock")
        try Data().write(to: release)
        let firstResult = try waitForResult(first, timeout: 20)
        try expect(firstResult.code == .success, "first locked transaction failed: \(firstResult.output)")
    }

    private static func testPushRaceRetriesAndPreservesBothDevices() throws {
        let fixture = try makeFixture(clones: ["client-a", "client-b"])
        let clientA = fixture.clones["client-a"]!
        let clientB = fixture.clones["client-b"]!
        let started = fixture.root.appendingPathComponent("race-started")
        let release = fixture.root.appendingPathComponent("race-release")
        let first = ResultBox()
        let managerA = manager(repo: clientA, deviceID: "device-a")

        managerA.synchronize(snapshotCommand: SyncCommand(
            executable: "/bin/sh",
            arguments: ["-c", "touch \(quote(started.path)); while [ ! -f \(quote(release.path)) ]; do sleep 0.05; done; printf '{\"_device\":\"device-a\",\"_ts\":2}' > device-a.json"],
            supervisorExecutable: "/usr/bin/python3"
        )) { first.value = $0 }
        try waitForFile(started)

        try Data("{\"_device\":\"device-b\",\"_ts\":3}".utf8)
            .write(to: clientB.appendingPathComponent("device-b.json"))
        _ = try git(["add", "device-b.json"], at: clientB)
        _ = try git(["commit", "-m", "device b update"], at: clientB)
        _ = try git(["push", "origin", "HEAD:main"], at: clientB)

        try Data().write(to: release)
        let result = try waitForResult(first, timeout: 30)
        try expect(result.code == .success, "push race did not recover: \(result.output)")
        _ = try git(["fetch", "origin", "main"], at: clientB)
        _ = try git(["show", "origin/main:device-a.json"], at: clientB)
        _ = try git(["show", "origin/main:device-b.json"], at: clientB)
    }

    private static func testAheadCommitChangingPeerIsRejectedBeforeSnapshot() throws {
        let fixture = try makeFixture(clones: ["client"])
        let repo = fixture.clones["client"]!
        let remoteBefore = try bareHead(fixture.origin)
        try Data("{\"_device\":\"device-b\",\"_ts\":4}".utf8)
            .write(to: repo.appendingPathComponent("device-b.json"))
        _ = try git(["add", "device-b.json"], at: repo)
        _ = try git(["commit", "-m", "unexpected peer update"], at: repo)
        let localBefore = try head(repo)
        let statusBefore = try git(["status", "--porcelain=v1", "--untracked-files=all"], at: repo)
            .output
        try expect(statusBefore.isEmpty, "ahead fixture should have a clean worktree")
        let sentinel = fixture.root.appendingPathComponent("peer-history-snapshot-ran")

        let result = try synchronize(
            repo: repo,
            deviceID: "device-a",
            shell: "touch \(quote(sentinel.path)); printf '{}' > device-a.json"
        )

        try expect(result.code == .dirtyRepository,
                   "peer-changing ahead commit should be rejected: \(result.output)")
        try expect(!FileManager.default.fileExists(atPath: sentinel.path),
                   "snapshot ran after unsafe local history was detected")
        let remoteAfter = try bareHead(fixture.origin)
        try expect(remoteAfter == remoteBefore,
                   "unsafe local history changed the remote")
        let localAfter = try head(repo)
        try expect(localAfter == localBefore,
                   "unsafe local history rejection changed local HEAD")
        let statusAfter = try git(["status", "--porcelain=v1", "--untracked-files=all"], at: repo)
            .output
        try expect(statusAfter == statusBefore,
                   "unsafe local history rejection changed the worktree")
    }

    private static func testMismatchedOwnedMarkerPreservesRealRebaseState() throws {
        let fixture = try makeFixture(clones: ["client", "peer"])
        let client = fixture.clones["client"]!
        let peer = fixture.clones["peer"]!
        let rebase = try createConflictedRebase(
            client: client,
            peer: peer,
            file: "seed.txt",
            clientContents: "client version\n",
            peerContents: "peer version\n"
        )
        let gitDirectory = client.appendingPathComponent(".git")
        let rebaseDirectory = gitDirectory.appendingPathComponent("rebase-merge")
        let marker = gitDirectory.appendingPathComponent("tokei-sync-rebase")
        let mismatchedOnto = String(repeating: "0", count: rebase.onto.count)
        try writeMarker(marker, head: rebase.originalHead, onto: mismatchedOnto)
        let rebaseBefore = try directorySnapshot(rebaseDirectory)
        let markerBefore = try Data(contentsOf: marker)
        let headBefore = try Data(contentsOf: gitDirectory.appendingPathComponent("HEAD"))
        let indexBefore = try Data(contentsOf: gitDirectory.appendingPathComponent("index"))
        let sentinel = fixture.root.appendingPathComponent("mismatched-marker-snapshot-ran")

        let result = try synchronize(
            repo: client,
            deviceID: "device-a",
            shell: "touch \(quote(sentinel.path)); printf '{}' > device-a.json"
        )

        try expect(result.code == .foreignOperation,
                   "mismatched marker should be treated as foreign: \(result.output)")
        try expect(!FileManager.default.fileExists(atPath: sentinel.path),
                   "snapshot ran while marker and rebase state disagreed")
        try expect(FileManager.default.fileExists(atPath: rebaseDirectory.path),
                   "mismatched marker removed the real rebase state")
        let rebaseAfter = try directorySnapshot(rebaseDirectory)
        try expect(rebaseAfter == rebaseBefore,
                   "mismatched marker changed rebase metadata")
        let markerAfter = try Data(contentsOf: marker)
        try expect(markerAfter == markerBefore,
                   "mismatched marker was changed or removed")
        let headStateAfter = try Data(contentsOf: gitDirectory.appendingPathComponent("HEAD"))
        try expect(headStateAfter == headBefore,
                   "mismatched marker changed HEAD state")
        let indexAfter = try Data(contentsOf: gitDirectory.appendingPathComponent("index"))
        try expect(indexAfter == indexBefore,
                   "mismatched marker changed the index")
    }

    private static func testMatchingOwnedMarkerPreservesRealRebaseState() throws {
        let fixture = try makeFixture(clones: ["client", "peer"])
        let client = fixture.clones["client"]!
        let peer = fixture.clones["peer"]!
        try Data("{\"value\":\"base\"}\n".utf8)
            .write(to: client.appendingPathComponent("device-a.json"))
        _ = try git(["add", "device-a.json"], at: client)
        _ = try git(["commit", "-m", "add device baseline"], at: client)
        _ = try git(["push", "origin", "HEAD:main"], at: client)
        _ = try git(["pull", "--ff-only", "origin", "main"], at: peer)

        let rebase = try createConflictedRebase(
            client: client,
            peer: peer,
            file: "device-a.json",
            clientContents: "{\"value\":\"client\"}\n",
            peerContents: "{\"value\":\"peer\"}\n"
        )
        let gitDirectory = client.appendingPathComponent(".git")
        let rebaseDirectory = gitDirectory.appendingPathComponent("rebase-merge")
        let marker = gitDirectory.appendingPathComponent("tokei-sync-rebase")
        try writeMarker(marker, head: rebase.originalHead, onto: rebase.onto)
        let remoteBefore = try bareHead(fixture.origin)
        let rebaseBefore = try directorySnapshot(rebaseDirectory)
        let markerBefore = try Data(contentsOf: marker)
        let headBefore = try Data(contentsOf: gitDirectory.appendingPathComponent("HEAD"))
        let indexBefore = try Data(contentsOf: gitDirectory.appendingPathComponent("index"))
        let sentinel = fixture.root.appendingPathComponent("matching-marker-snapshot-ran")

        let result = try synchronize(
            repo: client,
            deviceID: "device-a",
            shell: "touch \(quote(sentinel.path)); exit 1"
        )

        try expect(result.code == .foreignOperation,
                   "matching marker rebase should require manual recovery: \(result.output)")
        try expect(!FileManager.default.fileExists(atPath: sentinel.path),
                   "snapshot ran while an earlier process owned the rebase")
        try expect(FileManager.default.fileExists(atPath: rebaseDirectory.path),
                   "matching marker removed cross-process rebase state")
        let rebaseAfter = try directorySnapshot(rebaseDirectory)
        let markerAfter = try Data(contentsOf: marker)
        let headAfter = try Data(contentsOf: gitDirectory.appendingPathComponent("HEAD"))
        let indexAfter = try Data(contentsOf: gitDirectory.appendingPathComponent("index"))
        try expect(rebaseAfter == rebaseBefore,
                   "matching marker changed cross-process rebase metadata")
        try expect(markerAfter == markerBefore,
                   "matching marker was changed or removed")
        try expect(headAfter == headBefore,
                   "matching marker changed HEAD state")
        try expect(indexAfter == indexBefore,
                   "matching marker changed the index")
        let remoteAfter = try bareHead(fixture.origin)
        try expect(remoteAfter == remoteBefore,
                   "matching marker rejection changed the remote")
    }

    private static func testPythonSupervisorTimesOutAndTerminatesSnapshot() throws {
        let fixture = try makeFixture(clones: ["client"])
        let repo = fixture.clones["client"]!
        let started = fixture.root.appendingPathComponent("timeout-started")
        let finished = fixture.root.appendingPathComponent("timeout-finished")
        let shellPIDFile = fixture.root.appendingPathComponent("timeout-shell-pid")
        let childPIDFile = fixture.root.appendingPathComponent("timeout-child-pid")
        let shell = """
        touch \(quote(started.path))
        printf '%s' "$$" > \(quote(shellPIDFile.path))
        trap 'exit 143' TERM
        /bin/sleep 30 &
        child="$!"
        printf '%s' "$child" > \(quote(childPIDFile.path))
        wait "$child"
        touch \(quote(finished.path))
        """
        let box = ResultBox()
        let startedAt = Date()
        manager(repo: repo, deviceID: "device-a").synchronize(snapshotCommand: SyncCommand(
            executable: "/bin/sh",
            arguments: ["-c", shell],
            supervisorExecutable: "/usr/bin/python3",
            transactionTimeout: 5
        )) { box.value = $0 }
        let result = try waitForResult(box, timeout: 18)

        try expect(result.code == .timedOut,
                   "Python supervisor should report timeout: \(result.output)")
        try expect(Date().timeIntervalSince(startedAt) < 15,
                   "timeout supervisor took too long to terminate the transaction")
        try expect(FileManager.default.fileExists(atPath: started.path),
                   "timeout elapsed before the snapshot process started")
        try expect(!FileManager.default.fileExists(atPath: finished.path),
                   "timed out snapshot reached its completion sentinel")
        let shellPID = try textFile(shellPIDFile)
        let childPID = try textFile(childPIDFile)
        let shellExited = try waitForProcessExit(shellPID)
        let childExited = try waitForProcessExit(childPID)
        try expect(shellExited,
                   "snapshot shell process survived supervisor timeout: \(shellPID)")
        try expect(childExited,
                   "snapshot child process survived supervisor timeout: \(childPID)")
    }

    private static func testConfiguredPrePushHookDoesNotRunDuringSync() throws {
        let fixture = try makeFixture(clones: ["client"])
        let repo = fixture.clones["client"]!
        let hooksDirectory = fixture.root.appendingPathComponent("configured-hooks")
        try FileManager.default.createDirectory(
            at: hooksDirectory,
            withIntermediateDirectories: false
        )
        let sentinel = fixture.root.appendingPathComponent("pre-push-hook-ran")
        let hook = hooksDirectory.appendingPathComponent("pre-push")
        let hookScript = """
        #!/bin/sh
        /usr/bin/touch \(quote(sentinel.path))
        exit 99

        """
        try Data(hookScript.utf8).write(to: hook)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o755],
            ofItemAtPath: hook.path
        )
        _ = try git(["config", "core.hooksPath", hooksDirectory.path], at: repo)
        let configuredPath = try git(["config", "--get", "core.hooksPath"], at: repo)
            .output.trimmingCharacters(in: .whitespacesAndNewlines)
        try expect(configuredPath == hooksDirectory.path,
                   "fixture did not configure its failing pre-push hook")

        let result = try synchronize(
            repo: repo,
            deviceID: "device-a",
            shell: "printf '{\"_device\":\"device-a\",\"_ts\":5}' > device-a.json"
        )

        try expect(result.code == .success,
                   "configured pre-push hook blocked sync: \(result.output)")
        try expect(!FileManager.default.fileExists(atPath: sentinel.path),
                   "configured pre-push hook ran during Tokei sync")
        let remoteSnapshot = try run(
            "/usr/bin/git",
            ["--git-dir", fixture.origin.path, "show", "main:device-a.json"],
            at: fixture.root
        ).output.trimmingCharacters(in: .whitespacesAndNewlines)
        try expect(remoteSnapshot == "{\"_device\":\"device-a\",\"_ts\":5}",
                   "remote did not receive the local device snapshot")
    }

    private static func testReferenceTransactionHookDoesNotRunDuringSync() throws {
        let fixture = try makeFixture(clones: ["client"])
        let repo = fixture.clones["client"]!
        let hooksDirectory = fixture.root.appendingPathComponent("reference-hooks")
        try FileManager.default.createDirectory(
            at: hooksDirectory,
            withIntermediateDirectories: false
        )
        let sentinel = fixture.root.appendingPathComponent("reference-transaction-hook-ran")
        try writeExecutable(
            hooksDirectory.appendingPathComponent("reference-transaction"),
            contents: """
            #!/bin/sh
            /usr/bin/touch \(quote(sentinel.path))
            exit 99

            """
        )
        _ = try git(["config", "core.hooksPath", hooksDirectory.path], at: repo)

        let result = try synchronize(
            repo: repo,
            deviceID: "device-reference",
            shell: "printf '{\"_device\":\"device-reference\",\"_ts\":6}' > device-reference.json"
        )

        try expect(result.code == .success,
                   "reference-transaction hook blocked sync: \(result.output)")
        try expect(!FileManager.default.fileExists(atPath: sentinel.path),
                   "reference-transaction hook ran during Tokei sync")
        let remoteSnapshot = try run(
            "/usr/bin/git",
            ["--git-dir", fixture.origin.path, "show", "main:device-reference.json"],
            at: fixture.root
        ).output.trimmingCharacters(in: .whitespacesAndNewlines)
        try expect(remoteSnapshot == "{\"_device\":\"device-reference\",\"_ts\":6}",
                   "reference hook fixture did not push its snapshot")
    }

    private static func testRequiredCommitSigningDoesNotRunDuringSync() throws {
        let fixture = try makeFixture(clones: ["client"])
        let repo = fixture.clones["client"]!
        let signerSentinel = fixture.root.appendingPathComponent("failing-signer-ran")
        let signer = fixture.root.appendingPathComponent("failing-gpg")
        try writeExecutable(
            signer,
            contents: """
            #!/bin/sh
            /usr/bin/touch \(quote(signerSentinel.path))
            exit 99

            """
        )
        _ = try git(["config", "commit.gpgSign", "true"], at: repo)
        _ = try git(["config", "gpg.program", signer.path], at: repo)
        _ = try git(["config", "user.signingKey", "integration-check"], at: repo)
        let signingRequired = try git(["config", "--bool", "--get", "commit.gpgSign"], at: repo)
            .output.trimmingCharacters(in: .whitespacesAndNewlines)
        try expect(signingRequired == "true", "fixture did not require commit signing")

        let result = try synchronize(
            repo: repo,
            deviceID: "device-signing",
            shell: "printf '{\"_device\":\"device-signing\",\"_ts\":7}' > device-signing.json"
        )

        try expect(result.code == .success,
                   "required commit signing blocked sync: \(result.output)")
        try expect(!FileManager.default.fileExists(atPath: signerSentinel.path),
                   "Tokei invoked the configured failing signer")
        let remoteSnapshot = try run(
            "/usr/bin/git",
            ["--git-dir", fixture.origin.path, "show", "main:device-signing.json"],
            at: fixture.root
        ).output.trimmingCharacters(in: .whitespacesAndNewlines)
        try expect(remoteSnapshot == "{\"_device\":\"device-signing\",\"_ts\":7}",
                   "signing fixture did not push its snapshot")
    }

    private static func testPostAuditHeadDriftCannotPushUnauditedCommit() throws {
        let fixture = try makeFixture(clones: ["client", "builder"])
        let client = fixture.clones["client"]!
        let builder = fixture.clones["builder"]!
        let snapshot = "{\"_device\":\"device-drift\",\"_ts\":8}"
        let remoteBefore = try bareHead(fixture.origin)

        try Data(snapshot.utf8).write(to: builder.appendingPathComponent("device-drift.json"))
        _ = try git(["add", "device-drift.json"], at: builder)
        _ = try git(["commit", "-m", "builder snapshot tree"], at: builder)
        let snapshotParent = try head(builder)
        _ = try git(["checkout", "-b", "drift-side", remoteBefore], at: builder)
        _ = try git(["commit", "--allow-empty", "-m", "drift side parent"], at: builder)
        _ = try git(["checkout", "main"], at: builder)
        _ = try git(["merge", "--no-ff", "-s", "ours", "drift-side", "-m", "unaudited merge"], at: builder)
        let unauditedCommit = try head(builder)
        let unauditedParents = try git(["rev-list", "--parents", "-n", "1", unauditedCommit], at: builder)
            .output.split(whereSeparator: \.isWhitespace)
        try expect(unauditedParents.count == 3,
                   "drift fixture did not create a two-parent commit")
        let unauditedTree = try git(["rev-parse", "\(unauditedCommit)^{tree}"], at: builder)
            .output.trimmingCharacters(in: .whitespacesAndNewlines)
        let snapshotTree = try git(["rev-parse", "\(snapshotParent)^{tree}"], at: builder)
            .output.trimmingCharacters(in: .whitespacesAndNewlines)
        try expect(unauditedTree == snapshotTree,
                   "unaudited commit tree must match the expected snapshot tree")
        _ = try git(
            ["fetch", builder.path, "refs/heads/main:refs/tokei-test/unaudited"],
            at: client
        )
        let driftReady = fixture.root.appendingPathComponent("head-drift-ready")
        let driftSentinel = fixture.root.appendingPathComponent("head-drift-complete")
        let driftTimeout = fixture.root.appendingPathComponent("head-drift-timeout")
        let monitor = fixture.root.appendingPathComponent("head-drift-monitor.py")
        try Data("""
        import glob
        import os
        import subprocess
        import sys
        import time

        git_dir, target, ready, completed, timed_out = sys.argv[1:]
        open(ready, "w", encoding="utf-8").close()
        deadline = time.monotonic() + 30
        saw_audit = False
        while time.monotonic() < deadline:
            audit_files = glob.glob(os.path.join(git_dir, "tokei-sync-audit.*"))
            if audit_files:
                saw_audit = True
            elif saw_audit:
                result = subprocess.run(
                    ["/usr/bin/git", "--git-dir", git_dir, "update-ref", "refs/heads/main", target],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                with open(completed, "w", encoding="utf-8") as handle:
                    handle.write(str(result.returncode))
                raise SystemExit(result.returncode)
            time.sleep(0.001)
        open(timed_out, "w", encoding="utf-8").close()
        raise SystemExit(124)
        """.utf8).write(to: monitor)
        let monitorLog = fixture.root.appendingPathComponent("head-drift-monitor.log")
        let snapshotShell = """
        /usr/bin/python3 \(quote(monitor.path)) \(quote(client.appendingPathComponent(".git").path)) \(quote(unauditedCommit)) \(quote(driftReady.path)) \(quote(driftSentinel.path)) \(quote(driftTimeout.path)) </dev/null >\(quote(monitorLog.path)) 2>&1 &
        while [ ! -f \(quote(driftReady.path)) ]; do /bin/sleep 0.01; done
        printf '%s' \(quote(snapshot)) > device-drift.json
        """

        let result = try synchronize(
            repo: client,
            deviceID: "device-drift",
            shell: snapshotShell
        )

        try waitForFile(driftSentinel, timeout: 10)
        try expect(!FileManager.default.fileExists(atPath: driftTimeout.path),
                   "HEAD drift monitor did not observe the final audit")
        let driftStatus = try textFile(driftSentinel)
        try expect(driftStatus == "0",
                   "HEAD drift monitor failed to move main")
        let driftedHead = try head(client)
        try expect(driftedHead == unauditedCommit,
                   "HEAD drift monitor did not leave main on the unaudited commit")
        try expect(result.code == .success || result.code == .dirtyRepository,
                   "unexpected result after audited HEAD drift: \(result.output)")
        let remoteAfter = try bareHead(fixture.origin)
        try expect(remoteAfter != unauditedCommit,
                   "unaudited post-audit commit reached the remote")
        if result.code == .success {
            let remoteSnapshot = try run(
                "/usr/bin/git",
                ["--git-dir", fixture.origin.path, "show", "main:device-drift.json"],
                at: fixture.root
            ).output.trimmingCharacters(in: .whitespacesAndNewlines)
            try expect(remoteSnapshot == snapshot,
                       "successful fixed-SHA push did not contain the audited snapshot")
        } else {
            try expect(remoteAfter == remoteBefore,
                       "rejected HEAD drift still changed the remote")
        }
    }

    private static func testSupervisorKillsTermIgnoringGrandchildAfterLeaderExit() throws {
        let fixture = try makeFixture(clones: ["client"])
        let repo = fixture.clones["client"]!
        let started = fixture.root.appendingPathComponent("orphan-started")
        let grandchildPIDFile = fixture.root.appendingPathComponent("orphan-grandchild-pid")
        let python = """
        import os, signal, sys, time
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        with open(sys.argv[1], "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        time.sleep(30)
        """
        let shell = """
        /usr/bin/touch \(quote(started.path))
        /usr/bin/python3 -c \(quote(python)) \(quote(grandchildPIDFile.path)) </dev/null >/dev/null 2>&1 &
        grandchild="$!"
        wait "$grandchild"
        """
        let box = ResultBox()
        manager(repo: repo, deviceID: "device-orphan").synchronize(snapshotCommand: SyncCommand(
            executable: "/bin/sh",
            arguments: ["-c", shell],
            supervisorExecutable: "/usr/bin/python3",
            transactionTimeout: 5
        )) { box.value = $0 }
        let result = try waitForResult(box, timeout: 18)

        try expect(result.code == .timedOut,
                   "orphan supervisor scenario should time out: \(result.output)")
        try expect(FileManager.default.fileExists(atPath: started.path),
                   "orphan fixture snapshot never started")
        let grandchildPID = try textFile(grandchildPIDFile)
        let exited = try waitForProcessExit(grandchildPID, timeout: 5)
        if !exited {
            _ = try? runUnchecked(
                "/bin/kill",
                ["-KILL", grandchildPID],
                at: FileManager.default.temporaryDirectory
            )
        }
        try expect(exited,
                   "TERM-ignoring grandchild survived after its group leader exited: \(grandchildPID)")
    }

    private static func testSaveConfigRejectsDeviceIdentityChangeInIsolatedHome() throws {
        let root = try makeRoot()
        let home = root.appendingPathComponent("isolated-home", isDirectory: true)
        let configDirectory = home.appendingPathComponent(".tokei", isDirectory: true)
        try FileManager.default.createDirectory(
            at: configDirectory,
            withIntermediateDirectories: true
        )
        let configURL = configDirectory.appendingPathComponent("config.json")
        let original = """
        {
          "auto_sync" : true,
          "device_id" : "stable-device",
          "preserved_key" : "preserved-value",
          "sync_dir" : "/tmp/stable-sync",
          "sync_interval" : 60
        }
        """
        let originalData = Data(original.utf8)
        try originalData.write(to: configURL)

        let executable = URL(
            fileURLWithPath: CommandLine.arguments[0],
            relativeTo: URL(fileURLWithPath: FileManager.default.currentDirectoryPath, isDirectory: true)
        ).standardizedFileURL
        let child = try runUnchecked(
            executable.path,
            ["--isolated-config-identity-check", home.path],
            at: root,
            environmentOverrides: [
                "CFFIXED_USER_HOME": home.path,
                "HOME": home.path,
            ]
        )
        try expect(child.status == 0,
                   "isolated config identity child failed with status \(child.status): \(child.output)")
        let after = try Data(contentsOf: configURL)
        try expect(after == originalData,
                   "rejected device identity change modified config bytes on disk")
    }

    private static func runIsolatedConfigIdentityCheck(expectedHome: URL) throws {
        let expectedConfig = expectedHome
            .appendingPathComponent(".tokei", isDirectory: true)
            .appendingPathComponent("config.json")
            .standardizedFileURL
        try expect(SyncManager.configPath.standardizedFileURL == expectedConfig,
                   "Foundation did not isolate SyncManager.configPath: \(SyncManager.configPath.path)")
        let manager = SyncManager()
        guard let original = manager.config else {
            throw CheckError.failed("isolated manager did not load the valid config")
        }
        try expect(original.device_id == "stable-device",
                   "isolated manager loaded the wrong device identity")
        let saved = manager.saveConfig(SyncConfig(
            device_id: "changed-device",
            sync_dir: "/tmp/changed-sync",
            auto_sync: false,
            sync_interval: 120
        ))
        try expect(!saved, "saveConfig accepted a device identity change")
        try expect(manager.config?.device_id == "stable-device",
                   "rejected identity change modified manager.config")
        let diskConfig = SyncManager.loadConfig()
        try expect(diskConfig?.device_id == "stable-device",
                   "rejected identity change modified the disk config")
        print("isolated config identity check passed")
    }

    private static func testInheritedGitDirectoryCannotRedirectSync() throws {
        let targetFixture = try makeFixture(clones: ["target"])
        let target = targetFixture.clones["target"]!
        let decoyFixture = try makeFixture(clones: ["decoy"])
        let decoy = decoyFixture.clones["decoy"]!
        let decoyHeadBefore = try head(decoy)
        let decoyRemoteBefore = try bareHead(decoyFixture.origin)
        let decoyStatusBefore = try git(
            ["status", "--porcelain=v1", "--untracked-files=all"],
            at: decoy
        ).output
        let zdotDirectory = targetFixture.root.appendingPathComponent("hostile-zdotdir")
        try FileManager.default.createDirectory(
            at: zdotDirectory,
            withIntermediateDirectories: false
        )
        let zshenvSentinel = targetFixture.root.appendingPathComponent("hostile-zshenv-ran")
        let zshenv = """
        export GIT_DIR=\(quote(decoy.appendingPathComponent(".git").path))
        export GIT_WORK_TREE=\(quote(decoy.path))
        cd \(quote(decoy.path))
        /usr/bin/touch \(quote(zshenvSentinel.path))

        """
        try Data(zshenv.utf8).write(to: zdotDirectory.appendingPathComponent(".zshenv"))
        let originalGitDirectory = ProcessInfo.processInfo.environment["GIT_DIR"]
        let originalWorkTree = ProcessInfo.processInfo.environment["GIT_WORK_TREE"]
        let originalZdotDirectory = ProcessInfo.processInfo.environment["ZDOTDIR"]
        guard setenv("GIT_DIR", decoy.appendingPathComponent(".git").path, 1) == 0 else {
            throw CheckError.failed("cannot configure inherited Git redirection variables")
        }
        guard setenv("GIT_WORK_TREE", decoy.path, 1) == 0 else {
            restoreEnvironment("GIT_DIR", originalGitDirectory)
            throw CheckError.failed("cannot configure inherited Git redirection variables")
        }
        guard setenv("ZDOTDIR", zdotDirectory.path, 1) == 0 else {
            restoreEnvironment("GIT_DIR", originalGitDirectory)
            restoreEnvironment("GIT_WORK_TREE", originalWorkTree)
            throw CheckError.failed("cannot configure hostile ZDOTDIR")
        }
        defer {
            restoreEnvironment("GIT_DIR", originalGitDirectory)
            restoreEnvironment("GIT_WORK_TREE", originalWorkTree)
            restoreEnvironment("ZDOTDIR", originalZdotDirectory)
        }

        let result = try synchronize(
            repo: target,
            deviceID: "device-environment",
            shell: "printf '{\"_device\":\"device-environment\",\"_ts\":9}' > device-environment.json"
        )

        try expect(result.code == .success,
                   "inherited Git redirection blocked target sync: \(result.output)")
        let targetSnapshot = try run(
            "/usr/bin/git",
            ["--git-dir", targetFixture.origin.path, "show", "main:device-environment.json"],
            at: targetFixture.root
        ).output.trimmingCharacters(in: .whitespacesAndNewlines)
        try expect(targetSnapshot == "{\"_device\":\"device-environment\",\"_ts\":9}",
                   "target remote did not receive the isolated snapshot")
        let decoyHeadAfter = try head(decoy)
        let decoyRemoteAfter = try bareHead(decoyFixture.origin)
        let decoyStatusAfter = try git(
            ["status", "--porcelain=v1", "--untracked-files=all"],
            at: decoy
        ).output
        try expect(decoyHeadAfter == decoyHeadBefore,
                   "inherited GIT_DIR changed the decoy HEAD")
        try expect(decoyRemoteAfter == decoyRemoteBefore,
                   "inherited GIT_DIR changed the decoy remote")
        try expect(decoyStatusAfter == decoyStatusBefore,
                   "inherited GIT_WORK_TREE changed the decoy worktree")
        try expect(!FileManager.default.fileExists(atPath: zshenvSentinel.path),
                   "transaction shell loaded the hostile .zshenv")
        try expect(!FileManager.default.fileExists(
            atPath: decoy.appendingPathComponent("device-environment.json").path
        ), "snapshot was written into the decoy worktree")
    }

    private static func testPeerLoaderReportsBadFilesIndependently() throws {
        let root = try makeRoot()
        try Data("not-json".utf8).write(to: root.appendingPathComponent("bad.json"))
        try Data("{\"claude\":{}}".utf8).write(to: root.appendingPathComponent("missing-ts.json"))
        let report = manager(repo: root, deviceID: "local").loadPeers()

        try expect(report.peers.isEmpty, "invalid peer files should not decode")
        try expect(report.issues.map(\.stage) == [.json, .timestamp],
                   "peer issue stages were not deterministic: \(report.issues.map(\.stage))")
        try expect(report.issues.map(\.file) == ["bad.json", "missing-ts.json"],
                   "peer issue files were not deterministic: \(report.issues.map(\.file))")
    }

    private static func synchronize(repo: URL, deviceID: String, shell: String) throws -> GitSyncResult {
        let box = ResultBox()
        manager(repo: repo, deviceID: deviceID).synchronize(snapshotCommand: SyncCommand(
            executable: "/bin/sh",
            arguments: ["-c", shell],
            supervisorExecutable: "/usr/bin/python3"
        )) { box.value = $0 }
        return try waitForResult(box, timeout: 20)
    }

    private static func manager(repo: URL, deviceID: String) -> SyncManager {
        let manager = SyncManager()
        manager.config = SyncConfig(
            device_id: deviceID,
            sync_dir: repo.path,
            auto_sync: false,
            sync_interval: 30
        )
        return manager
    }

    private static func createConflictedRebase(
        client: URL,
        peer: URL,
        file: String,
        clientContents: String,
        peerContents: String
    ) throws -> ConflictedRebase {
        try Data(clientContents.utf8).write(to: client.appendingPathComponent(file))
        _ = try git(["add", file], at: client)
        _ = try git(["commit", "-m", "client conflicting update"], at: client)
        let originalHead = try head(client)

        try Data(peerContents.utf8).write(to: peer.appendingPathComponent(file))
        _ = try git(["add", file], at: peer)
        _ = try git(["commit", "-m", "peer conflicting update"], at: peer)
        _ = try git(["push", "origin", "HEAD:main"], at: peer)
        _ = try git(["fetch", "origin", "main"], at: client)
        let onto = try git(["rev-parse", "origin/main"], at: client).output
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let rebase = try runUnchecked(
            "/usr/bin/git",
            ["rebase", "--merge", "origin/main"],
            at: client
        )
        try expect(rebase.status != 0,
                   "fixture unexpectedly rebased without a conflict: \(rebase.output)")

        let stateDirectory = client.appendingPathComponent(".git/rebase-merge")
        try expect(FileManager.default.fileExists(atPath: stateDirectory.path),
                   "fixture did not create a real rebase-merge state")
        let actualHead = try textFile(stateDirectory.appendingPathComponent("orig-head"))
        let actualOnto = try textFile(stateDirectory.appendingPathComponent("onto"))
        try expect(actualHead == originalHead,
                   "real rebase orig-head did not match fixture HEAD")
        try expect(actualOnto == onto,
                   "real rebase onto did not match origin/main")
        return ConflictedRebase(originalHead: originalHead, onto: onto)
    }

    private static func writeMarker(_ url: URL, head: String, onto: String) throws {
        let marker = """
        tokei-sync-rebase-v2
        refs/heads/main
        \(head)
        origin/main
        \(onto)
        pid=integration-check
        started_at=2000-01-01T00:00:00Z

        """
        try Data(marker.utf8).write(to: url)
    }

    private static func writeExecutable(_ url: URL, contents: String) throws {
        try Data(contents.utf8).write(to: url)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o755],
            ofItemAtPath: url.path
        )
    }

    private static func restoreEnvironment(_ key: String, _ value: String?) {
        if let value {
            _ = setenv(key, value, 1)
        } else {
            _ = unsetenv(key)
        }
    }

    private static func head(_ repo: URL) throws -> String {
        try git(["rev-parse", "HEAD"], at: repo).output
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func bareHead(_ origin: URL) throws -> String {
        try run(
            "/usr/bin/git",
            ["--git-dir", origin.path, "rev-parse", "refs/heads/main"],
            at: origin.deletingLastPathComponent()
        ).output.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func directorySnapshot(_ directory: URL) throws -> [String: Data] {
        guard let enumerator = FileManager.default.enumerator(
            at: directory,
            includingPropertiesForKeys: [.isRegularFileKey]
        ) else {
            throw CheckError.failed("cannot enumerate \(directory.path)")
        }
        var snapshot: [String: Data] = [:]
        for case let file as URL in enumerator {
            let values = try file.resourceValues(forKeys: [.isRegularFileKey])
            guard values.isRegularFile == true else { continue }
            let relative = String(file.path.dropFirst(directory.path.count + 1))
            snapshot[relative] = try Data(contentsOf: file)
        }
        return snapshot
    }

    private static func textFile(_ url: URL) throws -> String {
        let data = try Data(contentsOf: url)
        guard let value = String(data: data, encoding: .utf8) else {
            throw CheckError.failed("cannot decode \(url.path) as UTF-8")
        }
        return value.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func processExists(_ pid: String) throws -> Bool {
        let result = try runUnchecked(
            "/bin/kill",
            ["-0", pid],
            at: FileManager.default.temporaryDirectory
        )
        return result.status == 0
    }

    private static func waitForProcessExit(_ pid: String, timeout: TimeInterval = 2) throws -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if try !processExists(pid) { return true }
            RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.02))
        }
        return try !processExists(pid)
    }

    private static func makeFixture(clones names: [String]) throws
        -> (root: URL, origin: URL, clones: [String: URL]) {
        let root = try makeRoot()
        let origin = root.appendingPathComponent("origin.git")
        _ = try run("/usr/bin/git", ["init", "--bare", "--initial-branch=main", origin.path], at: root)
        let seed = root.appendingPathComponent("seed")
        _ = try run("/usr/bin/git", ["clone", origin.path, seed.path], at: root)
        try configureGit(seed)
        try Data("seed\n".utf8).write(to: seed.appendingPathComponent("seed.txt"))
        _ = try git(["add", "seed.txt"], at: seed)
        _ = try git(["commit", "-m", "seed"], at: seed)
        _ = try git(["push", "origin", "HEAD:main"], at: seed)

        var clones: [String: URL] = [:]
        for name in names {
            let clone = root.appendingPathComponent(name)
            _ = try run("/usr/bin/git", ["clone", origin.path, clone.path], at: root)
            try configureGit(clone)
            clones[name] = clone
        }
        return (root, origin, clones)
    }

    private static func configureGit(_ repo: URL) throws {
        _ = try git(["config", "user.name", "Tokei Test"], at: repo)
        _ = try git(["config", "user.email", "tokei-test@example.invalid"], at: repo)
        _ = try git(["config", "commit.gpgsign", "false"], at: repo)
        _ = try git(["config", "core.hooksPath", "/dev/null"], at: repo)
    }

    private static func git(_ arguments: [String], at directory: URL) throws -> CommandResult {
        try run("/usr/bin/git", arguments, at: directory)
    }

    private static func run(_ executable: String, _ arguments: [String], at directory: URL) throws
        -> CommandResult {
        let result = try runUnchecked(executable, arguments, at: directory)
        guard result.status == 0 else {
            throw CheckError.failed(
                "\(executable) \(arguments.joined(separator: " ")) failed:\n\(result.output)"
            )
        }
        return result
    }

    private static func runUnchecked(
        _ executable: String,
        _ arguments: [String],
        at directory: URL,
        environmentOverrides: [String: String] = [:]
    ) throws -> CommandResult {
        let process = Process()
        let pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        process.currentDirectoryURL = directory
        process.standardOutput = pipe
        process.standardError = pipe
        process.standardInput = FileHandle.nullDevice
        var environment = ProcessInfo.processInfo.environment
        environment["GIT_TERMINAL_PROMPT"] = "0"
        for (key, value) in environmentOverrides {
            environment[key] = value
        }
        process.environment = environment
        try process.run()
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        let result = CommandResult(
            status: process.terminationStatus,
            output: String(data: data, encoding: .utf8) ?? ""
        )
        return result
    }

    private static func waitForResult(_ box: ResultBox, timeout: TimeInterval) throws -> GitSyncResult {
        let deadline = Date().addingTimeInterval(timeout)
        while box.value == nil && Date() < deadline {
            RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.02))
        }
        guard let result = box.value else {
            throw CheckError.failed("timed out waiting for sync result")
        }
        return result
    }

    private static func waitForFile(_ url: URL, timeout: TimeInterval = 10) throws {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if FileManager.default.fileExists(atPath: url.path) { return }
            RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.02))
        }
        throw CheckError.failed("timed out waiting for \(url.path)")
    }

    private static func makeRoot() throws -> URL {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("tokei-sync-tests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        roots.append(root)
        return root
    }

    private static func quote(_ value: String) -> String {
        "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }

    private static func expect(_ condition: @autoclosure () -> Bool,
                               _ message: String) throws {
        if !condition() { throw CheckError.failed(message) }
    }
}
