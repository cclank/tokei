// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "Tokei",
    defaultLocalization: "en",
    platforms: [.macOS(.v13)],
    targets: [
        .target(
            name: "CZstd",
            path: "Sources/CZstd",
            publicHeadersPath: "include",
            cSettings: [
                .headerSearchPath("."),
                .define("ZSTD_DISABLE_ASM"),
            ]
        ),
        .target(
            name: "TokeiUpdateSecurity",
            path: "Sources/TokeiUpdateSecurity"
        ),
        .target(
            name: "GrokBotBridge",
            path: "Sources/GrokBotBridge"
        ),
        .executableTarget(
            name: "TokeiGrokBotHelper",
            dependencies: ["GrokBotBridge"],
            path: "Sources/TokeiGrokBotHelper"
        ),
        .executableTarget(
            name: "Tokei",
            dependencies: ["CZstd", "TokeiUpdateSecurity", "GrokBotBridge"],
            path: "Sources/Tokei",
            resources: [.process("Resources")]
        )
    ]
)
