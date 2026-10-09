import Darwin
import Foundation

enum GrokBotHelperManager {
    /// 安装包里辅助程序的协议版本。2：--grok-bot-data-json 支持 --since 增量拉取。
    static let requiredProtocolVersion = 2
    /// 已安装的辅助程序不低于这个版本就照常用来采集。换新版会让钥匙串重新弹授权框，
    /// 不能因为 App 升级就把用户授权过的旧版停掉——只在用户主动（重新）授权时换。
    static let minimumProtocolVersion = 1
    private static let helperName = "TokeiGrokBotHelper"
    /// 解析时顺手记下已安装辅助程序的版本，界面据此提示重新授权，不在主线程起进程。
    private static var installedVersion: Int?
    private static let resolutionLock = NSLock()
    private static var cachedHelperURL: URL?
    private static var resolvedOnce = false
    private static var lastAuthorizationRepairAttempt = Date.distantPast
    private static let authorizationRepairInterval: TimeInterval = 5 * 60

    static func resolvedHelperURL() -> URL? {
        resolutionLock.lock()
        let resolved: URL?
        if resolvedOnce {
            resolved = cachedHelperURL
        } else {
            resolvedOnce = true
            let installed = installedHelperURL
            installedVersion = usableVersion(installed, requireCurrentUserOwner: true)
            if (installedVersion ?? 0) >= minimumProtocolVersion {
                cachedHelperURL = installed
            } else {
                cachedHelperURL = bundledHelperURLs.first {
                    isUsableHelper($0, requireCurrentUserOwner: false)
                }
            }
            resolved = cachedHelperURL
        }
        resolutionLock.unlock()
        if let resolved {
            repairAuthorizationMarkerIfNeeded(using: resolved)
        }
        return resolved
    }

    /// 已安装的是能用、但不是最新的辅助程序：提示用户重新授权一次换上新版。
    static var needsReauthorization: Bool {
        resolutionLock.lock()
        defer { resolutionLock.unlock() }
        return installedVersion.map { $0 < requiredProtocolVersion } ?? false
    }

    static func installIfNeeded() -> URL? {
        let destination = installedHelperURL
        if isUsableHelper(destination, requireCurrentUserOwner: true) {
            cache(destination)
            repairAuthorizationMarkerIfNeeded(using: destination)
            return destination
        }
        guard let source = bundledHelperURLs.first(where: {
            isUsableHelper($0, requireCurrentUserOwner: false)
        }) else { return nil }

        let directory = destination.deletingLastPathComponent()
        let temporary = directory.appendingPathComponent(
            ".\(helperName).\(UUID().uuidString)"
        )
        do {
            try FileManager.default.createDirectory(
                at: directory,
                withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700]
            )
            try FileManager.default.setAttributes(
                [.posixPermissions: 0o700],
                ofItemAtPath: directory.path
            )
            try FileManager.default.copyItem(at: source, to: temporary)
            try FileManager.default.setAttributes(
                [.posixPermissions: 0o700],
                ofItemAtPath: temporary.path
            )
            guard atomicReplace(temporary, destination) else {
                try? FileManager.default.removeItem(at: temporary)
                return nil
            }
        } catch {
            try? FileManager.default.removeItem(at: temporary)
            return nil
        }
        guard isUsableHelper(destination, requireCurrentUserOwner: true) else { return nil }
        cache(destination)
        resolutionLock.lock()
        installedVersion = requiredProtocolVersion
        resolutionLock.unlock()
        repairAuthorizationMarkerIfNeeded(using: destination)
        return destination
    }

    private static var installedHelperURL: URL {
        if let configured = ProcessInfo.processInfo.environment[
            "TOKEI_GROK_BOT_PERSISTENT_HELPER"
        ], !configured.isEmpty {
            return URL(fileURLWithPath: NSString(string: configured).expandingTildeInPath)
        }
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Tokei/Helpers")
            .appendingPathComponent(helperName)
    }

    private static var authorizationMarkerURL: URL {
        if let configured = ProcessInfo.processInfo.environment[
            "TOKEI_GROK_BOT_AUTH_MARKER"
        ], !configured.isEmpty {
            return URL(fileURLWithPath: NSString(string: configured).expandingTildeInPath)
        }
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".tokei/grok_bot_keychain_authorized")
    }

    private static func repairAuthorizationMarkerIfNeeded(using helper: URL) {
        guard !FileManager.default.fileExists(atPath: authorizationMarkerURL.path) else { return }
        let now = Date()
        resolutionLock.lock()
        let shouldAttempt = now.timeIntervalSince(lastAuthorizationRepairAttempt) >=
            authorizationRepairInterval
        if shouldAttempt {
            lastAuthorizationRepairAttempt = now
        }
        resolutionLock.unlock()
        guard shouldAttempt else {
            return
        }

        let process = Process()
        process.executableURL = helper
        process.arguments = ["--grok-bot-verify"]
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        let finished = DispatchSemaphore(value: 0)
        process.terminationHandler = { _ in finished.signal() }
        do {
            try process.run()
        } catch {
            return
        }
        guard finished.wait(timeout: .now() + 5) == .success else {
            process.terminate()
            return
        }
    }

    private static var bundledHelperURLs: [URL] {
        if let configured = ProcessInfo.processInfo.environment[
            "TOKEI_GROK_BOT_BUNDLED_HELPER"
        ], !configured.isEmpty {
            return [URL(fileURLWithPath: NSString(string: configured).expandingTildeInPath)]
        }
        var candidates = [
            Bundle.main.bundleURL
                .appendingPathComponent("Contents/Helpers")
                .appendingPathComponent(helperName),
        ]
        if let executable = Bundle.main.executableURL {
            candidates.append(
                executable.deletingLastPathComponent().appendingPathComponent(helperName)
            )
        }
        return candidates
    }

    private static func isUsableHelper(
        _ url: URL,
        requireCurrentUserOwner: Bool
    ) -> Bool {
        usableVersion(url, requireCurrentUserOwner: requireCurrentUserOwner) == requiredProtocolVersion
    }

    /// 文件本身可信（普通文件、属主对、别人写不了、可执行）时它报告的协议版本。
    private static func usableVersion(_ url: URL, requireCurrentUserOwner: Bool) -> Int? {
        var info = stat()
        guard lstat(url.path, &info) == 0,
              (info.st_mode & S_IFMT) == S_IFREG,
              (info.st_mode & (S_IWGRP | S_IWOTH)) == 0,
              (!requireCurrentUserOwner || info.st_uid == geteuid()),
              access(url.path, X_OK) == 0 else { return nil }
        return protocolVersion(at: url)
    }

    private static func protocolVersion(at url: URL) -> Int? {
        let process = Process()
        let output = Pipe()
        process.executableURL = url
        process.arguments = ["--grok-bot-helper-version"]
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        let finished = DispatchSemaphore(value: 0)
        process.terminationHandler = { _ in finished.signal() }
        do {
            try process.run()
        } catch {
            return nil
        }
        guard finished.wait(timeout: .now() + 2) == .success else {
            process.terminate()
            return nil
        }
        let data = output.fileHandleForReading.readDataToEndOfFile()
        guard process.terminationStatus == 0,
              data.count <= 32,
              let value = String(data: data, encoding: .utf8)?.trimmingCharacters(
                in: .whitespacesAndNewlines
              ) else { return nil }
        return Int(value)
    }

    private static func atomicReplace(_ source: URL, _ destination: URL) -> Bool {
        source.path.withCString { sourcePath in
            destination.path.withCString { destinationPath in
                rename(sourcePath, destinationPath) == 0
            }
        }
    }

    private static func cache(_ url: URL) {
        resolutionLock.lock()
        cachedHelperURL = url
        resolvedOnce = true
        resolutionLock.unlock()
    }
}
