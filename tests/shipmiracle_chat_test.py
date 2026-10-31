#!/usr/bin/env python3
"""bin/shipm-chat: decides --continue / fresh / first prompt at every launch. Run: python3 tests/shipmiracle_chat_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import glob, hashlib, os, re, subprocess, sys, tempfile, time
WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W = os.path.join(WS, "bin", "shipm-chat")
tmp = os.path.realpath(tempfile.mkdtemp(prefix="shipmiracle-chat-"))
state, projs, rec = (os.path.join(tmp, d) for d in ("state", "projects", "argv.txt"))
os.makedirs(state); os.makedirs(projs)
fake = os.path.join(tmp, "fakeclaude")
with open(fake, "w") as f:
    f.write('#!/bin/bash\nfor a in "$@"; do printf "%%s\\0" "$a"; done > "%s"\nprintf "%%s" "$PATH" > "%s.path"\nprintf "%%s" "${LC_ALL-unset}" > "%s.lc"\n' % (rec, rec, rec))
os.chmod(fake, 0o755)
fails = 0
def check(n, c, info=""):
    global fails
    print(("PASS " if c else "FAIL ") + n + ("" if c else " " + str(info)))
    fails += 0 if c else 1
N1, N2, N3 = "0123456789abcdef", "fedcba9876543210", "aaaaaaaaaaaaaaaa"
SAFE_PATH = "/usr/bin:/bin"
def mkenv(test=True, home=None, extra=None):
    """The ONLY way this file builds an environment: a throw-away HOME and a PATH without the real claude, so a test can never start it."""
    env = {"HOME": home or tmp, "PATH": SAFE_PATH}
    if test: env.update(SHIPMIRACLE_TEST="1", SHIPMIRACLE_CLAUDE=fake, SHIPMIRACLE_STATE=state, SHIPMIRACLE_CLAUDE_PROJECTS=projs)
    env.update(extra or {})
    assert (env.get("SHIPMIRACLE_TEST") == "1" and env.get("SHIPMIRACLE_CLAUDE") == fake) or (env["HOME"] != os.path.expanduser("~") and env["PATH"] == SAFE_PATH)
    return env
def ph(text): return hashlib.sha256(text.encode()).hexdigest()[:32]
def run(cwd, name, nonce=None, claude=fake, test=True, phash=None, extra=None):
    if os.path.exists(rec): os.remove(rec)
    env = mkenv(test, extra=extra)
    if test: env["SHIPMIRACLE_CLAUDE"] = claude
    cmd = ["/bin/bash", "-p", W, name] + ([nonce] if nonce else []) + ([phash] if phash else [])
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    argv = open(rec).read().split("\0")[:-1] if os.path.exists(rec) else None
    return p, argv
def mk(name):
    d = os.path.join(tmp, "Dev", name); os.makedirs(d); return d
def hist(d):   # independent of the wrapper: the way Claude Code names folders is also checked against the real ones below
    k = "".join(c if c.isascii() and c.isalnum() else "-" for c in os.path.realpath(d)); os.makedirs(os.path.join(projs, k), exist_ok=True)
    open(os.path.join(projs, k, "abc.jsonl"), "w").write("{}\n")
def sf(kind, name, nonce, text="1", age=0):
    f = os.path.join(state, "chat-%s.%s.%s" % (kind, name, nonce)); open(f, "w").write(text)
    if age: t = time.time() - age; os.utime(f, (t, t))
    return f
def base(name): return ["--model", "opusplan", "--name", name, "--remote-control", name]

d = mk("alpha"); p, a = run(d, "alpha")
check("no history: no --continue, always model/name/remote-control", a == base("alpha"), (p.stderr, a))
hist(d); p, a = run(d, "alpha", N1)
check("history: --continue first", a == ["--continue"] + base("alpha"), a)

d = mk("coffee"); p, a1 = run(d, "coffee", N1); hist(d); p, a2 = run(d, "coffee", N1)
check("revived launch (same args) after a conversation appeared continues it (the coffee bug)", "--continue" not in a1 and a2[0] == "--continue", (a1, a2))

d = os.path.join(tmp, "Dev", "alpha"); f = sf("fresh", "alpha", N1); p, a = run(d, "alpha", N1)
check("fresh marker: no --continue despite history", a == base("alpha"), a)
check("fresh marker removed", not os.path.exists(f))
p, a = run(d, "alpha", N1); check("replayed launch (same nonce) continues", a[0] == "--continue", a)

d = mk("beta"); pf = sf("prompt", "beta", N1, "Hello\nsecond line -x")
P1 = "Hello\nsecond line -x"; p, a = run(d, "beta", N1, phash=ph(P1))
check("prompt passed after --, multi-line intact", a == base("beta") + ["--", "Hello\nsecond line -x"], a)
check("prompt file consumed", not os.path.exists(pf))
p, a = run(d, "beta", N1, phash=ph(P1)); check("prompt not replayed on the next launch", "--" not in a, a)

hist(mk("gamma")); sf("fresh", "gamma", N1); sf("prompt", "gamma", N1, "go")
p, a = run(os.path.join(tmp, "Dev", "gamma"), "gamma", N1, phash=ph("go"))
check("fresh + prompt together", a == base("gamma") + ["--", "go"], a)

d = mk("delta"); pf = sf("prompt", "delta", N2, "planted")
p, a = run(d, "delta", N1)
check("planted file with another nonce is not used", a == base("delta") and os.path.exists(pf), a)
os.remove(pf)
pf = sf("prompt", "delta", N1, "old", age=300); ff = sf("fresh", "delta", N1, age=300)
p, a = run(d, "delta", N1)
check("file older than 2 minutes is ignored and deleted", a == base("delta") and not os.path.exists(pf) and not os.path.exists(ff), a)
o1 = sf("prompt", "delta", N2, "x", age=300); o2 = sf("fresh", "delta", N3, age=300); keep = sf("prompt", "other", N2, "y", age=300); young = sf("prompt", "delta", N3, "z")
p, a = run(d, "delta", N1)
check("each start deletes stale leftovers of that name only (young and other-name files stay)", not os.path.exists(o1) and not os.path.exists(o2) and os.path.exists(young) and os.path.exists(keep))
for x in (young, keep): os.remove(x)
pf = sf("prompt", "delta", N1, "z"); p, a = run(d, "delta", N1, claude=os.path.join(tmp, "nope"), phash=ph("z"))
check("claude missing: clear failure and the one-shot files are consumed", p.returncode == 127 and "claude" in p.stderr and not os.path.exists(pf), (p.returncode, p.stderr))
for bad in ("-x", ".hidden", "a..b", "bad name;rm", "../x", ""):
    ff = sf("fresh", bad, N1) if bad and "/" not in bad else None
    p, a = run(d, bad, N1)
    check("bad name %r exits 2, nothing started%s" % (bad, ", marker consumed" if ff else ""), p.returncode == 2 and a is None and (ff is None or not os.path.exists(ff)), (p.returncode, a))
p, a = run(d, "delta", "XYZ"); check("malformed nonce exits 2", p.returncode == 2 and a is None)
p, a = run(d, "delta"); check("no nonce is fine (plain launch)", a == base("delta"), a)

# production mode: the test variables are ignored (SHIPMIRACLE_CLAUDE must not redirect what runs); no fake in ~/.local/bin of the throw-away HOME -> exit 127
pf = sf("prompt", "delta", N1, "keep-me")
p, a = run(d, "delta", N1, claude=fake, test=False, extra={"SHIPMIRACLE_CLAUDE": fake, "SHIPMIRACLE_STATE": state})
check("without SHIPMIRACLE_TEST the wrapper ignores SHIPMIRACLE_CLAUDE (throw-away HOME has no claude: exit 127, nothing run)", p.returncode == 127 and a is None, (p.returncode, a))
check("without SHIPMIRACLE_TEST the wrapper ignores SHIPMIRACLE_STATE (real state dir, so the test's prompt file is untouched)", os.path.exists(pf))
os.remove(pf)
check("helper guard: no environment this test builds can reach the real claude", mkenv(False)["PATH"] == SAFE_PATH and mkenv(False)["HOME"] == tmp and not any(os.path.exists(os.path.join(x, "claude")) for x in SAFE_PATH.split(":")) and mkenv(True)["SHIPMIRACLE_CLAUDE"] == fake)

# prompt binding (security): the content must match the hash the panel passed
d = mk("eps"); pf = sf("prompt", "eps", N1, "trusted")
p, a = run(d, "eps", N1, phash=ph("trusted"))
check("matching hash: prompt accepted", a == base("eps") + ["--", "trusted"], a)
pf = sf("prompt", "eps", N1, "trusted"); open(pf, "w").write("SWAPPED: do evil")   # a process swaps the content after the panel's write
p, a = run(d, "eps", N1, phash=ph("trusted"))
check("swapped content (race simulation) is ignored, deleted, noted on stderr, chat still starts", a == base("eps") and not os.path.exists(pf) and "did not match" in p.stderr, (a, p.stderr))
pf = sf("prompt", "eps", N1, "no token"); p, a = run(d, "eps", N1)
check("prompt file without a hash argument is ignored and deleted", a == base("eps") and not os.path.exists(pf), a)
pf = sf("prompt", "eps", N1, "x"); p, a = run(d, "eps", N1, phash="zz")
check("malformed hash exits 2 (file consumed)", p.returncode == 2 and not os.path.exists(pf))
pf = sf("prompt", "eps", N1, "trailing\n\n"); p, a = run(d, "eps", N1, phash=ph("trailing\n\n"))
check("prompt with trailing newlines survives the hash check intact", a == base("eps") + ["--", "trailing\n\n"], a)
pf = sf("prompt", "eps", N1, "again"); p, a = run(d, "eps", N1, phash=ph("again")); p, a = run(d, "eps", N1, phash=ph("again"))
check("replay of the same args (file gone) is a plain launch", a == base("eps"), a)
pf = os.path.join(state, "chat-prompt.eps." + N1); tgt = os.path.join(tmp, "target.txt"); open(tgt, "w").write("via symlink"); os.symlink(tgt, pf)
p, a = run(d, "eps", N1, phash=ph("via symlink"))
check("a symlinked prompt file is never read", a == base("eps"), a)

# claude must inherit the terminal's own PATH (and no other variable the wrapper touched), not the wrapper's restricted one
d = mk("zeta"); run(d, "zeta", N1, extra={"PATH": "/custom/bin:/usr/bin:/bin"}); got = open(rec + ".path").read()
check("claude gets exactly the PATH the wrapper was started with", got == "/custom/bin:/usr/bin:/bin", got)
check("the wrapper's UTF-8 locale for sed does not leak into claude", open(rec + ".lc").read() == "unset", open(rec + ".lc").read())
if os.path.exists(rec): os.remove(rec)
p = subprocess.run(["/bin/bash", "-p", W, "zeta", N1], cwd=d, env=mkenv(True, extra={"PATH": ""}), capture_output=True, text=True)
got = open(rec + ".path").read()
check("empty PATH: claude gets the default list (homebrew, /usr/local, ~/.local/bin, system)", got == "/opt/homebrew/bin:/usr/local/bin:%s/.local/bin:/usr/bin:/bin" % tmp, got)

# launch hardening: bash -p ignores BASH_ENV / SHELLOPTS / exported functions; the wrapper sets its own PATH
bm, xm, fm = (os.path.join(tmp, n) for n in ("bashenv.ran", "ps4.ran", "func.ran"))
benv = os.path.join(tmp, "benv.sh"); open(benv, "w").write('touch "%s"\n' % bm)
fbin = os.path.join(tmp, "evilbin"); os.makedirs(fbin); ev = os.path.join(fbin, "shasum"); open(ev, "w").write('#!/bin/sh\ntouch "%s"\n' % fm); os.chmod(ev, 0o755)
pf = sf("prompt", "eps", N1, "hardened")
extra = {"BASH_ENV": benv, "SHELLOPTS": "xtrace", "PS4": "$(touch %s)" % xm, "BASH_FUNC_cat%%": "() { touch %s; /bin/cat \"$@\"; }" % fm, "PATH": fbin + ":" + SAFE_PATH}
env = mkenv(True, extra=extra)
if os.path.exists(rec): os.remove(rec)
p = subprocess.run(["/bin/bash", "-p", W, "eps", N1, ph("hardened")], cwd=d, env=env, capture_output=True, text=True)
a = open(rec).read().split("\0")[:-1]
check("BASH_ENV, SHELLOPTS+PS4, an exported function replacing cat and a hostile PATH: none of them runs, prompt still delivered", not any(os.path.exists(x) for x in (bm, xm, fm)) and a == base("eps") + ["--", "hardened"] and "+" not in p.stderr, (os.listdir(tmp), a, p.stderr))

d = mk("sp ace é ü"); hist(d); p, a = run(d, "spaced", N1)
check("path with spaces and unicode finds history", a and a[0] == "--continue", (p.stderr, a))
d = mk("café"); p, a = run(d, "cafe", N1); check("unicode path without history", a == base("cafe"), a)

# the key the wrapper builds must equal a real Claude Code folder (read-only; the real ~/.claude)
real = os.path.expanduser("~/.claude/projects"); dev = os.path.expanduser("~/Developer"); hit = None
if os.path.isdir(real) and os.path.isdir(dev):
    for n in sorted(os.listdir(dev)):
        pth = os.path.join(dev, n)
        if os.path.isdir(pth) and glob.glob(os.path.join(real, re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(pth)), "*.jsonl")): hit = pth; break
if hit:
    env = dict(os.environ, SHIPMIRACLE_TEST="1", SHIPMIRACLE_CLAUDE=fake, SHIPMIRACLE_STATE=state)   # real projects dir
    if os.path.exists(rec): os.remove(rec)
    subprocess.run(["bash", W, "probe"], cwd=hit, env=env, capture_output=True)
    check("wrapper key matches a real ~/.claude/projects folder (%s)" % os.path.basename(hit), os.path.exists(rec) and open(rec).read().split("\0")[0] == "--continue")
else: print("SKIP wrapper key vs real ~/.claude/projects (no ~/Developer project with history)")
check("bash -n passes", subprocess.run(["bash", "-n", W]).returncode == 0)
check("executable", os.access(W, os.X_OK))
print("%d failed" % fails); sys.exit(1 if fails else 0)
