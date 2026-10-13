"""Startup ordering, preview freshness and the real collector's network-free first pass."""
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests.test_cross_platform_smoke import _claude_records, _codex_lines

ROOT = Path(__file__).resolve().parents[1]


class StartupCollectorTests(unittest.TestCase):
    def test_local_first_pass_keeps_usage_and_never_calls_quota_providers(self):
        with tempfile.TemporaryDirectory(prefix="tokei-startup-") as tmp:
            home = Path(tmp)
            now = datetime.now().astimezone()
            claude = home / ".claude/projects/demo/session.jsonl"
            codex = home / ".codex/sessions/2026/10/13/rollout-demo.jsonl"
            claude.parent.mkdir(parents=True)
            codex.parent.mkdir(parents=True)
            claude.write_text("\n".join(json.dumps(r) for r in _claude_records(now)), encoding="utf-8")
            codex.write_text("\n".join(_codex_lines(now)) + "\n", encoding="utf-8")
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(("TOKEI_", "CODEX_", "CLAUDE_", "GROK_"))}
            env.update(HOME=tmp, USERPROFILE=tmp, APPDATA=str(home / "roaming"), LOCALAPPDATA=str(home / "local"))
            script = r'''
import importlib.util, sys, json, io, contextlib
from unittest.mock import patch
from contextlib import ExitStack
spec = importlib.util.spec_from_file_location('startup_usage', sys.argv[1])
u = importlib.util.module_from_spec(spec); sys.modules[spec.name] = u; spec.loader.exec_module(u)
names = ['fetch_codex_live_limits', 'fetch_codex_reset_cards', 'scan_claude_plan',
         'scan_grok_quota', 'scan_qwenwork_quota', 'fetch_kimi_live_limits', 'scan_provider_quotas']
with ExitStack() as stack:
    forbidden = [stack.enter_context(patch.object(u, name, side_effect=AssertionError(name))) for name in names]
    sys.argv = ['usage.30s.py', '--json', '--local-only', '--no-sync-snapshot']
    out = io.StringIO()
    with contextlib.redirect_stdout(out): u.main_json()
    data = json.loads(out.getvalue())
    assert data['claude']['ranges']['today']['in'] == 2000, data.get('_errors')
    assert data['codex']['ranges']['today']['cached'] == 7000, data.get('_errors')
    assert data['codex']['ranges']['today']['out'] == 900, data.get('_errors')
    assert data['claude']['q5'] is None
    for denied in forbidden: denied.assert_not_called()
print('local usage retained; all seven quota entry points untouched')
'''
            result = subprocess.run([sys.executable, "-c", script, str(ROOT / "usage.30s.py")],
                                    env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class StartupFrontendTests(unittest.TestCase):
    def test_preview_and_collection_ordering(self):
        node = shutil.which("node")
        compiler = ROOT / "windows/node_modules/typescript/bin/tsc"
        if not node or not compiler.is_file():
            self.skipTest("Windows frontend dependencies are not installed")
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([node, str(compiler), "--ignoreConfig", "--module", "commonjs",
                                     "--target", "ES2020", "--skipLibCheck", "--outDir", tmp,
                                     "src/lib/usagePreview.ts"], cwd=ROOT / "windows", capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            script = r'''
const assert = require('node:assert/strict');
const {encodeUsagePreview, decodeUsagePreview, initialUsage} = require(process.argv[1]);
const deferred = () => { let resolve, reject; const promise = new Promise((a,b) => {resolve=a;reject=b}); return {promise,resolve,reject}; };
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const now = new Date(2026, 9, 13, 12, 0, 0).getTime();
const usage = {claude: {ranges: {today: {in: 123, out: 456}}, q5: 90, account: 'private'},
 codex: {ranges: {today: {in: 200}}, p5: 88, reset_cards: {count: 3}},
 grok_bot: {ranges: {today: {calls: 2}}, quota: {account: 'private', windows: [90]}},
 cursor: {account: 'private', available: true}, _errors: {secret: 'private'}, _sync: {devices: ['private']}};
const text = encodeUsagePreview(usage, now - 1000);
const cached = decodeUsagePreview(text, now);
assert.equal(cached.updatedAt, now - 1000);
assert.equal(cached.usage.claude.ranges.today.in, 123);
assert.equal(cached.usage.claude.q5, undefined);
assert.equal(cached.usage.codex.reset_cards, undefined);
assert.equal(cached.usage.grok_bot.quota, undefined);
assert.equal(cached.usage.cursor, undefined);
assert.equal(text.includes('private'), false);
for (const bad of ['{', JSON.stringify({version: 99}), encodeUsagePreview(usage, now+1000),
 encodeUsagePreview(usage, new Date(2026,9,12,23,59).getTime()), 'x'.repeat(2097153)])
 assert.equal(decodeUsagePreview(bad, now), null);
(async () => {
 const ready = deferred(), full = deferred(); const calls=[], previews=[];
 const cold = initialUsage(ready.promise, async()=>null, async args=>{
  calls.push(args); return args.includes('--local-only') ? usage : full.promise;
 }, (data, source)=>previews.push({data,source}));
 await tick(); assert.equal(calls.length,0); // No collection before the opt-in configuration is ready.
 ready.resolve(); await tick();
 assert.equal(calls.length,2); assert.equal(previews[0].source,'local');
 let completed=false; cold.then(()=>completed=true); await tick(); assert.equal(completed,false);
 full.resolve(usage); assert.equal(await cold,usage);
 const warmCalls=[], warmPreviews=[];
 await initialUsage(Promise.resolve(),async()=>cached,async args=>{warmCalls.push(args);return usage},
  (data,source)=>warmPreviews.push({data,source}));
 assert.equal(warmCalls.length,1); assert.equal(warmPreviews[0].source,'cache');
 const late=deferred(), latePreviews=[];
 await initialUsage(Promise.resolve(),()=>late.promise,async()=>usage,(data,source)=>latePreviews.push(source));
 late.resolve(cached); await tick(); assert.deepEqual(latePreviews,['local']);
 const denied=Promise.reject(new Error('configuration failed')); const forbidden=[];
 await assert.rejects(initialUsage(denied,async()=>null,async()=>{forbidden.push(1);return usage},()=>{}));
 assert.equal(forbidden.length,0);
 const fallback=[];
 assert.equal(await initialUsage(Promise.resolve(),async()=>null,async args=>{
  fallback.push(args); if(args.includes('--local-only'))throw new Error('preview failed');return usage;
 },()=>{}), usage); assert.equal(fallback.length,2);
 console.log('cache filtering, midnight expiry, privacy gate, local-first, warm start and late-read race passed');
})().catch(err=>{console.error(err);process.exitCode=1});
'''
            result = subprocess.run([node, "-e", script, str(Path(tmp) / "usagePreview.js")],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


    def test_language_tables_are_loaded_in_each_window_after_a_shared_preference_change(self):
        node = shutil.which("node")
        compiler = ROOT / "windows/node_modules/typescript/bin/tsc"
        if not node or not compiler.is_file():
            self.skipTest("Windows frontend dependencies are not installed")
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([node, str(compiler), "--ignoreConfig", "--module", "commonjs",
                                     "--target", "ES2020", "--skipLibCheck", "--outDir", tmp,
                                     "src/lib/i18n.ts", "src/vite-env.d.ts"],
                                    cwd=ROOT / "windows", capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            script = r"""
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const assert = require('node:assert/strict');
const folder = process.argv[1], storage = new Map();
const tick = () => new Promise(resolve => setTimeout(resolve, 20));
function realm() {
 const handlers=[], cache=new Map(), reads=[];
 const context = vm.createContext({console, navigator:{languages:['zh'],language:'zh'},
  localStorage:{getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,v)},
  window:{addEventListener:(name,fn)=>{if(name==='storage')handlers.push(fn)}} });
 const load = (name) => {
  if (name === 'react') return {};
  if (name.includes('.lproj/')) {
   const lang=name.match(/(en|fr|ja|ko)\.lproj/)[1]; reads.push(lang);
   return {__esModule:true,default:`"主页" = "${{en:'Home',ja:'ホーム',fr:'Accueil',ko:'홈'}[lang]}";`};
  }
  const file=path.join(folder,name.replace('./','')+'.js');
  if(cache.has(file)) return cache.get(file);
  const exports={}; cache.set(file,exports);
  vm.runInContext('(function(exports, require){'+fs.readFileSync(file,'utf8')+'})',context)(exports,load);
  return exports;
 };
 return {i18n:load('./i18n'),handlers,reads};
}
(async()=>{
 const main=realm(), follower=realm();
 await main.i18n.prepareLanguage(); await follower.i18n.prepareLanguage();
 assert.equal(main.reads.length,0);assert.equal(follower.reads.length,0);
 main.i18n.setLanguage('ja');await tick();
 assert.equal(main.i18n.L('主页'),'ホーム');
 for(const handler of follower.handlers)handler({key:'appLanguage'});
 await tick();
 assert.equal(follower.i18n.L('主页'),'ホーム');
 assert.deepEqual([...follower.reads].sort(),['en','ja']);
 await Promise.all([follower.i18n.prepareLanguage(),follower.i18n.prepareLanguage()]);
 assert.equal(follower.reads.length,2); // No duplicate module reads.
 main.i18n.setLanguage('fr'); await tick();
 for(const handler of follower.handlers)handler({key:'appLanguage'});
 await tick();assert.equal(follower.i18n.L('主页'),'Accueil');
 assert.equal(follower.reads.includes('ko'),false);
 console.log('language loading and cross-window preference synchronization passed');
})().catch(err=>{console.error(err);process.exitCode=1});
"""
            result = subprocess.run([node, "-e", script, tmp], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
