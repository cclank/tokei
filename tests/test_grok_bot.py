import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

try:
    from .test_codex_limits import USAGE
except ImportError:
    from test_codex_limits import USAGE


class GrokBotTests(unittest.TestCase):
    def _write_blob(self, path, value):
        path.write_text(json.dumps({"schemaVersion": 1, "value": value}), encoding="utf-8")

    def test_local_snapshots_count_activity_without_inventing_tokens(self):
        now = datetime.now().astimezone().replace(hour=10, minute=0, second=0, microsecond=0)
        base_ms = int(now.timestamp() * 1000)
        entries = [
            {"id": "u1", "kind": "message", "role": "user", "requestId": "r1",
             "timestampMs": base_ms},
            {"id": "a1", "kind": "send-message", "requestId": "r1",
             "timestampMs": base_ms + 1_000, "message": {"type": "text", "content": "one"}},
            {"id": "a2", "kind": "send-message", "requestId": "r1",
             "timestampMs": base_ms + 2_000, "message": {"type": "connector"}},
            {"id": "a3", "kind": "send-message", "requestId": "r1",
             "timestampMs": base_ms + 3_000, "message": {"type": "text", "content": "two"}},
            {"id": "u2", "kind": "message", "role": "user", "requestId": "r2",
             "timestampMs": base_ms + 400_000},
            {"id": "a4", "kind": "send-message", "requestId": "r2",
             "timestampMs": base_ms + 401_000, "message": {"type": "text", "content": "three"}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_blob(root / "transcript.blob", {"entries": entries})
            self._write_blob(root / "transcript-copy.blob", {"entries": entries})
            self._write_blob(root / "roster.blob", {"rows": [{
                "id": "agent-1", "path": "/tmp/grok-project", "newestEntryId": "a4",
            }]})
            (root / "broken.blob").write_text("not json", encoding="utf-8")
            cache = {"v": USAGE._SCAN_CACHE_VERSION}
            with mock.patch.object(USAGE, "GROK_BOT_DIRS", [str(root)]):
                result = USAGE.scan_grok_bot(USAGE.range_bounds(), cache)
                again = USAGE.scan_grok_bot(USAGE.range_bounds(), cache)

        today = result["ranges"]["today"]
        self.assertEqual(today["sessions"], {"agent-1"})
        self.assertEqual(today["turns"], 2)
        self.assertEqual(today["calls"], 2)
        self.assertEqual(today["tools"], 1)
        self.assertEqual(today["duration"], 4)
        self.assertNotIn("tokens", today)
        self.assertEqual(again["ranges"]["today"]["calls"], 2)
        transcripts = [row for row in cache["grok_bot"].values()
                       if isinstance(row, dict) and row.get("kind") == "transcript"]
        self.assertEqual(sum(row.get("sid") == "agent-1" for row in transcripts), 1)
        self.assertTrue(all("project" not in row for row in transcripts))

    def test_quota_is_split_from_sand_usage(self):
        start = datetime.now().astimezone().replace(microsecond=0)
        reset = start + timedelta(days=7)
        quota = USAGE._normalize_grok_bot_quota({
            "hasNonZeroIncludedLimit": True,
            "usagePercent": 12.5,
            "currentPeriodStart": int(start.timestamp()),
            "nextResetTimestampUtc": int(reset.timestamp()),
            "grokPlanLabel": "X Premium+",
        }, identity={"account": "person@example.com"}, updated=1_800_000_000)

        self.assertTrue(quota["available"])
        self.assertEqual(quota["plan"], "X Premium+")
        self.assertEqual(quota["windows"][0]["used_pct"], 12.5)
        self.assertEqual(quota["windows"][0]["window_minutes"], 7 * 24 * 60)
        self.assertIsNone(quota["account"])

    def test_missing_included_allowance_does_not_report_fake_quota(self):
        quota = USAGE._normalize_grok_bot_quota({
            "hasNonZeroIncludedLimit": False,
            "usagePercent": 0,
        })
        self.assertEqual(quota, {})

    def test_bridge_usage_adds_official_tokens_models_and_cost(self):
        now = datetime.now().astimezone().replace(microsecond=0)
        event = {
            "timestamp": str(int(now.timestamp() * 1000)),
            "model": "grok-code-fast-1",
            "clientType": "sand",
            "tokenUsage": {
                "inputTokens": 100,
                "outputTokens": 20,
                "cacheReadTokens": 300,
                "cacheWriteTokens": 10,
                "totalCents": 1.5,
            },
        }
        payload = {
            "quotaFetched": True,
            "usageFetched": True,
            "updated": int(now.timestamp()),
            "sandUsage": {
                "hasNonZeroIncludedLimit": True,
                "usagePercent": 25,
            },
            "usageEventsDisplay": [event, dict(event)],
        }

        data = USAGE._grok_bot_provider_data(payload)

        today = data["usage"]["ranges"]["today"]
        self.assertTrue(data["available"])
        self.assertEqual(today["tokens"], 430)
        self.assertEqual(today["requests"], 1)
        self.assertEqual(today["cost"], 0.015)
        self.assertEqual(today["models"][0]["name"], "Grok Code Fast 1")
        self.assertEqual(data["usage"]["ranges"]["all"]["coverage"], "本年")

    def test_bridge_usage_is_kept_when_quota_is_unavailable(self):
        now = datetime.now().astimezone().replace(microsecond=0)
        payload = {
            "quotaFetched": False,
            "usageFetched": True,
            "usageEventsDisplay": [{
                "timestamp": str(int(now.timestamp() * 1000)),
                "model": "grok-code-fast-1",
                "tokenUsage": {"inputTokens": 10, "outputTokens": 5},
            }],
        }

        data = USAGE._grok_bot_provider_data(payload)

        self.assertFalse(data["available"])
        self.assertEqual(data["usage"]["ranges"]["today"]["tokens"], 15)

    def test_provider_scan_uses_native_grok_bot_without_cursor_login(self):
        native = {"available": True, "windows": [], "source": "grok-bot-api"}
        with mock.patch.object(
                USAGE, "_provider_quota_enabled",
                side_effect=lambda provider: provider == "grok_bot"), \
                mock.patch.object(USAGE, "_cursor_session", return_value=None), \
                mock.patch.object(
                    USAGE, "fetch_grok_bot_quota", return_value=native) as fetch_native, \
                mock.patch.object(USAGE, "fetch_cursor_quota") as fetch_cursor:
            result = USAGE.scan_provider_quotas()

        self.assertEqual(result["grok_bot"], native)
        fetch_native.assert_called_once_with()
        fetch_cursor.assert_not_called()

    def test_native_grok_bot_login_is_preferred_and_cached(self):
        reset = datetime.now().astimezone() + timedelta(days=7)
        payload = {
            "hasNonZeroIncludedLimit": True,
            "usagePercent": 37.5,
            "nextResetTimestampUtc": int(reset.timestamp()),
            "grokPlanLabel": "X Premium+",
        }
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(USAGE, "PROVIDER_QUOTA_CACHE", str(Path(tmp) / "quota.json")), \
                mock.patch.object(USAGE, "_grok_bot_active_account_id", return_value="a" * 64), \
                mock.patch.object(USAGE, "_grok_bot_authorization_generation", return_value=1), \
                mock.patch.object(USAGE, "_grok_bot_helper_sand_usage", return_value=payload) as helper, \
                mock.patch.object(USAGE, "_cursor_session") as cursor_session:
            first = USAGE.fetch_grok_bot_quota()
            second = USAGE.fetch_grok_bot_quota()

        self.assertEqual(first["windows"][0]["used_pct"], 37.5)
        self.assertEqual(first["source"], "grok-bot-api")
        self.assertEqual(second, first)
        helper.assert_called_once_with()
        cursor_session.assert_not_called()

    def test_active_account_id_comes_from_plaintext_account_index(self):
        account_id = "b" * 64
        with tempfile.TemporaryDirectory() as tmp:
            secrets = Path(tmp) / "sand-secrets.json"
            secrets.write_text(json.dumps({
                "cursor-accounts": json.dumps({
                    "active": account_id,
                    "accounts": {account_id: {"cursor-access-token": "ciphertext"}},
                }),
            }), encoding="utf-8")
            parsed = USAGE._grok_bot_active_account_id(str(secrets))

        self.assertEqual(parsed, account_id)

    def test_native_auth_failure_is_backed_off_for_five_minutes(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(USAGE, "PROVIDER_QUOTA_CACHE", str(Path(tmp) / "quota.json")), \
                mock.patch.object(USAGE, "_grok_bot_active_account_id", return_value="c" * 64), \
                mock.patch.object(USAGE, "_grok_bot_authorization_generation", return_value=2), \
                mock.patch.object(USAGE, "_grok_bot_helper_sand_usage", return_value=None) as helper, \
                mock.patch.object(USAGE, "_cursor_session", return_value=None):
            self.assertEqual(USAGE.fetch_grok_bot_quota(), {})
            self.assertEqual(USAGE.fetch_grok_bot_quota(), {})

        helper.assert_called_once_with()

    def test_recent_usage_cache_survives_missing_authorization_marker(self):
        now = datetime.now().astimezone().replace(microsecond=0)
        cached = USAGE._grok_bot_provider_data({
            "quotaFetched": True,
            "usageFetched": True,
            "updated": int(now.timestamp()),
            "sandUsage": {
                "hasNonZeroIncludedLimit": True,
                "usagePercent": 25,
            },
            "usageEventsDisplay": [{
                "timestamp": str(int(now.timestamp() * 1000)),
                "model": "grok-bot-default",
                "tokenUsage": {"inputTokens": 100, "outputTokens": 20},
            }],
        })
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(USAGE, "PROVIDER_QUOTA_CACHE", str(Path(tmp) / "quota.json")):
            USAGE._save_provider_quota_cache("grok_bot", "old-marker", cached)
            with mock.patch.object(USAGE, "_grok_bot_active_account_id", return_value="a" * 64), \
                    mock.patch.object(USAGE, "_grok_bot_authorization_generation", return_value=None), \
                    mock.patch.object(USAGE, "_grok_bot_repair_authorization_marker", return_value=False), \
                    mock.patch.object(USAGE, "_cursor_session", return_value=None):
                quota = USAGE.fetch_grok_bot_quota()

        self.assertTrue(quota["stale"])
        self.assertEqual(quota["source"], "cache")
        self.assertEqual(quota["usage"]["ranges"]["today"]["tokens"], 120)

    def test_historical_usage_has_no_quota_expiry(self):
        now = datetime.now().astimezone().replace(microsecond=0)
        cached = USAGE._grok_bot_provider_data({
            "quotaFetched": True,
            "usageFetched": True,
            "updated": int(now.timestamp()) - 2 * 60 * 60,
            "sandUsage": {
                "hasNonZeroIncludedLimit": True,
                "usagePercent": 25,
            },
            "usageEventsDisplay": [{
                "timestamp": str(int(now.timestamp() * 1000)),
                "model": "grok-bot-default",
                "tokenUsage": {"inputTokens": 100, "outputTokens": 20},
            }],
        })
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(USAGE, "PROVIDER_QUOTA_CACHE", str(Path(tmp) / "quota.json")):
            USAGE._save_provider_quota_cache(
                "grok_bot", "old-marker", cached,
                fetched_at=int(now.timestamp()) - 400 * 24 * 60 * 60,
            )
            with mock.patch.object(USAGE, "_grok_bot_active_account_id", return_value="a" * 64), \
                    mock.patch.object(USAGE, "_grok_bot_authorization_generation", return_value=None), \
                    mock.patch.object(USAGE, "_grok_bot_repair_authorization_marker", return_value=False), \
                    mock.patch.object(USAGE, "_cursor_session", return_value=None):
                quota = USAGE.fetch_grok_bot_quota()

        self.assertFalse(quota["available"])
        self.assertEqual(quota["windows"], [])
        self.assertTrue(quota["stale"])
        self.assertEqual(quota["usage"]["ranges"]["today"]["tokens"], 120)

    def test_missing_authorization_marker_is_repaired_without_user_prompt(self):
        payload = {
            "quotaFetched": True,
            "usageFetched": False,
            "sandUsage": {
                "hasNonZeroIncludedLimit": True,
                "usagePercent": 12.5,
            },
        }
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(USAGE, "PROVIDER_QUOTA_CACHE", str(Path(tmp) / "quota.json")), \
                mock.patch.object(USAGE, "_grok_bot_active_account_id", return_value="e" * 64), \
                mock.patch.object(
                    USAGE, "_grok_bot_authorization_generation", side_effect=[None, 7]), \
                mock.patch.object(
                    USAGE, "_grok_bot_repair_authorization_marker", return_value=True) as repair, \
                mock.patch.object(USAGE, "_grok_bot_helper_sand_usage", return_value=payload), \
                mock.patch.object(USAGE, "_cursor_session") as cursor_session:
            quota = USAGE.fetch_grok_bot_quota()

        self.assertEqual(quota["windows"][0]["used_pct"], 12.5)
        repair.assert_called_once_with()
        cursor_session.assert_not_called()

    def test_missing_marker_repair_failure_is_backed_off_for_five_minutes(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(USAGE, "PROVIDER_QUOTA_CACHE", str(Path(tmp) / "quota.json")), \
                mock.patch.object(USAGE, "_grok_bot_active_account_id", return_value="f" * 64), \
                mock.patch.object(USAGE, "_grok_bot_authorization_generation", return_value=None), \
                mock.patch.object(
                    USAGE, "_grok_bot_repair_authorization_marker", return_value=False) as repair, \
                mock.patch.object(USAGE, "_cursor_session", return_value=None):
            self.assertEqual(USAGE.fetch_grok_bot_quota(), {})
            self.assertEqual(USAGE.fetch_grok_bot_quota(), {})

        repair.assert_called_once_with()

    def test_confirmed_empty_native_quota_does_not_fall_back_to_cursor(self):
        payload = {"hasNonZeroIncludedLimit": False, "usagePercent": 0}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(USAGE, "PROVIDER_QUOTA_CACHE", str(Path(tmp) / "quota.json")), \
                mock.patch.object(USAGE, "_grok_bot_active_account_id", return_value="d" * 64), \
                mock.patch.object(USAGE, "_grok_bot_authorization_generation", return_value=3), \
                mock.patch.object(USAGE, "_grok_bot_helper_sand_usage", return_value=payload) as helper, \
                mock.patch.object(USAGE, "_cursor_session") as cursor_session:
            self.assertEqual(USAGE.fetch_grok_bot_quota(), {})
            self.assertEqual(USAGE.fetch_grok_bot_quota(), {})

        helper.assert_called_once_with()
        cursor_session.assert_not_called()

    def test_quota_failure_uses_one_hour_stale_cache(self):
        session = {"marker": "cursor-marker"}
        marker = USAGE._provider_credential_marker("cursor-usage-v1", session["marker"])
        cached = {
            "available": True,
            "windows": [{"id": "grok-bot-period", "title": "本周期额度",
                         "used_pct": 20}],
            "source": "cursor-sand-api",
            "stale": False,
        }
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(USAGE, "PROVIDER_QUOTA_CACHE", str(Path(tmp) / "quota.json")):
            USAGE._save_provider_quota_cache(
                "grok_bot", marker, cached,
                fetched_at=int(datetime.now().timestamp()) - 10 * 60,
            )
            with mock.patch.object(USAGE, "fetch_cursor_quota", return_value={}) as fetch:
                quota = USAGE.fetch_grok_bot_quota(session)

        fetch.assert_called_once_with(session, force=True)
        self.assertTrue(quota["stale"])
        self.assertEqual(quota["source"], "cache")


if __name__ == "__main__":
    unittest.main()


class GrokBotBackgroundHelperTests(unittest.TestCase):
    """辅助程序拉全年用量可能要一分多钟：放到后台跑，不拖住刷新、也不因超时丢结果。"""

    PAYLOAD = {"quotaFetched": True, "usageFetched": False,
               "sandUsage": {"hasNonZeroIncludedLimit": True, "usagePercent": 42}}

    def helper(self, tmp, delay=0.0, exit_code=0):
        script = Path(tmp) / "helper.sh"
        counter = Path(tmp) / "runs"
        script.write_text(
            "#!/bin/sh\n"
            f"echo run >> '{counter}'\n"
            f"sleep {delay}\n"
            f"[ {exit_code} -eq 0 ] || exit {exit_code}\n"
            f"printf '%s' '{json.dumps(self.PAYLOAD)}'\n", encoding="utf-8")
        script.chmod(0o700)
        return str(script), counter

    def patches(self, tmp, script, wait):
        return [mock.patch.object(USAGE, "PROVIDER_QUOTA_CACHE", str(Path(tmp) / "quota.json")),
                mock.patch.object(USAGE, "_grok_bot_active_account_id", return_value="a" * 64),
                mock.patch.object(USAGE, "_grok_bot_authorization_generation", return_value=1),
                mock.patch.object(USAGE, "_grok_bot_helper_path", return_value=script),
                mock.patch.object(USAGE, "_GROK_BOT_HELPER_WAIT", wait),
                mock.patch.object(USAGE, "_cursor_session", return_value=None)]

    def run_with(self, tmp, script, wait, steps):
        import contextlib
        with contextlib.ExitStack() as stack:
            for patch in self.patches(tmp, script, wait):
                stack.enter_context(patch)
            return [step() for step in steps]

    def test_a_slow_helper_finishes_in_the_background_and_is_picked_up_next_round(self):
        import time
        with tempfile.TemporaryDirectory() as tmp:
            script, counter = self.helper(tmp, delay=1.5)
            first, second = self.run_with(tmp, script, 0.3, [
                USAGE.fetch_grok_bot_quota,
                lambda: (time.sleep(2.5), USAGE.fetch_grok_bot_quota())[1],
            ])
            runs = counter.read_text().count("run")
        self.assertEqual(first, {}, "当轮没跑完：先用上一次的结果（这里没有）")
        self.assertEqual(second["windows"][0]["used_pct"], 42, "下一轮取到后台跑完的结果")
        self.assertEqual(runs, 1, "在跑的时候不重复启动")

    def test_a_fast_helper_is_still_answered_in_the_same_round(self):
        with tempfile.TemporaryDirectory() as tmp:
            script, _ = self.helper(tmp, delay=0)
            (quota,) = self.run_with(tmp, script, 5, [USAGE.fetch_grok_bot_quota])
        self.assertEqual(quota["windows"][0]["used_pct"], 42)

    def test_a_failing_helper_is_backed_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            script, counter = self.helper(tmp, delay=0, exit_code=2)
            results = self.run_with(tmp, script, 5,
                                    [USAGE.fetch_grok_bot_quota, USAGE.fetch_grok_bot_quota])
            runs = counter.read_text().count("run")
        self.assertEqual(results, [{}, {}])
        self.assertEqual(runs, 1, "失败后五分钟内不再启动")


class GrokBotIncrementalEventsTests(unittest.TestCase):
    """用量事件按天存档，平时只拉最近两天，不再每次从年初全量拉。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.object(USAGE, "PROVIDER_QUOTA_CACHE", str(Path(self.tmp.name) / "quota.json"))
        patch.start()
        self.addCleanup(patch.stop)
        self.today = datetime.now().astimezone().date()

    def ms(self, day, hour=12):
        return int(datetime(day.year, day.month, day.day, hour).timestamp() * 1000)

    def event(self, day, tokens, hour=12):
        return {"timestamp": str(self.ms(day, hour)), "model": "grok-bot-default",
                "tokenUsage": {"inputTokens": tokens, "outputTokens": 0}}

    def payload(self, start_day, events):
        return {"quotaFetched": True, "usageFetched": True,
                "usageStartDate": str(self.ms(start_day, 0)), "usageEventsDisplay": events,
                "sandUsage": {"hasNonZeroIncludedLimit": True, "usagePercent": 10}}

    def test_a_full_fetch_then_a_two_day_fetch_keep_the_whole_year(self):
        jan1 = self.today.replace(month=1, day=1)
        days = sorted({jan1, self.today - timedelta(days=2) if self.today.toordinal() - 2 >= jan1.toordinal() else jan1,
                       self.today})
        full = USAGE._grok_bot_merge_events(self.payload(jan1, [self.event(day, 100) for day in days]))
        self.assertEqual(len(full["usageEventsDisplay"]), len(days))

        since = USAGE._grok_bot_events_since()
        self.assertEqual(since, self.ms(max(self.today - timedelta(days=1), jan1), 0),
                         "从最后一天的前一天零点起补拉")
        fresh = USAGE._grok_bot_merge_events(self.payload(
            max(self.today - timedelta(days=1), jan1),
            [self.event(self.today, 100), self.event(self.today, 50, hour=13)]))
        tokens = sum(e["tokenUsage"]["inputTokens"] for e in fresh["usageEventsDisplay"])
        self.assertEqual(tokens, 100 * (len(days) - 1) + 150, "窗口里的今天整天替换，更早的留着")

    def test_quota_only_payload_still_shows_stored_usage(self):
        USAGE._grok_bot_merge_events(self.payload(self.today, [self.event(self.today, 70)]))
        merged = USAGE._grok_bot_merge_events({"quotaFetched": True, "usageFetched": False})
        self.assertEqual(merged["usageEventsDisplay"][0]["tokenUsage"]["inputTokens"], 70,
                         "这次没拉到用量时用存档")

    def test_last_years_files_are_removed(self):
        directory = Path(USAGE._grok_bot_event_dir())
        directory.mkdir(parents=True)
        old = directory / f"{self.today.year - 1}-12-31.json"
        old.write_text("[]", encoding="utf-8")
        USAGE._grok_bot_merge_events(self.payload(self.today, [self.event(self.today, 1)]))
        self.assertFalse(old.exists())

    def test_the_helper_is_asked_only_for_recent_days(self):
        USAGE._grok_bot_merge_events(self.payload(self.today, [self.event(self.today, 1)]))
        args_file = Path(self.tmp.name) / "args"
        script = Path(self.tmp.name) / "helper.sh"
        script.write_text(f"#!/bin/sh\necho \"$@\" > '{args_file}'\nexit 2\n", encoding="utf-8")
        script.chmod(0o700)
        with mock.patch.object(USAGE, "_grok_bot_helper_path", return_value=str(script)):
            running, started = USAGE._grok_bot_helper_start("marker")
            import time
            for _ in range(50):
                if args_file.exists():
                    break
                time.sleep(0.05)
        self.assertTrue(running and started)
        self.assertEqual(args_file.read_text().split(),
                         ["--grok-bot-data-json", "--since", str(USAGE._grok_bot_events_since())])
