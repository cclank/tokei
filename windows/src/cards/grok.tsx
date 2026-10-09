// Grok 卡片（PanelView.grokBlock 及 grokAuthExpiredNotice、grokQuotaStatus、grokQuotaSourceLabel、
// grokProductLabel、grokProductHelp、grokProductShareRow）与 Grok Bot 卡片（grokBotBlock）。
// Grok Bot 的官方额度授权在 Mac 上靠钥匙串原生助手（重新授权提示 grokBotReauthorizePrompt），
// Windows 没有这个助手：不显示授权相关的界面，JSON 里有的额度和用量照常画。
import * as Fmt from "../lib/fmt";
import { L } from "../lib/i18n";
import { rangeLabel } from "../lib/store";
import { getRange, totalTokens, type PerfStat, type RangeKey, type Ranges, type TokenModelStat, type TokenUsageRange, type Usage } from "../lib/types";
import { Icon } from "../ui/Icon";
import {
  CardHead,
  CostHeadline,
  EmptyHint,
  hasResetSinceReading,
  HStack,
  LabeledBadge,
  metric,
  MetricGrid,
  MiniBar,
  perfMetrics,
  QuotaRow,
  QuotaStateNotice,
  Spacer,
  ThinDivider,
  UsageEmptyHint,
  VStack,
  type Metric,
} from "../ui/kit";
import { ModelDisclosure, tokenModelRows } from "../ui/models";
import { fs, gradient, T, Theme, type RGB } from "../ui/theme";
import { EMPTY_QUOTA, ProviderQuotaContent, ProviderTokenUsageContent, type ProviderQuotaStat } from "./providerQuota";
import { quotaState, recentUsageHint } from "./shared";
import type { CardContext, CardSpec } from "./spec";
import { EMPTY_TOKEN_RANGE } from "./tokenUsage";

const MONO = "var(--mono)";

const Caption = ({ size, text }: { size: number; text: string }) => (
  <span style={{ fontSize: fs(size), color: T.tertiary }}>{text}</span>
);

// ---- Grok ----

/** Model.swift GrokRange（缺省字段在 grokRange() 里补 0）。 */
export interface GrokRange {
  tokens?: number;
  hit?: number;
  in?: number;
  out?: number;
  cr?: number;
  reason?: number;
  cost?: number;
  models?: TokenModelStat[];
  usage_available?: boolean;
  usage_calls?: number;
  usage_sessions?: number;
  sessions?: number;
  turns?: number | null;
  tools?: number | null;
  duration?: number | null;
  ctx_used?: number | null;
  ctx_window?: number | null;
  ctx?: number | null;
  errors?: number | null;
  cancellations?: number | null;
  ttft?: number | null;
  response?: number | null;
  perf?: PerfStat | null;
}

export interface GrokProductUsage {
  name: string;
  pct?: number | null;
}

/** Model.swift GrokStat。 */
export interface GrokStat {
  ranges?: Ranges<GrokRange>;
  model?: string | null;
  /** 本周期已用百分比（0–100）。 */
  pct?: number | null;
  /** 周期重置时间（unix epoch 秒）。 */
  reset?: number | null;
  /** 套餐名，如 SuperGrok。 */
  plan?: string | null;
  /** 分产品已用百分比（GrokBuild / Api 等）。 */
  products?: GrokProductUsage[];
  /** week / month。 */
  window?: string | null;
  /** log / live / cache。 */
  source?: string | null;
  q_updated?: number | null;
  stale?: boolean | null;
  /** 实时开关开着，但 Grok 登录已过期：没有发请求，显示的是本地日志里的额度。 */
  auth_expired?: boolean | null;
}

const EMPTY_GROK_RANGE: GrokRange = {};

function grokRange(raw: GrokRange) {
  return {
    ...raw,
    tokens: raw.tokens ?? 0,
    hit: raw.hit ?? 0,
    in: raw.in ?? 0,
    out: raw.out ?? 0,
    cr: raw.cr ?? 0,
    reason: raw.reason ?? 0,
    cost: raw.cost ?? 0,
    models: raw.models ?? [],
    usage_available: raw.usage_available ?? false,
    usage_calls: raw.usage_calls ?? 0,
    usage_sessions: raw.usage_sessions ?? 0,
    sessions: raw.sessions ?? 0,
  };
}

const grokStat = (usage: Usage): GrokStat => (usage.grok as GrokStat | undefined) ?? {};

const grokRangeAt = (g: GrokStat, key: RangeKey) => grokRange(getRange(g.ranges, key, EMPTY_GROK_RANGE));

function grokQuotaSourceLabel(source?: string | null): string {
  switch (source) {
    case "live":
      return L("Grok 实时接口");
    case "cache":
      return L("Grok 本地缓存");
    default:
      return L("Grok 本地日志");
  }
}

/** 账单 product 字段 → 更可读的名称。 */
function grokProductLabel(raw: string): string {
  switch (raw.toLowerCase()) {
    case "grokbuild":
      return L("Grok Build（本机 CLI）");
    case "api":
      return L("开放 API（api.x.ai）");
    case "grokchat":
      return L("Grok 网页聊天");
    default:
      return raw;
  }
}

/** 分产品占用说明（悬停）。 */
function grokProductHelp(raw: string): string {
  switch (raw.toLowerCase()) {
    case "grokbuild":
      return L("Grok Build / 本机 CLI 编程消耗，占用本周统一额度池的比例。");
    case "api":
      return L("通过 xAI 开放 API（api.x.ai / Console 密钥）调用模型的消耗，与 CLI 共用同一周额度池。");
    case "grokchat":
      return L("grok.com 网页聊天消耗，与 CLI / 开放 API 共用同一周额度池。");
    default:
      return L("该产品在本周统一额度池中的占用比例（与周剩余共用同一重置时间）。");
  }
}

/** 分产品占用：显示该产品在统一周额度里占了多少，不展示独立重置时间。 */
function GrokProductShareRow({ name, usedPct, tint, help }: { name: string; usedPct: number; tint: RGB; help: string }) {
  return (
    <div title={help} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <HStack gap={6}>
        <span
          style={{ fontSize: fs(11), color: T.secondary, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 }}
        >
          {name}
        </span>
        <Spacer />
        <span style={{ fontSize: fs(12), fontWeight: 600, fontFamily: MONO, color: T.primary, whiteSpace: "nowrap" }}>
          {L("占用 %@%%", usedPct.toFixed(0))}
        </span>
      </HStack>
      <MiniBar value={Math.max(0, Math.min(100, 100 - usedPct))} tint={gradient(tint, 0.75)} />
    </div>
  );
}

function GrokQuotaStatus({ stat }: { stat: GrokStat }) {
  const updated = stat.q_updated != null ? Fmt.reset(stat.q_updated) : L("更新时间未知");
  const help =
    stat.source === "live"
      ? L("已开启 Grok 实时额度查询。Grok Build / API 等为同一周额度池内的占用拆分，共享上方重置时间。")
      : L("默认只读 ~/.grok 本地日志，不访问网络");
  return (
    <div title={help}>
      <HStack gap={5} style={{ color: T.tertiary }}>
        <Icon name="clock" size={fs(9)} />
        <span style={{ fontSize: fs(9.5), fontFamily: MONO }}>{L("额度来源 %@ · %@", grokQuotaSourceLabel(stat.source), updated)}</span>
      </HStack>
    </div>
  );
}

/** 实时开关开着但登录过期时，明说现在看的是本地值，以及怎么恢复。 */
function GrokAuthExpiredNotice({ stat }: { stat: GrokStat }) {
  return (
    <QuotaStateNotice
      title={L("Grok 登录已过期")}
      detail={L("实时额度暂停查询，先显示本地日志里的额度。运行一次 grok 续期后自动恢复。")}
      source={grokQuotaSourceLabel(stat.source)}
      updated={stat.q_updated}
      tint={Theme.grok}
      warning
    />
  );
}

function grokMetrics(r: ReturnType<typeof grokRange>): Metric[] {
  const items: Metric[] = [];
  if (r.usage_available) {
    if (r.cost > 0) items.push(metric("dollarsign.circle", L("≈成本"), Fmt.dollars(r.cost)));
    items.push(metric("arrow.down", L("输入"), Fmt.human(r.in)));
    items.push(metric("bolt.fill", L("缓存读"), Fmt.human(r.cr)));
    items.push(metric("arrow.up", L("输出"), Fmt.human(r.out)));
    if (r.reason > 0) items.push(metric("brain", L("推理"), Fmt.human(r.reason)));
    items.push(metric("waveform", L("调用"), String(r.usage_calls)));
  }
  items.push(
    metric("arrow.triangle.2.circlepath", L("轮次"), String(r.turns ?? 0)),
    metric("wrench.and.screwdriver", L("工具"), String(r.tools ?? 0)),
  );
  if (r.duration != null && r.duration > 0) items.push(metric("clock", L("耗时"), Fmt.duration(r.duration * 1000)));
  if (r.ctx != null && r.ctx > 0) items.push(metric("chart.bar.fill", L("窗口"), `${r.ctx.toFixed(0)}%`));
  if (r.ttft != null && r.ttft > 0) {
    items.push(
      metric("timer", L("平均 TTFT"), `${(r.ttft / 1000).toFixed(1)}s`, L("首字延迟：从发出请求到收到第一个 token 的时间")),
    );
  }
  if (r.response != null && r.response > 0) items.push(metric("speedometer", L("平均响应"), `${(r.response / 1000).toFixed(1)}s`));
  // TTFT 已经有 Grok 自己的统计，这里只补输出速度
  items.push(...perfMetrics(r.perf, false));
  if ((r.errors ?? 0) > 0) items.push(metric("exclamationmark.triangle", L("错误"), String(r.errors ?? 0)));
  if ((r.cancellations ?? 0) > 0) items.push(metric("xmark.circle", L("取消"), String(r.cancellations ?? 0)));
  return items;
}

function GrokCard({ ctx }: { ctx: CardContext }) {
  const g = grokStat(ctx.usage);
  const r = grokRangeAt(g, ctx.range);
  const hasUsage = r.sessions > 0 || r.usage_calls > 0;
  const state = quotaState([[g.pct, g.stale]]);
  // 周期结束后，分产品占比说的是上一个周期，不再列出
  const periodEnded = hasResetSinceReading(g.stale === true, g.reset);
  const products = periodEnded ? [] : (g.products ?? []).filter((p) => p.pct != null);
  return (
    <VStack>
      <CardHead title="Grok" tint={Theme.grok} sessions={r.sessions} />
      {hasUsage ? (
        <>
          <CostHeadline
            value={Fmt.human(r.tokens)}
            caption={r.usage_available ? L("%@ 真实用量", ctx.rangeLabel) : L("%@ 上下文快照", ctx.rangeLabel)}
          />
          <MetricGrid hit={r.usage_available ? r.hit : 0} extra={grokMetrics(r)} tint={Theme.grok} />
          {r.usage_available && r.models.length > 0 ? (
            <ModelDisclosure rows={tokenModelRows(r.models, { perf: r.perf })} tint={Theme.grok} periodLabel={ctx.rangeLabel} />
          ) : (
            g.model && <LabeledBadge label="model" value={g.model} tint={Theme.grok} />
          )}
          <Caption
            size={8.5}
            text={
              r.usage_available
                ? r.cost > 0
                  ? L("来自 Grok Build 本地推理日志；成本按 API 价估算，订阅实付不按此。")
                  : L("来自 Grok Build 本地推理日志；当前模型未匹配到公开价格。")
                : L("旧版日志未保存真实用量，当前仅展示上下文与执行指标。")
            }
          />
        </>
      ) : (
        state !== "unavailable" && (
          <UsageEmptyHint
            rangeLabel={ctx.rangeLabel}
            refreshing={ctx.refreshing}
            recent={recentUsageHint(ctx, (key) => {
              const range = grokRangeAt(g, key);
              return range.in + range.out + range.cr + range.reason;
            })}
          />
        )
      )}
      {g.pct != null ? (
        <>
          <ThinDivider />
          {/* 总剩余：同一周额度池。分产品 usagePercent 是该产品在池内的占用占比，不是独立额度剩余。 */}
          <QuotaRow
            title={g.window === "month" ? L("月剩余") : L("周剩余")}
            pct={100 - g.pct}
            reset={g.reset}
            tint={Theme.grok}
            stale={g.stale === true}
          />
          {products.map((product) => (
            <GrokProductShareRow
              key={product.name}
              name={grokProductLabel(product.name)}
              usedPct={product.pct ?? 0}
              tint={Theme.grok}
              help={grokProductHelp(product.name)}
            />
          ))}
          {g.plan && <LabeledBadge label="plan" value={g.plan} tint={Theme.grok} />}
          <GrokQuotaStatus stat={g} />
          {g.auth_expired === true && <GrokAuthExpiredNotice stat={g} />}
        </>
      ) : g.auth_expired === true ? (
        <>
          {hasUsage && <ThinDivider />}
          <GrokAuthExpiredNotice stat={g} />
        </>
      ) : (
        hasUsage && (
          <>
            <ThinDivider />
            <QuotaStateNotice
              title={L("暂未获取到额度数据")}
              detail={L("用量统计不受影响；检测到订阅周期后会自动展示。")}
              source={grokQuotaSourceLabel(g.source)}
              updated={g.q_updated}
              tint={Theme.grok}
            />
          </>
        )
      )}
    </VStack>
  );
}

export const grokCard: CardSpec = {
  id: "grok",
  name: "Grok",
  visibleKey: "showGrok",
  visibleDefault: true,
  tint: Theme.grok,
  active: ({ usage, range }) => {
    const g = grokStat(usage);
    const r = grokRangeAt(g, range);
    return r.sessions > 0 || r.usage_calls > 0 || g.pct != null;
  },
  render: (ctx) => <GrokCard ctx={ctx} />,
};

// ---- Grok Bot ----

/** Grok Bot 的本地活动，结构是 Model.swift 的 QoderRange；这里只取卡片用到的字段。 */
export interface GrokBotActivityRange {
  sessions?: number;
  calls?: number;
  turns?: number;
  tools?: number;
  /** 秒 */
  duration?: number;
}

/** Model.swift GrokBotStat：本地活动 ranges + 官方额度 / 账号级用量 quota。 */
export interface GrokBotStat {
  ranges?: Ranges<GrokBotActivityRange>;
  quota?: ProviderQuotaStat;
}

const EMPTY_ACTIVITY: GrokBotActivityRange = {};

function activity(raw: GrokBotActivityRange) {
  return {
    sessions: raw.sessions ?? 0,
    calls: raw.calls ?? 0,
    turns: raw.turns ?? 0,
    tools: raw.tools ?? 0,
    duration: raw.duration ?? 0,
  };
}

type GrokBotActivity = ReturnType<typeof activity>;

interface GrokBotDisplay {
  key: RangeKey;
  range: GrokBotActivity;
  usage: TokenUsageRange;
}

const grokBotStat = (usage: Usage): GrokBotStat => (usage.grok_bot as GrokBotStat | undefined) ?? {};

const FALLBACK_ORDER: RangeKey[] = ["today", "yesterday", "week", "last_week", "month", "year", "all"];

/** 选中的区间没有活动也没有用量时，改显示最近一个有数据的区间（toolCards 里的 grokBotDisplay）。 */
function grokBotDisplay(usage: Usage, sel: RangeKey): GrokBotDisplay {
  const stat = grokBotStat(usage);
  const at = (key: RangeKey): GrokBotDisplay => ({
    key,
    range: activity(getRange(stat.ranges, key, EMPTY_ACTIVITY)),
    usage: getRange(stat.quota?.usage?.ranges, key, EMPTY_TOKEN_RANGE),
  });
  const hasData = (d: GrokBotDisplay) =>
    d.range.sessions > 0 || d.range.calls > 0 || d.range.turns > 0 || totalTokens(d.usage) > 0 || (d.usage.requests ?? 0) > 0;
  const selected = at(sel);
  if (hasData(selected)) return selected;
  for (const key of FALLBACK_ORDER) {
    if (key === sel) continue;
    const candidate = at(key);
    if (hasData(candidate)) return candidate;
  }
  return selected;
}

function GrokBotCard({ ctx }: { ctx: CardContext }) {
  const stat = grokBotStat(ctx.usage);
  const quota = stat.quota ?? EMPTY_QUOTA;
  const display = grokBotDisplay(ctx.usage, ctx.range);
  const r = display.range;
  const usage = display.usage;
  const hasActivity = r.sessions > 0 || r.calls > 0 || r.turns > 0;
  const hasUsage = totalTokens(usage) > 0 || (usage.requests ?? 0) > 0;
  const quotaEnabled = ctx.pref("grokBotQuotaEnabled", false);
  const displayedLabel = rangeLabel(display.key);
  const fallbackNote =
    display.key !== ctx.range ? <Caption size={9.5} text={L("%@暂无活动，显示%@最近记录", ctx.rangeLabel, displayedLabel)} /> : null;
  const activityMetrics: Metric[] = [
    metric("bubble.left", L("你的消息"), Fmt.human(r.turns)),
    metric("sparkles", L("响应"), Fmt.human(r.calls)),
  ];
  if (r.tools > 0) activityMetrics.push(metric("wrench.and.screwdriver", L("工具调用"), Fmt.human(r.tools)));
  if (r.duration > 0) activityMetrics.push(metric("clock", L("活跃"), Fmt.duration(r.duration * 1000)));
  return (
    <VStack>
      <CardHead title="Grok Bot" tint={Theme.grokBot} sessions={r.sessions} />
      {hasUsage ? (
        <>
          {fallbackNote}
          <ProviderTokenUsageContent r={usage} tint={Theme.grokBot} ctx={ctx} periodLabel={displayedLabel} />
          {hasActivity && <Caption size={8.5} text={L("本地记录 · %@ 条消息 · %@ 次响应", r.turns, r.calls)} />}
        </>
      ) : hasActivity ? (
        <>
          {fallbackNote}
          <CostHeadline value={Fmt.human(r.calls > 0 ? r.calls : r.turns)} caption={L("%@ 响应", displayedLabel)} />
          <MetricGrid top={activityMetrics} tint={Theme.grokBot} />
          {/* Mac 版这里还有一行「本地活动 · 授权后显示官方 Token、模型和成本」：授权靠 macOS 钥匙串助手，Windows 上没有，不显示。 */}
        </>
      ) : (
        !quota.available && <EmptyHint />
      )}
      {quota.available ? (
        <>
          {(hasActivity || hasUsage) && <ThinDivider />}
          <ProviderQuotaContent quota={quota} tint={Theme.grokBot} />
        </>
      ) : (
        quotaEnabled && <Caption size={9} text={L("官方数据暂时不可用，Tokei 将自动重试")} />
      )}
      {/* Mac 版的 grokBotReauthorizePrompt（授权助手更新后重新授权）依赖 macOS 钥匙串助手，Windows 不显示。 */}
    </VStack>
  );
}

export const grokBotCard: CardSpec = {
  id: "grok-bot",
  // 只有当前页签真有本地活动时才能复制（Mac：hasActivity && displayedRange == sel）。
  copyable: ({ usage, range }) => {
    const d = grokBotDisplay(usage, range);
    return d.key === range && (d.range.sessions > 0 || d.range.calls > 0 || d.range.turns > 0);
  },
  name: "Grok Bot",
  visibleKey: "showGrokBot",
  visibleDefault: true,
  tint: Theme.grokBot,
  active: ({ usage, range }) => {
    const d = grokBotDisplay(usage, range);
    return (
      d.range.sessions > 0 ||
      d.range.calls > 0 ||
      totalTokens(d.usage) > 0 ||
      (d.usage.requests ?? 0) > 0 ||
      Boolean(grokBotStat(usage).quota?.available)
    );
  },
  presentation: ({ usage, range }) => {
    const d = grokBotDisplay(usage, range);
    return d.range.sessions === 0 &&
      d.range.calls === 0 &&
      d.range.turns === 0 &&
      totalTokens(d.usage) === 0 &&
      (d.usage.requests ?? 0) === 0 &&
      Boolean(grokBotStat(usage).quota?.available)
      ? "compact"
      : "standard";
  },
  render: (ctx) => <GrokBotCard ctx={ctx} />,
};
