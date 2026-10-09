// 千问办公额度卡片（PanelView.qwenWorkBlock 及 qwenWorkSegmentRow、qwenWorkSharedBlock、
// qwenWorkDateRow、qwenWorkQuotaStatus、qwenWorkSegmentLabel、qwenWorkUnitLabel）。
import * as Fmt from "../lib/fmt";
import { L } from "../lib/i18n";
import { Icon } from "../ui/Icon";
import { CardHead, CostHeadline, HStack, MiniBar, QuotaRow, Spacer, ThinDivider, VStack } from "../ui/kit";
import { fs, gradient, rgba, T, Theme } from "../ui/theme";
import type { CardContext, CardSpec } from "./spec";

const MONO = "var(--mono)";
const QUOTA_ENABLED_KEY = "qwenWorkQuotaEnabled";

// ---- 数据结构（Model.swift 的 QwenWorkQuota / QwenWorkQuotaSegment / QwenWorkSharedQuota） ----
// Swift 端逐字段 `try?` 解码：类型不对的字段当作没有。这里按同样的口径规整一遍。

/** 单个积分桶。`total == 0` 不代表用完：部分套餐只给绝对余额，没有分母。 */
interface QwenWorkQuotaSegment {
  id: string;
  kind: string;
  total: number | null;
  used: number | null;
  remaining: number | null;
  percentage_used: number | null;
  unit: string | null;
  renews_at: number | null;
  expires_at: number | null;
}

/** 团队共享包：单独展示，从不计入个人积分。 */
interface QwenWorkSharedQuota {
  total: number | null;
  used: number | null;
  remaining: number | null;
  percentage_used: number | null;
  unit: string | null;
  expires_at: number | null;
}

interface QwenWorkQuota {
  available: boolean;
  remaining: number | null;
  remaining_pct: number | null;
  exceeded: boolean;
  is_team: boolean;
  expires_at: number | null;
  plan_expiration: number | null;
  segments: QwenWorkQuotaSegment[];
  shared: QwenWorkSharedQuota | null;
  source: string | null;
  updated: number | null;
  stale: boolean;
}

type Raw = Record<string, unknown>;

const isObject = (v: unknown): v is Raw => typeof v === "object" && v !== null && !Array.isArray(v);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const int = (v: unknown): number | null => (typeof v === "number" && Number.isInteger(v) ? v : null);
const str = (v: unknown): string | null => (typeof v === "string" ? v : null);
const optionalString = (v: unknown) => v == null || typeof v === "string";

function sharedOf(raw: Raw): QwenWorkSharedQuota {
  return {
    total: num(raw.total),
    used: num(raw.used),
    remaining: num(raw.remaining),
    percentage_used: num(raw.percentage_used),
    unit: str(raw.unit),
    expires_at: int(raw.expires_at),
  };
}

function segmentOf(raw: Raw): QwenWorkQuotaSegment {
  return { id: str(raw.id) ?? "", kind: str(raw.kind) ?? "", ...sharedOf(raw), renews_at: int(raw.renews_at) };
}

function qwenWorkQuota(value: unknown): QwenWorkQuota {
  const raw = isObject(value) ? value : {};
  // 数组里任何一项解不出来（不是对象、id/kind 不是字符串），Swift 整个 segments 退回空数组。
  const segments =
    Array.isArray(raw.segments) && raw.segments.every((s) => isObject(s) && optionalString(s.id) && optionalString(s.kind))
      ? (raw.segments as Raw[]).map(segmentOf)
      : [];
  return {
    available: raw.available === true,
    remaining: num(raw.remaining),
    remaining_pct: num(raw.remaining_pct),
    exceeded: raw.exceeded === true,
    is_team: raw.is_team === true,
    expires_at: int(raw.expires_at),
    plan_expiration: int(raw.plan_expiration),
    segments,
    shared: isObject(raw.shared) ? sharedOf(raw.shared) : null,
    source: str(raw.source),
    updated: int(raw.updated),
    stale: raw.stale === true,
  };
}

const hasQuota = (q: QwenWorkQuota) => q.available || q.remaining != null || q.segments.length > 0 || q.shared != null;

const clampPct = (value: number) => Math.max(0, Math.min(100, value));

/** 有分母（total > 0）时才把已用比例换成剩余比例；只有绝对余额时不画进度条。 */
const remainingPctOf = (bucket: { total: number | null; percentage_used: number | null }) =>
  (bucket.total ?? 0) > 0 && bucket.percentage_used != null ? clampPct(100 - bucket.percentage_used) : null;

function segmentLabel(segment: QwenWorkQuotaSegment): string {
  const key = segment.id === "" ? segment.kind : segment.id;
  switch (key.toLowerCase().split("-").join("_")) {
    case "plan":
    case "plan_credits":
      return L("套餐积分");
    case "addon":
    case "add_on":
    case "add_on_credits":
      return L("加购积分");
    case "shared_addon":
    case "shared_add_on":
    case "shared_add_on_credits":
      return L("共享加购积分");
    default:
      return key === "" ? L("积分") : key;
  }
}

function unitLabel(unit: string | null): string {
  if (!unit) return L("积分");
  return ["credit", "credits"].includes(unit.toLowerCase()) ? L("积分") : unit;
}

// ---- 视图 ----

function DateRow({ label, epoch }: { label: string; epoch: number }) {
  return (
    <HStack gap={5} style={{ color: T.tertiary }}>
      <Icon name="calendar" size={fs(8.5)} />
      <span style={{ fontSize: fs(9.5), fontFamily: MONO }}>
        {label} · {Fmt.reset(epoch)}
      </span>
    </HStack>
  );
}

function RemainingText({ remaining, unit }: { remaining: number | null; unit: string | null }) {
  if (remaining == null) return null;
  return (
    <span style={{ fontSize: fs(11), fontWeight: 600, fontFamily: MONO, color: T.primary, whiteSpace: "nowrap", flex: "none" }}>
      {L("剩余 %@ %@", Fmt.credits(remaining), unitLabel(unit))}
    </span>
  );
}

function UsedOfTotal({ used, total }: { used: number | null; total: number | null }) {
  if (total == null || !(total > 0)) return null;
  return (
    <span style={{ fontSize: fs(9), fontFamily: MONO, color: T.tertiary }}>
      {L("已用 %@ / 总量 %@", used != null ? Fmt.credits(used) : "?", Fmt.credits(total))}
    </span>
  );
}

function RemainingBar({ pct }: { pct: number | null }) {
  if (pct == null) return null;
  const low = pct <= 15;
  return (
    <HStack gap={6}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <MiniBar value={pct} tint={gradient(low ? Theme.red : Theme.qwenwork)} />
      </div>
      <span style={{ fontSize: fs(9.5), fontWeight: 600, fontFamily: MONO, color: low ? rgba(Theme.red) : T.secondary }}>
        {pct.toFixed(0)}%
      </span>
    </HStack>
  );
}

function SegmentRow({ segment }: { segment: QwenWorkQuotaSegment }) {
  return (
    <VStack gap={4} style={{ padding: "1px 0" }}>
      <HStack gap={6} align="baseline">
        <span
          style={{ fontSize: fs(11), color: T.secondary, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 }}
        >
          {segmentLabel(segment)}
        </span>
        <Spacer />
        <RemainingText remaining={segment.remaining} unit={segment.unit} />
      </HStack>
      <UsedOfTotal used={segment.used} total={segment.total} />
      <RemainingBar pct={remainingPctOf(segment)} />
      {segment.renews_at != null ? (
        <DateRow label={L("续期")} epoch={segment.renews_at} />
      ) : (
        segment.expires_at != null && <DateRow label={L("到期")} epoch={segment.expires_at} />
      )}
    </VStack>
  );
}

function SharedBlock({ shared }: { shared: QwenWorkSharedQuota }) {
  return (
    <VStack gap={5}>
      <HStack gap={6} align="baseline">
        <span style={{ fontSize: fs(10), fontWeight: 600, color: T.secondary }}>{L("团队共享资源包")}</span>
        <Spacer />
        <RemainingText remaining={shared.remaining} unit={shared.unit} />
      </HStack>
      <span style={{ fontSize: fs(8.5), color: T.tertiary }}>{L("共享包独立展示，不计入上方个人积分")}</span>
      <UsedOfTotal used={shared.used} total={shared.total} />
      <RemainingBar pct={remainingPctOf(shared)} />
      {shared.expires_at != null && <DateRow label={L("共享包到期")} epoch={shared.expires_at} />}
    </VStack>
  );
}

function QuotaStatus({ quota }: { quota: QwenWorkQuota }) {
  const sourceLabel =
    quota.source === "mcp" || quota.source === "local_mcp"
      ? L("本机 QwenWork 接口")
      : quota.source === "cache"
        ? L("本地缓存")
        : L("额度数据");
  const updated = quota.updated != null ? Fmt.reset(quota.updated) : L("更新时间未知");
  return (
    <div title={L("Tokei 仅通过千问办公桌面端的本机 QwenWork 接口读取额度，不读取或保存登录凭据。")}>
      <HStack gap={5} style={{ color: quota.stale ? rgba(Theme.orange, 0.88) : T.tertiary }}>
        <Icon name={quota.stale ? "exclamationmark.triangle.fill" : "clock"} size={fs(9)} />
        <span style={{ fontSize: fs(9.5), fontFamily: MONO }}>
          {quota.stale ? L("缓存可能已过期") : sourceLabel} · {updated}
        </span>
      </HStack>
    </div>
  );
}

function QwenWorkCard({ ctx }: { ctx: CardContext }) {
  const quota = qwenWorkQuota(ctx.usage.qwenwork);
  const tint = Theme.qwenwork;
  const enabled = ctx.pref(QUOTA_ENABLED_KEY, false);
  return (
    <VStack>
      <CardHead title={L("千问办公")} tint={tint} />
      {hasQuota(quota) ? (
        <>
          {quota.exceeded && (
            <HStack gap={6} style={{ color: rgba(Theme.red, 0.92) }}>
              <Icon name="exclamationmark.triangle.fill" size={fs(10)} />
              <span style={{ fontSize: fs(10), fontWeight: 600 }}>{L("官方额度状态：已用尽")}</span>
            </HStack>
          )}
          {quota.remaining != null && (
            <CostHeadline
              value={Fmt.credits(quota.remaining)}
              caption={quota.is_team ? L("团队账号个人可用积分") : L("个人可用积分")}
            />
          )}
          {/* 有明确比例时才画进度条。部分千问办公套餐只返回绝对积分余额。 */}
          {quota.remaining_pct != null && <QuotaRow title={L("综合剩余比例")} pct={clampPct(quota.remaining_pct)} tint={tint} />}
          {quota.expires_at != null && <DateRow label={L("额度有效期")} epoch={quota.expires_at} />}
          {quota.plan_expiration != null && quota.plan_expiration !== quota.expires_at && (
            <DateRow label={L("套餐有效期")} epoch={quota.plan_expiration} />
          )}
          {quota.segments.length > 0 && (
            <>
              <ThinDivider />
              <span style={{ fontSize: fs(10), fontWeight: 600, color: T.secondary }}>{L("个人积分明细")}</span>
              {quota.segments.map((segment, index) => (
                <SegmentRow key={index} segment={segment} />
              ))}
            </>
          )}
          {quota.shared && (
            <>
              <ThinDivider />
              <SharedBlock shared={quota.shared} />
            </>
          )}
          <QuotaStatus quota={quota} />
        </>
      ) : (
        <span style={{ fontSize: fs(10), color: T.tertiary }}>
          {enabled ? L("未读取到额度。请确认千问办公已登录并保持运行。") : L("在设置的「隐私与额度」中开启查询后显示。")}
        </span>
      )}
    </VStack>
  );
}

export const qwenworkCard: CardSpec = {
  id: "qwenwork",
  copyable: () => false,
  name: () => L("千问办公"),
  visibleKey: "showQwenWork",
  visibleDefault: true,
  tint: Theme.qwenwork,
  active: (ctx) => ctx.pref(QUOTA_ENABLED_KEY, false) || hasQuota(qwenWorkQuota(ctx.usage.qwenwork)),
  render: (ctx) => <QwenWorkCard ctx={ctx} />,
};
