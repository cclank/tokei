import importlib.util
import json
import os
import tempfile
import unittest
import urllib.error
import base64
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "usage.30s.py"
SPEC = importlib.util.spec_from_file_location("tokei_usage_reset_cards", SCRIPT)
USAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(USAGE)


class _Response:
    def __init__(self, payload, url=None):
        self.payload = json.dumps(payload).encode()
        self.url = url or USAGE._CODEX_RESET_CARDS_URL

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def geturl(self):
        return self.url

    def read(self, limit):
        return self.payload[:limit]


class CodexResetCardsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.auth_path = Path(self.tmp.name) / "auth.json"
        self.cache_path = Path(self.tmp.name) / "cache.json"
        self.auth_path.write_text(json.dumps({
            "tokens": {
                "access_token": "test-token",
                "account_id": "test-account",
            }
        }))
        self.patchers = [
            mock.patch.object(USAGE, "CODEX_AUTH", str(self.auth_path)),
            mock.patch.object(USAGE, "CODEX_RESET_CARDS_CACHE", str(self.cache_path)),
            mock.patch.object(USAGE, "_codex_uses_non_openai_provider", return_value=False),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def payload():
        return {
            "credits": [
                {
                    "id": "private-id",
                    "status": "available",
                    "is_supported_by_plan": True,
                    "expires_at": "2026-08-01T00:00:00Z",
                    "profile_user_id": "private-user",
                },
                {
                    "id": "used-card",
                    "status": "redeemed",
                    "is_supported_by_plan": True,
                    "expires_at": "2026-08-02T00:00:00Z",
                },
            ],
            "available_count": 1,
        }

    def test_normalizes_only_available_expirations(self):
        now = 1_785_000_000
        cards = USAGE._normalize_codex_reset_cards(self.payload(), now)

        self.assertEqual(cards["count"], 1)
        self.assertEqual(len(cards["expires"]), 1)
        self.assertEqual(set(cards), {"count", "expires", "updated"})

    def test_preserves_cards_with_the_same_expiration(self):
        now = 1_785_000_000
        credit = self.payload()["credits"][0]
        payload = {"credits": [credit, dict(credit)]}

        cards = USAGE._normalize_codex_reset_cards(payload, now)

        self.assertEqual(cards["count"], 2)
        self.assertEqual(cards["expires"], [cards["expires"][0]] * 2)

    def test_restart_reads_persistent_cache_without_another_request(self):
        now = 1_785_000_000
        opener = mock.Mock(return_value=_Response(self.payload()))
        with mock.patch("urllib.request.urlopen", opener):
            first = USAGE.fetch_codex_reset_cards(now_epoch=now)
            second = USAGE.fetch_codex_reset_cards(now_epoch=now + 60)

        self.assertEqual(first, second)
        self.assertEqual(opener.call_count, 1)
        state = json.loads(self.cache_path.read_text())
        self.assertLessEqual(
            state["next_attempt_at"],
            now + USAGE._CODEX_RESET_CARDS_REFRESH_INTERVAL,
        )
        self.assertNotIn("private-id", self.cache_path.read_text())
        self.assertNotIn("private-user", self.cache_path.read_text())

    def test_empty_result_is_cached_for_one_day(self):
        now = 1_785_000_000
        payload = {"credits": [], "available_count": 0}
        opener = mock.Mock(return_value=_Response(payload))
        with mock.patch("urllib.request.urlopen", opener):
            first = USAGE.fetch_codex_reset_cards(now_epoch=now)
            second = USAGE.fetch_codex_reset_cards(now_epoch=now + 3600)

        self.assertEqual(first["count"], 0)
        self.assertEqual(second["count"], 0)
        self.assertEqual(opener.call_count, 1)
        state = json.loads(self.cache_path.read_text())
        self.assertEqual(
            state["next_attempt_at"],
            now + USAGE._CODEX_RESET_CARDS_REFRESH_INTERVAL,
        )

    def test_nearest_expiry_refreshes_before_daily_interval(self):
        now = 1_785_000_000
        cards = {"count": 1, "expires": [now + 600], "updated": now}

        self.assertEqual(
            USAGE._codex_reset_cards_next_attempt(cards, now),
            now + 660,
        )

    def test_failure_uses_cache_and_backs_off(self):
        now = 1_785_000_000
        cards = USAGE._normalize_codex_reset_cards(self.payload(), now)
        context = USAGE._codex_auth_context(json.loads(self.auth_path.read_text()))
        self.cache_path.write_text(json.dumps({
            "account_key": context["account_key"],
            "auth_key": context["auth_key"],
            "cards": cards,
            "next_attempt_at": now,
        }))
        opener = mock.Mock(side_effect=OSError("offline"))
        with mock.patch("urllib.request.urlopen", opener):
            first = USAGE.fetch_codex_reset_cards(now_epoch=now)
            second = USAGE.fetch_codex_reset_cards(now_epoch=now + 60)

        self.assertEqual(first, cards)
        self.assertEqual(second, cards)
        self.assertEqual(opener.call_count, 1)
        state = json.loads(self.cache_path.read_text())
        self.assertEqual(
            state["next_attempt_at"],
            now + USAGE._CODEX_RESET_CARDS_RETRY_INTERVAL,
        )

    def test_expired_cached_card_is_hidden_during_failure(self):
        now = 1_785_000_000
        context = USAGE._codex_auth_context(json.loads(self.auth_path.read_text()))
        self.cache_path.write_text(json.dumps({
            "account_key": context["account_key"],
            "auth_key": context["auth_key"],
            "cards": {"count": 1, "expires": [now - 1], "updated": now - 100},
            "next_attempt_at": now,
        }))
        with mock.patch("urllib.request.urlopen", side_effect=OSError("offline")):
            cards = USAGE.fetch_codex_reset_cards(now_epoch=now)

        self.assertEqual(cards, {"count": 0, "expires": [], "updated": now - 100})

    def test_account_switch_does_not_show_previous_cards(self):
        now = 1_785_000_000
        self.cache_path.write_text(json.dumps({
            "account_key": "another-account",
            "cards": {"count": 1, "expires": [now + 5000], "updated": now - 100},
            "next_attempt_at": now + 5000,
        }))
        opener = mock.Mock(side_effect=OSError("offline"))
        with mock.patch("urllib.request.urlopen", opener):
            cards = USAGE.fetch_codex_reset_cards(now_epoch=now)

        self.assertEqual(cards, {})
        self.assertEqual(opener.call_count, 1)

    def test_missing_auth_does_not_request(self):
        self.auth_path.write_text(json.dumps({"OPENAI_API_KEY": "api-key-only"}))
        opener = mock.Mock()
        with mock.patch("urllib.request.urlopen", opener):
            cards = USAGE.fetch_codex_reset_cards(now_epoch=1_785_000_000)

        self.assertEqual(cards, {})
        opener.assert_not_called()

    def test_unauthorized_is_hidden_and_backed_off(self):
        now = 1_785_000_000
        error = urllib.error.HTTPError(
            USAGE._CODEX_RESET_CARDS_URL, 401, "Unauthorized", {}, None)
        with mock.patch("urllib.request.urlopen", side_effect=error):
            cards = USAGE.fetch_codex_reset_cards(now_epoch=now)

        self.assertEqual(cards, {})
        state = json.loads(self.cache_path.read_text())
        self.assertEqual(state["last_error"], "auth")
        self.assertEqual(
            state["next_attempt_at"],
            now + USAGE._CODEX_RESET_CARDS_RETRY_INTERVAL,
        )

    def test_changed_token_retries_immediately_after_auth_failure(self):
        now = 1_785_000_000
        old_context = USAGE._codex_auth_context(json.loads(self.auth_path.read_text()))
        self.cache_path.write_text(json.dumps({
            "account_key": old_context["account_key"],
            "auth_key": old_context["auth_key"],
            "last_error": "auth",
            "next_attempt_at": now + USAGE._CODEX_RESET_CARDS_RETRY_INTERVAL,
        }))
        self.auth_path.write_text(json.dumps({
            "tokens": {
                "access_token": "refreshed-token",
                "account_id": "test-account",
            }
        }))
        opener = mock.Mock(return_value=_Response(self.payload()))
        with mock.patch("urllib.request.urlopen", opener):
            cards = USAGE.fetch_codex_reset_cards(now_epoch=now + 60)

        self.assertEqual(cards["count"], 1)
        self.assertEqual(opener.call_count, 1)

    def test_account_id_falls_back_to_jwt_claim(self):
        payload = {
            "sub": "user-subject",
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "jwt-account",
            },
        }
        encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        token = f"header.{encoded}.signature"

        context = USAGE._codex_auth_context({
            "tokens": {"access_token": token},
        })

        self.assertEqual(context["account_id"], "jwt-account")
        self.assertTrue(context["account_key"])

    def test_rejects_cross_origin_redirect(self):
        now = 1_785_000_000
        opener = mock.Mock(return_value=_Response(
            self.payload(),
            url="https://example.com/rate-limit-reset-credits",
        ))
        with mock.patch("urllib.request.urlopen", opener):
            cards = USAGE.fetch_codex_reset_cards(now_epoch=now)

        self.assertEqual(cards, {})
        state = json.loads(self.cache_path.read_text())
        self.assertEqual(
            state["next_attempt_at"],
            now + USAGE._CODEX_RESET_CARDS_RETRY_INTERVAL,
        )


if __name__ == "__main__":
    unittest.main()
