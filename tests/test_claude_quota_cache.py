import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from test_codex_limits import USAGE


MAGIC = b"\x28\xb5\x2f\xfd"


class ClaudeQuotaCacheTests(unittest.TestCase):
    def setUp(self):
        self.now = int(time.time())

    def _iso(self, epoch):
        return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")

    def _payload(self, q5, q7, qf=None):
        payload = {
            "five_hour": {
                "utilization": q5,
                "resets_at": self._iso(self.now + 3600),
            },
            "seven_day": {
                "utilization": q7,
                "resets_at": self._iso(self.now + 7 * 86400),
            },
        }
        if qf is not None:
            payload["limits"] = [{
                "group": "weekly",
                "kind": "weekly_scoped",
                "percent": qf,
                "resets_at": self._iso(self.now + 7 * 86400),
                "scope": {
                    "model": {"display_name": "Fable", "id": None},
                    "surface": None,
                },
            }]
        return payload

    def _write_entry(self, directory, name, marker, modified):
        path = Path(directory) / f"{name}_0"
        path.write_bytes(b"organizations/test/usage\n" + MAGIC + marker.encode("ascii"))
        os.utime(path, ns=(modified * 1_000_000_000, modified * 1_000_000_000))
        return path

    def _decoder(self, payloads):
        def decode(data):
            marker = data[len(MAGIC):].decode("ascii")
            value = payloads.get(marker)
            if value == "corrupt":
                return b"{"
            return json.dumps(value).encode("utf-8") if value is not None else None
        return decode

    def _scan(self, cache_dir, state_file, decoder, now=None):
        with mock.patch.dict(os.environ, {"TOKEI_CLAUDE_CACHE_DIR": str(cache_dir)}), \
             mock.patch.object(USAGE, "CLAUDE_CACHE", str(Path(cache_dir) / "missing")), \
             mock.patch.object(USAGE, "CLAUDE_CACHE_DIRS", []), \
             mock.patch.object(USAGE, "CLAUDE_QUOTA_CACHE", str(state_file)), \
             mock.patch.object(USAGE, "_zstd_decompress", side_effect=decoder):
            return USAGE._scan_claude_plan_raw(now=self.now if now is None else now)

    def test_finds_entry_beyond_200_then_reuses_and_replaces_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cache_dir.mkdir()
            state_file = Path(tmp) / "state.json"
            valid = self._write_entry(cache_dir, "valid", "old", self.now - 500)
            for index in range(250):
                path = cache_dir / f"noise-{index}_0"
                path.write_bytes(b"ordinary chromium cache")
                modified = self.now - 499 + index
                os.utime(path, ns=(modified * 1_000_000_000, modified * 1_000_000_000))

            payloads = {
                "old": self._payload(37.0, 62.0, 81.0),
                "new": self._payload(41.0, 65.0, 83.0),
            }
            first = self._scan(cache_dir, state_file, self._decoder(payloads))

            self.assertEqual(first["q5"], 37.0)
            self.assertEqual(first["qf"], 81.0)
            self.assertFalse(first["q5_stale"])
            self.assertFalse(first["qf_stale"])
            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(state["candidate"]["path"], str(valid.resolve()))

            def should_not_decode(_):
                raise AssertionError("unchanged candidate should use the persisted snapshot")

            reused = self._scan(cache_dir, state_file, should_not_decode, now=self.now + 10)
            self.assertEqual(reused["q7"], 62.0)

            newest = self._write_entry(cache_dir, "newest", "new", self.now + 20)
            replaced = self._scan(cache_dir, state_file, self._decoder(payloads), now=self.now + 20)
            self.assertEqual(replaced["q5"], 41.0)
            self.assertEqual(replaced["qf"], 83.0)
            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(state["candidate"]["path"], str(newest.resolve()))

    def test_deleted_candidate_falls_back_to_remaining_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cache_dir.mkdir()
            state_file = Path(tmp) / "state.json"
            backup = self._write_entry(cache_dir, "backup", "backup", self.now - 120)
            primary = self._write_entry(cache_dir, "primary", "primary", self.now - 60)
            payloads = {
                "backup": self._payload(22.0, 44.0),
                "primary": self._payload(33.0, 55.0),
            }

            first = self._scan(cache_dir, state_file, self._decoder(payloads))
            self.assertEqual(first["q5"], 33.0)
            primary.unlink()

            fallback = self._scan(cache_dir, state_file, self._decoder(payloads), now=self.now + 5)
            self.assertEqual(fallback["q5"], 22.0)
            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(state["candidate"]["path"], str(backup.resolve()))

    def test_corrupt_new_response_keeps_last_valid_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cache_dir.mkdir()
            state_file = Path(tmp) / "state.json"
            valid = self._write_entry(cache_dir, "valid", "valid", self.now - 60)
            payloads = {"valid": self._payload(18.0, 29.0), "bad": "corrupt"}
            self._scan(cache_dir, state_file, self._decoder(payloads))

            self._write_entry(cache_dir, "bad", "bad", self.now + 5)
            result = self._scan(cache_dir, state_file, self._decoder(payloads), now=self.now + 5)

            self.assertEqual(result["q5"], 18.0)
            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(state["candidate"]["path"], str(valid.resolve()))

    def test_freshness_checks_source_age_and_each_reset(self):
        snapshot = {
            "q5": 10.0,
            "q5_reset": self.now + 300,
            "q7": 20.0,
            "q7_reset": self.now - 1,
            "qf": 30.0,
            "qf_reset": self.now + 300,
            "q_updated": self.now - 30,
        }
        fresh = USAGE._claude_quota_with_freshness(snapshot, now=self.now)
        self.assertFalse(fresh["q5_stale"])
        self.assertTrue(fresh["q7_stale"])
        self.assertFalse(fresh["qf_stale"])

        snapshot["q_updated"] = self.now - USAGE._CLAUDE_QUOTA_STALE_TTL - 1
        expired = USAGE._claude_quota_with_freshness(snapshot, now=self.now)
        self.assertTrue(expired["q5_stale"])
        self.assertTrue(expired["q7_stale"])
        self.assertTrue(expired["qf_stale"])

    def test_native_quota_environment_bypasses_python_zstd_dependency(self):
        native = {
            "q5": 36.0,
            "q5_reset": self.now + 3600,
            "q7": 13.0,
            "q7_reset": self.now + 7 * 86400,
            "qf": 26.0,
            "qf_reset": self.now + 7 * 86400,
            "q_updated": self.now - 10,
            "ignored": "not forwarded",
        }
        with mock.patch.dict(
                os.environ,
                {"TOKEI_CLAUDE_QUOTA_JSON": json.dumps(native)},
                clear=False), \
             mock.patch.object(
                 USAGE, "_scan_claude_plan_raw",
                 side_effect=AssertionError("native quota should bypass Python zstd")):
            result = USAGE.scan_claude_plan()

        self.assertEqual(result["q5"], 36.0)
        self.assertEqual(result["q7"], 13.0)
        self.assertEqual(result["qf"], 26.0)
        self.assertFalse(result["q7_stale"])
        self.assertNotIn("ignored", result)

    def test_invalid_native_quota_environment_falls_back_to_python_scan(self):
        fallback = {"q5": 9.0, "q_updated": self.now}
        with mock.patch.dict(
                os.environ, {"TOKEI_CLAUDE_QUOTA_JSON": "not-json"}, clear=False), \
             mock.patch.object(USAGE, "_scan_claude_plan_raw", return_value=fallback) as scan:
            result = USAGE.scan_claude_plan()

        self.assertEqual(result, fallback)
        scan.assert_called_once_with()

    def test_future_timestamp_file_does_not_poison_watermark(self):
        """issue #71:未来时间戳文件不参与水位线,新额度仍能被增量扫描捡到。"""
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cache_dir.mkdir()
            state_file = Path(tmp) / "state.json"
            future = self.now + 11 * 365 * 24 * 3600
            self._write_entry(cache_dir, "decoy", "junk", future)
            self._write_entry(cache_dir, "old", "old", self.now - 500)
            payloads = {"old": self._payload(37.0, 62.0)}
            first = self._scan(cache_dir, state_file, self._decoder(payloads))
            self.assertEqual(first["q5"], 37.0)
            state = json.loads(state_file.read_text(encoding="utf-8"))
            import datetime as _dt
            self.assertEqual(
                _dt.datetime.fromtimestamp(state["scan_mtime_ns"] / 1e9).year,
                _dt.datetime.fromtimestamp(self.now).year)

            self._write_entry(cache_dir, "new", "new", self.now + 600)
            payloads["new"] = self._payload(41.0, 65.0)
            second = self._scan(cache_dir, state_file, self._decoder(payloads),
                                now=self.now + 700)
            self.assertEqual(second["q5"], 41.0)

    def test_future_timestamp_file_is_not_repeatedly_redecoded(self):
        """未来文件签名记入 scan_boundary 后,不再每轮重复解析。"""
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cache_dir.mkdir()
            state_file = Path(tmp) / "state.json"
            self._write_entry(cache_dir, "decoy", "junk", self.now + 11 * 365 * 24 * 3600)
            self._write_entry(cache_dir, "old", "old", self.now - 500)
            payloads = {"old": self._payload(37.0, 62.0)}
            self._scan(cache_dir, state_file, self._decoder(payloads))
            seen = []

            def spy(data):
                seen.append(data[len(MAGIC):].decode("ascii"))
                return self._decoder(payloads)(data)

            self._scan(cache_dir, state_file, spy, now=self.now + 10)
            self.assertNotIn("junk", seen)

    def test_polluted_v2_state_is_discarded_on_upgrade(self):
        """被 2037 污染的 v2 状态在版本升级后自动作废,立即全量重扫恢复。"""
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cache_dir.mkdir()
            state_file = Path(tmp) / "state.json"
            self._write_entry(cache_dir, "old", "old", self.now - 500)
            state_file.write_text(json.dumps({
                "version": 2,
                "scan_mtime_ns": (self.now + 11 * 365 * 24 * 3600) * 1_000_000_000,
                "snapshot": {"q5": 1.0},
            }), encoding="utf-8")
            payloads = {"old": self._payload(37.0, 62.0)}
            result = self._scan(cache_dir, state_file, self._decoder(payloads))
            self.assertEqual(result["q5"], 37.0)
            self.assertEqual(json.loads(state_file.read_text(encoding="utf-8"))["version"], 3)


if __name__ == "__main__":
    unittest.main()
