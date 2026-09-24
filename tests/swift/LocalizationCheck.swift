import Foundation

private enum TestFailure: Error {
    case assertion(String)
}

@main
struct LocalizationCheck {
    static func main() throws {
        try expect(AppLanguage.allCases.map(\.rawValue).sorted() == ["en", "fr", "ja", "ko", "system", "zh"],
                   "AppLanguage must offer system/en/zh/fr/ja/ko for extensibility")
        // system 跟随首选语言，未知语言回退英文。
        try expect(AppLanguage.system.collectorCode.count == 2, "system must resolve to a code")
        try expect(AppLanguage(rawValue: "xx") == nil, "unknown raw value must not parse")
        try expect(AppLanguage.en.resolvedLocale.identifier == "en", "en must resolve")
        try expect(AppLanguage.fr.resolvedLocale.identifier == "fr", "fr must resolve")
        try expect(AppLanguage.ja.resolvedLocale.identifier == "ja", "ja must resolve")
        try expect(AppLanguage.ko.resolvedLocale.identifier == "ko", "ko must resolve")

        print("localization checks passed")
    }

    private static func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
        if !condition() {
            throw TestFailure.assertion(message)
        }
    }
}
