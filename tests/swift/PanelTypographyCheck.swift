import Foundation

private enum TestFailure: Error {
    case assertion(String)
}

@main
struct PanelTypographyCheck {
    static func main() throws {
        let suiteName = "com.tokei.tests.typography.\(UUID().uuidString)"
        guard let defaults = UserDefaults(suiteName: suiteName) else {
            throw TestFailure.assertion("could not create isolated defaults")
        }
        defer { defaults.removePersistentDomain(forName: suiteName) }

        try expect(PanelFontSize.small.scale == 1, "small should preserve current sizes")
        try expect(PanelFontSize.large.scale == 1.12, "large should use the bounded scale")
        try expect(PanelFontSize.large.label == "大", "large should have a user-facing label")
        try expect(PanelFontSize.allCases == [.small, .large], "only two sizes should be exposed")

        print("panel typography checks passed")
    }

    private static func expect(_ condition: @autoclosure () -> Bool,
                               _ message: String) throws {
        if !condition() {
            throw TestFailure.assertion(message)
        }
    }
}
