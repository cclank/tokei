import Foundation
import Security

// Only the query's target is redirected. Apple's actual SecItemCopyMatching
// enforces the real ACL and lock state; production no-UI flags stay unchanged.
func integrationKeychainRead(_ original: CFDictionary, _ output: UnsafeMutablePointer<CFTypeRef?>?) -> OSStatus {
    let env = ProcessInfo.processInfo.environment
    guard let path = env["TOKEI_TEST_KEYCHAIN"], let service = env["TOKEI_TEST_SERVICE"],
          let statusPath = env["TOKEI_TEST_READ_STATUS"] else { fatalError("Missing isolated fixture") }
    var keychain: SecKeychain?
    let opened = SecKeychainOpen(path, &keychain)
    guard opened == errSecSuccess, let keychain else { return opened }
    var query = original as! [String: Any]
    query[kSecAttrService as String] = service
    query[kSecMatchSearchList as String] = [keychain]
    let status = Security.SecItemCopyMatching(query as CFDictionary, output)
    try! String(status).write(toFile: statusPath, atomically: true, encoding: .utf8)
    return status
}

@main struct GrokBotRealKeychainHelper {
    static func main() {
#if TOKEI_GROK_BOT_KEYCHAIN_TEST
        GrokBotQuotaBridge.copyKeychainItem = integrationKeychainRead
#endif
        if CommandLine.arguments.contains("--grok-bot-data-json") {
            // Exercise the real credential path, replacing only the HTTP request
            // with a synthetic response so no credentials leave this test host.
            guard GrokBotQuotaBridge.integrationCredentialRead() else { exit(2) }
            let result: [String: Any] = [
                "quotaFetched": true, "usageFetched": false,
                "updated": Int(Date().timeIntervalSince1970),
                "sandUsage": ["hasNonZeroIncludedLimit": true, "usagePercent": 25],
            ]
            FileHandle.standardOutput.write(try! JSONSerialization.data(withJSONObject: result))
            return
        }
        if GrokBotQuotaBridge.runIfRequested() { return }
        exit(64)
    }
}
