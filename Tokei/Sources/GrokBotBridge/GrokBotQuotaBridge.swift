import Foundation
import Security
import CommonCrypto
import Darwin
import LocalAuthentication

private final class GrokBotNoRedirectDelegate: NSObject, URLSessionTaskDelegate {
    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest,
        completionHandler: @escaping (URLRequest?) -> Void
    ) {
        completionHandler(nil)
    }
}

public enum GrokBotQuotaBridge {
    private static let keychainService = "Grok Bot Safe Storage"
    private static let accountsKey = "cursor-accounts"
    private static let accessTokenKey = "cursor-access-token"
    private static let machineIDKey = "cursor-machine-id"
    private static let quotaURL = URL(
        string: "https://api2.cursor.sh/aiserver.v1.DashboardService/GetSandUsageStatus"
    )!
    private static let usageURL = URL(
        string: "https://api2.cursor.sh/aiserver.v1.DashboardService/GetFilteredUsageEvents"
    )!
    private static let maxResponseBytes = 2 * 1024 * 1024
    private static let maxUsageResponseBytes = 16 * 1024 * 1024
    private static let usagePageSize = 1_000
    // 平时只拉最近两天（--since），这里是首次从年初全量拉取时的上限：十万条。
    private static let maxUsagePages = 100

    private struct Credential {
        let token: String
        let machineID: String
    }

    private struct UsageResult {
        let events: [[String: Any]]
        let reportedCount: Int
        let startMilliseconds: Int64
    }

    private struct KeychainSecret {
        let password: Data
        let item: SecKeychainItem?
    }

    public static func runIfRequested() -> Bool {
        // 2：--grok-bot-data-json 支持 --since <毫秒>，只拉这之后的用量事件。
        if CommandLine.arguments.contains("--grok-bot-helper-version") {
            print("2")
            exit(0)
        }
        if CommandLine.arguments.contains("--grok-bot-authorize") {
            let ok = authorize()
            print(ok ? "ok" : "unavailable")
            exit(ok ? 0 : 2)
        }
        if CommandLine.arguments.contains("--grok-bot-verify") {
            let ok = verifyPersistentAuthorization()
            print(ok ? "ok" : "unavailable")
            exit(ok ? 0 : 2)
        }
        if CommandLine.arguments.contains("--grok-bot-data-json") {
            guard let data = fetchDataJSON(allowInteraction: false) else { exit(2) }
            FileHandle.standardOutput.write(data)
            exit(0)
        }
        if CommandLine.arguments.contains("--grok-bot-quota-json") {
            guard let data = fetchQuotaJSON(allowInteraction: false) else { exit(2) }
            FileHandle.standardOutput.write(data)
            exit(0)
        }
        return false
    }

    static func authorize() -> Bool {
        updateAuthorizationMarker(enabled: false)
        guard let result = credentialResult(
            allowInteraction: true,
            requireMarker: false,
            returnKeychainItem: true
        ) else { return false }

        // "Allow" may grant only this process one read. Persist the user's explicit
        // authorization by adding this app to the item's decrypt ACL, then let a
        // fresh process verify that the permission really survived.
        if let item = result.keychainItem {
            _ = persistCurrentAppAccess(to: item)
        }
        return true
    }

    static func verifyPersistentAuthorization() -> Bool {
        let ok = credential(allowInteraction: false, requireMarker: false) != nil
        updateAuthorizationMarker(enabled: ok)
        return ok
    }

    static func fetchQuotaJSON(allowInteraction: Bool) -> Data? {
        guard let credential = credential(
            allowInteraction: allowInteraction,
            requireMarker: !allowInteraction
        ), let object = fetchQuotaObject(credential: credential) else { return nil }
        return try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
    }

    static func fetchDataJSON(allowInteraction: Bool) -> Data? {
        guard let credential = credential(
            allowInteraction: allowInteraction,
            requireMarker: !allowInteraction
        ) else { return nil }

        let quota = fetchQuotaObject(credential: credential)
        let usage = fetchUsageEvents(credential: credential, since: requestedSince())
        guard quota != nil || usage != nil else { return nil }

        var output: [String: Any] = [
            "quotaFetched": quota != nil,
            "usageFetched": usage != nil,
            "updated": Int(Date().timeIntervalSince1970),
        ]
        if let quota { output["sandUsage"] = quota }
        if let usage {
            output["usageEventsDisplay"] = usage.events
            output["totalUsageEventsCount"] = usage.reportedCount
            output["usageStartDate"] = String(usage.startMilliseconds)
        }
        guard JSONSerialization.isValidJSONObject(output) else { return nil }
        return try? JSONSerialization.data(withJSONObject: output, options: [.sortedKeys])
    }

    private static func credential(
        allowInteraction: Bool,
        requireMarker: Bool
    ) -> Credential? {
        credentialResult(
            allowInteraction: allowInteraction,
            requireMarker: requireMarker,
            returnKeychainItem: false
        )?.credential
    }

    private static func credentialResult(
        allowInteraction: Bool,
        requireMarker: Bool,
        returnKeychainItem: Bool
    ) -> (credential: Credential, keychainItem: SecKeychainItem?)? {
        if requireMarker, !FileManager.default.fileExists(atPath: authorizationMarkerURL.path) {
            return nil
        }
        guard let secret = safeStoragePassword(
            allowInteraction: allowInteraction,
            returnKeychainItem: returnKeychainItem
        ) else {
            if !allowInteraction { updateAuthorizationMarker(enabled: false) }
            return nil
        }
        guard let stored = activeCredential(password: secret.password),
              let token = stored.token,
              let identity = jwtIdentity(token),
              identity.expiresAt > Date().timeIntervalSince1970 + 60 else { return nil }
        return (
            Credential(
                token: token,
                machineID: stored.machineID
            ),
            secret.item
        )
    }

    private static func fetchQuotaObject(credential: Credential) -> [String: Any]? {
        requestJSONObject(
            url: quotaURL,
            body: [:],
            credential: credential,
            timeout: 4,
            maxBytes: maxResponseBytes
        )
    }

    /// `--since <毫秒>`：采集器按天存了事件，只需要补最近的；没给就从年初拉。
    private static func requestedSince() -> Int64? {
        let arguments = CommandLine.arguments
        guard let index = arguments.firstIndex(of: "--since"), index + 1 < arguments.count else {
            return nil
        }
        return Int64(arguments[index + 1])
    }

    private static func fetchUsageEvents(credential: Credential, since: Int64? = nil) -> UsageResult? {
        let now = Date()
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = .current
        let year = calendar.component(.year, from: now)
        guard let start = calendar.date(from: DateComponents(year: year, month: 1, day: 1))
        else { return nil }
        let yearStartMilliseconds = Int64(start.timeIntervalSince1970 * 1_000)
        let endMilliseconds = Int64(now.timeIntervalSince1970 * 1_000)
        // 只认今年之内、不晚于现在的起点；越界就退回从年初拉
        let startMilliseconds = since.flatMap {
            $0 >= yearStartMilliseconds && $0 <= endMilliseconds ? $0 : nil
        } ?? yearStartMilliseconds
        var collected: [[String: Any]] = []
        var expectedCount: Int?
        var completed = false

        for page in 1...maxUsagePages {
            guard let response = requestJSONObject(
                url: usageURL,
                body: [
                    "page": page,
                    "pageSize": usagePageSize,
                    "startDate": String(startMilliseconds),
                    "endDate": String(endMilliseconds),
                    "clientType": "sand",
                ],
                credential: credential,
                timeout: 10,
                maxBytes: maxUsageResponseBytes
            ), let rawEvents = response["usageEventsDisplay"] as? [[String: Any]] else {
                return nil
            }
            if let count = integer(response["totalUsageEventsCount"]), count >= 0 {
                if let expectedCount, expectedCount != count { return nil }
                expectedCount = count
            }
            collected.append(contentsOf: rawEvents.compactMap(sanitizeUsageEvent))
            if rawEvents.isEmpty || rawEvents.count < usagePageSize ||
                (expectedCount.map { page * usagePageSize >= $0 } ?? false) {
                completed = true
                break
            }
        }
        guard completed else { return nil }
        return UsageResult(
            events: collected,
            reportedCount: expectedCount ?? collected.count,
            startMilliseconds: startMilliseconds
        )
    }

    private static func requestJSONObject(
        url: URL,
        body: [String: Any],
        credential: Credential,
        timeout: TimeInterval,
        maxBytes: Int
    ) -> [String: Any]? {
        guard url.scheme == "https", url.host?.lowercased() == "api2.cursor.sh",
              let bodyData = try? JSONSerialization.data(withJSONObject: body),
              bodyData.count <= maxResponseBytes else { return nil }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.httpBody = bodyData
        request.timeoutInterval = timeout
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("1", forHTTPHeaderField: "Connect-Protocol-Version")
        request.setValue("Bearer \(credential.token)", forHTTPHeaderField: "Authorization")
        request.setValue("sand", forHTTPHeaderField: "x-cursor-client-type")
        request.setValue(grokBotClientVersion, forHTTPHeaderField: "x-cursor-client-version")
        request.setValue("prod", forHTTPHeaderField: "x-sand-box-namespace")
        request.setValue("true", forHTTPHeaderField: "x-ghost-mode")
        request.setValue(cursorChecksum(machineID: credential.machineID),
                         forHTTPHeaderField: "x-cursor-checksum")
        request.setValue(UUID().uuidString, forHTTPHeaderField: "x-request-id")

        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieStorage = nil
        configuration.urlCache = nil
        configuration.timeoutIntervalForRequest = timeout
        configuration.timeoutIntervalForResource = timeout + 1
        let delegate = GrokBotNoRedirectDelegate()
        let session = URLSession(
            configuration: configuration,
            delegate: delegate,
            delegateQueue: nil
        )
        let semaphore = DispatchSemaphore(value: 0)
        var result: [String: Any]?
        let task = session.dataTask(with: request) { data, response, _ in
            defer { semaphore.signal() }
            guard let response = response as? HTTPURLResponse,
                  response.statusCode == 200,
                  let data,
                  data.count <= maxBytes,
                  let object = try? JSONSerialization.jsonObject(with: data)
                    as? [String: Any] else { return }
            result = object
        }
        task.resume()
        if semaphore.wait(timeout: .now() + timeout + 2) == .timedOut {
            task.cancel()
            session.invalidateAndCancel()
            return nil
        }
        session.finishTasksAndInvalidate()
        return result
    }

    static func sanitizedUsageEvents(from data: Data) -> [[String: Any]]? {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let events = object["usageEventsDisplay"] as? [[String: Any]] else { return nil }
        return events.compactMap(sanitizeUsageEvent)
    }

    private static func sanitizeUsageEvent(_ event: [String: Any]) -> [String: Any]? {
        if let clientType = event["clientType"] as? String,
           clientType.caseInsensitiveCompare("sand") != .orderedSame {
            return nil
        }
        guard let timestamp = integer64(event["timestamp"]), timestamp > 0,
              let tokenUsage = event["tokenUsage"] as? [String: Any] else { return nil }
        var cleanUsage: [String: Any] = [:]
        for key in [
            "inputTokens", "outputTokens", "cacheWriteTokens", "cacheReadTokens"
        ] {
            cleanUsage[key] = max(0, integer(tokenUsage[key]) ?? 0)
        }
        if let cents = number(tokenUsage["totalCents"]), cents >= 0 {
            cleanUsage["totalCents"] = cents
        }
        guard cleanUsage.values.contains(where: {
            ($0 as? Int).map { $0 > 0 } ?? false
        }) else { return nil }
        var clean: [String: Any] = [
            "timestamp": String(timestamp),
            "tokenUsage": cleanUsage,
            "clientType": "sand",
        ]
        if let eventData = try? JSONSerialization.data(
            withJSONObject: event,
            options: [.sortedKeys]
        ) {
            clean["eventKey"] = sha256Hex(eventData)
        }
        if let model = event["model"] as? String {
            let trimmed = model.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmed.isEmpty, trimmed.count <= 200 { clean["model"] = trimmed }
        }
        return clean
    }

    private static func sha256Hex(_ data: Data) -> String {
        var digest = [UInt8](repeating: 0, count: Int(CC_SHA256_DIGEST_LENGTH))
        data.withUnsafeBytes { bytes in
            _ = CC_SHA256(bytes.baseAddress, CC_LONG(data.count), &digest)
        }
        return digest.map { String(format: "%02x", $0) }.joined()
    }

    private static func integer(_ value: Any?) -> Int? {
        if let value = value as? NSNumber { return value.intValue }
        if let value = value as? String { return Int(value) }
        return nil
    }

    private static func integer64(_ value: Any?) -> Int64? {
        if let value = value as? NSNumber { return value.int64Value }
        if let value = value as? String { return Int64(value) }
        return nil
    }

    private static func number(_ value: Any?) -> Double? {
        if let value = value as? NSNumber { return value.doubleValue }
        if let value = value as? String { return Double(value) }
        return nil
    }

    static func decryptElectronSafeStorage(_ blob: Data, password: Data) -> String? {
        guard blob.count > 3 else { return nil }
        let prefix = String(data: blob.prefix(3), encoding: .utf8)
        guard prefix == "v10" || prefix == "v11" else { return nil }
        let encrypted = Data(blob.dropFirst(3))
        guard !encrypted.isEmpty, encrypted.count % kCCBlockSizeAES128 == 0,
              let key = deriveElectronKey(password) else { return nil }
        let iv = Data(repeating: 0x20, count: kCCBlockSizeAES128)
        let outputCapacity = encrypted.count + kCCBlockSizeAES128
        var output = Data(count: outputCapacity)
        var moved = 0
        let status = output.withUnsafeMutableBytes { outputBytes in
            encrypted.withUnsafeBytes { encryptedBytes in
                key.withUnsafeBytes { keyBytes in
                    iv.withUnsafeBytes { ivBytes in
                        CCCrypt(
                            CCOperation(kCCDecrypt),
                            CCAlgorithm(kCCAlgorithmAES),
                            CCOptions(kCCOptionPKCS7Padding),
                            keyBytes.baseAddress,
                            key.count,
                            ivBytes.baseAddress,
                            encryptedBytes.baseAddress,
                            encrypted.count,
                            outputBytes.baseAddress,
                            outputCapacity,
                            &moved
                        )
                    }
                }
            }
        }
        guard status == kCCSuccess, moved > 0, moved <= output.count else { return nil }
        output.removeSubrange(moved..<output.count)
        return String(data: output, encoding: .utf8)
    }

    private static func safeStoragePassword(
        allowInteraction: Bool,
        returnKeychainItem: Bool
    ) -> KeychainSecret? {
        var previousInteraction = DarwinBoolean(false)
        let interactionStatus = SecKeychainGetUserInteractionAllowed(&previousInteraction)
        if !allowInteraction, interactionStatus == errSecSuccess {
            SecKeychainSetUserInteractionAllowed(false)
        }
        defer {
            if !allowInteraction, interactionStatus == errSecSuccess {
                SecKeychainSetUserInteractionAllowed(previousInteraction.boolValue)
            }
        }
        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: keychainService,
            kSecMatchLimit as String: kSecMatchLimitOne,
            kSecReturnData as String: true,
        ]
        if returnKeychainItem {
            query[kSecReturnRef as String] = true
        }
        if !allowInteraction {
            let context = LAContext()
            context.interactionNotAllowed = true
            query[kSecUseAuthenticationContext as String] = context
            query[kSecUseAuthenticationUI as String] = uiFailPolicy as CFString
        }
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess else { return nil }
        if let data = item as? Data, !data.isEmpty {
            return KeychainSecret(password: data, item: nil)
        }
        guard let values = item as? [String: Any],
              let data = values[kSecValueData as String] as? Data,
              !data.isEmpty else {
            return nil
        }
        return KeychainSecret(
            password: data,
            item: keychainItem(from: values[kSecValueRef as String])
        )
    }

    private static func keychainItem(from value: Any?) -> SecKeychainItem? {
        guard let value else { return nil }
        let reference = value as CFTypeRef
        guard CFGetTypeID(reference) == SecKeychainItemGetTypeID() else { return nil }
        return unsafeBitCast(reference, to: SecKeychainItem.self)
    }

    private static func persistCurrentAppAccess(to item: SecKeychainItem) -> Bool {
        guard let executablePath = Bundle.main.executablePath else { return false }
        var trustedApp: SecTrustedApplication?
        let trustedStatus = executablePath.withCString {
            SecTrustedApplicationCreateFromPath($0, &trustedApp)
        }
        guard trustedStatus == errSecSuccess, let trustedApp else { return false }

        var access: SecAccess?
        guard SecKeychainItemCopyAccess(item, &access) == errSecSuccess,
              let access else { return false }
        var aclList: CFArray?
        guard SecAccessCopyACLList(access, &aclList) == errSecSuccess,
              let acls = aclList as? [SecACL] else { return false }

        var changed = false
        for acl in acls {
            let authorizations = SecACLCopyAuthorizations(acl) as NSArray
            guard authorizations.contains(kSecACLAuthorizationDecrypt) else { continue }

            var applicationList: CFArray?
            var description: CFString?
            var prompt = SecKeychainPromptSelector(rawValue: 0)
            guard SecACLCopyContents(
                acl,
                &applicationList,
                &description,
                &prompt
            ) == errSecSuccess,
                var applications = applicationList as? [SecTrustedApplication] else {
                return false
            }

            // Ad-hoc upgrades keep the path but change the trusted code hash.
            applications.removeAll { trustedApplicationPath($0) == executablePath }
            applications.append(trustedApp)
            guard SecACLSetContents(
                acl,
                applications as CFArray,
                description ?? keychainService as CFString,
                prompt
            ) == errSecSuccess else { return false }
            changed = true
        }
        guard changed else { return false }
        return SecKeychainItemSetAccess(item, access) == errSecSuccess
    }

    private static func trustedApplicationPath(_ application: SecTrustedApplication) -> String? {
        var data: CFData?
        guard SecTrustedApplicationCopyData(application, &data) == errSecSuccess,
              let raw = data as Data?,
              let path = String(data: raw, encoding: .utf8) else { return nil }
        return path.trimmingCharacters(in: .controlCharacters)
    }

    private static func activeCredential(
        password: Data
    ) -> (token: String?, machineID: String)? {
        let environment = ProcessInfo.processInfo.environment
        let secretsURL: URL
        if let configured = environment["TOKEI_GROK_BOT_SECRETS"], !configured.isEmpty {
            secretsURL = URL(fileURLWithPath: NSString(string: configured).expandingTildeInPath)
        } else {
            secretsURL = FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent("Library/Application Support/Grok Bot/sand-secrets.json")
        }
        guard let outerData = try? Data(contentsOf: secretsURL),
              outerData.count <= maxResponseBytes,
              let outer = try? JSONSerialization.jsonObject(with: outerData) as? [String: Any],
              let encodedMachineID = outer[machineIDKey] as? String,
              let machineID = decryptStoredSecret(encodedMachineID, password: password),
              isValidMachineID(machineID),
              let accountsJSON = outer[accountsKey] as? String,
              let accountsData = accountsJSON.data(using: .utf8),
              accountsData.count <= maxResponseBytes,
              let container = try? JSONSerialization.jsonObject(with: accountsData)
                as? [String: Any],
              let active = container["active"] as? String,
              let accounts = container["accounts"] as? [String: Any],
              let account = accounts[active] as? [String: Any],
              let encoded = account[accessTokenKey] as? String else { return nil }
        return (
            decryptStoredSecret(encoded, password: password),
            machineID
        )
    }

    private static func decryptStoredSecret(_ encoded: String, password: Data) -> String? {
        let ciphertext: String
        if encoded.hasPrefix("scoped:v1:"), let separator = encoded.lastIndex(of: ":") {
            ciphertext = String(encoded[encoded.index(after: separator)...])
        } else {
            ciphertext = encoded
        }
        guard ciphertext.count <= maxResponseBytes,
              let encrypted = Data(base64Encoded: ciphertext),
              let value = decryptElectronSafeStorage(encrypted, password: password),
              !value.isEmpty else { return nil }
        return value
    }

    private static func isValidMachineID(_ value: String) -> Bool {
        guard !value.isEmpty, value.count <= 512 else { return false }
        let allowed = CharacterSet(
            charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-"
        )
        return value.unicodeScalars.allSatisfy(allowed.contains)
    }

    private static func cursorChecksum(machineID: String, now: Date = Date()) -> String {
        let bucket = UInt64(max(0, Int64(now.timeIntervalSince1970 / 1_000)))
        var bytes = (0..<6).map { offset in
            UInt8(truncatingIfNeeded: bucket >> UInt64((5 - offset) * 8))
        }
        var previous: UInt8 = 165
        for index in bytes.indices {
            bytes[index] = (bytes[index] ^ previous) &+ UInt8(index)
            previous = bytes[index]
        }
        let encoded = Data(bytes).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
        return encoded + machineID
    }

    private static var grokBotClientVersion: String {
        let candidates = [
            "/Applications/Grok Bot.app/Contents/Info.plist",
            FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent("Applications/Grok Bot.app/Contents/Info.plist").path,
        ]
        for path in candidates {
            guard let info = NSDictionary(contentsOfFile: path),
                  let version = info["CFBundleShortVersionString"] as? String,
                  version.range(of: #"^\d+\.\d+\.\d+$"#,
                                options: .regularExpression) != nil else { continue }
            return version
        }
        return "0.30.0"
    }

    private static func deriveElectronKey(_ password: Data) -> Data? {
        let salt = Data("saltysalt".utf8)
        let keyLength = kCCKeySizeAES128
        var key = Data(count: keyLength)
        let status = key.withUnsafeMutableBytes { keyBytes in
            password.withUnsafeBytes { passwordBytes in
                salt.withUnsafeBytes { saltBytes in
                    CCKeyDerivationPBKDF(
                        CCPBKDFAlgorithm(kCCPBKDF2),
                        passwordBytes.bindMemory(to: Int8.self).baseAddress,
                        password.count,
                        saltBytes.bindMemory(to: UInt8.self).baseAddress,
                        salt.count,
                        CCPseudoRandomAlgorithm(kCCPRFHmacAlgSHA1),
                        1003,
                        keyBytes.bindMemory(to: UInt8.self).baseAddress,
                        keyLength
                    )
                }
            }
        }
        return status == kCCSuccess ? key : nil
    }

    private static func jwtIdentity(_ token: String) -> (userID: String, expiresAt: Double)? {
        let tokenCharacters = CharacterSet(
            charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
        )
        guard token.count <= 32_768,
              token.unicodeScalars.allSatisfy(tokenCharacters.contains) else { return nil }
        let components = token.split(separator: ".", omittingEmptySubsequences: false)
        guard components.count >= 2,
              let payload = base64URLData(String(components[1])),
              let claims = try? JSONSerialization.jsonObject(with: payload) as? [String: Any],
              let subject = claims["sub"] as? String,
              let expiresAt = (claims["exp"] as? NSNumber)?.doubleValue else { return nil }
        let userID = subject.split(separator: "|").last.map(String.init) ?? ""
        let valid = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")
        guard !userID.isEmpty, userID.unicodeScalars.allSatisfy(valid.contains) else { return nil }
        return (userID, expiresAt)
    }

    private static func base64URLData(_ value: String) -> Data? {
        var normalized = value.replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        let remainder = normalized.count % 4
        if remainder != 0 { normalized += String(repeating: "=", count: 4 - remainder) }
        return Data(base64Encoded: normalized)
    }

    private static let uiFailPolicy: String = {
        let path = "/System/Library/Frameworks/Security.framework/Security"
        guard let handle = dlopen(path, RTLD_NOW) else { return "u_AuthUIF" }
        defer { dlclose(handle) }
        guard let symbol = dlsym(handle, "kSecUseAuthenticationUIFail") else {
            return "u_AuthUIF"
        }
        return symbol.assumingMemoryBound(to: CFString?.self).pointee as String?
            ?? "u_AuthUIF"
    }()

    private static var authorizationMarkerURL: URL {
        if let configured = ProcessInfo.processInfo.environment["TOKEI_GROK_BOT_AUTH_MARKER"],
           !configured.isEmpty {
            return URL(fileURLWithPath: NSString(string: configured).expandingTildeInPath)
        }
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".tokei/grok_bot_keychain_authorized")
    }

    private static func updateAuthorizationMarker(enabled: Bool) {
        let url = authorizationMarkerURL
        if !enabled {
            try? FileManager.default.removeItem(at: url)
            return
        }
        do {
            try FileManager.default.createDirectory(
                at: url.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try String(Int(Date().timeIntervalSince1970)).write(
                to: url,
                atomically: true,
                encoding: .utf8
            )
            try FileManager.default.setAttributes(
                [.posixPermissions: 0o600],
                ofItemAtPath: url.path
            )
        } catch {
            try? FileManager.default.removeItem(at: url)
        }
    }
}
