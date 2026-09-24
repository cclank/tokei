import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LocalizationTests(unittest.TestCase):
    def test_swift_localization_check(self):
        binary = Path(__file__).resolve().parent / ".localization-check"
        sources = [
            str(ROOT / "Tokei/Sources/Tokei/L10n.swift"),
            str(ROOT / "tests/swift/LocalizationCheck.swift"),
        ]
        subprocess.run(
            ["swiftc", "-parse-as-library", "-framework", "Foundation"]
            + sources + ["-o", str(binary)],
            check=True,
            cwd=ROOT,
        )
        try:
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
        finally:
            binary.unlink(missing_ok=True)
        self.assertIn("localization checks passed", result.stdout)

    def test_strings_files_cover_all_keys(self):
        keys = set()
        for path in (ROOT / "Tokei/Sources/Tokei").rglob("*.swift"):
            if path.name == "L10n.swift":
                continue
            for match in re.finditer(r'L10n\.(?:t|f)\("([^"]+)"', path.read_text(encoding="utf-8")):
                keys.add(match.group(1))
        # L10n.swift 具名 accessor 也要有对应 key。
        l10n_src = (ROOT / "Tokei/Sources/Tokei/L10n.swift").read_text(encoding="utf-8")
        for match in re.finditer(r's\("([^"]+)"\)', l10n_src):
            keys.add(match.group(1))
        self.assertGreater(len(keys), 600, "should track 600+ keys")
        for lang in ("en", "zh", "fr", "ja", "ko"):
            strings = (ROOT / f"Tokei/Sources/Tokei/Resources/{lang}.lproj/Localizable.strings").read_text(
                encoding="utf-8")
            missing = [key for key in keys if f'"{key}"' not in strings]
            self.assertEqual(missing, [], f"{lang}.lproj missing keys: {missing[:5]}")

    def test_no_hardcoded_cjk_outside_l10n(self):
        offenders = []
        for path in (ROOT / "Tokei/Sources/Tokei").rglob("*.swift"):
            if path.name in ("L10n.swift",):
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
                stripped = line.strip()
                if stripped.startswith("//"):
                    continue
                for match in re.finditer(r'"([^"\n]*[\u4e00-\u9fff][^"\n]*)"', line):
                    offenders.append(f"{path.name}:{lineno}:{match.group(1)[:30]}")
        self.assertEqual(offenders, [], f"hardcoded CJK remains: {offenders[:10]}")

    def test_collector_language_table(self):
        spec_code = (
            "import importlib.util\n"
            "from pathlib import Path\n"
            "spec = importlib.util.spec_from_file_location('tokei_usage', Path('usage.30s.py'))\n"
            "u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)\n"
            "import json, os\n"
            "for lang in ('zh', 'en', 'fr', 'ja', 'ko'):\n"
            "    os.environ['TOKEI_LANG'] = lang\n"
            "    print(lang, u._T('plan_usage'), u.nice_model('<synthetic>'))\n"
        )
        result = subprocess.run(["python3", "-c", spec_code], check=True, capture_output=True,
                                text=True, cwd=ROOT)
        self.assertIn("zh 套餐用量 合成", result.stdout)
        self.assertIn("en Plan Usage Synthetic", result.stdout)
        self.assertIn("fr Utilisation du forfait", result.stdout)
        self.assertIn("ja プラン使用量 合成", result.stdout)
        self.assertIn("ko 요금제 사용량 합성", result.stdout)


if __name__ == "__main__":
    unittest.main()
