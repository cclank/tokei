// Windows 桌面窗口：导航、页签、卡片网格、页脚，以及设置等其他页面。
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { CARDS } from "./cards/registry";
import type { CardContext, CardSpec } from "./cards/spec";
import { sortedUsageCards } from "./lib/cardOrder";
import { call, inTauri } from "./lib/collector";
import { currentLanguage, L } from "./lib/i18n";
import { pushTrayMenu } from "./lib/native";
import { getPref, usePrefsVersion } from "./lib/prefs";
import { loadQuotaDetail, useQuotaDetail } from "./lib/quotaDetail";
import { pushTrayTooltip, rangeLabel, UsageProvider, useUsageStore } from "./lib/store";
import { DISPLAY_RANGES, type RangeKey, type Usage } from "./lib/types";
import { hideQuickPanel, isQuickSurface, openMainWindow } from "./lib/surface";
import { Icon } from "./ui/Icon";
import { Card, CardHeadTrailing } from "./ui/kit";
import { fill, fs, rgba, T, Theme } from "./ui/theme";

const DashboardPage = lazy(() => import("./pages/Dashboard"));
const ProjectsPage = lazy(() => import("./pages/Projects"));
const QuotaHistoryPage = lazy(() => import("./pages/QuotaHistory"));
const SettingsPage = lazy(() => import("./pages/Settings"));

function Loading() {
  return <div className="page-loading" role="status"><span className="spinner" /><span>{L("加载中…")}</span></div>;
}

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
    <button type="button" className={`header-button${active ? " active" : ""}`} title={tip} aria-label={tip} aria-pressed={active} onClick={onClick} style={{ fontSize: fs(11) }}>
      <Icon name={icon} size={fs(14)} strokeWidth={2} />
      <span>{tip}</span>
    </button>
  );
}

function Header({ mode, setMode }: { mode: PanelMode; setMode: (m: PanelMode) => void }) {
  const { lastUpdated } = useUsageStore();
  const emoji = festiveEmoji();
  const toggle = (target: PanelMode) => setMode(mode === target ? "cards" : target);
  return (
    <header className="panel-header">
      <button className="plain panel-brand" title={L("主页")} onClick={() => setMode("cards")}>
        <span style={{ position: "relative", display: "grid", placeItems: "center" }}>
          <Icon name="timer" size={fs(18)} color={rgba(Theme.claude)} strokeWidth={2.6} />
          {emoji && <span style={{ position: "absolute", right: -9, top: -9, fontSize: fs(11) }}>{emoji}</span>}
        </span>
        <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
          <span style={{ fontSize: fs(15), fontWeight: 700, letterSpacing: 0.5, color: T.primary }}>Tokei</span>
          <span style={{ fontSize: fs(9), color: T.tertiary, whiteSpace: "nowrap" }}>{L("知度 · AI 用量")}</span>
        </span>
      </button>
      <span className="panel-updated" style={{ fontSize: fs(9.5) }}>{lastUpdated}</span>
      <nav className="panel-navigation">
        <HeaderButton icon="folder" active={mode === "projects"} tip={L("项目足迹")} onClick={() => toggle("projects")} />
        <HeaderButton icon="chart.xyaxis.line" active={mode === "quotaHistory"} tip={L("额度曲线")} onClick={() => toggle("quotaHistory")} />
        <HeaderButton icon="chart.bar" active={mode === "dashboard"} tip={L("数据面板")} onClick={() => toggle("dashboard")} />
        <HeaderButton icon="gearshape" active={mode === "settings"} tip={L("设置")} onClick={() => toggle("settings")} />
      </nav>
    </header>
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

function QuickHeader({ range }: { range: RangeKey }) {
  const { lastUpdated } = useUsageStore();
  return (
    <header className="quick-header">
      <div className="quick-brand">
        <Icon name="timer" size={fs(18)} color={rgba(Theme.claude)} />
        <div>
          <span className="quick-title">Tokei <span>{L("快捷面板")}</span></span>
          <span className="quick-updated" style={{ fontSize: fs(9.5) }}>{lastUpdated}</span>
        </div>
      </div>
      <div className="quick-actions">
        <button type="button" className="header-button" onClick={() => void openMainWindow(range)} style={{ fontSize: fs(10) }}>
          <Icon name="arrow.up.right" size={fs(12)} />
          <span>{L("打开主窗口")}</span>
        </button>
        <button type="button" className="circle-button" title={L("关闭快捷面板")} aria-label={L("关闭快捷面板")} onClick={() => void hideQuickPanel()}>
          <Icon name="xmark" size={fs(12)} />
        </button>
      </div>
    </header>
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
    const { copySingleToolImage, currentShareVisibility } = await import("./lib/share");
    let targetRange = range;
    if (spec.id === "grok-bot" && usage) {
      const { grokBotDisplay } = await import("./cards/grok");
      targetRange = grokBotDisplay(usage, range).key;
    }
    if (usage && (await copySingleToolImage(spec.id, usage, targetRange, currentShareVisibility(), lastUpdated))) copy.markTool(spec.id);
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
  const { usage, error, refreshing, previewing } = useUsageStore();
  const detail = useQuotaDetail();
  const prefsVersion = usePrefsVersion();
  useEffect(() => {
    // 首批完整用量到达后再读周期缓存和统计，共用刷新去重，不阻塞首屏或预览。
    if (usage && !refreshing && !previewing &&
        ((getPref("showClaude", true) && usage.claude.q7 != null) ||
         (getPref("showCodex", true) && usage.codex.pw != null) ||
         (getPref("showGrok", true) && usage.grok?.pct != null))) loadQuotaDetail(false, isQuickSurface);
  }, [usage, refreshing, previewing, prefsVersion]);
  if (!usage) {
    return (
      <div style={{ height: 90, display: "grid", placeItems: "center", color: T.secondary, fontSize: fs(12) }}>
        {error ? (
          <span style={{ display: "flex", gap: 8, alignItems: "center", maxWidth: "100%" }}>
            <Icon name="exclamationmark.triangle.fill" color={rgba(Theme.claude)} size={fs(13)} />
            <span style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{error}</span>
          </span>
        ) : (
          <Loading />
        )}
      </div>
    );
  }
  const ctx: CardContext = { usage, range, rangeLabel: rangeLabel(range), refreshing, previewing, pref: getPref, quotaDetail: detail.payload };
  const visible = CARDS.filter((spec) => getPref(spec.visibleKey, spec.visibleDefault));
  const shown = visible.filter((spec) => safe(() => spec.active(ctx), false));
  const ordered = sortedUsageCards(shown, usage, range);
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
      <div className={ordered.length === 1 ? "grid one" : "grid"}>{ordered.map(render)}</div>
      {inactive.length > 0 && !refreshing && (
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

function Footer({ mode, range, copy, quick = false }: { mode: PanelMode; range: RangeKey; copy: Copy; quick?: boolean }) {
  const { usage, lastUpdated, refresh } = useUsageStore();
  const [awake, setAwake] = useState(false);
  useEffect(() => {
    if (quick) return;
    void call<boolean>("keep_awake_active").then((value) => setAwake(Boolean(value)));
  }, [quick]);
  const toggleAwake = async () => {
    const next = await call<boolean>("set_keep_awake", { on: !awake });
    setAwake(next ?? !awake);
  };
  return (
    <footer className="panel-footer">
      <span className="footer-note" style={{ fontSize: fs(9), color: T.tertiary }}>{mode === "settings" ? "Made by lank" : L("成本按 API 价估算,非订阅实付")}</span>
      <div className="footer-actions">
      {!quick && <FooterButton icon={awake ? "cup.and.saucer.fill" : "cup.and.saucer"} label={L("防休眠")} active={awake} onClick={toggleAwake} />}
      <FooterButton
        icon={copy.state.footer ? "checkmark" : "photo.on.rectangle"}
        label={copy.state.footer ? L("已复制") : L("复制")}
        onClick={async () => {
          const { copyUsageImage, currentShareVisibility } = await import("./lib/share");
          if (usage && (await copyUsageImage(usage, range, currentShareVisibility(), lastUpdated))) copy.markFooter();
        }}
      />
      <FooterButton icon="arrow.clockwise" label={L("刷新")} onClick={refresh} />
      {!quick && <FooterButton icon="power" label={L("退出")} onClick={() => void call("quit_app")} />}
      </div>
    </footer>
  );
}

function Panel({ ready }: { ready: boolean }) {
  const [mode, setMode] = useState<PanelMode>("cards");
  const [range, setRange] = useState<RangeKey>(() => {
    const value = new URLSearchParams(window.location.search).get("range") as RangeKey;
    return DISPLAY_RANGES.includes(value) ? value : "today";
  });
  const copy = useCopyFeedback();
  const scroll = useRef<HTMLElement>(null);
  usePrefsVersion();
  const language = currentLanguage();
  useEffect(() => {
    scroll.current?.scrollTo({ top: 0 });
  }, [mode]);
  useEffect(() => {
    if (inTauri && !isQuickSurface) void pushTrayMenu();
  }, [language]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (isQuickSurface) void hideQuickPanel();
        else setMode("cards");
      }
    };
    window.addEventListener("keydown", onKey);
    let disposed = false;
    let off: (() => void)[] = [];
    if (inTauri && !isQuickSurface) {
      void import("@tauri-apps/api/event").then(async ({ listen }) => {
        const listeners = await Promise.all([
          listen("tokei://open-settings", () => setMode("settings")),
          listen<RangeKey | null>("tokei://open-home", (event) => {
            setMode("cards");
            if (event.payload && DISPLAY_RANGES.includes(event.payload)) setRange(event.payload);
          }),
        ]);
        if (disposed) listeners.forEach((unlisten) => unlisten());
        else off = listeners;
      });
    }
    return () => {
      disposed = true;
      off.forEach((unlisten) => unlisten());
      window.removeEventListener("keydown", onKey);
    };
  }, []);
  const content = useMemo(() => {
    if (isQuickSurface) return <CardsPage range={range} setRange={setRange} copy={copy} />;
    if (!ready && mode !== "cards") return <Loading />;
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
  }, [mode, range, copy, ready]);
  return (
    <div className={`panel${isQuickSurface ? " quick-window" : ""}`}>
      {isQuickSurface ? <QuickHeader range={range} /> : <Header mode={mode} setMode={setMode} />}
      <main className="panel-scroll" ref={scroll}>
        <div className="panel-content">
        <Suspense fallback={<Loading />}>{content}</Suspense>
        </div>
      </main>
      <Footer mode={mode} range={range} copy={copy} quick={isQuickSurface} />
    </div>
  );
}

/** 完整刷新后才更新托盘和历史；预览数据不当作新的额度观测。 */
function onUsage(usage: Usage) {
  pushTrayTooltip(usage);
  void import("./lib/quotaHistory").then(({ recordQuotaHistory }) => recordQuotaHistory(usage)).catch(console.error);
}

export default function App({ collectorReady }: { collectorReady: Promise<void> }) {
  const [ready, setReady] = useState(isQuickSurface);
  useEffect(() => {
    let disposed = false;
    void collectorReady.then(() => {
      if (disposed) return;
      setReady(true);
      if (inTauri && !isQuickSurface) void call("start_activity_reporter", { enabled: getPref("shareBasicActivity", true) }).catch(() => {});
    }).catch((err) => {
      if (!disposed) setReady(true); // Keep settings/diagnostics reachable when configuration fails.
      console.error(err);
    });
    return () => { disposed = true; };
  }, [collectorReady]);
  return (
    <UsageProvider onUsage={isQuickSurface ? undefined : onUsage} shared={isQuickSurface} collectorReady={collectorReady}>
      <Panel ready={ready} />
    </UsageProvider>
  );
}
