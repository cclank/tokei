import Foundation

/// 界面语言。
///
/// 中文是源语言：代码里写的中文原文就是 key，`L("防休眠")` 在中文下原样返回，
/// 其他语言查 `Tokei/Localization/<lang>.lproj/Localizable.strings`（中文 → 译文），
/// 打包时复制到 App 的 Contents/Resources。词表不放在 Sources 里，免得 SwiftPM 接管本地化。
/// 这样代码读起来和写死中文时一样，词表缺哪句，测试一眼就能指出是哪句。
///
/// 采集器吐出来的标签（额度窗口名、详情标签、「合成」等）同样是中文，
/// 界面显示时再过一遍 `L()`，采集结果和同步快照本身不带语言。
enum AppLanguage: String, CaseIterable, Identifiable {
    case system, zh, en, fr, ja, ko

    var id: String { rawValue }

    static let defaultsKey = "appLanguage"

    /// 设置里的选项名。各语言用自己的写法，切到任何语言都认得出来。
    var optionName: String {
        switch self {
        case .system: return L("跟随系统")
        case .zh: return "中文" // l10n-ignore
        case .en: return "English"
        case .fr: return "Français"
        case .ja: return "日本語" // l10n-ignore
        case .ko: return "한국어"
        }
    }

    /// 实际生效的语言。跟随系统时取 macOS 首选语言，不支持的语言回退英文。
    var resolved: AppLanguage {
        guard self == .system else { return self }
        let preferred = Locale.preferredLanguages.first?.lowercased() ?? "en"
        for language in [AppLanguage.zh, .fr, .ja, .ko] where preferred.hasPrefix(language.rawValue) {
            return language
        }
        return .en
    }

    /// 用户没选过时：系统语言列表里只要有中文就用中文。很多中文用户的 macOS 首选语言
    /// 是英文、中文排第二，严格跟随系统会让他们升级后突然看到英文界面。
    /// 在设置里明确选「跟随系统」才只看第一语言。
    static var selected: AppLanguage {
        if let raw = UserDefaults.standard.string(forKey: defaultsKey),
           let language = AppLanguage(rawValue: raw) {
            return language
        }
        let preferred = Locale.preferredLanguages.map { $0.lowercased() }
        return preferred.contains { $0.hasPrefix("zh") } ? .zh : .system
    }

    static var current: AppLanguage {
        if let forced = L10n.forcedLanguage { return forced }
        return selected.resolved
    }
}

enum L10n {
    /// 离屏截图与测试用：不碰用户设置，直接指定语言。
    static var forcedLanguage: AppLanguage?

    /// 设置里换了语言。AppKit 那一侧（菜单栏标题、右键菜单）靠它刷新。
    static let languageDidChange = Notification.Name("TokeiLanguageDidChange")

    static var isChinese: Bool { AppLanguage.current == .zh }

    private static let lock = NSLock()
    private static var tables: [AppLanguage: [String: String]] = [:]

    /// 按当前语言取译文：当前语言 → 英文 → 中文原文。
    /// 法、日、韩的词表允许缺词，缺了先给英文；英文由测试保证齐全。
    static func lookup(_ key: String) -> String {
        let language = AppLanguage.current
        if language == .zh { return key }
        if let value = table(language)[key] { return value }
        if language != .en, let value = table(.en)[key] { return value }
        return key
    }

    /// 词表里只用 `%@`（按顺序）或 `%1$@`（按位置，译文可调换语序），`%%` 是百分号本身。
    /// 数字请先格式化成字符串再传进来，避免 %d / %@ 与参数类型对不上时崩溃。
    static func format(_ template: String, _ args: [Any]) -> String {
        let values = args.map { "\($0)" }
        var result = ""
        var next = 0
        var index = template.startIndex
        while index < template.endIndex {
            let character = template[index]
            guard character == "%" else {
                result.append(character)
                index = template.index(after: index)
                continue
            }
            let rest = template[template.index(after: index)...]
            if rest.hasPrefix("%") {
                result.append("%")
                index = template.index(index, offsetBy: 2)
            } else if rest.hasPrefix("@") {
                result += next < values.count ? values[next] : ""
                next += 1
                index = template.index(index, offsetBy: 2)
            } else if let dollar = rest.firstIndex(of: "$"),
                      let position = Int(rest[rest.startIndex..<dollar]),
                      rest[rest.index(after: dollar)...].hasPrefix("@") {
                result += (1...values.count).contains(position) ? values[position - 1] : ""
                index = template.index(dollar, offsetBy: 2)
            } else {
                result.append(character)
                index = template.index(after: index)
            }
        }
        return result
    }

    /// 翻译采集器给的文案（额度窗口名、详情标签、成就描述……）。
    ///
    /// 采集结果与同步快照一律存中文原文，显示时才翻译。先按原文精确查；查不到时
    /// 用词表里带 `%@` 的模板去套，例如「连续 120 天」套上「连续 %@ 天」。
    /// 只用固定部分里有中文的模板，免得「%@：%@」这种把什么都吞下去。
    static func data(_ text: String) -> String {
        let language = AppLanguage.current
        guard language != .zh, !text.isEmpty else { return text }
        let exact = lookup(text)
        if exact != text { return exact }
        for (template, pattern) in dataPatterns() {
            let range = NSRange(text.startIndex..., in: text)
            guard let match = pattern.firstMatch(in: text, range: range) else { continue }
            // 参数本身也可能是采集器的中文（「今日请求」里的「今日」），一并翻译。
            let args: [Any] = (1..<match.numberOfRanges).compactMap {
                Range(match.range(at: $0), in: text).map { data(String(text[$0])) }
            }
            let translated = lookup(template)
            return translated == template ? text : format(translated, args)
        }
        return text
    }

    private static var cachedPatterns: [(String, NSRegularExpression)]?

    private static func dataPatterns() -> [(String, NSRegularExpression)] {
        lock.lock()
        if let cached = cachedPatterns {
            lock.unlock()
            return cached
        }
        lock.unlock()
        let cjk = try? NSRegularExpression(pattern: "[\\u4e00-\\u9fff]")
        var patterns: [(String, NSRegularExpression)] = []
        for key in table(.en).keys where key.contains("%@") {
            let pieces = key.components(separatedBy: "%@")
            let fixed = pieces.joined()
            guard let cjk, cjk.firstMatch(in: fixed, range: NSRange(fixed.startIndex..., in: fixed)) != nil
            else { continue }
            let body = pieces.map { NSRegularExpression.escapedPattern(for: $0.replacingOccurrences(of: "%%", with: "%")) }
                .joined(separator: "(.+?)")
            if let regex = try? NSRegularExpression(pattern: "^" + body + "$") {
                patterns.append((key, regex))
            }
        }
        // 固定部分越长越具体，先试。
        patterns.sort { $0.0.count > $1.0.count }
        lock.lock()
        cachedPatterns = patterns
        lock.unlock()
        return patterns
    }

    private static func table(_ language: AppLanguage) -> [String: String] {
        lock.lock()
        defer { lock.unlock() }
        if let cached = tables[language] { return cached }
        let loaded = candidateURLs(language).lazy
            .compactMap { NSDictionary(contentsOf: $0) as? [String: String] }
            .first ?? [:]
        tables[language] = loaded
        return loaded
    }

    /// App 包里在 Contents/Resources；测试直接编译源码时退回源码树里的 Tokei/Localization。
    private static func candidateURLs(_ language: AppLanguage) -> [URL] {
        let file = "\(language.rawValue).lproj/Localizable.strings"
        var urls: [URL] = []
        if let resources = Bundle.main.resourceURL {
            urls.append(resources.appendingPathComponent(file))
        }
        urls.append(URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Localization").appendingPathComponent(file))
        return urls
    }
}

/// 界面文案。key 是中文原文，见 `L10n`。
func L(_ key: String) -> String {
    L10n.lookup(key)
}

/// 带参数的界面文案：`L("额度来源 %@ · %@", source, updated)`。
func L(_ key: String, _ args: Any...) -> String {
    L10n.format(L10n.lookup(key), args)
}
