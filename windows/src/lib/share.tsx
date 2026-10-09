// 「复制」用量图：Mac 版 UsageSummaryBuilder（各工具一行、合计）+ UsageShareImage（面板风格的分享卡片）。
// 页脚「复制」是当前区间所有工具的总览图；卡头的复制按钮是单个工具的图。画在 canvas 上，按 PNG 写进剪贴板。
import {
  ArrowDown,
  ArrowUp,
  AudioWaveform,
  Brain,
  CircleDollarSign,
  Layers,
  LayoutGrid,
  MessagesSquare,
  Timer,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { createElement } from "react";
import { fill, fs, rgba, T, Theme, type RGB } from "../ui/theme";
import * as Fmt from "./fmt";
import { L } from "./i18n";
import { getPref } from "./prefs";
import { rangeLabel } from "./store";
import { getRange, totalTokens, type RangeKey, type Ranges, type TokenUsageRange, type Usage } from "./types";

// ---------------------------------------------------------------------------
// 显示开关（UsageToolVisibility）：字段 → 偏好里的 show* 键，缺省都是开。
// ---------------------------------------------------------------------------

const VISIBILITY_KEYS = {
  claude: "showClaude",
  codex: "showCodex",
  gemini: "showGemini",
  grok: "showGrok",
  grokBot: "showGrokBot",
  qoder: "showQoderIde",
  qoderwork: "showQoderWork",
  qodercli: "showQoderCli",
  qodercliCN: "showQoderCliCN",
  hermes: "showHermes",
  zcode: "showZcode",
  mimocode: "showMimoCode",
  openclaw: "showOpenClaw",
  pi: "showPi",
  primeAgent: "showPrimeAgent",
  workbuddy: "showWorkBuddy",
  workbuddyAI: "showWorkBuddyAI",
  codebuddy: "showCodeBuddy",
  deepseekHarness: "showDeepSeekHarness",
  opencode: "showOpenCode",
  qwencode: "showQwenCode",
  kimicode: "showKimiCode",
  musecode: "showMuseCode",
  cmdcode: "showCmdCode",
  devin: "showDevin",
  minimax: "showMiniMax",
} as const;

type VisibilityField = keyof typeof VISIBILITY_KEYS;

/** 从偏好读出当前的显示开关（与 Mac 版 PanelView.toolVisibility 同一组键）。 */
export function currentShareVisibility(): Record<string, boolean> {
  const result: Record<string, boolean> = {};
  for (const key of Object.values(VISIBILITY_KEYS)) result[key] = getPref<boolean>(key, true);
  return result;
}

// ---------------------------------------------------------------------------
// 汇总（UsageSummaryBuilder）
// ---------------------------------------------------------------------------

/** 一个工具在所选区间的用量（与卡片口径一致）。 */
export interface ShareLine {
  id: string;
  name: string;
  cost_cny?: number | null;
  cost?: number | null;
  /** 总量（卡片大字的口径）。 */
  tokens?: number | null;
  sessions?: number | null;
  calls?: number | null;
  input?: number | null;
  output?: number | null;
  cacheRead?: number | null;
  cacheWrite?: number | null;
  reason?: number | null;
  /** 缓存命中率 0–100。 */
  hit?: number | null;
  extra?: string | null;
}

export interface ShareTotals {
  cost_cny: number;
  cost: number;
  tokens: number;
  sessions: number;
  calls: number;
  tools: number;
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
  reason: number;
}

function isEmptyLine(line: ShareLine): boolean {
  const parts = (line.input ?? 0) + (line.output ?? 0) + (line.cacheRead ?? 0) + (line.cacheWrite ?? 0) + (line.reason ?? 0);
  return (
    (line.tokens ?? 0) <= 0 &&
    (line.sessions ?? 0) <= 0 &&
    (line.calls ?? 0) <= 0 &&
    (line.cost ?? 0) <= 0 &&
    parts <= 0 &&
    !line.extra
  );
}

const sum = (values: (number | null | undefined)[]) => values.reduce<number>((acc, v) => acc + (v ?? 0), 0);

export function shareTotals(lines: ShareLine[]): ShareTotals {
  return {
    cost_cny: sum(lines.map((l) => l.cost_cny)),
    cost: sum(lines.map((l) => l.cost)),
    tokens: sum(lines.map((l) => l.tokens)),
    sessions: sum(lines.map((l) => l.sessions)),
    calls: sum(lines.map((l) => l.calls)),
    tools: lines.length,
    input: sum(lines.map((l) => l.input)),
    output: sum(lines.map((l) => l.output)),
    cacheRead: sum(lines.map((l) => l.cacheRead)),
    cacheWrite: sum(lines.map((l) => l.cacheWrite)),
    reason: sum(lines.map((l) => l.reason)),
  };
}

/** 把「更新 HH:mm:ss」这类状态文字规整成「更新于 …」；加载中 / 失败时不写。 */
export function formatUpdatedLine(updated?: string | null): string | null {
  if (updated == null) return null;
  const trimmed = updated.trim();
  if (!trimmed) return null;
  if ([L("加载失败"), L("预览")].includes(trimmed) || trimmed.startsWith(L("加载中"))) return null;
  let body = trimmed;
  for (const prefix of [L("更新于 %@", "").trim(), L("更新 %@", "").trim()]) {
    if (prefix && body.startsWith(prefix)) {
      body = body.slice(prefix.length).trim();
      break;
    }
  }
  if (!body) return null;
  return L("更新于 %@", body);
}

// 各家区间里汇总用到的字段（Model.swift 对应的结构）。
interface ClaudeShareRange {
  hit?: number;
  in?: number;
  out?: number;
  cr?: number;
  cw?: number;
  cost?: number;
  sessions?: number;
}
interface CodexShareRange {
  hit?: number;
  in?: number;
  cached?: number;
  out?: number;
  reason?: number;
  cost?: number;
  sessions?: number;
}
interface GeminiShareRange {
  hit?: number;
  in?: number;
  out?: number;
  cached?: number;
  thoughts?: number;
  cost?: number;
  sessions?: number;
}
interface GrokShareRange {
  tokens?: number;
  hit?: number;
  in?: number;
  out?: number;
  cr?: number;
  reason?: number;
  cost?: number;
  usage_available?: boolean;
  usage_calls?: number;
  usage_sessions?: number;
  sessions?: number;
}
/** QoderRange：Qoder CLI / CN、QoderWork、Grok Bot 的本地统计。 */
interface QoderShareRange {
  in?: number;
  out?: number;
  cr?: number;
  cw?: number;
  credits?: number;
  hit?: number;
  sessions?: number;
  calls?: number;
  turns?: number;
}
/** QoderIdeRange：Qoder Desktop。 */
interface QoderIdeShareRange {
  in?: number;
  out?: number;
  cached?: number;
  sessions?: number;
  calls?: number;
  ctx?: number;
}
interface HermesShareRange {
  hit?: number;
  in?: number;
  out?: number;
  cr?: number;
  cw?: number;
  reason?: number;
  cost?: number;
  sessions?: number;
}
interface OpenClawShareRange extends HermesShareRange {
  tasks?: number;
}

function rangeOf<T extends object>(usage: Usage, key: string, range: RangeKey): T {
  const stat = usage[key] as { ranges?: Ranges<T> | null } | undefined;
  return getRange(stat?.ranges ?? undefined, range, {} as T);
}

const n = (v: number | null | undefined) => v ?? 0;
const positive = (v: number | null | undefined) => (n(v) > 0 ? n(v) : null);

function tokenToolLine(
  id: string,
  name: string,
  r: TokenUsageRange,
  { includesCost = true, includesCredits = false, reasonIncludedInOutput = false } = {},
): ShareLine {
  const total = n(r.in) + n(r.out) + n(r.cr) + n(r.cw) + (reasonIncludedInOutput ? 0 : n(r.reason));
  return {
    id,
    name,
    cost_cny: includesCost ? (r.cost_cny ?? null) : null,
    cost: includesCost ? n(r.cost) : null,
    tokens: total,
    sessions: n(r.sessions),
    calls: null,
    input: n(r.in),
    output: n(r.out),
    cacheRead: n(r.cr),
    cacheWrite: n(r.cw),
    reason: positive(r.reason),
    hit: positive(r.hit),
    extra: includesCredits && n(r.credits) > 0 ? `${Fmt.credits(n(r.credits))} Credits` : null,
  };
}

function qoderCliLine(id: string, name: string, r: QoderShareRange): ShareLine {
  return {
    id,
    name,
    cost: null,
    tokens: n(r.in) + n(r.out) + n(r.cr) + n(r.cw),
    sessions: n(r.sessions),
    calls: n(r.calls),
    input: n(r.in),
    output: n(r.out),
    cacheRead: n(r.cr),
    cacheWrite: n(r.cw),
    reason: null,
    hit: positive(r.hit),
    extra: n(r.credits) > 0 ? `${Fmt.credits(n(r.credits))} Credits` : null,
  };
}

/** 所选区间里、打开了显示开关的各工具，一家一行（顺序同 Mac 版）；没有用量的不出现。 */
export function shareToolLines(usage: Usage, range: RangeKey, visibility: Record<string, boolean>): ShareLine[] {
  const visible = (field: VisibilityField) => visibility[VISIBILITY_KEYS[field]] ?? true;
  const lines: ShareLine[] = [];
  const push = (line: ShareLine) => {
    if (!isEmptyLine(line)) lines.push(line);
  };
  const tokenTool = (field: VisibilityField, key: string, id: string, name: string, options?: Parameters<typeof tokenToolLine>[3]) => {
    if (visible(field)) push(tokenToolLine(id, name, rangeOf<TokenUsageRange>(usage, key, range), options));
  };

  if (visible("claude")) {
    const r = rangeOf<ClaudeShareRange>(usage, "claude", range);
    push({
      id: "claude",
      name: "Claude Code",
      cost: n(r.cost),
      tokens: n(r.in) + n(r.out) + n(r.cr) + n(r.cw),
      sessions: n(r.sessions),
      calls: null,
      input: n(r.in),
      output: n(r.out),
      cacheRead: n(r.cr),
      cacheWrite: n(r.cw),
      reason: null,
      hit: positive(r.hit),
    });
  }
  if (visible("codex")) {
    const codexLine = (id: string, name: string, r: CodexShareRange): ShareLine => ({
      id,
      name,
      cost: n(r.cost),
      tokens: n(r.in) + n(r.cached) + n(r.out),
      sessions: n(r.sessions),
      calls: null,
      input: n(r.in),
      output: n(r.out),
      cacheRead: n(r.cached),
      cacheWrite: null,
      reason: positive(r.reason),
      hit: positive(r.hit),
    });
    push(codexLine("codex", "Codex", rangeOf<CodexShareRange>(usage, "codex", range)));
    const reserveRanges = (usage.codex as { reserve_ranges?: Ranges<CodexShareRange> | null } | undefined)?.reserve_ranges;
    if (reserveRanges) push(codexLine("codex_reserve", "Luna Reserve", getRange(reserveRanges, range, {} as CodexShareRange)));
  }
  if (visible("gemini")) {
    const r = rangeOf<GeminiShareRange>(usage, "gemini", range);
    push({
      id: "gemini",
      name: "Gemini",
      cost: n(r.cost),
      tokens: n(r.in) + n(r.cached) + n(r.out) + n(r.thoughts),
      sessions: n(r.sessions),
      calls: null,
      input: n(r.in),
      output: n(r.out),
      cacheRead: n(r.cached),
      cacheWrite: null,
      reason: positive(r.thoughts),
      hit: positive(r.hit),
    });
  }
  if (visible("grok")) {
    const r = rangeOf<GrokShareRange>(usage, "grok", range);
    const available = r.usage_available === true;
    push({
      id: "grok",
      name: "Grok",
      cost: positive(r.cost),
      tokens: available ? n(r.in) + n(r.out) + n(r.cr) + n(r.reason) : n(r.tokens),
      sessions: Math.max(n(r.sessions), n(r.usage_sessions)),
      calls: positive(r.usage_calls),
      input: available ? n(r.in) : null,
      output: available ? n(r.out) : null,
      cacheRead: available ? n(r.cr) : null,
      cacheWrite: null,
      reason: available ? positive(r.reason) : null,
      hit: available ? positive(r.hit) : null,
    });
  }
  if (visible("grokBot")) {
    const r = rangeOf<QoderShareRange>(usage, "grok_bot", range);
    const quota = (usage.grok_bot as { quota?: { usage?: { ranges?: Ranges<TokenUsageRange> } | null } } | undefined)?.quota;
    const account = getRange(quota?.usage?.ranges, range, {} as TokenUsageRange);
    const total = totalTokens(account);
    const hasComponents = n(account.in) + n(account.out) + n(account.cr) + n(account.cw) + n(account.reason) > 0;
    push({
      id: "grok-bot",
      name: "Grok Bot",
      cost: positive(account.cost),
      tokens: total > 0 ? total : null,
      sessions: n(r.sessions),
      calls: n(account.requests) > 0 ? n(account.requests) : positive(r.calls),
      input: hasComponents ? n(account.in) : null,
      output: hasComponents ? n(account.out) : null,
      cacheRead: positive(account.cr),
      cacheWrite: positive(account.cw),
      reason: null,
      hit: null,
      extra: n(r.turns) > 0 ? L("%@ 条消息", n(r.turns)) : null,
    });
  }
  if (visible("qoder")) {
    const r = rangeOf<QoderIdeShareRange>(usage, "qoder", range);
    push({
      id: "qoder",
      name: "Qoder Desktop",
      cost: null,
      tokens: n(r.in) + n(r.cached) + n(r.out),
      sessions: n(r.sessions),
      calls: n(r.calls),
      input: n(r.in),
      output: n(r.out),
      cacheRead: n(r.cached),
      cacheWrite: null,
      reason: null,
      hit: positive(r.ctx),
    });
  }
  if (visible("qoderwork")) {
    const r = rangeOf<QoderShareRange>(usage, "qoderwork", range);
    push({
      id: "qoderwork",
      name: "QoderWork",
      cost: null,
      tokens: n(r.in) + n(r.out),
      sessions: n(r.sessions),
      calls: n(r.calls),
      input: n(r.in),
      output: n(r.out),
      cacheRead: null,
      cacheWrite: null,
      reason: null,
      hit: null,
    });
  }
  if (visible("qodercli")) push(qoderCliLine("qodercli", "Qoder CLI", rangeOf<QoderShareRange>(usage, "qodercli", range)));
  if (visible("qodercliCN")) push(qoderCliLine("qodercli_cn", "Qoder CN", rangeOf<QoderShareRange>(usage, "qodercli_cn", range)));
  if (visible("hermes")) {
    const r = rangeOf<HermesShareRange>(usage, "hermes", range);
    push({
      id: "hermes",
      name: "Hermes",
      cost: n(r.cost),
      tokens: n(r.in) + n(r.out) + n(r.cr) + n(r.cw) + n(r.reason),
      sessions: n(r.sessions),
      calls: null,
      input: n(r.in),
      output: n(r.out),
      cacheRead: n(r.cr),
      cacheWrite: n(r.cw),
      reason: positive(r.reason),
      hit: positive(r.hit),
    });
  }
  tokenTool("zcode", "zcode", "zcode", "ZCode");
  tokenTool("mimocode", "mimocode", "mimocode", "MiMoCode");
  if (visible("openclaw")) {
    const r = rangeOf<OpenClawShareRange>(usage, "openclaw", range);
    push({
      id: "openclaw",
      name: "OpenClaw",
      cost: n(r.cost),
      tokens: n(r.in) + n(r.out) + n(r.cr) + n(r.cw) + n(r.reason),
      sessions: n(r.sessions),
      calls: positive(r.tasks),
      input: n(r.in),
      output: n(r.out),
      cacheRead: n(r.cr),
      cacheWrite: n(r.cw),
      reason: positive(r.reason),
      hit: positive(r.hit),
    });
  }
  tokenTool("pi", "pi", "pi", "Pi");
  tokenTool("primeAgent", "prime_agent", "prime_agent", "Prime Agent");
  tokenTool("workbuddy", "workbuddy", "workbuddy", "WorkBuddy");
  tokenTool("workbuddyAI", "workbuddy_ai", "workbuddy-ai", "WorkBuddy Intl.");
  tokenTool("codebuddy", "codebuddy", "codebuddy", "CodeBuddy", { includesCost: false, includesCredits: true });
  tokenTool("deepseekHarness", "deepseek_harness", "deepseek_harness", "DeepSeek Harness");
  tokenTool("opencode", "opencode", "opencode", "OpenCode");
  tokenTool("qwencode", "qwencode", "qwencode", "Qwen Code");
  // 卡片刻意不显示 Kimi 的成本，分享图里也不能凭空冒出来一个数。
  tokenTool("kimicode", "kimicode", "kimicode", "Kimi Code", { includesCost: false });
  tokenTool("musecode", "musecode", "musecode", "Muse Code", { reasonIncludedInOutput: true });
  tokenTool("cmdcode", "cmdcode", "cmdcode", "Command Code");
  tokenTool("devin", "devin", "devin", "Devin");
  tokenTool("minimax", "minimax", "minimax", "MiniMax Code");
  return lines;
}

// ---------------------------------------------------------------------------
// 画图（UsageShareImage）
// ---------------------------------------------------------------------------

const MULTI_WIDTH = 380;
const SINGLE_WIDTH = 340;
const SCALE = 2;

const TINTS: Record<string, RGB> = {
  "Claude Code": Theme.claude,
  Codex: Theme.codex,
  "Luna Reserve": Theme.codex,
  Gemini: Theme.gemini,
  Grok: Theme.grok,
  "Grok Bot": Theme.grokBot,
  "Qoder Desktop": Theme.qoder,
  QoderWork: Theme.qoderwork,
  "Qoder CLI": Theme.qodercli,
  "Qoder CN": Theme.qodercliCN,
  Hermes: Theme.hermes,
  ZCode: Theme.zcode,
  MiMoCode: Theme.mimocode,
  OpenClaw: Theme.openclaw,
  Pi: Theme.pi,
  WorkBuddy: Theme.workbuddy,
  "WorkBuddy Intl.": Theme.workbuddyAI,
  CodeBuddy: Theme.codebuddy,
  OpenCode: Theme.opencode,
  "Qwen Code": Theme.qwencode,
  "Kimi Code": Theme.kimicode,
  "Muse Code": Theme.musecode,
  "Command Code": Theme.cmdcode,
  "Prime Agent": Theme.primeAgent,
  "DeepSeek Harness": Theme.deepseekHarness,
  Devin: Theme.devin,
  "MiniMax Code": Theme.minimax,
};

/** 未知名字退回 tTertiary 那样的灰。 */
const tintFor = (name: string): RGB => TINTS[name] ?? [0.58, 0.58, 0.6];

const darker = (c: RGB): RGB => [c[0] * 0.85, c[1] * 0.85, c[2] * 0.85];

/** SwiftUI Text 的行高约为字号的 1.2 倍。 */
const lh = (size: number) => Math.ceil(size * 1.2);

interface Fonts {
  sans: string;
  mono: string;
}

function readFonts(): Fonts {
  const style = getComputedStyle(document.documentElement);
  return {
    sans: style.getPropertyValue("--sans").trim() || `"Segoe UI", "Microsoft YaHei UI", sans-serif`,
    mono: style.getPropertyValue("--mono").trim() || `"Cascadia Mono", Consolas, monospace`,
  };
}

// ---- 图标：lucide 图标转成 Path2D，同步画、任意倍率都清晰 ----

const ICONS = {
  timer: Timer,
  "dollarsign.circle": CircleDollarSign,
  "arrow.down": ArrowDown,
  "arrow.up": ArrowUp,
  "bolt.fill": Zap,
  "square.stack.3d.up.fill": Layers,
  brain: Brain,
  waveform: AudioWaveform,
  "square.grid.2x2": LayoutGrid,
  "bubble.left.and.bubble.right": MessagesSquare,
} satisfies Record<string, LucideIcon>;

type IconName = keyof typeof ICONS;

const iconPaths = new Map<IconName, Path2D[]>();

function elementPath(el: Element): Path2D | null {
  const num = (name: string) => Number(el.getAttribute(name) ?? 0);
  const path = new Path2D();
  const points = () =>
    (el.getAttribute("points") ?? "")
      .trim()
      .split(/[\s,]+/)
      .map(Number);
  switch (el.tagName.toLowerCase()) {
    case "path":
      return new Path2D(el.getAttribute("d") ?? "");
    case "circle":
      path.arc(num("cx"), num("cy"), num("r"), 0, Math.PI * 2);
      return path;
    case "ellipse":
      path.ellipse(num("cx"), num("cy"), num("rx"), num("ry"), 0, 0, Math.PI * 2);
      return path;
    case "line":
      path.moveTo(num("x1"), num("y1"));
      path.lineTo(num("x2"), num("y2"));
      return path;
    case "rect": {
      const x = num("x");
      const y = num("y");
      const w = num("width");
      const h = num("height");
      const r = Math.min(num("rx") || num("ry"), w / 2, h / 2);
      path.moveTo(x + r, y);
      path.arcTo(x + w, y, x + w, y + h, r);
      path.arcTo(x + w, y + h, x, y + h, r);
      path.arcTo(x, y + h, x, y, r);
      path.arcTo(x, y, x + w, y, r);
      path.closePath();
      return path;
    }
    case "polyline":
    case "polygon": {
      const values = points();
      for (let i = 0; i + 1 < values.length; i += 2) {
        if (i === 0) path.moveTo(values[i], values[i + 1]);
        else path.lineTo(values[i], values[i + 1]);
      }
      if (el.tagName.toLowerCase() === "polygon") path.closePath();
      return path;
    }
    default:
      return null;
  }
}

/** 第一次复制时把用到的图标渲染成 SVG 再拆成路径；失败就不画图标，图照样出。 */
async function loadIcons(): Promise<void> {
  if (iconPaths.size === Object.keys(ICONS).length) return;
  try {
    const { renderToStaticMarkup } = await import("react-dom/server");
    const parser = new DOMParser();
    for (const [name, icon] of Object.entries(ICONS) as [IconName, LucideIcon][]) {
      if (iconPaths.has(name)) continue;
      const markup = renderToStaticMarkup(createElement(icon, { size: 24 }));
      const svg = parser.parseFromString(markup, "image/svg+xml").documentElement;
      iconPaths.set(
        name,
        Array.from(svg.children)
          .map(elementPath)
          .filter((p): p is Path2D => p !== null),
      );
    }
  } catch (err) {
    console.error(err);
  }
}

function drawIcon(ctx: CanvasRenderingContext2D, name: IconName, x: number, y: number, size: number, stroke: string, width: number) {
  const paths = iconPaths.get(name);
  if (!paths?.length) return;
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(size / 24, size / 24);
  ctx.strokeStyle = stroke;
  ctx.lineWidth = width;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  for (const p of paths) ctx.stroke(p);
  ctx.restore();
}

// ---- 基本图元 ----

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  const radius = Math.max(0, Math.min(r, w / 2, h / 2));
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.arcTo(x + w, y, x + w, y + h, radius);
  ctx.arcTo(x + w, y + h, x, y + h, radius);
  ctx.arcTo(x, y + h, x, y, radius);
  ctx.arcTo(x, y, x + w, y, radius);
  ctx.closePath();
}

/** 圆角矩形描边画在内侧（strokeBorder）。 */
function strokeBorder(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number, style: string | CanvasGradient) {
  roundRect(ctx, x + 0.5, y + 0.5, w - 1, h - 1, r - 0.5);
  ctx.strokeStyle = style;
  ctx.lineWidth = 1;
  ctx.stroke();
}

const fontSpec = (size: number, weight: number, family: string) => `${weight} ${size}px ${family}`;

function fit(ctx: CanvasRenderingContext2D, text: string, maxWidth?: number): string {
  if (maxWidth == null || ctx.measureText(text).width <= maxWidth) return text;
  let s = text;
  while (s.length > 0 && ctx.measureText(`${s}…`).width > maxWidth) s = s.slice(0, -1);
  return `${s}…`;
}

/** 单行文字，竖直居中在 centerY；返回实际宽度。 */
function drawText(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  centerY: number,
  font: string,
  fillStyle: string,
  maxWidth?: number,
): number {
  ctx.font = font;
  ctx.fillStyle = fillStyle;
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  const shown = fit(ctx, text, maxWidth);
  ctx.fillText(shown, x, centerY);
  return ctx.measureText(shown).width;
}

/** 会话数徽标（卡头、分享图标题旁）。 */
function sessionsCapsule(ctx: CanvasRenderingContext2D, value: number, x: number, centerY: number, tint: RGB, f: Fonts): number {
  ctx.font = fontSpec(10, 700, f.sans);
  const text = String(value);
  const w = ctx.measureText(text).width + 10;
  const h = lh(10) + 3;
  roundRect(ctx, x, centerY - h / 2, w, h, h / 2);
  ctx.fillStyle = rgba(tint, 0.14);
  ctx.fill();
  drawText(ctx, text, x + 5, centerY, fontSpec(10, 700, f.sans), rgba(tint));
  return w;
}

type Cell =
  | { kind: "metric"; icon: IconName; label: string; value: string; tint: RGB }
  | { kind: "ring"; value: number; label: string; tint: RGB };

const metricCell = (icon: IconName, label: string, value: string, tint: RGB): Cell => ({ kind: "metric", icon, label, value, tint });

const cellRowHeight = () => Math.max(21, lh(fs(9.5)) + 1 + lh(fs(12.5)));

function drawCell(ctx: CanvasRenderingContext2D, cell: Cell, x: number, y: number, w: number, h: number, f: Fonts) {
  const cx = x + 10.5;
  const cy = y + h / 2;
  if (cell.kind === "metric") {
    ctx.beginPath();
    ctx.arc(cx, cy, 10.5, 0, Math.PI * 2);
    ctx.fillStyle = rgba(cell.tint, 0.1);
    ctx.fill();
    const size = fs(10.5);
    drawIcon(ctx, cell.icon, cx - size / 2, cy - size / 2, size, rgba(cell.tint), 2.6);
  } else {
    const r = (21 - 2.5) / 2;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.strokeStyle = fill(0.1);
    ctx.lineWidth = 2.5;
    ctx.stroke();
    const pct = Math.max(0.001, Math.min(1, cell.value / 100));
    const gradient = ctx.createLinearGradient(0, cy - r, 0, cy + r);
    gradient.addColorStop(0, rgba(cell.tint));
    gradient.addColorStop(1, rgba(darker(cell.tint)));
    ctx.beginPath();
    ctx.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * pct);
    ctx.strokeStyle = gradient;
    ctx.lineCap = "round";
    ctx.stroke();
    ctx.lineCap = "butt";
  }
  const labelH = lh(fs(9.5));
  const valueH = lh(fs(12.5));
  const top = y + (h - labelH - 1 - valueH) / 2;
  const textX = x + 21 + 8;
  const maxWidth = w - 21 - 8;
  const value = cell.kind === "ring" ? `${Math.round(cell.value)}%` : cell.value;
  drawText(ctx, cell.label, textX, top + labelH / 2, fontSpec(fs(9.5), 400, f.sans), T.tertiary, maxWidth);
  drawText(ctx, value, textX, top + labelH + 1 + valueH / 2, fontSpec(fs(12.5), 600, f.mono), T.primary, maxWidth);
}

/** 两列指标格（LazyVGrid）；ctx 为空时只量高度。 */
function drawGrid(ctx: CanvasRenderingContext2D | null, cells: Cell[], x: number, y: number, w: number, rowSpacing: number, f: Fonts): number {
  if (!cells.length) return 0;
  const colW = (w - 10) / 2;
  const rowH = cellRowHeight();
  const rows = Math.ceil(cells.length / 2);
  if (ctx) {
    cells.forEach((cell, i) => {
      drawCell(ctx, cell, x + (i % 2) * (colW + 10), y + Math.floor(i / 2) * (rowH + rowSpacing), colW, rowH, f);
    });
  }
  return rows * rowH + (rows - 1) * rowSpacing;
}

/** 大号总量 + 区间说明，按基线对齐（CostHeadline）。 */
function drawHeadline(ctx: CanvasRenderingContext2D | null, value: string, caption: string, x: number, y: number, w: number, f: Fonts): number {
  const size = fs(23);
  const h = lh(size);
  if (ctx) {
    const bigFont = fontSpec(size, 700, f.sans);
    ctx.font = bigFont;
    const m = ctx.measureText(value);
    const ascent = m.fontBoundingBoxAscent || size * 0.8;
    const descent = m.fontBoundingBoxDescent || size * 0.2;
    const baseline = y + (h - (ascent + descent)) / 2 + ascent;
    ctx.textAlign = "left";
    ctx.textBaseline = "alphabetic";
    ctx.fillStyle = "#fff";
    ctx.fillText(value, x, baseline);
    ctx.font = fontSpec(fs(10), 400, f.sans);
    ctx.fillStyle = T.tertiary;
    const captionX = x + m.width + 7;
    ctx.fillText(fit(ctx, caption, Math.max(0, x + w - captionX)), captionX, baseline);
  }
  return h;
}

/** 分享图标题：计时器图标 + 标题（+ 会话数）+ 副标题（shareHeader）。 */
function drawShareHeader(
  ctx: CanvasRenderingContext2D | null,
  title: string,
  subtitle: string,
  tint: RGB,
  x: number,
  y: number,
  w: number,
  f: Fonts,
  sessions?: number | null,
): number {
  const titleH = lh(15);
  const subH = lh(10);
  const h = titleH + 2 + subH;
  if (ctx) {
    const iconSize = 17;
    drawIcon(ctx, "timer", x, y + h / 2 - iconSize / 2, iconSize, rgba(tint), 2.6);
    const tx = x + iconSize + 9;
    const titleW = drawText(ctx, title, tx, y + titleH / 2, fontSpec(15, 700, f.sans), T.primary, w - (tx - x) - 40);
    if (sessions != null && sessions > 0) sessionsCapsule(ctx, sessions, tx + titleW + 6, y + titleH / 2, tint, f);
    drawText(ctx, subtitle, tx, y + titleH + 2 + subH / 2, fontSpec(10, 500, f.sans), T.tertiary, w - (tx - x));
  }
  return h;
}

function lineCells(line: ShareLine, tint: RGB): Cell[] {
  const cells: Cell[] = [];
  if (line.cost != null && (line.cost > 0 || (line.cost_cny ?? 0) > 0)) {
    cells.push(metricCell("dollarsign.circle", L("≈成本"), Fmt.nativeMoney(line.cost, line.cost_cny), tint));
  }
  if ((line.hit ?? 0) > 0) cells.push({ kind: "ring", value: line.hit ?? 0, label: "Cache Hit", tint });
  if ((line.input ?? 0) > 0) cells.push(metricCell("arrow.down", L("输入"), Fmt.human(line.input ?? 0), tint));
  if ((line.output ?? 0) > 0) cells.push(metricCell("arrow.up", L("输出"), Fmt.human(line.output ?? 0), tint));
  if ((line.cacheRead ?? 0) > 0) cells.push(metricCell("bolt.fill", L("缓存读"), Fmt.human(line.cacheRead ?? 0), tint));
  if ((line.cacheWrite ?? 0) > 0) cells.push(metricCell("square.stack.3d.up.fill", L("缓存写"), Fmt.human(line.cacheWrite ?? 0), tint));
  if ((line.reason ?? 0) > 0) cells.push(metricCell("brain", L("推理"), Fmt.human(line.reason ?? 0), tint));
  if ((line.calls ?? 0) > 0) cells.push(metricCell("waveform", L("调用"), String(line.calls), tint));
  return cells;
}

/** 一个工具的卡片（nativeToolCard）：色点 + 名称 + 会话数、总量、指标格。 */
function drawToolCard(
  ctx: CanvasRenderingContext2D | null,
  line: ShareLine,
  periodLabel: string,
  compact: boolean,
  x: number,
  y: number,
  w: number,
  f: Fonts,
): number {
  const tint = tintFor(line.name);
  const pad = 12;
  const inner = w - pad * 2;
  const nameSize = compact ? 13 : 14;
  const sessions = line.sessions ?? 0;
  const headH = Math.max(lh(nameSize), sessions > 0 ? lh(10) + 3 : 0, 8);
  const hasTokens = (line.tokens ?? 0) > 0;
  const cells = lineCells(line, tint);
  let h = pad + headH;
  if (hasTokens) h += 10 + lh(fs(23));
  if (cells.length) h += 10 + drawGrid(null, cells, 0, 0, inner, 8, f);
  h += pad;
  if (!ctx) return h;

  roundRect(ctx, x, y, w, h, 16);
  ctx.fillStyle = "rgba(0, 0, 0, 0.28)";
  ctx.fill();
  const border = ctx.createLinearGradient(x, y, x + w, y + h);
  border.addColorStop(0, rgba(tint, 0.35));
  border.addColorStop(1, fill(0.06));
  strokeBorder(ctx, x, y, w, h, 16, border);

  let cy = y + pad;
  const left = x + pad;
  const headCenter = cy + headH / 2;
  ctx.save();
  ctx.shadowColor = rgba(tint, 0.55);
  ctx.shadowBlur = 3 * SCALE;
  const dot = ctx.createLinearGradient(0, headCenter - 4, 0, headCenter + 4);
  dot.addColorStop(0, rgba(tint));
  dot.addColorStop(1, rgba(darker(tint)));
  ctx.beginPath();
  ctx.arc(left + 4, headCenter, 4, 0, Math.PI * 2);
  ctx.fillStyle = dot;
  ctx.fill();
  ctx.restore();
  const nameW = drawText(ctx, line.name, left + 8 + 7, headCenter, fontSpec(nameSize, 700, f.sans), T.primary, inner - 15 - 40);
  if (sessions > 0) sessionsCapsule(ctx, sessions, left + 15 + nameW + 7, headCenter, tint, f);
  cy += headH;

  if (hasTokens) {
    cy += 10;
    cy += drawHeadline(ctx, Fmt.human(line.tokens ?? 0), L("%@ 总量", periodLabel), left, cy, inner, f);
  }
  if (cells.length) {
    cy += 10;
    drawGrid(ctx, cells, left, cy, inner, 8, f);
  }
  return h;
}

function totalsCells(t: ShareTotals): Cell[] {
  const cells: Cell[] = [];
  if (t.cost > 0 || t.cost_cny > 0) cells.push(metricCell("dollarsign.circle", L("≈成本"), Fmt.nativeMoney(t.cost, t.cost_cny), Theme.claude));
  cells.push(metricCell("square.grid.2x2", L("工具"), String(t.tools), Theme.codex));
  if (t.sessions > 0) cells.push(metricCell("bubble.left.and.bubble.right", L("会话"), String(t.sessions), Theme.gemini));
  if (t.calls > 0) cells.push(metricCell("waveform", L("调用"), String(t.calls), Theme.grok));
  if (t.input > 0) cells.push(metricCell("arrow.down", L("输入"), Fmt.human(t.input), Theme.claude));
  if (t.output > 0) cells.push(metricCell("arrow.up", L("输出"), Fmt.human(t.output), Theme.codex));
  if (t.cacheRead > 0) cells.push(metricCell("bolt.fill", L("缓存读"), Fmt.human(t.cacheRead), Theme.hermes));
  if (t.cacheWrite > 0) cells.push(metricCell("square.stack.3d.up.fill", L("缓存写"), Fmt.human(t.cacheWrite), Theme.pi));
  if (t.reason > 0) cells.push(metricCell("brain", L("推理"), Fmt.human(t.reason), Theme.gemini));
  return cells;
}

/** 总览图底部的「合计明细」（detailedTotals）。 */
function drawTotals(ctx: CanvasRenderingContext2D | null, t: ShareTotals, periodLabel: string, x: number, y: number, w: number, f: Fonts): number {
  const pad = 12;
  const inner = w - pad * 2;
  const titleH = lh(11);
  const cells = totalsCells(t);
  let h = pad + titleH;
  if (t.tokens > 0) h += 10 + lh(fs(23));
  h += 10 + drawGrid(null, cells, 0, 0, inner, 9, f);
  h += pad;
  if (!ctx) return h;

  roundRect(ctx, x, y, w, h, 16);
  ctx.fillStyle = "rgba(0, 0, 0, 0.30)";
  ctx.fill();
  strokeBorder(ctx, x, y, w, h, 16, fill(0.08));

  let cy = y + pad;
  const left = x + pad;
  drawText(ctx, L("合计明细"), left, cy + titleH / 2, fontSpec(11, 600, f.sans), T.secondary, inner);
  cy += titleH;
  if (t.tokens > 0) {
    cy += 10;
    cy += drawHeadline(ctx, Fmt.human(t.tokens), L("%@ 总量", periodLabel), left, cy, inner, f);
  }
  cy += 10;
  drawGrid(ctx, cells, left, cy, inner, 9, f);
  return h;
}

/** 落款：更新时间 + 「Tokei · 知度」（footerBrand）。 */
function drawFooter(ctx: CanvasRenderingContext2D | null, updatedLine: string | null, x: number, y: number, w: number, f: Fonts): number {
  const updatedH = updatedLine ? lh(10) + 4 : 0;
  const brandH = lh(9);
  if (ctx) {
    if (updatedLine) drawText(ctx, updatedLine, x, y + lh(10) / 2, fontSpec(10, 400, f.mono), T.tertiary, w);
    drawText(ctx, L("Tokei · 知度"), x, y + updatedH + brandH / 2, fontSpec(9, 500, f.sans), fill(0.58 * 0.85), w);
  }
  return updatedH + brandH;
}

/** 整张图的底：上浅下深的圆角卡片 + 细描边（shareBackground）。 */
function drawBackground(ctx: CanvasRenderingContext2D, w: number, h: number) {
  roundRect(ctx, 0, 0, w, h, 18);
  const gradient = ctx.createLinearGradient(0, 0, 0, h);
  gradient.addColorStop(0, rgba([0.2, 0.21, 0.25]));
  gradient.addColorStop(1, rgba([0.12, 0.13, 0.16]));
  ctx.fillStyle = gradient;
  ctx.fill();
  strokeBorder(ctx, 0, 0, w, h, 18, fill(0.1));
}

type Layout = (ctx: CanvasRenderingContext2D | null, f: Fonts) => number;

/** 先量高度再按 2 倍分辨率画，导出 PNG。 */
async function renderPNG(width: number, layout: Layout): Promise<Blob> {
  await loadIcons();
  const f = readFonts();
  const height = Math.ceil(layout(null, f));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(width * SCALE);
  canvas.height = Math.round(height * SCALE);
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("canvas 2d unavailable");
  ctx.scale(SCALE, SCALE);
  drawBackground(ctx, width, height);
  layout(ctx, f);
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("toBlob failed"))), "image/png");
  });
}

/** 总览图（UsageShareOverviewView）：每个工具一张紧凑卡片，底下合计明细。 */
function overviewLayout(lines: ShareLine[], range: RangeKey, updatedLine: string | null): Layout {
  const period = rangeLabel(range);
  const totals = shareTotals(lines);
  return (ctx, f) => {
    const pad = 16;
    const inner = MULTI_WIDTH - pad * 2;
    let y = pad;
    y += drawShareHeader(ctx, L("Tokei 用量"), period, Theme.claude, pad, y, inner, f);
    y += 13;
    if (!lines.length) {
      const h = lh(12);
      if (ctx) drawText(ctx, L("当前范围无可分享的用量"), pad, y + 18 + h / 2, fontSpec(12, 400, f.sans), T.tertiary, inner);
      y += 18 + h + 18;
    } else {
      lines.forEach((line, i) => {
        if (i > 0) y += 10;
        y += drawToolCard(ctx, line, period, true, pad, y, inner, f);
      });
      y += 13;
      y += drawTotals(ctx, totals, period, pad, y, inner, f);
    }
    y += 13;
    y += drawFooter(ctx, updatedLine, pad, y, inner, f);
    return y + pad;
  };
}

/** 单个工具的图（UsageShareToolView）。 */
function toolLayout(line: ShareLine, range: RangeKey, updatedLine: string | null): Layout {
  const period = rangeLabel(range);
  return (ctx, f) => {
    const pad = 16;
    const inner = SINGLE_WIDTH - pad * 2;
    let y = pad;
    y += drawShareHeader(ctx, line.name, `Tokei · ${period}`, tintFor(line.name), pad, y, inner, f, line.sessions);
    y += 12;
    y += drawToolCard(ctx, line, period, false, pad, y, inner, f);
    y += 12;
    y += drawFooter(ctx, updatedLine, pad, y, inner, f);
    return y + pad;
  };
}

/**
 * 写进剪贴板。ClipboardItem 直接收 Promise：在点击的同一拍里调用 clipboard.write，
 * 不会因为画图耗时丢掉用户手势；不支持 Promise 的环境再等图画完重写一次。
 */
async function writePNG(render: () => Promise<Blob>): Promise<boolean> {
  if (typeof ClipboardItem === "undefined" || !navigator.clipboard?.write) return false;
  let blob: Promise<Blob>;
  try {
    blob = render();
  } catch (err) {
    console.error(err);
    return false;
  }
  blob.catch(() => undefined);
  try {
    await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
    return true;
  } catch {
    try {
      const resolved = await blob;
      await navigator.clipboard.write([new ClipboardItem({ "image/png": resolved })]);
      return true;
    } catch (err) {
      console.error(err);
      return false;
    }
  }
}

/** 总览图的 PNG（不写剪贴板）。 */
export function usageImageBlob(
  usage: Usage,
  range: RangeKey,
  visibility: Record<string, boolean>,
  updated: string,
): Promise<Blob> {
  const lines = shareToolLines(usage, range, visibility);
  return renderPNG(MULTI_WIDTH, overviewLayout(lines, range, formatUpdatedLine(updated)));
}

/** 单个工具的 PNG；这个工具在当前区间没有可分享的用量时是 null。 */
export function singleToolImageBlob(
  toolId: string,
  usage: Usage,
  range: RangeKey,
  visibility: Record<string, boolean>,
  updated: string,
): Promise<Blob> | null {
  const line = shareToolLines(usage, range, visibility).find((l) => l.id === toolId);
  return line ? renderPNG(SINGLE_WIDTH, toolLayout(line, range, formatUpdatedLine(updated))) : null;
}

/** 页脚「复制」：当前区间、已打开显示的所有工具的用量总览图。 */
export async function copyUsageImage(
  usage: Usage,
  range: RangeKey,
  visibility: Record<string, boolean>,
  updated: string,
): Promise<boolean> {
  return writePNG(() => usageImageBlob(usage, range, visibility, updated));
}

/** 卡头的复制按钮：单个工具的用量图；这个工具在当前区间没有可分享的用量时返回 false。 */
export async function copySingleToolImage(
  toolId: string,
  usage: Usage,
  range: RangeKey,
  visibility: Record<string, boolean>,
  updated: string,
): Promise<boolean> {
  let blob: Promise<Blob> | null;
  try {
    blob = singleToolImageBlob(toolId, usage, range, visibility, updated);
  } catch (err) {
    console.error(err);
    return false;
  }
  if (!blob) return false;
  const pending = blob;
  return writePNG(() => pending);
}
