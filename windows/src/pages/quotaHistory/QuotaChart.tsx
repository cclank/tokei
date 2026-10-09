// 剩余额度的阶梯折线图（Mac 版 QuotaHistoryChart）。悬停状态放在图表自己这里，
// 鼠标移动只重画图，不重算整页的投影。
import { useState, type MouseEvent } from "react";
import * as Fmt from "../../lib/fmt";
import { L } from "../../lib/i18n";
import { fs, T } from "../../ui/theme";
import {
  AXIS_TICK,
  axisDate,
  CHART_HEIGHT,
  ChartLegend,
  GRID_X,
  GRID_Y,
  hhmm,
  HoverBubble,
  HoverRow,
  LEGEND_GAP,
  legendHeight,
  MONO,
  monoWidth,
  oneLine,
  useElementWidth,
} from "./chartKit";
import { nearestHoverSample, type QuotaHistoryProjection, type QuotaHoverSample } from "./projection";

export interface QuotaChartSpan {
  /** 横轴刻度间隔（小时）。 */
  axisStride: number;
  /** 跨度超过一天时刻度标日期，免得满屏 00:00。 */
  axisShowsDate: boolean;
}

const Y_VALUES = [0, 25, 50, 75, 100];
const BUBBLE_WIDTH = 154;
const TICK_LENGTH = 4;

/** 落在 [start, end] 里、整点且小时数是 stride 倍数的时刻（.stride(by: .hour, count:)）。 */
function hourTicks(start: number, end: number, stride: number): number[] {
  const ticks: number[] = [];
  const first = new Date(start * 1000);
  first.setMinutes(0, 0, 0);
  let t = first.getTime() / 1000;
  if (t < start) t += 3600;
  for (; t <= end; t += 3600) {
    if (new Date(t * 1000).getHours() % stride === 0) ticks.push(t);
  }
  return ticks;
}

export function QuotaHistoryChart({
  projection,
  start,
  end,
  span,
  colors,
}: {
  projection: QuotaHistoryProjection;
  start: number;
  end: number;
  span: QuotaChartSpan;
  colors: Record<string, string>;
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const [hover, setHover] = useState<{ sample: QuotaHoverSample; x: number } | null>(null);

  const axisFont = fs(8.5);
  const plotTop = legendHeight() + LEGEND_GAP;
  const plotBottom = CHART_HEIGHT - Math.ceil(axisFont * 1.3) - TICK_LENGTH - 4;
  const plotLeft = Math.ceil(monoWidth("100%", axisFont)) + 6;
  const plotRight = Math.max(plotLeft + 1, width - 1);
  const plotWidth = plotRight - plotLeft;
  const plotHeight = plotBottom - plotTop;
  const duration = Math.max(1, end - start);
  const xOf = (timestamp: number) => plotLeft + ((timestamp - start) / duration) * plotWidth;
  const yOf = (remaining: number) => plotTop + (1 - remaining / 100) * plotHeight;
  const colorOf = (window: string) => colors[window] ?? "rgb(235, 133, 102)";

  const series = projection.windowNames.map((window) => {
    const data = projection.lineData.filter((datum) => datum.window === window);
    if (!data.length) return { window, path: "" };
    let path = `M${xOf(data[0].timestamp).toFixed(2)},${yOf(data[0].remaining).toFixed(2)}`;
    for (let i = 1; i < data.length; i++) {
      // .interpolationMethod(.stepEnd)：先保持上一个值走到下一个点的时刻，再竖着跳过去
      path += `H${xOf(data[i].timestamp).toFixed(2)}V${yOf(data[i].remaining).toFixed(2)}`;
    }
    return { window, path };
  });

  const ticks = hourTicks(start, end, span.axisStride);
  const tickLabel = (timestamp: number) => (span.axisShowsDate ? axisDate(timestamp) : hhmm(timestamp));

  const onMove = (event: MouseEvent<SVGRectElement>) => {
    const svg = event.currentTarget.ownerSVGElement;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * width;
    const time = start + ((x - plotLeft) / plotWidth) * duration;
    const sample = nearestHoverSample(projection.hoverSamples, time);
    setHover(sample ? { sample, x: xOf(sample.timestamp) } : null);
  };

  const rightmost = Math.max(plotLeft, plotRight - BUBBLE_WIDTH);
  const anchor = hover ? Math.min(Math.max(hover.x - BUBBLE_WIDTH / 2, plotLeft), rightmost) : 0;

  return (
    <div ref={ref} style={{ position: "relative", height: CHART_HEIGHT, minWidth: 0 }}>
      <div style={{ position: "absolute", left: 0, right: 0, top: 0 }}>
        <ChartLegend items={projection.windowNames.map((window) => ({ label: L(window), color: colorOf(window) }))} />
      </div>
      {width > 0 && (
        <svg width={width} height={CHART_HEIGHT} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          {Y_VALUES.map((value) => (
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
                {value}%
              </text>
            </g>
          ))}
          {ticks.map((timestamp) => {
            const x = xOf(timestamp);
            const label = tickLabel(timestamp);
            const fits = x + 2 + monoWidth(label, axisFont) <= width;
            return (
              <g key={`x${timestamp}`}>
                <line x1={x} x2={x} y1={plotTop} y2={plotBottom} stroke={GRID_X} strokeWidth={1} />
                <line x1={x} x2={x} y1={plotBottom} y2={plotBottom + TICK_LENGTH} stroke={AXIS_TICK} strokeWidth={1} />
                {fits && (
                  <text x={x + 2} y={plotBottom + TICK_LENGTH + 2} dominantBaseline="hanging" fontSize={axisFont} fontFamily={MONO} fill={T.tertiary}>
                    {label}
                  </text>
                )}
              </g>
            );
          })}
          {series.map(({ window, path }) =>
            path ? (
              <path
                key={`line-${window}`}
                d={path}
                fill="none"
                stroke={colorOf(window)}
                strokeWidth={2.2}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            ) : null,
          )}
          {projection.markerData.map((datum) => {
            const latest = projection.latestDatumIDs.has(datum.id);
            return (
              <circle
                key={`pt-${datum.id}`}
                cx={xOf(datum.timestamp)}
                cy={yOf(datum.remaining)}
                r={latest ? 2.25 : 1.6}
                fill={colorOf(datum.window)}
                opacity={latest ? 1 : 0.62}
              />
            );
          })}
          {hover && hover.sample.rows.length > 0 && (
            <line x1={hover.x} x2={hover.x} y1={plotTop} y2={plotBottom} stroke="rgba(255, 255, 255, 0.32)" strokeWidth={1} />
          )}
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
      {hover && hover.sample.rows.length > 0 && (
        <HoverBubble width={BUBBLE_WIDTH} left={anchor} top={plotTop + 4}>
          <span style={{ fontSize: fs(9.5), fontWeight: 600, fontFamily: MONO, color: T.primary }}>{hhmm(hover.sample.timestamp)}</span>
          {hover.sample.rows.map((row) => (
            <HoverRow key={row.window} color={colorOf(row.window)} title={L(row.window)} value={`${row.remaining.toFixed(1)}%`} />
          ))}
          {hover.sample.activity.length > 0 && (
            <span style={{ fontSize: fs(8.5), fontFamily: MONO, color: T.tertiary, ...oneLine }}>
              {hover.sample.activity.map((item) => `${item.model} +${Fmt.human(item.tokenDelta)}`).join(" · ")}
            </span>
          )}
        </HoverBubble>
      )}
    </div>
  );
}
