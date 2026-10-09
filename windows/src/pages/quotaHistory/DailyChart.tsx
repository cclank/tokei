// 长跨度（1月 / 1年）下画每日真实 token 消耗的堆叠柱状图（Mac 版 QuotaDailyChart）：
// 额度百分比快照只保留 7 天，月 / 年区间没有曲线可画。
import { useState, type MouseEvent } from "react";
import * as Fmt from "../../lib/fmt";
import { L } from "../../lib/i18n";
import { fs, rgba, T, Theme } from "../../ui/theme";
import {
  axisDate,
  CHART_HEIGHT,
  ChartLegend,
  dayKey,
  GRID_X,
  GRID_Y,
  HoverBubble,
  HoverRow,
  LEGEND_GAP,
  legendHeight,
  MONO,
  monoWidth,
  niceTicks,
  useElementWidth,
} from "./chartKit";
import { dailyTotal, type QuotaDailyPoint } from "./detail";

const BUBBLE_WIDTH = 150;

const TOOLS = [
  { name: "Claude Code", color: rgba(Theme.claude), value: (p: QuotaDailyPoint) => p.c },
  { name: "Codex", color: rgba(Theme.codex), value: (p: QuotaDailyPoint) => p.x },
  { name: "Grok", color: rgba(Theme.grok), value: (p: QuotaDailyPoint) => p.g },
];

/** "2026-10-09" → 本地零点的 Date。 */
function parseDay(key: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(key);
  return match ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : null;
}

/** 两个本地零点之间差几天（夏令时那天不是整 24 小时，取整）。 */
const daysBetween = (a: Date, b: Date) => Math.round((b.getTime() - a.getTime()) / 86_400_000);

export function QuotaDailyChart({ points }: { points: QuotaDailyPoint[] }) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const [hover, setHover] = useState<QuotaDailyPoint | null>(null);

  const days = points
    .map((point) => ({ point, day: parseDay(point.d) }))
    .filter((item): item is { point: QuotaDailyPoint; day: Date } => item.day !== null);
  const firstDay = days.length ? days.reduce((min, item) => (item.day < min ? item.day : min), days[0].day) : new Date();
  const lastIndex = days.reduce((max, item) => Math.max(max, daysBetween(firstDay, item.day)), 0);
  const dayCount = lastIndex + 1;
  const dayAt = (index: number) => new Date(firstDay.getFullYear(), firstDay.getMonth(), firstDay.getDate() + index);

  const axisFont = fs(8.5);
  const yTicks = niceTicks(Math.max(0, ...days.map((item) => dailyTotal(item.point))));
  const yMax = yTicks[yTicks.length - 1] || 1;
  const yLabelWidth = Math.max(...yTicks.map((value) => monoWidth(Fmt.human(value), axisFont)));
  const plotTop = legendHeight() + LEGEND_GAP;
  const plotBottom = CHART_HEIGHT - Math.ceil(axisFont * 1.3) - 6;
  const plotLeft = Math.ceil(yLabelWidth) + 6;
  const plotRight = Math.max(plotLeft + 1, width - 1);
  const plotWidth = plotRight - plotLeft;
  const plotHeight = plotBottom - plotTop;
  const slot = plotWidth / dayCount;
  const barWidth = Math.max(1, slot * 0.8);
  const yOf = (tokens: number) => plotTop + (1 - tokens / yMax) * plotHeight;

  // .stride(by: .day, count: max(points.count / 8, 1))
  const stride = Math.max(Math.floor(points.length / 8), 1);
  const xTicks: number[] = [];
  for (let index = 0; index < dayCount; index += stride) xTicks.push(index);

  const onMove = (event: MouseEvent<SVGRectElement>) => {
    const svg = event.currentTarget.ownerSVGElement;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * width;
    const index = Math.floor((x - plotLeft) / slot);
    if (index < 0 || index >= dayCount) {
      setHover(null);
      return;
    }
    const key = dayKey(dayAt(index));
    setHover(points.find((point) => point.d === key) ?? null);
  };

  return (
    <div ref={ref} style={{ position: "relative", height: CHART_HEIGHT, minWidth: 0 }}>
      <div style={{ position: "absolute", left: 0, right: 0, top: 0 }}>
        <ChartLegend items={TOOLS.map((tool) => ({ label: tool.name, color: tool.color }))} />
      </div>
      {width > 0 && (
        <svg width={width} height={CHART_HEIGHT} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          {yTicks.map((value) => (
            <g key={`y${value}`}>
              <line x1={plotLeft} x2={plotRight} y1={yOf(value)} y2={yOf(value)} stroke={GRID_Y} strokeWidth={1} />
              <text
                x={plotLeft - 5}
                y={yOf(value)}
                textAnchor="end"
                dominantBaseline="central"
                fontSize={axisFont}
                fontFamily={MONO}
                fill={T.tertiary}
              >
                {Fmt.human(value)}
              </text>
            </g>
          ))}
          {xTicks.map((index) => {
            const x = plotLeft + index * slot;
            const label = axisDate(dayAt(index).getTime() / 1000);
            const fits = x + 2 + monoWidth(label, axisFont) <= width;
            return (
              <g key={`x${index}`}>
                <line x1={x} x2={x} y1={plotTop} y2={plotBottom} stroke={GRID_X} strokeWidth={1} />
                {fits && (
                  <text x={x + 2} y={plotBottom + 4} dominantBaseline="hanging" fontSize={axisFont} fontFamily={MONO} fill={T.tertiary}>
                    {label}
                  </text>
                )}
              </g>
            );
          })}
          {days.map(({ point, day }) => {
            const x = plotLeft + daysBetween(firstDay, day) * slot + (slot - barWidth) / 2;
            let base = 0;
            return (
              <g key={point.d}>
                {TOOLS.map((tool) => {
                  const tokens = tool.value(point);
                  if (tokens <= 0) return null;
                  const top = yOf(base + tokens);
                  const bottom = yOf(base);
                  base += tokens;
                  return <rect key={tool.name} x={x} y={top} width={barWidth} height={Math.max(0, bottom - top)} fill={tool.color} />;
                })}
              </g>
            );
          })}
          <rect
            x={plotLeft}
            y={plotTop}
            width={plotWidth}
            height={Math.max(0, plotHeight)}
            fill="transparent"
            onMouseMove={onMove}
            onMouseLeave={() => setHover(null)}
          />
        </svg>
      )}
      {hover && (
        <HoverBubble width={BUBBLE_WIDTH} left={plotLeft + 6} top={plotTop + 4}>
          <span style={{ fontSize: fs(9.5), fontWeight: 600, fontFamily: MONO, color: T.primary }}>{hover.d}</span>
          {TOOLS.map((tool) => (
            <HoverRow key={tool.name} color={tool.color} title={tool.name} value={Fmt.human(tool.value(hover))} />
          ))}
          <span style={{ fontSize: fs(8.5), fontFamily: MONO, color: T.tertiary }}>{L("合计 %@", Fmt.grouped(dailyTotal(hover)))}</span>
        </HoverBubble>
      )}
    </div>
  );
}
