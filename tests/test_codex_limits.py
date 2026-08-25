import builtins
import atexit
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "usage.30s.py"

# usage.30s.py 在导入时就把 HOME 展开成 ~/.codex、~/.tokei/ledger.json 等路径常量,
# 必须在 exec_module 之前换成沙箱,否则真实账本会把毕生用量并进 scan 结果。
_SANDBOX_HOME = tempfile.mkdtemp(prefix="tokei-test-home-")
os.environ["HOME"] = _SANDBOX_HOME
os.environ["USERPROFILE"] = _SANDBOX_HOME
atexit.register(shutil.rmtree, _SANDBOX_HOME, True)

SPEC = importlib.util.spec_from_file_location("tokei_usage", SCRIPT)
USAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(USAGE)

# ledger_reconcile 会兜底回填"仅账本有"的天,进程内缓存不清会让前一个用例的天数漏进后一个。
_TESTCASE_RUN = unittest.TestCase.run


def _run_with_clean_ledger(self, *args, **kwargs):
    USAGE._LEDGER_CACHE["data"] = None
    USAGE._LEDGER_CACHE["dirty"] = False
    return _TESTCASE_RUN(self, *args, **kwargs)


unittest.TestCase.run = _run_with_clean_ledger


class _Response:
    def __init__(self, payload, url=None):
        self.payload = json.dumps(payload).encode()
        self.url = url or USAGE._CODEX_USAGE_URL

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def geturl(self):
        return self.url

    def read(self, limit):
        return self.payload[:limit]


class CodexQuotaValuesTests(unittest.TestCase):
    def setUp(self):
        self.patchers = [
            mock.patch.object(USAGE, "_codex_uses_non_openai_provider", return_value=False),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_legacy_primary_5h_secondary_week(self):
        limits = {
            "primary": {"used_percent": 25.0, "window_minutes": 300, "resets_at": 200},
            "secondary": {"used_percent": 40.0, "window_minutes": 10080, "resets_at": 300},
        }

        self.assertEqual(
            USAGE._codex_quota_values(limits, now_epoch=100),
            {"p5": 25.0, "pw": 40.0, "r5": 200, "rw": 300,
             "p5_stale": False, "pw_stale": False},
        )

    def test_week_only_primary(self):
        limits = {
            "primary": {"used_percent": 1.0, "window_minutes": 10080, "resets_at": 300},
            "secondary": None,
        }

        self.assertEqual(
            USAGE._codex_quota_values(limits, now_epoch=100),
            {"p5": None, "pw": 1.0, "r5": None, "rw": 300,
             "p5_stale": False, "pw_stale": False},
        )

    def test_expired_window_without_usage_is_reset(self):
        limits = {
            "primary": {"used_percent": 90.0, "window_minutes": 10080, "resets_at": 99},
        }

        self.assertEqual(
            USAGE._codex_quota_values(limits, now_epoch=100, consumed={"pw": 0}),
            {"p5": None, "pw": 0.0, "r5": None, "rw": None,
             "p5_stale": False, "pw_stale": False},
        )

    def test_expired_window_with_usage_is_stale(self):
        limits = {
            "primary": {"used_percent": 90.0, "window_minutes": 10080, "resets_at": 99},
        }

        self.assertEqual(
            USAGE._codex_quota_values(limits, now_epoch=100, consumed={"pw": 12345}),
            {"p5": None, "pw": 90.0, "r5": None, "rw": 99,
             "p5_stale": False, "pw_stale": True},
        )

    def test_expired_window_without_consumption_data_is_stale(self):
        limits = {
            "primary": {"used_percent": 90.0, "window_minutes": 10080, "resets_at": 99},
        }

        self.assertEqual(
            USAGE._codex_quota_values(limits, now_epoch=100, consumed=None),
            {"p5": None, "pw": 90.0, "r5": None, "rw": 99,
             "p5_stale": False, "pw_stale": True},
        )

    def test_live_quota_rejects_cross_origin_redirect(self):
        payload = {
            "rate_limit": {
                "primary_window": {
                    "used_percent": 25,
                    "limit_window_seconds": 604800,
                    "reset_at": 200,
                },
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            auth_path = Path(temp_dir) / "auth.json"
            cache_path = Path(temp_dir) / "cache.json"
            auth_path.write_text(json.dumps({
                "tokens": {
                    "access_token": "test-token",
                    "account_id": "test-account",
                },
            }))
            response = _Response(payload, url="https://example.com/usage")
            with mock.patch.object(USAGE, "CODEX_AUTH", str(auth_path)), \
                    mock.patch.object(USAGE, "CODEX_QUOTA_CACHE", str(cache_path)), \
                    mock.patch("urllib.request.urlopen", return_value=response):
                self.assertIsNone(USAGE.fetch_codex_live_limits())

    def test_live_quota_uses_initial_request_only_credentials(self):
        payload = {
            "rate_limit": {
                "primary_window": {
                    "used_percent": 25,
                    "limit_window_seconds": 604800,
                    "reset_at": 200,
                },
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            auth_path = Path(temp_dir) / "auth.json"
            cache_path = Path(temp_dir) / "cache.json"
            auth_path.write_text(json.dumps({
                "tokens": {
                    "access_token": "test-token",
                    "account_id": "test-account",
                },
            }))
            opener = mock.Mock(return_value=_Response(payload))
            with mock.patch.object(USAGE, "CODEX_AUTH", str(auth_path)), \
                    mock.patch.object(USAGE, "CODEX_QUOTA_CACHE", str(cache_path)), \
                    mock.patch("urllib.request.urlopen", opener):
                limits, _, _ = USAGE.fetch_codex_live_limits()

        request = opener.call_args.args[0]
        self.assertNotIn("Authorization", request.headers)
        self.assertEqual(
            request.unredirected_hdrs["Authorization"],
            "Bearer test-token",
        )
        self.assertEqual(limits["primary"]["used_percent"], 25.0)

    def test_recent_failure_uses_active_official_cache(self):
        now = USAGE.datetime.now().timestamp()
        auth = {
            "tokens": {
                "access_token": "test-token",
                "account_id": "test-account",
            },
        }
        account_key = USAGE._codex_auth_context(auth)["account_key"]
        limits = {
            "primary": {
                "used_percent": 69.0,
                "window_minutes": 10080,
                "resets_at": int(now + 3 * 24 * 3600),
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "cache.json"
            auth_path = Path(temp_dir) / "auth.json"
            auth_path.write_text(json.dumps(auth))
            cache_path.write_text(json.dumps({
                "fetched_at": now - 3600,
                "last_failure_at": now,
                "limits": limits,
                "plan": "pro",
                "account_key": account_key,
            }))
            with mock.patch.object(USAGE, "CODEX_AUTH", str(auth_path)), \
                    mock.patch.object(USAGE, "CODEX_QUOTA_CACHE", str(cache_path)), \
                    mock.patch("urllib.request.urlopen") as opener:
                cached_limits, plan, fetched_at = USAGE.fetch_codex_live_limits()

        opener.assert_not_called()
        self.assertEqual(cached_limits["primary"]["used_percent"], 69.0)
        self.assertEqual(plan, "pro")
        self.assertEqual(fetched_at, now - 3600)

    def test_recent_failure_rejects_cache_after_window_reset(self):
        now = USAGE.datetime.now().timestamp()
        auth = {
            "tokens": {
                "access_token": "test-token",
                "account_id": "test-account",
            },
        }
        account_key = USAGE._codex_auth_context(auth)["account_key"]
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "cache.json"
            auth_path = Path(temp_dir) / "auth.json"
            auth_path.write_text(json.dumps(auth))
            cache_path.write_text(json.dumps({
                "fetched_at": now - 3600,
                "last_failure_at": now,
                "limits": {
                    "primary": {
                        "used_percent": 69.0,
                        "window_minutes": 10080,
                        "resets_at": int(now - 1),
                    },
                },
                "plan": "pro",
                "account_key": account_key,
            }))
            with mock.patch.object(USAGE, "CODEX_AUTH", str(auth_path)), \
                    mock.patch.object(USAGE, "CODEX_QUOTA_CACHE", str(cache_path)):
                self.assertIsNone(USAGE.fetch_codex_live_limits())

    def test_official_cache_is_scoped_to_codex_account(self):
        now = USAGE.datetime.now().timestamp()
        auth = {
            "tokens": {
                "access_token": "test-token",
                "account_id": "current-account",
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "cache.json"
            auth_path = Path(temp_dir) / "auth.json"
            auth_path.write_text(json.dumps(auth))
            cache_path.write_text(json.dumps({
                "fetched_at": now - 3600,
                "last_failure_at": now,
                "limits": {
                    "primary": {
                        "used_percent": 69.0,
                        "window_minutes": 10080,
                        "resets_at": int(now + 3600),
                    },
                },
                "account_key": "different-account",
            }))
            with mock.patch.object(USAGE, "CODEX_AUTH", str(auth_path)), \
                    mock.patch.object(USAGE, "CODEX_QUOTA_CACHE", str(cache_path)), \
                    mock.patch("urllib.request.urlopen", side_effect=OSError("offline")):
                self.assertIsNone(USAGE.fetch_codex_live_limits())

    def test_newer_local_snapshot_wins_over_stale_official_cache(self):
        self.assertFalse(USAGE._codex_live_snapshot_is_current(
            1_700_000_000, "2023-11-14T22:13:21+00:00"))
        self.assertTrue(USAGE._codex_live_snapshot_is_current(
            1_700_000_002, "2023-11-14T22:13:21+00:00"))


def _epoch(year, month, day, hour=0, minute=0):
    return int(datetime(year, month, day, hour, minute).timestamp())


class CodexUsedSinceTests(unittest.TestCase):
    def days(self):
        boundary = [0] * 24
        boundary[3] = 40
        boundary[9] = 80
        later = [0] * 24
        later[1] = 230
        return {
            "2026-08-09": {"in": 500, "out": 50, "hours": [0] * 24},
            "2026-08-10": {"in": 100, "out": 20, "hours": boundary},
            "2026-08-11": {"in": 200, "out": 30, "hours": later},
        }

    def test_boundary_day_is_sliced_from_the_reset_hour(self):
        self.assertEqual(
            USAGE._codex_used_since(self.days(), _epoch(2026, 8, 10, 6)), 310)

    def test_reset_at_midnight_keeps_the_whole_boundary_day(self):
        self.assertEqual(
            USAGE._codex_used_since(self.days(), _epoch(2026, 8, 10)), 350)

    def test_reset_in_the_future_reports_no_usage(self):
        self.assertEqual(
            USAGE._codex_used_since(self.days(), _epoch(2026, 8, 12)), 0)

    def test_boundary_day_without_hours_counts_the_whole_day(self):
        days = self.days()
        days["2026-08-10"].pop("hours")

        self.assertEqual(
            USAGE._codex_used_since(days, _epoch(2026, 8, 10, 6)), 350)

    def test_missing_reset_time_is_unknown_not_zero(self):
        self.assertIsNone(USAGE._codex_used_since(self.days(), None))


class CodexScanFreshnessTests(unittest.TestCase):
    RESET = _epoch(2024, 1, 8, 2)

    def token_count(self, hour, minute, total, last, rate_limits=None):
        payload = {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": total[0],
                    "cached_input_tokens": total[1],
                    "output_tokens": total[2],
                    "reasoning_output_tokens": total[3],
                },
                "last_token_usage": {
                    "input_tokens": last[0],
                    "cached_input_tokens": last[1],
                    "output_tokens": last[2],
                    "reasoning_output_tokens": last[3],
                },
            },
        }
        if rate_limits:
            payload["rate_limits"] = rate_limits
        return json.dumps({
            "timestamp": datetime(2024, 1, 8, hour, minute).astimezone().isoformat(),
            "type": "event_msg",
            "payload": payload,
        })

    def bounds(self):
        day = datetime(2024, 1, 8, tzinfo=timezone.utc)
        return {
            "today": day,
            "yesterday": day - timedelta(days=1),
            "week": day,
            "last_week": day - timedelta(days=7),
            "last_week_end": day,
            "month": day.replace(day=1),
            "year": day.replace(month=1, day=1),
        }

    def scan(self, tmp):
        limits = {
            "limit_id": "codex",
            "plan_type": "pro",
            "primary": {"used_percent": 90.0, "window_minutes": 10080,
                        "resets_at": self.RESET},
            "secondary": None,
        }
        path = Path(tmp) / "rollout-freshness.jsonl"
        path.write_text("\n".join([
            json.dumps({
                "timestamp": "2024-01-08T00:00:00Z",
                "type": "session_meta",
                "payload": {"id": "freshness", "cwd": "/tmp/project"},
            }),
            self.token_count(0, 30, (100, 80, 10, 4), (100, 80, 10, 4),
                             rate_limits=limits),
            self.token_count(5, 0, (150, 120, 15, 6), (50, 40, 5, 2)),
        ]) + "\n", encoding="utf-8")

        with mock.patch.object(USAGE, "CODEX_DIR", tmp), \
                mock.patch.object(USAGE, "CODEX_ARCHIVED_DIR",
                                  str(Path(tmp) / "archived_sessions")), \
                mock.patch.object(USAGE, "fetch_codex_live_limits", return_value=None):
            return USAGE.scan_codex(self.bounds(), {"v": USAGE._SCAN_CACHE_VERSION})

    def test_scan_reports_reading_time_and_usage_since_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.scan(tmp)

        self.assertEqual(result["limits_updated"], _epoch(2024, 1, 8, 0, 30))
        # 重置点在 02:00,只有 05:00 那笔(50 输入 + 5 输出)算在窗口翻篇之后
        self.assertEqual(result["limits_consumed"], {"p5": None, "pw": 55})

    def test_expired_reading_with_usage_is_reported_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.scan(tmp)

        values = USAGE._codex_quota_values(
            result["limits"], now_epoch=self.RESET + 3600,
            consumed=result["limits_consumed"])

        self.assertTrue(values["pw_stale"])
        self.assertEqual(values["pw"], 90.0)
        self.assertEqual(values["rw"], self.RESET)


class CodexCustomProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config_path = Path(self.tmp.name) / "config.toml"
        self.quota_cache_path = Path(self.tmp.name) / "quota_cache.json"
        self.reset_cards_cache_path = Path(self.tmp.name) / "reset_cards_cache.json"
        self.auth_path = Path(self.tmp.name) / "auth.json"
        self.auth_path.write_text(json.dumps({
            "tokens": {"access_token": "test-token", "account_id": "test-account"}
        }))
        self.patchers = [
            mock.patch.object(USAGE, "CODEX_CONFIG", str(self.config_path)),
            mock.patch.object(USAGE, "CODEX_QUOTA_CACHE", str(self.quota_cache_path)),
            mock.patch.object(USAGE, "CODEX_RESET_CARDS_CACHE", str(self.reset_cards_cache_path)),
            mock.patch.object(USAGE, "CODEX_AUTH", str(self.auth_path)),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _write_config(self, text):
        self.config_path.write_text(text)

    def test_uses_non_openai_provider_with_explicit_custom(self):
        self._write_config('model_provider = "custom"\nmodel = "deepseek-v4-flash"\n')
        self.assertTrue(USAGE._codex_uses_non_openai_provider())

    def test_does_not_use_non_openai_provider_with_openai(self):
        self._write_config('model_provider = "openai"\nmodel = "gpt-5.5"\n')
        self.assertFalse(USAGE._codex_uses_non_openai_provider())

    def test_does_not_use_non_openai_provider_without_config(self):
        self.assertFalse(USAGE._codex_uses_non_openai_provider())

    def test_declared_but_unused_provider_block_stays_official(self):
        # 只准备了 provider 段、没把 model_provider 指过去的人还在用官方额度，
        # 误判成第三方会把他们的额度卡整块藏掉。
        self._write_config('[model_providers.packycode]\nbase_url = "https://x"\n')
        self.assertFalse(USAGE._codex_uses_non_openai_provider())

    def test_custom_provider_detected_without_tomllib(self):
        # macOS 自带的 /usr/bin/python3 是 3.9，没有 tomllib；模块级 import 会让
        # 整个脚本崩掉，所以走惰性导入 + 回退解析，这里锁住回退路径。
        self._write_config('model_provider = "packycode"\n'
                           '[model_providers.packycode]\nbase_url = "https://x"\n')
        real_import = builtins.__import__

        def no_tomllib(name, *args, **kwargs):
            if name == "tomllib":
                raise ImportError("no tomllib on 3.9")
            return real_import(name, *args, **kwargs)

        with mock.patch.object(builtins, "__import__", side_effect=no_tomllib):
            self.assertEqual(USAGE._codex_config()["model_provider"], "packycode")
            self.assertTrue(USAGE._codex_uses_non_openai_provider())

    def test_live_quota_remains_available_for_custom_provider(self):
        self._write_config(
            'model_provider = "custom"\n'
            '[model_providers.custom]\n'
            'name = "OpenAI"\n'
            'requires_openai_auth = true\n'
            'supports_websockets = true\n'
            'wire_api = "responses"\n'
        )
        payload = {
            "rate_limit": {
                "primary_window": {
                    "used_percent": 7,
                    "limit_window_seconds": 604800,
                    "reset_at": 200,
                },
            },
            "plan_type": "plus",
        }
        opener = mock.Mock(return_value=_Response(payload))
        with mock.patch("urllib.request.urlopen", opener):
            limits, plan, _ = USAGE.fetch_codex_live_limits()
        self.assertEqual(limits["primary"]["used_percent"], 7.0)
        self.assertEqual(limits["primary"]["window_minutes"], 10080)
        self.assertEqual(plan, "plus")
        opener.assert_called_once()
        self.assertTrue(self.quota_cache_path.exists())

    def test_scan_uses_live_quota_but_not_custom_provider_usage(self):
        path = Path(self.tmp.name) / "rollout-custom.jsonl"
        path.write_text("\n".join([
            json.dumps({
                "timestamp": "2026-08-25T00:00:00Z",
                "type": "session_meta",
                "payload": {"id": "custom-provider", "cwd": "/tmp/project"},
            }),
            json.dumps({
                "timestamp": "2026-08-25T00:01:00Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "last_token_usage": {
                            "input_tokens": 100,
                            "cached_input_tokens": 20,
                            "output_tokens": 10,
                            "reasoning_output_tokens": 2,
                        },
                    },
                },
            }),
        ]) + "\n")
        live_limits = {
            "limit_id": "codex",
            "plan_type": "plus",
            "primary": {
                "used_percent": 7.0,
                "window_minutes": 10080,
                "resets_at": 200,
            },
            "secondary": None,
        }
        bounds = {
            "today": datetime(2026, 8, 25, tzinfo=timezone.utc),
            "yesterday": datetime(2026, 8, 24, tzinfo=timezone.utc),
            "week": datetime(2026, 8, 25, tzinfo=timezone.utc),
            "last_week": datetime(2026, 8, 18, tzinfo=timezone.utc),
            "last_week_end": datetime(2026, 8, 25, tzinfo=timezone.utc),
            "month": datetime(2026, 8, 1, tzinfo=timezone.utc),
            "year": datetime(2026, 1, 1, tzinfo=timezone.utc),
        }
        with mock.patch.object(USAGE, "CODEX_DIR", self.tmp.name), \
                mock.patch.object(USAGE, "CODEX_ARCHIVED_DIR",
                                  str(Path(self.tmp.name) / "archived_sessions")), \
                mock.patch.object(USAGE, "_codex_uses_non_openai_provider", return_value=True), \
                mock.patch.object(
                    USAGE, "fetch_codex_live_limits",
                    return_value=(live_limits, "plus", datetime.now().timestamp())):
            result = USAGE.scan_codex(bounds, {"v": USAGE._SCAN_CACHE_VERSION})
        self.assertEqual(result["limits"], live_limits)
        self.assertEqual(result["plan"], "plus")
        self.assertIsNone(result["limits_consumed"])

    def test_reset_cards_survive_for_custom_provider(self):
        # 重置卡挂在 OpenAI 账号上，临时切到第三方中转不会让卡消失；
        # 按 provider 屏蔽会既藏掉卡、又删掉本地缓存。
        self._write_config('model_provider = "custom"\n')
        now = 1_785_000_000
        auth_context = USAGE._codex_auth_context(json.loads(self.auth_path.read_text()))
        self.reset_cards_cache_path.write_text(json.dumps({
            "account_key": auth_context["account_key"],
            "auth_key": auth_context["auth_key"],
            "next_attempt_at": now + 3600,
            "cards": {"count": 1, "expires": [now + 86400], "updated": now - 60},
        }))
        opener = mock.Mock(side_effect=AssertionError("should not call API"))
        with mock.patch("urllib.request.urlopen", opener):
            cards = USAGE.fetch_codex_reset_cards(now_epoch=now)
        self.assertEqual(cards["count"], 1)
        self.assertEqual(cards["expires"], [now + 86400])
        self.assertTrue(self.reset_cards_cache_path.exists())

    def test_iter_records_parses_token_count_with_ordinal_field(self):
        """Custom-provider Codex logs insert an 'ordinal' field between timestamp and type."""
        session_path = Path(self.tmp.name) / "rollout-ordinal.jsonl"
        session_path.write_text(json.dumps({
            "timestamp": "2026-08-07T08:00:01.000Z",
            "ordinal": 0,
            "type": "session_meta",
            "payload": {"model": "deepseek-v4-flash"}
        }) + "\n" + json.dumps({
            "timestamp": "2026-08-07T08:00:04.000Z",
            "ordinal": 18,
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 1000,
                        "cached_input_tokens": 800,
                        "output_tokens": 200,
                        "reasoning_output_tokens": 50,
                    }
                }
            }
        }) + "\n")
        records = list(USAGE._iter_codex_usage_records(str(session_path)))
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0], ("model", "deepseek-v4-flash"))
        self.assertEqual(records[1][0], "token")


if __name__ == "__main__":
    unittest.main()
