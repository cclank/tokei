// 项目足迹（Mac 版 ProjectTrailView）：按最近活跃把用过 AI 工具的项目目录分组列出，
// 可搜索、置顶；点一行在资源管理器里显示，右键菜单复制路径。数据来自采集脚本 `--projects`。
import { CircleX, Folder, Search, Star } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type MouseEvent as ReactMouseEvent } from "react";
import { collectJSON, inTauri } from "../lib/collector";
import * as Fmt from "../lib/fmt";
import { data, L } from "../lib/i18n";
import { openExternal } from "../lib/native";
import { usePref } from "../lib/prefs";
import { Icon } from "../ui/Icon";
import { fill, fs, rgba, T, Theme, type RGB } from "../ui/theme";

const MONO = "var(--mono)";

/** `--projects` 的一项（usage.30s.py projects()）。 */
interface TrailProject {
  path: string;
  name: string;
  last_active: string;
  sessions: number;
  tokens: number;
  cost_cny?: number | null;
  cost: number;
  top_model: string;
  tools: string[];
  ports?: number[] | null;
}

type Group = "pinned" | "today" | "week" | "earlier" | "dormant";
const GROUPS: Group[] = ["pinned", "today", "week", "earlier", "dormant"];

// Mac 版把列表存在 PanelView 的 @State 里，关掉再打开页面不用重新跑脚本；这里放在模块里，效果一样。
let trailCache: TrailProject[] | null = null;
let trailLoading: Promise<TrailProject[]> | null = null;

function fetchProjects(): Promise<TrailProject[]> {
  if (!trailLoading) {
    trailLoading = collectJSON<TrailProject[]>(["--projects"])
      .then((list) => (Array.isArray(list) ? list : []))
      .catch(() => [] as TrailProject[])
      .then((list) => {
        trailCache = list;
        trailLoading = null;
        return list;
      });
  }
  return trailLoading;
}

// ---- 路径：Windows 上是 C:\Users\me\repo，分隔符两种都要认 ----

let homeCache: string | null = null;
let homeResolved = false;

async function resolveHome(): Promise<string | null> {
  if (homeResolved) return homeCache;
  if (inTauri) {
    try {
      const { homeDir } = await import("@tauri-apps/api/path");
      homeCache = await homeDir();
    } catch {
      homeCache = null;
    }
  }
  homeResolved = true;
  return homeCache;
}

/** 拿不到主目录时按常见布局猜：/Users/x、/home/x、C:\Users\x。 */
function guessHome(path: string): string | null {
  const match = /^(\/Users\/[^/]+|\/home\/[^/]+|[A-Za-z]:[\\/]Users[\\/][^\\/]+)/i.exec(path);
  return match ? match[1] : null;
}

/** 主目录换成 ~（Windows 路径不分大小写）。 */
function abbreviatePath(path: string, home: string | null): string {
  const base = home || guessHome(path);
  if (!base) return path;
  const windows = /^[A-Za-z]:/.test(base) || base.includes("\\");
  const norm = (s: string) => (windows ? s.replace(/\\/g, "/").toLowerCase() : s);
  const h = norm(base).replace(/\/+$/, "");
  const p = norm(path);
  if (!h) return path;
  if (p === h) return "~";
  if (p.startsWith(`${h}/`)) return `~${path.slice(h.length)}`;
  return path;
}

/** 采集器给的 name 是 basename；它退回整条路径时（如末尾带反斜杠）这里再取一次。 */
function displayName(p: TrailProject): string {
  if (p.name && p.name !== p.path) return p.name;
  const trimmed = p.path.replace(/[\\/]+$/, "");
  const parts = trimmed.split(/[\\/]/);
  return parts[parts.length - 1] || p.path;
}

function fileURL(path: string): string {
  const forward = path.replace(/\\/g, "/");
  const encoded = forward.split("/").map(encodeURIComponent).join("/").replace(/^([A-Za-z])%3A/, "$1:");
  return /^[A-Za-z]:/.test(forward) ? `file:///${encoded}` : `file://${encoded}`;
}

/** Mac 的「在 Finder 中显示」：在资源管理器里选中这个目录。 */
async function revealInExplorer(path: string) {
  if (inTauri) {
    try {
      const { revealItemInDir } = await import("@tauri-apps/plugin-opener");
      await revealItemInDir(path);
      return;
    } catch {
      // 退回按 file:// 打开
    }
  }
  try {
    await openExternal(fileURL(path));
  } catch {
    // 打不开就算了
  }
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // 剪贴板不可用
  }
}

// ---- 分组与日期 ----

function parseDate(s: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  if (!match) return null;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return Number.isNaN(date.getTime()) ? null : date;
}

function startOfDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

function groupFor(p: TrailProject, pinned: Set<string>): Group {
  if (pinned.has(p.path)) return "pinned";
  const d = parseDate(p.last_active);
  if (!d) return "dormant";
  const days = Math.round((startOfDay(new Date()).getTime() - startOfDay(d).getTime()) / 86_400_000);
  if (days === 0) return "today";
  if (days <= 7) return "week";
  if (days > 14) return "dormant";
  return "earlier";
}

function groupLabel(g: Group): string {
  switch (g) {
    case "pinned":
      return L("置顶");
    case "today":
      return L("今天");
    case "week":
      return L("本周");
    case "earlier":
      return L("更早");
    case "dormant":
      return L("沉睡");
  }
}

const TOOL_COLORS: Record<string, RGB> = {
  claude: Theme.claude,
  codex: Theme.codex,
  grok: Theme.grok,
  hermes: Theme.hermes,
  zcode: Theme.zcode,
  mimocode: Theme.mimocode,
  pi: Theme.pi,
  prime_agent: Theme.primeAgent,
  workbuddy: Theme.workbuddy,
  workbuddy_ai: Theme.workbuddyAI,
  codebuddy: Theme.codebuddy,
  deepseek_harness: Theme.deepseekHarness,
  opencode: Theme.opencode,
  kimicode: Theme.kimicode,
  musecode: Theme.musecode,
  cmdcode: Theme.cmdcode,
  devin: Theme.devin,
  minimax: Theme.minimax,
};

const toolColor = (tool: string) => (TOOL_COLORS[tool] ? rgba(TOOL_COLORS[tool]) : T.tertiary);

const pad2 = (n: number) => String(n).padStart(2, "0");

// ---- 视图 ----

/** 中间省略（Swift truncationMode(.middle)）：尾巴固定显示，前半段放不下时打省略号。 */
function MiddleTruncated({ text }: { text: string }) {
  const cut = Math.max(0, text.length - 20);
  const ellipsis = { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0 } as const;
  return (
    <span style={{ display: "flex", minWidth: 0, fontSize: fs(9), fontFamily: MONO, color: T.tertiary }}>
      <span style={ellipsis}>{text.slice(0, cut)}</span>
      <span style={{ whiteSpace: "nowrap", flex: "none" }}>{text.slice(cut)}</span>
    </span>
  );
}

function SearchBar({ query, setQuery }: { query: string; setQuery: (q: string) => void }) {
  return (
    <div
      style={{
        flex: 1,
        minWidth: 0,
        display: "flex",
        alignItems: "center",
        gap: 7,
        padding: "6px 10px",
        borderRadius: 8,
        background: fill(0.06),
      }}
    >
      <Search size={fs(10)} strokeWidth={2.4} color={T.tertiary} style={{ flex: "none" }} />
      <input
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder={L("搜索项目…")}
        spellCheck={false}
        style={{
          flex: 1,
          minWidth: 0,
          border: "none",
          outline: "none",
          background: "transparent",
          padding: 0,
          fontSize: fs(11),
          color: T.primary,
        }}
      />
      {query && (
        <button className="plain" onClick={() => setQuery("")} style={{ display: "grid", placeItems: "center", flex: "none" }}>
          <CircleX size={fs(10)} strokeWidth={2.4} color={T.tertiary} />
        </button>
      )}
    </div>
  );
}

function SectionHeader({ title, dormant }: { title: string; dormant: boolean }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 5, paddingTop: 4 }}>
      {dormant && <span style={{ fontSize: fs(10) }}>💤</span>}
      <span style={{ fontSize: fs(11), fontWeight: 600, color: dormant ? T.tertiary : T.secondary }}>{title}</span>
    </div>
  );
}

function PortChips({ ports }: { ports: number[] }) {
  return (
    <div
      style={{ display: "flex", gap: 5, overflowX: "auto", overflowY: "hidden", height: 22, alignItems: "center", scrollbarWidth: ports.length > 4 ? "thin" : "none" }}
    >
      {ports.map((port) => (
        <button
          key={port}
          className="plain"
          onClick={(event) => {
            event.stopPropagation();
            void openExternal(`http://localhost:${port}`);
          }}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 3,
            flex: "none",
            padding: "2px 6px",
            borderRadius: 999,
            background: rgba(Theme.hermes, 0.12),
          }}
        >
          <span style={{ width: 5, height: 5, borderRadius: 3, background: rgba(Theme.green) }} />
          <span style={{ fontSize: fs(9), fontWeight: 500, fontFamily: MONO, color: rgba(Theme.hermes), whiteSpace: "nowrap" }}>
            localhost:{port}
          </span>
        </button>
      ))}
    </div>
  );
}

function ProjectRow({
  p,
  home,
  pinned,
  onTogglePin,
  onMenu,
}: {
  p: TrailProject;
  home: string | null;
  pinned: boolean;
  onTogglePin: () => void;
  onMenu: (event: ReactMouseEvent) => void;
}) {
  const meta = { fontSize: fs(9), color: T.tertiary, whiteSpace: "nowrap" } as const;
  return (
    <div
      onClick={() => void revealInExplorer(p.path)}
      onContextMenu={onMenu}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 9,
        padding: "8px 10px",
        borderRadius: 10,
        background: fill(0.04),
        cursor: "pointer",
      }}
    >
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 3 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 5, minWidth: 0 }}>
          <Folder size={fs(10)} strokeWidth={2} color={rgba(Theme.claude, 0.8)} fill={rgba(Theme.claude, 0.8)} style={{ flex: "none" }} />
          <span
            style={{
              fontSize: fs(12),
              fontWeight: 600,
              color: T.primary,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              minWidth: 0,
            }}
          >
            {displayName(p)}
          </span>
          {p.tools.map((tool) => (
            <span key={tool} style={{ width: 5, height: 5, borderRadius: 3, background: toolColor(tool), flex: "none" }} />
          ))}
        </div>
        <MiddleTruncated text={abbreviatePath(p.path, home)} />
        <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
          <span style={meta}>{Fmt.relativeDate(p.last_active)}</span>
          <span style={meta}>·</span>
          <span style={meta}>{p.sessions} sessions</span>
          <span style={meta}>·</span>
          <span style={{ ...meta, fontWeight: 500, color: T.secondary }}>{Fmt.nativeMoney(p.cost, p.cost_cny)}</span>
          {p.top_model && (
            <span
              style={{
                fontSize: fs(8),
                fontFamily: MONO,
                color: T.tertiary,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                minWidth: 0,
              }}
            >
              {data(p.top_model)}
            </span>
          )}
        </div>
        {p.ports && p.ports.length > 0 && <PortChips ports={p.ports} />}
      </div>
      <button
        className="plain"
        title={pinned ? L("取消置顶") : L("置顶")}
        onClick={(event) => {
          event.stopPropagation();
          onTogglePin();
        }}
        style={{ display: "grid", placeItems: "center", flex: "none", marginLeft: 4 }}
      >
        <Star
          size={fs(10)}
          strokeWidth={2.2}
          color={pinned ? rgba(Theme.qoder) : T.tertiary}
          fill={pinned ? rgba(Theme.qoder) : "none"}
        />
      </button>
    </div>
  );
}

interface MenuState {
  x: number;
  y: number;
  path: string;
}

/** 右键菜单（Mac 版 contextMenu）。终端 / Ghostty / iTerm / VS Code 几项在 Windows 上做不了，不显示。 */
function ContextMenu({ menu, onClose }: { menu: MenuState; onClose: () => void }) {
  useEffect(() => {
    const close = () => onClose();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("blur", close);
    window.addEventListener("resize", close);
    window.addEventListener("wheel", close, { passive: true });
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("blur", close);
      window.removeEventListener("resize", close);
      window.removeEventListener("wheel", close);
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);
  const items: { label: string; action: () => void }[] = [
    { label: L("在资源管理器中显示"), action: () => void revealInExplorer(menu.path) },
    { label: L("复制路径"), action: () => void copyText(menu.path) },
  ];
  const width = 200;
  const height = items.length * 26 + 10;
  const x = Math.max(4, Math.min(menu.x, window.innerWidth - width - 4));
  const y = Math.max(4, Math.min(menu.y, window.innerHeight - height - 4));
  return (
    <div
      onMouseDown={(event) => event.stopPropagation()}
      onContextMenu={(event) => event.preventDefault()}
      style={{
        position: "fixed",
        left: x,
        top: y,
        width,
        zIndex: 1000,
        padding: 5,
        borderRadius: 8,
        background: "rgba(44, 46, 54, 0.98)",
        boxShadow: "0 8px 24px rgba(0,0,0,0.45), inset 0 0 0 0.5px rgba(255,255,255,0.14)",
        display: "flex",
        flexDirection: "column",
      }}
    >
      {items.map((item) => (
        <button
          key={item.label}
          className="plain"
          onClick={() => {
            item.action();
            onClose();
          }}
          onMouseEnter={(event) => (event.currentTarget.style.background = fill(0.1))}
          onMouseLeave={(event) => (event.currentTarget.style.background = "transparent")}
          style={{ height: 26, padding: "0 9px", borderRadius: 5, fontSize: fs(11.5), color: T.primary, whiteSpace: "nowrap" }}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

export default function ProjectsPage() {
  const [projects, setProjects] = useState<TrailProject[] | null>(trailCache);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");
  const [home, setHome] = useState<string | null>(homeCache);
  const [menu, setMenu] = useState<MenuState | null>(null);
  const [pinnedRaw, setPinnedRaw] = usePref<string>("pinnedProjects", "");

  const pinned = useMemo(() => new Set(pinnedRaw.split("\n").filter(Boolean)), [pinnedRaw]);

  const loadData = useCallback(() => {
    setLoading(true);
    void fetchProjects().then((list) => {
      setProjects(list);
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    if (trailCache === null) loadData();
    void resolveHome().then(setHome);
  }, [loadData]);

  const togglePin = (path: string) => {
    const next = new Set(pinned);
    if (next.has(path)) next.delete(path);
    else next.add(path);
    setPinnedRaw([...next].sort().join("\n"));
  };

  const list = projects ?? [];
  const filtered = useMemo(() => {
    const q = query.toLowerCase();
    const matches = q ? list.filter((p) => p.name.toLowerCase().includes(q) || p.path.toLowerCase().includes(q)) : list;
    return [...matches].sort((a, b) => {
      const ap = pinned.has(a.path);
      const bp = pinned.has(b.path);
      if (ap !== bp) return ap ? -1 : 1;
      return a.last_active > b.last_active ? -1 : a.last_active < b.last_active ? 1 : 0;
    });
  }, [list, query, pinned]);

  const grouped = useMemo(() => {
    const map = new Map<Group, TrailProject[]>();
    for (const p of filtered) {
      const g = groupFor(p, pinned);
      map.set(g, [...(map.get(g) ?? []), p]);
    }
    return map;
  }, [filtered, pinned]);

  const earliest = useMemo(() => {
    const dates = list.map((p) => parseDate(p.last_active)).filter((d): d is Date => d !== null);
    if (!dates.length) return "?";
    const min = new Date(Math.min(...dates.map((d) => d.getTime())));
    return `${min.getFullYear()}-${pad2(min.getMonth() + 1)}-${pad2(min.getDate())}`;
  }, [list]);

  const closeMenu = useCallback(() => setMenu(null), []);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
        <SearchBar query={query} setQuery={setQuery} />
        <button className="circle-button" title={L("刷新")} onClick={loadData} style={{ color: T.tertiary }}>
          <Icon name="arrow.clockwise" size={fs(10)} strokeWidth={2.2} />
        </button>
      </div>
      {loading || projects === null ? (
        <div style={{ height: 120, display: "grid", placeItems: "center" }}>
          <span className="spinner" />
        </div>
      ) : filtered.length === 0 ? (
        <div style={{ height: 80, display: "grid", placeItems: "center", fontSize: fs(11), color: T.tertiary }}>{L("无匹配项目")}</div>
      ) : (
        <>
          {GROUPS.map((g) => {
            const items = grouped.get(g);
            if (!items?.length) return null;
            return (
              <div key={g} style={{ display: "contents" }}>
                <SectionHeader title={groupLabel(g)} dormant={g === "dormant"} />
                {items.map((p) => (
                  <ProjectRow
                    key={p.path}
                    p={p}
                    home={home}
                    pinned={pinned.has(p.path)}
                    onTogglePin={() => togglePin(p.path)}
                    onMenu={(event) => {
                      event.preventDefault();
                      setMenu({ x: event.clientX, y: event.clientY, path: p.path });
                    }}
                  />
                ))}
              </div>
            );
          })}
          <div style={{ fontSize: fs(9), color: T.tertiary, textAlign: "center", paddingTop: 4 }}>
            {L("共 %@ 个项目 · 最远 %@", list.length, earliest)}
          </div>
        </>
      )}
      {menu && <ContextMenu menu={menu} onClose={closeMenu} />}
    </div>
  );
}
