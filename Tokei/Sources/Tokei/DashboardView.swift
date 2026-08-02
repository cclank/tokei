import SwiftUI

struct DailyCost: Codable, Identifiable {
    var date: String
    var claude: Double
    var codex: Double
    var pi: Double = 0
    var workbuddy: Double?
    var qwencode: Double?
    var total: Double
    var c_in: Int = 0
    var c_out: Int = 0
    var c_cr: Int = 0
    var c_cw: Int = 0
    var x_in: Int = 0
    var x_out: Int = 0
    var x_cached: Int = 0
    var x_reason: Int = 0
    var p_in: Int = 0
    var p_out: Int = 0
    var p_cr: Int = 0
    var p_cw: Int = 0
    var p_reason: Int = 0
    var w_in: Int?
    var w_out: Int?
    var w_cr: Int?
    var w_cw: Int?
    var q_in: Int?
    var q_out: Int?
    var q_cr: Int?
    var q_reason: Int?
    var g_in: Int?
    var g_out: Int?
    var g_cr: Int?
    var g_reason: Int?
    var tokens: Int = 0
    var id: String { date }
}

struct ModelCost: Codable, Identifiable {
    var name: String
    var cost: Double
    var tool: String
    var `in`: Int?
    var out: Int?
    var cr: Int?
    var cw: Int?
    var reason: Int?
    var tokens: Int?
    var cost_per_k: Double = 0
    var out_ratio: Double = 0
    var id: String { name }

    init(name: String, cost: Double, tool: String, input: Int? = nil, out: Int? = nil,
         cr: Int? = nil, cw: Int? = nil, reason: Int? = nil, tokens: Int? = nil,
         cost_per_k: Double = 0, out_ratio: Double = 0) {
        self.name = name
        self.cost = cost
        self.tool = tool
        self.in = input
        self.out = out
        self.cr = cr
        self.cw = cw
        self.reason = reason
        self.tokens = tokens
        self.cost_per_k = cost_per_k
        self.out_ratio = out_ratio
    }
}

struct DashboardData: Codable {
    var daily: [DailyCost]
    var models: [ModelCost]
}

struct DashboardPayload: Codable {
    var daily: [DailyCost]
    var models: [ModelCost]
    var wrapped: WrappedData
}

final class DashboardRepository: ObservableObject {
    static let shared = DashboardRepository()

    @Published private(set) var payloads: [String: DashboardPayload] = [:]
    private var loadedAt: [String: Date] = [:]
    private var inFlight: Set<String> = []
    private var forcedReloadPending: Set<String> = []
    private let freshness: TimeInterval = 30

    func payload(for period: WrappedPeriod) -> DashboardPayload? {
        payloads[period.rawValue]
    }

    func load(_ period: WrappedPeriod, force: Bool = false) {
        let key = period.rawValue
        if !force, let loaded = loadedAt[key], Date().timeIntervalSince(loaded) < freshness {
            return
        }
        guard inFlight.insert(key).inserted else {
            if force { forcedReloadPending.insert(key) }
            return
        }

        DispatchQueue.global(qos: .utility).async {
            let result = DataLoader.runScriptRaw(
                args: ["--dashboard", "--period", key],
                timeout: 30
            )
            let payload = result.exitCode == 0 && !result.timedOut
                ? try? JSONDecoder().decode(DashboardPayload.self, from: Data(result.stdout.utf8))
                : nil
            DispatchQueue.main.async {
                self.inFlight.remove(key)
                let shouldReload = self.forcedReloadPending.remove(key) != nil
                if let payload {
                    self.loadedAt[key] = Date()
                    self.payloads[key] = payload
                } else {
                    fputs("Tokei dashboard failed: exit=\(result.exitCode) timeout=\(result.timedOut)\n", stderr)
                }
                if shouldReload { self.load(period, force: true) }
            }
        }
    }
}

struct DashboardView: View {
    @ObservedObject var store: Store
    @ObservedObject private var dashboardRepository = DashboardRepository.shared
    @State private var daily: [DailyCost] = []
    @State private var models: [ModelCost] = []
    @State private var wrapped: WrappedData? = nil
    @State private var baseDaily: [DailyCost] = []
    @State private var baseModels: [ModelCost] = []
    @State private var baseWrapped: WrappedData? = nil
    @State private var loading = true
    @State private var wrappedPeriod: WrappedPeriod = .all
    @AppStorage("hideProjects") private var hideProjects = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            if loading {
                HStack { Spacer(); ProgressView().controlSize(.small); Spacer() }
                    .frame(height: 200)
            } else {
                if let w = wrapped, w.total_tokens > 0 {
                    WrappedView(data: w, period: $wrappedPeriod) { p in loadWrapped(p) }
                }
                if !daily.isEmpty {
                    Divider().opacity(0.15)
                    modelSection
                    if let w = wrapped, !w.projects.isEmpty {
                        Divider().opacity(0.15)
                        projectsSection(w.projects)
                    }
                    Divider().opacity(0.15)
                    heatmapSection
                }
            }
        }
        .onAppear { loadData(showLoading: true) }
        .onChange(of: store.showAllDevices) { _ in applyCachedScope(animated: true) }
        .onChange(of: store.syncEnabled) { _ in applyCachedScope(animated: true) }
        .onReceive(store.$usage) { _ in applyCachedScope(animated: false) }
        .onReceive(dashboardRepository.$payloads) { payloads in
            guard let payload = payloads[wrappedPeriod.rawValue] else { return }
            apply(payload, animated: false)
        }
    }

    // MARK: - Summary

    // MARK: - Model Chart

    var modelSection: some View {
        let sorted = models.sorted { ($0.tokens ?? 0) > ($1.tokens ?? 0) }
        let top = Array(sorted.prefix(8))
        let maxTokens = Double(top.first?.tokens ?? 1)
        return VStack(alignment: .leading, spacing: 9) {
            Text("模型用量").font(.system(size: 13, weight: .bold))
            ForEach(top) { m in
                StatBar(name: m.name,
                        tokens: m.tokens ?? ((m.in ?? 0) + (m.out ?? 0)),
                        cost: m.cost, maxTokens: maxTokens,
                        tint: modelTint(m.tool))
            }
        }
    }

    func modelTint(_ tool: String) -> Color {
        switch tool {
        case "codex": return Theme.codex
        case "gemini": return Theme.gemini
        case "grok": return Theme.grok
        case "qoder": return Theme.qoder
        case "hermes": return Theme.hermes
        case "zcode": return Theme.zcode
        case "mimocode": return Theme.mimocode
        case "openclaw": return Theme.openclaw
        case "pi": return Theme.pi
        case "workbuddy": return Theme.workbuddy
        case "opencode": return Theme.opencode
        case "qwencode": return Theme.qwencode
        default: return Theme.claude
        }
    }

    // MARK: - Projects
    func projectsSection(_ projects: [WrappedProject]) -> some View {
        let maxTok = Double(projects.first?.tokens ?? 1)
        return VStack(alignment: .leading, spacing: 9) {
            Button {
                withAnimation(.easeInOut(duration: 0.25)) { hideProjects.toggle() }
            } label: {
                HStack(spacing: 5) {
                    Text("项目排行").font(.system(size: 13, weight: .bold))
                        .foregroundStyle(Theme.tPrimary)
                    Image(systemName: hideProjects ? "eye.slash.fill" : "eye")
                        .font(.system(size: 9)).foregroundStyle(Theme.tTertiary)
                    Spacer()
                    Image(systemName: hideProjects ? "chevron.down" : "chevron.up")
                        .font(.system(size: 9, weight: .bold)).foregroundStyle(Theme.tTertiary)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            if hideProjects {
                Text("已隐藏 \(projects.count) 个项目")
                    .font(.system(size: 10)).foregroundStyle(Theme.tTertiary)
            } else {
                ForEach(projects) { p in
                    StatBar(name: p.name, tokens: p.tokens, cost: p.cost,
                            maxTokens: maxTok, tint: Theme.claude)
                }
            }
        }
    }

    // MARK: - Heatmap

    @State private var heatRange = 2  // 0=日(7天) 1=月 2=年
    @State private var selectedCell: String? = nil

    var heatmapSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("活跃热力")
                    .font(.system(size: 13, weight: .bold))
                Spacer()
                Picker("", selection: $heatRange) {
                    Text("周").tag(0); Text("月").tag(1); Text("年").tag(2)
                }
                .pickerStyle(.segmented)
                .frame(width: 120)
                .controlSize(.mini)
                .onChange(of: heatRange) { _ in selectedCell = nil }
            }
            if heatRange == 0 { weekStrip } else { heatmapGrid }
            if let sel = selectedCell, let day = daily.first(where: { $0.date == sel }) {
                heatDetail(day)
            }
            heatmapLegend
        }
    }

    func heatDetail(_ d: DailyCost) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(d.date).font(.system(size: 13, weight: .bold, design: .monospaced))
                    .foregroundStyle(Theme.tPrimary)
                Spacer()
                Text(String(format: "$%.2f", d.total))
                    .font(.system(size: 15, weight: .bold, design: .rounded))
                    .foregroundStyle(.white)
                Button { selectedCell = nil } label: {
                    Image(systemName: "xmark.circle.fill").font(.system(size: 12))
                        .foregroundStyle(Theme.tTertiary)
                }
                .buttonStyle(.plain)
            }
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 105), spacing: 12)],
                      alignment: .leading, spacing: 8) {
                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 4) {
                        Circle().fill(Theme.claude).frame(width: 6, height: 6)
                        Text("Claude").font(.system(size: 11, weight: .medium)).foregroundStyle(Theme.claude)
                    }
                    Text("\(Fmt.human(d.c_in + d.c_out + d.c_cr + d.c_cw)) tok")
                        .font(.system(size: 11, design: .monospaced)).foregroundStyle(Theme.tTertiary)
                    Text(String(format: "$%.2f", d.claude))
                        .font(.system(size: 12, weight: .semibold, design: .monospaced)).foregroundStyle(Theme.tSecondary)
                }
                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 4) {
                        Circle().fill(Theme.codex).frame(width: 6, height: 6)
                        Text("Codex").font(.system(size: 11, weight: .medium)).foregroundStyle(Theme.codex)
                    }
                    Text("\(Fmt.human(d.x_in + d.x_out)) tok")
                        .font(.system(size: 11, design: .monospaced)).foregroundStyle(Theme.tTertiary)
                    Text(String(format: "$%.2f", d.codex))
                        .font(.system(size: 12, weight: .semibold, design: .monospaced)).foregroundStyle(Theme.tSecondary)
                }
                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 4) {
                        Circle().fill(Theme.pi).frame(width: 6, height: 6)
                        Text("Pi").font(.system(size: 11, weight: .medium)).foregroundStyle(Theme.pi)
                    }
                    Text("\(Fmt.human(d.p_in + d.p_out + d.p_cr + d.p_cw + d.p_reason)) tok")
                        .font(.system(size: 11, design: .monospaced)).foregroundStyle(Theme.tTertiary)
                    Text(String(format: "$%.2f", d.pi))
                        .font(.system(size: 12, weight: .semibold, design: .monospaced)).foregroundStyle(Theme.tSecondary)
                }
                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 4) {
                        Circle().fill(Theme.workbuddy).frame(width: 6, height: 6)
                        Text("WorkBuddy").font(.system(size: 11, weight: .medium)).foregroundStyle(Theme.workbuddy)
                    }
                    Text("\(Fmt.human((d.w_in ?? 0) + (d.w_out ?? 0) + (d.w_cr ?? 0) + (d.w_cw ?? 0))) tok")
                        .font(.system(size: 11, design: .monospaced)).foregroundStyle(Theme.tTertiary)
                    Text(String(format: "$%.2f", d.workbuddy ?? 0))
                        .font(.system(size: 12, weight: .semibold, design: .monospaced)).foregroundStyle(Theme.tSecondary)
                }
                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 4) {
                        Circle().fill(Theme.qwencode).frame(width: 6, height: 6)
                        Text("Qwen Code").font(.system(size: 11, weight: .medium)).foregroundStyle(Theme.qwencode)
                    }
                    Text("\(Fmt.human((d.q_in ?? 0) + (d.q_out ?? 0) + (d.q_cr ?? 0) + (d.q_reason ?? 0))) tok")
                        .font(.system(size: 11, design: .monospaced)).foregroundStyle(Theme.tTertiary)
                    Text(String(format: "$%.2f", d.qwencode ?? 0))
                        .font(.system(size: 12, weight: .semibold, design: .monospaced)).foregroundStyle(Theme.tSecondary)
                }
                if (d.g_in ?? 0) + (d.g_out ?? 0) + (d.g_cr ?? 0) + (d.g_reason ?? 0) > 0 {
                    VStack(alignment: .leading, spacing: 3) {
                        HStack(spacing: 4) {
                            Circle().fill(Theme.grok).frame(width: 6, height: 6)
                            Text("Grok Build").font(.system(size: 11, weight: .medium)).foregroundStyle(Theme.grok)
                        }
                        Text("\(Fmt.human((d.g_in ?? 0) + (d.g_out ?? 0) + (d.g_cr ?? 0) + (d.g_reason ?? 0))) tok")
                            .font(.system(size: 11, design: .monospaced)).foregroundStyle(Theme.tTertiary)
                        Text("成本未提供")
                            .font(.system(size: 10, weight: .medium)).foregroundStyle(Theme.tTertiary)
                    }
                }
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous)
            .fill(Color.black.opacity(0.3))
            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous)
                .strokeBorder(Theme.claude.opacity(0.2), lineWidth: 0.5)))
    }

    var weekStrip: some View {
        let cal = Calendar.current
        let today = Date()
        let fmt = DateFormatter()
        fmt.dateFormat = "yyyy-MM-dd"
        let dayLabels = ["一", "二", "三", "四", "五", "六", "日"]
        let costMap = Dictionary(uniqueKeysWithValues: daily.map { ($0.date, $0.total) })
        let maxCost = daily.map(\.total).max() ?? 1

        return HStack(alignment: .top, spacing: 4) {
            VStack(spacing: 2) {
                ForEach(0..<7, id: \.self) { r in
                    Text(dayLabels[r])
                        .font(.system(size: 8, weight: .medium))
                        .foregroundStyle(Theme.tTertiary)
                        .frame(width: 14, height: 20)
                }
            }
            ForEach(0..<1, id: \.self) { _ in
                VStack(spacing: 2) {
                    ForEach(0..<7, id: \.self) { i in
                        let realD = cal.date(byAdding: .day, value: -(6 - i), to: today)!
                        let ds = fmt.string(from: realD)
                        let cost = costMap[ds] ?? 0
                        HStack(spacing: 6) {
                            RoundedRectangle(cornerRadius: 3, style: .continuous)
                                .fill(heatColor(cost: cost, max: maxCost))
                                .frame(width: 20, height: 20)
                                .overlay(
                                    RoundedRectangle(cornerRadius: 3, style: .continuous)
                                        .strokeBorder(selectedCell == ds ? Theme.claude : .clear, lineWidth: 1.5)
                                )
                                .onTapGesture {
                                    withAnimation(.easeOut(duration: 0.2)) {
                                        selectedCell = selectedCell == ds ? nil : ds
                                    }
                                }
                            Text(String(ds.suffix(5)))
                                .font(.system(size: 9, design: .monospaced))
                                .foregroundStyle(Theme.tTertiary)
                                .frame(width: 38, alignment: .leading)
                            if cost > 0 {
                                Text(String(format: "$%.0f", cost))
                                    .font(.system(size: 10, weight: .semibold, design: .monospaced))
                                    .foregroundStyle(Theme.tSecondary)
                            }
                        }
                    }
                }
            }
        }
    }

    var heatmapGrid: some View {
        let cal = Calendar.current
        let today = Date()
        let totalDays: Int = heatRange == 1 ? 35 : 371
        let startDate = cal.date(byAdding: .day, value: -(totalDays - 1), to: today)!
        let costMap = Dictionary(uniqueKeysWithValues: daily.map { ($0.date, $0.total) })
        let maxCost = daily.map(\.total).max() ?? 1

        let fmt = DateFormatter()
        fmt.dateFormat = "yyyy-MM-dd"
        let dayLabels = ["一", "二", "三", "四", "五", "六", "日"]

        struct Cell: Identifiable {
            var id: Int; var row: Int; var col: Int; var cost: Double; var dateStr: String
        }

        var cells: [Cell] = []
        let startWeekday = (cal.component(.weekday, from: startDate) + 5) % 7
        for i in 0..<totalDays {
            guard let d = cal.date(byAdding: .day, value: i, to: startDate) else { continue }
            let ds = fmt.string(from: d)
            let offset = startWeekday + i
            let row = offset % 7
            let col = offset / 7
            cells.append(Cell(id: i, row: row, col: col, cost: costMap[ds] ?? 0, dateStr: ds))
        }
        let cols = (cells.last?.col ?? 0) + 1
        let cellSize: CGFloat = heatRange == 1 ? 20 : 12
        let gap: CGFloat = heatRange == 1 ? 3 : 2
        let radius: CGFloat = heatRange == 1 ? 4 : 2.5

        return HStack(alignment: .top, spacing: 4) {
            VStack(spacing: gap) {
                ForEach(0..<7, id: \.self) { r in
                    Text(dayLabels[r])
                        .font(.system(size: heatRange == 2 ? 8 : 10, weight: .medium))
                        .foregroundStyle(Theme.tTertiary)
                        .frame(width: 16, height: cellSize)
                }
            }
            ScrollViewReader { proxy in
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: gap) {
                        ForEach(0..<cols, id: \.self) { c in
                            VStack(spacing: gap) {
                                ForEach(0..<7, id: \.self) { r in
                                    let cell = cells.first { $0.row == r && $0.col == c }
                                    let ds = cell?.dateStr ?? ""
                                    let cost = cell?.cost ?? 0
                                    RoundedRectangle(cornerRadius: radius, style: .continuous)
                                        .fill(heatColor(cost: cost, max: maxCost))
                                        .frame(width: cellSize, height: cellSize)
                                    .overlay(
                                        RoundedRectangle(cornerRadius: radius, style: .continuous)
                                            .strokeBorder(selectedCell == ds ? Theme.claude : .clear, lineWidth: 2)
                                    )
                                    .onTapGesture {
                                        withAnimation(.easeOut(duration: 0.2)) {
                                            selectedCell = selectedCell == ds ? nil : ds
                                        }
                                    }
                                }
                            }
                            .id(c)
                        }
                        Color.clear.frame(width: 1, height: 1).id("heatEnd")
                    }
                }
                .onAppear {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                        proxy.scrollTo("heatEnd", anchor: .trailing)
                    }
                }
                .onChange(of: heatRange) { _ in
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                        proxy.scrollTo("heatEnd", anchor: .trailing)
                    }
                }
            }
        }
    }

    static let heatColors: [Color] = [
        Color(red: 0.18, green: 0.20, blue: 0.24),       // L0: 深灰(无活动)
        Color(red: 0.45, green: 0.32, blue: 0.22),       // L1: 暗棕
        Color(red: 0.72, green: 0.42, blue: 0.25),       // L2: 暖铜
        Color(red: 0.90, green: 0.55, blue: 0.30),       // L3: 亮橙
        Color(red: 0.98, green: 0.72, blue: 0.35),       // L4: 金黄
    ]

    func heatColor(cost: Double, max: Double) -> Color {
        if cost <= 0 { return Color.primary.opacity(0.04) }
        let ratio = min(cost / max, 1.0)
        if ratio < 0.15 { return Self.heatColors[1] }
        if ratio < 0.35 { return Self.heatColors[2] }
        if ratio < 0.60 { return Self.heatColors[3] }
        return Self.heatColors[4]
    }

    var heatmapLegend: some View {
        HStack(spacing: 5) {
            Spacer()
            Text("少").font(.system(size: 10)).foregroundStyle(Theme.tTertiary)
            ForEach(0..<5, id: \.self) { i in
                RoundedRectangle(cornerRadius: 2.5, style: .continuous)
                    .fill(i == 0 ? Color.primary.opacity(0.04) : Self.heatColors[i])
                    .frame(width: 12, height: 12)
            }
            Text("多").font(.system(size: 10)).foregroundStyle(Theme.tTertiary)
        }
    }

    func loadData(showLoading: Bool = false) {
        if let cached = dashboardRepository.payload(for: wrappedPeriod) {
            apply(cached, animated: false)
        } else if showLoading || (daily.isEmpty && models.isEmpty && wrapped == nil) {
            loading = true
        }
        dashboardRepository.load(wrappedPeriod)
    }

    func loadWrapped(_ period: WrappedPeriod) {
        if let cached = dashboardRepository.payload(for: period) {
            apply(cached, animated: true)
        }
        dashboardRepository.load(period)
    }

    func apply(_ payload: DashboardPayload, animated: Bool) {
        baseDaily = payload.daily
        baseModels = payload.models
        baseWrapped = payload.wrapped
        applyCachedScope(animated: animated)
        loading = false
    }

    func applyCachedScope(animated: Bool) {
        let update = {
            let fallback = DashboardData(daily: baseDaily, models: baseModels)
            if let scoped = scopedUsage() {
                let scopedDaily = allDeviceDaily(period: wrappedPeriod)
                daily = scopedDaily
                models = Self.dashboardData(from: scoped, period: wrappedPeriod, fallback: fallback).models
                wrapped = allDeviceWrapped(from: scoped, period: wrappedPeriod, daily: scopedDaily)
            } else {
                daily = baseDaily
                models = baseModels
                wrapped = baseWrapped
            }
            if !daily.isEmpty || !models.isEmpty || wrapped != nil {
                loading = false
            }
        }
        if animated {
            withAnimation(.easeInOut(duration: 0.22), update)
        } else {
            update()
        }
    }

    private func scopedUsage() -> Usage? {
        guard store.syncEnabled, store.showAllDevices, !store.peers.isEmpty else { return nil }
        return store.allDevicesUsage ?? store.usage
    }

    private func peerDashboards() -> [PeerDashboardSnapshot] {
        store.peers.compactMap(\.dashboard)
    }

    private func allDeviceDaily(period: WrappedPeriod) -> [DailyCost] {
        var byDate: [String: DailyCost] = [:]
        for item in baseDaily {
            if let existing = byDate[item.date] {
                byDate[item.date] = Self.mergeDaily(existing, item)
            } else {
                byDate[item.date] = item
            }
        }
        for snapshot in peerDashboards() {
            for item in snapshot.daily where Self.includes(dateString: item.date, in: period) {
                if let existing = byDate[item.date] {
                    byDate[item.date] = Self.mergeDaily(existing, item)
                } else {
                    byDate[item.date] = item
                }
            }
        }
        return byDate.values.sorted { $0.date < $1.date }
    }

    private func allDeviceWrapped(from usage: Usage, period: WrappedPeriod, daily scopedDaily: [DailyCost]) -> WrappedData {
        let peerWrapped = store.peers.compactMap { peer -> WrappedData? in
            guard let dashboard = peer.dashboard,
                  Self.rangeBoundsMatch(peer.rangeBounds, period: period) else { return nil }
            return dashboard.wrapped[period.rawValue]
        }
        var data = Self.wrappedData(from: usage, period: period, fallback: baseWrapped)

        data.hours = Self.sumArrays(([baseWrapped?.hours ?? []] + peerWrapped.map(\.hours)), count: 24)
        data.weekday = Self.sumArrays(([baseWrapped?.weekday ?? []] + peerWrapped.map(\.weekday)), count: 7)
        data.projects = Self.mergeProjects(([baseWrapped?.projects ?? []] + peerWrapped.map(\.projects)).flatMap { $0 })
        data.max_projs_day = ([baseWrapped?.max_projs_day ?? 0] + peerWrapped.map(\.max_projs_day)).max() ?? 0
        data.night_share = Self.nightShare(from: data.hours)

        let activeDays = scopedDaily.filter { $0.tokens > 0 || $0.total > 0 }.map(\.date).sorted()
        data.active_days = activeDays.count
        let streak = Self.streakInfo(activeDays)
        data.streak_max = streak.max
        data.streak_cur = streak.current
        if let busiest = scopedDaily.max(by: { $0.tokens < $1.tokens }) {
            data.busiest = WrappedBusiest(date: busiest.date, tokens: busiest.tokens)
        }

        let firstCandidates = ([baseWrapped?.first_day ?? ""] + peerWrapped.map(\.first_day) + activeDays)
            .filter { !$0.isEmpty }
        data.first_day = firstCandidates.min() ?? data.first_day
        data.period = period.rawValue
        return data
    }

    static func rangeBoundsMatch(_ peerBounds: [String: RangeBoundary], period: WrappedPeriod) -> Bool {
        if period == .all { return true }
        let key = rangeKey(for: period)
        guard let peer = peerBounds[key.rawValue],
              let local = SyncManager.currentRangeBounds()[key] else { return false }
        return peer == local
    }

    static func dashboardData(from usage: Usage, period: WrappedPeriod, fallback: DashboardData?) -> DashboardData {
        DashboardData(daily: fallback?.daily ?? [], models: usageModels(from: usage, period: period))
    }

    static func wrappedData(from usage: Usage, period: WrappedPeriod, fallback: WrappedData?) -> WrappedData {
        let key = rangeKey(for: period)
        let totalTokens = usageTotalTokens(usage, key)
        let totalCost = usageTotalCost(usage, key)
        let modelList = usageModels(from: usage, period: period)
        let top = modelList.max { ($0.tokens ?? 0) < ($1.tokens ?? 0) }
        var data = fallback ?? WrappedData()
        data.total_tokens = totalTokens
        data.total_cost = totalCost
        data.top_model = WrappedModel(name: top?.name ?? "-", tokens: top?.tokens ?? 0)
        data.period = period.rawValue
        if data.first_day.isEmpty {
            data.first_day = firstDay(for: period)
        }
        return data
    }

    static func rangeKey(for period: WrappedPeriod) -> RangeKey {
        switch period {
        case .day: return .today
        case .week: return .week
        case .month: return .month
        case .year: return .year
        case .all: return .all
        }
    }

    static func firstDay(for period: WrappedPeriod) -> String {
        let today = Date()
        let cal = Calendar.current
        let fmt = DateFormatter()
        fmt.dateFormat = "yyyy-MM-dd"
        switch period {
        case .day:
            return fmt.string(from: today)
        case .week:
            let weekday = cal.component(.weekday, from: today)
            let daysFromMonday = (weekday + 5) % 7
            return fmt.string(from: cal.date(byAdding: .day, value: -daysFromMonday, to: today) ?? today)
        case .month:
            let start = cal.date(from: cal.dateComponents([.year, .month], from: today)) ?? today
            return fmt.string(from: start)
        case .year:
            let start = cal.date(from: cal.dateComponents([.year], from: today)) ?? today
            return fmt.string(from: start)
        case .all:
            return ""
        }
    }

    static func includes(dateString: String, in period: WrappedPeriod) -> Bool {
        guard let start = firstDayString(for: period) else { return true }
        if period == .day { return dateString == start }
        return dateString >= start
    }

    static func firstDayString(for period: WrappedPeriod) -> String? {
        let today = Date()
        let cal = Calendar.current
        let fmt = DateFormatter()
        fmt.dateFormat = "yyyy-MM-dd"
        switch period {
        case .all:
            return nil
        case .day:
            return fmt.string(from: today)
        case .week:
            let weekday = cal.component(.weekday, from: today)
            let daysFromMonday = (weekday + 5) % 7
            return fmt.string(from: cal.date(byAdding: .day, value: -daysFromMonday, to: today) ?? today)
        case .month:
            let start = cal.date(from: cal.dateComponents([.year, .month], from: today)) ?? today
            return fmt.string(from: start)
        case .year:
            let start = cal.date(from: cal.dateComponents([.year], from: today)) ?? today
            return fmt.string(from: start)
        }
    }

    static func mergeDaily(_ lhs: DailyCost, _ rhs: DailyCost) -> DailyCost {
        DailyCost(date: lhs.date,
                  claude: lhs.claude + rhs.claude,
                  codex: lhs.codex + rhs.codex,
                  pi: lhs.pi + rhs.pi,
                  workbuddy: (lhs.workbuddy ?? 0) + (rhs.workbuddy ?? 0),
                  qwencode: (lhs.qwencode ?? 0) + (rhs.qwencode ?? 0),
                  total: lhs.total + rhs.total,
                  c_in: lhs.c_in + rhs.c_in,
                  c_out: lhs.c_out + rhs.c_out,
                  c_cr: lhs.c_cr + rhs.c_cr,
                  c_cw: lhs.c_cw + rhs.c_cw,
                  x_in: lhs.x_in + rhs.x_in,
                  x_out: lhs.x_out + rhs.x_out,
                  x_cached: lhs.x_cached + rhs.x_cached,
                  x_reason: lhs.x_reason + rhs.x_reason,
                  p_in: lhs.p_in + rhs.p_in,
                  p_out: lhs.p_out + rhs.p_out,
                  p_cr: lhs.p_cr + rhs.p_cr,
                  p_cw: lhs.p_cw + rhs.p_cw,
                  p_reason: lhs.p_reason + rhs.p_reason,
                  w_in: (lhs.w_in ?? 0) + (rhs.w_in ?? 0),
                  w_out: (lhs.w_out ?? 0) + (rhs.w_out ?? 0),
                  w_cr: (lhs.w_cr ?? 0) + (rhs.w_cr ?? 0),
                  w_cw: (lhs.w_cw ?? 0) + (rhs.w_cw ?? 0),
                  q_in: (lhs.q_in ?? 0) + (rhs.q_in ?? 0),
                  q_out: (lhs.q_out ?? 0) + (rhs.q_out ?? 0),
                  q_cr: (lhs.q_cr ?? 0) + (rhs.q_cr ?? 0),
                  q_reason: (lhs.q_reason ?? 0) + (rhs.q_reason ?? 0),
                  g_in: (lhs.g_in ?? 0) + (rhs.g_in ?? 0),
                  g_out: (lhs.g_out ?? 0) + (rhs.g_out ?? 0),
                  g_cr: (lhs.g_cr ?? 0) + (rhs.g_cr ?? 0),
                  g_reason: (lhs.g_reason ?? 0) + (rhs.g_reason ?? 0),
                  tokens: lhs.tokens + rhs.tokens)
    }

    static func sumArrays(_ arrays: [[Int]], count: Int) -> [Int] {
        var out = Array(repeating: 0, count: count)
        for array in arrays {
            for i in 0..<min(count, array.count) {
                out[i] += array[i]
            }
        }
        return out
    }

    static func mergeProjects(_ projects: [WrappedProject]) -> [WrappedProject] {
        var byName: [String: WrappedProject] = [:]
        for project in projects {
            if var existing = byName[project.name] {
                existing.tokens += project.tokens
                existing.cost += project.cost
                byName[project.name] = existing
            } else {
                byName[project.name] = project
            }
        }
        return byName.values.sorted { $0.tokens > $1.tokens }.prefix(8).map { $0 }
    }

    static func nightShare(from hours: [Int]) -> Double {
        let total = hours.reduce(0, +)
        guard total > 0 else { return 0 }
        let night = hours.prefix(6).reduce(0, +)
        return Double(night) / Double(total) * 100
    }

    static func streakInfo(_ dates: [String]) -> (max: Int, current: Int) {
        let fmt = DateFormatter()
        fmt.dateFormat = "yyyy-MM-dd"
        let days = dates.compactMap { fmt.date(from: $0) }.sorted()
        guard !days.isEmpty else { return (0, 0) }
        let cal = Calendar.current
        var maxRun = 1
        var run = 1
        for i in 1..<days.count {
            let gap = cal.dateComponents([.day], from: days[i - 1], to: days[i]).day ?? 0
            run = gap == 1 ? run + 1 : 1
            maxRun = max(maxRun, run)
        }
        let today = cal.startOfDay(for: Date())
        let last = cal.startOfDay(for: days.last ?? today)
        guard let gapToToday = cal.dateComponents([.day], from: last, to: today).day, gapToToday <= 1 else {
            return (maxRun, 0)
        }
        var current = 1
        if days.count > 1 {
            for i in stride(from: days.count - 1, through: 1, by: -1) {
                let gap = cal.dateComponents([.day], from: days[i - 1], to: days[i]).day ?? 0
                guard gap == 1 else { break }
                current += 1
            }
        }
        return (maxRun, current)
    }

    static func usageModels(from usage: Usage, period: WrappedPeriod) -> [ModelCost] {
        let key = rangeKey(for: period)
        var out: [ModelCost] = []

        let claude = usage.claude.ranges.get(key)
        for model in claude.models where model.total > 0 || model.cost > 0 {
            out.append(modelCost(name: model.name, cost: model.cost, tool: "claude",
                                 input: model.in, out: model.out, cr: model.cr, cw: model.cw,
                                 tokens: model.total))
        }

        let codex = usage.codex.ranges.get(key)
        let codexTokens = codex.in + codex.cached + codex.out
        if !codex.models.isEmpty {
            for model in codex.models {
                let tokens = model.in + model.cr + model.cw + model.out
                if tokens > 0 || model.cost > 0 {
                    out.append(modelCost(name: "\(model.name) (Codex)", cost: model.cost, tool: "codex",
                                         input: model.in, out: model.out, cr: model.cr, cw: model.cw,
                                         reason: model.reason, tokens: tokens))
                }
            }
        } else if codexTokens > 0 || codex.cost > 0 {
            out.append(modelCost(name: "Codex", cost: codex.cost, tool: "codex",
                                 input: codex.in + codex.cached, out: codex.out,
                                 reason: codex.reason, tokens: codexTokens))
        }

        let gemini = usage.gemini.ranges.get(key)
        for model in gemini.models {
            let tokens = model.in + model.out + model.cached + model.thoughts
            if tokens > 0 || model.cost > 0 {
                out.append(modelCost(name: model.name, cost: model.cost, tool: "gemini",
                                     input: model.in + model.cached, out: model.out,
                                     reason: model.thoughts, tokens: tokens))
            }
        }

        let grok = usage.grok.ranges.get(key)
        if !grok.models.isEmpty {
            appendTokenModels(grok.models, tool: "grok", suffix: "Grok Build", to: &out)
        } else if grok.usage_available && grok.tokens > 0 {
            out.append(modelCost(name: usage.grok.model ?? "Grok Build", cost: 0,
                                 tool: "grok", tokens: grok.tokens))
        }

        let qoderwork = usage.qoderwork.ranges.get(key)
        let qoderworkTokens = qoderwork.in + qoderwork.out
        if qoderworkTokens > 0 {
            let model = usage.qoderwork.model ?? "QoderWork"
            out.append(modelCost(name: "\(model) (QoderWork)", cost: 0, tool: "qoderwork",
                                 input: qoderwork.in, out: qoderwork.out, tokens: qoderworkTokens))
        }

        let qoder = usage.qoder.ranges.get(key)
        let qoderTokens = qoder.in + qoder.cached + qoder.out
        if qoderTokens > 0 {
            out.append(modelCost(name: usage.qoder.model ?? "Qoder Desktop", cost: 0, tool: "qoder",
                                 input: qoder.in + qoder.cached, out: qoder.out, tokens: qoderTokens))
        }

        appendTokenModels(usage.hermes.ranges.get(key).models, tool: "hermes", suffix: "Hermes", to: &out)
        appendTokenModels(usage.zcode.ranges.get(key).models, tool: "zcode", suffix: "ZCode", to: &out)
        appendTokenModels(usage.mimocode.ranges.get(key).models, tool: "mimocode", suffix: "MiMoCode", to: &out)
        appendTokenModels(usage.openclaw.ranges.get(key).models, tool: "openclaw", suffix: "OpenClaw", to: &out)
        appendTokenModels(usage.pi.ranges.get(key).models, tool: "pi", suffix: "Pi", to: &out)
        appendTokenModels(usage.workbuddy.ranges.get(key).models, tool: "workbuddy", suffix: "WorkBuddy", to: &out)
        appendTokenModels(usage.opencode.ranges.get(key).models, tool: "opencode", suffix: "OpenCode", to: &out)
        appendTokenModels(usage.qwencode.ranges.get(key).models, tool: "qwencode", suffix: "Qwen Code", to: &out)

        return out.sorted {
            if ($0.tokens ?? 0) != ($1.tokens ?? 0) { return ($0.tokens ?? 0) > ($1.tokens ?? 0) }
            return $0.cost > $1.cost
        }
    }

    static func appendTokenModels(_ models: [TokenModelStat], tool: String, suffix: String, to out: inout [ModelCost]) {
        for model in models {
            let tokens = tokenModelTotal(model)
            if tokens > 0 || model.cost > 0 {
                out.append(modelCost(name: "\(model.name) (\(suffix))", cost: model.cost, tool: tool,
                                     input: model.in, out: model.out, cr: model.cr, cw: model.cw,
                                     reason: model.reason, tokens: tokens))
            }
        }
    }

    static func modelCost(name: String, cost: Double, tool: String, input: Int? = nil, out: Int? = nil,
                          cr: Int? = nil, cw: Int? = nil, reason: Int? = nil, tokens: Int? = nil) -> ModelCost {
        let inputTokens = input ?? 0
        let outputTokens = out ?? 0
        let cacheReadTokens = cr ?? 0
        let cacheWriteTokens = cw ?? 0
        let reasonTokens = reason ?? 0
        let total = tokens ?? (inputTokens + outputTokens + cacheReadTokens + cacheWriteTokens + reasonTokens)
        let outK = Double(outputTokens) / 1000
        let costPerK = outK > 0 ? cost / outK : 0
        let outRatio = total > 0 ? Double(outputTokens) / Double(total) * 100 : 0
        return ModelCost(name: name, cost: cost, tool: tool, input: input, out: out,
                         cr: cr, cw: cw, reason: reason, tokens: total,
                         cost_per_k: costPerK, out_ratio: outRatio)
    }

    static func usageTotalTokens(_ usage: Usage, _ key: RangeKey) -> Int {
        let claude = usage.claude.ranges.get(key)
        let codex = usage.codex.ranges.get(key)
        let gemini = usage.gemini.ranges.get(key)
        let grok = usage.grok.ranges.get(key)
        let qoderwork = usage.qoderwork.ranges.get(key)
        let qoder = usage.qoder.ranges.get(key)
        return claude.in + claude.out + claude.cr + claude.cw
            + codex.in + codex.cached + codex.out
            + gemini.in + gemini.cached + gemini.out + gemini.thoughts
            + (grok.usage_available ? grok.tokens : 0)
            + qoderwork.in + qoderwork.out
            + qoder.in + qoder.cached + qoder.out
            + hermesTotal(usage.hermes.ranges.get(key))
            + tokenUsageTotal(usage.zcode.ranges.get(key))
            + tokenUsageTotal(usage.mimocode.ranges.get(key))
            + openClawTotal(usage.openclaw.ranges.get(key))
            + tokenUsageTotal(usage.pi.ranges.get(key))
            + tokenUsageTotal(usage.workbuddy.ranges.get(key))
            + tokenUsageTotal(usage.opencode.ranges.get(key))
            + tokenUsageTotal(usage.qwencode.ranges.get(key))
    }

    static func usageTotalCost(_ usage: Usage, _ key: RangeKey) -> Double {
        usage.claude.ranges.get(key).cost
            + usage.codex.ranges.get(key).cost
            + usage.gemini.ranges.get(key).cost
            + usage.hermes.ranges.get(key).cost
            + usage.zcode.ranges.get(key).cost
            + usage.mimocode.ranges.get(key).cost
            + usage.openclaw.ranges.get(key).cost
            + usage.pi.ranges.get(key).cost
            + usage.workbuddy.ranges.get(key).cost
            + usage.opencode.ranges.get(key).cost
            + usage.qwencode.ranges.get(key).cost
    }

    static func tokenUsageTotal(_ r: TokenUsageRange) -> Int {
        r.in + r.out + r.cr + r.cw + r.reason
    }

    static func hermesTotal(_ r: HermesRange) -> Int {
        r.in + r.out + r.cr + r.cw + r.reason
    }

    static func openClawTotal(_ r: OpenClawRange) -> Int {
        r.in + r.out + r.cr + r.cw
    }

    static func tokenModelTotal(_ m: TokenModelStat) -> Int {
        m.in + m.out + m.cr + m.cw + m.reason
    }

    static func runScript(_ args: [String]) -> Data {
        let result = DataLoader.runScriptRaw(args: args, timeout: 90)
        return Data(result.stdout.utf8)
    }

}
