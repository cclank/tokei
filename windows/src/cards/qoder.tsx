// Qoder 系列卡片（PanelView.qoderIdeBlock、qoderworkBlock、qodercliBlock）：
// Qoder Desktop、QoderWork、Qoder CLI，以及与 CLI 同格式、共用一种排法的 Qoder CN（~/.qoder-cn）。
import * as Fmt from "../lib/fmt";
import { L } from "../lib/i18n";
import { getRange, type PerfStat, type RangeKey, type Ranges, type TokenModelStat, type Usage } from "../lib/types";
import {
  CardHead,
  CostHeadline,
  EmptyHint,
  LabeledBadge,
  metric,
  MetricGrid,
  perfMetrics,
  VStack,
  type Metric,
} from "../ui/kit";
import { ModelDisclosure, tokenModelRows } from "../ui/models";
import { Theme, type RGB } from "../ui/theme";
import type { CardContext, CardSpec } from "./spec";

// ---- 数据结构（Model.swift 的 QoderRange / QoderStat / QoderIdeRange / QoderIdeStat） ----

/** QoderWork、Qoder CLI、Qoder CN 共用；缺的字段一律按 0。 */
interface QoderRange {
  in?: number;
  out?: number;
  cr?: number;
  cw?: number;
  credits?: number;
  usage_calls?: number;
  usage_available?: boolean;
  hit?: number;
  models?: TokenModelStat[];
  sessions?: number;
  calls?: number;
  sub_agents?: number;
  turns?: number;
  /** 毫秒。 */
  duration?: number;
  ctx?: number;
  tools?: number;
  est?: number;
  perf?: PerfStat | null;
}

interface QoderStat {
  ranges?: Ranges<QoderRange>;
  model?: string | null;
}

/** Qoder Desktop（IDE）的统计口径不同：cached 而不是 cr/cw，duration 是秒。 */
interface QoderIdeRange {
  in?: number;
  out?: number;
  cached?: number;
  sessions?: number;
  sub_agents?: number;
  calls?: number;
  messages?: number;
  ctx?: number;
  /** 秒。 */
  duration?: number;
}

interface QoderIdeStat {
  ranges?: Ranges<QoderIdeRange>;
  model?: string | null;
}

const EMPTY_QODER_RANGE: QoderRange = {};
const EMPTY_QODER_IDE_RANGE: QoderIdeRange = {};

function qoderRange(stat: QoderStat, range: RangeKey) {
  const r = getRange(stat.ranges, range, EMPTY_QODER_RANGE);
  return {
    in: r.in ?? 0,
    out: r.out ?? 0,
    cr: r.cr ?? 0,
    cw: r.cw ?? 0,
    credits: r.credits ?? 0,
    usage_available: r.usage_available === true,
    hit: r.hit ?? 0,
    models: r.models ?? [],
    sessions: r.sessions ?? 0,
    calls: r.calls ?? 0,
    sub_agents: r.sub_agents ?? 0,
    turns: r.turns ?? 0,
    duration: r.duration ?? 0,
    ctx: r.ctx ?? 0,
    tools: r.tools ?? 0,
    perf: r.perf ?? null,
  };
}

/** QoderRange.totalTokens。 */
const qoderTotal = (r: ReturnType<typeof qoderRange>) => r.in + r.out + r.cr + r.cw;

function qoderIdeRange(stat: QoderIdeStat, range: RangeKey) {
  const r = getRange(stat.ranges, range, EMPTY_QODER_IDE_RANGE);
  return {
    in: r.in ?? 0,
    out: r.out ?? 0,
    cached: r.cached ?? 0,
    sessions: r.sessions ?? 0,
    sub_agents: r.sub_agents ?? 0,
    calls: r.calls ?? 0,
    messages: r.messages ?? 0,
    ctx: r.ctx ?? 0,
    duration: r.duration ?? 0,
  };
}

const qoderStat = (usage: Usage, key: string): QoderStat => (usage[key] as QoderStat | undefined) ?? {};
const qoderIdeStat = (usage: Usage): QoderIdeStat => (usage.qoder as QoderIdeStat | undefined) ?? {};

/** modelBadge：只在有模型名时出现。 */
function ModelBadge({ model, tint }: { model?: string | null; tint: RGB }) {
  return model ? <LabeledBadge label="model" value={model} tint={tint} /> : null;
}

// ---- Qoder Desktop ----

function QoderIdeCard({ ctx }: { ctx: CardContext }) {
  const q = qoderIdeStat(ctx.usage);
  const r = qoderIdeRange(q, ctx.range);
  const tint = Theme.qoder;
  const total = r.in + r.cached + r.out;
  const items: Metric[] = [metric("terminal", L("模型调用"), String(r.calls)), metric("person.2", L("会话"), String(r.sessions))];
  if (r.sub_agents > 0) items.push(metric("point.3.connected.trianglepath.dotted", L("子agent"), String(r.sub_agents)));
  if (r.messages > 0) items.push(metric("bubble.left.and.bubble.right", L("消息数"), Fmt.human(r.messages)));
  if (r.ctx > 0) items.push(metric("chart.bar.fill", L("缓存命中"), `${r.ctx.toFixed(0)}%`));
  if (r.duration > 0) items.push(metric("clock", L("耗时"), Fmt.duration(r.duration * 1000)));
  if (r.in > 0) items.push(metric("arrow.down", L("输入"), Fmt.human(r.in)));
  if (r.out > 0) items.push(metric("arrow.up", L("输出"), Fmt.human(r.out)));
  if (r.cached > 0) items.push(metric("bolt.fill", L("缓存读"), Fmt.human(r.cached)));
  return (
    <VStack>
      <CardHead title="Qoder Desktop" tint={tint} />
      {r.calls > 0 || total > 0 ? (
        <>
          {total > 0 && <CostHeadline value={Fmt.human(total)} caption={L("%@ 总量", ctx.rangeLabel)} />}
          <MetricGrid top={items} tint={tint} />
          <ModelBadge model={q.model} tint={tint} />
        </>
      ) : (
        <EmptyHint />
      )}
    </VStack>
  );
}

// ---- QoderWork ----

function QoderWorkCard({ ctx }: { ctx: CardContext }) {
  const q = qoderStat(ctx.usage, "qoderwork");
  const r = qoderRange(q, ctx.range);
  const tint = Theme.qoderwork;
  const total = qoderTotal(r);
  const items: Metric[] = [
    metric("terminal", L("任务"), String(r.calls)),
    metric("person.2", L("会话"), String(r.sessions)),
    metric("clock", L("耗时"), Fmt.duration(r.duration)),
  ];
  if (r.in > 0) items.push(metric("arrow.down", L("输入"), Fmt.human(r.in)));
  if (r.out > 0) items.push(metric("arrow.up", L("输出"), Fmt.human(r.out)));
  if (r.sub_agents > 0) items.push(metric("point.3.connected.trianglepath.dotted", L("子agent"), String(r.sub_agents)));
  if (r.turns > 0) items.push(metric("bubble.left.and.bubble.right", L("模型调用"), Fmt.human(r.turns)));
  if (r.ctx > 0) items.push(metric("chart.bar.fill", L("平均深度"), `${r.ctx.toFixed(0)}%`));
  return (
    <VStack>
      <CardHead title="QoderWork" tint={tint} />
      {r.calls > 0 || total > 0 ? (
        <>
          {total > 0 && <CostHeadline value={Fmt.human(total)} caption={L("%@ 总量", ctx.rangeLabel)} />}
          <MetricGrid top={items} tint={tint} />
          <ModelBadge model={q.model} tint={tint} />
        </>
      ) : (
        <EmptyHint />
      )}
    </VStack>
  );
}

// ---- Qoder CLI / Qoder CN ----

interface QoderCliConfig {
  /** usage 里的键（qodercli、qodercli_cn）。 */
  key: string;
  name: string;
  tint: RGB;
}

function QoderCliCard({ ctx, config }: { ctx: CardContext; config: QoderCliConfig }) {
  const q = qoderStat(ctx.usage, config.key);
  const r = qoderRange(q, ctx.range);
  const tint = config.tint;
  const total = qoderTotal(r);
  const exactTokens = r.usage_available && total > 0;
  const extra: Metric[] = [
    metric("terminal", L("模型调用"), String(r.calls)),
    metric("person.2", L("会话"), String(r.sessions)),
    metric("bubble.left.and.bubble.right", L("消息数"), Fmt.human(r.turns)),
    metric("clock", L("活跃"), Fmt.duration(r.duration)),
  ];
  if (r.usage_available) {
    extra.push(metric("arrow.down", L("输入"), Fmt.human(r.in)), metric("arrow.up", L("输出"), Fmt.human(r.out)));
    if (r.cr > 0) extra.push(metric("bolt.fill", L("缓存读"), Fmt.human(r.cr)));
    if (r.cw > 0) extra.push(metric("square.stack.3d.up.fill", L("缓存写"), Fmt.human(r.cw)));
  }
  if (r.tools > 0) extra.push(metric("wrench.and.screwdriver", L("工具调用"), Fmt.human(r.tools)));
  if (r.sub_agents > 0) extra.push(metric("point.3.connected.trianglepath.dotted", L("子agent"), String(r.sub_agents)));
  extra.push(...perfMetrics(r.perf));
  const top = exactTokens && r.credits > 0 ? [metric("circle.hexagongrid.fill", "Credits", Fmt.credits(r.credits))] : [];
  return (
    <VStack>
      <CardHead title={config.name} tint={tint} />
      {r.calls > 0 || total > 0 ? (
        <>
          {exactTokens ? (
            <CostHeadline value={Fmt.human(total)} caption={L("%@ 总量", ctx.rangeLabel)} />
          ) : (
            // 内置路由不把 token 落盘（usage 全是 0），这时 Credits 是唯一的计量
            r.credits > 0 && <CostHeadline value={Fmt.credits(r.credits)} caption={L("%@ Credits", ctx.rangeLabel)} />
          )}
          <MetricGrid top={top} hit={r.hit} extra={extra} tint={tint} />
          {r.models.length > 0 ? (
            <ModelDisclosure rows={tokenModelRows(r.models, { perf: r.perf })} tint={tint} periodLabel={ctx.rangeLabel} />
          ) : (
            <ModelBadge model={q.model} tint={tint} />
          )}
        </>
      ) : (
        <EmptyHint />
      )}
    </VStack>
  );
}

function qoderCliCard(id: string, visibleKey: string, config: QoderCliConfig): CardSpec {
  return {
    id,
    name: config.name,
    visibleKey,
    visibleDefault: true,
    tint: config.tint,
    active: ({ usage, range }) => {
      const r = qoderRange(qoderStat(usage, config.key), range);
      return r.calls > 0 || qoderTotal(r) > 0;
    },
    render: (ctx) => <QoderCliCard ctx={ctx} config={config} />,
  };
}

export const qoderIdeCard: CardSpec = {
  id: "qoder",
  name: "Qoder Desktop",
  visibleKey: "showQoderIde",
  visibleDefault: true,
  tint: Theme.qoder,
  active: ({ usage, range }) => {
    const r = qoderIdeRange(qoderIdeStat(usage), range);
    return r.calls > 0 || r.in + r.cached + r.out > 0;
  },
  render: (ctx) => <QoderIdeCard ctx={ctx} />,
};

export const qoderworkCard: CardSpec = {
  id: "qoderwork",
  name: "QoderWork",
  visibleKey: "showQoderWork",
  visibleDefault: true,
  tint: Theme.qoderwork,
  active: ({ usage, range }) => {
    const r = qoderRange(qoderStat(usage, "qoderwork"), range);
    return r.calls > 0 || qoderTotal(r) > 0;
  },
  render: (ctx) => <QoderWorkCard ctx={ctx} />,
};

export const qodercliCard = qoderCliCard("qodercli", "showQoderCli", { key: "qodercli", name: "Qoder CLI", tint: Theme.qodercli });

export const qodercliCNCard = qoderCliCard("qodercli_cn", "showQoderCliCN", {
  key: "qodercli_cn",
  name: "Qoder CN",
  tint: Theme.qodercliCN,
});
