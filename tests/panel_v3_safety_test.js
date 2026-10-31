// Panel v3 robustness and CSP (task 5): a fuzz test and a static webview check, no Chrome needed for the string part (the DOM part uses it when it is installed).
//  1. FUZZ: html(data) is fed malformed, partial and huge data (nulls, wrong types, 10k-character names, bidi and control characters, missing fields, unknown kinds / states / verdicts, hostile
//     markup in every string field). It must never throw and never produce markup the author did not write: an HTML tokenizer reads the output; the set of tags and attribute names must stay inside
//     what a benign render produces, no on* attribute, no javascript: / data: URL, exactly one <script> and one <style>, and a hostile marker never appears as raw markup.
//  2. DATA CLEANERS: data.js collect() output for hostile files (see tests/data_flow_test.js) is covered there; here the cleaners of reports.js / setup.js / ask.js get hostile input too.
//  3. CSP / WEBVIEW (static): the generated page carries the CSP meta (default-src 'none', style and script only with the nonce), every <script> and <style> has the nonce, there is no inline
//     handler (onclick= ...), no style= attribute, no external URL (http://, https://, //host, @import, url(...)) in markup, style or script, no eval / Function / document.write / innerHTML of data,
//     and the extension builds the nonce per render with crypto.randomBytes.
//  4. EXPORT: tests/fixtures/panel-v3 and docs/summary stay out of the public export (hard-never list and the exporter's own default list).
// Run: node tests/panel_v3_safety_test.js
require('./shipmiracle_isolation').apply();
const fs = require('fs'), path = require('path');
const D = require('./panel_cdp'), F = require('./panel_v3_fixtures'), F3 = require('./panel_v3_tab_fixtures');
const { html } = require('../vscode-ext/shipmiracle-panel/panel.js');
const REPORTS = require('../vscode-ext/shipmiracle-panel/reports.js'), SETUP = require('../vscode-ext/shipmiracle-panel/setup.js'), ASK = require('../vscode-ext/shipmiracle-panel/ask.js');
const ROOT = path.join(__dirname, '..'), EXT = path.join(ROOT, 'vscode-ext', 'shipmiracle-panel');
const C = D.checker(), check = C.check;

// ---------------- a small HTML tokenizer (quote aware): -> { tags: Set, attrs: Set, scripts, styles, urls: [], handlers: [] } ----------------
function scan(src) {
  const out = { tags: new Set(), attrs: new Set(), scripts: 0, styles: 0, bad: [], text: '' };
  let i = 0; const n = src.length;
  while (i < n) {
    const lt = src.indexOf('<', i); if (lt < 0) { out.text += src.slice(i); break; }
    out.text += src.slice(i, lt);
    if (src.startsWith('<!--', lt)) { const e = src.indexOf('-->', lt + 4); i = e < 0 ? n : e + 3; continue; }
    if (src.startsWith('<!', lt)) { const e = src.indexOf('>', lt); i = e < 0 ? n : e + 1; continue; }
    const m = /^<(\/?)([A-Za-z][A-Za-z0-9-]*)/.exec(src.slice(lt, lt + 40));
    if (!m) { out.text += '<'; i = lt + 1; continue; }
    const name = m[2].toLowerCase(); let j = lt + m[0].length; out.tags.add(m[1] ? '/' + name : name);
    while (j < n) {                                                  // attributes
      while (j < n && /[\s/]/.test(src[j])) j++;
      if (src[j] === '>') { j++; break; }
      let k = j; while (k < n && !/[\s=/>]/.test(src[k])) k++;
      const an = src.slice(j, k).toLowerCase(); j = k; if (an) out.attrs.add(an);
      while (j < n && /\s/.test(src[j])) j++;
      let val = '';
      if (src[j] === '=') { j++; while (j < n && /\s/.test(src[j])) j++; if (src[j] === '"' || src[j] === "'") { const q = src[j]; const e = src.indexOf(q, j + 1); val = src.slice(j + 1, e < 0 ? n : e); j = e < 0 ? n : e + 1; } else { k = j; while (k < n && !/[\s>]/.test(src[k])) k++; val = src.slice(j, k); j = k; } }
      if (/^on/.test(an)) out.bad.push('handler ' + an);
      if (/^(href|src|srcdoc|formaction|action|xlink:href|poster)$/.test(an)) out.bad.push('url attribute ' + an + '=' + val.slice(0, 30));
      if (/^(href|src|srcdoc|formaction|action|xlink:href|poster)$/.test(an) && /^\s*(javascript|data|vbscript):/i.test(val)) out.bad.push('script url in ' + an);
    }
    i = j;
    if (!m[1] && (name === 'script' || name === 'style')) {          // raw text element: skip to its end tag
      if (name === 'script') out.scripts++; else out.styles++;
      const e = src.toLowerCase().indexOf('</' + name, i); i = e < 0 ? n : e;
    }
  }
  return out;
}

// ---------------- the data pool ----------------
const ASKP = (o = {}) => F.mk('ask', 'notes', { dir: '/x/ask', ask: { inbox: true, questions_today: 3, limit: 20, notes: 2, last: { title: 'What is a monad?', path: 'docs/notes/2026-10-21-what-is-a-monad.md', ts: 1 }, ...o } });
const idea = { id: 'F1', text: 'an idea', tags: ['ui'], date: '2026-10-20', verdict: 'BUILD NOW' };
const POOL = () => [...F.STATES.map(s => s.p), ...F.TYPES.map(t => t.p), F.EXTRA.queued, F.EXTRA.fast, F.EXTRA.arabic, F.EXTRA.held, ASKP(),
  F.mk('idea-app', 'software', { ideas: { open: [idea, { ...idea, id: 'F2', verdict: 'SPLIT OUT' }], evaluated: [], done: 1, dropped: 0 }, ci: { state: 'passing', url: '' }, agents: [{ id: 'a1', type: 'builder-frontend', model: 'sonnet', mins: 3, stalled: true, quiet: 700 }] })];
const BASE = (projects = POOL()) => ({ projects, reports: F3.REPORTS, setup: F3.SETUP(), health: F3.HEALTH(), plan: { meters: [{ id: 'week', label: 'Week', pct: 12.3, lvl: 0, resets: null }, { id: 'five', label: 'Five', pct: 99, lvl: 3, resets: Date.now() + 5000 }] },
  guard: { on: true, running: true, hold: false, battery: 80, lpm: false, away: 0 }, levelSwitch: { ok: true, why: '' }, remote: { state: 'off' }, ask: null, modelReset: null, creating: null, pnotice: '', ledger: { fresh: true } });

// ---------------- a seeded random source ----------------
let seed = +(process.env.SHIPMIRACLE_FUZZ_SEED || 20261021); const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; }; const pick = a => a[Math.floor(rnd() * a.length)];
const HOST = ['<script>ZZ()</script>', '"><img src=x onerror=ZZ()>', "' onfocus='ZZ()' x='", '</textarea><script>ZZ()</script>', '</script><script>ZZ()</script>', '</style><script>ZZ()</script>', '<svg onload=ZZ()>', '<!--', '-->', '&lt;b&gt;', '&#x3c;script&#x3e;',
  '‮⁦bidi⁩', '\u0000\u001b[31mctl\u007f\u0085', '  ', 'a'.repeat(10000), 'ا'.repeat(3000), '${ZZ()}', '`;ZZ();`', '{{7*7}}', 'javascript:ZZ()', 'data:text/html,<script>ZZ()</script>', '"', "'", '\\', '\\u003cscript\\u003e', '<a href="javascript:ZZ()">x</a>', '', ' ', '😀'.repeat(500), '\ud800', '%3Cscript%3E'];
const WEIRD = [null, undefined, 0, -1, 1e308, NaN, Infinity, true, false, [], {}, [null], [[]], { x: 1 }, '', 'x', 12345678901234567890, 'unknown-kind', '__proto__', 'constructor', 'toString', -0];
function leaves(o, path = [], out = []) { if (o && typeof o === 'object') for (const k of Object.keys(o)) leaves(o[k], [...path, k], out); else out.push(path); return out; }
function clone(o) { return o === undefined ? undefined : JSON.parse(JSON.stringify(o)); }
function setAt(o, p, v) { let c = o; for (let i = 0; i < p.length - 1; i++) { if (c[p[i]] === null || typeof c[p[i]] !== 'object') return; c = c[p[i]]; } if (v === undefined) delete c[p[p.length - 1]]; else c[p[p.length - 1]] = v; }
function mutate(data) {
  const d = clone(data), ls = leaves(d); const n = 1 + Math.floor(rnd() * 4);
  for (let k = 0; k < n; k++) { const p = pick(ls); const r = rnd(); setAt(d, p, r < 0.5 ? pick(HOST) : r < 0.85 ? pick(WEIRD) : { [pick(['__proto__', 'constructor', 'name'])]: pick(HOST) }); }
  if (rnd() < 0.15) { const keys = Object.keys(d); delete d[pick(keys)]; }                                       // a whole top-level field missing
  if (rnd() < 0.1 && Array.isArray(d.projects) && d.projects.length) { const p = pick(d.projects); if (p && typeof p === 'object') delete p[pick(Object.keys(p))]; }
  return d;
}

// ============ 1. FUZZ ============
const benign = html(BASE(), { nonce: 'N0NCE', csp: '' }), sb = scan(benign);
const BASE_TAGS = new Set([...sb.tags]), BASE_ATTRS = new Set([...sb.attrs]);
// widen the baseline with every benign variant the fixtures offer (all themes of data: ask project, held, limits, hard stop, ...): the union is what the author wrote
for (const extra of [{ reports: { items: [], status: 'bad' } }, { reports: { items: [], status: 'missing' } }, { setup: null }, { setup: { error: true, rows: [] } }, { health: null }, { projects: [] }, { plan: { meters: [] } }, { rview: { id: 'x', state: 'ok', text: 'Verdict: PASS\nNot verified: none\n', item: F3.ITEMS[0] } }, { creating: { name: 'new-one', ts: 1 } }, { pnotice: 'created' }, { guard: { on: false } }, { guard: { on: true, away: 2, hold: true, reason: 'x', battery: 10, lpm: true, running: false } }, { guard: { on: true, away: 1 } }]) {
  try { const s = scan(html({ ...BASE(), ...extra }, { nonce: 'N0NCE' })); s.tags.forEach(t => BASE_TAGS.add(t)); s.attrs.forEach(a => BASE_ATTRS.add(a)); } catch (e) { /* a variant the panel does not render */ }
}
// every attribute name the author wrote in a template of panel.js is allowed too (a state a fixture does not reach); a name an attacker injects is not in that source (the CSP check below proves it has no on* or style)
for (const m of fs.readFileSync(path.join(EXT, 'panel.js'), 'utf8').matchAll(/[\s"'`]([a-z][a-z-]*)=(?=["'$`])/g)) BASE_ATTRS.add(m[1]);
for (const m of fs.readFileSync(path.join(EXT, 'panel.js'), 'utf8').matchAll(/\s(data-[a-z-]+)(?=[\s>=])/g)) BASE_ATTRS.add(m[1]);                       // bare data-* flags such as data-dcmd
check('baseline: a benign render has exactly one <script> and one <style>, both with the nonce, and no handler or URL attribute', sb.scripts === 1 && sb.styles === 1 && sb.bad.length === 0 && /<script nonce="N0NCE">/.test(benign) && /<style nonce="N0NCE">/.test(benign), JSON.stringify(sb.bad));

const N = +(process.env.SHIPMIRACLE_FUZZ_N || 1500), ONLY = process.env.SHIPMIRACLE_FUZZ_DEBUG ? +process.env.SHIPMIRACLE_FUZZ_DEBUG : -1;
const fails = { throws: [], markup: [], marker: [] };
const t0 = Date.now();
for (let it = 0; it < N; it++) {
  const proj = []; const sub = 3 + Math.floor(rnd() * 5); const pool = POOL(); for (let k = 0; k < sub; k++) proj.push(pick(pool));
  const seedNow = seed, data = mutate(BASE(proj)); if (ONLY === it) { fs.writeFileSync(process.env.SHIPMIRACLE_FUZZ_OUT, JSON.stringify(data)); }
  let out; try { out = html(data, { nonce: 'N0NCE', csp: '' }); } catch (e) { fails.throws.push({ it, seed: seedNow, e: String(e && e.stack || e).split('\n').slice(0, 3).join(' | ') }); continue; }
  if (typeof out !== 'string') { fails.throws.push({ it, seed: seedNow, e: 'not a string' }); continue; }
  const s = scan(out), newTags = [...s.tags].filter(t => !BASE_TAGS.has(t)), newAttrs = [...s.attrs].filter(a => !BASE_ATTRS.has(a));
  if (s.scripts !== 1 || s.styles !== 1 || s.bad.length || newTags.length || newAttrs.length) fails.markup.push({ it, seed: seedNow, scripts: s.scripts, styles: s.styles, bad: s.bad.slice(0, 3), newTags, newAttrs });
  const body = out.slice(0, out.indexOf('<script nonce')) ;                                                // the static page script is not data; everything before it is markup + text
  if (/<script>ZZ|<img src=x onerror|<svg onload|onfocus='ZZ|<a href="javascript|<\/textarea><script/i.test(body.replace(/<style[\s\S]*?<\/style>/, ''))) fails.marker.push({ it, seed: seedNow });
}
console.log(`FUZZ ${N} malformed pages in ${Date.now() - t0} ms`);
check(`fuzz: html() never throws on ${N} malformed / partial / huge / hostile data objects`, fails.throws.length === 0, JSON.stringify(fails.throws.slice(0, 3)) + ' (' + fails.throws.length + ' throws)');
check(`fuzz: no new tag, no new attribute name, no on* attribute, no javascript:/data: URL, exactly one script and one style on ${N} pages`, fails.markup.length === 0, JSON.stringify(fails.markup.slice(0, 3)));
check('fuzz: no hostile marker (<script>, <img onerror>, <svg onload>, quote break-out, javascript: link) ever appears as raw markup', fails.marker.length === 0, JSON.stringify(fails.marker.slice(0, 3)));

// targeted: every string field of the fixtures set to each hostile string, one at a time (deterministic, no randomness)
{
  const base = BASE(), ls = leaves(base); let n = 0, bad = [];                    // EVERY leaf (strings, numbers, booleans, nulls), not only strings: a number field printed raw is an injection too
  for (const h of ['<script>ZZ()</script>', '"><img src=x onerror=ZZ()>', "' onfocus='ZZ()' x='", '</style><script>ZZ()</script>']) for (const p of ls) {
    const d = clone(base); setAt(d, p, h); n++;
    let out; try { out = html(d, { nonce: 'N0NCE' }); } catch (e) { bad.push(p.join('.') + ': throws'); continue; }
    const s = scan(out); if (s.scripts !== 1 || s.styles !== 1 || s.bad.length || [...s.tags].some(t => !BASE_TAGS.has(t)) || [...s.attrs].some(a => !BASE_ATTRS.has(a))) bad.push(p.join('.') + ': ' + JSON.stringify([s.scripts, s.styles, s.bad.slice(0, 2), [...s.tags].filter(t => !BASE_TAGS.has(t)), [...s.attrs].filter(a => !BASE_ATTRS.has(a))]));
  }
  console.log(`FUZZ targeted: ${n} pages (${ls.length} string fields x 4 hostile strings)`);
  check('targeted: each of the ' + ls.length + ' data fields (strings, numbers, flags) set to 4 hostile strings, one at a time: escaped everywhere (same tags and attributes as a benign page)', bad.length === 0, bad.slice(0, 4).join(' | ') + ' (' + bad.length + ')');
}
// the extremes
{
  const huge = 'x'.repeat(10000), big = BASE([F.mk(huge, 'software', { dir: '/x/' + huge, message: huge, next: huge, cr: [F.cr('CR-001', huge, 'open', 'do')] })]);
  let ok = true, len = 0, dt = 0; try { const t = Date.now(); const o = html(big, { nonce: 'N0NCE' }); dt = Date.now() - t; len = o.length; } catch (e) { ok = false; }
  check('a 10,000-character project name, CR title, message and next line: renders (' + len + ' bytes in ' + dt + ' ms), no throw', ok && dt < 2000);
  let ok2 = true; for (const d of [null, undefined, {}, { projects: null }, { projects: [null, undefined, 5, 'x', []] }, { projects: [{}] }, { projects: [{ name: 5 }] }, []]) { try { html(d, { nonce: 'N0NCE' }); } catch (e) { ok2 = false; console.log('  throws on', JSON.stringify(d), String(e).slice(0, 100)); } }
  check('degenerate top-level data (null, undefined, {}, projects null / with null, numbers, empty objects, [] ) does not throw', ok2);
}

// ============ 2. the cleaners ============
{
  let ok = true; const H = { id: '<b>', kind: 'stage', title: '<script>', sub: '"><img>', verdict: '<x>', ts: 'NaN', project: 'a'.repeat(5000), path: '/x\0y' };
  try { REPORTS.cleanItem(H); REPORTS.cleanItem(null); REPORTS.cleanItem([]); REPORTS.cleanItem({ id: 'ok-1', kind: 'stage', title: { toString() { throw new Error('x'); } } }); } catch (e) { ok = false; }
  check('reports.js cleanItem never throws on hostile or odd items, and drops ids with markup characters', ok && REPORTS.cleanItem(H) === null);
  const parse = s => SETUP.parseCheck(s);
  const evil = JSON.stringify({ v: 1, ready: false, rows: [{ n: 0, id: 'engine', title: '<script>ZZ()</script>', need: 'required', state: 'red', detail: 'token ghp_' + 'a'.repeat(30) + ' password=hunter2', connect: { kind: 'write', text: '"><img src=x onerror=ZZ()>' } }] });
  const p = parse(evil); const txt = JSON.stringify(p);
  check('setup.js parseCheck keeps hostile text as text, hides tokens and passwords, and refuses junk shapes without throwing', p.ok && !/ghp_|hunter2/.test(txt) && [null, '', '{', '[]', '{"v":2}', '{"v":1,"rows":[{"n":"x"}]}', 'x'.repeat(2e6)].every(s => { try { return parse(s).ok === false; } catch (e) { return false; } }));
  check('ask.js checkQuestion / guardNote never throw on odd input', [null, undefined, 5, {}, [], 'a\0b', '‮'].every(v => { try { ASK.checkQuestion(v); ASK.guardNote('/nonexistent', v); return true; } catch (e) { return false; } }));
}

// ============ 3. CSP / webview, static ============
{
  const SRC = { panel: fs.readFileSync(path.join(EXT, 'panel.js'), 'utf8'), ext: fs.readFileSync(path.join(EXT, 'extension.js'), 'utf8'), strings: fs.readFileSync(path.join(EXT, 'strings.js'), 'utf8') };
  const nonce = 'AbC123+/xyz=', csp = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}';">`;
  const page = html(BASE(), { nonce, csp }), s = scan(page);
  check('CSP: the extension builds the policy per render: default-src \'none\', style-src and script-src only with a fresh crypto.randomBytes nonce, nothing else allowed (no img-src, connect-src, frame-src, unsafe-inline, unsafe-eval)',
    /const nonce = crypto\.randomBytes\(12\)\.toString\('base64'\)/.test(SRC.ext) && /content="default-src 'none'; style-src 'nonce-\$\{nonce\}'; script-src 'nonce-\$\{nonce\}';"/.test(SRC.ext) && !/unsafe-inline|unsafe-eval|img-src|connect-src|frame-src|font-src|https?:\/\/[^'"\s]*'/.test(SRC.ext.match(/Content-Security-Policy[^`]*/)[0]));
  check('CSP: the generated page has the policy meta first in <head>, exactly one <script nonce> and one <style nonce>, every script / style tag carries the nonce', page.indexOf(csp) > 0 && page.indexOf(csp) < page.indexOf('<style') && s.scripts === 1 && s.styles === 1 && (page.match(/<(script|style)\b[^>]*>/g) || []).every(t => t.includes(`nonce="${nonce}"`)));
  check('CSP: no inline event handler attribute (onclick= ... ) and no style= attribute in the markup of a full page (all five tabs, every state)', s.bad.length === 0 && ![...s.attrs].some(a => /^on/.test(a)) && !s.attrs.has('style'), JSON.stringify([s.bad, [...s.attrs].filter(a => /^on|^style$/.test(a))]));
  check('CSP: no handler is wired through markup in the panel source either: no "on<event>=" inside a template string', !/\son(click|load|error|focus|blur|change|input|keydown|keyup|mouse\w+|submit)=/.test(SRC.panel.replace(/^\s*\/\/.*$/gm, '')));
  // external URLs: markup, style and script of the generated page, and the source
  const body = page.replace(/<meta http-equiv="Content-Security-Policy"[^>]*>/, ''), styleBlock = (/<style[^>]*>([\s\S]*?)<\/style>/.exec(page) || [, ''])[1], scriptBlock = (/<script[^>]*>([\s\S]*?)<\/script>/.exec(page) || [, ''])[1];
  const ext = []; for (const [nm, t] of [['markup', body.replace(/<style[\s\S]*?<\/style>/, '').replace(/<script[\s\S]*?<\/script>/, '')], ['style', styleBlock], ['script', scriptBlock]]) { for (const m of t.matchAll(/https?:\/\/[^\s"'<>)]+|(?<![:\w])\/\/[a-z0-9.-]+\.[a-z]{2,}\b|@import|url\(\s*["']?(?!#|data:image\/svg)/gi)) ext.push(nm + ': ' + m[0].slice(0, 40)); }
  check('CSP: no external URL anywhere in the generated page: no http(s)://, no protocol-relative //host, no @import, no url() in the style block, no fetch / XMLHttpRequest / WebSocket / import() in the script', ext.length === 0 && !/\bfetch\(|XMLHttpRequest|new WebSocket|\bimport\(|navigator\.sendBeacon|<link\b|<iframe|<object|<embed|<base\b/.test(page), JSON.stringify(ext.slice(0, 5)));
  check('CSP: the page script uses no eval, new Function, document.write, setTimeout/setInterval with a string, outerHTML or insertAdjacentHTML; innerHTML is not assigned from data', !/\beval\(|new Function\(|document\.write\(|set(Timeout|Interval)\(\s*['"`]|outerHTML\s*=|insertAdjacentHTML/.test(scriptBlock), (scriptBlock.match(/\beval\(|new Function\(|document\.write\(|outerHTML\s*=|insertAdjacentHTML/) || [''])[0]);
  const ih = [...scriptBlock.matchAll(/innerHTML\s*=\s*([^;\n]{0,80})/g)].map(m => m[1]); const dyn = ih.filter(x => !/^\s*(''|""|``)/.test(x));
  check('CSP: innerHTML is only ever cleared in the page script (' + ih.length + ' assignments' + (dyn.length ? ', non-empty: ' + dyn.join(' | ').slice(0, 120) : '') + ')', dyn.length === 0, dyn.join(' | ').slice(0, 300));
  check('CSP: strings.js (the copy) contains no markup and no URL: nothing in it can add an external resource', !/<[a-z]+[\s>]|https?:\/\//i.test(SRC.strings.replace(/^\s*\/\/.*$/gm, '')), (SRC.strings.match(/<[a-z]+[\s>]|https?:\/\/[^\s'"]*/i) || [''])[0]);
  check('webview options: scripts on, localResourceRoots empty (the page can read no local folder; it loads none)', /webview\.options = \{ enableScripts: true, localResourceRoots: \[\] \}/.test(SRC.ext));
}

// ============ 4. the public export ============
if (!fs.existsSync(path.join(ROOT, 'release', 'hard-never.txt'))) console.log('SKIP export rules check: the exported tree does not carry the private release/ rule files');
else {
  const never = fs.readFileSync(path.join(ROOT, 'release', 'hard-never.txt'), 'utf8').split('\n').map(x => x.trim()).filter(x => x && !x.startsWith('#'));
  const exp = fs.readFileSync(path.join(ROOT, 'shipmiracle', 'release', 'export.py'), 'utf8');
  const def = (/HARD_NEVER_DEFAULT = \(([\s\S]*?)\)\n/.exec(exp) || [, ''])[1];
  check('export: tests/fixtures/panel-v3/** and docs/summary/** are in release/hard-never.txt and in the exporter\'s built-in fallback list (they win over the tests/fixtures/** allow rule)', ['tests/fixtures/panel-v3/**', 'docs/summary/**'].every(x => never.includes(x) && def.includes('"' + x + '"')), JSON.stringify(never.filter(x => /panel|summary/.test(x))));
  const py = require('child_process').spawnSync('python3', ['-I', '-c', `
import sys, json; sys.path.insert(0, ${JSON.stringify(ROOT)})
from shipmiracle.release import export as E
rd = lambda f: open(${JSON.stringify(ROOT)} + "/release/" + f, encoding="utf-8").read()
R = E.Rules(E.parse_rules(rd("allowlist.txt")), E.parse_rules(rd("hard-never.txt")))
D = E.Rules(E.ALLOWLIST_DEFAULT, E.HARD_NEVER_DEFAULT)
names = ["tests/fixtures/panel-v3/idle-light.png", "tests/fixtures/panel-v3/setup-remote-dark.png", "docs/summary/panel-shots-manifest.json", "docs/summary/anything.md", "tests/fixtures/report/facts_cr012.json", "vscode-ext/shipmiracle-panel/panel.js", "tests/panel_v3_golden_test.js"]
print(json.dumps({n: [R.selected(n), D.selected(n)] for n in names}))`], { encoding: 'utf8', timeout: 20000 });
  let sel = {}; try { sel = JSON.parse(py.stdout); } catch (e) { /* reported below */ }
  check('export (real rules): the panel screenshots and docs/summary are NOT selected, by the release files nor by the built-in fallback; other fixtures and the panel code are', sel['tests/fixtures/panel-v3/idle-light.png'] + '' === 'false,false' && sel['tests/fixtures/panel-v3/setup-remote-dark.png'] + '' === 'false,false' && sel['docs/summary/panel-shots-manifest.json'] + '' === 'false,false' && sel['docs/summary/anything.md'] + '' === 'false,false' && sel['tests/fixtures/report/facts_cr012.json'] + '' === 'true,true' && sel['vscode-ext/shipmiracle-panel/panel.js'] + '' === 'true,true' && sel['tests/panel_v3_golden_test.js'] + '' === 'true,true', py.stderr.slice(0, 200) + JSON.stringify(sel));
}
// ============ 5. a real browser as the oracle (when Chrome is installed): EVERY string field set to a hostile payload at once ============
(async () => {
  if (!D.H.available()) { console.log('NOTE no Chrome: the DOM oracle was skipped'); return done(); }
  const S = await D.session({ size: '345,900' });
  const base = BASE(), ls = leaves(base).filter(p => typeof p.reduce((o, k) => o[k], base) === 'string');
  for (const [nm, payload] of [['img onerror', '"><img src=x onerror=window.__xss=1>'], ['script', '</textarea></style></script><script>window.__xss=2</script>'], ['svg + attribute break-out', "'><svg onload=window.__xss=3> x='"]]) {
    const d = clone(base); for (const p of ls) if (!/^(projects\.\d+\.(dir|name))$/.test(p.join('.'))) setAt(d, p, payload);
    const f = S.file('hostile', D.page('dark', d));
    for (const tab of ['projects', 'reports', 'ideas', 'health', 'setup']) {
      await S.load(f, 315, '?tab=' + tab, 1400); await S.sleep(200);
      const r = await S.ev(`({ xss: window.__xss === undefined, scripts: document.querySelectorAll('script').length, handlers: [...document.querySelectorAll('*')].filter(n => [...n.attributes].some(a => /^on/i.test(a.name))).length, imgs: document.querySelectorAll('img, iframe, object, embed, svg[onload]').length, ok: !!document.querySelector('.tabs') })`);
      check(`browser oracle [${nm}] ${tab}: nothing ran, one script element, no on* attribute, no img / iframe, the page still draws`, r.xss && r.scripts === 1 && r.handlers === 0 && r.imgs === 0 && r.ok, JSON.stringify(r));
    }
  }
  // M1: a data-armed="1" that arrives in markup (or is set on the element) is never consent: the first click still asks "Sure?" and posts nothing
  {
    const f = S.file('armed', D.page('dark', BASE([F.STATES.find(x => x.state === 'autopilot').p]))); await S.load(f, 315, '?tab=projects', 1400);
    await S.ev(`(() => { const b = document.querySelector('.btn.stopq[data-sure]'); b.setAttribute('data-armed', '1'); window.__b = b; })()`); await S.ev('window.__msgs.length = 0');
    await S.ev(`window.__b.click()`);
    const m = JSON.parse(await S.ev('JSON.stringify(window.__msgs)')).filter(x => x.type !== 'editing');
    check('armed state lives in a script variable: a preset data-armed="1" on the Stop autopilot button does not skip "Sure?" on Stop autopilot (nothing posted, the button asks)', m.length === 0 && /Sure/.test(await S.ev('window.__b.textContent')), JSON.stringify(m));
    await S.ev('window.__msgs.length = 0'); await S.ev(`window.__b.click()`);
    check('...and the second click (really armed) posts the stop once', JSON.parse(await S.ev('JSON.stringify(window.__msgs)')).filter(x => x.type !== 'editing').length === 1);
  }
  // M1: the Health badge from hostile counts (the exact reviewer payload) is a number or nothing, never markup
  {
    const evil = '<button class="btn primary" data-level="x" data-to="warn" data-armed="1">';
    const pg = html({ projects: [F.mk('hc-app', 'software')], health: { items: [], counts: { red: evil, amber: evil, info: evil } } }, { nonce: 'N' });
    check('Health badge: hostile health.counts strings never become markup (no extra button, no data-armed in the page)', !pg.includes(evil) && (pg.match(/data-armed="1"/g) || []).length === 0 && !/<button class="btn primary" data-level="x"/.test(pg) && scan(pg).attrs.has('data-to') === scan(html({ projects: [F.mk('hc-app', 'software')] }, { nonce: 'N' })).attrs.has('data-to'));
  }
  S.close(); done();
})().catch(e => { console.error(e); process.exit(2); });
function done() {   console.log(C.fails ? `\nFAILED: ${C.fails} of ${C.n}` : `\nALL PASS (${C.n})`); process.exit(C.fails ? 1 : 0);
}
