"""输出速度与首字延迟：按请求计时，按「天 × 模型」汇总。"""
import json
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from test_codex_limits import USAGE


class PerfHelperTests(unittest.TestCase):
    def test_samples_are_filtered_and_summed_by_model(self):
        perf = {}
        self.assertTrue(USAGE._perf_add(perf, "m", 500, 10, 1.0))
        self.assertFalse(USAGE._perf_add(perf, "m", 5, 10), "输出太少的请求不计")
        self.assertFalse(USAGE._perf_add(perf, "m", 5000, 0.5), "比 3000 tok/s 还快说明时间戳不可信")
        self.assertFalse(USAGE._perf_add(perf, "m", 500, 0), "没有时长不计")
        self.assertEqual((perf["m"]["o"], perf["m"]["g"], perf["m"]["n"]), (500, 10.0, 1))

    def test_summary_is_token_weighted_and_ttft_is_a_median(self):
        perf = {}
        USAGE._perf_add(perf, "claude-opus-5-5", 100, 1, 2.4)
        USAGE._perf_add(perf, "claude-opus-5-5", 900, 29)   # 一个拿不到首字时间的慢请求
        summary = USAGE._perf_summary(perf)
        self.assertEqual(summary["tps"], round(1000 / 30, 1), "按总 token / 总时长，不是平均每个请求的速度")
        self.assertEqual(round(summary["ttft"], 1), 2.4, "一个样本也显示，细分桶插值不出显示精度")
        for seconds in (1.0, 1.1, 60.0, 90.0):
            USAGE._perf_add(perf, "claude-opus-5-5", 100, 1, seconds)
        summary = USAGE._perf_summary(perf)
        self.assertEqual(round(summary["ttft"], 1), 2.4, "排队几十秒的长尾不把典型值拉高")
        self.assertEqual((summary["n"], summary["tn"], summary["o"]), (6, 5, 1400))
        self.assertEqual(sum(summary["th"].values()), 5, "直方图一起给 App，合并多台设备时重算中位数")
        self.assertIn("Opus 5.5", summary["models"], "按显示名汇总，和卡片上的模型行对得上")

    def test_every_ttft_lands_in_a_bucket_within_five_percent(self):
        for seconds in (0.0, 0.03, 0.05, 0.51, 3.0, 37.5, 120.0):
            low, high = USAGE._perf_ttft_bounds(USAGE._perf_ttft_bucket(seconds))
            self.assertTrue(low <= seconds < high or seconds == high, seconds)
            self.assertTrue(high - low <= max(0.05, high * 0.05 / 1.05) + 1e-9, seconds)

    def test_legacy_bucket_counts_never_exceed_the_request_count(self):
        legacy = {"m": {"o": 400, "g": 4.0, "n": 2, "t": {"9": 2}}}   # 旧的 2.0–2.5 秒粗桶
        self.assertTrue(2.2 <= USAGE._perf_summary(legacy)["ttft"] <= 2.4, "按粗桶中点 2.25 秒折进细分桶")
        stale = {"m": {"o": 400, "g": 4.0, "n": 2, "t": {"9": 2}, "th": {"40": 2}}}
        self.assertEqual(USAGE._perf_summary(stale)["tn"], 2, "新旧两份计数叠在一起时只认新的")

    def test_ledger_remainder_drops_speed_stats_without_requests(self):
        kept = {"in": 10, "perf": {"m": {"o": 100, "g": 1.0, "n": 1, "t": {"9": 1}}}}
        live = {"in": 10, "perf": {"m": {"o": 100, "g": 1.0, "n": 1, "th": {"40": 1}}}}
        merged = USAGE._ledger_merge_sources(kept, {"session": live}, "tool")
        self.assertEqual(merged["perf"]["m"]["n"], 1)
        self.assertNotIn("t", merged["perf"]["m"], "旧记录减去现有日志后没有剩下请求，旧分桶不该留下")

    def test_merging_two_sources_adds_everything_up(self):
        a, b = {}, {}
        USAGE._perf_add(a, "m", 100, 2, 0.5)
        USAGE._perf_add(b, "m", 300, 4, 3.0)
        merged = USAGE._perf_merge(USAGE._perf_merge({}, a), b)
        self.assertEqual((merged["m"]["o"], merged["m"]["g"], merged["m"]["n"]), (400, 6.0, 2))
        self.assertEqual(sum(merged["m"]["th"].values()), 2)


def _line(record):
    return json.dumps(record, separators=(",", ":"))


class CodexPerfTests(unittest.TestCase):
    T0 = datetime(2024, 1, 8, 1, 0, tzinfo=timezone.utc)

    def iso(self, seconds):
        return (self.T0 + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    def ms(self, seconds):
        return int((self.T0 + timedelta(seconds=seconds)).timestamp() * 1000)

    def request(self, start, total_out, ordinal=None):
        """一个请求：工具结果写入 → 2 秒后开始思考 → 跑一个命令 → 第 12 秒用量落盘，输出 500。"""
        head = {"timestamp": self.iso(start)}
        if ordinal is not None:
            head["ordinal"] = ordinal
        trigger = dict(head, type="response_item",
                       payload={"type": "function_call_output", "call_id": "c", "output": "ok"})
        command = {"timestamp": self.iso(start + 1), "type": "event_msg", "payload": {
            "type": "item_completed", "thread_id": "t", "turn_id": "u",
            "item": {"type": "CommandExecution", "id": "x"},
            "started_at_ms": self.ms(start + 1), "completed_at_ms": self.ms(start + 1)}}
        reasoning = {"timestamp": self.iso(start + 6), "type": "event_msg", "payload": {
            "type": "item_completed", "thread_id": "t", "turn_id": "u",
            "item": {"type": "Reasoning", "id": "r", "content": ["想" * 3000]},
            "started_at_ms": self.ms(start + 2), "completed_at_ms": self.ms(start + 6)}}
        tokens = {"timestamp": self.iso(start + 12), "type": "event_msg", "payload": {
            "type": "token_count", "info": {
                "total_token_usage": {"input_tokens": 1000 * total_out, "cached_input_tokens": 0,
                                      "output_tokens": 500 * total_out, "reasoning_output_tokens": 0},
                "last_token_usage": {"input_tokens": 1000, "cached_input_tokens": 0,
                                     "output_tokens": 500, "reasoning_output_tokens": 0}}}}
        return [_line(trigger), _line(command), _line(reasoning), _line(tokens)]

    def rollout(self, count):
        lines = [_line({"timestamp": self.iso(0), "type": "session_meta",
                        "payload": {"id": "s", "session_id": "s", "cwd": "/tmp/p"}}),
                 _line({"timestamp": self.iso(0), "type": "turn_context",
                        "payload": {"model": "gpt-6-sol", "cwd": "/tmp/p"}})]
        for i in range(count):
            lines += self.request(20 * i + 1, i + 1, ordinal=i if i % 2 else None)
        return lines

    def bounds(self):
        day = datetime(2024, 1, 8, tzinfo=timezone.utc)
        return {"today": day, "yesterday": day - timedelta(days=1), "week": day,
                "last_week": day - timedelta(days=7), "last_week_end": day,
                "month": day.replace(day=1), "year": day.replace(month=1, day=1)}

    def scan(self, tmp, cache):
        with mock.patch.object(USAGE, "CODEX_DIR", tmp), \
             mock.patch.object(USAGE, "CODEX_ARCHIVED_DIR", str(Path(tmp) / "archived")), \
             mock.patch.object(USAGE, "fetch_codex_live_limits", return_value=None):
            return USAGE.scan_codex(self.bounds(), cache)

    def test_ttft_runs_from_the_trigger_to_the_first_reasoning_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-a.jsonl"
            path.write_text("\n".join(self.rollout(6)) + "\n", encoding="utf-8")
            result = self.scan(tmp, {"v": USAGE._SCAN_CACHE_VERSION})
        summary = USAGE._perf_summary(result["ranges"]["all"].get("perf"))
        self.assertEqual(summary["n"], 6)
        self.assertEqual(summary["tps"], 50.0, "500 token / 从首字到落盘的 10 秒")
        self.assertEqual(round(summary["ttft"], 1), 2.0, "首字算到第一段思考，工具执行不算")

    def test_an_incremental_read_keeps_the_timing_state(self):
        lines = self.rollout(6)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-a.jsonl"
            cut = 2 + 4 * 3 + 2           # 第 4 个请求刚写完工具结果和命令
            path.write_text("\n".join(lines[:cut]) + "\n", encoding="utf-8")
            cache = {"v": USAGE._SCAN_CACHE_VERSION}
            self.scan(tmp, cache)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            result = self.scan(tmp, cache)
        summary = USAGE._perf_summary(result["ranges"]["all"].get("perf"))
        self.assertEqual((summary["n"], summary["tps"]), (6, 50.0))


class ClaudePerfTests(unittest.TestCase):
    def records(self, requests, think=True):
        base = datetime.now().astimezone().replace(microsecond=0) - timedelta(hours=1)
        rows = []
        for i in range(requests):
            start = base + timedelta(minutes=i)
            user_id, think_id, text_id = (str(uuid.uuid4()) for _ in range(3))
            rows.append({"type": "user", "message": {"role": "user", "content": "继续"},
                         "uuid": user_id, "timestamp": start.isoformat()})
            message = {"id": f"msg-{i}", "model": "claude-opus-5-5",
                       "usage": {"input_tokens": 10, "output_tokens": 400}}
            first = {"type": "assistant", "parentUuid": user_id, "requestId": f"req-{i}",
                     "message": dict(message, content=[{"type": "thinking"}]),
                     "uuid": think_id, "timestamp": (start + timedelta(seconds=2)).isoformat()}
            if think:
                first["thinkingDurationMs"] = 1500
            rows.append(first)
            rows.append({"type": "assistant", "parentUuid": think_id, "requestId": f"req-{i}",
                         "message": dict(message, content=[{"type": "text"}]),
                         "uuid": text_id, "timestamp": (start + timedelta(seconds=6)).isoformat()})
        return rows

    def scan(self, rows):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project" / "session.jsonl"
            path.parent.mkdir(parents=True)
            path.write_text("\n".join(_line(row) for row in rows) + "\n", encoding="utf-8")
            with mock.patch.object(USAGE, "CLAUDE_DIR", tmp):
                return USAGE.scan_claude(USAGE.range_bounds(), {"v": USAGE._SCAN_CACHE_VERSION})

    def test_thinking_duration_gives_first_token_and_generation_time(self):
        result = self.scan(self.records(5))
        summary = USAGE._perf_summary(result["ranges"]["all"].get("perf"))
        # 思考段 2 秒写入、思考了 1.5 秒 → 第 0.5 秒出首字；第 6 秒结束 → 生成 5.5 秒
        self.assertEqual(summary["n"], 5)
        self.assertEqual(summary["tps"], round(400 / 5.5, 1))
        self.assertEqual(round(summary["ttft"], 1), 0.5)

    def test_without_thinking_timing_speed_is_end_to_end(self):
        result = self.scan(self.records(5, think=False))
        summary = USAGE._perf_summary(result["ranges"]["all"].get("perf"))
        self.assertEqual(summary["tps"], round(400 / 6, 1), "从用户消息算到最后一段输出")
        self.assertIsNone(summary["ttft"])

    def test_request_start_skips_attachments_written_with_the_reply(self):
        start = datetime.now().astimezone().replace(microsecond=0) - timedelta(hours=1)
        at = lambda seconds: (start + timedelta(seconds=seconds)).isoformat()
        user_id, reminder_id, todo_id = (str(uuid.uuid4()) for _ in range(3))
        message = {"id": "msg-1", "model": "claude-opus-5-5",
                   "usage": {"input_tokens": 10, "output_tokens": 400}}
        # 真实日志的键序：parentUuid 打头，附件行的 type 紧挨着 uuid
        rows = [
            {"parentUuid": None, "isSidechain": False, "type": "user",
             "message": {"role": "user", "content": "继续"}, "uuid": user_id, "timestamp": at(0)},
            {"parentUuid": user_id, "isSidechain": False, "attachment": {"type": "todo_reminder"},
             "type": "attachment", "uuid": reminder_id, "timestamp": at(2)},
            {"parentUuid": reminder_id, "isSidechain": False, "attachment": {"type": "skill_listing"},
             "type": "attachment", "uuid": todo_id, "timestamp": at(2)},
            {"parentUuid": todo_id, "isSidechain": False, "type": "assistant", "requestId": "req-1",
             "message": dict(message, content=[{"type": "thinking"}]),
             "uuid": str(uuid.uuid4()), "timestamp": at(2), "thinkingDurationMs": 1500},
            {"parentUuid": None, "isSidechain": False, "type": "assistant", "requestId": "req-1",
             "message": dict(message, content=[{"type": "text"}]),
             "uuid": str(uuid.uuid4()), "timestamp": at(6)},
        ]
        summary = USAGE._perf_summary(self.scan(rows)["ranges"]["all"].get("perf"))
        self.assertEqual(summary["tn"], 1, "附件和回复同时写入，不能拿它当请求起点")
        self.assertEqual(round(summary["ttft"], 1), 0.5, "从用户消息算起")


if __name__ == "__main__":
    unittest.main()


class DurationFieldPerfTests(unittest.TestCase):
    """日志自带耗时字段的工具：只能算端到端（含首字等待）。"""

    def test_zcode_uses_the_call_start_and_end(self):
        import sqlite3
        now_ms = int(datetime.now().timestamp() * 1000)
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "db.sqlite"
            connection = sqlite3.connect(db)
            connection.execute("""CREATE TABLE model_usage (
                id TEXT PRIMARY KEY, session_id TEXT, model_id TEXT,
                input_tokens INTEGER, output_tokens INTEGER, reasoning_tokens INTEGER,
                cache_creation_input_tokens INTEGER, cache_read_input_tokens INTEGER,
                started_at INTEGER, completed_at INTEGER)""")
            connection.execute("INSERT INTO model_usage VALUES (?,?,?,?,?,?,?,?,?,?)",
                               ("r1", "s", "GLM-5.2", 100, 400, 100, 0, 0, now_ms - 4000, now_ms))
            connection.commit()
            connection.close()
            days = USAGE._scan_zcode_database(str(db))
        perf = USAGE._perf_summary(next(iter(days.values()))["perf"])
        self.assertEqual(perf["tps"], 100.0, "输出 400（已含推理）/ 4 秒")

    def test_qwen_request_carries_its_api_duration(self):
        from test_qwencode import request_record
        record = request_record("r1", "s1", 1000, output=300, thoughts=100)
        record["apiDurationMs"] = 2000
        entry = USAGE._qwen_request_entry(record)
        self.assertEqual(entry["gen"], 2.0)

    def test_muse_uses_the_model_call_duration(self):
        import test_musecode as muse
        case = muse.MuseCodeScanTests()
        with tempfile.TemporaryDirectory() as tmp:
            case.create_session(tmp)
            result, _ = case.scan(tmp)
        perf = USAGE._perf_summary(result["ranges"]["all"].get("perf"))
        # 两次调用各 1 秒：(500+50) + (200+10) 个 token
        self.assertEqual((perf["n"], perf["tps"]), (2, 380.0))


class QoderCliPerfTests(unittest.TestCase):
    def test_a_reply_runs_from_the_user_row_to_its_last_line(self):
        from test_qoder_usage import QoderUsageTests
        case = QoderUsageTests()
        start = datetime.now().astimezone().replace(microsecond=0) - timedelta(minutes=5)
        rows = [{"type": "user", "timestamp": start.isoformat(),
                 "message": {"role": "user", "content": "看看这个"}}]
        first = case.assistant((start + timedelta(seconds=2)).isoformat(), "m1", "r1",
                               input_tokens=100, output_tokens=400)
        last = case.assistant((start + timedelta(seconds=4)).isoformat(), "m1", "r1",
                              input_tokens=100, output_tokens=400)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "projects"
            case.write_jsonl(root / "project" / "session.jsonl", rows + [first, last])
            result, _ = case.scan_cli(root)
        perf = USAGE._perf_summary(result["ranges"]["all"].get("perf"))
        self.assertEqual((perf["n"], perf["tps"]), (1, 100.0), "400 token / 用户消息到最后一行的 4 秒")


class DeepSeekHarnessPerfTests(unittest.TestCase):
    def scan(self, events):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project" / "session.jsonl"
            path.parent.mkdir(parents=True)
            path.write_text("\n".join(json.dumps(item) for item in events) + "\n", encoding="utf-8")
            cache = {"v": USAGE._SCAN_CACHE_VERSION}
            with mock.patch.object(USAGE, "DEEPSEEK_HARNESS_DIR", tmp), \
                 mock.patch.object(USAGE, "ledger_reconcile",
                                   side_effect=lambda _tool, days, sources=None: days):
                result = USAGE.scan_deepseek_harness(USAGE.range_bounds(), cache)
        return USAGE._perf_summary(result["ranges"]["all"].get("perf"))

    def step(self, start, retry_at=None):
        def event(kind, at, **data):
            return {"type": kind, "time": start + at, "data": {"turn": 1, "step": 1, **data}}
        usage = {"inputTokens": 100, "outputTokens": 500, "reasoningTokens": 300}
        events = [event("step/start", 0),
                  event("assistant/chunk", 800, chunk={"type": "block-start", "index": 0}),
                  event("assistant/chunk", 900, chunk={"type": "block-start", "index": 1})]
        if retry_at is not None:
            events.append(event("llm/retry-started", retry_at))
            events.append(event("assistant/chunk", retry_at + 1_000,
                                chunk={"type": "block-start", "index": 0}))
        end = (retry_at or 0) + 6_000
        return events + [
            event("assistant/chunk", end, chunk={"type": "usage", "usage": usage}),
            event("assistant/chunk", end, chunk={"type": "finish"}),
            event("assistant/message", end + 20, usage=usage,
                  message={"source": {"provider": "deepseek-official", "model": "deepseek-v4-pro"}}),
        ]

    def test_first_block_and_finish_give_ttft_and_generation_time(self):
        start = int(datetime.now().timestamp() * 1000) - 60_000
        perf = self.scan(self.step(start))
        self.assertEqual((perf["n"], perf["tps"]), (1, 96.2), "含推理的 500 token / 首块到 finish 的 5.2 秒")
        self.assertEqual(round(perf["ttft"], 1), 0.8, "step 开始到第一个内容块")
        self.assertEqual(perf["models"]["Deepseek V4 Pro"]["n"], 1)

    def test_a_retry_restarts_the_clock(self):
        start = int(datetime.now().timestamp() * 1000) - 60_000
        perf = self.scan(self.step(start, retry_at=10_000))
        self.assertEqual(perf["tps"], 100.0, "重试后首块到 finish 是 5 秒")
        self.assertEqual(round(perf["ttft"], 1), 1.0, "TTFT 从重试开始算")


class LogAndDatabasePerfTests(unittest.TestCase):
    def test_hermes_reads_api_call_latency_from_agent_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs = Path(tmp) / ".hermes" / "logs"
            logs.mkdir(parents=True)
            (logs / "agent.log").write_text(
                "2026-06-04 18:03:59,497 INFO [s] agent.conversation_loop: API call #1: "
                "model=grok-4.3 provider=xai-oauth in=17277 out=326 total=17603 latency=5.0s\n"
                "2026-06-04 18:04:10,000 INFO [s] agent.conversation_loop: API call #2: "
                "model=grok-4.3 provider=xai-oauth in=17300 out=5 total=17305 latency=1.0s\n",
                encoding="utf-8")
            cache = {}
            with mock.patch.object(USAGE, "HOME", tmp):
                days = USAGE._hermes_log_perf(cache)
                with mock.patch.object(USAGE, "_perf_add", side_effect=AssertionError("reparsed")):
                    USAGE._hermes_log_perf(cache)
        perf = USAGE._perf_summary(days["2026-06-04"])
        self.assertEqual((perf["n"], perf["tps"]), (1, 65.2), "太短的回复不算样本")

    def test_pi_stream_seconds_runs_from_request_to_persist(self):
        self.assertEqual(USAGE._pi_stream_seconds("2026-06-04T10:00:05.500Z",
                                                  1780567200000), 5.5)
        self.assertIsNone(USAGE._pi_stream_seconds("2026-06-04T10:00:00.100Z", 1780567200000))
        self.assertIsNone(USAGE._pi_stream_seconds(None, 1780567200000))

    def test_opencode_steps_restart_after_the_previous_step(self):
        import sqlite3
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE message (id TEXT, data TEXT)")
        connection.execute("CREATE TABLE part (message_id TEXT, time_created INTEGER, data TEXT)")
        connection.execute("INSERT INTO message VALUES ('m1', ?)",
                           (json.dumps({"role": "assistant", "time": {"created": 1000}}),))
        parts = [
            (1000, {"type": "step-start"}),
            (3000, {"type": "reasoning", "time": {"start": 3000}}),
            (3500, {"type": "text", "time": {"start": 3500}}),
            (7000, {"type": "step-finish", "tokens": {"output": 300, "reasoning": 100}}),
            (9000, {"type": "step-start"}),
            (9500, {"type": "text", "time": {"start": 9500}}),
            (11500, {"type": "step-finish", "tokens": {"output": 200, "reasoning": 0}}),
        ]
        connection.executemany("INSERT INTO part VALUES ('m1', ?, ?)",
                               [(at, json.dumps(data)) for at, data in parts])
        timing = USAGE._opencode_step_timing(connection, {"message", "part"})
        self.assertEqual(timing["m1"], [(4.0, 2.0, 400), (2.0, 2.5, 200)])


class PerfStatMergeSwiftTests(unittest.TestCase):
    def test_devices_merge_by_recomputing_the_averages(self):
        import subprocess
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "perf-stat-merge-check"
            result = subprocess.run(
                ["swiftc", "-parse-as-library",
                 str(root / "Tokei/Sources/Tokei/Model.swift"),
                 str(root / "Tokei/Sources/Tokei/L10n.swift"),
                 str(root / "tests/swift/PerfStatMergeCheck.swift"),
                 "-o", str(binary)],
                capture_output=True, text=True, cwd=root)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("perf stat merge checks passed", result.stdout)

    def test_every_range_with_perf_merges_it_across_devices(self):
        import re
        root = Path(__file__).resolve().parents[1]
        model = (root / "Tokei/Sources/Tokei/Model.swift").read_text(encoding="utf-8")
        sync = (root / "Tokei/Sources/Tokei/SyncManager.swift").read_text(encoding="utf-8")
        with_perf = {match.group(1) for match in re.finditer(
            r"struct (\w+)Range: Codable \{(?:(?!\nstruct ).)*?var perf: PerfStat\?", model, re.S)}
        self.assertTrue({"Claude", "Codex", "Hermes", "TokenUsage"} <= with_perf)
        for name in with_perf:
            body = re.search(r"func mergeRanges\(_ dst: inout " + name + r"Ranges,.*?\n    \}\n",
                             sync, re.S)
            self.assertIsNotNone(body, name)
            self.assertIn("PerfStat.merged(d.perf, s.perf)", body.group(0), name)


class UsageDecodeStackTests(unittest.TestCase):
    def test_app_decodes_usage_only_on_the_big_stack_thread(self):
        # Usage 的解码栈帧会超过 GCD 工作线程 512 KB 的栈：在后台队列里直接解码会崩溃
        root = Path(__file__).resolve().parents[1] / "Tokei/Sources/Tokei"
        offenders = [path.name for path in root.glob("*.swift")
                     if path.name != "Model.swift"
                     and "decode(Usage.self" in path.read_text(encoding="utf-8")]
        self.assertEqual(offenders, [], "请改用 Usage.decode(from:)")
