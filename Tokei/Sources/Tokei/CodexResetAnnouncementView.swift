import SwiftUI

struct CodexResetAnnouncementView: View {
    @ObservedObject var monitor: CodexResetMonitor
    var live = true

    var body: some View {
        if live {
            TimelineView(.periodic(from: .now, by: 30)) { context in
                content(now: context.date)
            }
        } else {
            content(now: Date())
        }
    }

    private func content(now: Date) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Label(L("额外重置动态"), systemImage: "clock.arrow.circlepath")
                    .font(.system(size: Theme.fontSize(11), weight: .semibold))
                Spacer(minLength: 4)
                Link(destination: CodexResetMonitor.pageURL) {
                    Text("AIHOT ↗").font(.system(size: Theme.fontSize(10)))
                }
                .foregroundStyle(Theme.codex)
            }
            .foregroundStyle(Theme.tSecondary)

            if let snapshot = monitor.snapshot {
                let feed = snapshot.feed
                let stale = monitor.lastFetchFailed || feed.isStale(at: now, fetchedAt: snapshot.fetchedAt)
                if let event = feed.current {
                    eventContent(event, now: now, stale: stale)
                } else {
                    Text(stale ? L("上次检查：无待生效公告") : L("暂无待生效公告"))
                        .foregroundStyle(Theme.tPrimary)
                    if let event = feed.lastLanded {
                        Text(L("最近：%@", eventName(event)))
                            .foregroundStyle(Theme.tSecondary)
                        confirmation(event)
                        if event.phase(at: now) == .likely {
                            Text(L("按预计时间应已生效，尚未确认"))
                                .foregroundStyle(Theme.tSecondary)
                        }
                    }
                    Text(L("下一次尚未公布，不预测固定周期"))
                        .foregroundStyle(Theme.tTertiary)
                }
                if stale {
                    HStack {
                        Text(monitor.lastFetchFailed ? L("刷新失败，显示上次记录") : L("来源检查有延迟，等待更新"))
                            .foregroundStyle(.orange)
                        Spacer(minLength: 4)
                        retryButton
                    }
                }
                HStack(alignment: .firstTextBaseline) {
                    Text(L("检查 %@", localTime(feed.monitor?.lastVerifiedAt ?? feed.checkedAt)))
                    Spacer(minLength: 3)
                    if let url = (feed.current ?? feed.lastLanded)?.sourceURL {
                        Link(L("原帖 ↗"), destination: url).foregroundStyle(Theme.codex)
                    }
                }
                .foregroundStyle(Theme.tTertiary)
                .font(.system(size: Theme.fontSize(9)))
            } else {
                HStack {
                    Text(monitor.lastFetchFailed ? L("重置动态暂不可用") : L("正在读取重置公告…"))
                    Spacer(minLength: 4)
                    if monitor.lastFetchFailed {
                        retryButton
                    }
                }
                .foregroundStyle(Theme.tSecondary)
            }
            if let failure = monitor.lastFailure {
                Text(failureDescription(failure)).foregroundStyle(Theme.tTertiary)
            }
            Text(L("AIHOT 整理 · 非官方 · %@", Fmt.localTimeZoneCaption()))
                .font(.system(size: Theme.fontSize(9))).foregroundStyle(Theme.tTertiary)
        }
        .font(.system(size: Theme.fontSize(10)))
        .fixedSize(horizontal: false, vertical: true)
    }

    private var retryButton: some View {
        Button(L("重试")) { monitor.refresh(force: true) }
            .buttonStyle(.plain).foregroundStyle(Theme.codex)
            .disabled(monitor.isRefreshing)
    }

    private func failureDescription(_ failure: CodexResetMonitor.Failure) -> String {
        switch failure {
        case .network(let code): return L("网络请求失败（%@），将自动重试", code)
        case .http(let status): return L("来源返回 HTTP %@，将自动重试", status)
        case .invalidResponse: return L("来源响应无效，将自动重试")
        case .invalidData: return L("公告数据格式异常，将自动重试")
        }
    }

    private func eventName(_ event: CodexResetFeed.Event) -> String {
        if event.type == "reset_credit" { return L("重置卡发放") }
        if let label = event.displayLabel, !label.isEmpty { return label }
        return event.type == "direct_reset" ? L("额度重置") : L("重置公告")
    }

    @ViewBuilder
    private func eventContent(_ event: CodexResetFeed.Event, now: Date, stale: Bool) -> some View {
        Text(eventName(event)).foregroundStyle(Theme.tPrimary)
        if stale {
            Text(L("上次公告状态，待重新核实")).foregroundStyle(Theme.tSecondary)
        } else {
            switch event.phase(at: now) {
            case .confirmed:
                Text(L("已确认生效，以账户显示为准")).foregroundStyle(Theme.codex)
            case .likely:
                Text(L("按预计时间应已生效，尚未确认")).foregroundStyle(Theme.tSecondary)
            case .inProgress:
                Text(L("正在进行，等待完成确认")).foregroundStyle(Theme.codex)
            case .scheduled(let start):
                Text(L("距预计开始还有 %@", Fmt.remaining(Int(start.timeIntervalSince1970), now: now)))
                    .foregroundStyle(Theme.codex).monospacedDigit()
            case .withinWindow:
                Text(L("处于预计时段，等待确认")).foregroundStyle(Theme.codex)
            case .overdue:
                Text(L("已过预计时间，等待确认")).foregroundStyle(.orange)
            case .awaitingTime:
                Text(L("已宣布，具体时间待定")).foregroundStyle(Theme.tSecondary)
            case .unknown:
                Text(L("公告状态待核实，请查看原文")).foregroundStyle(Theme.tSecondary)
            }
        }
        if event.phase(at: now) == .confirmed {
            confirmation(event)
        } else if let window = event.window {
            if let from = window.from {
                Text(L("预计 %@", localTime(from) + (window.through.map { " – " + localTime($0) } ?? "")))
                    .foregroundStyle(Theme.tSecondary).monospacedDigit()
            } else if let through = window.through {
                Text(L("预计不晚于 %@", localTime(through))).foregroundStyle(Theme.tSecondary)
            }
            if let reason = window.reason, !reason.isEmpty {
                Text(reason).foregroundStyle(Theme.tTertiary).lineLimit(2).help(reason)
            }
        }
        let audience = event.presentation?.audienceZh ?? event.presentation?.scopeLabel
        Text(L("适用：%@", audience ?? L("原帖未说明")))
            .foregroundStyle(Theme.tTertiary).lineLimit(2)
        if event.type == "reset_credit" {
            Text(L("发卡后需自行使用，余额以 Codex 为准"))
                .foregroundStyle(Theme.tTertiary)
        }
    }

    @ViewBuilder
    private func confirmation(_ event: CodexResetFeed.Event) -> some View {
        if let confirmed = event.confirmedAt {
            Text(L("确认帖 %@ · 非精确到账时间", localTime(confirmed)))
                .foregroundStyle(Theme.tTertiary)
        } else if let day = event.occurredOn {
            Text(L("核实到账日期：%@（来源时区 UTC+8）", day))
                .foregroundStyle(Theme.tTertiary)
        } else if event.confirmationBasis == "receipt_review" {
            Text(L("来源已核实到账，具体日期未定")).foregroundStyle(Theme.tTertiary)
        }
    }

    private func localTime(_ date: Date) -> String { Fmt.localTime(Int(date.timeIntervalSince1970)) }
}
