// 诊断（Mac 版 runDiagnostics / formatDiagnostics / debugSummary）：跑一遍 `--json`，
// 把退出状态、输出大小、各家有没有数据、价格表、采集错误汇总成几行纯文本，方便复制给开发者。
import { call, inTauri, runCollector } from "../../lib/collector";

/** 与 Mac 版 formatDiagnostics 同一张表、同样的顺序。 */
const TOOLS = [
  "claude", "codex", "gemini", "antigravity", "cursor", "zed",
  "sub2api", "zai", "grok", "grok_bot", "qoder", "qoderwork", "qodercli",
  "qodercli_cn", "hermes",
  "zcode", "mimocode", "openclaw", "pi", "workbuddy", "workbuddy_ai",
  "codebuddy",
  "deepseek_harness",
  "opencode", "qwencode", "qwenwork", "kimicode", "musecode", "cmdcode", "prime_agent",
  "devin", "minimax",
];

interface ScriptResult {
  /** 采集脚本与 Python 的路径（Tauri 里才有；浏览器调界面时为空）。 */
  script?: { path: string; exists: boolean; size: number; python: string };
  exitCode: number;
  timedOut: boolean;
  elapsed: number;
  stdout: string;
  stderr: string;
}

/** Rust 侧 collector::RawOutput。 */
interface RawOutput {
  python: string;
  script: string;
  script_exists: boolean;
  script_size: number;
  exit_code: number | null;
  timed_out: boolean;
  elapsed: number;
  stdout: string;
  stderr: string;
}

/** Mac 版 DataLoader.runScriptRaw：不管成败都拿回退出状态和两路输出。 */
async function runScriptRaw(args: string[]): Promise<ScriptResult> {
  if (inTauri) {
    try {
      const raw = await call<RawOutput>("run_collector_raw", { args });
      if (raw) {
        return {
          script: { path: raw.script, exists: raw.script_exists, size: raw.script_size, python: raw.python },
          exitCode: raw.exit_code ?? -1,
          timedOut: raw.timed_out,
          elapsed: raw.elapsed,
          stdout: raw.stdout,
          stderr: raw.stderr,
        };
      }
    } catch (err) {
      return { exitCode: -1, timedOut: false, elapsed: 0, stdout: "", stderr: err instanceof Error ? err.message : String(err) };
    }
  }
  // 浏览器里调界面：走开发中间件，失败时只拿得到报错文本。
  const started = performance.now();
  try {
    const stdout = await runCollector(args);
    return { exitCode: 0, timedOut: false, elapsed: (performance.now() - started) / 1000, stdout, stderr: "" };
  } catch (err) {
    const elapsed = (performance.now() - started) / 1000;
    return { exitCode: -1, timedOut: false, elapsed, stdout: "", stderr: err instanceof Error ? err.message : String(err) };
  }
}

function describe(value: unknown): string {
  if (value == null) return "";
  return typeof value === "string" ? value : JSON.stringify(value);
}

export function formatDiagnostics(result: ScriptResult): string {
  const lines = result.script
    ? [
        `script: ${result.script.path}`,
        `exists: ${result.script.exists} size: ${result.script.size}B`,
        `python: ${result.script.python}`,
      ]
    : [];
  lines.push(
    `exit: ${result.exitCode} timeout: ${result.timedOut ? "yes" : "no"} elapsed: ${result.elapsed.toFixed(2)}s`,
    `stdout: ${new TextEncoder().encode(result.stdout).length}B stderr: ${new TextEncoder().encode(result.stderr).length}B`,
  );

  let json: Record<string, unknown> | null = null;
  try {
    const parsed: unknown = JSON.parse(result.stdout);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) json = parsed as Record<string, unknown>;
  } catch {
    json = null;
  }

  if (json) {
    const data = json;
    lines.push(`json: ok tools: ${TOOLS.filter((tool) => data[tool] != null).join(",")}`);
    const pricing = data._pricing as Record<string, unknown> | undefined;
    if (pricing && typeof pricing === "object") {
      lines.push(`pricing: ${describe(pricing.count) || "?"} ${describe(pricing.updated_at)}`);
    }
    const errors = data._errors as Record<string, unknown> | undefined;
    const keys = errors && typeof errors === "object" ? Object.keys(errors).sort() : [];
    if (errors && keys.length) {
      lines.push("errors:");
      for (const key of keys) lines.push(`- ${key}: ${describe(errors[key])}`);
    } else {
      lines.push("errors: none");
    }
  } else if (result.stdout.trim()) {
    lines.push("json: invalid");
    lines.push(result.stdout.slice(0, 600));
  }

  if (result.stderr.trim()) {
    lines.push("stderr:");
    lines.push(result.stderr.slice(0, 600));
  }
  return lines.join("\n");
}

export async function runDiagnostics(): Promise<string> {
  return formatDiagnostics(await runScriptRaw(["--json"]));
}

/** 折叠时的一行摘要：exit · json · errors。 */
export function diagnosticsSummary(output: string): string {
  if (!output) return "";
  const lines = output.split(/\r?\n/);
  return ["exit:", "json:", "errors:"]
    .map((prefix) => lines.find((line) => line.startsWith(prefix)) ?? "")
    .filter(Boolean)
    .join(" · ");
}
