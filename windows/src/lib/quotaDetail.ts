// 额度周期与长跨度每日消耗：对应 Mac 版 QuotaDetail.swift。数据来自采集脚本 `--quota-detail`
// （usage.30s.py 的 build_quota_detail），上次成功的结果原样缓存在 ~/.tokei/quota_detail.json，
// 打开页面时先摆出缓存，脚本跑完（1~3 秒）再换成新的。
import { useSyncExternalStore } from "react";
import { runCollector } from "./collector";
import { readTokeiFile, writeTokeiFile } from "./native";

/** 一天的 token 消耗（来自账本，已合并所有设备）。c = Claude Code、x = Codex、g = Grok。 */
export interface QuotaDailyPoint {
  d: string;
  c: number;
  x: number;
  g: number;
}

/** 一个额度周期 = 两次「余量 100%」之间。token 已合并所有设备。 */
export interface QuotaCycle {
  tool: string;
  window?: string | null;
  start: number;
  end: number;
  used_pct?: number | null;
  tokens: number;
  cost?: number | null;
  devices: Record<string, number>;
  approx: boolean;
  current: boolean;
}

export interface QuotaDetailPayload {
  daily: QuotaDailyPoint[];
  cycles: QuotaCycle[];
  devices: string[];
  missing: string[];
  now: number;
}

export const dailyTotal = (point: QuotaDailyPoint) => point.c + point.x + point.g;

/** 重锚会截短周期，月窗口也有长短。 */
export const cycleDurationDays = (cycle: QuotaCycle) => (cycle.end - cycle.start) / 86400;

/** 一个满额度大约值多少 token —— 按当前进度外推；太早期外推没意义。 */
export function projectedTotal(cycle: QuotaCycle): number | null {
  const used = cycle.used_pct;
  if (used == null || used < 3 || cycle.tokens <= 0) return null;
  const projected = Math.trunc((cycle.tokens / used) * 100);
  return Number.isSafeInteger(projected) ? projected : null;
}

export function cycleCostLabel(cycle: QuotaCycle): string | null {
  const cost = cycle.cost;
  return cost != null && Number.isFinite(cost) && cost >= 0 ? `$${cost.toFixed(2)}` : null;
}

export function projectedCost(cycle: QuotaCycle): number | null {
  const { cost, used_pct: used } = cycle;
  if (used == null || !Number.isFinite(used) || used < 3 || cost == null || !Number.isFinite(cost) || cost <= 0) return null;
  const projected = cost / used * 100;
  return Number.isFinite(projected) ? projected : null;
}

/** 只展示仍进行中且与卡片重置时间匹配的周期；容差与 macOS 和采集器一致。 */
export function currentCycle(payload: QuotaDetailPayload | null | undefined, tool: string, reset: number | null | undefined, now = Date.now() / 1000): QuotaCycle | null {
  if (reset == null || !Number.isFinite(reset) || reset <= now) return null;
  return payload?.cycles.find(cycle => cycle.tool === tool && cycle.current && cycle.start <= now && cycle.end > now && Math.abs(cycle.end - reset) <= 120) ?? null;
}

export function deviceBreakdown(cycle: QuotaCycle): { name: string; tokens: number }[] {
  return Object.entries(cycle.devices)
    .filter(([, tokens]) => tokens > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([name, tokens]) => ({ name, tokens }));
}

// ---------- 解码（对应 Swift 的 JSONDecoder：缺必需字段就整份作废） ----------

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

function decodeDaily(value: unknown): QuotaDailyPoint | null {
  if (!isRecord(value) || typeof value.d !== "string") return null;
  if (!isNumber(value.c) || !isNumber(value.x) || !isNumber(value.g)) return null;
  return { d: value.d, c: value.c, x: value.x, g: value.g };
}

function decodeCycle(value: unknown): QuotaCycle | null {
  if (!isRecord(value) || typeof value.tool !== "string") return null;
  if (!isNumber(value.start) || !isNumber(value.end) || !isNumber(value.tokens)) return null;
  if (value.window != null && typeof value.window !== "string") return null;
  if (value.cost != null && !isNumber(value.cost)) return null;
  if (typeof value.approx !== "boolean" || typeof value.current !== "boolean" || !isRecord(value.devices)) return null;
  const devices: Record<string, number> = {};
  for (const [name, tokens] of Object.entries(value.devices)) {
    if (!isNumber(tokens)) return null;
    devices[name] = tokens;
  }
  return {
    tool: value.tool,
    window: typeof value.window === "string" ? value.window : null,
    start: value.start,
    end: value.end,
    used_pct: isNumber(value.used_pct) ? value.used_pct : null,
    tokens: value.tokens,
    cost: isNumber(value.cost) ? value.cost : null,
    devices,
    approx: value.approx,
    current: value.current,
  };
}

function decodeList<T>(value: unknown, decode: (item: unknown) => T | null): T[] | null {
  if (!Array.isArray(value)) return null;
  const result: T[] = [];
  for (const item of value) {
    const decoded = decode(item);
    if (decoded === null) return null;
    result.push(decoded);
  }
  return result;
}

const decodeString = (value: unknown) => (typeof value === "string" ? value : null);

export function decodeQuotaDetail(text: string | null | undefined): QuotaDetailPayload | null {
  if (!text) return null;
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    return null;
  }
  if (!isRecord(raw) || !isNumber(raw.now)) return null;
  const daily = decodeList(raw.daily, decodeDaily);
  const cycles = decodeList(raw.cycles, decodeCycle);
  const devices = decodeList(raw.devices, decodeString);
  const missing = decodeList(raw.missing, decodeString);
  if (!daily || !cycles || !devices || !missing) return null;
  return { daily, cycles, devices, missing, now: raw.now };
}

// ---------- QuotaDetailRepository.shared ----------

const CACHE_FILE = "quota_detail.json";
const FRESHNESS_MS = 30_000;

export interface QuotaDetailSnapshot {
  payload: QuotaDetailPayload | null;
  refreshing: boolean;
}

let snapshot: QuotaDetailSnapshot = { payload: null, refreshing: false };
let cacheRequested = false;
let cacheInFlight = false;
let loadedAt = 0;
let forcedReloadPending = false;
const listeners = new Set<() => void>();

function update(patch: Partial<QuotaDetailSnapshot>) {
  snapshot = { ...snapshot, ...patch };
  listeners.forEach((listener) => listener());
}

/** 脚本要跑一会儿，先把上次落盘的结果摆出来，别让人对着空面板等。 */
function readCache(force = false) {
  if (cacheInFlight || (cacheRequested && !force)) return;
  cacheRequested = true;
  cacheInFlight = true;
  const previous = snapshot.payload;
  readTokeiFile(CACHE_FILE)
    .then((text) => {
      if (snapshot.payload !== previous) return;
      const cached = decodeQuotaDetail(text);
      if (cached) update({ payload: cached });
    })
    .catch(() => {})
    .finally(() => { cacheInFlight = false; });
}

export function loadQuotaDetail(force = false, cacheOnly = false) {
  readCache(cacheOnly);
  if (cacheOnly) return;
  if (!force && loadedAt && Date.now() - loadedAt < FRESHNESS_MS) return;
  if (snapshot.refreshing) {
    forcedReloadPending = forcedReloadPending || force;
    return;
  }
  update({ refreshing: true });
  runCollector(["--quota-detail"])
    .then((text) => {
      const decoded = decodeQuotaDetail(text);
      if (!decoded) {
        console.error("Tokei quota detail failed: undecodable output");
        update({ refreshing: false });
        return;
      }
      void writeTokeiFile(CACHE_FILE, text).catch(() => {});
      loadedAt = Date.now();
      update({ payload: decoded, refreshing: false });
    })
    .catch((err) => {
      console.error("Tokei quota detail failed:", err);
      update({ refreshing: false });
    })
    .finally(() => {
      if (forcedReloadPending) {
        forcedReloadPending = false;
        loadQuotaDetail(true);
      }
    });
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useQuotaDetail(): QuotaDetailSnapshot {
  return useSyncExternalStore(subscribe, () => snapshot, () => snapshot);
}
