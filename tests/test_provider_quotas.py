import base64
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

try:
    from .test_codex_limits import USAGE
except ImportError:
    from test_codex_limits import USAGE


def _jwt(payload):
    def encode(value):
        raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return f"{encode({'alg': 'none'})}.{encode(payload)}.signature"


class ProviderQuotaTests(unittest.TestCase):
    def setUp(self):
        self.old_user_dir = USAGE._USER_DIR
        self.old_cache = getattr(USAGE, "PROVIDER_QUOTA_CACHE", None)
        self.old_scan_cache = getattr(USAGE, "ANTIGRAVITY_SCAN_CACHE", None)
        self.old_credentials_cache = USAGE.ANTIGRAVITY_CREDENTIALS_CACHE
        self.old_env = dict(USAGE.os.environ)

    def tearDown(self):
        USAGE._USER_DIR = self.old_user_dir
        if self.old_cache is not None:
            USAGE.PROVIDER_QUOTA_CACHE = self.old_cache
        if self.old_scan_cache is not None:
            USAGE.ANTIGRAVITY_SCAN_CACHE = self.old_scan_cache
        USAGE.ANTIGRAVITY_CREDENTIALS_CACHE = self.old_credentials_cache
        USAGE.os.environ.clear()
        USAGE.os.environ.update(self.old_env)

    def isolate_cache(self, root):
        USAGE._USER_DIR = str(root)
        USAGE.PROVIDER_QUOTA_CACHE = str(root / "provider_quota_cache.json")
        USAGE.ANTIGRAVITY_SCAN_CACHE = str(root / "antigravity_scan_cache.json")
        USAGE.ANTIGRAVITY_CREDENTIALS_CACHE = str(root / "antigravity_credentials.json")

    def test_provider_queries_are_opt_in_except_local_antigravity(self):
        with tempfile.TemporaryDirectory() as tmp:
            USAGE._USER_DIR = tmp
            Path(tmp, "config.json").write_text("{}", encoding="utf-8")
            self.assertFalse(USAGE._provider_quota_enabled("cursor"))
            self.assertFalse(USAGE._provider_quota_enabled("grok_bot"))
            self.assertFalse(USAGE._provider_quota_enabled("zed"))
            self.assertFalse(USAGE._provider_quota_enabled("sub2api"))
            self.assertFalse(USAGE._provider_quota_enabled("zai"))
            self.assertTrue(USAGE._provider_quota_enabled("antigravity"))

            Path(tmp, "config.json").write_text(
                json.dumps({"cursor_quota_enabled": True}), encoding="utf-8")
            self.assertTrue(USAGE._provider_quota_enabled("cursor"))
            with mock.patch.dict(USAGE.os.environ, {"TOKEI_CURSOR_QUOTA": "0"}):
                self.assertFalse(USAGE._provider_quota_enabled("cursor"))

    def test_provider_http_does_not_follow_redirects_with_credentials(self):
        leaked = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/start":
                    self.send_response(302)
                    self.send_header("Location", "/leak")
                    self.end_headers()
                    return
                leaked.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, _format, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        with self.assertRaises(RuntimeError):
            USAGE._provider_json_request(
                f"http://127.0.0.1:{server.server_port}/start",
                headers={"Authorization": "Bearer secret"},
            )
        self.assertEqual(leaked, [])

    def test_cursor_reads_app_auth_and_maps_usage_summary(self):
        token = _jwt({
            "sub": "auth0|cursor-user",
            "email": "cursor@example.com",
            "exp": 4_000_000_000,
        })
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp, "state.vscdb")
            connection = sqlite3.connect(db_path)
            connection.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
            connection.execute(
                "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
                ("cursorAuth/accessToken", token),
            )
            connection.commit()
            connection.close()

            session = USAGE._cursor_app_session(str(db_path), now_epoch=1_800_000_000)

        self.assertEqual(session["account"], "cursor@example.com")
        self.assertIn("WorkosCursorSessionToken=cursor-user%3A%3A", session["cookie"])
        summary = {
            "billingCycleStart": "2026-08-01T00:00:00Z",
            "billingCycleEnd": "2026-09-01T00:00:00Z",
            "membershipType": "pro",
            "individualUsage": {
                "plan": {
                    "used": 388,
                    "limit": 2000,
                    "totalPercentUsed": 19.4,
                    "autoPercentUsed": 12.5,
                    "apiPercentUsed": 7.5,
                },
                "onDemand": {"enabled": True, "used": 450, "limit": 1000},
            },
        }
        quota = USAGE._normalize_cursor_quota(summary, identity=session, updated=1_800_000_000)

        self.assertTrue(quota["available"])
        self.assertEqual(quota["plan"], "Cursor Pro")
        self.assertEqual([row["id"] for row in quota["windows"]], ["cursor-auto", "cursor-api"])
        self.assertEqual([row["used_pct"] for row in quota["windows"]], [12.5, 7.5])
        self.assertEqual(quota["windows"][0]["reset"], 1_788_220_800)
        self.assertEqual(quota["details"][0]["value"], "$3.88 / $20.00")
        self.assertEqual(quota["details"][1]["value"], "$4.50 / $10.00")
        self.assertIsNone(quota["windows"][1]["detail"])

    def test_cursor_total_spend_uses_percent_when_plan_used_is_allotment(self):
        quota = USAGE._normalize_cursor_quota({
            "membershipType": "pro_plus",
            "individualUsage": {
                "plan": {
                    "used": 7000,
                    "limit": 7000,
                    "totalPercentUsed": 8.365737,
                    "autoPercentUsed": 7.173333,
                    "apiPercentUsed": 24.0,
                },
            },
        })

        self.assertEqual([row["id"] for row in quota["windows"]], ["cursor-auto", "cursor-api"])
        self.assertIsNone(quota["windows"][1]["detail"])
        self.assertEqual(quota["details"][0]["value"], "$16.80 / $70.00")
        self.assertEqual([row["used_pct"] for row in quota["windows"]], [7.173333, 24.0])

    def test_cursor_legacy_request_quota_overrides_token_percent(self):
        summary = {
            "membershipType": "pro",
            "individualUsage": {
                "plan": {"used": 500, "limit": 1000, "totalPercentUsed": 50},
            },
        }
        legacy = {"gpt-4": {"numRequestsTotal": 240, "maxRequestUsage": 500}}
        quota = USAGE._normalize_cursor_quota(summary, request_usage=legacy)

        self.assertEqual(len(quota["windows"]), 1)
        self.assertEqual(quota["windows"][0]["used_pct"], 48.0)
        self.assertEqual(quota["windows"][0]["detail"], "240 / 500 requests")

    def test_cursor_fetch_uses_cookie_and_normalized_legacy_user_id(self):
        session = {
            "cookie": "WorkosCursorSessionToken=cursor-user%3A%3Atoken",
            "account": "cursor@example.com",
            "subject": "auth0|cursor-user",
            "user_id": "cursor-user",
            "marker": "cursor-marker",
        }
        requests = []

        def request(url, **kwargs):
            requests.append((url, kwargs))
            self.assertEqual(
                kwargs["headers"]["Cookie"],
                "WorkosCursorSessionToken=cursor-user%3A%3Atoken",
            )
            if url.endswith("/api/usage-summary"):
                return {
                    "membershipType": "pro",
                    "individualUsage": {"plan": {"used": 100, "limit": 1000}},
                }
            if url.endswith("/api/auth/me"):
                return {"sub": "auth0|cursor-user", "email": "cursor@example.com"}
            if "/api/usage?" in url:
                self.assertTrue(url.endswith("user=cursor-user"), url)
                return {"gpt-4": {"numRequestsTotal": 24, "maxRequestUsage": 100}}
            if url.endswith("/api/dashboard/get-filtered-usage-events"):
                self.assertEqual(kwargs["method"], "POST")
                return {"totalUsageEventsCount": 0, "usageEventsDisplay": []}
            self.assertEqual(kwargs["method"], "POST")
            self.assertEqual(kwargs["headers"]["Origin"], "https://cursor.com")
            return {"hasNonZeroIncludedLimit": False}

        with tempfile.TemporaryDirectory() as tmp:
            self.isolate_cache(Path(tmp))
            with mock.patch.object(USAGE, "_provider_json_request", side_effect=request):
                quota = USAGE.fetch_cursor_quota(session)

        self.assertEqual(quota["windows"][0]["used_pct"], 24.0)
        self.assertEqual(len(requests), 5)
        self.assertEqual(quota["usage"]["ranges"]["today"]["tokens"], 0)

    def test_cursor_usage_events_map_tokens_cost_and_models(self):
        now = datetime.now().astimezone().replace(hour=12, minute=0, second=0, microsecond=0)
        events = [
            {
                "timestamp": str(int(now.timestamp() * 1000)),
                "model": "gpt-5.6-sol-medium",
                "tokenUsage": {
                    "inputTokens": 100, "outputTokens": 20,
                    "cacheReadTokens": 30, "cacheWriteTokens": 10,
                    "totalCents": 12.5,
                },
            },
            {
                "timestamp": int(now.timestamp() * 1000),
                "model": "gpt-5.6-sol-medium",
                "tokenUsage": {
                    "inputTokens": 40, "outputTokens": 5,
                    "cacheReadTokens": 0, "cacheWriteTokens": 0,
                    "totalCents": "2.5",
                },
            },
        ]

        usage = USAGE._normalize_cursor_usage_events(events, bounds=USAGE.range_bounds())
        today = usage["ranges"]["today"]

        self.assertEqual(today["tokens"], 205)
        self.assertEqual(today["in"], 140)
        self.assertEqual(today["out"], 25)
        self.assertEqual(today["cr"], 30)
        self.assertEqual(today["cw"], 10)
        self.assertEqual(today["requests"], 2)
        self.assertAlmostEqual(today["cost"], 0.15)
        self.assertEqual(today["models"][0]["name"], "GPT-5.6 Sol")
        self.assertEqual(today["models"][0]["tokens"], 205)

    def test_zed_maps_limited_and_unlimited_prediction_plans(self):
        payload = {
            "user": {"id": 42, "github_login": "octocat", "name": "Octo Cat"},
            "plan": {
                "plan_v3": "zed_pro",
                "subscription_period": {
                    "started_at": "2026-08-01T00:00:00Z",
                    "ended_at": "2026-09-01T00:00:00Z",
                },
                "usage": {"edit_predictions": {"used": 12, "limit": {"limited": 50}}},
                "has_overdue_invoices": False,
            },
        }
        quota = USAGE._normalize_zed_quota(payload, updated=1_800_000_000)

        self.assertEqual(quota["plan"], "Zed Pro")
        self.assertEqual(quota["account"], "octocat")
        self.assertEqual(quota["windows"][0]["used_pct"], 24.0)
        self.assertEqual(quota["windows"][0]["detail"], "12 / 50 predictions")

        payload["plan"]["usage"]["edit_predictions"]["limit"] = "unlimited"
        unlimited = USAGE._normalize_zed_quota(payload)
        self.assertEqual(unlimited["windows"][0]["used_pct"], 0.0)
        self.assertEqual(unlimited["windows"][0]["detail"], "Unlimited")

    def test_zed_lists_plans_for_each_organization(self):
        payload = {
            "user": {"github_login": "octocat", "name": "Octo Cat"},
            "default_organization_id": 10,
            "organizations": [
                {"id": 10, "name": "Octo's Organization", "is_personal": True},
                {"id": 20, "name": "Zed VIP", "is_personal": False},
            ],
            "plans_by_organization": {
                "10": "zed_student",
                "20": "zed_vip",
            },
            "plan": {
                "plan_v3": "zed_student",
                "usage": {"edit_predictions": {"used": 2, "limit": {"limited": 10}}},
            },
        }

        quota = USAGE._normalize_zed_quota(payload)

        self.assertEqual(quota["plan"], "Zed Student + Zed VIP")
        self.assertEqual(quota["details"], [
            {"label": "账号", "value": "Octo Cat"},
            {
                "label": "Octo's Organization",
                "value": "Zed Student",
                "secondary": "当前组织",
            },
            {"label": "Zed VIP", "value": "Zed VIP"},
        ])
        self.assertEqual(quota["windows"][0]["used_pct"], 20.0)

    def test_zed_settings_reject_cross_origin_credentials(self):
        trusted = USAGE._zed_connection_settings({
            "credentials_url": "zed-preview-key",
            "server_url": "https://zed.dev",
        })
        self.assertEqual(trusted["service"], "zed-preview-key")
        self.assertEqual(trusted["api_url"], "https://cloud.zed.dev/client/users/me")
        self.assertIsNone(USAGE._zed_connection_settings({
            "credentials_url": "https://zed.dev",
            "server_url": "https://attacker.example.com",
        }))
        self.assertIsNone(USAGE._zed_connection_settings({
            "server_url": "http://localhost:3000",
        }))

    def test_zed_fetch_sends_native_authorization_header(self):
        payload = {
            "user": {"id": 42, "github_login": "octocat", "name": None},
            "plan": {
                "plan_v3": "zed_pro",
                "subscription_period": None,
                "usage": {"edit_predictions": {"used": 1, "limit": {"limited": 10}}},
                "has_overdue_invoices": False,
            },
        }

        def request(url, **kwargs):
            self.assertEqual(url, "https://cloud.zed.dev/client/users/me")
            self.assertEqual(kwargs["headers"]["Authorization"], "42 zed-token")
            self.assertEqual(kwargs["headers"]["User-Agent"], "Tokei/1.0")
            return payload

        with tempfile.TemporaryDirectory() as tmp:
            self.isolate_cache(Path(tmp))
            with mock.patch.dict(USAGE.os.environ, {
                "TOKEI_ZED_USER_ID": "42",
                "TOKEI_ZED_ACCESS_TOKEN": "zed-token",
            }), mock.patch.object(USAGE, "_load_zed_connection_settings", return_value={
                "service": "https://zed.dev",
                "api_url": "https://cloud.zed.dev/client/users/me",
            }), mock.patch.object(USAGE, "_provider_json_request", side_effect=request):
                quota = USAGE.fetch_zed_quota()

        self.assertEqual(quota["windows"][0]["used_pct"], 10.0)

    def test_sub2api_validates_url_and_maps_subscription_windows(self):
        self.assertEqual(
            USAGE._sub2api_usage_url("https://api.example.com", timezone_name="Asia/Taipei"),
            "https://api.example.com/v1/usage?days=30&timezone=Asia%2FTaipei",
        )
        self.assertEqual(
            USAGE._sub2api_usage_url("http://127.0.0.1:8080/v1", timezone_name="UTC"),
            "http://127.0.0.1:8080/v1/usage?days=30&timezone=UTC",
        )
        self.assertIsNone(USAGE._sub2api_usage_url("http://api.example.com"))
        self.assertIsNone(USAGE._sub2api_usage_url("https://user:pass@api.example.com"))

        quota = USAGE._normalize_sub2api_quota({
            "mode": "unrestricted",
            "isValid": True,
            "planName": "Claude Team",
            "balance": 42.5,
            "unit": "USD",
            "subscription": {
                "daily_usage_usd": 2,
                "weekly_usage_usd": 10,
                "monthly_usage_usd": 30,
                "daily_limit_usd": 10,
                "weekly_limit_usd": 40,
                "monthly_limit_usd": 100,
                "expires_at": "2026-09-01T00:00:00Z",
            },
            "usage": {
                "today": {"requests": 4, "total_tokens": 1200, "actual_cost": 1.25},
            },
        })

        self.assertEqual(quota["plan"], "Claude Team")
        self.assertEqual([row["used_pct"] for row in quota["windows"][:3]], [20.0, 25.0, 30.0])
        self.assertEqual(quota["details"][0]["value"], "$42.50")
        self.assertEqual(quota["details"][2]["value"], "1,200")
        self.assertEqual(quota["details"][2]["secondary"], "$1.25")

    def test_sub2api_fetch_sends_bearer_key_to_normalized_usage_url(self):
        def request(url, **kwargs):
            self.assertIn("/v1/usage?days=30&timezone=", url)
            self.assertEqual(kwargs["headers"]["Authorization"], "Bearer group-key")
            self.assertEqual(kwargs["timeout"], 15)
            return {"isValid": True, "balance": 5}

        with tempfile.TemporaryDirectory() as tmp:
            self.isolate_cache(Path(tmp))
            with mock.patch.dict(USAGE.os.environ, {
                "SUB2API_API_KEY": "group-key",
                "SUB2API_BASE_URL": "https://api.example.com",
            }), mock.patch.object(USAGE, "_provider_json_request", side_effect=request):
                quota = USAGE.fetch_sub2api_quota()

        self.assertEqual(quota["details"][0]["value"], "$5.00")

    def test_zai_maps_session_weekly_and_mcp_limits(self):
        payload = {
            "code": 200,
            "success": True,
            "data": {
                "planName": "Pro",
                "limits": [
                    {
                        "type": "TOKENS_LIMIT", "unit": 3, "number": 5,
                        "percentage": 25, "nextResetTime": 1_785_816_000_000,
                    },
                    {
                        "type": "TOKENS_LIMIT", "unit": 6, "number": 1,
                        "percentage": 9, "nextResetTime": 1_786_291_200_000,
                    },
                    {
                        "type": "TIME_LIMIT", "unit": 5, "number": 1,
                        "usage": 1000, "currentValue": 224, "remaining": 776,
                        "percentage": 22,
                        "usageDetails": [{"modelCode": "search-prime", "usage": 210}],
                    },
                ],
            },
        }
        quota = USAGE._normalize_zai_quota(payload, region="global", updated=1_800_000_000)

        self.assertEqual(quota["plan"], "Pro")
        self.assertEqual([row["used_pct"] for row in quota["windows"]], [25.0, 9.0, 22.4])
        self.assertEqual(quota["windows"][0]["window_minutes"], 300)
        self.assertEqual(quota["windows"][1]["window_minutes"], 10080)
        self.assertEqual(quota["windows"][2]["title"], "MCP")
        self.assertEqual(quota["details"][-1]["value"], "210")

    def test_zai_team_url_replaces_existing_type_parameter(self):
        self.assertEqual(
            USAGE._zai_quota_url(
                "https://api.z.ai/api/monitor/usage/quota/limit?keep=1&type=9",
                scope="team",
            ),
            "https://api.z.ai/api/monitor/usage/quota/limit?keep=1&type=2",
        )

    def test_zai_team_fetch_sends_scope_headers_and_type(self):
        requests = []

        def request(url, **kwargs):
            requests.append(url)
            self.assertEqual(kwargs["headers"]["Authorization"], "Bearer zai-key")
            self.assertEqual(kwargs["headers"]["Bigmodel-Organization"], "org")
            self.assertEqual(kwargs["headers"]["Bigmodel-Project"], "project")
            if "/api/monitor/usage/model-usage?" in url:
                self.assertIn("type=3", url)
                return {
                    "code": 200, "success": True,
                    "data": {"x_time": [], "modelDataList": []},
                }
            self.assertTrue(url.endswith("/api/monitor/usage/quota/limit?type=2"), url)
            return {
                "code": 200,
                "success": True,
                "data": {"limits": [
                    {"type": "TOKENS_LIMIT", "unit": 3, "number": 5, "percentage": 25},
                ]},
            }

        with tempfile.TemporaryDirectory() as tmp:
            self.isolate_cache(Path(tmp))
            with mock.patch.dict(USAGE.os.environ, {
                "Z_AI_API_KEY": "zai-key",
                "Z_AI_REGION": "global",
                "Z_AI_USAGE_SCOPE": "team",
                "Z_AI_ORGANIZATION": "org",
                "Z_AI_PROJECT": "project",
            }), mock.patch.object(USAGE, "_provider_json_request", side_effect=request):
                quota = USAGE.fetch_zai_quota()

        self.assertEqual(quota["windows"][0]["used_pct"], 25.0)
        self.assertEqual(len(requests), 2)
        self.assertEqual(quota["usage"]["ranges"]["month"]["tokens"], 0)

    def test_zai_model_usage_maps_daily_ranges_and_models(self):
        today = datetime.now().astimezone().replace(hour=8, minute=0, second=0, microsecond=0)
        yesterday = today - timedelta(days=1)
        payload = {
            "code": 200,
            "success": True,
            "data": {
                "x_time": [today.strftime("%Y-%m-%d %H:%M"),
                           yesterday.strftime("%Y-%m-%d %H:%M")],
                "modelDataList": [
                    {"modelName": "glm-5.3", "tokensUsage": [100, 50]},
                    {"modelName": "glm-4.7", "tokensUsage": [20, None]},
                ],
            },
        }

        usage = USAGE._normalize_zai_model_usage(payload, bounds=USAGE.range_bounds())

        self.assertEqual(usage["ranges"]["today"]["tokens"], 120)
        self.assertEqual(usage["ranges"]["yesterday"]["tokens"], 50)
        self.assertEqual(usage["ranges"]["all"]["tokens"], 170)
        self.assertEqual(usage["ranges"]["year"]["coverage"], "近30天")
        self.assertEqual(usage["ranges"]["today"]["models"][0], {
            "name": "Glm 5.3", "tokens": 100, "in": 0, "out": 0,
            "cr": 0, "cw": 0, "reason": 0, "cost": 0.0,
        })

    def test_antigravity_parses_process_and_quota_summary(self):
        output = """
        123 /Applications/Antigravity.app/Contents/Resources/language_server_macos_arm \
          --csrf_token language-token --app_data_dir antigravity \
          --extension_server_port 64123 --extension_server_csrf_token extension-token
        """
        processes = USAGE._antigravity_process_infos(output)
        self.assertEqual(processes[0]["pid"], 123)
        self.assertEqual(processes[0]["csrf_token"], "language-token")
        self.assertEqual(processes[0]["extension_port"], 64123)

        quota = USAGE._normalize_antigravity_quota_summary({
            "response": {
                "groups": [
                    {
                        "displayName": "Gemini Models",
                        "buckets": [
                            {
                                "bucketId": "gemini-weekly",
                                "displayName": "Weekly Limit",
                                "remaining": {"remainingFraction": 0.82},
                                "resetTime": "2026-09-01T00:00:00Z",
                            },
                            {
                                "bucketId": "gemini-5h",
                                "displayName": "Five Hour Limit",
                                "remaining": {"case": "remainingFraction", "value": 0.91},
                            },
                        ],
                    },
                    {
                        "displayName": "Claude and GPT models",
                        "buckets": [
                            {
                                "bucketId": "3p-weekly",
                                "displayName": "Weekly Limit",
                                "remaining": {"remainingFraction": 0.64},
                            },
                            {
                                "bucketId": "3p-5h",
                                "displayName": "Five Hour Limit",
                                "remaining": {"remainingFraction": 0.73},
                            },
                        ],
                    },
                ],
            },
        }, updated=1_800_000_000)

        self.assertEqual(
            [row["title"] for row in quota["windows"]],
            ["Gemini 周", "Gemini 5h", "Claude/GPT 周", "Claude/GPT 5h"],
        )
        self.assertEqual([row["used_pct"] for row in quota["windows"]], [18.0, 9.0, 36.0, 27.0])
        self.assertEqual(quota["windows"][0]["window_minutes"], 10080)
        self.assertEqual(quota["windows"][1]["window_minutes"], 300)

    def test_antigravity_flat_quota_summary_matches_live_response(self):
        quota = USAGE._normalize_antigravity_quota_summary({
            "response": {"groups": [
                {"displayName": "Gemini Models", "buckets": [
                    {"bucketId": "gemini-weekly", "remainingFraction": 0.9921567,
                     "description": "You have used some of your weekly limit.",
                     "resetTime": "2026-09-27T00:57:44Z"},
                    {"bucketId": "gemini-5h", "remainingFraction": 0.9899,
                     "description": "You have used some of your 5-hour limit."},
                ]},
                {"displayName": "Claude and GPT models", "buckets": [
                    {"bucketId": "3p-weekly", "remainingFraction": 1},
                    {"bucketId": "3p-5h", "remainingFraction": 1},
                ]},
            ]},
        })

        rows = quota["windows"]
        self.assertEqual([row["used_pct"] for row in rows], [0.78433, 1.01, 0.0, 0.0])
        self.assertTrue(all(row["usage_known"] for row in rows))
        self.assertTrue(all(row["detail"] is None for row in rows))
        self.assertIsNotNone(rows[0]["reset"])

    def test_antigravity_remaining_distinguishes_zero_full_and_unknown(self):
        for fields, used in [
            ({"remainingFraction": 0}, 100.0),
            ({"remainingFraction": 1}, 0.0),
            ({"remainingFraction": 0, "remaining": {"remainingFraction": 1}}, 100.0),
            ({"remaining": {"remainingFraction": 0}}, 100.0),
            ({"remaining": {"case": "remainingFraction", "value": 1}}, 0.0),
            ({}, None),
            ({"remainingFraction": None}, None),
            ({"remainingFraction": "invalid"}, None),
        ]:
            with self.subTest(fields=fields):
                quota = USAGE._normalize_antigravity_quota_summary({"groups": [{
                    "displayName": "Gemini Models",
                    "buckets": [{"bucketId": "gemini-5h", "description": "Quota status",
                                 **fields}],
                }]})
                row = quota["windows"][1]
                self.assertEqual(row["used_pct"], used)
                self.assertEqual(row["usage_known"], used is not None)
                self.assertEqual(row["detail"], "暂时无法读取" if used is None else None)

    def test_antigravity_refreshes_quota_cached_by_old_parser(self):
        process = {"pid": 123, "csrf_token": "local-token"}
        endpoints = [("https", 64123, "local-token", True)]
        summary = {"groups": [{"displayName": "Gemini Models", "buckets": [
            {"bucketId": "gemini-5h", "remainingFraction": 1},
        ]}]}
        with tempfile.TemporaryDirectory() as tmp:
            self.isolate_cache(Path(tmp))
            old_marker = USAGE._provider_credential_marker(
                "antigravity", "quota-summary-v2", process["pid"], process["csrf_token"], endpoints)
            USAGE._save_provider_quota_cache("antigravity", old_marker, {
                "available": True, "windows": [{"usage_known": False, "used_pct": None}],
            })
            with mock.patch.object(USAGE, "_antigravity_running_processes", return_value=[process]), \
                    mock.patch.object(USAGE, "_antigravity_endpoints", return_value=endpoints), \
                    mock.patch.object(USAGE, "_antigravity_request", side_effect=[summary, {}]) as request:
                quota = USAGE.fetch_antigravity_quota()
                self.assertEqual(quota["windows"][1]["used_pct"], 0.0)
                self.assertTrue(quota["windows"][1]["usage_known"])
                self.assertEqual(request.call_count, 2)
                self.assertEqual(USAGE.fetch_antigravity_quota(), quota)
                self.assertEqual(request.call_count, 2)

    def test_antigravity_only_keeps_four_official_shared_windows(self):
        quota = USAGE._normalize_antigravity_quota_summary({"groups": [
            {"displayName": "Gemini Models", "buckets": [
                {"bucketId": "opaque-id", "window": "weekly", "remainingFraction": 1},
                {"bucketId": "gemini-weekly-duplicate", "remainingFraction": 0.2},
                {"bucketId": "gemini-daily", "remainingFraction": 0.5},
                {"bucketId": "gemini-5h", "remainingFraction": 0.9},
            ]},
            {"displayName": "Other Models", "buckets": [
                {"bucketId": "other-weekly", "remainingFraction": 0.4},
            ]},
        ]})
        self.assertEqual([row["title"] for row in quota["windows"]],
                         ["Gemini 周", "Gemini 5h", "Claude/GPT 周", "Claude/GPT 5h"])
        self.assertEqual([row["used_pct"] for row in quota["windows"]], [0.0, 10.0, None, None])
        self.assertFalse(quota["windows"][2]["usage_known"])

    def test_antigravity_summary_failure_keeps_stale_groups_not_model_rows(self):
        process = {"pid": 123, "csrf_token": "local-token"}
        endpoints = [("https", 64123, "local-token", True)]
        summary = {"groups": [{"displayName": "Gemini Models", "buckets": [
            {"bucketId": "gemini-weekly", "remainingFraction": 1},
            {"bucketId": "gemini-5h", "remainingFraction": 0.98},
        ]}]}
        with tempfile.TemporaryDirectory() as tmp:
            self.isolate_cache(Path(tmp))
            with mock.patch.object(USAGE, "_antigravity_running_processes", return_value=[process]), \
                    mock.patch.object(USAGE, "_antigravity_endpoints", return_value=endpoints):
                with mock.patch.object(USAGE, "_antigravity_request", side_effect=[summary, {}]):
                    fresh = USAGE.fetch_antigravity_quota()
                cache_path = Path(USAGE.PROVIDER_QUOTA_CACHE)
                cache = json.loads(cache_path.read_text())
                cache["providers"]["antigravity"]["fetched_at"] -= USAGE._PROVIDER_QUOTA_TTL + 1
                cache_path.write_text(json.dumps(cache))
                with mock.patch.object(USAGE, "_antigravity_request", side_effect=TimeoutError) as request:
                    stale = USAGE.fetch_antigravity_quota()
                self.assertTrue(stale["stale"])
                self.assertEqual(stale["windows"], fresh["windows"])
                self.assertEqual(len(stale["windows"]), 4)
                self.assertEqual(request.call_count, 1)
                self.assertTrue(request.call_args.args[1].endswith("/RetrieveUserQuotaSummary"))

                cache_path.unlink()
                with mock.patch.object(USAGE, "_antigravity_request", side_effect=TimeoutError) as request:
                    with self.assertRaises(TimeoutError):
                        USAGE.fetch_antigravity_quota()
                self.assertEqual(request.call_count, 1)

    def test_antigravity_user_status_only_supplies_account_identity(self):
        identity = USAGE._antigravity_user_identity({"userStatus": {
            "email": "test@example.com", "userTier": {"name": "Google AI Pro"},
            "cascadeModelConfigData": {"clientModelConfigs": [
                {"label": "Gemini Pro", "quotaInfo": {"remainingFraction": 1}},
            ]},
        }})
        self.assertEqual(identity, {"plan": "Google AI Pro", "account": "test@example.com"})

    def test_antigravity_scan_skips_ps_after_an_empty_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.isolate_cache(Path(tmp))
            with mock.patch.object(
                    USAGE.subprocess, "run",
                    return_value=mock.Mock(stdout=b"" if USAGE._IS_WINDOWS else "")) as run:
                self.assertEqual(USAGE._antigravity_running_processes(now_epoch=1000), [])
                self.assertEqual(run.call_count, 1)

                self.assertEqual(USAGE._antigravity_running_processes(now_epoch=1080), [])
                self.assertEqual(run.call_count, 1)

                USAGE._antigravity_running_processes(
                    now_epoch=1000 + USAGE._ANTIGRAVITY_SCAN_MISS_TTL)
                self.assertEqual(run.call_count, 2)

                USAGE._antigravity_running_processes(now_epoch=500)
                self.assertEqual(run.call_count, 3)

    def test_antigravity_scan_cache_never_hides_a_running_process(self):
        executable = (r"C:\Apps\Antigravity\language_server_windows_x64.exe" if USAGE._IS_WINDOWS
                      else "/Applications/Antigravity.app/Contents/Resources/language_server_macos_arm")
        output = (f"321 {executable} "
                  "--csrf_token language-token --app_data_dir antigravity")
        with tempfile.TemporaryDirectory() as tmp:
            self.isolate_cache(Path(tmp))
            Path(USAGE.ANTIGRAVITY_SCAN_CACHE).write_text(
                json.dumps({"empty_at": 900}), encoding="utf-8")
            # This test counts process scans, independently of credential discovery.
            with mock.patch.object(USAGE, "_discover_antigravity_credentials", return_value={}), \
                    mock.patch.object(
                        USAGE.subprocess, "run", return_value=mock.Mock(
                            stdout=output.encode("utf-8") if USAGE._IS_WINDOWS else output)) as run:
                processes = USAGE._antigravity_running_processes(now_epoch=2000)
                self.assertEqual([item["pid"] for item in processes], [321])
                self.assertFalse(Path(USAGE.ANTIGRAVITY_SCAN_CACHE).exists())

                USAGE._antigravity_running_processes(now_epoch=2001)
                self.assertEqual(run.call_count, 2)
                if not USAGE._IS_WINDOWS:
                    self.assertEqual(run.call_args.args[0], ["/bin/ps", "-ax", "-o", "pid=,command="])

    def test_antigravity_request_is_loopback_only_and_sends_csrf(self):
        with mock.patch.object(USAGE, "_provider_json_request", return_value={}) as request:
            USAGE._antigravity_request(
                ("https", 64123, "csrf-token", True),
                "/exa.language_server_pb.LanguageServerService/GetUserStatus",
                {"metadata": {}},
            )

        args, kwargs = request.call_args
        self.assertEqual(
            args[0],
            "https://127.0.0.1:64123/exa.language_server_pb.LanguageServerService/GetUserStatus",
        )
        self.assertEqual(kwargs["headers"]["X-Codeium-Csrf-Token"], "csrf-token")
        self.assertEqual(kwargs["headers"]["Connect-Protocol-Version"], "1")
        self.assertTrue(kwargs["allow_insecure_loopback_tls"])

    def test_provider_cache_is_scoped_to_credentials_without_storing_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            USAGE._USER_DIR = tmp
            USAGE.PROVIDER_QUOTA_CACHE = str(Path(tmp, "provider_quota_cache.json"))
            marker = USAGE._provider_credential_marker("sub2api", "secret-a", "https://api.test")
            quota = {"available": True, "windows": [], "updated": 1_800_000_000}
            USAGE._save_provider_quota_cache("sub2api", marker, quota, fetched_at=1_800_000_000)

            cache_text = Path(USAGE.PROVIDER_QUOTA_CACHE).read_text(encoding="utf-8")
            self.assertNotIn("secret-a", cache_text)
            if not USAGE._IS_WINDOWS:
                self.assertEqual(Path(USAGE.PROVIDER_QUOTA_CACHE).stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                USAGE._cached_provider_quota(
                    "sub2api", marker, max_age=60, now_epoch=1_800_000_030
                )["available"],
                True,
            )
            other = USAGE._provider_credential_marker("sub2api", "secret-b", "https://api.test")
            self.assertIsNone(USAGE._cached_provider_quota(
                "sub2api", other, max_age=60, now_epoch=1_800_000_030
            ))

    def test_provider_accounts_are_not_written_to_sync_snapshots(self):
        payload = {
            "claude": {"ranges": {}},
            "cursor": {"account": "cursor@example.com"},
            "zed": {"account": "octocat"},
            "sub2api": {"available": True},
            "zai": {"available": True},
            "antigravity": {"account": "gemini@example.com"},
            "grok_bot": {
                "ranges": {"today": {"sessions": 1}},
                "quota": {
                    "available": True,
                    "usage": {"ranges": {"today": {"tokens": 99}}},
                },
            },
        }
        snapshot = USAGE._sync_safe_usage_payload(payload)

        self.assertIn("claude", snapshot)
        for provider in ("cursor", "zed", "sub2api", "zai", "antigravity"):
            self.assertNotIn(provider, snapshot)
        self.assertEqual(snapshot["grok_bot"], payload["grok_bot"])
        self.assertIn("cursor", payload)

    def test_antigravity_proc_env_edge_cases(self):
        self.assertEqual(USAGE._antigravity_proc_env(0), {})
        self.assertEqual(USAGE._antigravity_proc_env(-1), {})
        self.assertEqual(USAGE._antigravity_proc_env(None), {})

    def test_antigravity_discover_credentials_from_environ(self):
        with mock.patch.dict(os.environ, {
            "ANTIGRAVITY_CSRF_TOKEN": "env-token",
            "ANTIGRAVITY_LS_ADDRESS": "localhost:63041",
        }):
            creds = USAGE._discover_antigravity_credentials([{"pid": 12345}])
            self.assertEqual(creds[12345], ("env-token", 63041))

    def test_antigravity_discover_credentials_from_cache_and_proc_env(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=True):
            self.isolate_cache(Path(tmp))
            cred_cache = Path(tmp) / "antigravity_credentials.json"
            cred_cache.write_text(json.dumps({
                "credentials": {"123": {"token": "cached-token", "port": 50001}}
            }))
            with mock.patch.object(USAGE, "ANTIGRAVITY_CREDENTIALS_CACHE", str(cred_cache)):
                creds = USAGE._discover_antigravity_credentials([{"pid": 123}])
                self.assertEqual(creds[123], ("cached-token", 50001))

            with mock.patch.object(USAGE, "ANTIGRAVITY_CREDENTIALS_CACHE", str(Path(tmp) / "missing.json")), \
                    mock.patch.object(USAGE, "_antigravity_proc_env", return_value={
                        "ANTIGRAVITY_CSRF_TOKEN": "proc-token",
                        "ANTIGRAVITY_LS_ADDRESS": "127.0.0.1:50002",
                    }):
                creds = USAGE._discover_antigravity_credentials([{"pid": 456}])
                self.assertEqual(creds[456], ("proc-token", 50002))

    def test_antigravity_endpoints_dual_protocol_and_csrf(self):
        process = {"pid": 999, "csrf_token": "token-xyz", "ls_port": 63041}
        with mock.patch.object(USAGE, "_antigravity_listening_ports", return_value=[63040, 63041]):
            endpoints = USAGE._antigravity_endpoints(process)
            self.assertIn(("http", 63040, "token-xyz", True), endpoints)
            self.assertIn(("https", 63040, "token-xyz", True), endpoints)
            self.assertIn(("http", 63041, "token-xyz", True), endpoints)
            self.assertIn(("https", 63041, "token-xyz", True), endpoints)

        no_csrf = {"pid": 999, "csrf_token": ""}
        with mock.patch.object(USAGE, "_antigravity_listening_ports", return_value=[63040]):
            endpoints = USAGE._antigravity_endpoints(no_csrf)
            self.assertIn(("http", 63040, "", False), endpoints)
            self.assertIn(("https", 63040, "", False), endpoints)

    def test_antigravity_rejects_stale_token_whose_ls_port_is_dead(self):
        process = {"pid": 321, "kind": "cli", "csrf_token": "",
                   "extension_port": None, "extension_csrf_token": None}
        with mock.patch.object(USAGE, "_antigravity_listening_ports", return_value=[51213]), \
                mock.patch.object(USAGE, "_antigravity_port_open", return_value=False):
            saved = USAGE._antigravity_attach_credentials([process], {321: ("stale-token", 54570)})
        self.assertEqual(process["csrf_token"], "")
        self.assertEqual(saved, {})

        with mock.patch.object(USAGE, "_antigravity_listening_ports", return_value=[51213]), \
                mock.patch.object(USAGE, "_antigravity_port_open", return_value=True):
            saved = USAGE._antigravity_attach_credentials([process], {321: ("fresh-token", 51213)})
        self.assertEqual(process["csrf_token"], "fresh-token")
        self.assertEqual(process["ls_port"], 51213)
        self.assertEqual(saved["321"], {"token": "fresh-token", "port": 51213})

    def test_antigravity_daemon_file_supplies_token_and_ports(self):
        with tempfile.TemporaryDirectory() as tmp:
            daemon = Path(tmp, "daemon")
            daemon.mkdir()
            Path(daemon, "ls_fixture.json").write_text(json.dumps({
                "pid": 4321, "httpsPort": 63041, "httpPort": 63042,
                "csrfToken": "daemon-token",
            }), encoding="utf-8")
            with mock.patch.object(USAGE, "ANTIGRAVITY_DAEMON_DIRS", (str(daemon),)), \
                    mock.patch.object(USAGE, "_antigravity_pid_alive", return_value=True), \
                    mock.patch.object(USAGE, "_antigravity_listening_ports",
                                      return_value=[63041, 63042]):
                entries = USAGE._antigravity_daemon_credentials()
                processes = USAGE._antigravity_merge_daemon_processes([], entries)
                endpoints = USAGE._antigravity_endpoints(processes[0])

        self.assertEqual(entries[0]["token"], "daemon-token")
        self.assertEqual(processes[0]["pid"], 4321)
        self.assertEqual(processes[0]["csrf_token"], "daemon-token")
        self.assertIn(("https", 63041, "daemon-token", True), endpoints)
        self.assertIn(("http", 63042, "daemon-token", True), endpoints)

    def test_antigravity_daemon_file_with_dead_pid_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            daemon = Path(tmp, "daemon")
            daemon.mkdir()
            Path(daemon, "ls_fixture.json").write_text(json.dumps({
                "pid": 4321, "httpsPort": 63041, "csrfToken": "daemon-token",
            }), encoding="utf-8")
            with mock.patch.object(USAGE, "ANTIGRAVITY_DAEMON_DIRS", (str(daemon),)), \
                    mock.patch.object(USAGE, "_antigravity_pid_alive", return_value=False):
                entries = USAGE._antigravity_daemon_credentials()
                processes = USAGE._antigravity_merge_daemon_processes([], entries)

        self.assertEqual(entries, [])
        self.assertEqual(processes, [])

    def test_antigravity_endpoints_ignore_dead_ls_port(self):
        process = {"pid": 9, "csrf_token": "token", "ls_port": 54570,
                   "ports": [51213], "daemon_ports": []}
        endpoints = USAGE._antigravity_endpoints(process)
        self.assertEqual({port for _scheme, port, _csrf, _required in endpoints}, {51213})
        self.assertIn(("https", 51213, "token", True), endpoints)

        unknown = {"pid": 9, "csrf_token": "token", "ls_port": 54570, "ports": []}
        endpoints = USAGE._antigravity_endpoints(unknown)
        self.assertIn(54570, {port for _scheme, port, _csrf, _required in endpoints})

    def test_antigravity_fetch_keeps_other_processes_after_csrf_rejection(self):
        process = {"pid": 777, "csrf_token": "bad-token", "ports": [63040]}
        endpoints = [("http", 63040, "bad-token", True),
                     ("https", 63040, "bad-token", True)]
        with tempfile.TemporaryDirectory() as tmp:
            self.isolate_cache(Path(tmp))
            Path(USAGE.ANTIGRAVITY_CREDENTIALS_CACHE).write_text(json.dumps({
                "credentials": {
                    "777": {"token": "bad-token", "port": 63040},
                    "888": {"token": "other-token", "port": 63041},
                }
            }), encoding="utf-8")
            with mock.patch.object(USAGE, "_antigravity_running_processes",
                                   return_value=[process]), \
                    mock.patch.object(USAGE, "_antigravity_endpoints",
                                      return_value=endpoints), \
                    mock.patch.object(USAGE, "_antigravity_request",
                                      side_effect=[OSError("SSL record layer failure"),
                                                   RuntimeError("HTTP 401")]):
                with self.assertRaises(RuntimeError) as raised:
                    USAGE.fetch_antigravity_quota()
            saved = json.loads(
                Path(USAGE.ANTIGRAVITY_CREDENTIALS_CACHE).read_text(encoding="utf-8"))

        self.assertIn("HTTP 401", str(raised.exception))
        self.assertNotIn("777", saved["credentials"])
        self.assertIn("888", saved["credentials"])

    def test_antigravity_fetch_fallback_on_http_or_ssl_error(self):
        process = {"pid": 888, "csrf_token": "valid-token"}
        endpoints = [
            ("http", 63040, "valid-token", True),
            ("https", 63040, "valid-token", True),
        ]
        summary = {"groups": [{"displayName": "Gemini Models", "buckets": [
            {"bucketId": "gemini-5h", "remainingFraction": 0.8},
        ]}]}
        with tempfile.TemporaryDirectory() as tmp:
            self.isolate_cache(Path(tmp))
            with mock.patch.object(USAGE, "_antigravity_running_processes", return_value=[process]), \
                    mock.patch.object(USAGE, "_antigravity_endpoints", return_value=endpoints):
                # 第一次请求 (http) 报 400，第二次请求 (https) 成功
                with mock.patch.object(USAGE, "_antigravity_request",
                                       side_effect=[RuntimeError("HTTP 400"), summary, {}]) as request:
                    quota = USAGE.fetch_antigravity_quota()
                    self.assertTrue(quota["available"])
                    self.assertEqual(quota["windows"][1]["used_pct"], 20.0)
                    self.assertEqual(request.call_count, 3)

    def test_antigravity_csrf_bypasses_environment_and_system_proxies(self):
        import urllib.request
        token = "fixture-only-csrf"

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                self.server.records.append(dict(self.headers))
                body = json.dumps({"source": self.server.label}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        servers = []
        for label in ("proxy", "target"):
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            server.label, server.records = label, []
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(thread.join)
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            servers.append(server)
        proxy, target = servers
        proxy_url = f"http://127.0.0.1:{proxy.server_port}"
        process = {"pid": 0, "csrf_token": token, "ls_port": target.server_port}
        with mock.patch.object(USAGE, "_antigravity_listening_ports", return_value=[]):
            endpoint = next(e for e in USAGE._antigravity_endpoints(process) if e[0] == "http")
        for source in ("environment", "system"):
            with self.subTest(source=source):
                proxy.records.clear()
                target.records.clear()
                environment = {"http_proxy": proxy_url} if source == "environment" else {}
                discovery = (mock.patch("urllib.request.getproxies", return_value={"http": proxy_url})
                             if source == "system" else mock.patch(
                                 "urllib.request.getproxies", wraps=urllib.request.getproxies))
                # No environment or system loopback exclusion may protect this request.
                with mock.patch.dict(os.environ, environment, clear=True), discovery, \
                        mock.patch("urllib.request.proxy_bypass", return_value=False):
                    self.assertNotIn("NO_PROXY", os.environ)
                    self.assertNotIn("no_proxy", os.environ)
                    response = USAGE._antigravity_request(endpoint, "/fixture", {})
                self.assertEqual(proxy.records, [], "proxy must receive no request or headers")
                self.assertEqual(response, {"source": "target"})
                self.assertEqual(len(target.records), 1)
                self.assertEqual(target.records[0]["X-Codeium-Csrf-Token"], token)

    def test_provider_external_https_keeps_proxy_support_and_tls_verification(self):
        import ssl
        import urllib.request
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"{}"
        proxy_url = "http://127.0.0.1:1"
        built = []
        original_build = urllib.request.build_opener
        def capture_opener(*handlers):
            opener = original_build(*handlers)
            built.append(opener)
            return opener
        with mock.patch("urllib.request.getproxies", return_value={"https": proxy_url}), \
                mock.patch("urllib.request.build_opener", side_effect=capture_opener) as build, \
                mock.patch("urllib.request.OpenerDirector.open", return_value=response), \
                mock.patch.object(ssl, "_create_unverified_context") as insecure:
            USAGE._provider_json_request(
                "https://quota.fixture.invalid/usage", allow_insecure_loopback_tls=True)
        insecure.assert_not_called()
        self.assertFalse(any(isinstance(h, urllib.request.ProxyHandler) for h in build.call_args.args))
        proxies = [h for h in built[0].handlers if isinstance(h, urllib.request.ProxyHandler)]
        self.assertEqual(proxies[0].proxies, {"https": proxy_url})
        tls = [h for h in built[0].handlers if isinstance(h, urllib.request.HTTPSHandler)]
        self.assertEqual(len(tls), 1)
        context = tls[0]._context or ssl.create_default_context()
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_provider_proxy_bypass_is_limited_to_loopback_hosts(self):
        import urllib.request
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"{}"
        for host, local in (("127.0.0.1", True), ("127.0.0.2", True),
                            ("[::1]", True), ("localhost", True),
                            ("localhost.fixture.invalid", False), ("192.0.2.1", False)):
            with self.subTest(host=host), \
                    mock.patch("urllib.request.build_opener", wraps=urllib.request.build_opener) as build, \
                    mock.patch("urllib.request.OpenerDirector.open", return_value=response):
                USAGE._provider_json_request(f"http://{host}/fixture")
            proxies = [h for h in build.call_args.args if isinstance(h, urllib.request.ProxyHandler)]
            self.assertEqual(len(proxies), int(local))
            if local:
                self.assertEqual(proxies[0].proxies, {})

    def test_exhausted_provider_cache_rechecks_hourly_and_validates_future_skew(self):
        now = 1800000000
        quota = {"available": True, "windows": [
            {"used_pct": 100, "reset": now + 7 * 86400},
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            self.isolate_cache(Path(tmp))
            for fetched_at, expected in ((now - 3599, True), (now - 3600, False),
                                         (now - 86400, False), (now + 301, False),
                                         (now + 300, True)):
                USAGE._save_provider_quota_cache("antigravity", "fixture", quota, fetched_at=fetched_at)
                for reader in (lambda **kw: USAGE._cached_provider_quota("antigravity", "fixture", **kw),
                               lambda **kw: USAGE._latest_cached_provider_quota("antigravity", **kw)):
                    with self.subTest(fetched_at=fetched_at, reader=reader):
                        self.assertEqual(reader(max_age=60, now_epoch=now) is not None, expected)

    def test_exhausted_provider_cache_cannot_hide_another_reset_window(self):
        now = 1800000000
        for used in (20, 100):
            for reverse in (False, True):
                windows = [{"used_pct": used, "reset": now - 1},
                           {"used_pct": 100, "reset": now + 86400}]
                if reverse:
                    windows.reverse()
                quota = {"available": True, "windows": windows}
                with self.subTest(used=used, reverse=reverse), tempfile.TemporaryDirectory() as tmp:
                    self.isolate_cache(Path(tmp))
                    USAGE._save_provider_quota_cache("antigravity", "fixture", quota, fetched_at=now - 500)
                    self.assertIsNone(USAGE._cached_provider_quota(
                        "antigravity", "fixture", max_age=60, now_epoch=now))
                    self.assertIsNone(USAGE._latest_cached_provider_quota(
                        "antigravity", max_age=60, now_epoch=now))

    def test_provider_cache_historical_fallback_keeps_history_and_skew_check(self):
        now = 1800000000
        with tempfile.TemporaryDirectory() as tmp:
            self.isolate_cache(Path(tmp))
            for exhausted in (False, True):
                quota = {"available": True, "windows": [
                    {"used_pct": 100 if exhausted else 20, "reset": now + 86400},
                    {"used_pct": 20, "reset": now - 1},
                ]}
                USAGE._save_provider_quota_cache("antigravity", "fixture", quota, fetched_at=now - 86400)
                for reader in (lambda **kw: USAGE._cached_provider_quota("antigravity", "fixture", **kw),
                               lambda **kw: USAGE._latest_cached_provider_quota("antigravity", **kw)):
                    history = reader(max_age=None, now_epoch=now, stale=True)
                    self.assertEqual(history["windows"], quota["windows"])
                    self.assertTrue(history["stale"])
                    self.assertEqual(history["source"], "cache")
                    history["windows"].clear()
                    self.assertEqual(len(reader(max_age=None, now_epoch=now)["windows"]), 2)
                    USAGE._save_provider_quota_cache("antigravity", "fixture", quota, fetched_at=now + 301)
                    self.assertIsNone(reader(max_age=None, now_epoch=now))
                    USAGE._save_provider_quota_cache("antigravity", "fixture", quota, fetched_at=now - 86400)

    def test_antigravity_quota_exhausted_sleep_retention(self):
        quota = {
            "available": True,
            "windows": [
                {"id": "antigravity-gemini-weekly", "used_pct": 50.0, "reset": 1800003600},
                {"id": "antigravity-gemini-5h", "used_pct": 100.0, "reset": 1800001800},
            ],
            "updated": 1800000000,
        }
        reset_at = USAGE._provider_quota_exhausted_reset_at(quota, now_epoch=1800000100)
        self.assertEqual(reset_at, 1800001800.0)

        with tempfile.TemporaryDirectory() as tmp:
            self.isolate_cache(Path(tmp))
            marker = "exhausted-marker"
            USAGE._save_provider_quota_cache("antigravity", marker, quota, fetched_at=1800000000)

            # 在 reset 之前，即使超过常规 TTL（如 300 秒），也依然复用缓存
            cached = USAGE._cached_provider_quota("antigravity", marker, max_age=60, now_epoch=1800000500)
            self.assertIsNotNone(cached)
            self.assertTrue(cached["available"])

            # 超过 reset 之后，正常过期返回 None
            expired = USAGE._cached_provider_quota("antigravity", marker, max_age=60, now_epoch=1800002000)
            self.assertIsNone(expired)


if __name__ == "__main__":
    unittest.main()
