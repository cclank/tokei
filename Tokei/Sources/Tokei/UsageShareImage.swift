import SwiftUI
import AppKit

/// Renders a shareable usage card image (generated to match native panel styling).
enum UsageShareImage {
    static let multiWidth: CGFloat = 380
    static let singleWidth: CGFloat = 340
    static let renderScale: CGFloat = 2

    // MARK: - Multi-tool (footer Copy)

    @MainActor
    static func render(
        usage: Usage,
        range: RangeKey,
        visibility: UsageToolVisibility,
        updated: String? = nil
    ) -> NSImage? {
        let lines = UsageSummaryBuilder.toolLines(
            usage: usage, range: range, visibility: visibility
        )
        return renderView(
            UsageShareOverviewView(
                range: range,
                lines: lines,
                totals: UsageSummaryBuilder.totals(for: lines),
                updatedLine: UsageSummaryBuilder.formatUpdatedLine(updated)
            )
        )
    }

    @MainActor
    static func pngData(
        usage: Usage,
        range: RangeKey,
        visibility: UsageToolVisibility,
        updated: String? = nil
    ) -> Data? {
        png(from: render(usage: usage, range: range, visibility: visibility, updated: updated))
    }

    @MainActor
    @discardableResult
    static func copyToPasteboard(
        usage: Usage,
        range: RangeKey,
        visibility: UsageToolVisibility,
        updated: String? = nil
    ) -> Bool {
        writeToPasteboard(
            render(usage: usage, range: range, visibility: visibility, updated: updated)
        )
    }

    // MARK: - Single tool (per-card Copy)

    @MainActor
    static func render(
        line: UsageSummaryBuilder.Line,
        range: RangeKey,
        updated: String? = nil
    ) -> NSImage? {
        renderView(
            UsageShareToolView(
                range: range,
                line: line,
                updatedLine: UsageSummaryBuilder.formatUpdatedLine(updated)
            )
        )
    }

    @MainActor
    static func pngData(
        line: UsageSummaryBuilder.Line,
        range: RangeKey,
        updated: String? = nil
    ) -> Data? {
        png(from: render(line: line, range: range, updated: updated))
    }

    @MainActor
    @discardableResult
    static func copyToPasteboard(
        line: UsageSummaryBuilder.Line,
        range: RangeKey,
        updated: String? = nil
    ) -> Bool {
        writeToPasteboard(render(line: line, range: range, updated: updated))
    }

    // MARK: - Helpers

    @MainActor
    private static func renderView<V: View>(_ content: V) -> NSImage? {
        let renderer = ImageRenderer(content: content.environment(\.colorScheme, .dark))
        renderer.scale = renderScale
        guard let cg = renderer.cgImage else { return nil }
        let size = NSSize(width: CGFloat(cg.width) / renderScale,
                          height: CGFloat(cg.height) / renderScale)
        return NSImage(cgImage: cg, size: size)
    }

    private static func png(from image: NSImage?) -> Data? {
        guard let image,
              let tiff = image.tiffRepresentation,
              let rep = NSBitmapImageRep(data: tiff) else { return nil }
        return rep.representation(using: .png, properties: [:])
    }

    @MainActor
    private static func writeToPasteboard(_ image: NSImage?) -> Bool {
        guard let image else { return false }
        let pb = NSPasteboard.general
        pb.clearContents()
        var ok = pb.writeObjects([image])
        if let data = png(from: image) {
            ok = pb.setData(data, forType: .png) || ok
        }
        return ok
    }

    static func tint(for name: String) -> Color {
        switch name {
        case "Claude Code": return Theme.claude
        case "Codex", "Luna Reserve": return Theme.codex
        case "Gemini": return Theme.gemini
        case "Grok": return Theme.grok
        case "Grok Bot": return Theme.grokBot
        case "Qoder Desktop": return Theme.qoder
        case "QoderWork": return Theme.qoderwork
        case "Qoder CLI": return Theme.qodercli
        case "Qoder CN": return Theme.qodercliCn
        case "Hermes": return Theme.hermes
        case "ZCode": return Theme.zcode
        case "MiMoCode": return Theme.mimocode
        case "OpenClaw": return Theme.openclaw
        case "Pi": return Theme.pi
        case "WorkBuddy": return Theme.workbuddy
        case "WorkBuddy Intl.": return Theme.workbuddyAI
        case "CodeBuddy": return Theme.codebuddy
        case "OpenCode": return Theme.opencode
        case "Qwen Code": return Theme.qwencode
        case "Kimi Code": return Theme.kimicode
        case "Muse Code": return Theme.musecode
        case "Command Code": return Theme.cmdcode
        case "Prime Agent": return Theme.primeAgent
        case "DeepSeek Harness": return Theme.deepseekHarness
        default: return Theme.tTertiary
        }
    }
}

// MARK: - Overview (all tools)

struct UsageShareOverviewView: View {
    var range: RangeKey
    var lines: [UsageSummaryBuilder.Line]
    var totals: UsageSummaryBuilder.Totals
    var updatedLine: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 13) {
            shareHeader(title: "Tokei 用量", subtitle: range.label, tint: Theme.claude)

            if lines.isEmpty {
                Text("当前范围无可分享的用量")
                    .font(.system(size: 12))
                    .foregroundStyle(Theme.tTertiary)
                    .padding(.vertical, 18)
            } else {
                VStack(spacing: 10) {
                    ForEach(lines) { line in
                        nativeToolCard(line, rangeLabel: range.label, compact: true)
                    }
                }

                detailedTotals
            }

            footerBrand(updatedLine)
        }
        .padding(16)
        .frame(width: UsageShareImage.multiWidth, alignment: .topLeading)
        .background(shareBackground)
    }

    private var detailedTotals: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("合计明细")
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(Theme.tSecondary)

            if totals.tokens > 0 {
                CostHeadline(
                    value: Fmt.human(totals.tokens),
                    caption: "\(range.label) 总量",
                    tint: Theme.claude
                )
            }

            LazyVGrid(
                columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)],
                alignment: .leading,
                spacing: 9
            ) {
                if totals.cost > 0 || totals.cost_cny > 0 {
                    MetricCell(icon: "dollarsign.circle", label: "≈成本",
                               value: nativeMoney(totals.cost, totals.cost_cny), tint: Theme.claude)
                }
                MetricCell(icon: "square.grid.2x2", label: "工具",
                           value: "\(totals.tools)", tint: Theme.codex)
                if totals.sessions > 0 {
                    MetricCell(icon: "bubble.left.and.bubble.right", label: "会话",
                               value: "\(totals.sessions)", tint: Theme.gemini)
                }
                if totals.calls > 0 {
                    MetricCell(icon: "waveform", label: "调用",
                               value: "\(totals.calls)", tint: Theme.grok)
                }
                if totals.input > 0 {
                    MetricCell(icon: "arrow.down", label: "输入",
                               value: Fmt.human(totals.input), tint: Theme.claude)
                }
                if totals.output > 0 {
                    MetricCell(icon: "arrow.up", label: "输出",
                               value: Fmt.human(totals.output), tint: Theme.codex)
                }
                if totals.cacheRead > 0 {
                    MetricCell(icon: "bolt.fill", label: "缓存读",
                               value: Fmt.human(totals.cacheRead), tint: Theme.hermes)
                }
                if totals.cacheWrite > 0 {
                    MetricCell(icon: "square.stack.3d.up.fill", label: "缓存写",
                               value: Fmt.human(totals.cacheWrite), tint: Theme.pi)
                }
                if totals.reason > 0 {
                    MetricCell(icon: "brain", label: "推理",
                               value: Fmt.human(totals.reason), tint: Theme.gemini)
                }
            }
        }
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                .fill(Color.black.opacity(0.30))
                .overlay(
                    RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                        .strokeBorder(Color.white.opacity(0.08), lineWidth: 1)
                )
        )
    }
}

// MARK: - Single tool

struct UsageShareToolView: View {
    var range: RangeKey
    var line: UsageSummaryBuilder.Line
    var updatedLine: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            shareHeader(title: line.name, subtitle: "Tokei · \(range.label)",
                        tint: UsageShareImage.tint(for: line.name), sessions: line.sessions)
            nativeToolCard(line, rangeLabel: range.label, compact: false)
            footerBrand(updatedLine)
        }
        .padding(16)
        .frame(width: UsageShareImage.singleWidth, alignment: .topLeading)
        .background(shareBackground)
    }
}

// MARK: - Shared pieces (native panel look)

private var shareBackground: some View {
    RoundedRectangle(cornerRadius: 18, style: .continuous)
        .fill(
            LinearGradient(
                colors: [
                    Color(red: 0.20, green: 0.21, blue: 0.25),
                    Color(red: 0.12, green: 0.13, blue: 0.16),
                ],
                startPoint: .top,
                endPoint: .bottom
            )
        )
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .strokeBorder(Color.white.opacity(0.10), lineWidth: 1)
        )
}

private func shareHeader(
    title: String, subtitle: String, tint: Color, sessions: Int? = nil
) -> some View {
    HStack(spacing: 9) {
        Image(systemName: "timer")
            .font(.system(size: 15, weight: .bold))
            .foregroundStyle(tint)
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 6) {
                Text(title)
                    .font(.system(size: 15, weight: .bold, design: .rounded))
                    .foregroundStyle(Theme.tPrimary)
                if let sessions, sessions > 0 {
                    Text("\(sessions)")
                        .font(.system(size: 10, weight: .bold, design: .rounded))
                        .foregroundStyle(tint)
                        .padding(.horizontal, 5).padding(.vertical, 1.5)
                        .background(Capsule().fill(tint.opacity(0.14)))
                }
            }
            Text(subtitle)
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(Theme.tTertiary)
        }
        Spacer(minLength: 0)
    }
}

private func nativeToolCard(
    _ line: UsageSummaryBuilder.Line,
    rangeLabel: String,
    compact: Bool
) -> some View {
    let tint = UsageShareImage.tint(for: line.name)
    return VStack(alignment: .leading, spacing: 10) {
        HStack(spacing: 7) {
            Circle().fill(tint.gradient).frame(width: 8, height: 8)
                .shadow(color: tint.opacity(0.55), radius: 3)
            Text(line.name)
                .font(.system(size: compact ? 13 : 14, weight: .bold))
                .foregroundStyle(Theme.tPrimary)
            if let sessions = line.sessions, sessions > 0 {
                Text("\(sessions)")
                    .font(.system(size: 10, weight: .bold, design: .rounded))
                    .foregroundStyle(tint)
                    .padding(.horizontal, 5).padding(.vertical, 1.5)
                    .background(Capsule().fill(tint.opacity(0.14)))
            }
            Spacer(minLength: 0)
        }

        if let tokens = line.tokens, tokens > 0 {
            CostHeadline(value: Fmt.human(tokens), caption: "\(rangeLabel) 总量", tint: tint)
        }

        LazyVGrid(
            columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)],
            alignment: .leading,
            spacing: 8
        ) {
            if let cost = line.cost, cost > 0 || (line.cost_cny ?? 0) > 0 {
                MetricCell(icon: "dollarsign.circle", label: "≈成本",
                           value: nativeMoney(cost, line.cost_cny), tint: tint)
            }
            if let hit = line.hit, hit > 0 {
                RingMetricCell(value: hit, label: "Cache Hit", tint: tint)
            }
            if let input = line.input, input > 0 {
                MetricCell(icon: "arrow.down", label: "输入", value: Fmt.human(input), tint: tint)
            }
            if let output = line.output, output > 0 {
                MetricCell(icon: "arrow.up", label: "输出", value: Fmt.human(output), tint: tint)
            }
            if let cr = line.cacheRead, cr > 0 {
                MetricCell(icon: "bolt.fill", label: "缓存读", value: Fmt.human(cr), tint: tint)
            }
            if let cw = line.cacheWrite, cw > 0 {
                MetricCell(icon: "square.stack.3d.up.fill", label: "缓存写",
                           value: Fmt.human(cw), tint: tint)
            }
            if let reason = line.reason, reason > 0 {
                MetricCell(icon: "brain", label: "推理", value: Fmt.human(reason), tint: tint)
            }
            if let calls = line.calls, calls > 0 {
                MetricCell(icon: "waveform", label: "调用", value: "\(calls)", tint: tint)
            }
        }
    }
    .padding(12)
    .background(
        RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
            .fill(Color.black.opacity(0.28))
            .overlay(
                RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                    .strokeBorder(
                        LinearGradient(
                            colors: [tint.opacity(0.35), Color.white.opacity(0.06)],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        ),
                        lineWidth: 1
                    )
            )
    )
}

private func footerBrand(_ updatedLine: String?) -> some View {
    VStack(alignment: .leading, spacing: 4) {
        if let updatedLine {
            Text(updatedLine)
                .font(.system(size: 10, design: .monospaced))
                .foregroundStyle(Theme.tTertiary)
        }
        Text("Tokei · 知度")
            .font(.system(size: 9, weight: .medium))
            .foregroundStyle(Theme.tTertiary.opacity(0.85))
    }
}
