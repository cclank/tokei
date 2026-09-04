import Foundation
import Darwin
import LocalAuthentication
import Security

enum ProviderSecret: String {
    case sub2api
    case zai
}

enum ProviderCredentialStore {
#if TOKEI_PROVIDER_CREDENTIAL_STORE_TEST
    // The test binary is compiled with a separate service so its round-trip
    // checks can never touch a user's real provider credentials.
    private static let service = "com.tokei.app.provider-api-key.test." + UUID().uuidString
    private static let testKeychainURL = FileManager.default.temporaryDirectory
        .appendingPathComponent("tokei-provider-" + UUID().uuidString + ".keychain-db")
    private static let testKeychain: SecKeychain = {
        let password = Data("tokei-provider-test".utf8)
        var keychain: SecKeychain?
        let status = testKeychainURL.path.withCString { path in
            password.withUnsafeBytes { bytes in
                SecKeychainCreate(
                    path,
                    UInt32(password.count),
                    bytes.baseAddress,
                    false,
                    nil,
                    &keychain
                )
            }
        }
        guard status == errSecSuccess, let keychain else {
            fatalError("Unable to create isolated provider test keychain: \(status)")
        }
        return keychain
    }()
#else
    // v2 avoids inaccessible items created by older ad-hoc builds whose ACL is
    // tied to a one-off code hash. Do not probe the old service: macOS can block
    // indefinitely while decrypting those items even when UI is disabled.
    private static let service = "com.tokei.app.provider-api-key.v2"
#endif
    private static let interactionLock = NSLock()
    private static let clearedMarker = "__TOKEI_PROVIDER_CLEARED_V1__"

#if TOKEI_PROVIDER_CREDENTIAL_STORE_TEST
    static func purgeTestItems() {
        for provider in [ProviderSecret.sub2api, .zai] {
            _ = SecItemDelete(baseQuery(for: provider, service: service) as CFDictionary)
        }
    }

    static func destroyTestKeychain() {
        _ = SecKeychainDelete(testKeychain)
        try? FileManager.default.removeItem(at: testKeychainURL)
    }
#endif

    private enum TokenLookup {
        case missing
        case cleared
        case value(String)
    }

    static func runIfRequested() -> Bool {
        if CommandLine.arguments.contains("--zed-authorize") {
            let ok = zedCredentials(allowInteraction: true) != nil
            print(ok ? "ok" : "unavailable")
            exit(ok ? 0 : 2)
        }
        if CommandLine.arguments.contains("--zed-verify") {
            let ok = zedCredentials() != nil
            print(ok ? "ok" : "unavailable")
            exit(ok ? 0 : 2)
        }
        return false
    }

    static func token(for provider: ProviderSecret) -> String? {
        switch tokenLookup(for: provider, service: service) {
        case .value(let value): return value
        case .cleared, .missing: return nil
        }
    }

    private static func tokenLookup(
        for provider: ProviderSecret,
        service: String
    ) -> TokenLookup {
        var query = baseQuery(for: provider, service: service)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        applyNoUI(to: &query)
        var result: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return .missing }
        guard let rawValue = String(data: data, encoding: .utf8) else { return .cleared }
        if rawValue == clearedMarker { return .cleared }
        let value = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard
              !value.isEmpty else { return .cleared }
        return .value(value)
    }

    @discardableResult
    static func setToken(_ token: String, for provider: ProviderSecret) -> Bool {
        let value = token.trimmingCharacters(in: .whitespacesAndNewlines)
        if value.isEmpty {
            let currentStatus = writeTokenData(
                Data(clearedMarker.utf8),
                for: provider, service: service, createIfMissing: true
            )
            return currentStatus == errSecSuccess
        }
        return writeTokenData(
            Data(value.utf8), for: provider, service: service, createIfMissing: true
        ) == errSecSuccess
    }

    private static func writeTokenData(
        _ data: Data,
        for provider: ProviderSecret,
        service: String,
        createIfMissing: Bool
    ) -> OSStatus {
        var query = baseQuery(for: provider, service: service)
        applyNoUI(to: &query)
        let update = [kSecValueData as String: data]
        let status = SecItemUpdate(query as CFDictionary, update as CFDictionary)
        if status == errSecSuccess || !createIfMissing { return status }
        guard status == errSecItemNotFound else { return status }
        var item = baseQuery(for: provider, service: service)
        targetTestKeychainForAdd(&item)
        item[kSecValueData as String] = data
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        applyNoUI(to: &item)
        return SecItemAdd(item as CFDictionary, nil)
    }

    static func environmentOverrides() -> [String: String] {
        var result: [String: String] = [:]
        if let token = token(for: .sub2api) {
            result["SUB2API_API_KEY"] = token
        }
        if let token = token(for: .zai) {
            result["Z_AI_API_KEY"] = token
        }
        if providerQuotaEnabled("zed"), let credentials = zedCredentials() {
            result["TOKEI_ZED_USER_ID"] = credentials.userID
            result["TOKEI_ZED_ACCESS_TOKEN"] = credentials.accessToken
        }
        return result
    }

    private static func baseQuery(
        for provider: ProviderSecret,
        service: String
    ) -> [String: Any] {
        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: provider.rawValue,
        ]
#if TOKEI_PROVIDER_CREDENTIAL_STORE_TEST
        query[kSecMatchSearchList as String] = [testKeychain]
#endif
        return query
    }

    private static func targetTestKeychainForAdd(_ item: inout [String: Any]) {
#if TOKEI_PROVIDER_CREDENTIAL_STORE_TEST
        item.removeValue(forKey: kSecMatchSearchList as String)
        item[kSecUseKeychain as String] = testKeychain
#endif
    }

    private static func providerQuotaEnabled(_ provider: String) -> Bool {
        let envKey = "TOKEI_\(provider.uppercased())_QUOTA"
        if ProcessInfo.processInfo.environment[envKey] == "1" { return true }
        if ProcessInfo.processInfo.environment[envKey] == "0" { return false }
        let url = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".tokei/config.json")
        guard let data = try? Data(contentsOf: url),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return false }
        return object["\(provider)_quota_enabled"] as? Bool ?? false
    }

    private struct ZedSettings: Decodable {
        var credentialsURL: String?
        var serverURL: String?

        enum CodingKeys: String, CodingKey {
            case credentialsURL = "credentials_url"
            case serverURL = "server_url"
        }
    }

    private static func zedCredentials(
        allowInteraction: Bool = false
    ) -> (userID: String, accessToken: String)? {
        let url = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".config/zed/settings.json")
        let settings = (try? Data(contentsOf: url))
            .flatMap { try? JSONDecoder().decode(ZedSettings.self, from: $0) }
        let credentialsURL = settings?.credentialsURL?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let serverURL = settings?.serverURL?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let serviceURL = [credentialsURL, serverURL, "https://zed.dev"]
            .compactMap { value -> String? in
                guard let value, !value.isEmpty else { return nil }
                return value
            }
            .first ?? "https://zed.dev"

        if let credentials = queryZedCredentials(
            itemClass: kSecClassInternetPassword,
            attribute: kSecAttrServer,
            value: serviceURL,
            allowInteraction: allowInteraction
        ) {
            return credentials
        }
        return queryZedCredentials(
            itemClass: kSecClassGenericPassword,
            attribute: kSecAttrService,
            value: serviceURL,
            allowInteraction: allowInteraction
        )
    }

    private static func queryZedCredentials(
        itemClass: CFTypeRef,
        attribute: CFString,
        value: String,
        allowInteraction: Bool
    ) -> (userID: String, accessToken: String)? {
        var query: [String: Any] = [
            kSecClass as String: itemClass,
            attribute as String: value,
            kSecMatchLimit as String: kSecMatchLimitOne,
            kSecReturnAttributes as String: true,
            kSecReturnData as String: true,
        ]
        if !allowInteraction {
            applyNoUI(to: &query)
        }
        var result: AnyObject?
        let status: OSStatus
        if allowInteraction {
            status = SecItemCopyMatching(query as CFDictionary, &result)
        } else {
            status = withoutKeychainUI {
                SecItemCopyMatching(query as CFDictionary, &result)
            }
        }
        guard status == errSecSuccess,
              let item = result as? [String: Any],
              let userID = item[kSecAttrAccount as String] as? String,
              let data = item[kSecValueData as String] as? Data,
              let accessToken = String(data: data, encoding: .utf8),
              !userID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !accessToken.isEmpty else { return nil }
        return (userID, accessToken)
    }

    private static func withoutKeychainUI<T>(_ body: () -> T) -> T {
        interactionLock.lock()
        defer { interactionLock.unlock() }
        var interactionAllowed: DarwinBoolean = false
        let status = SecKeychainGetUserInteractionAllowed(&interactionAllowed)
        if status == errSecSuccess {
            SecKeychainSetUserInteractionAllowed(false)
        }
        defer {
            if status == errSecSuccess {
                SecKeychainSetUserInteractionAllowed(interactionAllowed.boolValue)
            }
        }
        return body()
    }

    private static let uiFailPolicy: String = {
        let path = "/System/Library/Frameworks/Security.framework/Security"
        guard let handle = dlopen(path, RTLD_NOW) else { return "u_AuthUIF" }
        defer { dlclose(handle) }
        guard let symbol = dlsym(handle, "kSecUseAuthenticationUIFail") else {
            return "u_AuthUIF"
        }
        return symbol.assumingMemoryBound(to: CFString?.self).pointee as String? ?? "u_AuthUIF"
    }()

    private static func applyNoUI(to query: inout [String: Any]) {
        let context = LAContext()
        context.interactionNotAllowed = true
        query[kSecUseAuthenticationContext as String] = context
        query[kSecUseAuthenticationUI as String] = uiFailPolicy as CFString
    }
}
