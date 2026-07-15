import SwiftUI
import AppKit

struct TrailProject: Codable, Identifiable {
    var path: String
    var name: String
    var last_active: String
    var sessions: Int
    var tokens: Int
    var cost: Double
    var top_model: String
    var tools: [String]
    var ports: [Int]?
    var id: String { path }
}

struct ProjectTrailView: View {
    @Binding var cached: [TrailProject]?
    @State private var loading = false
    @State private var query = ""
    @AppStorage("pinnedProjects") private var pinnedRaw = ""

    private var projects: [TrailProject] { cached ?? [] }

    private var pinned: Set<String> {
        Set(pinnedRaw.split(separator: "\n").map(String.init))
    }

    private func togglePin(_ path: String) {
        var s = pinned
        if s.contains(path) { s.remove(path) } else { s.insert(path) }
        pinnedRaw = s.sorted().joined(separator: "\n")
    }

    private var filtered: [TrailProject] {
        let q = query.lowercased()
        let list = q.isEmpty ? projects : projects.filter {
            $0.name.lowercased().contains(q) || $0.path.lowercased().contains(q)
        }
        return list.sorted { a, b in
            let ap = pinned.contains(a.path), bp = pinned.contains(b.path)
            if ap != bp { return ap }
            return a.last_active > b.last_active
        }
    }

    private enum Group: String, CaseIterable { case pinned, today, week, earlier, dormant }

    private func group(for p: TrailProject) -> Group {
        if pinned.contains(p.path) { return .pinned }
        let cal = Calendar.current
        let today = cal.startOfDay(for: Date())
        guard let d = Self.parseDate(p.last_active) else { return .dormant }
        let days = cal.dateComponents([.day], from: cal.startOfDay(for: d), to: today).day ?? 999
        if days == 0 { return .today }
        if days <= 7 { return .week }
        if days > 14 { return .dormant }
        return .earlier
    }

    private func groupLabel(_ g: Group) -> String {
        switch g {
        case .pinned: return "置顶"
        case .today: return "今天"
        case .week: return "本周"
        case .earlier: return "更早"
        case .dormant: return "沉睡"
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 7) {
                searchBar
                Button { loadData() } label: {
                    Image(systemName: "arrow.clockwise")
                        .font(.system(size: 10, weight: .medium))
                        .foregroundStyle(Theme.tTertiary)
                        .frame(width: 24, height: 24)
                        .background(Circle().fill(Color.primary.opacity(0.06)))
                        .contentShape(Circle())
                }
                .buttonStyle(.plain)
                .tip("刷新")
            }
            if loading || cached == nil {
                HStack { Spacer(); ProgressView().controlSize(.small); Spacer() }
                    .frame(height: 120)
            } else if filtered.isEmpty {
                HStack { Spacer(); Text("无匹配项目").font(.system(size: 11)).foregroundStyle(Theme.tTertiary); Spacer() }
                    .frame(height: 80)
            } else {
                let grouped = Dictionary(grouping: filtered, by: { group(for: $0) })
                ForEach(Group.allCases, id: \.self) { g in
                    if let items = grouped[g], !items.isEmpty {
                        sectionHeader(groupLabel(g), dormant: g == .dormant)
                        ForEach(items) { p in
                            projectRow(p)
                        }
                    }
                }
                footer
            }
        }
        .onAppear { if cached == nil { loadData() } }
    }

    var searchBar: some View {
        HStack(spacing: 7) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(Theme.tTertiary)
            TextField("搜索项目…", text: $query)
                .font(.system(size: 11))
                .textFieldStyle(.plain)
                .foregroundStyle(Theme.tPrimary)
            if !query.isEmpty {
                Button { query = "" } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.system(size: 10)).foregroundStyle(Theme.tTertiary)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.horizontal, 10).padding(.vertical, 6)
        .background(RoundedRectangle(cornerRadius: 8, style: .continuous)
            .fill(Color.primary.opacity(0.06)))
    }

    func sectionHeader(_ title: String, dormant: Bool = false) -> some View {
        HStack(spacing: 5) {
            if dormant {
                Text("💤").font(.system(size: 10))
            }
            Text(title)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(dormant ? Theme.tTertiary : Theme.tSecondary)
        }
        .padding(.top, 4)
    }

    func projectRow(_ p: TrailProject) -> some View {
        HStack(spacing: 9) {
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 5) {
                    Image(systemName: "folder.fill")
                        .font(.system(size: 10, weight: .medium))
                        .foregroundStyle(Theme.claude.opacity(0.8))
                    Text(p.name)
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(Theme.tPrimary)
                        .lineLimit(1)
                    ForEach(p.tools, id: \.self) { t in
                        Circle().fill(toolColor(t)).frame(width: 5, height: 5)
                    }
                }
                Text(abbreviatePath(p.path))
                    .font(.system(size: 9, design: .monospaced))
                    .foregroundStyle(Theme.tTertiary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                HStack(spacing: 6) {
                    Text(Fmt.relativeDate(p.last_active))
                        .font(.system(size: 9)).foregroundStyle(Theme.tTertiary)
                    Text("·").foregroundStyle(Theme.tTertiary).font(.system(size: 9))
                    Text("\(p.sessions) sessions")
                        .font(.system(size: 9)).foregroundStyle(Theme.tTertiary)
                    Text("·").foregroundStyle(Theme.tTertiary).font(.system(size: 9))
                    Text("$\(Int(p.cost))")
                        .font(.system(size: 9, weight: .medium)).foregroundStyle(Theme.tSecondary)
                    if !p.top_model.isEmpty {
                        Text(p.top_model)
                            .font(.system(size: 8, design: .monospaced))
                            .foregroundStyle(Theme.tTertiary)
                            .lineLimit(1)
                    }
                }
                if let ports = p.ports, !ports.isEmpty {
                    ScrollView(.horizontal, showsIndicators: ports.count > 4) {
                        HStack(spacing: 5) {
                            ForEach(ports, id: \.self) { port in
                                Button {
                                    if let url = URL(string: "http://localhost:\(port)") {
                                        NSWorkspace.shared.open(url)
                                    }
                                } label: {
                                    HStack(spacing: 3) {
                                        Circle().fill(.green).frame(width: 5, height: 5)
                                        Text("localhost:\(port)")
                                            .font(.system(size: 9, weight: .medium, design: .monospaced))
                                            .foregroundStyle(Theme.hermes)
                                            .lineLimit(1)
                                    }
                                    .fixedSize(horizontal: true, vertical: false)
                                    .padding(.horizontal, 6).padding(.vertical, 2)
                                    .background(Capsule().fill(Theme.hermes.opacity(0.12)))
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }
                    .frame(height: 22)
                }
            }
            Spacer(minLength: 4)
            Button { togglePin(p.path) } label: {
                Image(systemName: pinned.contains(p.path) ? "star.fill" : "star")
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(pinned.contains(p.path) ? Theme.qoder : Theme.tTertiary)
            }
            .buttonStyle(.plain)
            .tip(pinned.contains(p.path) ? "取消置顶" : "置顶")
        }
        .padding(.horizontal, 10).padding(.vertical, 8)
        .background(RoundedRectangle(cornerRadius: 10, style: .continuous)
            .fill(Color.primary.opacity(0.04)))
        .contentShape(Rectangle())
        .onTapGesture { openInTerminal(p.path) }
        .contextMenu {
            Button("在终端打开") { openInTerminal(p.path) }
            Button("在 Ghostty 打开") { openInGhostty(p.path) }
            Button("在 iTerm 打开") { openInITerm(p.path) }
            Divider()
            Button("在 Finder 中显示") { NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: p.path) }
            Button("用 VS Code 打开") { openInVSCode(p.path) }
            Divider()
            Button("复制路径") {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(p.path, forType: .string)
            }
        }
    }

    var footer: some View {
        let earliest = projects.compactMap({ Self.parseDate($0.last_active) }).min()
        let fmt = DateFormatter()
        fmt.dateFormat = "yyyy-MM-dd"
        let earliestStr = earliest.map { fmt.string(from: $0) } ?? "?"
        return Text("共 \(projects.count) 个项目 · 最远 \(earliestStr)")
            .font(.system(size: 9)).foregroundStyle(Theme.tTertiary)
            .frame(maxWidth: .infinity)
            .padding(.top, 4)
    }

    // MARK: - Helpers

    func toolColor(_ t: String) -> Color {
        switch t {
        case "claude": return Theme.claude
        case "codex": return Theme.codex
        case "grok": return Theme.grok
        case "hermes": return Theme.hermes
        case "zcode": return Theme.zcode
        case "mimocode": return Theme.mimocode
        case "pi": return Theme.pi
        case "workbuddy": return Theme.workbuddy
        default: return Theme.tTertiary
        }
    }

    func abbreviatePath(_ path: String) -> String {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        if path.hasPrefix(home) { return "~" + path.dropFirst(home.count) }
        return path
    }

    func openInTerminal(_ path: String) {
        let script = "tell application \"Terminal\" to do script \"cd \(path.replacingOccurrences(of: "\"", with: "\\\""))\""
        if let s = NSAppleScript(source: script) { s.executeAndReturnError(nil) }
        NSWorkspace.shared.open(URL(fileURLWithPath: "/System/Applications/Utilities/Terminal.app"))
    }

    func openInGhostty(_ path: String) {
        let escaped = path.replacingOccurrences(of: "'", with: "'\\''")
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        proc.arguments = ["ghostty", "-e", "/bin/zsh", "-c", "cd '\(escaped)' && exec zsh"]
        try? proc.run()
    }

    func openInITerm(_ path: String) {
        let escaped = path.replacingOccurrences(of: "\"", with: "\\\"")
        let script = """
        tell application "iTerm"
            create window with default profile command "/bin/zsh -c \\"cd \\\"\(escaped)\\\"; exec zsh\\""
            activate
        end tell
        """
        if let s = NSAppleScript(source: script) { s.executeAndReturnError(nil) }
    }

    func openInVSCode(_ path: String) {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        proc.arguments = ["code", path]
        try? proc.run()
    }

    static func parseDate(_ s: String) -> Date? {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"
        return f.date(from: s)
    }

    func loadData() {
        loading = true
        DispatchQueue.global(qos: .utility).async {
            let data = DashboardView.runScript(["--projects"])
            let list = (try? JSONDecoder().decode([TrailProject].self, from: data)) ?? []
            DispatchQueue.main.async {
                cached = list
                loading = false
            }
        }
    }
}
