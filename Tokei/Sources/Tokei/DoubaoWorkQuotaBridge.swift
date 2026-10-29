import AppKit
import WebKit

/// The app owns this website session. No other application's credentials are accessed.
@MainActor
final class DoubaoWorkQuotaBridge: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    static let shared = DoubaoWorkQuotaBridge()
    static let changed = Notification.Name("TokeiDoubaoWorkQuotaChanged")
    static let defaultsKey = "doubaoWorkQuotaEnabled"
    private static let endpoint = URL(string:
        "https://www.doubao.com/member/quota-management?platform=desktop&is_work=1&is_setting_iframe=1&locale=zh")!
    private let nonce = UUID().uuidString
    private var enabled = false
    private var timer: Timer?
    private var timeout: DispatchWorkItem?
    private var webView: WKWebView?
    private var window: NSWindow?
    private var statusLabel: NSTextField?
    private var received = false
    private var snapshot: DoubaoWorkQuota?

    private var cacheURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".tokei/doubaowork_quota_cache.json")
    }

    func configure(enabled: Bool) {
        if enabled, self.enabled, timer != nil { return }
        self.enabled = enabled
        timer?.invalidate()
        timer = nil
        if !enabled {
            timeout?.cancel()
            webView?.stopLoading()
            window?.orderOut(nil)
            return
        }
        if snapshot == nil, let data = try? Data(contentsOf: cacheURL), data.count <= 65_536 {
            snapshot = try? JSONDecoder().decode(DoubaoWorkQuota.self, from: data)
        }
        let tick = Timer(timeInterval: 300, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.refresh() }
        }
        RunLoop.main.add(tick, forMode: .common)
        timer = tick
        refresh()
    }

    func connect() {
        UserDefaults.standard.set(true, forKey: Self.defaultsKey)
        guard SyncManager.setDoubaoWorkQuotaEnabled(true), makeWebView() else { return }
        if !enabled { configure(enabled: true) }
        if window == nil, let webView {
            let panel = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 780, height: 760),
                styleMask: [.titled, .closable, .miniaturizable, .resizable],
                backing: .buffered, defer: false)
            panel.title = L("连接豆包工作额度")
            panel.minSize = NSSize(width: 600, height: 560)
            panel.isReleasedWhenClosed = false
            let content = NSView()
            let note = NSTextField(wrappingLabelWithString: L("额度连接为试验功能，登录兼容性仍在验证。") + "\n" + L("请在豆包官网完成登录。登录状态在 Tokei 中保留，后续静默刷新；不会读取其他应用的登录凭据。"))
            note.font = .systemFont(ofSize: 12)
            note.textColor = .secondaryLabelColor
            let status = NSTextField(labelWithString: L("登录后点击“读取额度”"))
            status.font = .systemFont(ofSize: 11)
            status.textColor = .secondaryLabelColor
            statusLabel = status
            let button = NSButton(title: L("读取额度"), target: self, action: #selector(manualRefresh))
            let row = NSStackView(views: [status, button])
            row.orientation = .horizontal
            row.distribution = .fill
            let header = NSStackView(views: [note, row])
            header.orientation = .vertical
            header.alignment = .leading
            header.spacing = 8
            for view in [header, webView] {
                view.translatesAutoresizingMaskIntoConstraints = false
                content.addSubview(view)
            }
            NSLayoutConstraint.activate([
                header.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 16),
                header.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -16),
                header.topAnchor.constraint(equalTo: content.topAnchor, constant: 12),
                webView.topAnchor.constraint(equalTo: header.bottomAnchor, constant: 12),
                webView.leadingAnchor.constraint(equalTo: content.leadingAnchor),
                webView.trailingAnchor.constraint(equalTo: content.trailingAnchor),
                webView.bottomAnchor.constraint(equalTo: content.bottomAnchor),
            ])
            panel.contentView = content
            panel.center()
            window = panel
        }
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        if webView?.url == nil { loadQuotaPage() }
    }

    @objc private func manualRefresh() { loadQuotaPage() }

    private func refresh() {
        guard enabled, window?.isVisible != true, makeWebView() else { return }
        loadQuotaPage()
    }

    private func makeWebView() -> Bool {
        if webView != nil { return true }
        let bundled = Bundle.main.url(forResource: "doubaowork-quota", withExtension: "js")
        let development = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("doubaowork-quota.js")
        let url = bundled ?? (Bundle.main.bundleURL.pathExtension == "app" ? nil : development)
        guard let url, let script = try? String(contentsOf: url, encoding: .utf8) else {
            unavailable()
            return false
        }
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        configuration.userContentController.add(self, name: "tokeiDoubaoQuota")
        configuration.userContentController.addUserScript(WKUserScript(
            source: script.replacingOccurrences(of: "__TOKEI_DOUBAO_NONCE__", with: nonce),
            injectionTime: .atDocumentStart, forMainFrameOnly: true))
        let view = WKWebView(frame: NSRect(x: 0, y: 0, width: 780, height: 650),
            configuration: configuration)
        view.navigationDelegate = self
        webView = view
        return true
    }

    private func loadQuotaPage() {
        guard enabled, let webView else { return }
        timeout?.cancel()
        received = false
        statusLabel?.stringValue = L("正在读取官方额度…")
        webView.load(URLRequest(url: Self.endpoint, cachePolicy: .reloadIgnoringLocalCacheData,
                               timeoutInterval: 30))
        let work = DispatchWorkItem { [weak self] in
            MainActor.assumeIsolated {
                guard let self, self.enabled, !self.received else { return }
                self.unavailable()
            }
        }
        timeout = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 45, execute: work)
    }

    func userContentController(_ userContentController: WKUserContentController,
                               didReceive message: WKScriptMessage) {
        guard enabled, message.name == "tokeiDoubaoQuota", message.frameInfo.isMainFrame,
              message.frameInfo.securityOrigin.protocol == "https",
              ["www.doubao.com", "doubao.com"].contains(message.frameInfo.securityOrigin.host),
              let body = message.body as? [String: Any], body["nonce"] as? String == nonce,
              let value = body["snapshot"] as? [String: Any],
              let data = try? JSONSerialization.data(withJSONObject: value), data.count <= 65_536,
              var quota = try? JSONDecoder().decode(DoubaoWorkQuota.self, from: data),
              quota.status == "connected" else { return }
        quota.updated = Int(Date().timeIntervalSince1970)
        received = true
        timeout?.cancel()
        snapshot = quota
        save(quota)
        statusLabel?.stringValue = L("已连接，后续每 5 分钟静默刷新")
    }

    private func unavailable() {
        guard enabled else { return }
        timeout?.cancel()
        var value = snapshot ?? DoubaoWorkQuota(status: "unavailable")
        value.status = "unavailable"
        snapshot = value
        save(value)
        statusLabel?.stringValue = L("尚未读取到额度，请确认登录后点击“读取额度”")
    }

    private func save(_ quota: DoubaoWorkQuota) {
        guard let data = try? JSONEncoder().encode(quota) else { return }
        do {
            try FileManager.default.createDirectory(at: cacheURL.deletingLastPathComponent(),
                withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            try data.write(to: cacheURL, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: cacheURL.path)
            NotificationCenter.default.post(name: Self.changed, object: nil)
        } catch { /* A failed local write never opens a login or permission dialog. */ }
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!,
                 withError error: Error) {
        if (error as NSError).code != NSURLErrorCancelled { unavailable() }
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        let scheme = navigationAction.request.url?.scheme?.lowercased()
        decisionHandler(scheme == "https" || scheme == "about" ? .allow : .cancel)
    }
}
