// 额度曲线页里几个图表、列表共用的小部件：量宽度、图例、悬停气泡、迷你分段控件、时间格式。
// Mac 版用 Swift Charts，这里手写 SVG；样式数值照抄 QuotaHistoryView.swift。
import { useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { fill, fs, T } from "../../ui/theme";

export const MONO = "var(--mono)";
/** SwiftUI 的 .rounded 字体在 Windows 上没有对应，用界面字体。 */
export const ROUNDED = "var(--sans)";

/** 图表整体高度（含图例和横轴刻度），同 `.frame(height: 235)`。 */
export const CHART_HEIGHT = 235;

/** 网格线、刻度线的颜色（Color.white.opacity(x)）。 */
export const GRID_X = "rgba(255, 255, 255, 0.06)";
export const GRID_Y = "rgba(255, 255, 255, 0.08)";
export const AXIS_TICK = "rgba(255, 255, 255, 0.18)";

const pad = (n: number) => String(n).padStart(2, "0");

/** HH:mm（本地时区）。 */
export function hhmm(timestamp: number): string {
  const d = new Date(timestamp * 1000);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** MM-dd（本地时区）。 */
export function mmdd(timestamp: number): string {
  const d = new Date(timestamp * 1000);
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** 坐标轴上的日期：.dateTime.month(.twoDigits).day(.twoDigits) → MM/dd。 */
export function axisDate(timestamp: number): string {
  const d = new Date(timestamp * 1000);
  return `${pad(d.getMonth() + 1)}/${pad(d.getDate())}`;
}

/** yyyy-MM-dd（本地时区），与账本的日期 key 同格式。 */
export function dayKey(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function isToday(timestamp: number): boolean {
  return dayKey(new Date(timestamp * 1000)) === dayKey(new Date());
}

/** 等宽字体下一串字大约多宽（只用来留轴标签的位置、判断会不会出界）。 */
export function monoWidth(text: string, size: number): number {
  return text.length * size * 0.62;
}

/** 量一个容器的内容宽度，跟着窗口和字号变化。 */
export function useElementWidth<E extends HTMLElement>() {
  const ref = useRef<E>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () => setWidth(element.clientWidth);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

/** 图例：右上角一排「● 名称」（.chartLegend(position: .top, alignment: .trailing, spacing: 10)）。 */
export function ChartLegend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, height: legendHeight(), alignItems: "center" }}>
      {items.map((item) => (
        <span key={item.label} style={{ display: "flex", alignItems: "center", gap: 4, whiteSpace: "nowrap" }}>
          <span style={{ width: 6, height: 6, borderRadius: 3, background: item.color, flex: "none" }} />
          <span style={{ fontSize: fs(9.5), color: T.secondary }}>{item.label}</span>
        </span>
      ))}
    </div>
  );
}

export const legendHeight = () => Math.ceil(fs(9.5) * 1.4);
/** 图例和绘图区之间的间距。 */
export const LEGEND_GAP = 8;

/** 悬停气泡（深色圆角卡 + 细描边 + 投影），位置由调用方给。 */
export function HoverBubble({ width, left, top, children }: { width: number; left: number; top: number; children: ReactNode }) {
  return (
    <div
      style={{
        position: "absolute",
        left,
        top,
        width,
        padding: "6px 7px",
        borderRadius: 7,
        background: "rgba(26, 28, 36, 0.96)",
        boxShadow: "0 2px 10px rgba(0, 0, 0, 0.32), inset 0 0 0 0.75px rgba(255, 255, 255, 0.14)",
        display: "flex",
        flexDirection: "column",
        gap: 3,
        pointerEvents: "none",
        zIndex: 2,
      }}
    >
      {children}
    </div>
  );
}

/** 气泡里的一行：色点 + 名称 + 右侧数值。 */
export function HoverRow({ color, title, value }: { color: string; title: string; value: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 4, minWidth: 0 }}>
      <span style={{ width: 5, height: 5, borderRadius: 2.5, background: color, flex: "none" }} />
      <span style={{ fontSize: fs(9), color: T.secondary, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 }}>
        {title}
      </span>
      <span style={{ flex: 1, minWidth: 4 }} />
      <span style={{ fontSize: fs(9.5), fontWeight: 600, fontFamily: MONO, color: T.primary, whiteSpace: "nowrap" }}>{value}</span>
    </div>
  );
}

/** 迷你分段控件（.pickerStyle(.segmented).controlSize(.mini)）。 */
export function MiniSegmented<V>({
  options,
  value,
  onChange,
  width,
}: {
  options: { value: V; label: string }[];
  value: V;
  onChange: (value: V) => void;
  width: number;
}) {
  return (
    <div className="segmented" style={{ width, flex: "none", padding: 2, borderRadius: 7, background: fill(0.06) }}>
      {options.map((option, index) => (
        <button
          key={index}
          className={`segment${Object.is(option.value, value) ? " on" : ""}`}
          style={{
            fontSize: fs(10),
            padding: "2px 0",
            borderRadius: 5,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
            minWidth: 0,
          }}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/**
 * 同一列里按最宽的那段文字留宽度（SwiftUI 里叠一层 hidden 文本的做法）：
 * 几段样本文字和真正的内容叠在同一个网格格子里，格子按最宽的撑开。
 */
export function WidestOf({ samples, style, children }: { samples: string[]; style?: CSSProperties; children: ReactNode }) {
  return (
    <span style={{ display: "inline-grid", flex: "none", ...style }}>
      {samples.map((sample) => (
        <span key={sample} aria-hidden style={{ gridArea: "1 / 1", visibility: "hidden", whiteSpace: "nowrap" }}>
          {sample}
        </span>
      ))}
      <span style={{ gridArea: "1 / 1", whiteSpace: "nowrap" }}>{children}</span>
    </span>
  );
}

/** 一行文字超长时截断成「…」（lineLimit(1)）。 */
export const oneLine: CSSProperties = { whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 };

/** 纵轴自动刻度：取 1/2/2.5/5 × 10^n 的步长，大约 4 格。 */
export function niceTicks(maximum: number, target = 4): number[] {
  if (!(maximum > 0)) return [0];
  const raw = maximum / target;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= raw) ?? 10 * magnitude;
  const ticks: number[] = [];
  for (let value = 0; value <= maximum + step * 1e-9; value += step) ticks.push(value);
  if (ticks[ticks.length - 1] < maximum) ticks.push(ticks[ticks.length - 1] + step);
  return ticks;
}
