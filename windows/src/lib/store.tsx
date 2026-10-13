// 主窗口负责采集；快捷面板订阅同一份带版本号的状态。
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { call, collectJSON, inTauri } from "./collector";
import { L } from "./i18n";
import { trayQuotaTooltip } from "./trayQuota";
import { usePrefsVersion } from "./prefs";
import { newerSnapshot, type SharedUsageState, type UsageSnapshot } from "./usageSnapshot";
import type { RangeKey, Usage } from "./types";

const VISIBLE_INTERVAL = 10_000;
const IDLE_INTERVAL = 30_000;

export interface UsageStore {
  usage: Usage | null;
  error: string | null;
  refreshing: boolean;
  lastUpdated: string;
  refresh: () => void;
}

const UsageContext = createContext<UsageStore | null>(null);

export function useUsageStore(): UsageStore {
  const store = useContext(UsageContext);
  if (!store) throw new Error("UsageProvider missing");
  return store;
}

const pad = (n: number) => String(n).padStart(2, "0");

export function UsageProvider({ children, onUsage, shared = false }: { children: ReactNode; onUsage?: (usage: Usage) => void; shared?: boolean }) {
  const follower = shared && inTauri;
  const [usage, setUsage] = useState<Usage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  usePrefsVersion();
  const date = updatedAt != null ? new Date(updatedAt) : null;
  const lastUpdated = error ? L("加载失败") : date ? L("更新 %@", `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`) : L("加载中…");
  const snapshot = useRef<UsageSnapshot | null>(null);
  const inFlight = useRef(false);
  const pending = useRef(false);
  const onUsageRef = useRef(onUsage);
  onUsageRef.current = onUsage;

  const refresh = useCallback(() => {
    if (follower) {
      setRefreshing(true);
      void call("request_usage_refresh").catch((err) => {
        setError(String(err));
        setRefreshing(false);
      });
      return;
    }
    if (inFlight.current) {
      pending.current = true;
      return;
    }
    inFlight.current = true;
    setRefreshing(true);
    collectJSON<Usage>(["--json", "--no-sync-snapshot"])
      .then((next) => {
        setUsage(next);
        setError(null);
        setUpdatedAt(Date.now());
        onUsageRef.current?.(next);
      })
      .catch((err) => {
        setError(String(err));
      })
      .finally(() => {
        inFlight.current = false;
        setRefreshing(false);
        if (pending.current) {
          pending.current = false;
          refresh();
        }
      });
  }, [follower]);

  useEffect(() => {
    if (!inTauri || follower) return;
    const state: SharedUsageState = { usage, error, updated_at: updatedAt, refreshing };
    void call("publish_usage_snapshot", { snapshot: state }).catch((err) => console.error("Tokei usage snapshot publish failed", err));
  }, [usage, error, updatedAt, refreshing, follower]);

  useEffect(() => {
    let disposed = false;
    let unlisten: (() => void) | undefined;
    if (follower) {
      const apply = (next: UsageSnapshot) => {
        if (disposed) return;
        const selected = newerSnapshot(snapshot.current, next);
        if (selected === snapshot.current) return;
        snapshot.current = selected;
        setUsage(selected.state.usage);
        setError(selected.state.error);
        setUpdatedAt(selected.state.updated_at);
        setRefreshing(selected.state.refreshing);
      };
      void import("@tauri-apps/api/event").then(async ({ listen }) => {
        const off = await listen<UsageSnapshot>("tokei://usage-state", (event) => apply(event.payload));
        if (disposed) { off(); return; }
        unlisten = off;
        const initial = await call<UsageSnapshot>("get_usage_snapshot");
        if (initial) apply(initial);
      }).catch((err) => { if (!disposed) setError(String(err)); });
      return () => { disposed = true; unlisten?.(); };
    }
    refresh();
    let timer: number | undefined;
    let quickVisible = false;
    const schedule = () => {
      window.clearTimeout(timer);
      const interval = document.visibilityState === "visible" || quickVisible ? VISIBLE_INTERVAL : IDLE_INTERVAL;
      timer = window.setTimeout(() => {
        refresh();
        schedule();
      }, interval);
    };
    schedule();
    const onVisibility = () => {
      if (document.visibilityState === "visible") refresh();
      schedule();
    };
    document.addEventListener("visibilitychange", onVisibility);
    if (inTauri) {
      void import("@tauri-apps/api/event").then(async ({ listen }) => {
        const offs = await Promise.all([
          listen("tokei://refresh", () => refresh()),
          listen("tokei://panel-shown", () => refresh()),
          listen<boolean>("tokei://quick-visible", (event) => {
            quickVisible = event.payload;
            schedule();
            if (quickVisible) refresh();
          }),
        ]);
        if (disposed) { offs.forEach((off) => off()); return; }
        unlisten = () => offs.forEach((off) => off());
        const visible = await call<boolean>("quick_panel_visible");
        if (!disposed) { quickVisible = Boolean(visible); schedule(); }
      }).catch((err) => console.error("Tokei usage listeners failed", err));
    }
    return () => {
      disposed = true;
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
      unlisten?.();
    };
  }, [refresh, follower]);

  return <UsageContext.Provider value={{ usage, error, refreshing, lastUpdated, refresh }}>{children}</UsageContext.Provider>;
}

export function pushTrayTooltip(usage: Usage) {
  void call("set_tray_tooltip", { text: trayQuotaTooltip(usage) });
}

// key 写成 L() 的字面量，文案检查才认得出。
const RANGE_LABELS: Record<RangeKey, () => string> = {
  today: () => L("今日"),
  yesterday: () => L("昨日"),
  week: () => L("本周"),
  last_week: () => L("上周"),
  month: () => L("本月"),
  year: () => L("本年"),
  all: () => L("全部"),
};

export const rangeLabel = (key: RangeKey) => RANGE_LABELS[key]();
