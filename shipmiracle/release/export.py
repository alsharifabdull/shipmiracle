"""`shipm release export` (spec 2026-10-20-p8-spec.md section 4, steps 1-10). One-way, one commit per release, nothing is pushed unless
`--push --yes-publish` passes every gate. The default (dry run) runs no remote command at all.

1  refuse a dirty source (untracked files count); record HEAD sha and branch.
2  source = committed blobs only: `git ls-tree -r -z HEAD` filtered by the allowlist minus the hard-never list (release/allowlist.txt and
   release/hard-never.txt from HEAD; the lists below are the fallback); symlinks and submodules in the selection are refused; blobs
   come from one `git cat-file --batch` and are written into <state>/v1/release/stage-<ts>/tree (folder 0700); only the last stage is kept.
3  the overlay (release/overlay/** from HEAD) is laid over the tree.
4  release-check with the denylist required (stamp written on PASS); any finding stops.
5  test-all in a COPY of the tree (so the checked tree stays byte-identical) with temp HOME/STATE/CONFIG; --skip-tests is recorded and never pushable.
6  the commit: fresh `git init` in stage/repo, isolated git environment (no global or system config, temp HOME, TZ=UTC), the configured GitHub
   noreply identity, the fixed message `Release vX.Y.Z`, no trailers, a lightweight tag.
7  verification of the commit: author/committer all noreply, raw commit object free of denylist hits, +0000 dates, tree == the checked tree.
8  manifest <state>/v1/release/manifest-vX.Y.Z.json and the added/removed files since the previous manifest.
9  a dry run stops here and prints the owner's commands; it runs none of them.
10 --push: see _push_gates(); then `git push <url> main vX.Y.Z` from stage/repo (its pre-push hook runs `shipm push-check`)."""
from __future__ import annotations

import atexit
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata

from .. import ShipmiracleError, NotFound, SafetyError, UsageError
from .. import config, paths, projects, registry, state
from . import check as chk
from . import denylist as dl
from . import pushcheck

GIT = "git"
OVERLAY = "release/overlay/"
INPUT_FILES = ("release/placeholders.txt", "release/fixtures-reviewed.txt", "release/closure-exempt.txt", "release/website-fonts.sha256", "release/VERSION", "release/overlay/CHANGELOG.md")
NOREPLY_RE = re.compile(r"^\d+\+([A-Za-z0-9-]+)@users\.noreply\.github\.com$")
MAX_BLOB_TOTAL = 256 * 1024 * 1024
SHOW_LIMIT = 40

# fallbacks when release/allowlist.txt or release/hard-never.txt is not in HEAD (spec section 2)
ALLOWLIST_DEFAULT = (
    "shipmiracle/**", "bin/shipm", "bin/agent-check", "bin/shipm-bg", "bin/shipm-chat", "bin/shipm-guard", "bin/shipm-guard-admin", "bin/shipm-watch",
    "bin/shipm-ledger", "bin/shipm-prefix", "bin/apply-template", "bin/away-decisions", "bin/ci-status", "bin/daily", "bin/doctor",
    "bin/flow-report", "bin/gate-deny", "bin/idea", "bin/install-shipm-ext", "bin/new-project", "bin/plugins-update", "bin/promote-agent",
    "bin/skills-sync", "bin/status-extract", "bin/status-trim", "bin/test-all", "bin/test-linux", "bin/shipm-timer", "bin/shipm-presence-build", "tools/presence/**", "bin/vscode-recs", "hooks/shipm-hook", "agents/claude/*.md",
    "templates/**", "vscode-ext/shipmiracle-panel/**", "docs/standards/*.md", "docs/idea-review-method.md", "skills/skills.lock.json",
    "config/ideas.json", "config/notifications.json", "config/watch.json", "tests/*_test.py", "tests/*_test.js", "tests/*.py",
    "tests/shipmiracle_isolation.js", "tests/chrome_helper.js", "tests/panel_cdp.js", "tests/panel_live_world.js", "tests/panel_themes.js", "tests/panel_v3_fixtures.js",
    "tests/panel_v3_tab_fixtures.js", "tests/fixtures/**", "tests/fakes/**")
HARD_NEVER_DEFAULT = (
    "memory/**", "docs/STATUS.md", "docs/DECISIONS.md", "docs/ACCEPTANCE.md", "docs/FEATURE-IDEAS.md", "docs/parity.md", "docs/plans/**",
    "docs/baseline/**", "docs/golden/**", "docs/memory/**", "docs/owner-steps/**", "docs/status-archive/**", "docs/standards/known/**", "docs/standards/readme-claim-map.md", "docs/standards/repo-settings.md",
    "dotfiles/**", "reports/**", ".claude/**", "tests/private/**", "tools/private/**", "release/**", "skills/hig-*/**", "skills/swiftui-pro/**",
    "bin/delete-*", "config/ci-hold.txt", "config/flow.json", "tests/fixtures/panel-v3/**", "tests/fixtures/panel-v3-rev2/**", "docs/summary/**", "**/*.jsonl", "**/.env")

# test seams (tests set these; the defaults are the real behaviour)
CHECK = None            # callable(tree, inputs, deny) -> check.Report
MAX_FLAKY = 5             # more flaky suites than this means a broken or overloaded machine: no export
TEST_CMD = None         # argv list run in the copied tree instead of [python, bin/test-all]
ISATTY = None           # callable() -> bool
ASK = None              # callable(prompt) -> str
NOW = None              # callable() -> float


class Refused(ShipmiracleError):
    """The export or push was refused by one of its rules (exit 1); the message says which."""
    exit_code = 1


def _now():
    return int(NOW() if NOW else time.time())


def _say(text=""):
    sys.stdout.write(text + "\n")


# ---------------------------------------------------------------- globs
def glob_re(g):
    """'**/' = zero or more folders, '**' = anything, '*' = inside one folder, '?' = one character (same as tests/release_data_test.py)."""
    out, i = "", 0
    while i < len(g):
        if g.startswith("**/", i):
            out += "(?:.*/)?"; i += 3
        elif g.startswith("**", i):
            out += ".*"; i += 2
        elif g[i] == "*":
            out += "[^/]*"; i += 1
        elif g[i] == "?":
            out += "[^/]"; i += 1
        else:
            out += re.escape(g[i]); i += 1
    return re.compile("^" + out + "$")


def parse_rules(text):
    return [l.strip() for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]


class Rules(object):
    def __init__(self, allow, never, overlay_allow=()):
        self.allow = [glob_re(g) for g in allow]
        self.never = [glob_re(g) for g in never]
        self.overlay_allow = [glob_re(g) for g in overlay_allow]

    def overlay_ok(self, src_path, dst):
        """L10: an overlay file that matches the hard-never list ships only when release/overlay-allow.txt names its overlay path (release/overlay/<dst>)."""
        return not any(r.match(dst) for r in self.never) or any(r.match(src_path) for r in self.overlay_allow)

    def selected(self, path):
        return any(r.match(path) for r in self.allow) and not any(r.match(path) for r in self.never)


# ---------------------------------------------------------------- git on the source repo
def _src_env():
    return projects.git_env()


def _run(args, cwd, env=None, inp=None, timeout=120, check=True):
    argv = [GIT] + args
    try:
        r = subprocess.run(argv, cwd=cwd, input=inp, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, shell=False,
                           env=env if env is not None else _src_env(), stdin=None if inp is not None else subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        raise Refused("git %s could not run (%s)" % (args[0], type(e).__name__))
    if check and r.returncode != 0:
        raise Refused("git %s failed (exit %d): %s" % (args[0], r.returncode, r.stderr.decode("utf-8", "replace").strip()[:200]))
    return r


def _src(repo, args, inp=None, timeout=120):
    return _run(projects.GIT_PREFIX[1:] + ["-C", str(repo)] + args, None, inp=inp, timeout=timeout)


def source_info(repo):
    top = _src(repo, ["rev-parse", "--show-toplevel"]).stdout.decode().strip()
    dirty = _src(repo, ["status", "--porcelain=v1", "-z", "--untracked-files=all"]).stdout
    head = _src(repo, ["rev-parse", "HEAD"]).stdout.decode().strip()
    r = _run(projects.GIT_PREFIX[1:] + ["-C", str(repo), "symbolic-ref", "-q", "--short", "HEAD"], None, check=False)
    branch = r.stdout.decode().strip() if r.returncode == 0 else "(detached)"
    return {"top": top, "dirty": bool(dirty), "head": head, "branch": branch}


def list_head(repo):
    """[(mode, type, sha, path)] of `git ls-tree -r -z HEAD`."""
    out = _src(repo, ["ls-tree", "-r", "-z", "--full-tree", "HEAD"]).stdout
    rows = []
    for rec in out.split(b"\0"):
        if not rec:
            continue
        meta, _, path = rec.partition(b"\t")
        p = meta.decode().split(" ")
        if len(p) != 3:
            raise Refused("unexpected git ls-tree output")
        try:
            rows.append((p[0], p[1], p[2], path.decode("utf-8")))
        except UnicodeDecodeError:
            raise Refused("a committed path is not valid UTF-8; the export refuses it")
    return rows


def read_blobs(repo, shas):
    """{sha: bytes} through one `git cat-file --batch`."""
    want = sorted(set(shas))
    if not want:
        return {}
    r = _src(repo, ["cat-file", "--batch"], inp=("\n".join(want) + "\n").encode(), timeout=300)
    buf, pos, out, total = r.stdout, 0, {}, 0
    for sha in want:
        nl = buf.find(b"\n", pos)
        if nl < 0:
            raise Refused("git cat-file output ended early")
        hdr = buf[pos:nl].decode("utf-8", "replace").split(" ")
        if len(hdr) != 3 or hdr[0] != sha or hdr[1] != "blob":
            raise Refused("git cat-file did not return a blob for a committed file")
        size = int(hdr[2])
        total += size
        if total > MAX_BLOB_TOTAL:
            raise Refused("the selected files are larger than %d MB" % (MAX_BLOB_TOTAL >> 20))
        out[sha] = buf[nl + 1:nl + 1 + size]
        pos = nl + 1 + size + 1
    return out


def _bad_path(p):
    if not p or p.startswith("/") or "\\" in p or any(unicodedata.category(c).startswith("C") for c in p):
        return True
    parts = p.split("/")
    return any(x in ("", ".", "..") or x.lower() == ".git" for x in parts)


def load_rules(rows, repo):
    by = {p: s for m, t, s, p in rows}
    allow, never = list(ALLOWLIST_DEFAULT), list(HARD_NEVER_DEFAULT)
    wanted = [by[n] for n in ("release/allowlist.txt", "release/hard-never.txt", "release/overlay-allow.txt") if n in by]
    blobs = read_blobs(repo, wanted)
    if "release/allowlist.txt" in by:
        allow = parse_rules(blobs[by["release/allowlist.txt"]].decode("utf-8", "replace"))
    if "release/hard-never.txt" in by:
        never = parse_rules(blobs[by["release/hard-never.txt"]].decode("utf-8", "replace"))
    oa = parse_rules(blobs[by["release/overlay-allow.txt"]].decode("utf-8", "replace")) if "release/overlay-allow.txt" in by else []
    return Rules(allow, never, oa)


def select(rows, rules):
    """{path: (mode, sha)}: selected source files, then the overlay laid over them. Symlinks and submodules in the selection, unsafe
    paths and names that differ only in case are refused (the whole export stops)."""
    chosen, overlay = {}, {}
    for mode, typ, sha, path in rows:
        if path.startswith(OVERLAY):
            dst = path[len(OVERLAY):]
            if mode in ("120000", "160000") or typ != "blob":
                raise Refused("the overlay holds a symlink or submodule (%s): refused" % chk._clean(path))
            if _bad_path(dst):
                raise Refused("unsafe overlay path refused")
            if not rules.overlay_ok(path, dst):
                raise Refused("the overlay file %s matches the hard-never list and is not named in release/overlay-allow.txt: refused" % chk._clean(path))
            overlay[dst] = (mode, sha)
            continue
        if not rules.selected(path):
            continue
        if mode in ("120000", "160000") or typ != "blob":
            raise Refused("a selected path is a %s (mode %s): refused (%s)" % ("symlink" if mode == "120000" else "submodule", mode, chk._clean(path)))
        if _bad_path(path):
            raise Refused("unsafe path refused")
        chosen[path] = (mode, sha)
    n_over = len(overlay)
    chosen.update(overlay)
    seen = {}
    for p in chosen:
        k = unicodedata.normalize("NFC", p).casefold()
        if k in seen and seen[k] != p:
            raise Refused("two paths differ only in case or Unicode form (%s): refused" % chk._clean(p))
        seen[k] = p
    return chosen, n_over


def materialise(repo, dest, chosen):
    blobs = read_blobs(repo, [s for _, s in chosen.values()])
    dest = str(dest)
    os.makedirs(dest, 0o755)
    for path in sorted(chosen):
        mode, sha = chosen[path]
        full = os.path.join(dest, path)
        os.makedirs(os.path.dirname(full), 0o755, exist_ok=True)
        fd = os.open(full, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(blobs[sha])
        os.chmod(full, 0o755 if mode == "100755" else 0o644)


def build_tree(repo, dest):
    """Steps 2-3: select, write, overlay. Returns {"chosen", "overlay", "rows"}."""
    rows = list_head(repo)
    rules = load_rules(rows, repo)
    chosen, n_over = select(rows, rules)
    if not chosen:
        raise Refused("nothing is selected for the export")
    materialise(repo, dest, chosen)
    return {"chosen": chosen, "overlay": n_over, "rows": rows}


def dry_run_tree(repo=None):
    """A temp folder holding the dry-run export tree (HEAD blobs only, no dirty-tree rule: release-check is read-only); removed at exit."""
    d = tempfile.mkdtemp(prefix="shipmiracle-dry-")
    os.chmod(d, 0o700)
    atexit.register(shutil.rmtree, d, True)
    tree = os.path.join(d, "tree")
    build_tree(repo or paths.workspace_dir(), tree)
    return tree


# ---------------------------------------------------------------- stage folders
def release_dir():
    paths.assert_isolated(paths.state_dir())
    return state.ensure_dir(state.ensure_root() / "release")


def new_stage(rd):
    rd = str(rd)
    for n in os.listdir(rd):                                     # keep the last stage only
        p = os.path.join(rd, n)
        if re.fullmatch(r"stage-\d+(-\d+)?", n) and os.path.isdir(p) and not os.path.islink(p):
            shutil.rmtree(p, ignore_errors=True)
    base = "stage-%s" % time.strftime("%Y%m%d%H%M%S", time.gmtime(_now()))
    name, k = base, 0
    while os.path.lexists(os.path.join(rd, name)):
        k += 1
        name = "%s-%d" % (base, k)
    p = os.path.join(rd, name)
    os.mkdir(p, 0o700)
    return p


def _read_json(p):
    try:
        return json.loads(state.read_bytes_nofollow(p).decode("utf-8"))
    except (OSError, ValueError, ShipmiracleError):
        return None


def manifests(rd):
    out = []
    for n in os.listdir(str(rd)):
        if re.fullmatch(r"manifest-v\d[0-9A-Za-z.+-]*\.json", n):
            d = _read_json(os.path.join(str(rd), n))
            if isinstance(d, dict) and isinstance(d.get("ts"), int):
                out.append((d["ts"], n, d))
    out.sort(key=lambda x: (x[0], x[1]))
    return [d for _, _, d in out]


# ---------------------------------------------------------------- step 4: release-check
def _default_check(tree, inputs, deny):
    binary = chk.gitleaks_binary()
    return chk.scan(tree, inputs=inputs, deny=deny, deny_required=True, require_gitleaks=False,
                    gitleaks=lambda t: chk.run_gitleaks(t, binary), deny_skip_reason="no denylist on this machine")


def run_check(tree, inputs_dir):
    from . import cli as rcli
    deny = dl.load(rcli.denylist_path())
    if deny is not None and deny.malformed:
        sys.stderr.write("shipm: %d malformed denylist line(s) ignored\n" % deny.malformed)
    inputs = chk.load_inputs(inputs_dir)
    rep = (CHECK or _default_check)(tree, inputs, deny)
    return rep, deny


# ---------------------------------------------------------------- step 5: tests
def run_tests(tree, work):
    """test-all in a copy of the tree with temp HOME/STATE/CONFIG. Returns {"pass": n, "fail": n}; Refused when it did not pass."""
    run_dir = os.path.join(work, "testrun")
    shutil.copytree(tree, run_dir, symlinks=True)
    home = os.path.join(work, "test-home")
    for d in ("", "state", "cfg", "dev"):
        os.makedirs(os.path.join(home, d), 0o700, exist_ok=True)
    # TMPDIR must be under a FIXED temp root (the test isolation refuses any other) and, like a normal run, the system temp folder (/var/folders on macOS); the stage can live anywhere
    sysdir = tempfile.gettempdir()
    fixed = [os.path.realpath(x) for x in ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders")]
    base = sysdir if any(os.path.realpath(sysdir) == t or os.path.realpath(sysdir).startswith(t + os.sep) for t in fixed) else "/tmp"
    tmp = tempfile.mkdtemp(prefix="shipmiracle-testtmp-", dir=base)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": os.environ.get("LANG", "en_US.UTF-8"), "HOME": home, "SHIPMIRACLE_TEST": "1",
           "SHIPMIRACLE_HOME": home, "SHIPMIRACLE_STATE": os.path.join(home, "state"), "SHIPMIRACLE_CONFIG": os.path.join(home, "cfg"), "SHIPMIRACLE_DEV": os.path.join(home, "dev"),
           "SHIPMIRACLE_WS": run_dir, "TMPDIR": tmp}      # bytecode writing stays ON: the latency checks warm the .pyc cache of the throw-away copy, and with PYTHONDONTWRITEBYTECODE every fresh interpreter recompiled (5 ms instead of 0.6 ms, 45 ms instead of 9 ms)
    argv = list(TEST_CMD) if TEST_CMD else [sys.executable, os.path.join(run_dir, "bin", "test-all"), "--retry-failed"]
    try:
        r = subprocess.run(argv, cwd=run_dir, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=3600, shell=False)
    except (OSError, subprocess.SubprocessError) as e:
        raise Refused("test-all could not run in the stage (%s)" % type(e).__name__)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    text = r.stdout.decode("utf-8", "replace")
    log = os.path.join(work, "test-all.log")
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    m = None
    for m in re.finditer(r"^TOTAL: suites (\d+), passed (\d+), failed (\d+)(?:, flaky (\d+))?(?:,.*)?\s*$", text, re.M):
        pass
    if r.returncode != 0 or not m or int(m.group(3)) != 0 or int(m.group(1)) == 0 or int(m.group(2)) == 0:   # zero passed checks means nothing ran, never a pass
        tail = [l for l in text.splitlines() if l.strip()][-5:]
        raise Refused("test-all FAILED in the stage (exit %d); log %s; last lines: %s" % (r.returncode, log, " | ".join(tail)[:600]))
    flaky = int(m.group(4) or 0)
    if flaky > MAX_FLAKY:
        raise Refused("test-all: %d suites were flaky (limit %d): the machine is too loaded or broken, a retry is not a pass; log %s" % (flaky, MAX_FLAKY, log))
    flaky_names = re.findall(r"^  (\S+_test\.\w+): (.*)$", text.split("FLAKY suites", 1)[1], re.M) if flaky and "FLAKY suites" in text else []
    shutil.rmtree(run_dir, ignore_errors=True)
    out = {"pass": int(m.group(2)), "fail": int(m.group(3))}
    if flaky:
        out.update(flaky=flaky, flaky_suites=flaky_names)
    return out


# ---------------------------------------------------------------- step 6-7: the commit
def identity():
    name, email = config.get("release.author_name"), config.get("release.author_email")
    if not name or not email or not NOREPLY_RE.match(email):
        raise Refused("release.author_name / release.author_email are not set to a GitHub noreply identity; run: shipm release denylist --refresh")
    return name, email


def iso_env(home, name, email, ts):
    d = "%d +0000" % ts
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": home, "TZ": "UTC", "LANG": "C", "LC_ALL": "C",
            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_AUTHOR_DATE": d,
            "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email, "GIT_COMMITTER_DATE": d}


ISO_C = ["-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", "-c", "core.autocrlf=false",
         "-c", "core.fsmonitor=false", "-c", "core.safecrlf=false"]


def _g(repo_dir, env, args, check=True, inp=None):
    return _run(ISO_C + ["-C", repo_dir] + args, None, env=env, check=check, inp=inp)


def commit_release(stage, version, tree_dir, name, email, ts):
    """Step 6. Returns the repo folder; HEAD = the release commit, tag vX.Y.Z (lightweight)."""
    repo_dir = os.path.join(stage, "repo")
    shutil.copytree(tree_dir, repo_dir, symlinks=True)
    home = os.path.join(stage, "gith")
    os.mkdir(home, 0o700)
    env = iso_env(home, name, email, ts)
    _run(["init", "-q", "--template=", repo_dir], None, env=env)
    _g(repo_dir, env, ["symbolic-ref", "HEAD", "refs/heads/main"])
    _g(repo_dir, env, ["add", "-f", "-A", "."])
    _g(repo_dir, env, ["commit", "-q", "--no-verify", "--no-gpg-sign", "-m", "Release v%s" % version])
    _g(repo_dir, env, ["tag", "v%s" % version])
    return repo_dir, env


def verify_commit(repo_dir, env, version, name, email, want_tree, deny, rng=None):
    """Step 7 on the tip commit (and, for a commit on top of a parent, only the new commits in `rng`). Raises Refused."""
    tip = _g(repo_dir, env, ["rev-parse", "HEAD"]).stdout.decode().strip()
    args = ["log", "--format=%an%x00%ae%x00%cn%x00%ce"] + ([rng] if rng else [])
    rows = [l.split("\x00") for l in _g(repo_dir, env, args).stdout.decode("utf-8", "replace").splitlines() if l]
    if not rows or len(rows) != 1:
        raise Refused("expected exactly one new release commit, found %d" % len(rows))
    for an, ae, cn, ce in rows:
        if (an, ae, cn, ce) != (name, email, name, email) or not NOREPLY_RE.match(ae) or not NOREPLY_RE.match(ce):
            raise Refused("commit metadata check FAILED: author/committer is not the configured GitHub noreply identity")
    raw = _g(repo_dir, env, ["cat-file", "commit", tip]).stdout.decode("utf-8", "replace")
    head, _, msg = raw.partition("\n\n")
    if msg != "Release v%s\n" % version:
        raise Refused("commit metadata check FAILED: the message is not exactly 'Release v%s' (no trailers allowed)" % version)
    for line in head.splitlines():
        if line.startswith(("author ", "committer ")) and not re.search(r" \d+ \+0000$", line):
            raise Refused("commit metadata check FAILED: a date is not UTC (+0000)")
        if line.startswith(("gpgsig", "encoding", "mergetag")):
            raise Refused("commit metadata check FAILED: unexpected header %s" % line.split(" ")[0])
    if deny is not None:
        m = dl.Matcher(deny)
        if m:
            # The identity lines (verified above to be exactly the configured noreply identity) carry the PUBLIC login by design (D1: author name =
            # login, email = the numeric id plus the login at the GitHub noreply host). Two things are tolerated THERE, nowhere else (31 Oct 2026):
            # (1) the verified noreply email itself (an `email` entry the denylist refresh adds from the GitHub account, which is this address) is cut out of the
            # FIRST author line and the FIRST committer line only, the rest of those lines (name, timestamp) is still scanned; (2) the login-equivalent
            # entries (user == handle). A second author/committer line, any other header, the message and a different email all stay in the full scan.
            ident, other, seen = [], [], set()
            for l in head.splitlines():
                tag = l.split(" ", 1)[0] if l.startswith(("author ", "committer ")) else None
                if tag and tag not in seen:
                    seen.add(tag)
                    ident.append(l)
                else:
                    other.append(l)
            hits = m.search_norm(dl.norm("\n".join(other + ["", msg])))
            for l in ident:
                shown = l.replace("<%s>" % email, "<>")           # the verified identity, byte for byte; the check above made sure it is there
                if shown == l:
                    raise Refused("commit metadata check FAILED: the identity line does not carry the configured email")
                hits += [(k, h, o) for k, h, o in m.search_norm(dl.norm(shown)) if (k, h) not in m.login_hashes]
            if hits:
                raise Refused("commit metadata check FAILED: the raw commit object matches the denylist (%s)"
                              % ", ".join("kind=%s h=%s" % (k, h) for k, h, _ in hits[:5]))
    got = _g(repo_dir, env, ["rev-parse", "HEAD^{tree}"]).stdout.decode().strip()
    if got != want_tree:
        raise Refused("tree check FAILED: the commit's tree %s is not the checked tree %s" % (got[:12], want_tree[:12]))
    return tip


# ---------------------------------------------------------------- step 8: manifest
def file_list(tree):
    out = []
    for root, dirs, files in os.walk(tree):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(root, f)
            st = os.lstat(p)
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
                raise Refused("the stage tree holds a non-regular file: refused")
            h = hashlib.sha256()
            with open(p, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            out.append({"path": os.path.relpath(p, tree).replace(os.sep, "/"), "sha256": h.hexdigest(),
                        "mode": "100755" if st.st_mode & 0o100 else "100644"})
    out.sort(key=lambda x: x["path"])
    return out


def write_manifest(rd, m):
    p = os.path.join(str(rd), "manifest-v%s.json" % m["version"])
    state.atomic_write(p, (json.dumps(m, sort_keys=True, indent=1) + "\n").encode("utf-8"))
    return p


def diff_files(prev, files):
    old = {f["path"]: f["sha256"] for f in (prev or {}).get("files", []) if isinstance(f, dict)}
    new = {f["path"]: f["sha256"] for f in files}
    return sorted(set(new) - set(old)), sorted(set(old) - set(new)), sorted(p for p in new if p in old and old[p] != new[p])


# ---------------------------------------------------------------- owner commands (printed, never run)
def owner_commands(login):
    """The printed next steps for the EXISTING private repo (invited testers). Going public later is a separate step."""
    lg = login or ("<" + "login" + ">")      # built from parts: release-check --require-login must not find the placeholder in this tool
    return [
        "shipm registry add-remote public-engine --remote %s/shipmiracle --visibility private" % lg,
        "shipm config set release.push_enabled true     # only after P9 (the owner's go)",
        "shipm release export --push --yes-publish",
        "# invite a tester (read-only), once per tester:",
        "gh api -X PUT repos/%s/shipmiracle/collaborators/<tester> -f permission=pull" % lg,
        "# after the first push (branch protection):",
        "# needs GitHub Pro/Team for a private repo; skip on a free plan",
        "gh api -X PUT repos/%s/shipmiracle/branches/main/protection --input - <<< "
        "'{\"required_status_checks\":null,\"enforce_admins\":false,\"required_pull_request_reviews\":{\"required_approving_review_count\":1},"
        "\"restrictions\":null,\"allow_force_pushes\":false,\"allow_deletions\":false}'" % lg,
    ]


# ---------------------------------------------------------------- --push
def remote_url(remote):
    if remote.startswith("file://"):
        return remote
    return "https://github.com/%s.git" % remote


def _push_env():
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_") or k in ("GIT_SSH", "GIT_SSH_COMMAND", "GIT_ASKPASS")}


def _owner_gate(remote_is_file):
    """require_owner, but the temp-folder sandbox shortcut (SHIPMIRACLE_TEST=1) only counts for a file:// remote."""
    if "CLAUDECODE" in os.environ:
        test_ok = remote_is_file and os.environ.get("SHIPMIRACLE_TEST") == "1" and paths.sandboxed() and os.environ.get("SHIPMIRACLE_ENFORCE_OWNER") != "1"
        if not test_ok:
            raise SafetyError("shipm release export --push is for the owner in a terminal, not inside a Claude Code chat (CLAUDECODE is set)")


def push_gates(yes_publish, skip_tests):
    """Gates that need no export work; returns the public-engine entry. Order: --yes-publish, owner, terminal, push_enabled, registry."""
    if not yes_publish:
        raise UsageError("--push needs --yes-publish")
    if skip_tests:
        raise Refused("--push cannot be combined with --skip-tests: a run without tests can never be pushed")
    pubs = registry.public_engines()
    remote_is_file = len(pubs) == 1 and (pubs[0]["remote"] or "").startswith("file://")
    _owner_gate(remote_is_file)
    tty = ISATTY() if ISATTY else (sys.stdin.isatty() and sys.stdout.isatty())
    if not tty:
        raise Refused("--push needs a terminal (stdin and stdout are not a TTY)")
    if config.get("release.push_enabled") is not True:
        raise Refused("config release.push_enabled is off; the owner turns it on only after P9: shipm config set release.push_enabled true")
    if len(pubs) != 1:
        raise Refused("--push needs exactly one registry entry with role public-engine (found %d); shipm registry add-remote public-engine ..." % len(pubs))
    vis = pubs[0]["entry"].get("expected_visibility")
    if vis not in ("private", "public") or not pubs[0]["remote"]:
        raise Refused("the public-engine registry entry needs expected_visibility=private or public and an expected remote")
    verify_visibility(pubs[0])
    _say("push: pushing to %s repo %s%s" % (vis.upper(), pubs[0]["remote"], " (invited testers only)" if vis == "private" else ""))
    return pubs[0]


def verify_visibility(pub):
    """The real repo visibility must equal the registry's expected_visibility (read-only `gh api`; any failure refuses). A file:// remote
    (a local bare repo, nothing is published) has no visibility and is accepted only under SHIPMIRACLE_TEST=1."""
    remote, want = pub["remote"], pub["entry"].get("expected_visibility")
    if remote.startswith("file://"):
        if os.environ.get("SHIPMIRACLE_TEST") == "1":
            return
        raise Refused("cannot verify the visibility of a file:// remote: refused")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+", remote):
        raise Refused("cannot verify the visibility: %r is not OWNER/NAME" % remote[:60])
    gh = shutil.which("gh")
    if not gh:
        raise Refused("cannot verify the repo visibility: the gh tool is not installed (needed to check that %s is %s)" % (remote, want))
    # the host and repo come from the command line only: GH_HOST / GH_REPO / GH_ENTERPRISE_TOKEN in the environment must not redirect the call
    env = {k: v for k, v in os.environ.items() if k not in ("GH_HOST", "GH_REPO", "GH_ENTERPRISE_TOKEN")}
    try:
        r = subprocess.run([gh, "api", "--hostname", "github.com", "repos/%s" % remote, "--jq", "[.full_name,.private]|@tsv"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, shell=False, env=env)
    except (OSError, subprocess.SubprocessError) as e:
        raise Refused("cannot verify the repo visibility: gh could not run (%s)" % type(e).__name__)
    parts = r.stdout.decode("utf-8", "replace").strip().split("\t")
    if r.returncode != 0 or len(parts) != 2 or parts[1] not in ("true", "false"):
        raise Refused("cannot verify the repo visibility of %s (gh exit %d; sign in with gh auth login and check the name): refused" % (remote, r.returncode))
    if parts[0].lower() != remote.lower():
        raise Refused("the registry remote %s is now called %s on GitHub (renamed or transferred): refused; fix the registry remote first"
                      % (remote, parts[0][:80]))
    real = "private" if parts[1] == "true" else "public"
    if real != want:
        raise Refused("the registry says %s is %s but it is really %s: refused (fix the registry or the repo visibility first)"
                      % (remote, want.upper(), real.upper()))


def install_hook(repo_dir):
    hooks = os.path.join(repo_dir, ".git", "hooks")
    os.makedirs(hooks, exist_ok=True)
    engine = str(paths.workspace_dir())
    body = ("#!/usr/bin/env bash\n# shipm release stage: the registry guard decides (exit 1 refuses). Written by shipm release export.\n"
            "refs=$(cat)\nprintf '%%s\\n' \"$refs\" | %s push-check \"${1:-}\" \"${2:-}\" || exit 1\n"
            % shlex.quote(os.path.join(engine, "bin", "shipm")))
    p = os.path.join(hooks, "pre-push")
    with open(p, "w") as f:
        f.write(body)
    os.chmod(p, 0o755)
    return hooks


def _remote_refs(repo_dir, url, version):
    r = _run(["ls-remote", "--refs", url, "refs/heads/main", "refs/tags/v%s" % version], repo_dir, env=_push_env(), check=False, timeout=90)
    if r.returncode != 0:
        raise Refused("git ls-remote failed (exit %d): the public remote is not reachable" % r.returncode)
    main = tag = None
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        sha, _, ref = line.partition("\t")
        if ref == "refs/heads/main":
            main = sha
        elif ref == "refs/tags/v%s" % version:
            tag = sha
    return main, tag


PUSHED_FILE = "pushed.json"      # {"v":1,"version","commit","ts"}: the last release that reached the public remote (survives a re-export of any version)


def last_pushed(rd):
    d = _read_json(os.path.join(str(rd), PUSHED_FILE))
    return d if isinstance(d, dict) and d.get("v") == 1 and isinstance(d.get("commit"), str) else None


def do_push(ctx, pub, rd):
    """Steps 10: slug, ls-remote, ancestry, push. ctx: repo_dir, env, version, name, email, tree_sha, deny, manifest, mpath."""
    remote = pub["remote"]
    url = remote_url(remote)
    version, repo_dir, env = ctx["version"], ctx["repo_dir"], ctx["env"]
    vis = (pub["entry"].get("expected_visibility") or "").upper()
    note = "PRIVATE, invited testers only" if vis == "PRIVATE" else "PUBLIC, ANYONE CAN READ IT"
    prompt = "Type the repository to publish to (%s, %s) to confirm: " % (remote, note)
    typed = ASK(prompt) if ASK else input(prompt)
    if typed != remote:
        raise Refused("the typed repository does not match %s: nothing pushed" % remote)
    verify_visibility(pub)       # again, right before the push: the export took minutes
    main, tag = _remote_refs(repo_dir, url, version)
    if tag:
        raise Refused("the remote already has tag v%s: refused" % version)
    last = last_pushed(rd)
    tip = ctx["commit"]
    if main is None:
        _say("push: the remote is empty: first release (root commit)")
    else:
        if main != (last or {}).get("commit"):
            raise Refused("the remote main (%s) is not the last pushed release (%s): refused; look at the remote before anything else"
                          % (main[:12], ((last or {}).get("commit") or "none")[:12]))
        _run(["fetch", "-q", url, "refs/heads/main"], repo_dir, env=_push_env(), timeout=300)
        got = _g(repo_dir, env, ["rev-parse", "FETCH_HEAD"]).stdout.decode().strip()
        if got != main:
            raise Refused("the fetched main differs from ls-remote: refused")
        newc = _g(repo_dir, env, ["commit-tree", "HEAD^{tree}", "-p", main, "-m", "Release v%s" % version]).stdout.decode().strip()
        _g(repo_dir, env, ["update-ref", "refs/heads/main", newc])
        _g(repo_dir, env, ["tag", "-f", "v%s" % version, newc])
        tip = verify_commit(repo_dir, env, version, ctx["name"], ctx["email"], ctx["tree_sha"], ctx["deny"], rng="%s..%s" % (main, newc))
    # the guard in-process too (the hook is the second layer)
    lines = "refs/heads/main %s refs/heads/main %s\nrefs/tags/v%s %s refs/tags/v%s %s\n" % (tip, main or "0" * 40, version, tip, version, "0" * 40)
    res = pushcheck.check("origin", url, lines, cwd=repo_dir)
    if res.refused:
        raise Refused("; ".join(res.lines))
    hooks = install_hook(repo_dir)
    _say("push: git push %s main v%s" % (remote, version))
    r = _run(["-c", "core.hooksPath=" + hooks, "push", url, "main", "v%s" % version], repo_dir, env=_push_env(), check=False, timeout=600)
    if r.returncode != 0:
        raise Refused("git push FAILED (exit %d): %s" % (r.returncode, r.stderr.decode("utf-8", "replace").strip()[-300:]))
    m = dict(ctx["manifest"])
    m.update({"commit_sha": tip, "pushed": True, "push_ts": _now()})
    write_manifest(rd, m)
    state.atomic_write(os.path.join(str(rd), PUSHED_FILE), (json.dumps({"v": 1, "version": version, "commit": tip, "ts": _now()}, sort_keys=True) + "\n").encode("utf-8"))
    return tip


# ---------------------------------------------------------------- the whole thing
def export(repo=None, version=None, skip_tests=False, push=False, yes_publish=False):
    repo = str(repo or paths.workspace_dir())
    pub = push_gates(yes_publish, skip_tests) if push else None
    # 1
    info = source_info(repo)
    if info["dirty"]:
        raise Refused("the source work tree is not clean (modified or untracked files): commit or remove them first")
    _say("export: source %s on %s" % (info["head"][:12], info["branch"]))
    rd = release_dir()
    stage = new_stage(rd)
    tree = os.path.join(stage, "tree")
    # 2-3
    built = build_tree(repo, tree)
    chosen = built["chosen"]
    _say("export: %d files (%d from the overlay) in %s" % (len(chosen), built["overlay"], stage))
    inputs_dir = os.path.join(stage, "inputs")
    by = {p: s for m, t, s, p in built["rows"]}
    blobs = read_blobs(repo, [by[n] for n in INPUT_FILES if n in by])
    for n in INPUT_FILES:
        if n in by:
            dst = os.path.join(inputs_dir, n[len("release/"):])
            os.makedirs(os.path.dirname(dst), 0o700, exist_ok=True)
            with open(dst, "wb") as f:
                f.write(blobs[by[n]])
    vfile = blobs[by["release/VERSION"]].decode().strip() if "release/VERSION" in by else None
    if version is None:
        version = vfile
    if not version or not chk.VERSION_RE.fullmatch(version):
        raise Refused("no valid version (release/VERSION or --version x.y.z)")
    if vfile is not None and version != vfile:
        raise Refused("--version %s differs from release/VERSION %s" % (version, vfile))
    name, email = identity()
    # 4
    rep, deny = run_check(tree, inputs_dir)
    for line in rep.lines():
        _say("check: " + line)
    if rep.result != "PASS":
        raise Refused("release-check FAILED (%d findings): nothing committed; stage kept at %s" % (len(rep.findings), stage))
    chk.write_stamp(rep, {"no_denylist": False, "require_denylist": True, "require_gitleaks": False, "denylist_used": deny is not None})
    if any(c == "secrets/gitleaks" for c, _ in rep.skipped):
        _say("note: gitleaks is not installed: the gitleaks scan was SKIPPED (brew install gitleaks)")
    # 5
    if skip_tests:
        tests = "SKIPPED"
        _say("tests: SKIPPED (--skip-tests): this stage can never be pushed")
    else:
        tests = run_tests(tree, stage)
        _say("tests: test-all passed %d, failed %d, flaky %d" % (tests["pass"], tests["fail"], tests.get("flaky", 0)))
        for n_, first_ in tests.get("flaky_suites", []):
            _say("  FLAKY (passed alone on retry): %s: %s" % (n_, first_[:160]))
    # 6-7
    ts = _now()
    repo_dir, env = commit_release(stage, version, tree, name, email, ts)
    commit = verify_commit(repo_dir, env, version, name, email, rep.tree_sha, deny)
    _say("commit: %s v%s tree %s (author %s, UTC, no trailers)" % (commit[:12], version, rep.tree_sha[:12], email))
    # 8
    files = file_list(tree)
    prevs = manifests(rd)
    manifest = {"version": version, "source_sha": info["head"], "source_branch": info["branch"], "tree_sha": rep.tree_sha,
                "commit_sha": commit, "files": files,
                "check": {"result": "PASS", "tree_sha": rep.tree_sha, "files": rep.files, "skipped": [c for c, _ in rep.skipped]},
                "tests": tests, "ts": ts, "stage": stage}
    added, removed, changed = diff_files(prevs[-1] if prevs else None, files)
    mpath = write_manifest(rd, manifest)
    _say("manifest: %s (%d files)" % (mpath, len(files)))
    if prevs:
        _say("since the last manifest (v%s): %d added, %d removed, %d changed" % (prevs[-1].get("version"), len(added), len(removed), len(changed)))
        for tag, lst in (("added", added), ("removed", removed)):
            for p in lst[:SHOW_LIMIT]:
                _say("  %s %s" % (tag, chk._clean(p)))
            if len(lst) > SHOW_LIMIT:
                _say("  %s ... %d more" % (tag, len(lst) - SHOW_LIMIT))
    else:
        _say("since the last manifest: none (first export)")
    result = {"stage": stage, "version": version, "tree_sha": rep.tree_sha, "commit_sha": commit, "manifest": mpath, "tests": tests,
              "added": added, "removed": removed}
    if not push:
        m = NOREPLY_RE.match(email)
        _say("")
        _say("DRY RUN: nothing was pushed or published. Stage: %s" % stage)
        _say("Look at the file list above, then (in your own terminal, after P9) run:")
        for c in owner_commands(m.group(1) if m else None):
            _say("  " + c)
        return result
    ctx = {"version": version, "repo_dir": repo_dir, "env": env, "name": name, "email": email, "tree_sha": rep.tree_sha, "deny": deny,
           "commit": commit, "manifest": manifest}
    result["pushed_commit"] = do_push(ctx, pub, rd)
    _say("PUSHED v%s (%s) to %s" % (version, result["pushed_commit"][:12], pub["remote"]))
    return result


def run(a) -> int:
    if a.push and a.dry_run:
        raise UsageError("--push and --dry-run exclude each other")
    export(version=a.version, skip_tests=bool(a.skip_tests), push=bool(a.push), yes_publish=bool(a.yes_publish))
    return 0
