// Two-level project timeline of the card (release line, rail only for an open change, idle block, History, typed commands). Checks of panel.html(), timeline.js and sane.js; the extension route is in
// tests/ext_timeline_route_test.js, data.js in tests/data_timeline_test.js and the browser pictures in tests/panel_timeline_ui_test.js.
// Legacy golden: tests/fixtures/timeline-legacy-hash.json was written with TL_BASELINE=1 from the panel BEFORE this feature (main 6e0259d); with caps.release false/missing the page must hash the same.
// Re-baselined 31 Oct 2026 (fix/setup-calm, panel 0.5.1): the Setup tab's calm view added CSS and page script (setupx.js); the body markup of all 26 pages was verified byte-identical to main 073e29d (style and script stripped) before re-recording.
// Re-baselined again 31 Oct 2026 (fix/setup-checkbtn, panel 0.5.2): the Setup tab's "Check again" is now the standard .btn and Details a button.lnk (setupx.js CSS, panel.js Setup markup only); the body markup of all 26 pages was verified byte-identical to main 09b0fa8 (style and script stripped) before re-recording.
// Run: node tests/ext_timeline_test.js
require('./shipmiracle_isolation').apply();
const fs = require('fs'), path = require('path'), crypto = require('crypto');
const FIXED = Date.UTC(2026, 9, 30, 12, 0, 0);                         // the clock is frozen so "2 h ago" never changes between runs
const realNow = Date.now; Date.now = () => FIXED;
const EXT = path.join(__dirname, '..', 'vscode-ext', 'shipmiracle-panel');
const F = require('./panel_v3_fixtures');
const { html } = require(path.join(EXT, 'panel.js'));
const HASHFILE = path.join(__dirname, 'fixtures', 'timeline-legacy-hash.json');
const sha = s => crypto.createHash('sha256').update(s).digest('hex');
const ALL = [...F.STATES.map(s => s.p), ...F.TYPES.map(t => t.p), F.EXTRA.queued, F.EXTRA.fast, F.EXTRA.arabic, F.EXTRA.held];
const page = (projects, extra = {}) => html({ plan: { meters: [] }, guard: { on: true }, projects, ask: null, levelSwitch: { ok: true, why: '' }, ...extra }, {});
const legacyHashes = () => Object.fromEntries(ALL.map(p => [p.name, sha(page([p]))]));
if (process.env.TL_BASELINE === '1') { fs.mkdirSync(path.dirname(HASHFILE), { recursive: true }); fs.writeFileSync(HASHFILE, JSON.stringify(legacyHashes(), null, 1) + '\n'); console.log('wrote ' + HASHFILE + ' (' + ALL.length + ' pages)'); process.exit(0); }

const STR = require(path.join(EXT, 'strings.js')), SANE = require(path.join(EXT, 'sane.js'));
const TLF = require(path.join(EXT, 'timeline.js'));
const REAL = TLF;                                              // the pure parts (argv builders, version checks) are plain functions of the module
let fails = 0, total = 0; const check = (n, c, info = '') => { total++; console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' ' + String(info).slice(0, 400))); if (!c) fails++; };
const strip = h => String(h).replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').replace(/&#39;/g, "'").replace(/&quot;/g, '"').replace(/\s+/g, ' ').trim();
const one = (h, re) => { const m = h.match(re); return m ? m[0] : ''; };
const body = h => h.replace(/<style[\s\S]*?<\/style>/g, '').replace(/<script[\s\S]*?<\/script>/g, '');
const relText = h => strip(one(h, /<div class="tlrel[^"]*"[^>]*>[\s\S]*?<\/span>/));
const mk = F.mk, cr = F.cr;
const rel = (o = {}) => ({ last: { version: '1.0', date: '2026-10-12', tag: 'v1.0' }, working: null, since: { changes: 0, commits: 0 }, ...o });
const H = (id, title, status, closed, release) => ({ id, title, status, closed, release });
const hist1 = [H('CR-009', 'Arabic onboarding', 'delivered', '2026-10-11', '1.0'), H('CR-008', 'Export report', 'delivered', '2026-10-05', '1.0')];
const T = (p, release, history, caps = true) => page([{ ...p, release, history }], { capabilities: { release: caps } }).replace(/<style[\s\S]*?<\/style>/g, '');      // (the CSS names every class, so checks look at the markup and the script only)
const noRail = h => !/<ol class="rail"/.test(h);
const STEPS = h => (h.match(/data-step="/g) || []).length;
const WORK11 = { version: '1.1', source: 'package.json' };

// ---- 1. legacy: caps.release false or missing -> the page is byte-identical to the one before this feature
const gold = JSON.parse(fs.readFileSync(HASHFILE, 'utf8'));
const now0 = legacyHashes();
check('legacy golden: all ' + ALL.length + ' fixture pages hash like the pre-feature panel (main 6e0259d)', ALL.every(p => now0[p.name] === gold[p.name]), ALL.filter(p => now0[p.name] !== gold[p.name]).map(p => p.name).join());
const withData = ALL.map(p => ({ ...p, release: rel({ working: WORK11, since: { changes: 3, commits: 9 } }), history: hist1 }));
check('legacy: caps.release false + release/history in the data -> pages identical to the golden', withData.every(p => sha(page([p], { capabilities: { release: false } })) === gold[p.name]));
check('legacy: capabilities without a release flag + release/history in the data -> pages identical to the golden', withData.every(p => sha(page([p], { capabilities: { aside: true } })) === sha(page([ALL.find(a => a.name === p.name)], { capabilities: { aside: true } }))));
check('caps.release true but a project without release data -> no timeline markup on its card', !/tlrel|tlidle|tlhb/.test(body(page([ALL[0]], { capabilities: { release: true } }))));

// ---- 2. the card states
const idle = mk('idle-app', 'software', { chatOpen: false });
let h = T(idle, rel(), hist1);
check('idle after a release: "Released v1.0 · 12 Oct · nothing new since"', relText(h) === 'Released v1.0 · 12 Oct · nothing new since', relText(h));
check('idle: no rail at all (no empty and no all-done rail)', noRail(h) && STEPS(h) === 0 && !/class="rs s-/.test(h));
check('idle: "Last change: CR-009 Arabic onboarding · done 11 Oct"', /Last change: CR-009 Arabic onboarding · done 11 Oct/.test(strip(h)), strip(one(h, /<div class="tlidle"[\s\S]*?<\/div><\/div>/)));
check('idle: "Next: start a change (Brief)" and a Start a change button (data-act tlcr) with an aria-label', /Next: start a change \(Brief\)/.test(strip(h)) && /data-act="tlcr"[^>]*aria-label="[^"]+"/.test(h) && />Start a change</.test(h));
check('idle: data-state idle and the release line is a labelled group', /data-state="idle"/.test(h) && /class="tlrel"[^>]*role="group" aria-label="Release: Released v1\.0, 12 Oct, nothing new since"/.test(h), one(h, /<div class="tlrel[^>]*>/));
const dlv = F.STATES.find(s => s.state === 'delivered').p;
h = T(dlv, rel(), [H('CR-012', 'RTL fix', 'delivered', '2026-10-11', '1.0')]);
check('a delivered change with nothing open never draws an all-done rail', noRail(h) && !/\bs-done\b/.test(h) && /data-state="idle"/.test(h), one(h, /data-state="[^"]*"/));
h = page([{ ...dlv, release: rel(), history: [] }], { capabilities: { release: false } });
check('control: with caps.release false the same delivered project still draws the old all-done rail', !noRail(h) && /\bs-done\b/.test(h));

const planning = mk('plan-app', 'software', { state: 'working', cr: [cr('CR-012', 'RTL fix', 'open', 'plan')], flow: F.run('planner', 'opus') });
h = T(planning, rel({ working: WORK11, since: { changes: 2, commits: 7 } }), hist1);
check('planning: "Released v1.0 · 12 Oct · working on v1.1 · 2 changes done"', relText(h) === 'Released v1.0 · 12 Oct · working on v1.1 · 2 changes done', relText(h));
check('planning: the 7-step rail is there and there is no idle block', STEPS(h) === 7 && !/tlidle/.test(h) && /data-state="planning"/.test(h));
check('the last step reads "Done" (not Ship) and the first is still Brief', /data-step="deliver"[^>]*data-name="Done"/.test(h) && !/data-name="Ship"/.test(h) && /data-step="scope"[^>]*data-name="Brief"/.test(h), one(h, /data-step="deliver"[^>]*>/));
check('the rail has a screen-reader label naming the steps', /<ol class="rail" aria-label="Steps: Brief, Plan, OK, Build, Test, Review, Done"/.test(h), one(h, /<ol class="rail"[^>]*>/));
const renamed = { ...planning, stageLabels: { ...planning.stageLabels, deliver: 'Handed over' } };
check('a rename of the last step in the data wins over the Ship -> Done mapping', /data-name="Handed over"/.test(T(renamed, rel(), [])) && !/data-name="Done"/.test(T(renamed, rel(), [])));
const building = mk('build-app', 'software', { state: 'working', agents: [{ type: 'builder-frontend', model: 'sonnet', mins: 12 }], cr: [cr('CR-012', 'RTL fix', 'open', 'do')], flow: F.run('builder-frontend', 'sonnet') });
h = T(building, rel({ working: WORK11, since: { changes: 1, commits: 2 } }), hist1);
check('building: "working on v1.1 · 1 change done" (singular) and the Build step is current', /working on v1\.1 · 1 change done$/.test(relText(h)) && /data-step="do"[^>]*aria-current="step"/.test(h) && STEPS(h) === 7, relText(h));
const waiting = mk('ok-app', 'software', { state: 'needs-input', cr: [cr('CR-013', 'Export report', 'open', 'approve', { waiting_on: 'owner' })] });
h = T(waiting, rel({ working: WORK11, since: { changes: 2, commits: 4 } }), hist1);
check('waiting for the OK: the rail is there, the primary stays "Review plan", no Start a change button', STEPS(h) === 7 && /data-state="approval"/.test(h) && /data-primary="plan"/.test(h) && !/data-act="tlcr"/.test(h));
const queued = mk('q-app', 'software', { cr: [cr('CR-013', 'Export report', 'queued', 'scope')] });
check('a queued change also draws the rail (open / blocked / queued)', STEPS(T(queued, rel(), [])) === 7);

const unpl = mk('un-app', 'software', { state: 'working', chatOpen: true, dirty: 3 });
h = T(unpl, rel(), hist1);
check('chat working with edits and no change: "Unplanned work · not on the timeline" + Track as a change, no rail', /data-state="unplanned"/.test(h) && /Unplanned work · not on the timeline/.test(strip(h)) && />Track as a change</.test(h) && noRail(h), one(h, /data-state="[^"]*"/));
check('unplanned: the Track button is the only command button (no second Start a change)', (h.match(/data-act="tlcr"/g) || []).length === 1);
const talk = mk('talk-app', 'software', { state: 'idle', chatOpen: true });
h = T(talk, rel(), hist1);
check('chat open and only talking: "Chat open · no change yet", no rail, Start a change offered', /data-state="chatonly"/.test(h) && /Chat open · no change yet/.test(strip(h)) && noRail(h) && />Start a change</.test(h));
check('chat working but nothing edited is "talking", not "unplanned"', /data-state="chatonly"/.test(T(mk('talk2-app', 'software', { state: 'working', chatOpen: true, dirty: 0 }), rel(), [])));
check('a chat with an open change is never "unplanned"', !/data-state="(unplanned|chatonly)"/.test(T({ ...building, chatOpen: true, dirty: 5 }, rel(), [])));
check('a held project offers no Start a change button', !/data-act="tlcr"/.test(T(F.EXTRA.held, rel(), hist1)));

h = T(mk('new-app', 'app', {}), { last: null, working: { version: '1.0', source: 'Xcode' }, since: { changes: 0, commits: 0 } }, []);
check('no release yet: "No release yet · building v1.0 (Xcode)"', relText(h) === 'No release yet · building v1.0 (Xcode)', relText(h));
check('no release yet and no history: "No change finished yet" instead of a rail', /No change finished yet/.test(strip(h)) && noRail(h), strip(one(h, /<div class="tlidle"[\s\S]*?<\/div><\/div>/)));
const content = mk('blog', 'content', {});
h = T(content, { last: null, working: null, since: { changes: 0, commits: 0 } }, [H('CR-004', 'Spring post', 'delivered', '2026-10-09', null)]);
check('content project without a version: "Last done: CR-004 · 9 Oct"', relText(h) === 'Last done: CR-004 · 9 Oct', relText(h));
check('content project without a version or history: "No release yet"', relText(T(content, { last: null, working: null, since: { changes: 0, commits: 0 } }, [])) === 'No release yet');
check('a date from another year shows the year, with no time-zone shift for a plain date', /Released v1\.0 · 31 Dec 2025/.test(relText(T(idle, rel({ last: { version: '1.0', date: '2025-12-31', tag: 'v1.0' } }), []))), relText(T(idle, rel({ last: { version: '1.0', date: '2025-12-31', tag: 'v1.0' } }), [])));

h = T(idle, rel({ working: WORK11, since: { changes: 3, commits: 8 } }), hist1);
check('v1.1 ready: "v1.1 ready · 3 changes done since v1.0" + [Mark v1.1 released]', relText(h) === 'v1.1 ready · 3 changes done since v1.0' && />Mark v1\.1 released</.test(h) && /data-act="tlmark" data-verb="1\.1"/.test(h), relText(h));
check('ready: the button carries an aria-label with the project', /data-act="tlmark"[^>]*aria-label="Mark v1\.1 released for idle-app"/.test(h), one(h, /<button[^>]*tlmark[^>]*>/));
h = T(building, rel({ working: WORK11, since: { changes: 3, commits: 8 } }), hist1);
check('no Mark button while a change is open', !/data-act="tlmark"/.test(h) && !/ready/.test(relText(h)));
h = T(idle, rel({ working: WORK11, since: { changes: 0, commits: 0 } }), hist1);
check('working version above the release but nothing done: no Mark button', !/data-act="tlmark"/.test(h) && relText(h) === 'Released v1.0 · 12 Oct · working on v1.1', relText(h));
h = T(idle, rel({ working: { version: '1.0', source: 'package.json' }, since: { changes: 2, commits: 3 } }), hist1);
check('working version equal to the release with changes since: "2 changes done since", no button', !/data-act="tlmark"/.test(h) && relText(h) === 'Released v1.0 · 12 Oct · 2 changes done since', relText(h));
h = T(idle, rel({ working: { version: '1.1"><img src=x onerror=alert(1)>', source: '<b>x</b>' }, since: { changes: 3, commits: 8 } }), hist1);
check('a hostile working version is escaped and gets no button', !/data-act="tlmark"/.test(h) && !/<img src=x/.test(h) && !/<b>x<\/b>/.test(h));
check('a version that is not digits and dots gets no button (1.1.1.1.1, 1.x, 1..2, -1)', ['1.1.1.1.1', '1.x', '1..2', '-1'].every(v => !/data-act="tlmark"/.test(T(idle, rel({ working: { version: v, source: 's' }, since: { changes: 3, commits: 8 } }), []))));
check('a leading v in the data (v1.2) still types a clean 1.2', /data-verb="1\.2"/.test(T(idle, rel({ last: { version: 'v1.0', date: '2026-10-12' }, working: { version: 'v1.2', source: 's' }, since: { changes: 1, commits: 1 } }), [])));

// ---- 3. History
const big = Array.from({ length: 12 }, (_, i) => H('CR-' + String(20 - i).padStart(3, '0'), 'Change ' + i, i === 4 ? 'abandoned' : 'delivered', '2026-10-' + String(28 - i).padStart(2, '0'), i < 3 ? null : i < 8 ? '1.1' : '1.0'));
h = T(idle, rel({ working: { version: '1.2', source: 'p' }, since: { changes: 3, commits: 8 } }), big);
check('History: a collapsed disclosure "History (10)", aria-expanded=false, controls a hidden region', /class="lnk tlhb"[^>]*aria-expanded="false"[^>]*aria-controls="tlh-idle-app"/.test(h) && /id="tlh-idle-app"[^>]*hidden/.test(h) && />History \(10\) </.test(h), one(h, /<button[^>]*tlhb[^>]*>/));
const hb = one(h, /<div class="tlhist"[\s\S]*?<\/div><\/div>/);
check('History lists at most 10 changes, newest first', (hb.match(/<li>/g) || []).length === 10 && hb.indexOf('CR-020') < hb.indexOf('CR-019') && !/CR-009/.test(hb), (hb.match(/<li>/g) || []).length);
const heads = [...hb.matchAll(/<h5[^>]*>([^<]*)<\/h5>/g)].map(m => m[1]);
check('History is grouped under release headings: Not released yet, v1.1, v1.0 (with its date)', JSON.stringify(heads) === JSON.stringify(['Not released yet', 'Released in v1.1', 'Released in v1.0 · 12 Oct']), JSON.stringify(heads));
check('History: an abandoned change says so, a delivered one does not', /CR-016<\/b> <bdi[^>]*>Change 4<\/bdi> · abandoned/.test(hb) && !/Change 3<\/bdi> · delivered/.test(hb), hb.slice(0, 600));
check('History: no block when the data has no history', !/tlhb/.test(T(idle, rel(), [])) && !/tlhb/.test(T(idle, rel(), null)));
check('History: titles are isolated for Arabic (bdi dir=auto)', /<bdi dir="auto">إصلاح RTL<\/bdi>/.test(T(idle, rel(), [H('CR-001', 'إصلاح RTL', 'delivered', '2026-10-01', '1.0')])));
h = T(idle, rel(), [H('CR-001', '<img src=x onerror=alert(1)>', 'delivered', '2026-10-01', '1.0"><x')]);
check('History: hostile titles and release names are escaped', !/<img src=x/.test(body(h)) && !/<x>/.test(body(h)));
check('History: the page script restores the open set and sends no message', /function tlHist\(/.test(h) && !/function tlHist[^\n]*postMessage/.test(h));

// ---- 4. sane.js: the shape guard
const sp = SANE.sane({ projects: [{ name: 'x', dir: '/x', release: { last: { version: 7, date: ['x'], tag: null }, working: 'no', since: { changes: 'NaN', commits: -4 } }, history: [1, null, ...Array.from({ length: 14 }, (_, i) => ({ id: 'CR-' + i, title: { a: 1 }, status: 'delivered', closed: null, release: 3 }))] }], capabilities: { release: 'yes' } });
check('sane: capabilities.release is true only for true', sp.capabilities.release === false && SANE.sane({ capabilities: { release: true } }).capabilities.release === true);
const q = sp.projects[0];
check('sane: wrong-typed release fields become safe defaults', q.release && q.release.working === null && q.release.since.changes === 0 && q.release.since.commits === 0, JSON.stringify(q.release));
check('sane: history keeps at most 10 objects and every field is text', Array.isArray(q.history) && q.history.length === 10 && q.history.every(x => ['id', 'title', 'status', 'release'].every(k => typeof x[k] === 'string')), JSON.stringify(q.history).slice(0, 160));
const good = { last: { version: '1.0', date: '2026-10-12', tag: 'v1.0' }, working: { version: '1.1', source: 'package.json' }, since: { changes: 2, commits: 5 } };
const sg = SANE.sane({ projects: [{ name: 'x', dir: '/x', release: good, history: hist1 }] }).projects[0];
check('sane: a valid release and history pass through unchanged', JSON.stringify(sg.release) === JSON.stringify(good) && JSON.stringify(sg.history) === JSON.stringify(hist1), JSON.stringify(sg));
const sl = SANE.sane({ projects: [{ name: 'x', dir: '/x' }] }).projects[0];
check('sane: a project without release/history gets neither key (legacy shape)', !('release' in sl) && !('history' in sl));
check('page: hostile release data never throws and never reaches the page as markup', (() => { try { const x = page([{ ...idle, release: { last: { version: '<i>', date: '2026-10-12' }, working: { version: {}, source: [] }, since: 'x' }, history: 'no' }], { capabilities: { release: true } }); return /Released v&lt;i&gt;/.test(body(x)); } catch (e) { return false; } })());

// ---- 5. the two typed commands (timeline.js): validated before anything is typed
check('markArgv: a clean version and project give `shipm release mark 1.1 --project demo`', JSON.stringify(REAL.markArgv('/ws/bin/shipm', 'demo', '1.1')) === JSON.stringify([['/ws/bin/shipm', 'release', 'mark', '1.1', '--project', 'demo']]));
const throws = f => { try { f(); return false; } catch (e) { return true; } };
check('markArgv: 1, 1.2.3 and 1.2.3.4 are fine', ['1', '1.2.3', '1.2.3.4'].every(v => REAL.markArgv('s', 'demo', v).length === 1));
check('markArgv: 1.2.3.4.5 and every shell or odd text is refused', ['1.2.3.4.5', '1.1;ls', '1.1 && x', '$(x)', '1.1\n', '', '1.', '.1', '-1', '1.1\u001b', 'x', null, undefined].every(v => throws(() => REAL.markArgv('s', 'demo', v))));
check('markArgv: unsafe project names are refused', ['', '--x', 'a b', 'a;b', 'a/b', '$(x)', 'x'.repeat(101)].every(n => throws(() => REAL.markArgv('s', n, '1.1'))));
check("openLine: types `shipm cr open --project NAME ''` (single quotes, the cursor goes between them) with no newline and no Enter", REAL.openLine('/ws/bin/shipm', 'demo') === "'/ws/bin/shipm' 'cr' 'open' '--project' 'demo' ''" && !/[\r\n]/.test(REAL.openLine('/ws/bin/shipm', 'demo')) && !REAL.openLine('/ws/bin/shipm', 'demo').includes('"'), REAL.openLine('/ws/bin/shipm', 'demo'));
check('openLine: unsafe project names are refused', ['', '--x', 'a b', 'a;b', 'a/b', '$(x)', '"; rm -rf /', 'x'.repeat(101), null, undefined].every(n => throws(() => REAL.openLine('s', n))));
check('verOk and cmpVer', REAL.verOk('1.10.3') && !REAL.verOk('1.x') && REAL.cmpVer('1.10', '1.9') === 1 && REAL.cmpVer('1.0', '1.0.0') === 0 && REAL.cmpVer('0.9', '1.0') === -1);

// ---- 6. size and source rules
const PANEL = fs.readFileSync(path.join(EXT, 'panel.js'), 'utf8'), TLS = fs.readFileSync(path.join(EXT, 'timeline.js'), 'utf8');
check('panel.js stays under 200 KB and gets the timeline from timeline.js', Buffer.byteLength(PANEL) < 200000 && /require\('\.\/timeline'\)/.test(PANEL), Buffer.byteLength(PANEL));
check('timeline.js: every visible word comes from strings.js (no English sentence in the markup code)', !/[>`'"][A-Z][a-z]+ [a-z]+[^`'"]*(<\/|`)/.test(TLS.split('\n').filter(l => !/^\s*\/\/|^const (css|clientJs)|^\.|^@media|^body\./.test(l)).join('\n').replace(/\/\/.*$/gm, '').replace(/'[^'\n]*'/g, "''")));
check('timeline page script: no eval, innerHTML or network call', !/eval\(|innerHTML|fetch\(|XMLHttpRequest/.test(TLF.clientJs));
check('strings.js has the tl block and no tl text uses a digit-less placeholder typo', STR.tl && Object.values(STR.tl).every(v => typeof v === 'string' && (v.match(/\{/g) || []).length === (v.match(/\}/g) || []).length));

Date.now = realNow;
console.log(fails ? `\nFAILED: ${fails} of ${total}` : `\nALL PASS (${total})`); process.exit(fails ? 1 : 0);
