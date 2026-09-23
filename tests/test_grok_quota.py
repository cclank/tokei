import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

try:
    from .test_codex_limits import USAGE
except ImportError:
    from test_codex_limits import USAGE


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        fixed = cls(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
        return fixed.replace(tzinfo=None) if tz is None else fixed.astimezone(tz)


class GrokQuotaTests(unittest.TestCase):
    def setUp(self):
        self.old_home = USAGE.GROK_HOME
        self.old_log = USAGE.GROK_LOG
        self.old_auth = USAGE.GROK_AUTH
        self.old_cache = USAGE.GROK_QUOTA_CACHE
        self.old_user = USAGE._USER_DIR
        self.datetime_patcher = mock.patch.object(USAGE, "datetime", FixedDateTime)
        self.datetime_patcher.start()

    def tearDown(self):
        self.datetime_patcher.stop()
        USAGE.GROK_HOME = self.old_home
        USAGE.GROK_LOG = self.old_log
        USAGE.GROK_AUTH = self.old_auth
        USAGE.GROK_QUOTA_CACHE = self.old_cache
        USAGE._USER_DIR = self.old_user

    def configure(self, root):
        USAGE.GROK_HOME = str(root / ".grok")
        USAGE.GROK_LOG = str(root / ".grok" / "logs" / "unified.jsonl")
        USAGE.GROK_AUTH = str(root / ".grok" / "auth.json")
        USAGE.GROK_QUOTA_CACHE = str(root / ".tokei" / "grok_quota_cache.json")
        USAGE._USER_DIR = str(root / ".tokei")
        Path(USAGE._USER_DIR).mkdir(parents=True, exist_ok=True)

    def billing_line(self, pct, start, end, plan="SuperGrok", products=None, ts=None):
        config = {
            "creditUsagePercent": pct,
            "currentPeriod": {
                "type": "USAGE_PERIOD_TYPE_WEEKLY",
                "start": start,
                "end": end,
            },
            "billingPeriodStart": start,
            "billingPeriodEnd": end,
        }
        if products is not None:
            config["productUsage"] = products
        return {
            "ts": ts or start,
            "msg": "billing: fetched credits config",
            "ctx": {"config": config, "subscriptionTier": plan},
        }

    def test_local_log_is_preferred_and_live_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.configure(root)
            write_jsonl(Path(USAGE.GROK_LOG), [
                self.billing_line(
                    44.0,
                    "2026-07-14T08:24:06+00:00",
                    "2026-07-21T08:24:06+00:00",
                    ts="2026-07-19T02:00:00+00:00",
                ),
            ])
            with mock.patch.object(USAGE, "fetch_grok_live_quota") as live:
                quota = USAGE.scan_grok_quota()
                live.assert_not_called()

        self.assertEqual(quota["pct"], 44.0)
        self.assertEqual(quota["plan"], "SuperGrok")
        self.assertEqual(quota["source"], "log")
        self.assertEqual(quota["window"], "week")
        self.assertFalse(quota["stale"])
        self.assertIsNotNone(quota["reset"])

    def test_local_log_treats_omitted_zero_percent_as_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.configure(root)
            start = "2026-07-19T08:41:16+00:00"
            end = "2026-07-26T08:41:16+00:00"
            write_jsonl(Path(USAGE.GROK_LOG), [{
                "ts": "2026-07-19T09:00:00+00:00",
                "msg": "billing: fetched credits config",
                "ctx": {
                    "subscriptionTier": "X Premium+",
                    "config": {
                        "currentPeriod": {
                            "type": "USAGE_PERIOD_TYPE_WEEKLY",
                            "start": start,
                            "end": end,
                        },
                        "billingPeriodStart": start,
                        "billingPeriodEnd": end,
                        "isUnifiedBillingUser": True,
                    },
                },
            }])

            quota = USAGE.scan_grok_quota()

        self.assertEqual(quota["pct"], 0.0)
        self.assertEqual(quota["plan"], "X Premium+")
        self.assertEqual(quota["source"], "log")
        self.assertFalse(quota["stale"])
        self.assertIsNotNone(quota["reset"])

    def test_missing_percent_requires_complete_unified_period(self):
        quota = USAGE._normalize_grok_billing({
            "currentPeriod": {
                "start": "2026-07-19T08:41:16+00:00",
                "end": "2026-07-26T08:41:16+00:00",
            },
        })

        self.assertIsNone(quota)

    def test_live_api_only_when_config_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.configure(root)
            (root / ".tokei" / "config.json").write_text(
                json.dumps({"grok_live_quota_enabled": True}), encoding="utf-8")
            write_jsonl(Path(USAGE.GROK_LOG), [
                self.billing_line(
                    10.0,
                    "2026-07-14T08:24:06+00:00",
                    "2026-07-21T08:24:06+00:00",
                    ts="2026-07-19T01:00:00+00:00",
                ),
            ])
            live_payload = {
                "pct": 55.0,
                "reset": 1784622246,
                "plan": "SuperGrok",
                "products": [{"name": "GrokBuild", "pct": 50.0}],
                "window": "week",
                "source": "live",
                "updated": 1784430000,
                "stale": False,
            }
            with mock.patch.object(USAGE, "fetch_grok_live_quota", return_value=live_payload):
                quota = USAGE.scan_grok_quota()

        self.assertEqual(quota["pct"], 55.0)
        self.assertEqual(quota["source"], "live")
        self.assertEqual(quota["products"][0]["name"], "GrokBuild")

    def test_env_zero_forces_offline_even_if_config_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.configure(root)
            (root / ".tokei" / "config.json").write_text(
                json.dumps({"grok_live_quota_enabled": True}), encoding="utf-8")
            write_jsonl(Path(USAGE.GROK_LOG), [
                self.billing_line(
                    12.0,
                    "2026-07-14T08:24:06+00:00",
                    "2026-07-21T08:24:06+00:00",
                    ts="2026-07-19T01:00:00+00:00",
                ),
            ])
            with mock.patch.dict(USAGE.os.environ, {"TOKEI_GROK_LIVE_QUOTA": "0"}), \
                 mock.patch.object(USAGE, "fetch_grok_live_quota") as live:
                self.assertFalse(USAGE._grok_live_quota_enabled())
                quota = USAGE.scan_grok_quota()
                live.assert_not_called()

        self.assertEqual(quota["source"], "log")
        self.assertEqual(quota["pct"], 12.0)

    def test_normalize_marks_expired_period_stale(self):
        # 2020-01-01 的 epoch 约 1577836800；用更大 now 判定已过期。
        quota = USAGE._normalize_grok_billing(
            {
                "creditUsagePercent": 80.0,
                "currentPeriod": {
                    "type": "USAGE_PERIOD_TYPE_WEEKLY",
                    "end": "2020-01-01T00:00:00+00:00",
                },
                "productUsage": [{"product": "GrokBuild", "usagePercent": 70.0}],
            },
            plan="SuperGrok",
            source="log",
            updated=1_700_000_000,
            now_epoch=1_700_000_000,
        )
        self.assertTrue(quota["stale"])
        self.assertEqual(quota["pct"], 0.0)
        self.assertIsNone(quota["reset"])
        self.assertEqual(quota["products"][0]["pct"], 0.0)

    def _write_auth(self, token="test-token", expires_at=None):
        Path(USAGE.GROK_AUTH).parent.mkdir(parents=True, exist_ok=True)
        entry = {"key": token, "auth_mode": "oidc"}
        if expires_at is not None:
            entry["expires_at"] = expires_at
        Path(USAGE.GROK_AUTH).write_text(json.dumps({
            "https://auth.x.ai::id": entry,
        }), encoding="utf-8")

    def _fake_billing_response(self, body, final_url=None):
        payload = json.dumps(body).encode("utf-8")

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, *args, **kwargs):
                return payload

            def geturl(self):
                return final_url or USAGE._GROK_LIVE_BILLING_URL

        return FakeResponse()

    def test_live_fetch_uses_auth_and_writes_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.configure(root)
            (root / ".tokei" / "config.json").write_text(
                json.dumps({"grok_live_quota_enabled": True}), encoding="utf-8")
            self._write_auth()

            body = {
                "config": {
                    "creditUsagePercent": 33.0,
                    "currentPeriod": {
                        "type": "USAGE_PERIOD_TYPE_WEEKLY",
                        "start": "2026-07-14T08:24:06+00:00",
                        "end": "2026-07-21T08:24:06+00:00",
                    },
                    "productUsage": [
                        {"product": "GrokBuild", "usagePercent": 30.0},
                        {"product": "Api", "usagePercent": 3.0},
                        {"product": "GrokChat"},
                    ],
                }
            }
            with mock.patch("urllib.request.urlopen",
                            return_value=self._fake_billing_response(body)) as opener:
                quota = USAGE.fetch_grok_live_quota()

            self.assertEqual(opener.call_count, 1)
            req = opener.call_args[0][0]
            self.assertEqual(req.full_url, USAGE._GROK_LIVE_BILLING_URL)
            self.assertEqual(req.get_header("Authorization"), "Bearer test-token")
            self.assertNotIn("Authorization", req.headers)
            self.assertEqual(
                req.unredirected_hdrs.get("Authorization"), "Bearer test-token")
            self.assertEqual(quota["pct"], 33.0)
            self.assertEqual(quota["source"], "live")
            self.assertEqual(quota["window"], "week")
            self.assertIsNotNone(quota["reset"])
            # GrokChat 无 usagePercent 时 pct 为 None，UI 会过滤；解析仍保留条目。
            self.assertEqual(
                [(p["name"], p["pct"]) for p in quota["products"]],
                [("GrokBuild", 30.0), ("Api", 3.0), ("GrokChat", None)],
            )
            cached = json.loads(Path(USAGE.GROK_QUOTA_CACHE).read_text(encoding="utf-8"))
            self.assertEqual(cached["quota"]["pct"], 33.0)
            self.assertEqual(cached["source"], "live")

    def test_live_fetch_rejects_redirected_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.configure(root)
            (root / ".tokei" / "config.json").write_text(
                json.dumps({"grok_live_quota_enabled": True}), encoding="utf-8")
            self._write_auth()
            body = {"config": {"creditUsagePercent": 20.0}}
            response = self._fake_billing_response(
                body, final_url="https://example.invalid/billing")
            with mock.patch("urllib.request.urlopen", return_value=response):
                quota = USAGE.fetch_grok_live_quota()

        self.assertIsNone(quota)

    def test_normalize_clamps_invalid_percentages(self):
        quota = USAGE._normalize_grok_billing(
            {
                "creditUsagePercent": 140,
                "productUsage": [
                    {"product": "GrokBuild", "usagePercent": -3},
                    {"product": "Api", "usagePercent": float("inf")},
                ],
            },
            now_epoch=1_700_000_000,
        )
        self.assertEqual(quota["pct"], 100.0)
        self.assertEqual(quota["products"][0]["pct"], 0.0)
        self.assertIsNone(quota["products"][1]["pct"])

    def test_live_api_parses_real_shape_product_usage(self):
        """对齐真实接口：creditUsagePercent + productUsage 占用拆分。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.configure(root)
            (root / ".tokei" / "config.json").write_text(
                json.dumps({"grok_live_quota_enabled": True}), encoding="utf-8")
            self._write_auth()
            body = {
                "config": {
                    "currentPeriod": {
                        "type": "USAGE_PERIOD_TYPE_WEEKLY",
                        "start": "2026-07-14T08:24:06.864825+00:00",
                        "end": "2026-07-21T08:24:06.864825+00:00",
                    },
                    "creditUsagePercent": 54.0,
                    "productUsage": [
                        {"product": "GrokBuild", "usagePercent": 52.0},
                        {"product": "Api", "usagePercent": 2.0},
                        {"product": "GrokChat"},
                    ],
                    "isUnifiedBillingUser": True,
                    "billingPeriodStart": "2026-07-14T08:24:06.864825+00:00",
                    "billingPeriodEnd": "2026-07-21T08:24:06.864825+00:00",
                }
            }
            with mock.patch("urllib.request.urlopen",
                            return_value=self._fake_billing_response(body)):
                quota = USAGE.fetch_grok_live_quota()

        self.assertEqual(quota["pct"], 54.0)
        self.assertEqual(quota["source"], "live")
        self.assertEqual(quota["products"][0]["name"], "GrokBuild")
        self.assertEqual(quota["products"][0]["pct"], 52.0)
        self.assertEqual(quota["products"][1]["name"], "Api")
        self.assertEqual(quota["products"][1]["pct"], 2.0)
        # 分产品是占用占比，总和应接近总已用（允许接口四舍五入）
        used = sum(p["pct"] for p in quota["products"] if p["pct"] is not None)
        self.assertAlmostEqual(used, 54.0, places=5)

    def test_live_api_failure_falls_back_to_local_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.configure(root)
            (root / ".tokei" / "config.json").write_text(
                json.dumps({"grok_live_quota_enabled": True}), encoding="utf-8")
            self._write_auth()
            write_jsonl(Path(USAGE.GROK_LOG), [
                self.billing_line(
                    41.0,
                    "2026-07-14T08:24:06+00:00",
                    "2026-07-21T08:24:06+00:00",
                    ts="2026-07-19T03:00:00+00:00",
                ),
            ])
            with mock.patch("urllib.request.urlopen", side_effect=OSError("network down")):
                quota = USAGE.scan_grok_quota()

        self.assertEqual(quota["pct"], 41.0)
        self.assertEqual(quota["source"], "log")
        self.assertEqual(quota["plan"], "SuperGrok")

    def test_live_api_skipped_without_auth_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.configure(root)
            (root / ".tokei" / "config.json").write_text(
                json.dumps({"grok_live_quota_enabled": True}), encoding="utf-8")
            # 无 auth.json
            write_jsonl(Path(USAGE.GROK_LOG), [
                self.billing_line(
                    22.0,
                    "2026-07-14T08:24:06+00:00",
                    "2026-07-21T08:24:06+00:00",
                    ts="2026-07-19T03:00:00+00:00",
                ),
            ])
            with mock.patch("urllib.request.urlopen") as opener:
                quota = USAGE.scan_grok_quota()
                opener.assert_not_called()

        self.assertEqual(quota["source"], "log")
        self.assertEqual(quota["pct"], 22.0)

    def test_expired_token_skips_request_and_marks_auth_expired(self):
        """issue #89:过期 token 不发注定 401 的请求,直接标本地日志 + auth_expired。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.configure(root)
            (root / ".tokei" / "config.json").write_text(
                json.dumps({"grok_live_quota_enabled": True}), encoding="utf-8")
            # FixedDateTime 是 2026-07-19 12:00 UTC;expires 早于 now - skew 即过期。
            self._write_auth(token="expired-token", expires_at="2026-07-19T10:00:00+00:00")
            write_jsonl(Path(USAGE.GROK_LOG), [
                self.billing_line(
                    41.0,
                    "2026-07-14T08:24:06+00:00",
                    "2026-07-21T08:24:06+00:00",
                    ts="2026-07-19T03:00:00+00:00",
                ),
            ])
            with mock.patch("urllib.request.urlopen") as opener:
                quota = USAGE.scan_grok_quota()
                opener.assert_not_called()

        self.assertEqual(quota["pct"], 41.0)
        self.assertEqual(quota["source"], "log")
        self.assertTrue(quota.get("auth_expired"))

    def test_valid_token_still_fires_live_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.configure(root)
            (root / ".tokei" / "config.json").write_text(
                json.dumps({"grok_live_quota_enabled": True}), encoding="utf-8")
            self._write_auth(token="fresh-token", expires_at="2026-07-19T18:00:00+00:00")
            body = {"config": {"creditUsagePercent": 33.0,
                               "currentPeriod": {"type": "USAGE_PERIOD_TYPE_WEEKLY",
                                                 "start": "2026-07-14T08:24:06+00:00",
                                                 "end": "2026-07-21T08:24:06+00:00"}}}
            with mock.patch("urllib.request.urlopen",
                            return_value=self._fake_billing_response(body)) as opener:
                quota = USAGE.fetch_grok_live_quota()

        self.assertEqual(opener.call_count, 1)
        req = opener.call_args[0][0]
        self.assertEqual(req.unredirected_hdrs.get("Authorization"), "Bearer fresh-token")
        self.assertEqual(quota["source"], "live")
        self.assertIsNone(quota.get("auth_expired"))

    def test_auth_state_reports_expiry_and_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.configure(root)
            self._write_auth(token="t", expires_at="2026-07-19T10:00:00+00:00")
            token, expired, mtime = USAGE._grok_auth_state(
                now_epoch=datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc).timestamp())
            self.assertEqual(token, "t")
            self.assertTrue(expired)
            self.assertIsNotNone(mtime)
            self._write_auth(token="t", expires_at="2026-07-19T18:00:00+00:00")
            _, expired_fresh, _ = USAGE._grok_auth_state(
                now_epoch=datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc).timestamp())
            self.assertFalse(expired_fresh)

    def test_external_auth_refresh_invalidates_live_cache(self):
        """OpenUsage/grok 写回 auth.json 后,旧 live 缓存立刻失效,不必干等 30s TTL。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.configure(root)
            (root / ".tokei" / "config.json").write_text(
                json.dumps({"grok_live_quota_enabled": True}), encoding="utf-8")
            self._write_auth(token="old-token")
            body = {"config": {"creditUsagePercent": 10.0,
                               "currentPeriod": {"type": "USAGE_PERIOD_TYPE_WEEKLY",
                                                 "start": "2026-07-14T08:24:06+00:00",
                                                 "end": "2026-07-21T08:24:06+00:00"}}}
            with mock.patch("urllib.request.urlopen",
                            return_value=self._fake_billing_response(body)):
                first = USAGE.fetch_grok_live_quota()
            self.assertEqual(first["source"], "live")
            # 外部刷新 auth.json:token 轮换,文件 mtime 变新。
            import time as _time
            _time.sleep(0.02)
            self._write_auth(token="rotated-token")
            body2 = {"config": {"creditUsagePercent": 11.0,
                                "currentPeriod": {"type": "USAGE_PERIOD_TYPE_WEEKLY",
                                                  "start": "2026-07-14T08:24:06+00:00",
                                                  "end": "2026-07-21T08:24:06+00:00"}}}
            with mock.patch("urllib.request.urlopen",
                            return_value=self._fake_billing_response(body2)) as opener:
                second = USAGE.fetch_grok_live_quota()
            self.assertEqual(opener.call_count, 1)
            req = opener.call_args[0][0]
            self.assertEqual(req.unredirected_hdrs.get("Authorization"), "Bearer rotated-token")
            self.assertEqual(second["pct"], 11.0)

    def test_compute_surfaces_live_quota_fields(self):
        """compute() 输出的 grok 块应带上 pct/reset/products/source。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.configure(root)
            (root / ".tokei" / "config.json").write_text(
                json.dumps({"grok_live_quota_enabled": True}), encoding="utf-8")
            self._write_auth()
            write_jsonl(Path(USAGE.GROK_LOG), [])
            live = {
                "pct": 12.5,
                "reset": 1_784_622_246,
                "plan": "SuperGrok",
                "products": [
                    {"name": "GrokBuild", "pct": 10.0},
                    {"name": "Api", "pct": 2.5},
                ],
                "window": "week",
                "source": "live",
                "updated": 1_784_400_000,
                "stale": False,
            }
            empty_ranges = {
                k: {"tokens": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0,
                    "cost": 0.0, "models": {}, "usage_sessions": set(), "usage_calls": 0,
                    "sessions": set(), "turns": 0, "tools": 0, "duration": 0,
                    "ctx_used": 0, "ctx_window": 0, "errors": 0, "cancellations": 0,
                    "ttft_sum": 0, "response_sum": 0, "latency_count": 0}
                for k in USAGE.RANGE_KEYS
            }
            with mock.patch.object(USAGE, "scan_grok",
                                   return_value={"ranges": empty_ranges, "model": "grok-4.5",
                                                 "days": {}}), \
                 mock.patch.object(USAGE, "scan_grok_quota", return_value=live), \
                 mock.patch.object(USAGE, "scan_claude",
                                   return_value=USAGE._empty_claude()), \
                 mock.patch.object(USAGE, "scan_codex",
                                   return_value=USAGE._empty_codex()), \
                 mock.patch.object(USAGE, "scan_gemini",
                                   return_value=USAGE._empty_gemini()), \
                 mock.patch.object(USAGE, "scan_qoder",
                                   return_value=USAGE._empty_qoder()), \
                 mock.patch.object(USAGE, "scan_qoder_ide",
                                   return_value=USAGE._empty_qoder_ide()), \
                 mock.patch.object(USAGE, "scan_hermes",
                                   return_value=USAGE._empty_hermes()), \
                 mock.patch.object(USAGE, "scan_zcode",
                                   return_value=USAGE._empty_zcode()), \
                 mock.patch.object(USAGE, "scan_mimocode",
                                   return_value=USAGE._empty_mimocode()), \
                 mock.patch.object(USAGE, "scan_openclaw",
                                   return_value=USAGE._empty_openclaw()), \
                 mock.patch.object(USAGE, "scan_pi",
                                   return_value=USAGE._empty_pi()), \
                 mock.patch.object(USAGE, "scan_workbuddy",
                                   return_value=USAGE._empty_workbuddy()), \
                 mock.patch.object(USAGE, "scan_workbuddy_ai",
                                   return_value=USAGE._empty_workbuddy()), \
                 mock.patch.object(USAGE, "scan_opencode",
                                   return_value=USAGE._empty_opencode()), \
                 mock.patch.object(USAGE, "scan_qwencode",
                                   return_value=USAGE._empty_qwencode()), \
                 mock.patch.object(USAGE, "scan_claude_plan", return_value={}):
                result = USAGE.compute()

        grok = result["grok"]
        self.assertEqual(grok["pct"], 12.5)
        self.assertEqual(grok["reset"], 1_784_622_246)
        self.assertEqual(grok["plan"], "SuperGrok")
        self.assertEqual(grok["source"], "live")
        self.assertEqual(grok["window"], "week")
        self.assertEqual(grok["products"][1]["name"], "Api")
        self.assertEqual(grok["products"][1]["pct"], 2.5)
        self.assertEqual(grok["model"], "grok-4.5")


if __name__ == "__main__":
    unittest.main()
