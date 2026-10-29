import Foundation
import AppKit

// SyncManager's dashboard payloads are unrelated to these activity-only checks.
struct DailyCost: Codable {}
struct WrappedData: Codable {}

private enum Failure: Error { case assertion(String) }
private func expect(_ value: @autoclosure () -> Bool, _ message: String) throws {
    if !value() { throw Failure.assertion(message) }
}

@main
struct DoubaoWorkCheck {
    static let a = String(repeating: "a", count: 64)
    static let b = String(repeating: "b", count: 64)
    static let c = String(repeating: "c", count: 64)

    static func fixture(_ stat: Any? = nil) throws -> Usage {
        let zero: [String: Any] = [
            "hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "cached": 0,
            "reason": 0, "thoughts": 0, "tokens": 0, "cost": 0, "models": [],
            "sessions": 0, "tasks": 0, "completed": 0, "failed": 0,
        ]
        let ranges = Dictionary(uniqueKeysWithValues: RangeKey.allCases.map { ($0.rawValue, zero) })
        var json: [String: Any] = [:]
        for tool in ["claude", "codex", "gemini", "grok", "hermes", "openclaw", "opencode"] {
            json[tool] = ["ranges": ranges]
        }
        json["claude"] = ["ranges": ranges, "session_name": "", "session_total": 0]
        if let stat { json["doubaowork"] = stat }
        return try Usage.decode(from: JSONSerialization.data(withJSONObject: json))
    }

    static func stat(_ ids: [String], today: Bool = true) -> [String: Any] {
        let range: [String: Any] = ["sessions": ids.count, "session_ids": ids]
        return ["ranges": ["today": today ? range : ["sessions": 0, "session_ids": []],
                           "year": range, "all": range],
                "source": "doubaowork-local-cache", "updated": 100]
    }

    static func peer(_ usage: Usage, now: Date, id: String = "peer") -> PeerDevice {
        let bounds = Dictionary(uniqueKeysWithValues: SyncManager.currentRangeBounds(now: now)
            .map { ($0.key.rawValue, $0.value) })
        return PeerDevice(deviceId: id, lastSync: now, usage: usage, rangeBounds: bounds)
    }

    @MainActor
    static func main() throws {
        L10n.forcedLanguage = .zh
        let old = try fixture()
        try expect(!old.doubaoWork.hasActivity, "old snapshots must default to empty")
        for raw: Any in [NSNull(), "malformed", ["ranges": NSNull()]] {
            let usage = try fixture(raw)
            try expect(!usage.doubaoWork.hasActivity, "optional malformed data must not break Usage decoding")
        }
        let partial = try fixture(["ranges": ["today": "bad", "year": ["sessions": 2]],
                                   "source": NSNull(), "updated": "bad"])
        try expect(partial.doubaoWork.hasActivity, "missing IDs must retain an older count")
        try expect(partial.doubaoWork.ranges.today.sessions == 0, "malformed range defaults independently")
        try expect(partial.doubaoWork.ranges.get(.all).sessions == 2, "legacy all falls back to year")
        try expect(partial.doubaoWork.updated == nil, "invalid timestamp is unknown")

        let left = DoubaoWorkRange(sessions: 2, session_ids: [b, a, a])
        let right = DoubaoWorkRange(sessions: 2, session_ids: [b, c])
        let union = left.merged(with: right)
        try expect(union.sessions == 3 && union.session_ids == [a, b, c], "overlapping IDs must union")
        try expect(union.merged(with: left) == union, "repeat merge must be idempotent")
        try expect(left.merged(with: right) == right.merged(with: left), "union must be order independent")
        try expect(DoubaoWorkRange().merged(with: left) == left, "empty legacy range must be an identity")
        let legacy = DoubaoWorkRange(sessions: 8)
        try expect(legacy.merged(with: left).sessions == 8, "missing IDs use max, never sum")
        try expect(legacy.merged(with: left).session_ids == nil, "fallback must retain uncertainty")
        let mismatch = DoubaoWorkRange(sessions: 4, session_ids: [a])
        try expect(mismatch.merged(with: right).sessions == 4, "incomplete IDs use max")
        let malformed = try JSONDecoder().decode(DoubaoWorkRange.self, from:
            Data(#"{"sessions":6,"session_ids":[42]}"#.utf8))
        try expect(malformed.merged(with: left).sessions == 6, "malformed ID types preserve count fallback")
        let invalid = DoubaoWorkRange(sessions: 5, session_ids: ["raw-conversation-id"])
        try expect(invalid.session_ids == nil && invalid.merged(with: right).sessions == 5,
                   "non-hash IDs cannot be treated as complete")

        let local = try fixture(stat([a, b]))
        let remote = try fixture(stat([b, c]))
        let now = ISO8601DateFormatter().date(from: "2026-10-29T12:00:00Z")!
        let epoch = Int(now.timeIntervalSince1970)
        let quotaJSON: [String: Any] = ["version": 1, "status": "connected", "updated": epoch,
            "windows": [["window_type": 2, "used_percent": 20, "start_time_ms": (epoch - 1000) * 1000,
                         "end_time_ms": (epoch + 604800) * 1000, "less_than_one_percent": false]]]
        var withQuotaJSON = stat([a, b])
        withQuotaJSON["quota"] = quotaJSON
        let withQuota = try fixture(withQuotaJSON)
        let quota = withQuota.doubaoWork.quota!
        try expect(quota.isFresh(now: now), "live quota timestamp must be retained")
        try expect(quota.windows[0].remaining == 80 && quota.windows[0].reset == epoch + 604800,
                   "quota is a percentage, with reset milliseconds normalized once")
        try expect(!quota.isFresh(now: now.addingTimeInterval(1801)), "old readings must be stale")
        try expect(quota.windows[0].hasReset(now: now.addingTimeInterval(604801)), "expired windows must reset")
        let quotaOnly = try fixture(["quota": quotaJSON])
        try expect(quotaOnly.doubaoWork.hasActivity, "connected quota must display even without cached conversations")
        let withoutLocalQuota = SyncManager.merge(local: local, peers: [peer(withQuota, now: now)], now: now)
        try expect(withoutLocalQuota.doubaoWork.quota == nil, "another device's account quota must not replace this account")
        let quotaMerged = SyncManager.merge(local: withQuota, peers: [peer(remote, now: now)], now: now)
        try expect(quotaMerged.doubaoWork.quota?.windows.first?.remaining == 80,
                   "device merging must retain local quota without adding percentages")
        var badQuota = quotaJSON
        badQuota["windows"] = [["window_type": 2, "used_percent": 101, "start_time_ms": 0,
                               "end_time_ms": 0, "less_than_one_percent": false]]
        var badStat = stat([a])
        badStat["quota"] = badQuota
        let badUsage = try fixture(badStat)
        try expect(badUsage.doubaoWork.quota == nil,
                   "invalid quota must not break conversation history or invent remaining usage")
        let peers = [peer(remote, now: now)]
        let merged = SyncManager.merge(local: local, peers: peers, now: now)
        for key in [RangeKey.today, .year, .all] {
            try expect(merged.doubaoWork.ranges.get(key).sessions == 3, "sync must deduplicate \(key)")
        }
        try expect(local.doubaoWork.ranges.today.sessions == 2, "all-device merge must preserve local snapshot")
        let repeated = SyncManager.merge(local: merged, peers: peers, now: now)
        try expect(repeated.doubaoWork.ranges.today == merged.doubaoWork.ranges.today,
                   "repeat peer input must not inflate counts")
        let fromEmpty = SyncManager.merge(local: old, peers: [peer(local, now: now), peer(remote, now: now, id: "second")], now: now)
        try expect(fromEmpty.doubaoWork.ranges.today.sessions == 3, "two peer caches must union from an empty local cache")
        let reversed = SyncManager.merge(local: old, peers: [peer(remote, now: now), peer(local, now: now, id: "second")], now: now)
        try expect(reversed.doubaoWork.ranges.today == fromEmpty.doubaoWork.ranges.today, "peer order must not change union")
        let older = Calendar.current.date(byAdding: .day, value: -1, to: now)!
        let rollover = SyncManager.merge(local: old, peers: [peer(remote, now: older)], now: now)
        try expect(rollover.doubaoWork.ranges.today.sessions == 0 && rollover.doubaoWork.ranges.yesterday.sessions == 2,
                   "peer day ranges must follow existing date boundaries")
        let oldPeer = try fixture(["ranges": ["today": ["sessions": 8]]])
        let conservative = SyncManager.merge(local: local, peers: [peer(oldPeer, now: now)], now: now)
        try expect(conservative.doubaoWork.ranges.today.sessions == 8, "sync legacy data must use max")

        let roundTrip = try Usage.decode(from: JSONEncoder().encode(merged))
        try expect(roundTrip.doubaoWork.ranges.today == union, "Codable must retain the union IDs")
        let encoded = try JSONSerialization.jsonObject(with: JSONEncoder().encode(merged.doubaoWork)) as! [String: Any]
        try expect(Set(encoded.keys) == ["ranges", "source", "updated"], "activity stat must not encode fake usage fields")

        let zeroToday = try fixture(stat([a, b], today: false))
        try expect(zeroToday.doubaoWork.hasActivity && zeroToday.doubaoWork.ranges.today.sessions == 0,
                   "known conversations must keep a zero-today card active")
        let line = UsageSummaryBuilder.line(forToolID: "doubaowork", usage: zeroToday, range: .today,
                                            visibility: .allVisible)!
        try expect(line.sessions == 0 && line.activityLabel == "今日 新建会话", "share must retain selected zero period")
        try expect(line.tokens == nil && line.cost == nil && line.cost_cny == nil && line.calls == nil &&
                   line.input == nil && line.output == nil && line.reason == nil && line.hit == nil,
                   "activity share must not invent token/cost/call metrics")
        try expect(line.sourceCaption == DoubaoWorkStat.sourceCaption, "share must explain the metric limitation")
        let allLine = UsageSummaryBuilder.line(forToolID: "doubaowork", usage: zeroToday, range: .all,
                                               visibility: .allVisible)!
        try expect(allLine.sessions == 2 && allLine.activityLabel == "累计会话", "all uses cumulative conversations")
        var liveQuotaStat = stat([a, b])
        var liveQuota = quotaJSON
        liveQuota["updated"] = Int(Date().timeIntervalSince1970)
        liveQuotaStat["quota"] = liveQuota
        let liveQuotaUsage = try fixture(liveQuotaStat)
        let quotaLine = UsageSummaryBuilder.line(forToolID: "doubaowork", usage: liveQuotaUsage,
            range: .today, visibility: .allVisible)!
        try expect(quotaLine.extra?.contains("80%") == true && quotaLine.tokens == nil,
                   "share must include real percentage quota without inventing tokens")
        let text = UsageSummaryBuilder.text(usage: zeroToday, range: .today, visibility: .allVisible)
        try expect(text.contains("Doubao Work  0 今日 新建会话"), "plain text must share the actual displayed metric")
        try expect(!text.contains("0 tok") && !text.contains("成本") && !text.contains("调用"), "plain text must not invent usage")
        var hidden = UsageToolVisibility.allVisible
        hidden.doubaoWork = false
        try expect(UsageSummaryBuilder.line(forToolID: "doubaowork", usage: zeroToday, range: .today, visibility: hidden) == nil,
                   "hidden cards must be absent from shares")
        try expect(UsageSummaryBuilder.line(forToolID: "doubaowork", usage: old, range: .today, visibility: .allVisible) == nil,
                   "old empty snapshots must not create a share card")
        try expect(UsageCardOrdering.tokens(for: "doubaowork", usage: merged, range: .today) == 0,
                   "unknown token total is zero for ordering only")
        let totals = UsageSummaryBuilder.totals(for: [allLine])
        try expect(totals.sessions == 2 && totals.calls == 0 && totals.tokens == 0 && totals.cost == 0,
                   "activity must not inflate token/cost totals")

        _ = NSApplication.shared
        guard let png = UsageShareImage.pngData(line: line, range: .today), !png.isEmpty else {
            throw Failure.assertion("activity-only share must render a real PNG")
        }
        if CommandLine.arguments.count > 1 {
            try png.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
        }
        print("Doubao Work decoding, sync union, zero-period sharing and native PNG checks passed")
    }
}
