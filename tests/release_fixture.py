"""World for the release / history suites (release_facts_test, history_compact_test, release_cli_test). Not a test.
A fully temp HOME / DEV / STATE / config / workspace (SHIPMIRACLE_TEST=1), small git repositories with fixed commit dates, a Sim that writes real
change-request transitions through the engine (so the log is what production writes), and a `shipm` runner. No network: a push goes to a bare temp repo."""
import json, os, pathlib, shutil, subprocess, sys, tempfile, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation

ROOT = pathlib.Path(__file__).resolve().parent.parent
TMP = pathlib.Path(tempfile.mkdtemp(prefix="shipmiracle-rel-")).resolve()
HOME = pathlib.Path(os.environ["HOME"]).resolve()
DEV, STATE, CONF, WS = (TMP / n for n in ("dev", "state", "config", "ws"))
for _d in (DEV, STATE, CONF, WS / "config"):
    _d.mkdir(parents=True, exist_ok=True)
(WS / "config" / "flow.json").write_text('{\n  "default": "strict",\n  "projects": {}\n}\n')
os.chmod(CONF, 0o700)
ENV = dict(os.environ, SHIPMIRACLE_TEST="1", SHIPMIRACLE_DEV=str(DEV), SHIPMIRACLE_STATE=str(STATE), SHIPMIRACLE_CONFIG=str(CONF), SHIPMIRACLE_WS=str(WS), TZ="UTC")
for _k in ("SHIPMIRACLE_DEBUG", "CLAUDECODE", "SHIPMIRACLE_ENFORCE_OWNER"):
    ENV.pop(_k, None)
os.environ.update({k: v for k, v in ENV.items() if k.startswith("SHIPMIRACLE_") or k == "TZ"})
time.tzset()
sys.path.insert(0, str(ROOT))
import atexit
atexit.register(shutil.rmtree, str(TMP), True)

from shipmiracle.playbook import engine, gate, store  # noqa: E402

fails = 0
n_checks = 0


def check(name, ok, info=""):
    global fails, n_checks
    n_checks += 1
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:900]))
    fails += 0 if ok else 1


def finish():
    print("%d checks, %d failed" % (n_checks, fails))
    sys.exit(1 if fails else 0)


def shipm(*args, env=None, cwd=None):
    r = subprocess.run([sys.executable, str(ROOT / "bin" / "shipm")] + list(args), env=env or ENV, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL, cwd=cwd)
    return r.returncode, r.stdout, r.stderr


def git(d, *a, date=None, check_rc=True):
    env = dict(ENV)
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date + "T12:00:00+0000"
    r = subprocess.run(["git", "-C", str(d)] + list(a), env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if check_rc and r.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(a), r.stderr))
    return r.stdout.strip()


_n = [0]


def mkrepo(name=None, first_date="2026-01-10"):
    """A project folder under DEV with one commit (README, dated first_date). Returns the path."""
    _n[0] += 1
    d = DEV / (name or "proj%d" % _n[0])
    d.mkdir(parents=True)
    git(d, "init", "-q", "-b", "main")
    (d / "README.md").write_text("x\n")
    git(d, "add", "-A")
    git(d, "commit", "-q", "-m", "init", date=first_date)
    return d


def commit(d, msg, date, fname="f.txt"):
    """A new commit that changes a file; returns its full id."""
    p = pathlib.Path(d) / fname
    p.write_text((p.read_text() if p.exists() else "") + msg + "\n")
    git(d, "add", "-A")
    git(d, "commit", "-q", "-m", msg, date=date)
    return git(d, "rev-parse", "HEAD")


def set_software(d):
    (STATE / "health.json").write_text(json.dumps({"ts": time.time(), "chats": {pathlib.Path(d).name: {"chats": 0}}}))     # fresh chat state: no open chat in the project
    rc, o, e = shipm("playbook", "set", "type", "software", "--project", str(d))
    assert rc == 0, (o, e)


class Sim:
    """Real engine transitions for change requests of one project; append() writes them to the CR log."""

    def __init__(self, d, t=1760000000):
        self.d = d
        self.rules = gate.stage_rules(str(d))
        assert self.rules is not None, "set_software(d) first"
        self.w = engine.new_work()
        self.w["project"] = pathlib.Path(d).name
        self.t = t
        self.trs = []

    def tick(self, n=60):
        self.t += n
        return self.t

    def ev(self, kind, by=None, **data):
        return {"kind": kind, "data": data, "by": by or data.get("role") or "x", "ts": self.tick()}

    def adv(self, cr, stage, kind, by=None, **data):
        self.trs += engine.advance(self.w, cr["id"], stage, self.ev(kind, by, **data), self.rules)

    def deliver(self, title, head=None, at=None):
        """Open a CR and walk it through every stage to delivered; the Deliver stage records `head` (a commit id, cut to 12). `at`: epoch seconds of the opening."""
        if at is not None:
            self.t = at
        cr, trs = engine.open_cr(self.w, title, "owner", self.tick(), lane="full", base="ab" * 20, rules=self.rules, kind="cli_open")
        self.trs += trs
        self.adv(cr, "scope", "role_stop", "scoper", role="scope")
        self.adv(cr, "plan", "plan_presented", "planner", plan_sha="cd" * 32, role_ts=self.t)
        self.adv(cr, "approve", "owner_prompt", "owner", owner_words=True)
        self.adv(cr, "do", "role_stop", "builder", role="build", diff={"files": 1, "lines": 3, "risk": [], "deps": False})
        self.adv(cr, "verify", "qa_pass", "verifier", counts={"passed": 3, "failed": 0, "total": 3}, evidence="t -> 3 passed", cmd="t")
        self.adv(cr, "review", "review_verdict", "reviewer", lens="correctness", verdict="ACCEPT")
        self.adv(cr, "deliver", "git_delivered", "lead", **({"head": head[:12]} if head else {}))
        self.adv(cr, "learn", "status_dated", "lead")
        self.adv(cr, "learn", "report_written", "lead")
        return cr

    def abandon(self, title):
        cr, trs = engine.open_cr(self.w, title, "owner", self.tick(), lane="full", base="ab" * 20, rules=self.rules, kind="cli_open")
        self.trs += trs
        self.trs += engine.abandon(self.w, cr["id"], self.ev("owner_override", "owner"), self.rules)
        return cr

    def append(self):
        store.append(self.d, self.trs, base=STATE)
        self.trs = []
