import unittest
from unittest import mock
from datetime import datetime, timezone

try:
    from .test_codex_limits import USAGE
    from .test_deepseek_harness import harness_event
except ImportError:
    from test_codex_limits import USAGE
    from test_deepseek_harness import harness_event


class DeepSeekTimePricingTests(unittest.TestCase):
    @staticmethod
    def at_utc(day, hour, minute=0):
        return datetime(2026, 8, day, hour, minute, tzinfo=timezone.utc)

    def test_flash_peak_boundaries_are_evaluated_in_beijing_time(self):
        # 01:00 UTC = 09:00 Beijing, and 10:00 UTC = 18:00 Beijing.
        off_peak_before_morning = USAGE._deepseek_official_price(
            "deepseek-v4-flash", at=self.at_utc(19, 0, 59)
        )
        peak_morning = USAGE._deepseek_official_price(
            "deepseek-v4-flash", at=self.at_utc(19, 1)
        )
        off_peak_midday = USAGE._deepseek_official_price(
            "deepseek-v4-flash", at=self.at_utc(19, 4)
        )
        peak_afternoon = USAGE._deepseek_official_price(
            "deepseek-v4-flash", at=self.at_utc(19, 6)
        )
        off_peak_evening = USAGE._deepseek_official_price(
            "deepseek-v4-flash", at=self.at_utc(19, 10)
        )

        self.assertEqual(off_peak_before_morning["in"], 1.5)
        self.assertEqual(peak_morning["in"], 3.0)
        self.assertEqual(off_peak_midday["in"], 1.5)
        self.assertEqual(peak_afternoon["in"], 3.0)
        self.assertEqual(off_peak_evening["in"], 1.5)

    def test_pro_uses_the_same_schedule_with_its_own_prices(self):
        price = USAGE._deepseek_official_price(
            "DeepSeek-V4-Pro-0813",
            at=self.at_utc(19, 1),
        )

        self.assertEqual(price["in"], 9.0)
        self.assertEqual(price["out"], 27.0)
        self.assertEqual(price["cache_read"], 0.30)

    def test_price_change_is_effective_at_midnight_and_keeps_previous_history(self):
        before_cutover = USAGE._deepseek_official_price(
            "deepseek-v4-flash",
            at=self.at_utc(16, 15, 59),
        )
        at_cutover = USAGE._deepseek_official_price(
            "deepseek-v4-flash",
            at=self.at_utc(16, 16),
        )
        peak_after_cutover = USAGE._deepseek_official_price(
            "deepseek-v4-flash",
            at=self.at_utc(17, 1),
        )

        self.assertEqual(before_cutover["in"], 1.0)
        self.assertEqual(before_cutover["out"], 2.0)
        self.assertEqual(before_cutover["cache_read"], 0.02)
        self.assertEqual(at_cutover["in"], 1.5)
        self.assertEqual(at_cutover["out"], 4.5)
        self.assertEqual(at_cutover["cache_read"], 0.05)
        self.assertEqual(peak_after_cutover["in"], 3.0)

    def test_nonofficial_route_uses_static_pricing(self):
        event = harness_event(
            "assistant/message", int(self.at_utc(19, 1).timestamp() * 1000), 1, 1,
            {"inputTokens": 1_000_000, "outputTokens": 1_000_000},
            model="deepseek-v4-flash",
        )
        event["data"]["message"]["source"]["provider"] = "openrouter"
        with mock.patch.dict(USAGE._PRICING_DB, {
            "deepseek/deepseek-v4-flash": {
                "in": 0.1, "out": 0.2, "cache_read": 0.01, "cache_write": 0.0,
            },
        }):
            record = USAGE._deepseek_harness_usage_record(event)
        self.assertAlmostEqual(record["cost"], 0.3)

    def test_harness_event_cost_uses_event_timestamp(self):
        event = harness_event(
            "assistant/message", int(self.at_utc(19, 1).timestamp() * 1000), 1, 1,
            {"inputTokens": 1_000_000, "outputTokens": 1_000_000},
            model="deepseek-v4-flash",
        )
        record = USAGE._deepseek_harness_usage_record(event)
        self.assertEqual(record["cost"], 0)
        self.assertAlmostEqual(record["cost_cny"], 12.0)

        # Untimed events are excluded; they must not silently use today's price.
        event.pop("time")
        self.assertIsNone(USAGE._deepseek_harness_usage_record(event))

    def test_weekend_stays_off_peak(self):
        price = USAGE._deepseek_official_price("deepseek-v4-flash", self.at_utc(22, 1))
        self.assertEqual(price["in"], 1.5)

    def test_september_cutover_preserves_history_and_updates_all_flash_names(self):
        before = datetime(2026, 9, 10, 3, 59, 59, tzinfo=timezone.utc)
        cutover = datetime(2026, 9, 10, 4, tzinfo=timezone.utc)
        self.assertEqual(USAGE._deepseek_official_price("deepseek-v4-flash", before)["in"], 3.0)
        for name in ("deepseek-flash", "deepseek-v4.1-flash", "deepseek-v4-flash",
                     "deepseek-v4-flash-vision-exp", "deepseek-v4-flash-0731",
                     "deepseek/deepseek-v4.1-flash"):
            with self.subTest(model=name):
                price = USAGE._deepseek_official_price(name, cutover)
                self.assertEqual(price, {"in": 1.0, "out": 4.0,
                                         "cache_read": 0.02, "cache_write": 0.0})

    def test_new_flash_peak_weekend_and_request_cost(self):
        for day, hour, expected in ((11, 1, 10.04), (11, 4, 5.02),
                                     (11, 6, 10.04), (11, 10, 5.02), (12, 1, 5.02)):
            with self.subTest(day=day, hour=hour):
                at = datetime(2026, 9, day, hour, tzinfo=timezone.utc)
                event = harness_event("assistant/message", int(at.timestamp() * 1000), 1, 1,
                                      {"inputTokens": 1_000_000, "outputTokens": 1_000_000,
                                       "cacheReadTokens": 1_000_000}, model="deepseek-flash")
                self.assertAlmostEqual(USAGE._deepseek_harness_usage_record(event)["cost_cny"], expected)

    def test_pro_remains_on_its_existing_prices_after_september_fourteenth(self):
        price = USAGE._deepseek_official_price(
            "deepseek-v4-pro", datetime(2026, 9, 14, 6, tzinfo=timezone.utc))
        self.assertEqual(price["in"], 9.0)
        self.assertEqual(price["out"], 27.0)
        self.assertEqual(price["cache_read"], 0.30)

    def test_recalculation_does_not_replace_mixed_time_cost(self):
        model = {
            "name": "deepseek/deepseek-v4-flash",
            "in": 2_000_000,
            "out": 2_000_000,
            "cr": 0,
            "cw": 0,
            "reason": 0,
            "cost": 3.52,
        }
        result = {"deepseek_harness": {"ranges": {"today": {"models": [model], "cost": 3.52}}}}

        USAGE._recalc_costs(result)

        self.assertEqual(model["cost"], 3.52)
        self.assertEqual(result["deepseek_harness"]["ranges"]["today"]["cost"], 3.52)


if __name__ == "__main__":
    unittest.main()
