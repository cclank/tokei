import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DevinUsageModelTests(unittest.TestCase):
    def test_devin_stat_decodes_tokens_and_quota_independently(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "devin-usage-model-check"
            result = subprocess.run(
                [
                    "swiftc",
                    "-parse-as-library",
                    str(ROOT / "Tokei/Sources/Tokei/Model.swift"),
                    str(ROOT / "Tokei/Sources/Tokei/L10n.swift"),
                    str(ROOT / "tests/swift/DevinUsageModelCheck.swift"),
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
            self.assertIn("devin usage model checks passed", result.stdout)

    def test_the_two_devin_sources_stay_separate_in_the_model(self):
        """CLI 的 token 和桌面端的额度是两个互不相干的库，模型上也不能互相兜底。"""
        source = (ROOT / "Tokei/Sources/Tokei/Model.swift").read_text()
        start = source.index("struct DevinStat")
        body = source[start:source.index("struct Usage", start)]

        self.assertIn("forKey: .ranges", body)
        self.assertIn("forKey: .quota", body)
        # 任何一半缺席都解码成空，而不是拿另一半顶上
        self.assertNotIn("quota.ranges", body)


if __name__ == "__main__":
    unittest.main()
