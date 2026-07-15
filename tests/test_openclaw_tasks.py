import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from test_codex_limits import USAGE


class OpenClawTaskTests(unittest.TestCase):
    def create_database(self, path, created_ms, statuses):
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
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
        connection.commit()
        connection.close()

    def scan(self, state_db, legacy_db, agents_dir):
        old_state = USAGE.OPENCLAW_STATE_DB
        old_legacy = USAGE.OPENCLAW_DB
        old_agents = USAGE.OPENCLAW_AGENTS
        USAGE.OPENCLAW_STATE_DB = str(state_db)
        USAGE.OPENCLAW_DB = str(legacy_db)
        USAGE.OPENCLAW_AGENTS = str(agents_dir)
        try:
            cache = {"v": USAGE._SCAN_CACHE_VERSION}
            result = USAGE.scan_openclaw(USAGE.range_bounds(), cache)
            return result, cache
        finally:
            USAGE.OPENCLAW_STATE_DB = old_state
            USAGE.OPENCLAW_DB = old_legacy
            USAGE.OPENCLAW_AGENTS = old_agents

    def test_prefers_new_database_and_accepts_new_statuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_db = root / "state" / "openclaw.sqlite"
            legacy_db = root / "tasks" / "runs.sqlite"
            created_ms = int(datetime.now().astimezone().timestamp() * 1000)
            self.create_database(
                state_db, created_ms,
                ["succeeded", "success", "completed", "failed", "error"],
            )
            self.create_database(legacy_db, created_ms, ["completed"])

            result, cache = self.scan(state_db, legacy_db, root / "agents")

        today = result["ranges"]["today"]
        self.assertEqual(cache["openclaw"]["_db"]["path"], str(state_db))
        self.assertEqual(today["tasks"], 5)
        self.assertEqual(today["completed"], 3)
        self.assertEqual(today["failed"], 2)

    def test_falls_back_to_legacy_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_db = root / "state" / "openclaw.sqlite"
            legacy_db = root / "tasks" / "runs.sqlite"
            created_ms = int(datetime.now().astimezone().timestamp() * 1000)
            self.create_database(legacy_db, created_ms, ["completed", "failed"])

            result, cache = self.scan(state_db, legacy_db, root / "agents")

        today = result["ranges"]["today"]
        self.assertEqual(cache["openclaw"]["_db"]["path"], str(legacy_db))
        self.assertEqual(today["tasks"], 2)
        self.assertEqual(today["completed"], 1)
        self.assertEqual(today["failed"], 1)


if __name__ == "__main__":
    unittest.main()
