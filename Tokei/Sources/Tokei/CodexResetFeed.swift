import Foundation

/// AIHOT's public announcement feed is independent of personal quota windows.
struct CodexResetFeed: Codable {
    let schemaVersion: Int
    let checkedAt: Date
    let current: Event?
    let lastLanded: Event?
    let monitor: Monitor?

    struct Monitor: Codable {
        let status: String
        let lastVerifiedAt: Date?
    }

    struct Event: Codable {
        let id: String
        let type: String
        let status: String
        let displayLabel: String?
        let confirmedAt: Date?
        let occurredOn: String?
        let confirmationBasis: String?
        let estimate: Window?
        let schedule: Window?
        let presentation: Presentation?
        let posts: [Post]?

        struct Window: Codable {
            let from: Date?
            let through: Date?
            let reason: String?
        }

        struct Presentation: Codable {
            let status: String?
            let audienceZh: String?
            let scopeLabel: String?
            let productsZh: String?
        }

        struct Post: Codable {
            let url: String
        }

        var window: Window? { estimate ?? schedule }
        var sourceURL: URL? {
            posts?.compactMap { post in
                guard let url = URL(string: post.url), url.scheme == "https",
                      ["x.com", "twitter.com"].contains(url.host?.lowercased() ?? "")
                else { return nil }
                return url
            }.first
        }

        enum Phase: Equatable {
            case confirmed, likely, inProgress, awaitingTime, withinWindow, overdue, unknown
            case scheduled(Date)
        }

        func phase(at now: Date) -> Phase {
            // Explicit confirmation wins over earlier estimates and progress posts.
            if status == "confirmed" || presentation?.status == "confirmed" { return .confirmed }
            switch presentation?.status ?? status {
            case "likely_completed": return .likely
            case "expired_unconfirmed": return .overdue
            case "in_progress": return .inProgress
            case "announced":
                guard let window else { return .awaitingTime }
                if let end = window.through, now >= end { return .overdue }
                if let start = window.from, now < start { return .scheduled(start) }
                if window.through == nil, window.from != nil { return .overdue }
                if window.from != nil || window.through != nil { return .withinWindow }
                return .awaitingTime
            default: return .unknown
            }
        }
    }

    enum FeedError: Error { case unsupportedSchema, invalidWindow, invalidResponse }

    static func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let value = try decoder.singleValueContainer().decode(String.self)
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let date = formatter.date(from: value) { return date }
            formatter.formatOptions = [.withInternetDateTime]
            guard let date = formatter.date(from: value) else {
                throw DecodingError.dataCorrupted(.init(codingPath: decoder.codingPath,
                                                       debugDescription: "Invalid ISO8601 timestamp"))
            }
            return date
        }
        return decoder
    }

    static func decode(_ data: Data) throws -> Self {
        // Missing current/lastLanded is not equivalent to an explicit null (no event).
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              root.keys.contains("current"), root.keys.contains("lastLanded") else {
            throw FeedError.invalidResponse
        }
        let feed = try decoder().decode(Self.self, from: data)
        try feed.validate()
        return feed
    }

    func validate() throws {
        guard schemaVersion == 1 else { throw FeedError.unsupportedSchema }
        for event in [current, lastLanded].compactMap({ $0 }) {
            for window in [event.estimate, event.schedule].compactMap({ $0 }) {
                if let start = window.from, let end = window.through, end < start {
                    throw FeedError.invalidWindow
                }
            }
        }
    }

    func isStale(at now: Date, fetchedAt: Date) -> Bool {
        let verified = monitor?.lastVerifiedAt ?? checkedAt
        return now.timeIntervalSince(verified) > 30 * 60 ||
            now.timeIntervalSince(fetchedAt) > 30 * 60 ||
            verified.timeIntervalSince(now) > 5 * 60 ||
            (monitor?.status != nil && monitor?.status != "healthy")
    }
}
