"""Automatic public-price verification must stay offline-safe and nonblocking."""
import contextlib
import io
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

try:
    from .test_codex_limits import USAGE as U
except ImportError:
    from test_codex_limits import USAGE as U

PAGE = (Path(__file__).parent / "fixtures/openai_standard_pricing.md").read_text()


class AutoPricingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / "pricing_update_state.json"
        self.official = self.root / "pricing_official.json"
        for key, value in {
            "_USER_DIR": str(self.root), "PRICING_UPDATE_STATE": str(self.state),
            "OFFICIAL_PRICING_FILE": str(self.official), "PRICING_FILE": str(self.root / "pricing.json"),
            "_OFFICIAL_PRICING_DB": {},
        }.items():
            patch = mock.patch.object(U, key, value)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.dict(os.environ, {"TOKEI_AUTO_PRICING": "1"})
        patch.start()
        self.addCleanup(patch.stop)
        self.quiet = contextlib.ExitStack()
        self.quiet.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.quiet.enter_context(contextlib.redirect_stderr(io.StringIO()))
        self.addCleanup(self.quiet.close)

    def fresh_state(self):
        return {"last_attempt": time.time() - 600, "catalog_checked_at": time.time(),
                "openai_checked_at": time.time(), "checked_models": [], "errors": []}

    @staticmethod
    def snapshot(model="gpt-9.1-terra"):
        return {"codex": {"ranges": {"today": {"models": [{"model_id": model, "name": model}]}}}}

    def test_standard_only_including_a_model_the_app_did_not_know(self):
        prices = U._parse_openai_prices(PAGE)
        self.assertEqual(len(prices), 4)
        p = prices["openai/gpt-9.1-terra"]
        self.assertEqual((p["in"], p["out"], p["cache_read"], p["cache_write"]), (1, 5, .05, 1.25))
        self.assertEqual(p["long_context"], {"threshold": 272000, "in": 2, "out": 7.5, "cache_read": .1})
        self.assertEqual(prices["openai/gpt-5.4-mini"]["out"], 4.5)

    def test_changed_or_truncated_page_does_not_create_zero_prices(self):
        for page in ("", "<html>unavailable</html>", PAGE.replace("Standard pricing data", "renamed"),
                     PAGE.replace("Prices per 1M tokens.", "Prices per 1K tokens."),
                     PAGE.replace("Short context: ≤272K input tokens.", "")):
            with self.subTest(page=page[:50]), self.assertRaises(ValueError):
                U._parse_openai_prices(page)
        malformed = PAGE.replace("$0.05 | $1.25", "TBD | $1.25", 1)
        self.assertNotIn("openai/gpt-9.1-terra", U._parse_openai_prices(malformed))

    def test_verified_prices_replace_copied_defaults_but_keep_manual_values(self):
        model = "openai/gpt-6.1-terra"
        official = {model: {"in": 2.0, "out": 7.0, "cache_read": .1, "cache_write": 2.5}}
        installed = {"models": {model: dict(U._BUILTIN_OVERRIDE_MODELS[model])}}
        merged, _ = U._merge_pricing_overrides(installed, official=official)
        self.assertEqual(merged[model]["out"], 7)
        installed["models"][model]["in"] = 9.0
        merged, _ = U._merge_pricing_overrides(installed, official=official)
        self.assertEqual(merged[model]["in"], 9)

    def test_official_context_threshold_and_prices_are_used_directly(self):
        model = "openai/gpt-9.1-terra"
        price = {"in": 1, "out": 5, "cache_read": .05, "cache_write": 1.25,
                 "long_context": {"threshold": 400000, "in": 4, "out": 11, "cache_read": .2}}
        with mock.patch.object(U, "_OFFICIAL_PRICING_DB", {model: price}), \
             mock.patch.object(U, "_OV_MODELS", {model: price}), \
             mock.patch.object(U, "_OVERRIDES", {}):
            self.assertAlmostEqual(U._codex_estimated_cost(model, 300000, 0, 10000), .35)
            self.assertAlmostEqual(U._codex_estimated_cost(model, 500000, 400000, 10000), .59)

    def test_source_and_time_are_saved_and_old_models_are_retained(self):
        old = {"in": 1, "out": 2, "cache_read": .1, "source": U._OPENAI_PRICING_URL, "verified_at": 1}
        self.official.write_text(json.dumps({"models": {"openai/gpt-4-old": old}}))
        with mock.patch.object(U, "_fetch_openai_prices", return_value=U._parse_openai_prices(PAGE)), \
             mock.patch.object(U, "_record_pricing_changes") as changed:
            U._update_openai_prices()
        data = json.loads(self.official.read_text())
        self.assertEqual(data["models"]["openai/gpt-4-old"], old)
        price = data["models"]["openai/gpt-9.1-terra"]
        self.assertEqual(price["source"], U._OPENAI_PRICING_URL)
        self.assertGreater(price["verified_at"], time.time() - 10)
        self.assertIn("openai/gpt-9.1-terra", changed.call_args.args[0])

    def test_failed_parse_preserves_the_last_valid_file(self):
        self.official.write_text('{"kept": true}')
        with mock.patch.object(U, "_fetch_openai_prices", side_effect=ValueError("changed page")):
            with self.assertRaises(ValueError):
                U._update_openai_prices()
        self.assertEqual(self.official.read_text(), '{"kept": true}')

    def test_daily_verification_does_not_invalidate_costs_when_only_time_changes(self):
        price = {"in": 1, "out": 5, "cache_read": .05, "cache_write": 1.25}
        one = {"openai/gpt-9.1-terra": dict(price, verified_at=1)}
        two = {"openai/gpt-9.1-terra": dict(price, verified_at=2)}
        a, _ = U._merge_pricing_overrides({}, official=one)
        b, _ = U._merge_pricing_overrides({}, official=two)
        self.assertEqual(U._effective_pricing_map(overrides=a, official=one),
                         U._effective_pricing_map(overrides=b, official=two))

    def test_each_source_can_succeed_while_the_other_is_offline(self):
        with mock.patch.object(U, "_update_catalog_prices", return_value=1), \
             mock.patch.object(U, "_update_openai_prices", return_value=None):
            self.assertEqual(U.update_prices(), 0)
        state = json.loads(self.state.read_text())
        self.assertEqual(state["errors"], ["catalog"])
        self.assertIn("openai_checked_at", state)
        self.assertFalse(U._pricing_refresh_due(state, now=time.time() + 600))
        self.assertTrue(U._pricing_refresh_due(state, now=time.time() + 3601))

    def test_recent_prices_are_reused_and_new_unknown_model_checks_early(self):
        with mock.patch.object(U, "_OFFICIAL_PRICING_DB", {"known": {}}):
            state = self.fresh_state()
            self.assertFalse(U._pricing_refresh_due(state))
            self.assertTrue(U._pricing_refresh_due(state, ["new-model-hash"]))
            state["checked_models"] = ["new-model-hash"]
            self.assertFalse(U._pricing_refresh_due(state, ["new-model-hash"]))
            self.assertTrue(U._pricing_refresh_due(state, now=time.time() + 86401))

    def test_clock_jumps_do_not_disable_checks_forever(self):
        state = self.fresh_state()
        state.update(last_attempt=time.time() + 86400, catalog_checked_at=time.time() + 86400,
                     openai_checked_at=time.time() + 86400)
        self.assertTrue(U._pricing_refresh_due(state))

    def test_background_worker_is_detached_and_requests_are_coalesced(self):
        with mock.patch.object(U.subprocess, "Popen", return_value=mock.Mock(pid=123)) as spawn:
            self.assertTrue(U._schedule_pricing_refresh(self.snapshot()))
            self.assertFalse(U._schedule_pricing_refresh(self.snapshot()))
        self.assertEqual(spawn.call_count, 1)
        args, kwargs = spawn.call_args
        self.assertEqual(args[0][-1], "--auto-update-prices")
        self.assertNotIn("gpt-9.1-terra", str(args))
        self.assertEqual(kwargs["stdout"], U.subprocess.DEVNULL)
        self.assertEqual(kwargs["start_new_session"], not U._IS_WINDOWS)
        state = json.loads(self.state.read_text())
        self.assertNotIn("gpt-9.1-terra", self.state.read_text())
        self.assertEqual(len(state["pending_models"][0]), 64)

    def test_windows_worker_does_not_open_a_console_or_use_a_shell(self):
        fd = os.open(self.root / "lock", os.O_RDWR | os.O_CREAT, 0o600)
        with mock.patch.object(U, "_IS_WINDOWS", True), \
             mock.patch.object(U, "_NO_WINDOW", {"creationflags": 0x08000000}), \
             mock.patch.object(U, "_pricing_update_lock", return_value=fd), \
             mock.patch.object(U, "_unlock_file"), \
             mock.patch.object(U.subprocess, "Popen", return_value=mock.Mock(pid=123)) as spawn:
            self.assertTrue(U._schedule_pricing_refresh(self.snapshot()))
        self.assertEqual(spawn.call_args.kwargs["creationflags"], 0x08000000)
        self.assertFalse(spawn.call_args.kwargs["start_new_session"])
        self.assertNotIn("shell", spawn.call_args.kwargs)

    def test_disabled_and_local_preview_do_not_start_network_work(self):
        with mock.patch.dict(os.environ, {"TOKEI_AUTO_PRICING": "0"}), \
             mock.patch.object(U.subprocess, "Popen") as spawn:
            self.assertFalse(U._schedule_pricing_refresh(self.snapshot()))
            spawn.assert_not_called()
        with mock.patch.object(U, "compute", return_value={}), \
             mock.patch.object(U, "_schedule_pricing_refresh") as schedule, \
             mock.patch.object(U.sys, "argv", ["usage.py", "--json", "--local-only", "--no-sync-snapshot"]):
            U.main_json()
            schedule.assert_not_called()

    def test_readonly_state_does_not_break_collection(self):
        with mock.patch.object(U, "_pricing_update_lock", side_effect=PermissionError("readonly")):
            self.assertFalse(U._schedule_pricing_refresh(self.snapshot()))

    def test_unknown_codex_price_is_marked_with_its_actual_reference(self):
        row = U._format_token_models({"gpt-9.1-terra": {"in": 1000}},
                                     price_model=U._codex_price_model)[0]
        self.assertEqual(row["pref"], "GPT-6.1 Terra")

    def test_both_sources_failing_preserves_prices_and_records_retry(self):
        with mock.patch.object(U, "_update_catalog_prices", side_effect=OSError("offline")), \
             mock.patch.object(U, "_update_openai_prices", side_effect=ValueError("changed")):
            self.assertEqual(U.update_prices(), 1)
        state = json.loads(self.state.read_text())
        self.assertEqual(state["errors"], ["catalog", "openai"])
        self.assertFalse(U._pricing_refresh_due(state, now=time.time() + 600))

    def test_source_download_is_bounded_and_uses_only_a_fixed_public_url(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.geturl.return_value = U._OPENAI_PRICING_URL
        response.read.return_value = PAGE.encode()
        with mock.patch("urllib.request.urlopen", return_value=response) as get:
            self.assertIn("openai/gpt-9.1-terra", U._fetch_openai_prices())
        request = get.call_args.args[0]
        self.assertEqual(request.full_url, U._OPENAI_PRICING_URL)
        self.assertIsNone(request.data)
        self.assertNotIn("Authorization", request.headers)
        response.read.assert_called_once_with(2 * 1024 * 1024 + 1)
        response.read.return_value = b"x" * (2 * 1024 * 1024 + 1)
        with mock.patch("urllib.request.urlopen", return_value=response), self.assertRaises(ValueError):
            U._fetch_openai_prices()

    def test_invalid_official_cache_cannot_supply_nonfinite_prices(self):
        self.official.write_text(json.dumps({"models": {
            "openai/gpt-9.1-terra": {"source": U._OPENAI_PRICING_URL,
                "in": float("nan"), "out": 5, "cache_read": .05}}}))
        self.assertEqual(U._load_official_pricing(), {})

    def test_config_can_disable_background_checks(self):
        (self.root / "config.json").write_text('{"auto_pricing_enabled":false}')
        with mock.patch.object(U.subprocess, "Popen") as spawn:
            self.assertFalse(U._schedule_pricing_refresh(self.snapshot()))
            spawn.assert_not_called()

    def test_large_unknown_sets_do_not_refetch_every_five_minutes(self):
        unknown = [f"model-{i:04d}" for i in range(300)]
        state = self.fresh_state()
        state["checked_models"] = unknown[-256:]
        state["unknown_signature"] = hashlib.sha256("\n".join(sorted(unknown)).encode()).hexdigest()
        with mock.patch.object(U, "_OFFICIAL_PRICING_DB", {"known": {}}):
            self.assertFalse(U._pricing_refresh_due(state, unknown))
            self.assertTrue(U._pricing_refresh_due(state, unknown + ["brand-new-model"]))

    def test_broken_optional_metadata_does_not_break_usage_json(self):
        self.official.write_text('[]')
        self.assertIsNone(U._pricing_metadata()["official_verified_at"])

    def test_auto_update_writes_user_cache_even_when_development_catalog_is_selected(self):
        development = self.root / "development/pricing.json"
        with mock.patch.object(U, "PRICING_FILE", str(development)), \
             mock.patch.object(U, "_update_catalog_prices", return_value=0) as catalog, \
             mock.patch.object(U, "_update_openai_prices", return_value=None):
            U.update_prices(auto=True)
            catalog.assert_called_once()
            self.assertEqual(U.PRICING_FILE, str(self.root / "pricing.json"))
            self.assertFalse(development.exists())


if __name__ == "__main__":
    unittest.main()
