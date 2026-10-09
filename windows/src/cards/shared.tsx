// 多张卡片共用的判断。
import * as Fmt from "../lib/fmt";
import { rangeLabel } from "../lib/store";
import type { RangeKey } from "../lib/types";
import type { CardContext } from "./spec";

export type QuotaState = "unavailable" | "available" | "partiallyStale" | "expired";

/** SubscriptionQuotaState.resolve：几个额度窗口的读数整体处在什么状态。 */
export function quotaState(windows: [number | null | undefined, boolean | null | undefined][]): QuotaState {
  const available = windows.filter(([value]) => value != null);
  if (!available.length) return "unavailable";
  const stale = available.filter(([, isStale]) => isStale === true).length;
  if (stale === 0) return "available";
  return stale === available.length ? "expired" : "partiallyStale";
}

/** 只在「今日」为空时给旁证：昨天 / 本周 / 本月最近一次有多少（UsageEmptyState）。 */
export function recentUsageHint(ctx: CardContext, tokens: (key: RangeKey) => number): string | null {
  if (ctx.range !== "today" || tokens("today") !== 0) return null;
  for (const key of ["yesterday", "week", "month"] as RangeKey[]) {
    const value = tokens(key);
    if (value > 0) return `${rangeLabel(key)} ${Fmt.human(value)}`;
  }
  return null;
}
