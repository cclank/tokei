// 托盘的额度来源（Mac 版 MenuBarQuotaSource）：偏好键、默认值、名称与读数和 Mac 版一致。
// Windows 托盘图标画不了文字，这些开关决定托盘悬停提示里列哪些窗口（trayQuotaTooltip）。
import { L } from "./i18n";
import { getPref } from "./prefs";
import type { Usage } from "./types";
import { hasResetSinceReading } from "../ui/kit";
import { Theme, type RGB } from "../ui/theme";

interface Reading {
  value: number | null | undefined;
  stale: boolean;
  reset: number | null | undefined;
}

export interface TrayQuotaSource {
  id: string;
  label: () => string;
  /** `claude5h` 与 `codexWeek` 沿用 Mac 版已发布的键名。 */
  key: string;
  defaultEnabled: boolean;
  tint: RGB;
  reading: (usage: Usage) => Reading;
}

function read(stat: object | null | undefined, value: string, stale: string, reset: string): Reading {
  const fields = (stat ?? {}) as Record<string, unknown>;
  return {
    value: fields[value] as number | null | undefined,
    stale: fields[stale] === true,
    reset: fields[reset] as number | null | undefined,
  };
}

/** 顺序即优先级（MenuBarQuotaSource.allCases）。 */
export const TRAY_QUOTA_SOURCES: TrayQuotaSource[] = [
  { id: "claude5h", label: () => "Claude 5h", key: "menuBarQuotaClaude", defaultEnabled: true, tint: Theme.claude, reading: (u) => read(u.claude, "q5", "q5_stale", "q5_reset") },
  { id: "claudeWeek", label: () => L("Claude 周"), key: "menuBarQuotaClaudeWeek", defaultEnabled: false, tint: Theme.claude, reading: (u) => read(u.claude, "q7", "q7_stale", "q7_reset") },
  { id: "claudeFable", label: () => "Claude Fable", key: "menuBarQuotaClaudeFable", defaultEnabled: false, tint: Theme.orange, reading: (u) => read(u.claude, "qf", "qf_stale", "qf_reset") },
  { id: "codex5h", label: () => "Codex 5h", key: "menuBarQuotaCodex5h", defaultEnabled: false, tint: Theme.codex, reading: (u) => read(u.codex, "p5", "p5_stale", "r5") },
  { id: "codexWeek", label: () => L("Codex 周"), key: "menuBarQuotaCodex", defaultEnabled: true, tint: Theme.codex, reading: (u) => read(u.codex, "pw", "pw_stale", "rw") },
  { id: "kimi5h", label: () => "Kimi 5h", key: "menuBarQuotaKimi5h", defaultEnabled: false, tint: Theme.kimicode, reading: (u) => read(u.kimicode, "p5", "p5_stale", "r5") },
  { id: "kimiSubscription", label: () => L("Kimi 订阅"), key: "menuBarQuotaKimiSubscription", defaultEnabled: false, tint: Theme.kimicode, reading: (u) => read(u.kimicode, "pw", "pw_stale", "rw") },
  { id: "grok", label: () => "Grok", key: "menuBarQuotaGrok", defaultEnabled: false, tint: Theme.grok, reading: (u) => read(u.grok, "pct", "stale", "reset") },
];

export const trayQuotaEnabled = (source: TrayQuotaSource) => getPref(source.key, source.defaultEnabled);

export interface TrayQuotaMetric {
  source: TrayQuotaSource;
  /** 剩余百分比的整数；窗口已重置、还没读到新数时是「—」。 */
  value: string;
  stale: boolean;
}

/** MenuBarQuotaSource.metrics：勾选中、且账号有这个窗口的项，已用换成剩余。 */
export function trayQuotaMetrics(usage: Usage): TrayQuotaMetric[] {
  const metrics: TrayQuotaMetric[] = [];
  for (const source of TRAY_QUOTA_SOURCES) {
    if (!trayQuotaEnabled(source)) continue;
    const reading = source.reading(usage);
    if (reading.value == null) continue;
    if (hasResetSinceReading(reading.stale, reading.reset)) {
      metrics.push({ source, value: "—", stale: true });
    } else {
      metrics.push({ source, value: (100 - reading.value).toFixed(0), stale: reading.stale });
    }
  }
  return metrics;
}

/** 托盘悬停提示：「Tokei · Claude 5h 42% · Codex 周 80%」，全关或都没有时只写 Tokei。 */
export function trayQuotaTooltip(usage: Usage): string {
  const parts = trayQuotaMetrics(usage).map(({ source, value }) => `${source.label()} ${value === "—" ? value : `${value}%`}`);
  return parts.length ? `Tokei · ${parts.join(" · ")}` : "Tokei";
}
