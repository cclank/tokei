import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

try:
    from .test_codex_limits import USAGE
except ImportError:
    from test_codex_limits import USAGE


class OpenClawTaskTests(unittest.TestCase):
    def create_database(self, path, created_ms, statuses, with_tasks=True):
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        if with_tasks:
            connection.execute("""
                CREATE TABLE task_runs (
                    run_id TEXT PRIMARY KEY, status TEXT, created_at INTEGER
                )
            """)
            connection.executemany(
                "INSERT INTO task_runs VALUES (?, ?, ?)",
                [(f"run-{index}", status, created_ms)
                 for index, status in enumerate(statuses)],
            )
        else:
            connection.execute("CREATE TABLE metadata (key TEXT, value TEXT)")
        connection.commit()
        connection.close()

    def add_agent_registry(self, state_db, paths):
        state_db.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(state_db)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS agent_databases (
                agent_id TEXT NOT NULL,
                path TEXT NOT NULL,
                schema_version INTEGER NOT NULL,
                last_seen_at INTEGER NOT NULL,
                size_bytes INTEGER,
                PRIMARY KEY (agent_id, path)
            )
        """)
        connection.executemany(
            "INSERT INTO agent_databases VALUES (?, ?, ?, ?, ?)",
            [(f"agent-{index}", path, 19, 1_700_000_000_000, None)
             for index, path in enumerate(paths)],
        )
        connection.commit()
        connection.close()

    def create_agent_database(self, path, events, session_models=None, fts_event=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        connection.execute("""
            CREATE TABLE transcript_events (
                session_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                event_json TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (session_id, seq)
            )
        """)
        connection.execute("""
            CREATE TABLE session_windows (
                session_id TEXT PRIMARY KEY,
                session_key TEXT NOT NULL,
                previous_session_id TEXT,
                reason TEXT,
                session_scope TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                transcript_updated_at INTEGER,
                transcript_observed_at INTEGER,
                session_entry_provenance INTEGER NOT NULL,
                acp_owned INTEGER NOT NULL,
                plugin_owner_id TEXT,
                hook_external_content_source TEXT,
                started_at INTEGER,
                ended_at INTEGER,
                status TEXT,
                chat_type TEXT,
                channel TEXT,
                account_id TEXT,
                primary_conversation_id TEXT,
                model_provider TEXT,
                model TEXT,
                agent_harness_id TEXT,
                parent_session_key TEXT,
                spawned_by TEXT,
                display_name TEXT
            )
        """)
        connection.execute("CREATE TABLE session_transcript_fts (event_json TEXT NOT NULL)")
        connection.executemany(
            "INSERT INTO transcript_events VALUES (?, ?, ?, ?)",
            [(session_id, seq, json.dumps(event), created_ms)
             for seq, (session_id, event, created_ms) in enumerate(events, 1)],
        )
        for session_id, model in (session_models or {}).items():
            created_ms = next(
                created for sid, _, created in events if sid == session_id)
            connection.execute("""
                INSERT INTO session_windows (
                    session_id, session_key, session_scope, created_at, updated_at,
                    session_entry_provenance, acp_owned, started_at, model
                ) VALUES (?, ?, 'local', ?, ?, 1, 0, ?, ?)
            """, (session_id, f"session:{session_id}", created_ms, created_ms,
                  created_ms, model))
        if fts_event is not None:
            connection.execute(
                "INSERT INTO session_transcript_fts VALUES (?)", (json.dumps(fts_event),))
        connection.commit()
        connection.close()

    def usage_event(self, event_id, timestamp, usage, role="assistant",
                    model=None, response_model=None):
        message = {"role": role, "usage": usage}
        if model is not None:
            message["model"] = model
        if response_model is not None:
            message["responseModel"] = response_model
        return {"type": "message", "id": event_id,
                "timestamp": timestamp.isoformat(), "message": message}

    def write_jsonl(self, path, session_id, events):
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [{"type": "session", "id": session_id,
                 "timestamp": datetime.now().astimezone().isoformat()}] + events
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def scan(self, state_db, legacy_db, agents_dir, cache=None, ledger=None):
        old_state = USAGE.OPENCLAW_STATE_DB
        old_legacy = USAGE.OPENCLAW_DB
        old_agents = USAGE.OPENCLAW_AGENTS
        old_ledger_cache = USAGE._LEDGER_CACHE.copy()
        USAGE.OPENCLAW_STATE_DB = str(state_db)
        USAGE.OPENCLAW_DB = str(legacy_db)
        USAGE.OPENCLAW_AGENTS = str(agents_dir)
        USAGE._LEDGER_CACHE.clear()
        USAGE._LEDGER_CACHE.update({
            "data": ledger or {"v": USAGE._LEDGER_VERSION,
                                "tools": {"openclaw": {}}},
            "dirty": False,
        })
        try:
            if cache is None:
                cache = {"v": USAGE._SCAN_CACHE_VERSION}
            result = USAGE.scan_openclaw(USAGE.range_bounds(), cache)
            return result, cache
        finally:
            USAGE.OPENCLAW_STATE_DB = old_state
            USAGE.OPENCLAW_DB = old_legacy
            USAGE.OPENCLAW_AGENTS = old_agents
            USAGE._LEDGER_CACHE.clear()
            USAGE._LEDGER_CACHE.update(old_ledger_cache)

    def test_prefers_new_database_and_accepts_current_statuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "db ? folder"
            state_db = root / "state" / "openclaw.sqlite"
            legacy_db = root / "tasks" / "runs.sqlite"
            created_ms = int(datetime.now().astimezone().timestamp() * 1000)
            self.create_database(
                state_db, created_ms,
                ["succeeded", "success", "completed", "FAILED", "error"],
            )
            self.create_database(legacy_db, created_ms, ["completed"])

            result, cache = self.scan(state_db, legacy_db, root / "agents")

        today = result["ranges"]["today"]
        self.assertEqual(cache["openclaw"]["_db"]["path"], str(state_db))
        self.assertEqual(today["tasks"], 5)
        self.assertEqual(today["completed"], 3)
        self.assertEqual(today["failed"], 2)

    def test_falls_back_when_new_database_is_missing_or_has_no_task_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_db = root / "state" / "openclaw.sqlite"
            legacy_db = root / "tasks" / "runs.sqlite"
            created_ms = int(datetime.now().astimezone().timestamp() * 1000)
            self.create_database(state_db, created_ms, [], with_tasks=False)
            self.create_database(legacy_db, created_ms, ["completed", "failed"])

            result, cache = self.scan(state_db, legacy_db, root / "agents")

        today = result["ranges"]["today"]
        self.assertEqual(cache["openclaw"]["_db"]["path"], str(legacy_db))
        self.assertEqual(today["tasks"], 2)
        self.assertEqual(today["completed"], 1)
        self.assertEqual(today["failed"], 1)

    def test_falls_back_when_new_task_table_has_an_incompatible_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_db = root / "state" / "openclaw.sqlite"
            legacy_db = root / "tasks" / "runs.sqlite"
            state_db.parent.mkdir(parents=True)
            connection = sqlite3.connect(state_db)
            connection.execute("CREATE TABLE task_runs (run_id TEXT PRIMARY KEY)")
            connection.commit()
            connection.close()
            created_ms = int(datetime.now().astimezone().timestamp() * 1000)
            self.create_database(legacy_db, created_ms, ["success"])

            result, cache = self.scan(state_db, legacy_db, root / "agents")

        self.assertEqual(cache["openclaw"]["_db"]["path"], str(legacy_db))
        self.assertEqual(result["ranges"]["today"]["completed"], 1)

    def test_does_not_reuse_legacy_counts_when_new_database_read_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_db = root / "state" / "openclaw.sqlite"
            legacy_db = root / "tasks" / "runs.sqlite"
            created_ms = int(datetime.now().astimezone().timestamp() * 1000)
            self.create_database(legacy_db, created_ms, ["completed"])
            _, cache = self.scan(state_db, legacy_db, root / "agents")

            self.create_database(state_db, created_ms, ["succeeded", "succeeded"])
            old_state = USAGE.OPENCLAW_STATE_DB
            old_legacy = USAGE.OPENCLAW_DB
            old_agents = USAGE.OPENCLAW_AGENTS
            USAGE.OPENCLAW_STATE_DB = str(state_db)
            USAGE.OPENCLAW_DB = str(legacy_db)
            USAGE.OPENCLAW_AGENTS = str(root / "agents")
            try:
                with mock.patch.object(USAGE, "_scan_openclaw_db", side_effect=sqlite3.OperationalError):
                    result = USAGE.scan_openclaw(USAGE.range_bounds(), cache)
            finally:
                USAGE.OPENCLAW_STATE_DB = old_state
                USAGE.OPENCLAW_DB = old_legacy
                USAGE.OPENCLAW_AGENTS = old_agents

        self.assertEqual(result["ranges"]["today"]["tasks"], 0)

    def test_discovers_relative_agent_database_and_reads_only_transcript_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "openclaw fixture"
            state_db = root / "state" / "openclaw.sqlite"
            legacy_db = root / "tasks" / "runs.sqlite"
            agent_db = root / "agents" / "example-agent" / "agent" / "openclaw-agent.sqlite"
            now = datetime.now().astimezone().replace(microsecond=0)
            created_ms = int((now - timedelta(days=1)).timestamp() * 1000)
            task_created_ms = int(now.timestamp() * 1000)
            usage = {"input": 0, "output": 0, "cacheRead": 40, "cacheWrite": 3,
                     "reasoningTokens": 7, "totalTokens": 50,
                     "cost": {"total": 0.75}}
            assistant = self.usage_event("event-usage", now, usage)
            user_decoy = self.usage_event(
                "event-user", now,
                {"input": 9_999, "output": 9_999, "cost": {"total": 99}},
                role="user",
            )
            no_usage = {"type": "message", "id": "event-no-usage",
                        "timestamp": now.isoformat(),
                        "message": {"role": "assistant"}}
            fts_decoy = self.usage_event(
                "fts-decoy", now,
                {"input": 8_888, "output": 8_888, "cost": {"total": 88}},
            )
            self.create_database(state_db, task_created_ms, ["completed"])
            relative = os.path.relpath(agent_db, root)
            self.add_agent_registry(state_db, [relative, relative])
            self.create_agent_database(
                agent_db,
                [("session-sqlite", assistant, created_ms),
                 ("session-sqlite", user_decoy, created_ms),
                 ("session-sqlite", no_usage, created_ms)],
                {"session-sqlite": "vendor/example-session-model"},
                fts_event=fts_decoy,
            )
            trajectory = (root / "agents" / "example-agent" / "sessions"
                          / "ignored.trajectory.jsonl")
            self.write_jsonl(trajectory, "trajectory-session", [fts_decoy])

            result, cache = self.scan(state_db, legacy_db, root / "agents")

        today = result["ranges"]["today"]
        self.assertEqual(today["tasks"], 1)
        self.assertEqual((today["in"], today["out"], today["cr"], today["cw"],
                          today["reason"]), (0, 0, 40, 3, 7))
        self.assertAlmostEqual(today["cost"], 0.75)
        self.assertEqual(today["sessions"], {"session-sqlite"})
        selected = cache["openclaw"]["_selected_days"][now.date().isoformat()]
        self.assertIn("vendor/example-session-model", selected["models"])
        sqlite_entries = [entry for entry in cache["openclaw"].values()
                          if isinstance(entry, dict) and entry.get("source") == "sqlite"]
        self.assertEqual(len(sqlite_entries), 1)

    def test_response_model_precedes_message_model_and_unknown_stays_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_db = root / "state" / "openclaw.sqlite"
            agent_db = root / "agents" / "example-agent" / "agent" / "openclaw-agent.sqlite"
            now = datetime.now().astimezone().replace(microsecond=0)
            created_ms = int(now.timestamp() * 1000)
            self.create_database(state_db, created_ms, [], with_tasks=False)
            self.add_agent_registry(state_db, [os.path.relpath(agent_db, root)])
            base_usage = {"input": 5, "output": 2, "cacheRead": 0,
                          "cacheWrite": 0, "reasoningTokens": 0,
                          "totalTokens": 7, "cost": {"total": 0}}
            response_event = self.usage_event(
                "event-response", now, base_usage,
                model="vendor/example-message-model",
                response_model="vendor/example-response-model",
            )
            unknown_event = self.usage_event(
                "event-unknown", now, base_usage,
            )
            self.create_agent_database(
                agent_db,
                [("session-response", response_event, created_ms),
                 ("session-unknown", unknown_event, created_ms)],
            )

            _, cache = self.scan(state_db, root / "missing.sqlite", root / "agents")

        models = cache["openclaw"]["_selected_days"][now.date().isoformat()]["models"]
        self.assertIn("vendor/example-response-model", models)
        self.assertNotIn("vendor/example-message-model", models)
        self.assertIn("unknown", models)

    def test_pricing_fallback_treats_reasoning_as_separate_output(self):
        now = datetime.now().astimezone().replace(microsecond=0)
        event = self.usage_event(
            "event-priced", now,
            {"input": 10, "output": 20, "cacheRead": 30, "cacheWrite": 40,
             "reasoningTokens": 5, "totalTokens": 105, "cost": {"total": 0}},
            model="vendor/example-priced",
        )
        with mock.patch.dict(USAGE._PRICING_DB, {
            "vendor/example-priced": {
                "in": 1.0, "out": 2.0, "cache_read": 3.0, "cache_write": 4.0,
            },
        }):
            record = USAGE._openclaw_usage_record(event)

        expected = (10 * 1.0 + (20 + 5) * 2.0 + 30 * 3.0 + 40 * 4.0) / 1_000_000
        self.assertAlmostEqual(record["cost"], expected, places=12)

    def test_sqlite_and_jsonl_choose_one_copy_per_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_db = root / "state" / "openclaw.sqlite"
            agent_db = root / "agents" / "example-agent" / "agent" / "openclaw-agent.sqlite"
            sessions_dir = root / "agents" / "example-agent" / "sessions"
            now = datetime.now().astimezone().replace(microsecond=0)
            created_ms = int(now.timestamp() * 1000)
            self.create_database(state_db, created_ms, [], with_tasks=False)
            self.add_agent_registry(state_db, [os.path.relpath(agent_db, root)])
            shared = self.usage_event(
                "event-shared", now,
                {"input": 10, "output": 0, "cacheRead": 0, "cacheWrite": 0,
                 "reasoningTokens": 0, "totalTokens": 10, "cost": {"total": 0}},
                model="vendor/example-model",
            )
            unique = self.usage_event(
                "event-unique", now,
                {"input": 7, "output": 0, "cacheRead": 0, "cacheWrite": 0,
                 "reasoningTokens": 0, "totalTokens": 7, "cost": {"total": 0}},
                model="vendor/example-model",
            )
            trajectory = self.usage_event(
                "event-trajectory", now,
                {"input": 1_000, "output": 0, "cacheRead": 0, "cacheWrite": 0,
                 "reasoningTokens": 0, "totalTokens": 1_000, "cost": {"total": 0}},
            )
            self.create_agent_database(
                agent_db, [("session-shared", shared, created_ms)])
            self.write_jsonl(sessions_dir / "session-shared.jsonl", "session-shared", [shared])
            self.write_jsonl(sessions_dir / "archived-copy.jsonl", "session-shared", [shared])
            self.write_jsonl(sessions_dir / "session-unique.jsonl", "session-unique", [unique])
            self.write_jsonl(
                sessions_dir / "session-unique.trajectory.jsonl",
                "session-unique", [trajectory],
            )

            result, _ = self.scan(state_db, root / "missing.sqlite", root / "agents")

        today = result["ranges"]["today"]
        self.assertEqual(today["in"], 17)
        self.assertEqual(today["sessions"], {"session-shared", "session-unique"})

    def test_agent_wal_change_invalidates_cached_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_db = root / "state" / "openclaw.sqlite"
            agent_db = root / "agents" / "example-agent" / "agent" / "openclaw-agent.sqlite"
            now = datetime.now().astimezone().replace(microsecond=0)
            created_ms = int(now.timestamp() * 1000)
            self.create_database(state_db, created_ms, [], with_tasks=False)
            self.add_agent_registry(state_db, [os.path.relpath(agent_db, root)])
            first = self.usage_event(
                "event-first", now,
                {"input": 3, "output": 0, "totalTokens": 3, "cost": {"total": 0}},
            )
            second = self.usage_event(
                "event-second", now,
                {"input": 4, "output": 0, "totalTokens": 4, "cost": {"total": 0}},
            )
            self.create_agent_database(
                agent_db, [("session-wal", first, created_ms)])
            cache = {"v": USAGE._SCAN_CACHE_VERSION}
            initial, cache = self.scan(
                state_db, root / "missing.sqlite", root / "agents", cache=cache)
            connection = sqlite3.connect(agent_db)
            try:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA wal_autocheckpoint=0")
                connection.execute(
                    "INSERT INTO transcript_events VALUES (?, ?, ?, ?)",
                    ("session-wal", 2, json.dumps(second), created_ms),
                )
                connection.commit()
                self.assertTrue(Path(str(agent_db) + "-wal").exists())
                refreshed, cache = self.scan(
                    state_db, root / "missing.sqlite", root / "agents", cache=cache)
            finally:
                connection.close()

        self.assertEqual(initial["ranges"]["today"]["in"], 3)
        self.assertEqual(refreshed["ranges"]["today"]["in"], 7)
        sqlite_entry = next(
            entry for entry in cache["openclaw"].values()
            if isinstance(entry, dict) and entry.get("source") == "sqlite"
        )
        self.assertIn("-wal", sqlite_entry["sig"])

    def test_legacy_jsonl_remains_supported_without_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = datetime.now().astimezone().replace(microsecond=0)
            event = self.usage_event(
                "legacy-event", now,
                {"input": 2, "output": 3, "cacheRead": 4, "cacheWrite": 5,
                 "reasoningTokens": 6, "totalTokens": 20, "cost": {"total": 0.2}},
                model="vendor/example-legacy-model",
            )
            self.write_jsonl(
                root / "agents" / "example-agent" / "sessions" / "legacy.jsonl",
                "legacy-session", [event],
            )

            result, _ = self.scan(
                root / "missing-state.sqlite", root / "missing-legacy.sqlite",
                root / "agents",
            )

        today = result["ranges"]["today"]
        self.assertEqual((today["in"], today["out"], today["cr"], today["cw"],
                          today["reason"]), (2, 3, 4, 5, 6))
        self.assertEqual(today["sessions"], {"legacy-session"})
        self.assertAlmostEqual(today["cost"], 0.2)

    def test_new_openclaw_ledger_version_can_replace_old_duplicate_high_water(self):
        day_key = datetime.now().astimezone().date().isoformat()
        old = {"in": 100, "out": 20, "cr": 0, "cw": 0, "reason": 0,
               "cost": 1.0, "models": {}, "hours": [0] * 24}
        new = {"in": 10, "out": 2, "cr": 0, "cw": 0, "reason": 1,
               "cost": 0.1, "models": {}, "hours": [0] * 24,
               "_ledger_version": USAGE._OPENCLAW_LEDGER_VERSION}
        ledger = {"v": USAGE._LEDGER_VERSION,
                  "tools": {"openclaw": {day_key: old}}}
        original = USAGE._LEDGER_CACHE.copy()
        try:
            USAGE._LEDGER_CACHE.clear()
            USAGE._LEDGER_CACHE.update({"data": ledger, "dirty": False})
            merged = USAGE.ledger_reconcile("openclaw", {day_key: new})
        finally:
            USAGE._LEDGER_CACHE.clear()
            USAGE._LEDGER_CACHE.update(original)

        self.assertEqual(merged[day_key]["in"], 10)
        self.assertEqual(merged[day_key]["reason"], 1)


if __name__ == "__main__":
    unittest.main()
