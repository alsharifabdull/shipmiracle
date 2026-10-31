"""bin/shipm-guard-admin: --print needs no root and writes nothing; the line equals the old one; root and odd names are refused.
Nothing here ever runs the install path (the fake `id` only reaches the checks that stop before any write). Run: python3 tests/guard_admin_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import os, pathlib, pwd, re, subprocess, sys, tempfile
ws = pathlib.Path(__file__).resolve().parent.parent
ADMIN = str(ws / "bin/shipm-guard-admin")
tmp = pathlib.Path(tempfile.mkdtemp())
fails = []
def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name, info if not cond else "")
    if not cond: fails.append(name)

def old_line(user):
    """Today's rule text (the printf of the version at commit 8535593, same format string)."""
    P = "/usr/bin/pmset"
    return "%s ALL=(root) NOPASSWD: %s -a disablesleep 1, %s -a disablesleep 0, %s -b lowpowermode 1, %s -b lowpowermode 0\n" % (user, P, P, P, P)

def run(*args, env=None, path=None):
    e = dict(os.environ if env is None else env)
    if path: e["PATH"] = path + ":" + e["PATH"]
    return subprocess.run(["/bin/sh", ADMIN, *args], capture_output=True, text=True, env=e, stdin=subprocess.DEVNULL)

me = pwd.getpwuid(os.getuid()).pw_name
before = set(os.listdir(tmp))
r = run("--print", "alice"); check("--print USER equals today's line exactly", r.returncode == 0 and r.stdout == old_line("alice"), r.stdout + r.stderr)
r = run("--print"); check("--print without a name uses the calling account and needs no root", os.getuid() != 0 and r.returncode == 0 and r.stdout == old_line(me), r.stdout + r.stderr)
git = None
for _rel in ("bin/shipm-guard-admin", "bin/" + "a" + "iw-guard-admin"):       # the helper was renamed after that commit: follow it
    git = subprocess.run(["git", "-C", str(ws), "show", "8535593:" + _rel], capture_output=True, text=True)
    if git.returncode == 0:
        break
_have = subprocess.run(["git", "-C", str(ws), "cat-file", "-e", "8535593^{commit}"], capture_output=True).returncode == 0
if _have and git.returncode != 0:
    check("the old helper is found in commit 8535593 (under either name)", False, git.stderr)
if git.returncode == 0:
    m = re.search(r"^printf '([^\n]*)' \"\$U\"", git.stdout, re.M)
    check("the format string equals the one at commit 8535593", bool(m) and (m.group(1).replace("\\n", "\n") % tuple(["alice"] + ["/usr/bin/pmset"] * 4)) == old_line("alice"), git.stdout[:200])
elif not _have:
    print("SKIP old-commit comparison (commit not in this clone)")
for bad in ("root", "Alice", "a b", "1abc", "", "x" * 33, "a;rm", "$(id)", "a\nb"):
    r = run("--print", bad); check("--print refuses %r" % bad, r.returncode != 0 and r.stdout == "" and "refusing" in r.stderr, r.stdout + r.stderr)
# fake `id` says we are root: only the checks that stop before any write are exercised
fake = tmp / "fakebin"; fake.mkdir(); (fake / "id").write_text('#!/bin/sh\n[ "$1" = "-u" ] && echo 0 || echo root\n'); (fake / "id").chmod(0o755)
for label, env_user in (("unset", None), ("root", "root"), ("bad name", "Evil User"), ("injection", "x;touch /tmp/pwned")):
    e = {k: v for k, v in os.environ.items() if k != "SUDO_USER"}
    if env_user is not None: e["SUDO_USER"] = env_user
    r = run(env=e, path=str(fake)); check("as root with SUDO_USER %s: refused before anything is written" % label, r.returncode != 0 and "OK" not in r.stdout and "visudo" not in r.stderr, r.stdout + r.stderr)
r = run(); check("not root and no --print: 'run with sudo', exit 1", os.getuid() == 0 or (r.returncode == 1 and "run with sudo" in r.stdout), r.stdout + r.stderr)
check("nothing was written to the temp folder", set(os.listdir(tmp)) == before | {"fakebin"} and not pathlib.Path("/tmp/pwned").exists())
src = pathlib.Path(ADMIN).read_text()
check("no literal account name in the script, SUDO_USER is required", me not in src and "${SUDO_USER:?" in src)
print("\nFAILED:" if fails else "\nALL PASS", fails); sys.exit(1 if fails else 0)
