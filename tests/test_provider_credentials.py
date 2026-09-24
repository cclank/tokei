import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProviderCredentialStoreTests(unittest.TestCase):
    def test_legacy_keychain_round_trip_is_noninteractive(self):
        swiftc = shutil.which("swiftc")
        if swiftc is None:
            self.skipTest("swiftc is required")

        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "provider-credential-store-check"
            result = subprocess.run(
                [
                    swiftc,
                    "-parse-as-library",
                    "-D",
                    "TOKEI_PROVIDER_CREDENTIAL_STORE_TEST",
                    str(ROOT / "Tokei/Sources/Tokei/ProviderCredentialStore.swift"),
                    str(ROOT / "Tokei/Sources/Tokei/L10n.swift"),
                    str(ROOT / "tests/swift/ProviderCredentialStoreCheck.swift"),
                    "-o",
                    str(binary),
                ],
                capture_output=True,
                text=True,
                cwd=ROOT,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("provider credential keychain checks passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
