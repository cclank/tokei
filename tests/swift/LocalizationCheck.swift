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

        // Price update report: several collector lines, each translated on its own.
        let priceReport = "已更新 454 个在线模型，保留 144 个历史模型 → /tmp/pricing.json\n"
            + "已核对 12 个 OpenAI 官方模型价格\n"
        expect(L10n.dataLines(priceReport)
                == "Updated 454 active models, kept 144 retired models → /tmp/pricing.json\n"
                + "Verified official prices for 12 OpenAI models",
               "price update report: \(L10n.dataLines(priceReport))")
        expect(L10n.dataLines("已更新 454 个在线模型 → /tmp/pricing.json")
                == "Updated 454 active models → /tmp/pricing.json",
               "price update without retired models")
        L10n.forcedLanguage = .zh
        expect(L10n.dataLines(priceReport + "\n")
                == priceReport.trimmingCharacters(in: .newlines),
               "Chinese keeps the price update report as is")
        L10n.forcedLanguage = .en

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

        // Sync detail: script messages are translated, Git's own lines pass through.
        let syncFailure = "From github.com:someone/tokei-data\n"
            + "Tokei sync error: 同步仓库必须位于 main 分支，当前为 feature/x"
        L10n.forcedLanguage = .en
        expect(L10n.syncOutput(syncFailure)
                == "From github.com:someone/tokei-data\n"
                + "Tokei sync error: The sync repository must be on the main branch; currently on feature/x",
               "sync failure detail: \(L10n.syncOutput(syncFailure))")
        expect(L10n.syncOutput("检测到其他设备同时更新，正在重试 2/3\n多设备同步完成")
                == "Another device updated at the same time; retrying 2/3\nMulti-device sync complete",
               "sync progress lines: \(L10n.syncOutput("检测到其他设备同时更新，正在重试 2/3\n多设备同步完成"))")
        expect(L10n.syncOutput("Tokei sync error: 无法检查本地提交 abc123 的本机快照")
                == "Tokei sync error: Cannot inspect this device’s snapshot in local commit abc123",
               "the longer commit template wins")
        expect(L10n.syncOutput("Tokei sync error: 检测到未完成的 MERGE_HEAD，已停止且未改动仓库")
                == "Tokei sync error: Found an unfinished MERGE_HEAD; stopped without changing the repository",
               "operation name is kept")
        L10n.forcedLanguage = .zh
        expect(L10n.syncOutput(syncFailure) == syncFailure, "Chinese keeps the sync detail as is")

        print("localization checks passed")
    }
}
