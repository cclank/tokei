import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from test_codex_limits import USAGE as U
from test_qwencode import request_record, summary_record


class TokenAccountingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.day = datetime.now().astimezone().date().isoformat()
        for name, value in (
            ('CODEX_DIR', str(self.root / 'sessions')),
            ('CODEX_ARCHIVED_DIR', str(self.root / 'archive')),
            ('_SCAN_CACHE_FILE', str(self.root / 'cache.json')),
            ('_LEDGER_FILE', str(self.root / 'ledger.json')),
        ):
            p = mock.patch.object(U, name, value)
            p.start()
            self.addCleanup(p.stop)
        for name, value in (('fetch_codex_live_limits', None), ('_codex_is_custom_provider', True)):
            p = mock.patch.object(U, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.dict('os.environ', {'TOKEI_CODEX_DIR': '', 'TOKEI_CODEX_ARCHIVED_DIR': ''})
        p.start()
        self.addCleanup(p.stop)
        Path(U.CODEX_DIR).mkdir()

    def row(self, kind, payload, second=0):
        return {'timestamp': f'{self.day}T08:00:{second:02d}+08:00', 'type': kind, 'payload': payload}

    def usage(self, inp=100, out=20, reason=10):
        return dict(input_tokens=inp, cached_input_tokens=0, output_tokens=out,
                    reasoning_output_tokens=reason, total_tokens=inp + out)

    def response(self, rid, usage, total=None, owner='s', second=0):
        return self.row('token_usage_record', {'thread_id': owner, 'response_id': rid,
                        'usage': usage, 'thread_token_usage': total or usage}, second)

    def snapshot(self, usage, total=None, second=0):
        return self.row('event_msg', {'type': 'token_count', 'info': {
            'last_token_usage': usage, 'total_token_usage': total or usage}}, second)

    def write(self, rows, name='s', parent=None):
        meta = {'id': name, 'cwd': '/fixture'}
        if parent:
            meta['forked_from_id'] = parent
        path = Path(U.CODEX_DIR) / f'rollout-{name}.jsonl'
        path.write_text('\n'.join(json.dumps(r) for r in [self.row('session_meta', meta),
                        self.row('turn_context', {'model': 'gpt-5.5'}), *rows]) + '\n')
        return path

    def scan(self, cache):
        return U.scan_codex(U.range_bounds(), cache)['ranges']['all']

    def test_resumed_session_segments_with_same_thread_are_both_counted(self):
        self.write([self.response('old-1', self.usage()),
                    self.response('old-2', self.usage(50, 5, 0))])
        segment = self.write([self.response('new-1', self.usage(70, 7, 0))], name='segment')
        text = segment.read_text().replace('"id": "segment"', '"id": "s"')
        segment.write_text(text)
        result = self.scan({})
        self.assertEqual(result['in'] + result['out'], 252)

    def test_resumed_segments_overlap_and_incremental_append_do_not_double_count(self):
        old = self.write([self.response('r1', self.usage()),
                          self.response('r2', self.usage(50, 5, 0))])
        segment = self.write([self.response('r2', self.usage(50, 5, 0)),
                              self.response('r3', self.usage(70, 7, 0))], name='segment')
        segment.write_text(segment.read_text().replace('"id": "segment"', '"id": "s"'))
        cache = {}
        self.assertEqual(self.scan(cache)['in'] + self.scan(cache)['out'], 252)
        with segment.open('a') as f:
            f.write(json.dumps(self.response('r4', self.usage(30, 3, 0))) + '\n')
        warm = self.scan(cache)
        self.assertEqual(warm['in'] + warm['out'], 285)
        U._LEDGER_CACHE.update(data=None, dirty=False)
        cold = self.scan({})
        self.assertEqual(warm, cold)

    def test_segment_becoming_superset_rebuilds_warm_deduplication(self):
        self.write([self.response('r1', self.usage()),
                    self.response('r2', self.usage(50, 5, 0))])
        segment = self.write([self.response('r2', self.usage(50, 5, 0)),
                              self.response('r3', self.usage(70, 7, 0))], name='segment')
        segment.write_text(segment.read_text().replace('"id": "segment"', '"id": "s"'))
        cache = {}
        self.scan(cache)
        with segment.open('a') as f:
            for row in [self.response('r1', self.usage()),
                        self.response('r4', self.usage(30, 3, 0))]:
                f.write(json.dumps(row) + '\n')
        warm = self.scan(cache)
        self.assertEqual(warm['in'] + warm['out'], 285)
        U._LEDGER_CACHE.update(data=None, dirty=False)
        self.assertEqual(warm, self.scan({}))

    def test_legacy_first_overlap_keeps_response_identity_across_scans(self):
        for incremental in (False, True):
            with self.subTest(incremental=incremental):
                U._LEDGER_CACHE.update(data=None, dirty=False)
                path = self.write([self.snapshot(self.usage())])
                cache = {}
                if incremental:
                    self.scan(cache)
                with path.open('a') as f:
                    for row in [self.response('r1', self.usage()),
                                self.response('r2', self.usage(50, 5, 0))]:
                        f.write(json.dumps(row) + '\n')
                segment = self.write([self.response('r1', self.usage()),
                                      self.response('r3', self.usage(70, 7, 0))], name='segment')
                segment.write_text(segment.read_text().replace('"id": "segment"', '"id": "s"'))
                value = self.scan(cache)
                self.assertEqual(value['in'] + value['out'], 252)
                segment.unlink()

    def test_response_only_and_dual_written_compaction(self):
        regular = self.usage()
        compact = self.usage(254769, 1249, 0)
        next_usage = self.usage(50, 5, 0)
        self.write([self.response('r1', regular), self.snapshot(regular),
                    self.response('compact', compact, self.usage(254869, 1269, 10), second=1),
                    self.snapshot(self.usage(0, 0, 0), regular, second=1),
                    self.response('r2', next_usage, self.usage(254919, 1274, 10), second=2),
                    self.snapshot(next_usage, self.usage(150, 25, 10), second=2)])
        result = self.scan({})
        self.assertEqual(result['in'] + result['out'], 120 + 256018 + 55)

    def test_append_between_response_and_mirror_equals_cold_scan(self):
        path = self.write([self.response('r1', self.usage())])
        cache = {}
        self.assertEqual(self.scan(cache)['in'], 100)
        with path.open('a') as f:
            for r in [self.snapshot(self.usage()), self.response('r1', self.usage()),
                      self.response('r2', self.usage(50, 5, 0), self.usage(150, 25, 10), second=1)]:
                f.write(json.dumps(r) + '\n')
        warm = self.scan(cache)
        U._LEDGER_CACHE.update(data=None, dirty=False)
        cold = self.scan({})
        self.assertEqual(warm, cold)
        self.assertEqual(warm['in'] + warm['out'], 175)

    def test_owned_response_is_not_dropped_as_replay_burst(self):
        self.write([self.response(f'r{i}', self.usage(), self.usage(100*(i+1), 20*(i+1)))
                    for i in range(6)])
        self.assertEqual(self.scan({})['in'], 600)

    def test_interleaved_responses_and_legacy_first_mirrors(self):
        a, b, total = self.usage(), self.usage(50, 5, 0), self.usage(150, 25, 10)
        self.write([self.response('r1', a), self.response('r2', b, total),
                    self.snapshot(a), self.snapshot(b, total),
                    self.snapshot(a, self.usage(250, 45, 20), second=1),
                    self.response('r3', a, self.usage(250, 45, 20), second=1)])
        result = self.scan({})
        self.assertEqual(result['in'] + result['out'], 295)

    def test_legacy_only_fork_prefix_matches_new_parent_record(self):
        self.write([self.response('r1', self.usage()), self.snapshot(self.usage())])
        self.write([self.snapshot(self.usage()),
                    self.snapshot(self.usage(50, 5, 0), self.usage(150, 25), second=1)], 'child', 's')
        result = self.scan({})
        self.assertEqual(result['in'] + result['out'], 175)

    def test_fork_replayed_response_and_legacy_mirror_not_counted_twice(self):
        rows = [self.response('r1', self.usage()), self.snapshot(self.usage())]
        self.write(rows)
        self.write([*rows, self.response('r2', self.usage(50, 5, 0),
                                       self.usage(150, 25), owner='child', second=1)], 'child', 's')
        result = self.scan({})
        self.assertEqual(result['in'] + result['out'], 175)

    def test_codex_totals_agree_in_dashboard_wrapped_and_legacy_ledger(self):
        days = {}
        U._codex_add_event(days, [f'{self.day}T08:00:00+08:00', self.day,
                                 100, 60, 20, 10, 100, 60, 20, 10, 0, 'gpt-5.5'])
        cache = {'codex': {'s': {'days': days}}}
        U._LEDGER_CACHE['data'] = {'v': U._LEDGER_VERSION, 'tools': {'codex': days}}
        daily = U.build_daily_costs(refresh=False, _cache=cache)
        wrapped = U.build_wrapped(refresh=False, _cache=cache)
        self.assertEqual(daily['daily'][0]['tokens'], 120)
        self.assertEqual(daily['models'][0]['tokens'], 120)
        self.assertEqual(wrapped['total_tokens'], 120)
        self.assertEqual(sum(wrapped['hours']), 120)
        self.assertEqual(wrapped['top_model']['tokens'], 120)

    def test_deleted_session_then_new_session_survives_flush_and_restart(self):
        old = self.write([self.snapshot(self.usage(100, 0, 0))])
        cache = {}
        self.assertEqual(self.scan(cache)['in'], 100)
        U.ledger_flush()
        old.unlink()
        self.write([self.snapshot(self.usage(60, 0, 0))], 'new')
        self.assertEqual(self.scan(cache)['in'], 160)
        U.ledger_flush()
        U._LEDGER_CACHE.update(data=None, dirty=False)
        self.assertEqual(self.scan({})['in'], 160)
        daily = U.build_daily_costs(refresh=False, _cache=cache)
        wrapped = U.build_wrapped(refresh=False, _cache=cache)
        self.assertEqual(sum(v['tokens'] for v in daily['daily']), 160)
        self.assertEqual(sum(v['tokens'] for v in daily['models']), 160)
        self.assertEqual(wrapped['total_tokens'], 160)
        self.assertEqual(sum(wrapped['hours']), 160)

    def test_source_ledger_migrates_without_adding_existing_history_twice(self):
        U._LEDGER_CACHE['data'] = {'v': 1, 'tools': {'codex': {self.day: {'in': 100, 'out': 0}}}}
        a = {'a': {self.day: {'in': 60, 'out': 0}}}
        self.assertEqual(U.ledger_reconcile('codex', {self.day: {'in': 60}}, a)[self.day]['in'], 100)
        U.ledger_flush()
        U._LEDGER_CACHE.update(data=None, dirty=False)
        b = {'b': {self.day: {'in': 20, 'out': 0}}}
        self.assertEqual(U.ledger_reconcile('codex', {self.day: {'in': 20}}, b)[self.day]['in'], 120)
        self.assertEqual(U.ledger_reconcile('codex', {self.day: {'in': 60}}, a)[self.day]['in'], 120)

    def test_concurrent_source_saves_union_sources_and_keep_larger_known_source(self):
        import copy
        def save(identity, amount):
            U.ledger_reconcile('codex', {self.day: {'in': amount}},
                               {identity: {self.day: {'in': amount}}})
        save('a', 100)
        first = copy.deepcopy(U._LEDGER_CACHE['data'])
        U._LEDGER_CACHE.update(data={'v': 1, 'tools': {}}, dirty=False)
        save('b', 60)
        U.ledger_flush()
        U._LEDGER_CACHE.update(data=first, dirty=True)
        U.ledger_flush()
        self.assertEqual(U._load_ledger()['tools']['codex'][self.day]['in'], 160)
        save('a', 120)
        U.ledger_flush()
        self.assertEqual(U._load_ledger()['tools']['codex'][self.day]['in'], 180)

    def test_source_accounting_upgrade_can_correct_old_overcount(self):
        def reconcile(amount, version):
            return U.ledger_reconcile('codex', {self.day: {'in': amount}},
                {'a': {self.day: {'in': amount, '_accounting_version': version}}})[self.day]['in']
        self.assertEqual(reconcile(200, 1), 200)
        U.ledger_flush()
        self.assertEqual(reconcile(100, 2), 100)
        U.ledger_flush()
        U._LEDGER_CACHE.update(data=None, dirty=False)
        self.assertEqual(U._load_ledger()['tools']['codex'][self.day]['in'], 100)

    def test_legacy_remainder_does_not_duplicate_models_or_invent_hours(self):
        old = {'in': 100, 'out': 0, 'cached': 0, 'reason': 0,
               'models': {'old-model': {'in': 100}}, 'hours': [110] + [0]*23}
        live = {'in': 60, 'out': 0, 'cached': 0, 'reason': 0,
                'models': {'new-model': {'in': 60}}, 'hours': [60] + [0]*23}
        U._LEDGER_CACHE['data'] = {'v': 1, 'tools': {'codex': {self.day: old}}}
        day = U.ledger_reconcile('codex', {self.day: live}, {'s': {self.day: live}})[self.day]
        self.assertEqual(day['in'], 100)
        self.assertEqual(sum(v.get('in', 0) for v in day['models'].values()), 100)
        self.assertEqual(day['models']['unknown']['in'], 40)
        self.assertEqual(sum(day['hours']), 60)
        U.ledger_flush()
        U._LEDGER_CACHE.update(data=None, dirty=False)
        saved = U._load_ledger()['tools']['codex'][self.day]
        self.assertEqual(saved['models'], day['models'])
        self.assertEqual(saved['hours'], day['hours'])

    def test_all_deleted_logs_use_ledger(self):
        old = self.write([self.snapshot(self.usage(100, 0, 0))])
        cache = {}
        self.scan(cache)
        U.ledger_flush()
        old.unlink()
        self.assertEqual(self.scan(cache)['in'], 100)

    def test_qwen_partial_request_history_is_filled_from_summary(self):
        request = self.root / 'requests.jsonl'
        summary = self.root / 'summary.jsonl'
        request.write_text(json.dumps(request_record('r2', 's', 60)) + '\n')
        summary.write_text(json.dumps(summary_record('s', 160)) + '\n')
        entries = U._qwen_entries([str(request)], str(summary))
        self.assertEqual(sum(U.token_total(e) for e in entries), 160)
        self.assertEqual(sum(sum(U.token_total(v) for v in e['models'].values()) for e in entries), 160)
        request.write_text('\n'.join(json.dumps(request_record(rid, 's', n))
                                      for rid, n in [('r1', 100), ('r2', 60), ('r3', 20)]) + '\n')
        self.assertEqual(sum(U.token_total(e) for e in U._qwen_entries([str(request)], str(summary))), 180)
