"""Synthetic Chromium fixtures only: no real account IDs, prompts or caches."""
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

try:
    from .test_codex_limits import USAGE
except ImportError:
    from test_codex_limits import USAGE


def vint(number):
    result = bytearray()
    while number > 127:
        result.append((number & 127) | 128)
        number >>= 7
    result.append(number)
    return bytes(result)


def sized(data):
    return vint(len(data)) + data


def v8(value):
    if value is None:
        return b"0"
    if isinstance(value, bool):
        return b"T" if value else b"F"
    if isinstance(value, str):
        return b"S" + sized(value.encode("utf-8"))
    if isinstance(value, int):
        return b"U" + vint(value)
    if isinstance(value, float):
        return b"N" + struct.pack("<d", value)
    if isinstance(value, list):
        return b"A" + vint(len(value)) + b"".join(v8(v) for v in value) + b"$\0" + vint(len(value))
    if isinstance(value, dict):
        return b"o" + b"".join(v8(k) + v8(v) for k, v in value.items()) + b"{" + vint(len(value))
    raise TypeError(type(value))


def blink(value):
    return b"\xff\x15\xfe" + b"\0" * 12 + b"\xff\x0f" + v8(value)


def snappy_literal(data):
    n = len(data) - 1
    if n < 60:
        tag = bytes([n << 2])
    else:
        width = (n.bit_length() + 7) // 8
        tag = bytes([(59 + width) << 2]) + n.to_bytes(width, "little")
    return vint(len(data)) + tag + data


def stored(value, compressed=False):
    payload = blink(value)
    return b"\x01" + (b"\xff\x11\x02" + snappy_literal(payload) if compressed else payload)


def log(records):
    data = bytearray()
    for record in records:
        first = True
        while first or record:
            left = 32768 - len(data) % 32768
            if left < 7:
                data.extend(b"\0" * left)
                left = 32768
            chunk, record = record[:left - 7], record[left - 7:]
            kind = (1 if first else 4) if not record else (2 if first else 3)
            data.extend(struct.pack("<IHB", USAGE._doubao_crc(bytes([kind]) + chunk), len(chunk), kind))
            data.extend(chunk)
            first = False
    return bytes(data)


def batch(rows, sequence=100):
    data = struct.pack("<QI", sequence, len(rows))
    for key, value in rows:
        data += bytes([int(value is not None)]) + sized(key)
        if value is not None:
            data += sized(value)
    return data


def block(entries):
    data, previous = bytearray(), b""
    for key, value in entries:
        shared = 0
        while shared < min(len(previous), len(key)) and previous[shared] == key[shared]:
            shared += 1
        data.extend(vint(shared) + vint(len(key) - shared) + vint(len(value)) + key[shared:] + value)
        previous = key
    return bytes(data) + struct.pack("<II", 0, 1)


def table(rows, compressed=True):
    entries = [(key + struct.pack("<Q", (seq << 8) | int(value is not None)), value or b"")
               for key, seq, value in rows]
    data = block(entries)
    if compressed:
        data = snappy_literal(data)
    compression = bytes([int(compressed)])
    payload = data + compression + struct.pack("<I", USAGE._doubao_crc(data + compression))
    index = block([(entries[-1][0], vint(0) + vint(len(data)))])
    index_offset = len(payload)
    payload += index + b"\0" + struct.pack("<I", USAGE._doubao_crc(index + b"\0"))
    handles = b"\0\0" + vint(index_offset) + vint(len(index))
    return payload + handles.ljust(40, b"\0") + struct.pack("<Q", 0xDB4775248B80FB57)


KEY = b"\x00\x04\x02\x01\x01\x01\x00c"  # db=4, store=2, data index=1
BLOB_KEY = KEY[:3] + b"\x03" + KEY[4:]


def conversation(identity="task-a", created=None, updated=None, agent=True):
    created = created if created is not None else datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    return {
        "conversation_id": identity, "conversation_type": 3 if agent else 1,
        "create_time": str(int(created)), "update_time": str(int(updated if updated is not None else created)),
        "extra": json.dumps({"agent_mode_last_used": "1", "model_item_key": "9"} if agent else {}),
        "name": "private-title-never-persist", "message": "private-prompt-never-persist",
    }


def cached(rows, uid="synthetic-account-a"):
    return {"uid": uid, "schema": "synthetic-cache-schema", "data": {"conversations": rows, "hasMore": False}}


def database(root, rows, tables=(), obsolete=(), tail=b""):
    root.mkdir(parents=True, exist_ok=True)
    edit = b"\x01" + sized(b"idb_cmp1") + b"\x02" + vint(7) + b"\x03" + vint(8) + b"\x04" + vint(100)
    for number, content in tables:
        (root / f"{number:06d}.ldb").write_bytes(content)
        edit += b"\x07" + vint(0) + vint(number) + vint(len(content)) + sized(KEY) + sized(KEY)
    for number, content in obsolete:
        (root / f"{number:06d}.ldb").write_bytes(content)
        edit += b"\x07" + vint(0) + vint(number) + vint(len(content)) + sized(KEY) + sized(KEY)
        edit += b"\x06" + vint(0) + vint(number)
    (root / "CURRENT").write_text("MANIFEST-000001\n")
    (root / "MANIFEST-000001").write_bytes(log([edit]))
    (root / "000007.log").write_bytes(log([batch(rows)]) + tail)


class DoubaoBinaryTests(unittest.TestCase):
    def test_crc_uses_castagnoli_known_vector(self):
        expected = (((0xE3069283 >> 15) | (0xE3069283 << 17)) + 0xA282EAD8) & 0xFFFFFFFF
        self.assertEqual(USAGE._doubao_crc(b"123456789"), expected)

    def test_snappy_overlapping_copy_and_all_copy_widths(self):
        self.assertEqual(USAGE._doubao_snappy(b"\x0c\x08abc\x22\x03\x00"), b"abc" * 4)
        self.assertEqual(USAGE._doubao_snappy(b"\x08\x00a\x0d\x01"), b"a" * 8)
        self.assertEqual(USAGE._doubao_snappy(b"\x05\x00a\x0f\x01\x00\x00\x00"), b"a" * 5)
        for invalid in (b"\x05\x00a", b"\x05\x12\x00\x00", vint(USAGE._DOUBAOWORK_MAX_VALUE + 1)):
            with self.assertRaises(ValueError):
                USAGE._doubao_snappy(invalid)

    def test_wal_fragmentation_checksums_and_incomplete_tail(self):
        payload = b"x" * 70000
        encoded = log([payload, b"end"])
        self.assertEqual(list(USAGE._doubao_log_records(encoded)), [payload, b"end"])
        self.assertEqual(list(USAGE._doubao_log_records(encoded[:-2])), [payload])
        broken = bytearray(encoded); broken[12] ^= 1
        with self.assertRaises(ValueError):
            list(USAGE._doubao_log_records(bytes(broken)))
        with self.assertRaises(ValueError):
            USAGE._doubao_batch_records(batch([(KEY, b"a")]) + b"bad")

    def test_sst_prefix_compression_tombstones_and_checksums(self):
        rows = [(KEY, 9, b"old"), (KEY, 10, None), (KEY + b"next", 11, b"new")]
        for compressed in (True, False):
            data = table(rows, compressed)
            self.assertEqual(list(USAGE._doubao_table_records(data)),
                             [(k, seq, int(v is not None), v or b"") for k, seq, v in rows])
            broken = bytearray(data); broken[8] ^= 1
            with self.assertRaises(ValueError):
                list(USAGE._doubao_table_records(bytes(broken)))

    def test_v8_plain_compressed_unicode_sparse_arrays_and_references(self):
        value = cached([conversation()]); value["中文"] = "豆包😀"
        for compressed in (True, False):
            self.assertEqual(USAGE._doubao_v8_value(stored(value, compressed)), value)
        # Root array gets ID 0; child object ID 1 can be referenced again.
        encoded = b"A\x02oS\x01xU\x01{\x01^\x01$\x00\x02"
        header = b"\0\xff\x15\xfe" + b"\0" * 12 + b"\xff\x0f"
        array = USAGE._doubao_v8_value(header + encoded)
        self.assertIs(array[0], array[1])
        sparse = USAGE._doubao_v8_value(header + b"a\x03U\x01S\x01x@\x01\x03")
        self.assertEqual(sparse, [None, "x", None])
        text = "豆包".encode("utf-16-le")
        self.assertEqual(USAGE._doubao_v8_value(header + b"c" + sized(text)), "豆包")
        with self.assertRaises(ValueError):
            USAGE._doubao_v8_value(header + b"^\x02")
        with self.assertRaises(ValueError):
            USAGE._doubao_v8_value(header + b"B\x01\x00")

    def test_manifest_ignores_obsolete_tables_and_honors_current_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = table([(KEY, 1, stored(cached([conversation("deleted")])) )])
            live = table([(KEY, 2, stored(cached([conversation("current")])) )])
            database(root, [(KEY, None)], tables=[(3, live)], obsolete=[(2, old)])
            files, _ = USAGE._doubao_db_plan(str(root))
            self.assertEqual({Path(f).name for f in files}, {"000003.ldb", "000007.log"})
            self.assertEqual(USAGE._doubao_read_db(str(root), files), [])
            # Even a higher sequence in an unreferenced file must be ignored.
            (root / "000099.ldb").write_bytes(table([(KEY, 999, stored(cached([conversation()])))]))
            self.assertEqual(USAGE._doubao_read_db(str(root), USAGE._doubao_db_plan(str(root))[0]), [])

    def test_external_serialized_blob_requires_live_reference_and_exact_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "chat.indexeddb.leveldb"
            payload = blink(cached([conversation()]))
            number = 0x123
            blob = Path(str(root)[:-8] + ".blob") / "4" / "01" / "123"
            blob.parent.mkdir(parents=True); blob.write_bytes(payload)
            wrapper = b"\x01\xff\x11\x01" + vint(len(payload)) + b"\0"
            reference = b"\0" + vint(number) + b"\0" + vint(len(payload))
            database(root, [(KEY, wrapper), (BLOB_KEY, reference)])
            files, _ = USAGE._doubao_db_plan(str(root))
            self.assertEqual(len(USAGE._doubao_read_db(str(root), files)), 1)
            database(root, [(KEY, wrapper), (BLOB_KEY, None)])
            self.assertEqual(USAGE._doubao_read_db(str(root), USAGE._doubao_db_plan(str(root))[0]), [])

    def test_current_cannot_traverse_out_of_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "CURRENT").write_text("../MANIFEST-000001")
            with self.assertRaises(ValueError):
                USAGE._doubao_db_plan(str(root))


class DoubaoScannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tokei-doubao-unit-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "source"
        self.patchers = [mock.patch.object(USAGE, "DOUBAOWORK_DIRS", [str(self.root)]),
                         mock.patch.object(USAGE, "_LEDGER_FILE", str(Path(self.temp.name) / "ledger.json"))]
        for patcher in self.patchers:
            patcher.start(); self.addCleanup(patcher.stop)
        self.cache = {"v": USAGE._SCAN_CACHE_VERSION}

    def scan(self):
        return USAGE.scan_doubaowork(USAGE.range_bounds(), self.cache)

    def test_only_new_agent_conversations_count_not_chat_messages_or_update_date(self):
        yesterday = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        rows = [conversation(created=yesterday.timestamp(), updated=time.time()), conversation("ordinary", agent=False)]
        database(self.root, [(KEY, stored(cached(rows), compressed=True)),
                             (KEY + b"copy", stored(cached(rows)))])
        result = self.scan()
        self.assertEqual(result["ranges"]["today"]["sessions"], 0)
        self.assertEqual(result["ranges"]["yesterday"]["sessions"], 1)
        self.assertEqual(result["ranges"]["all"]["sessions"], 1)
        self.assertLessEqual(abs(result["updated"] - time.time()), 2)
        self.assertEqual(set(result["ranges"]["all"]), {"sessions", "session_ids"})
        self.assertRegex(result["ranges"]["all"]["session_ids"][0], r"^[a-f0-9]{64}$")
        serialized = json.dumps(self.cache)
        for private in ("private-title-never-persist", "private-prompt-never-persist", "synthetic-account-a", "task-a", "model_item_key"):
            self.assertNotIn(private, serialized)

    def test_distinct_accounts_count_once_each_and_warm_scan_does_not_reparse(self):
        database(self.root, [(KEY, stored(cached([conversation()]))),
                             (KEY + b"other", stored(cached([conversation()], uid="synthetic-account-b")))])
        first = self.scan()
        self.assertEqual(first["ranges"]["today"]["sessions"], 2)
        with mock.patch.object(USAGE, "_doubao_read_db", side_effect=AssertionError("warm parse")):
            self.assertEqual(self.scan(), first)
        self.assertEqual(USAGE._sync_safe_usage_payload({"doubaowork": first})["doubaowork"], first)

    def test_cache_cleanup_and_collector_restart_keep_deduplicated_history(self):
        database(self.root, [(KEY, stored(cached([conversation()])))])
        first = self.scan(); USAGE.ledger_flush()
        self.assertEqual(first["ranges"]["all"]["sessions"], 1)
        shutil.rmtree(self.root)
        USAGE._LEDGER_CACHE["data"] = None
        self.assertEqual(self.scan(), first)
        self.assertFalse(self.cache["doubaowork"])
        # Recreated profile/WAL with the same cloud conversation is still one.
        database(self.root, [(KEY, stored(cached([conversation()])))])
        self.assertEqual(self.scan()["ranges"]["all"]["sessions"], 1)
        ledger_text = Path(USAGE._LEDGER_FILE).read_text()
        self.assertNotIn("synthetic-account", ledger_text)
        self.assertNotIn("private-prompt", ledger_text)
        self.assertEqual(USAGE._ledger_token_sum(json.loads(ledger_text)["tools"]["doubaowork"].popitem()[1], "doubaowork"), 0)

    def test_new_session_same_day_increases_history_and_bad_rotation_keeps_last_good(self):
        database(self.root, [(KEY, stored(cached([conversation()])))])
        self.assertEqual(self.scan()["ranges"]["today"]["sessions"], 1)
        database(self.root, [(KEY, stored(cached([conversation(), conversation("task-b")])))])
        second = self.scan()
        self.assertEqual(second["ranges"]["today"]["sessions"], 2)
        (self.root / "MANIFEST-000001").write_bytes(b"corrupt manifest")
        self.assertEqual(self.scan(), second)

    def test_missing_invalid_and_future_timestamps_are_never_assigned_mtime(self):
        rows = []
        for i, timestamp in enumerate((None, "not-a-date", True, "nan", "1", str(int(time.time()) + 3600))):
            row = conversation(str(i)); row["create_time"] = timestamp; rows.append(row)
        database(self.root, [(KEY, stored(cached(rows)))])
        result = self.scan()
        self.assertEqual(result["ranges"]["all"]["sessions"], 0)
        self.assertNotIn("updated", result)

    def test_profile_discovery_and_duplicate_chat_launcher_caches(self):
        chat = self.root / "Default" / "IndexedDB" / "chrome_doubaowork-chat_0.indexeddb.leveldb"
        launcher = self.root / "Profile 1" / "IndexedDB" / "chrome_doubaowork-launcher_0.indexeddb.leveldb"
        for root in (chat, launcher):
            database(root, [(KEY, stored(cached([conversation()])))])
        self.assertEqual(len(USAGE._doubao_databases()), 2)
        self.assertEqual(self.scan()["ranges"]["today"]["sessions"], 1)

    def test_missing_blob_in_another_store_does_not_hide_valid_conversations(self):
        other = KEY[:2] + b"\x03" + KEY[3:]
        reference_key = other[:3] + b"\x03" + other[4:]
        payload = blink(cached([conversation("task-b")]))
        wrapper = b"\x01\xff\x11\x01" + vint(len(payload)) + b"\0"
        reference = b"\0" + vint(0x123) + b"\0" + vint(len(payload))
        database(self.root, [(KEY, stored(cached([conversation()]))),
                             (other, wrapper), (reference_key, reference)])
        self.assertEqual(self.scan()["ranges"]["all"]["sessions"], 1)
        # The missing file can arrive after its WAL entry, without a DB change.
        blob = Path(str(self.root) + ".blob") / "4" / "01" / "123"
        blob.parent.mkdir(parents=True); blob.write_bytes(payload)
        self.assertEqual(self.scan()["ranges"]["all"]["sessions"], 2)
        with mock.patch.object(USAGE, "_doubao_read_db", side_effect=AssertionError("warm parse")):
            self.assertEqual(self.scan()["ranges"]["all"]["sessions"], 2)

    def test_shipping_json_entry_point_in_isolated_home(self):
        database(self.root, [(KEY, stored(cached([conversation()])))])
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("TOKEI_", "CODEX_", "CLAUDE_", "GROK_"))}
        env.update(HOME=self.temp.name, USERPROFILE=self.temp.name,
                   APPDATA=str(Path(self.temp.name) / "Roaming"),
                   LOCALAPPDATA=str(Path(self.temp.name) / "Local"),
                   TOKEI_AUTO_PRICING="0", TOKEI_DOUBAOWORK_DIR=str(self.root))
        script = Path(__file__).resolve().parents[1] / "usage.30s.py"
        for _ in range(2):
            result = subprocess.run([sys.executable, str(script), "--json", "--local-only", "--no-sync-snapshot"],
                                    env=env, capture_output=True, timeout=30, check=True)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["doubaowork"]["ranges"]["today"]["sessions"], 1)
            self.assertNotIn("doubaowork", payload.get("_errors", {}))
            self.assertEqual(set(payload["doubaowork"]["ranges"]["today"]), {"sessions", "session_ids"})


if __name__ == "__main__":
    unittest.main()
