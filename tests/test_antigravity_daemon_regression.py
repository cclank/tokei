import ctypes
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from test_codex_limits import USAGE


class AntigravityDaemonRegressionTests(unittest.TestCase):
    def process(self):
        return {"pid": 4321, "kind": "ide", "csrf_token": "", "ports": [51213],
                "extension_port": None, "extension_csrf_token": None}

    def test_known_process_ignores_daemon_with_no_matching_live_port(self):
        process = self.process()
        stale = {"pid": 4321, "token": "stale-fixture", "ports": [54570]}
        with mock.patch.object(USAGE, "_antigravity_pid_alive", return_value=True), \
             mock.patch.object(USAGE, "_antigravity_listening_ports", return_value=[51213]):
            merged = USAGE._antigravity_merge_daemon_processes([process], [stale])
            endpoints = USAGE._antigravity_endpoints(merged[0])
        self.assertEqual(merged[0]["csrf_token"], "", "A stale daemon must not supply credentials")
        self.assertEqual({row[1] for row in endpoints}, {51213})

    def test_stale_daemon_does_not_shadow_a_later_valid_file(self):
        process = self.process()
        stale = {"pid": 4321, "token": "stale-fixture", "ports": [54570]}
        valid = {"pid": 4321, "token": "current-fixture", "ports": [51213]}
        with mock.patch.object(USAGE, "_antigravity_pid_alive", return_value=True), \
             mock.patch.object(USAGE, "_antigravity_listening_ports", return_value=[51213]):
            merged = USAGE._antigravity_merge_daemon_processes([process], [stale, valid])
        self.assertEqual(merged[0]["csrf_token"], "current-fixture")

    def test_windows_daemon_discovery_uses_read_only_process_queries(self):
        kernel = mock.Mock()
        kernel.OpenProcess.return_value = 99

        def status(_handle, code):
            code._obj.value = 259
            return True

        kernel.GetExitCodeProcess.side_effect = status
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "ls_fixture.json").write_text(json.dumps({
                "pid": 4321, "httpsPort": 51213, "csrfToken": "windows-fixture",
            }))
            with mock.patch.object(USAGE, "_IS_WINDOWS", True), \
                 mock.patch.object(ctypes, "WinDLL", return_value=kernel, create=True), \
                 mock.patch.object(USAGE.os, "kill", side_effect=AssertionError("must not terminate a Windows process")), \
                 mock.patch.object(USAGE, "ANTIGRAVITY_DAEMON_DIRS", [directory]), \
                 mock.patch.object(USAGE, "_windows_powershell", return_value="51213\n"):
                entries = USAGE._antigravity_daemon_credentials()
                processes = USAGE._antigravity_merge_daemon_processes([], entries)
                self.assertEqual(processes[0]["csrf_token"], "windows-fixture")
                self.assertEqual(processes[0]["ports"], [51213])
        self.assertTrue(kernel.CloseHandle.called)
        self.assertEqual(kernel.OpenProcess.call_args.args, (0x1000, False, 4321))

    def test_windows_exited_process_closes_handle_and_never_supplies_credentials(self):
        kernel = mock.Mock()
        kernel.OpenProcess.return_value = 99
        kernel.GetExitCodeProcess.return_value = False
        with mock.patch.object(USAGE, "_IS_WINDOWS", True), \
             mock.patch.object(ctypes, "WinDLL", return_value=kernel, create=True):
            self.assertFalse(USAGE._antigravity_pid_alive(4321))
        kernel.CloseHandle.assert_called_once_with(99)

    @unittest.skipUnless(sys.platform == "win32", "Real Win32 process query requires Windows")
    def test_actual_windows_process_can_be_queried_without_termination(self):
        self.assertTrue(USAGE._antigravity_pid_alive(os.getpid()))


if __name__ == "__main__":
    unittest.main()
