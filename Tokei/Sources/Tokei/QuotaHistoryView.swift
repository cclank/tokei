import Charts
import SwiftUI

private extension QuotaHistoryTool {
    var tint: Color { self == .claude ? Theme.claude : Theme.codex }
}

private enum QuotaHistorySpan: Int, CaseIterable, Identifiable {
    case hour = 1
    case sixHours = 6
    case day = 24
    case week = 168
    case month = 720
    case year = 8760

    var id: Int { rawValue }
    var label: String {
        switch self {
        case .hour: return "1h"
        case .sixHours: return "6h"
        case .day: return "24h"
        case .week: return "1周"
        case .month: return "1月"
        case .year: return "1年"
        }
    }
    var axisStride: Int {
        switch self {
        case .hour: return 1
        case .sixHours: return 2
        case .day: return 6
        case .week: return 24
        default: return 24
        }
    }
    /// 跨度超过一天时,每个刻度都写 HH:mm 会重复出现 00:00,改标日期。
    var axisShowsDate: Bool { rawValue >= 168 }
    /// 额度% 快照只留 7 天,再长的跨度没有曲线可画,改用账本里的每日消耗。
    var showsDailyTokens: Bool { self == .month || self == .year }
    var days: Int { max(rawValue / 24, 1) }
}

private struct QuotaHistoryFrame {
    var now: Date
    var start: Date
    var projection: QuotaHistoryProjection
}

struct QuotaHistoryView: View {
    static let dayFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "MM-dd"
        return formatter
    }()
    private static let collapsedCycleLimit = 8

    @ObservedObject var history: QuotaHistoryStore
    let onLoad: () -> Void
    @ObservedObject private var detail = QuotaDetailRepository.shared
    @State private var tool: QuotaHistoryTool = .claude
    @State private var span: QuotaHistorySpan = .day
    @State private var cycleTool: String?
    @State private var expandedCycleHistory: Set<String> = []

    /// 有周期数据的工具,固定顺序 —— 免得刷新一次卡片就换个位置。
    private var cycleTools: [String] {
        let present = Set((detail.payload?.cycles ?? []).map(\.tool))
        return ["claude", "codex", "grok"].filter(present.contains)
    }

    private var visibleCycleTools: [String] {
        guard let cycleTool, cycleTools.contains(cycleTool) else { return cycleTools }
        return [cycleTool]
    }

    private func currentCycle(_ tool: String) -> QuotaCycle? {
        (detail.payload?.cycles ?? []).first { $0.tool == tool && $0.current }
    }

    private func completedCycles(_ tool: String) -> [QuotaCycle] {
        (detail.payload?.cycles ?? [])
            .filter { $0.tool == tool && !$0.current }
            .sorted { $0.start > $1.start }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 13) {
            cycleSection
            controls
            if span.showsDailyTokens {
                dailyTokensSection
            } else {
                quotaCurveSection
            }
            footnote
        }
        .onAppear(perform: onLoad)
    }

    @ViewBuilder
    private var quotaCurveSection: some View {
        let frame = makeFrame()
        Card(tint: tool.tint) {
            VStack(alignment: .leading, spacing: 12) {
                summary(frame.projection)
                if frame.projection.lineData.isEmpty {
                    emptyState
                } else {
                    quotaChart(frame)
                }
            }
        }
        dailyConsumptionSection(frame.projection)
        changesSection(frame.projection)
        activitySection(frame.projection)
    }

    /// 按天汇总的额度消耗（issue #85）：每天消耗了周额度的多少个百分点。
    @ViewBuilder
    private func dailyConsumptionSection(_ projection: QuotaHistoryProjection) -> some View {
        let rows = projection.dailyConsumption.filter { $0.window == dailyConsumptionWindow }
        if !rows.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Text("每天用了多少额度")
                    .font(.system(size: Theme.fontSize(12), weight: .bold))
                    .foregroundStyle(Theme.tPrimary)
                let maxConsumed = max(rows.map(\.consumed).max() ?? 0, 0.05)
                ForEach(Array(rows.prefix(7))) { row in
                    HStack(spacing: 8) {
                        Text(Self.dayFormatter.string(from: row.dayStart))
                            .font(.system(size: Theme.fontSize(9.5), design: .monospaced))
                            .foregroundStyle(Theme.tTertiary)
                            .frame(width: 36, alignment: .leading)
                        GeometryReader { proxy in
                            RoundedRectangle(cornerRadius: 2)
                                .fill(seriesColor(for: row.window).opacity(row.isComplete ? 0.85 : 0.4))
                                .frame(width: max(2, proxy.size.width * CGFloat(row.consumed / maxConsumed)))
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .frame(width: 90, height: 8)
                        Text((row.isComplete ? "" : "约 ") + String(format: "%.1f%%", row.consumed))
                            .font(.system(size: Theme.fontSize(10.5), weight: .semibold, design: .monospaced))
                            .foregroundStyle(Theme.tPrimary)
                            .frame(width: 62, alignment: .trailing)
                        if row.resets > 0 {
                            Text("回满×\(row.resets)")
                                .font(.system(size: Theme.fontSize(9)))
                                .foregroundStyle(Theme.tTertiary)
                        }
                        if !row.isComplete {
                            Text("采样不全")
                                .font(.system(size: Theme.fontSize(9)))
                                .foregroundStyle(Theme.tTertiary)
                        }
                        Spacer()
                    }
                }
            }
        }
    }

    /// 每日消耗默认看的窗口：Codex 看周，Claude 看周 · 全部。
    private var dailyConsumptionWindow: String {
        tool == .codex ? "周" : "周 · 全部"
    }

    private var footnote: some View {
        Text(span.showsDailyTokens
             ? "长跨度画的是每日真实 token 消耗，已合并所有设备的账本（CLI 清理旧日志也不缩水）；额度百分比快照只保留 7 天，画不了这么长。"
             : "额度曲线来自本机定时快照；每日消耗是当天剩余额度下降量之和（回满不抵扣），采样不足 20 小时的天标“约”；模型标记来自同一分钟内本地会话 token 增量，仅表示相关活动，不等同于官方逐模型扣费归因。")
            .font(.system(size: Theme.fontSize(9.5)))
            .foregroundStyle(Theme.tTertiary)
            .fixedSize(horizontal: false, vertical: true)
    }

    // MARK: - 周额度消耗

    private var cycleSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            cycleHeader
            if detail.payload == nil {
                Card(tint: Theme.codex) { cyclePlaceholder("正在读取周额度…") }
            } else if visibleCycleTools.isEmpty {
                Card(tint: Theme.codex) {
                    cyclePlaceholder("所有订阅的额度重置时间都拿不到，定位不了周期")
                }
            } else {
                ForEach(visibleCycleTools, id: \.self) { tool in
                    cycleGroup(tool)
                }
            }
            if cycleTool == nil {
                ForEach(missingTools, id: \.self) { tool in
                    Text(missingHint(tool))
                        .font(.system(size: Theme.fontSize(9)))
                        .foregroundStyle(Theme.tTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    private var cycleHeader: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text("一个周额度用了多少")
                    .font(.system(size: Theme.fontSize(14), weight: .bold))
                    .foregroundStyle(Theme.tPrimary)
                Text(cycleSubtitle)
                    .font(.system(size: Theme.fontSize(9.5)))
                    .foregroundStyle(Theme.tTertiary)
            }
            Spacer()
            if cycleTools.count > 1 {
                Picker("", selection: $cycleTool) {
                    Text("全部").tag(String?.none)
                    ForEach(cycleTools, id: \.self) { tool in
                        Text(cycleName(tool)).tag(String?.some(tool))
                    }
                }
                .pickerStyle(.segmented)
                .frame(width: CGFloat(54 * (cycleTools.count + 1) + 24))
                .controlSize(.mini)
            }
        }
    }

    private var cycleSubtitle: String {
        var text = "从上次额度回满算到下次回满"
        if let devices = detail.payload?.devices, devices.count > 1 {
            text += " · \(devices.count) 台设备已合并"
        }
        // 首屏是上次落盘的缓存,刷新完会自己变,标出来免得误当成实时值。
        if detail.refreshing && detail.payload != nil {
            text += " · 更新中"
        }
        return text
    }

    /// 一个 harness 一块:当前周期和历史周期共用同一张卡片。
    @ViewBuilder
    private func cycleGroup(_ tool: String) -> some View {
        let past = completedCycles(tool)
        if let cycle = currentCycle(tool) {
            Card(tint: cycleTint(tool)) {
                VStack(alignment: .leading, spacing: 12) {
                    cycleCard(cycle)
                    if !past.isEmpty {
                        Divider()
                            .overlay(cycleTint(tool).opacity(0.18))
                        completedCyclesSection(tool, past, compactTitle: true)
                    }
                }
            }
        } else if !past.isEmpty {
            Card(tint: cycleTint(tool)) {
                completedCyclesSection(tool, past, compactTitle: false)
            }
        }
    }

    /// 拿不到额度读数的工具 —— 周期切不出来,得告诉用户怎么把它找回来。
    private var missingTools: [String] {
        detail.payload?.missing ?? []
    }

    private func missingHint(_ tool: String) -> String {
        switch tool {
        case "claude":
            return "Claude Code 还没有周额度卡片：可打开 Claude Desktop 的 Usage 页面，"
                + "或在设置的「隐私与额度」开启 Claude Code CLI 额度查询。"
        case "grok":
            return "Grok 还没有周额度卡片：登录一次 grok.com 让 Tokei 抓到额度读数。"
        default:
            return "Codex 还没有周额度卡片：跑一次 codex 让它刷新额度读数。"
        }
    }

    private func cycleCard(_ cycle: QuotaCycle) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text("\(cycleName(cycle.tool)) 周额度")
                    .font(.system(size: Theme.fontSize(12), weight: .bold))
                    .foregroundStyle(cycleTint(cycle.tool))
                Spacer()
                Text("\(Fmt.countdown(cycle.end)) 后回满")
                    .font(.system(size: Theme.fontSize(9.5)))
                    .foregroundStyle(Theme.tTertiary)
            }
            if let used = cycle.used_pct {
                cycleProgress(used, tint: cycleTint(cycle.tool))
            }
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("这个周期已经用了")
                        .font(.system(size: Theme.fontSize(9.5)))
                        .foregroundStyle(Theme.tTertiary)
                    HStack(alignment: .firstTextBaseline, spacing: 7) {
                        Text((cycle.approx ? "≈" : "") + Fmt.human(cycle.tokens))
                            .font(.system(size: Theme.fontSize(25), weight: .bold, design: .rounded))
                            .foregroundStyle(Theme.tPrimary)
                            .lineLimit(1)
                            .minimumScaleFactor(0.6)
                        Text("tokens")
                            .font(.system(size: Theme.fontSize(10)))
                            .foregroundStyle(Theme.tTertiary)
                    }
                    Text(Fmt.grouped(cycle.tokens))
                        .font(.system(size: Theme.fontSize(9.5), design: .monospaced))
                        .foregroundStyle(Theme.tTertiary)
                }
                Spacer()
                if let projected = cycle.projectedTotal {
                    VStack(alignment: .trailing, spacing: 2) {
                        Text("照这个用法，整个周期约")
                            .font(.system(size: Theme.fontSize(9.5)))
                            .foregroundStyle(Theme.tTertiary)
                        Text(Fmt.human(projected))
                            .font(.system(size: Theme.fontSize(17), weight: .bold, design: .rounded))
                            .foregroundStyle(Theme.tSecondary)
                            .lineLimit(1)
                            .minimumScaleFactor(0.6)
                    }
                }
            }
            if cycle.deviceBreakdown.count > 1 {
                Text(cycle.deviceBreakdown
                        .map { "\($0.name) \(Fmt.human($0.tokens))" }
                        .joined(separator: "  ·  "))
                    .font(.system(size: Theme.fontSize(9), design: .monospaced))
                    .foregroundStyle(Theme.tTertiary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
            }
        }
    }

    private func cycleProgress(_ used: Double, tint: Color) -> some View {
        HStack(spacing: 8) {
            GeometryReader { geometry in
                let ratio = min(max(used, 0), 100) / 100
                ZStack(alignment: .leading) {
                    Capsule()
                        .fill(Color.white.opacity(0.08))
                    Capsule()
                        .fill(tint.opacity(0.85))
                        .frame(width: geometry.size.width * ratio)
                }
            }
            .frame(height: 7)
            Text(String(format: "已用 %.0f%%", used))
                .font(.system(size: Theme.fontSize(10), weight: .semibold, design: .monospaced))
                .foregroundStyle(Theme.tSecondary)
                .frame(width: 62, alignment: .trailing)
        }
    }

    private func completedCyclesSection(
        _ tool: String,
        _ cycles: [QuotaCycle],
        compactTitle: Bool
    ) -> some View {
        let peak = max(cycles.map(\.tokens).max() ?? 1, 1)
        let uneven = cycles.contains { $0.durationDays < 6.5 }
        let expanded = expandedCycleHistory.contains(tool)
        let visibleCycles = expanded
            ? cycles
            : Array(cycles.prefix(Self.collapsedCycleLimit))
        let hiddenCount = max(0, cycles.count - Self.collapsedCycleLimit)
        return VStack(alignment: .leading, spacing: 6) {
            Text(compactTitle ? "过去几个周期" : "\(cycleName(tool)) 过去几个周期")
                .font(.system(size: Theme.fontSize(11), weight: .semibold))
                .foregroundStyle(Theme.tSecondary)
            if uneven {
                Text("不足 7 天的是重置时间被提前重锚，额度提前回满，长度不一样不能直接比。")
                    .font(.system(size: Theme.fontSize(9)))
                    .foregroundStyle(Theme.tTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            ForEach(visibleCycles) { cycle in
                HStack(spacing: 8) {
                    Text("\(Fmt.day(cycle.start)) → \(Fmt.day(cycle.end))")
                        .font(.system(size: Theme.fontSize(9.5), design: .monospaced))
                        .foregroundStyle(Theme.tTertiary)
                        .frame(width: 92, alignment: .leading)
                    Text(String(format: "%.1f天", cycle.durationDays))
                        .font(.system(size: Theme.fontSize(9.5), design: .monospaced))
                        .foregroundStyle(Theme.tTertiary)
                        .frame(width: 38, alignment: .trailing)
                    GeometryReader { geometry in
                        Capsule()
                            .fill(cycleTint(tool).opacity(0.55))
                            .frame(
                                width: geometry.size.width
                                    * CGFloat(cycle.tokens) / CGFloat(peak)
                            )
                    }
                    .frame(height: 7)
                    Text((cycle.approx ? "≈" : "") + Fmt.human(cycle.tokens))
                        .font(.system(size: Theme.fontSize(11), weight: .semibold, design: .rounded))
                        .foregroundStyle(Theme.tSecondary)
                        .frame(width: 52, alignment: .trailing)
                    Text(cycle.used_pct.map { String(format: "用到%.0f%%", $0) } ?? "—")
                        .font(.system(size: Theme.fontSize(9), design: .monospaced))
                        .foregroundStyle(Theme.tTertiary)
                        .frame(width: 52, alignment: .trailing)
                }
            }
            if hiddenCount > 0 {
                Button {
                    withAnimation(.easeInOut(duration: 0.2)) {
                        if expanded {
                            expandedCycleHistory.remove(tool)
                        } else {
                            expandedCycleHistory.insert(tool)
                        }
                    }
                } label: {
                    HStack(spacing: 5) {
                        Image(systemName: expanded ? "chevron.up" : "chevron.down")
                        Text(expanded ? "收起更早周期" : "查看更早的 \(hiddenCount) 个周期")
                        Spacer(minLength: 0)
                    }
                    .font(.system(size: Theme.fontSize(9.5), weight: .semibold))
                    .foregroundStyle(cycleTint(tool).opacity(0.9))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .padding(.top, 2)
            }
        }
    }

    private func cycleName(_ tool: String) -> String {
        switch tool {
        case "claude": return "Claude Code"
        case "grok": return "Grok"
        default: return "Codex"
        }
    }

    private func cycleTint(_ tool: String) -> Color {
        switch tool {
        case "claude": return Theme.claude
        case "grok": return Theme.grok
        default: return Theme.codex
        }
    }

    private func cyclePlaceholder(_ text: String) -> some View {
        HStack {
            Spacer()
            Text(text)
                .font(.system(size: Theme.fontSize(11)))
                .foregroundStyle(Theme.tTertiary)
            Spacer()
        }
        .frame(height: 58)
    }

    // MARK: - 长跨度每日消耗

    private var dailyTokensSection: some View {
        let points = recentDailyPoints
        let claude = points.reduce(0) { $0 + $1.c }
        let codex = points.reduce(0) { $0 + $1.x }
        let grok = points.reduce(0) { $0 + $1.g }
        return Card(tint: Theme.codex) {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .top, spacing: 12) {
                    dailyStat("Claude Code", claude, Theme.claude)
                    dailyStat("Codex", codex, Theme.codex)
                    dailyStat("Grok", grok, Theme.grok)
                    dailyStat("合计", claude + codex + grok, Theme.tPrimary)
                }
                if points.isEmpty {
                    dailyEmpty
                } else {
                    QuotaDailyChart(points: points)
                }
            }
        }
    }

    private var recentDailyPoints: [QuotaDailyPoint] {
        // 账本只存有用量的日子,按行数取后 N 条会跨出区间,必须按日期截断。
        let cutoff = Calendar.current.date(
            byAdding: .day, value: -(span.days - 1), to: Date()
        ) ?? Date()
        let key = Self.dayKeyFormatter.string(from: cutoff)
        return (detail.payload?.daily ?? []).filter { $0.d >= key }
    }

    private func dailyStat(_ title: String, _ tokens: Int, _ tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(.system(size: Theme.fontSize(9.5)))
                .foregroundStyle(Theme.tTertiary)
            Text(Fmt.human(tokens))
                .font(.system(size: Theme.fontSize(19), weight: .bold, design: .rounded))
                .foregroundStyle(tint)
                .lineLimit(1)
                .minimumScaleFactor(0.6)
            Text(Fmt.grouped(tokens))
                .font(.system(size: Theme.fontSize(9), design: .monospaced))
                .foregroundStyle(Theme.tTertiary)
                .lineLimit(1)
                .minimumScaleFactor(0.6)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var dailyEmpty: some View {
        VStack(spacing: 8) {
            Image(systemName: "chart.bar.xaxis")
                .font(.system(size: Theme.fontSize(24)))
                .foregroundStyle(Theme.codex.opacity(0.8))
            Text("账本里还没有这个区间的用量")
                .font(.system(size: Theme.fontSize(12), weight: .semibold))
                .foregroundStyle(Theme.tSecondary)
        }
        .frame(maxWidth: .infinity)
        .frame(height: 210)
    }

    private var controls: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text("额度轨迹")
                    .font(.system(size: Theme.fontSize(14), weight: .bold))
                    .foregroundStyle(Theme.tPrimary)
                Text(span.showsDailyTokens ? "按天聚合 · 真实 token 消耗" : "按分钟聚合 · 剩余额度")
                    .font(.system(size: Theme.fontSize(9.5)))
                    .foregroundStyle(Theme.tTertiary)
            }
            Spacer()
            if !span.showsDailyTokens {
                Picker("", selection: $tool) {
                    ForEach(QuotaHistoryTool.allCases) { tool in
                        Text(tool.rawValue).tag(tool)
                    }
                }
                .pickerStyle(.segmented)
                .frame(width: 164)
                .controlSize(.mini)
            }
            Picker("", selection: $span) {
                ForEach(QuotaHistorySpan.allCases) { span in
                    Text(span.label).tag(span)
                }
            }
            .pickerStyle(.segmented)
            .frame(width: 216)
            .controlSize(.mini)
        }
    }

    private func summary(_ projection: QuotaHistoryProjection) -> some View {
        HStack(spacing: 13) {
            ForEach(projection.windowNames, id: \.self) { window in
                quotaSummary(
                    title: summaryTitle(for: window),
                    value: projection.latestValues[window],
                    tint: seriesColor(for: window)
                )
            }
            VStack(alignment: .leading, spacing: 3) {
                Text("采样点")
                    .font(.system(size: Theme.fontSize(9.5)))
                    .foregroundStyle(Theme.tTertiary)
                Text("\(projection.points.count)")
                    .font(.system(size: Theme.fontSize(15), weight: .bold, design: .rounded))
                    .foregroundStyle(Theme.tPrimary)
            }
            Spacer()
            if let largest = projection.dropEvents.max(by: { $0.drop < $1.drop }) {
                VStack(alignment: .trailing, spacing: 3) {
                    Text("最大区间下降")
                        .font(.system(size: Theme.fontSize(9.5)))
                        .foregroundStyle(Theme.tTertiary)
                    Text(String(format: "-%.1f%% / %dmin", largest.drop, largest.durationMinutes))
                        .font(.system(size: Theme.fontSize(12), weight: .semibold, design: .monospaced))
                        .foregroundStyle(seriesColor(for: largest.window))
                }
            }
        }
    }

    private func quotaSummary(title: String, value: Double?, tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(.system(size: Theme.fontSize(9.5)))
                .foregroundStyle(Theme.tTertiary)
            Text(value.map { String(format: "%.1f%%", $0) } ?? "—")
                .font(.system(size: Theme.fontSize(15), weight: .bold, design: .rounded))
                .foregroundStyle(value.map { $0 <= 15 ? Color.red : tint } ?? Theme.tTertiary)
        }
    }

    private func quotaChart(_ frame: QuotaHistoryFrame) -> some View {
        QuotaHistoryChart(
            projection: frame.projection,
            start: frame.start,
            end: frame.now,
            span: span,
            colors: Dictionary(
                uniqueKeysWithValues: frame.projection.windowNames.map {
                    ($0, seriesColor(for: $0))
                }
            )
        )
    }

    private var emptyState: some View {
        VStack(spacing: 8) {
            Image(systemName: "chart.xyaxis.line")
                .font(.system(size: Theme.fontSize(24)))
                .foregroundStyle(tool.tint.opacity(0.8))
            Text("正在开始记录额度轨迹")
                .font(.system(size: Theme.fontSize(12), weight: .semibold))
                .foregroundStyle(Theme.tSecondary)
            Text("Tokei 每 30 秒刷新，曲线按分钟聚合。保持应用运行后，这里会逐步出现数据。")
                .font(.system(size: Theme.fontSize(10)))
                .foregroundStyle(Theme.tTertiary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .frame(height: 210)
    }

    private func changesSection(_ projection: QuotaHistoryProjection) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("最近额度变化")
                .font(.system(size: Theme.fontSize(12), weight: .bold))
                .foregroundStyle(Theme.tPrimary)
            if projection.dropEvents.isEmpty {
                Text("当前时间范围内还没有检测到额度下降")
                    .font(.system(size: Theme.fontSize(10)))
                    .foregroundStyle(Theme.tTertiary)
            } else {
                ForEach(Array(projection.dropEvents.prefix(8))) { event in
                    HStack(spacing: 8) {
                        Text(Self.timeFormatter.string(from: event.timestamp))
                            .font(.system(size: Theme.fontSize(9.5), design: .monospaced))
                            .foregroundStyle(Theme.tTertiary)
                            .frame(width: 40, alignment: .leading)
                        Text(event.window)
                            .font(.system(size: Theme.fontSize(9.5), weight: .semibold))
                            .foregroundStyle(tool.tint)
                            .frame(width: 42, alignment: .leading)
                        Text(String(format: "-%.1f%%", event.drop))
                            .font(.system(size: Theme.fontSize(10.5), weight: .semibold, design: .monospaced))
                            .foregroundStyle(Theme.tPrimary)
                            .frame(width: 54, alignment: .trailing)
                        Text("\(event.durationMinutes) 分钟")
                            .font(.system(size: Theme.fontSize(9.5)))
                            .foregroundStyle(Theme.tTertiary)
                        activityText(event.activity)
                        Spacer()
                    }
                }
            }
        }
    }

    private func activitySection(_ projection: QuotaHistoryProjection) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("模型活动标记")
                .font(.system(size: Theme.fontSize(12), weight: .bold))
                .foregroundStyle(Theme.tPrimary)
            if projection.activityEvents.isEmpty {
                Text("尚未检测到该工具的模型 token 增量")
                    .font(.system(size: Theme.fontSize(10)))
                    .foregroundStyle(Theme.tTertiary)
            } else {
                ForEach(Array(projection.activityEvents.prefix(8))) { event in
                    HStack(spacing: 8) {
                        Text(Self.timeFormatter.string(
                            from: Date(timeIntervalSince1970: TimeInterval(event.timestamp))
                        ))
                            .font(.system(size: Theme.fontSize(9.5), design: .monospaced))
                            .foregroundStyle(Theme.tTertiary)
                            .frame(width: 40, alignment: .leading)
                        activityText(event.activity)
                        Spacer()
                    }
                }
            }
        }
    }

    private func activityText(_ activity: [QuotaModelActivity]) -> some View {
        Text(activity.map { "\($0.model) +\(Fmt.human($0.tokenDelta))" }.joined(separator: " · "))
            .font(.system(size: Theme.fontSize(9.5), design: .monospaced))
            .foregroundStyle(Theme.tSecondary)
            .lineLimit(1)
    }

    private func makeFrame() -> QuotaHistoryFrame {
        let now = Date()
        let start = now.addingTimeInterval(TimeInterval(-span.rawValue * 60 * 60))
        return QuotaHistoryFrame(
            now: now,
            start: start,
            projection: QuotaHistoryProjection(
                points: history.points(since: start),
                tool: tool
            )
        )
    }

    private func seriesColor(for window: String) -> Color {
        switch (tool, window) {
        case (.claude, "5 小时"):
            return Color(red: 1.00, green: 0.43, blue: 0.28)
        case (.claude, "周 · 全部"):
            return Color(red: 0.66, green: 0.55, blue: 1.00)
        case (.claude, "周 · Fable"):
            return Color(red: 1.00, green: 0.72, blue: 0.16)
        case (.codex, "周"):
            return Theme.codex
        default:
            return tool.tint
        }
    }

    private func summaryTitle(for window: String) -> String {
        window == "5 小时" ? "5h 剩余" : "\(window)剩余"
    }

    private static let timeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter
    }()

    private static let dayKeyFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }()
}

/// 长跨度下画每日真实 token 消耗:额度% 快照只保留 7 天,月/年区间没有曲线可画。
private struct QuotaDailyChart: View {
    let points: [QuotaDailyPoint]

    @State private var hover: QuotaDailyPoint?

    private static let dayFormatter: DateFormatter = QuotaHistoryView.dayFormatter

    private struct Bar: Identifiable {
        var id: String { "\(day.timeIntervalSince1970)-\(tool)" }
        var day: Date
        var tool: String
        var tokens: Int
    }

    private var bars: [Bar] {
        points.flatMap { point -> [Bar] in
            guard let day = Self.dayFormatter.date(from: point.d) else { return [] }
            return [
                Bar(day: day, tool: "Claude Code", tokens: point.c),
                Bar(day: day, tool: "Codex", tokens: point.x),
                Bar(day: day, tool: "Grok", tokens: point.g),
            ]
        }
    }

    var body: some View {
        Chart(bars) { bar in
            BarMark(
                x: .value("日期", bar.day, unit: .day),
                y: .value("Token", bar.tokens)
            )
            .foregroundStyle(by: .value("工具", bar.tool))
        }
        .chartForegroundStyleScale(
            domain: ["Claude Code", "Codex", "Grok"],
            range: [Theme.claude, Theme.codex, Theme.grok]
        )
        .chartLegend(position: .top, alignment: .trailing, spacing: 10)
        .chartXAxis {
            AxisMarks(values: .stride(by: .day, count: axisStrideDays)) { _ in
                AxisGridLine().foregroundStyle(Color.white.opacity(0.06))
                AxisValueLabel(format: .dateTime.month(.twoDigits).day(.twoDigits))
                    .font(.system(size: Theme.fontSize(8.5), design: .monospaced))
                    .foregroundStyle(Theme.tTertiary)
            }
        }
        .chartYAxis {
            AxisMarks(position: .leading) { value in
                AxisGridLine().foregroundStyle(Color.white.opacity(0.08))
                AxisValueLabel {
                    if let tokens = value.as(Int.self) {
                        Text(Fmt.human(tokens))
                    }
                }
                .font(.system(size: Theme.fontSize(8.5), design: .monospaced))
                .foregroundStyle(Theme.tTertiary)
            }
        }
        .frame(height: 235)
        .chartOverlay { proxy in
            GeometryReader { geometry in
                let plot = geometry[proxy.plotAreaFrame]
                Rectangle()
                    .fill(.clear)
                    .contentShape(Rectangle())
                    .onContinuousHover { phase in
                        switch phase {
                        case .active(let location):
                            guard plot.contains(location),
                                  let date: Date = proxy.value(atX: location.x - plot.minX)
                            else {
                                hover = nil
                                return
                            }
                            hover = nearestPoint(to: date)
                        case .ended:
                            hover = nil
                        }
                    }
                if let hover {
                    hoverBubble(hover, plot: plot)
                }
            }
        }
    }

    private var axisStrideDays: Int {
        max(points.count / 8, 1)
    }

    private func nearestPoint(to date: Date) -> QuotaDailyPoint? {
        let key = Self.dayFormatter.string(from: date)
        return points.first { $0.d == key }
    }

    private func hoverBubble(_ point: QuotaDailyPoint, plot: CGRect) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(point.d)
                .font(.system(size: Theme.fontSize(9.5), weight: .semibold, design: .monospaced))
                .foregroundStyle(Theme.tPrimary)
            hoverRow("Claude Code", point.c, Theme.claude)
            hoverRow("Codex", point.x, Theme.codex)
            hoverRow("Grok", point.g, Theme.grok)
            Text("合计 \(Fmt.grouped(point.total))")
                .font(.system(size: Theme.fontSize(8.5), design: .monospaced))
                .foregroundStyle(Theme.tTertiary)
        }
        .padding(.horizontal, 7)
        .padding(.vertical, 6)
        .frame(width: 150, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 7)
                .fill(Color(red: 0.10, green: 0.11, blue: 0.14).opacity(0.96))
                .shadow(color: Color.black.opacity(0.32), radius: 5, y: 2)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 7)
                .strokeBorder(Color.white.opacity(0.14), lineWidth: 0.75)
        )
        .offset(x: plot.minX + 6, y: plot.minY + 4)
        .allowsHitTesting(false)
    }

    private func hoverRow(_ title: String, _ tokens: Int, _ tint: Color) -> some View {
        HStack(spacing: 4) {
            Circle()
                .fill(tint)
                .frame(width: 5, height: 5)
            Text(title)
                .font(.system(size: Theme.fontSize(9)))
                .foregroundStyle(Theme.tSecondary)
            Spacer(minLength: 4)
            Text(Fmt.human(tokens))
                .font(.system(size: Theme.fontSize(9.5), weight: .semibold, design: .monospaced))
                .foregroundStyle(Theme.tPrimary)
        }
    }
}

/// Owns hover state so pointer movement redraws only the chart, not the parent
/// page and its complete history projection.
private struct QuotaHistoryChart: View {
    let projection: QuotaHistoryProjection
    let start: Date
    let end: Date
    let span: QuotaHistorySpan
    let colors: [String: Color]

    @State private var hover: (sample: QuotaHoverSample, x: CGFloat)?

    var body: some View {
        Chart {
            ForEach(projection.lineData) { item in
                LineMark(
                    x: .value("时间", item.timestamp),
                    y: .value("剩余额度", item.remaining),
                    series: .value("额度窗口", item.window)
                )
                .foregroundStyle(by: .value("额度窗口", item.window))
                .interpolationMethod(.stepEnd)
                .lineStyle(StrokeStyle(lineWidth: 2.2, lineCap: .round, lineJoin: .round))
            }
            ForEach(projection.markerData) { item in
                let isLatest = projection.latestDatumIDs.contains(item.id)
                PointMark(
                    x: .value("活动时间", item.timestamp),
                    y: .value("活动额度", item.remaining)
                )
                .foregroundStyle(by: .value("额度窗口", item.window))
                .symbolSize(isLatest ? 16 : 8)
                .opacity(isLatest ? 1 : 0.62)
            }
        }
        .chartXScale(domain: start ... end)
        .chartYScale(domain: 0 ... 100)
        .chartForegroundStyleScale(
            domain: projection.windowNames,
            range: projection.windowNames.map { colors[$0] ?? Theme.claude }
        )
        .chartLegend(position: .top, alignment: .trailing, spacing: 10)
        .chartXAxis {
            AxisMarks(values: .stride(by: .hour, count: span.axisStride)) { value in
                AxisGridLine().foregroundStyle(Color.white.opacity(0.06))
                AxisTick().foregroundStyle(Color.white.opacity(0.18))
                AxisValueLabel(
                    format: span.axisShowsDate
                        ? .dateTime.month(.twoDigits).day(.twoDigits)
                        : .dateTime.hour().minute()
                )
                    .font(.system(size: Theme.fontSize(8.5), design: .monospaced))
                    .foregroundStyle(Theme.tTertiary)
            }
        }
        .chartYAxis {
            AxisMarks(position: .leading, values: [0, 25, 50, 75, 100]) { value in
                AxisGridLine().foregroundStyle(Color.white.opacity(0.08))
                AxisValueLabel {
                    if let number = value.as(Int.self) {
                        Text("\(number)%")
                    }
                }
                .font(.system(size: Theme.fontSize(8.5), design: .monospaced))
                .foregroundStyle(Theme.tTertiary)
            }
        }
        .frame(height: 235)
        .chartOverlay { proxy in
            GeometryReader { geometry in
                let plot = geometry[proxy.plotAreaFrame]
                Rectangle()
                    .fill(.clear)
                    .contentShape(Rectangle())
                    .onContinuousHover { phase in
                        switch phase {
                        case .active(let location):
                            guard plot.contains(location),
                                  let date: Date = proxy.value(atX: location.x - plot.minX),
                                  let sample = projection.nearestHoverSample(to: date),
                                  let x = proxy.position(forX: sample.timestamp)
                            else {
                                hover = nil
                                return
                            }
                            hover = (sample: sample, x: x + plot.minX)
                        case .ended:
                            hover = nil
                        }
                    }
                if let hover {
                    hoverBubble(at: hover, plot: plot)
                }
            }
        }
    }

    @ViewBuilder
    private func hoverBubble(
        at hover: (sample: QuotaHoverSample, x: CGFloat),
        plot: CGRect
    ) -> some View {
        if !hover.sample.rows.isEmpty {
            let bubbleWidth: CGFloat = 154
            let rightmost = max(plot.minX, plot.maxX - bubbleWidth)
            let anchor = min(
                max(hover.x - bubbleWidth / 2, plot.minX),
                rightmost
            )
            ZStack(alignment: .topLeading) {
                Rectangle()
                    .fill(Color.white.opacity(0.32))
                    .frame(width: 1, height: plot.height)
                    .position(x: hover.x, y: plot.midY)
                VStack(alignment: .leading, spacing: 3) {
                    Text(Self.timeFormatter.string(from: hover.sample.timestamp))
                        .font(.system(size: Theme.fontSize(9.5), weight: .semibold, design: .monospaced))
                        .foregroundStyle(Theme.tPrimary)
                    ForEach(hover.sample.rows) { row in
                        HStack(spacing: 4) {
                            Circle()
                                .fill(colors[row.window] ?? Theme.claude)
                                .frame(width: 5, height: 5)
                            Text(row.window)
                                .font(.system(size: Theme.fontSize(9)))
                                .foregroundStyle(Theme.tSecondary)
                                .lineLimit(1)
                            Spacer(minLength: 4)
                            Text(String(format: "%.1f%%", row.remaining))
                                .font(.system(size: Theme.fontSize(9.5), weight: .semibold, design: .monospaced))
                                .foregroundStyle(Theme.tPrimary)
                        }
                    }
                    if !hover.sample.activity.isEmpty {
                        Text(
                            hover.sample.activity
                                .map { "\($0.model) +\(Fmt.human($0.tokenDelta))" }
                                .joined(separator: " · ")
                        )
                        .font(.system(size: Theme.fontSize(8.5), design: .monospaced))
                        .foregroundStyle(Theme.tTertiary)
                        .lineLimit(1)
                    }
                }
                .padding(.horizontal, 7)
                .padding(.vertical, 6)
                .frame(width: bubbleWidth, alignment: .leading)
                .background(
                    RoundedRectangle(cornerRadius: 7)
                        .fill(Color(red: 0.10, green: 0.11, blue: 0.14).opacity(0.96))
                        .shadow(color: Color.black.opacity(0.32), radius: 5, y: 2)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 7)
                        .strokeBorder(Color.white.opacity(0.14), lineWidth: 0.75)
                )
                .offset(x: anchor, y: plot.minY + 4)
                .allowsHitTesting(false)
            }
        }
    }

    private static let timeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter
    }()
}
