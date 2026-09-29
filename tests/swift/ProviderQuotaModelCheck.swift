import Foundation

private enum TestFailure: Error {
    case assertion(String)
}

private func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() { throw TestFailure.assertion(message) }
}

@main
struct ProviderQuotaModelCheck {
    static func main() throws {
        // 断言的是中文输出，不能随跑测试那台机器的系统语言变化。
        L10n.forcedLanguage = .zh
        if CommandLine.arguments.contains("--usage-stdin") {
            let data = FileHandle.standardInput.readDataToEndOfFile()
            let usage = try JSONDecoder().decode(Usage.self, from: data)
            try expect(!usage.cursor.available, "disabled Cursor should decode as unavailable")
            try expect(!usage.zed.available, "disabled Zed should decode as unavailable")
            try expect(!usage.sub2api.available, "disabled Sub2API should decode as unavailable")
            try expect(!usage.zai.available, "disabled z.ai should decode as unavailable")
            print("provider quota usage decode passed")
            return
        }
        let data = Data("""
        {
          "available": true,
          "plan": "Pro",
          "account": "user@example.com",
          "windows": [
            {
              "id": "weekly",
              "title": "周额度",
              "used_pct": 35.5,
              "reset": 1788220800,
              "window_minutes": 10080,
              "detail": "35.5 / 100",
              "usage_known": true
            }
          ],
          "details": [
            {"label": "余额", "value": "$42.50", "secondary": "USD"}
          ],
          "usage": {
            "ranges": {
              "today": {"tokens": 205, "in": 140, "out": 25, "cr": 30, "cw": 10, "requests": 2, "cost": 0.15, "models": [{"name": "GPT-5.6 Sol", "tokens": 205}]},
              "yesterday": {}, "week": {}, "last_week": {},
              "month": {}, "year": {"coverage": "近30天"}
            }
          },
          "source": "fixture",
          "updated": 1787702400,
          "stale": false
        }
        """.utf8)
        let quota = try JSONDecoder().decode(ProviderQuotaStat.self, from: data)
        try expect(quota.available, "available")
        try expect(quota.plan == "Pro", "plan")
        try expect(quota.windows.first?.used_pct == 35.5, "window percent")
        try expect(quota.windows.first?.window_minutes == 10080, "window minutes")
        try expect(quota.details.first?.secondary == "USD", "detail secondary")
        try expect(quota.usage?.ranges.today.totalTokens == 205, "provider token total")
        try expect(quota.usage?.ranges.today.requests == 2, "provider request count")
        try expect(quota.usage?.ranges.today.models.first?.tokens == 205, "provider model tokens")
        try expect(quota.usage?.ranges.year.coverage == "近30天", "provider range coverage")

        let empty = try JSONDecoder().decode(ProviderQuotaStat.self, from: Data("{}".utf8))
        try expect(!empty.available, "empty availability")
        try expect(empty.windows.isEmpty, "empty windows")
        try expect(empty.details.isEmpty, "empty details")

        let grokBot = try JSONDecoder().decode(GrokBotStat.self, from: Data("""
        {
          "ranges": {
            "today": {"sessions": 1, "calls": 2, "turns": 2, "tools": 1, "duration": 4},
            "yesterday": {}, "week": {}, "last_week": {},
            "month": {}, "year": {}
          },
          "quota": {
            "available": true,
            "plan": "X Premium+",
            "windows": [{"id": "grok-bot-period", "title": "本周期额度", "used_pct": 12.5}]
          }
        }
        """.utf8))
        try expect(grokBot.ranges.today.calls == 2, "Grok Bot response count")
        try expect(grokBot.ranges.today.tools == 1, "Grok Bot tool count")
        try expect(grokBot.quota.windows.first?.used_pct == 12.5, "Grok Bot quota")

        let geminiRanges = try JSONDecoder().decode(GeminiRanges.self, from: Data("""
        {
          "today": {"hit": 0, "in": 0, "out": 0, "cached": 0, "thoughts": 0, "cost": 0, "models": [], "sessions": 0},
          "yesterday": {"hit": 75, "in": 100, "out": 20, "cached": 30, "thoughts": 10, "cost": 1.25, "models": [], "sessions": 1},
          "week": {"hit": 75, "in": 100, "out": 20, "cached": 30, "thoughts": 10, "cost": 1.25, "models": [], "sessions": 1},
          "last_week": {"hit": 0, "in": 0, "out": 0, "cached": 0, "thoughts": 0, "cost": 0, "models": [], "sessions": 0},
          "month": {"hit": 75, "in": 100, "out": 20, "cached": 30, "thoughts": 10, "cost": 1.25, "models": [], "sessions": 1},
          "year": {"hit": 75, "in": 100, "out": 20, "cached": 30, "thoughts": 10, "cost": 1.25, "models": [], "sessions": 1}
        }
        """.utf8))
        try expect(!geminiRanges.get(.today).hasUsage,
                   "Gemini card should stay hidden when the selected range is empty")
        try expect(geminiRanges.get(.yesterday).hasUsage,
                   "Gemini card should appear when the selected range has usage")
        try expect(geminiRanges.get(.yesterday).totalTokens == 160,
                   "Gemini selected-range total")

        print("provider quota model checks passed")
    }
}
