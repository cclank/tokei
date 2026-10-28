"""Background collection must never request consent or discard an existing grant."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

try:
    from .test_codex_limits import USAGE
except ImportError:
    from test_codex_limits import USAGE


class GrokBotResolverTests(unittest.TestCase):
    def resolve(self, responses):
        with mock.patch.object(USAGE, "_IS_WINDOWS", False), \
                mock.patch.object(USAGE.sys, "platform", "darwin"), \
                mock.patch.dict(os.environ, {"TOKEI_GROK_BOT_HELPER": "", "TOKEI_GROK_BOT_HELPER_BLOCKED": "0"}), \
                mock.patch.object(USAGE.os.path, "isfile", return_value=True), \
                mock.patch.object(USAGE.os, "access", return_value=True), \
                mock.patch.object(USAGE.subprocess, "run", side_effect=responses) as run:
            result = USAGE._grok_bot_helper_path()
        return result, run.call_args_list

    def test_standalone_collector_uses_the_same_persistent_helper_resolver(self):
        helper = str(Path(tempfile.gettempdir()) / "previously-authorized-helper")
        result, calls = self.resolve([
            subprocess.CompletedProcess([], 0, "4\n"),
            subprocess.CompletedProcess([], 0, json.dumps({"helper": helper, "blocked": False})),
        ])
        self.assertEqual(result, helper)
        self.assertEqual([call.args[0][1] for call in calls],
                         ["--grok-bot-helper-version", "--grok-bot-resolve-helper"])

    def test_old_apps_are_never_launched_with_an_unknown_command(self):
        for version in ("1", "2", "3", "unexpected"):
            with self.subTest(version=version):
                result, calls = self.resolve([subprocess.CompletedProcess([], 0, version)])
                self.assertIsNone(result)
                self.assertEqual(len(calls), 1)

    def test_blocked_or_failed_resolution_has_no_main_app_fallback(self):
        for payload in ('{"helper":"/old-helper","blocked":true}', '{}', 'null', 'invalid'):
            with self.subTest(payload=payload):
                result, _ = self.resolve([
                    subprocess.CompletedProcess([], 0, "4"),
                    subprocess.CompletedProcess([], 0, payload),
                ])
                self.assertIsNone(result)
        result, _ = self.resolve([subprocess.TimeoutExpired("helper-version", 3)])
        self.assertIsNone(result)

    def test_missing_configured_helper_never_switches_keychain_identity(self):
        with mock.patch.object(USAGE, "_IS_WINDOWS", False), \
                mock.patch.dict(os.environ, {"TOKEI_GROK_BOT_HELPER": "/missing", "TOKEI_GROK_BOT_HELPER_BLOCKED": "0"}), \
                mock.patch.object(USAGE.os.path, "isfile", return_value=False), \
                mock.patch.object(USAGE.subprocess, "run") as run:
            self.assertIsNone(USAGE._grok_bot_helper_path())
        run.assert_not_called()


@unittest.skipUnless(sys.platform == "darwin", "Exercises the macOS shell helper")
class GrokBotConsentPreservationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.grant = self.root / "historical-consent"
        self.grant.write_bytes(b"original-consent\n")
        self.original = self.fingerprint()
        self.script = self.root / "old-helper.sh"
        self.script.write_text(
            '#!/bin/sh\n'
            'test "$1" = "--grok-bot-data-json" || exit 99\n'
            'test -f "$TOKEI_GROK_BOT_AUTH_MARKER" || exit 98\n'
            # Reproduce old bridges erasing their marker after a locked keychain.
            'rm "$TOKEI_GROK_BOT_AUTH_MARKER"\n'
            'exit 2\n')
        self.script.chmod(0o700)
        for patch in [
            mock.patch.object(USAGE, "PROVIDER_QUOTA_CACHE", str(self.root / "quota.json")),
            mock.patch.object(USAGE, "GROK_BOT_AUTH_MARKER", str(self.grant)),
            mock.patch.object(USAGE, "_grok_bot_helper_path", return_value=str(self.script)),
            mock.patch.object(USAGE, "_grok_bot_events_since", return_value=None),
        ]:
            patch.start()
            self.addCleanup(patch.stop)

    def fingerprint(self):
        return self.grant.read_bytes(), self.grant.stat().st_mtime_ns

    def test_repeated_old_helper_failures_preserve_the_real_consent(self):
        processes = []
        original_popen = subprocess.Popen

        def spawn(*args, **kwargs):
            process = original_popen(*args, **kwargs)
            processes.append(process)
            return process

        with mock.patch.object(USAGE.subprocess, "Popen", side_effect=spawn):
            for generation in range(3):
                self.assertEqual(USAGE._grok_bot_helper_start(str(generation)), (True, True))
                self.assertEqual(processes[-1].wait(timeout=5), 2)
                self.assertEqual(self.fingerprint(), self.original)
                self.assertEqual(list(self.root.glob(".grok-bot-consent-*")), [])

    def test_missing_consent_cannot_be_recreated_by_background_collection(self):
        self.grant.unlink()
        with mock.patch.object(USAGE.subprocess, "Popen") as run:
            self.assertEqual(USAGE._grok_bot_helper_start("historical-cache-marker"), (False, False))
        run.assert_not_called()
        self.assertFalse(self.grant.exists())
        self.assertEqual(list(self.root.glob(".grok-bot-consent-*")), [])

    def test_launch_failure_cleans_temporary_consent_and_keeps_original(self):
        with mock.patch.object(USAGE.subprocess, "Popen", side_effect=OSError("fixture failure")):
            self.assertEqual(USAGE._grok_bot_helper_start("marker"), (False, False))
        self.assertEqual(self.fingerprint(), self.original)
        self.assertEqual(list(self.root.glob(".grok-bot-consent-*")), [])


if __name__ == "__main__":
    unittest.main()
