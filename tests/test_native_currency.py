import unittest
import hashlib
from datetime import datetime, timezone
from unittest import mock
from test_codex_limits import USAGE
from test_deepseek_harness import harness_event


class NativeCurrencyTests(unittest.TestCase):
    def test_mixed_official_and_channel_survive_ledger_ranges_and_dashboard(self):
        ts = int(datetime(2026, 9, 11, 4, tzinfo=timezone.utc).timestamp() * 1000)
        event = harness_event('assistant/message', ts, 1, 1,
                              {'inputTokens': 1_000_000, 'outputTokens': 1_000_000,
                               'cacheReadTokens': 1_000_000}, model='deepseek-v4-flash')
        official = USAGE._deepseek_harness_usage_record(event)
        self.assertEqual(official['cost'], 0)
        self.assertAlmostEqual(official['cost_cny'], 5.02)
        event['data']['message']['source']['provider'] = 'openrouter'
        event['data']['step'] = 2
        with mock.patch.object(USAGE, '_raw_price', return_value={
            'in': 0.1, 'out': 0.2, 'cache_read': 0.01, 'cache_write': 0}):
            channel = USAGE._deepseek_harness_usage_record(event)
        self.assertAlmostEqual(channel['cost'], 0.31)
        self.assertEqual(channel['cost_cny'], 0)
        sources = {}
        for record in (official, channel):
            USAGE._ledger_add_record_source(sources, 'session', record['date'], record)
        day = sources['session'][official['date']]
        bucket = USAGE._empty_token_bucket()
        USAGE._merge_token_day(bucket, day)
        self.assertAlmostEqual(bucket['cost'], 0.31)
        self.assertAlmostEqual(bucket['cost_cny'], 5.02)
        models = USAGE._format_token_models(bucket['models'])
        self.assertEqual(len(models), 1)
        self.assertAlmostEqual(models[0]['cost_cny'], 5.02)
        result = {'deepseek_harness': {'ranges': {'today': {'models': models, 'cost': .31, 'cost_cny': 5.02}}}}
        USAGE._recalc_costs(result)
        self.assertAlmostEqual(models[0]['cost'], .31)
        self.assertAlmostEqual(models[0]['cost_cny'], 5.02)
        cache = {'deepseek_harness': {'a': {'sid': 'session', 'records': [official, channel]}}}
        ledger = {'tools': {'deepseek_harness': {official['date']: day}}}
        with mock.patch.object(USAGE, '_load_ledger', return_value=ledger):
            dashboard = USAGE.build_daily_costs(refresh=False, _cache=cache)
            wrapped = USAGE.build_wrapped(refresh=False, _cache=cache)
        self.assertAlmostEqual(sum(d['cost_cny'] for d in dashboard['daily']), 5.02)
        self.assertAlmostEqual(sum(m.get('cost_cny', 0) for m in dashboard['models']), 5.02)
        self.assertAlmostEqual(wrapped['cost_cny'], 5.02)
        self.assertAlmostEqual(wrapped['total_cost'], .31)

    def test_opencode_requires_explicit_official_provider(self):
        message = {'role': 'assistant', 'modelID': 'deepseek-flash',
                   'time': {'created': int(datetime(2026, 9, 11, 6, tzinfo=timezone.utc).timestamp()*1000)},
                   'tokens': {'input': 1_000_000, 'output': 1_000_000}, 'cost': .75}
        for provider, usd, cny in [('deepseek', 0, 10), ('openrouter', .75, 0), ('', .75, 0)]:
            with self.subTest(provider=provider):
                message['providerID'] = provider
                day = USAGE._opencode_message_day(message)
                self.assertEqual(day['cost'], usd)
                self.assertEqual(day['cost_cny'], cny)
                merged = USAGE._empty_token_day()
                USAGE._merge_live_token_day(merged, day)
                self.assertEqual(merged['cost_cny'], cny)
                self.assertEqual(merged['models']['deepseek-flash']['cost_cny'], cny)

    def test_new_currency_revision_replaces_old_usd_source(self):
        old = {'in': 1_000_000, 'cost': .15, '_cost_version': 4}
        new = {'in': 1_000_000, 'cost': 0, 'cost_cny': 1, '_cost_version': 5}
        ledger = {'v': USAGE._LEDGER_VERSION, 'tools': {'deepseek_harness': {
            '2026-09-11': dict(old, _sources={hashlib.sha256(b's').hexdigest(): old})}}}
        saved = USAGE._LEDGER_CACHE.copy()
        try:
            USAGE._LEDGER_CACHE.update(data=ledger, dirty=False)
            result = USAGE.ledger_reconcile('deepseek_harness', {'2026-09-11': new},
                                            {'s': {'2026-09-11': new}})
            self.assertEqual(result['2026-09-11']['cost'], 0)
            self.assertEqual(result['2026-09-11']['cost_cny'], 1)
        finally:
            USAGE._LEDGER_CACHE.clear()
            USAGE._LEDGER_CACHE.update(saved)

    def test_aggregate_legacy_currency_migration_drops_reconstructed_usd(self):
        old = {'in': 1_000_000, 'cost': .14, '_cost_version': 3,
               'models': {'deepseek-v4-flash': {'in': 1_000_000, 'cost': .14}}}
        new = {'in': 1_000_000, 'cost': 0, 'cost_cny': 1, '_cost_version': 5,
               'models': {'deepseek-v4-flash': {'in': 1_000_000, 'cost_cny': 1}}}
        value = USAGE._ledger_merge_sources(old, {'session': new}, 'deepseek_harness')
        self.assertEqual(value['in'], 1_000_000)
        self.assertEqual(value['cost'], 0)
        self.assertEqual(value['cost_cny'], 1)
        self.assertEqual(value['models']['deepseek-v4-flash'].get('cost', 0), 0)

    def test_opencode_partial_logs_cannot_replace_older_larger_ledger(self):
        day = '2026-09-11'
        old = {'in': 1000, 'cost': 1}
        live = {'in': 400, 'cost': 0, 'cost_cny': .0004, '_cost_version': 2}
        ledger = {'v': USAGE._LEDGER_VERSION, 'tools': {'opencode': {day: old}}}
        with mock.patch.object(USAGE, '_load_ledger', return_value=ledger):
            result = USAGE.ledger_reconcile('opencode', {day: live})
            self.assertEqual(result[day]['in'], 1000)
            self.assertEqual(ledger['tools']['opencode'][day]['cost'], 1)
            complete = dict(live, **{'in': 1000, 'cost_cny': .001})
            result = USAGE.ledger_reconcile('opencode', {day: complete})
            self.assertEqual(result[day]['cost'], 0)
            self.assertEqual(result[day]['cost_cny'], .001)

    def test_partial_harness_migration_keeps_unattributed_history(self):
        old = {'in': 1000, 'cost': 1}
        new = {'in': 400, 'cost': 0, 'cost_cny': .4, '_cost_version': 5}
        result = USAGE._ledger_merge_sources(old, {'s': new}, 'deepseek_harness')
        self.assertEqual(result['in'], 1000)
        self.assertEqual(result['cost'], 1)
        self.assertEqual(result['_sources']['legacy']['in'], 600)
        # Fully migrated orphan currency is cleaned even after an earlier save.
        orphan = {'in': 1000, 'cost': 1, 'cost_cny': 1,
                  '_sources': {'legacy': {'in': 0, 'cost': 1},
                               's': {'in': 1000, 'cost_cny': 1}}}
        full = {'in': 1000, 'cost_cny': 1}
        repaired = USAGE._ledger_merge_sources(orphan, {'s': full}, 'deepseek_harness')
        self.assertEqual(repaired['cost'], 0)
        self.assertEqual(repaired['cost_cny'], 1)
        self.assertEqual(repaired, USAGE._ledger_merge_sources(repaired, {'s': full}, 'deepseek_harness'))

    def test_cny_amount_is_not_ledger_token_volume(self):
        self.assertEqual(USAGE._ledger_day_total({'in': 400, 'cost': 1, 'cost_cny': 1000}), 400)

    def test_opencode_flush_keeps_concurrently_saved_history(self):
        import tempfile
        import json
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'ledger.json'
            path.write_text(json.dumps({'v': USAGE._LEDGER_VERSION, 'tools': {
                'opencode': {'2026-09-11': {'in': 1000, 'cost': 1}}}}))
            USAGE._LEDGER_CACHE.update(data={'v': USAGE._LEDGER_VERSION, 'tools': {
                'opencode': {'2026-09-11': {'in': 400, 'cost_cny': .4, '_cost_version': 2}}}}, dirty=True)
            with mock.patch.object(USAGE, '_LEDGER_FILE', str(path)):
                USAGE.ledger_flush()
            day = json.loads(path.read_text())['tools']['opencode']['2026-09-11']
            self.assertEqual(day['in'], 1000)
            self.assertEqual(day['cost'], 1)
