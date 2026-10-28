import Foundation

@main struct GrokBotRealKeychainResolver {
    static func main() {
        guard GrokBotHelperManager.runIfRequested() else { exit(64) }
    }
}
