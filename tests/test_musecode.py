import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from test_codex_limits import USAGE


def _us(amount):
    return int(amount.timestamp() * 1_000_000)


def metadata_record(sid, project, recorded_at):
    return {
        "schema_version": 1,
        "id": "meta-1",
        "stream": {"kind": "session", "id": sid},
        "sequence": 1,
        "recorded_at": recorded_at,
        "record_type": "event",
        "durability": "durable",
        "causation_id": None,
        "payload_type": "runtime.session.metadata",
        "payload_schema_version": 1,
        "payload": {
            "kind": "metadata",
            "record": {"workspace_root": project, "provider_id": "meta"},
        },
    }


def run_model_record(sid, run_id, model_id, recorded_at):
    return {
        "schema_version": 1,
        "id": "run-model-1",
        "stream": {"kind": "session", "id": sid},
        "sequence": 2,
        "recorded_at": recorded_at,
        "record_type": "event",
        "durability": "durable",
        "causation_id": None,
        "payload_type": "run.model.configured",
        "payload_schema_version": 1,
        "payload": {
            "kind": "run_model",
            "record": {
                "command_id": run_id,
                "run_stream": {"kind": "run", "id": run_id},
                "provider_id": "meta",
                "model_id": model_id,
            },
        },
    }


def completed_record(sid, run_id, source_id, model, usage, recorded_at):
    return {
        "schema_version": 1,
        "id": f"evt-{source_id}",
        "stream": {"kind": "session", "id": sid},
        "sequence": 10,
        "recorded_at": recorded_at,
        "record_type": "event",
        "durability": "durable",
        "causation_id": None,
        "payload_type": "runtime.session",
        "payload_schema_version": 1,
        "payload": {
            "kind": "run",
            "run_id": run_id,
            "event": {
                "kind": "model_completed",
                "usage": usage,
                "duration_ms": 1000,
                "finish_reason": "stop",
                "model": model,
            },
        },
        "source_run_record_id": source_id,
        "source_run_record_sequence": 20,
    }


def attribution_record(sid, run_id, recorded_at):
    # goal_usage_attribution 只是归因账本,不能重复计入用量。
    return {
        "schema_version": 1,
        "stream": {"kind": "session", "id": sid},
        "sequence": 11,
        "recorded_at": recorded_at,
        "record_type": "event",
        "durability": "durable",
        "causation_id": None,
        "payload_type": "runtime.session",
        "payload_schema_version": 1,
        "payload": {
            "kind": "run",
            "run_id": run_id,
            "event": {
                "kind": "goal_usage_attribution",
                "record": {
                    "usage_id": "usage-1",
                    "usage_family": "provider",
                    "quantity": {"unit": "tokens", "reported": True,
                                 "input_tokens": 99999, "output_tokens": 99999,
                                 "cached_tokens": 0, "reasoning_tokens": 0},
                },
            },
            "source_run_record_id": "attrib-1",
            "source_run_record_sequence": 21,
        },
    }


class MuseCodeScanTests(unittest.TestCase):
    def create_session(self, root):
        project = "/tmp/muse-project"
        sid = "sess-1"
        session_file = (Path(root) / "sessions" / "2026" / "09" / "07" / sid
                        / "session.jsonl")
        session_file.parent.mkdir(parents=True)
        now = datetime.now().astimezone().replace(minute=0, second=0, microsecond=0)
        recorded_at = _us(now)
        records = [
            metadata_record(sid, project, recorded_at),
            run_model_record(sid, "run-1", "muse-spark-1.2", recorded_at),
            completed_record(sid, "run-1", "rec-1", "muse-spark-1.2", {
                "input_tokens": 30000, "output_tokens": 500,
                "cached_tokens": 27000, "cache_write_tokens": 100,
                "cache_read_tokens": 27000, "reasoning_tokens": 50,
            }, recorded_at),
            # 同一条 source_run_record_id 是重放,必须去重。
            completed_record(sid, "run-1", "rec-1", "muse-spark-1.2", {
                "input_tokens": 11111, "output_tokens": 111,
                "cached_tokens": 0, "cache_write_tokens": 0,
                "cache_read_tokens": 0, "reasoning_tokens": 0,
            }, recorded_at),
            # same-as-main 回退到 run.model.configured 的模型。
            completed_record(sid, "run-1", "rec-2", "same-as-main", {
                "input_tokens": 10000, "output_tokens": 200,
                "cached_tokens": 1000, "cache_write_tokens": 0,
                "cache_read_tokens": 1000, "reasoning_tokens": 10,
            }, recorded_at),
            attribution_record(sid, "run-1", recorded_at),
        ]
        session_file.write_text(
            "\n".join(json.dumps(record) for record in records) + "\n{broken\n",
            encoding="utf-8",
        )
        return session_file, now, project

    def scan(self, root, cache=None):
        old_root = USAGE.MUSE_DIR
        USAGE.MUSE_DIR = str(root)
        scan_cache = cache if cache is not None else {"v": USAGE._SCAN_CACHE_VERSION}
        try:
            result = USAGE.scan_musecode(USAGE.range_bounds(), scan_cache)
        finally:
            USAGE.MUSE_DIR = old_root
        return result, scan_cache

    def expected_cost(self):
        price = USAGE._raw_price("meta/muse-spark-1.2")
        first = (3000 * price["in"] + 500 * price["out"]
                 + 27000 * price["cache_read"] + 100 * price["cache_write"]) / 1e6
        second = (9000 * price["in"] + 200 * price["out"]
                  + 1000 * price["cache_read"]) / 1e6
        return first + second

    def test_completed_events_split_cache_and_dedupe_replays(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_file, now, project = self.create_session(tmp)
            result, cache = self.scan(tmp)

            with mock.patch.object(
                USAGE, "_scan_muse_session",
                side_effect=AssertionError("unchanged session was rescanned"),
            ):
                self.scan(tmp, cache=cache)

        usage = result["ranges"]["all"]
        self.assertEqual(usage["in"], 12000)
        self.assertEqual(usage["out"], 700)
        self.assertEqual(usage["cr"], 28000)
        self.assertEqual(usage["cw"], 100)
        self.assertEqual(usage["reason"], 60)
        self.assertEqual(USAGE._muse_token_total(usage), 40800)
        self.assertEqual(usage["sessions"], {"sess-1"})
        self.assertAlmostEqual(usage["cost"], self.expected_cost(), places=9)
        models = usage["models"]
        self.assertEqual(set(models), {"meta/muse-spark-1.2"})
        self.assertEqual(models["meta/muse-spark-1.2"]["in"], 12000)
        self.assertEqual(models["meta/muse-spark-1.2"]["reason"], 60)
        self.assertEqual(USAGE._muse_token_total(models["meta/muse-spark-1.2"]), 40800)
        entry = cache["musecode"][str(session_file)]
        self.assertEqual(entry["sid"], "sess-1")
        self.assertEqual(entry["proj"], project)
        self.assertEqual(entry["parser_version"], USAGE._MUSE_PARSER_VERSION)
        self.assertEqual(entry["days"][now.date().isoformat()]["hours"][now.hour],
                         40800)

        with mock.patch.object(
            USAGE, "_load_ledger",
            return_value={"v": USAGE._LEDGER_VERSION, "tools": {}},
        ):
            daily = USAGE.build_daily_costs("1d", refresh=False, _cache=cache)
            wrapped = USAGE.build_wrapped("1d", refresh=False, _cache=cache)
        self.assertEqual(daily["daily"][0]["tokens"], 40800)
        muse_model = next(model for model in daily["models"]
                          if model["tool"] == "musecode")
        self.assertEqual(muse_model["tokens"], 40800)
        self.assertEqual(wrapped["total_tokens"], 40800)
        self.assertEqual(wrapped["top_model"]["tokens"], 40800)

    def test_missing_source_clears_stale_cache(self):
        stale = {
            "v": USAGE._SCAN_CACHE_VERSION,
            "musecode": {"/old/session.jsonl": {"sig": "old", "days": {}}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            result, cache = self.scan(tmp, cache=stale)

        self.assertEqual(result["ranges"]["all"]["in"], 0)
        self.assertEqual(cache["musecode"], {})
        self.assertTrue(cache["_dirty"])

    def test_ledger_fallback_preserves_cost_without_double_counting_reasoning(self):
        today = datetime.now().astimezone().date().isoformat()
        day = {
            "in": 12000, "out": 700, "cr": 28000, "cw": 100,
            "reason": 60, "cost": 0.25, "models": {}, "hours": [0] * 24,
        }
        ledger = {
            "v": USAGE._LEDGER_VERSION,
            "tools": {"musecode": {today: day}},
        }
        cache = {"v": USAGE._SCAN_CACHE_VERSION, "musecode": {}}

        with mock.patch.object(USAGE, "_load_ledger", return_value=ledger):
            daily = USAGE.build_daily_costs("1d", refresh=False, _cache=cache)
            wrapped = USAGE.build_wrapped("1d", refresh=False, _cache=cache)

        self.assertEqual(daily["daily"][0]["tokens"], 40800)
        self.assertEqual(daily["daily"][0]["musecode"], 0.25)
        self.assertEqual(daily["daily"][0]["total"], 0.25)
        self.assertEqual(wrapped["total_tokens"], 40800)
        self.assertEqual(wrapped["total_cost"], 0.25)

    def test_millisecond_timestamps_and_flat_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            sid = "sess-flat"
            session_file = Path(tmp) / "sessions" / sid / "session.jsonl"
            session_file.parent.mkdir(parents=True)
            now = datetime.now().astimezone().replace(minute=0, second=0,
                                                      microsecond=0)
            recorded_ms = int(now.timestamp() * 1000)
            session_file.write_text(json.dumps(completed_record(
                sid, "run-9", "rec-9", "muse-spark-1.3", {
                    "input_tokens": 2000, "output_tokens": 100,
                    "cached_tokens": 500, "cache_write_tokens": 0,
                    "cache_read_tokens": 500, "reasoning_tokens": 5,
                }, recorded_ms)) + "\n", encoding="utf-8")
            result, cache = self.scan(tmp)

        usage = result["ranges"]["all"]
        self.assertEqual(usage["in"], 1500)
        self.assertEqual(usage["cr"], 500)
        self.assertEqual(usage["reason"], 5)
        self.assertEqual(usage["sessions"], {"sess-flat"})
        self.assertIn("meta/muse-spark-1.3", usage["models"])
        self.assertIsNone(cache["musecode"][str(session_file)]["proj"])

    def test_normalize_maps_muse_models_to_meta_pricing(self):
        self.assertEqual(USAGE._normalize("muse-spark-1.3-contributor"),
                         "meta/muse-spark-1.3-contributor")
        self.assertEqual(USAGE._normalize("muse-glimmer-30b"),
                         "meta/muse-glimmer-30b")
        self.assertIsNotNone(USAGE._pricing_id("muse-spark-1.3"))

    def test_muse_ui_totals_treat_reasoning_as_output_detail(self):
        root = Path(__file__).resolve().parents[1]
        sources = root / "Tokei" / "Sources" / "Tokei"
        panel = (sources / "PanelView.swift").read_text()
        dashboard = (sources / "DashboardView.swift").read_text()
        summary = (sources / "UsageSummaryBuilder.swift").read_text()
        muse_call = next(line for line in panel.splitlines()
                         if 'toolID: "musecode"' in line)
        self.assertIn("reasonIncludedInOutput: true", muse_call)
        self.assertIn(
            "tokenUsageTotal(usage.musecode.ranges.get(key), "
            "reasonIncludedInOutput: true)", dashboard)
        self.assertIn(
            'range: usage.musecode.ranges.get(range), reasonIncludedInOutput: true',
            summary)


if __name__ == "__main__":
    unittest.main()
