// 活跃热力（DashboardView 的 heatmapSection）：周 = 最近 7 天竖条，月 = 35 天、年 = 371 天的
// 周一起始方格；点格子展开当天各工具的明细卡（HeatDetailCard）。
import { CircleX } from "lucide-react";
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import * as Fmt from "../../lib/fmt";
import { L } from "../../lib/i18n";
import { fill, fs, rgba, T, Theme, type RGB } from "../../ui/theme";
import { SectionTitle } from "./Sections";
import type { DailyCost } from "./types";

const MONO = "var(--mono)";

const n = (value: number | null | undefined) => value ?? 0;
const pad = (value: number) => String(value).padStart(2, "0");
const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const addDays = (d: Date, days: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + days);

/** 热力色阶：L0 无活动，L1 暗棕 → L4 金黄。 */
const HEAT_COLORS: RGB[] = [
  [0.18, 0.2, 0.24],
  [0.45, 0.32, 0.22],
  [0.72, 0.42, 0.25],
  [0.9, 0.55, 0.3],
  [0.98, 0.72, 0.35],
];

const EMPTY_HEAT = fill(0.04);

function heatColor(activity: number, max: number): string {
  if (activity <= 0 || max <= 0) return EMPTY_HEAT;
  const ratio = Math.min(activity / max, 1);
  if (ratio < 0.15) return rgba(HEAT_COLORS[1]);
  if (ratio < 0.35) return rgba(HEAT_COLORS[2]);
  if (ratio < 0.6) return rgba(HEAT_COLORS[3]);
  return rgba(HEAT_COLORS[4]);
}

function HeatToolCell({ name, tint, tokens, children }: { name: string; tint: RGB; tokens: number; children?: ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3, minWidth: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
        <span style={{ width: 6, height: 6, borderRadius: 3, background: rgba(tint), flex: "none" }} />
        <span style={{ fontSize: fs(11), fontWeight: 500, color: rgba(tint), whiteSpace: "nowrap" }}>{name}</span>
      </div>
      <span style={{ fontSize: fs(11), fontFamily: MONO, color: T.tertiary, whiteSpace: "nowrap" }}>{Fmt.human(tokens)} tok</span>
      {children}
    </div>
  );
}

function CostLine({ text }: { text: string }) {
  return <span style={{ fontSize: fs(12), fontWeight: 600, fontFamily: MONO, color: T.secondary, whiteSpace: "nowrap" }}>{text}</span>;
}

function ToolCell({ name, tint, tokens, cost, cny }: { name: string; tint: RGB; tokens: number; cost: number; cny?: number | null }) {
  return (
    <HeatToolCell name={name} tint={tint} tokens={tokens}>
      <CostLine text={Fmt.nativeMoney(cost, cny)} />
    </HeatToolCell>
  );
}

/** 点开某一天：当日总额 + 各工具的 token 与成本。 */
export function HeatDetailCard({ day, onClose }: { day: DailyCost; onClose: () => void }) {
  const waTokens = n(day.wa_in) + n(day.wa_out) + n(day.wa_cr) + n(day.wa_cw);
  const dTokens = n(day.d_in) + n(day.d_out) + n(day.d_cr) + n(day.d_cw) + n(day.d_reason);
  const gTokens = n(day.g_in) + n(day.g_out) + n(day.g_cr) + n(day.g_reason);
  const wTokens = n(day.w_in) + n(day.w_out) + n(day.w_cr) + n(day.w_cw);
  const qTokens = n(day.q_in) + n(day.q_out) + n(day.q_cr) + n(day.q_reason);
  const cbTokens = n(day.cb_in) + n(day.cb_out) + n(day.cb_cr) + n(day.cb_cw);
  const reserveTokens = n(day.xr_in) + n(day.xr_out);
  return (
    <div
      style={{
        padding: 12,
        borderRadius: 12,
        background: "rgba(0, 0, 0, 0.3)",
        boxShadow: `inset 0 0 0 0.5px ${rgba(Theme.claude, 0.2)}`,
        display: "flex",
        flexDirection: "column",
        gap: 6,
        animation: "dash-fade-in 0.2s ease-out",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: fs(13), fontWeight: 700, fontFamily: MONO, color: T.primary }}>{day.date}</span>
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: fs(15), fontWeight: 700, color: "#fff", fontVariantNumeric: "tabular-nums" }}>
          {Fmt.nativeMoney(day.total, day.cost_cny)}
        </span>
        <button className="plain" onClick={onClose} style={{ display: "grid", placeItems: "center" }}>
          <CircleX size={fs(12)} color={T.tertiary} strokeWidth={2.4} />
        </button>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(105px, 1fr))", columnGap: 12, rowGap: 8 }}>
        <ToolCell name="Claude" tint={Theme.claude} tokens={n(day.c_in) + n(day.c_out) + n(day.c_cr) + n(day.c_cw)} cost={day.claude} />
        <ToolCell name="Codex" tint={Theme.codex} tokens={n(day.x_in) + n(day.x_out)} cost={day.codex} />
        {(reserveTokens > 0 || n(day.codex_reserve) > 0) && (
          <ToolCell name="Luna Reserve" tint={Theme.codex} tokens={reserveTokens} cost={n(day.codex_reserve)} />
        )}
        <ToolCell
          name="Pi"
          tint={Theme.pi}
          tokens={n(day.p_in) + n(day.p_out) + n(day.p_cr) + n(day.p_cw) + n(day.p_reason)}
          cost={n(day.pi)}
        />
        <ToolCell
          name="Prime Agent"
          tint={Theme.primeAgent}
          tokens={n(day.pa_in) + n(day.pa_out) + n(day.pa_cr) + n(day.pa_cw) + n(day.pa_reason)}
          cost={n(day.prime_agent)}
        />
        <ToolCell name="WorkBuddy" tint={Theme.workbuddy} tokens={wTokens} cost={n(day.workbuddy)} />
        {waTokens > 0 && <ToolCell name="WorkBuddy Intl." tint={Theme.workbuddyAI} tokens={waTokens} cost={n(day.workbuddy_ai)} />}
        {dTokens > 0 && (
          <ToolCell
            name="DeepSeek Harness"
            tint={Theme.deepseekHarness}
            tokens={dTokens}
            cost={n(day.deepseek_harness)}
            cny={day.cny_by_tool?.deepseek_harness}
          />
        )}
        {(cbTokens > 0 || n(day.cb_credits) > 0) && (
          <HeatToolCell name="CodeBuddy" tint={Theme.codebuddy} tokens={cbTokens}>
            {n(day.cb_credits) > 0 && <CostLine text={`${Fmt.credits(n(day.cb_credits))} Credits`} />}
          </HeatToolCell>
        )}
        <ToolCell name="Qwen Code" tint={Theme.qwencode} tokens={qTokens} cost={n(day.qwencode)} />
        {gTokens > 0 && <ToolCell name="Grok Build" tint={Theme.grok} tokens={gTokens} cost={n(day.grok)} />}
      </div>
    </div>
  );
}

/** 0 = 周（最近 7 天），1 = 月，2 = 年。 */
type HeatRange = 0 | 1 | 2;

function MiniSegmented({ value, onChange }: { value: HeatRange; onChange: (value: HeatRange) => void }) {
  const options: [HeatRange, string][] = [
    [0, L("周")],
    [1, L("月")],
    [2, L("年")],
  ];
  return (
    <div className="segmented" style={{ width: 120, padding: 2, borderRadius: 7, background: fill(0.06), flex: "none" }}>
      {options.map(([key, label]) => (
        <button
          key={key}
          className={`segment${key === value ? " on" : ""}`}
          style={{ fontSize: 10, padding: "2px 0", borderRadius: 5 }}
          onClick={() => onChange(key)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function HeatCell({
  size,
  radius,
  color,
  selected,
  border,
  onClick,
}: {
  size: number;
  radius: number;
  color: string;
  selected: boolean;
  border: number;
  onClick?: () => void;
}) {
  return (
    <div
      className="dash-cell"
      onClick={onClick}
      style={{
        width: size,
        height: size,
        borderRadius: radius,
        background: color,
        boxShadow: selected ? `inset 0 0 0 ${border}px ${rgba(Theme.claude)}` : "none",
        cursor: onClick ? "pointer" : "default",
        flex: "none",
      }}
    />
  );
}

/** 周：今天往前 7 天，一天一行（格子 + 日期 + 当天金额）。 */
function WeekStrip({ daily, selected, onSelect }: { daily: DailyCost[]; selected: string | null; onSelect: (date: string) => void }) {
  const today = new Date();
  const dayLabels = Fmt.weekdayLabels();
  const byDate = new Map(daily.map((d) => [d.date, d]));
  const maxActivity = daily.length ? Math.max(...daily.map((d) => n(d.tokens))) : 1;
  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: 4 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {dayLabels.map((label, r) => (
          <span
            key={r}
            style={{
              width: 14,
              height: 20,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: fs(8),
              fontWeight: 500,
              color: T.tertiary,
              whiteSpace: "nowrap",
            }}
          >
            {label}
          </span>
        ))}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {Array.from({ length: 7 }, (_, i) => {
          const ds = ymd(addDays(today, -(6 - i)));
          const day = byDate.get(ds);
          const cost = day?.total ?? 0;
          return (
            <div key={ds} style={{ display: "flex", alignItems: "center", gap: 6, height: 20 }}>
              <HeatCell
                size={20}
                radius={3}
                color={heatColor(n(day?.tokens), maxActivity)}
                selected={selected === ds}
                border={1.5}
                onClick={() => onSelect(ds)}
              />
              <span style={{ width: 38, fontSize: fs(9), fontFamily: MONO, color: T.tertiary, whiteSpace: "nowrap" }}>{ds.slice(-5)}</span>
              {(cost > 0 || n(day?.cost_cny) > 0) && (
                <span style={{ fontSize: fs(10), fontWeight: 600, fontFamily: MONO, color: T.secondary, whiteSpace: "nowrap" }}>
                  {Fmt.nativeMoney(cost, day?.cost_cny)}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** 月 / 年：周一起始的方格，列是周；横向可滚，打开时滚到最近一周。 */
function HeatGrid({
  daily,
  range,
  selected,
  onSelect,
}: {
  daily: DailyCost[];
  range: 1 | 2;
  selected: string | null;
  onSelect: (date: string) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollLeft = el.scrollWidth;
  }, [range]);

  const today = new Date();
  const totalDays = range === 1 ? 35 : 371;
  const start = addDays(today, -(totalDays - 1));
  const activity = new Map(daily.map((d) => [d.date, n(d.tokens)]));
  const maxActivity = daily.length ? Math.max(...daily.map((d) => n(d.tokens))) : 1;
  const dayLabels = Fmt.weekdayLabels();

  // 周一 = 第 0 行
  const startWeekday = (start.getDay() + 6) % 7;
  const columns: (string | null)[][] = [];
  for (let i = 0; i < totalDays; i++) {
    const offset = startWeekday + i;
    const row = offset % 7;
    const col = Math.floor(offset / 7);
    if (!columns[col]) columns[col] = Array<string | null>(7).fill(null);
    columns[col][row] = ymd(addDays(start, i));
  }

  const cellSize = range === 1 ? 20 : 12;
  const gap = range === 1 ? 3 : 2;
  const radius = range === 1 ? 4 : 2.5;

  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: 4 }}>
      <div style={{ display: "flex", flexDirection: "column", gap, flex: "none" }}>
        {dayLabels.map((label, r) => (
          <span
            key={r}
            style={{
              width: 16,
              height: cellSize,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: range === 2 ? 8 : 10,
              fontWeight: 500,
              color: T.tertiary,
              whiteSpace: "nowrap",
            }}
          >
            {label}
          </span>
        ))}
      </div>
      <div ref={scrollRef} className="dash-hscroll" style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", gap, width: "max-content" }}>
          {columns.map((column, c) => (
            <div key={c} style={{ display: "flex", flexDirection: "column", gap }}>
              {column.map((ds, r) => (
                <HeatCell
                  key={r}
                  size={cellSize}
                  radius={radius}
                  color={heatColor(ds ? (activity.get(ds) ?? 0) : 0, maxActivity)}
                  selected={ds != null && selected === ds}
                  border={2}
                  onClick={ds ? () => onSelect(ds) : undefined}
                />
              ))}
            </div>
          ))}
          <div style={{ width: 1, height: 1, flex: "none" }} />
        </div>
      </div>
    </div>
  );
}

function HeatmapLegend() {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
      <div style={{ flex: 1 }} />
      <span style={{ fontSize: fs(10), color: T.tertiary }}>{L("少")}</span>
      {HEAT_COLORS.map((color, i) => (
        <span key={i} style={{ width: 12, height: 12, borderRadius: 2.5, background: i === 0 ? EMPTY_HEAT : rgba(color), flex: "none" }} />
      ))}
      <span style={{ fontSize: fs(10), color: T.tertiary }}>{L("多")}</span>
    </div>
  );
}

export function HeatmapSection({ daily }: { daily: DailyCost[] }) {
  const [heatRange, setHeatRange] = useState<HeatRange>(2);
  const [selected, setSelected] = useState<string | null>(null);
  const toggle = (date: string) => setSelected((current) => (current === date ? null : date));
  const selectedDay = selected ? daily.find((d) => d.date === selected) : undefined;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <SectionTitle>{L("活跃热力")}</SectionTitle>
        <div style={{ flex: 1 }} />
        <MiniSegmented
          value={heatRange}
          onChange={(value) => {
            setHeatRange(value);
            setSelected(null);
          }}
        />
      </div>
      {heatRange === 0 ? (
        <WeekStrip daily={daily} selected={selected} onSelect={toggle} />
      ) : (
        <HeatGrid daily={daily} range={heatRange} selected={selected} onSelect={toggle} />
      )}
      {selectedDay && <HeatDetailCard day={selectedDay} onClose={() => setSelected(null)} />}
      <HeatmapLegend />
    </div>
  );
}
