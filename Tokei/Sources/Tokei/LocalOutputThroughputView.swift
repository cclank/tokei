import SwiftUI

struct LocalOutputThroughputView: View {
    let throughput: LocalOutputThroughput
    var live = true

    var body: some View {
        if live {
            TimelineView(.periodic(from: .now, by: 1)) { context in
                content(at: context.date)
            }
        } else {
            content(at: Date())
        }
    }

    private func content(at now: Date) -> some View {
        HStack(spacing: 8) {
            Label(L("本机总输出"), systemImage: "speedometer")
                .foregroundStyle(Theme.tSecondary)
            Spacer(minLength: 4)
            if let reading = throughput.reading(at: now) {
                Text(L("近 %@ 秒", Int(reading.seconds)))
                    .foregroundStyle(Theme.tTertiary)
                Text("≈ " + Fmt.tps(reading.tokensPerSecond))
                    .fontWeight(.semibold).monospacedDigit().foregroundStyle(Theme.brand)
            } else {
                Text(L("等待采样…")).foregroundStyle(Theme.tTertiary)
            }
        }
        .font(.system(size: Theme.fontSize(10)))
        .help(L("本机所有已采集任务的新增输出（含推理）÷ 实际经过时间，最多统计最近 60 秒。并发任务相加，不受日期、卡片显隐或多设备切换影响。基于日志落盘，可能延迟；不含输入、缓存和云端账号用量。"))
        .padding(.horizontal, 10).padding(.vertical, 8)
        .background(RoundedRectangle(cornerRadius: 8).fill(Theme.brand.opacity(0.06)))
    }
}
