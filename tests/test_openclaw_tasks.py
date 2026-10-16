import importlib.util
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

try:
    import zstandard as _zstandard
except ImportError:
    _zstandard = None

ZSTANDARD_AVAILABLE = _zstandard is not None


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

    def create_agent_database(self, path, events, session_models=None, fts_event=None,
                              zstd=False):
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        if zstd:
            connection.execute("""
                CREATE TABLE transcript_events (
                    session_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    event_json TEXT,
                    created_at INTEGER NOT NULL,
                    event_zstd BLOB,
                    event_utf8_bytes INTEGER
                )
            """)
        else:
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
        if zstd:
            if _zstandard is None:
                connection.close()
                self.skipTest("zstandard not installed")
            compressor = _zstandard.ZstdCompressor()
            rows = []
            for seq, (session_id, event, created_ms) in enumerate(events, 1):
                payload = json.dumps(event).encode("utf-8")
                rows.append((session_id, seq, None, created_ms,
                             compressor.compress(payload), len(payload)))
            connection.executemany(
                "INSERT INTO transcript_events VALUES (?, ?, ?, ?, ?, ?)", rows)
        else:
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

    def test_relative_agent_path_uses_openclaw_root_when_registry_is_overridden(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp)
            openclaw_root = fixture / "custom-openclaw-root"
            state_db = fixture / "registry-copy.sqlite"
            agent_db = (openclaw_root / "agents" / "example-agent" / "agent"
                        / "openclaw-agent.sqlite")
            now = datetime.now().astimezone().replace(microsecond=0)
            created_ms = int(now.timestamp() * 1000)
            self.create_database(state_db, created_ms, [], with_tasks=False)
            self.add_agent_registry(state_db, [
                "agents/example-agent/agent/openclaw-agent.sqlite",
            ])
            event = self.usage_event(
                "event-custom-root", now,
                {"input": 9, "output": 0, "totalTokens": 9,
                 "cost": {"total": 0}},
            )
            self.create_agent_database(
                agent_db, [("session-custom-root", event, created_ms)])

            result, _ = self.scan(
                state_db, fixture / "missing.sqlite", openclaw_root / "agents",
            )

        self.assertEqual(result["ranges"]["today"]["in"], 9)

    def test_reasoning_tokens_are_output_subset_for_totals_hours_and_cost(self):
        now = datetime.now().astimezone().replace(microsecond=0)
        event = self.usage_event(
            "event-priced", now,
            {"input": 10, "output": 20, "reasoningTokens": 5,
             "totalTokens": 30, "cost": {"total": 0}},
            model="vendor/example-priced",
        )
        with mock.patch.dict(USAGE._PRICING_DB, {
            "vendor/example-priced": {
                "in": 1.0, "out": 2.0, "cache_read": 3.0, "cache_write": 4.0,
            },
        }):
            record = USAGE._openclaw_usage_record(event)

        days = {}
        USAGE._openclaw_add_record(days, record)
        day = days[now.date().isoformat()]
        cache = {"openclaw": {"_selected_days": days}}
        with mock.patch.object(USAGE, "_load_ledger", return_value={"tools": {}}):
            daily = USAGE.build_daily_costs(refresh=False, _cache=cache)
        wrapped = USAGE.build_wrapped(refresh=False, _cache=cache)

        expected_cost = (10 * 1.0 + 20 * 2.0) / 1_000_000
        with self.subTest("reasoning detail remains available"):
            self.assertEqual(record["reason"], 5)
        with self.subTest("fallback output pricing does not add reasoning"):
            self.assertAlmostEqual(record["cost"], expected_cost, places=12)
        for label, actual in (
                ("hour total", day["hours"][now.hour]),
                ("daily total", daily["daily"][0]["tokens"]),
                ("daily model total", daily["models"][0]["tokens"]),
                ("wrapped total", wrapped["total_tokens"]),
                ("wrapped model total", wrapped["top_model"]["tokens"])):
            with self.subTest(label):
                self.assertEqual(actual, 30)

    def test_openclaw_state_dir_controls_defaults_and_relative_registry_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp)
            home = fixture / "home"
            cases = (
                ("default", None, home / ".openclaw"),
                ("absolute", str(fixture / "absolute-state"),
                 fixture / "absolute-state"),
                ("tilde", "~/tilde-state", home / "tilde-state"),
            )
            for name, configured, state_root in cases:
                with self.subTest(name):
                    registry_db = fixture / f"{name}-registry.sqlite"
                    relative_agent_db = Path(
                        "agents/example-agent/agent/openclaw-agent.sqlite")
                    agent_db = state_root / relative_agent_db
                    self.create_database(registry_db, 1_700_000_000_000, [],
                                         with_tasks=False)
                    self.add_agent_registry(registry_db, [str(relative_agent_db)])
                    self.create_agent_database(agent_db, [])
                    environment = {
                        "HOME": str(home),
                        "USERPROFILE": str(home),
                        "TOKEI_OPENCLAW_DB": str(registry_db),
                    }
                    if configured is not None:
                        environment["OPENCLAW_STATE_DIR"] = configured
                    with mock.patch.dict(os.environ, environment, clear=True):
                        spec = importlib.util.spec_from_file_location(
                            f"tokei_usage_openclaw_{name}", USAGE.__file__)
                        usage = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(usage)
                        registry_ok, paths = usage._openclaw_agent_db_paths(sqlite3)

                    self.assertEqual(
                        (usage.OPENCLAW_STATE_DB, usage.OPENCLAW_DB,
                         usage.OPENCLAW_AGENTS, registry_ok, paths),
                        (str(state_root / "state" / "openclaw.sqlite"),
                         str(state_root / "tasks" / "runs.sqlite"),
                         str(state_root / "agents"), True, [str(agent_db.resolve())]),
                    )

    def test_openclaw_card_treats_reasoning_as_output_detail(self):
        root = Path(__file__).resolve().parents[1]
        panel = (root / "Tokei" / "Sources" / "Tokei" / "PanelView.swift").read_text()
        start = panel.index("func openclawBlock(")
        end = panel.index("// MARK:", start)
        block = panel[start:end]

        self.assertIn("r.in + r.out + r.cr + r.cw", block)
        self.assertNotIn(
            "CostHeadline(value: Fmt.human(r.in + r.out + r.cr + r.cw + r.reason)",
            block,
        )
        self.assertIn("reasonIncludedInOutput: true", block)

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


    def test_reads_zstd_stored_transcript_events(self):
        """event_json 为 NULL 时正文在 event_zstd，用量事件不能被丢弃。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "openclaw fixture"
            state_db = root / "state" / "openclaw.sqlite"
            agent_db = root / "agents" / "example-agent" / "agent" / "openclaw-agent.sqlite"
            now = datetime.now().astimezone().replace(microsecond=0)
            created_ms = int((now - timedelta(days=1)).timestamp() * 1000)
            task_created_ms = int(now.timestamp() * 1000)
            usage = {"input": 120, "output": 30, "cacheRead": 40, "cacheWrite": 0,
                     "reasoningTokens": 7, "totalTokens": 190,
                     "cost": {"total": 0.75}}
            assistant = self.usage_event("zstd-usage", now, usage)
            self.create_database(state_db, task_created_ms, ["completed"])
            self.add_agent_registry(state_db, [
                os.path.relpath(agent_db, root)])
            self.create_agent_database(
                agent_db,
                [("session-zstd", assistant, created_ms)],
                {"session-zstd": "vendor/zstd-session-model"},
                zstd=True,
            )

            result, _ = self.scan(state_db, root / "tasks" / "runs.sqlite",
                                  root / "agents")

        today = result["ranges"]["today"]
        self.assertEqual((today["in"], today["out"], today["cr"], today["cw"],
                          today["reason"]), (120, 30, 40, 0, 7))
        self.assertAlmostEqual(today["cost"], 0.75)
        self.assertEqual(today["sessions"], {"session-zstd"})

    def test_mixed_json_and_zstd_events_are_deduplicated(self):
        """两种存储并存时按事件 id 去重，不会把同一事件算两次。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "openclaw fixture"
            state_db = root / "state" / "openclaw.sqlite"
            agent_db = root / "agents" / "example-agent" / "agent" / "openclaw-agent.sqlite"
            now = datetime.now().astimezone().replace(microsecond=0)
            created_ms = int((now - timedelta(days=1)).timestamp() * 1000)
            task_created_ms = int(now.timestamp() * 1000)
            json_usage = {"input": 100, "output": 10, "cacheRead": 0, "cacheWrite": 0,
                          "reasoningTokens": 0, "totalTokens": 110,
                          "cost": {"total": 0.1}}
            zstd_usage = {"input": 500, "output": 50, "cacheRead": 0, "cacheWrite": 0,
                          "reasoningTokens": 0, "totalTokens": 550,
                          "cost": {"total": 0.5}}
            json_event = self.usage_event("evt-json", now, json_usage)
            zstd_event = self.usage_event("evt-zstd", now, zstd_usage)
            duplicate = self.usage_event("evt-json", now, zstd_usage)
            self.create_database(state_db, task_created_ms, ["completed"])
            self.add_agent_registry(state_db, [os.path.relpath(agent_db, root)])
            self.create_agent_database(
                agent_db,
                [("session-mixed", json_event, created_ms),
                 ("session-mixed", zstd_event, created_ms),
                 ("session-mixed", duplicate, created_ms)],
                zstd=True,
            )

            result, _ = self.scan(state_db, root / "tasks" / "runs.sqlite",
                                  root / "agents")

        today = result["ranges"]["today"]
        # evt-json(100) 只计一次（幂等重复行被 id 去重），加 evt-zstd(500)
        self.assertEqual(today["in"], 600)
        self.assertEqual(today["out"], 60)

    def test_zstd_events_skipped_when_dependency_missing(self):
        """缺 zstandard 时安全降级：不报错，只是读不到压缩事件。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "openclaw fixture"
            state_db = root / "state" / "openclaw.sqlite"
            agent_db = root / "agents" / "example-agent" / "agent" / "openclaw-agent.sqlite"
            now = datetime.now().astimezone().replace(microsecond=0)
            created_ms = int((now - timedelta(days=1)).timestamp() * 1000)
            task_created_ms = int(now.timestamp() * 1000)
            assistant = self.usage_event(
                "zstd-usage", now,
                {"input": 120, "output": 30, "cacheRead": 0, "cacheWrite": 0,
                 "reasoningTokens": 0, "totalTokens": 150, "cost": {"total": 0.75}},
            )
            self.create_database(state_db, task_created_ms, ["completed"])
            self.add_agent_registry(state_db, [os.path.relpath(agent_db, root)])
            self.create_agent_database(agent_db, [("session-zstd", assistant, created_ms)],
                                       zstd=True)

            with mock.patch.object(USAGE, "_OPENCLAW_ZSTD_AVAILABLE", False):
                result, _ = self.scan(state_db, root / "tasks" / "runs.sqlite",
                                      root / "agents")

        today = result["ranges"]["today"]
        # 解压不可用：压缩事件被跳过，但扫描本身不得抛异常
        self.assertEqual((today["in"], today["out"]), (0, 0))

    def test_parser_version_bump_rescans_stale_cached_sessions(self):
        """旧缓存（parser_version=3）必须被重扫，才能补回压缩事件。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "openclaw fixture"
            state_db = root / "state" / "openclaw.sqlite"
            agent_db = root / "agents" / "example-agent" / "agent" / "openclaw-agent.sqlite"
            now = datetime.now().astimezone().replace(microsecond=0)
            created_ms = int((now - timedelta(days=1)).timestamp() * 1000)
            task_created_ms = int(now.timestamp() * 1000)
            assistant = self.usage_event(
                "zstd-usage", now,
                {"input": 120, "output": 30, "cacheRead": 0, "cacheWrite": 0,
                 "reasoningTokens": 0, "totalTokens": 150, "cost": {"total": 0.75}},
            )
            self.create_database(state_db, task_created_ms, ["completed"])
            self.add_agent_registry(state_db, [os.path.relpath(agent_db, root)])
            self.create_agent_database(agent_db, [("session-zstd", assistant, created_ms)],
                                       zstd=True)

            # 模拟旧解析器写下的缓存：parser_version 落后，days 为空
            entry_key = "sqlite:" + os.path.realpath(str(agent_db))
            stale_entry = {"source": "sqlite", "path": str(agent_db),
                           "sig": "stale-signature", "parser_version": 3,
                           "sessions": {}}
            cache = {"v": USAGE._SCAN_CACHE_VERSION,
                     "openclaw": {entry_key: stale_entry}}
            result, cache = self.scan(state_db, root / "tasks" / "runs.sqlite",
                                      root / "agents", cache=cache)

        refreshed = cache["openclaw"][entry_key]
        self.assertEqual(refreshed["parser_version"], USAGE._OPENCLAW_PARSER_VERSION)
        self.assertGreaterEqual(refreshed["parser_version"], 4)

    def test_zstd_decoder_rejects_non_zstd_input(self):
        """只接受 zstd 魔数开头的 BLOB，其余一律返回 None。"""
        self.assertIsNone(USAGE._openclaw_zstd_blob(b"not-zstd"))
        self.assertIsNone(USAGE._openclaw_zstd_blob(b""))
        self.assertIsNone(USAGE._openclaw_zstd_blob(None))
        self.assertIsNone(USAGE._openclaw_zstd_blob("a string"))


if __name__ == "__main__":
    unittest.main()
