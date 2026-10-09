// 「诊断」与「价格表」两块（Mac 版 settingsDiagnosticsSection / settingsPricingSection、
// runPriceUpdate、toggleDiagnostics）。
import { useEffect, useState } from "react";
import { runCollector } from "../../lib/collector";
import { L } from "../../lib/i18n";
import { useUsageStore } from "../../lib/store";
import { Icon } from "../../ui/Icon";
import { fill, fs, T } from "../../ui/theme";
import { ActionButton, MiniSpinner, SettingsSection } from "./controls";
import { diagnosticsSummary, runDiagnostics } from "./diagnostics";

const MONO = "var(--mono)";

/** 失败时 run_collector 的报错是「采集脚本退出码 …」一行加 stderr 末尾，只留 stderr 那段。 */
function collectorError(err: unknown): string {
  const message = (err instanceof Error ? err.message : String(err)).trim();
  const newline = message.indexOf("\n");
  const tail = newline >= 0 ? message.slice(newline + 1).trim() : "";
  return tail || message;
}

export function PricingSection() {
  const { refresh } = useUsageStore();
  const [updating, setUpdating] = useState(false);
  const [result, setResult] = useState("");

  const run = async (flag: "--update-prices" | "--update-unknown", message: string) => {
    setUpdating(true);
    setResult(message);
    let next: string;
    try {
      const output = await runCollector([flag]);
      next = output.trim();
      if (flag === "--update-unknown") {
        try {
          const json = JSON.parse(output) as { count?: unknown };
          if (typeof json.count === "number" && Number.isInteger(json.count)) {
            next = json.count > 0 ? L("补全 %@ 个模型", json.count) : L("所有模型已匹配 ✓");
          }
        } catch {
          // 不是 JSON 就原样显示
        }
      }
    } catch (err) {
      next = collectorError(err);
    }
    setUpdating(false);
    setResult(next);
    refresh();
  };

  // 结果停留 30 秒后自动消失，点一下也能收起。
  useEffect(() => {
    if (!result || updating) return;
    const timer = window.setTimeout(() => setResult(""), 30_000);
    return () => window.clearTimeout(timer);
  }, [result, updating]);

  return (
    <SettingsSection icon="dollarsign.circle" title={L("价格表")}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <ActionButton
          icon="arrow.down.circle"
          title={L("全量更新")}
          disabled={updating}
          onClick={() => void run("--update-prices", L("全量更新中…"))}
        />
        <ActionButton
          icon="magnifyingglass.circle"
          title={L("查漏补缺")}
          disabled={updating}
          onClick={() => void run("--update-unknown", L("查漏补缺中…"))}
        />
        {updating && <MiniSpinner />}
      </div>
      {result && !updating && (
        <span
          className="st-clamp"
          title={result}
          onClick={() => setResult("")}
          style={{ WebkitLineClamp: 2, fontSize: fs(9), color: T.tertiary, cursor: "pointer", overflowWrap: "anywhere" }}
        >
          {result}
        </span>
      )}
    </SettingsSection>
  );
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    return;
  } catch {
    // WebView 不给剪贴板权限时退回老办法
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  document.execCommand("copy");
  area.remove();
}

export function DiagnosticsSection() {
  const [running, setRunning] = useState(false);
  const [output, setOutput] = useState("");
  const [expanded, setExpanded] = useState(false);

  const toggle = async () => {
    if (!running && output) {
      setOutput("");
      setExpanded(false);
      return;
    }
    setRunning(true);
    setOutput("running...");
    setExpanded(false);
    const report = await runDiagnostics();
    setRunning(false);
    setOutput(report);
  };

  const title = running ? L("检查中…") : output ? L("收起诊断") : L("运行诊断");
  const summary = diagnosticsSummary(output);

  return (
    <SettingsSection icon="stethoscope" title={L("诊断")}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <ActionButton
          icon={!output || running ? "ladybug" : "chevron.up.circle"}
          title={title}
          disabled={running}
          onClick={() => void toggle()}
        />
        {running && <MiniSpinner />}
        <div style={{ flex: 1 }} />
        {output && (
          <button className="st-circle" title={L("复制诊断")} onClick={() => void copyText(output)} style={{ width: 22, height: 22 }}>
            <Icon name="doc.on.doc" size={fs(10)} />
          </button>
        )}
      </div>
      {output && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, padding: 8, borderRadius: 6, background: fill(0.05), minWidth: 0 }}>
          <button
            className="plain"
            onClick={() => setExpanded((value) => !value)}
            style={{ display: "flex", alignItems: "center", gap: 5, width: "100%", color: T.secondary, minWidth: 0 }}
          >
            <Icon name={expanded ? "chevron.down" : "chevron.right"} size={fs(8)} strokeWidth={3} />
            <span
              style={{
                flex: 1,
                minWidth: 0,
                fontSize: fs(9),
                fontFamily: MONO,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {summary}
            </span>
          </button>
          {expanded && (
            <span
              className="st-clamp"
              style={{
                WebkitLineClamp: 16,
                fontSize: fs(8.5),
                fontFamily: MONO,
                color: T.secondary,
                whiteSpace: "pre-wrap",
                overflowWrap: "anywhere",
                userSelect: "text",
              }}
            >
              {output}
            </span>
          )}
        </div>
      )}
    </SettingsSection>
  );
}
