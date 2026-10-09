// 额度曲线的数据加工：对应 Mac 版 QuotaHistoryProjection.swift（已提交的版本）。
// 时间一律用 Unix 秒。
import type { QuotaHistoryPoint, QuotaModelActivity } from "../../lib/quotaHistory";

export type QuotaHistoryTool = "Claude Code" | "Codex";

export const QUOTA_HISTORY_TOOLS: QuotaHistoryTool[] = ["Claude Code", "Codex"];

// 数据里的窗口标识（历史记录按它存），显示时再过 L()。
export const WINDOW_CLAUDE_5H = "5 小时"; // l10n-ignore
export const WINDOW_CLAUDE_WEEK = "周 · 全部"; // l10n-ignore
export const WINDOW_CLAUDE_FABLE = "周 · Fable"; // l10n-ignore
export const WINDOW_CODEX_WEEK = "周"; // l10n-ignore

export function windowNames(tool: QuotaHistoryTool): string[] {
  return tool === "Claude Code" ? [WINDOW_CLAUDE_5H, WINDOW_CLAUDE_WEEK, WINDOW_CLAUDE_FABLE] : [WINDOW_CODEX_WEEK];
}

export interface QuotaChartDatum {
  id: string;
  timestamp: number;
  remaining: number;
  window: string;
  activity: QuotaModelActivity[];
}

export interface QuotaDropEvent {
  id: string;
  timestamp: number;
  durationMinutes: number;
  window: string;
  drop: number;
  activity: QuotaModelActivity[];
}

export interface QuotaActivityEvent {
  timestamp: number;
  activity: QuotaModelActivity[];
}

export interface QuotaHoverRow {
  window: string;
  remaining: number;
}

export interface QuotaHoverSample {
  timestamp: number;
  rows: QuotaHoverRow[];
  activity: QuotaModelActivity[];
}

/** 某个本地自然日里，一个额度窗口被用掉了多少个百分点（issue #85）。 */
export interface QuotaDailyConsumption {
  id: string;
  /** 当天零点（本地时区）的 Unix 秒。 */
  dayStart: number;
  window: string;
  /** 当天所有下降量之和。回满、滚动窗口里旧用量过期造成的上升都不抵扣。 */
  consumed: number;
  /** 当天回满的次数（一次上升至少 refillThreshold 个百分点才算）。 */
  refills: number;
  /** 这天的数说得准；采样空档跨过零点、期间又掉了额度时说不清掉在哪天，界面标「约」。 */
  isComplete: boolean;
}

export interface QuotaHistoryProjection {
  points: QuotaHistoryPoint[];
  windowNames: string[];
  lineData: QuotaChartDatum[];
  markerData: QuotaChartDatum[];
  latestValues: Map<string, number>;
  latestDatumIDs: Set<string>;
  dropEvents: QuotaDropEvent[];
  activityEvents: QuotaActivityEvent[];
  hoverSamples: QuotaHoverSample[];
}

const datumID = (timestamp: number, window: string) => `${timestamp}:${window}`;

function toolActivity(point: QuotaHistoryPoint, tool: QuotaHistoryTool): QuotaModelActivity[] {
  return tool === "Claude Code" ? point.claudeActivity : point.codexActivity;
}

function windowActivity(point: QuotaHistoryPoint, window: string, tool: QuotaHistoryTool): QuotaModelActivity[] {
  const all = toolActivity(point, tool);
  if (tool !== "Claude Code" || window !== WINDOW_CLAUDE_FABLE) return all;
  return all.filter((item) => item.model.toLowerCase().includes("fable"));
}

function windowValue(window: string, point: QuotaHistoryPoint, tool: QuotaHistoryTool): number | undefined {
  if (tool === "Claude Code") {
    if (window === WINDOW_CLAUDE_5H) return point.claudeFiveHourRemaining;
    if (window === WINDOW_CLAUDE_WEEK) return point.claudeWeekRemaining;
    if (window === WINDOW_CLAUDE_FABLE) return point.claudeFableWeekRemaining;
    return undefined;
  }
  return window === WINDOW_CODEX_WEEK ? point.codexWeekRemaining : undefined;
}

/** 平台期压缩：保留每次数值变化的前后两点和首尾两点，阶梯线画出来完全一样，点数少很多。 */
function compactFlatSegments(series: QuotaChartDatum[]): QuotaChartDatum[] {
  if (series.length <= 2) return series;
  const compacted: QuotaChartDatum[] = [series[0]];
  for (let i = 1; i < series.length - 1; i++) {
    const current = series[i];
    if (current.remaining !== series[i - 1].remaining || current.remaining !== series[i + 1].remaining) {
      compacted.push(current);
    }
  }
  compacted.push(series[series.length - 1]);
  return compacted;
}

function activitySignature(activity: QuotaModelActivity[]): string | null {
  if (!activity.length) return null;
  const models = activity
    .map((item) => item.model.trim().toLowerCase())
    .filter((model) => model.length > 0)
    .sort();
  return models.length ? models.join("\u001f") : null;
}

/** 一次算好图表要的全部数据，复杂度与点数成线性。 */
export function projectQuotaHistory(points: QuotaHistoryPoint[], tool: QuotaHistoryTool): QuotaHistoryProjection {
  const windows = windowNames(tool);
  const seriesByWindow = new Map<string, QuotaChartDatum[]>(windows.map((window) => [window, []]));
  const latestValues = new Map<string, number>();
  const latestByWindow = new Map<string, QuotaChartDatum>();
  const drops: QuotaDropEvent[] = [];
  const previousByWindow = new Map<string, { point: QuotaHistoryPoint; remaining: number }>();
  const activityEvents: QuotaActivityEvent[] = [];
  const hoverSamples: QuotaHoverSample[] = [];

  for (const point of points) {
    const pointActivity = toolActivity(point, tool);
    if (pointActivity.length) activityEvents.push({ timestamp: point.timestamp, activity: pointActivity });

    const hoverRows: QuotaHoverRow[] = [];
    for (const window of windows) {
      const remaining = windowValue(window, point, tool);
      if (remaining === undefined) continue;
      const activity = windowActivity(point, window, tool);
      const datum: QuotaChartDatum = { id: datumID(point.timestamp, window), timestamp: point.timestamp, remaining, window, activity };
      seriesByWindow.get(window)?.push(datum);
      latestValues.set(window, remaining);
      latestByWindow.set(window, datum);
      hoverRows.push({ window, remaining });

      const previous = previousByWindow.get(window);
      if (previous) {
        const drop = previous.remaining - remaining;
        if (drop >= 0.05) {
          drops.push({
            id: datum.id,
            timestamp: point.timestamp,
            durationMinutes: Math.max(1, Math.trunc((point.timestamp - previous.point.timestamp) / 60)),
            window,
            drop,
            activity,
          });
        }
      }
      previousByWindow.set(window, { point, remaining });
    }
    if (hoverRows.length) hoverSamples.push({ timestamp: point.timestamp, rows: hoverRows, activity: pointActivity });
  }

  const latestDatumIDs = new Set([...latestByWindow.values()].map((datum) => datum.id));
  const markerByID = new Map([...latestByWindow.values()].map((datum) => [datum.id, datum]));
  const lineData: QuotaChartDatum[] = [];
  for (const window of windows) {
    const series = seriesByWindow.get(window) ?? [];
    lineData.push(...compactFlatSegments(series));
    let previousSignature: string | null = null;
    for (const datum of series) {
      const signature = activitySignature(datum.activity);
      if (signature !== null && signature !== previousSignature) markerByID.set(datum.id, datum);
      previousSignature = signature;
    }
  }

  const windowIndex = (window: string) => {
    const index = windows.indexOf(window);
    return index < 0 ? Number.MAX_SAFE_INTEGER : index;
  };
  const markerData = [...markerByID.values()].sort((a, b) =>
    a.timestamp === b.timestamp ? windowIndex(a.window) - windowIndex(b.window) : a.timestamp - b.timestamp,
  );

  return {
    points,
    windowNames: windows,
    lineData,
    markerData,
    latestValues,
    latestDatumIDs,
    dropEvents: drops.sort((a, b) => b.timestamp - a.timestamp),
    activityEvents: activityEvents.reverse(),
    hoverSamples,
  };
}

/** 二分找离 time 最近的采样（一样近时取前一个）。 */
export function nearestHoverSample(samples: QuotaHoverSample[], time: number): QuotaHoverSample | null {
  if (!samples.length) return null;
  let lower = 0;
  let upper = samples.length;
  while (lower < upper) {
    const middle = Math.floor((lower + upper) / 2);
    if (samples[middle].timestamp < time) lower = middle + 1;
    else upper = middle;
  }
  if (lower === 0) return samples[0];
  if (lower === samples.length) return samples[samples.length - 1];
  const before = samples[lower - 1];
  const after = samples[lower];
  return Math.abs(before.timestamp - time) <= Math.abs(after.timestamp - time) ? before : after;
}

/** 本地时区某个时刻所在那天的零点（Unix 秒）。 */
export function localDayStart(timestamp: number): number {
  const d = new Date(timestamp * 1000);
  return Math.floor(new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() / 1000);
}

function nextDayStart(dayStart: number): number {
  const d = new Date(dayStart * 1000);
  return Math.floor(new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1).getTime() / 1000);
}

/**
 * 按本地自然日汇总每个窗口剩余额度的下降量，新 → 旧（issue #85）。
 *
 * 同一窗口相邻两个快照之间：下降记为消耗，记在后一个快照所在的那天；上升不抵扣（Claude 周额度是滚动窗口，
 * 旧用量过期时剩余会慢慢回升，那不是「没用」），一次升够 refillThreshold 才算回满。
 * 只有采样空档跨过零点、期间又确实掉了额度，并且落在离当天开头 / 结尾超过 edgeTolerance 的位置，
 * 才把受影响的那天标「约」；最早那天开头缺采样时也标「约」。
 */
export function dailyConsumption(
  points: QuotaHistoryPoint[],
  tool: QuotaHistoryTool,
  refillThreshold = 10,
  edgeTolerance = 2 * 3600,
): QuotaDailyConsumption[] {
  interface Day {
    consumed: number;
    refills: number;
    first: number;
    last: number;
    uncertain: boolean;
  }
  const windows = windowNames(tool);
  const days = new Map<string, Map<number, Day>>();
  const previous = new Map<string, { value: number; timestamp: number }>();
  const sorted = [...points].sort((a, b) => a.timestamp - b.timestamp);
  for (const point of sorted) {
    const today = localDayStart(point.timestamp);
    for (const window of windows) {
      const remaining = windowValue(window, point, tool);
      if (remaining === undefined) continue;
      let byDay = days.get(window);
      if (!byDay) {
        byDay = new Map();
        days.set(window, byDay);
      }
      let day = byDay.get(today);
      if (!day) {
        day = { consumed: 0, refills: 0, first: Number.MAX_SAFE_INTEGER, last: Number.MIN_SAFE_INTEGER, uncertain: false };
        byDay.set(today, day);
      }
      day.first = Math.min(day.first, point.timestamp);
      day.last = Math.max(day.last, point.timestamp);
      const prior = previous.get(window);
      if (prior) {
        if (remaining < prior.value) {
          day.consumed += prior.value - remaining;
          const priorDay = localDayStart(prior.timestamp);
          if (priorDay !== today) {
            // 这次下降跨过了零点：离当天开头太远，可能有一部分属于前一天
            if (point.timestamp - today > edgeTolerance) day.uncertain = true;
            if (nextDayStart(priorDay) - prior.timestamp > edgeTolerance) {
              const earlier = byDay.get(priorDay);
              if (earlier) earlier.uncertain = true;
            }
          }
        } else if (remaining - prior.value >= refillThreshold) {
          day.refills += 1;
        }
      }
      previous.set(window, { value: remaining, timestamp: point.timestamp });
    }
  }

  const result: QuotaDailyConsumption[] = [];
  for (const [window, byDay] of days) {
    const oldest = Math.min(...byDay.keys());
    for (const [start, day] of byDay) {
      const missingHistory = start === oldest && day.first - start > edgeTolerance;
      result.push({
        id: `${start}:${window}`,
        dayStart: start,
        window,
        consumed: day.consumed,
        refills: day.refills,
        isComplete: !day.uncertain && !missingHistory,
      });
    }
  }
  return result.sort((a, b) =>
    a.dayStart === b.dayStart ? Math.max(0, windows.indexOf(a.window)) - Math.max(0, windows.indexOf(b.window)) : b.dayStart - a.dayStart,
  );
}
