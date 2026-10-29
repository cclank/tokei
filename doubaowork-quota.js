/* Observe only official quota responses. Credentials and raw responses stay in the webview. */
(function (root) {
  "use strict";
  const hosts = new Set(["www.doubao.com", "doubao.com"]);
  const endpoint = "/alice/commerce/sale/subscription/overview/";
  const nonce = "__TOKEI_DOUBAO_NONCE__";

  function project(body) {
    if (!body || body.code !== 0) return null;
    const groups = body.data?.window_limit_section?.window_limit_groups;
    if (!Array.isArray(groups)) return null;
    const general = groups.filter(g => g?.feature_group === "general");
    if (general.length !== 1 || !Array.isArray(general[0].window_limits)) return null;
    const windows = [];
    for (const value of general[0].window_limits) {
      if (!value || ![1, 2].includes(value.window_type)) continue;
      const p = value.used_percent;
      const start = value.start_time, end = value.end_time;
      if (typeof p !== "number" || !Number.isFinite(p) || p < 0 || p > 100 ||
          !Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 0 || end < 0 ||
          (end > 0 && (end < start || end > 32503680000000)) ||
          typeof value.less_than_one_percent !== "boolean" ||
          windows.some(w => w.window_type === value.window_type)) return null;
      windows.push({window_type: value.window_type, used_percent: p,
        start_time_ms: start, end_time_ms: end,
        less_than_one_percent: value.less_than_one_percent});
    }
    if (!windows.length) return null;
    return {version: 1, status: "connected", updated: Math.floor(Date.now() / 1000), windows};
  }

  if (typeof document === "undefined" && typeof module === "object" && module.exports) {
    module.exports = {project};
    return;
  }
  if (root.location?.protocol !== "https:" || !hosts.has(root.location.hostname) ||
      root !== root.top) return;

  function matches(url) {
    try {
      const parsed = new URL(String(url), root.location.href);
      return parsed.origin === root.location.origin && parsed.pathname === endpoint;
    } catch (_) { return false; }
  }
  let last = "";
  function publish(body) {
    const snapshot = project(body);
    if (!snapshot) return;
    const signature = JSON.stringify(snapshot.windows);
    if (signature === last) return;
    last = signature;
    const message = {nonce, snapshot};
    if (root.webkit?.messageHandlers?.tokeiDoubaoQuota) {
      root.webkit.messageHandlers.tokeiDoubaoQuota.postMessage(message);
    } else {
      // The native navigation callback cancels this URL before any network request.
      root.location.href = "https://tokei.invalid/doubaowork-quota#" +
        encodeURIComponent(JSON.stringify(message));
    }
  }
  const originalFetch = root.fetch;
  if (typeof originalFetch === "function") {
    root.fetch = function () {
      const promise = originalFetch.apply(this, arguments);
      const input = arguments[0];
      if (matches(typeof input === "string" || input instanceof URL ? input : input?.url)) {
        promise.then(response => {
          if (!response.ok) return;
          return response.clone().text().then(text => {
            if (text.length <= 131072) publish(JSON.parse(text));
          });
        }).catch(() => {});
      }
      return promise;
    };
  }
  const XHR = root.XMLHttpRequest;
  if (XHR?.prototype) {
    const targets = new WeakSet();
    const open = XHR.prototype.open, send = XHR.prototype.send;
    XHR.prototype.open = function (method, url) {
      targets.delete(this);
      if (matches(url)) targets.add(this);
      return open.apply(this, arguments);
    };
    XHR.prototype.send = function () {
      if (targets.has(this)) this.addEventListener("load", function () {
        try {
          if (this.status < 200 || this.status >= 300) return;
          if (this.responseType === "json") publish(this.response);
          else if ((!this.responseType || this.responseType === "text") &&
                   this.responseText.length <= 131072) publish(JSON.parse(this.responseText));
        } catch (_) {}
      }, {once: true});
      return send.apply(this, arguments);
    };
  }
})(globalThis);
