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

    def test_summary_is_token_weighted_and_ttft_needs_enough_samples(self):
        perf = {}
        for _ in range(4):
            USAGE._perf_add(perf, "claude-opus-5-5", 100, 1, 1.1)
        USAGE._perf_add(perf, "claude-opus-5-5", 900, 29)   # 一个慢的长请求
        summary = USAGE._perf_summary(perf)
        self.assertEqual(summary["tps"], round(1300 / 33, 1), "按总 token / 总时长，不是平均每个请求的速度")
        self.assertIsNone(summary["ttft"], "首字只有 4 个样本，中位数不稳，不显示")
        USAGE._perf_add(perf, "claude-opus-5-5", 100, 1, 1.2)
        summary = USAGE._perf_summary(perf)
        self.assertTrue(1.0 <= summary["ttft"] <= 1.25)
        self.assertIn("Opus 5.5", summary["models"], "按显示名汇总，和卡片上的模型行对得上")

    def test_merging_two_sources_adds_everything_up(self):
        a, b = {}, {}
        USAGE._perf_add(a, "m", 100, 2, 0.5)
        USAGE._perf_add(b, "m", 300, 4, 3.0)
        merged = USAGE._perf_merge(USAGE._perf_merge({}, a), b)
        self.assertEqual((merged["m"]["o"], merged["m"]["g"], merged["m"]["n"]), (400, 6.0, 2))
        self.assertEqual(sum(merged["m"]["t"].values()), 2)


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
        # 首字分桶存，中位数在桶内插值：正好 2 秒的样本落在 2–2.5 秒那一桶
        self.assertTrue(2.0 <= summary["ttft"] <= 2.5, "首字算到第一段思考，工具执行不算")

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
        self.assertTrue(0.4 <= summary["ttft"] <= 0.6)

    def test_without_thinking_timing_speed_is_end_to_end(self):
        result = self.scan(self.records(5, think=False))
        summary = USAGE._perf_summary(result["ranges"]["all"].get("perf"))
        self.assertEqual(summary["tps"], round(400 / 6, 1), "从用户消息算到最后一段输出")
        self.assertIsNone(summary["ttft"])


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
