import { getRange, totalTokens, type RangeKey, type Ranges, type TokenUsageRange, type Usage } from "./types";

interface UsageRange extends TokenUsageRange {
  cached?: number;
  thoughts?: number;
  usage_available?: boolean;
}

interface UsageStat {
  ranges?: Ranges<UsageRange>;
  reserve_ranges?: Ranges<UsageRange>;
  usage?: UsageStat;
  quota?: { usage?: UsageStat };
}

const at = (stat: UsageStat | undefined, range: RangeKey): UsageRange => getRange(stat?.ranges, range, {});
const components = (r: UsageRange, includeReason = true) =>
  (r.in ?? 0) + (r.out ?? 0) + (r.cr ?? 0) + (r.cw ?? 0) + (includeReason ? (r.reason ?? 0) : 0);
const codexTokens = (r: UsageRange) => (r.in ?? 0) + (r.cached ?? 0) + (r.out ?? 0);

/** Match each card's token accounting, using only the selected time range. */
export function cardTokens(id: string, usage: Usage, range: RangeKey): number {
  const key = id.replace(/-/g, "_");
  const stat = usage[key] as UsageStat | undefined;
  const r = at(stat, range);
  switch (id) {
    case "claude": return components(r, false);
    case "codex": return codexTokens(r) + codexTokens(getRange(stat?.reserve_ranges, range, {}));
    case "gemini": return (r.in ?? 0) + (r.cached ?? 0) + (r.out ?? 0) + (r.thoughts ?? 0);
    case "cursor":
    case "zai": return totalTokens(at(stat?.usage, range));
    case "grok": return r.usage_available ? (r.tokens ?? 0) : 0;
    case "grok-bot": return totalTokens(at(stat?.quota?.usage, range));
    case "doubaowork": return 0; // Unknown token total, used only for ordering.
    case "copilot": return (r.out ?? 0) + (r.reason ?? 0);
    case "qoder": return codexTokens(r);
    case "qoderwork":
    case "qodercli":
    case "qodercli_cn":
    case "openclaw":
    case "musecode": return components(r, false);
    case "devin":
    case "minimax": return totalTokens(r);
    case "hermes":
    case "zcode":
    case "mimocode":
    case "pi":
    case "prime_agent":
    case "workbuddy":
    case "workbuddy-ai":
    case "codebuddy":
    case "deepseek_harness":
    case "opencode":
    case "qwencode":
    case "kimicode":
    case "cmdcode": return components(r);
    default: return 0;
  }
}

/** Keep equal totals stable and leave the registry/visible-card arrays untouched. */
export function sortedUsageCards<T extends { id: string }>(cards: T[], usage: Usage, range: RangeKey): T[] {
  return cards.map((card, index) => {
    const tokens = cardTokens(card.id, usage, range);
    return { card, index, tokens: Number.isFinite(tokens) ? Math.max(0, tokens) : 0 };
  }).sort((a, b) => b.tokens - a.tokens || a.index - b.index).map(({ card }) => card);
}
