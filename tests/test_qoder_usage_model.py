import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class QoderUsageModelTests(unittest.TestCase):
    def test_qoder_harness_models_keep_exact_usage_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "qoder-usage-model-check"
            result = subprocess.run(
                [
                    "swiftc",
                    "-parse-as-library",
                    str(ROOT / "Tokei/Sources/Tokei/Model.swift"),
                    str(ROOT / "Tokei/Sources/Tokei/L10n.swift"),
                    str(ROOT / "tests/swift/QoderUsageModelCheck.swift"),
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
            self.assertIn("qoder usage model checks passed", result.stdout)

    def test_usage_decoder_does_not_fallback_qoderwork_to_qoder(self):
        source = (ROOT / "Tokei/Sources/Tokei/Model.swift").read_text()
        start = source.index("qoderwork =")
        end = source.index("qoder =", start)
        qoderwork_decode = source[start:end]

        self.assertIn("forKey: .qoderwork", qoderwork_decode)
        self.assertNotIn("forKey: .qoder)", qoderwork_decode)

    def test_qoder_cards_use_only_their_selected_ranges(self):
        source = (ROOT / "Tokei/Sources/Tokei/PanelView.swift").read_text()
        cards_start = source.index("private func toolCards(for u: Usage)")
        cards_end = source.index("private func toolCardsLayout", cards_start)
        cards = source[cards_start:cards_end]

        self.assertIn("active: qr.calls > 0 || qr.in + qr.cached + qr.out > 0", cards)
        self.assertIn("active: qwr.calls > 0 || qwr.totalTokens > 0", cards)
        self.assertIn("active: qclir.calls > 0 || qclir.totalTokens > 0", cards)

        work_start = source.index("func qoderworkBlock")
        cli_start = source.index("func qodercliBlock", work_start)
        work_block = source[work_start:cli_start]
        cli_end = source.index("// MARK:", cli_start + 20)
        cli_block = source[cli_start:cli_end]

        self.assertIn("Fmt.human(r.totalTokens)", work_block)
        self.assertIn("Fmt.human(r.totalTokens)", cli_block)
        self.assertIn("L10n.metricCacheRead", cli_block)
        self.assertIn("L10n.metricCacheWrite", cli_block)
        self.assertIn('"Credits"', cli_block)

    def test_qoder_cli_summary_and_sync_use_cli_exact_tokens(self):
        summary = (ROOT / "Tokei/Sources/Tokei/UsageSummaryBuilder.swift").read_text()
        cli_start = summary.index('id: "qodercli"')
        cli_end = summary.index("if !line.isEmpty", cli_start)
        cli_line = summary[cli_start:cli_end]
        self.assertIn("tokens: r.totalTokens", cli_line)
        self.assertIn("input: r.in", cli_line)
        self.assertIn("cacheRead: r.cr", cli_line)
        self.assertIn("cacheWrite: r.cw", cli_line)

        sync = (ROOT / "Tokei/Sources/Tokei/SyncManager.swift").read_text()
        self.assertIn(
            "mergeRanges(&u.qodercli.ranges, peer.usage.qodercli.ranges, pairs)",
            sync,
        )
        merge_start = sync.index("private static func mergeRanges(_ dst: inout QoderRanges")
        merge_end = sync.index("private static func mergeRanges(_ dst: inout QoderIdeRanges", merge_start)
        merge = sync[merge_start:merge_end]
        self.assertIn("d.cr += s.cr", merge)
        self.assertIn("d.cw += s.cw", merge)
        self.assertIn("d.credits += s.credits", merge)

    def test_qoder_cli_exact_tokens_reach_dashboard_and_menu_bar(self):
        dashboard = (ROOT / "Tokei/Sources/Tokei/DashboardView.swift").read_text()
        self.assertIn("let qodercli = usage.qodercli.ranges.get(key)", dashboard)
        self.assertIn("+ qodercli.totalTokens", dashboard)
        self.assertIn('tool: "qodercli"', dashboard)

        main = (ROOT / "Tokei/Sources/Tokei/main.swift").read_text()
        self.assertIn("showQoderCli", main)
        self.assertIn("u.qodercli.ranges.get(.today)", main)
        self.assertIn("total += r.totalTokens", main)


if __name__ == "__main__":
    unittest.main()
