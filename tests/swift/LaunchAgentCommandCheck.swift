import Foundation

@main
struct LaunchAgentCommandCheck {
    static func main() {
        let result = LaunchAgentLoginItemService.runCommand(
            executableURL: URL(fileURLWithPath: "/usr/bin/awk"),
            arguments: [#"BEGIN { for (i = 0; i < 65536; i++) printf "0123456789abcdef"; exit 7 }"#]
        )
        precondition(result.status == 7, "child exit status must be retained")
        precondition(result.output.utf8.count == 1048576, "large output must be fully drained")
        let error = LaunchAgentLoginItemService.runCommand(
            executableURL: URL(fileURLWithPath: "/bin/sh"),
            arguments: ["-c", "printf error-message >&2; exit 3"]
        )
        precondition(error.status == 3 && error.output == "error-message", "stderr must be captured")
        let empty = LaunchAgentLoginItemService.runCommand(
            executableURL: URL(fileURLWithPath: "/usr/bin/true"), arguments: []
        )
        precondition(empty.status == 0 && empty.output.isEmpty, "empty output must complete")
        print("launch agent command checks passed")
    }
}
