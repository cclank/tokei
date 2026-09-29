import Foundation

private enum TestFailure: Error {
    case assertion(String)
}

private func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() { throw TestFailure.assertion(message) }
}

@main
struct DevinUsageModelCheck {
    static func main() throws {
        // 断言的是中文输出，不能随跑测试那台机器的系统语言变化。
        L10n.forcedLanguage = .zh
        // 两个来源同时有数据：CLI 会话库的 token 与桌面端保存的套餐额度。
        let both = try JSONDecoder().decode(DevinStat.self, from: Data("""
        {
          "ranges": {
            "today": {"hit": 70.5, "in": 17370, "out": 166, "cr": 41664, "cw": 0, "reason": 0, "cost": 0.42, "sessions": 1, "models": [{"model_id": "swe-1-6-slow", "name": "Swe 1 6 Slow", "in": 17370, "out": 166, "cr": 41664, "cw": 0, "reason": 0, "cost": 0.42, "pin": 0, "pout": 0}]},
            "yesterday": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
            "week": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
            "last_week": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
            "month": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
            "year": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []},
            "all": {"hit": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0, "sessions": 0, "models": []}
          },
          "quota": {
            "available": true,
            "plan": "Devin Pro",
            "windows": [
              {"id": "devin-daily", "title": "日额度", "used_pct": 2,
               "reset": 1789372800, "window_minutes": 1440, "usage_known": true},
              {"id": "devin-weekly", "title": "周额度", "used_pct": 1,
               "reset": 1789891200, "window_minutes": 10080, "usage_known": true}
            ],
            "details": [{"label": "超额余额", "value": "$10.00"}],
            "source": "devin-app-cache",
            "updated": 1789912191,
            "stale": false
          }
        }
        """.utf8))

        let today = both.ranges.get(.today)
        try expect(today.in == 17370, "Devin fresh input")
        try expect(today.cr == 41664, "Devin cache read")
        try expect(today.cw == 0, "Devin cache write")
        try expect(today.out == 166, "Devin output")
        try expect(today.totalTokens == 59200, "Devin exact total")
        try expect(today.sessions == 1, "Devin sessions")
        try expect(today.models.count == 1, "Devin models")

        try expect(both.quota.available, "Devin quota availability")
        try expect(both.quota.plan == "Devin Pro", "Devin plan line")
        try expect(both.quota.windows.count == 2, "Devin window count")
        try expect(both.quota.windows[0].id == "devin-daily", "Devin daily window")
        try expect(both.quota.windows[0].window_minutes == 1440, "Devin daily length")
        try expect(both.quota.windows[1].window_minutes == 10080, "Devin weekly length")
        try expect(!both.quota.stale, "Devin fresh snapshot")
        try expect(both.quota.updated == 1789912191, "Devin launch stamp")

        // 免费套餐报的是一池消息数：没有周期，也没有重置时刻。
        let free = try JSONDecoder().decode(DevinStat.self, from: Data("""
        {
          "quota": {
            "available": true, "plan": "Devin Free",
            "windows": [{"id": "devin-messages", "title": "消息额度",
                         "used_pct": 30, "usage_known": true,
                         "detail": "剩余 1,750 / 2,500 条"}],
            "source": "devin-app-cache", "updated": 1789912191, "stale": true
          }
        }
        """.utf8))
        try expect(free.quota.windows.count == 1, "Devin message pool window")
        try expect(free.quota.windows[0].window_minutes == nil, "Devin message pool has no period")
        try expect(free.quota.windows[0].reset == nil, "Devin message pool has no reset")
        try expect(free.quota.stale, "Devin stale snapshot")
        // 缺失的那一半解码成空，不是解码失败。
        try expect(free.ranges.get(.today).totalTokens == 0, "Devin absent ranges decode empty")

        // 整个键缺席时，Usage 仍然能解码（旧版脚本 + 新版 App）。
        let missing = try JSONDecoder().decode(DevinStat.self, from: Data("{}".utf8))
        try expect(!missing.quota.available, "Devin absent quota")
        try expect(missing.ranges.get(.all).totalTokens == 0, "Devin absent tokens")

        print("devin usage model checks passed")
    }
}
