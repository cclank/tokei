// Claude Code 卡片（PanelView.claudeBlock）。
import * as Fmt from "../lib/fmt";
import { L } from "../lib/i18n";
import { getRange, modelPerf, type ClaudeRange, type ClaudeStat } from "../lib/types";
import { Icon } from "../ui/Icon";
import {
  CardHead,
  CostHeadline,
  HStack,
  metric,
  MetricGrid,
  perfMetrics,
  QuotaRow,
  QuotaStateNotice,
  StaleQuotaFootnote,
  ThinDivider,
  UsageEmptyHint,
  VStack,
} from "../ui/kit";
import { ModelDisclosure, type ModelRow } from "../ui/models";
import { fs, T, Theme } from "../ui/theme";
import type { CardContext, CardSpec } from "./spec";
import { quotaState, recentUsageHint } from "./shared";

export const EMPTY_CLAUDE_RANGE: ClaudeRange = { hit: 0, in: 0, out: 0, cr: 0, cw: 0, cost: 0, models: [], sessions: 0 };

function ClaudeQuotaStatus({ stat }: { stat: ClaudeStat }) {
  // 读数是一起刷新的：只要还有一个窗口是新的，其余过期的只是窗口翻篇（行上写「已重置」）
  const fresh =
    (stat.q5 != null && stat.q5_stale !== true) ||
    (stat.q7 != null && stat.q7_stale !== true) ||
    (stat.qf != null && stat.qf_stale !== true);
  if (!fresh) {
    return <StaleQuotaFootnote updated={stat.q_updated} help={L("Claude Code 或 Claude 桌面端下次读到额度时自动刷新")} />;
  }
  return (
    <div title={L("来自 Claude Code CLI 或 Desktop")}>
      <HStack gap={5} style={{ color: T.tertiary }}>
        <Icon name="clock" size={fs(9.5)} />
        <span style={{ fontSize: fs(9.5), fontFamily: "var(--mono)" }}>
          {L("额度更新")} · {stat.q_updated != null ? Fmt.reset(stat.q_updated) : L("更新时间未知")}
        </span>
      </HStack>
    </div>
  );
}

function ClaudeCard({ ctx }: { ctx: CardContext }) {
  const c = ctx.usage.claude;
  const r = getRange(c.ranges, ctx.range, EMPTY_CLAUDE_RANGE);
  const sessions = r.sessions ?? 0;
  const state = quotaState([
    [c.q5, c.q5_stale],
    [c.q7, c.q7_stale],
    [c.qf, c.qf_stale],
  ]);
  const rows: ModelRow[] = (r.models ?? [])
    .filter((m) => m.name !== "合成") // l10n-ignore
    .map((m) => {
      const denom = m.cr + m.cw + m.in;
      return {
        id: m.name,
        name: m.name,
        pin: m.pin,
        pout: m.pout,
        pcr: m.pcr ?? 0,
        cost: m.cost,
        total: m.in + m.out + m.cr + m.cw,
        hit: denom > 0 ? (m.cr / denom) * 100 : 0,
        tokIn: m.in,
        tokOut: m.out,
        tokCR: m.cr,
        tokCW: m.cw,
        perf: modelPerf(r.perf, m.name),
        hasBreakdown: true,
      };
    });
  const cliQuota = ctx.pref("claudeCLIQuotaEnabled", false);
  return (
    <VStack>
      <CardHead title="Claude Code" tint={Theme.claude} sessions={sessions} />
      {sessions > 0 ? (
        <>
          <CostHeadline value={Fmt.human(r.in + r.out + r.cr + r.cw)} caption={L("%@ 总量", ctx.rangeLabel)} />
          <MetricGrid
            top={[metric("dollarsign.circle", L("≈成本"), Fmt.dollars(r.cost))]}
            hit={r.hit}
            extra={[
              metric("arrow.down", L("输入"), Fmt.human(r.in)),
              metric("arrow.up", L("输出"), Fmt.human(r.out)),
              metric("bolt.fill", L("缓存读"), Fmt.human(r.cr)),
              metric("square.stack.3d.up.fill", L("缓存写"), Fmt.human(r.cw)),
              ...perfMetrics(r.perf),
            ]}
            tint={Theme.claude}
          />
          {rows.length > 0 && <ModelDisclosure rows={rows} tint={Theme.claude} periodLabel={ctx.rangeLabel} alwaysShowCost />}
        </>
      ) : (
        state !== "unavailable" && (
          <UsageEmptyHint
            rangeLabel={ctx.rangeLabel}
            refreshing={ctx.refreshing}
            recent={recentUsageHint(ctx, (key) => {
              const range = getRange(c.ranges, key, EMPTY_CLAUDE_RANGE);
              return range.in + range.out + range.cr + range.cw;
            })}
          />
        )
      )}
      {state !== "unavailable" ? (
        <>
          <ThinDivider />
          {c.q5 != null && <QuotaRow title={L("5h 剩余")} pct={100 - c.q5} reset={c.q5_reset} tint={Theme.claude} stale={c.q5_stale === true} />}
          {c.q7 != null && (
            <QuotaRow title={L("周 · 全部剩余")} pct={100 - c.q7} reset={c.q7_reset} tint={Theme.claude} stale={c.q7_stale === true} />
          )}
          {c.qf != null && (
            <QuotaRow title={L("周 · Fable 剩余")} pct={100 - c.qf} reset={c.qf_reset} tint={Theme.orange} stale={c.qf_stale === true} />
          )}
          <ClaudeQuotaStatus stat={c} />
        </>
      ) : (
        sessions > 0 && (
          <>
            <ThinDivider />
            <QuotaStateNotice
              title={L("暂未获取到额度数据")}
              detail={
                cliQuota
                  ? L("用量统计不受影响；登录态或网络恢复后会自动重试。")
                  : L("仅使用 CLI 时，可在「隐私与额度」开启 Claude Code CLI 额度查询。")
              }
              source={L("Claude Code 额度缓存")}
              updated={c.q_updated}
              tint={Theme.claude}
            />
          </>
        )
      )}
    </VStack>
  );
}

export const claudeCard: CardSpec = {
  id: "claude",
  name: "Claude",
  visibleKey: "showClaude",
  visibleDefault: true,
  tint: Theme.claude,
  active: ({ usage, range }) => {
    const c = usage.claude;
    return (getRange(c.ranges, range, EMPTY_CLAUDE_RANGE).sessions ?? 0) > 0 || c.q5 != null || c.q7 != null || c.qf != null;
  },
  render: (ctx) => <ClaudeCard ctx={ctx} />,
};
