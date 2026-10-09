// 托盘面板（Mac 版 PanelView 的外壳）：头部、页签、卡片网格、页脚，以及设置等其他页面。
import { useEffect, useMemo, useRef, useState } from "react";
import { CARDS } from "./cards/registry";
import type { CardContext, CardSpec } from "./cards/spec";
import { call, inTauri } from "./lib/collector";
import { currentLanguage, L } from "./lib/i18n";
import { recordQuotaHistory } from "./lib/quotaHistory";
import { copySingleToolImage, copyUsageImage, currentShareVisibility } from "./lib/share";
import { pushTrayMenu } from "./lib/native";
import { getPref, usePrefsVersion } from "./lib/prefs";
import { pushTrayTooltip, rangeLabel, UsageProvider, useUsageStore } from "./lib/store";
import { DISPLAY_RANGES, type RangeKey, type Usage } from "./lib/types";
import DashboardPage from "./pages/Dashboard";
import { prewarmDashboard } from "./pages/dashboard/repository";
import ProjectsPage from "./pages/Projects";
import QuotaHistoryPage from "./pages/QuotaHistory";
import SettingsPage from "./pages/Settings";
import { Icon } from "./ui/Icon";
import { Card, CardHeadTrailing, HStack, Spacer } from "./ui/kit";
import { fill, fs, gradient, rgba, T, Theme } from "./ui/theme";

export type PanelMode = "cards" | "quotaHistory" | "dashboard" | "projects" | "settings";

function festiveEmoji(): string | null {
  const d = new Date();
  const key = `${d.getMonth() + 1}-${d.getDate()}`;
  if (key === "12-24" || key === "12-25") return "🎄";
  if (key === "1-1") return "🎉";
  if (key === "10-31") return "🎃";
  if (key === "2-14") return "❤️";
  return null;
}

function HeaderButton({ icon, active, tip, onClick }: { icon: string; active: boolean; tip: string; onClick: () => void }) {
  return (
    <button className="circle-button" title={tip} onClick={onClick} style={{ color: active ? rgba(Theme.claude) : T.tertiary }}>
      <Icon name={icon} size={fs(12)} strokeWidth={2} />
    </button>
  );
}

function Header({ mode, setMode }: { mode: PanelMode; setMode: (m: PanelMode) => void }) {
  const { lastUpdated } = useUsageStore();
  const emoji = festiveEmoji();
  const toggle = (target: PanelMode) => setMode(mode === target ? "cards" : target);
  return (
    <HStack gap={9}>
      <button className="plain" title={L("主页")} onClick={() => setMode("cards")} style={{ display: "flex", alignItems: "center", gap: 9 }}>
        <span style={{ position: "relative", display: "grid", placeItems: "center" }}>
          <Icon name="timer" size={fs(18)} color={rgba(Theme.claude)} strokeWidth={2.6} />
          {emoji && <span style={{ position: "absolute", right: -9, top: -9, fontSize: fs(11) }}>{emoji}</span>}
        </span>
        <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
          <span style={{ fontSize: fs(15), fontWeight: 700, letterSpacing: 0.5, color: T.primary }}>Tokei</span>
          <span style={{ fontSize: fs(9), color: T.tertiary, whiteSpace: "nowrap" }}>{L("知度 · AI 用量")}</span>
        </span>
      </button>
      <Spacer />
      <span style={{ fontSize: fs(9.5), fontFamily: "var(--mono)", color: T.tertiary, whiteSpace: "nowrap" }}>{lastUpdated}</span>
      <HeaderButton icon="folder" active={mode === "projects"} tip={L("项目足迹")} onClick={() => toggle("projects")} />
      <HeaderButton icon="chart.xyaxis.line" active={mode === "quotaHistory"} tip={L("额度曲线")} onClick={() => toggle("quotaHistory")} />
      <HeaderButton icon="chart.bar" active={mode === "dashboard"} tip={L("数据面板")} onClick={() => toggle("dashboard")} />
      <HeaderButton icon="gearshape" active={mode === "settings"} tip={L("设置")} onClick={() => toggle("settings")} />
    </HStack>
  );
}

function SegmentedTabs({ value, onChange }: { value: RangeKey; onChange: (k: RangeKey) => void }) {
  return (
    <div className="segmented" style={{ background: fill(0.06) }}>
      {DISPLAY_RANGES.map((key) => (
        <button key={key} className={`segment${key === value ? " on" : ""}`} style={{ fontSize: fs(12) }} onClick={() => onChange(key)}>
          {rangeLabel(key)}
        </button>
      ))}
    </div>
  );
}

/** 「已复制」的反馈：页脚和卡头同一时间只亮一处，1.6 秒后复原（同 Mac）。 */
interface CopyFeedback {
  footer: boolean;
  tool: string | null;
}

function useCopyFeedback() {
  const [state, setState] = useState<CopyFeedback>({ footer: false, tool: null });
  const timer = useRef<number | undefined>(undefined);
  const mark = (next: CopyFeedback) => {
    setState(next);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setState({ footer: false, tool: null }), 1600);
  };
  return {
    state,
    markFooter: () => mark({ footer: true, tool: null }),
    markTool: (id: string) => mark({ footer: false, tool: id }),
  };
}

type Copy = ReturnType<typeof useCopyFeedback>;

/** 卡头右侧的「复制此工具用量图」（Mac 版 cardCopyButton）。 */
function CardCopyButton({ spec, range, copy }: { spec: CardSpec; range: RangeKey; copy: Copy }) {
  const { usage, lastUpdated } = useUsageStore();
  const done = copy.state.tool === spec.id;
  const onClick = async () => {
    if (usage && (await copySingleToolImage(spec.id, usage, range, currentShareVisibility(), lastUpdated))) copy.markTool(spec.id);
  };
  return (
    <button
      className="plain"
      title={done ? L("已复制图片") : L("复制此工具用量图")}
      onClick={onClick}
      style={{
        width: 22,
        height: 22,
        borderRadius: 11,
        flex: "none",
        display: "grid",
        placeItems: "center",
        background: fill(done ? 0.1 : 0.06),
        color: done ? rgba(spec.tint) : T.tertiary,
      }}
    >
      <Icon name={done ? "checkmark" : "photo.on.rectangle"} size={fs(10)} strokeWidth={2.6} />
    </button>
  );
}

function cardName(spec: CardSpec) {
  return typeof spec.name === "function" ? spec.name() : spec.name;
}

function CardsPage({ range, setRange, copy }: { range: RangeKey; setRange: (k: RangeKey) => void; copy: Copy }) {
  const { usage, error, refreshing } = useUsageStore();
  usePrefsVersion();
  if (!usage) {
    return (
      <div style={{ height: 90, display: "grid", placeItems: "center", color: T.secondary, fontSize: fs(12) }}>
        {error ? (
          <span style={{ display: "flex", gap: 8, alignItems: "center", maxWidth: "100%" }}>
            <Icon name="exclamationmark.triangle.fill" color={rgba(Theme.claude)} size={fs(13)} />
            <span style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{error}</span>
          </span>
        ) : (
          <span className="spinner" />
        )}
      </div>
    );
  }
  const ctx: CardContext = { usage, range, rangeLabel: rangeLabel(range), refreshing, pref: getPref };
  const visible = CARDS.filter((spec) => getPref(spec.visibleKey, spec.visibleDefault));
  const shown = visible.filter((spec) => safe(() => spec.active(ctx), false));
  const compact = shown.filter((spec) => (spec.presentation?.(ctx) ?? "standard") === "compact");
  const standard = shown.filter((spec) => (spec.presentation?.(ctx) ?? "standard") === "standard");
  const inactive = visible.filter((spec) => !shown.includes(spec)).map(cardName);
  const render = (spec: CardSpec) => (
    <Card key={`${spec.id}:${range}`} tint={spec.tint}>
      <CardHeadTrailing.Provider
        value={safe(() => spec.copyable?.(ctx) ?? true, false) ? <CardCopyButton spec={spec} range={range} copy={copy} /> : null}
      >
        {safe(() => spec.render(ctx), <span style={{ color: T.tertiary, fontSize: fs(10) }}>{L("暂无数据")}</span>)}
      </CardHeadTrailing.Provider>
    </Card>
  );
  return (
    <>
      <SegmentedTabs value={range} onChange={setRange} />
      {compact.length > 0 && <div className={compact.length === 1 ? "grid one" : "grid"}>{compact.map(render)}</div>}
      {standard.length > 0 && <div className="grid">{standard.map(render)}</div>}
      {inactive.length > 0 && (
        <div style={{ fontSize: fs(9), color: T.tertiary, textAlign: "center" }}>{L("未检测到本地数据: %@", inactive.join(" · "))}</div>
      )}
    </>
  );
}

function safe<T>(fn: () => T, fallback: T): T {
  try {
    return fn();
  } catch (err) {
    console.error(err);
    return fallback;
  }
}

function FooterButton({ icon, label, onClick, active = false, tip }: { icon: string; label: string; onClick: () => void; active?: boolean; tip?: string }) {
  return (
    <button
      className={`footer-button${active ? " active" : ""}`}
      title={tip}
      onClick={onClick}
      style={active ? { color: rgba(Theme.claude), background: rgba(Theme.claude, 0.14) } : undefined}
    >
      <Icon name={icon} size={fs(11)} strokeWidth={2.4} />
      <span style={{ fontSize: fs(11), fontWeight: 500 }}>{label}</span>
    </button>
  );
}

function Footer({ mode, range, copy }: { mode: PanelMode; range: RangeKey; copy: Copy }) {
  const { usage, lastUpdated, refresh } = useUsageStore();
  const [awake, setAwake] = useState(false);
  useEffect(() => {
    void call<boolean>("keep_awake_active").then((value) => setAwake(Boolean(value)));
  }, []);
  const toggleAwake = async () => {
    const next = await call<boolean>("set_keep_awake", { on: !awake });
    setAwake(next ?? !awake);
  };
  return (
    <HStack gap={4}>
      <span style={{ fontSize: fs(9), color: T.tertiary }}>{mode === "settings" ? "Made by lank" : L("成本按 API 价估算,非订阅实付")}</span>
      <Spacer />
      <FooterButton icon={awake ? "cup.and.saucer.fill" : "cup.and.saucer"} label={L("防休眠")} active={awake} onClick={toggleAwake} />
      <FooterButton
        icon={copy.state.footer ? "checkmark" : "photo.on.rectangle"}
        label={copy.state.footer ? L("已复制") : L("复制")}
        onClick={async () => {
          if (usage && (await copyUsageImage(usage, range, currentShareVisibility(), lastUpdated))) copy.markFooter();
        }}
      />
      <FooterButton icon="arrow.clockwise" label={L("刷新")} onClick={refresh} />
      <FooterButton icon="power" label={L("退出")} onClick={() => void call("quit_app")} />
    </HStack>
  );
}

function Panel() {
  const [mode, setMode] = useState<PanelMode>("cards");
  const [range, setRange] = useState<RangeKey>("today");
  const copy = useCopyFeedback();
  usePrefsVersion();
  const language = currentLanguage();
  useEffect(() => {
    if (inTauri) void pushTrayMenu();
  }, [language]);
  useEffect(() => {
    if (!inTauri) return;
    let off: (() => void) | undefined;
    import("@tauri-apps/api/event").then(async ({ listen }) => {
      off = await listen("tokei://open-settings", () => setMode("settings"));
    });
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") void call("hide_panel");
    };
    window.addEventListener("keydown", onKey);
    return () => {
      off?.();
      window.removeEventListener("keydown", onKey);
    };
  }, []);
  const content = useMemo(() => {
    switch (mode) {
      case "settings":
        return <SettingsPage onClose={() => setMode("cards")} />;
      case "dashboard":
        return <DashboardPage />;
      case "projects":
        return <ProjectsPage />;
      case "quotaHistory":
        return <QuotaHistoryPage />;
      default:
        return <CardsPage range={range} setRange={setRange} copy={copy} />;
    }
  }, [mode, range, copy]);
  return (
    <div className="panel" style={{ background: `${gradient([0.2, 0.21, 0.25], 0.97)}` }}>
      <div className="panel-scroll">
        <div className="panel-content">
          <Header mode={mode} setMode={setMode} />
          {content}
          <div style={{ flex: 1 }} />
          <Footer mode={mode} range={range} copy={copy} />
        </div>
      </div>
    </div>
  );
}

let dashboardPrewarmed = false;

/** 每次刷新成功：更新托盘提示、记一笔额度曲线；第一次刷新完顺带预热数据面板的「全部」（同 Mac）。 */
function onUsage(usage: Usage) {
  pushTrayTooltip(usage);
  void recordQuotaHistory(usage);
  if (!dashboardPrewarmed) {
    dashboardPrewarmed = true;
    prewarmDashboard();
  }
}

export default function App() {
  return (
    <UsageProvider onUsage={onUsage}>
      <Panel />
    </UsageProvider>
  );
}
