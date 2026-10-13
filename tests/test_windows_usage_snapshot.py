"""A delayed initial response must not replace a newer cross-window event."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WindowsUsageSnapshotTests(unittest.TestCase):
    def test_newer_event_wins_over_late_initial_snapshot(self):
        node = shutil.which("node")
        compiler = ROOT / "windows/node_modules/typescript/bin/tsc"
        if not node or not compiler.is_file():
            self.skipTest("Windows frontend dependencies are not installed")
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([
                node, str(compiler), "--ignoreConfig", "--module", "commonjs",
                "--target", "ES2020", "--skipLibCheck", "--outDir", tmp,
                "src/lib/usageSnapshot.ts",
            ], cwd=ROOT / "windows", capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            script = r"""
const assert = require('node:assert/strict');
const {newerSnapshot} = require(process.argv[1]);
const initial = {revision: 3, state: {usage: {tokens: 10}, error: null, updated_at: 100, refreshing: false}};
const event = {revision: 5, state: {usage: {tokens: 20}, error: null, updated_at: 200, refreshing: false}};
let current = newerSnapshot(null, event);
assert.equal(current, event);
assert.equal(newerSnapshot(current, initial), event);
assert.equal(newerSnapshot(current, {...event}), event);
const failed = {revision: 6, state: {...event.state, error: 'offline'}};
assert.equal(newerSnapshot(current, failed), failed);
assert.equal(failed.state.usage.tokens, 20);
"""
            result = subprocess.run([
                node, "-e", script, str(Path(tmp) / "usageSnapshot.js"),
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
