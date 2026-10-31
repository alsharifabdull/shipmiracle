// The Setup tab of the cross-platform onboarding (plan 2026-10-21-cross-platform-onboarding.md section 4.6): the one-line OS description, the Quick setup card (five choices, the
// recommended answer selected, a "Run in terminal" button that RUNS `shipm init --prefs ...` at once, with no prompt), the not-ready required rows on top, and everything else behind a closed Details button (all required ready: one calm line).
// Shown only when the CLI sends the onboarding fields (stage / class / os_supported and the top-level os line); an older CLI keeps the old full list. Everything is escaped, symbols are ASCII.
// A factory like cardx.js: panel.js passes the helpers it shares.
module.exports = function make(D) {
const { t, esc, setupRow, effRow } = D;
const isReq = r => (r.cls || r.need) === 'required';
const unsupported = r => r.os_supported === false;
// "Optional never red": an optional or advanced row that is not ready is shown grey, never red; only a required row can be red.
const view = r => (!isReq(r) && r.state === 'red' ? { ...r, state: 'skipped' } : r);
const MK = { ok: ['ok', '+', 'quick.markOk'], needs: ['red', '!', 'quick.markNeeds'], opt: ['skip', '-', 'quick.markOpt'], no: ['skip', 'x', 'quick.markNo'] };
function plainRow(r, kind) {                                  // a row without buttons (not supported on this OS)
  const [cls, glyph, key] = MK[kind];
  return `<li class="chk ${cls}" data-row="${esc(r.id)}" data-need="${esc(r.need)}" data-state="unsupported"><span class="cmark" role="img" aria-label="${esc(t(key))}">${glyph}</span><div class="cbody"><div class="cname"><b dir="auto">${esc(r.title)}</b></div><div class="creason">${esc(t('quick.unsupported'))}</div>${r.docs ? `<div class="chint" dir="auto">${esc(t('quick.docs', { url: r.docs }))}</div>` : ''}</div></li>`;
}
// the five choices; the awake choice exists on macOS only (the CLI asks it only where keep-awake works), the system pop-ups option on macOS and Linux
function choices(os) {
  const k = os && os.kind;
  const opts = (name, list, def) => `<div class="qsg" role="radiogroup">${list.map(([v, label]) => `<label class="qso"><input type="radio" name="qs-${name}" value="${v}" data-qs="${name}"${v === def ? ' checked' : ''}><span>${esc(label)}${v === def ? ` <span class="qsr">(${esc(t('quick.recommended'))})</span>` : ''}</span></label>`).join('')}</div>`;
  const fs = (name, legend, body) => `<fieldset class="qsf" data-qsq="${name}"><legend>${esc(legend)}</legend>${body}</fieldset>`;
  const parts = [
    fs('lang', t('quick.lang'), opts('lang', [['en', t('quick.langEn')], ['ar', t('quick.langAr')]], 'en')),
    fs('folder', t('quick.folder'), `<input type="text" class="fin" data-qs="folder" data-qsdefault="~/Developer" value="~/Developer" maxlength="200" autocomplete="off" spellcheck="false" aria-label="${esc(t('quick.folder'))}" dir="ltr"><div class="nhint">${esc(t('quick.folderHelp'))}</div>`),
    fs('autonomy', t('quick.autonomy'), opts('autonomy', [['normal', t('quick.autNormal')], ['step', t('quick.autStep')], ['own', t('quick.autOwn')]], 'normal'))
  ];
  if (k === 'macos') parts.push(fs('awake', t('quick.awake'), opts('awake', [['yes', t('quick.yes')], ['no', t('quick.no')]], 'yes')));
  parts.push(fs('notify', t('quick.notify'), opts('notify', [['vscode', t('quick.notVscode')]].concat(k === 'macos' || k === 'linux' ? [['system', t('quick.notSystem')]] : [], [['none', t('quick.notNone')]]), 'vscode')));
  return parts.join('');
}
function quickCard(os) {
  return `<section class="qs" aria-labelledby="qs-h"><h3 id="qs-h" class="qsh">${esc(t('quick.title'))}</h3><p class="nhint">${esc(t('quick.intro'))}</p>${choices(os)}<div class="nhint">${esc(t('quick.cmdLabel'))}</div><code class="chcmd" data-qscmd dir="ltr"></code><div class="brow qsb"><button type="button" class="btn go" data-setup="prefs">${esc(t('quick.run'))}</button></div></section>`;
}
// -> { header, sub, ok, icon, body } (the pane body after the notice), or null when the CLI is too old for it.
// Calm view (every supported required row ready): one "Setup complete" line and a closed Details button; the Quick setup card, the OS line and every row (optional ones too) live inside Details.
// Fix view (a required row is not ready): "Setup · N to fix", only the not-ready required rows with their buttons at the top, the Quick setup card only while it has never been run
// (its row is not green), everything else inside Details. Details is a real button (aria-expanded) in the History-toggle style (button.lnk, trailing chevron); "Check again" is the panel's secondary .btn; the page script below opens it, closed by default, and keeps the choice in vscode.setState.
const CHECK = '<svg class="scalmi" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false"><circle cx="8" cy="8" r="8" fill="currentColor"/><path d="M4.6 8.4l2.3 2.3 4.5-4.9" fill="none" stroke="var(--card)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
function pane(s, data) {
  if (!s || s.error || !s.quick || !s.os) return null;
  const rows = s.rows.map(r => effRow(r, data.remote)).map(view);
  const prefs = rows.filter(r => r.stage === 'prefs'), rest = rows.filter(r => r.stage !== 'prefs');
  const reqRows = rest.filter(r => isReq(r) && !unsupported(r)), needs = reqRows.filter(r => r.state !== 'green'), ok = needs.length === 0;
  const others = rest.filter(r => !needs.includes(r)), li = r => unsupported(r) ? plainRow(r, 'no') : setupRow(r, true);
  const quickFirst = !ok && !prefs.some(r => r.state === 'green');                    // the card stays in view only while Quick setup has never been run
  const os = `<p class="osl" data-os="${esc(s.os.kind)}" aria-label="${esc(t('quick.osAria'))}" dir="auto">${esc(s.os.line)}</p>`;
  const details = `<div class="sdet"><button type="button" class="lnk sdetb" data-sdet aria-expanded="false" aria-controls="sdet-body">${esc(t('quick.details'))} <span class="sdetchev" aria-hidden="true">▸</span></button><div class="sdetbody" id="sdet-body" data-sdetbody hidden>${os}${quickFirst ? '' : quickCard(s.os)}<ul class="chks sall">${others.map(li).join('')}</ul></div></div>`;
  const fix = ok ? '' : `<section class="qn" aria-label="${esc(t('quick.needs'))}"><ul class="chks">${needs.map(li).join('')}</ul></section>${quickFirst ? quickCard(s.os) : ''}`;
  return { ok, icon: ok ? CHECK : '', header: ok ? t('quick.calmTitle') : t('quick.headerFix', { n: needs.length }), sub: ok ? t('quick.calmSub') : t('setup.notReady'), body: fix + details };
}
const css = String.raw`.osl{margin:0 0 8px;font-size:11.5px;color:var(--mutt);overflow-wrap:anywhere}
.qs{margin:0 0 10px;padding:10px;border:1px solid var(--bd);border-radius:8px;background:var(--card);display:flex;flex-direction:column;gap:8px}.qsh{margin:0;font-size:13px;font-weight:600}.qs p{margin:0}
.qsf{border:0;margin:0;padding:0;display:flex;flex-direction:column;gap:4px;min-width:0}.qsf legend{padding:0;font-size:11.5px;color:var(--mutt)}.qsg{display:flex;flex-wrap:wrap;gap:4px}
.qso{display:inline-flex;align-items:center;gap:6px;min-height:26px;padding:2px 8px;border:1px solid var(--bd);border-radius:6px;font-size:12px;cursor:pointer}.qso:has(input:checked){border-color:var(--acc);background:var(--acc-soft)}.qso input{margin:0;flex:none}.qsr{font-size:10.5px;color:var(--acct)}
.qso:focus-within{outline:2px solid var(--acc);outline-offset:1px}.qsb{grid-template-columns:minmax(0,1fr)}.qs .chcmd{user-select:all}
.qn{margin:0 0 10px}.qn .chks{margin:6px 0 0}.shead .scalm{display:inline-flex;align-items:center;gap:6px;color:var(--okt)}.scalmi{flex:none}
.sdet{margin:8px 0 10px}.sdet .sdetb.lnk{position:relative;display:inline-flex;align-items:center;height:24px;min-height:24px;min-width:24px;margin-inline-start:-5px;padding-inline-end:20px}.sdetchev{position:absolute;top:50%;inset-inline-end:6px;margin-top:-.5em;line-height:1;text-decoration:none;transition:transform .15s ease-out}.sdetb[aria-expanded=true] .sdetchev{transform:rotate(90deg)}
.sdetb:focus-visible{outline:2px solid var(--acc);outline-offset:1px}.sdetbody{margin-top:8px}.sdetbody .qs{margin-top:0}.sdetbody .sall{margin:0}
@media (prefers-reduced-motion:reduce){.sdetchev{transition:none}}
body.vscode-high-contrast .qs,body.vscode-high-contrast .qso{border:1px solid var(--vscode-contrastBorder,currentColor)}`;
// the page script: the five choices build the command text live (the same words the extension re-checks); the choices are kept across redraws in vscode.setState; typing posts editing so the panel does not redraw
const clientJs = String.raw`// ---- Setup Details button (aria-expanded; closed by default; the choice is kept in vscode.setState)
{ const b = document.querySelector('[data-sdet]'), body = b && document.getElementById(b.getAttribute('aria-controls')); if (b && body) { const set = on => { b.setAttribute('aria-expanded', on ? 'true' : 'false'); body.hidden = !on; }; set(!!S.sdet); b.addEventListener('click', () => { const on = b.getAttribute('aria-expanded') !== 'true'; set(on); if (on) S.sdet = 1; else delete S.sdet; vscode.setState(S); }); } }
// ---- Quick setup card (Setup tab): live command text, choices kept in vscode.setState, one message to the extension
function qsRead() { const o = {}; document.querySelectorAll('[data-qs]').forEach(n => { const k = n.dataset.qs; if (n.type === 'radio') { if (n.checked) o[k] = n.value; } else if (n.type === 'text') o[k] = n.value.trim(); }); return o; }
function qsCmd(o) { return 'shipm init --prefs --lang ' + o.lang + ' --folder ' + o.folder + ' --autonomy ' + o.autonomy + (o.awake ? ' --awake ' + o.awake : '') + ' --notify ' + o.notify; }
function qsShow() { const c = document.querySelector('[data-qscmd]'); if (!c) return; const o = qsRead(); c.textContent = qsCmd(o); S.qs = o; vscode.setState(S); }
if (document.querySelector('[data-qscmd]')) {
  const sv = S.qs || {}; document.querySelectorAll('[data-qs]').forEach(n => { const k = n.dataset.qs; if (sv[k] == null) return; if (n.type === 'radio') n.checked = n.value === sv[k]; else if (n.type === 'text') n.value = sv[k]; });
  qsShow();
  document.addEventListener('change', e => { if (e.target.closest && e.target.closest('[data-qs]')) qsShow(); });
  document.addEventListener('input', e => { if (e.target.closest && e.target.closest('[data-qs][type="text"]')) qsShow(); });
  document.addEventListener('focusin', e => { if (e.target.closest && e.target.closest('[data-qs][type="text"]')) vscode.postMessage({ type: 'editing', on: true }); });
  document.addEventListener('focusout', e => { if (e.target.closest && e.target.closest('[data-qs][type="text"]')) vscode.postMessage({ type: 'editing', on: false }); });
}`;
return { pane, css, clientJs };
};
