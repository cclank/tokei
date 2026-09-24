import Foundation
import SwiftUI

/// 应用语言：跟随系统 / English / 中文 / Français。
/// 新增语言 = 新建 `<lang>.lproj/Localizable.strings` + RawValue + 显示名，零其他改动。
enum AppLanguage: String, CaseIterable, Identifiable {
    case system
    case en
    case zh
    case fr

    var id: String { rawValue }

    static let defaultsKey = "appLanguage"

    /// 设置页显示名（不本地化，保证各语言下都能认出选项）。
    var label: String {
        switch self {
        case .system: return "System / 跟随系统 / Système"
        case .en: return "English"
        case .zh: return "中文"
        case .fr: return "Français"
        }
    }

    /// 解析为实际 locale；system 跟随 macOS 首选语言（非 en/zh/fr 时回退英文）。
    var resolvedLocale: Locale {
        switch self {
        case .en: return Locale(identifier: "en")
        case .zh: return Locale(identifier: "zh-Hans")
        case .fr: return Locale(identifier: "fr")
        case .system:
            let first = Locale.preferredLanguages.first ?? "en"
            if first.hasPrefix("zh") { return Locale(identifier: "zh-Hans") }
            if first.hasPrefix("fr") { return Locale(identifier: "fr") }
            return Locale(identifier: "en")
        }
    }

    /// collector 对齐用：system 展开为实际语言代码。
    var collectorCode: String {
        switch self {
        case .en: return "en"
        case .zh: return "zh"
        case .fr: return "fr"
        case .system:
            let first = Locale.preferredLanguages.first ?? "en"
            if first.hasPrefix("zh") { return "zh" }
            if first.hasPrefix("fr") { return "fr" }
            return "en"
        }
    }

    /// 当前生效 locale（main.swift 根视图注入 `.environment(\.locale, …)` 用）。
    static var currentLocale: Locale {
        let raw = UserDefaults.standard.string(forKey: AppLanguage.defaultsKey)
        return (AppLanguage(rawValue: raw ?? "") ?? .system).resolvedLocale
    }
}

/// 强类型本地化 key：杜绝散落字面量。
/// 用法：`Text(L10n.tabHome)` 或 `String(format: L10n.daysAgo, days)`。
/// 新增 UI 文案必须先加 en+zh 的 key（test_localization 卡住），fr 允许后补。
enum L10n {
    /// 测试/裸 swiftc 场景下 Bundle.main 没有 .lproj 时，按当前语言直读 strings 文件。
    private static let table: [String: [String: String]] = {
        let fm = FileManager.default
        let langs = ["en", "zh", "fr"]
        // 1. SwiftPM 资源 bundle（Tokei.app / swift build）。
        let candidates: [URL] = [
            Bundle.main.bundleURL.appendingPathComponent("Tokei_Tokei.bundle"),
            Bundle.main.bundleURL.appendingPathComponent("Resources"),
            Bundle.main.resourceURL,
        ].compactMap { $0 }
        for base in candidates {
            var table: [String: [String: String]] = [:]
            var ok = false
            for lang in langs {
                let url = base.appendingPathComponent("\(lang).lproj/Localizable.strings")
                if let dict = NSDictionary(contentsOf: url) as? [String: String] {
                    table[lang] = dict
                    ok = true
                }
            }
            if ok { return table }
        }
        // 2. 源码树（tests/swift 裸编译）：相对 L10n.swift 向上找 Resources。
        let thisFile = URL(fileURLWithPath: #file).deletingLastPathComponent()
        var dir: URL? = thisFile
        for _ in 0 ..< 4 {
            guard let d = dir else { break }
            let res = d.appendingPathComponent("Resources")
            var table: [String: [String: String]] = [:]
            var ok = false
            for lang in langs {
                let url = res.appendingPathComponent("\(lang).lproj/Localizable.strings")
                if let dict = NSDictionary(contentsOf: url) as? [String: String] {
                    table[lang] = dict
                    ok = true
                }
            }
            if ok { return table }
            dir = d.deletingLastPathComponent()
        }
        return [:]
    }()

    private static var testBundle: Bundle? = {
        let candidates: [URL] = [
            Bundle.main.bundleURL.appendingPathComponent("Tokei_Tokei.bundle"),
            Bundle.main.bundleURL,
        ]
        for base in candidates {
            for lang in ["zh", "en"] {
                if FileManager.default.fileExists(
                    atPath: base.appendingPathComponent("\(lang).lproj").path) {
                    if let b = Bundle(url: base) { return b }
                }
            }
        }
        return nil
    }()

    private static func langCode() -> String {
        let raw = UserDefaults.standard.string(forKey: AppLanguage.defaultsKey)
        let lang = (AppLanguage(rawValue: raw ?? "") ?? .system).collectorCode
        // tests/swift 裸编译无 bundle 时跟随测试进程的系统语言（与 App 行为一致）。
        if Bundle.main.path(forResource: "zh", ofType: "lproj") == nil,
           testBundle == nil, table["en"] == nil {
            let first = Locale.preferredLanguages.first ?? "en"
            if first.hasPrefix("zh") { return "zh" }
            if first.hasPrefix("fr") { return "fr" }
            return "en"
        }
        return lang
    }

    private static let bundleCacheLock = NSLock()
    private static var bundleTableCache: [String: [String: String]] = [:]

    static var isChinese: Bool {
        langCode().hasPrefix("zh")
    }

    /// 兼容旧版采集缓存及对端同步数据中的历史合成模型名
    static let legacySyntheticName = "合成"

    private static func s(_ key: String) -> String {
        let lang = langCode()
        bundleCacheLock.lock()
        if let dict = bundleTableCache[lang] {
            bundleCacheLock.unlock()
            if let v = dict[key] { return v }
        } else if let bundle = Bundle.main.url(forResource: lang, withExtension: "lproj"),
                  let dict = NSDictionary(contentsOf: bundle.appendingPathComponent("Localizable.strings")) as? [String: String] {
            bundleTableCache[lang] = dict
            bundleCacheLock.unlock()
            if let v = dict[key] { return v }
        } else {
            bundleCacheLock.unlock()
        }
        if let v = table[lang]?[key] { return v }
        if let v = table["en"]?[key] { return v }
        if let b = testBundle {
            let v = NSLocalizedString(key, bundle: b, comment: "")
            if v != key { return v }
        }
        let v = NSLocalizedString(key, comment: "")
        return v == key ? (table["zh"]?[key] ?? key) : v
    }

    static var tabHome: String { s("tab_home") }
    static var rangeToday: String { s("range_today") }
    static var rangeYesterday: String { s("range_yesterday") }
    static var weekThis: String { s("week_this") }
    static var rangeLastWeek: String { s("range_last_week") }
    static var rangeMonth: String { s("range_month") }
    static var rangeYear: String { s("range_year") }
    static var scopeLocal: String { s("scope_local") }
    static var scopeAll: String { s("scope_all") }
    static var metricIn: String { s("metric_in") }
    static var metricOut: String { s("metric_out") }
    static var metricCacheRead: String { s("metric_cache_read") }
    static var metricCacheWrite: String { s("metric_cache_write") }
    static var metricReason: String { s("metric_reason") }
    static var metricCost: String { s("metric_cost") }
    static var metricSessions: String { s("metric_sessions") }
    static var metricCalls: String { s("metric_calls") }
    static var metricTools: String { s("metric_tools") }
    static var shareTitle: String { s("share_title") }
    static var quota5h: String { s("quota_5h") }
    static var quotaWeekAll: String { s("quota_week_all") }
    static var quotaWeekFable: String { s("quota_week_fable") }
    static var quotaWeek: String { s("quota_week") }
    static var quotaTrajectory: String { s("quota_trajectory") }
    static var dailyConsumptionTitle: String { s("daily_consumption_title") }
    static var modelSynthetic: String { s("model_synthetic") }
    static var modelUnknown: String { s("model_unknown") }
    static var sizeSmall: String { s("size_small") }
    static var sizeLarge: String { s("size_large") }
    static var resetSoon: String { s("reset_soon") }
    static var exhausted: String { s("exhausted") }
    static var loading: String { s("loading") }
    static var language: String { s("language") }
    static var grokLive: String { s("grok_live") }
    static var grokLog: String { s("grok_log") }
    static var grokCache: String { s("grok_cache") }

    /// 通用 key 访问（自动生成的 s001… 迁移串）。
    static func t(_ key: String) -> String { s(key) }

    /// 带格式参数的串（strings 文件里用 %@/%d/%f 占位）。
    static func f(_ key: String, _ args: CVarArg...) -> String {
        String(format: s(key), arguments: args)
    }
}
