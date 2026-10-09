// Tokei 回顾（Mac 版 WrappedView，按已提交版本移植）：总量大字 + 时间段切换、五个统计片、
// 巅峰日 Top 3、成就徽章（新解锁金光扫过 + 轻弹入）、24 小时活跃时段；跨 10 亿档位时撒花。
import {
  Banknote,
  Calendar,
  ChevronDown,
  ChevronUp,
  CircleDollarSign,
  ClockCheck,
  Crosshair,
  Crown,
  Diamond,
  Flame,
  Grid2x2,
  Grid3x3,
  Hexagon,
  LayoutPanelLeft,
  MoonStar,
  Repeat,
  Sparkles,
  Sunrise,
  Umbrella,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import * as Fmt from "../../lib/fmt";
import { data as translateData, isChinese, L } from "../../lib/i18n";
import { getPref, setPref } from "../../lib/prefs";
import { Icon } from "../../ui/Icon";
import { fill, fs, gradient, rgba, T, Theme, type RGB } from "../../ui/theme";
import { FaintDivider, SectionTitle } from "./Sections";
import { WRAPPED_PERIODS, wrappedPeriodLabel, type WrappedAchievement, type WrappedData, type WrappedPeakDay, type WrappedPeriod } from "./types";

const MONO = "var(--mono)";

// 成就「已见」集合与 token 里程碑档位，键名与 Mac 版 UserDefaults 一致。
const SEEN_KEY = "seenAchievements";
const MILESTONE_KEY = "lastTokenMilestone";

function seenSet(): Set<string> {
  const stored = getPref<unknown>(SEEN_KEY, []);
  return new Set(Array.isArray(stored) ? stored.filter((item): item is string => typeof item === "string") : []);
}

function markSeen(titles: string[]) {
  const seen = seenSet();
  titles.forEach((title) => seen.add(title));
  setPref(SEEN_KEY, Array.from(seen));
}

/** 每 10 亿一档；比上次记下的档位高就撒花。 */
function checkMilestone(tokens: number): boolean {
  const current = Math.floor(tokens / 1_000_000_000);
  const last = Number(getPref<number>(MILESTONE_KEY, 0)) || 0;
  if (current > last) {
    setPref(MILESTONE_KEY, current);
    return true;
  }
  return false;
}

/** 带「亿」的描述在其他语言里按 K / M / B 重写（WrappedAchievement.displayDesc）。 */
function displayDesc(a: WrappedAchievement): string {
  if (!isChinese() && a.tokens != null && a.tokens_template) return L(a.tokens_template, Fmt.human(a.tokens));
  return translateData(a.desc);
}

// 采集器给的成就图标是 SF Symbols 名，这里映射到 lucide。
const ACHIEVEMENT_ICONS: Record<string, LucideIcon> = {
  "crown.fill": Crown,
  "hexagon.fill": Hexagon,
  "diamond.fill": Diamond,
  diamond: Diamond,
  "dollarsign.circle.fill": CircleDollarSign,
  "banknote.fill": Banknote,
  banknote: Banknote,
  "flame.fill": Flame,
  "bolt.fill": Zap,
  "square.grid.3x3.fill": Grid3x3,
  "square.grid.2x2.fill": Grid2x2,
  scope: Crosshair,
  "rectangle.3.group.fill": LayoutPanelLeft,
  "clock.badge.checkmark.fill": ClockCheck,
  "repeat.circle.fill": Repeat,
  "repeat.circle": Repeat,
  "moon.stars.fill": MoonStar,
  "sunrise.fill": Sunrise,
  "beach.umbrella.fill": Umbrella,
  calendar: Calendar,
};

function AchievementIcon({ name, size }: { name: string; size: number }) {
  const Component = ACHIEVEMENT_ICONS[name];
  if (Component) return <Component size={size} color="#fff" strokeWidth={2.6} />;
  return <Icon name={name} size={size} color="#fff" strokeWidth={2.6} />;
}

/** "2026-07-21" → 「7月21日」；格式不对原样返回。 */
function peakDate(s: string): string {
  const parts = s.split("-");
  if (parts.length !== 3) return s;
  const m = Number(parts[1]);
  const d = Number(parts[2]);
  if (!Number.isInteger(m) || !Number.isInteger(d) || parts[1] === "" || parts[2] === "") return s;
  return L("%@月%@日", m, d);
}

const shortDate = (s: string) => (s.length >= 10 ? s.slice(-5) : s);

/** 成本换算彩蛋（随机：咖啡 / 火锅 / 码字）。 */
function funFactText(d: WrappedData, seed: number): string {
  const coffee = Math.round(d.total_cost / 4);
  const hotpot = Math.round(d.total_cost / 40);
  switch (seed) {
    case 0:
      return L("这些花费 ≈ %@ 杯咖啡 ☕", coffee.toLocaleString());
    case 1:
      return L("这些花费 ≈ %@ 顿火锅 🍲", hotpot.toLocaleString());
    default:
      return L("这些 token ≈ 码了 %@ 字 ✍️", Fmt.human(Math.trunc(d.total_tokens * 0.6)));
  }
}

/** 一行放不下时把字缩小，最多缩到 60%（lineLimit(1).minimumScaleFactor(0.6)）。 */
function FitText({ text, size, style }: { text: string; size: number; style?: CSSProperties }) {
  const ref = useRef<HTMLSpanElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const fit = () => {
      el.style.fontSize = `${size}px`;
      const ratio = el.scrollWidth > el.clientWidth && el.scrollWidth > 0 ? el.clientWidth / el.scrollWidth : 1;
      el.style.fontSize = `${size * Math.max(0.6, ratio)}px`;
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(el);
    return () => observer.disconnect();
  }, [text, size]);
  return (
    <span
      ref={ref}
      title={text}
      style={{
        display: "block",
        minWidth: 0,
        flex: "1 1 auto",
        whiteSpace: "nowrap",
        overflow: "hidden",
        textOverflow: "ellipsis",
        fontSize: size,
        ...style,
      }}
    >
      {text}
    </span>
  );
}

function PeriodPicker({ period, onChange }: { period: WrappedPeriod; onChange: (p: WrappedPeriod) => void }) {
  return (
    <div style={{ display: "flex", padding: 2, borderRadius: 999, background: fill(0.06), flex: "none" }}>
      {WRAPPED_PERIODS.map((p) => {
        const on = p === period;
        return (
          <button
            key={p}
            className="plain"
            onClick={() => {
              if (p !== period) onChange(p);
            }}
            style={{
              fontSize: fs(9),
              fontWeight: on ? 700 : 500,
              color: on ? "#fff" : T.tertiary,
              padding: "3px 7px",
              borderRadius: 999,
              background: on ? gradient(Theme.claude) : "transparent",
              whiteSpace: "nowrap",
              transition: "background 0.2s, color 0.2s",
            }}
          >
            {wrappedPeriodLabel(p)}
          </button>
        );
      })}
    </div>
  );
}

function Hero({ d, period, onPeriodChange, funSeed }: { d: WrappedData; period: WrappedPeriod; onPeriodChange: (p: WrappedPeriod) => void; funSeed: number }) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 5,
        padding: 14,
        borderRadius: 16,
        background: `linear-gradient(135deg, ${rgba(Theme.claude, 0.16)}, ${rgba(Theme.gemini, 0.06)})`,
        boxShadow: `inset 0 0 0 0.75px ${rgba(Theme.claude, 0.12)}`,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
        <Sparkles size={fs(11)} color={rgba(Theme.claude)} strokeWidth={2.6} />
        <span style={{ fontSize: fs(11), fontWeight: 700, letterSpacing: 1.5, color: T.secondary, whiteSpace: "nowrap" }}>{L("回顾")}</span>
        <div style={{ flex: 1 }} />
        <PeriodPicker period={period} onChange={onPeriodChange} />
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
        {d.first_day !== "" && (
          <span style={{ fontSize: fs(9), fontFamily: MONO, color: T.tertiary }}>{period === "all" ? L("自 %@", d.first_day) : d.first_day}</span>
        )}
        {d.active_days > 0 && <span style={{ fontSize: fs(9), fontFamily: MONO, color: T.tertiary }}>{L("· %@ 天活跃", d.active_days)}</span>}
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
        <span
          style={{
            fontSize: fs(32),
            fontWeight: 800,
            lineHeight: 1.15,
            fontVariantNumeric: "tabular-nums",
            background: `linear-gradient(90deg, ${rgba(Theme.claude)}, ${rgba(Theme.gemini)})`,
            WebkitBackgroundClip: "text",
            backgroundClip: "text",
            color: "transparent",
          }}
        >
          {Fmt.human(d.total_tokens)}
        </span>
        <span style={{ fontSize: fs(10.5), color: T.tertiary }}>tokens</span>
      </div>
      {d.total_cost > 0 && <span style={{ fontSize: fs(9.5), color: "rgba(255, 255, 255, 0.7)" }}>{"💡 " + funFactText(d, funSeed)}</span>}
    </div>
  );
}

function Chip({ label, value, tint, alpha = 1, icon }: { label: string; value: string; tint: RGB; alpha?: number; icon?: LucideIcon }) {
  const ChipIcon = icon;
  return (
    <div
      style={{
        flex: "1 1 0",
        minWidth: 0,
        display: "flex",
        flexDirection: "column",
        gap: 3,
        padding: "7px 9px",
        borderRadius: 11,
        background: rgba(tint, 0.1 * alpha),
      }}
    >
      <span style={{ fontSize: fs(9), fontWeight: 500, color: rgba(tint, 0.9 * alpha), whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
        {label}
      </span>
      <div style={{ display: "flex", alignItems: "center", gap: 3, minWidth: 0 }}>
        {ChipIcon && <ChipIcon size={fs(10)} color={rgba(tint, alpha)} strokeWidth={2.8} style={{ flex: "none" }} />}
        <FitText text={value} size={fs(12.5)} style={{ fontWeight: 700, color: "#fff" }} />
      </div>
    </div>
  );
}

function StatChips({ d }: { d: WrappedData }) {
  const avg = d.active_days > 0 ? d.total_cost / d.active_days : 0;
  return (
    <div style={{ display: "flex", gap: 7 }}>
      <Chip label={L("总成本")} value={Fmt.nativeMoney(d.total_cost, d.cost_cny)} tint={Theme.claude} />
      <Chip label={L("连续")} value={L("%@ 天", d.streak_cur)} tint={Theme.hermes} icon={Flame} />
      <Chip label={L("日均")} value={Fmt.nativeMoney(avg, (d.cost_cny ?? 0) / Math.max(d.active_days, 1))} tint={Theme.gemini} />
      <Chip label={L("峰值日")} value={shortDate(d.busiest.date)} tint={Theme.red} alpha={0.85} />
      <Chip label={L("本命模型")} value={translateData(d.top_model.name)} tint={Theme.codex} />
    </div>
  );
}

function PeakDaysSection({ peaks }: { peaks: WrappedPeakDay[] }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
      <SectionTitle>{L("巅峰日")}</SectionTitle>
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        {peaks.slice(0, 3).map((p, i) => (
          <div
            key={p.date}
            style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 9px", borderRadius: 10, background: fill(0.05), minWidth: 0 }}
          >
            <span
              style={{
                width: 18,
                height: 18,
                borderRadius: 9,
                display: "grid",
                placeItems: "center",
                flex: "none",
                fontSize: fs(10),
                fontWeight: 700,
                color: "#fff",
                background: i === 0 ? gradient(Theme.claude) : "rgba(255, 255, 255, 0.14)",
              }}
            >
              {i + 1}
            </span>
            <span style={{ fontSize: fs(11.5), fontWeight: 600, color: T.primary, whiteSpace: "nowrap", flex: "none" }}>{peakDate(p.date)}</span>
            <span style={{ fontSize: fs(9.5), fontFamily: MONO, color: T.secondary, whiteSpace: "nowrap", flex: "none" }}>{Fmt.human(p.tokens)}</span>
            <div style={{ flex: 1, minWidth: 6 }} />
            {p.projects && p.projects.length > 0 && (
              <span
                title={p.projects.join(" · ")}
                style={{ fontSize: fs(9), color: T.tertiary, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", minWidth: 0, flex: "0 1 auto" }}
              >
                {p.projects.join(" · ")}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/** 成就徽章：新解锁时轻弹入 + 金光扫过（只在挂上时判断一次是否「新」）。 */
function Badge({ a, isNew, delay }: { a: WrappedAchievement; isNew: boolean; delay: number }) {
  const [animate] = useState(isNew);
  const desc = displayDesc(a);
  return (
    <div
      style={{
        position: "relative",
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "7px 9px",
        borderRadius: 10,
        background: fill(0.05),
        overflow: "hidden",
        minWidth: 0,
        animation: animate ? `dash-badge-pop 0.6s ease-out ${delay}s both` : undefined,
      }}
    >
      <span
        style={{
          width: 26,
          height: 26,
          borderRadius: 13,
          display: "grid",
          placeItems: "center",
          flex: "none",
          background: `linear-gradient(135deg, ${rgba(Theme.claude)}, ${rgba(Theme.claude, 0.6)})`,
          boxShadow: `inset 0 0 0 0.5px rgba(255, 255, 255, 0.22), 0 1px 3px ${rgba(Theme.claude, 0.4)}`,
        }}
      >
        <AchievementIcon name={a.icon} size={fs(12)} />
      </span>
      <div style={{ display: "flex", flexDirection: "column", gap: 1, minWidth: 0 }}>
        <span style={{ fontSize: fs(11.5), fontWeight: 700, color: T.primary, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {translateData(a.title)}
        </span>
        <span title={desc} style={{ fontSize: fs(9), color: T.tertiary, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {desc}
        </span>
      </div>
      {animate && (
        <span
          style={{
            position: "absolute",
            top: 0,
            bottom: 0,
            left: "-130%",
            width: "45%",
            pointerEvents: "none",
            background: "linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.55), transparent)",
            mixBlendMode: "plus-lighter",
            animation: `dash-badge-shimmer 0.8s ease-in-out ${delay + 0.1}s both`,
          }}
        />
      )}
    </div>
  );
}

function AchievementsSection({ d }: { d: WrappedData }) {
  const [expanded, setExpanded] = useState(false);
  const limit = 10;
  const hasMore = d.achievements.length > limit;
  const shown = expanded || !hasMore ? d.achievements : d.achievements.slice(0, limit);
  const seen = seenSet();
  const Chevron = expanded ? ChevronUp : ChevronDown;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
        <SectionTitle>{L("成就")}</SectionTitle>
        <span
          style={{
            fontSize: fs(9.5),
            fontWeight: 700,
            color: rgba(Theme.claude),
            padding: "1px 5px",
            borderRadius: 999,
            background: rgba(Theme.claude, 0.14),
          }}
        >
          {d.achievements.length}
        </span>
        <div style={{ flex: 1 }} />
        {hasMore && (
          <button className="plain" onClick={() => setExpanded((v) => !v)} style={{ display: "flex", alignItems: "center", gap: 3, color: T.tertiary }}>
            <span style={{ fontSize: fs(10), fontWeight: 500 }}>{expanded ? L("收起") : L("展开全部")}</span>
            <Chevron size={fs(8)} strokeWidth={3} />
          </button>
        )}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 7 }}>
        {shown.map((a, i) => (
          <Badge key={a.title} a={a} isNew={!seen.has(a.title)} delay={i * 0.07} />
        ))}
      </div>
    </div>
  );
}

function RhythmSection({ d }: { d: WrappedData }) {
  const top = d.hours.length ? Math.max(...d.hours) : 0;
  const maxH = Math.max(d.hours.length ? top : 1, 1);
  const peak = d.hours.length ? d.hours.indexOf(top) : -1;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center" }}>
        <SectionTitle>{L("活跃时段")}</SectionTitle>
        <div style={{ flex: 1 }} />
        {peak >= 0 && (
          <span style={{ fontSize: fs(9.5), fontFamily: MONO, color: T.tertiary }}>{L("高峰 %@", `${String(peak).padStart(2, "0")}:00`)}</span>
        )}
      </div>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 48 }}>
        {Array.from({ length: 24 }, (_, h) => {
          const v = h < d.hours.length ? d.hours[h] : 0;
          const ratio = v / maxH;
          return (
            <div
              key={h}
              className="dash-bar"
              style={{
                flex: "1 1 0",
                minWidth: 0,
                height: Math.max(2, 48 * ratio),
                borderRadius: 2,
                background: h === peak ? gradient(Theme.claude) : rgba(Theme.claude, 0.32),
              }}
            />
          );
        })}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        {[0, 6, 12, 18, 23].map((h) => (
          <span key={h} style={{ fontSize: fs(8), fontFamily: MONO, color: T.tertiary }}>
            {h}
          </span>
        ))}
      </div>
    </div>
  );
}

const CONFETTI_PALETTE: RGB[] = [
  Theme.claude,
  Theme.qoder,
  Theme.qoderwork,
  Theme.qodercli,
  Theme.hermes,
  Theme.deepseekHarness,
  Theme.codex,
  Theme.gemini,
  Theme.zcode,
  Theme.mimocode,
  Theme.codebuddy,
  Theme.openclaw,
];

/** 撒花：跨 token 里程碑时从顶部落下的彩屑。 */
function Confetti() {
  return (
    <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 220, pointerEvents: "none", zIndex: 2 }}>
      {Array.from({ length: 30 }, (_, i) => {
        const frac = ((i * 37) % 100) / 100;
        const duration = 1.5 + ((i * 13) % 10) / 10;
        const delay = ((i * 7) % 8) / 10;
        return (
          <span
            key={i}
            style={
              {
                position: "absolute",
                top: 0,
                left: `${frac * 100}%`,
                width: 6,
                height: 9,
                borderRadius: 1.5,
                background: rgba(CONFETTI_PALETTE[i % CONFETTI_PALETTE.length]),
                "--dash-rot": `${i * 47}deg`,
                animation: `dash-confetti-fall ${duration}s ease-in ${delay}s both`,
              } as CSSProperties
            }
          />
        );
      })}
    </div>
  );
}

export function WrappedView({
  data,
  period,
  onPeriodChange,
}: {
  data: WrappedData;
  period: WrappedPeriod;
  onPeriodChange: (p: WrappedPeriod) => void;
}) {
  const [funSeed] = useState(() => Math.floor(Math.random() * 3));
  const [showConfetti, setShowConfetti] = useState(false);
  const appearData = useRef(data);

  // 出现时：跨档撒花；1.8 秒后把这次看到的成就记为「已见」。
  useEffect(() => {
    if (checkMilestone(appearData.current.total_tokens)) setShowConfetti(true);
    const titles = appearData.current.achievements.map((a) => a.title);
    const timer = window.setTimeout(() => markSeen(titles), 1800);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (!showConfetti) return;
    const timer = window.setTimeout(() => setShowConfetti(false), 2600);
    return () => window.clearTimeout(timer);
  }, [showConfetti]);

  const peaks = data.peak_days ?? [];
  return (
    <div style={{ position: "relative", display: "flex", flexDirection: "column", gap: 12 }}>
      <Hero d={data} period={period} onPeriodChange={onPeriodChange} funSeed={funSeed} />
      <StatChips d={data} />
      {peaks.length > 0 && <PeakDaysSection peaks={peaks} />}
      {data.achievements.length > 0 && <AchievementsSection d={data} />}
      <FaintDivider />
      <RhythmSection d={data} />
      {showConfetti && <Confetti />}
    </div>
  );
}
