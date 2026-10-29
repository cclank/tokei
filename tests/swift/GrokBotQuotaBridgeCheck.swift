import Foundation
import Security
import Darwin
import LocalAuthentication

@main
struct GrokBotQuotaBridgeCheck {
    static func main() {
        if GrokBotQuotaBridge.runIfRequested() { return }
        checkKeychainInteractionPolicy()
        checkFailedReadsPreserveAuthorization()
        let encoded = "djEwWQZAlsI15AYVuYhxWuDnjtvLtdxVhAFCrSG6HezmEw0="
        guard let blob = Data(base64Encoded: encoded),
              let value = GrokBotQuotaBridge.decryptElectronSafeStorage(
                blob,
                password: Data("test-password".utf8)
              ),
              value == "fixture-access-token" else {
            exit(1)
        }
        let fixture = Data(#"""
        {
          "usageEventsDisplay": [
            {
              "timestamp": "1800000000000",
              "model": "grok-code-fast-1",
              "clientType": "sand",
              "userEmail": "private@example.com",
              "conversationId": "private-conversation",
              "tokenUsage": {
                "inputTokens": 120,
                "outputTokens": 30,
                "cacheReadTokens": 400,
                "cacheWriteTokens": 10,
                "totalCents": 1.25
              }
            },
            {
              "timestamp": "1800000001000",
              "model": "cursor-model",
              "clientType": "cursor",
              "tokenUsage": {"inputTokens": 99}
            }
          ]
        }
        """#.utf8)
        guard let events = GrokBotQuotaBridge.sanitizedUsageEvents(from: fixture),
              events.count == 1,
              events[0]["model"] as? String == "grok-code-fast-1",
              events[0]["userEmail"] == nil,
              events[0]["conversationId"] == nil,
              (events[0]["eventKey"] as? String)?.count == 64,
              let usage = events[0]["tokenUsage"] as? [String: Any],
              usage["cacheReadTokens"] as? Int == 400 else {
            exit(1)
        }
        print("ok")
    }

    private static func checkFailedReadsPreserveAuthorization() {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("tokei-grok-consent-\(UUID().uuidString)")
        try! FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let marker = root.appendingPathComponent("authorized")
        let existing = Data("historical-authorization".utf8)
        try! existing.write(to: marker)
        let modified = try! marker.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate
        setenv("TOKEI_GROK_BOT_AUTH_MARKER", marker.path, 1)
        defer {
            unsetenv("TOKEI_GROK_BOT_AUTH_MARKER")
            try? FileManager.default.removeItem(at: root)
        }
        var queries = 0
        for failure in [errSecInteractionNotAllowed, errSecAuthFailed, errSecNotAvailable, errSecItemNotFound] {
            GrokBotQuotaBridge.copyKeychainItem = { query, _ in
                queries += 1
                let query = query as! [String: Any]
                precondition((query[kSecUseAuthenticationContext as String] as? LAContext)?.interactionNotAllowed == true)
                precondition(query[kSecUseAuthenticationUI as String] != nil)
                return failure
            }
            for _ in 0..<3 {
                precondition(GrokBotQuotaBridge.fetchQuotaJSON(allowInteraction: false) == nil)
                precondition(GrokBotQuotaBridge.fetchDataJSON(allowInteraction: false) == nil)
                precondition(!GrokBotQuotaBridge.verifyPersistentAuthorization())
                precondition(try! Data(contentsOf: marker) == existing)
                precondition(try! marker.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate == modified)
            }
        }
        precondition(queries == 36)
        GrokBotQuotaBridge.copyKeychainItem = { _, _ in errSecUserCanceled }
        precondition(!GrokBotQuotaBridge.authorize(), "Cancelling a new prompt must retain the existing grant")
        precondition(try! Data(contentsOf: marker) == existing)
        try! FileManager.default.removeItem(at: marker)
        GrokBotQuotaBridge.copyKeychainItem = { _, _ in
            preconditionFailure("A missing consent marker must not reach any Keychain query")
        }
        precondition(GrokBotQuotaBridge.fetchQuotaJSON(allowInteraction: false) == nil)
        precondition(GrokBotQuotaBridge.fetchDataJSON(allowInteraction: false) == nil)
    }

    private static func keychainInteractionAllowed() -> Bool {
        var allowed = DarwinBoolean(false)
        precondition(
            SecKeychainGetUserInteractionAllowed(&allowed) == errSecSuccess,
            "Could not read the process keychain interaction setting"
        )
        return allowed.boolValue
    }

    private static func checkKeychainInteractionPolicy() {
        let original = keychainInteractionAllowed()
        defer { _ = SecKeychainSetUserInteractionAllowed(original) }
        precondition(SecKeychainSetUserInteractionAllowed(true) == errSecSuccess)

        for _ in 0..<3 {
            let value: String? = GrokBotQuotaBridge.withKeychainInteractionSuppressed(
                allowInteraction: false
            ) {
                precondition(!keychainInteractionAllowed(), "Background reads must not prompt on any macOS")
                return "read"
            }
            precondition(value == "read" && keychainInteractionAllowed())

            let failedRead: String? = GrokBotQuotaBridge.withKeychainInteractionSuppressed(
                allowInteraction: false
            ) {
                precondition(!keychainInteractionAllowed())
                return nil
            }
            precondition(failedRead == nil && keychainInteractionAllowed(),
                         "Failed reads must restore the previous setting")
        }

        for _ in 0..<2 {
            let value: String? = GrokBotQuotaBridge.withKeychainInteractionSuppressed(
                allowInteraction: true
            ) {
                precondition(keychainInteractionAllowed(), "Explicit authorization may prompt")
                return "interactive"
            }
            precondition(value == "interactive" && keychainInteractionAllowed())
        }

        precondition(SecKeychainSetUserInteractionAllowed(false) == errSecSuccess)
        let value: Int? = GrokBotQuotaBridge.withKeychainInteractionSuppressed(
            allowInteraction: false
        ) {
            precondition(!keychainInteractionAllowed())
            return 1
        }
        precondition(value == 1 && !keychainInteractionAllowed(),
                     "A previously disabled setting must remain disabled")
    }

}
