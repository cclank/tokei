import Combine
import Darwin
import Foundation
import ServiceManagement

protocol LoginItemServicing: AnyObject {
    var status: SMAppService.Status { get }
    var diagnosticName: String { get }
    func register() throws
    func unregister() throws
}

extension SMAppService: LoginItemServicing {
    var diagnosticName: String { "serviceManagement" }
}

private enum LaunchAgentLoginItemError: LocalizedError {
    case invalidApplication
    case commandFailed(String)

    var errorDescription: String? {
        switch self {
        case .invalidApplication:
            return L10n.t("s268")
        case .commandFailed(let message):
            return message.isEmpty ? L10n.t("s457") : L10n.f("s458", message)
        }
    }
}

final class LaunchAgentLoginItemService: LoginItemServicing {
    typealias CommandResult = (status: Int32, output: String)
    typealias CommandRunner = ([String]) -> CommandResult

    static let label = "com.tokei.app.login"

    let diagnosticName = "launchAgent"
    let applicationURL: URL
    let plistURL: URL

    private let commandRunner: CommandRunner
    private let fileManager: FileManager
    private var domain: String { "gui/\(getuid())" }
    private var serviceTarget: String { "\(domain)/\(Self.label)" }

    init(applicationURL: URL = Bundle.main.bundleURL,
         plistURL: URL? = nil,
         fileManager: FileManager = .default,
         commandRunner: @escaping CommandRunner = LaunchAgentLoginItemService.runLaunchctl) {
        self.applicationURL = applicationURL.standardizedFileURL
        self.fileManager = fileManager
        self.plistURL = plistURL ?? fileManager.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/LaunchAgents/\(Self.label).plist")
        self.commandRunner = commandRunner
    }

    var hasConfiguration: Bool {
        fileManager.fileExists(atPath: plistURL.path)
    }

    var status: SMAppService.Status {
        guard configurationMatchesCurrentApplication() else { return .notRegistered }
        return commandRunner(["print", serviceTarget]).status == 0 ? .enabled : .requiresApproval
    }

    func register() throws {
        guard applicationURL.pathExtension == "app",
              fileManager.fileExists(atPath: applicationURL.path) else {
            throw LaunchAgentLoginItemError.invalidApplication
        }

        let data = try PropertyListSerialization.data(
            fromPropertyList: configuration(),
            format: .xml,
            options: 0
        )
        try fileManager.createDirectory(
            at: plistURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try data.write(to: plistURL, options: .atomic)
        try fileManager.setAttributes([.posixPermissions: 0o644], ofItemAtPath: plistURL.path)

        _ = commandRunner(["bootout", serviceTarget])
        _ = commandRunner(["enable", serviceTarget])
        let result = commandRunner(["bootstrap", domain, plistURL.path])
        guard result.status == 0 else {
            throw LaunchAgentLoginItemError.commandFailed(result.output)
        }
    }

    func unregister() throws {
        _ = commandRunner(["bootout", serviceTarget])
        if fileManager.fileExists(atPath: plistURL.path) {
            try fileManager.removeItem(at: plistURL)
        }
    }

    private func configuration() -> [String: Any] {
        [
            "Label": Self.label,
            "ProgramArguments": ["/usr/bin/open", applicationURL.path],
            "RunAtLoad": true,
            "ProcessType": "Interactive",
            "LimitLoadToSessionType": "Aqua",
        ]
    }

    private func configurationMatchesCurrentApplication() -> Bool {
        guard let data = try? Data(contentsOf: plistURL),
              let plist = try? PropertyListSerialization.propertyList(
                from: data, options: [], format: nil
              ) as? [String: Any],
              plist["Label"] as? String == Self.label,
              let arguments = plist["ProgramArguments"] as? [String] else {
            return false
        }
        return arguments == ["/usr/bin/open", applicationURL.path]
    }

    private static func runLaunchctl(arguments: [String]) -> CommandResult {
        let process = Process()
        let pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        process.arguments = arguments
        process.standardOutput = pipe
        process.standardError = pipe
        do {
            try process.run()
            process.waitUntilExit()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            let output = String(data: data, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            return (process.terminationStatus, output)
        } catch {
            return (-1, error.localizedDescription)
        }
    }
}

enum LoginItemServiceFactory {
    static func make() -> LoginItemServicing {
        let fallback = LaunchAgentLoginItemService()
        if fallback.hasConfiguration {
            return fallback
        }
        let service = SMAppService.mainApp
        return service.status == .notFound ? fallback : service
    }
}

private enum LoginItemManagerError: LocalizedError {
    case applicationNotFound

    var errorDescription: String? {
        switch self {
        case .applicationNotFound:
            return L10n.t("s269")
        }
    }
}

@MainActor
final class LoginItemManager: ObservableObject {
    static let shared = LoginItemManager()
    nonisolated static let requestedDefaultsKey = "launchAtLoginRequested"

    @Published private(set) var enabled = false
    @Published private(set) var requiresApproval = false
    @Published private(set) var errorMessage: String?

    private let service: LoginItemServicing
    private let defaults: UserDefaults

    private init() {
        service = LoginItemServiceFactory.make()
        defaults = .standard
        refresh()
        repairRegistrationIfNeeded()
    }

    init(service: LoginItemServicing, defaults: UserDefaults) {
        self.service = service
        self.defaults = defaults
        refresh()
        repairRegistrationIfNeeded()
    }

    func refresh() {
        let status = service.status
        enabled = status == .enabled || status == .requiresApproval
        requiresApproval = status == .requiresApproval
        if enabled {
            defaults.set(true, forKey: Self.requestedDefaultsKey)
            if status == .enabled {
                errorMessage = nil
            }
        } else if status == .notFound,
                  defaults.bool(forKey: Self.requestedDefaultsKey) {
            errorMessage = LoginItemManagerError.applicationNotFound.localizedDescription
        }
    }

    func setEnabled(_ shouldEnable: Bool) {
        errorMessage = nil
        defaults.set(shouldEnable, forKey: Self.requestedDefaultsKey)
        do {
            switch (shouldEnable, service.status) {
            case (true, .notRegistered):
                try service.register()
            case (true, .notFound):
                throw LoginItemManagerError.applicationNotFound
            case (false, .enabled), (false, .requiresApproval):
                try service.unregister()
            default:
                break
            }
        } catch {
            errorMessage = error.localizedDescription
        }
        refresh()
        scheduleRefresh()
    }

    @discardableResult
    func repairRegistrationIfNeeded() -> Bool {
        guard defaults.bool(forKey: Self.requestedDefaultsKey),
              service.status == .notRegistered else {
            refresh()
            return false
        }
        do {
            try service.register()
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
        refresh()
        scheduleRefresh()
        return enabled
    }

    func openSystemSettings() {
        SMAppService.openSystemSettingsLoginItems()
    }

    private func scheduleRefresh() {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
            self?.refresh()
        }
    }
}

enum LoginItemCommandLine {
    private static let commands = [
        "--login-item-status",
        "--login-item-register",
        "--login-item-unregister",
    ]

    static func runIfRequested(arguments: [String] = CommandLine.arguments) -> Bool {
        guard let command = commands.first(where: arguments.contains) else { return false }
        let service = LoginItemServiceFactory.make()
        let defaults = UserDefaults.standard
        let outputPath = argumentValue(after: "--login-item-output", in: arguments)

        do {
            switch command {
            case "--login-item-register":
                defaults.set(true, forKey: LoginItemManager.requestedDefaultsKey)
                if service.status != .enabled && service.status != .requiresApproval {
                    try service.register()
                }
            case "--login-item-unregister":
                defaults.set(false, forKey: LoginItemManager.requestedDefaultsKey)
                if service.status == .enabled || service.status == .requiresApproval {
                    try service.unregister()
                }
            default:
                break
            }
            emit(service: service, error: nil, outputPath: outputPath)
        } catch {
            emit(service: service, error: error.localizedDescription, outputPath: outputPath)
        }
        return true
    }

    private static func argumentValue(after name: String, in arguments: [String]) -> String? {
        guard let index = arguments.firstIndex(of: name), index + 1 < arguments.count else {
            return nil
        }
        return arguments[index + 1]
    }

    private static func emit(service: LoginItemServicing, error: String?, outputPath: String?) {
        let status = "\(service.diagnosticName):\(statusName(service.status))"
        let value = error.map { "\(status)\nerror=\($0)" } ?? status
        print(value)
        if let outputPath {
            try? value.write(toFile: outputPath, atomically: true, encoding: .utf8)
        }
    }

    private static func statusName(_ status: SMAppService.Status) -> String {
        switch status {
        case .notRegistered: return "notRegistered"
        case .enabled: return "enabled"
        case .requiresApproval: return "requiresApproval"
        case .notFound: return "notFound"
        @unknown default: return "unknown(\(status.rawValue))"
        }
    }
}
