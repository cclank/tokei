"""Kimi Code 官方额度:解析、缓存、以及"宁可说不知道也不谎报"的降级行为。"""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from test_codex_limits import USAGE


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


# 取自真实响应(api.kimi.com/coding/v1/usages):数字一律是字符串,
# 5h 窗口在 limits[] 里按 TIME_UNIT_MINUTE/300 描述,顶层 usage 不带 window。
def sample(now=None, five_used="2", sub_used="90"):
    now = now or datetime.now(timezone.utc)
    return {
        "user": {"userId": "u-1", "membership": {"level": "LEVEL_INTERMEDIATE"}},
        "usage": {
            "limit": "100", "used": sub_used,
            "remaining": str(100 - int(sub_used)),
            "resetTime": iso(now + timedelta(days=1)),
        },
        "limits": [{
            "window": {"duration": 300, "timeUnit": "TIME_UNIT_MINUTE"},
            "detail": {
                "limit": "100", "used": five_used,
                "remaining": str(100 - int(five_used)),
                "resetTime": iso(now + timedelta(hours=5)),
            },
        }],
    }


class KimiQuotaParseTests(unittest.TestCase):
    def test_parses_string_numbers_from_real_payload(self):
        limits = USAGE._kimi_live_to_limits(sample())
        self.assertAlmostEqual(limits["five_hour"]["used_percent"], 2.0)
        self.assertAlmostEqual(limits["subscription"]["used_percent"], 90.0)
        self.assertEqual(limits["plan"], "LEVEL_INTERMEDIATE")
        self.assertEqual(limits["user_id"], "u-1")

    def test_five_hour_window_accepts_both_time_units(self):
        self.assertEqual(USAGE._kimi_window_minutes(
            {"duration": 300, "timeUnit": "TIME_UNIT_MINUTE"}), 300)
        self.assertEqual(USAGE._kimi_window_minutes(
            {"duration": 5, "timeUnit": "TIME_UNIT_HOUR"}), 300)
        self.assertIsNone(USAGE._kimi_window_minutes(
            {"duration": 5, "timeUnit": "TIME_UNIT_UNSPECIFIED"}))

    def test_used_is_derived_when_only_remaining_is_given(self):
        slot = USAGE._kimi_slot({"limit": "100", "remaining": "40"})
        self.assertAlmostEqual(slot["used_percent"], 60.0)

    def test_zero_limit_is_not_a_percentage(self):
        self.assertIsNone(USAGE._kimi_slot({"limit": "0", "used": "0"}))

    def test_payload_without_any_quota_returns_none(self):
        self.assertIsNone(USAGE._kimi_live_to_limits({"user": {}, "limits": []}))

    def test_non_five_hour_windows_are_ignored(self):
        data = sample()
        data["limits"][0]["window"] = {"duration": 1, "timeUnit": "TIME_UNIT_HOUR"}
        limits = USAGE._kimi_live_to_limits(data)
        self.assertIsNone(limits["five_hour"])
        self.assertIsNotNone(limits["subscription"])


class KimiQuotaStaleTests(unittest.TestCase):
    def test_fresh_reading_is_not_stale(self):
        now = int(datetime.now().timestamp())
        limits = USAGE._kimi_live_to_limits(sample())
        values = USAGE._kimi_quota_values(limits, now_epoch=now, updated_at=now)
        self.assertFalse(values["p5_stale"])
        self.assertFalse(values["pw_stale"])
        self.assertAlmostEqual(values["p5"], 2.0)

    def test_window_rollover_marks_stale_instead_of_reporting_full(self):
        """窗口翻篇后不能显示"已回满" —— Kimi 额度按次计,本机无从反推真实消耗。"""
        limits = {"five_hour": {"used_percent": 80.0, "resets_at": 1000},
                  "subscription": {"used_percent": 90.0, "resets_at": 5000}}
        values = USAGE._kimi_quota_values(limits, now_epoch=2000, updated_at=1900)
        self.assertTrue(values["p5_stale"])
        self.assertFalse(values["pw_stale"])
        self.assertAlmostEqual(values["p5"], 80.0)

    def test_old_reading_marks_stale_even_inside_window(self):
        now = 100000
        old = now - USAGE._KIMI_QUOTA_STALE_AFTER - 1
        limits = {"five_hour": {"used_percent": 10.0, "resets_at": now + 3600},
                  "subscription": {"used_percent": 20.0, "resets_at": now + 86400}}
        values = USAGE._kimi_quota_values(limits, now_epoch=now, updated_at=old)
        self.assertTrue(values["p5_stale"])
        self.assertTrue(values["pw_stale"])

    def test_missing_quota_is_not_stale(self):
        values = USAGE._kimi_quota_values(None, now_epoch=1000, updated_at=1)
        self.assertFalse(values["p5_stale"])
        self.assertIsNone(values["p5"])


class KimiQuotaFetchTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="kimi-quota-")
        self.cache = os.path.join(self.home, "kimi_quota_cache.json")
        self.creds_dir = os.path.join(self.home, "kimi", "credentials")
        os.makedirs(self.creds_dir, exist_ok=True)
        self.env = mock.patch.dict(
            os.environ, {"TOKEI_KIMI_DIR": os.path.join(self.home, "kimi")}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.cache_patch = mock.patch.object(USAGE, "KIMI_QUOTA_CACHE", self.cache)
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)

    def write_creds(self, expires_in_seconds):
        path = os.path.join(self.creds_dir, "kimi-code.json")
        with open(path, "w") as fh:
            json.dump({
                "access_token": "tok-" + str(expires_in_seconds),
                "refresh_token": "refresh-should-never-be-used",
                "expires_at": int(datetime.now().timestamp()) + expires_in_seconds,
            }, fh)

    def write_cache(self, age_seconds, used=42.0):
        with open(self.cache, "w") as fh:
            json.dump({
                "fetched_at": datetime.now().timestamp() - age_seconds,
                "limits": {
                    "five_hour": {"used_percent": used,
                                  "resets_at": int(datetime.now().timestamp()) + 3600},
                    "subscription": {"used_percent": 90.0,
                                     "resets_at": int(datetime.now().timestamp()) + 86400},
                },
                "plan": "LEVEL_INTERMEDIATE",
                "user_id": "u-1",
            }, fh)

    def test_expired_token_never_hits_the_network(self):
        """CLI 的登录态很短命。过期后发请求必然 401,更重要的是不能代刷 refresh_token。"""
        self.write_creds(expires_in_seconds=-60)
        self.write_cache(age_seconds=USAGE._KIMI_QUOTA_TTL + 10)
        with mock.patch("urllib.request.urlopen") as opener:
            result = USAGE.fetch_kimi_live_limits()
        opener.assert_not_called()
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result[0]["five_hour"]["used_percent"], 42.0)

    def test_refresh_token_is_never_read(self):
        self.write_creds(expires_in_seconds=-60)
        auth = USAGE._kimi_auth_context()
        self.assertTrue(auth["expired"])
        self.assertNotIn("refresh_token", auth)

    def test_fresh_cache_short_circuits_before_reading_credentials(self):
        self.write_cache(age_seconds=1)
        with mock.patch("urllib.request.urlopen") as opener:
            limits, plan, _ = USAGE.fetch_kimi_live_limits()
        opener.assert_not_called()
        self.assertEqual(plan, "LEVEL_INTERMEDIATE")
        self.assertAlmostEqual(limits["five_hour"]["used_percent"], 42.0)

    def test_live_fetch_writes_cache(self):
        self.write_creds(expires_in_seconds=1800)
        payload = json.dumps(sample()).encode()

        class Res:
            def __enter__(self_inner): return self_inner
            def __exit__(self_inner, *a): return False
            def geturl(self_inner): return USAGE._KIMI_USAGE_URL
            def read(self_inner, *a): return payload

        with mock.patch("urllib.request.urlopen", return_value=Res()):
            limits, plan, fetched = USAGE.fetch_kimi_live_limits()
        self.assertAlmostEqual(limits["subscription"]["used_percent"], 90.0)
        self.assertEqual(plan, "LEVEL_INTERMEDIATE")
        with open(self.cache) as fh:
            saved = json.load(fh)
        self.assertEqual(saved["user_id"], "u-1")
        self.assertEqual(saved["source"], "live")

    def test_redirect_off_host_is_rejected(self):
        self.write_creds(expires_in_seconds=1800)

        class Res:
            def __enter__(self_inner): return self_inner
            def __exit__(self_inner, *a): return False
            def geturl(self_inner): return "https://evil.example.com/usages"
            def read(self_inner, *a): return json.dumps(sample()).encode()

        with mock.patch("urllib.request.urlopen", return_value=Res()):
            self.assertIsNone(USAGE.fetch_kimi_live_limits())

    def test_network_failure_falls_back_to_cache_and_backs_off(self):
        self.write_creds(expires_in_seconds=1800)
        self.write_cache(age_seconds=USAGE._KIMI_QUOTA_TTL + 10)
        with mock.patch("urllib.request.urlopen", side_effect=OSError("boom")):
            result = USAGE.fetch_kimi_live_limits()
        self.assertIsNotNone(result)
        with open(self.cache) as fh:
            self.assertIn("last_failure_at", json.load(fh))

    def test_disabled_by_env(self):
        self.write_creds(expires_in_seconds=1800)
        with mock.patch.dict(os.environ, {"TOKEI_KIMI_LIVE_QUOTA": "0"}):
            with mock.patch("urllib.request.urlopen") as opener:
                self.assertIsNone(USAGE.fetch_kimi_live_limits())
            opener.assert_not_called()

    def test_no_credentials_returns_none(self):
        with mock.patch("urllib.request.urlopen") as opener:
            self.assertIsNone(USAGE.fetch_kimi_live_limits())
        opener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
