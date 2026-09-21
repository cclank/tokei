import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class UpdaterSecurityTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "darwin", "Tokei updater is macOS-only")
    def test_swift_security_policy(self):
        swiftc = shutil.which("swiftc")
        self.assertIsNotNone(swiftc, "swiftc is required")

        root = Path(__file__).resolve().parents[1]
        policy = root / "Tokei" / "Sources" / "TokeiUpdateSecurity" / "UpdateSecurity.swift"
        harness = root / "tests" / "swift" / "UpdaterSecurityCheck.swift"

        with tempfile.TemporaryDirectory(prefix="tokei-updater-test-") as temp_dir:
            binary = Path(temp_dir) / "updater-security-check"
            compile_result = subprocess.run(
                [swiftc, str(policy), str(harness), "-o", str(binary)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(
                compile_result.returncode,
                0,
                compile_result.stdout + compile_result.stderr,
            )

            run_result = subprocess.run(
                [str(binary)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(
                run_result.returncode,
                0,
                run_result.stdout + run_result.stderr,
            )
            self.assertIn("Updater security checks passed", run_result.stdout)

    def test_release_metadata_includes_dmg_sha256(self):
        root = Path(__file__).resolve().parents[1]
        generator = root / "Tokei" / "generate_update_metadata.sh"

        with tempfile.TemporaryDirectory(prefix="tokei-metadata-test-") as temp_dir:
            dmg = Path(temp_dir) / "Tokei.dmg"
            output = Path(temp_dir) / "latest.json"
            dmg.write_bytes(b"test-dmg")

            result = subprocess.run(
                ["/bin/bash", str(generator), "v1.0.14", str(dmg), str(output)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            metadata = json.loads(output.read_text())
            self.assertEqual(metadata["tag_name"], "v1.0.14")
            self.assertEqual(
                metadata["download_url"],
                "https://dl.lanshuagent.com/tokei/Tokei-v1.0.14.dmg",
            )
            self.assertEqual(metadata["sha256"], hashlib.sha256(b"test-dmg").hexdigest())

    def test_settings_page_exposes_explicit_update_actions_for_every_state(self):
        panel = (
            Path(__file__).resolve().parents[1]
            / "Tokei" / "Sources" / "Tokei" / "PanelView.swift"
        ).read_text(encoding="utf-8")

        self.assertIn("settingsUpdateSection", panel)
        start = panel.index("var settingsUpdateSection: some View")
        end = panel.index("var settingsSystemSection: some View", start)
        section = panel[start:end]

        self.assertIn('settingsSection("arrow.triangle.2.circlepath", "版本与更新")', section)
        self.assertIn(r'Text("当前版本 \(Updater.releaseTag)")', section)
        self.assertIn('case .idle:', section)
        self.assertIn('title: "检查更新"', section)
        self.assertIn('updater.checkForUpdate()', section)
        self.assertIn('case .checking:', section)
        self.assertIn('Text("正在检查")', section)
        self.assertIn('case .upToDate:', section)
        self.assertIn('"已是最新版本"', section)
        self.assertIn('case .available(let tag, _, _):', section)
        self.assertIn(r'title: "升级到 \(tag)"', section)
        self.assertIn('updater.performUpdate()', section)
        self.assertIn('case .downloading(let progress):', section)
        self.assertIn(r'Text("下载中 \(Int(progress * 100))%")', section)
        self.assertIn('case .installing:', section)
        self.assertIn('Text("正在安装")', section)
        self.assertIn('case .failed(let message):', section)
        self.assertIn('title: "重试"', section)
        self.assertIn('Text(message)', section)

        main = (
            Path(__file__).resolve().parents[1]
            / "Tokei" / "Sources" / "Tokei" / "main.swift"
        ).read_text(encoding="utf-8")
        self.assertGreaterEqual(main.count("Updater.shared.checkForUpdate()"), 2)
        self.assertIn(
            "Timer.scheduledTimer(withTimeInterval: Updater.automaticCheckInterval",
            main,
        )


if __name__ == "__main__":
    unittest.main()
