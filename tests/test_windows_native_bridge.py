"""Permission gates, cache behavior, redirection and Windows credential formats."""
import base64
import ctypes
import http.server
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.error
import uuid

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("windows_native_bridge_tests", ROOT / "windows/native_bridge.py")
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = self.root / "Grok Bot"
        self.profile.mkdir()
        self.secrets = self.profile / "sand-secrets.json"
        self.credentials = self.root / "credentials.json"
        self.now = int(time.time())
        self.environment = mock.patch.dict(os.environ, {
            "TOKEI_WINDOWS_STATE_DIR": str(self.root),
            "TOKEI_GROK_BOT_SECRETS": str(self.secrets),
            "TOKEI_GROK_BOT_AUTH_MARKER": str(self.root / "grok_bot_keychain_authorized"),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        windows = mock.patch.object(B, "WINDOWS", True)
        windows.start()
        self.addCleanup(windows.stop)
        self.token = "header." + base64.urlsafe_b64encode(json.dumps({
            "sub": "auth|fixture-user", "exp": self.now + 86400,
        }).encode()).decode().rstrip("=") + ".signature"
        self.write_account("a" * 64)
        (self.root / "config.json").write_text(json.dumps({"grok_bot_quota_enabled": True}))
        self.credentials.write_text(json.dumps({"claudeAiOauth": {
            "accessToken": "fixture-access-token", "expiresAt": (self.now + 86400) * 1000,
        }}))

    def write_account(self, active):
        self.secrets.write_text(json.dumps({"cursor-accounts": json.dumps({"active": active,
            "accounts": {active: {"cursor-access-token": "encrypted-token"}}}),
            "cursor-machine-id": "encrypted-machine"}))

    def decryptor(self, value, profile):
        return self.token if value == "encrypted-token" else "fixture-machine"

    def authorize(self):
        with mock.patch.object(B, "decrypt_secret", side_effect=self.decryptor):
            self.assertEqual(B.authorize_grok(), {"status": "authorized"})

    def claude(self, desktop=None, now=None, requester=None):
        return B.fetch_claude_quota(desktop or {}, now=now or self.now,
            credentials=self.credentials, directory=self.root, requester=requester)

    def payload(self, now=None):
        from datetime import datetime, timezone
        reset = datetime.fromtimestamp((now or self.now) + 3600, timezone.utc).isoformat()
        return {"five_hour": {"utilization": 20, "resets_at": reset},
                "seven_day": {"utilization": 30, "resets_at": reset}}

    def test_fresh_desktop_skips_credential_read_and_network(self):
        requester = mock.Mock(side_effect=AssertionError("network forbidden"))
        self.credentials.unlink()
        desktop = {"q5": 1, "q7": 2, "q5_stale": False, "q7_stale": False}
        self.assertEqual(self.claude(desktop, requester=requester), desktop)
        requester.assert_not_called()

    def test_claude_cache_is_five_minutes_and_does_not_store_tokens(self):
        requester = mock.Mock(return_value=self.payload())
        first = self.claude(requester=requester)
        self.assertEqual(first["q5"], 20)
        self.assertEqual(self.claude(now=self.now + 299, requester=requester)["q7"], 30)
        self.assertEqual(requester.call_count, 1)
        self.claude(now=self.now + 300, requester=requester)
        self.assertEqual(requester.call_count, 2)
        cache = (self.root / "claude_cli_quota_cache.json").read_text()
        self.assertNotIn("fixture-access-token", cache)
        self.assertNotIn("Authorization", cache)
        self.assertEqual(requester.call_args.args[0], B.CLAUDE_URL)

    def test_expired_login_and_header_injection_do_not_send(self):
        requester = mock.Mock(side_effect=AssertionError("network forbidden"))
        for oauth in [{"accessToken": "fixture", "expiresAt": self.now * 1000},
                      {"accessToken": "fixture\r\nInjected: secret"}]:
            self.credentials.write_text(json.dumps({"claudeAiOauth": oauth}))
            self.assertEqual(self.claude(requester=requester), {})
        requester.assert_not_called()

    def test_rate_limit_uses_retry_after_and_minimum_backoff(self):
        error = urllib.error.HTTPError(B.CLAUDE_URL, 429, "rate limited", {"Retry-After": "900"}, None)
        requester = mock.Mock(side_effect=error)
        self.claude(requester=requester)
        self.claude(now=self.now + 899, requester=requester)
        self.assertEqual(requester.call_count, 1)
        self.claude(now=self.now + 900, requester=requester)
        self.assertEqual(requester.call_count, 2)

    def test_failed_query_keeps_last_snapshot_and_marks_it_stale(self):
        requester = mock.Mock(return_value=self.payload())
        self.claude(requester=requester)
        requester.side_effect = OSError("fixture offline")
        result = self.claude(now=self.now + 1900, requester=requester)
        self.assertEqual(result["q5"], 20)
        self.assertTrue(result["q5_stale"])
        self.claude(now=self.now + 1901, requester=requester)
        self.assertEqual(requester.call_count, 2)

    def test_changed_login_does_not_reuse_previous_account_cache(self):
        requester = mock.Mock(return_value=self.payload())
        self.claude(requester=requester)
        self.credentials.write_text(json.dumps({"claudeAiOauth": {"accessToken": "new-fixture-account"}}))
        requester.return_value = {"five_hour": {"utilization": 85}}
        self.assertEqual(self.claude(now=self.now + 1, requester=requester)["q5"], 85)
        self.assertEqual(requester.call_count, 2)

    def test_model_quota_invalid_percentages_are_rejected(self):
        payload = {"five_hour": {"utilization": -1}, "seven_day": {"utilization": True},
            "limits": [{"kind": "weekly_scoped", "scope": {"model": {"display_name": "Fable"}}, "percent": 42}]}
        self.assertEqual(B.claude_snapshot(payload, self.now), {"q_updated": self.now, "qf": 42, "qf_reset": None})

    def test_grok_requires_a_grant_before_decrypting(self):
        with mock.patch.object(B, "decrypt_secret", side_effect=AssertionError("must not decrypt")):
            self.assertEqual(B.grok_status()["status"], "authorization_required")
            with self.assertRaises(B.BridgeError):
                B.grok_credential()

    def test_grok_grant_survives_restart_without_storing_credentials(self):
        self.authorize()
        path = B.grok_grant_path()
        self.assertNotIn(self.token, path.read_text())
        self.assertNotIn("encrypted-token", path.read_text())
        spec = importlib.util.spec_from_file_location("restarted_windows_bridge", ROOT / "windows/native_bridge.py")
        restarted = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(restarted)
        with mock.patch.object(restarted, "WINDOWS", True):
            self.assertEqual(restarted.grok_status()["status"], "authorized")

    def test_grok_account_switch_requires_new_authorization(self):
        self.authorize()
        self.write_account("b" * 64)
        with mock.patch.object(B, "decrypt_secret", side_effect=AssertionError("must not decrypt")):
            self.assertEqual(B.grok_status()["status"], "authorization_required")
            with self.assertRaises(B.BridgeError):
                B.grok_credential()

    def test_grok_disabled_gate_prevents_decryption_and_network(self):
        self.authorize()
        (self.root / "config.json").write_text('{"grok_bot_quota_enabled":false}')
        with mock.patch.object(B, "decrypt_secret", side_effect=AssertionError("must not decrypt")):
            with self.assertRaisesRegex(B.BridgeError, "disabled"):
                B.fetch_grok_data(requester=mock.Mock(side_effect=AssertionError("must not send")))

    def test_expired_grok_login_cannot_be_authorized(self):
        self.token = "header." + base64.urlsafe_b64encode(json.dumps({"sub": "auth|fixture", "exp": 1}).encode()).decode().rstrip("=") + ".sig"
        with mock.patch.object(B, "decrypt_secret", side_effect=self.decryptor):
            self.assertEqual(B.authorize_grok()["status"], "expired")
        self.assertFalse(B.grok_grant_path().exists())

    def test_grok_payload_is_sanitized_and_uses_its_own_login(self):
        self.authorize()
        event = {"timestamp": str(self.now * 1000), "model": "fixture-model", "clientType": "sand",
            "tokenUsage": {"inputTokens": 3, "outputTokens": 5, "totalCents": 2}, "text": "PRIVATE-TEXT"}
        def request(url, headers, body, **kwargs):
            self.assertEqual(headers["Authorization"], "Bearer " + self.token)
            self.assertEqual(headers["x-cursor-client-type"], "sand")
            if url == B.GROK_QUOTA_URL:
                return {"usagePercent": 10, "hasNonZeroIncludedLimit": True, "privateField": "PRIVATE-TEXT"}
            return {"usageEventsDisplay": [event], "totalUsageEventsCount": 1}
        with mock.patch.object(B, "decrypt_secret", side_effect=self.decryptor):
            result = B.fetch_grok_data(requester=request)
        serialized = json.dumps(result)
        self.assertNotIn("PRIVATE-TEXT", serialized)
        self.assertNotIn(self.token, serialized)
        self.assertTrue(result["quotaFetched"])
        self.assertTrue(result["usageFetched"])
        self.assertEqual(result["usageEventsDisplay"][0]["tokenUsage"]["inputTokens"], 3)

    def test_revoked_permission_discards_an_in_flight_result(self):
        self.authorize()
        def request(*args, **kwargs):
            (self.root / "config.json").write_text('{"grok_bot_quota_enabled":false}')
            return {"usagePercent": 10}
        with mock.patch.object(B, "decrypt_secret", side_effect=self.decryptor):
            with self.assertRaises(B.BridgeError):
                B.fetch_grok_data(requester=request)

    def test_electron_gcm_and_scoped_dpapi_formats(self):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        key = b"k" * 32
        nonce = b"n" * 12
        encoded = base64.b64encode(b"v10" + nonce + AESGCM(key).encrypt(nonce, b"fixture", None)).decode()
        (self.profile / "Local State").write_text(json.dumps({"os_crypt": {
            "encrypted_key": base64.b64encode(b"DPAPIwrapped-key").decode(),
        }}))
        unprotect = mock.Mock(return_value=key)
        self.assertEqual(B.decrypt_secret(encoded, self.profile, unprotect), "fixture")
        unprotect.assert_called_once_with(b"wrapped-key")
        legacy = "scoped:v1:fixture:" + base64.b64encode(b"legacy-dpapi-blob").decode()
        self.assertEqual(B.decrypt_secret(legacy, self.profile, lambda raw: b"legacy"), "legacy")
        unsupported = base64.b64encode(b"v20app-bound-ciphertext").decode()
        with self.assertRaisesRegex(B.BridgeError, "unsupported_format"):
            B.decrypt_secret(unsupported, self.profile, mock.Mock(side_effect=AssertionError("must not decrypt")))

    def test_activity_has_four_fields_and_stable_random_id(self):
        sent = []
        with mock.patch.object(B.platform, "version", return_value="10.0.22631"):
            B.report_activity(self.root / "Telemetry", "1.0.46", lambda payload: sent.append(payload) or True)
            B.report_activity(self.root / "Telemetry", "1.0.46", lambda payload: sent.append(payload) or False)
        self.assertEqual(len(sent), 2)
        self.assertEqual(set(sent[0]), {"installation_id", "app_version", "os_name", "os_version"})
        self.assertEqual(sent[0]["installation_id"], sent[1]["installation_id"])
        self.assertEqual(uuid.UUID(sent[0]["installation_id"]).version, 4)
        self.assertEqual(sent[0]["os_version"], "10.0")

    def test_corrupt_activity_state_is_preserved_without_a_new_identity(self):
        folder = self.root / "Telemetry"
        folder.mkdir()
        (folder / "state.json").write_text("CORRUPT")
        sender = mock.Mock()
        B.report_activity(folder, "1.0.46", sender)
        sender.assert_not_called()
        self.assertEqual((folder / "state.json").read_text(), "CORRUPT")

    def test_redirect_never_receives_a_credential(self):
        visits = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                visits.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/must-not-receive-token")
                self.end_headers()
            def log_message(self, *args): pass
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/quota"
            with mock.patch.object(B, "CLAUDE_URL", url):
                with self.assertRaises(urllib.error.HTTPError):
                    B.request_json(url, {"Authorization": "Bearer fixture-only"})
            self.assertEqual(visits, ["/quota"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    @unittest.skipUnless(sys.platform == "win32", "Real DPAPI is Windows-only")
    def test_real_windows_dpapi_round_trip(self):
        from ctypes import wintypes
        class Blob(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]
        raw = b"fixture-Windows-only"
        data = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        source, output = Blob(len(raw), data), Blob()
        crypt = ctypes.WinDLL("crypt32", use_last_error=True)
        crypt.CryptProtectData.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        crypt.CryptProtectData.restype = wintypes.BOOL
        self.assertTrue(crypt.CryptProtectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)))
        try:
            protected = ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel = ctypes.WinDLL("kernel32")
            kernel.LocalFree.argtypes = [ctypes.c_void_p]
            kernel.LocalFree.restype = ctypes.c_void_p
            kernel.LocalFree(output.pbData)
        self.assertEqual(B.dpapi_decrypt(protected), raw)


if __name__ == "__main__":
    unittest.main()
