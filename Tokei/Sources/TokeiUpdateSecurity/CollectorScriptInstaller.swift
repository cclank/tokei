import Foundation

public enum CollectorScriptInstaller {
    private static let revisionPrefix = "# TOKEI_COLLECTOR_REVISION="

    private static func collectorRevision(at path: String) -> Int? {
        guard let handle = FileHandle(forReadingAtPath: path) else { return nil }
        defer { handle.closeFile() }
        let data = handle.readData(ofLength: 4096)
        // Decode lines independently: the read limit may split a UTF-8
        // character in a later comment without invalidating the ASCII revision.
        for line in data.split(separator: 0x0A) {
            guard let header = String(data: line, encoding: .utf8),
                  header.hasPrefix(revisionPrefix) else { continue }
            return Int(header.dropFirst(revisionPrefix.count)
                .trimmingCharacters(in: .whitespacesAndNewlines))
        }
        return nil
    }

    private static func shouldPreserveInstalledScript(
        installedPath: String,
        bundledPath: String,
        recordedRelease: String,
        bundledRelease: String
    ) -> Bool {
        if let bundledRevision = collectorRevision(at: bundledPath) {
            guard let installedRevision = collectorRevision(at: installedPath) else {
                // Legacy custom builds can carry a larger app version while still
                // lacking collector fixes shipped by the current bundle.
                return false
            }
            if installedRevision != bundledRevision {
                return installedRevision > bundledRevision
            }
        }
        return UpdateSecurity.isNewerVersion(recordedRelease, than: bundledRelease)
    }

    public static func sync(resourceDir: String, userDir: URL, bundledRelease: String) {
        let fileManager = FileManager.default
        try? fileManager.createDirectory(at: userDir, withIntermediateDirectories: true)
        let markerPath = userDir.appendingPathComponent("script.version").path

        for name in ["usage.30s.py", "pricing.json", "pricing_overrides.json"] {
            let source = (resourceDir as NSString).appendingPathComponent(name)
            let destination = userDir.appendingPathComponent(name).path
            guard fileManager.fileExists(atPath: source) else { continue }

            if name == "usage.30s.py" {
                // 只升不降:旧版 app 启动不得用旧脚本覆盖新版脚本
                if fileManager.fileExists(atPath: destination),
                   let recorded = try? String(contentsOfFile: markerPath, encoding: .utf8)
                       .trimmingCharacters(in: .whitespacesAndNewlines),
                   !recorded.isEmpty,
                   shouldPreserveInstalledScript(
                       installedPath: destination,
                       bundledPath: source,
                       recordedRelease: recorded,
                       bundledRelease: bundledRelease
                   ) {
                    continue
                }
                try? fileManager.removeItem(atPath: destination)
                try? fileManager.copyItem(atPath: source, toPath: destination)
                try? bundledRelease.write(
                    toFile: markerPath,
                    atomically: true,
                    encoding: .utf8
                )
            } else if !fileManager.fileExists(atPath: destination) {
                try? fileManager.copyItem(atPath: source, toPath: destination)
            }
        }
    }
}
