import json
import os
import tempfile
import time
from datetime import datetime
import unittest
from pathlib import Path
from unittest import mock
from concurrent.futures import ThreadPoolExecutor

from test_codex_limits import USAGE


WEEK = USAGE._QUOTA_WEEK_HOURS * 3600


def _anchor(reset, used, seen=0):
    return {"reset": reset, "first_seen": seen, "last_seen": seen, "max_used": used}


class QuotaCycleStartTests(unittest.TestCase):
    def test_month_starts_at_the_same_local_time_in_the_previous_calendar_month(self):
        cases = [
            (datetime(2026, 11, 20, 10, 15, 30), datetime(2026, 10, 20, 10, 15, 30)),
            (datetime(2026, 1, 20, 10), datetime(2025, 12, 20, 10)),
            (datetime(2026, 3, 31, 10), datetime(2026, 2, 28, 10)),
            (datetime(2024, 3, 31, 10), datetime(2024, 2, 29, 10)),
        ]
        for reset, expected in cases:
            with self.subTest(reset=reset):
                self.assertEqual(USAGE._quota_cycle_start(int(reset.timestamp()), "month"),
                                 int(expected.timestamp()))

    @unittest.skipUnless(hasattr(time, "tzset"), "需要可切换本地时区")
    def test_month_keeps_local_time_across_daylight_saving_change(self):
        try:
            with mock.patch.dict(os.environ, {"TZ": "America/New_York"}):
                time.tzset()
                reset = int(datetime(2026, 3, 20, 10).timestamp())
                expected = int(datetime(2026, 2, 20, 10).timestamp())
                self.assertEqual(USAGE._quota_cycle_start(reset, "month"), expected)
        finally:
            time.tzset()


class QuotaToolReadingTests(unittest.TestCase):
    def test_grok_accepts_week_and_month_but_rejects_unknown_windows(self):
        for window in ("week", "month", "day", "unknown", None):
            with self.subTest(window=window):
                reading = USAGE._quota_tool_reading({"grok": {
                    "pct": 54.0, "reset": 6 * WEEK, "q_updated": 5 * WEEK, "window": window,
                }}, "grok")
                self.assertEqual(reading, (54.0, 6 * WEEK, 5 * WEEK, window)
                                 if window in ("week", "month") else None)

    def test_claude_and_codex_always_use_week(self):
        for tool, fields in (("claude", {"q7": 30, "q7_reset": 6 * WEEK}),
                             ("codex", {"pw": 30, "rw": 6 * WEEK})):
            with self.subTest(tool=tool):
                reading = USAGE._quota_tool_reading({tool: dict(fields, window="month")}, tool)
                self.assertEqual(reading, (30, 6 * WEEK, 0, "week"))


class MergeQuotaAnchorsTests(unittest.TestCase):
    def test_peer_window_is_preserved_and_missing_or_invalid_window_defaults_to_week(self):
        for window in ("month", "week", None, "day", ["month"]):
            with self.subTest(window=window):
                row = _anchor(2000, 8.0)
                if window is not None:
                    row["window"] = window
                anchors = USAGE._merge_quota_anchors({}, {"grok": [row]})
                self.assertEqual(anchors["grok"][0]["window"],
                                 window if window in ("week", "month") else "week")

    def test_different_windows_with_the_same_reset_remain_separate(self):
        anchors = {"grok": [_anchor(2000, 8.0)]}
        USAGE._merge_quota_anchors(anchors, {"grok": [dict(_anchor(2000, 12.0), window="month")]})
        self.assertEqual(len(anchors["grok"]), 2)
        self.assertEqual(anchors["grok"][1]["window"], "month")

    def test_same_window_seen_on_two_machines_collapses_into_one_row(self):
        anchors = {"codex": [_anchor(1000, 30.0, seen=600)]}
        USAGE._merge_quota_anchors(anchors, {"codex": [
            {"reset": 1000 + USAGE._QUOTA_ANCHOR_JITTER - 1, "first_seen": 400,
             "last_seen": 900, "max_used": 71.0},
        ]})
        self.assertEqual(len(anchors["codex"]), 1)
        self.assertEqual(anchors["codex"][0]["max_used"], 71.0)
        self.assertEqual(anchors["codex"][0]["last_seen"], 900)

    def test_window_only_the_peer_saw_is_added(self):
        anchors = {}
        USAGE._merge_quota_anchors(
            anchors, {"grok": [_anchor(2000, 8.0, seen=1500)]})
        self.assertEqual([r["reset"] for r in anchors["grok"]], [2000])

    def test_lower_peer_reading_never_lowers_the_local_peak(self):
        anchors = {"codex": [_anchor(1000, 88.0, seen=900)]}
        USAGE._merge_quota_anchors(
            anchors, {"codex": [{"reset": 1000, "last_seen": 950, "max_used": 12.0}]})
        self.assertEqual(anchors["codex"][0]["max_used"], 88.0)

    def test_junk_in_a_peer_snapshot_is_dropped_without_creating_rows(self):
        anchors = {}
        USAGE._merge_quota_anchors(anchors, {
            "codex": [{"reset": "下周"}, {"reset": 0}, {"no": "reset"}, "nope", None],
            "notatool": [_anchor(1000, 5.0)],
            "grok": "notalist",
        })
        self.assertEqual(anchors, {})

    def test_unreadable_max_used_counts_as_zero_instead_of_raising(self):
        anchors = {}
        USAGE._merge_quota_anchors(
            anchors, {"codex": [{"reset": 1000, "max_used": "满", "last_seen": "刚刚"}]})
        self.assertEqual(anchors["codex"][0]["max_used"], 0.0)
        self.assertEqual(anchors["codex"][0]["last_seen"], 0)

    def test_empty_incoming_is_a_no_op(self):
        anchors = {"codex": [_anchor(1000, 30.0)]}
        USAGE._merge_quota_anchors(anchors, None)
        self.assertEqual(anchors, {"codex": [_anchor(1000, 30.0)]})


class AnchorCyclesTests(unittest.TestCase):
    def test_month_anchor_starts_one_calendar_month_before_reset(self):
        reset = int(datetime(2026, 11, 20, 10).timestamp())
        start = int(datetime(2026, 10, 20, 10).timestamp())
        anchors = {"grok": [dict(_anchor(reset, 40.0), window="month")]}
        self.assertEqual(USAGE._quota_anchor_cycles(anchors, "grok", 8, start + 60),
                         [(start, reset, 40.0, True, "month")])

    def test_month_end_billing_cycles_join_at_observed_resets(self):
        boundaries = [int(value.timestamp()) for value in (
            datetime(2026, 2, 28, 10), datetime(2026, 3, 31, 10),
            datetime(2026, 4, 30, 10), datetime(2026, 5, 31, 10),
        )]
        anchors = {"grok": [dict(_anchor(reset, 40.0), window="month")
                            for reset in boundaries[1:]]}
        cycles = USAGE._quota_anchor_cycles(anchors, "grok", 8, boundaries[-1] - 60)
        chronological = cycles[::-1]
        self.assertEqual([(cycle[0], cycle[1]) for cycle in chronological],
                         list(zip(boundaries, boundaries[1:])))
        for previous, current in zip(chronological, chronological[1:]):
            self.assertEqual(previous[1], current[0])

    def test_only_nearby_monthly_resets_adjust_the_calendar_start(self):
        reset = int(datetime(2026, 5, 20, 10).timestamp())
        calendar_start = int(datetime(2026, 4, 20, 10).timestamp())
        for previous_window in ("month", "week"):
            for offset in (-4, -3, 3, 4):
                with self.subTest(previous_window=previous_window, offset=offset):
                    previous_reset = calendar_start + offset * 86400
                    anchors = {"grok": [dict(_anchor(previous_reset, 40.0), window=previous_window),
                                        dict(_anchor(reset, 20.0), window="month")]}
                    cycles = USAGE._quota_anchor_cycles(anchors, "grok", 8, reset - 60)
                    expected = (previous_reset if previous_window == "month" and abs(offset) <= 3
                                else calendar_start)
                    self.assertEqual(cycles[0][0], expected)

    def test_legacy_anchor_still_uses_seven_days(self):
        anchors = {"grok": [_anchor(6 * WEEK, 40.0)]}
        self.assertEqual(USAGE._quota_anchor_cycles(anchors, "grok", 8, 5 * WEEK),
                         [(5 * WEEK, 6 * WEEK, 40.0, True, "week")])

    def test_mixed_windows_use_the_next_anchors_window_to_clip_the_previous_cycle(self):
        cases = [
            ("week", datetime(2026, 11, 10, 10), "month", datetime(2026, 12, 5, 10)),
            ("month", datetime(2026, 11, 20, 10), "week", datetime(2026, 11, 25, 10)),
        ]
        for window, old, next_window, new in cases:
            with self.subTest(window=window):
                old_reset, new_reset = int(old.timestamp()), int(new.timestamp())
                old_start = USAGE._quota_cycle_start(old_reset, window)
                new_start = USAGE._quota_cycle_start(new_reset, next_window)
                anchors = {"grok": [dict(_anchor(old_reset, 40.0), window=window),
                                    dict(_anchor(new_reset, 20.0), window=next_window)]}
                cycles = USAGE._quota_anchor_cycles(anchors, "grok", 8, new_start + 60)
                self.assertEqual(cycles, [(new_start, new_reset, 20.0, True, next_window),
                                          (old_start, min(old_reset, new_start), 40.0, False, window)])

    def test_idle_monthly_reset_drift_does_not_open_another_cycle(self):
        old = int(datetime(2026, 10, 20, 10).timestamp())
        first_zero = int(datetime(2026, 11, 5, 10).timestamp())
        now = int(datetime(2026, 10, 5, 11).timestamp())
        anchors = {"grok": [dict(_anchor(old, 58.0), window="month")]}
        USAGE._record_quota_anchor(anchors, "grok", first_zero, 0.0, now, window="month")
        USAGE._record_quota_anchor(anchors, "grok", first_zero + 3600, 0.0, now, window="month")
        cycles = USAGE._quota_anchor_cycles(anchors, "grok", 8, now)
        self.assertEqual(len(cycles), 2)
        self.assertEqual(cycles[0][0], USAGE._quota_cycle_start(first_zero, "month"))

    def test_latest_window_still_running_is_marked_current(self):
        anchors = {"codex": [_anchor(5 * WEEK, 40.0), _anchor(6 * WEEK, 20.0)]}
        cycles = USAGE._quota_anchor_cycles(anchors, "codex", 8, 6 * WEEK - 1)
        self.assertEqual(len(cycles), 2)
        self.assertTrue(cycles[0][3])
        self.assertFalse(cycles[1][3])

    def test_latest_window_already_over_is_history_not_current(self):
        # 读数断了就不会再有新锚点,最后一条也会过期 —— 别再摆成「进行中」。
        anchors = {"codex": [_anchor(5 * WEEK, 40.0), _anchor(6 * WEEK, 20.0)]}
        cycles = USAGE._quota_anchor_cycles(anchors, "codex", 8, 6 * WEEK + 1)
        self.assertEqual(len(cycles), 2)
        self.assertFalse(any(c[3] for c in cycles))

    def test_two_future_resets_still_yield_exactly_one_current_cycle(self):
        # 重锚会留下两条 reset 都在未来的锚点。面板只认第一条 current,
        # 多标一条另一条就既不在当前卡片也不在历史里了。
        anchors = {"codex": [_anchor(6 * WEEK, 40.0), _anchor(6 * WEEK + 3600, 20.0)]}
        cycles = USAGE._quota_anchor_cycles(anchors, "codex", 8, 5 * WEEK)
        self.assertEqual(sum(1 for c in cycles if c[3]), 1)
        self.assertTrue(cycles[0][3])
        self.assertEqual(cycles[0][0], 6 * WEEK + 3600 - WEEK)

    def test_zero_percent_early_reset_starts_a_new_cycle_immediately(self):
        old_reset = 6 * WEEK
        new_reset = old_reset + 4 * 24 * 3600
        anchors = {"codex": [_anchor(old_reset, 58.0)]}

        USAGE._record_quota_anchor(
            anchors, "codex", new_reset, 0.0, new_reset - WEEK + 60
        )
        cycles = USAGE._quota_anchor_cycles(
            anchors, "codex", 8, new_reset - WEEK + 60
        )

        self.assertTrue(anchors["codex"][-1]["confirmed_reset"])
        self.assertEqual(len(cycles), 2)
        self.assertTrue(cycles[0][3])
        self.assertEqual(cycles[0][0], new_reset - WEEK)
        self.assertEqual(cycles[0][2], 0.0)
        self.assertEqual(cycles[1][1], new_reset - WEEK)

    def test_idle_zero_percent_drift_does_not_open_another_cycle(self):
        old_reset = 6 * WEEK
        first_zero_reset = old_reset + 4 * 24 * 3600
        drifted_reset = first_zero_reset + 3600
        anchors = {"codex": [_anchor(old_reset, 58.0)]}

        USAGE._record_quota_anchor(
            anchors, "codex", first_zero_reset, 0.0, first_zero_reset - WEEK
        )
        USAGE._record_quota_anchor(
            anchors, "codex", drifted_reset, 0.0, drifted_reset - WEEK
        )
        cycles = USAGE._quota_anchor_cycles(
            anchors, "codex", 8, drifted_reset - WEEK
        )

        self.assertTrue(anchors["codex"][-2]["confirmed_reset"])
        self.assertNotIn("confirmed_reset", anchors["codex"][-1])
        self.assertEqual(len(cycles), 2)
        self.assertEqual(cycles[0][0], first_zero_reset - WEEK)

    def test_confirmed_peer_reset_is_kept_without_local_history(self):
        reset = 6 * WEEK
        anchors = {}
        USAGE._merge_quota_anchors(anchors, {"codex": [{
            "reset": reset,
            "last_seen": reset - WEEK,
            "max_used": 0.0,
            "confirmed_reset": True,
        }]})

        cycles = USAGE._quota_anchor_cycles(
            anchors, "codex", 8, reset - WEEK
        )

        self.assertTrue(anchors["codex"][0]["confirmed_reset"])
        self.assertEqual(len(cycles), 1)
        self.assertTrue(cycles[0][3])

    def test_detail_limit_keeps_older_cycles_for_ui_disclosure(self):
        anchors = {
            "codex": [
                _anchor((index + 2) * WEEK, 10.0 + index)
                for index in range(12)
            ]
        }

        cycles = USAGE._quota_anchor_cycles(
            anchors, "codex", USAGE._QUOTA_CYCLE_HISTORY, 20 * WEEK
        )

        self.assertEqual(len(cycles), 12)
        self.assertGreater(len(cycles), 8)
        self.assertFalse(any(cycle[3] for cycle in cycles))


class CycleSpecsTests(unittest.TestCase):
    def _run(self, payload, peer_anchors, now, existing=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "quota_cycles.json")
            if existing is not None:
                Path(path).write_text(json.dumps({"anchors": existing}), encoding="utf-8")
            with mock.patch.object(USAGE, "_QUOTA_ANCHOR_FILE", path):
                charted, missing, anchors = USAGE._quota_cycle_specs(
                    payload, [(USAGE._QUOTA_SELF_DEVICE, {}, None, {})], peer_anchors, now)
            saved = (json.loads(Path(path).read_text(encoding="utf-8"))["anchors"]
                     if os.path.exists(path) else {})
        return charted, missing, anchors, saved

    def test_stale_reading_keeps_the_stored_history(self):
        # 过期读数被 _quota_tool_reading 挡在门外,但历史周期不该跟着一起消失。
        charted, missing, anchors, _saved = self._run(
            {"codex": {"pw": 100.0, "rw": 6 * WEEK, "pw_stale": True}},
            [], 6 * WEEK, existing={"codex": [_anchor(5 * WEEK, 40.0)]})
        self.assertEqual(charted, ["codex"])
        self.assertNotIn("codex", missing)
        self.assertEqual([r["reset"] for r in anchors["codex"]], [5 * WEEK])

    def test_peer_anchors_fill_in_history_this_machine_never_saw(self):
        charted, missing, anchors, saved = self._run(
            {}, [{"codex": [_anchor(5 * WEEK, 40.0, seen=5 * WEEK)]}], 6 * WEEK)
        self.assertEqual(charted, ["codex"])
        self.assertNotIn("codex", missing)
        self.assertEqual([r["reset"] for r in anchors["codex"]], [5 * WEEK])
        # 别人的观测不回写自己的账,否则一份读数会在两台机器之间来回记。
        self.assertEqual(saved, {})

    def test_reading_seen_on_this_machine_is_persisted(self):
        charted, _missing, _anchors, saved = self._run(
            {"grok": {"pct": 54.0, "reset": 6 * WEEK, "window": "week"}}, [], 5 * WEEK)
        self.assertEqual(charted, ["grok"])
        self.assertEqual([r["reset"] for r in saved["grok"]], [6 * WEEK])

    def test_monthly_reading_is_persisted_with_its_window(self):
        charted, _missing, _anchors, saved = self._run(
            {"grok": {"pct": 54.0, "reset": 6 * WEEK, "window": "month"}}, [], 5 * WEEK)
        self.assertEqual(charted, ["grok"])
        self.assertEqual(saved["grok"][0]["window"], "month")

    def test_tool_with_neither_reading_nor_history_is_reported_missing(self):
        charted, missing, _anchors, _saved = self._run({}, [], 6 * WEEK)
        self.assertEqual(charted, [])
        self.assertEqual(missing, ["claude", "codex", "grok"])


class RefreshQuotaAnchorsTests(unittest.TestCase):
    def test_main_refresh_preserves_monthly_window_without_opening_detail(self):
        reset = int(datetime(2026, 11, 20, 10).timestamp())
        now = int(datetime(2026, 10, 25, 10).timestamp())
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
                USAGE, "_QUOTA_ANCHOR_FILE", os.path.join(tmp, "cycles.json")):
            USAGE._record_local_quota_readings(
                {"grok": {"pct": 25, "reset": reset, "window": "month"}}, now)
            anchors = USAGE._load_quota_anchors()
        self.assertEqual(anchors["grok"][0]["window"], "month")
        cycles = USAGE._quota_anchor_cycles(anchors, "grok", 8, now)
        self.assertEqual(cycles[0][0], int(datetime(2026, 10, 20, 10).timestamp()))
        self.assertEqual(cycles[0][4], "month")

    def test_exhaustion_is_preserved_when_no_detail_page_was_opened(self):
        old_reset = 6 * WEEK
        new_reset = old_reset + 2 * 86400
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
                USAGE, "_QUOTA_ANCHOR_FILE", os.path.join(tmp, "cycles.json")):
            for used, reset, now in ((75, old_reset, 5 * WEEK),
                                     (100, old_reset, new_reset - WEEK - 60),
                                     (0, new_reset, new_reset - WEEK)):
                USAGE._record_local_quota_readings(
                    {"codex": {"pw": used, "rw": reset}}, now)
            anchors = USAGE._load_quota_anchors()
            cycles = USAGE._quota_anchor_cycles(anchors, "codex", 8, new_reset - WEEK)
        self.assertEqual(len(cycles), 2)
        self.assertEqual(cycles[1][2], 100)
        self.assertEqual(cycles[0][2], 0)
        self.assertTrue(cycles[0][3])
        self.assertEqual(cycles[1][1], new_reset - WEEK)

    def test_stale_main_readings_do_not_change_the_peak(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
                USAGE, "_QUOTA_ANCHOR_FILE", os.path.join(tmp, "cycles.json")):
            USAGE._record_local_quota_readings({"codex": {"pw": 75, "rw": 6 * WEEK}}, 5 * WEEK)
            USAGE._record_local_quota_readings(
                {"codex": {"pw": 100, "rw": 6 * WEEK, "pw_stale": True}}, 5 * WEEK + 60)
            self.assertEqual(USAGE._load_quota_anchors()["codex"][0]["max_used"], 75)

    def test_concurrent_refreshes_cannot_replace_a_higher_peak(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
                USAGE, "_QUOTA_ANCHOR_FILE", os.path.join(tmp, "cycles.json")):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(USAGE._record_local_quota_readings,
                                      {"codex": {"pw": used, "rw": 6 * WEEK}}, 5 * WEEK)
                           for used in (100, 75)]
                for future in futures:
                    future.result()
            self.assertEqual(USAGE._load_quota_anchors()["codex"][0]["max_used"], 100)


class HistoryQuotaPeakTests(unittest.TestCase):
    def test_existing_minute_history_repairs_the_completed_cycle_and_survives_pruning(self):
        old_reset, new_reset = 6 * WEEK, 6 * WEEK + 2 * 86400
        boundary = new_reset - WEEK
        anchors = {"codex": [_anchor(old_reset, 75), _anchor(new_reset, 23)]}
        points = [
            {"timestamp": boundary - 3600, "codexWeekRemaining": 0},
            {"timestamp": boundary + 60, "codexWeekRemaining": 100},
            {"timestamp": boundary + 3600, "codexWeekRemaining": 77},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            anchor_path, history_path = Path(tmp, "cycles.json"), Path(tmp, "history.json")
            anchor_path.write_text(json.dumps({"anchors": anchors}))
            history_path.write_text(json.dumps({"version": 1, "points": points}))
            with mock.patch.object(USAGE, "_QUOTA_ANCHOR_FILE", str(anchor_path)), \
                 mock.patch.object(USAGE, "_QUOTA_HISTORY_FILE", str(history_path)):
                _charted, _missing, repaired = USAGE._quota_cycle_specs(
                    {}, [(USAGE._QUOTA_SELF_DEVICE, {}, None, {})], [], boundary + 7200)
                cycles = USAGE._quota_anchor_cycles(repaired, "codex", 8, boundary + 7200)
                self.assertEqual(cycles[1][2], 100)
                self.assertEqual(cycles[0][2], 23)
                self.assertEqual(cycles[1][1], boundary)
                history_path.write_text(json.dumps({"version": 1, "points": []}))
                saved = USAGE._load_quota_anchors()
                self.assertEqual(saved["codex"][0]["max_used"], 100)
                self.assertEqual(USAGE._quota_anchor_cycles(saved, "codex", 8, boundary + 7200)[1][2], 100)

    def test_partial_observations_never_invent_exhaustion(self):
        anchors = {"codex": [_anchor(6 * WEEK, 70)]}
        with mock.patch.object(USAGE, "_load_quota_history_points", return_value=[
            {"timestamp": 5 * WEEK + 60, "codexWeekRemaining": 25},
        ]):
            self.assertTrue(USAGE._reconcile_quota_anchor_peaks(anchors, anchors, 5 * WEEK + 120))
        self.assertEqual(anchors["codex"][0]["max_used"], 75)

    def test_peer_boundary_prevents_attributing_the_next_cycles_exhaustion_to_local_history(self):
        old, peer_reset, current = 6 * WEEK, 6 * WEEK + 86400, 7 * WEEK
        local = {"codex": [_anchor(old, 75), _anchor(current, 23)]}
        boundaries = {"codex": local["codex"] + [_anchor(peer_reset, 80)]}
        with mock.patch.object(USAGE, "_load_quota_history_points", return_value=[
            {"timestamp": peer_reset - WEEK + 3600, "codexWeekRemaining": 0},
        ]):
            self.assertFalse(USAGE._reconcile_quota_anchor_peaks(local, boundaries, current - WEEK + 7200))
        self.assertEqual([r["max_used"] for r in local["codex"]], [75, 23])

    def test_invalid_missing_and_future_readings_do_not_fabricate_a_peak(self):
        anchors = {"codex": [_anchor(6 * WEEK, 75)]}
        with mock.patch.object(USAGE, "_load_quota_history_points", return_value=[
            None, {}, {"timestamp": 5 * WEEK + 60},
            {"timestamp": 5 * WEEK + 60, "codexWeekRemaining": False},
            {"timestamp": 5 * WEEK + 60, "codexWeekRemaining": -1},
            {"timestamp": 5 * WEEK + 60, "codexWeekRemaining": float("nan")},
            {"timestamp": 6 * WEEK + 60, "codexWeekRemaining": 0},
        ]):
            self.assertFalse(USAGE._reconcile_quota_anchor_peaks(anchors, anchors, 5 * WEEK + 120))
        self.assertEqual(anchors["codex"][0]["max_used"], 75)


class DeviceLedgerAnchorTests(unittest.TestCase):
    def test_peer_anchors_are_collected_even_when_the_snapshot_has_no_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "air.json").write_text(json.dumps({
                "_device": "air",
                "_quota_anchors": {"codex": [_anchor(5 * WEEK, 40.0)]},
            }), encoding="utf-8")
            Path(tmp, "self.json").write_text(json.dumps({
                "_device": "self",
                "_quota_anchors": {"codex": [_anchor(9 * WEEK, 40.0)]},
            }), encoding="utf-8")
            with mock.patch.object(USAGE, "_load_tokei_config",
                                   return_value={"sync_dir": tmp, "device_id": "self"}), \
                 mock.patch.object(USAGE, "_load_ledger", return_value={}):
                devices, peer_anchors = USAGE._quota_device_ledgers()
        # 没有 _ledger 的 peer 不参与 token 合并,但它的周期观测照收。
        self.assertEqual([name for name, _t, _s, _d in devices], [USAGE._QUOTA_SELF_DEVICE])
        # 自己那份快照是本地锚点的副本,再并一遍就是自己跟自己对账。
        self.assertEqual(len(peer_anchors), 1)
        self.assertEqual([r["reset"] for r in peer_anchors[0]["codex"]], [5 * WEEK])


class QuotaDetailWindowTests(unittest.TestCase):
    def test_detail_outputs_each_cycles_window_with_tokens_and_cost(self):
        reset = int(datetime(2026, 11, 20, 10).timestamp())
        anchors = {"grok": [dict(_anchor(reset, 40.0), window="month")],
                   "codex": [_anchor(reset, 20.0)]}
        tools = {"grok": {"2026-10-21": {"in": 400, "cost": 8.0}}}
        devices = [("peer", tools, {}, USAGE._quota_daily_from_tools(tools))]
        with mock.patch.object(USAGE, "_quota_detail_inputs", return_value=({}, {})), \
             mock.patch.object(USAGE, "_quota_device_ledgers", return_value=(devices, [])), \
             mock.patch.object(USAGE, "_quota_cycle_specs", return_value=(["grok", "codex"], [], anchors)):
            result = USAGE.build_quota_detail()
        cycles = {cycle["tool"]: cycle for cycle in result["cycles"]}
        self.assertEqual(cycles["grok"]["window"], "month")
        self.assertEqual(cycles["grok"]["start"], int(datetime(2026, 10, 20, 10).timestamp()))
        self.assertEqual(cycles["grok"]["tokens"], 400)
        self.assertEqual(cycles["grok"]["cost"], 8.0)
        self.assertEqual(cycles["codex"]["window"], "week")


class QuotaWindowCostTests(unittest.TestCase):
    def _devices(self, tools):
        return [("peer", tools, {}, USAGE._quota_daily_from_tools(tools))]

    def test_interior_days_take_full_cost_and_edges_split_by_token_share(self):
        hours = [0] * 24
        hours[18] = 300
        hours[6] = 100
        tools = {"claude": {
            "2026-03-02": {"in": 400, "cost": 8.0, "hours": hours},
            "2026-03-03": {"in": 1000, "cost": 5.0},
            "2026-03-04": {"in": 50, "cost": 99.0},
        }}
        start = USAGE._quota_local_day_range("2026-03-02")[0] + 12 * 3600
        end = USAGE._quota_local_day_range("2026-03-04")[0]
        tokens, _per_device, approx, cost = USAGE._quota_window_tokens(
            self._devices(tools), "claude", "c", start, end, None)
        self.assertEqual(tokens, 1300)
        self.assertFalse(approx)
        # 3 月 2 日下午占当天 3/4 的 token,成本也只摊 3/4;3 月 4 日不在窗口里。
        self.assertAlmostEqual(cost, 5.0 + 8.0 * 0.75)

    def test_day_without_tokens_contributes_no_cost(self):
        tools = {"claude": {"2026-03-02": {"cost": 3.0}}}
        start = USAGE._quota_local_day_range("2026-03-02")[0] + 6 * 3600
        end = start + 6 * 3600
        *_rest, cost = USAGE._quota_window_tokens(
            self._devices(tools), "claude", "c", start, end, None)
        self.assertEqual(cost, 0.0)


    def _own_case(self, rows, *, day_cost=11.0, day_tokens=400):
        day = "2026-03-02"
        day_start, day_end = USAGE._quota_local_day_range(day)
        cached = [{"mid": str(i), "timestamp": USAGE.datetime.fromtimestamp(day_start + hour * 3600).astimezone().isoformat(),
                   "in": tokens, **({"cost": cost} if cost is not None else {})}
                  for i, (hour, tokens, cost) in enumerate(rows)]
        events = USAGE._quota_claude_events({"claude": {"fixture": {"events": cached}}})
        hours = [0] * 24
        for hour, tokens, _cost in rows:
            hours[hour] += tokens
        tools = {"claude": {day: {"in": day_tokens, "cost": day_cost, "hours": hours}}}
        devices = [(USAGE._QUOTA_SELF_DEVICE, tools, None, USAGE._quota_daily_from_tools(tools))]
        return devices, events, day_start, day_end

    def test_full_zero_token_day_does_not_add_cost(self):
        tools = {"claude": {"2026-03-02": {"cost": 3.0}}}
        start, end = USAGE._quota_local_day_range("2026-03-02")
        *_, cost = USAGE._quota_window_tokens(self._devices(tools), "claude", "c", start, end, None)
        self.assertEqual(cost, 0.0)

    def test_invalid_day_costs_cannot_poison_cycle_json(self):
        for raw in (float("nan"), float("inf"), "NaN", "-Infinity", -3, True, 10 ** 400):
            with self.subTest(kind=type(raw).__name__):
                tools = {"claude": {"2026-03-02": {"in": 10, "cost": raw}}}
                self.assertIsNone(USAGE._quota_day_cost(tools, "claude", "2026-03-02"))
                start, end = USAGE._quota_local_day_range("2026-03-02")
                *_, cost = USAGE._quota_window_tokens(self._devices(tools), "claude", "c", start, end, None)
                self.assertIsNone(json.loads(json.dumps({"cost": cost}, allow_nan=False))["cost"])

    def test_missing_positive_usage_cost_is_unknown_not_free(self):
        start, end = USAGE._quota_local_day_range("2026-03-02")
        for tokens, expected in ((10, None), (0, 0.0)):
            with self.subTest(tokens=tokens):
                tools = {"claude": {"2026-03-02": {"in": tokens}}}
                *_, cost = USAGE._quota_window_tokens(self._devices(tools), "claude", "c", start, end, None)
                self.assertEqual(cost, expected)

    def test_complete_local_events_use_request_costs_for_mixed_day(self):
        devices, events, start, end = self._own_case([(6, 300, 9.0), (18, 100, 2.0)])
        tokens, _, _, cost = USAGE._quota_window_tokens(devices, "claude", "c", start + 12 * 3600, end, events)
        self.assertEqual(tokens, 100)
        self.assertEqual(cost, 2.0)

    def test_partial_or_legacy_cost_events_keep_ledger_allocation(self):
        for rows in ([(18, 100, 2.0)], [(6, 300, None), (18, 100, None)],
                     [(6, 300, 90.0), (18, 100, 20.0)]):
            with self.subTest(rows=rows):
                devices, events, start, end = self._own_case(rows)
                *_, cost = USAGE._quota_window_tokens(devices, "claude", "c", start + 12 * 3600, end, events)
                self.assertEqual(cost, 2.75)

    def test_complete_events_keep_empty_subhour_window_empty(self):
        devices, events, start, _end = self._own_case([(12, 400, 11.0)])
        tokens, _, _, cost = USAGE._quota_window_tokens(devices, "claude", "c", start + 12 * 3600 + 1800, start + 13 * 3600, events)
        self.assertEqual((tokens, cost), (0, 0.0))

    def test_codex_event_cost_uses_main_bucket_and_cached_price(self):
        day = "2026-03-02"
        start, end = USAGE._quota_local_day_range(day)
        ts = USAGE.datetime.fromtimestamp(start + 18 * 3600).astimezone().isoformat()
        rows = [[ts, day, 0, 0, 0, 0, 100, 0, 0, 0, 2.0, "openai/gpt-5.5"],
                [ts, day, 0, 0, 0, 0, 300, 0, 0, 0, 9.0, USAGE._CODEX_RESERVE_MODEL]]
        cache = {"codex": {"fixture": {"canonical": True, "event_count": 2}}}
        with mock.patch.object(USAGE, "_iter_codex_cached_events", return_value=rows):
            events = USAGE._quota_codex_events([(start, end)], cache)
        self.assertEqual([event[2] for event in events], [100])
        self.assertEqual(events[0][3], 2.0)


class SyncSnapshotAnchorTests(unittest.TestCase):
    def _snapshot(self, anchors):
        written = {}
        with mock.patch.object(USAGE, "compute", return_value={}), \
             mock.patch.object(USAGE, "_load_json", return_value={}), \
             mock.patch.object(USAGE, "_load_ledger", return_value={}), \
             mock.patch.object(USAGE, "_load_quota_anchors", return_value=anchors), \
             mock.patch.object(USAGE, "_write_configured_sync_snapshot",
                               side_effect=lambda d: written.update(d) or True):
            self.assertEqual(USAGE.write_sync_snapshot(), 0)
        return written

    def test_local_anchors_ride_along_with_the_snapshot(self):
        anchors = {"codex": [_anchor(5 * WEEK, 40.0)]}
        self.assertEqual(self._snapshot(anchors)["_quota_anchors"], anchors)

    def test_key_is_omitted_when_there_is_nothing_to_share(self):
        self.assertNotIn("_quota_anchors", self._snapshot({}))


if __name__ == "__main__":
    unittest.main()
