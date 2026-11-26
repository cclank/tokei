"""A refreshed native metric grid must match a fresh render of the same data."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "Tokei/Sources/Tokei"


def source_block(source, marker):
    """Compile the production renderer directly; do not maintain a test copy."""
    start = source.index(marker)
    opening = source.index("{", start)
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


@unittest.skipUnless(sys.platform == "darwin", "Native SwiftUI grid is macOS-only")
class MetricGridRefreshTests(unittest.TestCase):
    def test_updates_do_not_keep_old_metric_cells(self):
        panel = (SRC / "PanelView.swift").read_text(encoding="utf-8")
        design = (SRC / "Design.swift").read_text(encoding="utf-8")
        source = (ROOT / "tests/swift/MetricGridRefreshCheck.swift.in").read_text(encoding="utf-8")
        cells = source_block(design, "struct MetricCell: View")
        cells += "\n" + source_block(design, "struct RingMetricCell: View")
        cells += "\n" + source_block(design, "struct EqualHeightGrid: Layout")
        identity_marker = "private enum MetricGridCell: Identifiable"
        identity = source_block(panel, identity_marker) if identity_marker in panel else ""
        source = source.replace("/* PRODUCTION_CELLS */", cells)
        source = source.replace("/* PRODUCTION_METRIC */", source_block(panel, "struct Metric {"))
        source = source.replace("/* PRODUCTION_IDENTITY */", identity)
        source = source.replace("/* PRODUCTION_GRID */", "@ViewBuilder\n" + source_block(panel, "func metricGrid("))
        env = os.environ.copy()
        compatible_sdk = Path("/Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk")
        if "SDKROOT" not in env and compatible_sdk.is_dir():
            env["SDKROOT"] = str(compatible_sdk)
        with tempfile.TemporaryDirectory(prefix="tokei-grid-regression-") as tmp:
            directory = Path(tmp)
            swift = directory / "check.swift"
            binary = directory / "check"
            swift.write_text(source, encoding="utf-8")
            compiled = subprocess.run(["swiftc", str(swift), "-o", str(binary)],
                                      capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(binary), str(directory / "renders")],
                                    capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("native rendered updates: 40, failures: 0", result.stdout)


if __name__ == "__main__":
    unittest.main()
