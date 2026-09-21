import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from test_codex_limits import USAGE


def _ts(dt):
    return dt.astimezone().isoformat()


def _token_count_line(ts, last, total, rl=None):
    payload = {
        "type": "token_count",
        "info": {"last_token_usage": last, "total_token_usage": total},
    }
    if rl is not None:
        payload["rate_limits"] = rl
    return json.dumps({"timestamp": ts, "type": "event_msg", "payload": payload})


def _token_usage_record_line(ts, response_id, usage, total=None, thread_id=None):
    payload = {
        "response_id": response_id,
        "usage": usage,
        "thread_token_usage": total or usage,
    }
    if thread_id is not None:
        payload["thread_id"] = thread_id
    return json.dumps({"timestamp": ts, "type": "token_usage_record", "payload": payload})


def _session_meta_line(ts, session_id):
    return json.dumps({
        "timestamp": ts,
        "type": "session_meta",
        "payload": {"id": session_id, "cwd": "/tmp/reserve"},
    })


def _turn_context_line(ts, model):
    return json.dumps({
        "timestamp": ts,
        "type": "turn_context",
        "payload": {"model": model},
    })


def _usage(inp, cached, out, reason=0):
    return {"input_tokens": inp, "cached_input_tokens": cached,
            "cache_write_input_tokens": 0, "output_tokens": out,
            "reasoning_output_tokens": reason, "total_tokens": inp + out}


def _main_rl():
    return {"limit_id": "codex", "limit_name": None,
            "primary": {"used_percent": 50.0, "window_minutes": 10080,
                        "resets_at": 1790118835},
            "plan_type": "plus"}


def _reserve_rl():
    return {"limit_id": "base_model_inference", "limit_name": "gpt-reserve",
            "primary": {"used_percent": 10.0, "window_minutes": 10080,
                        "resets_at": 1790174743},
            "plan_type": "plus"}


def _write_rollout(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class CodexLunaReserveTests(unittest.TestCase):
    def _make_files(self, root):
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        ts = _ts(now)
        main_file = Path(root) / "sessions" / "rollout-main.jsonl"
        _write_rollout(main_file, [
            _turn_context_line(ts, "gpt-5.6-luna"),
            _token_count_line(ts, _usage(20000, 15000, 500),
                              _usage(20000, 15000, 500), _main_rl()),
        ])
        reserve_file = Path(root) / "sessions" / "rollout-reserve.jsonl"
        _write_rollout(reserve_file, [
            _turn_context_line(ts, "gpt-reserve"),
            _token_count_line(ts, _usage(10000, 9000, 200),
                              _usage(10000, 9000, 200), _reserve_rl()),
        ])
        mixed_file = Path(root) / "sessions" / "rollout-mixed.jsonl"
        _write_rollout(mixed_file, [
            _turn_context_line(ts, "gpt-5.6-luna"),
            _token_count_line(ts, _usage(30000, 20000, 300),
                              _usage(30000, 20000, 300), _main_rl()),
            _token_count_line(ts, _usage(5000, 4500, 100),
                              _usage(35000, 24500, 400), _reserve_rl()),
        ])
        return now

    def _scan(self, root, cache=None, custom_provider=False):
        root = Path(root).resolve()
        if getattr(self, "_ledger_root", None) != root:
            USAGE._LEDGER_CACHE.update(data=None, dirty=False)
            self._ledger_root = root
        sessions = root / "sessions"
        archive = root / "archive"
        sessions.mkdir(parents=True, exist_ok=True)
        cache = cache if cache is not None else {"v": USAGE._SCAN_CACHE_VERSION}
        with mock.patch.object(USAGE, "CODEX_DIR", str(sessions)), \
             mock.patch.object(USAGE, "CODEX_ARCHIVED_DIR", str(archive)), \
             mock.patch.object(USAGE, "_SCAN_CACHE_FILE", str(Path(root) / "scan-cache.json")), \
             mock.patch.object(USAGE, "_LEDGER_FILE", str(Path(root) / "ledger.json")), \
             mock.patch.object(USAGE, "fetch_codex_live_limits", return_value=None), \
             mock.patch.object(USAGE, "_codex_is_custom_provider", return_value=custom_provider):
            result = USAGE.scan_codex(USAGE.range_bounds(), cache)
        return result, cache

    def _cached_events(self, root, path):
        with mock.patch.object(
                USAGE, "_SCAN_CACHE_FILE", str(Path(root) / "scan-cache.json")):
            return list(USAGE._iter_codex_cached_events(str(path.resolve())))

    def test_reserve_split_from_main_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_files(tmp)
            result, _ = self._scan(tmp)

        main = result["ranges"]["all"]
        self.assertEqual(main["in"], 50000)
        self.assertEqual(main["cached"], 35000)
        self.assertEqual(main["out"], 800)
        self.assertNotIn("gpt-reserve", main["models"])
        self.assertNotIn("GPT", {m for m in main["models"]})

        reserve = result["reserve_ranges"]["all"]
        self.assertEqual(reserve["in"], 15000)
        self.assertEqual(reserve["cached"], 13500)
        self.assertEqual(reserve["out"], 300)
        self.assertEqual(set(reserve["models"]), {"gpt-reserve"})

        quota = result["reserve_quota"]
        self.assertIsNotNone(quota)
        self.assertEqual(quota["used_percent"], 10.0)
        self.assertEqual(quota["resets_at"], 1790174743)

    def test_response_first_reserve_mirror_backfills_current_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime.now(timezone.utc).replace(microsecond=0)
            ts = _ts(now)
            usage = _usage(120, 80, 30, 10)
            path = Path(tmp) / "sessions" / "rollout-response-first.jsonl"
            _write_rollout(path, [
                _session_meta_line(ts, "response-first"),
                _turn_context_line(ts, "gpt-5.6-luna"),
                _token_usage_record_line(ts, "resp-1", usage, thread_id="response-first"),
                _token_count_line(ts, usage, usage, _reserve_rl()),
            ])
            result, cache = self._scan(tmp)

            day = cache["codex"][str(path.resolve())]["days"][now.astimezone().date().isoformat()]
            events = self._cached_events(tmp, path)

        self.assertEqual(result["ranges"]["all"]["in"], 0)
        self.assertEqual(result["ranges"]["all"]["out"], 0)
        self.assertEqual(result["reserve_ranges"]["all"]["in"], 120)
        self.assertEqual(set(day["models"]), {"gpt-reserve"})
        self.assertAlmostEqual(
            day["cost"], USAGE._codex_estimated_cost("gpt-reserve", 120, 80, 30))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][11], "gpt-reserve")
        self.assertEqual(events[0][12], hashlib.sha256(b"resp-1").hexdigest())
        self.assertAlmostEqual(
            events[0][10], USAGE._codex_estimated_cost("gpt-reserve", 120, 80, 30))

    def test_response_first_reserve_mirror_backfills_incremental_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime.now(timezone.utc).replace(microsecond=0)
            ts = _ts(now)
            usage = _usage(120, 80, 30, 10)
            path = Path(tmp) / "sessions" / "rollout-incremental.jsonl"
            _write_rollout(path, [
                _session_meta_line(ts, "incremental"),
                _turn_context_line(ts, "gpt-5.6-luna"),
                _token_usage_record_line(ts, "resp-1", usage, thread_id="incremental"),
            ])
            cache = {"v": USAGE._SCAN_CACHE_VERSION}
            first, _ = self._scan(tmp, cache)
            self.assertEqual(first["ranges"]["all"]["in"], 120)

            with path.open("a", encoding="utf-8") as handle:
                handle.write(_token_count_line(ts, usage, usage, _reserve_rl()) + "\n")
            result, cache = self._scan(tmp, cache)
            events = self._cached_events(tmp, path)
            with mock.patch.object(USAGE, "_LEDGER_FILE", str(Path(tmp) / "ledger.json")):
                USAGE.ledger_flush()
                USAGE._LEDGER_CACHE.update(data=None, dirty=False)
                persisted = USAGE._load_ledger()["tools"]

        self.assertEqual(result["ranges"]["all"]["in"], 0)
        self.assertEqual(result["reserve_ranges"]["all"]["in"], 120)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][11], "gpt-reserve")
        self.assertEqual(events[0][12], hashlib.sha256(b"resp-1").hexdigest())
        entry = cache["codex"][str(path.resolve())]
        self.assertEqual(set(next(iter(entry["days"].values()))["models"]), {"gpt-reserve"})
        day_key = now.astimezone().date().isoformat()
        self.assertEqual(persisted["codex"][day_key].get("in", 0), 0)
        self.assertEqual(persisted["codex_reserve"][day_key]["in"], 120)

    def test_legacy_first_reserve_mirror_is_counted_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime.now(timezone.utc).replace(microsecond=0)
            ts = _ts(now)
            usage = _usage(120, 80, 30, 10)
            path = Path(tmp) / "sessions" / "rollout-legacy-first.jsonl"
            _write_rollout(path, [
                _session_meta_line(ts, "legacy-first"),
                _turn_context_line(ts, "gpt-5.6-luna"),
                _token_count_line(ts, usage, usage, _reserve_rl()),
                _token_usage_record_line(ts, "resp-1", usage, thread_id="legacy-first"),
                _token_usage_record_line(ts, "resp-1", usage, thread_id="legacy-first"),
            ])
            result, cache = self._scan(tmp)
            events = self._cached_events(tmp, path)

        self.assertEqual(result["ranges"]["all"]["in"], 0)
        self.assertEqual(result["reserve_ranges"]["all"]["in"], 120)
        self.assertEqual(result["reserve_ranges"]["all"]["out"], 30)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][11], "gpt-reserve")
        self.assertEqual(events[0][12], hashlib.sha256(b"resp-1").hexdigest())
        entry = cache["codex"][str(path.resolve())]
        self.assertEqual(len(entry["response_ids"]), 1)

    def test_resumed_segments_link_response_to_reserve_mirror(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime.now(timezone.utc).replace(microsecond=0)
            ts = _ts(now)
            usage = _usage(120, 80, 30, 10)
            _write_rollout(Path(tmp) / "sessions" / "rollout-a.jsonl", [
                _session_meta_line(ts, "resumed"),
                _turn_context_line(ts, "gpt-5.6-luna"),
                _token_usage_record_line(ts, "resp-1", usage, thread_id="resumed"),
            ])
            _write_rollout(Path(tmp) / "sessions" / "rollout-b.jsonl", [
                _session_meta_line(ts, "resumed"),
                _token_count_line(ts, usage, usage, _reserve_rl()),
            ])
            result, _ = self._scan(tmp)

        self.assertEqual(result["ranges"]["all"]["in"], 0)
        self.assertEqual(result["reserve_ranges"]["all"]["in"], 120)
        self.assertEqual(result["reserve_ranges"]["all"]["out"], 30)
        self.assertEqual(len(result["reserve_ranges"]["all"]["sessions"]), 1)

    def test_split_preserves_source_sessions_and_hours(self):
        with tempfile.TemporaryDirectory() as tmp:
            local = datetime.now().astimezone().replace(
                hour=9, minute=0, second=0, microsecond=0)
            day_key = local.date().isoformat()
            main_usage = _usage(100, 60, 20, 10)
            reserve_usage = _usage(50, 40, 5, 3)
            _write_rollout(Path(tmp) / "sessions" / "rollout-main.jsonl", [
                _session_meta_line(_ts(local), "main"),
                _turn_context_line(_ts(local), "gpt-5.6-luna"),
                _token_count_line(_ts(local), main_usage, main_usage, _main_rl()),
            ])
            reserve_time = local + timedelta(hours=1)
            _write_rollout(Path(tmp) / "sessions" / "rollout-reserve.jsonl", [
                _session_meta_line(_ts(reserve_time), "reserve"),
                _turn_context_line(_ts(reserve_time), "gpt-reserve"),
                _token_count_line(
                    _ts(reserve_time), reserve_usage, reserve_usage, _reserve_rl()),
            ])
            result, cache = self._scan(tmp)

        self.assertEqual(len(result["ranges"]["all"]["sessions"]), 1)
        self.assertEqual(len(result["reserve_ranges"]["all"]["sessions"]), 1)
        main_day = USAGE._codex_accounted_days(cache)[day_key]
        reserve_day = USAGE._codex_accounted_days(cache, reserve=True)[day_key]
        self.assertEqual(main_day["hours"][9], 120)
        self.assertEqual(main_day["hours"][10], 0)
        self.assertEqual(reserve_day["hours"][9], 0)
        self.assertEqual(reserve_day["hours"][10], 55)

    def test_pure_reserve_session_does_not_activate_main_usage_or_quota(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime.now(timezone.utc).replace(microsecond=0)
            ts = _ts(now)
            usage = _usage(50, 40, 5, 3)
            _write_rollout(Path(tmp) / "sessions" / "rollout-reserve-only.jsonl", [
                _session_meta_line(ts, "reserve-only"),
                _turn_context_line(ts, "gpt-reserve"),
                _token_count_line(ts, usage, usage, _reserve_rl()),
            ])
            result, _ = self._scan(tmp)
            ledger = USAGE._load_ledger()["tools"]

        self.assertEqual(len(result["ranges"]["all"]["sessions"]), 0)
        self.assertEqual(len(result["reserve_ranges"]["all"]["sessions"]), 1)
        self.assertNotIn(now.astimezone().date().isoformat(), ledger["codex"])
        self.assertIn(now.astimezone().date().isoformat(), ledger["codex_reserve"])
        self.assertIsNone(result["limits"])
        self.assertIsNotNone(result["reserve_quota"])

    def test_old_mixed_codex_ledgers_are_replaced_not_added_to_reserve(self):
        for source_aware in (False, True):
            with self.subTest(source_aware=source_aware), tempfile.TemporaryDirectory() as tmp:
                USAGE._LEDGER_CACHE.update(data=None, dirty=False)
                local = datetime.now().astimezone().replace(
                    hour=9, minute=0, second=0, microsecond=0)
                ts = _ts(local)
                day_key = local.date().isoformat()
                main_usage = _usage(100, 0, 10)
                reserve_usage = _usage(50, 0, 5)
                combined = _usage(150, 0, 15)
                path = Path(tmp) / "sessions" / "rollout-mixed-ledger.jsonl"
                _write_rollout(path, [
                    _session_meta_line(ts, "mixed-ledger"),
                    _turn_context_line(ts, "gpt-5.6-luna"),
                    _token_count_line(ts, main_usage, main_usage, _main_rl()),
                    _token_count_line(
                        _ts(local + timedelta(hours=1)), reserve_usage, combined, _reserve_rl()),
                ])
                old_days = {}
                USAGE._codex_add_event(old_days, [
                    ts, day_key, 100, 0, 10, 0, 100, 0, 10, 0,
                    USAGE._codex_estimated_cost("gpt-5.6-luna", 100, 0, 10),
                    "openai/gpt-5.6-luna", None,
                ])
                USAGE._codex_add_event(old_days, [
                    _ts(local + timedelta(hours=1)), day_key, 150, 0, 15, 0, 50, 0, 5, 0,
                    USAGE._codex_estimated_cost("gpt-reserve", 50, 0, 5),
                    "gpt-reserve", None,
                ])
                old_day = old_days[day_key]
                old_day.pop("model_hours", None)  # pre-v7 aggregate/source ledger shape
                if source_aware:
                    source_id = hashlib.sha256(b"mixed-ledger").hexdigest()
                    snapshot = dict(old_day, _accounting_version=6)
                    stored = dict(old_day, _sources={source_id: snapshot})
                else:
                    stored = old_day
                USAGE._LEDGER_CACHE["data"] = {
                    "v": USAGE._LEDGER_VERSION,
                    "tools": {"codex": {day_key: stored}},
                }
                result, cache = self._scan(tmp)

                main = result["ranges"]["all"]
                reserve = result["reserve_ranges"]["all"]
                self.assertEqual(main["in"], 100)
                self.assertEqual(reserve["in"], 50)
                self.assertEqual(main["in"] + reserve["in"], 150)
                self.assertEqual(main["out"] + reserve["out"], 15)
                self.assertEqual(USAGE._CODEX_PARSER_VERSION, 7)
                self.assertEqual(USAGE._CODEX_ACCOUNTING_VERSION, 7)
                entry = cache["codex"][str(path.resolve())]
                self.assertEqual(entry["parser_version"], 7)
                self.assertEqual(entry["accounting_version"], 7)
                ledger = USAGE._load_ledger()["tools"]
                self.assertEqual(ledger["codex"][day_key]["in"], 100)
                self.assertEqual(ledger["codex_reserve"][day_key]["in"], 50)
                self.assertNotIn("gpt-reserve", ledger["codex"][day_key]["models"])
                self.assertEqual(
                    set(ledger["codex_reserve"][day_key]["models"]), {"gpt-reserve"})
                source_id = hashlib.sha256(b"mixed-ledger").hexdigest()
                for tool in ("codex", "codex_reserve"):
                    snapshot = ledger[tool][day_key]["_sources"][source_id]
                    self.assertEqual(snapshot["_accounting_version"], 7)
                    self.assertEqual(snapshot["_ledger_version"], 7)

    def test_reserve_is_in_daily_wrapped_and_separate_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_files(tmp)
            result, cache = self._scan(tmp)
            daily = USAGE.build_daily_costs("all", refresh=False, _cache=cache)
            wrapped = USAGE.build_wrapped("all", refresh=False, _cache=cache)

        row = daily["daily"][-1]
        main = result["ranges"]["all"]
        reserve = result["reserve_ranges"]["all"]
        self.assertEqual(row["codex"], round(main["cost"], 2))
        self.assertEqual(row["codex_reserve"], round(reserve["cost"], 2))
        self.assertEqual(row["total"], round(main["cost"] + reserve["cost"], 2))
        self.assertEqual(row["tokens"], main["in"] + main["out"] + reserve["in"] + reserve["out"])
        self.assertEqual({m["tool"] for m in daily["models"]}, {"codex", "codex_reserve"})
        self.assertEqual(wrapped["total_tokens"], row["tokens"])
        self.assertAlmostEqual(wrapped["total_cost"], row["total"], places=2)
        self.assertTrue(any("Luna Reserve" in m["name"] for m in daily["models"]))

    def test_reserve_reasoning_is_not_double_counted_in_wrapped(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
            usage = _usage(120, 80, 30, 20)
            _write_rollout(Path(tmp) / "sessions" / "rollout-reserve-only.jsonl", [
                _session_meta_line(_ts(now), "reserve-only"),
                _turn_context_line(_ts(now), "gpt-reserve"),
                _token_count_line(_ts(now), usage, usage, _reserve_rl()),
            ])
            _, cache = self._scan(tmp)
            daily = USAGE.build_daily_costs("all", refresh=False, _cache=cache)
            wrapped = USAGE.build_wrapped("all", refresh=False, _cache=cache)

        self.assertEqual(daily["daily"][-1]["tokens"], 150)
        reserve_model = next(
            model for model in daily["models"] if model["tool"] == "codex_reserve")
        self.assertEqual(reserve_model["tokens"], 150)
        self.assertEqual(reserve_model["reason"], 20)
        self.assertEqual(wrapped["total_tokens"], 150)
        self.assertEqual(sum(wrapped["hours"]), 150)
        self.assertEqual(wrapped["top_model"]["tokens"], 150)
        self.assertIn("Luna Reserve", wrapped["top_model"]["name"])

    def test_custom_provider_hides_reserve_quota(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_files(tmp)
            result, _ = self._scan(tmp, custom_provider=True)
        self.assertIsNone(result["reserve_quota"])

    def test_swift_dashboard_and_panel_preserve_reserve_semantics(self):
        root = Path(__file__).resolve().parents[1]
        sources = root / "Tokei/Sources/Tokei"
        model = (sources / "Model.swift").read_text()
        dashboard = (sources / "DashboardView.swift").read_text()
        panel = (sources / "PanelView.swift").read_text()
        main = (sources / "main.swift").read_text()

        self.assertIn("var stale: Bool?", model)
        self.assertIn("let pct = q.usedPercent, q.stale != true", panel)
        self.assertIn("Reserve 额度读数已过期", panel)
        self.assertIn("+ reserve.tokens", dashboard)
        self.assertIn("+ (usage.codex.reserveRanges?.get(key).cost ?? 0)", dashboard)
        self.assertIn("total += r.tokens + reserve.tokens", main)

    def test_expired_reserve_quota_resets_or_becomes_stale_from_consumption(self):
        now = datetime.now(timezone.utc).replace(minute=30, second=0, microsecond=0)
        reset = int((now - timedelta(hours=1)).timestamp())
        limits = _reserve_rl()
        limits["primary"]["resets_at"] = reset

        for consumed_after_reset, expected_used, expected_reset, expected_stale in (
                (False, 0.0, None, False), (True, 10.0, reset, True)):
            with self.subTest(consumed_after_reset=consumed_after_reset), \
                 tempfile.TemporaryDirectory() as tmp:
                USAGE._LEDGER_CACHE.update(data=None, dirty=False)
                event_time = now if consumed_after_reset else now - timedelta(hours=2)
                usage = _usage(50, 0, 5)
                _write_rollout(Path(tmp) / "sessions" / "rollout-quota.jsonl", [
                    _session_meta_line(_ts(event_time), "quota"),
                    _turn_context_line(_ts(event_time), "gpt-reserve"),
                    _token_count_line(_ts(event_time), usage, usage, limits),
                ])
                result, _ = self._scan(tmp)

            quota = result["reserve_quota"]
            self.assertEqual(quota["used_percent"], expected_used)
            self.assertEqual(quota["resets_at"], expected_reset)
            self.assertEqual(quota["stale"], expected_stale)

    def test_reserve_cost_uses_luna_pricing(self):
        luna = USAGE._codex_estimated_cost("gpt-5.6-luna", 1000, 900, 100)
        reserve = USAGE._codex_estimated_cost("gpt-reserve", 1000, 900, 100)
        gpt55 = USAGE._codex_estimated_cost("openai/gpt-5.5", 1000, 900, 100)
        self.assertAlmostEqual(reserve, luna, places=9)
        self.assertLess(reserve, gpt55 / 10)

    def test_reserve_helpers(self):
        self.assertTrue(USAGE._codex_is_reserve_model("gpt-reserve"))
        self.assertTrue(USAGE._codex_is_reserve_model("GPT-Reserve"))
        self.assertFalse(USAGE._codex_is_reserve_model("gpt-5.6-luna"))
        self.assertFalse(USAGE._codex_is_reserve_model(None))
        self.assertTrue(USAGE._codex_is_reserve_limits(
            {"limit_id": "base_model_inference", "limit_name": "gpt-reserve"}))
        self.assertTrue(USAGE._codex_is_reserve_limits(
            {"limit_id": "base_model_inference", "limit_name": None}))
        self.assertFalse(USAGE._codex_is_reserve_limits(
            {"limit_id": "codex", "limit_name": None}))
        self.assertFalse(USAGE._codex_is_reserve_limits(None))


if __name__ == "__main__":
    unittest.main()
