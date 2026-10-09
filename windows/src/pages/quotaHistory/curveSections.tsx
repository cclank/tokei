// 额度轨迹下面的几块：摘要、空态、每天用了多少额度、最近额度变化、模型活动标记、长跨度每日消耗
// （Mac 版 QuotaHistoryView 的 quotaCurveSection / dailyTokensSection 及其子视图）。
import { BarChart3, LineChart } from "lucide-react";
import * as Fmt from "../../lib/fmt";
import { L } from "../../lib/i18n";
import type { QuotaModelActivity } from "../../lib/quotaHistory";
import { Card, HStack, Spacer, VStack } from "../../ui/kit";
import { fs, rgba, T, Theme, type RGB } from "../../ui/theme";
import { hhmm, isToday, mmdd, MONO, oneLine, ROUNDED, WidestOf } from "./chartKit";
import { QuotaDailyChart } from "./DailyChart";
import type { QuotaDailyPoint } from "./detail";
import {
  WINDOW_CLAUDE_5H,
  WINDOW_CLAUDE_FABLE,
  WINDOW_CLAUDE_WEEK,
  WINDOW_CODEX_WEEK,
  windowNames,
  type QuotaDailyConsumption,
  type QuotaHistoryProjection,
  type QuotaHistoryTool,
} from "./projection";

export function toolTint(tool: QuotaHistoryTool): RGB {
  return tool === "Claude Code" ? Theme.claude : Theme.codex;
}

/** 每个额度窗口的线色。 */
export function seriesColor(tool: QuotaHistoryTool, window: string): string {
  if (tool === "Claude Code") {
    if (window === WINDOW_CLAUDE_5H) return rgba([1.0, 0.43, 0.28]);
    if (window === WINDOW_CLAUDE_WEEK) return rgba([0.66, 0.55, 1.0]);
    if (window === WINDOW_CLAUDE_FABLE) return rgba([1.0, 0.72, 0.16]);
  } else if (window === WINDOW_CODEX_WEEK) {
    return rgba(Theme.codex);
  }
  return rgba(toolTint(tool));
}

function summaryTitle(window: string): string {
  return window === WINDOW_CLAUDE_5H ? L("5h 剩余") : L("%@剩余", L(window));
}

const percent1 = (value: number) => `${value.toFixed(1)}%`;

function QuotaSummaryValue({ title, value, tint }: { title: string; value: number | undefined; tint: string }) {
  const color = value === undefined ? T.tertiary : value <= 15 ? rgba(Theme.red) : tint;
  return (
    <VStack gap={3} style={{ flex: "none" }}>
      <span style={{ fontSize: fs(9.5), color: T.tertiary, whiteSpace: "nowrap" }}>{title}</span>
      <span style={{ fontSize: fs(15), fontWeight: 700, fontFamily: ROUNDED, color, whiteSpace: "nowrap" }}>
        {value === undefined ? "—" : percent1(value)}
      </span>
    </VStack>
  );
}

export function QuotaSummary({ projection, tool }: { projection: QuotaHistoryProjection; tool: QuotaHistoryTool }) {
  // max(by:) 取第一个最大值；dropEvents 新 → 旧，所以一样大时取最近的那次
  const largest = projection.dropEvents.reduce<(typeof projection.dropEvents)[number] | null>(
    (best, event) => (best === null || event.drop > best.drop ? event : best),
    null,
  );
  return (
    <HStack gap={13}>
      {projection.windowNames.map((window) => (
        <QuotaSummaryValue
          key={window}
          title={summaryTitle(window)}
          value={projection.latestValues.get(window)}
          tint={seriesColor(tool, window)}
        />
      ))}
      <VStack gap={3} style={{ flex: "none" }}>
        <span style={{ fontSize: fs(9.5), color: T.tertiary, whiteSpace: "nowrap" }}>{L("采样点")}</span>
        <span style={{ fontSize: fs(15), fontWeight: 700, fontFamily: ROUNDED, color: T.primary }}>{projection.points.length}</span>
      </VStack>
      <Spacer />
      {largest && (
        <VStack gap={3} style={{ alignItems: "flex-end", flex: "none" }}>
          <span style={{ fontSize: fs(9.5), color: T.tertiary, whiteSpace: "nowrap" }}>{L("最大区间下降")}</span>
          <span style={{ fontSize: fs(12), fontWeight: 600, fontFamily: MONO, color: seriesColor(tool, largest.window), whiteSpace: "nowrap" }}>
            {`-${largest.drop.toFixed(1)}% / ${largest.durationMinutes}min`}
          </span>
        </VStack>
      )}
    </HStack>
  );
}

export function QuotaEmptyState({ tool }: { tool: QuotaHistoryTool }) {
  return (
    <div style={{ height: 210, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8 }}>
      <LineChart size={fs(24)} color={rgba(toolTint(tool), 0.8)} strokeWidth={2} />
      <span style={{ fontSize: fs(12), fontWeight: 600, color: T.secondary }}>{L("正在开始记录额度轨迹")}</span>
      <span style={{ fontSize: fs(10), color: T.tertiary, textAlign: "center" }}>
        {L("Tokei 每 30 秒刷新，曲线按分钟聚合。保持应用运行后，这里会逐步出现数据。")}
      </span>
    </div>
  );
}

/** 每天用掉了周额度的多少个百分点（issue #85）。Codex 看周额度，Claude 看周 · 全部。 */
export function DailyConsumptionSection({ daily, tool }: { daily: QuotaDailyConsumption[]; tool: QuotaHistoryTool }) {
  const names = windowNames(tool);
  const window = tool === "Codex" ? names[0] : names[1];
  const rows = daily.filter((row) => row.window === window).slice(0, 7);
  if (!rows.length) return null;
  const largest = Math.max(Math.max(...rows.map((row) => row.consumed)), 0.1);
  return (
    <VStack gap={8}>
      <HStack gap={6} align="baseline">
        <span style={{ fontSize: fs(12), fontWeight: 700, color: T.primary }}>{L("每天用了多少额度")}</span>
        <span style={{ fontSize: fs(9.5), fontWeight: 600, color: rgba(toolTint(tool)) }}>{L(window)}</span>
      </HStack>
      {rows.map((row) => {
        const value = percent1(row.consumed);
        return (
          <HStack key={row.id} gap={8}>
            <span style={{ fontSize: fs(9.5), fontFamily: MONO, color: T.tertiary, width: 40, flex: "none", whiteSpace: "nowrap" }}>
              {isToday(row.dayStart) ? L("今天") : mmdd(row.dayStart)}
            </span>
            <div style={{ width: 96, height: 7, flex: "none", position: "relative" }}>
              <div
                style={{
                  position: "absolute",
                  left: 0,
                  top: 0,
                  bottom: 0,
                  width: Math.max(2, 96 * (row.consumed / largest)),
                  borderRadius: 3.5,
                  background: seriesColor(tool, row.window),
                  opacity: row.isComplete ? 0.85 : 0.4,
                }}
              />
            </div>
            <span
              style={{
                fontSize: fs(10.5),
                fontWeight: 600,
                fontFamily: MONO,
                color: T.primary,
                width: 64,
                flex: "none",
                textAlign: "right",
                whiteSpace: "nowrap",
              }}
            >
              {row.isComplete ? value : L("约 %@", value)}
            </span>
            {row.refills > 0 && <span style={{ fontSize: fs(9), color: T.tertiary, whiteSpace: "nowrap" }}>{L("回满 ×%@", row.refills)}</span>}
            <Spacer />
          </HStack>
        );
      })}
    </VStack>
  );
}

function ActivityText({ activity }: { activity: QuotaModelActivity[] }) {
  return (
    <span style={{ fontSize: fs(9.5), fontFamily: MONO, color: T.secondary, flex: "0 1 auto", ...oneLine }}>
      {activity.map((item) => `${item.model} +${Fmt.human(item.tokenDelta)}`).join(" · ")}
    </span>
  );
}

export function ChangesSection({ projection, tool }: { projection: QuotaHistoryProjection; tool: QuotaHistoryTool }) {
  const names = windowNames(tool);
  return (
    <VStack gap={8}>
      <span style={{ fontSize: fs(12), fontWeight: 700, color: T.primary }}>{L("最近额度变化")}</span>
      {projection.dropEvents.length === 0 ? (
        <span style={{ fontSize: fs(10), color: T.tertiary }}>{L("当前时间范围内还没有检测到额度下降")}</span>
      ) : (
        projection.dropEvents.slice(0, 8).map((event) => (
          <HStack key={event.id} gap={8}>
            <span style={{ fontSize: fs(9.5), fontFamily: MONO, color: T.tertiary, width: 40, flex: "none" }}>{hhmm(event.timestamp)}</span>
            {/* 列宽按这个工具最长的窗口名来定：译文（Semaine · Fable）比中文长，各行也要对齐 */}
            <WidestOf samples={names.map((name) => L(name))} style={{ minWidth: 42, fontSize: fs(9.5), fontWeight: 600, color: rgba(toolTint(tool)) }}>
              {L(event.window)}
            </WidestOf>
            <span
              style={{
                fontSize: fs(10.5),
                fontWeight: 600,
                fontFamily: MONO,
                color: T.primary,
                width: 54,
                flex: "none",
                textAlign: "right",
                whiteSpace: "nowrap",
              }}
            >
              {`-${percent1(event.drop)}`}
            </span>
            <span style={{ fontSize: fs(9.5), color: T.tertiary, whiteSpace: "nowrap", flex: "none" }}>{L("%@ 分钟", event.durationMinutes)}</span>
            <ActivityText activity={event.activity} />
            <Spacer />
          </HStack>
        ))
      )}
    </VStack>
  );
}

export function ActivitySection({ projection }: { projection: QuotaHistoryProjection }) {
  return (
    <VStack gap={8}>
      <span style={{ fontSize: fs(12), fontWeight: 700, color: T.primary }}>{L("模型活动标记")}</span>
      {projection.activityEvents.length === 0 ? (
        <span style={{ fontSize: fs(10), color: T.tertiary }}>{L("尚未检测到该工具的模型 token 增量")}</span>
      ) : (
        projection.activityEvents.slice(0, 8).map((event) => (
          <HStack key={event.timestamp} gap={8}>
            <span style={{ fontSize: fs(9.5), fontFamily: MONO, color: T.tertiary, width: 40, flex: "none" }}>{hhmm(event.timestamp)}</span>
            <ActivityText activity={event.activity} />
            <Spacer />
          </HStack>
        ))
      )}
    </VStack>
  );
}

function DailyStat({ title, tokens, color }: { title: string; tokens: number; color: string }) {
  return (
    <VStack gap={3} style={{ flex: 1 }}>
      <span style={{ fontSize: fs(9.5), color: T.tertiary, ...oneLine }}>{title}</span>
      <span style={{ fontSize: fs(19), fontWeight: 700, fontFamily: ROUNDED, color, ...oneLine }}>{Fmt.human(tokens)}</span>
      <span style={{ fontSize: fs(9), fontFamily: MONO, color: T.tertiary, ...oneLine }}>{Fmt.grouped(tokens)}</span>
    </VStack>
  );
}

/** 长跨度：账本里的每日真实 token 消耗（已合并所有设备）。 */
export function DailyTokensSection({ points }: { points: QuotaDailyPoint[] }) {
  const claude = points.reduce((sum, point) => sum + point.c, 0);
  const codex = points.reduce((sum, point) => sum + point.x, 0);
  const grok = points.reduce((sum, point) => sum + point.g, 0);
  return (
    <Card tint={Theme.codex}>
      <VStack gap={12}>
        <HStack gap={12} align="flex-start">
          <DailyStat title="Claude Code" tokens={claude} color={rgba(Theme.claude)} />
          <DailyStat title="Codex" tokens={codex} color={rgba(Theme.codex)} />
          <DailyStat title="Grok" tokens={grok} color={rgba(Theme.grok)} />
          <DailyStat title={L("合计")} tokens={claude + codex + grok} color={T.primary} />
        </HStack>
        {points.length === 0 ? (
          <div style={{ height: 210, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8 }}>
            <BarChart3 size={fs(24)} color={rgba(Theme.codex, 0.8)} strokeWidth={2} />
            <span style={{ fontSize: fs(12), fontWeight: 600, color: T.secondary }}>{L("账本里还没有这个区间的用量")}</span>
          </div>
        ) : (
          <QuotaDailyChart points={points} />
        )}
      </VStack>
    </Card>
  );
}
