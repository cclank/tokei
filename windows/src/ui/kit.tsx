// 卡片里复用的小部件，逐个对应 Mac 版 Design.swift 与 PanelView.swift 里的同名视图。
import { createContext, useContext, useState, type CSSProperties, type ReactNode } from "react";
import * as Fmt from "../lib/fmt";
import { L } from "../lib/i18n";
import type { PerfStat } from "../lib/types";
import { Icon } from "./Icon";
import { CARD_RADIUS, fill, fs, gradient, rgba, T, Theme, type RGB } from "./theme";

const MONO = "var(--mono)";

export function Card({ tint, children }: { tint: RGB; children: ReactNode }) {
  // 毛玻璃上的浮起卡片：淡色填充 + 左上到右下渐隐的描边 + 柔和投影（Design.swift Card）。
  const layer = (color: string) => `linear-gradient(${color}, ${color}) padding-box`;
  return (
    <div
      className="card"
      style={{
        borderRadius: CARD_RADIUS,
        border: "1px solid transparent",
        background: [
          "linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0) 50%) padding-box",
          layer(rgba(tint, 0.08)),
          layer("rgba(0,0,0,0.26)"),
          `linear-gradient(135deg, ${rgba(tint, 0.38)}, ${rgba(tint, 0.05)}) border-box`,
        ].join(", "),
      }}
    >
      {children}
    </div>
  );
}

export function VStack({ gap = 11, children, style }: { gap?: number; children: ReactNode; style?: CSSProperties }) {
  return <div style={{ display: "flex", flexDirection: "column", gap, minWidth: 0, ...style }}>{children}</div>;
}

export function HStack({
  gap = 6,
  align = "center",
  children,
  style,
}: {
  gap?: number;
  align?: CSSProperties["alignItems"];
  children: ReactNode;
  style?: CSSProperties;
}) {
  return <div style={{ display: "flex", alignItems: align, gap, minWidth: 0, ...style }}>{children}</div>;
}

export const Spacer = () => <div style={{ flex: 1, minWidth: 0 }} />;

export function Tip({ text, children }: { text?: string | null; children: ReactNode }) {
  return <span title={text || undefined} style={{ display: "contents" }}>{children}</span>;
}

/** 卡头：色点 + 名称 + 会话数徽标（+ 右侧的复制按钮由调用方给）。 */
/** 卡片列表给每张卡的卡头右侧按钮（复制此工具用量图），卡片自己不用管。 */
export const CardHeadTrailing = createContext<ReactNode>(null);

export function CardHead({
  title,
  tint,
  sessions = 0,
  trailing,
}: {
  title: string;
  tint: RGB;
  sessions?: number;
  trailing?: ReactNode;
}) {
  const provided = useContext(CardHeadTrailing);
  return (
    <HStack gap={7}>
      <span
        style={{
          width: 8,
          height: 8,
          borderRadius: 4,
          background: gradient(tint),
          boxShadow: `0 0 3px ${rgba(tint, 0.6)}`,
          flex: "none",
        }}
      />
      <span style={{ fontSize: fs(14), fontWeight: 700, color: T.primary, whiteSpace: "nowrap" }}>{title}</span>
      {sessions > 0 && (
        <span
          style={{
            fontSize: fs(10),
            fontWeight: 700,
            color: rgba(tint),
            padding: "1.5px 5px",
            borderRadius: 999,
            background: rgba(tint, 0.12),
          }}
        >
          {sessions}
        </span>
      )}
      <Spacer />
      {trailing ?? provided}
    </HStack>
  );
}

/** 大号总量 + 区间说明（CostHeadline）。 */
export function CostHeadline({ value, caption }: { value: string; caption: string }) {
  return (
    <HStack gap={7} align="baseline">
      <span style={{ fontSize: fs(23), fontWeight: 700, color: "#fff", fontVariantNumeric: "tabular-nums" }}>{value}</span>
      <span style={{ fontSize: fs(10), color: T.tertiary }}>{caption}</span>
    </HStack>
  );
}

export interface Metric {
  icon: string;
  label: string;
  value: string;
  help?: string;
}

export const metric = (icon: string, label: string, value: string, help?: string): Metric => ({
  icon,
  label,
  value,
  help,
});

export function MetricCell({ m, tint }: { m: Metric; tint: RGB }) {
  return (
    <div title={m.help} style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
      <span
        style={{
          width: 21,
          height: 21,
          borderRadius: 11,
          background: rgba(tint, 0.1),
          color: rgba(tint),
          display: "grid",
          placeItems: "center",
          flex: "none",
        }}
      >
        <Icon name={m.icon} size={fs(10.5)} strokeWidth={2.6} />
      </span>
      <div style={{ display: "flex", flexDirection: "column", gap: 1, minWidth: 0 }}>
        <span style={{ fontSize: fs(9.5), color: T.tertiary, display: "flex", alignItems: "center", gap: 3, whiteSpace: "nowrap" }}>
          {m.label}
          {m.help && <Icon name="info.circle" size={fs(8.5)} strokeWidth={2} />}
        </span>
        <span style={{ fontSize: fs(12.5), fontWeight: 600, fontFamily: MONO, color: T.primary, whiteSpace: "nowrap" }}>
          {m.value}
        </span>
      </div>
    </div>
  );
}

function Ring({ value, tint, size, line }: { value: number; tint: RGB; size: number; line: number }) {
  const r = (size - line) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0.001, Math.min(1, value / 100));
  return (
    <svg width={size} height={size} style={{ flex: "none", transform: "rotate(-90deg)" }}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={fill(0.1)} strokeWidth={line} />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke={rgba(tint)}
        strokeWidth={line}
        strokeLinecap="round"
        strokeDasharray={`${c * pct} ${c}`}
      />
    </svg>
  );
}

export function RingMetricCell({ value, label, tint }: { value: number; label: string; tint: RGB }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
      <Ring value={value} tint={tint} size={21} line={2.5} />
      <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
        <span style={{ fontSize: fs(9.5), color: T.tertiary }}>{label}</span>
        <span style={{ fontSize: fs(12.5), fontWeight: 600, fontFamily: MONO, color: T.primary }}>
          {Math.round(value)}%
        </span>
      </div>
    </div>
  );
}

/** 两列指标格：top 在前，命中率环（hit>0 时）其后，再接 extra。 */
export function MetricGrid({ top = [], hit = 0, extra = [], tint }: { top?: Metric[]; hit?: number; extra?: Metric[]; tint: RGB }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", columnGap: 10, rowGap: 9 }}>
      {top.map((m, i) => (
        <MetricCell key={`t${i}`} m={m} tint={tint} />
      ))}
      {hit > 0 && <RingMetricCell value={hit} label="Cache Hit" tint={tint} />}
      {extra.map((m, i) => (
        <MetricCell key={`e${i}`} m={m} tint={tint} />
      ))}
    </div>
  );
}

export const ThinDivider = () => <div style={{ height: 1, background: fill(0.08), flex: "none" }} />;

export function MiniBar({ value, tint }: { value: number; tint: string }) {
  return (
    <div style={{ height: 5, borderRadius: 3, background: fill(0.09), position: "relative", overflow: "hidden" }}>
      <div
        style={{
          position: "absolute",
          inset: 0,
          width: `max(3px, ${Math.min(100, Math.max(0, value))}%)`,
          borderRadius: 3,
          background: tint,
          transition: "width 0.18s ease-out",
        }}
      />
    </div>
  );
}

/** 窗口重置时刻已过且读数过期：上次的百分比属于上一个窗口，只写「已重置」。 */
export function hasResetSinceReading(stale: boolean, reset?: number | null, now = Date.now()): boolean {
  return stale && reset != null && reset * 1000 <= now;
}

export function remainingLabel(remaining: number): string {
  const clamped = Math.min(100, Math.max(0, remaining));
  return clamped < 0.5 ? L("已用尽") : `${clamped.toFixed(0)}%`;
}

/** 一行额度（剩余百分比 + 重置时刻 + 细进度条）。 */
export function QuotaRow({
  title,
  pct,
  detail,
  reset,
  tint,
  stale = false,
}: {
  title: string;
  pct: number;
  detail?: string | null;
  reset?: number | null;
  tint: RGB;
  stale?: boolean;
}) {
  const low = pct <= 15 && !stale;
  const resetSince = hasResetSinceReading(stale, reset);
  const help = resetSince
    ? L("窗口已在 %@ 重置，还没读到新窗口的额度", Fmt.reset(reset))
    : stale
      ? L("上次读到的额度，尚未刷新")
      : reset != null
        ? L("%@ 后重置", Fmt.countdown(reset))
        : "";
  return (
    <div title={help || undefined} style={{ display: "flex", flexDirection: "column", gap: 4, opacity: stale ? 0.65 : 1 }}>
      <HStack gap={6}>
        <span style={{ fontSize: fs(11), color: T.secondary, whiteSpace: "nowrap" }}>{title}</span>
        {detail && <span style={{ fontSize: fs(10), fontFamily: MONO, color: T.tertiary }}>{detail}</span>}
        <Spacer />
        {resetSince ? (
          <span style={{ fontSize: fs(11), fontWeight: 600, color: T.tertiary }}>{L("已重置")}</span>
        ) : (
          <>
            <span
              style={{
                fontSize: fs(12),
                fontWeight: 600,
                fontFamily: MONO,
                color: low ? rgba(Theme.red) : stale ? T.tertiary : T.primary,
              }}
            >
              {remainingLabel(pct)}
            </span>
            {reset != null && (
              <span style={{ fontSize: fs(9.5), fontFamily: MONO, color: T.tertiary, whiteSpace: "nowrap" }}>
                · {Fmt.reset(reset)}
              </span>
            )}
          </>
        )}
      </HStack>
      {!resetSince && <MiniBar value={pct} tint={low ? rgba(Theme.red) : gradient(tint, stale ? 0.4 : 1)} />}
    </div>
  );
}

export function EmptyHint() {
  return <span style={{ fontSize: fs(10), color: T.tertiary }}>{L("暂无数据")}</span>;
}

/** 空态：刷新中 / 真的没有，两者必须能分辨（UsageEmptyState）。 */
export function UsageEmptyHint({ rangeLabel, refreshing, recent }: { rangeLabel: string; refreshing: boolean; recent?: string | null }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2, fontSize: fs(10), color: T.tertiary }}>
      {refreshing ? (
        <span>{L("正在刷新%@用量…", rangeLabel)}</span>
      ) : (
        <>
          <span>{L("%@暂无用量，额度状态如下", rangeLabel)}</span>
          {recent && <span>{L("最近一次 · %@", recent)}</span>}
        </>
      )}
    </div>
  );
}

export function QuotaStateNotice({
  title,
  detail,
  source,
  updated,
  tint,
  warning = false,
}: {
  title: string;
  detail: string;
  source: string;
  updated?: number | null;
  tint: RGB;
  warning?: boolean;
}) {
  const statusTint = warning ? Theme.orange : tint;
  const updatedLabel = updated != null ? L("上次更新 %@", Fmt.reset(updated)) : L("尚无更新时间");
  return (
    <div
      style={{
        padding: 9,
        borderRadius: 9,
        background: rgba(statusTint, 0.07),
        boxShadow: `inset 0 0 0 0.5px ${rgba(statusTint, 0.16)}`,
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      <HStack gap={6} style={{ color: rgba(statusTint, 0.95) }}>
        <Icon name={warning ? "exclamationmark.triangle.fill" : "info.circle.fill"} size={fs(11)} />
        <span style={{ fontSize: fs(11), fontWeight: 600 }}>{title}</span>
      </HStack>
      <span style={{ fontSize: fs(9.5), color: T.secondary }}>{detail}</span>
      <HStack gap={5} style={{ color: T.tertiary }}>
        <Icon name="clock" size={fs(9)} />
        <span style={{ fontSize: fs(9), fontFamily: MONO }}>
          {source} · {updatedLabel}
        </span>
      </HStack>
    </div>
  );
}

/** 读数过期时的落款：照常展示最后一次读数，这里只标一下是什么时候读到的。 */
export function StaleQuotaFootnote({ updated, help }: { updated?: number | null; help: string }) {
  return (
    <div title={help}>
      <HStack gap={5} style={{ color: T.tertiary }}>
        <Icon name="clock.arrow.circlepath" size={fs(9.5)} />
        <span style={{ fontSize: fs(9.5), fontFamily: MONO }}>
          {L("上次读到 · %@", updated != null ? Fmt.reset(updated) : L("更新时间未知"))}
        </span>
      </HStack>
    </div>
  );
}

export function LabeledBadge({ label, value, tint }: { label: string; value: string; tint: RGB }) {
  return (
    <HStack>
      <span style={{ fontSize: fs(11), color: T.tertiary }}>{label}</span>
      <Spacer />
      <span
        style={{
          fontSize: fs(10),
          fontWeight: 600,
          fontFamily: MONO,
          color: T.secondary,
          padding: "2px 7px",
          borderRadius: 999,
          background: rgba(tint, 0.16),
        }}
      >
        {value}
      </span>
    </HStack>
  );
}

/** 平均输出速度、TTFT 中位数两格，只在有样本时出现。 */
export function perfMetrics(perf: PerfStat | null | undefined, includeTTFT = true): Metric[] {
  if (!perf || !(perf.n > 0)) return [];
  const items: Metric[] = [
    metric(
      "gauge.medium",
      L("平均输出速度"),
      Fmt.tps(perf.tps),
      L("输出 token 总数 ÷ 生成总时长，来自 %@ 个请求；拿不到首字时间的请求按整个请求的耗时算", perf.n),
    ),
  ];
  if (includeTTFT && perf.ttft != null) {
    items.push(
      metric(
        "timer",
        L("TTFT 中位数"),
        Fmt.seconds(perf.ttft),
        L("首字延迟：从发出请求到收到第一个 token 的时间，%@ 个请求的中位数", perf.tn ?? perf.n),
      ),
    );
  }
  return items;
}

export function Disclosure({
  open,
  onToggle,
  label,
  tint,
}: {
  open: boolean;
  onToggle: () => void;
  label: string;
  tint: RGB;
}) {
  return (
    <button className="plain" onClick={onToggle} style={{ display: "flex", alignItems: "center", gap: 5, width: "100%" }}>
      <Icon name="chart.pie.fill" size={fs(10)} color={rgba(tint)} />
      <span style={{ fontSize: fs(11), fontWeight: 500, color: T.secondary }}>{label}</span>
      <Icon name={open ? "chevron.down" : "chevron.right"} size={fs(9)} color={T.tertiary} strokeWidth={3} />
    </button>
  );
}

export function useToggle(initial = false): [boolean, () => void] {
  const [value, setValue] = useState(initial);
  return [value, () => setValue((v) => !v)];
}
