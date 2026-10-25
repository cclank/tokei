import assert from "node:assert/strict";
import { after, beforeEach, test } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { testRuntime } from "./runtime.mjs";

const runtime = await testRuntime();
after(() => runtime.close());
beforeEach(() => runtime.clear());
const detail = await runtime.load("src/pages/quotaHistory/detail.ts");
const { CycleSection } = await runtime.load("src/pages/quotaHistory/CycleSection.tsx");
const { CARDS } = await runtime.load("src/cards/registry.ts");
const i18n = await runtime.load("src/lib/i18n.ts");
const now = Math.floor(Date.now() / 1000);
const cycle = (overrides = {}) => ({
  tool: "grok", window: "month", start: now - 86400, end: now + 86400,
  used_pct: 25, tokens: 123456, cost: 12.5,
  devices: { synthetic: 123456 }, approx: true, current: true, ...overrides,
});
const payload = (cycles = [cycle()]) => ({ daily: [], cycles, devices: ["synthetic"], missing: [], now });
const decode = (cycles) => detail.decodeQuotaDetail(JSON.stringify(payload(cycles)));
const section = (cycles) => renderToStaticMarkup(createElement(CycleSection, { detail: { payload: decode(cycles), refreshing: false } }));

test("quota decoding preserves monthly windows and optional costs from old caches", () => {
  assert.equal(decode([cycle()]).cycles[0].window, "month");
  assert.equal(decode([cycle()]).cycles[0].cost, 12.5);
  const legacy = cycle();
  delete legacy.window;
  delete legacy.cost;
  assert.ok(decode([legacy]));
  assert.doesNotMatch(section([legacy]), /Grok 月额度|\$12\.50/);
});

test("monthly cycles use monthly labels and never show the short-week warning", () => {
  const html = section([cycle(), cycle({ start: now - 5 * 86400, end: now - 2 * 86400, current: false })]);
  assert.match(html, /Grok 月额度/);
  assert.match(html, /一个额度周期用了多少/);
  assert.match(html, /\$12\.50/);
  assert.doesNotMatch(html, /Grok 周额度|不足 7 天/);
  assert.match(section([cycle({ window: "week" }), cycle({ window: "week", start: now - 5 * 86400, end: now - 2 * 86400, current: false })]), /不足 7 天/);
});

test("only the live matching cycle contributes spend, with the same 120-second tolerance as macOS", () => {
  assert.equal(typeof detail.currentCycle, "function");
  const p = payload();
  for (const drift of [-120, -60, 0, 60, 120]) assert.equal(detail.currentCycle(p, "grok", now + 86400 + drift, now)?.cost, 12.5);
  for (const drift of [-121, 121]) assert.equal(detail.currentCycle(p, "grok", now + 86400 + drift, now), null);
  assert.equal(detail.currentCycle(p, "codex", now + 86400, now), null);
  assert.equal(detail.currentCycle(p, "grok", null, now), null);
  assert.equal(detail.currentCycle(payload([cycle({ end: now })]), "grok", now + 60, now), null);
  assert.equal(detail.currentCycle(payload([cycle({ start: now + 1 })]), "grok", now + 86400, now), null);
});

test("all three cards display cycle spend once and suppress missing, expired or mismatched costs", () => {
  for (const tool of ["claude", "codex", "grok"]) {
    const usage = {
      claude: { ranges: {}, q7: 25, q7_reset: now + 86400 },
      codex: { ranges: {}, pw: 25, rw: now + 86400 },
      grok: { ranges: {}, pct: 25, reset: now + 86400, window: "month", products: [] },
    };
    const ctx = { usage, range: "today", rangeLabel: "今日", refreshing: false, pref: (_key, fallback) => fallback,
      quotaDetail: payload([cycle({ tool })]) };
    const card = CARDS.find(item => item.id === tool);
    const render = () => renderToStaticMarkup(card.render(ctx));
    assert.equal((render().match(/本周期已花/g) ?? []).length, 1, tool);
    assert.match(render(), /\$12\.50/);
    for (const invalid of [undefined, null, -1, NaN, Infinity]) {
      ctx.quotaDetail = payload([cycle({ tool, cost: invalid })]);
      assert.doesNotMatch(render(), /本周期已花/, `${tool}: invalid cost ${invalid}`);
    }
    ctx.quotaDetail = payload([cycle({ tool, cost: 0 })]);
    assert.match(render(), /\$0\.00/);
    for (const overrides of [{ end: now - 1 }, { end: now + 86400 + 121 }, { current: false }]) {
      ctx.quotaDetail = payload([cycle({ tool, ...overrides })]);
      assert.doesNotMatch(render(), /本周期已花/, `${tool}: inactive cycle`);
    }
  }
});

test("cycle labels and spend follow the shared five-language dictionaries", async () => {
  for (const [lang, title] of [["zh", "Grok 月额度"], ["en", "Grok monthly quota"], ["fr", "Quota mensuel Grok"], ["ja", "Grok の月次利用枠"], ["ko", "Grok 월간 한도"]]) {
    runtime.pref("appLanguage", lang);
    await i18n.prepareLanguage(lang);
    assert.ok(section([cycle()]).includes(title), lang);
  }
});

test("quick panels refresh the shared cycle cache without launching a second collector", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async input => {
    calls.push(String(input));
    assert.ok(String(input).startsWith("/__tokei/file?"), "only the main window may collect cycles");
    return Response.json(payload());
  };
  try {
    detail.loadQuotaDetail(false, true);
    detail.loadQuotaDetail(false, true);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(calls.length, 1, "deduplicate concurrent cache reads");
    detail.loadQuotaDetail(false, true);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(calls.length, 2, "refresh the cache on a later usage snapshot");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
