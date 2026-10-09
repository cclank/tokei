// 数据面板的数据仓库（Mac 版 DashboardRepository）：按时间段缓存 `--dashboard` 的结果，
// 30 秒内不重复跑；同一时间段同时只跑一个，强制刷新排到这一次之后。
// 放在模块里而不是组件里，关掉再打开数据面板时直接用缓存。
import { useSyncExternalStore } from "react";
import { collectJSON } from "../../lib/collector";
import { normalizePayload, type DashboardPayload, type WrappedPeriod } from "./types";

const FRESHNESS = 30_000;

const payloads = new Map<WrappedPeriod, DashboardPayload>();
const loadedAt = new Map<WrappedPeriod, number>();
const inFlight = new Set<WrappedPeriod>();
const forcedReloadPending = new Set<WrappedPeriod>();
const listeners = new Set<() => void>();
let version = 0;

function emit() {
  version++;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function cachedDashboard(period: WrappedPeriod): DashboardPayload | null {
  return payloads.get(period) ?? null;
}

export function loadDashboard(period: WrappedPeriod, force = false) {
  if (!force) {
    const loaded = loadedAt.get(period);
    if (loaded != null && Date.now() - loaded < FRESHNESS) return;
  }
  if (inFlight.has(period)) {
    if (force) forcedReloadPending.add(period);
    return;
  }
  inFlight.add(period);
  collectJSON<Partial<DashboardPayload>>(["--dashboard", "--period", period])
    .then((raw) => {
      loadedAt.set(period, Date.now());
      payloads.set(period, normalizePayload(raw));
      emit();
    })
    .catch((err) => {
      console.error("Tokei dashboard failed:", err);
    })
    .finally(() => {
      inFlight.delete(period);
      if (forcedReloadPending.delete(period)) loadDashboard(period, true);
    });
}

/** 主刷新完成后预热「全部」（Mac 版 Store 首次刷新后的 DashboardRepository.shared.load(.all, force: true)）。 */
export function prewarmDashboard() {
  loadDashboard("all", true);
}

/** 任一时间段的缓存更新都会让订阅的组件重渲染。 */
export function useDashboardVersion(): number {
  return useSyncExternalStore(subscribe, () => version);
}
