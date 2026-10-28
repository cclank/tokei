import Darwin
import Foundation
import CryptoKit

enum GrokBotHelperManager {
    /// 5：所有 macOS 的后台读取均禁止进程交互，保留历史授权。
    static let requiredProtocolVersion = 5
    /// 已安装的辅助程序不低于这个版本就照常用来采集。换新版会让钥匙串重新弹授权框，
    /// 不能因为 App 升级就把用户授权过的旧版停掉——只在用户主动（重新）授权时换。
    static let minimumProtocolVersion = 1
    private static let helperName = "TokeiGrokBotHelper"
    /// 解析时顺手记下已安装辅助程序的版本，界面据此提示重新授权，不在主线程起进程。
    private static var installedVersion: Int?
    private static let resolutionLock = NSLock()
    private static var cachedHelperURL: URL?
    private static var resolvedOnce = false
    private static var backgroundAccessBlocked = false
    // v1.0.48 官方 Universal 助手缺少旧系统的进程级交互保护。
    // 精确识别问题产物，保留其他已授权助手的文件与钥匙串 ACL。
    static let unsafeLegacyHelperDigests: Set<String> = [
        "1525a5c064142306f108097b68fa2b785d7215f127e8c6c44fdb55994fc3cc9e",
    ]

    static func resolvedHelperURL(
        macOSMajorVersion: Int = ProcessInfo.processInfo.operatingSystemVersion.majorVersion,
        blockedHelperDigests: Set<String> = unsafeLegacyHelperDigests
    ) -> URL? {
        resolutionLock.lock()
        let resolved: URL?
        if resolvedOnce {
            resolved = cachedHelperURL
        } else {
            resolvedOnce = true
            let installed = installedHelperURL
            installedVersion = usableVersion(installed, requireCurrentUserOwner: true)
            if (installedVersion ?? 0) >= minimumProtocolVersion {
                let unsafe: Bool
                if (installedVersion ?? 0) < 3 {
                    unsafe = (try? Data(contentsOf: installed)).map {
                        blockedHelperDigests.contains(SHA256.hash(data: $0).map {
                            String(format: "%02x", $0)
                        }.joined()) || !$0.containsLegacyKeychainSuppression
                    } ?? true
                } else {
                    // Protocols 3/4 suppressed interaction only before macOS 26.
                    unsafe = macOSMajorVersion >= 26 && (installedVersion ?? 0) < 5
                }
                backgroundAccessBlocked = unsafe
                cachedHelperURL = unsafe ? nil : installed
            } else {
                // A bundled executable has a different Keychain identity. Only
                // explicit authorization may install it; do not probe it on launch.
                cachedHelperURL = nil
            }
            resolved = cachedHelperURL
        }
        resolutionLock.unlock()
        return resolved
    }

    static func runIfRequested() -> Bool {
        guard CommandLine.arguments.contains("--grok-bot-resolve-helper") else { return false }
        let path = resolvedHelperURL()?.path
        let result: [String: Any] = [
            "helper": path as Any? ?? NSNull(),
            "blocked": path == nil || isBackgroundAccessBlocked,
        ]
        if let data = try? JSONSerialization.data(withJSONObject: result) {
            FileHandle.standardOutput.write(data)
        }
        return true
    }

    static var isBackgroundAccessBlocked: Bool {
        resolutionLock.lock()
        defer { resolutionLock.unlock() }
        return backgroundAccessBlocked
    }

    /// 已安装的是能用、但不是最新的辅助程序：提示用户重新授权一次换上新版。
    static var needsReauthorization: Bool {
        resolutionLock.lock()
        defer { resolutionLock.unlock() }
        return backgroundAccessBlocked || (installedVersion.map { $0 < 2 } ?? false)
    }

    static func installIfNeeded() -> URL? {
        let destination = installedHelperURL
        if isUsableHelper(destination, requireCurrentUserOwner: true) {
            cache(destination)
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
        backgroundAccessBlocked = false
        resolutionLock.unlock()
    }
}

private extension Data {
    /// Protocols 1/2 predate capability reporting. Their dedicated bridge had
    /// one Keychain read path. A build without this import cannot suppress the
    /// legacy ACL prompt. This also detects re-signed and single-arch v1.0.48
    /// helpers whose whole-file digest differs from the official Universal DMG.
    var containsLegacyKeychainSuppression: Bool {
        range(of: Data("_SecKeychainSetUserInteractionAllowed\0".utf8)) != nil
    }
}
