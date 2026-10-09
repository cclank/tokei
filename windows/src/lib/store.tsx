// 面板的数据：定时跑采集脚本，开着面板时 10 秒一刷，收起时 30 秒（同 Mac 版 Store）。
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { call, collectJSON, inTauri } from "./collector";
import { L } from "./i18n";
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

export function UsageProvider({ children, onUsage }: { children: ReactNode; onUsage?: (usage: Usage) => void }) {
  const [usage, setUsage] = useState<Usage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(L("加载中…"));
  const inFlight = useRef(false);
  const pending = useRef(false);
  const onUsageRef = useRef(onUsage);
  onUsageRef.current = onUsage;

  const refresh = useCallback(() => {
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
        const now = new Date();
        setLastUpdated(L("更新 %@", `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`));
        onUsageRef.current?.(next);
      })
      .catch((err) => {
        setError(String(err));
        setLastUpdated(L("加载失败"));
      })
      .finally(() => {
        inFlight.current = false;
        setRefreshing(false);
        if (pending.current) {
          pending.current = false;
          refresh();
        }
      });
  }, []);

  useEffect(() => {
    refresh();
    let timer: number | undefined;
    const schedule = () => {
      window.clearTimeout(timer);
      const interval = document.visibilityState === "visible" ? VISIBLE_INTERVAL : IDLE_INTERVAL;
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
    let unlisten: (() => void) | undefined;
    if (inTauri) {
      import("@tauri-apps/api/event").then(async ({ listen }) => {
        const offs = await Promise.all([listen("tokei://refresh", () => refresh()), listen("tokei://panel-shown", () => refresh())]);
        unlisten = () => offs.forEach((off) => off());
      });
    }
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
      unlisten?.();
    };
  }, [refresh]);

  return <UsageContext.Provider value={{ usage, error, refreshing, lastUpdated, refresh }}>{children}</UsageContext.Provider>;
}

/** 托盘悬停提示：列出当前的额度剩余（Windows 托盘放不下 Mac 菜单栏那样的文字）。 */
export function trayTooltip(usage: Usage): string {
  const parts: string[] = [];
  const c = usage.claude;
  if (c?.q5 != null) parts.push(`Claude 5h ${Math.round(100 - c.q5)}%`);
  if (c?.q7 != null) parts.push(`Claude ${L("周")} ${Math.round(100 - c.q7)}%`);
  const x = usage.codex;
  if (x?.p5 != null) parts.push(`Codex 5h ${Math.round(100 - x.p5)}%`);
  if (x?.pw != null) parts.push(`Codex ${L("周")} ${Math.round(100 - x.pw)}%`);
  return parts.length ? `Tokei · ${parts.join(" · ")}` : "Tokei";
}

export function pushTrayTooltip(usage: Usage) {
  void call("set_tray_tooltip", { text: trayTooltip(usage) });
}

export const RANGE_LABEL_KEYS: Record<RangeKey, string> = {
  today: "今日",
  yesterday: "昨日",
  week: "本周",
  last_week: "上周",
  month: "本月",
  year: "本年",
  all: "全部",
};

export const rangeLabel = (key: RangeKey) => L(RANGE_LABEL_KEYS[key]);
