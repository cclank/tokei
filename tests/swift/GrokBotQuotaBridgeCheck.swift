import Foundation
import Security
import Darwin

@main
struct GrokBotQuotaBridgeCheck {
    static func main() {
        if GrokBotQuotaBridge.runIfRequested() { return }
        checkLegacyKeychainInteractionPolicy()
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

    private static func keychainInteractionAllowed() -> Bool {
        var allowed = DarwinBoolean(false)
        precondition(
            SecKeychainGetUserInteractionAllowed(&allowed) == errSecSuccess,
            "Could not read the process keychain interaction setting"
        )
        return allowed.boolValue
    }

    private static func checkLegacyKeychainInteractionPolicy() {
        let original = keychainInteractionAllowed()
        defer { _ = SecKeychainSetUserInteractionAllowed(original) }
        precondition(SecKeychainSetUserInteractionAllowed(true) == errSecSuccess)

        for version in [13, 15, 25] {
            let value: String? = GrokBotQuotaBridge.withLegacyKeychainInteractionSuppressed(
                allowInteraction: false, macOSMajorVersion: version
            ) {
                precondition(!keychainInteractionAllowed(), "Legacy reads must not prompt")
                return "read"
            }
            precondition(value == "read" && keychainInteractionAllowed())

            let failedRead: String? = GrokBotQuotaBridge.withLegacyKeychainInteractionSuppressed(
                allowInteraction: false, macOSMajorVersion: version
            ) {
                precondition(!keychainInteractionAllowed())
                return nil
            }
            precondition(failedRead == nil && keychainInteractionAllowed(),
                         "Failed reads must restore the previous setting")
        }

        for version in [26, 27] {
            let value: String? = GrokBotQuotaBridge.withLegacyKeychainInteractionSuppressed(
                allowInteraction: false, macOSMajorVersion: version
            ) {
                precondition(keychainInteractionAllowed(),
                             "macOS 26 and later must not use the legacy suppression API")
                return "modern"
            }
            precondition(value == "modern" && keychainInteractionAllowed())
        }

        for version in [15, 26] {
            let value: String? = GrokBotQuotaBridge.withLegacyKeychainInteractionSuppressed(
                allowInteraction: true, macOSMajorVersion: version
            ) {
                precondition(keychainInteractionAllowed(), "Explicit authorization may prompt")
                return "interactive"
            }
            precondition(value == "interactive" && keychainInteractionAllowed())
        }

        precondition(SecKeychainSetUserInteractionAllowed(false) == errSecSuccess)
        let value: Int? = GrokBotQuotaBridge.withLegacyKeychainInteractionSuppressed(
            allowInteraction: false, macOSMajorVersion: 15
        ) {
            precondition(!keychainInteractionAllowed())
            return 1
        }
        precondition(value == 1 && !keychainInteractionAllowed(),
                     "A previously disabled setting must remain disabled")
    }

}
