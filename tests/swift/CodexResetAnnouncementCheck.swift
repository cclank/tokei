import Foundation

private func expect(_ condition: @autoclosure () throws -> Bool, _ message: String) throws {
    if try !condition() { throw NSError(domain: message, code: 1) }
}

private final class MockFeed: URLProtocol {
    static var body = Data()
    static var status = 200
    static var failure: Error?
    static var requests: [URLRequest] = []
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.requests.append(request)
        if let failure = Self.failure {
            client?.urlProtocol(self, didFailWithError: failure)
            return
        }
        let response = HTTPURLResponse(url: request.url!, statusCode: Self.status,
                                       httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Self.body)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

@main
struct CodexResetAnnouncementCheck {
    static func main() throws {
        let defaults = UserDefaults(suiteName: "reset-test-" + UUID().uuidString)!
        try expect(CodexResetMonitor.isEnabled(in: defaults), "new installs default on")
        defaults.set(false, forKey: CodexResetMonitor.enabledKey)
        try expect(!CodexResetMonitor.isEnabled(in: defaults), "explicit off is preserved")
        defaults.removeObject(forKey: CodexResetMonitor.enabledKey)
        let stamp = "2026-10-15T14:00:00.000+08:00"
        let now = ISO8601DateFormatter().date(from: "2026-10-15T06:00:00Z")!
        var event: [String: Any] = [
            "id": "example", "type": "direct_reset", "status": "announced",
            "presentation": ["status": "announced"],
            "estimate": ["from": "2026-10-15T15:00:00.000+08:00",
                         "through": "2026-10-15T17:00:00+08:00"],
            "posts": [["url": "https://x.com/thsottiaux/status/123"]]
        ]
        func feed(_ event: [String: Any]?, last: [String: Any]? = nil) throws -> Data {
            try JSONSerialization.data(withJSONObject: [
                "schemaVersion": 1, "checkedAt": stamp,
                "current": event as Any? ?? NSNull(), "lastLanded": last as Any? ?? NSNull(),
                "monitor": ["status": "healthy", "lastVerifiedAt": stamp]
            ])
        }
        let pending = try CodexResetFeed.decode(feed(event))
        let item = pending.current!
        try expect(item.phase(at: now) == .scheduled(now.addingTimeInterval(3600)), "future countdown")
        try expect(item.phase(at: now.addingTimeInterval(3600)) == .withinWindow, "window starts inclusively")
        try expect(item.phase(at: now.addingTimeInterval(10800)) == .overdue, "window end is unconfirmed, not reset")
        NSTimeZone.default = TimeZone(identifier: "America/Los_Angeles")!
        try expect(item.phase(at: now) == .scheduled(now.addingTimeInterval(3600)), "offset timestamps independent of local DST")
        try expect(!pending.isStale(at: now, fetchedAt: now), "fresh feed")
        try expect(pending.isStale(at: now.addingTimeInterval(1801), fetchedAt: now), "stale upstream timestamp")
        try expect(pending.isStale(at: now, fetchedAt: now.addingTimeInterval(-1801)), "stale local cache")
        try expect(pending.isStale(at: now.addingTimeInterval(-600), fetchedAt: now), "future clock skew")

        event["status"] = "confirmed"
        event["confirmedAt"] = stamp
        event["presentation"] = ["status": "in_progress"]
        let confirmed = try CodexResetFeed.decode(feed(nil, last: event))
        try expect(confirmed.current == nil, "no next reset invented from last event")
        try expect(confirmed.lastLanded!.phase(at: now) == .confirmed, "confirmation wins over earlier progress")
        try expect(try CodexResetFeed.decode(feed(nil)).lastLanded == nil, "empty history accepted")

        event["status"] = "announced"
        event["confirmedAt"] = nil
        for (state, expected) in [("likely_completed", CodexResetFeed.Event.Phase.likely),
                                  ("in_progress", .inProgress), ("expired_unconfirmed", .overdue),
                                  ("new_unrecognized_status", .unknown)] {
            event["presentation"] = ["status": state]
            try expect(try CodexResetFeed.decode(feed(event)).current!.phase(at: now) == expected, state)
        }
        event["presentation"] = ["status": "announced"]
        event["estimate"] = nil
        event["type"] = "reset_credit"
        let noTime = try CodexResetFeed.decode(feed(event))
        try expect(noTime.current!.phase(at: now) == .awaitingTime, "missing time never guessed")
        try expect(noTime.current!.type == "reset_credit", "credit event remains distinct")
        event["schedule"] = ["from": stamp]
        try expect(try CodexResetFeed.decode(feed(event)).current!.phase(at: now) == .overdue, "single timestamp expires safely")

        event["posts"] = [["url": "file:///etc/passwd"], ["url": "https://evil.example/"]]
        try expect(try CodexResetFeed.decode(feed(event)).current!.sourceURL == nil, "unsafe source links ignored")
        event["schedule"] = ["from": "invalid"]
        func rejects(_ data: Data) throws {
            do { _ = try CodexResetFeed.decode(data) }
            catch { return }
            throw NSError(domain: "invalid feed accepted", code: 1)
        }
        try rejects(feed(event))
        event["schedule"] = ["from": "2026-10-15T15:00:00+08:00", "through": stamp]
        try rejects(feed(event))
        try rejects(Data("{\"schemaVersion\":1,\"checkedAt\":\"\(stamp)\"}".utf8))
        try rejects(Data("<html>Access denied</html>".utf8))
        let validData = try feed(nil, last: confirmedEvent())
        var unsupported = try JSONSerialization.jsonObject(with: validData) as! [String: Any]
        unsupported["schemaVersion"] = 2
        try rejects(JSONSerialization.data(withJSONObject: unsupported))

        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockFeed.self]
        let session = URLSession(configuration: config)
        let cacheURL = URL(fileURLWithPath: CommandLine.arguments[1]).appendingPathComponent("cache.json")
        let monitor = CodexResetMonitor(session: session, cacheURL: cacheURL)
        MockFeed.body = validData
        monitor.refresh(enabled: false, now: now)
        try expect(!monitor.isRefreshing && MockFeed.requests.isEmpty, "disabled feature never requests the feed")
        monitor.refresh(enabled: true, now: now)
        monitor.refresh(enabled: true, now: now)
        try wait(monitor)
        try expect(MockFeed.requests.count == 1, "deduplicates concurrent refresh")
        try expect(monitor.snapshot?.feed.lastLanded?.id == "confirmed", "live response decoded")
        let request = MockFeed.requests[0]
        try expect(request.value(forHTTPHeaderField: "Authorization") == nil &&
                   request.value(forHTTPHeaderField: "Cookie") == nil && request.httpBody == nil,
                   "anonymous read only public request")
        try expect(request.url == CodexResetMonitor.feedURL, "only public feed endpoint")
        monitor.refresh(enabled: true, now: now.addingTimeInterval(599))
        try expect(!monitor.isRefreshing && MockFeed.requests.count == 1, "ten minute throttle")
        let cached = CodexResetMonitor(session: session, cacheURL: cacheURL)
        try expect(cached.snapshot?.feed.lastLanded?.id == "confirmed", "persisted cache loads")

        MockFeed.failure = URLError(.notConnectedToInternet)
        monitor.refresh(enabled: true, now: now.addingTimeInterval(600))
        try wait(monitor)
        try expect(monitor.lastFetchFailed && monitor.snapshot != nil, "offline keeps last good snapshot")
        try expect(monitor.lastFailure == .network(URLError.notConnectedToInternet.rawValue), "network failure classified")
        monitor.refresh(enabled: true, now: now.addingTimeInterval(659))
        try expect(!monitor.isRefreshing, "failed requests are still throttled")
        MockFeed.failure = nil
        MockFeed.body = Data("<html>blocked</html>".utf8)
        monitor.refresh(enabled: true, now: now.addingTimeInterval(660))
        try wait(monitor)
        try expect(monitor.lastFetchFailed && monitor.snapshot != nil, "bad response cannot erase cache")
        try expect(monitor.lastFailure == .invalidData, "parse failure classified")
        MockFeed.body = validData
        monitor.refresh(enabled: true, now: now.addingTimeInterval(779))
        try expect(!monitor.isRefreshing, "second failure backs off two minutes")
        monitor.refresh(enabled: true, now: now.addingTimeInterval(780))
        try wait(monitor)
        try expect(!monitor.lastFetchFailed && monitor.snapshot != nil, "failed refresh retries promptly after network recovery")
        monitor.refresh(enabled: true, now: now.addingTimeInterval(2400))
        monitor.refresh(enabled: false, now: now.addingTimeInterval(2400))
        RunLoop.main.run(until: Date().addingTimeInterval(0.05))
        try expect(!monitor.isRefreshing && !monitor.lastFetchFailed, "disabling cancels without a stale failure callback")
        print("reset announcement checks passed")
    }

    static func confirmedEvent() -> [String: Any] {
        ["id": "confirmed", "type": "direct_reset", "status": "confirmed",
         "confirmedAt": "2026-10-15T14:00:00+08:00"]
    }

    static func wait(_ monitor: CodexResetMonitor) throws {
        let deadline = Date().addingTimeInterval(5)
        while monitor.isRefreshing && Date() < deadline {
            RunLoop.main.run(until: Date().addingTimeInterval(0.01))
        }
        try expect(!monitor.isRefreshing, "network callback timed out")
    }
}
