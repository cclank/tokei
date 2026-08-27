import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOKEI_SRC = ROOT / "Tokei" / "Sources" / "Tokei"


class MenuBarQuotaSourceTests(unittest.TestCase):
    def test_codex_5h_source_is_opt_in_and_does_not_disturb_weekly(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "menu-bar-quota-check"
            subprocess.run(
                [
                    "swiftc",
                    "-parse-as-library",
                    # 输出名带连字符时 swiftc 推导出的 module 名非法，产物一跑就 SIGKILL。
                    "-module-name",
                    "MenuBarQuotaCheck",
                    str(TOKEI_SRC / "Model.swift"),
                    str(TOKEI_SRC / "Design.swift"),
                    str(TOKEI_SRC / "MenuBarStyle.swift"),
                    str(ROOT / "tests/swift/MenuBarQuotaSourceCheck.swift"),
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
            self.assertIn("menu bar quota source checks passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
