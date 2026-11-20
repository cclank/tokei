import assert from "node:assert/strict";
import { after, beforeEach, test } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { testRuntime } from "./runtime.mjs";

const runtime = await testRuntime();
window.location = { search: "" };
after(() => runtime.close());
beforeEach(() => runtime.clear());
const tokens = await runtime.load("src/lib/trayTokens.ts");
const quota = await runtime.load("src/lib/trayQuota.ts");
const { TrayQuotaSection } = await runtime.load("src/pages/Settings.tsx");
const i18n = await runtime.load("src/lib/i18n.ts");
const now = Math.floor(Date.now() / 1000);
const usage = () => ({
  claude: { q5: 20, q7: 40, q7_reset: now + 1000, ranges: { today: { in: 100, out: 20, cr: 30, cw: 40 }, week: { in: 999999 } } },
  codex: { pw: 35, rw: now + 1000, ranges: { today: { in: 100, cached: 200, out: 50, reason: 40 } },
    reserve_ranges: { today: { in: 10, cached: 20, out: 30, reason: 25 } } },
  gemini: { ranges: { today: { in: 100, cached: 50, out: 20, thoughts: 10 } } },
  grok: { pct: 25, reset: now + 1000, ranges: { today: { tokens: 42 } } },
  antigravity: { windows: [
    { id: "antigravity-gemini-weekly", reset: now + 1000 },
    { id: "antigravity-3p-weekly", reset: now + 1500 },
    { id: "antigravity-gemini-5h", reset: now + 100 },
  ] },
});
const cycle = (tool, overrides = {}) => ({ tool, start: now - 500, end: now + 1000, current: true,
  tokens: 1000, devices: { 本机: 300, peer: 700 }, approx: false, ...overrides });
const detail = (cycles = [cycle("claude"), cycle("codex")]) => ({ daily: [], cycles, devices: ["本机", "peer"], missing: [], now });
const mode = period => { runtime.pref("menuBarContent", "tokens"); runtime.pref("menuBarTokenPeriod", period); };

test("existing quota defaults and independent source preferences are preserved", () => {
  assert.equal(tokens.trayContent(), "quota");
  assert.equal(tokens.tokenPeriod(), "today");
  assert.equal(quota.trayQuotaTooltip(usage()), "Tokei · Claude 5h 80% · Codex 周 65%");
  assert.deepEqual(tokens.TRAY_TOKEN_SOURCES.filter(tokens.trayTokenEnabled).map(s => s.id), ["claude", "codex"]);
  runtime.pref("menuBarTokenClaude", false);
  assert.match(quota.trayQuotaTooltip(usage()), /Claude 5h 80%/);
  mode("today");
  assert.doesNotMatch(quota.trayQuotaTooltip(usage()), /Claude/);
  runtime.pref("menuBarTokenClaude", true);
  runtime.pref("menuBarQuotaClaude", false);
  assert.match(quota.trayQuotaTooltip(usage()), /Claude Code 今日 190 Token/);
  runtime.pref("menuBarContent", "unknown");
  runtime.pref("menuBarTokenPeriod", "unknown");
  assert.equal(tokens.trayContent(), "quota");
  assert.equal(tokens.tokenPeriod(), "today");
});

test("daily token totals count cache once, include reserve and never add Codex reasoning twice", () => {
  mode("today");
  assert.deepEqual(tokens.trayTokenMetrics(usage()).map(m => m.tokens), [190, 410]);
  assert.equal(quota.trayQuotaTooltip(usage()), "Tokei · Claude Code 今日 190 Token · Codex 今日 410 Token");
  assert.equal(tokens.needsTrayCycleData(), false);
  const u = usage();
  u.claude.ranges.today.in = -1;
  assert.equal(tokens.trayTokenMetrics(u)[0].value, "—");
  u.codex.ranges.today.in = Number.MAX_SAFE_INTEGER;
  assert.equal(tokens.trayTokenMetrics(u)[1].tokens, null);
});

test("current period uses actual live cycles and respects the device scope", () => {
  mode("cycle");
  assert.equal(tokens.needsTrayCycleData(), true);
  assert.deepEqual(tokens.trayTokenMetrics(usage(), detail(), false, now).map(m => m.tokens), [300, 300]);
  assert.deepEqual(tokens.trayTokenMetrics(usage(), detail(), true, now).map(m => m.tokens), [1000, 1000]);
  assert.match(quota.trayQuotaTooltip(usage(), detail()), /Claude Code 本周期 300 Token/);
  assert.doesNotMatch(quota.trayQuotaTooltip(usage(), detail()), /999999|%/);
  for (const overrides of [{ current: false }, { end: now }, { start: now + 1 }, { end: now + 1121 }]) {
    assert.equal(tokens.trayTokenMetrics(usage(), detail([cycle("claude", overrides)]), false, now)[0].tokens, null);
  }
  assert.equal(tokens.trayTokenMetrics(usage(), detail([cycle("claude", { end: now + 1120 })]), false, now)[0].tokens, 300);
  assert.equal(tokens.trayTokenMetrics(usage(), null)[0].value, "—");
  assert.match(quota.trayQuotaTooltip(usage(), null), /暂无用量统计/);
});

test("zero local usage and approximate or legacy cycle records keep their meaning", () => {
  mode("cycle");
  const p = detail([cycle("claude", { devices: { peer: 1000 } })]);
  assert.equal(tokens.trayTokenMetrics(usage(), p, false, now)[0].tokens, 0);
  p.cycles[0].devices = {};
  assert.equal(tokens.trayTokenMetrics(usage(), p, false, now)[0].tokens, null);
  p.cycles[0].devices = { 本机: 123456 };
  p.cycles[0].approx = true;
  assert.equal(tokens.trayTokenMetrics(usage(), p, false, now)[0].value, "≈123K");
  assert.match(quota.trayQuotaTooltip(usage(), p), /约 123,456 Token/);
});

test("Antigravity sums only matched weekly pools and requires every active pool", () => {
  mode("cycle");
  runtime.pref("menuBarTokenClaude", false);
  runtime.pref("menuBarTokenCodex", false);
  runtime.pref("menuBarTokenAntigravity", true);
  const p = detail([
    cycle("antigravity", { window_id: "antigravity-gemini-weekly", usage_scope: "local", tokens: 100 }),
    cycle("antigravity", { window_id: "antigravity-3p-weekly", usage_scope: "local", tokens: 200, end: now + 1500, approx: true }),
    cycle("antigravity", { window_id: "antigravity-gemini-5h", tokens: 9999, end: now + 100 }),
  ]);
  assert.equal(tokens.trayTokenMetrics(usage(), p, false, now)[0].tokens, 300);
  assert.equal(tokens.trayTokenMetrics(usage(), p, false, now)[0].approximate, true);
  p.cycles.splice(1, 1);
  assert.equal(tokens.trayTokenMetrics(usage(), p, false, now)[0].tokens, null);
  mode("today");
  assert.equal(tokens.trayTokenMetrics(usage())[0].tokens, 180);
});

test("all sources off avoids cycle collection and long tooltips fit the Windows limit", () => {
  mode("cycle");
  for (const s of tokens.TRAY_TOKEN_SOURCES) runtime.pref(s.key, false);
  assert.equal(tokens.needsTrayCycleData(), false);
  assert.equal(quota.trayQuotaTooltip(usage()), "Tokei");
  mode("today");
  for (const s of tokens.TRAY_TOKEN_SOURCES) runtime.pref(s.key, true);
  const u = usage(), huge = Number.MAX_SAFE_INTEGER;
  u.claude.ranges.today = { in: huge, out: 0, cr: 0, cw: 0 };
  u.codex.ranges.today = { in: huge, cached: 0, out: 0, reason: 0 };
  delete u.codex.reserve_ranges;
  u.gemini.ranges.today = { in: huge, cached: 0, out: 0, thoughts: 0 };
  u.grok.ranges.today.tokens = huge;
  const text = quota.trayQuotaTooltip(u);
  assert.ok(text.length <= 127, text);
  for (const name of ["Claude", "Codex", "Antigravity", "Grok", "Token"]) assert.ok(text.includes(name), text);
});

test("settings expose both modes and periods without mixing quota and token switches", () => {
  let html = renderToStaticMarkup(createElement(TrayQuotaSection));
  assert.match(html, /显示内容|额度百分比|Token 用量/);
  assert.match(html, /Claude 5h/);
  assert.doesNotMatch(html, /用量范围/);
  mode("cycle");
  html = renderToStaticMarkup(createElement(TrayQuotaSection));
  for (const label of ["用量范围", "今日", "本周期", "用量来源", "Claude Code", "Codex"]) assert.ok(html.includes(label), label);
  assert.doesNotMatch(html, /Claude 5h|Codex 5h/);
  assert.match(html, /Windows 通过托盘悬停提示/);
});

test("token tooltip labels use the shared language tables", async () => {
  mode("cycle");
  for (const [lang, period] of [["en", "Current cycle"], ["fr", "Cycle en cours"], ["ja", "現在のサイクル"], ["ko", "현재 주기"]]) {
    runtime.pref("appLanguage", lang);
    await i18n.prepareLanguage(lang);
    assert.ok(quota.trayQuotaTooltip(usage(), detail()).includes(period), lang);
  }
});
