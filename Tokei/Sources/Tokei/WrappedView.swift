import SwiftUI

struct WrappedAchievement: Codable, Identifiable {
    var icon: String; var title: String; var desc: String
    var tint: String = "coral"
    var id: String { title }
}

struct WrappedProject: Codable, Identifiable {
    var name: String; var tokens: Int; var cost: Double
    var id: String { name }
}

struct WrappedBusiest: Codable { var date = ""; var tokens = 0 }
struct WrappedModel: Codable { var name = "-"; var tokens = 0 }
struct WrappedPeakDay: Codable { var date: String; var tokens: Int; var projects: [String]? }

struct WrappedData: Codable {
    var total_tokens = 0
    var total_cost: Double = 0
    var active_days = 0
    var streak_max = 0
    var streak_cur = 0
    var busiest = WrappedBusiest()
    var peak_days: [WrappedPeakDay]?          // 可选:老 JSON 缺字段时为 nil
    var day_projects: [String: [String]]?     // 日期→当日项目(合并视图回填用)
    var top_model = WrappedModel()
    var hours: [Int] = []
    var weekday: [Int] = []
    var projects: [WrappedProject] = []
    var max_projs_day = 0
    var night_share: Double = 0
    var first_day = ""
    var achievements: [WrappedAchievement] = []
    var period: String = "all"
}

enum WrappedPeriod: String, CaseIterable {
    case day = "1d", week = "7d", month = "30d", year = "365d", all = "all"
    var label: String {
        switch self {
        case .day: return "今日"
        case .week: return "本周"
        case .month: return "本月"
        case .year: return "今年"
        case .all: return "全部"
        }
    }
}

// Tokei 回顾 —— 作息 / 项目 / 连续 / 成就(Claude 数据)。
struct WrappedView: View {
    let data: WrappedData
    @Binding var period: WrappedPeriod
    var onPeriodChange: (WrappedPeriod) -> Void = { _ in }
    @State private var achievementsExpanded = false
    @State private var funSeed = 0
    @State private var showConfetti = false
    @State private var loadingPeriod = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            hero(data)
            statChips(data)
            if let peaks = data.peak_days, !peaks.isEmpty { peakDaysSection(peaks) }
            if !data.achievements.isEmpty { achievementsSection(data) }
            Divider().opacity(0.15)
            rhythmSection(data)
        }
        .overlay(alignment: .top) {
            if showConfetti { ConfettiView().frame(height: 220).allowsHitTesting(false) }
        }
        .onAppear {
            funSeed = Int.random(in: 0...2)
            if Self.checkMilestone(data.total_tokens) {
                showConfetti = true
                DispatchQueue.main.asyncAfter(deadline: .now() + 2.6) { showConfetti = false }
            }
            let titles = data.achievements.map { $0.title }
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.8) { Self.markSeen(titles) }
        }
    }

    // 成就"已见"集合 + token 里程碑档位(持久化,驱动金光/撒花)
    static func seenSet() -> Set<String> {
        Set(UserDefaults.standard.stringArray(forKey: "seenAchievements") ?? [])
    }
    static func markSeen(_ titles: [String]) {
        UserDefaults.standard.set(Array(seenSet().union(titles)), forKey: "seenAchievements")
    }
    static func checkMilestone(_ tokens: Int) -> Bool {
        let cur = tokens / 1_000_000_000          // 每 10 亿一档
        let last = UserDefaults.standard.integer(forKey: "lastTokenMilestone")
        if cur > last {
            UserDefaults.standard.set(cur, forKey: "lastTokenMilestone")
            return true
        }
        return false
    }

    // MARK: - Hero
    func hero(_ d: WrappedData) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 5) {
                Image(systemName: "sparkles").font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Theme.claude)
                Text("回顾").font(.system(size: 11, weight: .bold)).tracking(1.5)
                    .foregroundStyle(Theme.tSecondary)
                Spacer()
                periodPicker
            }
            HStack(spacing: 4) {
                if !d.first_day.isEmpty {
                    Text(period == .all ? "自 \(d.first_day)" : d.first_day)
                        .font(.system(size: 9, design: .monospaced)).foregroundStyle(Theme.tTertiary)
                }
                if d.active_days > 0 {
                    Text("· \(d.active_days) 天活跃")
                        .font(.system(size: 9, design: .monospaced)).foregroundStyle(Theme.tTertiary)
                }
            }
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(Fmt.human(d.total_tokens))
                    .font(.system(size: 32, weight: .heavy, design: .rounded))
                    .foregroundStyle(LinearGradient(colors: [Theme.claude, Theme.gemini],
                                                    startPoint: .leading, endPoint: .trailing))
                    .contentTransition(.numericText())
                Text("tokens").font(.system(size: 10.5)).foregroundStyle(Theme.tTertiary)
            }
            if d.total_cost > 0 {
                Text("💡 " + funFactText(d))
                    .font(.system(size: 9.5))
                    .foregroundStyle(.white.opacity(0.7))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(LinearGradient(colors: [Theme.claude.opacity(0.16), Theme.gemini.opacity(0.06)],
                                     startPoint: .topLeading, endPoint: .bottomTrailing))
                .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .strokeBorder(Theme.claude.opacity(0.12), lineWidth: 0.75))
        )
    }

    // MARK: - Stat chips
    func statChips(_ d: WrappedData) -> some View {
        let avg = d.active_days > 0 ? d.total_cost / Double(d.active_days) : 0
        return HStack(spacing: 7) {
            chip("总成本", "$" + intStr(d.total_cost), Theme.claude)
            chip("连续", "\(d.streak_cur) 天", Theme.hermes, icon: "flame.fill")
            chip("日均", "$" + intStr(avg), Theme.gemini)
            chip("峰值日", shortDate(d.busiest.date), Color.red.opacity(0.85))
            chip("本命模型", d.top_model.name, Theme.codex)
        }
    }

    func chip(_ label: String, _ value: String, _ tint: Color, icon: String? = nil) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label).font(.system(size: 9, weight: .medium)).foregroundStyle(tint.opacity(0.9))
            HStack(spacing: 3) {
                if let icon {
                    Image(systemName: icon).font(.system(size: 10, weight: .bold)).foregroundStyle(tint)
                }
                Text(value).font(.system(size: 12.5, weight: .bold, design: .rounded))
                    .foregroundStyle(.white).lineLimit(1).minimumScaleFactor(0.6)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, 7).padding(.horizontal, 9)
        .background(
            RoundedRectangle(cornerRadius: 11, style: .continuous)
                .fill(tint.opacity(0.10))
        )
    }

    // MARK: - Achievements
    func achievementsSection(_ d: WrappedData) -> some View {
        let limit = 10
        let hasMore = d.achievements.count > limit
        let shown = (achievementsExpanded || !hasMore) ? d.achievements : Array(d.achievements.prefix(limit))
        return VStack(alignment: .leading, spacing: 7) {
            HStack(spacing: 5) {
                Text("成就").font(.system(size: 13, weight: .bold)).foregroundStyle(Theme.tPrimary)
                Text("\(d.achievements.count)")
                    .font(.system(size: 9.5, weight: .bold, design: .rounded))
                    .foregroundStyle(Theme.claude)
                    .padding(.horizontal, 5).padding(.vertical, 1)
                    .background(Capsule().fill(Theme.claude.opacity(0.14)))
                Spacer()
                if hasMore {
                    Button {
                        withAnimation(.easeInOut(duration: 0.25)) { achievementsExpanded.toggle() }
                    } label: {
                        HStack(spacing: 3) {
                            Text(achievementsExpanded ? "收起" : "展开全部")
                                .font(.system(size: 10, weight: .medium))
                            Image(systemName: achievementsExpanded ? "chevron.up" : "chevron.down")
                                .font(.system(size: 8, weight: .bold))
                        }
                        .foregroundStyle(Theme.tTertiary)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
            LazyVGrid(columns: [GridItem(.flexible(), spacing: 7), GridItem(.flexible(), spacing: 7)],
                      spacing: 7) {
                let seen = Self.seenSet()
                ForEach(Array(shown.enumerated()), id: \.element.id) { i, a in
                    BadgeView(a: a, isNew: !seen.contains(a.title), delay: Double(i) * 0.07)
                }
            }
        }
    }


    // MARK: - 巅峰日 Top 3(现存日志 + 持久账本合并的单日高峰)
    func peakDaysSection(_ peaks: [WrappedPeakDay]) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            Text("巅峰日").font(.system(size: 13, weight: .bold)).foregroundStyle(Theme.tPrimary)
            VStack(spacing: 5) {
                ForEach(Array(peaks.prefix(3).enumerated()), id: \.element.date) { i, p in
                    HStack(spacing: 8) {
                        Text("\(i + 1)")
                            .font(.system(size: 10, weight: .bold, design: .rounded))
                            .foregroundStyle(.white)
                            .frame(width: 18, height: 18)
                            .background(
                                Circle().fill(i == 0 ? AnyShapeStyle(Theme.claude.gradient)
                                                     : AnyShapeStyle(Color.white.opacity(0.14)))
                            )
                        Text(peakDate(p.date))
                            .font(.system(size: 11.5, weight: .semibold))
                            .foregroundStyle(Theme.tPrimary)
                            .lineLimit(1)
                        Text(Fmt.human(p.tokens))
                            .font(.system(size: 9.5, design: .monospaced))
                            .foregroundStyle(Theme.tSecondary)
                        Spacer(minLength: 6)
                        if let projs = p.projects, !projs.isEmpty {
                            Text(projs.joined(separator: " · "))
                                .font(.system(size: 9))
                                .foregroundStyle(Theme.tTertiary)
                                .lineLimit(1)
                                .truncationMode(.tail)
                        }
                    }
                    .padding(.horizontal, 9).padding(.vertical, 6)
                    .background(RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .fill(Color.primary.opacity(0.05)))
                }
            }
        }
    }

    // "2026-07-21" → "7月21日";异常输入原样返回。
    func peakDate(_ s: String) -> String {
        let parts = s.split(separator: "-")
        guard parts.count == 3, let m = Int(parts[1]), let d = Int(parts[2]) else { return s }
        return "\(m)月\(d)日"
    }

    // MARK: - 24h rhythm
    func rhythmSection(_ d: WrappedData) -> some View {
        let maxH = max(d.hours.max() ?? 1, 1)
        let peak = d.hours.firstIndex(of: d.hours.max() ?? 0) ?? -1
        return VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("活跃时段").font(.system(size: 13, weight: .bold))
                Spacer()
                if peak >= 0 {
                    Text(String(format: "高峰 %02d:00", peak))
                        .font(.system(size: 9.5, design: .monospaced)).foregroundStyle(Theme.tTertiary)
                }
            }
            HStack(alignment: .bottom, spacing: 2) {
                ForEach(0..<24, id: \.self) { h in
                    let v = h < d.hours.count ? d.hours[h] : 0
                    let ratio = CGFloat(v) / CGFloat(maxH)
                    RoundedRectangle(cornerRadius: 2, style: .continuous)
                        .fill(h == peak ? AnyShapeStyle(Theme.claude.gradient)
                                        : AnyShapeStyle(Theme.claude.opacity(0.32)))
                        .frame(maxWidth: .infinity)
                        .frame(height: max(2, 48 * ratio))
                }
            }
            .frame(height: 48, alignment: .bottom)
            HStack(spacing: 0) {
                ForEach([0, 6, 12, 18, 23], id: \.self) { h in
                    Text("\(h)").font(.system(size: 8, design: .monospaced))
                        .foregroundStyle(Theme.tTertiary)
                    if h != 23 { Spacer() }
                }
            }
        }
    }

    // MARK: - Period picker
    var periodPicker: some View {
        HStack(spacing: 0) {
            ForEach(WrappedPeriod.allCases, id: \.rawValue) { p in
                Button {
                    guard p != period else { return }
                    period = p
                    loadingPeriod = true
                    onPeriodChange(p)
                } label: {
                    Text(p.label)
                        .font(.system(size: 9, weight: p == period ? .bold : .medium))
                        .foregroundStyle(p == period ? .white : Theme.tTertiary)
                        .padding(.horizontal, 7).padding(.vertical, 3)
                        .background(
                            p == period
                                ? AnyShapeStyle(Theme.claude.gradient)
                                : AnyShapeStyle(Color.clear)
                        )
                        .clipShape(Capsule())
                }
                .buttonStyle(.plain)
            }
        }
        .padding(2)
        .background(Capsule().fill(Color.primary.opacity(0.06)))
    }

    // MARK: - helpers
    // 成本换算彩蛋(随机:咖啡 / 火锅)
    func funFactText(_ d: WrappedData) -> String {
        let coffee = Int((d.total_cost / 4).rounded())
        let hotpot = Int((d.total_cost / 40).rounded())
        switch funSeed {
        case 0:  return "这些花费 ≈ \(coffee.formatted()) 杯咖啡 ☕"
        case 1:  return "这些花费 ≈ \(hotpot.formatted()) 顿火锅 🍲"
        default: return "这些 token ≈ 码了 \(Fmt.human(Int(Double(d.total_tokens) * 0.6))) 字 ✍️"
        }
    }

    func intStr(_ v: Double) -> String {
        let f = NumberFormatter(); f.numberStyle = .decimal; f.maximumFractionDigits = 0
        return f.string(from: NSNumber(value: Int(v))) ?? "\(Int(v))"
    }
    func shortDate(_ s: String) -> String { s.count >= 10 ? String(s.suffix(5)) : s }
}

// 成就徽章:新解锁时金光扫过 + 轻弹入。
struct BadgeView: View {
    let a: WrappedAchievement
    let isNew: Bool
    let delay: Double
    @State private var bounce: CGFloat = 1
    @State private var shimmer: CGFloat = -1.3

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: a.icon).font(.system(size: 12, weight: .bold))
                .foregroundStyle(.white)
                .frame(width: 26, height: 26)
                .background(
                    Circle().fill(LinearGradient(colors: [Theme.claude, Theme.claude.opacity(0.6)],
                                                 startPoint: .topLeading, endPoint: .bottomTrailing))
                )
                .overlay(Circle().strokeBorder(Color.white.opacity(0.22), lineWidth: 0.5))
                .shadow(color: Theme.claude.opacity(0.4), radius: 3, y: 1)
            VStack(alignment: .leading, spacing: 1) {
                Text(a.title).font(.system(size: 11.5, weight: .bold)).foregroundStyle(Theme.tPrimary)
                Text(a.desc).font(.system(size: 9)).foregroundStyle(Theme.tTertiary).lineLimit(1)
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 9).padding(.vertical, 7)
        .background(RoundedRectangle(cornerRadius: 10, style: .continuous)
            .fill(Color.primary.opacity(0.05)))
        .overlay {
            GeometryReader { geo in
                LinearGradient(colors: [.clear, .white.opacity(0.55), .clear],
                               startPoint: .leading, endPoint: .trailing)
                    .frame(width: geo.size.width * 0.45)
                    .offset(x: shimmer * geo.size.width)
                    .blendMode(.plusLighter)
            }
            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            .allowsHitTesting(false)
        }
        .scaleEffect(bounce)
        .onAppear {
            guard isNew else { return }
            bounce = 0.7
            withAnimation(.spring(response: 0.45, dampingFraction: 0.5).delay(delay)) {
                bounce = 1
            }
            withAnimation(.easeInOut(duration: 0.8).delay(delay + 0.1)) {
                shimmer = 1.3
            }
        }
    }
}

// 撒花:跨 token 里程碑时从顶部落下的彩屑。
struct ConfettiView: View {
    @State private var fall = false
    private let palette: [Color] = [Theme.claude, Theme.qoder, Theme.qoderwork, Theme.hermes,
                                    Theme.codex, Theme.gemini, Theme.zcode, Theme.mimocode,
                                    Theme.openclaw, Theme.deepseekHarness]
    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .top) {
                ForEach(0..<30, id: \.self) { i in
                    let frac = CGFloat((i * 37) % 100) / 100
                    let dur = 1.5 + Double((i * 13) % 10) / 10
                    let dly = Double((i * 7) % 8) / 10
                    RoundedRectangle(cornerRadius: 1.5)
                        .fill(palette[i % palette.count])
                        .frame(width: 6, height: 9)
                        .rotationEffect(.degrees(Double(i * 47)))
                        .offset(x: frac * geo.size.width,
                                y: fall ? geo.size.height + 40 : -40)
                        .opacity(fall ? 0 : 1)
                        .animation(.easeIn(duration: dur).delay(dly), value: fall)
                }
            }
        }
        .onAppear { fall = true }
        .allowsHitTesting(false)
    }
}
