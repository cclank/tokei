// 额度历史：对应 Mac 版 QuotaHistoryStore.swift 与 main.swift 的 recordQuotaHistory。
// 每次刷新成功后记一笔「这一分钟的剩余额度 + 各模型今日 token 的增量」，存在 ~/.tokei/quota_history.json。
// 文件格式与 Mac 版逐字段一致（version 1，键名同 Swift 属性名，可选值缺省就不写），两边拷来拷去都能直接读。
import { useEffect, useSyncExternalStore } from "react";
import { readTokeiFile, writeTokeiFile } from "./native";
import type { Usage } from "./types";

export interface QuotaModelActivity {
  model: string;
  tokenDelta: number;
}

export interface QuotaHistoryPoint {
  /** 整分钟的 Unix 秒。 */
  timestamp: number;
  claudeFiveHourRemaining?: number;
  claudeWeekRemaining?: number;
  claudeFableWeekRemaining?: number;
  codexWeekRemaining?: number;
  claudeActivity: QuotaModelActivity[];
  codexActivity: QuotaModelActivity[];
}

export interface QuotaCapture {
  claudeFiveHourRemaining?: number;
  claudeWeekRemaining?: number;
  claudeFableWeekRemaining?: number;
  codexWeekRemaining?: number;
  claudeModelTotals: Map<string, number>;
  codexModelTotals: Map<string, number>;
}

interface QuotaHistoryState {
  version: number;
  points: QuotaHistoryPoint[];
  lastClaudeModelTotals: Map<string, number>;
  lastCodexModelTotals: Map<string, number>;
  hasClaudeBaseline: boolean;
  hasCodexBaseline: boolean;
  claudeBaselineDay?: number;
  codexBaselineDay?: number;
}

const FILE_NAME = "quota_history.json";
/** 与 Mac 版默认一样只留 7 天（retentionHours = 24 * 7，下限 24 小时）。 */
const RETENTION_SECONDS = Math.max(24, 24 * 7) * 60 * 60;
/** Claude 今日模型列表里的「合成」行不是真实模型，Mac 版同样跳过。 */
const SYNTHETIC_MODEL = "合成"; // l10n-ignore

// ---------- 读写文件 ----------

const emptyState = (): QuotaHistoryState => ({
  version: 1,
  points: [],
  lastClaudeModelTotals: new Map(),
  lastCodexModelTotals: new Map(),
  hasClaudeBaseline: false,
  hasCodexBaseline: false,
});

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

function finite(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function integer(value: unknown): number | undefined {
  const n = finite(value);
  return n === undefined ? undefined : Math.trunc(n);
}

function decodeActivity(value: unknown): QuotaModelActivity[] {
  if (!Array.isArray(value)) return [];
  const result: QuotaModelActivity[] = [];
  for (const item of value) {
    if (!isRecord(item) || typeof item.model !== "string") continue;
    const delta = integer(item.tokenDelta);
    if (delta === undefined) continue;
    result.push({ model: item.model, tokenDelta: delta });
  }
  return result;
}

function decodeTotals(value: unknown): Map<string, number> {
  const totals = new Map<string, number>();
  if (!isRecord(value)) return totals;
  for (const [model, total] of Object.entries(value)) {
    const n = integer(total);
    if (n !== undefined) totals.set(model, n);
  }
  return totals;
}

function decodePoint(value: unknown): QuotaHistoryPoint | null {
  if (!isRecord(value)) return null;
  const timestamp = integer(value.timestamp);
  if (timestamp === undefined) return null;
  return {
    timestamp,
    claudeFiveHourRemaining: finite(value.claudeFiveHourRemaining),
    claudeWeekRemaining: finite(value.claudeWeekRemaining),
    claudeFableWeekRemaining: finite(value.claudeFableWeekRemaining),
    codexWeekRemaining: finite(value.codexWeekRemaining),
    claudeActivity: decodeActivity(value.claudeActivity),
    codexActivity: decodeActivity(value.codexActivity),
  };
}

/** 解析失败或版本不认识时从空记录开始（Mac 版 loadState 同样处理）。 */
function decodeState(text: string | null): QuotaHistoryState {
  if (!text) return emptyState();
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch (err) {
    console.error("Tokei quota history load failed:", err);
    return emptyState();
  }
  if (!isRecord(raw) || raw.version !== 1) {
    console.error("Tokei quota history version is unsupported:", isRecord(raw) ? raw.version : raw);
    return emptyState();
  }
  const points = (Array.isArray(raw.points) ? raw.points : [])
    .map(decodePoint)
    .filter((point): point is QuotaHistoryPoint => point !== null)
    .sort((a, b) => a.timestamp - b.timestamp);
  return {
    version: 1,
    points,
    lastClaudeModelTotals: decodeTotals(raw.lastClaudeModelTotals),
    lastCodexModelTotals: decodeTotals(raw.lastCodexModelTotals),
    hasClaudeBaseline: raw.hasClaudeBaseline === true,
    hasCodexBaseline: raw.hasCodexBaseline === true,
    claudeBaselineDay: integer(raw.claudeBaselineDay),
    codexBaselineDay: integer(raw.codexBaselineDay),
  };
}

const encodeActivity = (list: QuotaModelActivity[]) =>
  list.map((item) => ({ model: item.model, tokenDelta: Math.trunc(item.tokenDelta) }));

const encodeTotals = (totals: Map<string, number>) =>
  Object.fromEntries([...totals].map(([model, total]) => [model, Math.trunc(total)]));

/**
 * 写成 Swift JSONEncoder 能解的样子：非可选字段（含空数组、空字典、false）一律写出，
 * 可选值没有就整个键不写；整数字段保证是整数（Swift 的 Int 不收 1.5）。
 */
function encodeState(state: QuotaHistoryState): string {
  return JSON.stringify({
    version: 1,
    points: state.points.map((point) => ({
      timestamp: Math.trunc(point.timestamp),
      claudeFiveHourRemaining: point.claudeFiveHourRemaining,
      claudeWeekRemaining: point.claudeWeekRemaining,
      claudeFableWeekRemaining: point.claudeFableWeekRemaining,
      codexWeekRemaining: point.codexWeekRemaining,
      claudeActivity: encodeActivity(point.claudeActivity),
      codexActivity: encodeActivity(point.codexActivity),
    })),
    lastClaudeModelTotals: encodeTotals(state.lastClaudeModelTotals),
    lastCodexModelTotals: encodeTotals(state.lastCodexModelTotals),
    hasClaudeBaseline: state.hasClaudeBaseline,
    hasCodexBaseline: state.hasCodexBaseline,
    claudeBaselineDay: state.claudeBaselineDay,
    codexBaselineDay: state.codexBaselineDay,
  });
}

// ---------- 内存里的单例（QuotaHistoryStore.shared） ----------

let state: QuotaHistoryState | null = null;
let loading: Promise<QuotaHistoryState> | null = null;
let published: QuotaHistoryPoint[] = [];
let queue: Promise<void> = Promise.resolve();
const listeners = new Set<() => void>();

function publish() {
  published = state ? [...state.points] : [];
  listeners.forEach((listener) => listener());
}

/**
 * 读一次文件，之后只用内存里的副本（Mac 版也只在启动时读）。
 * 读文件本身出错（不是「没有这个文件」）时不当成空记录，免得下一次保存把 7 天的历史覆盖掉；下回再试。
 */
function ensureLoaded(): Promise<QuotaHistoryState> {
  if (state) return Promise.resolve(state);
  if (!loading) {
    loading = readTokeiFile(FILE_NAME)
      .then((text) => {
        state = decodeState(text);
        publish();
        return state;
      })
      .catch((err) => {
        loading = null;
        throw err;
      });
  }
  return loading;
}

function save(current: QuotaHistoryState): Promise<void> {
  return writeTokeiFile(FILE_NAME, encodeState(current)).catch((err) => {
    console.error("Tokei quota history write failed:", err);
  });
}

/** 本地时区当天零点的 Unix 秒（Calendar.current.startOfDay）。 */
function startOfDay(date: Date): number {
  return Math.floor(new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime() / 1000);
}

function normalized(value: number | undefined): number | undefined {
  if (value === undefined || !Number.isFinite(value)) return undefined;
  return Math.min(100, Math.max(0, value));
}

function byDeltaThenModel(a: QuotaModelActivity, b: QuotaModelActivity): number {
  if (a.tokenDelta === b.tokenDelta) return a.model < b.model ? -1 : a.model > b.model ? 1 : 0;
  return b.tokenDelta - a.tokenDelta;
}

function activity(current: Map<string, number>, previous: Map<string, number>, hasBaseline: boolean): QuotaModelActivity[] {
  if (!hasBaseline) return [];
  const result: QuotaModelActivity[] = [];
  for (const [model, total] of current) {
    const delta = total - (previous.get(model) ?? 0);
    if (delta > 0) result.push({ model, tokenDelta: delta });
  }
  return result.sort(byDeltaThenModel);
}

interface PreparedBaseline {
  previous: Map<string, number>;
  hasBaseline: boolean;
  dayChanged: boolean;
}

/** 跨了自然日：今日 token 统计清零了，旧基线作废。 */
function prepareBaseline(previous: Map<string, number>, hasBaseline: boolean, baselineDay: number | undefined, currentDay: number): PreparedBaseline {
  const dayChanged = baselineDay !== undefined && baselineDay !== currentDay;
  return dayChanged ? { previous: new Map(), hasBaseline: false, dayChanged: true } : { previous, hasBaseline, dayChanged: false };
}

function sameTotals(a: Map<string, number>, b: Map<string, number>): boolean {
  if (a.size !== b.size) return false;
  for (const [model, total] of a) if (b.get(model) !== total) return false;
  return true;
}

function updatedBaseline(current: Map<string, number>, prepared: PreparedBaseline, existingDay: number | undefined, currentDay: number) {
  // 刷新整体成功时，某个扫描器失败也可能给出空的今日区间。同一天里已有非空基线就保留，
  // 免得恢复后把一整天的用量都算到某一分钟头上。
  const shouldReplace = prepared.dayChanged || !prepared.hasBaseline || current.size > 0 || prepared.previous.size === 0;
  if (!shouldReplace) {
    return { totals: prepared.previous, hasBaseline: prepared.hasBaseline, day: existingDay, changed: false };
  }
  const changed = !sameTotals(prepared.previous, current) || !prepared.hasBaseline || existingDay !== currentDay;
  return { totals: current, hasBaseline: true, day: currentDay as number | undefined, changed };
}

function mergeActivity(existing: QuotaModelActivity[], incoming: QuotaModelActivity[]): QuotaModelActivity[] {
  const totals = new Map(existing.map((item) => [item.model, item.tokenDelta]));
  for (const item of incoming) totals.set(item.model, (totals.get(item.model) ?? 0) + item.tokenDelta);
  return [...totals].map(([model, tokenDelta]) => ({ model, tokenDelta })).sort(byDeltaThenModel);
}

function merge(existing: QuotaHistoryPoint, incoming: QuotaHistoryPoint): QuotaHistoryPoint {
  return {
    timestamp: existing.timestamp,
    claudeFiveHourRemaining: incoming.claudeFiveHourRemaining ?? existing.claudeFiveHourRemaining,
    claudeWeekRemaining: incoming.claudeWeekRemaining ?? existing.claudeWeekRemaining,
    claudeFableWeekRemaining: incoming.claudeFableWeekRemaining ?? existing.claudeFableWeekRemaining,
    codexWeekRemaining: incoming.codexWeekRemaining ?? existing.codexWeekRemaining,
    claudeActivity: mergeActivity(existing.claudeActivity, incoming.claudeActivity),
    codexActivity: mergeActivity(existing.codexActivity, incoming.codexActivity),
  };
}

function sameActivity(a: QuotaModelActivity[], b: QuotaModelActivity[]): boolean {
  return a.length === b.length && a.every((item, i) => item.model === b[i].model && item.tokenDelta === b[i].tokenDelta);
}

function samePoint(a: QuotaHistoryPoint, b: QuotaHistoryPoint): boolean {
  return (
    a.timestamp === b.timestamp &&
    a.claudeFiveHourRemaining === b.claudeFiveHourRemaining &&
    a.claudeWeekRemaining === b.claudeWeekRemaining &&
    a.claudeFableWeekRemaining === b.claudeFableWeekRemaining &&
    a.codexWeekRemaining === b.codexWeekRemaining &&
    sameActivity(a.claudeActivity, b.claudeActivity) &&
    sameActivity(a.codexActivity, b.codexActivity)
  );
}

/** QuotaHistoryStore.record：按分钟落一个点，同一分钟内的多次刷新合并成一个。返回是否需要保存。 */
function record(current: QuotaHistoryState, capture: QuotaCapture, date: Date): boolean {
  const minute = Math.floor(date.getTime() / 1000 / 60) * 60;
  const day = startOfDay(date);
  const cutoff = minute - RETENTION_SECONDS;
  let changed = false;

  const retained = current.points.filter((point) => point.timestamp >= cutoff);
  if (retained.length !== current.points.length) {
    current.points = retained;
    changed = true;
  }

  const claudeBaseline = prepareBaseline(current.lastClaudeModelTotals, current.hasClaudeBaseline, current.claudeBaselineDay, day);
  const codexBaseline = prepareBaseline(current.lastCodexModelTotals, current.hasCodexBaseline, current.codexBaselineDay, day);
  const claudeActivity = activity(capture.claudeModelTotals, claudeBaseline.previous, claudeBaseline.hasBaseline);
  const codexActivity = activity(capture.codexModelTotals, codexBaseline.previous, codexBaseline.hasBaseline);

  const nextClaude = updatedBaseline(capture.claudeModelTotals, claudeBaseline, current.claudeBaselineDay, day);
  current.lastClaudeModelTotals = nextClaude.totals;
  current.hasClaudeBaseline = nextClaude.hasBaseline;
  current.claudeBaselineDay = nextClaude.day;

  const nextCodex = updatedBaseline(capture.codexModelTotals, codexBaseline, current.codexBaselineDay, day);
  current.lastCodexModelTotals = nextCodex.totals;
  current.hasCodexBaseline = nextCodex.hasBaseline;
  current.codexBaselineDay = nextCodex.day;

  const incoming: QuotaHistoryPoint = {
    timestamp: minute,
    claudeFiveHourRemaining: normalized(capture.claudeFiveHourRemaining),
    claudeWeekRemaining: normalized(capture.claudeWeekRemaining),
    claudeFableWeekRemaining: normalized(capture.claudeFableWeekRemaining),
    codexWeekRemaining: normalized(capture.codexWeekRemaining),
    claudeActivity,
    codexActivity,
  };
  const hasUsefulData =
    incoming.claudeFiveHourRemaining !== undefined ||
    incoming.claudeWeekRemaining !== undefined ||
    incoming.claudeFableWeekRemaining !== undefined ||
    incoming.codexWeekRemaining !== undefined ||
    incoming.claudeActivity.length > 0 ||
    incoming.codexActivity.length > 0;

  if (hasUsefulData) {
    const lastIndex = current.points.length - 1;
    if (lastIndex >= 0 && current.points[lastIndex].timestamp === minute) {
      const merged = merge(current.points[lastIndex], incoming);
      if (!samePoint(merged, current.points[lastIndex])) {
        current.points = [...current.points.slice(0, lastIndex), merged];
        changed = true;
      }
    } else {
      current.points = [...current.points, incoming];
      changed = true;
    }
  }

  return changed || nextClaude.changed || nextCodex.changed;
}

// ---------- 从一次刷新结果取读数（main.swift recordQuotaHistory） ----------

const tokens = (value: unknown) => integer(value) ?? 0;

/** 过期的读数不记（属于上一个窗口或来源太久没更新）；剩余 = 100 − 已用。 */
function remaining(used: unknown, stale: unknown): number | undefined {
  if (stale === true) return undefined;
  const value = finite(used);
  return value === undefined ? undefined : 100 - value;
}

export function quotaCapture(usage: Usage): QuotaCapture {
  const claude = usage.claude;
  const codex = usage.codex;
  const claudeModelTotals = new Map<string, number>();
  for (const model of claude?.ranges?.today?.models ?? []) {
    if (model.name === SYNTHETIC_MODEL) continue;
    const total = tokens(model.in) + tokens(model.out) + tokens(model.cr) + tokens(model.cw);
    claudeModelTotals.set(model.name, (claudeModelTotals.get(model.name) ?? 0) + total);
  }
  const codexModelTotals = new Map<string, number>();
  for (const model of codex?.ranges?.today?.models ?? []) {
    const total = tokens(model.in) + tokens(model.out) + tokens(model.cr) + tokens(model.cw);
    codexModelTotals.set(model.name, (codexModelTotals.get(model.name) ?? 0) + total);
  }
  return {
    claudeFiveHourRemaining: remaining(claude?.q5, claude?.q5_stale),
    claudeWeekRemaining: remaining(claude?.q7, claude?.q7_stale),
    claudeFableWeekRemaining: remaining(claude?.qf, claude?.qf_stale),
    codexWeekRemaining: remaining(codex?.pw, codex?.pw_stale),
    claudeModelTotals,
    codexModelTotals,
  };
}

/**
 * 每次刷新成功后调用一次。读数在调用这一刻取好，写盘按调用顺序排队，不会两次写交错。
 * 出错只打日志，不抛给调用方。
 */
export function recordQuotaHistory(usage: Usage): Promise<void> {
  const at = new Date();
  let capture: QuotaCapture;
  try {
    capture = quotaCapture(usage);
  } catch (err) {
    console.error("Tokei quota history capture failed:", err);
    return queue;
  }
  queue = queue
    .then(async () => {
      const current = await ensureLoaded();
      if (record(current, capture, at)) {
        publish();
        await save(current);
      }
    })
    .catch((err) => {
      console.error("Tokei quota history record failed:", err);
    });
  return queue;
}

// ---------- 给界面用 ----------

/** 读入（只读一次）并返回全部点，按时间升序。 */
export async function loadQuotaHistory(): Promise<QuotaHistoryPoint[]> {
  await ensureLoaded();
  return published;
}

/** 当前内存里的全部点（还没读文件时为空）。 */
export function quotaHistoryPoints(): QuotaHistoryPoint[] {
  return published;
}

/** QuotaHistoryStore.points(since:)：since 为 Unix 秒。 */
export function quotaHistoryPointsSince(points: QuotaHistoryPoint[], since: number): QuotaHistoryPoint[] {
  return points.filter((point) => point.timestamp >= since);
}

export function subscribeQuotaHistory(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** React 里订阅额度历史：首次使用时读文件，之后每次记录有变化都会重渲染。 */
export function useQuotaHistory(): QuotaHistoryPoint[] {
  const points = useSyncExternalStore(subscribeQuotaHistory, quotaHistoryPoints, quotaHistoryPoints);
  useEffect(() => {
    ensureLoaded().catch((err) => console.error("Tokei quota history load failed:", err));
  }, []);
  return points;
}
