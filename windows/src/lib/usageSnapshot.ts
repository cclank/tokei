import type { Usage } from "./types";

export interface SharedUsageState {
  usage: Usage | null;
  error: string | null;
  updated_at: number | null;
  refreshing: boolean;
}

export interface UsageSnapshot {
  revision: number;
  state: SharedUsageState;
}

/** 先订阅事件再读初始快照时，忽略晚到的旧响应。 */
export function newerSnapshot(current: UsageSnapshot | null, next: UsageSnapshot): UsageSnapshot {
  return !current || next.revision > current.revision ? next : current;
}
