import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANEL_FILES = [
    "PanelView.swift",
    "DashboardView.swift",
    "ProjectTrailView.swift",
    "QuotaHistoryView.swift",
    "Design.swift",
    "WrappedView.swift",
]


class PanelTypographyTests(unittest.TestCase):
    def test_two_bounded_font_sizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "panel-typography-check"
            subprocess.run(
                [
                    "swiftc",
                    "-parse-as-library",
                    "-module-cache-path", str(Path(tmp) / "module-cache"),
                    str(ROOT / "Tokei/Sources/Tokei/PanelTypography.swift"),
                    str(ROOT / "tests/swift/PanelTypographyCheck.swift"),
                    "-o", str(binary),
                ],
                check=True,
                cwd=ROOT,
            )
            result = subprocess.run(
                [str(binary)], check=True, capture_output=True, text=True
            )
            self.assertIn("panel typography checks passed", result.stdout)

    def test_panel_numeric_fonts_use_the_shared_scale(self):
        raw_font = re.compile(r"\.font\(\.system\(size:\s*[0-9]")
        violations = []
        source_dir = ROOT / "Tokei/Sources/Tokei"
        for name in PANEL_FILES:
            for line_number, line in enumerate(
                (source_dir / name).read_text().splitlines(), start=1
            ):
                if raw_font.search(line):
                    violations.append(f"{name}:{line_number}")
        self.assertEqual([], violations, "unscaled panel fonts: " + ", ".join(violations))

    def test_setting_is_persistent_and_defaults_to_small(self):
        source = (ROOT / "Tokei/Sources/Tokei/PanelView.swift").read_text()
        self.assertIn("@AppStorage(PanelFontSize.defaultsKey)", source)
        self.assertIn("PanelFontSize.small.rawValue", source)
        self.assertIn('Picker("字体大小"', source)


if __name__ == "__main__":
    unittest.main()
