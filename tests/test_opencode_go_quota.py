import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from .test_codex_limits import USAGE
except ImportError:
    from test_codex_limits import USAGE


# Matches the official /inference/go/v1/usage contract, without a real key.
PAYLOAD = {
    "usage": {
        "rolling": {"status": "ok", "percent": 0, "resetsAt": "2026-11-21T15:00:00.000Z"},
        "weekly": {"status": "rate-limited", "percent": 100, "resetsAt": "2026-11-23T00:00:00.000Z"},
        "monthly": {"status": "ok", "percent": 50, "resetsAt": "2026-12-01T00:00:00.000Z"},
    }
}


class OpenCodeGoQuotaTests(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.root = Path(root.name)
        self.config = self.root / "config.json"
        self.cache = self.root / "provider_quota_cache.json"
        for patch in (
            mock.patch.object(USAGE, "_USER_DIR", str(self.root)),
            mock.patch.object(USAGE, "PROVIDER_QUOTA_CACHE", str(self.cache)),
            mock.patch.object(USAGE, "_PIPED_PROVIDER_KEYS", {}),
            mock.patch.dict(os.environ, {}, clear=True),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def enable(self):
        self.config.write_text('{"opencode_go_quota_enabled":true}', encoding="utf-8")

    def test_three_windows_and_utc_resets(self):
        quota = USAGE._normalize_opencode_go_quota(PAYLOAD)
        self.assertTrue(quota["available"])
        self.assertEqual(
            [(w["id"], w["used_pct"], w["reset"], w["window_minutes"]) for w in quota["windows"]],
            [("rolling", 0, 1795273200, 300), ("weekly", 100, 1795392000, 10080),
             ("monthly", 50, 1796083200, None)],
        )

    def test_missing_or_invalid_meters_are_not_displayed_as_zero(self):
        quota = USAGE._normalize_opencode_go_quota({
            "usage": {"rolling": {"percent": True}, "weekly": {"percent": -1}, "monthly": {"percent": 13}}
        })
        self.assertEqual([w["id"] for w in quota["windows"]], ["monthly"])
        self.assertIsNone(quota["windows"][0]["reset"])
        for invalid in ({}, {"usage": {"monthly": {"percent": 101}}}, {"usage": None}):
            with self.assertRaises(ValueError):
                USAGE._normalize_opencode_go_quota(invalid)

    def test_no_network_without_both_opt_in_and_key(self):
        with mock.patch.object(USAGE, "_provider_json_request") as request:
            with mock.patch.dict(os.environ, {"TOKEI_OPENCODE_GO_API_KEY": "fixture-only"}):
                self.assertEqual(USAGE.scan_opencode_go_quota(), {})
            self.enable()
            self.assertEqual(USAGE.scan_opencode_go_quota(), {})
            request.assert_not_called()

    def test_fixed_endpoint_and_cache_isolation_on_key_change(self):
        self.enable()
        USAGE._PIPED_PROVIDER_KEYS["TOKEI_OPENCODE_GO_API_KEY"] = "fixture-first"
        with mock.patch.object(USAGE, "_provider_json_request", return_value=PAYLOAD) as request:
            self.assertTrue(USAGE.scan_opencode_go_quota()["available"])
            self.assertTrue(USAGE.scan_opencode_go_quota()["available"])
            request.assert_called_once_with(
                "https://opencode.ai/inference/go/v1/usage",
                headers={"Authorization": "Bearer fixture-first"}, timeout=5,
            )
            USAGE._PIPED_PROVIDER_KEYS["TOKEI_OPENCODE_GO_API_KEY"] = "fixture-second"
            USAGE.scan_opencode_go_quota()
            self.assertEqual(request.call_count, 2)
            del USAGE._PIPED_PROVIDER_KEYS["TOKEI_OPENCODE_GO_API_KEY"]
            self.assertEqual(USAGE.scan_opencode_go_quota(), {})
        self.assertNotIn("fixture-", self.cache.read_text(encoding="utf-8"))

    def test_scan_output_and_safe_auth_error(self):
        self.config.write_text(json.dumps({
            "opencode_go_quota_enabled": True, "antigravity_quota_enabled": False, "devin_quota_enabled": False,
        }), encoding="utf-8")
        USAGE._PIPED_PROVIDER_KEYS["TOKEI_OPENCODE_GO_API_KEY"] = "fixture-only"
        errors = {}
        with mock.patch.object(USAGE, "_provider_json_request", side_effect=RuntimeError("HTTP 403: fixture-only")):
            self.assertEqual(USAGE.scan_provider_quotas(errors)["opencode_go"], {})
        self.assertEqual(errors, {"opencode_go_quota": "RuntimeError: OpenCode Go quota unavailable"})
        with mock.patch.object(USAGE, "_provider_json_request", return_value=PAYLOAD):
            result = USAGE.scan_provider_quotas({})
        self.assertEqual(len(result["opencode_go"]["windows"]), 3)
        self.assertNotIn("fixture-only", json.dumps(result))

    def test_collector_payload_exposes_quota_and_local_startup_skips_it(self):
        self.config.write_text(json.dumps({
            "opencode_go_quota_enabled": True, "antigravity_quota_enabled": False, "devin_quota_enabled": False,
        }), encoding="utf-8")
        USAGE._PIPED_PROVIDER_KEYS["TOKEI_OPENCODE_GO_API_KEY"] = "fixture-only"
        with mock.patch.object(USAGE, "_provider_json_request", return_value=PAYLOAD) as request:
            self.assertEqual(USAGE.compute(local_only=True)["opencode_go"], {})
            request.assert_not_called()
            quota = USAGE.compute()["opencode_go"]
            self.assertEqual([w["used_pct"] for w in quota["windows"]], [0, 100, 50])
            request.assert_called_once()
