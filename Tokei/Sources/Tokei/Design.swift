import SwiftUI

struct VisualEffect: NSViewRepresentable {
    func makeNSView(context: Context) -> NSVisualEffectView {
        let v = NSVisualEffectView()
        v.material = .hudWindow
        v.blendingMode = .behindWindow
        v.state = .active
        return v
    }
    func updateNSView(_ v: NSVisualEffectView, context: Context) {}
}

private class PassthroughView: NSView {
    override func hitTest(_ point: NSPoint) -> NSView? { nil }
}

struct Tip: NSViewRepresentable {
    let text: String
    func makeNSView(context: Context) -> NSView {
        let v = PassthroughView(); v.toolTip = text; return v
    }
    func updateNSView(_ v: NSView, context: Context) { v.toolTip = text }
}

extension View {
    func tip(_ text: String) -> some View { overlay(Tip(text: text)) }
}

// 设计系统:颜色 / 间距 / 圆角集中定义,组件语义化复用。
enum Theme {
    static let claude = Color(red: 0.92, green: 0.52, blue: 0.40)   // 柔珊瑚
    static let codex  = Color(red: 0.42, green: 0.68, blue: 0.98)   // 天青
    static let gemini = Color(red: 0.62, green: 0.52, blue: 0.92)   // 薰衣草
    static let grok   = Color(red: 0.65, green: 0.68, blue: 0.75)   // 冷灰银
    static let qoder  = Color(red: 0.90, green: 0.75, blue: 0.35)   // 琥珀金
    static let qoderwork = Color(red: 0.75, green: 0.65, blue: 0.30)  // 暗琥珀
    static let qodercli = Color(red: 0.96, green: 0.84, blue: 0.45)  // 亮琥珀
    static let hermes = Color(red: 0.40, green: 0.82, blue: 0.60)   // 翠绿
    static let zcode = Color(red: 0.52, green: 0.80, blue: 0.34)    // 青柠绿
    static let mimocode = Color(red: 0.95, green: 0.50, blue: 0.26) // 暖橙
    static let openclaw = Color(red: 0.85, green: 0.45, blue: 0.68) // 玫红
    static let pi = Color(red: 0.74, green: 0.58, blue: 0.95)       // 柔紫
    static let workbuddy = Color(red: 0.25, green: 0.78, blue: 0.72) // 青绿
    static let opencode = Color(red: 0.55, green: 0.75, blue: 0.90) // 天蓝灰
    static let qwencode = Color(red: 0.48, green: 0.55, blue: 0.95) // 靛蓝

    static let panelWidth: CGFloat = 322
    static let cardRadius: CGFloat = 16
    static let outerPad: CGFloat = 15

    static var brand: LinearGradient {
        LinearGradient(colors: [claude.opacity(0.8), claude],
                       startPoint: .leading, endPoint: .trailing)
    }

    static var bg: LinearGradient {
        LinearGradient(colors: [Color(red: 0.20, green: 0.21, blue: 0.25).opacity(0.92),
                                Color(red: 0.12, green: 0.13, blue: 0.16).opacity(0.95)],
                       startPoint: .top, endPoint: .bottom)
    }

    static let tPrimary   = Color.white.opacity(0.97)
    static let tSecondary = Color.white.opacity(0.82)
    static let tTertiary  = Color.white.opacity(0.58)
}

// 毛玻璃之上的浮起卡片:淡色填充 + 渐变描边 + 柔和投影。
struct Card<Content: View>: View {
    var tint: Color
    @ViewBuilder var content: () -> Content
    @State private var hover = false
    var body: some View {
        content()
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .padding(13)
            .background(
                RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                    .fill(Color.black.opacity(0.26))
                    .overlay(
                        RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                            .fill(tint.opacity(0.08))
                    )
                    .overlay(alignment: .top) {
                        RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                            .fill(LinearGradient(
                                colors: [Color.white.opacity(0.05), .clear],
                                startPoint: .top, endPoint: .center))
                    }
            )
            .overlay(
                RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                    .strokeBorder(
                        LinearGradient(colors: [tint.opacity(0.38), tint.opacity(0.05)],
                                       startPoint: .topLeading, endPoint: .bottomTrailing),
                        lineWidth: 0.75)
            )
            .shadow(color: Color.black.opacity(hover ? 0.42 : 0.30),
                    radius: hover ? 16 : 12, x: 0, y: hover ? 9 : 6)
            .scaleEffect(hover ? 1.012 : 1)
            .onHover { hover = $0 }
            .animation(.easeOut(duration: 0.18), value: hover)
    }
}

struct EqualHeightGrid: Layout {
    var columns = 2
    var hSpacing: CGFloat = 13
    var vSpacing: CGFloat = 13

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        guard !subviews.isEmpty else { return .zero }
        let colW = colWidth(in: proposal.width ?? 600)
        var h: CGFloat = 0
        for row in stride(from: 0, to: subviews.count, by: columns) {
            if row > 0 { h += vSpacing }
            h += rowHeight(row: row, colW: colW, subviews: subviews)
        }
        return CGSize(width: proposal.width ?? 600, height: h)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let colW = colWidth(in: bounds.width)
        var y = bounds.minY
        for row in stride(from: 0, to: subviews.count, by: columns) {
            let rh = rowHeight(row: row, colW: colW, subviews: subviews)
            for i in row..<min(row + columns, subviews.count) {
                let x = bounds.minX + CGFloat(i - row) * (colW + hSpacing)
                subviews[i].place(at: CGPoint(x: x, y: y), anchor: .topLeading,
                                  proposal: .init(width: colW, height: rh))
            }
            y += rh + vSpacing
        }
    }

    private func colWidth(in total: CGFloat) -> CGFloat {
        (total - hSpacing * CGFloat(columns - 1)) / CGFloat(columns)
    }
    private func rowHeight(row: Int, colW: CGFloat, subviews: Subviews) -> CGFloat {
        (row..<min(row + columns, subviews.count)).map {
            subviews[$0].sizeThatFits(.init(width: colW, height: nil)).height
        }.max() ?? 0
    }
}

// 命中率环形仪表 —— 卡片视觉焦点之一。
struct RingGauge: View {
    var value: Double            // 0...100
    var tint: Color
    var size: CGFloat = 40
    var body: some View {
        ZStack {
            Circle().stroke(Color.primary.opacity(0.10), lineWidth: 4.5)
            Circle()
                .trim(from: 0, to: max(0.001, min(1, value / 100)))
                .stroke(tint.gradient, style: StrokeStyle(lineWidth: 4.5, lineCap: .round))
                .rotationEffect(.degrees(-90))
                .shadow(color: tint.opacity(0.35), radius: 4)
            VStack(spacing: -1) {
                Text("\(Int(value.rounded()))")
                    .font(.system(size: size * 0.30, weight: .bold, design: .rounded))
                    .foregroundStyle(.primary)
                Text("%")
                    .font(.system(size: size * 0.16, weight: .semibold))
                    .foregroundStyle(.secondary)
            }
        }
        .frame(width: size, height: size)
        .animation(.easeOut(duration: 0.18), value: value)
    }
}

// 细进度条(配额用)。
struct MiniBar: View {
    var value: Double            // 0...100
    var tint: Color
    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.primary.opacity(0.09))
                Capsule()
                    .fill(tint.gradient)
                    .frame(width: max(3, geo.size.width * min(1, value / 100)))
            }
        }
        .frame(height: 5)
        .animation(.easeOut(duration: 0.18), value: value)
    }
}

// 排行条:细 Capsule + 中性轨道,对数刻度。模型/项目共用。
struct StatBar: View {
    var name: String
    var tokens: Int
    var cost: Double
    var maxTokens: Double
    var tint: Color
    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 6) {
                Text(name).font(.system(size: 11, weight: .medium))
                    .foregroundStyle(Theme.tPrimary).lineLimit(1)
                Spacer(minLength: 8)
                Text(Fmt.human(tokens)).font(.system(size: 9.5, design: .monospaced))
                    .foregroundStyle(Theme.tTertiary)
                Text("$\(Int(cost))").font(.system(size: 10, weight: .semibold, design: .monospaced))
                    .foregroundStyle(Theme.tSecondary)
            }
            GeometryReader { geo in
                let ratio = maxTokens > 0 ? (Double(tokens) / maxTokens).squareRoot() : 0
                Capsule().fill(LinearGradient(colors: [tint.opacity(0.5), tint],
                                              startPoint: .leading, endPoint: .trailing))
                    .frame(width: max(5, geo.size.width * CGFloat(ratio)), height: 5)
            }
            .frame(height: 5)
        }
    }
}

// 指标格子:图标 + 标签 + 等宽数值。
struct MetricCell: View {
    var icon: String
    var label: String
    var value: String
    var tint: Color
    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon)
                .font(.system(size: 9.5, weight: .bold))
                .foregroundStyle(tint)
                .frame(width: 21, height: 21)
                .background(Circle().fill(tint.opacity(0.10)))
            VStack(alignment: .leading, spacing: 1) {
                Text(label)
                    .font(.system(size: 9.5))
                    .foregroundStyle(Theme.tTertiary)
                Text(value)
                    .font(.system(size: 12.5, weight: .semibold, design: .monospaced))
                    .foregroundStyle(Theme.tPrimary)
            }
            Spacer(minLength: 0)
        }
    }
}

struct RingMetricCell: View {
    var value: Double
    var label: String
    var tint: Color
    var body: some View {
        HStack(spacing: 8) {
            ZStack {
                Circle().stroke(Color.primary.opacity(0.10), lineWidth: 2.5)
                Circle()
                    .trim(from: 0, to: max(0.001, min(1, value / 100)))
                    .stroke(tint.gradient, style: StrokeStyle(lineWidth: 2.5, lineCap: .round))
                    .rotationEffect(.degrees(-90))
            }
            .frame(width: 21, height: 21)
            VStack(alignment: .leading, spacing: 1) {
                Text(label)
                    .font(.system(size: 9.5))
                    .foregroundStyle(Theme.tTertiary)
                Text("\(Int(value.rounded()))%")
                    .font(.system(size: 12.5, weight: .semibold, design: .monospaced))
                    .foregroundStyle(Theme.tPrimary)
            }
            Spacer(minLength: 0)
        }
        .animation(.easeOut(duration: 0.5), value: value)
    }
}

// 大号成本焦点行。
struct CostHeadline: View {
    var value: String
    var caption: String
    var tint: Color
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 7) {
            Text(value)
                .font(.system(size: 23, weight: .bold, design: .rounded))
                .foregroundStyle(.white)
                .contentTransition(.numericText())
            Text(caption)
                .font(.system(size: 10))
                .foregroundStyle(Theme.tTertiary)
            Spacer(minLength: 0)
        }
    }
}

// 自定义滑动分段控件(替代原生 segmented),选中态滑动高亮。
struct SegmentedTabs: View {
    @Binding var sel: RangeKey
    @State private var highlighted: RangeKey
    @Namespace private var ns

    init(sel: Binding<RangeKey>) {
        _sel = sel
        _highlighted = State(initialValue: sel.wrappedValue)
    }

    var body: some View {
        HStack(spacing: 2) {
            ForEach(RangeKey.displayCases) { k in
                let on = k == highlighted
                Text(k.label)
                    .font(.system(size: 12, weight: on ? .semibold : .regular))
                    .foregroundStyle(on ? AnyShapeStyle(.primary) : AnyShapeStyle(.secondary))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 5)
                    .background {
                        if on {
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .fill(.ultraThinMaterial)
                                .overlay(
                                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                                        .strokeBorder(Color.primary.opacity(0.14), lineWidth: 1))
                                .shadow(color: .black.opacity(0.18), radius: 3, y: 1)
                                .matchedGeometryEffect(id: "seg", in: ns)
                        }
                    }
                    .contentShape(Rectangle())
                    .onTapGesture {
                        guard sel != k else { return }
                        sel = k
                        withAnimation(.easeOut(duration: 0.18)) { highlighted = k }
                    }
            }
        }
        .padding(3)
        .background(
            RoundedRectangle(cornerRadius: 11, style: .continuous)
                .fill(Color.primary.opacity(0.06))
        )
        .onChange(of: sel) { value in
            guard highlighted != value else { return }
            highlighted = value
        }
    }
}

// 底部图标按钮,带 hover 高亮。
struct IconButton: View {
    var icon: String
    var label: String
    var action: () -> Void
    @State private var hover = false
    var body: some View {
        Button(action: action) {
            HStack(spacing: 4) {
                Image(systemName: icon).font(.system(size: 10, weight: .semibold))
                Text(label).font(.system(size: 11, weight: .medium))
            }
            .foregroundStyle(hover ? AnyShapeStyle(.primary) : AnyShapeStyle(.secondary))
            .padding(.horizontal, 9)
            .padding(.vertical, 4)
            .background(
                RoundedRectangle(cornerRadius: 7, style: .continuous)
                    .fill(Color.primary.opacity(hover ? 0.10 : 0))
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
    }
}
