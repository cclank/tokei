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
}

struct GeminiRanges: Codable {
    var today: GeminiRange
    var yesterday: GeminiRange
    var week: GeminiRange
    var last_week: GeminiRange
    var month: GeminiRange
    var year: GeminiRange
    var all: GeminiRange?
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
    var name: String
    var `in`: Int
    var out: Int
    var cr: Int = 0
    var cw: Int = 0
    var reason: Int = 0
    var cost: Double
    var pin: Double = 0
    var pout: Double = 0
    var id: String { name }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        `in` = try c.decodeIfPresent(Int.self, forKey: .in) ?? 0
        out = try c.decodeIfPresent(Int.self, forKey: .out) ?? 0
        cr = try c.decodeIfPresent(Int.self, forKey: .cr) ?? 0
        cw = try c.decodeIfPresent(Int.self, forKey: .cw) ?? 0
        reason = try c.decodeIfPresent(Int.self, forKey: .reason) ?? 0
        cost = try c.decodeIfPresent(Double.self, forKey: .cost) ?? 0
        pin = try c.decodeIfPresent(Double.self, forKey: .pin) ?? 0
        pout = try c.decodeIfPresent(Double.self, forKey: .pout) ?? 0
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
    var hit: Double
    var `in`: Int
    var out: Int
    var cr: Int
    var cw: Int
    var reason: Int
    var cost: Double
    var sessions: Int = 0
    var models: [TokenModelStat] = []

    init(hit: Double = 0, `in` input: Int = 0, out: Int = 0, cr: Int = 0, cw: Int = 0,
         reason: Int = 0, cost: Double = 0, sessions: Int = 0, models: [TokenModelStat] = []) {
        self.hit = hit
        self.in = input
        self.out = out
        self.cr = cr
        self.cw = cw
        self.reason = reason
        self.cost = cost
        self.sessions = sessions
        self.models = models
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        hit = try c.decodeIfPresent(Double.self, forKey: .hit) ?? 0
        `in` = try c.decodeIfPresent(Int.self, forKey: .in) ?? 0
        out = try c.decodeIfPresent(Int.self, forKey: .out) ?? 0
        cr = try c.decodeIfPresent(Int.self, forKey: .cr) ?? 0
        cw = try c.decodeIfPresent(Int.self, forKey: .cw) ?? 0
        reason = try c.decodeIfPresent(Int.self, forKey: .reason) ?? 0
        cost = try c.decodeIfPresent(Double.self, forKey: .cost) ?? 0
        sessions = try c.decodeIfPresent(Int.self, forKey: .sessions) ?? 0
        models = try c.decodeIfPresent([TokenModelStat].self, forKey: .models) ?? []
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

struct Usage: Codable {
    var claude: ClaudeStat
    var codex: CodexStat
    var gemini: GeminiStat
    var grok: GrokStat
    var qoderwork: QoderStat
    var qoder: QoderIdeStat
    var qodercli: QoderStat
    var hermes: HermesStat
    var zcode: TokenUsageStat
    var mimocode: TokenUsageStat
    var openclaw: OpenClawStat
    var pi: TokenUsageStat
    var workbuddy: TokenUsageStat
    var opencode: TokenUsageStat
    var qwencode: TokenUsageStat
    var deepseek_harness: TokenUsageStat

    enum CodingKeys: String, CodingKey {
        case claude, codex, gemini, grok, qoder, qoderwork, qodercli, hermes, zcode, mimocode
        case openclaw, pi, workbuddy, opencode, qwencode, deepseek_harness
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        claude = try c.decode(ClaudeStat.self, forKey: .claude)
        codex = try c.decode(CodexStat.self, forKey: .codex)
        gemini = try c.decode(GeminiStat.self, forKey: .gemini)
        grok = try c.decode(GrokStat.self, forKey: .grok)
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
        workbuddy = try c.decodeIfPresent(TokenUsageStat.self, forKey: .workbuddy) ?? TokenUsageStat(ranges: .empty)
        opencode = try c.decode(TokenUsageStat.self, forKey: .opencode)
        qwencode = try c.decodeIfPresent(TokenUsageStat.self, forKey: .qwencode) ?? TokenUsageStat(ranges: .empty)
        deepseek_harness = try c.decodeIfPresent(TokenUsageStat.self, forKey: .deepseek_harness)
            ?? TokenUsageStat(ranges: .empty)
    }
}

enum Fmt {
    static func human(_ n: Int) -> String {
        let v = Double(n)
        if v >= 100_000_000 { return String(format: "%.1f亿", v / 100_000_000) }
        if v >= 1_000_000 { return String(format: "%.1fM", v / 1_000_000) }
        if v >= 1_000 { return String(format: "%.0fK", v / 1_000) }
        return String(format: "%.0f", v)
    }

    static func reset(_ epoch: Int?) -> String {
        guard let e = epoch else { return "?" }
        let d = Date(timeIntervalSince1970: TimeInterval(e))
        let f = DateFormatter()
        f.dateFormat = "MM-dd HH:mm"
        return f.string(from: d)
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
