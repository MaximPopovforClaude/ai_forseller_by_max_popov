"""Execute actual HomeTasks callbacks with deferred HTTP; no browser or network."""
import shutil
import os
import subprocess
import unittest
from pathlib import Path


NODE_TEST = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const strip = require('node:module').stripTypeScriptTypes;
if (!strip) { console.log('SKIP: Node lacks stripTypeScriptTypes'); process.exit(77); }
const source = fs.readFileSync(path.join(process.argv[1], 'web/frontend/src/HomeTasks.tsx'), 'utf8');
const clean = text => strip(text.replace(/^import .*\n/gm, '').replace(/^export /gm, ''));
const prefix = source.split('  if (!r) return')[0]
  + ' return {r,msg,load,rebuild,isCurrent};\n}\n';
const cardPrefix = source.slice(source.indexOf('function TaskCard(')).split('  const o = t.outcome;')[0]
  + ' return {fb,mark,busy,open};\n}\n';
function hooks() {
  const states = [], refs = [], effects = [];
  let si = 0, ri = 0, ei = 0;
  return {
    states, effects,
    reset() { si = ri = ei = 0; },
    useState(initial) {
      const i = si++;
      if (!(i in states)) states[i] = initial;
      return [states[i], v => { states[i] = typeof v === 'function' ? v(states[i]) : v; }];
    },
    useRef(initial) { const i = ri++; return refs[i] ||= {current: initial}; },
    useEffect(fn, deps) {
      const i = ei++, old = effects[i];
      if (!old || deps.some((d, n) => d !== old.deps[n])) {
        old?.cleanup?.(); effects[i] = {deps, cleanup: fn()};
      }
    },
    unmount() { effects.forEach(e => e?.cleanup?.()); }
  };
}
const flush = () => new Promise(resolve => setImmediate(resolve));
function fixture() {
  const h = hooks(), gets = [], posts = [], intervals = new Map(), listeners = new Map(), alerts = [];
  let nextTimer = 0;
  const http = {
    get: url => new Promise((resolve, reject) => gets.push({url, resolve, reject})),
    post: (url, body) => new Promise((resolve, reject) => posts.push({url, body, resolve, reject}))
  };
  const window = {setInterval: fn => { intervals.set(++nextTimer, fn); return nextTimer; },
                  clearInterval: id => intervals.delete(id)};
  const document = {visibilityState: 'visible',
    addEventListener: (name, fn) => listeners.set(name, fn),
    removeEventListener: (name, fn) => { if (listeners.get(name) === fn) listeners.delete(name); }};
  const HomeTasks = new Function('useState', 'useRef', 'useEffect', 'http', 'window', 'document',
    clean(prefix) + ';return HomeTasks;')(h.useState, h.useRef, h.useEffect, http, window, document);
  const render = shop => { h.reset(); return HomeTasks({shop}); };
  const card = current => {
    const ch = hooks();
    const TaskCard = new Function('useState', 'http', 'alert', clean(cardPrefix) + ';return TaskCard;')
      (ch.useState, http, message => alerts.push(message));
    const renderCard = () => { ch.reset(); return TaskCard({t: {id: 17}, r: {}, shop: 3,
      showDay: false, onDone: current.load, isCurrent: current.isCurrent}); };
    return {h: ch, render: renderCard};
  };
  return {h, gets, posts, render, card, intervals, listeners, document, alerts};
}
(async () => {
  // A delayed initial GET and an old callback cannot overwrite/request a different shop.
  let f = fixture(), old = f.render(3);
  f.render(8); f.gets[1].resolve({enabled: true, tag: 'shop8'}); await flush();
  f.gets[0].resolve({enabled: true, tag: 'late3'}); await flush();
  assert.equal(f.render(8).r.tag, 'shop8');
  await old.load(); await old.rebuild();
  assert.equal(f.gets.length, 2); assert.equal(f.posts.length, 0);
  // Returning to the same shop does not revive callbacks from its previous visit.
  const current3 = f.render(3);
  await old.load(); assert.equal(f.gets.length, 3); assert.equal(old.isCurrent(), false);
  f.gets[2].resolve({enabled: true, tag: 'new3'}); await flush();
  assert.equal(f.render(3).r.tag, 'new3');
  // Reordered polling/visibility/manual refreshes keep the newest response.
  void current3.load(); const first = f.gets.at(-1);
  void current3.load(); const second = f.gets.at(-1);
  second.resolve({enabled: true, tag: 'latest'}); await flush();
  first.resolve({enabled: true, tag: 'older'}); await flush();
  assert.equal(f.render(3).r.tag, 'latest');
  const before = f.gets.length;
  f.intervals.values().next().value();
  f.document.visibilityState = 'hidden'; f.listeners.get('visibilitychange')();
  f.document.visibilityState = 'visible'; f.listeners.get('visibilitychange')();
  assert.equal(f.gets.length, before + 2);
  assert.ok(f.gets.slice(before).every(g => g.url === '/api/shops/3/ai_tasks'));
  // Unmount invalidates pending work and unregisters both refresh sources.
  void current3.rebuild(); const pendingRebuild = f.posts.at(-1);
  f.h.unmount(); assert.equal(f.intervals.size, 0); assert.equal(f.listeners.size, 0);
  f.gets.at(-1).resolve({enabled: true, tag: 'after-unmount'});
  pendingRebuild.resolve({message: 'after-unmount'}); await flush();
  assert.equal(f.h.states[0].tag, 'latest'); assert.equal(f.h.states[3], '');
  assert.equal(f.gets.length, before + 2);

  // Rebuild success/error from an earlier shop cannot alter its replacement.
  for (const reject of [false, true]) {
    f = fixture(); old = f.render(3); void old.rebuild();
    f.render(8); const count = f.gets.length;
    if (reject) f.posts[0].reject(new Error('old failure'));
    else f.posts[0].resolve({message: 'old success'});
    await flush(); assert.equal(f.h.states[3], ''); assert.equal(f.gets.length, count);
    const now = f.render(8); void now.rebuild();
    f.posts.at(-1).resolve({message: 'queued8'}); await flush();
    assert.equal(f.h.states[3], 'queued8'); assert.equal(f.gets.at(-1).url, '/api/shops/8/ai_tasks');
    f.h.unmount();
  }
  // Feedback/status callbacks must not refresh, alert or set state after a shop switch.
  for (const action of ['fb', 'mark']) for (const reject of [false, true]) {
    f = fixture(); old = f.render(3); const c = f.card(old), callbacks = c.render();
    if (action === 'fb') callbacks.fb(1, 'fixture'); else void callbacks.mark('done');
    assert.equal(f.posts[0].url, '/api/shops/3/ai_tasks/' + (action === 'fb' ? 'feedback' : 'status'));
    assert.equal(f.posts[0].body.id, 17);
    f.render(8); const beforeStates = [...c.h.states], count = f.gets.length;
    if (reject) f.posts[0].reject(new Error('old failure')); else f.posts[0].resolve({});
    await flush(); assert.equal(f.gets.length, count); assert.deepEqual(f.alerts, []);
    assert.deepEqual(c.h.states, beforeStates);
    callbacks.fb(1, 'stale'); await callbacks.mark('done'); assert.equal(f.posts.length, 1);
    f.h.unmount();
  }
  // Current feedback still clears busy, refreshes, and reports genuine request errors.
  f = fixture(); const now = f.render(3), c = f.card(now);
  c.render().fb(1, 'fixture'); assert.equal(c.h.states[2], true);
  f.posts[0].resolve({}); await flush();
  assert.equal(c.h.states[2], false); assert.equal(f.gets.length, 2);
  void c.render().mark('done'); f.posts[1].resolve({}); await flush();
  assert.equal(f.gets.length, 3);
  c.render().fb(-1, 'fixture'); f.posts[2].reject(new Error('current failure')); await flush();
  assert.deepEqual(f.alerts, ['current failure']); assert.equal(c.h.states[2], false);
  f.h.unmount();
  console.log('HomeTasks: stale GETs, revisit, latest response, polling, unmount and mutation isolation OK');
})().catch(e => { console.error(e); process.exitCode = 1; });
"""


class HomeTasksRaceTests(unittest.TestCase):
    def test_api_binds_saved_tasks_to_their_run(self):
        import stometric.web                                      
        from stometric import ai_tasks, api_ai_tasks
        from datetime import date, datetime, timezone
        from unittest.mock import MagicMock, patch
        day = date(2026, 11, 5)
        task = dict.fromkeys(("steps", "vc", "check_spec", "status_by", "status_note", "status_at", "status_who", "outcome"))
        task.update(id=101, run_id=81, day=day, title='Synthetic task', why='Synthetic evidence', tag='stock', certainty='probable',
                    effect_week=None, priority=1, nm_ids=[], status='new', created_at=datetime(2026,11,5,tzinfo=timezone.utc))
        run = dict(id=81, day=day, status='ok', entry_ok=True, data_coverage={}, summary='Synthetic summary',
                   started_at=datetime(2026,11,5,8,50,tzinfo=timezone.utc), finished_at=datetime(2026,11,5,9,tzinfo=timezone.utc))
        c=MagicMock()
        def execute(sql,args):
            if sql.startswith('SELECT t.*'):
                self.assertEqual(args[0],8)
                result=MagicMock();result.fetchall.return_value=[task];return result
            if sql.startswith('SELECT task_id, user_id'):return iter([])
            if sql.startswith('SELECT DISTINCT ON (day)'):
                self.assertIn('(day) id, day',sql);self.assertEqual(args[0],8);return iter([run])
            raise AssertionError(sql)
        c.execute.side_effect=execute
        with patch.object(api_ai_tasks.auth,'shop_role',return_value='viewer'), \
             patch.object(ai_tasks,'is_enabled',return_value=True),patch.object(ai_tasks,'marketplace',return_value='wb'), \
             patch.object(api_ai_tasks,'today_msk',return_value=day),patch('stometric.entry_coverage.report_present',return_value=True):
            out=api_ai_tasks.tasks_get(8,u={'id':77},c=c)
        self.assertEqual(out['runs']['2026-11-05']['id'],81)
        self.assertEqual(out['tasks'][0]['run_id'],81)
        self.assertFalse(out['can_edit']);c.commit.assert_not_called()

    def test_rebuild_completion_and_errors_in_actual_react(self):
        node = shutil.which("node")
        if not node: self.skipTest("Node unavailable")
        root = Path(__file__).resolve().parents[1]
        for mode in ("development", "production"):
            result = subprocess.run([node, str(root / "tools/frontend/home_tasks_status.cjs"), str(root)],
                                    capture_output=True, text=True, timeout=20, env={**os.environ, "NODE_ENV": mode})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_actual_callbacks_ignore_stale_shop_and_keep_current_actions(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node unavailable; run frontend regression on build host")
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([node, "-e", NODE_TEST, str(root)], capture_output=True,
                                text=True, timeout=20)
        if result.returncode == 77:
            self.skipTest(result.stdout.strip())
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)


if __name__ == "__main__":
    unittest.main()
