const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const script = fs.readFileSync(require('node:path').join(__dirname, '..', 'doubaowork-quota.js'), 'utf8');
const mod = {exports: {}};
vm.runInNewContext(script, {module: mod, globalThis: {}, Date, URL, Set, Number, WeakSet});
const {project} = mod.exports;
function fixture() {
  return {code: 0, data: {window_limit_section: {window_limit_groups: [{feature_group: 'general', window_limits: [
    {window_type: 1, used_percent: 0, start_time: 0, end_time: 0, less_than_one_percent: false},
    {window_type: 2, used_percent: 20, start_time: 1800000000000, end_time: 1800604800000,
      less_than_one_percent: false}]}]}}};
}
test('official response projects exact percentages and never identity or raw payload', () => {
  const raw = fixture();
  raw.data.token = 'synthetic-token';
  raw.data.window_limit_section.window_limit_groups[0].window_limits[0].user_id = 'synthetic-id';
  const value = project(raw);
  assert.equal(value.windows[0].used_percent, 0);
  assert.equal(value.windows[1].used_percent, 20);
  assert.equal(value.windows[1].end_time_ms - value.windows[1].start_time_ms, 604800000);
  assert.equal(JSON.stringify(value).includes('synthetic'), false);
  assert.equal(Object.hasOwn(value, 'tokens'), false);
});
test('missing counters and ambiguous quota pools never become zero', () => {
  assert.equal(project({code: 0, data: {}}), null);
  const raw = fixture();
  raw.data.window_limit_section.window_limit_groups.push(raw.data.window_limit_section.window_limit_groups[0]);
  assert.equal(project(raw), null);
  raw.data.window_limit_section.window_limit_groups = [{feature_group: 'enterprise', window_limits: []}];
  assert.equal(project(raw), null);
});
test('reject malformed percentages and preserve less-than-one semantics', () => {
  for (const value of [null, '20', true, -1, 101, NaN, Infinity]) {
    const raw = fixture();
    raw.data.window_limit_section.window_limit_groups[0].window_limits[0].used_percent = value;
    assert.equal(project(raw), null);
  }
  const raw = fixture();
  raw.data.window_limit_section.window_limit_groups[0].window_limits[0].less_than_one_percent = true;
  assert.equal(project(raw).windows[0].less_than_one_percent, true);
});
test('observer ignores other origins and only forwards a minimal successful overview response', async () => {
  const posts = [], calls = [];
  const response = {ok: true, clone: () => ({text: async () => JSON.stringify(fixture())})};
  const originalFetch = function (...args) {calls.push(args); return Promise.resolve(response);};
  const browser = {location: {protocol: 'https:', hostname: 'www.doubao.com', origin: 'https://www.doubao.com',
    href: 'https://www.doubao.com/member/quota-management'}, fetch: originalFetch,
    webkit: {messageHandlers: {tokeiDoubaoQuota: {postMessage: v => posts.push(v)}}}};
  browser.top = browser;
  vm.runInNewContext(script, {globalThis: browser, Date, URL, Set, Number, WeakSet});
  const options = {method: 'POST', body: '{}'};
  const returned = await browser.fetch('/alice/commerce/sale/subscription/overview/', options);
  await new Promise(r => setImmediate(r));
  assert.equal(returned, response);
  assert.equal(calls[0][1], options);
  assert.equal(posts.length, 1);
  assert.equal(posts[0].snapshot.windows[1].used_percent, 20);
  await browser.fetch('https://unrelated.example/alice/commerce/sale/subscription/overview/', options);
  await new Promise(r => setImmediate(r));
  assert.equal(posts.length, 1);
});
test('observer never runs on unrelated pages or embedded frames', () => {
  for (const location of [
    {protocol: 'http:', hostname: 'www.doubao.com'},
    {protocol: 'https:', hostname: 'www.doubao.com.unrelated.example'},
  ]) {
    const original = () => {};
    const browser = {location, fetch: original};
    browser.top = browser;
    vm.runInNewContext(script, {globalThis: browser, Date, URL, Set, Number, WeakSet});
    assert.equal(browser.fetch, original);
  }
  const original = () => {};
  const frame = {location: {protocol: 'https:', hostname: 'www.doubao.com'}, fetch: original, top: {}};
  vm.runInNewContext(script, {globalThis: frame, Date, URL, Set, Number, WeakSet});
  assert.equal(frame.fetch, original);
});
test('XHR observation forwards only valid quota data without changing request or body', () => {
  const posts = [];
  class XHR {
    open(...args) {this.opened = args;}
    addEventListener(event, callback) {this.listener = callback;}
    send(body) {this.sent = body;}
    complete() {this.status = 200; this.responseType = 'json'; this.response = fixture(); this.listener?.call(this);}
  }
  const browser = {location: {protocol: 'https:', hostname: 'www.doubao.com', origin: 'https://www.doubao.com',
    href: 'https://www.doubao.com/member/quota-management'}, XMLHttpRequest: XHR,
    webkit: {messageHandlers: {tokeiDoubaoQuota: {postMessage: value => posts.push(value)}}}};
  browser.top = browser;
  vm.runInNewContext(script, {globalThis: browser, Date, URL, Set, Number, WeakSet});
  const xhr = new XHR();
  xhr.open('POST', '/alice/commerce/sale/subscription/overview/', true);
  xhr.send('{}');
  xhr.complete();
  assert.equal(xhr.opened[0], 'POST');
  assert.equal(xhr.sent, '{}');
  assert.equal(posts.length, 1);
  assert.equal(posts[0].snapshot.windows[1].used_percent, 20);
});
