import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from test_codex_limits import USAGE


class QuotaDetailCacheTests(unittest.TestCase):
    def test_recent_snapshot_avoids_collection_and_preserves_quota_fields(self):
        payload = {tool: {} for tool, _ in USAGE._QUOTA_TOOLS}
        payload['codex'] = {'pw': 42, 'rw': 2000000000, 'q_updated': 1900000000}
        cache = {'_dirty': False, 'codex': {}}
        with tempfile.TemporaryDirectory() as home:
            path = Path(home, '.tokei', 'last_usage.json')
            path.parent.mkdir()
            path.write_text(json.dumps(payload))
            with mock.patch.object(USAGE, 'HOME', home), \
                 mock.patch.object(USAGE, '_load_scan_cache', return_value=cache) as load, \
                 mock.patch.object(USAGE, 'compute') as collect:
                actual, actual_cache = USAGE._quota_detail_inputs()

        self.assertEqual(actual, payload)
        self.assertIs(actual_cache, cache)
        load.assert_called_once_with()
        collect.assert_not_called()

    def test_missing_stale_future_corrupt_and_invalid_snapshots_collect(self):
        valid = json.dumps({tool: {} for tool, _ in USAGE._QUOTA_TOOLS})
        cases = [(None, 0), (valid, -61), (valid, 120), ('{', 0), ('[]', 0), ('{}', 0)]
        for content, offset in cases:
            with self.subTest(content=content, offset=offset), tempfile.TemporaryDirectory() as home:
                path = Path(home, '.tokei', 'last_usage.json')
                path.parent.mkdir()
                if content is not None:
                    path.write_text(content)
                    stamp = time.time() + offset
                    os.utime(path, (stamp, stamp))
                with mock.patch.object(USAGE, 'HOME', home), mock.patch.object(USAGE, 'compute', return_value={'fresh': True}) as collect:
                    self.assertEqual(USAGE._quota_detail_payload(), {'fresh': True})
                    collect.assert_called_once_with()

    def test_dirty_event_cache_forces_collection_and_reloads_cache(self):
        payload = {tool: {} for tool, _ in USAGE._QUOTA_TOOLS}
        refreshed_cache = {'_dirty': False, 'codex': {'fresh': True}}
        with tempfile.TemporaryDirectory() as home:
            path = Path(home, '.tokei', 'last_usage.json')
            path.parent.mkdir()
            path.write_text(json.dumps(payload))
            with mock.patch.object(USAGE, 'HOME', home), \
                 mock.patch.object(USAGE, '_load_scan_cache', side_effect=[
                     {'_dirty': True}, refreshed_cache,
                 ]) as load, \
                 mock.patch.object(USAGE, 'compute', return_value=payload) as collect:
                actual, cache = USAGE._quota_detail_inputs()

        self.assertEqual(actual, payload)
        self.assertIs(cache, refreshed_cache)
        collect.assert_called_once_with()
        self.assertEqual(load.call_count, 2)

    def test_shared_cache_preserves_deduplication_and_codex_token_units(self):
        ts = "2026-07-10T00:00:00+00:00"
        cache = {
            'claude': {'session': {'events': [
                {'mid': 'm', 'timestamp': ts, 'in': 100, 'out': 10, 'cr': 20},
                {'mid': 'm', 'timestamp': ts, 'in': 100, 'out': 10, 'cr': 20},
            ]}},
            'codex': {
                'canonical': {'canonical': True, 'event_count': 2, 'drop_count': 1},
                'duplicate': {'canonical': False, 'event_count': 2},
            },
        }
        # idx6 includes cached input; idx7 must not be added a second time.
        row = [ts, '2026-07-10', 100, 80, 5, 0, 100, 80, 5]
        with mock.patch.object(USAGE, '_load_scan_cache', return_value=cache) as load, \
             mock.patch.object(USAGE, '_iter_codex_cached_events', return_value=[row]) as rows:
            expected_claude = USAGE._quota_claude_events()
            expected_codex = USAGE._quota_codex_events([(1, 2000000000)])
            load.reset_mock()
            rows.reset_mock()
            self.assertEqual(USAGE._quota_claude_events(cache), expected_claude)
            self.assertEqual(USAGE._quota_codex_events([(1, 2000000000)], cache), expected_codex)
            self.assertEqual([e[2] for e in expected_claude], [130])
            self.assertEqual([e[2] for e in expected_codex], [105])
            rows.assert_called_once_with('canonical', start_index=1)
            load.assert_not_called()

    def test_detail_loads_event_cache_once_for_both_providers(self):
        now = int(time.time())
        cache = {'claude': {}, 'codex': {}}
        anchors = {tool: [{'reset': now + 3600, 'max_used': 20}] for tool in ('claude', 'codex')}
        with mock.patch.object(USAGE, '_quota_detail_inputs', return_value=({}, cache)) as inputs, \
             mock.patch.object(USAGE, '_quota_device_ledgers', return_value=([], [])), \
             mock.patch.object(USAGE, '_quota_cycle_specs', return_value=(['claude', 'codex'], ['grok'], anchors)):
            result = USAGE.build_quota_detail()
            self.assertEqual(len(result['cycles']), 2)
            self.assertEqual({c['tool'] for c in result['cycles']}, {'claude', 'codex'})
            inputs.assert_called_once_with()

    def test_view_load_waits_for_the_main_refresh(self):
        root = Path(__file__).resolve().parents[1] / 'Tokei' / 'Sources' / 'Tokei'
        main = (root / 'main.swift').read_text()
        panel = (root / 'PanelView.swift').read_text()
        history = (root / 'QuotaHistoryView.swift').read_text()
        repository = (root / 'QuotaDetail.swift').read_text()

        self.assertIn('func loadQuotaDetail()', main)
        self.assertIn('QuotaDetailRepository.shared.load(force: true)', main)
        self.assertIn('onLoad: store.loadQuotaDetail', panel)
        self.assertIn('.onAppear(perform: onLoad)', history)
        self.assertNotIn('.onAppear { detail.load() }', history)
        self.assertIn('private var forcedReloadPending = false', repository)
        self.assertIn('forcedReloadPending = forcedReloadPending || force', repository)
        self.assertIn('if self.forcedReloadPending', repository)


if __name__ == '__main__':
    unittest.main()
