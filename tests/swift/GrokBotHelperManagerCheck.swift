import Darwin
import Foundation
import CryptoKit

private enum TestFailure: Error {
    case assertion(String)
}

@main
struct GrokBotHelperManagerCheck {
    static func main() throws {
        if let scenario = CommandLine.arguments.dropFirst().first {
            try checkLegacyAuthorization(scenario)
            print("grok bot helper manager checks passed")
            return
        }
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("tokei-grok-helper-\(UUID().uuidString)")
        let bundled = root.appendingPathComponent("BundledHelper")
        let installed = root.appendingPathComponent("installed/TokeiGrokBotHelper")
        let authorizationMarker = root.appendingPathComponent("authorization-marker")
        defer {
            unsetenv("TOKEI_GROK_BOT_BUNDLED_HELPER")
            unsetenv("TOKEI_GROK_BOT_PERSISTENT_HELPER")
            unsetenv("TOKEI_GROK_BOT_AUTH_MARKER")
            try? FileManager.default.removeItem(at: root)
        }

        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)

        // 已授权的旧版助手照常用来采集，并提示重新授权；用户点授权时才换成新版。
        // 先跑这一段：管理器在进程里缓存解析结果。
        let legacyRoot = root.appendingPathComponent("legacy")
        let legacyBundled = legacyRoot.appendingPathComponent("BundledHelper")
        let legacyInstalled = legacyRoot.appendingPathComponent("installed/TokeiGrokBotHelper")
        try FileManager.default.createDirectory(
            at: legacyInstalled.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try writeHelper(to: legacyBundled, marker: "new")
        try writeHelper(to: legacyInstalled, marker: "old",
                        version: GrokBotHelperManager.minimumProtocolVersion)
        // 已有授权标记必须保留，解析助手时不能重新访问钥匙串。
        let legacyMarker = legacyRoot.appendingPathComponent("authorization-marker")
        try Data("ok\n".utf8).write(to: legacyMarker)
        setenv("TOKEI_GROK_BOT_BUNDLED_HELPER", legacyBundled.path, 1)
        setenv("TOKEI_GROK_BOT_PERSISTENT_HELPER", legacyInstalled.path, 1)
        setenv("TOKEI_GROK_BOT_AUTH_MARKER", legacyMarker.path, 1)
        try expect(GrokBotHelperManager.resolvedHelperURL() == legacyInstalled,
                   "an authorized older helper should keep collecting data after an app update")
        try expect(GrokBotHelperManager.needsReauthorization,
                   "an older helper should prompt for re-authorization")
        try expect(GrokBotHelperManager.installIfNeeded() == legacyInstalled,
                   "authorizing should upgrade the helper in place")
        try expect(try String(contentsOf: legacyInstalled, encoding: .utf8).contains("# new"),
                   "authorizing should replace the older helper with the bundled one")
        try expect(!GrokBotHelperManager.needsReauthorization,
                   "the prompt should go away after upgrading")

        try writeHelper(to: bundled, marker: "original")
        try FileManager.default.createDirectory(
            at: installed.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try FileManager.default.createSymbolicLink(at: installed, withDestinationURL: bundled)
        setenv("TOKEI_GROK_BOT_BUNDLED_HELPER", bundled.path, 1)
        setenv("TOKEI_GROK_BOT_PERSISTENT_HELPER", installed.path, 1)
        setenv("TOKEI_GROK_BOT_AUTH_MARKER", authorizationMarker.path, 1)

        let first = GrokBotHelperManager.installIfNeeded()
        try expect(first == installed, "helper should install at the persistent path")
        let installedData = try Data(contentsOf: installed)
        try expect(installedData == Data(try String(contentsOf: bundled, encoding: .utf8).utf8),
                   "installed helper should match the bundled helper")
        let attributes = try FileManager.default.attributesOfItem(atPath: installed.path)
        try expect((attributes[.posixPermissions] as? NSNumber)?.intValue == 0o700,
                   "installed helper permissions should be owner-only")
        try expect(!FileManager.default.fileExists(atPath: authorizationMarker.path),
                   "installing an executable must not trigger background authorization")

        try writeHelper(to: bundled, marker: "replacement")
        let second = GrokBotHelperManager.installIfNeeded()
        try expect(second == installed, "existing compatible helper should be reused")
        try expect(try Data(contentsOf: installed) == installedData,
                   "an app update should not replace a compatible authorized helper")
        try expect(GrokBotHelperManager.resolvedHelperURL() == installed,
                   "data collection should prefer the persistent helper")

        print("grok bot helper manager checks passed")
    }

    private static func checkLegacyAuthorization(_ scenario: String) throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("tokei-helper-authorization-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: root) }
        let installed = root.appendingPathComponent("installed/TokeiGrokBotHelper")
        let bundled = root.appendingPathComponent("bundled/TokeiGrokBotHelper")
        let marker = root.appendingPathComponent("authorized")
        for path in [installed, bundled] {
            try FileManager.default.createDirectory(
                at: path.deletingLastPathComponent(), withIntermediateDirectories: true)
        }
        try writeHelper(to: installed, marker: "preserved-old", version: 2)
        try writeHelper(to: bundled, marker: "fixed-current")
        let old = try Data(contentsOf: installed)
        let grant = Data("existing-authorization\n".utf8)
        try grant.write(to: marker)
        setenv("TOKEI_GROK_BOT_PERSISTENT_HELPER", installed.path, 1)
        setenv("TOKEI_GROK_BOT_BUNDLED_HELPER", bundled.path, 1)
        setenv("TOKEI_GROK_BOT_AUTH_MARKER", marker.path, 1)
        let digest = SHA256.hash(data: old).map { String(format: "%02x", $0) }.joined()
        let blocked: Set<String> = scenario == "preserve-v2" ? [] : [digest]
        let version = scenario == "modern-v2" ? 27 : 15
        let helper = GrokBotHelperManager.resolvedHelperURL(
            macOSMajorVersion: version, blockedHelperDigests: blocked)
        try expect(try Data(contentsOf: installed) == old, "resolving must preserve trusted helper bytes")
        try expect(try Data(contentsOf: marker) == grant, "existing authorization must be retained")
        if scenario == "blocked-v2" {
            try expect(helper == nil, "a known unsafe helper must not run in the background")
            try expect(GrokBotHelperManager.isBackgroundAccessBlocked, "collector fallback must be blocked")
            try expect(GrokBotHelperManager.needsReauthorization, "manual upgrade must be discoverable")
            try expect(GrokBotHelperManager.installIfNeeded() == installed, "explicit authorization must install the fixed helper")
            try expect(try Data(contentsOf: installed) == Data(contentsOf: bundled), "manual upgrade must use the fixed executable")
            try expect(try Data(contentsOf: marker) == grant, "installing must not silently overwrite authorization")
            try expect(!GrokBotHelperManager.isBackgroundAccessBlocked, "manual upgrade clears the unsafe-helper state")
            try expect(!GrokBotHelperManager.needsReauthorization, "upgrade prompt must clear")
        } else {
            try expect(helper == installed, "safe authorized helpers must continue to work")
            try expect(!GrokBotHelperManager.isBackgroundAccessBlocked, "safe old helpers must remain enabled")
            try expect(!GrokBotHelperManager.needsReauthorization, "normal upgrades must not require reauthorization")
        }
        try FileManager.default.removeItem(at: marker)
        for _ in 0..<3 { _ = GrokBotHelperManager.resolvedHelperURL() }
        try expect(!FileManager.default.fileExists(atPath: marker.path), "background refresh must never probe authorization")
    }

    private static func writeHelper(
        to url: URL, marker: String,
        version: Int = GrokBotHelperManager.requiredProtocolVersion
    ) throws {
        let script = """
        #!/bin/sh
        # \(marker)
        if [ "$1" = "--grok-bot-helper-version" ]; then
          echo \(version)
          exit 0
        fi
        if [ "$1" = "--grok-bot-verify" ]; then
          printf 'ok\\n' > "$TOKEI_GROK_BOT_AUTH_MARKER"
          exit 0
        fi
        exit 2
        """
        try Data(script.utf8).write(to: url, options: .atomic)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o755],
            ofItemAtPath: url.path
        )
    }

    private static func expect(
        _ condition: @autoclosure () throws -> Bool,
        _ message: String
    ) throws {
        if try !condition() {
            throw TestFailure.assertion(message)
        }
    }
}
