import Foundation

@main
struct LocalizationCheck {
    static func expect(_ condition: Bool, _ message: String) {
        if !condition {
            fputs("FAIL: \(message)\n", stderr)
            exit(1)
        }
    }

    static func main() {
        // 中文：key 原样返回，带参数的照常替换，%% 还原成 %
        L10n.forcedLanguage = .zh
        expect(L("防休眠") == "防休眠", "Chinese returns the key itself")
        expect(L("已用 %@%%", "38") == "已用 38%", "Chinese formats arguments: \(L("已用 %@%%", "38"))")
        expect(L10n.data("连续 12 天") == "连续 12 天", "Chinese leaves collector text alone")

        // 英文
        L10n.forcedLanguage = .en
        expect(L("防休眠") == "Caffeine", "English lookup: \(L("防休眠"))")
        expect(L("已用 %@%%", "38") == "Used 38%", "English formats: \(L("已用 %@%%", "38"))")
        expect(L("这句词表里没有") == "这句词表里没有", "unknown keys fall back to the original")

        // 法文缺的词条回退英文，而不是中文
        L10n.forcedLanguage = .fr
        expect(L("Grok 登录已过期") == "Grok login expired",
               "French falls back to English: \(L("Grok 登录已过期"))")
        expect(L("设置") != "设置" && L("设置") != "Settings", "French has its own entry for 设置")

        // 按位置的占位符让译文可以调换语序
        expect(L10n.format("%2$@ – %1$@ %%", ["a", "b"]) == "b – a %", "positional placeholders")
        expect(L10n.format("%@ / %@", [1, 2]) == "1 / 2", "non-string arguments")

        // 采集器文案：精确匹配、套模板、参数里的中文一并翻译
        L10n.forcedLanguage = .en
        expect(L10n.data("5 小时") == "5 hours", "exact collector key: \(L10n.data("5 小时"))")
        expect(L10n.data("连续 12 天") == "12-day streak", "template: \(L10n.data("连续 12 天"))")
        expect(L10n.data("主项目占 64%") == "Main project 64%",
               "template with a literal percent: \(L10n.data("主项目占 64%"))")
        expect(L10n.data("合成 (Claude)") == "Synthetic (Claude)",
               "template args pass through: \(L10n.data("合成 (Claude)"))")
        expect(L10n.data("Opus 5.5") == "Opus 5.5", "non-Chinese data is untouched")

        // 数字单位：中文用「亿」，其他语言用 B
        L10n.forcedLanguage = .zh
        expect(Fmt.human(1_500_000_000) == "15.0亿", "Chinese uses 亿: \(Fmt.human(1_500_000_000))")
        L10n.forcedLanguage = .en
        expect(Fmt.human(1_500_000_000) == "1.5B", "English uses B: \(Fmt.human(1_500_000_000))")
        expect(Fmt.human(250_000_000) == "250.0M", "English keeps M below a billion")
        expect(Fmt.weekdayLabels.first == "Mon" && Fmt.weekdayLabels.count == 7,
               "English weekdays start on Monday: \(Fmt.weekdayLabels)")
        L10n.forcedLanguage = .zh
        expect(Fmt.weekdayLabels == ["一", "二", "三", "四", "五", "六", "日"], "Chinese weekdays")

        print("localization checks passed")
    }
}
