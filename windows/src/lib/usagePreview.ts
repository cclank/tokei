import type { Usage } from "./types";

export const USAGE_PREVIEW_FILE = "windows-usage-preview.json";
const MAX_BYTES = 2 * 1024 * 1024;
const MAX_AGE = 24 * 60 * 60 * 1000;
const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

export interface UsagePreview { usage: Usage; updatedAt: number }

/** Keep usage ranges only. Account names, credentials and old quota readings stay out of the preview. */
export function previewUsage(usage: Usage): Usage {
  const result: Record<string, unknown> = { claude: { ranges: {} }, codex: { ranges: {} } };
  for (const [tool, value] of Object.entries(usage)) {
    if (tool.startsWith("_") || !record(value) || !record(value.ranges)) continue;
    result[tool] = { ranges: value.ranges };
    if (record(value.reserve_ranges)) (result[tool] as Record<string, unknown>).reserve_ranges = value.reserve_ranges;
  }
  return result as Usage;
}

export function encodeUsagePreview(usage: Usage, updatedAt: number): string | null {
  const text = JSON.stringify({ version: 1, updatedAt, usage: previewUsage(usage) });
  return text.length <= MAX_BYTES ? text : null;
}

export function decodeUsagePreview(text: string | null, now = Date.now()): UsagePreview | null {
  if (!text || text.length > MAX_BYTES) return null;
  try {
    const value: unknown = JSON.parse(text);
    if (!record(value) || value.version !== 1 || typeof value.updatedAt !== "number" ||
      !Number.isFinite(value.updatedAt) || value.updatedAt > now || now - value.updatedAt > MAX_AGE ||
      new Date(value.updatedAt).toDateString() !== new Date(now).toDateString() ||
      !record(value.usage) || !record(value.usage.claude) || !record(value.usage.codex) ||
      !record(value.usage.claude.ranges) || !record(value.usage.codex.ranges)) return null;
    return { usage: previewUsage(value.usage as Usage), updatedAt: value.updatedAt };
  } catch { return null; }
}

/** A late cache read must never delay collection or replace newer data. */
export async function initialUsage(
  ready: Promise<void>,
  read: () => Promise<UsagePreview | null>,
  collect: (args: string[]) => Promise<Usage>,
  preview: (value: UsagePreview, source: "cache" | "local") => void,
): Promise<Usage> {
  let accepted = false;
  let collecting = false;
  const cached = read().then((value) => {
    if (value && !collecting) { accepted = true; preview(value, "cache"); }
  }).catch(() => {});
  await ready;
  // Give fast local reads a chance, without blocking on a slow or unavailable disk.
  let timer: ReturnType<typeof setTimeout> | undefined;
  await Promise.race([cached, new Promise<void>((resolve) => { timer = setTimeout(resolve, 150); })]);
  clearTimeout(timer);
  collecting = true;
  if (!accepted) {
    try {
      const usage = await collect(["--json", "--no-sync-snapshot", "--local-only"]);
      preview({ usage, updatedAt: Date.now() }, "local");
    } catch { /* A failed preview must not suppress the normal collection. */ }
  }
  return collect(["--json", "--no-sync-snapshot"]);
}
