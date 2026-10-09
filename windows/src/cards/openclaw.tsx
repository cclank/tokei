// OpenClaw 卡片（PanelView.openclawBlock）：有 token 时同 Hermes 的排法，只有任务记录时列任务数。
import * as Fmt from "../lib/fmt";
import { L } from "../lib/i18n";
import { getRange, tokenRange, type Ranges, type TokenUsageRange } from "../lib/types";
import { CardHead, CostHeadline, EmptyHint, HStack, metric, MetricGrid, perfMetrics, VStack, type Metric } from "../ui/kit";
import { ModelDisclosure, tokenModelRows } from "../ui/models";
import { fs, rgba, T, Theme } from "../ui/theme";
import type { CardContext, CardSpec } from "./spec";

/** Model.swift OpenClawRange：任务计数 + 与 TokenUsageRange 同名的 token 字段。 */
interface OpenClawRange
  extends Pick<TokenUsageRange, "hit" | "in" | "out" | "cr" | "cw" | "reason" | "cost" | "sessions" | "models" | "perf"> {
  tasks?: number;
  completed?: number;
  failed?: number;
}

interface OpenClawStat {
  ranges?: Ranges<OpenClawRange>;
}

const EMPTY_OPENCLAW_RANGE: OpenClawRange = {};

function openClawRange(ctx: Pick<CardContext, "usage" | "range">) {
  const stat = (ctx.usage.openclaw as OpenClawStat | undefined) ?? {};
  const raw = getRange(stat.ranges, ctx.range, EMPTY_OPENCLAW_RANGE);
  return { ...tokenRange(raw), tasks: raw.tasks ?? 0, completed: raw.completed ?? 0, failed: raw.failed ?? 0 };
}

function TaskCount({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <span style={{ fontSize: fs(10), color: T.tertiary }}>{label}</span>
      <span style={{ fontSize: fs(16), fontWeight: 700, color, fontVariantNumeric: "tabular-nums" }}>{value}</span>
    </div>
  );
}

function OpenClawCard({ ctx }: { ctx: CardContext }) {
  const r = openClawRange(ctx);
  const tint = Theme.openclaw;
  const extra: Metric[] = [
    metric("arrow.down", L("输入"), Fmt.human(r.in)),
    metric("arrow.up", L("输出"), Fmt.human(r.out)),
    metric("bolt.fill", L("缓存读"), Fmt.human(r.cr)),
  ];
  if (r.reason > 0) extra.push(metric("brain", L("推理"), Fmt.human(r.reason)));
  if (r.tasks > 0) extra.push(metric("checklist", L("任务"), String(r.tasks)));
  extra.push(...perfMetrics(r.perf));
  return (
    <VStack>
      <CardHead title="OpenClaw" tint={tint} sessions={r.sessions} />
      {r.in + r.out + r.cr + r.cw + r.reason > 0 ? (
        <>
          <CostHeadline value={Fmt.human(r.in + r.out + r.cr + r.cw)} caption={L("%@ 总量", ctx.rangeLabel)} />
          <MetricGrid top={[metric("dollarsign.circle", L("≈成本"), Fmt.dollars(r.cost))]} hit={r.hit} extra={extra} tint={tint} />
          {r.models.length > 0 && (
            <ModelDisclosure
              rows={tokenModelRows(r.models, { reasonIncludedInOutput: true, perf: r.perf })}
              tint={tint}
              periodLabel={ctx.rangeLabel}
            />
          )}
        </>
      ) : r.tasks > 0 ? (
        <HStack gap={16} align="flex-start">
          <TaskCount label={L("任务")} value={r.tasks} color={T.primary} />
          {r.completed > 0 && <TaskCount label={L("完成")} value={r.completed} color={rgba(Theme.green)} />}
          {r.failed > 0 && <TaskCount label={L("失败")} value={r.failed} color={rgba(Theme.red, 0.8)} />}
        </HStack>
      ) : (
        <EmptyHint />
      )}
    </VStack>
  );
}

export const openclawCard: CardSpec = {
  id: "openclaw",
  name: "OpenClaw",
  visibleKey: "showOpenClaw",
  visibleDefault: true,
  tint: Theme.openclaw,
  active: (ctx) => {
    const r = openClawRange(ctx);
    return r.tasks > 0 || r.in + r.out + r.cr + r.cw + r.reason > 0;
  },
  render: (ctx) => <OpenClawCard ctx={ctx} />,
};
