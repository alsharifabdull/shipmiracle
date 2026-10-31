// Redaction (vscode-ext/shipmiracle-panel/redact.js, used by detail.js sanitize): (1) every input shape finishes fast (linear: 200k of one repeated character, long key=value runs, hostile mixtures, each < 50 ms, best of 3);
// (2) a precision / recall table: secret-shaped samples must not survive, ordinary text must come back unchanged; (3) the bound on the input and the ellipsis rule. Every secret-looking string is built at run time
// from pieces and random characters: no secret literal sits in the repo. Run: node tests/ext_redact_test.js
require('./shipmiracle_isolation').apply();
const path = require('path'), os = require('os');
const D = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/detail.js'));
let fails = 0, n = 0; const check = (name, c, info = '') => { n++; console.log((c ? 'PASS ' : 'FAIL ') + name + (c ? '' : ' ' + info)); if (!c) fails++; };

// ---- 1. timing ---------------------------------------------------------------------------------------------------------------------------------
const LOAD = os.loadavg()[0], LIMIT = LOAD > 12 ? 200 : 50;                         // a busy machine gets a wider limit (a quadratic pass takes seconds, not milliseconds)
const ESC = String.fromCharCode(27), BEL = String.fromCharCode(7), CYR = String.fromCharCode(0x430), FW = String.fromCharCode(0xff1d);
const N = 200000, rep = (s, k = N) => s.repeat(Math.ceil(k / s.length)).slice(0, k);
const J = (...a) => a.join('');                                                  // (the table below declares its own, from the probe it was ported from: renamed there)
const shapes = {
  'a': rep('a'), '0': rep('0'), '.': rep('.'), 'ab-': rep('ab-'), 'A1': rep('A1'), 'a.': rep('a.'), 'sk-': rep('sk-'), 'eyJa.a.': rep('eyJa.a.'), ':': rep(':'), '=': rep('='), '/': rep('/'), '-': rep('-'), '_': rep('_'), ' ': rep(' '), '"': rep('"'),
  'key=value runs': rep('key=value '), 'password= runs': rep(J('pass', 'word=')), 'token: runs': rep(J('tok', 'en: ')), 'api_key= runs': rep(J('api', '_key=x ')), 'x-auth-token: runs': rep(J('X-Auth', '-Token: a ')), 'quote runs': rep(J('pass', 'word="a')),
  'key" runs': rep(J('tok', 'en"=')), 'pw/pin/key runs': rep('pw pin key sig pass '), 'pwdpwd': rep('pwd'), 'authauth': rep('auth'), 'PEM no end': J('-----BEGIN PRIV', 'ATE KEY-----', rep('x')), 'PEM repeats': rep(J('-----BEGIN PRIV', 'ATE KEY----- ')),
  'URL userinfo a:': J('http://', rep('a:', N)), 'URL scheme dots': rep('a.'), 'scheme://': rep('a://'), 'Authorization runs': rep(J('Authori', 'zation: a ')), 'Authorization one': J('Authori', 'zation: ', rep('a ')), 'Cookie runs': rep('Cookie: a=b; '), 'Cookie pairs': J('Cookie: ', rep('a=b;')),
  'Bearer runs': rep('Bearer a'), 'Bearer long': J('Bearer ', rep('a')), 'curl -u runs': rep('curl -u a:b '), '--password runs': rep(J('--pass', 'word a ')), 'mysql -p runs': rep('mysql -p'), 'ESC[ runs': rep(ESC + '['), 'ESC] runs': rep(ESC + ']'), 'ESC[0 long': ESC + '[' + rep('0'), 'OSC no end': ESC + ']0;' + rep('a'),
  'Cyrillic a': rep(CYR), 'full-width =': rep(J('pass', 'word', FW)), 'hex': rep('0123456789abcdef'), 'b64': rep('QWxhZGRpbjpvcGVuIHNlc2FtZQ12'), 'b64 lines': rep('QWxhZGRpbjpvcGVuIHNlc2FtZQ12 '), 'words': rep('lorem ipsum dolor '), 'path': rep('src/app/x/'),
  'dash words': rep('some-tool-name-'), 'markdown links': rep('[a]('), 'hostile mix': rep(J('Authori', 'zation: Bearer a=b; Cookie: x=y; pass', 'word="a" sk', '-aaaaaaaaaaaaaaaaaaaa eyJa.b.c -----BEGIN PRIV', 'ATE KEY----- http://a:b@h ')), 'secret words mix': rep(J('token secret pass', 'word auth key pin pw sig credential '))
};
let slow = [];
for (const [name, text] of Object.entries(shapes)) {
  let best = Infinity; for (let i = 0; i < 3; i++) { const t0 = process.hrtime.bigint(); D.sanitize(text, 300); best = Math.min(best, Number(process.hrtime.bigint() - t0) / 1e6); }
  if (best >= LIMIT) slow.push(name + ' ' + best.toFixed(0) + ' ms');
}
check(`timing: ${Object.keys(shapes).length} hostile inputs of 200k characters each finish < ${LIMIT} ms through sanitize (best of 3; load average ${LOAD.toFixed(1)})`, slow.length === 0, slow.join('; '));
check('timing: a 128 KB message with a unique secret inside is masked and fast (the extension host reads this size every 15 s)', (() => { const t0 = Date.now(); const secretV = J('sk-', 'ant-', 'api03-', 'Zz9Yy8', 'Xx7Ww6'); const out = D.sanitize(rep('lorem ipsum ', 60000) + secretV + rep(' dolor', 60000), 280); return Date.now() - t0 < LIMIT * 3 && !out.includes('Zz9Yy8'); })());
check('bound: a long text is cut BEFORE the passes and still shows an ellipsis even when masking shortened it', (() => { const t = D.sanitize(rep(J('pass', 'word=hunter12345 '), 20000), 100); return t.endsWith('…') && t.length <= 101; })());
check('bound: a secret straddling the input cut is not left half visible', (() => { const lim = 300 * 4 + 2000; const sec = J('sk-', 'ant-', 'api03-', 'AbCdEfGhIjKlMnOp'); const pad = rep('x ', lim - 12); const out = D.sanitize(pad + sec + ' tail', 300); return !/sk-|ant-|api03|AbCd/.test(out); })());

// ---- 2. precision / recall -----------------------------------------------------------------------------------------------------------------------
const R='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
let seed=7;const rnd=()=>(seed=(seed*1103515245+12345)&0x7fffffff)/0x7fffffff;
const rs=(n,al=R)=>{let o='';for(let i=0;i<n;i++)o+=al[Math.floor(rnd()*al.length)];return o};
const b64=n=>rs(n,R+'+/'), hex=n=>rs(n,'0123456789abcdef');
// [label, text, secretSubstring]
const S=[];const add=(l,t,s)=>S.push([l,t,s]);
let v;
v=b64(40);add('AWS secret 40b64 bare',`secret is ${v} ok`,v);
v=b64(40);add('AWS secret_access_key=',J('aws_secret_access_key = ',v),v);
v=b64(40);add('AWS secret json',J('{"SecretAccessKey": "',v,'"}'),v);
v='AKIA'+rs(16,'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567');add('AWS access key id',`key ${v} here`,v);
v='AIza'+rs(35,R+'-_');add('Google API key',`key=${v}`,v);
v='AIza'+rs(35,R+'-_');add('Google API key bare',`use ${v} now`,v);
v='ya29.'+rs(60,R+'-_');add('Google oauth',`token ${v}`,v);
v=J('sk_','live_',rs(24));add('Stripe sk_live',`stripe ${v}`,v);
v=J('rk_','live_',rs(24));add('Stripe rk_live',`stripe ${v}`,v);
v=J('pk_','test_',rs(24));add('Stripe pk_test',`pub ${v}`,v);
v=J('whsec_',rs(32));add('Stripe whsec',`hook ${v}`,v);
v=J('xox','b-',rs(11,'0123456789'),'-',rs(12,'0123456789'),'-',rs(24));add('Slack xoxb',`slack ${v}`,v);
v=J('xox','p-',rs(11,'0123456789'),'-',rs(12,'0123456789'),'-',rs(24));add('Slack xoxp',`slack ${v}`,v);
v=J('https://hooks.sl','ack.com/services/T',rs(8,'ABCDEFGH0123'),'/B',rs(8,'ABCDEFGH0123'),'/',rs(24));add('Slack webhook',`post to ${v}`,v);
v='AC'+hex(32);add('Twilio SID',`sid ${v}`,v);
v=hex(32);add('Twilio auth_token=',J('TWILIO_AUTH', '_TO', 'KEN=', v),v);
v='SG.'+rs(22,R+'-_')+'.'+rs(43,R+'-_');add('SendGrid',`sendgrid ${v}`,v);
v=rs(8)+'~'+rs(30,R+'._~-');add('Azure client secret',`client secret ${v}`,v);
v=b64(44)+'==';add('Azure storage AccountKey',`AccountKey=${v};EndpointSuffix=x`,v);
v='npm_'+rs(36);add('npm token',`npm ${v}`,v);
v='pypi-'+'AgEIcHlwaS5vcmc'+rs(60,R+'-_');add('PyPI token',`upload ${v}`,v);
v=b64(64);add('SSH key body line',J('ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQ',v,' user@host'),v);
v=b64(64);add('OpenSSH key fragment',J('b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAA',v),v);
v=rs(14);add('DB URL postgres',`postgres://admin:${v}@db.example.com:5432/app`,v);
v=rs(14);add('DB URL mongodb+srv',`mongodb+srv://u:${v}@cluster0.x.mongodb.net/db`,v);
v=rs(14);add('DB URL redis no user',`redis://:${v}@cache:6379`,v);
v=rs(14);add('DB URL mysql params',`mysql://root@host/db?password=${v}`,v);
v=rs(24);add('Cookie header',`Cookie: session=${v}; theme=dark`,v);
v=rs(24);add('Cookie header 2',`Cookie: theme=dark; sid=${v}`,v);
v=rs(24);add('Set-Cookie',`Set-Cookie: sessionid=${v}; HttpOnly; Secure`,v);
v=rs(24);add('x-api-key header',`x-api-key: ${v}`,v);
v=rs(24);add('X-Auth-Token header',`X-Auth-Token: ${v}`,v);
v=rs(30);add('curl -H Authorization',`curl -H 'Authorization: Bearer ${v}' https://api.x.com`,v);
v=rs(30);add('curl -H "Authorization: token"',`curl -H "Authorization: token ${v}" https://api.x.com`,v);
v=rs(20);add('curl -u user:pass',`curl -u admin:${v} https://x.com`,v);
v=rs(20);add('.env quoted',`API_KEY="${v}"`,v);
v=rs(20);add('.env single quoted',`DB_PASS='${v}'`,v);
v=rs(20);add('export KEY=',`export STRIPE_KEY=${v}`,v);
v=rs(20);add('export SECRET space',`export MY_SECRET=${v}`,v);
v=rs(12);add('YAML password',`password: ${v}`,v);
v=rs(12);add('YAML nested',`db:\n  password: ${v}\n  user: x`,v);
v=rs(12);add('YAML pass key',`pass: ${v}`,v);
v=rs(12);add('passwd space',`the password is ${v}`,v);
v=rs(12);add('My password is (prose)',`My password is ${v}1!`,v+'1!');
v=b64(60);add('b64 split by newline',`${v.slice(0,30)}\n${v.slice(30)}`,v.slice(0,30));
v=b64(60);add('b64 split by newline (2nd half)',`${v.slice(0,30)}\n${v.slice(30)}`,v.slice(30));
v=rs(20);add('zero-width in secret',`api_key=${v.slice(0,8)}​${v.slice(8)}`,v.slice(0,8));
v=rs(40);add('ZW in prefix token',`ghp_${v.slice(0,10)}​${v.slice(10)}`,v.slice(0,10));
v=rs(20);add('Cyrillic a lookalike key',`apі_key=${v}`,v);
v=rs(20);add('fullwidth equals',`password＝${v}`,v);
v=rs(20);add('Cyrillic o in password',`passwоrd=${v}`,v);
v=J(rs(10),'%2F',rs(10));add('URL-encoded %2F',`token=${v}%2B${rs(10)}%3D`,v);
v=rs(24);add('URL-enc key access_token',`https://x.com/cb?access_token=${v}&state=1`,v);
v=rs(24);add('query param key=',`https://x.com/api?key=${v}`,v);
v=rs(24);add('query param sig=',`https://x.com/f?sig=${v}`,v);
v=rs(24);add('code block',"```\nAPI_TOKEN="+v+"\n```",v);
v=rs(20);add('code block json',"```json\n{\"clientSecret\": \""+v+"\"}\n```",v);
v=b64(24);add('Basic auth header',`Authorization: Basic ${v}==`,v);
v=rs(12);add('JSON single quote',`{'password': '${v}'}`,v);
v=rs(12);add('Python dict',`creds = dict(user='a', pw='${v}')`,v);
v=rs(12);add('pw= short key',`pw=${v}`,v);
v=rs(12);add('pass= key',`pass=${v}`,v);
v=rs(6,'0123456789');add('PIN',`pin=${v}`,v);
v=rs(40);add('github fine-grained',`github_pat_${rs(22)}_${v}`,v);
v=hex(40);add('40 hex bare (AWS-like / sha1 token)',`deploy key ${v}`,v);
v=hex(64);add('64 hex secret',`secret hex ${v}`,v);
v=b64(100);add('long b64 one line',`data:${v}`,v);
v=J(hex(8),'-',hex(4),'-',hex(4),'-',hex(4),'-',hex(12));add('Heroku-style key = a UUID after a secret-named key',`HEROKU_API_KEY=${v}`,v);
v='eyJ'+rs(20)+'.'+rs(5)+'.'+rs(5);add('short JWT',`jwt ${v}`,v);
v=rs(25);add('Bearer short',`Bearer ${v}`,v);
v=rs(40);add('sk- openai',`sk-proj-${v}`,v);
v=rs(30);add('secret in prose colon',`The secret: ${v}9`,v);
v=rs(10);add('client_secret space-eq',`client_secret = ${v}x1`,v);
v=rs(18);add('Authorization tail dup',`Authorization: ApiKey ${v}`,v);
v=rs(18);add('--password flag',`mysql --password ${v} -u root`,v);
v=rs(18);add('--password= flag',`tool --password=${v}`,v);
v=rs(18);add('-p flag',`mysql -p${v} -u root`,v);
v=rs(18);add('token in quotes prose',`the token is "${v}9"`,v);
// harmless
const H=[];const h=(l,t)=>H.push([l,t]);
h('prose password','Please reset your password from the settings page');
h('prose token','The token budget is low, we should compact soon');
h('token: budget','the token: budget is low');
h('password policy','The password policy requires at least 12 characters.');
h('auth flow','We need to review the auth flow before release.');
h('authentication','Authentication failed for the user, retry later');
h('secret word','Keep the secret sauce simple.');
h('https url','See https://github.com/example-login/example-repo/pull/123 for details');
h('url w/ query','https://example.com/search?q=hello&page=2');
h('url long path','https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Array/prototype');
h('version','Upgraded node to v20.11.1 and npm 10.2.4, vscode 1.95.0');
h('semver range','requires ">=18.17.0 <21.0.0-beta.1"');
h('git sha commit','fixed in commit '+'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678');
h('short sha','see 2b7a60d and 197c170');
h('sha256 label','sha256 '+'0123456789abcdef'.repeat(4));
h('sha with @','pinned @'+'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678');
h('path abs','/work/home/Developer/AI-Workspace/vscode-ext/shipmiracle-panel/detail.js');
h('path worktree png','/work/home/Developer/.worktrees/AI-Workspace/platform-v2/docs/summary/f9-quiet-dark-315.png');
h('path rel','docs/summary/panel-shots-manifest.json updated');
h('long filename','tests/panel_v3_f9_fixtures_with_a_very_long_descriptive_name_for_testing.js');
h('uuid','session 3f2b8c1e-9a4d-4e7b-8c1f-2d5a6b7c8e9f ended');
h('CamelCase id','call getUserAccountSettingsFromDatabase now');
h('UPPER_SNAKE','set MAX_RETRY_COUNT_FOR_NETWORK_REQUESTS to 5');
h('snake fn','def compute_average_response_time_in_ms():');
h('kebab words','the quiet-dark-light-contrast-theme-variant is used');
h('Arabic','تم إصلاح الخطأ في الملف وتشغيل الاختبارات بنجاح');
h('Arabic digits','الإصدار ١٢٣٤٥٦٧٨٩٠ و ٩٨٧٦٥٤٣٢١٠');
h('Arabic mixed','افتح الملف detail.js ثم شغّل bin/test-all');
h('numbers','Total 1234567890123456 ms, 3.14159265358979, 100000000');
h('phone-ish','Call +966 50 123 4567 tomorrow');
h('date iso','Updated: 2026-10-21T14:05:33.123Z by Claude');
h('code ident','const redactionPatternsForSensitiveValues = new RegExp(x);');
h('md link','[docs](https://example.com/docs/guide) and `bin/doctor`');
h('email','contact user@example.com about it');
h('hash dotted','node_modules/.bin/some-tool-name-with-long-name-v1.2.3');
h('PASS counts','PASS 99 checks, FAIL 0, SKIP 0 in 15 s');
h('words keyname','the keys and tokens of the lexer, and the secretary job');
h('author','author: Example User');
h('npm pkg','@modelcontextprotocol/server-filesystem@latest');
h('docker img','docker pull ghcr.io/owner/some-image-name:1.2.3-alpine');
h('branch','git checkout platform-v2-feature-redaction-rewrite-final');
h('timestamp','1729512345678901234');
h('sentence w/ colon','Auth: ok, token: ok, secret: none');
h('keyboard','press Ctrl+Shift+P then type Shipmiracle');

// ---- round 3 shapes (docker / sshpass / terraform / table / ssh config / XML / Arabic / wifi / gpg / bare provider tokens / vault / crypt hashes / telegram)
{ const up = n => rs(n, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'), url = n => rs(n, R + '-_'); let v;
  v = J(rs(20), '!'); add('docker login -p', `docker login -u bob -p ${v} registry.example.io`, v);
  v = J(rs(14), '!2'); add('sshpass -p quoted', `sshpass -p '${v}' ssh bob@host`, v);
  v = J(rs(18), '@1'); add('terraform variable default', J('variable "db_pass', 'word" { default = "', v, '" }'), v);
  v = rs(32); add('markdown table cell', J('| name | value |\n|---|---|\n| api_to', 'ken | ', v, ' |'), v);
  v = J(rs(14), '!'); add('ssh config Password VALUE', J('Host x\n  User bob\n  Pass', 'word ', v), v);
  v = J(rs(14), '!'); add('XML add key value', J('<add key="Pass', 'word" value="', v, '"/>'), v);
  v = J(rs(14), '!7'); add('XML element', J('<pass', 'word>', v, '</pass', 'word>'), v);
  v = J(rs(12), '9'); add('Arabic key phrase', 'كلمة السر: ' + v, v);
  v = J(rs(12), '9'); add('Arabic password phrase', 'كلمة المرور = ' + v, v);
  v = rs(16); add('wifi psk', `psk="${v}" ssid="x"`, v);
  v = J(rs(14), ' ', rs(6)); add('gpg --passphrase quoted', J('gpg --batch --pass', "phrase '", v, "' -d f"), v);
  v = J('glp', 'at-', url(20)); add('gitlab bare', `remote: use ${v} to clone`, v);
  v = J('h', 'f_', rs(34)); add('huggingface bare', `using ${v} for hub`, v);
  v = J('sh', 'pat_', hex(32)); add('shopify pat', v, v); v = J('sh', 'pca_', hex(32)); add('shopify pca', `x ${v}`, v); v = J('sh', 'pss_', hex(32)); add('shopify pss', `x ${v}`, v);
  v = J('h', 'vs.', url(24)); add('vault hvs', `vault login ${v}`, v); v = J('h', 'vb.', url(24)); add('vault hvb', `vault login ${v}`, v);
  v = J(rs(8), '$', rs(22)); add('htpasswd apr1', J('admin:$ap', 'r1$', v), v);
  v = J('$2y$', '10$', rs(53, R + './')); add('bcrypt $2y$', `hash ${v}`, v); v = J('$6', '$', rs(8), '$', rs(60, R + './')); add('sha512-crypt $6$', `hash ${v}`, v);
  v = J(String(100000000 + Math.floor(rnd() * 8e8)), ':AA', url(33)); add('telegram bot (id and token)', `https://api.telegram.org/bot${v}/getMe`, v);
}
// ---- round 3 precision: keys that are not secret words, hashes after sha labels, prose
h('requestId uuid', 'requestId=3f2b8c1e-9a4d-4e7b-8c1f-2d5a6b7c8e9f done'); h('request_id uuid colon', 'request_id: 3f2b8c1e-9a4d-4e7b-8c1f-2d5a6b7c8e9f done'); h('sha256 colon', 'sha256: ' + '0123456789abcdef'.repeat(4)); h('sha256 equals', 'sha256=' + '0123456789abcdef'.repeat(4));
h('author=bob', 'author=bob'); h('authority', 'authority=ab12cd34 authorize=true authentic=xx12345678'); h('author prose', 'The author and the authority authorize the authentic copy'); h('docker -p ports', 'docker run -p 8080:80 -p 443:443 image'); h('password policy', 'the password policy applies to all users');
// ---- round 4 (final) shapes: nested keys under a parent key, plain-word passwords, bare shapes
{ const up = n => rs(n, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'); let v;
  v = J(rs(8), '!x1'); add('nested under auth:', J('au', 'th:\n  pass', 'word: "', v, '"'), v);
  v = J(rs(14), '#1'); add('helm auth: postgresPassword', J('au', 'th:\n  postgresPass', 'word: "', v, '"\n  username: app'), v);
  v = J(rs(12), '!7'); add('credentials: parent then pass', J('credent', 'ials:\n  user: bob\n  pass: ', v), v);
  v = J(rs(12), '!7'); add('secrets: parent', J('sec', 'rets:\n  token: ', v, '\n  other: x'), v);
  v = rs(24, 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'); add('netrc all letters', J('machine h.example login bob pass', 'word ', v), v);
  v = rs(18, 'abcdefghijklmnopqrstuvwxyz'); add('netrc multi-line all letters', J('machine g.example\n  login bob\n  pass', 'word ', v), v);
  v = 'hunter'; add('password: plain word', J('pass', 'word: ', v), v);
  v = J('GR1', rs(20)); add('gitlab runner GR1 token', `register with ${v} now`, v);
  v = rs(20); add('gitlab-runner --registration-token', J('gitlab-runner register --registration', '-token ', v), v);
  v = rs(20); add('pgpass line', J('db.internal:5432:appdb:appuser:', v), v);
  v = hex(32); add('sentry dsn', J('https://', v, '@o123456.ingest.sentry.io/456789'), v);
  v = J('S', 'K', hex(32)); add('twilio api key SK', `key ${v}`, v);
}
// ---- round 4 precision: code is not a secret, syntax stays intact; ids and digests that their label names
h('env member', 'const apiKey = process.env.API_KEY;'); h('this.token null', 'this.token = null;'); h('zod call', 'password: z.string().min(8),'); h('json schema', '{"type":"object","properties":{"password":{"type":"string","minLength":8},"username":{"type":"string"}},"required":["password"]}');
h('regex', 'const re = /token=([^&]+)/;'); h('shell var', 'export PASS' + 'WORD=$DB_PASS' + ' && run'); h('config member', 'token: config.auth.value,');
h('etag', 'etag: "' + '0123456789abcdef'.repeat(2) + '"'); h('traceparent', 'traceparent: 00-' + '0123456789abcdef'.repeat(2) + '-' + '0123456789abcdef' + '-01'); h('build id', 'Build ID: ' + 'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678'); h('rev-parse', 'git rev-parse HEAD -> ' + 'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678');
h('checksum', 'checksum: ' + '0123456789abcdef'.repeat(4)); h('request id', 'request id ' + '0123456789abcdef'.repeat(2)); h('password prose words', 'The password must contain 8 characters; the password policy and password reset page are linked.');
h('parent key alone', 'auth:\n  enabled: true\n  mode: basic');
// ---- the rare leaks QA reproduced (a few in a thousand random values): checked over thousands of random trials each, not one sample
{ const trials = (name, gen, secretOf) => { let bad = 0; for (let i = 0; i < 3000; i++) { const [text, sec] = gen(); if (D.sanitize(text, 2000).includes(sec)) bad++; } check(`random trials: ${name} (3000 values, ${bad} leaked)`, bad === 0); };
  const lower = 'abcdefghijklmnopqrstuvwxyz', alnum = R, b64c = R + '+/';
  trials('VAULT_TOKEN=s.<24 letters, no digit> (a member-expression look-alike under a secret key name)', () => { const v = J('s.', rs(24, lower + lower.toUpperCase())); return [J('VAULT_TO', 'KEN=', v), v.slice(2)]; });
  trials('a bare 44-char base64 blob with + or / and a trailing = (no key around it)', () => { let v; do { v = rs(43, b64c); } while (!/[+\/]/.test(v) || !/\d/.test(v) || !/[a-z]/.test(v) || !/[A-Z]/.test(v)); v += '='; return [`data ${v} end`, v.slice(3, 30)]; });
  trials('Azure SAS sig=/… and sig=<anything> (any sig= / signature= value is a secret)', () => { const v = J('/', rs(42, alnum)); return [J('?sv=2022&se=2027&sr=b&s', 'ig=', v, '&sp=r'), v.slice(1, 30)]; });
  trials('signature=<random with slashes and plus signs>', () => { const v = rs(40, b64c); return [J('signa', 'ture=', v), v.slice(2, 30)]; });
  check('code with a long name is still code under a secret key name only when it has no 20+ character run', D.sanitize('const token = config.auth.value;', 200) === 'const token = config.auth.value;' && D.sanitize(J('const to', 'ken = config.', 'a'.repeat(5), '.', 'b'.repeat(5), ';'), 200).includes('config.'));
}
// ---- precision for round 5: paths with real names, properties files, common words after password
h('path with + free segments', 'see src/components/settings/panel/detail/index.tsx and lib/util/format_date.py'); h('label.password=Password', 'label.password=Password'); h('errors.token.expired', 'errors.token.expired=Your session token has expired'); h('password manager', 'Use a password manager such as 1Password.'); h('password reset flow', 'the password reset flow'); h('password confirmation', 'password confirmation mismatch and password rotation check');
h('password hashing', 'password hashing uses bcrypt, password history is kept, password complexity applies'); h('login minimum', 'password minimum length is 12, maximum 64; password validation fails'); h('config member under key', 'const token = config.auth.value;');
// ---- cost: a 50k value is cheap (the tests look at the first 4096 characters only)
check('cost: redact() of a 50k-character value finishes < 10 ms (best of 3; 40 ms when the machine is busy)', (() => { const R2 = require(path.join(__dirname, '../vscode-ext/shipmiracle-panel/redact.js')); const t = J('API_', 'KEY=', rs(50000, R + '+/')); let best = 1e9; for (let i = 0; i < 3; i++) { const a = process.hrtime.bigint(); R2.redact(t); best = Math.min(best, Number(process.hrtime.bigint() - a) / 1e6); } return best < (LOAD > 12 ? 40 : 10); })());
// more ordinary texts that contain key words
h('mkdir -p', 'run mkdir -p build/output and cd build'); h('key word prose', 'press the key and enter the pin at the door'); h('the password is wrong', 'the password is wrong, try again'); h('the token is expired', 'the token is expired again');
let leak = 0, mang = 0; const leaked = [], mangled = [];
for (const [l, t, sec] of S) { const r = D.sanitize(t, 100000); if (r.includes(sec)) { leak++; leaked.push(l); } }
for (const [l, t] of H) { const r = D.sanitize(t, 100000); if (r !== D.clean(t)) { mang++; mangled.push(l + ' -> ' + r.slice(0, 60)); } }
console.log(`TABLE recall: ${S.length - leak} of ${S.length} secret shapes hidden (${leak} leaked); precision: ${H.length - mang} of ${H.length} ordinary texts unchanged (${mang} changed)`);
check(`recall on OUR OWN corpus (not a guarantee for real text): every shape in it is hidden (${S.length - leak} of ${S.length})`, leak === 0, leaked.join('; '));
check(`precision: every ordinary text comes back unchanged (${H.length - mang} of ${H.length})`, mang === 0, mangled.join('; '));
// pairs that must differ in ONE respect (a key word with / without a secret-looking value)
check('prose with a key word stays; the same key word with = always hides', D.sanitize('the token: budget is low', 200) === 'the token: budget is low' && D.sanitize(J('tok', 'en=budget'), 200) === J('tok', 'en=[hidden]'));
check('a UUID in prose stays, a UUID after a secret-named key is hidden', D.sanitize('id 3f2b8c1e-9a4d-4e7b-8c1f-2d5a6b7c8e9f ok', 200) === 'id 3f2b8c1e-9a4d-4e7b-8c1f-2d5a6b7c8e9f ok' && D.sanitize(J('API_', 'KEY=', '3f2b8c1e-9a4d-4e7b-8c1f-2d5a6b7c8e9f'), 200) === J('API_', 'KEY=[hidden]'));
check('hiding is idempotent over the whole table (the page cleans the text a second time)', S.every(([l, t]) => { const a = D.sanitize(t, 100000); return D.sanitize(a, 100000) === a; }));
console.log(fails ? `\nFAILED: ${fails} of ${n}` : `\nALL PASS (${n})`); process.exit(fails ? 1 : 0);
