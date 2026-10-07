import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from test_codex_limits import USAGE


class PiOmpUsageTests(unittest.TestCase):
    def test_omp_sessions_reasoning_and_authoritative_cost_are_collected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".omp" / "agent" / "sessions"
            session = root / "project" / "session.jsonl"
            session.parent.mkdir(parents=True)
            timestamp = datetime.now().astimezone().replace(microsecond=0).isoformat()
            records = [
                {"type": "session", "id": "omp-session", "cwd": "/tmp/omp-project"},
                {
                    "type": "message",
                    "timestamp": timestamp,
                    "message": {
                        "role": "assistant",
                        "provider": "openai",
                        "model": "gpt-5.5",
                        "usage": {
                            "input": 100,
                            "output": 20,
                            "cacheRead": 30,
                            "cacheWrite": 4,
                            "reasoningTokens": 5,
                            "cost": {"total": 0.42},
                        },
                    },
                },
            ]
            session.write_text("\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8")

            old_omp = USAGE.OMP_SESSION_DIR
            old_pi = USAGE.PI_SESSION_DIR
            old_agent = USAGE.PI_AGENT_DIR
            USAGE.OMP_SESSION_DIR = str(root)
            USAGE.PI_SESSION_DIR = str(Path(tmp) / "missing-pi")
            USAGE.PI_AGENT_DIR = str(Path(tmp) / "missing-agent")
            try:
                cache = {"v": USAGE._SCAN_CACHE_VERSION}
                result = USAGE.scan_pi(USAGE.range_bounds(), cache)
            finally:
                USAGE.OMP_SESSION_DIR = old_omp
                USAGE.PI_SESSION_DIR = old_pi
                USAGE.PI_AGENT_DIR = old_agent

        usage = result["ranges"]["all"]
        self.assertEqual(usage["in"], 100)
        self.assertEqual(usage["out"], 20)
        self.assertEqual(usage["cr"], 30)
        self.assertEqual(usage["cw"], 4)
        self.assertEqual(usage["reason"], 5)
        self.assertEqual(USAGE.token_total(usage), 159)
        self.assertEqual(usage["sessions"], {"omp-session"})
        self.assertAlmostEqual(usage["cost"], 0.42)
        self.assertTrue(cache["_dirty"])
        self.assertEqual(len(cache["pi"]), 1)

    def test_response_model_wins_over_a_routing_group_request(self):
        # 经网关选路由组时 message.model 是 group/<id>，它不是一个模型；
        # 回包里的 responseModel 才是真正作答的成员。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".pi" / "agent" / "sessions"
            session = root / "project" / "session.jsonl"
            session.parent.mkdir(parents=True)
            timestamp = datetime.now().astimezone().replace(microsecond=0).isoformat()
            records = [
                {"type": "session", "id": "pi-session", "cwd": "/tmp/pi-project"},
                {"type": "model_change", "modelId": "group/auto-glm-5-3-flash"},
                {
                    "type": "message",
                    "timestamp": timestamp,
                    "message": {
                        "role": "assistant",
                        "provider": "magpie",
                        "model": "group/auto-glm-5-3-flash",
                        "responseModel": "zcode/GLM-5.3-Flash",
                        "usage": {"input": 100, "output": 20},
                    },
                },
            ]
            session.write_text("\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8")

            old_omp = USAGE.OMP_SESSION_DIR
            old_pi = USAGE.PI_SESSION_DIR
            old_agent = USAGE.PI_AGENT_DIR
            USAGE.OMP_SESSION_DIR = str(Path(tmp) / "missing-omp")
            USAGE.PI_SESSION_DIR = str(root)
            USAGE.PI_AGENT_DIR = str(Path(tmp) / "missing-agent")
            try:
                result = USAGE.scan_pi(USAGE.range_bounds(), {"v": USAGE._SCAN_CACHE_VERSION})
            finally:
                USAGE.OMP_SESSION_DIR = old_omp
                USAGE.PI_SESSION_DIR = old_pi
                USAGE.PI_AGENT_DIR = old_agent

        models = result["ranges"]["all"]["models"]
        self.assertEqual(list(models), ["zcode/GLM-5.3-Flash"])
        self.assertEqual(models["zcode/GLM-5.3-Flash"]["in"], 100)

    def test_placeholder_response_model_falls_back_to_the_request(self):
        # 厂商把真实名报成 auto 时，不能说这个模型叫 Auto。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".pi" / "agent" / "sessions"
            session = root / "project" / "session.jsonl"
            session.parent.mkdir(parents=True)
            timestamp = datetime.now().astimezone().replace(microsecond=0).isoformat()
            records = [
                {"type": "session", "id": "pi-session", "cwd": "/tmp/pi-project"},
                {
                    "type": "message",
                    "timestamp": timestamp,
                    "message": {
                        "role": "assistant",
                        "provider": "qoder",
                        "model": "Qwen3.8-Flash",
                        "responseModel": "auto",
                        "usage": {"input": 100, "output": 20},
                    },
                },
            ]
            session.write_text("\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8")

            old_omp = USAGE.OMP_SESSION_DIR
            old_pi = USAGE.PI_SESSION_DIR
            old_agent = USAGE.PI_AGENT_DIR
            USAGE.OMP_SESSION_DIR = str(Path(tmp) / "missing-omp")
            USAGE.PI_SESSION_DIR = str(root)
            USAGE.PI_AGENT_DIR = str(Path(tmp) / "missing-agent")
            try:
                result = USAGE.scan_pi(USAGE.range_bounds(), {"v": USAGE._SCAN_CACHE_VERSION})
            finally:
                USAGE.OMP_SESSION_DIR = old_omp
                USAGE.PI_SESSION_DIR = old_pi
                USAGE.PI_AGENT_DIR = old_agent

        models = result["ranges"]["all"]["models"]
        self.assertEqual(list(models), ["qoder/Qwen3.8-Flash"])

    def test_resolved_duplicate_roots_and_first_present_reasoning_are_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            real_root = Path(tmp) / "sessions"
            alias_root = Path(tmp) / "alias"
            real_root.mkdir()
            os.symlink(real_root, alias_root)
            old_omp = USAGE.OMP_SESSION_DIR
            old_pi = USAGE.PI_SESSION_DIR
            old_agent = USAGE.PI_AGENT_DIR
            USAGE.OMP_SESSION_DIR = str(real_root)
            USAGE.PI_SESSION_DIR = str(alias_root)
            USAGE.PI_AGENT_DIR = str(Path(tmp) / "missing")
            try:
                self.assertEqual(USAGE._pi_session_dirs(), [str(real_root.resolve()), str((Path(tmp) / "missing" / "sessions").resolve()), str((Path(USAGE.HOME) / ".pi" / "agent" / "sessions").resolve())])
                self.assertEqual(USAGE._pi_usage_int({"reasoning": 0, "reasoningTokens": 9}, "reasoning", "reasoningTokens"), 0)
            finally:
                USAGE.OMP_SESSION_DIR = old_omp
                USAGE.PI_SESSION_DIR = old_pi
                USAGE.PI_AGENT_DIR = old_agent


if __name__ == "__main__":
    unittest.main()
