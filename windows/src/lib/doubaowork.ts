import { L } from "./i18n";
import * as Fmt from "./fmt";
import { rangeLabel } from "./store";
import type { DoubaoWorkQuota, DoubaoWorkQuotaWindow, DoubaoWorkRange, DoubaoWorkStat, RangeKey } from "./types";

const RANGE_KEYS: RangeKey[] = ["today", "yesterday", "week", "last_week", "month", "year", "all"];

/** Keep the selected period, including zero; older snapshots may omit ranges. */
export function doubaoWorkRange(stat: DoubaoWorkStat | null | undefined, key: RangeKey): DoubaoWorkRange {
  const raw = key === "all" ? stat?.ranges?.all ?? stat?.ranges?.year : stat?.ranges?.[key];
  const count = raw?.sessions;
  return {
    sessions: typeof count === "number" && Number.isSafeInteger(count) ? Math.max(0, count) : 0,
    session_ids: raw?.session_ids,
  };
}

export function doubaoWorkHasActivity(stat: DoubaoWorkStat | null | undefined): boolean {
  return RANGE_KEYS.some(key => doubaoWorkRange(stat, key).sessions > 0);
}

export function doubaoWorkActivityLabel(key: RangeKey): string {
  return key === "all" ? L("累计会话") : L("%@ 新建会话", rangeLabel(key));
}

export function doubaoWorkSourceCaption(stat?: DoubaoWorkStat | null): string {
  return doubaoWorkQuota(stat)?.windows.length
    ? L("账号额度来自豆包官网；会话数来自本机缓存，未提供 Token 用量")
    : L("仅统计已缓存的 Agent 会话，未提供 Token 用量");
}

const MAX_TIME_MS = 32_503_680_000_000;
const FRESH_FOR_MS = 30 * 60_000;

/** Treat malformed cache data as absent, including duplicate or unknown windows. */
export function doubaoWorkQuota(stat: DoubaoWorkStat | null | undefined): DoubaoWorkQuota | null {
  const q = stat?.quota;
  if (!q || q.version !== 1 || !["connected", "login_required", "unavailable"].includes(q.status) ||
      (q.updated != null && (!Number.isSafeInteger(q.updated) || q.updated <= 0)) || !Array.isArray(q.windows) || q.windows.length > 2) return null;
  if (!q.windows.length) return q.status !== "connected" ? q : null;
  if (q.updated == null) return null;
  const seen = new Set<number>();
  for (const w of q.windows) {
    if (!w || ![1, 2].includes(w.window_type) || seen.has(w.window_type) ||
        typeof w.used_percent !== "number" || !Number.isFinite(w.used_percent) || w.used_percent < 0 || w.used_percent > 100 ||
        !Number.isSafeInteger(w.start_time_ms) || !Number.isSafeInteger(w.end_time_ms) ||
        w.start_time_ms < 0 || w.end_time_ms < 0 || w.start_time_ms > MAX_TIME_MS || w.end_time_ms > MAX_TIME_MS ||
        (w.end_time_ms > 0 && w.end_time_ms < w.start_time_ms) ||
        typeof w.less_than_one_percent !== "boolean" || (w.less_than_one_percent && w.used_percent >= 1)) return null;
    seen.add(w.window_type);
  }
  return q;
}

export interface DoubaoWorkQuotaRow {
  title: string;
  caption: string;
  value: string;
  detail: string | null;
  remaining: number | null;
  stale: boolean;
}

export function doubaoWorkQuotaRows(stat: DoubaoWorkStat | null | undefined, now = Date.now()): DoubaoWorkQuotaRow[] {
  const q = doubaoWorkQuota(stat);
  return ([1, 2] as const).map(kind => {
    const title = kind === 1 ? L("当前时段额度") : L("7 天额度");
    const w: DoubaoWorkQuotaWindow | undefined = q?.windows.find(value => value.window_type === kind);
    const expired = !q || q.updated == null || !w || q.updated * 1000 > now + 60_000 ||
      now - q.updated * 1000 > FRESH_FOR_MS || (w.end_time_ms > 0 && w.end_time_ms <= now) || w.start_time_ms > now + 60_000;
    const stale = expired || q?.status !== "connected";
    const remaining = !expired && !w!.less_than_one_percent ? 100 - w!.used_percent : null;
    return {
      title,
      caption: remaining != null ? `${title} · ${L("剩余额度")}` : title,
      value: expired ? "—" : w!.less_than_one_percent ? L("已用 <1%") : `${Fmt.credits(remaining!)}%`,
      detail: expired ? null : w!.end_time_ms > 0 ? `${Fmt.reset(w!.end_time_ms / 1000)} · ${L("%@ 后重置", Fmt.countdown(w!.end_time_ms / 1000))}` : null,
      remaining,
      stale,
    };
  });
}

export function doubaoWorkQuotaNotice(stat: DoubaoWorkStat | null | undefined, now = Date.now()): string | null {
  const q = doubaoWorkQuota(stat);
  if (q && q.status !== "connected" && q.windows.length > 0) return L("上次读取的额度，等待刷新");
  if (!q || q.status === "login_required") return L("连接豆包账号查看额度");
  if (q.status === "unavailable") return L("尚未读取到额度，请确认登录后点击“读取额度”");
  return doubaoWorkQuotaRows(stat, now).some(row => row.stale) ? L("上次读取的额度，等待刷新") : null;
}
