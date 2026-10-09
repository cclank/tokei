// 数据面板（Mac 版 DashboardView）：回顾、模型用量、账号 Provider 模型、项目排行、活跃热力。
// 数据来自采集脚本 `--dashboard --period <p>`，按时间段缓存在 dashboard/repository.ts。
import { useEffect, useRef, useState } from "react";
import { usePrefsVersion } from "../lib/prefs";
import { useUsageStore } from "../lib/store";
import { getRange, type TokenModelStat, type TokenUsageRange, type Usage } from "../lib/types";
import { HeatmapSection } from "./dashboard/Heatmap";
import { cachedDashboard, loadDashboard, useDashboardVersion } from "./dashboard/repository";
import { FaintDivider, ModelSection, ProjectsSection, ProviderModelSection } from "./dashboard/Sections";
import { DashboardStyles } from "./dashboard/styles";
import { rangeKeyFor, type DashboardPayload, type ModelCost, type WrappedPeriod } from "./dashboard/types";
import { WrappedView } from "./dashboard/Wrapped";

/**
 * Grok Bot 的模型行跟着面板的额度数据走（usage.grok_bot.quota.usage），与额度卡片保持一致；
 * 拿不到账号用量时退回 `--dashboard` 自带的 grok_bot 行（grokBotModelsForCurrentScope）。
 */
function grokBotModels(usage: Usage | null, period: WrappedPeriod, base: ModelCost[]): ModelCost[] {
  const ranges = usage?.grok_bot?.quota?.usage?.ranges;
  if (!ranges) return base.filter((m) => m.tool === "grok_bot");
  const range = getRange<TokenUsageRange>(ranges, rangeKeyFor(period), {});
  return (range.models ?? []).map((model: TokenModelStat) => {
    const input = model.in ?? 0;
    const out = model.out ?? 0;
    const cr = model.cr ?? 0;
    const cw = model.cw ?? 0;
    const reason = model.reason ?? 0;
    const tokens = model.tokens ?? input + out + cr + cw + reason;
    const outputThousands = out / 1_000;
    return {
      name: model.name,
      cost: model.cost ?? 0,
      tool: "grok_bot",
      in: input,
      out,
      cr,
      cw,
      reason,
      tokens,
      cost_per_k: outputThousands > 0 ? (model.cost ?? 0) / outputThousands : 0,
      out_ratio: tokens > 0 ? (out / tokens) * 100 : 0,
    };
  });
}

export default function DashboardPage() {
  const { usage } = useUsageStore();
  usePrefsVersion();
  const dashboardVersion = useDashboardVersion();
  const [period, setPeriod] = useState<WrappedPeriod>("all");
  const [base, setBase] = useState<DashboardPayload | null>(() => cachedDashboard("all"));
  const periodRef = useRef(period);
  periodRef.current = period;

  // 当前时间段的数据到了就换上；新时间段还没到时先留着上一份。
  useEffect(() => {
    const payload = cachedDashboard(period);
    if (payload) setBase(payload);
  }, [dashboardVersion, period]);

  // 打开时和每次主刷新完成后强制重载：账号 Provider 的模型天数由主刷新写入，
  // 跟着重算才能和额度卡片对得上（Mac 版 onReceive(store.$usage)）。
  useEffect(() => {
    loadDashboard(periodRef.current, true);
  }, [usage]);

  const changePeriod = (next: WrappedPeriod) => {
    setPeriod(next);
    loadDashboard(next);
  };

  if (!base) {
    return (
      <>
        <DashboardStyles />
        <div style={{ height: 200, display: "grid", placeItems: "center" }}>
          <span className="spinner" />
        </div>
      </>
    );
  }

  const providerModels = (base.provider_models ?? []).filter((m) => m.tool !== "grok_bot");
  const models = base.models.filter((m) => m.tool !== "grok_bot").concat(grokBotModels(usage, period, base.models));
  const daily = base.daily;
  const wrapped = base.wrapped;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, minWidth: 0 }}>
      <DashboardStyles />
      {wrapped.total_tokens > 0 && <WrappedView data={wrapped} period={period} onPeriodChange={changePeriod} />}
      {models.length > 0 && (
        <>
          <FaintDivider />
          <ModelSection models={models} />
        </>
      )}
      {providerModels.length > 0 && (
        <>
          <FaintDivider />
          <ProviderModelSection models={providerModels} />
        </>
      )}
      {daily.length > 0 && (
        <>
          {wrapped.projects.length > 0 && (
            <>
              <FaintDivider />
              <ProjectsSection projects={wrapped.projects} />
            </>
          )}
          <FaintDivider />
          <HeatmapSection daily={daily} />
        </>
      )}
    </div>
  );
}
