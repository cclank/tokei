"""端到端冒烟：在干净的临时 HOME 里以子进程跑采集脚本的每个入口。

这是 Windows 版的底线检查（CI 在 windows-latest 上跑同一份）：脚本能启动、能写账本和
缓存（文件锁）、stdout 按 UTF-8 输出中文、读得了带中文的 config.json 和同步快照，
Windows 风格的工作目录（C:\\…）也能归到项目上。macOS / Linux 上跑同样有效。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "usage.30s.py"
PROJECT = "C:\\Users\\dev\\演示项目"


def _claude_records(now):
    records = []
    for i, (inp, out, cr, cw) in enumerate(((1200, 300, 40_000, 2_000), (800, 150, 42_000, 0))):
        stamp = (now - timedelta(minutes=10 - i)).isoformat()
        records.append({
            "type": "user", "timestamp": stamp, "uuid": f"u{i}", "parentUuid": None,
            "cwd": PROJECT, "message": {"role": "user", "content": "帮我看看这个函数 ⚡"},
        })
        records.append({
            "type": "assistant", "timestamp": stamp, "uuid": f"a{i}", "parentUuid": f"u{i}",
            "requestId": f"req-{i}", "isSidechain": False, "cwd": PROJECT,
            "message": {
                "id": f"msg-{i}", "model": "claude-opus-5-5",
                "usage": {"input_tokens": inp, "output_tokens": out,
                          "cache_read_input_tokens": cr, "cache_creation_input_tokens": cw},
            },
        })
    return records


def _codex_lines(now):
    def event(minutes, kind, payload):
        return json.dumps({"timestamp": (now - timedelta(minutes=minutes)).isoformat(),
                           "type": kind, "payload": payload}, ensure_ascii=False)

    def usage(total):
        inp, cached, out, reasoning = total
        return {"input_tokens": inp, "cached_input_tokens": cached,
                "output_tokens": out, "reasoning_output_tokens": reasoning}

    return [
        event(20, "session_meta", {"id": "smoke-session", "cwd": PROJECT, "originator": "codex_cli_rs"}),
        event(19, "turn_context", {"model": "gpt-6-sol", "cwd": PROJECT}),
        event(18, "event_msg", {"type": "token_count", "info": {
            "total_token_usage": usage((5000, 4000, 600, 100)),
            "last_token_usage": usage((5000, 4000, 600, 100))}}),
        event(17, "event_msg", {"type": "token_count", "info": {
            "total_token_usage": usage((9000, 7000, 900, 150)),
            "last_token_usage": usage((4000, 3000, 300, 50))}}),
    ]


class CrossPlatformSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="tokei-smoke-")
        home = Path(cls._tmp.name)
        cls.home = home
        now = datetime.now().astimezone()

        claude = home / ".claude" / "projects" / "C--Users-dev-demo" / "smoke.jsonl"
        claude.parent.mkdir(parents=True)
        claude.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in _claude_records(now)) + "\n",
                          encoding="utf-8")

        day = now.strftime("%Y/%m/%d").split("/")
        codex = home / ".codex" / "sessions" / day[0] / day[1] / day[2] / "rollout-smoke.jsonl"
        codex.parent.mkdir(parents=True)
        codex.write_text("\n".join(_codex_lines(now)) + "\n", encoding="utf-8")

        cls.sync_dir = home / "sync"
        cls.sync_dir.mkdir()
        tokei = home / ".tokei"
        tokei.mkdir()
        (tokei / "config.json").write_text(json.dumps({
            "device_id": "smoke-pc", "sync_dir": str(cls.sync_dir),
            "auto_sync": False, "note": "中文配置",
        }, ensure_ascii=False), encoding="utf-8")

        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("TOKEI_", "CODEX_", "CLAUDE_", "GROK_"))}
        env.update({
            "HOME": str(home), "USERPROFILE": str(home),
            "APPDATA": str(home / "AppData" / "Roaming"),
            "LOCALAPPDATA": str(home / "AppData" / "Local"),
        })
        # 故意不设 PYTHONIOENCODING / PYTHONUTF8：Windows 上要靠脚本自己把 stdout 切到 UTF-8。
        env.pop("PYTHONIOENCODING", None)
        env.pop("PYTHONUTF8", None)
        cls.env = env

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_script(self, *args):
        result = subprocess.run([sys.executable, str(SCRIPT), *args], env=self.env,
                                capture_output=True, timeout=180)
        stderr = result.stderr.decode("utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, f"{args} failed:\n{stderr[-3000:]}")
        return result.stdout.decode("utf-8")

    def test_json_counts_tokens_writes_sync_snapshot_and_survives_a_second_run(self):
        for attempt in range(2):  # 第二轮走缓存、账本合并与文件锁
            payload = json.loads(self.run_script("--json"))
            claude = payload["claude"]["ranges"]["today"]
            self.assertEqual(claude["in"], 2000, f"run {attempt + 1}")
            self.assertEqual(claude["out"], 450)
            self.assertEqual(claude["cr"], 82_000)
            self.assertEqual(claude["cw"], 2_000)
            self.assertEqual([m["name"] for m in claude["models"]], ["Opus 5.5"])
            codex = payload["codex"]["ranges"]["today"]
            self.assertEqual((codex["in"], codex["cached"], codex["out"]), (2000, 7000, 900))
            self.assertEqual([m["name"] for m in codex["models"]], ["GPT-6 Sol"])

        snapshot = self.sync_dir / "smoke-pc.json"
        self.assertTrue(snapshot.is_file(), "同步快照没写出来")
        json.loads(snapshot.read_text(encoding="utf-8"))
        self.assertTrue((self.home / ".tokei" / "ledger.json").is_file(), "账本没落盘")

    def test_projects_keep_windows_style_working_directories(self):
        projects = self.run_script("--projects")
        self.assertIn("演示项目", projects, "C:\\ 开头的工作目录被当成非绝对路径过滤掉了")

    def test_every_other_entry_point_runs(self):
        for args in (("--dashboard",), ("--daily-costs",), ("--wrapped",), ("--quota-detail",)):
            with self.subTest(args=args):
                json.loads(self.run_script(*args))
        self.assertTrue(self.run_script().strip(), "SwiftBar 文本输出为空")


if __name__ == "__main__":
    unittest.main()
