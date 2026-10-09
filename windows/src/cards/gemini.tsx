// Gemini / Antigravity 卡片（PanelView.geminiBlock）。
// 本地 token 来自 Gemini CLI（usage.gemini）；Antigravity 的套餐额度（usage.antigravity，
// ProviderQuotaStat）画在同一张卡的下半部分，只在有本地用量时出现（与 Mac 版一致）。
import * as Fmt from "../lib/fmt";
import { L } from "../lib/i18n";
import { getRange, type PerfStat, type Ranges } from "../lib/types";
import { CardHead, CostHeadline, metric, MetricGrid, perfMetrics, ThinDivider, VStack, type Metric } from "../ui/kit";
import { ModelDisclosure, type ModelRow } from "../ui/models";
import { Theme } from "../ui/theme";
import { EMPTY_QUOTA, ProviderQuotaContent, type ProviderQuotaStat } from "./providerQuota";
import type { CardContext, CardSpec } from "./spec";

/** Model.swift GeminiModelStat。 */
export interface GeminiModelStat {
  name: string;
  in: number;
  out: number;
  cached: number;
  thoughts: number;
  cost: number;
  /** 输入单价 $/M */
  pin: number;
  /** 输出单价 $/M */
  pout: number;
  /** 缓存读单价 $/M；老数据没有 */
  pcr?: number | null;
}

/** Model.swift GeminiRange。 */
export interface GeminiRange {
  hit: number;
  in: number;
  out: number;
  cached: number;
  thoughts: number;
  cost: number;
  models?: GeminiModelStat[];
  sessions?: number;
  perf?: PerfStat | null;
}

export interface GeminiStat {
  ranges: Ranges<GeminiRange>;
}

export const EMPTY_GEMINI_RANGE: GeminiRange = { hit: 0, in: 0, out: 0, cached: 0, thoughts: 0, cost: 0, models: [], sessions: 0 };

function geminiRange(ctx: CardContext): GeminiRange {
  const stat = ctx.usage.gemini as GeminiStat | undefined;
  return getRange(stat?.ranges, ctx.range, EMPTY_GEMINI_RANGE);
}

/** GeminiRange.totalTokens */
const geminiTotal = (r: GeminiRange) => r.in + r.out + r.cached + r.thoughts;

/** GeminiRange.hasUsage */
const geminiHasUsage = (r: GeminiRange) => (r.sessions ?? 0) > 0 || geminiTotal(r) > 0;

function GeminiCard({ ctx }: { ctx: CardContext }) {
  const r = geminiRange(ctx);
  const quota = (ctx.usage.antigravity as ProviderQuotaStat | undefined) ?? EMPTY_QUOTA;
  if (!geminiHasUsage(r)) return <VStack>{null}</VStack>;
  const extra: Metric[] = [
    metric("arrow.down", L("输入"), Fmt.human(r.in)),
    metric("arrow.up", L("输出"), Fmt.human(r.out)),
    metric("bolt.fill", L("缓存"), Fmt.human(r.cached)),
  ];
  if (r.thoughts > 0) extra.push(metric("brain", L("推理"), Fmt.human(r.thoughts)));
  extra.push(...perfMetrics(r.perf));
  // Mac 版 geminiRows：缓存读放 tokCR，thoughts 放 tokCW（明细标签沿用 Mac 版的写法），不带速度。
  const rows: ModelRow[] = (r.models ?? []).map((m) => {
    const denom = m.cached + m.in;
    return {
      id: m.name,
      name: m.name,
      pin: m.pin,
      pout: m.pout,
      pcr: m.pcr ?? 0,
      cost: m.cost,
      total: m.in + m.out + m.cached + m.thoughts,
      hit: denom > 0 ? (m.cached / denom) * 100 : 0,
      tokIn: m.in,
      tokOut: m.out,
      tokCR: m.cached,
      tokCW: m.thoughts,
      hasBreakdown: true,
    };
  });
  return (
    <VStack>
      <CardHead title="Gemini / Antigravity" tint={Theme.gemini} sessions={r.sessions ?? 0} />
      <CostHeadline value={Fmt.human(geminiTotal(r))} caption={L("%@ 总量", ctx.rangeLabel)} />
      <MetricGrid
        top={[metric("dollarsign.circle", L("≈成本"), Fmt.dollars(r.cost))]}
        hit={r.hit}
        extra={extra}
        tint={Theme.gemini}
      />
      {rows.length > 0 && <ModelDisclosure rows={rows} tint={Theme.gemini} periodLabel={ctx.rangeLabel} alwaysShowCost />}
      {quota.available && (
        <>
          <ThinDivider />
          <ProviderQuotaContent quota={quota} tint={Theme.gemini} />
        </>
      )}
    </VStack>
  );
}

export const geminiCard: CardSpec = {
  id: "gemini",
  name: "Gemini",
  visibleKey: "showGemini",
  visibleDefault: true,
  tint: Theme.gemini,
  active: (ctx) => geminiHasUsage(geminiRange(ctx)),
  render: (ctx) => <GeminiCard ctx={ctx} />,
};
