import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "Tokei" / "Sources" / "Tokei"


class UsageEmptyStateTests(unittest.TestCase):
    def test_swift_empty_state_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "usage-empty-state-check"
            result = subprocess.run(
                [
                    "swiftc",
                    "-parse-as-library",
                    str(SRC / "L10n.swift"),
                    str(SRC / "Model.swift"),
                    str(SRC / "UsageEmptyState.swift"),
                    str(ROOT / "tests/swift/UsageEmptyStateCheck.swift"),
                    "-o",
                    str(binary),
                ],
                capture_output=True,
                text=True,
                cwd=ROOT,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("usage empty state checks passed", result.stdout)


class RefreshSchedulingTests(unittest.TestCase):
    """面板的刷新调度。这些是真实故障的回归护栏，不是风格检查。"""

    def setUp(self):
        self.main = (SRC / "main.swift").read_text()

    def test_timer_runs_in_common_mode(self):
        """Timer.scheduledTimer 只注册 .default 模式：用户一滚动面板，
        runloop 进入 .eventTracking，自动刷新就停摆——越盯着看越不更新。"""
        self.assertIn("RunLoop.main.add(tick, forMode: .common)", self.main)
        # 定时刷新不能再退回 scheduledTimer
        refresh_timers = re.findall(
            r"Timer\.scheduledTimer\([^)]*\)\s*\{[^}]*store\.refresh\(\)", self.main
        )
        self.assertEqual(refresh_timers, [], "refresh timer must not use .default mode")

    def test_panel_open_refreshes_faster_than_idle(self):
        self.assertLess(
            self._interval("visibleRefreshInterval"),
            self._interval("idleRefreshInterval"),
            "an open panel must refresh more often than a closed one",
        )

    def test_scheduling_counts_the_refresh_the_panel_itself_triggered(self):
        """打开面板会顺手刷一次；调度要认这一次，否则开完面板马上又刷一遍。"""
        self.assertIn("lastRefreshStartedAt = Date()", self.main)
        self.assertIn(
            "Date().timeIntervalSince(self.store.lastRefreshStartedAt) >= due", self.main
        )

    def test_ui_can_tell_a_refresh_is_in_flight(self):
        """空态卡片要靠它区分「真没用量」和「还没刷出来」。"""
        self.assertIn("@Published var isRefreshing", self.main)
        self.assertIn("didSet { isRefreshing = refreshInFlight }", self.main)

    def _interval(self, name):
        match = re.search(rf"{name}:\s*TimeInterval\s*=\s*([0-9.]+)", self.main)
        self.assertIsNotNone(match, f"{name} not found")
        return float(match.group(1))


if __name__ == "__main__":
    unittest.main()
