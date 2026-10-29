import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "Tokei" / "Sources" / "Tokei"


class DoubaoWorkModelTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("swiftc"), "Swift/AppKit requires macOS")
    def test_decode_sync_deduplication_and_native_share(self):
        with tempfile.TemporaryDirectory(prefix="tokei-doubao-native-") as tmp:
            binary = Path(tmp) / "check"
            sources = [SRC / name for name in (
                "Model.swift", "L10n.swift", "Design.swift", "PanelTypography.swift",
                "UsageSummaryBuilder.swift", "UsageShareImage.swift", "UsageCardOrdering.swift", "SyncManager.swift",
            )]
            sources.append(ROOT / "tests" / "swift" / "DoubaoWorkCheck.swift")
            subprocess.run(["swiftc", "-parse-as-library", "-j", "1", "-module-cache-path", str(Path(tmp) / "modules"),
                            *map(str, sources), "-o", str(binary)], cwd=ROOT, check=True,
                           capture_output=True, text=True, timeout=180)
            image = Path(tmp) / "card.png"
            result = subprocess.run([str(binary), str(image)], cwd=ROOT, check=True,
                                    capture_output=True, text=True, timeout=30)
            self.assertIn("Doubao Work decoding, sync union, zero-period sharing and native PNG checks passed", result.stdout)
            self.assertEqual(image.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
