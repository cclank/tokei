import assert from "node:assert/strict";
import { after, test } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { testRuntime } from "./runtime.mjs";

const runtime = await testRuntime();
const RealDate = globalThis.Date;
let clock = Math.floor(RealDate.now() / 60000) * 60000;
const base = clock / 1000;
globalThis.Date = class extends RealDate {
  constructor(...args) { super(...(args.length ? args : [clock])); }
  static now() { return clock; }
};
after(async () => { globalThis.Date = RealDate; await runtime.close(); });

const gemini = "antigravity-gemini-weekly";
const fiveHour = "antigravity-gemini-5h";
const thirdParty = "antigravity-3p-weekly";
const argon = "antigravity-gemini-argon-weekly";
const legacy = {
  version: 1,
  points: [{ timestamp: base - 120, claudeWeekRemaining: 74, codexWeekRemaining: 42,
    claudeActivity: [], codexActivity: [{ model: "gpt-fixture", tokenDelta: 100 }] }],
  lastClaudeModelTotals: {}, lastCodexModelTotals: {}, hasClaudeBaseline: false, hasCodexBaseline: false,
};
let saved = JSON.stringify(legacy);
const writes = [];
window.__TAURI_INTERNALS__ = {
  invoke: async (command, args) => {
    assert.equal(args.name, "quota_history.json");
    if (command === "read_tokei_file") return saved;
    assert.equal(command, "write_tokei_file", "history must not launch a collector or make quota requests");
    saved = args.content; writes.push(JSON.parse(saved));
  },
};
const history = await runtime.load("src/lib/quotaHistory.ts");
const projection = await runtime.load("src/pages/quotaHistory/projection.ts");
const { QuotaSummary } = await runtime.load("src/pages/quotaHistory/curveSections.tsx");
const reading = (id, used_pct, extra = {}) => ({ id, used_pct, ...extra });
const usage = windows => ({ antigravity: { available: true, stale: false, windows } });

test("Antigravity captures only known, unexpired readings and preserves real zero/full values", () => {
  const input = usage([
    reading(gemini, 0, { reset: base + 1 }), reading(thirdParty, 100), reading(fiveHour, 50),
    reading("expired", 10, { reset: base }), reading("unknown", 0, { usage_known: false }),
    reading("missing", null), reading("negative", -1), reading("over", 101),
    reading("nan", NaN), reading("infinity", Infinity), reading("", 1),
  ]);
  assert.deepEqual(history.quotaCapture(input, base).antigravityRemaining, { [thirdParty]: 0, [gemini]: 100 });
  assert.equal(history.quotaCapture(input, base).antigravityRemaining[fiveHour], undefined);
  input.antigravity.stale = true;
  assert.equal(history.quotaCapture(input, base).antigravityRemaining, undefined);
  input.antigravity.stale = false; input.antigravity.available = false;
  assert.equal(history.quotaCapture(input, base).antigravityRemaining, undefined);
});

test("persisted legacy history, same-minute partial updates and independent quota pools coexist", async () => {
  await history.loadQuotaHistory();
  assert.equal(history.quotaHistoryPoints().length, 1, "v1 history without new fields must load");
  await history.recordQuotaHistory(usage([reading(gemini, 1), reading(fiveHour, 100), reading(thirdParty, 0), reading(argon, 1)]));
  clock += 30000;
  await history.recordQuotaHistory(usage([reading(gemini, 10), reading(thirdParty, 0, { usage_known: false })]));
  let points = history.quotaHistoryPoints();
  assert.equal(points.length, 2, "updates in one minute merge");
  assert.equal(points.at(-1).antigravityRemaining[gemini], 90);
  assert.equal(points.at(-1).antigravityRemaining[thirdParty], 100, "unknown partial readings preserve last valid same-minute data");
  assert.equal(points.at(-1).antigravityRemaining[fiveHour], undefined, "five-hour quotas are not recorded in history");

  clock += 30000;
  await history.recordQuotaHistory(usage([reading(gemini, 20), reading(thirdParty, 4), reading(argon, 40)]));
  points = history.quotaHistoryPoints();
  assert.equal(points.at(-1).antigravityRemaining[fiveHour], undefined, "no forward-filled quota for missing windows");
  const label = projection.ANTIGRAVITY_WINDOWS.find(w => w.id === gemini).title;
  const graph = projection.projectQuotaHistory(points, "Antigravity", label);
  assert.deepEqual(graph.windowNames, [label]);
  assert.equal(graph.points.length, 2, "Claude/Codex-only samples do not count as Antigravity samples");
  assert.deepEqual(graph.dropEvents.map(event => event.drop), [10]);
  assert.equal(graph.activityEvents.length, 0, "never copy Codex activity onto Antigravity");
  const argonLabel = projection.ANTIGRAVITY_WINDOWS.find(w => w.id === argon).title;
  assert.deepEqual(projection.projectQuotaHistory(points, "Antigravity", argonLabel).dropEvents.map(e => e.drop), [39]);
  const summary = renderToStaticMarkup(createElement(QuotaSummary, { projection: graph, tool: "Antigravity" }));
  assert.match(summary, /80\.0%/);
  assert.doesNotMatch(summary, /Claude\/GPT|Argon/);

  clock += 60000;
  await history.recordQuotaHistory(usage([reading(gemini, 0)]));
  const daily = projection.dailyConsumption(history.quotaHistoryPoints(), "Antigravity").find(row => row.window === label);
  assert.equal(daily.consumed, 10, "a refill does not cancel consumption");
  assert.equal(daily.refills, 1);
  const persisted = writes.at(-1);
  assert.equal(persisted.version, 1);
  assert.deepEqual(persisted.points[0], legacy.points[0], "existing tool history survives serialization");
  assert.equal(persisted.points.at(-1).antigravityRemaining[gemini], 100);
  assert.ok(projection.QUOTA_HISTORY_TOOLS.includes("Antigravity"));
  assert.ok(projection.ANTIGRAVITY_WINDOWS.every(window => window.id.endsWith("-weekly")));
});
