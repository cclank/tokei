"""扫描缓存按工具分片存。

以前整份 16 MB 的缓存在活跃使用时每 30 秒重写一次（每小时约 2 GB 写盘），
哪怕只有 Claude 那一小块变了。现在每个工具一个分片、文件名带内容哈希，
没变的分片不重写；清单是唯一的提交点。Claude、Codex 这种十几 MB 的工具缓存
再按会话拆桶，活跃时只重写正在变的那一两个桶。
"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from test_codex_limits import USAGE


class ScanCacheShardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "scan_cache.json"
        self.patch = mock.patch.object(USAGE, "_SCAN_CACHE_FILE", str(self.path))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def save(self, cache):
        cache = dict(cache, _dirty=True)
        cache.setdefault("v", USAGE._SCAN_CACHE_VERSION)
        USAGE._save_scan_cache(cache)

    def shard_dir(self):
        return Path(USAGE._scan_shard_dir())

    def shard_files(self):
        return sorted(p.name for p in self.shard_dir().iterdir()
                      if p.name != USAGE._SCAN_SHARD_MANIFEST)

    def test_an_unchanged_tool_is_not_rewritten(self):
        self.save({"claude": {"a": 1}, "codex": {"big": "x" * 1000}})
        codex = next(self.shard_dir().glob("codex.*.json"))
        before = codex.stat().st_mtime_ns
        time.sleep(0.02)

        self.save({"claude": {"a": 2}, "codex": {"big": "x" * 1000}})

        self.assertTrue(codex.exists(), "Codex 没变，分片原样保留")
        self.assertEqual(codex.stat().st_mtime_ns, before, "没变的分片不能重写")
        stored, dirty = USAGE._read_scan_cache_file()
        self.assertEqual(stored["claude"], {"a": 2})
        self.assertFalse(dirty)

    def test_the_manifest_is_the_only_commit_point(self):
        """分片写好、清单还没换就被杀掉时，读到的仍是上一份完整的缓存。"""
        self.save({"codex": {"cost": 1}, "_pricing_effective": {"m": 1}})
        real_write = os.replace

        def crash_on_manifest(src, dst):
            if dst.endswith(USAGE._SCAN_SHARD_MANIFEST):
                raise OSError("killed")
            return real_write(src, dst)

        with mock.patch.object(USAGE.os, "replace", side_effect=crash_on_manifest):
            self.save({"codex": {"cost": 2}, "_pricing_effective": {"m": 2}})

        stored, _ = USAGE._read_scan_cache_file()
        self.assertEqual(stored["codex"], {"cost": 1})
        self.assertEqual(stored["_pricing_effective"], {"m": 1}, "不能出现一半新一半旧")

    def test_superseded_shards_are_removed_only_after_the_grace_period(self):
        self.save({"claude": {"a": 1}})
        old = next(self.shard_dir().glob("claude.*.json"))
        self.save({"claude": {"a": 2}})
        self.assertTrue(old.exists(), "读的人可能还拿着上一份清单")

        stale = time.time() - USAGE._SCAN_SHARD_GRACE - 10
        os.utime(old, (stale, stale))
        self.save({"claude": {"a": 3}})
        self.assertFalse(old.exists())
        self.assertEqual(len(list(self.shard_dir().glob("claude.*.json"))), 2)

    def test_a_legacy_single_file_is_read_and_then_migrated(self):
        self.path.write_text(json.dumps({"v": USAGE._SCAN_CACHE_VERSION,
                                         "claude": {"legacy": True}}), encoding="utf-8")
        cache = USAGE._load_scan_cache()
        self.assertEqual(cache["claude"], {"legacy": True})
        self.assertTrue(cache["_dirty"], "从单文件读来的要写成分片")

        USAGE._save_scan_cache(cache)
        self.assertFalse(self.path.exists(), "迁完删掉旧单文件")
        self.assertEqual(USAGE._read_scan_cache_file()[0]["claude"], {"legacy": True})

    def test_a_newer_legacy_file_wins_over_an_older_manifest(self):
        """回退到旧版又升回来：旧版写下的单文件更新，以它为准。"""
        self.save({"claude": {"from": "shards"}})
        manifest = self.shard_dir() / USAGE._SCAN_SHARD_MANIFEST
        past = time.time() - 60
        os.utime(manifest, (past, past))
        self.path.write_text(json.dumps({"v": USAGE._SCAN_CACHE_VERSION,
                                         "claude": {"from": "legacy"}}), encoding="utf-8")
        self.assertEqual(USAGE._read_scan_cache_file()[0]["claude"], {"from": "legacy"})

    def test_a_missing_shard_costs_only_that_tool(self):
        self.save({"claude": {"a": 1}, "codex": {"b": 2}})
        next(self.shard_dir().glob("codex.*.json")).unlink()

        cache = USAGE._load_scan_cache()
        self.assertEqual(cache["claude"], {"a": 1})
        self.assertNotIn("codex", cache, "缺的那片下一轮重扫")
        self.assertTrue(cache["_dirty"])

    def big_tool(self, count=200):
        # 故意打乱插入顺序：读回来要和写进去一样，不能变成按桶或按键排序
        return {f"/sessions/{(i * 37) % count:04d}.jsonl": {"sig": i, "events": ["x" * 50]}
                for i in range(count)}

    def test_a_big_tool_is_bucketed_and_only_the_changed_bucket_is_rewritten(self):
        codex = self.big_tool()
        with mock.patch.object(USAGE, "_SCAN_SHARD_BUCKET_BYTES", 1024):
            self.save({"codex": codex, "claude": {"a": 1}})
            buckets = {p.name: p.stat().st_mtime_ns for p in self.shard_dir().glob("codex.b*.json")}
            self.assertGreater(len(buckets), 1, "大的工具缓存拆成多个桶")
            time.sleep(0.02)

            changed = dict(codex)
            changed["/sessions/0005.jsonl"] = {"sig": "new", "events": ["y" * 50]}
            self.save({"codex": changed, "claude": {"a": 1}})

        after = {p.name: p.stat().st_mtime_ns for p in self.shard_dir().glob("codex.b*.json")}
        self.assertEqual(len(set(after) - set(buckets)), 1, "只有那个会话所在的桶写了新文件")
        for name, mtime in buckets.items():
            self.assertEqual(after[name], mtime, "没变的桶不能重写")
        stored, dirty = USAGE._read_scan_cache_file()
        self.assertFalse(dirty)
        self.assertEqual(stored["codex"], changed)
        self.assertEqual(list(stored["codex"]), list(changed), "条目顺序和拆桶前一样")

    def test_a_missing_bucket_costs_only_that_tool(self):
        with mock.patch.object(USAGE, "_SCAN_SHARD_BUCKET_BYTES", 1024):
            self.save({"codex": self.big_tool(), "claude": {"a": 1}})
        next(self.shard_dir().glob("codex.b*.json")).unlink()

        cache = USAGE._load_scan_cache()
        self.assertEqual(cache["claude"], {"a": 1})
        self.assertNotIn("codex", cache, "缺了一个桶就整个工具重扫，不能只剩一部分会话")
        self.assertTrue(cache["_dirty"])

    def test_resetting_the_cache_clears_both_formats(self):
        self.save({"claude": {"a": 1}})
        self.path.write_text("{}", encoding="utf-8")
        USAGE._remove_scan_cache_files()
        self.assertFalse(self.path.exists())
        self.assertFalse(self.shard_dir().exists())


if __name__ == "__main__":
    unittest.main()
