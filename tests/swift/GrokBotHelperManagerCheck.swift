import Darwin
import Foundation

private enum TestFailure: Error {
    case assertion(String)
}

@main
struct GrokBotHelperManagerCheck {
    static func main() throws {
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
        // 标记事先就在：这一段不触发补标记，免得占掉后面那次（每 5 分钟最多一次）
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
        try expect(FileManager.default.fileExists(atPath: authorizationMarker.path),
                   "a usable authorization should restore the missing local marker")

        try writeHelper(to: bundled, marker: "replacement")
        let second = GrokBotHelperManager.installIfNeeded()
        try expect(second == installed, "existing compatible helper should be reused")
        try expect(try Data(contentsOf: installed) == installedData,
                   "an app update should not replace a compatible authorized helper")
        try expect(GrokBotHelperManager.resolvedHelperURL() == installed,
                   "data collection should prefer the persistent helper")

        print("grok bot helper manager checks passed")
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
