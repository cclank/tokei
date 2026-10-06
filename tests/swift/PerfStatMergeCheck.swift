import Foundation

private enum TestFailure: Error {
    case assertion(String)
}

private func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() { throw TestFailure.assertion(message) }
}

@main
struct PerfStatMergeCheck {
    static func main() throws {
        // 本机 2 个 TTFT 样本落在第 40 桶，对方 1 个落在第 70 桶：合并后中位数仍在第 40 桶
        let local = try JSONDecoder().decode(PerfStat.self, from: Data("""
        {"tps": 100.0, "ttft": 0.33, "n": 4, "o": 1000, "g": 10.0, "tn": 2, "th": {"40": 2},
         "models": {"Opus 5.5": {"tps": 100.0, "ttft": 0.33, "n": 4, "o": 1000, "g": 10.0, "tn": 2, "th": {"40": 2}}}}
        """.utf8))
        let peer = try JSONDecoder().decode(PerfStat.self, from: Data("""
        {"tps": 25.0, "ttft": 1.4, "n": 1, "o": 1000, "g": 40.0, "tn": 1, "th": {"70": 1},
         "models": {"GPT-6.1 Sol": {"tps": 25.0, "ttft": 1.4, "n": 1, "o": 1000, "g": 40.0, "tn": 1, "th": {"70": 1}}}}
        """.utf8))
        guard let merged = PerfStat.merged(local, peer) else {
            throw TestFailure.assertion("两台设备都有数据，合并结果不该为空")
        }
        try expect(merged.tps == 40.0, "速度按 2000 token / 50 秒重算，不是两个平均值再平均")
        try expect(merged.th == ["40": 2, "70": 1], "直方图逐桶相加")
        let low = 0.05 * pow(1.05, 39.0), high = 0.05 * pow(1.05, 40.0)
        try expect(merged.ttft == ((low + (high - low) * 0.75) * 100).rounded() / 100,
                   "中位数按合并后的直方图重算，和采集器同一套分桶")
        try expect(merged.n == 5 && merged.tn == 3, "请求数和 TTFT 样本数相加")
        try expect(merged.models?.count == 2, "两边的模型都保留")
        try expect(PerfStat.merged(nil, peer) == peer, "本机没有数据时用对方的")
        try expect(PerfStat.merged(local, nil) == local, "对方没有数据时保留本机的")

        let old = PerfModelStat(tps: 50, ttft: nil, n: 1)
        let mixed = old.merged(with: PerfModelStat(tps: 100, ttft: 2, n: 3))
        try expect(mixed.tps == 87.5, "没带累加值时按请求数加权")
        try expect(mixed.ttft == 2 && mixed.tn == 3, "只有一边有 TTFT 时就用那一边的")
        print("perf stat merge checks passed")
    }
}
