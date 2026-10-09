// Hermes 卡片（PanelView.hermesBlock）。
import * as Fmt from "../lib/fmt";
import { L } from "../lib/i18n";
import { getRange, tokenRange, type Ranges, type TokenUsageRange } from "../lib/types";
import { CardHead, CostHeadline, EmptyHint, metric, MetricGrid, perfMetrics, VStack, type Metric } from "../ui/kit";
import { ModelDisclosure, tokenModelRows } from "../ui/models";
import { Theme } from "../ui/theme";
import type { CardContext, CardSpec } from "./spec";

/** Model.swift HermesRange：hit、in、out、cr、cw、reason、cost、sessions、models、perf，
 *  是 TokenUsageRange 的子集，直接借用它的类型与 tokenRange() 补零。 */
type HermesRange = Pick<TokenUsageRange, "hit" | "in" | "out" | "cr" | "cw" | "reason" | "cost" | "sessions" | "models" | "perf">;

interface HermesStat {
  ranges?: Ranges<HermesRange>;
}

const EMPTY_HERMES_RANGE: HermesRange = {};

function hermesRange(ctx: Pick<CardContext, "usage" | "range">) {
  const stat = (ctx.usage.hermes as HermesStat | undefined) ?? {};
  return tokenRange(getRange(stat.ranges, ctx.range, EMPTY_HERMES_RANGE));
}

function HermesCard({ ctx }: { ctx: CardContext }) {
  const r = hermesRange(ctx);
  const tint = Theme.hermes;
  const extra: Metric[] = [
    metric("arrow.down", L("输入"), Fmt.human(r.in)),
    metric("arrow.up", L("输出"), Fmt.human(r.out)),
    metric("bolt.fill", L("缓存读"), Fmt.human(r.cr)),
  ];
  if (r.reason > 0) extra.push(metric("brain", L("推理"), Fmt.human(r.reason)));
  extra.push(...perfMetrics(r.perf));
  return (
    <VStack>
      <CardHead title="Hermes" tint={tint} sessions={r.sessions} />
      {r.sessions > 0 ? (
        <>
          <CostHeadline value={Fmt.human(r.in + r.out + r.cr + r.cw + r.reason)} caption={L("%@ 总量", ctx.rangeLabel)} />
          <MetricGrid top={[metric("dollarsign.circle", L("≈成本"), Fmt.dollars(r.cost))]} hit={r.hit} extra={extra} tint={tint} />
          {r.models.length > 0 && (
            <ModelDisclosure rows={tokenModelRows(r.models, { perf: r.perf })} tint={tint} periodLabel={ctx.rangeLabel} />
          )}
        </>
      ) : (
        <EmptyHint />
      )}
    </VStack>
  );
}

export const hermesCard: CardSpec = {
  id: "hermes",
  name: "Hermes",
  visibleKey: "showHermes",
  visibleDefault: true,
  tint: Theme.hermes,
  active: (ctx) => hermesRange(ctx).sessions > 0,
  render: (ctx) => <HermesCard ctx={ctx} />,
};
