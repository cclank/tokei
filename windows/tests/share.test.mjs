import assert from "node:assert/strict";
import { after, beforeEach, test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { testRuntime } from "./runtime.mjs";

const runtime = await testRuntime();
after(() => runtime.close());
beforeEach(() => runtime.clear());
const share = await runtime.load("src/lib/share.tsx");
const { cursorCard, zaiCard, zedCard, sub2apiCard } = await runtime.load("src/cards/providerQuota.tsx");
const { grokBotDisplay, grokBotCard } = await runtime.load("src/cards/grok.tsx");
const ctx = usage => ({ usage, range: "today", rangeLabel: "今日", refreshing: false, pref: (_key, fallback) => fallback });
const r = { in: 100, out: 20, sessions: 1, requests: 3, cost: 1, cost_cny: 2 };
const usage = {
  claude: { ranges: { today: { in: 100, out: 20, sessions: 1, cost: 1 } } },
  cursor: { usage: { ranges: { today: r } } },
  zai: { usage: { ranges: { today: r } } },
};

test("share defaults match the default-off provider cards and explicit preferences", () => {
  for (const card of [cursorCard, zaiCard]) {
    assert.equal(card.visibleDefault, false);
    assert.equal(share.currentShareVisibility()[card.visibleKey], false);
  }
  runtime.pref("showCursor", true);
  runtime.pref("showZai", false);
  const lines = share.shareToolLines(usage, "today", share.currentShareVisibility());
  assert.ok(lines.some(line => line.id === "cursor"));
  assert.equal(lines.some(line => line.id === "zai"), false);
  runtime.pref("showCursor", false);
  assert.equal(share.shareToolLines(usage, "today", share.currentShareVisibility())
    .some(line => line.id === "cursor"), false);
});

test("provider account lines stay shareable without inflating local overview totals", () => {
  const lines = share.shareToolLines(usage, "today", { showCursor: true, showZai: true });
  assert.ok(lines.some(line => line.id === "cursor"));
  assert.ok(lines.some(line => line.id === "zai"));
  const base = share.shareTotals(share.shareToolLines({ claude: usage.claude }, "today", {}));
  assert.deepEqual(share.shareTotals(lines), base);
  assert.equal(base.tokens, 120);
  assert.equal(base.cost, 1);
  assert.equal(base.tools, 1);
  assert.equal(base.cost_cny, 0);
  assert.equal(share.shareTotals(lines.filter(line => line.id !== "claude")).tokens, 0);
});

test("fallback response/message share uses the displayed period and actual drawing inputs", () => {
  const sample = { grok_bot: { ranges: { last_week: { sessions: 5, calls: 64, turns: 38 } } } };
  const display = grokBotDisplay(sample, "today");
  assert.equal(display.key, "last_week");
  assert.equal(grokBotCard.copyable(ctx(sample)), true);
  const line = share.shareToolLines(sample, display.key, {}).find(item => item.id === "grok-bot");
  assert.equal(line.calls, 64);
  assert.match(line.extra, /38/);
  const headline = share.shareLineHeadline(line, "上周");
  assert.equal(headline.value, "64");
  assert.equal(headline.caption, "上周 响应");
  const cells = share.shareLineCells(line, [0.5, 0.5, 0.5]);
  assert.ok(cells.some(cell => cell.label === "调用" && cell.value === "64"));
  assert.ok(cells.some(cell => String(cell.value).includes("38")));
  assert.equal(share.shareLineHeadline({ ...line, tokens: 200 }, "上周").caption, "上周 总量");
  assert.equal(share.shareLineHeadline({ id: "empty", name: "Empty" }, "今日"), null);
});

test("Grok Bot shows missing usage separately from authorization and quota", () => {
  const activity = { today: { sessions: 1, calls: 2, turns: 2 } };
  const render = (quota, ranges = activity) => renderToStaticMarkup(grokBotCard.render(ctx({ grok_bot: { ranges, quota } })));
  const quota = { available: true, source: "grok-bot-api", windows: [{ title: "本周期额度", used_pct: 10 }] };
  const partial = render({ ...quota, usage_fetch: { status: "partial", reported_events: 287, received_events: 226 } });
  assert.match(partial, /额度已更新 · 该时段用量明细暂不可用/);
  assert.match(partial, /90%/);
  assert.doesNotMatch(partial, /授权后显示/);
  assert.match(render({ ...quota, usage_fetch: { status: "complete" } }), /该时段暂无官方用量记录/);
  assert.match(render(quota, {}), /额度已更新 · 该时段用量明细暂不可用/);
  assert.match(render({ ...quota, stale: true }), /本地活动 · 该时段用量明细暂不可用/);
  assert.match(render({ ...quota, usage_fetch: { status: "partial" }, usage: { ranges: { today: r } } }),
    /本次官方用量明细可能不全/);
  assert.match(render({ ...quota, usage_fetch: { status: "unavailable" }, usage: { ranges: { today: r } } }),
    /官方用量暂未更新 · 显示已保存的记录/);
  assert.match(render({}), /授权后显示官方 Token/);
});

test("quota-only providers stay compact; token or request usage stays standard/copyable", () => {
  assert.equal(cursorCard.presentation(ctx({ cursor: { available: true } })), "compact");
  assert.equal(cursorCard.copyable(ctx({ cursor: { available: true } })), false);
  assert.equal(cursorCard.presentation(ctx({ cursor: usage.cursor })), "standard");
  assert.equal(cursorCard.copyable(ctx({ cursor: usage.cursor })), true);
  const requestsOnly = ctx({ cursor: { usage: { ranges: { today: { requests: 2 } } } } });
  assert.equal(cursorCard.presentation(requestsOnly), "standard");
  assert.equal(cursorCard.copyable(requestsOnly), true);
  for (const card of [zedCard, sub2apiCard]) {
    assert.equal(card.presentation(ctx({})), "compact");
    assert.equal(card.copyable(ctx({})), false);
  }
});
