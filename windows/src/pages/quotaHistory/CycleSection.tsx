// 「一个周额度用了多少」：当前周期 + 过去几个周期（Mac 版 QuotaHistoryView 的 cycleSection）。
import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import * as Fmt from "../../lib/fmt";
import { data, L } from "../../lib/i18n";
import { Card, HStack, Spacer, VStack } from "../../ui/kit";
import { fs, rgba, T, Theme, type RGB } from "../../ui/theme";
import { MiniSegmented, MONO, oneLine, ROUNDED, WidestOf } from "./chartKit";
import { cycleDurationDays, deviceBreakdown, projectedTotal, type QuotaCycle, type QuotaDetailSnapshot } from "./detail";

const COLLAPSED_CYCLE_LIMIT = 8;
/** 有周期数据的工具按固定顺序排，免得刷新一次卡片就换个位置。 */
const CYCLE_TOOL_ORDER = ["claude", "codex", "grok"];

export function cycleName(tool: string): string {
  switch (tool) {
    case "claude":
      return "Claude Code";
    case "grok":
      return "Grok";
    default:
      return "Codex";
  }
}

export function cycleTint(tool: string): RGB {
  switch (tool) {
    case "claude":
      return Theme.claude;
    case "grok":
      return Theme.grok;
    default:
      return Theme.codex;
  }
}

function missingHint(tool: string): string {
  switch (tool) {
    case "claude":
      return L("Claude Code 还没有周额度卡片：可打开 Claude Desktop 的 Usage 页面，") + L("或在设置的「隐私与额度」开启 Claude Code CLI 额度查询。");
    case "grok":
      return L("Grok 还没有周额度卡片：登录一次 grok.com 让 Tokei 抓到额度读数。");
    default:
      return L("Codex 还没有周额度卡片：跑一次 codex 让它刷新额度读数。");
  }
}

function CyclePlaceholder({ text }: { text: string }) {
  return (
    <div style={{ height: 58, display: "grid", placeItems: "center", textAlign: "center", fontSize: fs(11), color: T.tertiary }}>{text}</div>
  );
}

function CycleProgress({ used, tint }: { used: number; tint: RGB }) {
  const ratio = Math.min(Math.max(used, 0), 100) / 100;
  return (
    <HStack gap={8}>
      <div style={{ flex: 1, height: 7, borderRadius: 3.5, background: "rgba(255, 255, 255, 0.08)", position: "relative", overflow: "hidden" }}>
        <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${ratio * 100}%`, borderRadius: 3.5, background: rgba(tint, 0.85) }} />
      </div>
      <span
        style={{
          fontSize: fs(10),
          fontWeight: 600,
          fontFamily: MONO,
          color: T.secondary,
          whiteSpace: "nowrap",
          minWidth: 62,
          textAlign: "right",
          flex: "none",
        }}
      >
        {L("已用 %@%%", used.toFixed(0))}
      </span>
    </HStack>
  );
}

function CycleCard({ cycle }: { cycle: QuotaCycle }) {
  const tint = cycleTint(cycle.tool);
  const projected = projectedTotal(cycle);
  const breakdown = deviceBreakdown(cycle);
  return (
    <VStack gap={9}>
      <HStack gap={8} align="baseline">
        <span style={{ fontSize: fs(12), fontWeight: 700, color: rgba(tint), whiteSpace: "nowrap" }}>{L("%@ 周额度", cycleName(cycle.tool))}</span>
        <Spacer />
        <span style={{ fontSize: fs(9.5), color: T.tertiary, whiteSpace: "nowrap" }}>{L("%@ 后回满", Fmt.countdown(cycle.end))}</span>
      </HStack>
      {cycle.used_pct != null && <CycleProgress used={cycle.used_pct} tint={tint} />}
      <HStack gap={8} align="baseline">
        <VStack gap={2}>
          <span style={{ fontSize: fs(9.5), color: T.tertiary }}>{L("这个周期已经用了")}</span>
          <HStack gap={7} align="baseline">
            <span style={{ fontSize: fs(25), fontWeight: 700, fontFamily: ROUNDED, color: T.primary, whiteSpace: "nowrap" }}>
              {(cycle.approx ? "≈" : "") + Fmt.human(cycle.tokens)}
            </span>
            <span style={{ fontSize: fs(10), color: T.tertiary }}>tokens</span>
          </HStack>
          <span style={{ fontSize: fs(9.5), fontFamily: MONO, color: T.tertiary }}>{Fmt.grouped(cycle.tokens)}</span>
        </VStack>
        <Spacer />
        {projected != null && (
          <VStack gap={2} style={{ alignItems: "flex-end" }}>
            <span style={{ fontSize: fs(9.5), color: T.tertiary, whiteSpace: "nowrap" }}>{L("照这个用法，整个周期约")}</span>
            <span style={{ fontSize: fs(17), fontWeight: 700, fontFamily: ROUNDED, color: T.secondary, whiteSpace: "nowrap" }}>
              {Fmt.human(projected)}
            </span>
          </VStack>
        )}
      </HStack>
      {breakdown.length > 1 && (
        <span style={{ fontSize: fs(9), fontFamily: MONO, color: T.tertiary, ...oneLine }}>
          {breakdown.map((item) => `${data(item.name)} ${Fmt.human(item.tokens)}`).join("  ·  ")}
        </span>
      )}
    </VStack>
  );
}

function CompletedCycles({
  tool,
  cycles,
  compactTitle,
  expanded,
  onToggle,
}: {
  tool: string;
  cycles: QuotaCycle[];
  compactTitle: boolean;
  expanded: boolean;
  onToggle: () => void;
}) {
  const tint = cycleTint(tool);
  const peak = Math.max(Math.max(...cycles.map((cycle) => cycle.tokens), 1), 1);
  const uneven = cycles.some((cycle) => cycleDurationDays(cycle) < 6.5);
  const visible = expanded ? cycles : cycles.slice(0, COLLAPSED_CYCLE_LIMIT);
  const hiddenCount = Math.max(0, cycles.length - COLLAPSED_CYCLE_LIMIT);
  // 按最宽的「用到100%」留列宽：译文（使用率 100%）更长，写死宽度会截断
  const usedSample = L("用到%@%%", "100");
  return (
    <VStack gap={6}>
      <span style={{ fontSize: fs(11), fontWeight: 600, color: T.secondary }}>
        {compactTitle ? L("过去几个周期") : L("%@ 过去几个周期", cycleName(tool))}
      </span>
      {uneven && (
        <span style={{ fontSize: fs(9), color: T.tertiary }}>{L("不足 7 天的是重置时间被提前重锚，额度提前回满，长度不一样不能直接比。")}</span>
      )}
      {visible.map((cycle) => (
        <HStack key={`${cycle.tool}-${cycle.start}`} gap={8}>
          <span style={{ fontSize: fs(9.5), fontFamily: MONO, color: T.tertiary, width: 92, flex: "none", whiteSpace: "nowrap" }}>
            {`${Fmt.day(cycle.start)} → ${Fmt.day(cycle.end)}`}
          </span>
          <span style={{ fontSize: fs(9.5), fontFamily: MONO, color: T.tertiary, width: 38, flex: "none", textAlign: "right", whiteSpace: "nowrap" }}>
            {L("%@天", cycleDurationDays(cycle).toFixed(1))}
          </span>
          <div style={{ flex: 1, height: 7, minWidth: 0, position: "relative" }}>
            <div
              style={{
                position: "absolute",
                left: 0,
                top: 0,
                bottom: 0,
                width: `${(cycle.tokens / peak) * 100}%`,
                borderRadius: 3.5,
                background: rgba(tint, 0.55),
              }}
            />
          </div>
          <span
            style={{
              fontSize: fs(11),
              fontWeight: 600,
              fontFamily: ROUNDED,
              color: T.secondary,
              width: 52,
              flex: "none",
              textAlign: "right",
              whiteSpace: "nowrap",
            }}
          >
            {(cycle.approx ? "≈" : "") + Fmt.human(cycle.tokens)}
          </span>
          <span style={{ fontSize: fs(9), fontFamily: MONO, color: T.tertiary, minWidth: 52, flex: "none", textAlign: "right" }}>
            <WidestOf samples={[usedSample]}>{cycle.used_pct != null ? L("用到%@%%", cycle.used_pct.toFixed(0)) : "—"}</WidestOf>
          </span>
        </HStack>
      ))}
      {hiddenCount > 0 && (
        <button
          className="plain"
          onClick={onToggle}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 5,
            width: "100%",
            paddingTop: 2,
            fontSize: fs(9.5),
            fontWeight: 600,
            color: rgba(tint, 0.9),
          }}
        >
          {expanded ? <ChevronUp size={fs(9.5)} strokeWidth={2.6} /> : <ChevronDown size={fs(9.5)} strokeWidth={2.6} />}
          <span>{expanded ? L("收起更早周期") : L("查看更早的 %@ 个周期", hiddenCount)}</span>
        </button>
      )}
    </VStack>
  );
}

export function CycleSection({ detail }: { detail: QuotaDetailSnapshot }) {
  const [cycleTool, setCycleTool] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const payload = detail.payload;
  const allCycles = payload?.cycles ?? [];
  const present = new Set(allCycles.map((cycle) => cycle.tool));
  const cycleTools = CYCLE_TOOL_ORDER.filter((tool) => present.has(tool));
  const visibleTools = cycleTool && cycleTools.includes(cycleTool) ? [cycleTool] : cycleTools;

  let subtitle = L("从上次额度回满算到下次回满");
  if (payload && payload.devices.length > 1) subtitle += L(" · %@ 台设备已合并", payload.devices.length);
  // 首屏是上次落盘的缓存，刷新完会自己变，标出来免得误当成实时值。
  if (detail.refreshing && payload) subtitle += L(" · 更新中");

  const toggle = (tool: string) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(tool)) next.delete(tool);
      else next.add(tool);
      return next;
    });

  const group = (tool: string) => {
    const current = allCycles.find((cycle) => cycle.tool === tool && cycle.current);
    const past = allCycles.filter((cycle) => cycle.tool === tool && !cycle.current).sort((a, b) => b.start - a.start);
    const tint = cycleTint(tool);
    const history = (compactTitle: boolean) => (
      <CompletedCycles tool={tool} cycles={past} compactTitle={compactTitle} expanded={expanded.has(tool)} onToggle={() => toggle(tool)} />
    );
    if (current) {
      return (
        <Card key={tool} tint={tint}>
          <VStack gap={12}>
            <CycleCard cycle={current} />
            {past.length > 0 && (
              <>
                <div style={{ height: 1, background: rgba(tint, 0.18), flex: "none" }} />
                {history(true)}
              </>
            )}
          </VStack>
        </Card>
      );
    }
    if (past.length) {
      return (
        <Card key={tool} tint={tint}>
          {history(false)}
        </Card>
      );
    }
    return null;
  };

  return (
    <VStack gap={10}>
      <HStack gap={10} align="baseline">
        <VStack gap={2}>
          <span style={{ fontSize: fs(14), fontWeight: 700, color: T.primary }}>{L("一个周额度用了多少")}</span>
          <span style={{ fontSize: fs(9.5), color: T.tertiary }}>{subtitle}</span>
        </VStack>
        <Spacer />
        {cycleTools.length > 1 && (
          <MiniSegmented
            width={54 * (cycleTools.length + 1) + 24}
            value={cycleTool && cycleTools.includes(cycleTool) ? cycleTool : null}
            onChange={setCycleTool}
            options={[{ value: null as string | null, label: L("全部") }, ...cycleTools.map((tool) => ({ value: tool as string | null, label: cycleName(tool) }))]}
          />
        )}
      </HStack>
      {!payload ? (
        <Card tint={Theme.codex}>
          <CyclePlaceholder text={L("正在读取周额度…")} />
        </Card>
      ) : visibleTools.length === 0 ? (
        <Card tint={Theme.codex}>
          <CyclePlaceholder text={L("所有订阅的额度重置时间都拿不到，定位不了周期")} />
        </Card>
      ) : (
        visibleTools.map(group)
      )}
      {cycleTool === null &&
        (payload?.missing ?? []).map((tool) => (
          <span key={tool} style={{ fontSize: fs(9), color: T.tertiary }}>
            {missingHint(tool)}
          </span>
        ))}
    </VStack>
  );
}
