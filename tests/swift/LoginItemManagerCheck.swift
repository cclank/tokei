import Foundation
import ServiceManagement

private enum TestFailure: Error {
    case assertion(String)
}

private final class FakeLoginItemService: LoginItemServicing {
    let diagnosticName = "fake"
    var status: SMAppService.Status
    var registerCount = 0
    var unregisterCount = 0

    init(status: SMAppService.Status) {
        self.status = status
    }

    func register() throws {
        registerCount += 1
        status = .enabled
    }

    func unregister() throws {
        unregisterCount += 1
        status = .notRegistered
    }
}

@main
struct LoginItemManagerCheck {
    @MainActor
    static func main() throws {
        // 断言的是中文输出，不能随跑测试那台机器的系统语言变化。
        L10n.forcedLanguage = .zh
        let suiteName = "com.tokei.tests.login-item.\(UUID().uuidString)"
        guard let defaults = UserDefaults(suiteName: suiteName) else {
            throw TestFailure.assertion("could not create isolated defaults")
        }
        defer { defaults.removePersistentDomain(forName: suiteName) }

        let service = FakeLoginItemService(status: .notRegistered)
        let manager = LoginItemManager(service: service, defaults: defaults)
        manager.setEnabled(true)
        try expect(service.registerCount == 1, "enable should register once")
        try expect(manager.enabled, "registered service should be enabled")
        try expect(defaults.bool(forKey: LoginItemManager.requestedDefaultsKey),
                   "enable intent should persist")

        manager.setEnabled(false)
        try expect(service.unregisterCount == 1, "disable should unregister once")
        try expect(!manager.enabled, "unregistered service should be disabled")
        try expect(!defaults.bool(forKey: LoginItemManager.requestedDefaultsKey),
                   "disable intent should persist")

        defaults.set(true, forKey: LoginItemManager.requestedDefaultsKey)
        let staleService = FakeLoginItemService(status: .notRegistered)
        let repaired = LoginItemManager(service: staleService, defaults: defaults)
        try expect(staleService.registerCount == 1,
                   "saved intent should repair a missing registration")
        try expect(repaired.enabled, "repaired registration should be enabled")

        let appURL = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("Tokei-\(UUID().uuidString).app")
        let plistURL = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("LaunchAgents-\(UUID().uuidString)/\(LaunchAgentLoginItemService.label).plist")
        try FileManager.default.createDirectory(at: appURL, withIntermediateDirectories: true)
        defer {
            try? FileManager.default.removeItem(at: appURL)
            try? FileManager.default.removeItem(at: plistURL.deletingLastPathComponent())
        }
        var loaded = false
        let launchAgent = LaunchAgentLoginItemService(
            applicationURL: appURL,
            plistURL: plistURL,
            commandRunner: { arguments in
                switch arguments.first {
                case "print": return (loaded ? 0 : 1, "")
                case "bootstrap": loaded = true; return (0, "")
                case "bootout": loaded = false; return (0, "")
                default: return (0, "")
                }
            }
        )
        try expect(launchAgent.status == .notRegistered, "missing plist should be unregistered")
        try launchAgent.register()
        try expect(launchAgent.status == .enabled, "loaded launch agent should be enabled")
        let plistData = try Data(contentsOf: plistURL)
        let plist = try PropertyListSerialization.propertyList(
            from: plistData, options: [], format: nil
        ) as? [String: Any]
        let arguments = plist?["ProgramArguments"] as? [String]
        try expect(arguments == ["/usr/bin/open", appURL.path],
                   "launch agent should open the exact app path")
        try launchAgent.unregister()
        try expect(!FileManager.default.fileExists(atPath: plistURL.path),
                   "unregister should remove the plist")

        print("login item manager checks passed")
    }

    private static func expect(_ condition: @autoclosure () -> Bool,
                               _ message: String) throws {
        if !condition() {
            throw TestFailure.assertion(message)
        }
    }
}
