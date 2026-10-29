// Runs only against an explicitly named temporary test keychain.
import AppKit
import Foundation
import Security
import Darwin

private func checked(_ status: OSStatus, _ operation: String) {
    guard status == errSecSuccess else {
        fputs("\(operation): \(status)\n", stderr)
        exit(1)
    }
}

@main struct GrokBotKeychainFixture {
    static func main() throws {
        let args = Array(CommandLine.arguments.dropFirst())
        guard args.count >= 1 else { exit(64) }
        if args[0] == "watch-windows" {
            guard args.count == 3 else { exit(64) }
            var samples = 0
            var seen: Set<String> = []
            while !FileManager.default.fileExists(atPath: args[2]) {
                guard let windows = CGWindowListCopyWindowInfo(.optionOnScreenOnly, kCGNullWindowID)
                    as? [[String: Any]] else { exit(2) }
                for window in windows {
                    if let owner = window[kCGWindowOwnerName as String] as? String,
                       ["SecurityAgent", "CoreServicesUIAgent", "LocalAuthenticationRemoteService"].contains(owner) {
                        seen.insert(owner)
                    }
                }
                samples += 1
                let data = try JSONSerialization.data(withJSONObject: ["samples": samples, "authorizationWindows": seen.sorted()])
                try data.write(to: URL(fileURLWithPath: args[1]), options: .atomic)
                usleep(100_000)
            }
            return
        }
        if args[0] == "windows" {
            guard let windows = CGWindowListCopyWindowInfo(.optionAll, kCGNullWindowID)
                as? [[String: Any]] else { exit(2) }
            let owners = windows.compactMap { $0[kCGWindowOwnerName as String] as? String }
            let auth = owners.filter {
                ["SecurityAgent", "CoreServicesUIAgent", "LocalAuthenticationRemoteService"].contains($0)
            }
            let data = try JSONSerialization.data(withJSONObject: ["windows": windows.count, "authorizationWindows": auth])
            FileHandle.standardOutput.write(data)
            return
        }
        if args[0] == "window-preflight" {
            let app = NSApplication.shared
            app.setActivationPolicy(.accessory)
            app.finishLaunching()
            let window = NSWindow(contentRect: NSRect(x: 40, y: 40, width: 180, height: 80),
                                  styleMask: [.titled], backing: .buffered, defer: false)
            window.title = "Tokei isolated CI check"
            window.isReleasedWhenClosed = false
            window.orderFrontRegardless()
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
            let windows = CGWindowListCopyWindowInfo(.optionOnScreenOnly, kCGNullWindowID) as? [[String: Any]] ?? []
            let visible = windows.contains { ($0[kCGWindowOwnerPID as String] as? Int32) == getpid() }
            window.close()
            guard visible else { fputs("Window observation unavailable\n", stderr); exit(2) }
            print("window observation available")
            return
        }
        guard args.count >= 3, args[1].hasSuffix(".keychain-db") else { exit(64) }
        let path = args[1]
        let password = "tokei-isolated-test-keychain"
        var keychain: SecKeychain?
        if args[0] == "create" {
            checked(path.withCString { path in
                password.withCString { passwordBytes in
                    SecKeychainCreate(path, UInt32(password.utf8.count), passwordBytes, false, nil, &keychain)
                }
            }, "create isolated keychain")
        } else {
            checked(SecKeychainOpen(path, &keychain), "open isolated keychain")
        }
        guard let keychain else { exit(1) }
        if args[0] == "delete" { checked(SecKeychainDelete(keychain), "delete fixture"); return }
        if args[0] == "lock" { checked(SecKeychainLock(keychain), "lock fixture"); return }
        if args[0] == "unlock" {
            checked(password.withCString { SecKeychainUnlock(keychain, UInt32(password.utf8.count), $0, true) }, "unlock fixture")
            return
        }
        let service = args[2]
        if args[0] == "create" {
            guard args.count == 4 else { exit(64) }
            var helper: SecTrustedApplication?
            var administrator: SecTrustedApplication?
            checked(SecTrustedApplicationCreateFromPath(args[3], &helper), "trust fixture helper")
            checked(SecTrustedApplicationCreateFromPath(nil, &administrator), "trust fixture administrator")
            var access: SecAccess?
            checked(SecAccessCreate("Tokei isolated keychain test" as CFString,
                                   [helper!, administrator!] as CFArray, &access), "create fixture ACL")
            let item: [String: Any] = [
                kSecClass as String: kSecClassGenericPassword,
                kSecAttrService as String: service,
                kSecAttrAccount as String: "fixture-account",
                kSecAttrAccess as String: access!,
                kSecUseKeychain as String: keychain,
                kSecValueData as String: Data("fixture-safe-storage-password".utf8),
            ]
            checked(SecItemAdd(item as CFDictionary, nil), "save fixture credential")
            return
        }
        if args[0] == "acl" {
            let query: [String: Any] = [
                kSecClass as String: kSecClassGenericPassword,
                kSecAttrService as String: service,
                kSecMatchSearchList as String: [keychain],
                kSecReturnRef as String: true,
                kSecMatchLimit as String: kSecMatchLimitOne,
            ]
            var item: CFTypeRef?
            checked(SecItemCopyMatching(query as CFDictionary, &item), "find fixture metadata")
            var access: SecAccess?
            checked(SecKeychainItemCopyAccess(unsafeBitCast(item!, to: SecKeychainItem.self), &access), "read fixture ACL")
            var list: CFArray?
            checked(SecAccessCopyACLList(access!, &list), "read fixture ACL entries")
            var entries: [[String: Any]] = []
            for acl in (list as? [SecACL] ?? []) {
                var apps: CFArray?
                var description: CFString?
                var prompt = SecKeychainPromptSelector(rawValue: 0)
                checked(SecACLCopyContents(acl, &apps, &description, &prompt), "read ACL contents")
                let applicationData = (apps as? [SecTrustedApplication] ?? []).map { app -> String in
                    var data: CFData?
                    checked(SecTrustedApplicationCopyData(app, &data), "read trusted application")
                    return (data! as Data).base64EncodedString()
                }.sorted()
                entries.append(["applications": applicationData, "prompt": prompt.rawValue,
                                "authorizations": (SecACLCopyAuthorizations(acl) as NSArray).map { String(describing: $0) }.sorted()])
            }
            FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: entries, options: .sortedKeys))
            return
        }
        exit(64)
    }
}
