import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ClaudeCLIQuotaBridgeTests(unittest.TestCase):
    def test_bridge_cache_and_failure_behavior(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "claude-cli-quota-bridge-check"
            subprocess.run(
                [
                    "swiftc",
                    "-parse-as-library",
                    str(ROOT / "Tokei/Sources/Tokei/ClaudeCLIQuotaBridge.swift"),
                    str(ROOT / "Tokei/Sources/Tokei/L10n.swift"),
                    str(ROOT / "tests/swift/ClaudeCLIQuotaBridgeCheck.swift"),
                    "-o",
                    str(binary),
                ],
                check=True,
                cwd=ROOT,
            )
            result = subprocess.run(
                [str(binary)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("claude cli quota bridge checks passed", result.stdout)

    def test_bridge_uses_fixed_anthropic_endpoint_and_rejects_redirects(self):
        source = (ROOT / "Tokei/Sources/Tokei/ClaudeCLIQuotaBridge.swift").read_text()
        self.assertIn("https://api.anthropic.com/api/oauth/usage", source)
        self.assertIn("completionHandler(nil)", source)
        self.assertIn('response.url?.host?.lowercased() == "api.anthropic.com"', source)
        self.assertIn('betaHeader = "oauth-2025-04-20"', source)
        self.assertIn('"claude-code/\\(version)"', source)
        self.assertIn('response.statusCode == 429', source)
        self.assertIn('value(forHTTPHeaderField: "Retry-After")', source)
        self.assertNotIn("refreshToken", source)


if __name__ == "__main__":
    unittest.main()
