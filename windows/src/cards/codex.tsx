// Codex 卡片（PanelView.codexBlock、codexResetCardsRow、codexReserveBlock）。
import { useState } from "react";
import * as Fmt from "../lib/fmt";
import { L } from "../lib/i18n";
import { getRange, type CodexRange, type CodexResetCards } from "../lib/types";
import { Icon } from "../ui/Icon";
import {
  CardHead,
  CostHeadline,
  HStack,
  LabeledBadge,
  metric,
  MetricGrid,
  perfMetrics,
  QuotaRow,
  QuotaStateNotice,
  Spacer,
  StaleQuotaFootnote,
  ThinDivider,
  UsageEmptyHint,
  VStack,
  type Metric,
} from "../ui/kit";
import { ModelDisclosure, tokenModelRows } from "../ui/models";
import { fill, fs, rgba, T, Theme } from "../ui/theme";
import { recentUsageHint } from "./shared";
import type { CardContext, CardSpec } from "./spec";

export const EMPTY_CODEX_RANGE: CodexRange = { hit: 0, in: 0, cached: 0, out: 0, reason: 0, cost: 0, sessions: 0, models: [] };

const MONO = "var(--mono)";

function ResetCardsRow({ cards }: { cards: CodexResetCards }) {
  const [open, setOpen] = useState(false);
  const expirations = [...cards.expires].sort((a, b) => a - b);
  const nearest = expirations[0];
  return (
    <>
      <button
        className="plain"
        onClick={() => setOpen((v) => !v)}
        title={nearest != null ? L("最近一张 %@ 后到期", Fmt.remaining(nearest)) : L("查看重置卡到期时间")}
        style={{ display: "flex", alignItems: "center", gap: 6, width: "100%" }}
      >
        <Icon name="arrow.clockwise.circle.fill" size={fs(11)} color={rgba(Theme.codex)} />
        <span style={{ fontSize: fs(11), color: T.secondary }}>{L("重置卡")}</span>
        <span style={{ fontSize: fs(10), fontWeight: 600, fontFamily: MONO, color: T.primary }}>{L("%@ 张", cards.count)}</span>
        <Spacer />
        {nearest != null && (
          <span style={{ fontSize: fs(9.5), fontFamily: MONO, color: T.tertiary, whiteSpace: "nowrap" }}>
            {L("%@ · %@后", Fmt.localTime(nearest), Fmt.remaining(nearest))}
          </span>
        )}
        <Icon name={open ? "chevron.down" : "chevron.right"} size={fs(9)} color={T.tertiary} strokeWidth={3} />
      </button>
      {open && (
        <div style={{ padding: 9, borderRadius: 7, background: fill(0.05), display: "flex", flexDirection: "column", gap: 7 }}>
          <HStack>
            <span style={{ fontSize: fs(9.5), fontWeight: 500, color: T.tertiary }}>{L("到期时间")}</span>
            <Spacer />
            <span style={{ fontSize: fs(9), fontFamily: MONO, color: T.tertiary }}>{Fmt.localTimeZoneCaption()}</span>
          </HStack>
          {expirations.map((expiry, index) => (
            <HStack key={index} gap={7}>
              <span
                style={{
                  width: 16,
                  height: 16,
                  borderRadius: 8,
                  display: "grid",
                  placeItems: "center",
                  fontSize: fs(9),
                  fontWeight: 600,
                  fontFamily: MONO,
                  color: rgba(Theme.codex),
                  background: rgba(Theme.codex, 0.14),
                }}
              >
                {index + 1}
              </span>
              <span style={{ fontSize: fs(10.5), fontWeight: 500, color: T.secondary }}>{L("完整重置")}</span>
              <Spacer />
              <span style={{ fontSize: fs(9.5), fontFamily: MONO, color: T.primary, whiteSpace: "nowrap" }}>
                {L("%@ · %@后", Fmt.localTime(expiry), Fmt.remaining(expiry))}
              </span>
            </HStack>
          ))}
        </div>
      )}
    </>
  );
}

function CodexCard({ ctx }: { ctx: CardContext }) {
  const x = ctx.usage.codex;
  const r = getRange(x.ranges, ctx.range, EMPTY_CODEX_RANGE);
  const sessions = r.sessions ?? 0;
  const hasQuota = x.p5 != null || x.pw != null || x.reserve_quota != null || (x.reset_cards?.count ?? 0) > 0;
  const extra: Metric[] = [
    metric("arrow.down", L("输入"), Fmt.human(r.in)),
    metric("bolt.fill", L("缓存读"), Fmt.human(r.cached)),
    metric("arrow.up", L("输出"), Fmt.human(r.out)),
  ];
  if (r.reason > 0) extra.push(metric("brain", L("推理"), Fmt.human(r.reason)));
  extra.push(...perfMetrics(r.perf));
  const reserve = x.reserve_ranges ? getRange(x.reserve_ranges, ctx.range, EMPTY_CODEX_RANGE) : null;
  const reserveQuota = x.reserve_quota;
  return (
    <VStack>
      <CardHead title="Codex" tint={Theme.codex} sessions={sessions} />
      {sessions > 0 ? (
        <>
          <CostHeadline value={Fmt.human(r.in + r.cached + r.out)} caption={L("%@ 总量", ctx.rangeLabel)} />
          <MetricGrid top={[metric("dollarsign.circle", L("≈成本"), Fmt.dollars(r.cost))]} hit={r.hit} extra={extra} tint={Theme.codex} />
          {(r.models?.length ?? 0) > 0 && (
            <ModelDisclosure
              rows={tokenModelRows(r.models ?? [], { reasonIncludedInOutput: true, perf: r.perf })}
              tint={Theme.codex}
              periodLabel={ctx.rangeLabel}
            />
          )}
        </>
      ) : (
        hasQuota && (
          <UsageEmptyHint
            rangeLabel={ctx.rangeLabel}
            refreshing={ctx.refreshing}
            recent={recentUsageHint(ctx, (key) => {
              const range = getRange(x.ranges, key, EMPTY_CODEX_RANGE);
              return range.in + range.out + range.reason;
            })}
          />
        )
      )}
      {hasQuota && <ThinDivider />}
      {x.p5 != null && <QuotaRow title={L("5h 剩余")} pct={100 - x.p5} reset={x.r5} tint={Theme.codex} stale={x.p5_stale === true} />}
      {x.pw != null && <QuotaRow title={L("周剩余")} pct={100 - x.pw} reset={x.rw} tint={Theme.codex} stale={x.pw_stale === true} />}
      {reserveQuota?.used_percent != null && (
        <QuotaRow
          title={L("Reserve 剩余")}
          pct={100 - reserveQuota.used_percent}
          detail={L("常规额度外")}
          reset={reserveQuota.resets_at}
          tint={Theme.codex}
          stale={reserveQuota.stale === true}
        />
      )}
      {reserve && (reserve.sessions ?? 0) > 0 && (
        <ModelDisclosure
          rows={tokenModelRows(reserve.models ?? [], { reasonIncludedInOutput: true })}
          tint={Theme.codex}
          periodLabel={ctx.rangeLabel}
        />
      )}
      {(x.p5_stale === true || x.pw_stale === true || reserveQuota?.stale === true) && (
        <StaleQuotaFootnote
          updated={x.q_updated}
          help={L("窗口重置后本机又用过 Codex，旧读数不再准确；等下一条额度记录更新。")}
        />
      )}
      {x.reset_cards && x.reset_cards.count > 0 && <ResetCardsRow cards={x.reset_cards} />}
      {x.plan && <LabeledBadge label="plan" value={x.plan} tint={Theme.codex} />}
      {sessions > 0 && !hasQuota && (
        <>
          <ThinDivider />
          <QuotaStateNotice
            title={L("暂未获取到额度数据")}
            detail={L("用量统计不受影响；检测到订阅周期后会自动展示。")}
            source={L("Codex 本地状态")}
            updated={null}
            tint={Theme.codex}
          />
        </>
      )}
    </VStack>
  );
}

export const codexCard: CardSpec = {
  id: "codex",
  name: "Codex",
  visibleKey: "showCodex",
  visibleDefault: true,
  tint: Theme.codex,
  active: ({ usage, range }) => {
    const x = usage.codex;
    return (
      (getRange(x.ranges, range, EMPTY_CODEX_RANGE).sessions ?? 0) > 0 ||
      x.p5 != null ||
      x.pw != null ||
      (x.reset_cards?.count ?? 0) > 0
    );
  },
  render: (ctx) => <CodexCard ctx={ctx} />,
};
