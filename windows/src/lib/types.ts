// 采集脚本 `usage.30s.py --json` 的输出结构，对应 Mac 版 Model.swift。
// 这里只放多家共用的类型；某一家独有的结构定义在它自己的卡片文件里（见 src/cards/*）。

export type RangeKey = "today" | "yesterday" | "week" | "last_week" | "month" | "year" | "all";

export const DISPLAY_RANGES: RangeKey[] = ["today", "yesterday", "week", "last_week", "month", "year"];

export type Ranges<T> = Record<Exclude<RangeKey, "all">, T> & { all?: T };

/** 取某个区间；`all` 缺省时退回本年（Mac 版 get(.all) 同理）。 */
export function getRange<T>(ranges: Ranges<T> | undefined | null, key: RangeKey, empty: T): T {
  if (!ranges) return empty;
  if (key === "all") return ranges.all ?? ranges.year ?? empty;
  return ranges[key] ?? empty;
}

export interface PerfModelStat {
  tps: number;
  ttft?: number | null;
  n: number;
  o?: number;
  g?: number;
  tn?: number;
  th?: Record<string, number>;
}

export interface PerfStat extends PerfModelStat {
  models?: Record<string, PerfModelStat> | null;
}

/** 按模型行的显示名找这一行的速度；对不上时只比字母和数字（GLM-5.3 / glm 5.3）。 */
export function modelPerf(perf: PerfStat | null | undefined, name: string): PerfModelStat | undefined {
  const models = perf?.models;
  if (!models) return undefined;
  if (models[name]) return models[name];
  const key = matchKey(name);
  const hit = Object.entries(models).find(([k]) => matchKey(k) === key);
  return hit?.[1];
}

export function matchKey(name: string): string {
  return name.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
}

export interface ClaudeModelStat {
  name: string;
  in: number;
  out: number;
  cr: number;
  cw: number;
  cost: number;
  pin: number;
  pout: number;
  pcr?: number | null;
}

export interface ClaudeRange {
  hit: number;
  in: number;
  out: number;
  cr: number;
  cw: number;
  cost: number;
  models?: ClaudeModelStat[];
  sessions?: number;
  perf?: PerfStat | null;
}

export interface ClaudeStat {
  ranges: Ranges<ClaudeRange>;
  session_name?: string;
  session_total?: number;
  q5?: number | null;
  q5_reset?: number | null;
  q7?: number | null;
  q7_reset?: number | null;
  qf?: number | null;
  qf_reset?: number | null;
  q_updated?: number | null;
  q5_stale?: boolean | null;
  q7_stale?: boolean | null;
  qf_stale?: boolean | null;
}

export interface TokenModelStat {
  model_id?: string | null;
  name: string;
  tokens?: number | null;
  in: number;
  out: number;
  cr?: number;
  cw?: number;
  reason?: number;
  cost: number;
  cost_cny?: number | null;
  credits?: number;
  pin?: number;
  pout?: number;
  pcr?: number;
  /** 没有公开价、按别的模型估算时参照的模型名。 */
  pref?: string | null;
}

export interface CodexRange {
  hit: number;
  in: number;
  cached: number;
  out: number;
  reason: number;
  cost: number;
  sessions?: number;
  models?: TokenModelStat[];
  perf?: PerfStat | null;
}

export interface CodexResetCards {
  count: number;
  expires: number[];
  updated?: number | null;
}

export interface CodexReserveQuota {
  used_percent?: number | null;
  resets_at?: number | null;
  window_minutes?: number | null;
  plan?: string | null;
  updated?: number | null;
  stale?: boolean | null;
}

export interface CodexStat {
  ranges: Ranges<CodexRange>;
  reserve_ranges?: Ranges<CodexRange> | null;
  reserve_quota?: CodexReserveQuota | null;
  p5?: number | null;
  pw?: number | null;
  r5?: number | null;
  rw?: number | null;
  q_updated?: number | null;
  p5_stale?: boolean | null;
  pw_stale?: boolean | null;
  plan?: string | null;
  reset_cards?: CodexResetCards | null;
}

export interface TokenUsageRange {
  tokens?: number;
  hit?: number;
  in?: number;
  out?: number;
  cr?: number;
  cw?: number;
  reason?: number;
  cost?: number;
  cost_cny?: number | null;
  credits?: number;
  requests?: number;
  sessions?: number;
  models?: TokenModelStat[];
  coverage?: string | null;
  perf?: PerfStat | null;
}

export interface TokenUsageStat {
  ranges: Ranges<TokenUsageRange>;
}

/** 规整成全部字段都有值的 TokenUsageRange，省得每处写 `?? 0`。 */
export function tokenRange(r?: TokenUsageRange | null): Required<Omit<TokenUsageRange, "coverage" | "perf" | "cost_cny">> &
  Pick<TokenUsageRange, "coverage" | "perf" | "cost_cny"> {
  return {
    tokens: r?.tokens ?? 0,
    hit: r?.hit ?? 0,
    in: r?.in ?? 0,
    out: r?.out ?? 0,
    cr: r?.cr ?? 0,
    cw: r?.cw ?? 0,
    reason: r?.reason ?? 0,
    cost: r?.cost ?? 0,
    cost_cny: r?.cost_cny ?? null,
    credits: r?.credits ?? 0,
    requests: r?.requests ?? 0,
    sessions: r?.sessions ?? 0,
    models: r?.models ?? [],
    coverage: r?.coverage ?? null,
    perf: r?.perf ?? null,
  };
}

/** Mac 版 TokenUsageRange.totalTokens。 */
export function totalTokens(r: TokenUsageRange): number {
  const t = r.tokens ?? 0;
  return t > 0 ? t : (r.in ?? 0) + (r.out ?? 0) + (r.cr ?? 0) + (r.cw ?? 0) + (r.reason ?? 0);
}

/** 采集脚本 `--json` 的整份输出。各家的具体结构见各自的卡片文件。 */
export interface Usage {
  claude: ClaudeStat;
  codex: CodexStat;
  // 其余各家：gemini、grok、grok_bot、qoder、qoderwork、qodercli、qodercli_cn、hermes、
  // zcode、mimocode、openclaw、pi、prime_agent、workbuddy、workbuddy_ai、codebuddy、
  // deepseek_harness、opencode、qwencode、qwenwork、kimicode、musecode、cmdcode、devin、
  // minimax、antigravity、cursor、zed、sub2api、zai
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [provider: string]: any;
}
