// 数据面板里的条形列表：模型用量、账号 Provider 模型、项目排行（DashboardView 的
// modelSection / providerModelSection / projectsSection，条形是 Design.swift 的 StatBar）。
import { ChevronDown, ChevronUp, Eye, EyeOff } from "lucide-react";
import * as Fmt from "../../lib/fmt";
import { data, L } from "../../lib/i18n";
import { usePref } from "../../lib/prefs";
import { fill, fs, rgba, T, Theme, type RGB } from "../../ui/theme";
import type { ModelCost, WrappedProject } from "./types";

const MONO = "var(--mono)";

/** 段落标题：13pt 粗体。 */
export function SectionTitle({ children }: { children: string }) {
  return <span style={{ fontSize: fs(13), fontWeight: 700, color: T.primary, whiteSpace: "nowrap" }}>{children}</span>;
}

/** Divider().opacity(0.15)：分隔线（深色下 separator 约 10% 白）再乘 0.15。 */
export function FaintDivider() {
  return <div style={{ height: 1, background: fill(0.1 * 0.15), flex: "none" }} />;
}

/** 名称 + token + 金额，下面一根按 √(tokens/最大值) 缩放的渐变胶囊条。 */
export function StatBar({
  name,
  tokens,
  cost,
  costCny,
  maxTokens,
  tint,
}: {
  name: string;
  tokens: number;
  cost: number;
  costCny?: number | null;
  maxTokens: number;
  tint: RGB;
}) {
  const ratio = maxTokens > 0 ? Math.sqrt(tokens / maxTokens) : 0;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5, minWidth: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
        <span
          title={name}
          style={{
            fontSize: fs(11),
            fontWeight: 500,
            color: T.primary,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
            minWidth: 0,
            flex: "0 1 auto",
          }}
        >
          {name}
        </span>
        <div style={{ flex: 1, minWidth: 8 }} />
        <span style={{ fontSize: fs(9.5), fontFamily: MONO, color: T.tertiary, whiteSpace: "nowrap", flex: "none" }}>
          {Fmt.human(tokens)}
        </span>
        <span style={{ fontSize: fs(10), fontWeight: 600, fontFamily: MONO, color: T.secondary, whiteSpace: "nowrap", flex: "none" }}>
          {Fmt.nativeMoney(cost, costCny)}
        </span>
      </div>
      <div style={{ height: 5, position: "relative" }}>
        <div
          className="dash-bar"
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            height: 5,
            width: `max(5px, ${Math.min(1, ratio) * 100}%)`,
            borderRadius: 2.5,
            background: `linear-gradient(90deg, ${rgba(tint, 0.5)}, ${rgba(tint)})`,
          }}
        />
      </div>
    </div>
  );
}

/** 模型行的颜色按来源工具（modelTint）。 */
export function modelTint(tool: string): RGB {
  switch (tool) {
    case "codex":
    case "codex_reserve":
      return Theme.codex;
    case "gemini":
      return Theme.gemini;
    case "cursor":
      return Theme.cursor;
    case "zai":
      return Theme.zai;
    case "grok_bot":
      return Theme.grokBot;
    case "grok":
      return Theme.grok;
    case "qoder":
      return Theme.qoder;
    case "qoderwork":
      return Theme.qoderwork;
    case "qodercli":
      return Theme.qodercli;
    case "qodercli_cn":
      return Theme.qodercliCN;
    case "hermes":
      return Theme.hermes;
    case "zcode":
      return Theme.zcode;
    case "mimocode":
      return Theme.mimocode;
    case "openclaw":
      return Theme.openclaw;
    case "pi":
      return Theme.pi;
    case "prime_agent":
      return Theme.primeAgent;
    case "workbuddy":
      return Theme.workbuddy;
    case "workbuddy_ai":
      return Theme.workbuddyAI;
    case "codebuddy":
      return Theme.codebuddy;
    case "deepseek_harness":
      return Theme.deepseekHarness;
    case "opencode":
      return Theme.opencode;
    case "qwencode":
      return Theme.qwencode;
    case "kimicode":
      return Theme.kimicode;
    case "musecode":
      return Theme.musecode;
    case "cmdcode":
      return Theme.cmdcode;
    case "devin":
      return Theme.devin;
    case "minimax":
      return Theme.minimax;
    default:
      return Theme.claude;
  }
}

/** 按 token 从多到少取前 8 个；最长的那根条以第一名为满。 */
function topModels(models: ModelCost[]) {
  const top = [...models].sort((a, b) => (b.tokens ?? 0) - (a.tokens ?? 0)).slice(0, 8);
  const maxTokens = top.length ? (top[0].tokens ?? 1) : 1;
  return { top, maxTokens };
}

const modelTokens = (m: ModelCost) => m.tokens ?? (m.in ?? 0) + (m.out ?? 0);

export function ModelSection({ models }: { models: ModelCost[] }) {
  const { top, maxTokens } = topModels(models);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
      <SectionTitle>{L("模型用量")}</SectionTitle>
      {top.map((m, i) => (
        <StatBar
          key={`${m.tool}:${m.name}:${i}`}
          name={data(m.name)}
          tokens={modelTokens(m)}
          cost={m.cost}
          costCny={m.cost_cny}
          maxTokens={maxTokens}
          tint={modelTint(m.tool)}
        />
      ))}
    </div>
  );
}

export function ProviderModelSection({ models }: { models: ModelCost[] }) {
  const { top, maxTokens } = topModels(models);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
      <SectionTitle>{L("账号 Provider 模型")}</SectionTitle>
      <span style={{ fontSize: fs(9), color: T.tertiary }}>{L("账号级统计单独展示，不并入本地工具总计")}</span>
      {top.map((m, i) => (
        <StatBar
          key={`${m.tool}:${m.name}:${i}`}
          name={data(m.name)}
          tokens={modelTokens(m)}
          cost={m.cost}
          maxTokens={maxTokens}
          tint={modelTint(m.tool)}
        />
      ))}
    </div>
  );
}

/** 项目排行：标题可点，收起时只写「已隐藏 N 个项目」（偏好 hideProjects 与 Mac 同名）。 */
export function ProjectsSection({ projects }: { projects: WrappedProject[] }) {
  const [hideProjects, setHideProjects] = usePref<boolean>("hideProjects", false);
  const maxTokens = projects.length ? projects[0].tokens : 1;
  const EyeIcon = hideProjects ? EyeOff : Eye;
  const Chevron = hideProjects ? ChevronDown : ChevronUp;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
      <button
        className="plain"
        onClick={() => setHideProjects(!hideProjects)}
        style={{ display: "flex", alignItems: "center", gap: 5, width: "100%" }}
      >
        <SectionTitle>{L("项目排行")}</SectionTitle>
        <EyeIcon size={fs(9)} color={T.tertiary} strokeWidth={2.2} />
        <div style={{ flex: 1 }} />
        <Chevron size={fs(9)} color={T.tertiary} strokeWidth={3} />
      </button>
      {hideProjects ? (
        <span style={{ fontSize: fs(10), color: T.tertiary }}>{L("已隐藏 %@ 个项目", projects.length)}</span>
      ) : (
        projects.map((p, i) => (
          <StatBar
            key={`${p.name}:${i}`}
            name={p.name}
            tokens={p.tokens}
            cost={p.cost}
            costCny={p.cost_cny}
            maxTokens={maxTokens}
            tint={Theme.claude}
          />
        ))
      )}
    </div>
  );
}
