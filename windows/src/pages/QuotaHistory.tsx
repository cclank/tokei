// 额度曲线页（Mac 版 QuotaHistoryView，按已提交的版本移植）：
// 周额度周期 → 额度轨迹（剩余额度阶梯线 / 长跨度每日 token 柱状图）→ 每天用了多少额度 → 最近额度变化 → 模型活动标记。
import { useEffect, useMemo, useState } from "react";
import { L } from "../lib/i18n";
import { usePrefsVersion } from "../lib/prefs";
import { quotaHistoryPointsSince, useQuotaHistory } from "../lib/quotaHistory";
import { useUsageStore } from "../lib/store";
import { Card, HStack, Spacer, VStack } from "../ui/kit";
import { fs, T } from "../ui/theme";
import { dayKey, MiniSegmented } from "./quotaHistory/chartKit";
import { CycleSection } from "./quotaHistory/CycleSection";
import {
  ActivitySection,
  ChangesSection,
  DailyConsumptionSection,
  DailyTokensSection,
  QuotaEmptyState,
  QuotaSummary,
  seriesColor,
  toolTint,
} from "./quotaHistory/curveSections";
import { loadQuotaDetail, useQuotaDetail } from "./quotaHistory/detail";
import { dailyConsumption, projectQuotaHistory, QUOTA_HISTORY_TOOLS, type QuotaHistoryTool } from "./quotaHistory/projection";
import { QuotaHistoryChart } from "./quotaHistory/QuotaChart";

/** 跨度（小时）。 */
type QuotaHistorySpan = 1 | 6 | 24 | 168 | 720 | 8760;

const SPANS: QuotaHistorySpan[] = [1, 6, 24, 168, 720, 8760];

function spanLabel(span: QuotaHistorySpan): string {
  switch (span) {
    case 1:
      return "1h";
    case 6:
      return "6h";
    case 24:
      return "24h";
    case 168:
      return L("1周");
    case 720:
      return L("1月");
    default:
      return L("1年");
  }
}

function axisStride(span: QuotaHistorySpan): number {
  switch (span) {
    case 1:
      return 1;
    case 6:
      return 2;
    case 24:
      return 6;
    default:
      return 24;
  }
}

/** 额度% 快照只留 7 天，再长的跨度没有曲线可画，改用账本里的每日消耗。 */
const showsDailyTokens = (span: QuotaHistorySpan) => span === 720 || span === 8760;
const spanDays = (span: QuotaHistorySpan) => Math.max(Math.floor(span / 24), 1);

function Controls({
  tool,
  setTool,
  span,
  setSpan,
}: {
  tool: QuotaHistoryTool;
  setTool: (tool: QuotaHistoryTool) => void;
  span: QuotaHistorySpan;
  setSpan: (span: QuotaHistorySpan) => void;
}) {
  const daily = showsDailyTokens(span);
  return (
    <HStack gap={10}>
      <VStack gap={2}>
        <span style={{ fontSize: fs(14), fontWeight: 700, color: T.primary, whiteSpace: "nowrap" }}>{L("额度轨迹")}</span>
        <span style={{ fontSize: fs(9.5), color: T.tertiary }}>{daily ? L("按天聚合 · 真实 token 消耗") : L("按分钟聚合 · 剩余额度")}</span>
      </VStack>
      <Spacer />
      {!daily && (
        <MiniSegmented width={164} value={tool} onChange={setTool} options={QUOTA_HISTORY_TOOLS.map((value) => ({ value, label: value }))} />
      )}
      <MiniSegmented width={216} value={span} onChange={setSpan} options={SPANS.map((value) => ({ value, label: spanLabel(value) }))} />
    </HStack>
  );
}

function QuotaCurveSection({ tool, span }: { tool: QuotaHistoryTool; span: QuotaHistorySpan }) {
  const points = useQuotaHistory();
  const now = Date.now() / 1000;
  const start = now - span * 3600;
  // 点都在整分钟上，按「起点向上取整到分钟」缓存，过滤结果与按精确起点过滤一致
  const startMinute = Math.ceil(start / 60) * 60;
  const projection = useMemo(
    () => projectQuotaHistory(quotaHistoryPointsSince(points, startMinute), tool),
    [points, tool, startMinute],
  );
  // 每天用了多少额度取本机留着的全部快照（最多 7 天），不跟着跨度走，否则选 24h 时只剩今天和半个昨天
  const daily = useMemo(() => dailyConsumption(points, tool), [points, tool]);
  const colors = Object.fromEntries(projection.windowNames.map((window) => [window, seriesColor(tool, window)]));
  return (
    <>
      <Card tint={toolTint(tool)}>
        <VStack gap={12}>
          <QuotaSummary projection={projection} tool={tool} />
          {projection.lineData.length === 0 ? (
            <QuotaEmptyState tool={tool} />
          ) : (
            <QuotaHistoryChart
              projection={projection}
              start={start}
              end={now}
              span={{ axisStride: axisStride(span), axisShowsDate: span >= 168 }}
              colors={colors}
            />
          )}
        </VStack>
      </Card>
      <DailyConsumptionSection daily={daily} tool={tool} />
      <ChangesSection projection={projection} tool={tool} />
      <ActivitySection projection={projection} />
    </>
  );
}

export default function QuotaHistoryPage() {
  usePrefsVersion();
  // 每次刷新后重渲染一次，让横轴的「现在」跟着走
  useUsageStore();
  const detail = useQuotaDetail();
  const [tool, setTool] = useState<QuotaHistoryTool>("Claude Code");
  const [span, setSpan] = useState<QuotaHistorySpan>(24);

  useEffect(() => {
    loadQuotaDetail(true);
  }, []);

  // 账本只存有用量的日子，按行数取后 N 条会跨出区间，必须按日期截断
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - (spanDays(span) - 1));
  const cutoffKey = dayKey(cutoff);
  const recentDaily = (detail.payload?.daily ?? []).filter((point) => point.d >= cutoffKey);

  return (
    <VStack gap={13}>
      <CycleSection detail={detail} />
      <Controls tool={tool} setTool={setTool} span={span} setSpan={setSpan} />
      {showsDailyTokens(span) ? <DailyTokensSection points={recentDaily} /> : <QuotaCurveSection tool={tool} span={span} />}
      <span style={{ fontSize: fs(9.5), color: T.tertiary }}>
        {showsDailyTokens(span)
          ? L("长跨度画的是每日真实 token 消耗，已合并所有设备的账本（CLI 清理旧日志也不缩水）；额度百分比快照只保留 7 天，画不了这么长。")
          : L(
              "额度曲线来自本机定时快照；每日用量是当天剩余额度下降之和，回满不抵扣，当天有一头没采到的标「约」；模型标记来自同一分钟内本地会话 token 增量，仅表示相关活动，不等同于官方逐模型扣费归因。",
            )}
      </span>
    </VStack>
  );
}
