"""Projected cache validation only; these tests never load credentials or use the network."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from .test_codex_limits import USAGE
except ImportError:
    from test_codex_limits import USAGE


class DoubaoWorkQuotaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "doubaowork_quota_cache.json"
        self.patch = mock.patch.object(USAGE, "_USER_DIR", self.tmp.name)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.config = mock.patch.object(USAGE, "_tokei_config", return_value={"doubaowork_quota_enabled": True})
        self.config_mock = self.config.start()
        self.addCleanup(self.config.stop)
        self.raw = {"version": 1, "status": "connected", "updated": 1800000000, "windows": [
            {"window_type": 1, "used_percent": 0, "start_time_ms": 0, "end_time_ms": 0,
             "less_than_one_percent": False},
            {"window_type": 2, "used_percent": 20, "start_time_ms": 1799900000000,
             "end_time_ms": 1800504800000, "less_than_one_percent": False}]}

    def read(self, value=None):
        self.path.write_text(json.dumps(self.raw if value is None else value))
        return USAGE._doubaowork_quota_cache(now=1800000000)

    def test_off_by_default_and_explicit_boolean_only(self):
        for flag in [None, False, 1, "true"]:
            self.config_mock.return_value = {"doubaowork_quota_enabled": flag}
            with mock.patch("builtins.open", side_effect=AssertionError("disabled must not read cache")):
                self.assertIsNone(USAGE._doubaowork_quota_cache())

    def test_exact_zero_full_and_under_one_percent(self):
        for amount in [0, 20, 100, 0.25]:
            self.raw["windows"][0]["used_percent"] = amount
            self.assertEqual(self.read()["windows"][0]["used_percent"], amount)
        self.raw["windows"][0]["less_than_one_percent"] = True
        self.assertTrue(self.read()["windows"][0]["less_than_one_percent"])

    def test_only_projected_fields_reach_snapshot(self):
        self.raw["token"] = "synthetic-secret"
        self.raw["windows"][0]["account_id"] = "synthetic-account"
        clean = self.read()
        self.assertEqual(set(clean), {"version", "status", "updated", "windows"})
        self.assertNotIn("synthetic", json.dumps(clean))
        self.assertNotIn("tokens", clean)

    def test_invalid_percent_time_and_duplicate_windows_are_unknown(self):
        cases = [("used_percent", -1), ("used_percent", 101), ("used_percent", True),
                 ("used_percent", "20"), ("used_percent", float("nan")),
                 ("end_time_ms", -1), ("start_time_ms", True),
                 ("less_than_one_percent", 1), ("window_type", 3)]
        for field, value in cases:
            raw = copy.deepcopy(self.raw)
            raw["windows"][0][field] = value
            with self.subTest(field=field, value=value):
                self.assertIsNone(self.read(raw))
        raw = copy.deepcopy(self.raw)
        raw["windows"][1]["window_type"] = 1
        self.assertIsNone(self.read(raw))

    def test_stale_cache_retains_original_timestamp_for_stale_ui(self):
        self.raw["updated"] -= 3600
        self.assertEqual(self.read()["updated"], self.raw["updated"])
        self.raw["status"] = "unavailable"
        self.assertEqual(self.read()["status"], "unavailable")
        self.raw["updated"] = 1800000301
        self.assertIsNone(self.read())

    def test_missing_truncated_and_oversized_cache_are_unknown(self):
        self.assertIsNone(USAGE._doubaowork_quota_cache())
        for data in [b"{", b"x" * 65537, b"null", b"[]"]:
            self.path.write_bytes(data)
            self.assertIsNone(USAGE._doubaowork_quota_cache())

    def test_quota_reaches_collector_without_local_conversations(self):
        self.path.write_text(json.dumps(self.raw))
        with mock.patch.object(USAGE, "_doubao_databases", return_value=[]), \
             mock.patch.object(USAGE, "ledger_touch"), \
             mock.patch.object(USAGE, "ledger_reconcile", return_value={}), \
             mock.patch.object(USAGE._time, "time", return_value=1800000000):
            result = USAGE.scan_doubaowork({}, {})
        self.assertEqual(result["ranges"]["today"]["sessions"], 0)
        self.assertEqual(result["quota"]["windows"][1]["used_percent"], 20)
        self.assertNotIn("tokens", result)


if __name__ == "__main__":
    unittest.main()
