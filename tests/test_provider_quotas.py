import base64
import json
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
        self.old_env = dict(USAGE.os.environ)

    def tearDown(self):
        USAGE._USER_DIR = self.old_user_dir
        if self.old_cache is not None:
            USAGE.PROVIDER_QUOTA_CACHE = self.old_cache
        if self.old_scan_cache is not None:
            USAGE.ANTIGRAVITY_SCAN_CACHE = self.old_scan_cache
        USAGE.os.environ.clear()
        USAGE.os.environ.update(self.old_env)

    def isolate_cache(self, root):
        USAGE._USER_DIR = str(root)
        USAGE.PROVIDER_QUOTA_CACHE = str(root / "provider_quota_cache.json")
        USAGE.ANTIGRAVITY_SCAN_CACHE = str(root / "antigravity_scan_cache.json")

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
        self.assertEqual([row["used_pct"] for row in quota["windows"]], [19.4, 12.5, 7.5])
        self.assertEqual(quota["windows"][0]["reset"], 1_788_220_800)
        self.assertEqual(quota["details"][0]["value"], "$3.88 / $20.00")
        self.assertEqual(quota["details"][1]["value"], "$4.50 / $10.00")

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
            ["Gemini 5h", "Gemini 周", "Claude/GPT 5h", "Claude/GPT 周"],
        )
        self.assertEqual([row["used_pct"] for row in quota["windows"]], [9.0, 18.0, 27.0, 36.0])
        self.assertEqual(quota["windows"][0]["window_minutes"], 300)
        self.assertEqual(quota["windows"][1]["window_minutes"], 10080)

    def test_antigravity_scan_skips_ps_after_an_empty_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.isolate_cache(Path(tmp))
            with mock.patch.object(
                    USAGE.subprocess, "run", return_value=mock.Mock(stdout="")) as run:
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
        output = ("321 /Applications/Antigravity.app/Contents/Resources/language_server_macos_arm "
                  "--csrf_token language-token --app_data_dir antigravity")
        with tempfile.TemporaryDirectory() as tmp:
            self.isolate_cache(Path(tmp))
            Path(USAGE.ANTIGRAVITY_SCAN_CACHE).write_text(
                json.dumps({"empty_at": 900}), encoding="utf-8")
            with mock.patch.object(
                    USAGE.subprocess, "run", return_value=mock.Mock(stdout=output)) as run:
                processes = USAGE._antigravity_running_processes(now_epoch=2000)
                self.assertEqual([item["pid"] for item in processes], [321])
                self.assertFalse(Path(USAGE.ANTIGRAVITY_SCAN_CACHE).exists())

                USAGE._antigravity_running_processes(now_epoch=2001)
                self.assertEqual(run.call_count, 2)

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


if __name__ == "__main__":
    unittest.main()
