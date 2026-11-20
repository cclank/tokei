// 与 Mac 菜单栏共用偏好键和统计口径。Windows 在托盘悬停提示中展示。
import { L } from "./i18n";
import { grouped, human } from "./fmt";
import { getPref } from "./prefs";
import { currentCycle, type QuotaCycle, type QuotaDetailPayload } from "./quotaDetail";
import type { Usage } from "./types";
import { Theme } from "../ui/theme";
import type { ProviderQuotaStat } from "../cards/providerQuota";

export const MENU_BAR_CONTENT_KEY = "menuBarContent";
export const TOKEN_PERIOD_KEY = "menuBarTokenPeriod";
export type TokenPeriod = "today" | "cycle";
export const trayContent = () => getPref<string>(MENU_BAR_CONTENT_KEY, "quota") === "tokens" ? "tokens" : "quota";
export const tokenPeriod = (): TokenPeriod => getPref<string>(TOKEN_PERIOD_KEY, "today") === "cycle" ? "cycle" : "today";
export const tokenPeriodLabel = (period: TokenPeriod) => period === "today" ? L("今日") : L("本周期");

export const TRAY_TOKEN_SOURCES = [
  { id: "claude", label: "Claude Code", key: "menuBarTokenClaude", defaultEnabled: true, tint: Theme.claude },
  { id: "codex", label: "Codex", key: "menuBarTokenCodex", defaultEnabled: true, tint: Theme.codex },
  { id: "antigravity", label: "Gemini / Antigravity", key: "menuBarTokenAntigravity", defaultEnabled: false, tint: Theme.gemini },
  { id: "grok", label: "Grok", key: "menuBarTokenGrok", defaultEnabled: false, tint: Theme.grok },
] as const;
type TokenSource = typeof TRAY_TOKEN_SOURCES[number];
type SourceID = TokenSource["id"];
export const trayTokenEnabled = (source: TokenSource) => getPref(source.key, source.defaultEnabled);
export const needsTrayCycleData = () => trayContent() === "tokens" && tokenPeriod() === "cycle" && TRAY_TOKEN_SOURCES.some(trayTokenEnabled);

function sum(values: number[]): number | null {
  let result = 0;
  for (const n of values) {
    if (!Number.isSafeInteger(n) || n < 0 || !Number.isSafeInteger(result + n)) return null;
    result += n;
  }
  return result;
}

function todayTokens(usage: Usage, source: SourceID): number | null {
  switch (source) {
    case "claude": {
      const r = usage.claude?.ranges?.today;
      return sum([r?.in ?? 0, r?.out ?? 0, r?.cr ?? 0, r?.cw ?? 0]);
    }
    case "codex": {
      const r = usage.codex?.ranges?.today, reserve = usage.codex?.reserve_ranges?.today;
      // reasoning 已含在 out，缓存只加一次；今日包含单列的重置卡用量。
      return sum([r?.in ?? 0, r?.cached ?? 0, r?.out ?? 0, reserve?.in ?? 0, reserve?.cached ?? 0, reserve?.out ?? 0]);
    }
    case "antigravity": {
      const r = usage.gemini?.ranges?.today;
      return sum([r?.in ?? 0, r?.cached ?? 0, r?.out ?? 0, r?.thoughts ?? 0]);
    }
    case "grok": return sum([usage.grok?.ranges?.today?.tokens ?? 0]);
  }
}

function cycles(usage: Usage, source: SourceID, detail: QuotaDetailPayload | null | undefined, now: number): QuotaCycle[] | null {
  if (!detail) return null;
  if (source === "antigravity") {
    const quota = usage.antigravity as ProviderQuotaStat | undefined;
    const windows = (quota?.windows ?? []).filter(w => w.id?.startsWith("antigravity-") && w.id.endsWith("-weekly"));
    if (!windows.length) return null;
    const result: QuotaCycle[] = [], seen = new Set<string>();
    for (const window of windows) {
      const id = window.id, reset = window.reset;
      if (!id || seen.has(id)) continue;
      seen.add(id);
      if (reset == null || reset <= now) return null;
      const cycle = detail.cycles.find(c => c.tool === "antigravity" && c.window_id === id && c.current &&
        c.start <= now && c.end > now && Math.abs(c.end - reset) <= 120);
      if (!cycle) return null;
      result.push(cycle);
    }
    return result;
  }
  const reset = source === "claude" ? usage.claude?.q7_reset : source === "codex" ? usage.codex?.rw : usage.grok?.reset;
  const cycle = currentCycle(detail, source, reset, now);
  return cycle ? [cycle] : null;
}

export function trayTokenMetrics(usage: Usage, detail?: QuotaDetailPayload | null, allDevices = false, now = Date.now() / 1000) {
  const period = tokenPeriod();
  return TRAY_TOKEN_SOURCES.filter(trayTokenEnabled).map(source => {
    let tokens: number | null = null, approximate = false;
    if (period === "today") tokens = todayTokens(usage, source.id);
    else {
      const active = cycles(usage, source.id, detail, now);
      if (active) {
        const counts = active.map(c => {
          if (allDevices || c.usage_scope === "local") return c.tokens;
          const selfDevice = "本机"; // l10n-ignore: collector's stable device identifier
          if (c.devices[selfDevice] != null) return c.devices[selfDevice];
          return detail?.devices.includes(selfDevice) && sum(Object.values(c.devices)) === c.tokens ? 0 : null;
        });
        if (counts.every((n): n is number => n != null)) tokens = sum(counts);
        approximate = active.some(c => c.approx);
      }
    }
    return { source, period, tokens, approximate, value: tokens == null ? "—" : `${approximate ? "≈" : ""}${human(tokens)}` };
  });
}

export function trayTokenTooltip(usage: Usage, detail?: QuotaDetailPayload | null): string {
  const metrics = trayTokenMetrics(usage, detail);
  const parts = metrics.map(({ source, period, tokens, approximate }) => {
    const name = `${source.label} ${tokenPeriodLabel(period)}`;
    if (tokens == null) return L("%@ 暂无用量统计", name);
    return approximate ? L("%@ 约 %@ Token", name, grouped(tokens)) : L("%@ %@ Token", name, grouped(tokens));
  });
  const full = parts.length ? `Tokei · ${parts.join(" · ")}` : "Tokei";
  if (full.length <= 127) return full;
  // Windows 通知区限制 127 个 UTF-16 单元；超长时保留每个工具，改用紧凑数值。
  const compact = metrics.map(({ source, value }) => `${source.id === "antigravity" ? "Antigravity" : source.id === "claude" ? "Claude" : source.label} ${value}`);
  return `Tokei · ${tokenPeriodLabel(tokenPeriod())} Token\n${compact.join(" · ")}`;
}
