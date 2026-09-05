import Foundation

enum RangeKey: String, CaseIterable, Identifiable {
    case yesterday, today, week, lastWeek = "last_week", month, year, all
    var id: String { rawValue }
    static let displayCases: [RangeKey] = [.today, .yesterday, .week, .lastWeek, .month, .year]
    var label: String {
        switch self {
        case .today: return "今日"
        case .yesterday: return "昨日"
        case .week: return "本周"
        case .lastWeek: return "上周"
        case .month: return "本月"
        case .year: return "本年"
        case .all: return "全部"
        }
    }
}

struct ClaudeModelStat: Codable, Identifiable {
    var name: String
    var `in`: Int
    var out: Int
    var cr: Int
    var cw: Int
    var cost: Double
    var pin: Double      // 输入单价 $/M
    var pout: Double     // 输出单价 $/M
    var id: String { name }
    var total: Int { `in` + out + cr + cw }
}

struct ClaudeRange: Codable {
    var hit: Double
    var `in`: Int
    var out: Int
    var cr: Int
    var cw: Int
    var cost: Double
    var models: [ClaudeModelStat] = []
    var sessions: Int = 0

    var tokens: Int { `in` + out + cr + cw }
}

struct ClaudeRanges: Codable {
    var today: ClaudeRange
    var yesterday: ClaudeRange
    var week: ClaudeRange
    var last_week: ClaudeRange
    var month: ClaudeRange
    var year: ClaudeRange
    var all: ClaudeRange?
    func get(_ k: RangeKey) -> ClaudeRange {
        switch k {
        case .today: return today; case .yesterday: return yesterday
        case .week: return week; case .lastWeek: return last_week
        case .month: return month; case .year: return year
        case .all: return all ?? year
        }
    }
    mutating func set(_ k: RangeKey, _ v: ClaudeRange) {
        switch k {
        case .today: today = v; case .yesterday: yesterday = v
        case .week: week = v; case .lastWeek: last_week = v
        case .month: month = v; case .year: year = v
        case .all: all = v
        }
    }
}

struct ClaudeStat: Codable {
    var ranges: ClaudeRanges
    var session_name: String
    var session_total: Int
    var q5: Double?
    var q5_reset: Int?
    var q7: Double?
    var q7_reset: Int?
    var qf: Double?
    var qf_reset: Int?
    var q_updated: Int?
    var q5_stale: Bool?
    var q7_stale: Bool?
    var qf_stale: Bool?
}

struct CodexRange: Codable {
    var hit: Double
    var `in`: Int
    var cached: Int
    var out: Int
    var reason: Int
    var cost: Double
    var sessions: Int = 0
    var models: [TokenModelStat] = []

    var tokens: Int { `in` + cached + out }

    init(hit: Double = 0, `in` input: Int = 0, cached: Int = 0, out: Int = 0,
         reason: Int = 0, cost: Double = 0, sessions: Int = 0, models: [TokenModelStat] = []) {
        self.hit = hit
        self.in = input
        self.cached = cached
        self.out = out
        self.reason = reason
        self.cost = cost
        self.sessions = sessions
        self.models = models
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        hit = try c.decodeIfPresent(Double.self, forKey: .hit) ?? 0
        `in` = try c.decodeIfPresent(Int.self, forKey: .in) ?? 0
        cached = try c.decodeIfPresent(Int.self, forKey: .cached) ?? 0
        out = try c.decodeIfPresent(Int.self, forKey: .out) ?? 0
        reason = try c.decodeIfPresent(Int.self, forKey: .reason) ?? 0
        cost = try c.decodeIfPresent(Double.self, forKey: .cost) ?? 0
        sessions = try c.decodeIfPresent(Int.self, forKey: .sessions) ?? 0
        models = try c.decodeIfPresent([TokenModelStat].self, forKey: .models) ?? []
    }
}

struct CodexRanges: Codable {
    var today: CodexRange
    var yesterday: CodexRange
    var week: CodexRange
    var last_week: CodexRange
    var month: CodexRange
    var year: CodexRange
    var all: CodexRange?
    func get(_ k: RangeKey) -> CodexRange {
        switch k {
        case .today: return today; case .yesterday: return yesterday
        case .week: return week; case .lastWeek: return last_week
        case .month: return month; case .year: return year
        case .all: return all ?? year
        }
    }
    mutating func set(_ k: RangeKey, _ v: CodexRange) {
        switch k {
        case .today: today = v; case .yesterday: yesterday = v
        case .week: week = v; case .lastWeek: last_week = v
        case .month: month = v; case .year: year = v
        case .all: all = v
        }
    }
}

struct CodexStat: Codable {
    var ranges: CodexRanges
    var p5: Double?
    var pw: Double?
    var r5: Int?
    var rw: Int?
    var q_updated: Int?
    var p5_stale: Bool?
    var pw_stale: Bool?
    var plan: String?
    var reset_cards: CodexResetCards?
}

struct CodexResetCards: Codable {
    var count: Int
    var expires: [Int]
    var updated: Int?
}

struct GeminiModelStat: Codable, Identifiable {
    var name: String
    var `in`: Int
    var out: Int
    var cached: Int
    var thoughts: Int
    var cost: Double
    var pin: Double      // 输入单价 $/M
    var pout: Double     // 输出单价 $/M
    var id: String { name }
}

struct GeminiRange: Codable {
    var hit: Double
    var `in`: Int
    var out: Int
    var cached: Int
    var thoughts: Int
    var cost: Double
    var models: [GeminiModelStat] = []
    var sessions: Int = 0

    var totalTokens: Int { self.in + out + cached + thoughts }
    var hasUsage: Bool { sessions > 0 || totalTokens > 0 }
}

struct GeminiRanges: Codable {
    var today: GeminiRange
    var yesterday: GeminiRange
    var week: GeminiRange
    var last_week: GeminiRange
    var month: GeminiRange
    var year: GeminiRange
    var all: GeminiRange?

    /// A zero-activity selected range should not hide a recent local session.
    /// Return the nearest useful range together with its real label so the UI
    /// never presents yesterday/week data as today's data.
    func displayRange(for preferred: RangeKey) -> (range: GeminiRange, key: RangeKey) {
        let order: [RangeKey]
        switch preferred {
        case .today:
            order = [.today, .yesterday, .week, .month, .year, .all]
        case .yesterday:
            order = [.yesterday, .today, .week, .month, .year, .all]
        case .week:
            order = [.week, .today, .yesterday, .month, .year, .all]
        case .lastWeek:
            order = [.lastWeek, .week, .month, .year, .all, .today, .yesterday]
        case .month:
            order = [.month, .year, .all, .week, .today, .yesterday]
        case .year:
            order = [.year, .all, .month, .week, .today, .yesterday]
        case .all:
            order = [.all, .year, .month, .week, .today, .yesterday]
        }
        for key in order {
            let candidate = get(key)
            if candidate.hasUsage { return (candidate, key) }
        }
        return (get(preferred), preferred)
    }

    func get(_ k: RangeKey) -> GeminiRange {
        switch k {
        case .today: return today; case .yesterday: return yesterday
        case .week: return week; case .lastWeek: return last_week
        case .month: return month; case .year: return year
        case .all: return all ?? year
        }
    }
    mutating func set(_ k: RangeKey, _ v: GeminiRange) {
        switch k {
        case .today: today = v; case .yesterday: yesterday = v
        case .week: week = v; case .lastWeek: last_week = v
        case .month: month = v; case .year: year = v
        case .all: all = v
        }
    }
}

struct GeminiStat: Codable {
    var ranges: GeminiRanges
}

struct GrokRange: Codable {
    var tokens: Int
    var hit: Double = 0
    var `in`: Int = 0
    var out: Int = 0
    var cr: Int = 0
    var reason: Int = 0
    var cost: Double = 0
    var models: [TokenModelStat] = []
    var usage_available: Bool = false
    var usage_calls: Int = 0
    var usage_sessions: Int = 0
    var sessions: Int = 0
    var turns: Int?
    var tools: Int?
    var duration: Int?
    var ctx_used: Int?
    var ctx_window: Int?
    var ctx: Double?
    var errors: Int?
    var cancellations: Int?
    var ttft: Int?
    var response: Int?

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        tokens = try c.decodeIfPresent(Int.self, forKey: .tokens) ?? 0
        hit = try c.decodeIfPresent(Double.self, forKey: .hit) ?? 0
        `in` = try c.decodeIfPresent(Int.self, forKey: .in) ?? 0
        out = try c.decodeIfPresent(Int.self, forKey: .out) ?? 0
        cr = try c.decodeIfPresent(Int.self, forKey: .cr) ?? 0
        reason = try c.decodeIfPresent(Int.self, forKey: .reason) ?? 0
        cost = try c.decodeIfPresent(Double.self, forKey: .cost) ?? 0
        models = try c.decodeIfPresent([TokenModelStat].self, forKey: .models) ?? []
        usage_available = try c.decodeIfPresent(Bool.self, forKey: .usage_available) ?? false
        usage_calls = try c.decodeIfPresent(Int.self, forKey: .usage_calls) ?? 0
        usage_sessions = try c.decodeIfPresent(Int.self, forKey: .usage_sessions) ?? 0
        sessions = try c.decodeIfPresent(Int.self, forKey: .sessions) ?? 0
        turns = try c.decodeIfPresent(Int.self, forKey: .turns)
        tools = try c.decodeIfPresent(Int.self, forKey: .tools)
        duration = try c.decodeIfPresent(Int.self, forKey: .duration)
        ctx_used = try c.decodeIfPresent(Int.self, forKey: .ctx_used)
        ctx_window = try c.decodeIfPresent(Int.self, forKey: .ctx_window)
        ctx = try c.decodeIfPresent(Double.self, forKey: .ctx)
        errors = try c.decodeIfPresent(Int.self, forKey: .errors)
        cancellations = try c.decodeIfPresent(Int.self, forKey: .cancellations)
        ttft = try c.decodeIfPresent(Int.self, forKey: .ttft)
        response = try c.decodeIfPresent(Int.self, forKey: .response)
    }
}

struct GrokRanges: Codable {
    var today: GrokRange
    var yesterday: GrokRange
    var week: GrokRange
    var last_week: GrokRange
    var month: GrokRange
    var year: GrokRange
    var all: GrokRange?
    func get(_ k: RangeKey) -> GrokRange {
        switch k {
        case .today: return today; case .yesterday: return yesterday
        case .week: return week; case .lastWeek: return last_week
        case .month: return month; case .year: return year
        case .all: return all ?? year
        }
    }
    mutating func set(_ k: RangeKey, _ v: GrokRange) {
        switch k {
        case .today: today = v; case .yesterday: yesterday = v
        case .week: week = v; case .lastWeek: last_week = v
        case .month: month = v; case .year: year = v
        case .all: all = v
        }
    }
}

struct GrokProductUsage: Codable, Identifiable {
    var name: String
    var pct: Double?
    var id: String { name }
}

struct GrokStat: Codable {
    var ranges: GrokRanges
    var model: String?
    /// 本周期已用百分比（0–100）。
    var pct: Double?
    /// 周期重置时间（unix epoch 秒）。
    var reset: Int?
    /// 套餐名，如 SuperGrok。
    var plan: String?
    /// 分产品已用百分比（GrokBuild / Api 等）。
    var products: [GrokProductUsage] = []
    /// week / month。
    var window: String?
    /// log / live / cache。
    var source: String?
    var q_updated: Int?
    var stale: Bool?

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ranges = try c.decode(GrokRanges.self, forKey: .ranges)
        model = try c.decodeIfPresent(String.self, forKey: .model)
        pct = try c.decodeIfPresent(Double.self, forKey: .pct)
        reset = try c.decodeIfPresent(Int.self, forKey: .reset)
        plan = try c.decodeIfPresent(String.self, forKey: .plan)
        products = try c.decodeIfPresent([GrokProductUsage].self, forKey: .products) ?? []
        window = try c.decodeIfPresent(String.self, forKey: .window)
        source = try c.decodeIfPresent(String.self, forKey: .source)
        q_updated = try c.decodeIfPresent(Int.self, forKey: .q_updated)
        stale = try c.decodeIfPresent(Bool.self, forKey: .stale)
    }
}

struct QoderRange: Codable {
    var `in`: Int = 0
    var out: Int = 0
    var sessions: Int = 0
    var calls: Int = 0
    var sub_agents: Int = 0
    var turns: Int = 0
    var duration: Int = 0
    var ctx: Double = 0
    var tools: Int = 0
    var est: Int = 0

    enum CodingKeys: String, CodingKey {
        case `in`, out, sessions, calls, sub_agents, turns, duration, ctx, tools, est
    }

    init(`in` input: Int = 0, out: Int = 0, sessions: Int = 0, calls: Int = 0,
         sub_agents: Int = 0, turns: Int = 0, duration: Int = 0, ctx: Double = 0,
         tools: Int = 0, est: Int = 0) {
        self.in = input
        self.out = out
        self.sessions = sessions
        self.calls = calls
        self.sub_agents = sub_agents
        self.turns = turns
        self.duration = duration
        self.ctx = ctx
        self.tools = tools
        self.est = est
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.in = try c.decodeIfPresent(Int.self, forKey: .in) ?? 0
        self.out = try c.decodeIfPresent(Int.self, forKey: .out) ?? 0
        self.sessions = try c.decodeIfPresent(Int.self, forKey: .sessions) ?? 0
        self.calls = try c.decodeIfPresent(Int.self, forKey: .calls) ?? 0
        self.sub_agents = try c.decodeIfPresent(Int.self, forKey: .sub_agents) ?? 0
        self.turns = try c.decodeIfPresent(Int.self, forKey: .turns) ?? 0
        self.duration = try c.decodeIfPresent(Int.self, forKey: .duration) ?? 0
        self.ctx = try c.decodeIfPresent(Double.self, forKey: .ctx) ?? 0
        self.tools = try c.decodeIfPresent(Int.self, forKey: .tools) ?? 0
        self.est = try c.decodeIfPresent(Int.self, forKey: .est) ?? 0
    }
}

struct QoderRanges: Codable {
    var today: QoderRange
    var yesterday: QoderRange
    var week: QoderRange
    var last_week: QoderRange
    var month: QoderRange
    var year: QoderRange
    var all: QoderRange? = nil
    static var empty: QoderRanges {
        let r = QoderRange()
        return QoderRanges(today: r, yesterday: r, week: r, last_week: r, month: r, year: r)
    }
    func get(_ k: RangeKey) -> QoderRange {
        switch k {
        case .today: return today; case .yesterday: return yesterday
        case .week: return week; case .lastWeek: return last_week
        case .month: return month; case .year: return year
        case .all: return all ?? year
        }
    }
    mutating func set(_ k: RangeKey, _ v: QoderRange) {
        switch k {
        case .today: today = v; case .yesterday: yesterday = v
        case .week: week = v; case .lastWeek: last_week = v
        case .month: month = v; case .year: year = v
        case .all: all = v
        }
    }
}

struct QoderStat: Codable {
    var ranges: QoderRanges
    var model: String?
}

struct QoderIdeRange: Codable {
    var `in`: Int
    var out: Int
    var cached: Int = 0
    var sessions: Int = 0
    var sub_agents: Int = 0
    var calls: Int = 0
    var messages: Int = 0
    var ctx: Double = 0
    var duration: Int = 0

    enum CodingKeys: String, CodingKey {
        case `in`, out, cached, sessions, sub_agents, calls, messages, ctx, duration
    }

    init(`in` input: Int = 0, out: Int = 0, cached: Int = 0, sessions: Int = 0,
         sub_agents: Int = 0, calls: Int = 0, messages: Int = 0,
         ctx: Double = 0, duration: Int = 0) {
        self.in = input
        self.out = out
        self.cached = cached
        self.sessions = sessions
        self.sub_agents = sub_agents
        self.calls = calls
        self.messages = messages
        self.ctx = ctx
        self.duration = duration
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.`in` = try c.decodeIfPresent(Int.self, forKey: .in) ?? 0
        self.out = try c.decodeIfPresent(Int.self, forKey: .out) ?? 0
        self.cached = try c.decodeIfPresent(Int.self, forKey: .cached) ?? 0
        self.sessions = try c.decodeIfPresent(Int.self, forKey: .sessions) ?? 0
        self.sub_agents = try c.decodeIfPresent(Int.self, forKey: .sub_agents) ?? 0
        self.calls = try c.decodeIfPresent(Int.self, forKey: .calls) ?? 0
        self.messages = try c.decodeIfPresent(Int.self, forKey: .messages) ?? 0
        self.ctx = try c.decodeIfPresent(Double.self, forKey: .ctx) ?? 0
        self.duration = try c.decodeIfPresent(Int.self, forKey: .duration) ?? 0
    }
}

struct QoderIdeRanges: Codable {
    var today: QoderIdeRange
    var yesterday: QoderIdeRange
    var week: QoderIdeRange
    var last_week: QoderIdeRange
    var month: QoderIdeRange
    var year: QoderIdeRange
    var all: QoderIdeRange? = nil
    static var empty: QoderIdeRanges {
        let r = QoderIdeRange()
        return QoderIdeRanges(today: r, yesterday: r, week: r, last_week: r, month: r, year: r)
    }
    func get(_ k: RangeKey) -> QoderIdeRange {
        switch k {
        case .today: return today; case .yesterday: return yesterday
        case .week: return week; case .lastWeek: return last_week
        case .month: return month; case .year: return year
        case .all: return all ?? year
        }
    }
    mutating func set(_ k: RangeKey, _ v: QoderIdeRange) {
        switch k {
        case .today: today = v; case .yesterday: yesterday = v
        case .week: week = v; case .lastWeek: last_week = v
        case .month: month = v; case .year: year = v
        case .all: all = v
        }
    }
}

struct QoderIdeStat: Codable {
    var ranges: QoderIdeRanges
    var model: String?
}

struct HermesRange: Codable {
    var hit: Double
    var `in`: Int
    var out: Int
    var cr: Int
    var cw: Int
    var reason: Int
    var cost: Double
    var sessions: Int = 0
    var models: [TokenModelStat] = []
}
struct TokenModelStat: Codable, Identifiable {
    var modelId: String?
    var name: String
    var tokens: Int?
    var `in`: Int
    var out: Int
    var cr: Int = 0
    var cw: Int = 0
    var reason: Int = 0
    var cost: Double
    var pin: Double = 0
    var pout: Double = 0
    var id: String { modelId ?? name }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        modelId = try c.decodeIfPresent(String.self, forKey: .modelId)
        name = try c.decode(String.self, forKey: .name)
        tokens = try c.decodeIfPresent(Int.self, forKey: .tokens)
        `in` = try c.decodeIfPresent(Int.self, forKey: .in) ?? 0
        out = try c.decodeIfPresent(Int.self, forKey: .out) ?? 0
        cr = try c.decodeIfPresent(Int.self, forKey: .cr) ?? 0
        cw = try c.decodeIfPresent(Int.self, forKey: .cw) ?? 0
        reason = try c.decodeIfPresent(Int.self, forKey: .reason) ?? 0
        cost = try c.decodeIfPresent(Double.self, forKey: .cost) ?? 0
        pin = try c.decodeIfPresent(Double.self, forKey: .pin) ?? 0
        pout = try c.decodeIfPresent(Double.self, forKey: .pout) ?? 0
    }

    private enum CodingKeys: String, CodingKey {
        case modelId = "model_id"
        case name, tokens, `in`, out, cr, cw, reason, cost, pin, pout
    }
}
struct HermesRanges: Codable {
    var today, yesterday, week, last_week, month, year: HermesRange
    var all: HermesRange? = nil
    func get(_ k: RangeKey) -> HermesRange {
        switch k {
        case .today: return today; case .yesterday: return yesterday
        case .week: return week; case .lastWeek: return last_week
        case .month: return month; case .year: return year
        case .all: return all ?? year
        }
    }
    mutating func set(_ k: RangeKey, _ v: HermesRange) {
        switch k {
        case .today: today = v; case .yesterday: yesterday = v
        case .week: week = v; case .lastWeek: last_week = v
        case .month: month = v; case .year: year = v
        case .all: all = v
        }
    }
}
struct HermesStat: Codable { var ranges: HermesRanges }

struct OpenClawRange: Codable {
    var tasks: Int
    var completed: Int
    var failed: Int
    var hit: Double
    var `in`: Int
    var out: Int
    var cr: Int
    var cw: Int
    var cost: Double
    var sessions: Int
    var models: [TokenModelStat]

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        tasks = try c.decode(Int.self, forKey: .tasks)
        completed = try c.decode(Int.self, forKey: .completed)
        failed = try c.decode(Int.self, forKey: .failed)
        hit = try c.decodeIfPresent(Double.self, forKey: .hit) ?? 0
        `in` = try c.decodeIfPresent(Int.self, forKey: .in) ?? 0
        out = try c.decodeIfPresent(Int.self, forKey: .out) ?? 0
        cr = try c.decodeIfPresent(Int.self, forKey: .cr) ?? 0
        cw = try c.decodeIfPresent(Int.self, forKey: .cw) ?? 0
        cost = try c.decodeIfPresent(Double.self, forKey: .cost) ?? 0
        sessions = try c.decodeIfPresent(Int.self, forKey: .sessions) ?? 0
        models = try c.decodeIfPresent([TokenModelStat].self, forKey: .models) ?? []
    }
}
struct OpenClawRanges: Codable {
    var today, yesterday, week, last_week, month, year: OpenClawRange
    var all: OpenClawRange? = nil
    func get(_ k: RangeKey) -> OpenClawRange {
        switch k {
        case .today: return today; case .yesterday: return yesterday
        case .week: return week; case .lastWeek: return last_week
        case .month: return month; case .year: return year
        case .all: return all ?? year
        }
    }
    mutating func set(_ k: RangeKey, _ v: OpenClawRange) {
        switch k {
        case .today: today = v; case .yesterday: yesterday = v
        case .week: week = v; case .lastWeek: last_week = v
        case .month: month = v; case .year: year = v
        case .all: all = v
        }
    }
}
struct OpenClawStat: Codable { var ranges: OpenClawRanges }

struct TokenUsageRange: Codable {
    var tokens: Int
    var hit: Double
    var `in`: Int
    var out: Int
    var cr: Int
    var cw: Int
    var reason: Int
    var cost: Double
    var requests: Int
    var sessions: Int = 0
    var models: [TokenModelStat] = []
    var coverage: String?

    var totalTokens: Int {
        tokens > 0 ? tokens : `in` + out + cr + cw + reason
    }

    var hasComponents: Bool {
        `in` + out + cr + cw + reason > 0
    }

    init(tokens: Int = 0, hit: Double = 0, `in` input: Int = 0, out: Int = 0,
         cr: Int = 0, cw: Int = 0, reason: Int = 0, cost: Double = 0,
         requests: Int = 0, sessions: Int = 0, models: [TokenModelStat] = [],
         coverage: String? = nil) {
        self.tokens = tokens
        self.hit = hit
        self.in = input
        self.out = out
        self.cr = cr
        self.cw = cw
        self.reason = reason
        self.cost = cost
        self.requests = requests
        self.sessions = sessions
        self.models = models
        self.coverage = coverage
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        tokens = try c.decodeIfPresent(Int.self, forKey: .tokens) ?? 0
        hit = try c.decodeIfPresent(Double.self, forKey: .hit) ?? 0
        `in` = try c.decodeIfPresent(Int.self, forKey: .in) ?? 0
        out = try c.decodeIfPresent(Int.self, forKey: .out) ?? 0
        cr = try c.decodeIfPresent(Int.self, forKey: .cr) ?? 0
        cw = try c.decodeIfPresent(Int.self, forKey: .cw) ?? 0
        reason = try c.decodeIfPresent(Int.self, forKey: .reason) ?? 0
        cost = try c.decodeIfPresent(Double.self, forKey: .cost) ?? 0
        requests = try c.decodeIfPresent(Int.self, forKey: .requests) ?? 0
        sessions = try c.decodeIfPresent(Int.self, forKey: .sessions) ?? 0
        models = try c.decodeIfPresent([TokenModelStat].self, forKey: .models) ?? []
        coverage = try c.decodeIfPresent(String.self, forKey: .coverage)
    }
}
struct TokenUsageRanges: Codable {
    var today, yesterday, week, last_week, month, year: TokenUsageRange
    var all: TokenUsageRange? = nil
    static var empty: TokenUsageRanges {
        let r = TokenUsageRange()
        return TokenUsageRanges(today: r, yesterday: r, week: r, last_week: r, month: r, year: r)
    }
    func get(_ k: RangeKey) -> TokenUsageRange {
        switch k {
        case .today: return today; case .yesterday: return yesterday
        case .week: return week; case .lastWeek: return last_week
        case .month: return month; case .year: return year
        case .all: return all ?? year
        }
    }
    mutating func set(_ k: RangeKey, _ v: TokenUsageRange) {
        switch k {
        case .today: today = v; case .yesterday: yesterday = v
        case .week: week = v; case .lastWeek: last_week = v
        case .month: month = v; case .year: year = v
        case .all: all = v
        }
    }
}
struct TokenUsageStat: Codable { var ranges: TokenUsageRanges }

/// Kimi Code 既有本地 token 统计,也有官方额度(5h 滚动窗口 + 订阅周期)。
/// 订阅窗口的周期长度接口没有给,因此只透传它返回的重置时刻,不替它命名周期。
struct KimiCodeStat: Codable {
    var ranges: TokenUsageRanges
    var p5: Double? = nil
    var pw: Double? = nil
    var r5: Int? = nil
    var rw: Int? = nil
    var q_updated: Int? = nil
    var p5_stale: Bool? = nil
    var pw_stale: Bool? = nil
    var plan: String? = nil

    var hasQuota: Bool { p5 != nil || pw != nil }
    var hasStaleQuota: Bool { p5_stale == true || pw_stale == true }
}

/// A single quota bucket reported by the QwenWork desktop app.
/// `total == 0` does not imply that the bucket is empty: some plans expose
/// only an absolute remaining-credit balance.
struct QwenWorkQuotaSegment: Codable, Identifiable {
    var id = ""
    var kind = ""
    var total: Double?
    var used: Double?
    var remaining: Double?
    var percentage_used: Double?
    var unit: String?
    var renews_at: Int?
    var expires_at: Int?

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decodeIfPresent(String.self, forKey: .id) ?? ""
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? ""
        total = try? c.decodeIfPresent(Double.self, forKey: .total)
        used = try? c.decodeIfPresent(Double.self, forKey: .used)
        remaining = try? c.decodeIfPresent(Double.self, forKey: .remaining)
        percentage_used = try? c.decodeIfPresent(Double.self, forKey: .percentage_used)
        unit = try? c.decodeIfPresent(String.self, forKey: .unit)
        renews_at = try? c.decodeIfPresent(Int.self, forKey: .renews_at)
        expires_at = try? c.decodeIfPresent(Int.self, forKey: .expires_at)
    }
}

/// A team/shared package is displayed separately and never added to the
/// personal credit balance.
struct QwenWorkSharedQuota: Codable {
    var total: Double?
    var used: Double?
    var remaining: Double?
    var percentage_used: Double?
    var unit: String?
    var expires_at: Int?

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        total = try? c.decodeIfPresent(Double.self, forKey: .total)
        used = try? c.decodeIfPresent(Double.self, forKey: .used)
        remaining = try? c.decodeIfPresent(Double.self, forKey: .remaining)
        percentage_used = try? c.decodeIfPresent(Double.self, forKey: .percentage_used)
        unit = try? c.decodeIfPresent(String.self, forKey: .unit)
        expires_at = try? c.decodeIfPresent(Int.self, forKey: .expires_at)
    }
}

struct QwenWorkQuota: Codable {
    var available = false
    var remaining: Double?
    var remaining_pct: Double?
    var exceeded = false
    var is_team = false
    var expires_at: Int?
    var plan_expiration: Int?
    var segments: [QwenWorkQuotaSegment] = []
    var shared: QwenWorkSharedQuota?
    var source: String?
    var updated: Int?
    var stale = false

    init() {}

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        available = (try? c.decodeIfPresent(Bool.self, forKey: .available)) ?? false
        remaining = try? c.decodeIfPresent(Double.self, forKey: .remaining)
        remaining_pct = try? c.decodeIfPresent(Double.self, forKey: .remaining_pct)
        exceeded = (try? c.decodeIfPresent(Bool.self, forKey: .exceeded)) ?? false
        is_team = (try? c.decodeIfPresent(Bool.self, forKey: .is_team)) ?? false
        expires_at = try? c.decodeIfPresent(Int.self, forKey: .expires_at)
        plan_expiration = try? c.decodeIfPresent(Int.self, forKey: .plan_expiration)
        segments = (try? c.decodeIfPresent([QwenWorkQuotaSegment].self, forKey: .segments)) ?? []
        shared = try? c.decodeIfPresent(QwenWorkSharedQuota.self, forKey: .shared)
        source = try? c.decodeIfPresent(String.self, forKey: .source)
        updated = try? c.decodeIfPresent(Int.self, forKey: .updated)
        stale = (try? c.decodeIfPresent(Bool.self, forKey: .stale)) ?? false
    }
}

struct ProviderQuotaWindow: Codable, Identifiable {
    var id = ""
    var title = ""
    var used_pct: Double?
    var reset: Int?
    var window_minutes: Int?
    var detail: String?
    var usage_known = true

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decodeIfPresent(String.self, forKey: .id) ?? ""
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? id
        used_pct = try? c.decodeIfPresent(Double.self, forKey: .used_pct)
        reset = try? c.decodeIfPresent(Int.self, forKey: .reset)
        window_minutes = try? c.decodeIfPresent(Int.self, forKey: .window_minutes)
        detail = try? c.decodeIfPresent(String.self, forKey: .detail)
        usage_known = (try? c.decodeIfPresent(Bool.self, forKey: .usage_known)) ?? true
    }
}

struct ProviderQuotaDetail: Codable {
    var label = ""
    var value = ""
    var secondary: String?

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        label = try c.decodeIfPresent(String.self, forKey: .label) ?? ""
        value = try c.decodeIfPresent(String.self, forKey: .value) ?? ""
        secondary = try? c.decodeIfPresent(String.self, forKey: .secondary)
    }
}

struct ProviderQuotaStat: Codable {
    var available = false
    var plan: String?
    var account: String?
    var windows: [ProviderQuotaWindow] = []
    var details: [ProviderQuotaDetail] = []
    var usage: TokenUsageStat? = nil
    var source: String?
    var updated: Int?
    var stale = false

    init() {}

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        available = (try? c.decodeIfPresent(Bool.self, forKey: .available)) ?? false
        plan = try? c.decodeIfPresent(String.self, forKey: .plan)
        account = try? c.decodeIfPresent(String.self, forKey: .account)
        windows = (try? c.decodeIfPresent([ProviderQuotaWindow].self, forKey: .windows)) ?? []
        details = (try? c.decodeIfPresent([ProviderQuotaDetail].self, forKey: .details)) ?? []
        usage = try? c.decodeIfPresent(TokenUsageStat.self, forKey: .usage)
        source = try? c.decodeIfPresent(String.self, forKey: .source)
        updated = try? c.decodeIfPresent(Int.self, forKey: .updated)
        stale = (try? c.decodeIfPresent(Bool.self, forKey: .stale)) ?? false
    }
}

struct GrokBotStat: Codable {
    var ranges: QoderRanges
    var quota: ProviderQuotaStat

    static var empty: GrokBotStat {
        GrokBotStat(ranges: .empty, quota: ProviderQuotaStat())
    }

    init(ranges: QoderRanges, quota: ProviderQuotaStat) {
        self.ranges = ranges
        self.quota = quota
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ranges = (try? c.decodeIfPresent(QoderRanges.self, forKey: .ranges)) ?? .empty
        quota = (try? c.decodeIfPresent(ProviderQuotaStat.self, forKey: .quota))
            ?? ProviderQuotaStat()
    }
}

struct Usage: Codable {
    var claude: ClaudeStat
    var codex: CodexStat
    var gemini: GeminiStat
    var grok: GrokStat
    var grokBot: GrokBotStat
    var qoderwork: QoderStat
    var qoder: QoderIdeStat
    var qodercli: QoderStat
    var hermes: HermesStat
    var zcode: TokenUsageStat
    var mimocode: TokenUsageStat
    var openclaw: OpenClawStat
    var pi: TokenUsageStat
    var prime_agent: TokenUsageStat
    var workbuddy: TokenUsageStat
    var workbuddyAI: TokenUsageStat
    var deepseekHarness: TokenUsageStat
    var opencode: TokenUsageStat
    var qwencode: TokenUsageStat
    var qwenwork: QwenWorkQuota
    var kimicode: KimiCodeStat
    var antigravity: ProviderQuotaStat
    var cursor: ProviderQuotaStat
    var zed: ProviderQuotaStat
    var sub2api: ProviderQuotaStat
    var zai: ProviderQuotaStat

    enum CodingKeys: String, CodingKey {
        case claude, codex, gemini, grok, grokBot = "grok_bot"
        case qoder, qoderwork, qodercli, hermes, zcode, mimocode
        case openclaw, pi, workbuddy, workbuddyAI = "workbuddy_ai"
        case deepseekHarness = "deepseek_harness", opencode, qwencode
        case qwenwork, kimicode, prime_agent, antigravity, cursor, zed, sub2api, zai
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        claude = try c.decode(ClaudeStat.self, forKey: .claude)
        codex = try c.decode(CodexStat.self, forKey: .codex)
        gemini = try c.decode(GeminiStat.self, forKey: .gemini)
        grok = try c.decode(GrokStat.self, forKey: .grok)
        grokBot = try c.decodeIfPresent(GrokBotStat.self, forKey: .grokBot) ?? .empty
        qoderwork = (try? c.decodeIfPresent(QoderStat.self, forKey: .qoderwork))
            ?? (try? c.decodeIfPresent(QoderStat.self, forKey: .qoder))
            ?? QoderStat(ranges: .empty, model: nil)
        qoder = (try? c.decodeIfPresent(QoderIdeStat.self, forKey: .qoder))
            ?? QoderIdeStat(ranges: .empty, model: nil)
        qodercli = (try? c.decodeIfPresent(QoderStat.self, forKey: .qodercli))
            ?? QoderStat(ranges: .empty, model: nil)
        hermes = try c.decode(HermesStat.self, forKey: .hermes)
        zcode = try c.decodeIfPresent(TokenUsageStat.self, forKey: .zcode) ?? TokenUsageStat(ranges: .empty)
        mimocode = try c.decodeIfPresent(TokenUsageStat.self, forKey: .mimocode) ?? TokenUsageStat(ranges: .empty)
        openclaw = try c.decode(OpenClawStat.self, forKey: .openclaw)
        pi = try c.decodeIfPresent(TokenUsageStat.self, forKey: .pi) ?? TokenUsageStat(ranges: .empty)
        prime_agent = try c.decodeIfPresent(TokenUsageStat.self, forKey: .prime_agent) ?? TokenUsageStat(ranges: .empty)
        workbuddy = try c.decodeIfPresent(TokenUsageStat.self, forKey: .workbuddy) ?? TokenUsageStat(ranges: .empty)
        workbuddyAI = try c.decodeIfPresent(TokenUsageStat.self, forKey: .workbuddyAI) ?? TokenUsageStat(ranges: .empty)
        deepseekHarness = try c.decodeIfPresent(TokenUsageStat.self, forKey: .deepseekHarness) ?? TokenUsageStat(ranges: .empty)
        opencode = try c.decode(TokenUsageStat.self, forKey: .opencode)
        qwencode = try c.decodeIfPresent(TokenUsageStat.self, forKey: .qwencode) ?? TokenUsageStat(ranges: .empty)
        qwenwork = (try? c.decodeIfPresent(QwenWorkQuota.self, forKey: .qwenwork)) ?? QwenWorkQuota()
        kimicode = try c.decodeIfPresent(KimiCodeStat.self, forKey: .kimicode) ?? KimiCodeStat(ranges: .empty)
        antigravity = try c.decodeIfPresent(ProviderQuotaStat.self, forKey: .antigravity) ?? ProviderQuotaStat()
        cursor = try c.decodeIfPresent(ProviderQuotaStat.self, forKey: .cursor) ?? ProviderQuotaStat()
        zed = try c.decodeIfPresent(ProviderQuotaStat.self, forKey: .zed) ?? ProviderQuotaStat()
        sub2api = try c.decodeIfPresent(ProviderQuotaStat.self, forKey: .sub2api) ?? ProviderQuotaStat()
        zai = try c.decodeIfPresent(ProviderQuotaStat.self, forKey: .zai) ?? ProviderQuotaStat()
    }
}

enum Fmt {
    static func credits(_ n: Double) -> String {
        if abs(n.rounded() - n) < 0.000_001 {
            return String(format: "%.0f", n)
        }
        return String(format: "%.2f", n)
            .replacingOccurrences(of: "0+$", with: "", options: .regularExpression)
            .replacingOccurrences(of: "\\.$", with: "", options: .regularExpression)
    }

    static func human(_ n: Int) -> String {
        let v = Double(n)
        if v >= 100_000_000 { return String(format: "%.1f亿", v / 100_000_000) }
        if v >= 1_000_000 { return String(format: "%.1fM", v / 1_000_000) }
        if v >= 1_000 { return String(format: "%.0fK", v / 1_000) }
        return String(format: "%.0f", v)
    }

    /// 千分位精确写法，如 234,567,890。分隔符固定为逗号，不随语言环境变化。
    static func grouped(_ n: Int) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.groupingSeparator = ","
        formatter.usesGroupingSeparator = true
        return formatter.string(from: NSNumber(value: n)) ?? String(n)
    }

    static func reset(_ epoch: Int?) -> String {
        guard let e = epoch else { return "?" }
        let d = Date(timeIntervalSince1970: TimeInterval(e))
        let f = DateFormatter()
        f.dateFormat = "MM-dd HH:mm"
        return f.string(from: d)
    }

    static func day(_ epoch: Int?) -> String {
        guard let e = epoch else { return "?" }
        let f = DateFormatter()
        f.dateFormat = "MM-dd"
        return f.string(from: Date(timeIntervalSince1970: TimeInterval(e)))
    }

    static func beijingTime(_ epoch: Int, full: Bool = false) -> String {
        let d = Date(timeIntervalSince1970: TimeInterval(epoch))
        let f = DateFormatter()
        f.timeZone = TimeZone(identifier: "Asia/Shanghai")
        f.locale = Locale(identifier: "zh_CN")
        f.dateFormat = full ? "yyyy-MM-dd HH:mm:ss" : "MM-dd HH:mm"
        return f.string(from: d)
    }

    static func countdown(_ epoch: Int?) -> String {
        guard let e = epoch else { return "?" }
        let s = TimeInterval(e) - Date().timeIntervalSince1970
        if s <= 0 { return "即将重置" }
        let h = Int(s) / 3600, m = (Int(s) % 3600) / 60
        return h > 0 ? "\(h)h\(m)m" : "\(m)m"
    }

    static func duration(_ ms: Int) -> String {
        let s = ms / 1000
        if s >= 3600 { return String(format: "%dh%dm", s / 3600, (s % 3600) / 60) }
        if s >= 60 { return String(format: "%dm%ds", s / 60, s % 60) }
        return "\(s)s"
    }

    static func price(_ x: Double) -> String { String(format: "%g", x) }

    static func relativeDate(_ iso: String) -> String {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"
        guard let d = f.date(from: iso) else { return iso }
        let days = Calendar.current.dateComponents([.day], from: Calendar.current.startOfDay(for: d),
                                                    to: Calendar.current.startOfDay(for: Date())).day ?? 0
        if days == 0 { return "今天" }
        if days == 1 { return "昨天" }
        if days <= 7 { return "\(days)天前" }
        if days <= 30 { return "\(days / 7)周前" }
        return "\(days / 30)月前"
    }
}
