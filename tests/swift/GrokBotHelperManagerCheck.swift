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

    private static func writeHelper(to url: URL, marker: String) throws {
        let script = """
        #!/bin/sh
        # \(marker)
        if [ "$1" = "--grok-bot-helper-version" ]; then
          echo \(GrokBotHelperManager.requiredProtocolVersion)
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
