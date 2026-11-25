"""Claude Code 侧调用：不落成 assistant 消息、只出现在会话结束时 cost-state 行里的用量。

真实来源（Claude Code 2.1.x）：WebSearch / WebFetch 由小模型 claude-haiku-5-5 代办，
主模型自己的上下文压缩等调用也不写消息；会话结束时追加一行
{"type":"cost-state","sessionId":…,"modelUsage":{模型:{inputTokens,…,webSearchRequests,costUSD}}}，
续聊时从上一行恢复后接着累加。
"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from test_codex_limits import USAGE

OPUS = "claude-opus-5-5"
HAIKU = "claude-haiku-5-5"


def compact(record):
    return json.dumps(record, separators=(",", ":"))


def user(uuid, when):
    # 与真实日志一致的键序与紧凑格式，scan 才会把它认作增量续读的切点
    return compact({"parentUuid": None, "isSidechain": False, "type": "user",
                    "message": {"role": "user", "content": "hi"},
                    "uuid": uuid, "timestamp": when.isoformat()})


def assistant(message_id, when, model=OPUS, inp=0, out=0, cr=0, cw=0, searches=0,
              cw5=None, cw1=None, fetches=0):
    usage = {"input_tokens": inp, "output_tokens": out,
             "cache_read_input_tokens": cr, "cache_creation_input_tokens": cw}
    if searches or fetches:
        usage["server_tool_use"] = {"web_search_requests": searches, "web_fetch_requests": fetches}
    if cw5 is not None or cw1 is not None:
        usage["cache_creation"] = {"ephemeral_5m_input_tokens": cw5,
                                   "ephemeral_1h_input_tokens": cw1}
    return compact({"parentUuid": None, "isSidechain": False, "type": "assistant",
                    "timestamp": when.isoformat(), "requestId": "req-" + message_id,
                    "cwd": "/tmp/claude-project",
                    "message": {"id": message_id, "model": model, "usage": usage}})


def cost_state(session_id, models, start_time=0):
    usage = {}
    for model, u in models.items():
        usage[model] = {"inputTokens": u.get("in", 0), "outputTokens": u.get("out", 0),
                        "cacheReadInputTokens": u.get("cr", 0),
                        "cacheCreationInputTokens": u.get("cw", 0),
                        "webSearchRequests": u.get("ws", 0), "costUSD": u.get("cost_usd", 0)}
        if "cw1" in u:
            usage[model]["cacheCreationEphemeral5mInputTokens"] = u.get("cw5", 0)
            usage[model]["cacheCreationEphemeral1hInputTokens"] = u["cw1"]
    return compact({"type": "cost-state", "sessionId": session_id, "totalCostUSD": 0,
                    "totalAPIDuration": 0, "totalAPIDurationWithoutRetries": 0,
                    "totalToolDuration": 0, "totalLinesAdded": 0, "totalLinesRemoved": 0,
                    "totalDuration": 0, "startTime": start_time, "modelUsage": usage,
                    "hasUnknownModelCost": False})


class ClaudeSideUsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old_dir = USAGE.CLAUDE_DIR
        USAGE.CLAUDE_DIR = self.tmp.name
        self.cache = {"v": USAGE._SCAN_CACHE_VERSION}
        self.now = datetime.now().astimezone().replace(microsecond=0)

    def tearDown(self):
        USAGE.CLAUDE_DIR = self.old_dir
        self.tmp.cleanup()

    def write(self, name, lines, append=False):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a" if append else "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        return path

    def scan(self, key="all"):
        return USAGE.scan_claude(USAGE.range_bounds(), self.cache)["ranges"][key]

    def test_haiku_search_counted_from_cost_state(self):
        self.write("project/s1.jsonl", [
            user("00000000-0000-0000-0000-000000000001", self.now),
            assistant("m1", self.now, inp=8, out=350, cr=65890),
            cost_state("s1", {OPUS: {"in": 8, "out": 350, "cr": 65890},
                              HAIKU: {"in": 14092, "out": 680, "ws": 1}}),
        ])
        usage = self.scan()
        haiku = usage["models"][HAIKU]
        self.assertEqual((haiku["in"], haiku["out"]), (14092, 680))
        self.assertEqual(haiku["ws"], 1)
        # Claude Code 的 costUSD：14092×$0.1/M + 680×$0.5/M + 1 次搜索 $0.01
        self.assertAlmostEqual(haiku["cost"], 0.0117492, places=7)
        # 主模型的消息与 cost-state 一致：不额外补
        self.assertEqual(usage["models"][OPUS]["in"], 8)
        self.assertEqual(usage["in"], 8 + 14092)

    def test_main_model_side_calls_fill_the_gap(self):
        self.write("project/s2.jsonl", [
            user("00000000-0000-0000-0000-000000000002", self.now),
            assistant("m1", self.now, inp=100, out=10, cr=1000, cw=50),
            cost_state("s2", {OPUS: {"in": 150, "out": 30, "cr": 5000, "cw": 50}}),
        ])
        opus = self.scan()["models"][OPUS]
        self.assertEqual((opus["in"], opus["out"], opus["cr"], opus["cw"]), (150, 30, 5000, 50))

    def test_message_and_side_web_searches_are_each_charged_once(self):
        self.write("project/search.jsonl", [
            assistant("m1", self.now, model=HAIKU, inp=10, searches=1),
            cost_state("search", {HAIKU: {"in": 10, "ws": 2}}),
        ])
        haiku = self.scan()["models"][HAIKU]
        self.assertEqual(haiku["in"], 10)
        self.assertEqual(haiku["ws"], 2)
        self.assertAlmostEqual(haiku["cost"], 0.020001)

    def test_model_fetch_counter_survives_deduplication_and_log_removal(self):
        trigger = json.loads(assistant("trigger", self.now, inp=10))
        trigger["message"]["content"] = [{"type": "tool_use", "name": "WebFetch", "id": "tool-1"}]
        path = self.write("project/fetch.jsonl", [
            compact(trigger),
            assistant("haiku-1", self.now, model=HAIKU, inp=40),
            assistant("haiku-1", self.now, model=HAIKU, inp=40, fetches=2),
            cost_state("fetch", {OPUS: {"in": 10}, HAIKU: {"in": 50}}),
        ])
        models = self.scan("today")["models"]
        self.assertEqual(models[HAIKU]["in"], 50)
        self.assertEqual(models[HAIKU]["wf"], 2)
        self.assertNotIn("wf", models[OPUS])

        path.unlink()
        self.assertEqual(self.scan("today")["models"][HAIKU]["wf"], 2)

    def test_side_tokens_do_not_use_the_session_total_as_the_long_prompt_size(self):
        self.write("project/haiku.jsonl", [
            assistant("m1", self.now, model=HAIKU, inp=10, searches=1),
            cost_state("haiku", {HAIKU: {"in": 145218, "out": 21175, "ws": 6,
                                         "cost_usd": 0.0851093}}),
        ])
        haiku = self.scan()["models"][HAIKU]
        self.assertEqual((haiku["in"], haiku["out"]), (145218, 21175))
        self.assertAlmostEqual(haiku["cost"], 0.0851093)

    def test_side_cost_keeps_long_prompt_charge_reported_by_claude(self):
        self.write("project/haiku-long.jsonl", [
            assistant("m1", self.now, inp=10),
            cost_state("haiku-long", {HAIKU: {"in": 120000, "cost_usd": 0.06}}),
        ])
        self.assertAlmostEqual(self.scan()["models"][HAIKU]["cost"], 0.06)

    def test_session_still_running_has_no_side_usage(self):
        self.write("project/s3.jsonl", [
            user("00000000-0000-0000-0000-000000000003", self.now),
            assistant("m1", self.now, inp=100, out=10),
        ])
        usage = self.scan()
        self.assertEqual(set(usage["models"]), {OPUS})
        self.assertEqual(usage["in"], 100)

    def test_resumed_session_counts_each_segment_once_on_its_own_day(self):
        earlier = self.now - timedelta(days=1)
        self.write("project/s4.jsonl", [
            user("00000000-0000-0000-0000-000000000004", earlier),
            assistant("m1", earlier, inp=100),
            cost_state("s4", {OPUS: {"in": 100}, HAIKU: {"in": 1000}}),
            user("00000000-0000-0000-0000-000000000005", self.now),
            assistant("m2", self.now, inp=200),
            # 续聊后累计：主模型 300 = 100 + 200，Haiku 1500 = 1000 + 本段 500
            cost_state("s4", {OPUS: {"in": 300}, HAIKU: {"in": 1500}}),
        ])
        self.assertEqual(self.scan()["models"][HAIKU]["in"], 1500)
        self.assertEqual(self.scan("yesterday")["models"][HAIKU]["in"], 1000)
        self.assertEqual(self.scan("today")["models"][HAIKU]["in"], 500)
        self.assertEqual(self.scan()["models"][OPUS]["in"], 300)

    def test_counter_that_restarts_is_a_new_segment(self):
        self.write("project/s5.jsonl", [
            assistant("m1", self.now, inp=10),
            cost_state("s5", {OPUS: {"in": 10}, HAIKU: {"in": 1000}}),
            assistant("m2", self.now, inp=20),
            cost_state("s5", {OPUS: {"in": 20}, HAIKU: {"in": 300}}),
        ])
        usage = self.scan()
        self.assertEqual(usage["models"][HAIKU]["in"], 1300)
        self.assertEqual(usage["models"][OPUS]["in"], 30)

    def test_repeated_cost_state_line_is_not_double_counted(self):
        line = cost_state("s6", {OPUS: {"in": 10}, HAIKU: {"in": 700, "ws": 1}})
        self.write("project/s6.jsonl", [assistant("m1", self.now, inp=10), line, line])
        haiku = self.scan()["models"][HAIKU]
        self.assertEqual((haiku["in"], haiku["ws"]), (700, 1))

    def test_cache_writes_split_by_cost_state_tiers(self):
        self.write("project/s7.jsonl", [
            assistant("m1", self.now),
            cost_state("s7", {HAIKU: {"cw": 400, "cw5": 100, "cw1": 300}}),
        ])
        side = USAGE._claude_side_events(
            str(self.root / "project/s7.jsonl"),
            {"events": [], "costs": [USAGE._claude_cost_state(
                cost_state("s7", {HAIKU: {"cw": 400, "cw5": 100, "cw1": 300}}), 2,
                self.now.timestamp())]})
        self.assertEqual((side[0]["cw5"], side[0]["cw1"]), (100, 300))
        self.assertEqual(self.scan()["models"][HAIKU]["cw"], 400)

    def test_subagent_messages_are_not_counted_again(self):
        self.write("project/s8.jsonl", [
            assistant("m1", self.now, inp=100),
            cost_state("s8", {OPUS: {"in": 130}, HAIKU: {"in": 50}}),
        ])
        self.write("project/s8/subagents/agent-1.jsonl", [
            assistant("sub-1", self.now - timedelta(seconds=5), inp=30),
        ])
        usage = self.scan()
        self.assertEqual(usage["models"][OPUS]["in"], 130)
        self.assertEqual(usage["models"][HAIKU]["in"], 50)

    def test_duplicate_subagent_message_only_subtracted_once(self):
        message = assistant("sub-1", self.now, inp=30)
        self.write("project/mirror.jsonl", [
            message,
            cost_state("mirror", {OPUS: {"in": 50}}),
        ])
        self.write("project/mirror/subagents/agent-1.jsonl", [message])
        self.assertEqual(self.scan()["models"][OPUS]["in"], 50)

    def test_side_cache_write_tiers_exclude_logged_writes(self):
        self.write("project/cache-tiers.jsonl", [
            assistant("m1", self.now, model=HAIKU, cw=300, cw5=0, cw1=300),
            cost_state("cache-tiers", {HAIKU: {"cw": 400, "cw5": 100, "cw1": 300}}),
        ])
        haiku = self.scan()["models"][HAIKU]
        self.assertEqual(haiku["cw"], 400)
        self.assertAlmostEqual(haiku["cost"], (100 * 0.125 + 300 * 0.2) / 1e6)

    def test_incremental_rescan_keeps_earlier_cost_state(self):
        earlier = self.now - timedelta(minutes=10)
        path = self.write("project/s9.jsonl", [
            user("00000000-0000-0000-0000-000000000009", earlier),
            assistant("m1", earlier, inp=100),
            cost_state("s9", {OPUS: {"in": 100}, HAIKU: {"in": 1000}}),
            user("00000000-0000-0000-0000-000000000010", self.now),
            assistant("m2", self.now, inp=200),
        ])
        self.assertEqual(self.scan()["models"][HAIKU]["in"], 1000)
        entry = self.cache["claude"][str(path)]
        self.assertEqual(len(entry["costs"]), 1)
        self.assertGreater(entry["cut"][1], entry["costs"][0]["line"])

        self.write("project/s9.jsonl", [
            cost_state("s9", {OPUS: {"in": 300}, HAIKU: {"in": 1400}}),
        ], append=True)
        usage = self.scan()
        self.assertEqual(usage["models"][HAIKU]["in"], 1400)
        self.assertEqual(usage["models"][OPUS]["in"], 300)
        self.assertEqual(len(self.cache["claude"][str(path)]["costs"]), 2)

    def test_quota_events_include_side_usage(self):
        self.write("project/s10.jsonl", [
            assistant("m1", self.now, inp=10),
            cost_state("s10", {OPUS: {"in": 10}, HAIKU: {"in": 900, "out": 100}}),
        ])
        self.scan()
        totals = sorted(tokens for _, _, tokens, _ in USAGE._quota_claude_events(self.cache))
        self.assertEqual(totals, [10, 1000])

    def test_context_window_suffix_in_cost_state_matches_logged_base_model(self):
        self.write("project/ctx1m.jsonl", [
            user("00000000-0000-0000-0000-000000000011", self.now),
            assistant("m1", self.now, model=OPUS, inp=100, out=50, cr=50_000, cw=1_000),
            cost_state("ctx1m", {
                f"{OPUS}[1m]": {"in": 120, "out": 60, "cr": 52_000, "cw": 1_000},
                HAIKU: {"in": 400, "out": 20, "ws": 1},
            }, start_time=1_790_115_954_465),
        ])
        usage = self.scan()
        self.assertEqual(set(usage["models"]), {OPUS, HAIKU})
        opus = usage["models"][OPUS]
        self.assertEqual((opus["in"], opus["out"], opus["cr"], opus["cw"]), (120, 60, 52_000, 1_000))
        expected_opus_cost = USAGE._claude_event_cost({
            "model": OPUS, "in": 120, "out": 60, "cr": 52_000, "cw": 1_000,
        })
        self.assertAlmostEqual(opus["cost"], expected_opus_cost, places=9)
        self.assertEqual(USAGE._normalize(f"{OPUS}[1m]"), USAGE._normalize(OPUS))
        self.assertEqual(USAGE.price_for(f"{OPUS}[1m]"), USAGE.price_for(OPUS))

    def test_cost_state_merges_base_and_context_suffix_variants(self):
        self.write("project/ctx-mix.jsonl", [
            assistant("m1", self.now, model=OPUS, inp=100, cr=10_000),
            cost_state("ctx-mix", {
                OPUS: {"in": 40, "cr": 4_000},
                f"{OPUS}[1m]": {"in": 80, "cr": 7_000},
            }, start_time=1_790_115_954_466),
        ])
        usage = self.scan()
        self.assertEqual(set(usage["models"]), {OPUS})
        self.assertEqual((usage["models"][OPUS]["in"], usage["models"][OPUS]["cr"]), (120, 11_000))

    def test_resumed_session_in_new_file_uses_prior_cost_state_as_baseline(self):
        earlier = self.now - timedelta(days=1)
        start_time = 1_791_000_000_000
        replayed = assistant("m-old", earlier, model=OPUS, inp=1_000, out=200, cr=100_000, cw=5_000)
        self.write("project/session-a.jsonl", [
            user("00000000-0000-0000-0000-000000000021", earlier),
            replayed,
            # A 累计含之前已压缩的历史用量（远大于现存的 m-old）
            cost_state("session-a", {
                OPUS: {"in": 20_000, "out": 5_000, "cr": 6_000_000_000, "cw": 100_000},
                HAIKU: {"in": 50_000, "out": 1_000, "ws": 2},
            }, start_time=start_time),
        ])
        # B 续接 A：重放 m-old + 新增 m-new，首条 cost-state 继承 A 的累计值并加上本段新增与侧调用
        self.write("project/session-b.jsonl", [
            replayed,
            user("00000000-0000-0000-0000-000000000022", self.now),
            assistant("m-new", self.now, model=OPUS, inp=500, out=100, cr=3_000_000, cw=2_000),
            cost_state("session-b", {
                OPUS: {"in": 20_700, "out": 5_150, "cr": 6_003_500_000, "cw": 102_000},
                HAIKU: {"in": 53_000, "out": 1_200, "ws": 3},
            }, start_time=start_time),
            user("00000000-0000-0000-0000-000000000023", self.now + timedelta(minutes=5)),
            assistant("m-new-2", self.now + timedelta(minutes=5), model=OPUS, inp=100, out=50, cr=1_000_000),
            cost_state("session-b", {
                OPUS: {"in": 20_800, "out": 5_200, "cr": 6_004_500_000, "cw": 102_000},
                HAIKU: {"in": 53_000, "out": 1_200, "ws": 3},
            }, start_time=start_time),
        ])
        today = self.scan("today")
        yesterday = self.scan("yesterday")
        # 昨日只含 A 的 60 亿；今日只含 B 两段的新增（Opus cr = 3.5M + 1M = 4.5M，Haiku = 3000 in / 200 out / 1 ws）
        self.assertEqual(yesterday["models"][OPUS]["cr"], 6_000_000_000)
        self.assertEqual(today["models"][OPUS]["cr"], 4_500_000)
        self.assertEqual(today["models"][OPUS]["in"], 800)
        self.assertEqual(today["models"][OPUS]["out"], 200)
        self.assertEqual(today["models"][HAIKU]["in"], 3_000)
        self.assertEqual(today["models"][HAIKU]["out"], 200)
        self.assertEqual(today["models"][HAIKU]["ws"], 1)

    def test_multi_hop_resumed_chain_and_independent_sessions(self):
        t1 = self.now - timedelta(days=2)
        t2 = self.now - timedelta(days=1)
        t3 = self.now
        chain_start = 1_792_000_000_000
        self.write("project/chain-a.jsonl", [
            assistant("c1", t1, model=OPUS, cr=1_000),
            cost_state("chain-a", {OPUS: {"cr": 10_000}}, start_time=chain_start),
        ])
        self.write("project/chain-b.jsonl", [
            assistant("c1", t1, model=OPUS, cr=1_000),
            assistant("c2", t2, model=OPUS, cr=2_000),
            cost_state("chain-b", {OPUS: {"cr": 12_500}}, start_time=chain_start),
        ])
        self.write("project/chain-c.jsonl", [
            assistant("c1", t1, model=OPUS, cr=1_000),
            assistant("c2", t2, model=OPUS, cr=2_000),
            assistant("c3", t3, model=OPUS, cr=3_000),
            cost_state("chain-c", {OPUS: {"cr": 16_000}}, start_time=chain_start),
        ])
        # 独立新会话（不同 startTime）仍从零算起
        self.write("project/independent.jsonl", [
            assistant("ind-1", t3, model=OPUS, cr=100),
            cost_state("independent", {OPUS: {"cr": 10_500}}, start_time=chain_start + 999),
        ])
        total = self.scan("all")
        today = self.scan("today")
        # 链路总计 16,000 + 独立会话 10,500 = 26,500
        self.assertEqual(total["models"][OPUS]["cr"], 26_500)
        # 今日 = chain-c 增量 3,500 + independent 10,500 = 14,000
        self.assertEqual(today["models"][OPUS]["cr"], 14_000)

    def test_accounting_version_replaces_inflated_v1_ledger_and_clears_phantom_day(self):
        import hashlib
        earlier = self.now - timedelta(days=1)
        phantom_day = (self.now - timedelta(days=2)).date().isoformat()
        today_key = self.now.date().isoformat()
        start_time = 1_793_000_000_000
        self.write("project/old-a.jsonl", [
            assistant("oa1", earlier, model=OPUS, cr=100),
            cost_state("old-a", {OPUS: {"cr": 5_000_000}}, start_time=start_time),
        ])
        self.write("project/resumed-b.jsonl", [
            assistant("oa1", earlier, model=OPUS, cr=100),
            assistant("ob1", self.now, model=OPUS, cr=1_000),
            cost_state("resumed-b", {OPUS: {"cr": 5_001_200}}, start_time=start_time),
        ])
        sid_b = hashlib.sha256(b"resumed-b.jsonl").hexdigest()
        sid_deleted = hashlib.sha256(b"archived-deleted.jsonl").hexdigest()
        ledger = USAGE._load_ledger()
        ledger["tools"]["claude"] = {
            today_key: {
                "in": 0, "out": 0, "cr": 5_001_200, "cw": 0, "cost": 1.0,
                "models": {OPUS: {"in": 0, "out": 0, "cr": 5_001_200, "cw": 0, "cost": 1.0}},
                "_sources": {
                    sid_b: {
                        "in": 0, "out": 0, "cr": 5_001_200, "cw": 0, "cost": 1.0,
                        "models": {OPUS: {"in": 0, "out": 0, "cr": 5_001_200, "cw": 0, "cost": 1.0}},
                        "_accounting_version": 1,
                    },
                },
            },
            phantom_day: {
                "in": 0, "out": 0, "cr": 900_000, "cw": 0, "cost": 0.5,
                "models": {f"{OPUS}[1m]": {"in": 0, "out": 0, "cr": 900_000, "cw": 0, "cost": 0.5}},
                "_sources": {
                    sid_b: {
                        "in": 0, "out": 0, "cr": 800_000, "cw": 0, "cost": 0.4,
                        "models": {f"{OPUS}[1m]": {"in": 0, "out": 0, "cr": 800_000, "cw": 0, "cost": 0.4}},
                        "_accounting_version": 1,
                    },
                    sid_deleted: {
                        "in": 0, "out": 0, "cr": 100_000, "cw": 0, "cost": 0.1,
                        "models": {OPUS: {"in": 0, "out": 0, "cr": 100_000, "cw": 0, "cost": 0.1}},
                        "_accounting_version": 1,
                    },
                },
            },
        }
        # 新口径（v2）重算应覆盖 v1 的虚高数，并清除在盘文件在 phantom_day 上的旧版幻影记录，
        # 同时完整保留已删文件 archived-deleted.jsonl 的 100,000。
        today = self.scan("today")
        all_range = self.scan("all")
        self.assertEqual(today["cr"], 1_200)
        self.assertEqual(ledger["tools"]["claude"][phantom_day]["cr"], 100_000)
        self.assertEqual(all_range["cr"], 5_000_000 + 1_200 + 100_000)
        # 再次合并旧版 v1 大值记录时，仍保持 v2 的修正结果。
        remerged = USAGE.ledger_reconcile("claude", {today_key: {"cr": 5_001_200}}, {
            "resumed-b.jsonl": {today_key: {"cr": 5_001_200, "_accounting_version": 1}},
        })
        self.assertEqual(remerged[today_key]["cr"], 1_200)


if __name__ == "__main__":
    unittest.main()
