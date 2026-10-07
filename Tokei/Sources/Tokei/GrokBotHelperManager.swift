import Darwin
import Foundation

enum GrokBotHelperManager {
    static let requiredProtocolVersion = 2
    private static let helperName = "TokeiGrokBotHelper"
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
            if isUsableHelper(installed, requireCurrentUserOwner: true) {
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
        var info = stat()
        guard lstat(url.path, &info) == 0,
              (info.st_mode & S_IFMT) == S_IFREG,
              (info.st_mode & (S_IWGRP | S_IWOTH)) == 0,
              (!requireCurrentUserOwner || info.st_uid == geteuid()),
              access(url.path, X_OK) == 0 else { return false }
        return protocolVersion(at: url) == requiredProtocolVersion
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
