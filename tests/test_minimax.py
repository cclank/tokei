import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from test_codex_limits import USAGE


def log_line(session_id, turn_id, model):
    record = {"session_id": session_id, "turn_id": turn_id, "provider": "minimax",
              "model": model, "response_status": 200}
    return f"[16:20:26.013] INFO: [] llm_response_identifiers {json.dumps(record)}\n"


class MiniMaxHome:
    """一份最小的 ~/.minimax/v2：sqlite/runtime-state.sqlite + observability/logs。"""

    def __init__(self, root):
        self.root = Path(root)
        (self.root / "sqlite").mkdir(parents=True)
        self.logs = self.root / "observability" / "logs"
        self.logs.mkdir(parents=True)
        self.db = self.root / "sqlite" / "runtime-state.sqlite"
        connection = sqlite3.connect(self.db)
        connection.execute("""CREATE TABLE local_runtime_token_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
            agent_name TEXT NOT NULL, framework_type TEXT NOT NULL, turn_id TEXT,
            model TEXT, ts INTEGER NOT NULL, input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL, reasoning_tokens INTEGER NOT NULL,
            cache_read_tokens INTEGER NOT NULL, cache_write_tokens INTEGER NOT NULL,
            cost_usd REAL, raw TEXT)""")
        connection.execute("""CREATE TABLE local_runtime_sessions (
            session_id TEXT PRIMARY KEY, record_json TEXT NOT NULL,
            updated_at_ms INTEGER NOT NULL, workspace_dir TEXT,
            project_workspace_dir TEXT, is_default_workspace INTEGER)""")
        connection.commit()
        connection.close()

    def session(self, session_id, workdir, is_default=0):
        connection = sqlite3.connect(self.db)
        connection.execute(
            "INSERT INTO local_runtime_sessions VALUES (?, '{}', 0, ?, ?, ?)",
            (session_id, workdir, workdir, is_default))
        connection.commit()
        connection.close()

    def usage(self, session_id, turn_id, *, ts, inp=100, out=10, cr=0, cw=0,
              reasoning=0, model=None, total=None):
        raw = {"input": inp, "output": out, "cacheRead": cr, "cacheWrite": cw,
               "totalTokens": total if total is not None else inp + out + cr + cw}
        connection = sqlite3.connect(self.db)
        connection.execute(
            "INSERT INTO local_runtime_token_usage (session_id, agent_name, "
            "framework_type, turn_id, model, ts, input_tokens, output_tokens, "
            "reasoning_tokens, cache_read_tokens, cache_write_tokens, cost_usd, raw) "
            "VALUES (?, 'mavis', 'pi-agent', ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
            (session_id, turn_id, model, ts, inp, out, reasoning, cr, cw, json.dumps(raw)))
        connection.commit()
        connection.close()

    def log(self, name, text):
        with open(self.logs / name, "a", encoding="utf-8") as handle:
            handle.write(text)


def epoch_ms(year=2026, month=9, day=28, hour=16):
    return int(datetime(year, month, day, hour).timestamp() * 1000)


class MiniMaxLogTests(unittest.TestCase):
    def test_reads_incrementally_and_leaves_a_half_written_line_for_later(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = MiniMaxHome(tmp)
            home.log("runtime-2026092816.log", log_line("s1", "t1", "MiniMax-M3")
                     + "[16:21:00.000] INFO: [] unrelated {\"turn_id\":\"x\"}\n"
                     + log_line("s1", "t2", "MiniMax-M3").rstrip("\n"))
            offsets, pending = {}, {}
            learned = USAGE._minimax_read_turn_models(str(home.logs), offsets, pending, now=1)
            self.assertEqual(learned, 1)
            self.assertEqual(set(pending), {"t1"}, "只认 llm_response_identifiers，半行不读")

            home.log("runtime-2026092816.log", "\n")
            learned = USAGE._minimax_read_turn_models(str(home.logs), offsets, pending, now=2)
            self.assertEqual(learned, 1, "只读新增的部分，不重复认识 t1")
            self.assertEqual(pending["t2"], ["MiniMax-M3", 2])

    def test_a_rotated_file_is_forgotten_and_a_rewritten_one_is_read_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = MiniMaxHome(tmp)
            home.log("runtime-2026092816.log", log_line("s1", "t1", "MiniMax-M3"))
            offsets, pending = {}, {}
            USAGE._minimax_read_turn_models(str(home.logs), offsets, pending)
            (home.logs / "runtime-2026092816.log").unlink()
            home.log("runtime-2026092817.log", log_line("s1", "t2", "MiniMax-M3") * 3)
            USAGE._minimax_read_turn_models(str(home.logs), offsets, pending)
            self.assertEqual(set(offsets), {"runtime-2026092817.log"})

            (home.logs / "runtime-2026092817.log").write_text(
                log_line("s1", "t3", "MiniMax-M2.7"), encoding="utf-8")
            USAGE._minimax_read_turn_models(str(home.logs), offsets, pending)
            self.assertIn("t3", pending, "文件变短说明被重写，要从头读")


class MiniMaxDatabaseTests(unittest.TestCase):
    def test_tokens_are_four_parallel_buckets_and_the_model_comes_from_the_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = MiniMaxHome(tmp)
            home.usage("s1", "t1", ts=epoch_ms(), inp=9124, out=690, cr=128)
            days, runs, through, matched = USAGE._scan_minimax_database(
                str(home.db), {"t1": ["MiniMax-M3", 0]}, [], 0)
        day = days["2026-09-28"]
        self.assertEqual((day["in"], day["out"], day["cr"], day["cw"]), (9124, 690, 128, 0))
        self.assertEqual(USAGE.token_total(day), 9942, "与 raw.totalTokens 一致")
        self.assertEqual(list(day["models"]), ["minimax/minimax-m3"])
        self.assertGreater(day["cost"], 0, "按 MiniMax-M3 的公开价折算")
        self.assertEqual(matched, {"t1"})
        self.assertEqual((runs, through), ([[1, "MiniMax-M3"]], 1))

    def test_models_survive_log_rotation_through_the_row_runs(self):
        """日志按小时轮转被删掉之后，已经对上的模型不能跟着丢。"""
        with tempfile.TemporaryDirectory() as tmp:
            home = MiniMaxHome(tmp)
            home.usage("s1", "t1", ts=epoch_ms())
            home.usage("s1", "t2", ts=epoch_ms())
            _, runs, through, _ = USAGE._scan_minimax_database(
                str(home.db), {"t1": ["MiniMax-M3", 0], "t2": ["MiniMax-M2.7", 0]}, [], 0)
            home.usage("s1", "t3", ts=epoch_ms())
            days, runs, through, _ = USAGE._scan_minimax_database(
                str(home.db), {"t3": ["MiniMax-M2.7", 0]}, runs, through)
        models = days["2026-09-28"]["models"]
        self.assertEqual(models["minimax/minimax-m3"]["in"], 100)
        self.assertEqual(models["minimax/minimax-m2.7"]["in"], 200)
        self.assertEqual(runs, [[1, "MiniMax-M3"], [2, "MiniMax-M2.7"]], "按行号区间压缩")
        self.assertEqual(through, 3)

    def test_a_session_fallback_is_shown_but_never_stored_as_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = MiniMaxHome(tmp)
            home.usage("s1", "t1", ts=epoch_ms())
            home.usage("s1", "t2", ts=epoch_ms())
            days, runs, _, _ = USAGE._scan_minimax_database(
                str(home.db), {"t1": ["MiniMax-M3", 0]}, [], 0)
        self.assertEqual(days["2026-09-28"]["models"]["minimax/minimax-m3"]["in"], 200)
        self.assertEqual(runs, [[1, "MiniMax-M3"], [2, None]])

    def test_a_rebuilt_database_discards_the_old_row_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = MiniMaxHome(tmp)
            home.usage("s1", "t1", ts=epoch_ms())
            days, runs, through, _ = USAGE._scan_minimax_database(
                str(home.db), {}, [[1, "MiniMax-M3"], [5, "MiniMax-M2.7"]], 9)
        self.assertEqual(list(days["2026-09-28"]["models"]), ["minimax"])
        self.assertEqual((runs, through), ([[1, None]], 1))

    def test_only_user_workspaces_count_as_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = MiniMaxHome(tmp)
            scratch = os.path.join(USAGE.HOME, ".minimax", "sessions", "s1", "workspace")
            home.session("s1", scratch, is_default=1)
            home.session("s2", os.path.join(USAGE.HOME, ".minimax-agent-cn", "projects"))
            home.session("s3", "/work/tokei")
            for session_id in ("s1", "s2", "s3"):
                home.usage(session_id, "t-" + session_id, ts=epoch_ms())
            days, *_ = USAGE._scan_minimax_database(str(home.db), {}, [], 0)
        day = days["2026-09-28"]
        self.assertEqual(list(day.get("projects", {})), ["/work/tokei"])
        self.assertEqual(day["projects"]["/work/tokei"]["sessions"], ["s3"])
        self.assertEqual(day["sessions"], ["s1", "s2", "s3"], "会话照常计数")

    def test_reasoning_counts_only_when_the_raw_total_says_it_is_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = MiniMaxHome(tmp)
            home.usage("s1", "t1", ts=epoch_ms(), inp=100, out=10, reasoning=5)
            home.usage("s1", "t2", ts=epoch_ms(), inp=100, out=10, reasoning=5, total=115)
            days, *_ = USAGE._scan_minimax_database(str(home.db), {}, [], 0)
        self.assertEqual(days["2026-09-28"]["reason"], 5)
        self.assertEqual(USAGE.token_total(days["2026-09-28"]), 225)

    def test_a_store_without_the_usage_table_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "runtime-state.sqlite"
            sqlite3.connect(db).close()
            self.assertEqual(USAGE._scan_minimax_database(str(db), {}, [], 0),
                             ({}, [], 0, set()))


class MiniMaxScanTests(unittest.TestCase):
    def setUp(self):
        self.old_paths = USAGE.MINIMAX_DB_PATHS
        self.old_ledger = USAGE._LEDGER_FILE

    def tearDown(self):
        USAGE.MINIMAX_DB_PATHS = self.old_paths
        USAGE._LEDGER_FILE = self.old_ledger
        USAGE._LEDGER_CACHE.update({"data": None, "dirty": False})

    def scan(self, tmp, cache):
        USAGE._LEDGER_FILE = str(Path(tmp) / "ledger.json")
        USAGE._LEDGER_CACHE.update({"data": None, "dirty": False})
        return USAGE.scan_minimax(USAGE.range_bounds(), cache)

    def test_a_log_that_lands_after_the_row_still_fills_in_the_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = MiniMaxHome(Path(tmp) / "v2")
            USAGE.MINIMAX_DB_PATHS = [str(home.db)]
            cache = {"v": USAGE._SCAN_CACHE_VERSION}
            now = int(datetime.now().timestamp() * 1000)
            home.usage("s1", "t1", ts=now)
            result = self.scan(tmp, cache)
            self.assertEqual(list(result["ranges"]["today"]["models"]), ["minimax"])

            home.log("runtime-2026092816.log", log_line("s1", "t1", "MiniMax-M3"))
            result = self.scan(tmp, cache)
            entry = next(iter(cache["minimax"].values()))
        self.assertEqual(list(result["ranges"]["today"]["models"]), ["minimax/minimax-m3"])
        self.assertEqual(entry["pending"], {}, "对上的 turn 已固化进 runs，不再暂存")
        self.assertEqual(entry["runs"], [[1, "MiniMax-M3"]])

    def test_a_version_bump_keeps_the_evidence_gathered_from_rotated_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = MiniMaxHome(Path(tmp) / "v2")
            USAGE.MINIMAX_DB_PATHS = [str(home.db)]
            home.usage("s1", "t1", ts=int(datetime.now().timestamp() * 1000))
            key = "db:" + os.path.realpath(home.db)
            cache = {"v": USAGE._SCAN_CACHE_VERSION, "minimax": {key: {
                "version": 0, "runs": [[1, "MiniMax-M3"]], "through": 1, "days": {}}}}
            result = self.scan(tmp, cache)
        self.assertEqual(list(result["ranges"]["today"]["models"]), ["minimax/minimax-m3"])

    def test_no_database_reports_empty_ranges(self):
        with tempfile.TemporaryDirectory() as tmp:
            USAGE.MINIMAX_DB_PATHS = [str(Path(tmp) / "missing.sqlite")]
            result = self.scan(tmp, {"v": USAGE._SCAN_CACHE_VERSION})
        self.assertEqual(USAGE.token_total(result["ranges"]["all"]), 0)

    def test_minimax_joins_the_project_dimension(self):
        self.assertIn("minimax", {tool for tool, _ in USAGE._PROJECT_DAY_SOURCES})

    def test_model_names_keep_the_brand_casing_and_resolve_to_a_price(self):
        self.assertEqual(USAGE.nice_model("minimax/minimax-m3"), "MiniMax M3")
        self.assertEqual(USAGE.nice_model("MiniMax-M2.7-highspeed"), "MiniMax M2.7 Highspeed")
        self.assertEqual(USAGE._pricing_id("MiniMax-M3"), "minimax/minimax-m3")
        # highspeed 用 MiniMax 官方按量价（OpenRouter 未收录）
        self.assertEqual(USAGE._pricing_id("MiniMax-M2.7-highspeed"), "minimax/minimax-m2.7-highspeed")
        self.assertEqual(USAGE._raw_price("MiniMax-M2.7-highspeed")["in"], 0.6)
        # 还没公开定价的预览版沿用同一版本线上一个版本（M3）的价
        self.assertEqual(USAGE._pricing_id("MiniMax-M3.1-Flash-Preview"), "minimax/minimax-m3")


class MiniMaxQuotaTests(unittest.TestCase):
    def setUp(self):
        self.old_user_dir = USAGE._USER_DIR
        self.old_cache = USAGE.PROVIDER_QUOTA_CACHE
        self.old_env = dict(USAGE.os.environ)
        self.tmp = tempfile.TemporaryDirectory()
        USAGE._USER_DIR = self.tmp.name
        USAGE.PROVIDER_QUOTA_CACHE = str(Path(self.tmp.name, "provider_quota_cache.json"))
        Path(self.tmp.name, "config.json").write_text("{}", encoding="utf-8")
        for key in ("TOKEI_MINIMAX_API_KEY", "TOKEI_MINIMAX_REGION", "TOKEI_MINIMAX_QUOTA"):
            USAGE.os.environ.pop(key, None)

    def tearDown(self):
        USAGE._USER_DIR = self.old_user_dir
        USAGE.PROVIDER_QUOTA_CACHE = self.old_cache
        USAGE.os.environ.clear()
        USAGE.os.environ.update(self.old_env)
        self.tmp.cleanup()

    def windows(self, payload):
        quota = USAGE._normalize_minimax_quota(payload, updated=1_790_000_000)
        return {window["id"]: window for window in quota["windows"]}

    def test_remaining_percent_shape(self):
        windows = self.windows({"model_remains": [{
            "model_name": "general",
            "current_interval_remaining_percent": 70, "end_time": 1_790_003_600_000,
            "current_weekly_remaining_percent": 95, "weekly_end_time": 1_790_500_000_000,
            "interval_boost_permille": 1500}]})
        self.assertEqual(windows["minimax-5h"]["used_pct"], 30)
        self.assertEqual(windows["minimax-5h"]["reset"], 1_790_003_600)
        self.assertEqual(windows["minimax-5h"]["window_minutes"], 300)
        self.assertEqual(windows["minimax-weekly"]["used_pct"], 5)

    def test_used_over_boosted_total_percent_strings(self):
        windows = self.windows({"model_remains": [{
            "model_name": "general",
            "current_interval_used_percent": "75%", "current_interval_total_percent": "150%",
            "current_weekly_used_percent": "10", "current_weekly_total_percent": ""}]})
        self.assertEqual(windows["minimax-5h"]["used_pct"], 50, "加赠后总额 150%")
        self.assertEqual(windows["minimax-weekly"]["used_pct"], 10)

    def test_usage_count_is_the_remaining_count(self):
        """官方字段名叫 usage_count，桌面端的解析证明它其实是「剩余」次数。"""
        windows = self.windows({"model_remains": [{
            "model_name": "MiniMax-M2",
            "current_interval_total_count": 1500, "current_interval_usage_count": 1200,
            "remains_time": 3_600_000}]})
        self.assertEqual(windows["minimax-5h"]["used_pct"], 20)
        self.assertEqual(windows["minimax-5h"]["detail"], "300/1,500 次")
        self.assertEqual(windows["minimax-5h"]["reset"], 1_790_003_600)

    def test_unlimited_windows_and_the_video_pool(self):
        windows = self.windows({"model_remains": [
            {"model_name": "video-01", "current_interval_total_count": 10,
             "current_interval_usage_count": 4},
            {"model_name": "general", "current_interval_status": 3,
             "current_weekly_status": 3}]})
        self.assertEqual(windows["minimax-5h"]["used_pct"], 0)
        self.assertEqual(windows["minimax-5h"]["detail"], "不限量")
        self.assertEqual(windows["minimax-video"]["used_pct"], 60)

    def test_an_empty_answer_is_not_available(self):
        self.assertFalse(USAGE._normalize_minimax_quota({"model_remains": []})["available"])

    def test_the_query_is_opt_in_and_needs_a_key(self):
        self.assertFalse(USAGE._provider_quota_enabled("minimax"))
        with mock.patch.object(USAGE, "_provider_json_request") as request:
            self.assertEqual(USAGE.fetch_minimax_quota(), {})
        request.assert_not_called()

    def test_a_key_from_the_other_region_falls_through_to_it(self):
        USAGE.os.environ["TOKEI_MINIMAX_API_KEY"] = "sk-cp-test"
        calls = []

        def respond(url, headers=None, timeout=None):
            calls.append(url)
            self.assertEqual(headers, {"Authorization": "Bearer sk-cp-test"})
            if "minimaxi.com" in url:
                return {"base_resp": {"status_code": 1004, "status_msg": "cookie is missing"}}
            return {"model_remains": [{"model_name": "general",
                                       "current_interval_remaining_percent": 40}],
                    "base_resp": {"status_code": 0}}

        with mock.patch.object(USAGE, "_provider_json_request", side_effect=respond):
            quota = USAGE.fetch_minimax_quota()
            self.assertEqual(quota["region"], "global")
            self.assertEqual(quota["windows"][0]["used_pct"], 60)
            self.assertEqual(len(calls), 2)
            self.assertEqual(USAGE.fetch_minimax_quota(), quota, "TTL 内走缓存")
            self.assertEqual(len(calls), 2)

    def test_a_missing_endpoint_falls_back_to_the_documented_one(self):
        USAGE.os.environ["TOKEI_MINIMAX_API_KEY"] = "sk-cp-test"
        USAGE.os.environ["TOKEI_MINIMAX_REGION"] = "cn"

        def respond(url, headers=None, timeout=None):
            if "openplatform" in url:
                raise RuntimeError("HTTP 404")
            return {"model_remains": [{"model_name": "general",
                                       "current_interval_remaining_percent": 90}]}

        with mock.patch.object(USAGE, "_provider_json_request", side_effect=respond):
            quota = USAGE.fetch_minimax_quota()
        self.assertEqual(quota["windows"][0]["used_pct"], 10)

    def test_a_rejected_key_is_not_retried_on_every_refresh(self):
        USAGE.os.environ["TOKEI_MINIMAX_API_KEY"] = "sk-cp-wrong"
        rejected = {"base_resp": {"status_code": 1004, "status_msg": "unauthorized"}}
        with mock.patch.object(USAGE, "_provider_json_request",
                               return_value=rejected) as request:
            with self.assertRaises(PermissionError):
                USAGE.fetch_minimax_quota()
            self.assertEqual(request.call_count, 2, "两个区域各试一次")
            self.assertEqual(USAGE.fetch_minimax_quota(), {})
            self.assertEqual(request.call_count, 2, "失败同样按 TTL 节流")

    def test_quota_never_rides_along_in_sync_snapshots(self):
        payload = {"minimax": {"ranges": {"today": {"in": 1}}, "quota": {"available": True}},
                   "devin": {"ranges": {}, "quota": {"account": "someone@example.com"}}}
        snapshot = USAGE._sync_safe_usage_payload(payload)
        self.assertEqual(snapshot["minimax"], {"ranges": {"today": {"in": 1}}})
        self.assertEqual(snapshot["devin"], {"ranges": {}})
        self.assertIn("quota", payload["devin"], "只改快照，不改本机数据")


if __name__ == "__main__":
    unittest.main()
