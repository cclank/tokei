// Provider 额度区块（PanelView.providerQuotaContent / providerQuotaBlock / tokenAndQuotaBlock），
// 以及只用它们的卡片：Cursor、Zed、Sub2API、z.ai、Devin、MiniMax Code。
// Gemini/Antigravity、Grok Bot 的卡片也引用这里的 ProviderQuotaContent。
import * as Fmt from "../lib/fmt";
import { data, L } from "../lib/i18n";
import { getRange, tokenRange, totalTokens, type Ranges, type TokenUsageRange, type TokenUsageStat } from "../lib/types";
import { Icon } from "../ui/Icon";
import {
  CardHead,
  CostHeadline,
  HStack,
  metric,
  MetricGrid,
  perfMetrics,
  QuotaRow,
  Spacer,
  StaleQuotaFootnote,
  ThinDivider,
  VStack,
  type Metric,
} from "../ui/kit";
import { ModelDisclosure, tokenModelRows } from "../ui/models";
import { fs, rgba, T, Theme, type RGB } from "../ui/theme";
import type { CardContext, CardSpec } from "./spec";
import { EMPTY_TOKEN_RANGE, estimatedCostLabel, tokenUsageMetrics, UnpricedModelsNote } from "./tokenUsage";

const MONO = "var(--mono)";

export interface ProviderQuotaWindow {
  id?: string;
  title?: string;
  used_pct?: number | null;
  reset?: number | null;
  window_minutes?: number | null;
  detail?: string | null;
  /** 缺省视为 true。 */
  usage_known?: boolean;
}

export interface ProviderQuotaDetail {
  label?: string;
  value?: string;
  secondary?: string | null;
}

export interface ProviderQuotaStat {
  available?: boolean;
  plan?: string | null;
  account?: string | null;
  windows?: ProviderQuotaWindow[];
  details?: ProviderQuotaDetail[];
  usage?: TokenUsageStat | null;
  source?: string | null;
  updated?: number | null;
  stale?: boolean;
}

export const EMPTY_QUOTA: ProviderQuotaStat = {};

export function ProviderQuotaPill({ text, tint }: { text: string; tint: RGB }) {
  return (
    <span
      style={{
        fontSize: fs(9.5),
        fontWeight: 600,
        fontFamily: MONO,
        color: T.secondary,
        padding: "2px 7px",
        borderRadius: 999,
        background: rgba(tint, 0.16),
        whiteSpace: "nowrap",
      }}
    >
      {text}
    </span>
  );
}

function detailValue(detail: ProviderQuotaDetail): string {
  const label = detail.label ?? "";
  const value = detail.value ?? "";
  // 采集器给的标签是中文原文（显示时才翻译），按原文认。
  if (label.includes("到期") && /^\d+$/.test(value)) return Fmt.reset(Number(value));
  return data(value);
}

/** 套餐 / 账号、各额度窗口、明细与更新时间。 */
export function ProviderQuotaContent({ quota, tint }: { quota: ProviderQuotaStat; tint: RGB }) {
  const windows = quota.windows ?? [];
  const details = (quota.details ?? []).slice(0, 12);
  return (
    <>
      {(quota.plan || quota.account) && (
        <HStack gap={6}>
          {quota.plan && <ProviderQuotaPill text={quota.plan} tint={tint} />}
          {quota.account && (
            <span
              style={{ fontSize: fs(9), fontFamily: MONO, color: T.tertiary, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
            >
              {quota.account}
            </span>
          )}
        </HStack>
      )}
      {windows.map((w, index) => {
        const title = data(w.title || w.id || "");
        if ((w.usage_known ?? true) && w.used_pct != null) {
          return (
            <QuotaRow
              key={w.id || index}
              title={title}
              pct={Math.max(0, Math.min(100, 100 - w.used_pct))}
              detail={w.detail ? data(w.detail) : null}
              reset={w.reset}
              tint={tint}
            />
          );
        }
        return (
          <HStack key={w.id || index} gap={6} align="baseline">
            <span style={{ fontSize: fs(11), color: T.secondary }}>{title}</span>
            <Spacer />
            <span style={{ fontSize: fs(9.5), fontFamily: MONO, color: T.tertiary, textAlign: "right" }}>
              {w.detail ? data(w.detail) : L("额度比例未知")}
            </span>
          </HStack>
        );
      })}
      {details.length > 0 && (
        <>
          <ThinDivider />
          <VStack gap={6}>
            {details.map((detail, index) => (
              <HStack key={index} gap={8} align="baseline">
                <span style={{ fontSize: fs(10), color: T.tertiary }}>{data(detail.label ?? "")}</span>
                <Spacer />
                <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 1 }}>
                  <span style={{ fontSize: fs(10), fontWeight: 600, fontFamily: MONO, color: T.primary }}>{detailValue(detail)}</span>
                  {detail.secondary && (
                    <span style={{ fontSize: fs(8.5), fontFamily: MONO, color: T.tertiary, textAlign: "right" }}>{data(detail.secondary)}</span>
                  )}
                </span>
              </HStack>
            ))}
          </VStack>
        </>
      )}
      {quota.stale ? (
        <StaleQuotaFootnote updated={quota.updated} help={L("当前展示最近一次成功结果；登录态或网络恢复后会自动刷新。")} />
      ) : (
        quota.updated != null && (
          <HStack gap={5} style={{ color: T.tertiary }}>
            <Icon name="clock" size={fs(9)} />
            <span style={{ fontSize: fs(9), fontFamily: MONO }}>{L("额度更新于 %@", Fmt.reset(quota.updated))}</span>
          </HStack>
        )
      )}
    </>
  );
}

/** 账号级用量（Cursor、z.ai、Grok Bot）：单列统计，避免与本地日志重复计算。 */
export function ProviderTokenUsageContent({
  r: raw,
  tint,
  ctx,
  periodLabel,
  showModels = true,
}: {
  r: TokenUsageRange;
  tint: RGB;
  ctx: CardContext;
  periodLabel?: string;
  showModels?: boolean;
}) {
  const r = tokenRange(raw);
  const top: Metric[] = [];
  if (r.cost > 0) top.push(metric("dollarsign.circle", L("API 价"), Fmt.dollars(r.cost)));
  if (r.requests > 0) top.push(metric("arrow.triangle.2.circlepath", L("请求"), Fmt.human(r.requests)));
  const details: Metric[] = [];
  if (r.in + r.out + r.cr + r.cw + r.reason > 0) {
    details.push(metric("arrow.down", L("输入"), Fmt.human(r.in)), metric("arrow.up", L("输出"), Fmt.human(r.out)));
    if (r.cr > 0) details.push(metric("bolt.fill", L("缓存读"), Fmt.human(r.cr)));
    if (r.cw > 0) details.push(metric("square.stack.3d.up.fill", L("缓存写"), Fmt.human(r.cw)));
    if (r.reason > 0) details.push(metric("brain", L("推理"), Fmt.human(r.reason)));
  }
  const label = periodLabel ?? ctx.rangeLabel;
  return (
    <VStack gap={9}>
      <CostHeadline value={Fmt.human(totalTokens(raw))} caption={L("%@ 账号总量", r.coverage ? data(r.coverage) : label)} />
      <span style={{ fontSize: fs(8.5), color: T.tertiary }}>{L("账号级用量 · 单列统计，避免与本地工具日志重复计算")}</span>
      {(top.length > 0 || details.length > 0) && <MetricGrid top={top} hit={r.hit} extra={details} tint={tint} />}
      {showModels && r.models.length > 0 && <ModelDisclosure rows={tokenModelRows(r.models)} tint={tint} periodLabel={label} />}
    </VStack>
  );
}

function SetupHint({ text }: { text: string }) {
  return <span style={{ fontSize: fs(10), color: T.tertiary }}>{text}</span>;
}

function quotaOf(ctx: CardContext, key: string): ProviderQuotaStat {
  return (ctx.usage[key] as ProviderQuotaStat | undefined) ?? EMPTY_QUOTA;
}

function accountUsage(quota: ProviderQuotaStat, range: CardContext["range"]): TokenUsageRange {
  return getRange(quota.usage?.ranges, range, EMPTY_TOKEN_RANGE);
}

interface ProviderQuotaCardConfig {
  id: string;
  key: string;
  name: string;
  visibleKey: string;
  tint: RGB;
  setupHint: () => string;
  /** Cursor、z.ai 有账号级用量：有用量就是标准卡，否则是只显示额度的小卡。 */
  hasAccountUsage?: boolean;
  /** Zed、Sub2API：打开开关就画（没配置时显示设置提示）。 */
  activeWhenVisible?: boolean;
}

function providerQuotaCard(config: ProviderQuotaCardConfig): CardSpec {
  const usageOf = (ctx: CardContext) => (config.hasAccountUsage ? accountUsage(quotaOf(ctx, config.key), ctx.range) : EMPTY_TOKEN_RANGE);
  return {
    id: config.id,
    name: config.name,
    visibleKey: config.visibleKey,
    visibleDefault: false,
    tint: config.tint,
    active: (ctx) => {
      if (config.activeWhenVisible) return true;
      const quota = quotaOf(ctx, config.key);
      const r = usageOf(ctx);
      if (config.id === "cursor") return totalTokens(r) > 0 || (r.requests ?? 0) > 0;
      return Boolean(quota.available) || totalTokens(r) > 0;
    },
    presentation: (ctx) => (totalTokens(usageOf(ctx)) > 0 ? "standard" : "compact"),
    render: (ctx) => {
      const quota = quotaOf(ctx, config.key);
      const r = usageOf(ctx);
      const hasUsage = totalTokens(r) > 0 || (r.requests ?? 0) > 0;
      return (
        <VStack>
          <CardHead title={config.name} tint={config.tint} />
          {hasUsage && <ProviderTokenUsageContent r={r} tint={config.tint} ctx={ctx} />}
          {quota.available ? (
            <>
              {hasUsage && <ThinDivider />}
              <ProviderQuotaContent quota={quota} tint={config.tint} />
            </>
          ) : (
            !hasUsage && <SetupHint text={config.setupHint()} />
          )}
        </VStack>
      );
    },
  };
}

export const cursorCard = providerQuotaCard({
  id: "cursor",
  key: "cursor",
  name: "Cursor",
  visibleKey: "showCursor",
  tint: Theme.cursor,
  hasAccountUsage: true,
  setupHint: () => L("请确认 Cursor.app 已登录；Tokei 会复用其本地登录态读取额度。"),
});

export const zedCard = providerQuotaCard({
  id: "zed",
  key: "zed",
  name: "Zed",
  visibleKey: "showZed",
  tint: Theme.zed,
  activeWhenVisible: true,
  setupHint: () => L("请先在 Zed 中登录 GitHub，再到设置的「Provider 额度」中授权读取登录态。"),
});

export const sub2apiCard = providerQuotaCard({
  id: "sub2api",
  key: "sub2api",
  name: "Sub2API",
  visibleKey: "showSub2API",
  tint: Theme.sub2api,
  activeWhenVisible: true,
  setupHint: () => L("请在设置的「Provider 额度」中保存 Base URL 与 Group API Key。"),
});

export const zaiCard = providerQuotaCard({
  id: "zai",
  key: "zai",
  name: "z.ai / GLM",
  visibleKey: "showZai",
  tint: Theme.zai,
  hasAccountUsage: true,
  setupHint: () => L("请在设置的「Provider 额度」中选择区域并保存 API Key。"),
});

// ---- Devin、MiniMax Code：本地 token 与套餐额度两个来源，任何一半有数据就画那一半 ----

interface TokenAndQuotaStat {
  ranges?: Ranges<TokenUsageRange>;
  quota?: ProviderQuotaStat;
}

function tokenAndQuotaCard(config: {
  id: string;
  key: string;
  name: string;
  visibleKey: string;
  tint: RGB;
  emptyHint: () => string;
}): CardSpec {
  const statOf = (ctx: CardContext) => (ctx.usage[config.key] as TokenAndQuotaStat | undefined) ?? {};
  return {
    id: config.id,
    name: config.name,
    visibleKey: config.visibleKey,
    visibleDefault: true,
    tint: config.tint,
    active: (ctx) => {
      const stat = statOf(ctx);
      return (getRange(stat.ranges, ctx.range, EMPTY_TOKEN_RANGE).sessions ?? 0) > 0 || Boolean(stat.quota?.available);
    },
    render: (ctx) => {
      const stat = statOf(ctx);
      const raw = getRange(stat.ranges, ctx.range, EMPTY_TOKEN_RANGE);
      const r = tokenRange(raw);
      const quota = stat.quota ?? EMPTY_QUOTA;
      const hasUsage = r.sessions > 0;
      return (
        <VStack>
          <CardHead title={config.name} tint={config.tint} sessions={r.sessions} />
          {hasUsage && (
            <>
              <CostHeadline value={Fmt.human(totalTokens(raw))} caption={L("%@ 总量", ctx.rangeLabel)} />
              <MetricGrid
                top={[metric("dollarsign.circle", L("≈成本"), estimatedCostLabel(raw))]}
                hit={r.hit}
                extra={[...tokenUsageMetrics(raw), ...perfMetrics(r.perf)]}
                tint={config.tint}
              />
              <UnpricedModelsNote models={r.models} />
              {r.models.length > 0 && (
                <ModelDisclosure rows={tokenModelRows(r.models, { perf: r.perf })} tint={config.tint} periodLabel={ctx.rangeLabel} />
              )}
            </>
          )}
          {quota.available ? (
            <>
              {hasUsage && <ThinDivider />}
              <ProviderQuotaContent quota={quota} tint={config.tint} />
            </>
          ) : (
            !hasUsage && <SetupHint text={config.emptyHint()} />
          )}
        </VStack>
      );
    },
  };
}

export const devinCard = tokenAndQuotaCard({
  id: "devin",
  key: "devin",
  name: "Devin",
  visibleKey: "showDevin",
  tint: Theme.devin,
  emptyHint: () => L("请打开一次 Devin 桌面端并登录，它会把套餐额度写入本地；") + L("Token 统计来自 Devin CLI 的会话库。"),
});

export const minimaxCard = tokenAndQuotaCard({
  id: "minimax",
  key: "minimax",
  name: "MiniMax Code",
  visibleKey: "showMiniMax",
  tint: Theme.minimax,
  emptyHint: () =>
    L("Token 统计来自 MiniMax Code 桌面端的本地数据库；") + L("在设置 → Provider 额度 填入 Token Plan Key 可显示 5 小时与周额度。"),
});
