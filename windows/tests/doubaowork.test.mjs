import assert from "node:assert/strict";
import { after, beforeEach, test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { testRuntime } from "./runtime.mjs";

const runtime = await testRuntime();
after(() => runtime.close());
beforeEach(() => runtime.clear());
const { doubaoWorkCard } = await runtime.load("src/cards/doubaowork.tsx");
const { CARDS } = await runtime.load("src/cards/registry.ts");
const activity = await runtime.load("src/lib/doubaowork.ts");
const share = await runtime.load("src/lib/share.tsx");
const { cardTokens } = await runtime.load("src/lib/cardOrder.ts");
const { prepareLanguage } = await runtime.load("src/lib/i18n.ts");
const ctx = (usage, range = "today") => ({ usage, range, rangeLabel: "今日", refreshing: false, pref: (_key, fallback) => fallback });
const sample = {
  doubaowork: { ranges: { today: { sessions: 0, session_ids: [] }, year: { sessions: 2 }, all: { sessions: 2 } }, source: "doubaowork-local-cache" },
};

test("registered activity card defaults on and settings/share use the same visibility key", () => {
  const spec = CARDS.find(card => card.id === "doubaowork");
  assert.equal(spec, doubaoWorkCard);
  assert.equal(spec.name, "Doubao Work");
  assert.equal(spec.visibleKey, "showDoubaoWork");
  assert.equal(spec.visibleDefault, true);
  assert.equal(share.currentShareVisibility().showDoubaoWork, true);
  runtime.pref("showDoubaoWork", false);
  assert.equal(share.currentShareVisibility().showDoubaoWork, false);
  assert.equal(share.shareToolLines(sample, "today", share.currentShareVisibility()).some(line => line.id === spec.id), false);
});

test("missing and malformed activity snapshots are harmless and do not create data", () => {
  for (const raw of [undefined, null, "malformed", {}, { ranges: null }, { ranges: { today: { sessions: "2" } } }, { ranges: { today: { sessions: -2 } } }]) {
    const usage = { doubaowork: raw };
    assert.equal(doubaoWorkCard.active(ctx(usage)), false);
    assert.equal(doubaoWorkCard.copyable(ctx(usage)), false);
    assert.equal(activity.doubaoWorkRange(raw, "today").sessions, 0);
    assert.equal(share.shareToolLines(usage, "today", {}).some(line => line.id === "doubaowork"), false);
  }
  assert.equal(activity.doubaoWorkRange({ ranges: { year: { sessions: 7 } } }, "all").sessions, 7);
  assert.equal(activity.doubaoWorkHasActivity({ source: "doubaowork-local-cache", updated: 100 }), false);
});

test("zero today stays zero while activity detection follows each displayed snapshot", () => {
  assert.equal(doubaoWorkCard.active(ctx(sample)), true);
  assert.equal(doubaoWorkCard.copyable(ctx(sample)), true);
  assert.equal(doubaoWorkCard.active(ctx({})), false);
  assert.equal(activity.doubaoWorkRange(sample.doubaowork, "today").sessions, 0);
  const html = renderToStaticMarkup(doubaoWorkCard.render(ctx(sample)));
  assert.doesNotMatch(html, /当前时段额度|7 天额度/);
  assert.match(html, /<button[^>]*>连接豆包账号查看额度<\/button>/);
  assert.match(html, /今日 新建会话/);
  assert.match(html, /仅统计已缓存的 Agent 会话，未提供 Token 用量/);
  assert.doesNotMatch(html, /账号额度来自豆包官网/);
  assert.doesNotMatch(html, /总量|成本|TTFT|tok\/s|调用|条消息/);
  const all = renderToStaticMarkup(doubaoWorkCard.render(ctx(sample, "all")));
  assert.match(all, />2<\/span>/);
  assert.match(all, /累计会话/);
  assert.equal(cardTokens("doubaowork", sample, "today"), 0);
  assert.equal(cardTokens("doubaowork", sample, "all"), 0);
});

test("activity without quota shares unknown quota and no invented token, cost, or call cells", () => {
  const line = share.shareToolLines(sample, "today", {}).find(line => line.id === "doubaowork");
  assert.ok(line);
  assert.equal(line.sessions, 0);
  assert.deepEqual(share.shareLineHeadline(line, "今日"), { value: "0", caption: "今日 新建会话" });
  assert.match(line.sourceCaption, /未提供 Token 用量/);
  for (const key of ["tokens", "cost", "cost_cny", "calls", "input", "output", "cacheRead", "cacheWrite", "reason", "hit"]) {
    assert.equal(line[key] == null, true, key);
  }
  assert.deepEqual(share.shareLineCells(line, [0.5, 0.5, 0.5]), []);
  const all = share.shareToolLines(sample, "all", {}).find(line => line.id === "doubaowork");
  assert.deepEqual(share.shareLineHeadline(all, "全部"), { value: "2", caption: "累计会话" });
  const totals = share.shareTotals([all]);
  assert.equal(totals.sessions, 2);
  assert.equal(totals.tokens, 0);
  assert.equal(totals.cost, 0);
  assert.equal(totals.calls, 0);
});

test("English activity card and share have translated metrics and limitations", async () => {
  runtime.pref("appLanguage", "en");
  await prepareLanguage("en");
  const html = renderToStaticMarkup(doubaoWorkCard.render(ctx(sample)));
  assert.match(html, /new conversations/);
  assert.match(html, /Token usage is not provided/);
  assert.doesNotMatch(html, /[一-鿿]/);
  const line = share.shareToolLines(sample, "all", {}).find(line => line.id === "doubaowork");
  assert.equal(line.activityLabel, "Total conversations");
});

const quotaSample = () => {
  const now = Date.now();
  return { doubaowork: { ...sample.doubaowork, quota: { version: 1, status: "connected", updated: Math.floor(now / 1000), windows: [
    { window_type: 1, used_percent: 0, start_time_ms: 0, end_time_ms: 0, less_than_one_percent: false },
    { window_type: 2, used_percent: 20, start_time_ms: now - 86400000, end_time_ms: now + 6 * 86400000, less_than_one_percent: false },
  ] } } };
};

test("real current-account quotas are the hero for every activity period", () => {
  const usage = quotaSample();
  for (const period of ["today", "yesterday", "week", "month", "year", "all"]) {
    const context = ctx(usage, period);
    const html = renderToStaticMarkup(doubaoWorkCard.render(context));
    assert.match(html, />100%<\/span>/);
    assert.match(html, />80%<\/span>/);
    assert.match(html, /当前时段额度 · 剩余额度/);
    assert.match(html, /7 天额度 · 剩余额度/);
    assert.match(html, /后重置/);
    assert.equal(doubaoWorkCard.active(context), true);
    assert.equal(cardTokens("doubaowork", usage, period), 0);
    const line = share.shareToolLines(usage, period, {}).find(line => line.id === "doubaowork");
    assert.deepEqual(share.shareLineHeadline(line, period), { value: "100%", caption: "当前时段额度 · 剩余额度" });
    assert.deepEqual(share.shareLineCells(line, [0.5, 0.5, 0.5]).map(cell => cell.value), ["80%"]);
    for (const key of ["tokens", "cost", "calls", "input", "output", "cacheRead", "cacheWrite", "reason"]) assert.equal(line[key] == null, true, key);
  }
});

test("quota alone activates the card and under-one-percent never becomes exact 100 percent left", () => {
  const usage = quotaSample();
  delete usage.doubaowork.ranges;
  usage.doubaowork.quota.windows[0].less_than_one_percent = true;
  assert.equal(doubaoWorkCard.active(ctx(usage)), true);
  const html = renderToStaticMarkup(doubaoWorkCard.render(ctx(usage)));
  assert.match(html, /已用 &lt;1%/);
  assert.doesNotMatch(html, /100%|新建会话|累计会话/);
  const line = share.shareToolLines(usage, "yesterday", {}).find(line => line.id === "doubaowork");
  assert.equal(share.shareLineHeadline(line, "昨日").value, "已用 <1%");
});

test("expired windows and snapshots older than 30 minutes display unknown pending refresh", () => {
  const usage = quotaSample();
  const q = usage.doubaowork.quota;
  const now = Date.now();
  q.windows[1].end_time_ms = now - 1;
  let rows = activity.doubaoWorkQuotaRows(usage.doubaowork, now);
  assert.equal(rows[0].value, "100%");
  assert.equal(rows[1].value, "—");
  assert.equal(rows[1].detail, null);
  assert.match(activity.doubaoWorkQuotaNotice(usage.doubaowork, now), /等待刷新/);
  q.updated = Math.floor(now / 1000) - 1801;
  rows = activity.doubaoWorkQuotaRows(usage.doubaowork, now);
  assert.deepEqual(rows.map(row => row.value), ["—", "—"]);
  q.updated = Math.floor(now / 1000) + 120;
  assert.deepEqual(activity.doubaoWorkQuotaRows(usage.doubaowork, now).map(row => row.value), ["—", "—"]);
});

test("missing, duplicate, unknown and malformed windows never fabricate zero usage", () => {
  const valid = quotaSample().doubaowork;
  for (const mutate of [
    q => { q.windows[1].window_type = 1; },
    q => { q.windows[0].window_type = 3; },
    q => { q.windows[0].used_percent = "0"; },
    q => { q.windows[0].used_percent = -1; },
    q => { q.windows[0].used_percent = 101; },
    q => { q.windows[0].end_time_ms = -1; },
    q => { q.windows[0].less_than_one_percent = "false"; },
    q => { q.windows = []; },
    q => { q.version = 2; },
  ]) {
    const stat = structuredClone(valid); mutate(stat.quota);
    assert.equal(activity.doubaoWorkQuota(stat), null);
    assert.deepEqual(activity.doubaoWorkQuotaRows(stat).map(row => row.value), ["—", "—"]);
  }
  const partial = structuredClone(valid);
  partial.quota.windows = [partial.quota.windows[1]];
  assert.deepEqual(activity.doubaoWorkQuotaRows(partial).map(row => row.value), ["—", "80%"]);
});

test("login-required and unavailable states do not invent zero percentages or tokens", () => {
  for (const status of ["login_required", "unavailable"]) {
    const usage = { doubaowork: { quota: { version: 1, updated: Math.floor(Date.now() / 1000), status, windows: [] } } };
    assert.equal(doubaoWorkCard.active(ctx(usage)), true);
    assert.equal(doubaoWorkCard.copyable(ctx(usage)), false);
    const html = renderToStaticMarkup(doubaoWorkCard.render(ctx(usage)));
    assert.doesNotMatch(html, /100%|80%|0%|0 Token|tok\/s/);
    assert.match(html, /连接豆包账号查看额度/);
    assert.match(activity.doubaoWorkQuotaNotice(usage.doubaowork), status === "login_required" ? /连接豆包账号查看额度/ : /尚未读取到额度/);
    assert.equal(share.shareToolLines(usage, "today", {}).some(line => line.id === "doubaowork"), false);
  }
});

test("failed refresh preserves valid last readings and marks them stale without changing their date", () => {
  for (const status of ["login_required", "unavailable"]) {
    const usage = quotaSample();
    const stamp = usage.doubaowork.quota.updated;
    usage.doubaowork.quota.status = status;
    assert.equal(activity.doubaoWorkQuota(usage.doubaowork).updated, stamp);
    const rows = activity.doubaoWorkQuotaRows(usage.doubaowork);
    assert.deepEqual(rows.map(row => row.value), ["100%", "80%"]);
    assert.equal(rows.every(row => row.stale), true);
    assert.match(activity.doubaoWorkQuotaNotice(usage.doubaowork), /上次读取的额度，等待刷新/);
    assert.match(renderToStaticMarkup(doubaoWorkCard.render(ctx(usage))), /等待刷新/);
  }
});

test("native setting is opt-in and a browser preview cannot fake a successful connection", async () => {
  const native = await runtime.load("src/lib/doubaoworkQuotaNative.ts");
  const config = await runtime.load("src/pages/settings/collectorConfig.ts");
  assert.equal(native.DOUBAO_QUOTA_PREF, "doubaoWorkQuotaEnabled");
  assert.equal(config.PRIVACY_CONFIG_KEYS.doubaoWorkQuotaEnabled, "doubaowork_quota_enabled");
  assert.deepEqual(await native.doubaoQuotaConnection(), { enabled: false, status: "unavailable" });
  await assert.rejects(native.connectDoubaoQuota(), /requires the Windows app/);
  await assert.rejects(native.refreshDoubaoQuota(), /requires the Windows app/);
  await assert.rejects(native.setDoubaoQuotaEnabled(true), /requires the Windows app/);
});
