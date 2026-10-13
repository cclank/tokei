"""The collector only invokes Windows integrations through their opt-in gates."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("windows_collector_integration", ROOT / "usage.30s.py")
U = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = U
SPEC.loader.exec_module(U)


class WindowsCollectorTests(unittest.TestCase):
    def test_cli_disabled_never_loads_the_native_bridge(self):
        desktop = {"q5": 20}
        with mock.patch.object(U, "_IS_WINDOWS", True), \
                mock.patch.object(U, "_provider_quota_enabled", return_value=False), \
                mock.patch.object(U, "_claude_quota_from_environment", return_value=None), \
                mock.patch.object(U, "_scan_claude_plan_raw", return_value=desktop), \
                mock.patch.object(U, "_windows_native_bridge") as bridge:
            self.assertEqual(U.scan_claude_plan(), desktop)
        bridge.assert_not_called()

    def test_cli_enabled_passes_desktop_data_to_the_bridge(self):
        desktop = {"q5": 20}
        bridge = mock.Mock()
        bridge.fetch_claude_quota.return_value = {"q5": 30, "q7": 40}
        with mock.patch.object(U, "_IS_WINDOWS", True), \
                mock.patch.object(U, "_provider_quota_enabled", return_value=True), \
                mock.patch.object(U, "_claude_quota_from_environment", return_value=None), \
                mock.patch.object(U, "_scan_claude_plan_raw", return_value=desktop), \
                mock.patch.object(U, "_windows_native_bridge", return_value=bridge):
            self.assertEqual(U.scan_claude_plan()["q7"], 40)
        bridge.fetch_claude_quota.assert_called_once_with(desktop)

    def test_grok_ungranted_never_reads_a_cursor_login(self):
        bridge = mock.Mock()
        bridge.grok_status.return_value = {"status": "authorization_required"}
        with mock.patch.object(U, "_IS_WINDOWS", True), \
                mock.patch.object(U, "_windows_native_bridge", return_value=bridge), \
                mock.patch.object(U, "_cursor_session") as cursor:
            self.assertIsNone(U.fetch_grok_bot_quota())
        cursor.assert_not_called()

    def test_background_worker_is_hidden_and_uses_bundled_python(self):
        bridge = mock.Mock(__file__="fixture/native_bridge.py")
        with mock.patch.object(U, "_IS_WINDOWS", True), \
                mock.patch.object(U, "_windows_native_bridge", return_value=bridge), \
                mock.patch.object(U, "_grok_bot_helper_files", return_value=("fixture/result.json", "fixture/state.json")), \
                mock.patch.object(U, "_load_json", return_value={}), \
                mock.patch.object(U, "_grok_bot_events_since", return_value=1000), \
                mock.patch.object(U.os, "makedirs"), \
                mock.patch.object(U, "_atomic_write_json"), \
                mock.patch.object(U.subprocess, "Popen") as spawn:
            spawn.return_value.pid = 42
            self.assertEqual(U._grok_bot_helper_start("fixture-marker"), (True, True))
        args = spawn.call_args.args[0]
        self.assertEqual(args[:3], [sys.executable, bridge.__file__, "grok-data"])
        self.assertEqual(spawn.call_args.kwargs["creationflags"], 0x08000000)
        self.assertNotIn("/bin/sh", args)


if __name__ == "__main__":
    unittest.main()
