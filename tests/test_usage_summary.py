import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOKEI_SRC = ROOT / "Tokei" / "Sources" / "Tokei"


class UsageSummaryBuilderTests(unittest.TestCase):
    def test_summary_builder_period_visibility_and_totals(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "usage-summary-check"
            subprocess.run(
                [
                    "swiftc",
                    "-parse-as-library",
                    str(TOKEI_SRC / "Model.swift"),
                    str(TOKEI_SRC / "Design.swift"),
                    str(TOKEI_SRC / "PanelTypography.swift"),
                    str(TOKEI_SRC / "UsageSummaryBuilder.swift"),
                    str(TOKEI_SRC / "UsageShareImage.swift"),
                    str(ROOT / "tests/swift/UsageSummaryBuilderCheck.swift"),
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
            self.assertIn("usage summary builder checks passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
