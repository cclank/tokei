import json
import os
import random
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

try:
    from .test_codex_limits import USAGE
except ImportError:
    from test_codex_limits import USAGE


def isolate_ledger(testcase):
    USAGE._LEDGER_CACHE.update({"data": None, "dirty": False})
    patcher = mock.patch.object(
        USAGE, "_load_ledger_from_disk",
        return_value={"v": USAGE._LEDGER_VERSION, "tools": {}})
    patcher.start()
    testcase.addCleanup(patcher.stop)


def gemini_message(message_id, input_tokens, timestamp, model="gemini-3.5-flash"):
    return {
        "id": message_id,
        "timestamp": timestamp,
        "type": "gemini",
        "model": model,
        "tokens": {"input": input_tokens, "output": 10, "cached": 5, "thoughts": 2},
    }


class GeminiUsageTests(unittest.TestCase):
    def setUp(self):
        isolate_ledger(self)
        self.old_dir = USAGE.GEMINI_DIR
        self.old_dirs = USAGE.GEMINI_DIRS

    def tearDown(self):
        USAGE.GEMINI_DIR = self.old_dir
        USAGE.GEMINI_DIRS = self.old_dirs

    def test_jsonl_updates_nested_subagents_and_migration_dedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            chats = Path(tmp) / "project" / "chats"
            nested = chats / "parent-session"
            nested.mkdir(parents=True)
            now = datetime.now().astimezone().replace(microsecond=0).isoformat()

            legacy = {
                "sessionId": "main-session",
                "projectHash": "project",
                "lastUpdated": now,
                "messages": [gemini_message("legacy-msg", 500, now)],
            }
            (chats / "session-old.json").write_text(json.dumps(legacy), encoding="utf-8")

            main_records = [
                {"sessionId": "main-session", "projectHash": "project", "lastUpdated": now},
                gemini_message("main-msg", 50, now),
                gemini_message("main-msg", 150, now),
            ]
            (chats / "session-new.jsonl").write_text(
                "\n".join(json.dumps(item) for item in main_records) + "\n", encoding="utf-8")

            sub_records = [
                {"sessionId": "sub-session", "projectHash": "project", "kind": "subagent"},
                gemini_message("sub-msg", 1000, now),
            ]
            (nested / "sub-session.jsonl").write_text(
                "\n".join(json.dumps(item) for item in sub_records) + "\n", encoding="utf-8")

            USAGE.GEMINI_DIR = tmp
            USAGE.GEMINI_DIRS = [tmp]
            cache = {"v": USAGE._SCAN_CACHE_VERSION}
            result = USAGE.scan_gemini(USAGE.range_bounds(), cache)
            with mock.patch.object(
                USAGE, "_load_gemini_usage_file",
                side_effect=AssertionError("unchanged Gemini files were reparsed"),
            ):
                cached = USAGE.scan_gemini(USAGE.range_bounds(), cache)

        usage = result["ranges"]["all"]
        self.assertEqual(usage["in"], 1150)
        self.assertEqual(usage["out"], 20)
        self.assertEqual(usage["cached"], 10)
        self.assertEqual(usage["thoughts"], 4)
        self.assertEqual(usage["sessions"], {"main-session", "sub-session"})
        self.assertEqual(cached["ranges"]["all"]["in"], 1150)
        self.assertEqual(len(cache["gemini"]), 3)
        self.assertTrue(cache["_dirty"])

    def test_rewind_and_checkpoint_follow_gemini_journal_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.jsonl"
            now = datetime.now().astimezone().replace(microsecond=0).isoformat()
            records = [
                {"sessionId": "session", "projectHash": "project"},
                gemini_message("one", 10, now),
                gemini_message("two", 20, now),
                {"$rewindTo": "two"},
                {"$set": {"messages": [gemini_message("three", 30, now)]}},
                gemini_message("three", 40, now),
            ]
            path.write_text("\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8")

            parsed = USAGE._load_gemini_usage_file(str(path))

        self.assertEqual(len(parsed["events"]), 1)
        self.assertEqual(parsed["events"][0]["id"], "three")
        self.assertEqual(parsed["events"][0]["tokens"]["input"], 40)

    def test_antigravity_sqlite_protobuf_parsing_and_scan(self):
        def encode_varint(val):
            res = bytearray()
            while True:
                b = val & 0x7F
                val >>= 7
                if val:
                    res.append(b | 0x80)
                else:
                    res.append(b)
                    break
            return bytes(res)

        def encode_proto_field(field_num, wire_type, val):
            key = (field_num << 3) | wire_type
            if wire_type == 0:
                return encode_varint(key) + encode_varint(val)
            elif wire_type == 2:
                if isinstance(val, str):
                    val = val.encode("utf-8")
                return encode_varint(key) + encode_varint(len(val)) + val
            raise NotImplementedError

        def duration(seconds, nanos):
            return encode_proto_field(1, 0, seconds) + encode_proto_field(2, 0, nanos)

        def make_gen_step(model, inp, out, cached, thoughts, ts_sec, with_response=False):
            # 实测字段 3 是含思考的总输出（= 9 思考 + 10 回复）；新版还带 10
            tok_sub = (encode_proto_field(2, 0, inp) +
                       encode_proto_field(3, 0, out + thoughts) +
                       encode_proto_field(5, 0, cached) +
                       encode_proto_field(9, 0, thoughts))
            if with_response:
                tok_sub += encode_proto_field(10, 0, out)
            time_sub = encode_proto_field(4, 2, encode_proto_field(1, 0, ts_sec))
            sub1 = (encode_proto_field(19, 2, model) +
                    encode_proto_field(4, 2, tok_sub) +
                    encode_proto_field(9, 2, time_sub) +
                    # 首字 2.5 秒、流式 0.5 秒
                    encode_proto_field(11, 2, duration(2, 500_000_000)) +
                    encode_proto_field(12, 2, duration(0, 500_000_000)))
            return encode_proto_field(1, 2, sub1)

        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            conv_dir = Path(tmp) / "antigravity-cli" / "conversations"
            conv_dir.mkdir(parents=True)
            db_path = conv_dir / "session-12345.db"

            now_sec = int(datetime.now().astimezone().timestamp())
            step0 = make_gen_step("gemini-3.7-flash", inp=200, out=50, cached=800, thoughts=20, ts_sec=now_sec)
            step1 = make_gen_step("gemini-3.7-flash", inp=500, out=100, cached=1200, thoughts=40,
                                  ts_sec=now_sec + 10, with_response=True)

            conn = sqlite3.connect(str(db_path))
            conn.execute("CREATE TABLE gen_metadata (idx INTEGER PRIMARY KEY, data BLOB, size INTEGER)")
            conn.execute("INSERT INTO gen_metadata (idx, data, size) VALUES (0, ?, ?)", (step0, len(step0)))
            conn.execute("INSERT INTO gen_metadata (idx, data, size) VALUES (1, ?, ?)", (step1, len(step1)))
            conn.commit()
            conn.close()

            # Test _load_antigravity_db directly
            parsed = USAGE._load_antigravity_db(str(db_path))
            self.assertIsNotNone(parsed)
            self.assertEqual(parsed["sid"], "session-12345")
            self.assertEqual(len(parsed["events"]), 2)
            self.assertEqual(parsed["events"][0]["tokens"]["input"], 1000)  # 200 + 800 cached
            self.assertEqual(parsed["events"][0]["tokens"]["cached"], 800)
            self.assertEqual(parsed["events"][0]["tokens"]["output"], 50, "输出不含思考，思考单独计")
            self.assertEqual(parsed["events"][0]["tokens"]["thoughts"], 20)
            self.assertEqual(parsed["events"][1]["tokens"]["output"], 100)
            self.assertEqual(parsed["events"][0]["timing"], [2.5, 0.5])
            self.assertEqual(parsed["events"][1]["tokens"]["input"], 1700)  # 500 + 1200 cached

            # Test full scan_gemini integration and cache
            USAGE.GEMINI_DIR = str(conv_dir)
            USAGE.GEMINI_DIRS = [str(conv_dir)]
            cache = {"v": USAGE._SCAN_CACHE_VERSION}
            result = USAGE.scan_gemini(USAGE.range_bounds(), cache)
            with mock.patch.object(
                USAGE, "_load_antigravity_db",
                side_effect=AssertionError("unchanged Antigravity DB was reparsed"),
            ):
                cached_res = USAGE.scan_gemini(USAGE.range_bounds(), cache)

            usage = result["ranges"]["all"]
            self.assertEqual(usage["in"], 2700)  # total prompt tokens = 1000 + 1700
            self.assertEqual(usage["cached"], 2000)  # 800 + 1200
            self.assertEqual(usage["out"], 150)  # 50 + 100
            self.assertEqual(usage["thoughts"], 60)  # 20 + 40
            perf = USAGE._perf_summary(usage.get("perf"))
            self.assertEqual(perf["tps"], 150.0, "回复 token / 流式时长：150 / 1 秒")
            self.assertEqual(usage["sessions"], {"session-12345"})
            self.assertEqual(cached_res["ranges"]["all"]["in"], 2700)
            self.assertTrue(cache["_dirty"])


class AntigravityRobustnessTests(unittest.TestCase):
    """Antigravity 的 .db 是二进制 + 逆向字段号,坏数据必须挡在账本之外。"""

    @staticmethod
    def _varint(val):
        out = bytearray()
        while True:
            b = val & 0x7F
            val >>= 7
            if val:
                out.append(b | 0x80)
            else:
                out.append(b)
                break
        return bytes(out)

    @classmethod
    def _field(cls, num, wire, val):
        key = cls._varint((num << 3) | wire)
        if wire == 0:
            return key + cls._varint(val)
        if isinstance(val, str):
            val = val.encode("utf-8")
        return key + cls._varint(len(val)) + val

    @classmethod
    def _step(cls, ts_sec, inp=100, out=10, cached=900, thoughts=5, model="gemini-3-pro"):
        tokens = (cls._field(2, 0, inp) + cls._field(3, 0, out)
                  + cls._field(5, 0, cached) + cls._field(9, 0, thoughts))
        return cls._field(1, 2, cls._field(19, 2, model)
                          + cls._field(4, 2, tokens)
                          + cls._field(9, 2, cls._field(4, 2, cls._field(1, 0, ts_sec))))

    def _write_db(self, blobs, dirname="conv"):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(root, True))
        directory = root / dirname
        directory.mkdir(parents=True)
        path = directory / "conv.db"
        conn = sqlite3.connect(str(path))
        conn.execute("CREATE TABLE gen_metadata (idx INTEGER PRIMARY KEY, data BLOB)")
        for idx, blob in enumerate(blobs):
            conn.execute("INSERT INTO gen_metadata VALUES (?, ?)", (idx, blob))
        conn.commit()
        conn.close()
        return str(path)

    def test_current_antigravity_rows_use_referenced_step_timestamp(self):
        now_sec = int(datetime.now().astimezone().timestamp())
        tokens = (self._field(2, 0, 200) + self._field(3, 0, 50)
                  + self._field(5, 0, 800) + self._field(9, 0, 20))
        generation = self._field(19, 2, "gemini-3.7-flash") + self._field(4, 2, tokens)
        # Current Antigravity rows omit the old embedded timestamp. Field 2 is a
        # packed list of referenced step indexes; the step metadata owns the time.
        row = self._field(2, 2, self._varint(4) + self._varint(5)) \
            + self._field(1, 2, generation)
        step_metadata = self._field(1, 2, self._field(1, 0, now_sec))

        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(root, True))
        path = root / "current.db"
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE gen_metadata (idx INTEGER PRIMARY KEY, data BLOB, size INTEGER)")
        conn.execute("CREATE TABLE steps (idx INTEGER PRIMARY KEY, metadata BLOB)")
        conn.execute("INSERT INTO gen_metadata VALUES (0, ?, ?)", (row, len(row)))
        conn.execute("INSERT INTO steps VALUES (4, ?)", (step_metadata,))
        conn.execute("INSERT INTO steps VALUES (5, ?)", (step_metadata,))
        conn.commit()
        conn.close()

        parsed = USAGE._load_antigravity_db(str(path))

        self.assertIsNotNone(parsed)
        self.assertEqual(len(parsed["events"]), 1)
        event = parsed["events"][0]
        self.assertEqual(event["model"], "gemini-3.7-flash")
        self.assertEqual(event["tokens"]["input"], 1000)
        self.assertEqual(event["tokens"]["cached"], 800)
        self.assertEqual(event["timestamp"], datetime.fromtimestamp(
            now_sec, USAGE.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def test_oversized_varint_is_rejected_instead_of_hanging(self):
        # 不封顶时 val 会长成百万位大整数,O(n²) 能把 30 秒一轮的采集器拖死。
        with self.assertRaises(ValueError):
            USAGE._decode_proto_varint(b"\xff" * 200_000, 0)

    def test_random_bytes_never_become_usage_events(self):
        random.seed(7)
        for _ in range(200):
            blob = bytes(random.getrandbits(8) for _ in range(64))
            self.assertIsNone(USAGE._antigravity_gen_step(blob))

    def test_one_bad_row_does_not_discard_the_whole_database(self):
        path = self._write_db([self._step(1780000000), self._step(10 ** 18)])
        parsed = USAGE._load_antigravity_db(path)
        self.assertIsNotNone(parsed)
        self.assertEqual(len(parsed["events"]), 1)

    def test_question_mark_in_path_cannot_override_read_only_mode(self):
        # f"file:{path}?mode=ro" 会被路径里的 ? 截断,mode 可被改成 rwc。
        path = self._write_db([self._step(1780000000)], dirname="proj?mode=rwc&x=")
        parsed = USAGE._load_antigravity_db(path)
        self.assertIsNotNone(parsed)
        self.assertEqual(len(parsed["events"]), 1)

    def test_db_cache_signature_covers_the_wal_file(self):
        path = self._write_db([self._step(1780000000)])
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("INSERT INTO gen_metadata VALUES (1, ?)", (self._step(1780000100),))
        conn.commit()

        isolate_ledger(self)
        old_dir, old_dirs = USAGE.GEMINI_DIR, USAGE.GEMINI_DIRS
        self.addCleanup(lambda: setattr(USAGE, "GEMINI_DIR", old_dir))
        self.addCleanup(lambda: setattr(USAGE, "GEMINI_DIRS", old_dirs))
        USAGE.GEMINI_DIR = os.path.dirname(path)
        USAGE.GEMINI_DIRS = [os.path.dirname(path)]
        cache = {"v": USAGE._SCAN_CACHE_VERSION}
        USAGE.scan_gemini(USAGE.range_bounds(), cache)
        conn.close()

        signature = cache["gemini"][os.path.realpath(path)]["sig"]
        # 新数据可能整段落在 -wal 里,签名不含它就等于「文件永远没变」→ 用量冻住。
        self.assertIn("-wal", signature)


if __name__ == "__main__":
    unittest.main()
