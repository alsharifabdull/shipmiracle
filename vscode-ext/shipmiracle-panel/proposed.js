// Proposed assets (F5, Learn stage): `shipm report panel` -> proposed_assets [{path, why, stage, cr}], at most 3. The panel only SHOWS them: path and why as plain text, and the one command the owner
// may run in a terminal (`shipm playbook asset add ...`) as text to copy. Nothing here runs it; the engine refuses it from a chat. The command is BUILT here from the cleaned fields (never taken from the
// data, a second pass can only withhold one): only a path of the engine's own safe shape and a known stage get one, the purpose is a single-quoted word list without quotes, markup or backticks. Pure Node, no vscode.
const DETAIL = require('./detail');
const STAGES = ['scope', 'plan', 'approve', 'do', 'verify', 'review', 'deliver'];
const SAFE_PATH = /^[A-Za-z0-9][A-Za-z0-9._\/-]{0,118}[A-Za-z0-9_]$/;          // the engine's own rule (toolbox.py _SAFE_PATH)
const NAME = /^[A-Za-z0-9._-]{1,100}$/;
const CMD = /^shipm playbook asset add [A-Za-z0-9][A-Za-z0-9._\/-]{0,118}[A-Za-z0-9_] --stage [a-z]{2,10} --purpose '[^'\u0000-\u001f\u007f-\u009f]{0,200}'(?: --project [A-Za-z0-9._-]{1,100})?$/;
const MAX = 3;

function commandOf(path, why, stage, project) {
  if (!SAFE_PATH.test(path) || path.split('/').includes('..') || !STAGES.includes(stage)) return '';
  const purpose = String(why).replace(/[<>`'"\\$]/g, '').replace(/\s+/g, ' ').trim().slice(0, 100);
  const proj = typeof project === 'string' && NAME.test(project) && !project.startsWith('-') ? ' --project ' + project : '';
  const c = `shipm playbook asset add ${path} --stage ${stage} --purpose '${purpose}'${proj}`;
  return CMD.test(c) ? c : '';
}
// -> [{path, why, stage, command}] (command '' when none may be offered). `rows` is untrusted: anything unexpected is dropped.
function clean(rows, project) {
  if (!Array.isArray(rows)) return [];
  const out = [];
  for (const r of rows) {
    if (out.length >= MAX) break;
    if (!r || typeof r !== 'object' || typeof r.path !== 'string' || !r.path) continue;
    const rawPath = r.path.slice(0, 300), path = DETAIL.sanitize(rawPath, 200), why = DETAIL.sanitize(typeof r.why === 'string' ? r.why : '', 160);
    const stage = typeof r.stage === 'string' && /^[a-z]{2,10}$/.test(r.stage) ? r.stage : '';
    out.push({ path, why, stage, command: path === rawPath && r.command !== '' ? commandOf(path, why, stage, project) : '' });   // an earlier pass that withheld the command (the path was changed by cleaning) stays withheld
  }
  return out;
}
module.exports = { clean, commandOf, CMD, MAX };
