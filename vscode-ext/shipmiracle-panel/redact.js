// Best-effort masking of secret-shaped text (UX addendum 5f). Pure Node, no I/O. NOT a guarantee: it hides what looks like a secret and leaves ordinary text alone.
// Every pass is LINEAR in the input: no unanchored open-ended quantifier is ever restarted at each position (the key/value pass is a scanner with 64-character windows, the other
// regexes have bounded quantifiers or consume what they match), and sanitize() in detail.js cuts the input to the display limit plus slack BEFORE these passes run.
// Hidden: PEM private keys, URL passwords (also an empty user), Authorization / Proxy-Authorization / Cookie / Set-Cookie headers, curl -u user:pass, --password VALUE, mysql -pVALUE, Bearer values, JWTs,
// provider key prefixes (Stripe, Google, Slack, SendGrid, npm, PyPI, Twilio, Azure client secrets, AWS, GitHub, Anthropic / OpenAI style) also inside identifiers, values of any key whose NAME contains
// token / secret / password / passcode / pwd / api key / auth / credential / private key / access key (or is exactly pass / pw / pin / key / sig as a word part), prose "the password is X",
// and long standalone hex or base64-like blobs (also split in two lines). Letters from other scripts that look like Latin ones and full-width signs are folded before matching.
// Kept: UUIDs after non-secret words, paths and file names, lowercase dash-joined names with a version, identifiers under 40 characters, git SHAs after commit / sha / sha256 / @ / a backtick, prose.
const HIDDEN = '[hidden]';

// ---- folding: a 1:1 (same length) skeleton of the text for matching, so indexes carry over to the original
const CONF = new Map();
{ const add = (to, codes) => codes.forEach(c => CONF.set(c, to));
  add('a', [0x430, 0x3b1]); add('c', [0x441]); add('e', [0x435, 0x3b5]); add('o', [0x43e, 0x3bf]); add('p', [0x440, 0x3c1]); add('x', [0x445]); add('y', [0x443]); add('i', [0x456, 0x3b9]); add('j', [0x458]);
  add('s', [0x455]); add('k', [0x43a, 0x3ba]); add('d', [0x501]); add('h', [0x4bb]); add('q', [0x51b]); add('w', [0x51d]); add('t', [0x3c4]); add('u', [0x3c5]); add('v', [0x3bd]);
  add('A', [0x410, 0x391]); add('B', [0x412, 0x392]); add('E', [0x415, 0x395]); add('K', [0x41a, 0x39a]); add('M', [0x41c, 0x39c]); add('H', [0x41d, 0x397]); add('O', [0x41e, 0x39f]); add('P', [0x420, 0x3a1]);
  add('C', [0x421]); add('T', [0x422, 0x3a4]); add('X', [0x425, 0x3a7]); add('I', [0x406, 0x399]); add('J', [0x408]); add('S', [0x405]); add('Z', [0x396]); add('N', [0x39d]); add('Y', [0x3a5]); }
function skeleton(s) {
  let o = '';
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c >= 0xff01 && c <= 0xff5e) o += String.fromCharCode(c - 0xfee0);        // full-width ASCII (the full-width equals sign too)
    else if (c < 128) o += (c >= 65 && c <= 90) ? String.fromCharCode(c + 32) : s[i];   // lower-cased ASCII
    else { const m = CONF.get(c); o += m ? (m.toLowerCase()) : s[i]; }
  }
  return o;
}

// ---- passes that are plain regexes with bounded quantifiers
const PEM = /-----BEGIN [A-Z ]{0,40}PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]{0,40}PRIVATE KEY-----|$)/g;
const URL_USER = /\b([A-Za-z][A-Za-z0-9+.-]{0,20}:\/\/)[^\s\/@:]{0,100}:[^\s\/@]{1,200}@/g;
const AUTH_HDR = /\b((?:Proxy-)?Authorization)(\s{0,2}[:=]\s{0,2})(?:"[^"]{0,500}"|'[^']{0,500}'|[A-Za-z]{1,30}\s[^\s,;]{1,500}(?:,\s?[^\s,;]{1,500}){0,10}|[^\s,;]{1,500})/gi;
const COOKIE = /\b((?:Set-)?Cookie)(\s{0,2}:\s{0,2})(?:[\w.%-]{1,64}(?:=[^\s;]{0,500})?;?\s?){1,40}/gi;
const CURL_U = /(\s(?:-u|--user)\s{1,2})[^\s:]{1,64}:\S{1,200}/g;
const CLI_FLAG = /(--(?:password|passwd|pass|passphrase|passcode|token|registration-token|secret|api-?key|access-?key|auth-?token)(?:=|\s))(?:'[^']{1,300}'|"[^"]{1,300}"|\S{1,300})/gi;
const MYSQL_P = /(\bmysql(?:dump|admin)?\b[^|;&\n]{0,200}?\s-p)\S{1,200}/g;
const PW_FLAG = /(\b(?:docker|podman)\s+login\b[^|;&\n]{0,200}?\s-p\s{1,2}|\bsshpass\b[^|;&\n]{0,60}?\s-p\s{0,2})(?:'[^']{1,200}'|"[^"]{1,200}"|\S{1,200})/g;
const TF_VAR = /(\bvariable\s+"[^"]{0,64}(?:pass|secret|token|key|credential|pwd)[^"]{0,64}"\s*\{[^}]{0,200}?\bdefault\s*=\s*)(?:"[^"]{1,300}"|'[^']{1,300}')/gi;
const XML_ADD = /(\bkey\s*=\s*"[^"]{0,64}(?:pass|secret|token|key|credential|pwd)[^"]{0,64}"\s+value\s*=\s*)"[^"]{1,300}"/gi;
const XML_EL = /(<((?:[A-Za-z_][\w.-]{0,64})?(?:passw|secret|token|pwd|credential|apikey|api_key|private_key|access_key)[\w.-]{0,64})>)[^<]{1,300}(?=<\/)/gi;
const PGPASS = /\b([A-Za-z0-9._-]{1,64}:[0-9]{2,5}:[A-Za-z0-9_*-]{1,64}:[A-Za-z0-9_*-]{1,64}:)[^\s:]{4,200}/g;
const SENTRY = /(https?:\/\/)[0-9a-f]{32}(@)/g;
const BEARER = /\bBearer\s{1,2}[A-Za-z0-9._~+\/=-]{8,500}/gi;
const JWT = /\beyJ[A-Za-z0-9_-]{0,4000}\.[A-Za-z0-9_-]{1,4000}\.[A-Za-z0-9_-]{0,4000}/g;
const NB = '(?<![A-Za-z0-9])';
const PREFIXES = [`${NB}sk-ant-[A-Za-z0-9_-]{6,256}`, `${NB}sk-[A-Za-z0-9_-]{16,256}`, `${NB}[sr]k_(?:live|test)_[A-Za-z0-9]{10,256}`, `${NB}pk_(?:live|test)_[A-Za-z0-9]{10,256}`, `${NB}whsec_[A-Za-z0-9]{16,256}`,
  `${NB}gh[pousr]_[A-Za-z0-9]{16,256}`, `${NB}github_pat_[A-Za-z0-9_]{16,256}`, `${NB}AKIA[0-9A-Z]{12,64}`, `${NB}ASIA[0-9A-Z]{12,64}`, `${NB}AIza[0-9A-Za-z_-]{30,128}`, `${NB}ya29\\.[A-Za-z0-9_-]{20,512}`,
  `${NB}xox[baprs]-[A-Za-z0-9-]{8,256}`, `hooks\\.slack\\.com/services/[A-Za-z0-9/]{10,256}`, `${NB}SG\\.[A-Za-z0-9_-]{16,128}\\.[A-Za-z0-9_-]{16,128}`, `${NB}npm_[A-Za-z0-9]{30,128}`, `${NB}pypi-[A-Za-z0-9_-]{30,512}`,
  `${NB}AC[0-9a-f]{32}(?![0-9a-f])`, `${NB}glpat-[A-Za-z0-9_-]{20,128}`, `${NB}GR1[0-9A-Za-z]{20,64}`, `${NB}SK[0-9a-f]{32}(?![0-9a-f])`, `${NB}hf_[A-Za-z0-9]{30,128}`, `${NB}sh(?:pat|pca|pss|ppa)_[0-9a-f]{32}`, `${NB}dop_v1_[0-9a-f]{64}`, `${NB}hv[sb]\\.[A-Za-z0-9_-]{20,256}`,
  `${NB}(?:bot)?[0-9]{6,12}:AA[A-Za-z0-9_-]{30,64}`, '\\$apr1\\$[./A-Za-z0-9$]{8,128}', '\\$2[abxy]?\\$[0-9]{2}\\$[./A-Za-z0-9]{40,64}', '\\$[156y]\\$[./A-Za-z0-9$]{10,256}', `${NB}[A-Za-z0-9]{8}~[A-Za-z0-9_.~-]{20,200}`].map(r => new RegExp(r, 'g'));

// ---- key / value scanner (linear: every candidate looks at most 64 characters left and right)
const STRONG = /token|secret|passw(?:or)?d|passphrase|passcode|pwd|api[_-]?key|apikey|(?<![a-z])auth(?![a-z])|credential|private[_-]?key|access[_-]?key|signature|كلمة السر|كلمة المرور|الرقم السري|توكن/g;
const WEAK = /(?<![a-z0-9])(?:pass|pw|pin|key|sig|psk)(?![a-z0-9])|رمز|مفتاح/g;
const isId = c => (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c === '_' || c === '.' || c === '-';
const secretish = v => v.length >= 8 && (/[0-9]/.test(v) || /[^A-Za-z]/.test(v) || (/[a-z]/.test(v) && /[A-Z]/.test(v) && v.length >= 12));
const proseSecretish = v => (v.length >= 4 && /[0-9!@#$%^&*]/.test(v)) || (v.length >= 8 && /[a-z]/.test(v) && /[A-Z]/.test(v));
const STOP = new Set([' ', '"', "'", ',', ';', '&', ')', ']', '}', '>', '\t', '|', '<']);
const STOPWORDS = new Set(('is are was were be been being the a an and or not no yes ok okay none null nil true false undefined must should shall may can could will would does do did has have had if when then else to for in of on at by with without your you my our their his her its we it this that these those too very more less most field input hash policy reset required requirement requirements protected manager page link email flow form strength change changed update updated rule rules length expires expired expiry wrong correct invalid valid incorrect strong weak empty missing here there below above before after only also both each any all new old current previous same different one two first last next using used use set sets stored store storage saved save entry entered enter prompt prompted hint hints box text label placeholder reminder recovery generator generated default defaults example examples sample file files list lists config configuration setting settings value values from into onto via per about as so but than because during until while through under over upon within between among against after before since like unlike near off out up down again once always never often sometimes already still yet just even ever really actually please thanks thank ask asks asked asking forgot forget forgotten remember remembers hashing check checks mismatch confirmation rotation leak login minimum maximum validation validator complexity history').split(' '));
const NAMEISH = /^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*){1,6}$/;          // member expression: process.env.API_KEY, config.db.user
// a value that is CODE, not a secret: a literal word, a member expression, a call, a shell variable, structure or a regex (starts with { [ ( \ / < $)
function codeLike(val, secretKey) {
  if (secretKey && /[A-Za-z0-9]{20,}/.test(val)) return false;                      // a secret-named key with a long alphanumeric value: not code, whatever it looks like (VAULT_TOKEN=s.GbWxy...)
  if (/^(?:null|true|false|undefined|nil|None|True|False|NULL)$/.test(val)) return true;
  if (/^[{[(\\\/<$]/.test(val)) return true;
  if (/^[A-Za-z_$][\w$.]*\(/.test(val)) return true;                            // a call: z.string().min(8)
  if (NAMEISH.test(val) && /[a-z]/.test(val) && val.split('.').every(x => x.length <= 40 && !(x.length >= 12 && /[A-Z]/.test(x) && /[a-z]/.test(x) && /\d/.test(x)))) return true;      // a member expression of ordinary names (a random-looking part is a secret: s.GbW1G1TW...)
  return false;
}
function keyvalPass(orig) {
  const low = skeleton(orig), n = orig.length, hits = [];
  for (const re of [STRONG, WEAK]) { re.lastIndex = 0; let m; while ((m = re.exec(low)) !== null) { hits.push([m.index, m.index + m[0].length, re === WEAK]); if (m[0].length === 0) re.lastIndex++; } }
  hits.sort((a, b) => a[0] - b[0]);
  const out = []; let pos = 0;
  for (const [i0, i1, weak] of hits) {
    if (i0 < pos) continue;
    let s = i0, e = i1;
    while (s > pos && i0 - s < 64 && isId(low[s - 1])) s--;
    while (e < n && e - i1 < 64 && isId(low[e])) e++;
    let j = e, keyQuoted = false;
    if (low[j] === '"' || low[j] === "'") { keyQuoted = true; j++; }
    let k = j; while (k < n && k - j < 3 && low[k] === ' ') k++;
    let sep = '';
    if (low.startsWith('=>', k)) sep = '=>'; else if (low.startsWith(':=', k)) sep = ':='; else if (low[k] === '=') sep = '='; else if (low[k] === ':') sep = ':'; else if (low[k] === '|') sep = '|';           // a markdown table cell: | api_token | VALUE |
    const sp = !sep && !keyQuoted && k > e && e - s === i1 - i0 && /^(?:passw(?:or)?d|passphrase|pwd|psk)$/.test(low.slice(i0, i1)) && /^ {1,2}\S/.test(low.slice(e, e + 3)) && !/^ {1,2}(?:is|are|was|=)( |$)/.test(low.slice(e, e + 6));      // ssh config: Password VALUE
    let prose = false;
    if (sp) { sep = ' '; k = e + 1; while (k < n && low[k] === ' ') k++; }
    if (!sep) {                                                                   // prose: "the password is X" / "my token is \"X\""
      const m = /^ {1,2}(?:is|are|was|=) {1,2}/.exec(low.slice(e, e + 12));
      if (!m || keyQuoted || e - s !== i1 - i0) continue;
      prose = true; k = e + m[0].length;
    } else if (sep !== ' ') k += sep.length;
    while (k < n && k - j < 8 && low[k] === ' ') k++;
    let v0 = k, v1;
    const q = orig[v0];
    if (q === '"' || q === "'") { const close = orig.indexOf(q, v0 + 1); v1 = close >= 0 && close - v0 <= 500 ? close + 1 : Math.min(n, v0 + 200); }
    else { v1 = v0; while (v1 < n && v1 - v0 < 300 && !STOP.has(orig[v1])) v1++; }
    if (orig.startsWith(HIDDEN, v0)) continue;                                    // already masked (the page cleans the text a second time)
    const val = orig.slice(v0, v1); if (!val) continue;
    const quoted = q === '"' || q === "'", xhdr = low.slice(s, s + 2) === 'x-';
    if (!quoted && !prose && sep !== ' ' && (val.endsWith(':') || (orig[v1] === ':' && /^[A-Za-z_][\w.-]*$/.test(val)))) continue;      // a PARENT key (auth: / credentials: / secrets:): its nested key is the next hit and hides its own value
    const keyName = low.slice(s, e), sigKey = keyName === 'sig' || keyName === 'signature', secretKey = !weak;
    if (!quoted && !prose && !sigKey && codeLike(val, secretKey)) continue;                                                                                    // code, not a secret: process.env.X, null, z.string().min(8), {...}, regex
    if (!quoted && !prose && sep === '=' && /^[A-Z][a-z]+$/.test(val) && !/(?:\.|_)value$/.test(keyName)) {                                  // properties files: label.password=Password / errors.token.expired=Your session token has expired
      const word = low.slice(i0, i1), after = orig.slice(v1, v1 + 40);
      if (val.toLowerCase() === word || /^ [a-z]{2,}/.test(after)) continue;
    }
    let hide;
    if (prose) hide = quoted || proseSecretish(val);
    else if (sep === ' ') hide = (val.length >= 8 && /[0-9!@#$%^&*]/.test(val)) || (val.length >= 4 && !STOPWORDS.has(val.toLowerCase().replace(/[.,;:!?]+$/, '')));      // netrc / ssh config: password VALUE (a plain word counts unless it is an ordinary one)
    else if (sep === ':' || sep === '|') hide = keyQuoted || quoted || xhdr || secretish(val) ? (!weak || val.length >= 6) : (/^(?:passw(?:or)?d|passcode|pwd)$/.test(low.slice(i0, i1)) && e === i1 && val.length >= 4 && !STOPWORDS.has(val.toLowerCase().replace(/[.,;:!?]+$/, '')));
    else hide = !weak || val.length >= 6;                                         // = => :=  always for a strong key; a weak one (pass, pw, pin, key, sig) needs a value of 6+
    if (!hide) continue;
    out.push(orig.slice(pos, v0), HIDDEN); pos = v1;
  }
  if (!out.length) return orig;
  out.push(orig.slice(pos)); return out.join('');
}

// ---- blobs
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const GIT_BEFORE = /(?:commit |sha\d{0,3}[:=]? ?|@|`)$/i;
const randomSeg = x => x.length >= 16 && ((/[A-Z]/.test(x) && /[a-z]/.test(x) && /\d/.test(x)) || /^\d+$/.test(x));
function exempt(run) {                                                           // ordinary-looking long runs that are NOT secrets
  if (UUID.test(run)) return true;
  if (/\.[A-Za-z][A-Za-z0-9]{0,4}$/.test(run)) return true;                       // a file name
  if (run.includes('/') && !run.includes('+') && !/=$/.test(run)) { const segs = run.split('/').filter(Boolean), ok = x => /^\.?[a-z][a-z_-]{2,30}(?:\.[a-z0-9]{1,5})?$/.test(x);      // a path: no + and no trailing =, ordinary segments, and at least half of them recognizable names (dir words or name.ext)
    if (segs.length && segs.every(x => x.length <= 64 && !randomSeg(x)) && segs.filter(ok).length * 2 >= segs.length) return true; }
  const parts = run.split(/[-_.]/);
  if (parts.length >= 3 && parts.every(x => /^[A-Za-z]{1,16}$/.test(x) || /^\d{1,6}$/.test(x))) return true;   // words and numbers joined by - _ .
  if (parts.length >= 3 && run === run.toLowerCase() && parts.every(x => /^[a-z0-9]{1,16}$/.test(x)) && parts.filter(x => /^[a-z]+$/.test(x)).length * 10 >= parts.length * 6) return true;   // lowercase names with a version: some-tool-name-v1.2.3
  return false;
}
const LABEL_BEFORE = /(?:etag|traceparent|trace[-_ ]?id|span[-_ ]?id|request[-_ ]?id|build[-_ ]?id|rev-parse|\bhead|commit|sha\d{0,3}|checksum|digest)(?:[:=\s"'>-]|->){0,6}$/i;
function verdict(run, off, whole) {                                              // true = hide
  if (run.length < 32 || exempt(run.length > 4096 ? run.slice(0, 4096) : run)) return false;                // the tests look at the first 4096 characters only (a longer run costs no more)
  if (LABEL_BEFORE.test(whole.slice(Math.max(0, off - 24), off))) return false;                    // an id or a digest that its label names (not a secret)
  if (/^[A-Fa-f0-9]+$/.test(run)) return !((run.length === 40 || run.length === 64) && /^[0-9a-f]+$/.test(run) && GIT_BEFORE.test(whole.slice(Math.max(0, off - 12), off)));
  if (/^[A-Za-z0-9_]+$/.test(run) && run.length < 40) return false;                // an identifier
  return /\d/.test(run) && /[A-Za-z]/.test(run);
}
function blobPass(t) {
  const ms = [...t.matchAll(/[A-Za-z0-9+\/_.-]{28,}=*/g)]; if (!ms.length) return t;
  const hide = new Array(ms.length).fill(false), tails = ms.map(m => (/[.]+$/.exec(m[0]) || [''])[0]);
  ms.forEach((m, i) => { const run = m[0].slice(0, m[0].length - tails[i].length); hide[i] = verdict(run, m.index, t); });
  for (let i = 0; i + 1 < ms.length; i++) {                                       // a base64 blob split across two lines (the cleaner turned the line break into one space)
    const a = ms[i], b = ms[i + 1];
    if (hide[i] && hide[i + 1]) continue;
    if (a.index + a[0].length + 1 !== b.index || t[a.index + a[0].length] !== ' ') continue;
    if (!/^[A-Za-z0-9+\/=]{28,}$/.test(a[0]) || !/^[A-Za-z0-9+\/=]{28,}$/.test(b[0])) continue;
    const both = a[0] + b[0]; if (/\d/.test(both) && /[a-z]/.test(both) && /[A-Z]/.test(both) && !exempt(both)) { hide[i] = true; hide[i + 1] = true; }
  }
  const out = []; let pos = 0;
  ms.forEach((m, i) => { if (!hide[i]) return; out.push(t.slice(pos, m.index), HIDDEN + tails[i]); pos = m.index + m[0].length; });
  out.push(t.slice(pos)); return out.join('');
}

function redact(s) {
  let t = String(s).replace(PEM, HIDDEN).replace(URL_USER, '$1' + HIDDEN + '@').replace(AUTH_HDR, (m, k, sep) => k + sep + HIDDEN).replace(COOKIE, (m, k, sep) => k + sep + HIDDEN);
  t = t.replace(CURL_U, '$1' + HIDDEN).replace(CLI_FLAG, '$1' + HIDDEN).replace(MYSQL_P, '$1' + HIDDEN).replace(PW_FLAG, '$1' + HIDDEN);
  t = t.replace(PGPASS, '$1' + HIDDEN).replace(SENTRY, '$1' + HIDDEN + '$2').replace(TF_VAR, '$1' + HIDDEN).replace(XML_ADD, '$1' + HIDDEN).replace(XML_EL, '$1' + HIDDEN);
  t = t.replace(BEARER, 'Bearer ' + HIDDEN).replace(JWT, HIDDEN);
  for (const re of PREFIXES) t = t.replace(re, HIDDEN);
  return blobPass(keyvalPass(t));
}
module.exports = { redact, skeleton, HIDDEN };
