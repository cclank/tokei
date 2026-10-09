// 通用 token 卡片（PanelView.tokenUsageBlock）和用它的十几家工具，外加 Kimi Code。
import * as Fmt from "../lib/fmt";
import { data, L } from "../lib/i18n";
import { getRange, tokenRange, type Ranges, type TokenModelStat, type TokenUsageRange } from "../lib/types";
import {
  CardHead,
  CostHeadline,
  EmptyHint,
  LabeledBadge,
  metric,
  MetricGrid,
  perfMetrics,
  QuotaRow,
  QuotaStateNotice,
  StaleQuotaFootnote,
  ThinDivider,
  UsageEmptyHint,
  VStack,
  type Metric,
} from "../ui/kit";
import { ModelDisclosure, tokenModelRows } from "../ui/models";
import { fs, T, Theme, type RGB } from "../ui/theme";
import { recentUsageHint } from "./shared";
import type { CardContext, CardSpec } from "./spec";

export const EMPTY_TOKEN_RANGE: TokenUsageRange = {};

export function tokenUsageMetrics(r: TokenUsageRange, inclusiveIO = false): Metric[] {
  const t = tokenRange(r);
  if (inclusiveIO) {
    const items = [metric("arrow.down", L("输入"), Fmt.human(t.in + t.cr + t.cw)), metric("arrow.up", L("输出"), Fmt.human(t.out + t.reason))];
    if (t.cr > 0) items.push(metric("bolt.fill", L("其中缓存读"), Fmt.human(t.cr)));
    if (t.reason > 0) items.push(metric("brain", L("其中推理"), Fmt.human(t.reason)));
    if (t.cw > 0) items.push(metric("square.stack.3d.up.fill", L("其中缓存写"), Fmt.human(t.cw)));
    return items;
  }
  const items = [
    metric("arrow.down", L("输入"), Fmt.human(t.in)),
    metric("arrow.up", L("输出"), Fmt.human(t.out)),
    metric("bolt.fill", L("缓存读"), Fmt.human(t.cr)),
    metric("square.stack.3d.up.fill", L("缓存写"), Fmt.human(t.cw)),
  ];
  if (t.reason > 0) items.push(metric("brain", L("推理"), Fmt.human(t.reason)));
  return items;
}

/** 有 token、却既没有公开价也没有 Credits 的模型：不按别的模型猜价。 */
export function unpricedModels(models: TokenModelStat[]): TokenModelStat[] {
  return models.filter(
    (m) =>
      m.in + m.out + (m.cr ?? 0) + (m.cw ?? 0) + (m.reason ?? 0) > 0 && m.cost === 0 && (m.cost_cny ?? 0) === 0 && (m.credits ?? 0) === 0,
  );
}

/** 「≈成本」：用到的模型全没有公开价时写「—」，$0.00 看着像算出来的结果。 */
export function estimatedCostLabel(r: TokenUsageRange): string {
  const t = tokenRange(r);
  const used = t.models.filter((m) => m.in + m.out + (m.cr ?? 0) + (m.cw ?? 0) + (m.reason ?? 0) > 0);
  if (t.cost === 0 && (t.cost_cny ?? 0) === 0 && used.length > 0 && unpricedModels(used).length === used.length) return "—";
  return Fmt.nativeMoney(t.cost, t.cost_cny);
}

export function UnpricedModelsNote({ models }: { models: TokenModelStat[] }) {
  const unpriced = unpricedModels(models);
  if (!unpriced.length) return null;
  return (
    <span style={{ fontSize: fs(9), color: T.tertiary }}>
      {L("≈成本未计入没有公开价的模型：%@", unpriced.map((m) => data(m.name)).join(" · "))}
    </span>
  );
}

export interface TokenUsageOptions {
  inclusiveIO?: boolean;
  showsCost?: boolean;
  showsCredits?: boolean;
  reasonIncludedInOutput?: boolean;
}

/** 通用卡片的正文（卡头之下）：总量、指标格、未计价说明、按模型。 */
export function TokenUsageBody({
  r: raw,
  tint,
  ctx,
  inclusiveIO = false,
  showsCost = true,
  showsCredits = false,
  reasonIncludedInOutput = false,
}: { r: TokenUsageRange; tint: RGB; ctx: CardContext } & TokenUsageOptions) {
  const r = tokenRange(raw);
  const total = r.in + r.out + r.cr + r.cw + (reasonIncludedInOutput ? 0 : r.reason);
  const credit = showsCredits && r.credits > 0 ? [metric("circle.hexagongrid.fill", "Credits", Fmt.credits(r.credits))] : [];
  return (
    <>
      <CostHeadline value={Fmt.human(total)} caption={L("%@ 总量", ctx.rangeLabel)} />
      <MetricGrid
        top={showsCost ? [metric("dollarsign.circle", L("≈成本"), estimatedCostLabel(raw))] : []}
        hit={r.hit}
        extra={[...credit, ...tokenUsageMetrics(raw, inclusiveIO), ...perfMetrics(r.perf)]}
        tint={tint}
      />
      {showsCost && <UnpricedModelsNote models={r.models} />}
      {r.models.length > 0 && (
        <ModelDisclosure
          rows={tokenModelRows(r.models, { reasonIncludedInOutput, inclusiveIO, perf: r.perf })}
          tint={tint}
          periodLabel={ctx.rangeLabel}
        />
      )}
    </>
  );
}

export function TokenUsageCard({ title, r, tint, ctx, ...options }: { title: string; r: TokenUsageRange; tint: RGB; ctx: CardContext } & TokenUsageOptions) {
  const sessions = r.sessions ?? 0;
  return (
    <VStack>
      <CardHead title={title} tint={tint} sessions={sessions} />
      {sessions > 0 ? <TokenUsageBody r={r} tint={tint} ctx={ctx} {...options} /> : <EmptyHint />}
    </VStack>
  );
}

interface TokenUsageCardConfig extends TokenUsageOptions {
  id: string;
  /** usage 里的键（与 id 不总一样：workbuddy-ai 对应 workbuddy_ai）。 */
  key: string;
  name: string;
  title: string;
  visibleKey: string;
  tint: RGB;
  /** CodeBuddy 只有 Credits 也算有数据。 */
  activeWhenTokensOrCredits?: boolean;
}

function rangeOf(ctx: CardContext, key: string): TokenUsageRange {
  const stat = ctx.usage[key] as { ranges?: Ranges<TokenUsageRange> } | undefined;
  return getRange(stat?.ranges, ctx.range, EMPTY_TOKEN_RANGE);
}

function tokenCard(config: TokenUsageCardConfig): CardSpec {
  return {
    id: config.id,
    name: config.name,
    visibleKey: config.visibleKey,
    visibleDefault: true,
    tint: config.tint,
    active: (ctx) => {
      const r = tokenRange(rangeOf(ctx, config.key));
      if (config.activeWhenTokensOrCredits) return r.sessions > 0 || r.in + r.out + r.cr + r.cw + r.reason > 0 || r.credits > 0;
      return r.sessions > 0;
    },
    render: (ctx) => (
      <TokenUsageCard
        title={config.title}
        r={rangeOf(ctx, config.key)}
        tint={config.tint}
        ctx={ctx}
        inclusiveIO={config.inclusiveIO}
        showsCost={config.showsCost}
        showsCredits={config.showsCredits}
        reasonIncludedInOutput={config.reasonIncludedInOutput}
      />
    ),
  };
}

export const zcodeCard = tokenCard({ id: "zcode", key: "zcode", name: "ZCode", title: "ZCode", visibleKey: "showZcode", tint: Theme.zcode });
export const mimocodeCard = tokenCard({
  id: "mimocode",
  key: "mimocode",
  name: "MiMoCode",
  title: "MiMoCode",
  visibleKey: "showMimoCode",
  tint: Theme.mimocode,
});
export const piCard = tokenCard({ id: "pi", key: "pi", name: "Pi", title: "Pi Coding Agent", visibleKey: "showPi", tint: Theme.pi });
export const primeAgentCard = tokenCard({
  id: "prime_agent",
  key: "prime_agent",
  name: "Prime Agent",
  title: "Prime Agent",
  visibleKey: "showPrimeAgent",
  tint: Theme.primeAgent,
});
export const workbuddyCard = tokenCard({
  id: "workbuddy",
  key: "workbuddy",
  name: "WorkBuddy",
  title: "WorkBuddy",
  visibleKey: "showWorkBuddy",
  tint: Theme.workbuddy,
  showsCredits: true,
});
export const workbuddyAICard = tokenCard({
  id: "workbuddy-ai",
  key: "workbuddy_ai",
  name: "WorkBuddy Intl.",
  title: "WorkBuddy Intl.",
  visibleKey: "showWorkBuddyAI",
  tint: Theme.workbuddyAI,
  showsCredits: true,
});
export const codebuddyCard = tokenCard({
  id: "codebuddy",
  key: "codebuddy",
  name: "CodeBuddy",
  title: "CodeBuddy",
  visibleKey: "showCodeBuddy",
  tint: Theme.codebuddy,
  showsCost: false,
  showsCredits: true,
  activeWhenTokensOrCredits: true,
});
export const deepseekHarnessCard = tokenCard({
  id: "deepseek_harness",
  key: "deepseek_harness",
  name: "DeepSeek Harness",
  title: "DeepSeek Harness",
  visibleKey: "showDeepSeekHarness",
  tint: Theme.deepseekHarness,
  inclusiveIO: true,
});
export const opencodeCard = tokenCard({
  id: "opencode",
  key: "opencode",
  name: "OpenCode",
  title: "OpenCode",
  visibleKey: "showOpenCode",
  tint: Theme.opencode,
});
export const qwencodeCard = tokenCard({
  id: "qwencode",
  key: "qwencode",
  name: "Qwen Code",
  title: "Qwen Code",
  visibleKey: "showQwenCode",
  tint: Theme.qwencode,
});
export const musecodeCard = tokenCard({
  id: "musecode",
  key: "musecode",
  name: "Muse Code",
  title: "Muse Code",
  visibleKey: "showMuseCode",
  tint: Theme.musecode,
  reasonIncludedInOutput: true,
});
export const cmdcodeCard = tokenCard({
  id: "cmdcode",
  key: "cmdcode",
  name: "Command Code",
  title: "Command Code",
  visibleKey: "showCmdCode",
  tint: Theme.cmdcode,
});

// ---- Kimi Code：本地 token 统计 + 官方额度（5h 滚动窗口 + 订阅周期） ----

interface KimiCodeStat {
  ranges: Ranges<TokenUsageRange>;
  p5?: number | null;
  pw?: number | null;
  r5?: number | null;
  rw?: number | null;
  q_updated?: number | null;
  p5_stale?: boolean | null;
  pw_stale?: boolean | null;
  plan?: string | null;
}

function KimiCodeCard({ ctx }: { ctx: CardContext }) {
  const x = (ctx.usage.kimicode ?? { ranges: undefined }) as KimiCodeStat;
  const r = tokenRange(getRange(x.ranges, ctx.range, EMPTY_TOKEN_RANGE));
  const hasQuota = x.p5 != null || x.pw != null;
  const hasStale = x.p5_stale === true || x.pw_stale === true;
  const tint = Theme.kimicode;
  return (
    <VStack>
      <CardHead title="Kimi Code" tint={tint} sessions={r.sessions} />
      {r.sessions > 0 ? (
        <>
          <CostHeadline value={Fmt.human(r.in + r.out + r.cr + r.cw + r.reason)} caption={L("%@ 总量", ctx.rangeLabel)} />
          <MetricGrid hit={r.hit} extra={tokenUsageMetrics(r)} tint={tint} />
          {r.models.length > 0 && <ModelDisclosure rows={tokenModelRows(r.models)} tint={tint} periodLabel={ctx.rangeLabel} />}
        </>
      ) : hasQuota ? (
        <UsageEmptyHint
          rangeLabel={ctx.rangeLabel}
          refreshing={ctx.refreshing}
          recent={recentUsageHint(ctx, (key) => {
            const range = tokenRange(getRange(x.ranges, key, EMPTY_TOKEN_RANGE));
            return range.in + range.out + range.cr + range.cw + range.reason;
          })}
        />
      ) : (
        <EmptyHint />
      )}
      {(hasQuota || hasStale) && <ThinDivider />}
      {x.p5 != null && <QuotaRow title={L("5h 剩余")} pct={100 - x.p5} reset={x.r5} tint={tint} stale={x.p5_stale === true} />}
      {x.pw != null && <QuotaRow title={L("订阅额度剩余")} pct={100 - x.pw} reset={x.rw} tint={tint} stale={x.pw_stale === true} />}
      {hasStale && (
        <StaleQuotaFootnote
          updated={x.q_updated}
          help={L(
            "Kimi Code 的登录态很快到期,过期后 Tokei 不再查询官方额度,也不会代它刷新。在 Kimi Code 里发一条消息即可让它自行刷新,额度随后恢复更新。",
          )}
        />
      )}
      {x.plan && <LabeledBadge label="plan" value={x.plan.split("LEVEL_").join("")} tint={tint} />}
      {r.sessions > 0 && !hasQuota && !hasStale && (
        <>
          <ThinDivider />
          <QuotaStateNotice
            title={L("暂未获取到额度数据")}
            detail={L("用量统计不受影响；登录 Kimi Code 后会自动展示官方额度。")}
            source={L("Kimi Code 本地登录态")}
            updated={null}
            tint={tint}
          />
        </>
      )}
    </VStack>
  );
}

export const kimicodeCard: CardSpec = {
  id: "kimicode",
  name: "Kimi Code",
  visibleKey: "showKimiCode",
  visibleDefault: true,
  tint: Theme.kimicode,
  active: ({ usage, range }) => {
    const x = (usage.kimicode ?? {}) as KimiCodeStat;
    const r = tokenRange(getRange(x.ranges, range, EMPTY_TOKEN_RANGE));
    return r.sessions > 0 || x.p5 != null || x.pw != null || x.p5_stale === true || x.pw_stale === true;
  },
  render: (ctx) => <KimiCodeCard ctx={ctx} />,
};
