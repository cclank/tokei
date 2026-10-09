// 数据面板与回顾的 JSON 结构：采集脚本 `--dashboard --period <p>` 的输出
// （build_daily_costs 的 daily / models / provider_models，加 build_wrapped 的 wrapped），
// 对应 Mac 版 DashboardView.swift 的 DailyCost / ModelCost / DashboardPayload 与 WrappedView.swift 的 WrappedData。
import { L } from "../../lib/i18n";
import type { RangeKey } from "../../lib/types";

/** 回顾的时间段（WrappedPeriod），值就是传给采集脚本的 `--period`。 */
export type WrappedPeriod = "1d" | "7d" | "30d" | "365d" | "all";

export const WRAPPED_PERIODS: WrappedPeriod[] = ["1d", "7d", "30d", "365d", "all"];

/** WrappedPeriod.label。 */
export function wrappedPeriodLabel(period: WrappedPeriod): string {
  switch (period) {
    case "1d":
      return L("今日");
    case "7d":
      return L("本周");
    case "30d":
      return L("本月");
    case "365d":
      return L("今年");
    case "all":
      return L("全部");
  }
}

/** 时间段对应面板页签的区间（providerRangeKey / rangeKey(for:)）。 */
export function rangeKeyFor(period: WrappedPeriod): RangeKey {
  switch (period) {
    case "1d":
      return "today";
    case "7d":
      return "week";
    case "30d":
      return "month";
    case "365d":
      return "year";
    case "all":
      return "all";
  }
}

/** 一天的成本与各工具 token（DailyCost）。成本是美元，cost_cny / cny_by_tool 是原生人民币。 */
export interface DailyCost {
  date: string;
  claude: number;
  codex: number;
  codex_reserve?: number | null;
  gemini?: number | null;
  grok?: number | null;
  hermes?: number | null;
  openclaw?: number | null;
  zcode?: number | null;
  mimocode?: number | null;
  devin?: number | null;
  minimax?: number | null;
  pi?: number | null;
  prime_agent?: number | null;
  workbuddy?: number | null;
  workbuddy_ai?: number | null;
  codebuddy?: number | null;
  deepseek_harness?: number | null;
  qwencode?: number | null;
  kimicode?: number | null;
  musecode?: number | null;
  cmdcode?: number | null;
  cny_by_tool?: Record<string, number> | null;
  cost_cny?: number | null;
  total: number;
  c_in?: number;
  c_out?: number;
  c_cr?: number;
  c_cw?: number;
  x_in?: number;
  x_out?: number;
  x_cached?: number;
  x_reason?: number;
  xr_in?: number | null;
  xr_out?: number | null;
  xr_cached?: number | null;
  xr_reason?: number | null;
  p_in?: number;
  p_out?: number;
  p_cr?: number;
  p_cw?: number;
  p_reason?: number;
  pa_in?: number;
  pa_out?: number;
  pa_cr?: number;
  pa_cw?: number;
  pa_reason?: number;
  w_in?: number | null;
  w_out?: number | null;
  w_cr?: number | null;
  w_cw?: number | null;
  wa_in?: number | null;
  wa_out?: number | null;
  wa_cr?: number | null;
  wa_cw?: number | null;
  cb_in?: number | null;
  cb_out?: number | null;
  cb_cr?: number | null;
  cb_cw?: number | null;
  cb_credits?: number | null;
  d_in?: number | null;
  d_out?: number | null;
  d_cr?: number | null;
  d_cw?: number | null;
  d_reason?: number | null;
  q_in?: number | null;
  q_out?: number | null;
  q_cr?: number | null;
  q_reason?: number | null;
  g_in?: number | null;
  g_out?: number | null;
  g_cr?: number | null;
  g_reason?: number | null;
  tokens?: number;
}

/** 一个模型在区间内的合计（ModelCost）。name 已带「(Codex)」这类来源后缀。 */
export interface ModelCost {
  name: string;
  cost: number;
  cost_cny?: number | null;
  tool: string;
  in?: number | null;
  out?: number | null;
  cr?: number | null;
  cw?: number | null;
  reason?: number | null;
  credits?: number | null;
  tokens?: number | null;
  cost_per_k?: number;
  out_ratio?: number;
}

export interface WrappedAchievement {
  icon: string;
  title: string;
  desc: string;
  tint?: string;
  /** 带「亿」的描述另附原始数和模板，其他语言按 K / M / B 重写。 */
  tokens?: number | null;
  tokens_template?: string | null;
}

export interface WrappedProject {
  name: string;
  tokens: number;
  cost: number;
  cost_cny?: number | null;
}

export interface WrappedBusiest {
  date: string;
  tokens: number;
}

export interface WrappedModel {
  name: string;
  tokens: number;
}

export interface WrappedPeakDay {
  date: string;
  tokens: number;
  projects?: string[] | null;
}

export interface WrappedData {
  total_tokens: number;
  cost_cny?: number | null;
  total_cost: number;
  active_days: number;
  streak_max: number;
  streak_cur: number;
  busiest: WrappedBusiest;
  /** 老 JSON 缺字段时为空。 */
  peak_days?: WrappedPeakDay[] | null;
  /** 日期 → 当日项目（合并视图回填用）。 */
  day_projects?: Record<string, string[]> | null;
  top_model: WrappedModel;
  hours: number[];
  weekday: number[];
  projects: WrappedProject[];
  max_projs_day: number;
  night_share: number;
  first_day: string;
  achievements: WrappedAchievement[];
  period: string;
}

export interface DashboardPayload {
  daily: DailyCost[];
  models: ModelCost[];
  provider_models?: ModelCost[] | null;
  wrapped: WrappedData;
}

/** 缺字段时补成 Mac 版 WrappedData() 的默认值。 */
export function normalizeWrapped(raw: Partial<WrappedData> | null | undefined): WrappedData {
  const w = raw ?? {};
  return {
    total_tokens: w.total_tokens ?? 0,
    cost_cny: w.cost_cny ?? null,
    total_cost: w.total_cost ?? 0,
    active_days: w.active_days ?? 0,
    streak_max: w.streak_max ?? 0,
    streak_cur: w.streak_cur ?? 0,
    busiest: { date: w.busiest?.date ?? "", tokens: w.busiest?.tokens ?? 0 },
    peak_days: w.peak_days ?? null,
    day_projects: w.day_projects ?? null,
    top_model: { name: w.top_model?.name ?? "-", tokens: w.top_model?.tokens ?? 0 },
    hours: w.hours ?? [],
    weekday: w.weekday ?? [],
    projects: w.projects ?? [],
    max_projs_day: w.max_projs_day ?? 0,
    night_share: w.night_share ?? 0,
    first_day: w.first_day ?? "",
    achievements: w.achievements ?? [],
    period: w.period ?? "all",
  };
}

export function normalizePayload(raw: Partial<DashboardPayload>): DashboardPayload {
  return {
    daily: raw.daily ?? [],
    models: raw.models ?? [],
    provider_models: raw.provider_models ?? [],
    wrapped: normalizeWrapped(raw.wrapped),
  };
}
