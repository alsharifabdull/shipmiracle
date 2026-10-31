"""Autopilot hard stops H1..H9 (Phase 6 spec section 2). Pure: no hook plumbing, no events, no state files.

    check(event, tool, tool_input, cwd, ctx) -> [Stop(rule, id, text, ...)]      ([] = nothing to stop)

Detection is token level on flow's tokenizer (shipmiracle.hooks.flow: cmd_segments / norm_seg / blank_quotes / glob_re / bash_targets / admin_seg; importing it has no
side effect, checked by tests/hardstop_test.py). Quoted words are data: `echo "git push -f"` is one word of echo. Exceptions that are scanned for
FORBIDDEN literals: inline interpreter code (-c/-e), heredocs into an interpreter or shell, SQL client arguments, changed scripts, test-runner added lines.
Anything the tokenizer cannot resolve (parse error, `cd $X`, `git $X`, `eval`, a pipe into a shell, a changed script that fails the scan) is H9: fail closed.
Everything environmental comes in through Ctx, so tests need no git for most cases. Python 3.9."""
from __future__ import annotations

import fnmatch
import glob as _glob
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from typing import Callable, Dict, List, NamedTuple, Optional, Set

from shipmiracle import paths
from shipmiracle.hooks import flow as F
from . import rules as R

RAISE = False             # tests: let internal errors surface instead of becoming H9
DISABLED = set()          # rule ids switched off; ONLY for the mutation test in tests/hardstop_test.py (production never sets it)


class Stop(NamedTuple):
    rule: str                      # "H1".."H9"
    id: str                        # "H-" + 6 hex
    text: str                      # the deny text, spec section 2 "On a stop"
    label: str = ""                # "H2-publish"
    excerpt: str = ""              # <= 200 chars, secrets redacted
    cmd_sha: str = ""              # sha256 of the command / path the id was made from


class Ctx:
    """Everything environmental a check needs (a plain class: dataclasses+inspect cost ~4 ms of import on every hook call; same keyword API as before).
    root: the auto worktree root. base_sha. scope: scope globs (relative). deps_mode "none"|"listed", deps_names, mcp_allow.
    tracked(rel) -> tracked files at or under rel ("." = whole tree); None = `git ls-files`.
    changed: rel paths changed since base (diff --name-only + untracked), a set or a callable returning one (lazy).
    test_paths, dep_files, active_cr, ends, auto_branch, ahead (commits on the auto branch after base; None = unknown),
    ref_ok(ref) (is it the auto branch / a commit after the CR base?), read_text(rel), added_text(rel) (added lines since base; default `git diff -U0`),
    test_command, declared(kind, name) (is an npm/pip package declared by the project; default reads package.json / requirements / pyproject and the local bin), limit (None|"budget"|"time"|"budget_unknown"|"near", H8 from the engine), engine_block ("verify_twice" on SubagentStop, H7),
    home, tmp_roots, extra_protected."""
    _LISTS = ("hooks_rel", "scope", "deps_names", "mcp_allow", "test_paths", "dep_files", "ends", "extra_protected")
    _DEFAULTS = {"base_sha": "", "scope": None, "deps_mode": "none", "deps_names": None, "mcp_allow": None, "tracked": None, "changed": None, "test_paths": None,
                 "dep_files": None, "active_cr": None, "ends": None, "auto_branch": "", "ahead": None, "ref_ok": None, "read_text": None, "added_text": None,
                 "test_command": "", "hooks_rel": None, "declared": None, "limit": None, "engine_block": None, "home": "", "tmp_roots": None, "extra_protected": None}

    def __init__(self, root, **kw):
        bad = set(kw) - set(self._DEFAULTS)
        if bad:
            raise TypeError("Ctx got unexpected keyword arguments: %s" % ", ".join(sorted(bad)))
        self.root = root
        for k, dflt in self._DEFAULTS.items():
            v = kw.get(k, dflt)
            if v is None and k in self._LISTS:
                v = []
            elif k == "changed" and v is None:
                v = set()
            setattr(self, k, v)

    def __repr__(self):
        return "Ctx(root=%r)" % (self.root,)


# ---------------------------------------------------------------------------------------------------------------------------------------------
def _fold(p):
    return paths.fold(p)


def _pf(p):
    """Key for the PROTECTED paths: always case-folded (same as the gate's pfold)."""
    return os.path.normcase(str(p)).casefold()


def _cf(p):
    """A name below the worktree for the lower-case rule tables (RECORD_FILES, EXTRA_GATE_NAMES): always case-folded, on every OS. A Linux file system keeps
    CLAUDE.md and claude.md apart, but the rule is about the NAME: a file called CLAUDE.md is one the agent reads as instructions wherever it runs."""
    import unicodedata
    return unicodedata.normalize("NFC", str(p)).casefold()


def _git(root, args, timeout=5):
    env = {"PATH": "/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin", "HOME": os.path.expanduser("~"), "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"}
    try:
        r = subprocess.run(["git", "-C", root, "-c", "core.fsmonitor=false"] + list(args), env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


def _words(s):
    return s.split()


class Seg:
    __slots__ = ("raw", "a", "u", "ww", "depth", "xargs", "lead")

    def __init__(self, raw, a, u, ww, depth, xargs=False, lead=()):
        self.raw = raw; self.a = a; self.u = u; self.ww = ww; self.depth = depth; self.xargs = xargs; self.lead = lead


KEYWORDS = ("if", "then", "else", "elif", "do", "while", "until", "!", "time", "coproc", "function", "select")


class _Run:
    def __init__(self, ctx, cwd):
        self.ctx = ctx
        self.root = os.path.realpath(ctx.root)
        self.froot = _fold(self.root).rstrip("/")
        self.cwd = cwd if isinstance(cwd, str) and os.path.isabs(cwd) else self.root
        self.hits = []                       # (rule, excerpt, subject-or-None, sub-label)
        self.home = os.path.realpath(ctx.home or str(paths.home()))
        tmp = ctx.tmp_roots
        if tmp is None:
            tmp = ["/tmp", "/private/tmp", "/var/folders", "/private/var/folders"]               # fixed roots: a chat-set TMPDIR must not widen what the hard stop treats as scratch space
        self.tmp = [_fold(os.path.realpath(t)).rstrip("/") for t in tmp if t and os.path.realpath(t) not in ("/", self.home)]
        self.scope_re = [F.glob_re(_fold(g)) for g in ctx.scope if isinstance(g, str) and g]
        self.test_re = [F.glob_re(_fold(g)) for g in ctx.test_paths if isinstance(g, str) and g]
        self.dep_files = {_fold(d) for d in ctx.dep_files}
        self._changed_folded = None             # `ctx.changed` may be a set or a callable returning one: resolved on first use (the hook pays for git only when a rule needs it)
        self._changed_raw = None
        self.cr_ends = set(ctx.ends or [])
        self._tracked = {}
        self.written = set()
        self._prot_dirs = None
        self.deadline_hits = 0
        self._declared = {}
        self._env_cache = {}

    @property
    def changed(self):
        if self._changed_folded is None:
            raw = self.ctx.changed() if callable(self.ctx.changed) else self.ctx.changed
            self._changed_raw = set(raw or ())
            self._changed_folded = {_fold(c) for c in self._changed_raw}
        return self._changed_folded

    # ------------------------------------------------------------------ results
    def hit(self, rule, excerpt, subject=None, sub=None):
        self.hits.append((rule, R.excerpt(excerpt), subject, sub))

    def rules_hit(self):
        return {h[0] for h in self.hits}

    # ------------------------------------------------------------------ paths
    def expand(self, p):
        """Text of a path word with the few variables we know; None when it still has an unknown variable or substitution."""
        if not isinstance(p, str) or not p or "\x00" in p:
            return None
        for sub_, rep_ in (("$(pwd)", self.cwd), ("`pwd`", self.cwd), ("$(git rev-parse --show-toplevel)", self.root), ("`git rev-parse --show-toplevel`", self.root)):
            if p.startswith(sub_):
                p = rep_ + p[len(sub_):]
        for v in ("${HOME}", "$HOME"):
            if p.startswith(v + "/") or p == v:
                p = self.home + p[len(v):]
        for v in ("${PWD}", "$PWD"):
            if p.startswith(v + "/") or p == v:
                p = self.cwd + p[len(v):]
        for v in ("${CLAUDE_PROJECT_DIR}", "$CLAUDE_PROJECT_DIR"):
            if p.startswith(v + "/") or p == v:
                p = self.root + p[len(v):]
        if p == "~" or p.startswith("~/"):
            p = self.home + p[1:]
        elif p.startswith("~"):
            return None
        if "$" in p or "`" in p:
            return None
        return p

    def real(self, p, base=None):
        e = self.expand(p)
        if e is None:
            return None
        if not os.path.isabs(e):
            e = os.path.join(base or self.cwd, e)
        return os.path.realpath(e)

    def inside(self, ap):
        k = _fold(ap)
        return k == self.froot or k.startswith(self.froot + "/")

    def rel(self, ap):
        r = os.path.relpath(ap, self.root)
        if r == ".." or r.startswith("../"):             # case-different spelling of the same root (macOS)
            k = _fold(ap)
            if self.inside(ap):
                return ap[len(self.root) + 1:] if len(ap) > len(self.root) else "."
        return r

    def is_tmp(self, ap):
        k = _fold(ap)
        return any(k == t or k.startswith(t + "/") for t in self.tmp) or k == "/dev/null" or k.startswith("/dev/")

    def in_scope(self, rel):
        fr = _fold(rel)
        if fr == ".":
            return True
        if self.is_record(rel):
            return True
        if self.is_always_excluded(_cf(rel)):
            return False
        return any(rx.match(fr) for rx in self.scope_re)

    def is_record(self, rel):
        """docs/STATUS.md and docs/DECISIONS.md (the record files an autopilot run may always write): folded only where the file system ignores case (macOS, a WSL Windows drive);
        on a case-sensitive file system only the exact names count, DOCS/STATUS.MD is another file there (D9 m1). The exclusion tables keep _cf: a name is a name wherever it runs."""
        rel = str(rel)
        if _cf(rel) not in R.RECORD_FILES:
            return False
        probe = self.root.rstrip("/") + "/A"
        if _fold(probe) != os.path.normcase(probe):               # the file system folds case
            return True
        return rel in R.RECORD_EXACT

    @staticmethod
    def is_always_excluded(fr):
        parts = fr.split("/")
        if parts[0] in (".shipmiracle", ".claude", ".githooks", ".git", ".co" "dex", ".husky") or fr == ".mcp.json" or fr in R.PERSIST_PROJECT_FILES \
                or fr.startswith(".github/workflows/") or fr == ".github/workflows":
            return True
        return parts[-1].startswith(".env") or parts[-1] in R.EXTRA_GATE_NAMES

    def scope_ok(self, ap):
        if self.inside(ap):
            return self.in_scope(self.rel(ap))
        return self.is_tmp(ap)

    def prot_dirs(self):
        if self._prot_dirs is None:
            h = self.home
            ws = str(paths.workspace_dir())
            dirs = [h + "/.claude", str(paths.config_dir()), str(paths.state_dir()), h + "/.ssh", h + "/.aws", h + "/.config/gh", h + "/.gnupg", h + "/.kube",
                    h + "/.docker", h + "/.local/share/keyrings", h + "/.local/share/shipmiracle", h + "/.local/lib",   # Linux: keyring, engine link, user site-packages
                    ws + "/hooks", ws + "/shipmiracle", ws + "/bin", ws + "/config"]
            dirs += [h + "/" + d for d in R.PERSIST_HOME_DIRS] + list(R.PERSIST_ABS_DIRS)
            for g in R.PERSIST_HOME_GLOBS:
                dirs += _glob.glob(h + "/" + g)                                                      # the macOS user site-packages (one folder per python version)         # the shared persistence table (launch agents, git config, user units, autostart, session environment)
            dirs += list(self.ctx.extra_protected or [])
            gf = os.path.join(self.root, ".git")
            try:
                if os.path.isfile(gf):
                    first = open(gf, encoding="utf-8", errors="replace").readline().strip()
                    if first.startswith("gitdir:"):
                        gd = first[7:].strip()
                        dirs.append(gd if os.path.isabs(gd) else os.path.join(self.root, gd))
                        dirs.append(os.path.dirname(os.path.dirname(gd if os.path.isabs(gd) else os.path.join(self.root, gd))))   # the main .git
            except OSError:
                pass
            self._prot_dirs = [_pf(os.path.realpath(d)).rstrip("/") for d in dirs if d]
            self._prot_files = [_pf(os.path.realpath(h + "/" + f)) for f in R.PERSIST_HOME_FILES]
        return self._prot_dirs

    def protected(self, ap, kind="write"):
        """H5: files that control the gate, hooks, settings, secrets, persistence. Real path in; compared case-folded on every OS like the gate's pfold (D9 m4): a spelling that only
        looks like a protected folder on a case-sensitive file system is refused too (over-refusal inside the protected folders, never an opening)."""
        k = _pf(ap)
        base = os.path.basename(k)
        if base.startswith(".env") and base != ".env.example":
            return True
        if self.inside(ap):
            rel = _pf(self.rel(ap))
            if rel == ".":
                return kind == "remove"
            parts = rel.split("/")
            if parts[0] in (".shipmiracle", ".claude", ".githooks", ".co" "dex", ".husky") or ".git" in parts or rel == ".mcp.json" or rel in R.PERSIST_PROJECT_FILES \
                    or rel == ".github/workflows" or rel.startswith(".github/workflows/"):
                return True
            if kind == "remove" and rel in (".github",):
                return True
        else:
            if ".git" in k.split("/") and not self.is_tmp(ap):
                return True
        for d in self.prot_dirs():
            if k == d or k.startswith(d + "/"):
                return True
            if kind == "remove" and d.startswith(k.rstrip("/") + "/"):
                return True
        if k in self._prot_files:
            return True
        return False

    def sens_word(self, w):
        """A word that names a secret / credential location (H5: reads and edits)."""
        if not isinstance(w, str) or not w or not any(k in w for k in SENS_KEYS):
            return False
        w = re.sub(r"^\d*[<>]+&?", "", w)
        cands = [w]
        if w.startswith("-") and "=" in w:
            cands.append(w.split("=", 1)[1])
        for c in cands:
            e = self.expand(c) or c
            e = e.rstrip("/")
            if re.search(r"(?:^|/)\.(?:ssh|aws|gnupg|kube)(?:/|$)", e) or re.search(r"(?:^|/)\.config/gh(?:/|$)", e) or re.search(r"(?:^|/)\.docker/config\.json$", e):
                return True
            if re.search(r"(?:^|/)(?:\.netrc|\.pypirc|\.git-credentials)$", e) or re.search(r"(?:^|/)Library/Launch(?:Agents|Daemons)(?:/|$)", e):
                return True
            if re.search(r"(?:^|/)\.local/share/keyrings(?:/|$)", e) or PROC_ENVIRON.search(os.path.normpath(e)):
                return True                                       # D9 M3: the Linux keyring and other processes' environments are read like ~/.ssh
            b = e.rsplit("/", 1)[-1]
            if b.startswith(".env") and b != ".env.example":
                return True
        return False

    # ------------------------------------------------------------------ git facts
    def tracked_under(self, rel):
        key = rel
        if key in self._tracked:
            return self._tracked[key]
        if self.ctx.tracked is not None:
            out = list(self.ctx.tracked(rel) or [])
        else:
            o = _git(self.root, ["ls-files", "-z", "--", rel]) if rel not in (".", "") else _git(self.root, ["ls-files", "-z"])
            out = [x for x in (o or "").split("\0") if x]
        self._tracked[key] = out
        return out

    def read_rel(self, rel):
        if self.ctx.read_text is not None:
            return self.ctx.read_text(rel)
        p = os.path.join(self.root, rel)
        try:
            if os.path.getsize(p) > 2000000:
                return None
            with open(p, encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return None

    def added(self, rel):
        if self.ctx.added_text is not None:
            return self.ctx.added_text(rel)
        if self.tracked_under(rel):
            o = _git(self.root, ["diff", "-U0", self.ctx.base_sha or "HEAD", "--", rel])
            if o is None:
                return None
            return "\n".join(ln[1:] for ln in o.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
        return self.read_rel(rel)

    def ref_ok(self, ref):
        c = self.ctx
        if c.ref_ok is not None:
            return bool(c.ref_ok(ref))
        if ref in ("HEAD", "@"):
            return True
        if c.auto_branch and ref in (c.auto_branch, "refs/heads/" + c.auto_branch):
            return True
        m = re.fullmatch(r"(?:HEAD|@)(?:~(\d*)|\^+)", ref)
        if m and c.ahead is not None:
            n = int(m.group(1)) if m.group(1) else (ref.count("^") or 1)
            return n <= c.ahead
        return False

    # ------------------------------------------------------------------ entry: Bash
    def bash(self, cmd, depth=0, cwd=None):
        if len(cmd) > R.BIG_CMD:
            self.hit("H9", "command longer than 100 KB (%d bytes)" % len(cmd))
            return
        if cwd is not None:
            self.cwd = cwd
        bodies = self.heredocs(cmd)
        main = cmd
        for a0, b0 in reversed(self.hd_spans):
            main = main[:a0] + main[b0:]
        if sum(main.count(ch) for ch in ";|&(){}<>$\\'\"`") > R.MAX_SPECIAL:
            self.hit("H9", "command too complex to check (%d operator and quote characters)" % sum(main.count(ch) for ch in ";|&(){}<>$\\'\"`"))
            return
        if main.count(" ") + main.count("\n") + main.count("\t") > R.MAX_WORDS * 2:
            self.hit("H9", "command has more than %d words" % R.MAX_WORDS)
            return
        bq = F.blank_quotes(main)
        segs = []
        self.collect(cmd, depth, segs)
        if len(segs) > R.MAX_SEGS or sum(len(x.raw) for x in segs) > R.MAX_WORDS:
            self.hit("H9", "command has more than %d simple commands or %d words" % (R.MAX_SEGS, R.MAX_WORDS))
            return
        self.syntax(cmd, bq, segs)
        if PROC_ENV_TEXT.search(re.sub(r"\$\{[^}]*\}|\$\([^)]*\)|`[^`]*`", "X", cmd)):
            self.hit("H5", "reads the environment of another process (/proc/<pid>/environ)")
        try:                                              # owner proof (OP6): the raw text of the command names an autopilot admin command, or a launcher runs code outside this chat
            gsegs = [(s.a, s.u, s.ww) for s in segs] + F.all_segs(cmd)     # the gate's own view as well: every find -exec clause, the commands inside sh -c (D9)
            rt = F.raw_admin(cmd, gsegs)
            if rt == F.DECODE_TEXT:
                rt = ""                                   # eval / decoded text into a shell are hardstop's own H9 rules (below), not H5
            if not rt and any(w_ and F._cmd_name(w_[0]) in F.HARD_LAUNCHERS for _a, _u, w_ in gsegs):
                rt = "a launcher that runs code outside this chat"
            if rt:
                self.hit("H5", "%s" % rt[:140])
        except Exception:
            pass
        for s in segs:
            self.seg(s)
        self.pipe_xargs(segs)
        for prefix, body in bodies:
            self.heredoc(prefix, body, depth)
        self.targets(cmd, depth)

    def targets(self, cmd, depth):
        """Write targets by flow's own parser: H5 for protected files, H6 for anything outside the scope."""
        def p5(ap, kind="write"):
            # flow's parser hands over the path as written (L4: a link is judged as a link): protected if the link itself or its target is
            return self.protected(ap, kind) or self.protected(os.path.realpath(ap), kind)

        def p6(ap, kind="write"):
            ap = os.path.realpath(ap)                    # compare the RESOLVED path with the scope and the temp roots (/tmp is /private/tmp, a link may leave the tree)
            if kind != "write" or ap == self.root or ap == "/dev/null" or ap.startswith("/dev/"):
                return False
            if not os.path.exists(ap) and re.fullmatch(r"[+=-][rwxXst]+|[ugoa]*[-+=][rwxXstugo,+=-]+|[0-7]{3,4}|[\w.-]*:[\w.-]*", os.path.basename(ap)):
                return False                                 # chmod / chown arguments flow's parser takes for paths
            return not self.scope_ok(ap) and not self.protected(ap, kind)
        try:
            b5 = F.bash_targets(cmd, self.cwd, self.root, p5)
            b6 = F.bash_targets(cmd, self.cwd, self.root, p6)
        except Exception as e:
            self.hit("H9", "the command cannot be parsed (%s)" % (str(e)[:60] or type(e).__name__))
            return
        for x in b5[:3]:
            self.hit("H5", "write to a protected file: %s" % x)
        for x in b6[:3]:
            self.hit("H6", "write outside the charter scope: %s" % x)

    # ------------------------------------------------------------------ tokenising
    def collect(self, text, depth, out):
        for raw in F.cmd_segments(text[:R.BIG_CMD]):
            # flow's norm_seg (P3 R2) rewrites `find ... -exec CMD` to CMD; the find rules here need the find command itself, so cut before -exec
            fx = next((i for i, x in enumerate(raw) if x in F.EXEC_FLAGS and any(os.path.basename(y) == "find" for y in raw[:i])), None)
            if fx is not None:
                a, u, wp = F.norm_seg(raw[:fx])
                lead = tuple(raw[:fx - len(wp)])
                ww = list(wp) + list(raw[fx:])
            else:
                a, u, ww = F.norm_seg(raw)
                lead = tuple(raw[:len(raw) - len(ww)]) if "ENVSPLIT" not in a else tuple(raw)     # env -S re-tokenises its value: the length arithmetic no longer holds
                ww = list(ww)
            while ww and ww[0] in KEYWORDS:
                ww = ww[1:]
            ww, xargs = self.strip_extra(ww)
            out.append(Seg(raw, a, u, ww, depth, xargs, lead))
            if not ww:
                continue
            b = os.path.basename(ww[0])
            if b in F.SHELLS or b == "fish":
                k = next((i for i in range(1, len(ww) - 1) if re.match(r"^-\w*c$", ww[i])), None)
                if k is not None:
                    if depth >= R.MAX_DEPTH:
                        self.hit("H9", "shell -c nested deeper than %d levels" % R.MAX_DEPTH)
                    else:
                        self.collect(ww[k + 1], depth + 1, out)
            elif b == "eval":
                if depth >= R.MAX_DEPTH:
                    self.hit("H9", "eval nested deeper than %d levels" % R.MAX_DEPTH)
                else:
                    self.collect(" ".join(ww[1:]), depth + 1, out)

    @staticmethod
    def strip_extra(ww):
        xargs = False
        while ww and os.path.basename(ww[0]) in R.EXTRA_WRAPPERS:
            b = os.path.basename(ww[0]); i = 1
            if b == "xargs":
                xargs = True
                while i < len(ww) and ww[i].startswith("-"):
                    i += 2 if ww[i] in ("-I", "-n", "-P", "-L", "-d", "-E", "-s", "-a", "-R", "-S") else 1
            elif b in ("timeout", "gtimeout"):
                while i < len(ww) and ww[i].startswith("-"):
                    i += 2 if ww[i] in ("-s", "-k", "--signal", "--kill-after") else 1
                i += 1
            elif b in ("watch",):
                while i < len(ww) and ww[i].startswith("-"):
                    i += 2 if ww[i] in ("-n", "--interval", "-d") else 1
            else:
                while i < len(ww) and ww[i].startswith("-"):
                    i += 1
            ww = ww[i:]
        return ww, xargs

    def heredocs(self, c):
        """[(prefix text before the <<, body)]: heredoc bodies, found the way flow.cmd_segments skips them (quotes and comments respected)."""
        out = []; i = 0; n = len(c); pend = []; sep_at = 0; self.hd_spans = []
        while i < n:
            ch = c[i]
            if ch == "'":
                j = c.find("'", i + 1); i = n if j < 0 else j + 1
            elif ch == '"':
                j = i + 1
                while j < n and c[j] != '"':
                    j += 2 if c[j] == "\\" else 1
                i = j + 1
            elif ch == "\\":
                i += 2
            elif ch == "#" and (i == 0 or c[i - 1] in " \t\n;&|("):
                j = c.find("\n", i); i = n if j < 0 else j
            elif ch == "<" and c.startswith("<<", i) and not c.startswith("<<<", i):
                j = i + 2
                if c.startswith("-", j):
                    j += 1
                while j < n and c[j] in " \t":
                    j += 1
                k = j
                while k < n and c[k] not in " \t\n;&|<>()":
                    k += 1
                pend.append((c[sep_at:i], c[j:k].replace("'", "").replace('"', "").replace("\\", ""), c.startswith("<<-", i)))
                i = k
            elif ch == "\n":
                i += 1
                if pend:
                    s0 = i
                    for prefix, delim, dash in pend:
                        lines = []
                        while i < n:
                            e = c.find("\n", i); e = n if e < 0 else e
                            line = c[i:e]; i = min(e + 1, n)
                            if (line.lstrip("\t") if dash else line) == delim:
                                break
                            lines.append(line)
                        out.append((prefix, "\n".join(lines)))
                    self.hd_spans.append((s0, i))
                    pend = []
                sep_at = i
            else:
                if ch in ";&|(":
                    sep_at = i + 1
                i += 1
        return out

    # ------------------------------------------------------------------ syntax-level checks (raw text with quotes blanked)
    def syntax(self, cmd, bq, segs):
        main = bq
        if re.search(r"(?<![&>|<])&(?![&>])[ \t]*(?:\n|;|\)|$)", main.rstrip() + "\n") and re.search(r"[^\s&]", main):
            self.hit("H5", "background process (trailing &)")
        # pipe into a shell or interpreter that reads its program from stdin
        if "|" in main:
            for piece in re.split(r"(?<!\|)\|(?!\|)", main)[1:]:
                for sg in F.cmd_segments(piece)[:1]:
                    a, u, ww = F.norm_seg(sg)
                    ww, _x = self.strip_extra(list(ww))
                    if ww and self.reads_stdin_program(ww):
                        self.hit("H9", "output piped into %s" % os.path.basename(ww[0]))
        # sensitive tool left alone next to a substitution or brace expansion: the real argument is hidden
        if re.search(r"(?:^|[;&|(\n])[ \t]*(?:\$\(|`)", main):
            self.hit("H9", "the command word is a substitution")
        hidden = "$(" in main or "`" in main or "{" in main
        if hidden:
            for s in segs:
                if s.ww and os.path.basename(s.ww[0]) in HIDING_TOOLS and not [x for x in s.ww[1:] if not x.startswith("-")]:
                    self.hit("H9", "%s with a hidden argument ($(), backticks or braces)" % os.path.basename(s.ww[0]))

    @staticmethod
    def reads_stdin_program(ww):
        b = os.path.basename(ww[0])
        if b == "eval":
            return True
        if b in ("source", "."):
            return True
        shellish = b in F.SHELLS or b == "fish"
        interp = bool(R.INTERP_RE.match(b)) and b not in ("osascript",)
        if not (shellish or interp):
            return False
        i = 1
        while i < len(ww):
            x = ww[i]
            if re.match(r"^-\w*c$", x) and shellish:
                return False
            if interp and any(x == f for fl in R.INLINE_FLAGS.values() for f in fl) or (interp and re.match(r"^-[A-Za-z]*[ceEpr]$", x) and not b.startswith(("python3-")) and _family(b) in R.INLINE_FLAGS and x.lstrip("-") != "" and _inline_flag(b, x)):
                return False
            if x == "-m" and _family(b) == "python":
                return False
            if x in ("-o", "+o", "-O", "-W", "-X", "-r", "--require", "-I"):
                i += 2 if x not in ("-I",) else 1
                continue
            if x.startswith("-") and x not in ("-",):
                i += 1
                continue
            if x in ("-", "/dev/stdin") or x.startswith("/dev/fd/") or x.startswith("<"):
                return True
            return False
        return True

    # ------------------------------------------------------------------ one simple command
    def seg(self, s):
        a, u, ww = s.a, s.u, s.ww
        self.assign_rules(a, u, s)
        for lw in s.lead:
            if os.path.basename(lw) in R.LEAD_PERSIST:
                self.hit("H5", "%s" % os.path.basename(lw))
        if not ww:
            return
        c0 = ww[0]; b = os.path.basename(c0)
        full = " ".join(s.raw)
        if c0.startswith(("<", ">")) and len(c0) > 1:
            self.hit("H9", "the command word is a redirect: %s" % c0)
            return
        if "ENVSPLIT" in s.a or (any(os.path.basename(x) == "env" for x in s.lead) and any(x.startswith("-S") or x.startswith("--split-string") for x in s.lead)):
            self.hit("H9", "env -S splits a string into a command")
        if re.search(r"[$`*?\[\],{}]", c0) and not re.fullmatch(r"\[\[?", c0) and c0 not in ("]]", "]"):
            self.hit("H9", "command word is not literal: %s" % c0)
            return
        negated = set()
        if b == "find":                                  # `find . ! -name '.env*'` names the secrets to leave out
            for i, x in enumerate(ww[:-2]):
                if x in ("!", "-not") and ww[i + 1] in ("-name", "-iname"):
                    negated.add(i + 2)
        for wi, w in enumerate(ww):
            if wi == 0 or wi in negated:
                continue
            if self.sens_word(w) and b not in ("echo", "printf", "true", ":") and not w.startswith(("--exclude=", "--exclude-dir=", "--ignore=", "--ignore-dir=")):
                self.hit("H5", "%s %s" % (b, w))
                break
        self.redirects(ww)
        self.note_writes(b, ww)
        if admin_hit(a, u, ww):
            self.hit("H5", "shipm admin command: %s" % full)
        if F._fold(b) == "shipm" or (R.INTERP_RE.match(b) and "shipmiracle" in ww):
            self.shipmiracle_cmd(ww)
        if b in R.PERSIST_CMDS:
            self.hit("H5", full)
        if b == "open" and any(x in ("Terminal", "iTerm", "iTerm2") for x in ww[1:]) or (b == "open" and any(x.endswith((".command", ".sh", ".app", ".terminal", ".workflow", ".scpt")) for x in ww[1:])):
            self.hit("H5", "open starts another program: %s" % full)
        if b == "defaults" and "write" in ww[1:3]:
            self.hit("H5", full)
        if b in ("export", "declare", "typeset", "readonly", "local", "unset", "set", "setenv"):
            for w in ww[1:]:
                nm = w.split("=", 1)[0].lstrip("-")
                if b == "set" and not w.startswith("-") and "=" not in w:
                    continue
                if nm and (nm.startswith(R.ENV_CODE_PREFIX) or nm in R.ENV_CODE_VARS):
                    self.hit("H5", full)
                if nm in R.GIT_SCOPE_VARS:
                    self.hit("H6", full)
                if nm == "DOCKER_HOST":
                    self.hit("H4", full)
        for w in ww[1:]:
            if re.search(r"(?:^|/)Library/Launch(?:Agents|Daemons)", w):
                self.hit("H5", full)
        if b == "eval":
            self.hit("H9", "eval")
        elif b in ("source", "."):
            self.source(ww, s)
        if b == "cd" or b == "pushd":
            self.cd(ww)
        elif b == "popd":
            self.hit("H9", "popd: the new directory is unknown")
        if (b == "base64" and any(x in ("-d", "-D", "--decode", "-di") for x in ww[1:])) or (b == "xxd" and "-r" in ww[1:]) or b in ("uudecode", "b64decode") or \
                (b == "openssl" and any(x in ("-d", "-base64", "base64", "-a") for x in ww[1:]) and any(x in ("enc", "base64") for x in ww[1:])):
            self.hit("H9", "decoding of hidden text (%s)" % b)
        if b == "mkdir":
            for t in self.positionals(ww[1:]):
                ap = self.real(t)
                if ap is None:
                    self.hit("H9", "mkdir with an unknown path")
                elif not (self.is_tmp(ap) and not self.inside(ap)) and not (self.inside(ap) and (self.in_scope(self.rel(ap)) or self.in_scope(self.rel(ap) + "/x"))):
                    self.hit("H6", "mkdir outside the scope: %s" % t)
        self.delete_rules(b, ww, s)
        self.git_family(b, ww, s)
        self.net_rules(b, ww, s)
        self.prod_rules(b, ww, s)
        self.deps_rules(b, ww, s)
        self.exec_rules(b, ww, s)
        self.outside_rules(b, ww, s)
        self.new_rules(b, ww, s)

    # -------- assignments / environment
    def assign_rules(self, a, u, s):
        for nm in a:
            if nm.startswith(R.ENV_CODE_PREFIX) or nm in R.ENV_CODE_VARS:
                self.hit("H5", "assignment of %s" % nm)
            if nm in R.GIT_SCOPE_VARS:
                self.hit("H6", "assignment of %s" % nm)
            if nm == "DOCKER_HOST":
                self.hit("H4", "DOCKER_HOST assignment")
        if u:
            self.hit("H5", "env -u %s" % " ".join(u))

    def redirects(self, ww):
        """A redirect target that is a variable or substitution: unclear execution."""
        i = 0
        while i < len(ww):
            w = ww[i]
            m = re.match(r"^\d*(>>?|&>>?|>\||<<<|<)(.*)$", w)
            if m and w not in ("<", ">") or w in (">", ">>", "<", "<<<", "&>", ">|"):
                if m and m.group(1) == "<" and not m.group(2):
                    pass
                tgt = m.group(2) if m and m.group(2) else (ww[i + 1] if i + 1 < len(ww) else "")
                if m and m.group(1) in (">", ">>", "&>", "&>>", ">|") and tgt and not tgt.startswith("&") and ("$" in tgt or "`" in tgt):
                    ex = self.expand(tgt)
                    if ex is None:
                        self.hit("H9", "redirect to an unknown target: %s" % tgt)
                if w in (">", ">>", "&>", ">|") and i + 1 < len(ww) and ("$" in ww[i + 1] or "`" in ww[i + 1]) and self.expand(ww[i + 1]) is None:
                    self.hit("H9", "redirect to an unknown target: %s" % ww[i + 1])
            i += 1

    def note_writes(self, b, ww):
        """Files this same command writes before it may run them (a file made and run in one call is not 'changed since base' yet)."""
        r = ww[1:]
        tg = []
        for i, w in enumerate(ww):
            m = re.match(r"^\d*(?:>>?|&>>?|>\|)(.*)$", w)
            if m:
                tg.append(m.group(1) or (ww[i + 1] if i + 1 < len(ww) else ""))
        if b in ("tee", "touch", "install", "cp", "mv", "ln", "dd", "curl", "wget", "sed", "perl", "chmod", "git", "unzip", "tar", "cat", "printf", "echo"):
            tg += [x for x in r if not x.startswith("-")]
        for x in tg:
            ap = self.real(x[3:] if x.startswith("of=") else x)
            if ap:
                self.written.add(_fold(ap))

    def shipmiracle_cmd(self, ww):
        args = [x for x in ww[1:] if not x.startswith("-")]
        if args and args[0] == "shipmiracle":
            args = args[1:]
        if args[:1] == ["autopilot"]:
            self.hit("H5", "shipm autopilot (owner only)")
        if args[:2] == ["cr", "start"] and len(args) > 2:
            cr = args[2]
            if self.cr_ends and cr not in self.cr_ends:
                self.hit("H6", "shipm cr start %s is not in the charter ends" % cr)
        elif args[:1] == ["cr"] and len(args) > 1 and args[1] in ("abandon", "advance", "open"):
            pass

    # -------- cd
    def cd(self, ww):
        pos = [x for x in ww[1:] if not x.startswith("-") or x == "-"]
        if not pos:
            tgt = self.home
        elif pos[0] == "-":
            self.hit("H9", "cd -: the directory is unknown")
            return
        else:
            tgt = pos[0]
        ap = self.real(tgt)
        if ap is None:
            self.hit("H9", "cd %s: the directory is unknown" % tgt)
            return
        if not (self.inside(ap) or self.is_tmp(ap)):
            self.hit("H6", "cd outside the worktree: %s" % tgt)
        self.cwd = ap

    # -------- deletion (H1) and scope of removed files
    def cover(self, toks, kind, label, what):
        """Targets of rm / git rm / mv sources / find -delete. Counts tracked files; H1 for >3, a whole tracked dir, the root, docs/**."""
        total = 0
        for t in toks:
            if "$" in t or "`" in t or "\x03" in t:
                if self.expand(t) is None:
                    self.hit("H9", "%s with an unknown target: %s" % (label, t))
                    continue
            ex = self.expand(t) or t
            cands = [ex]
            if re.search(r"[*?\[]", ex):
                full = ex if os.path.isabs(ex) else os.path.join(self.cwd, ex)
                try:
                    cands = sorted(_glob.glob(full))[:2000] or [ex]
                except Exception:
                    cands = [ex]
            for c in cands:
                ap = os.path.realpath(c if os.path.isabs(c) else os.path.join(self.cwd, c))
                if self.is_tmp(ap) and not self.inside(ap):
                    continue
                if not self.inside(ap):
                    if _fold(self.root).startswith(_fold(ap).rstrip("/") + "/"):
                        self.hit("H1", "%s of a folder that holds the worktree: %s" % (label, t))
                    self.hit("H6", "%s outside the worktree: %s" % (label, t))
                    continue
                rel = self.rel(ap)
                fr = _fold(rel)
                if fr == ".":
                    self.hit("H1", "%s of the worktree root: %s" % (label, t))
                    continue
                if self.protected(ap, "remove"):
                    self.hit("H5", "%s of a protected path: %s" % (label, t))
                if fr == "docs" or fr.startswith("docs/"):
                    self.hit("H1", "%s under docs/: %s" % (label, t))
                files = self.tracked_under(rel)
                total += len(files)
                if files and not self.in_scope(rel) and not all(self.in_scope(f) for f in files):
                    self.hit("H6", "%s of tracked files outside the scope: %s" % (label, t))
        if total > 3:
            self.hit("H1", "%s covers %d tracked files (limit 3)" % (label, total))

    def delete_rules(self, b, ww, s):
        r = ww[1:]
        if b in ("rm", "unlink", "rmdir", "shred", "trash"):
            toks = self.positionals(r)
            if s.xargs or (not toks and ("$(" in " ".join(s.raw) or "`" in " ".join(s.raw))):
                self.hit("H9", "%s with targets that are not known" % b)
                return
            if not toks and b == "rm" and not any(x in ("--help", "--version") for x in r):
                self.hit("H9", "rm without targets (xargs, substitution or nothing)")
                return
            self.cover(toks, "remove", b, ww)
        elif b == "mv":
            td = F.opt_dir(r)
            toks = self.positionals(r)
            src = toks if td is not None else toks[:-1]
            self.cover(src, "remove", "mv source", ww)
        elif b == "find":
            self.find(ww, s)
        elif b == "rsync":
            if any(x == "--delete" or x.startswith("--delete-") or x == "--remove-source-files" for x in r):
                toks = self.positionals(r)
                self.cover(toks[-1:] if toks else [], "remove", "rsync --delete", ww)
        elif b in R.SQL_CLIENTS:
            txt = " ".join(r)
            if R.SQL_BAD.search(txt):
                self.hit("H1", "%s with DROP/TRUNCATE" % b)
            if b == "sqlite3" and any(R.SQLITE_DOT.search(w) or w.lstrip().startswith(".") and re.match(r"\.(?:shell|system|read|load|output|once|excel|log|backup|save)\b", w.lstrip(), re.I) for w in r):
                self.hit("H5", "sqlite3 dot-command that runs a program or reads/writes a file")
            for w in r:
                if w.endswith(".sql"):
                    p = self.real(w)
                    if p and self.inside(p):
                        t = self.read_rel(self.rel(p))
                        if t and R.SQL_BAD.search(t):
                            self.hit("H1", "%s runs a .sql file with DROP/TRUNCATE: %s" % (b, w))
        elif b in ("dropdb", "dropuser", "dropdb_all", "mongodump_drop"):
            self.hit("H1", full_of(s))
        if b == "mongorestore" and "--drop" in r:
            self.hit("H1", "mongorestore --drop")
        # database reset families anywhere in the words
        words = ww
        for i, w in enumerate(words):
            if re.fullmatch(r"db:(?:drop|reset|migrate:reset|schema:load)(?::.*)?", w) or w in ("schema:drop", "migrate:fresh", "--force-reset", "flushdb", "flushall"):
                self.hit("H1", "database reset: %s" % w)
            if w == "reset" and i >= 2 and words[i - 2:i] == ["migrate", words[i - 1]] and words[i - 1] == "migrate":
                pass
            if w == "reset" and i >= 1 and words[i - 1] == "migrate" and any(os.path.basename(x) in ("prisma", "prisma.js") for x in words[:i]):
                self.hit("H1", "prisma migrate reset")
            if w == "reset" and i >= 1 and words[i - 1] == "db" and any(os.path.basename(x) == "supabase" for x in words[:i]):
                self.hit("H1", "supabase db reset")
            if w == "flush" and i >= 1 and any(os.path.basename(x) in ("manage.py", "django-admin") for x in words[:i]):
                self.hit("H1", "manage.py flush")

    @staticmethod
    def positionals(r):
        if "--" in r:
            k = r.index("--")
            return [x for x in r[:k] if not x.startswith("-")] + r[k + 1:]
        return [x for x in r if not x.startswith("-")]

    def find(self, ww, s):
        r = ww[1:]
        starts = []
        for x in r:
            if x.startswith("-") or x in ("(", "!"):
                break
            starts.append(x)
        starts = starts or ["."]
        has_exec = any(x in r for x in ("-exec", "-execdir", "-ok", "-okdir"))
        if has_exec:
            k = next(i for i, x in enumerate(r) if x in ("-exec", "-execdir", "-ok", "-okdir"))
            sub = []
            for x in r[k + 1:]:
                if x in (";", "+"):
                    break
                sub.append(x)
            sub, _ = self.strip_extra(sub)
            if sub:
                nb = os.path.basename(sub[0])
                if nb in ("rm", "unlink", "rmdir", "mv", "shred"):
                    self.find_cover(starts, r, "find -exec " + nb)
                else:
                    import shlex
                    segs2 = []
                    self.collect(shlex.join(sub), s.depth, segs2)
                    for g2 in segs2:
                        g2.xargs = True
                        self.seg(g2)
        if "-delete" in r:
            self.find_cover(starts, r, "find -delete")

    def find_cover(self, starts, r, label):
        names = [r[i + 1] for i, x in enumerate(r) if x in ("-name", "-path", "-wholename") and i + 1 < len(r)]
        inames = [r[i + 1] for i, x in enumerate(r) if x in ("-iname", "-ipath") and i + 1 < len(r)]
        unknown = any(x in r for x in ("-regex", "-iregex", "-newer", "-mtime", "-mmin", "-size", "-perm", "-user", "-empty", "-not", "!", "-o", "-or"))
        total = 0
        for t in starts:
            if "$" in t or "`" in t:
                if self.expand(t) is None:
                    self.hit("H9", "%s with an unknown start: %s" % (label, t))
                    continue
            ap = self.real(t)
            if ap is None:
                continue
            if self.is_tmp(ap) and not self.inside(ap):
                continue
            if not self.inside(ap):
                self.hit("H6", "%s outside the worktree: %s" % (label, t))
                continue
            rel = self.rel(ap)
            fr = _fold(rel)
            if fr == "docs" or fr.startswith("docs/"):
                self.hit("H1", "%s under docs/: %s" % (label, t))
            if self.protected(ap, "remove") and (names or inames):
                pass
            files = self.tracked_under(rel)
            if (names or inames) and not unknown:
                sel = []
                for f in files:
                    base = f.rsplit("/", 1)[-1]
                    if all((fnmatch.fnmatchcase(base, n) if "/" not in n else fnmatch.fnmatchcase(f, n.lstrip("./") if not n.startswith("*") else n)) for n in names) and \
                       all(fnmatch.fnmatchcase(base.lower(), n.lower()) for n in inames):
                        sel.append(f)
                total += len(sel)
            else:
                total += len(files)
        if total > 3:
            self.hit("H1", "%s would delete %d tracked files (limit 3)" % (label, total))

    # -------- git
    def git_family(self, b, ww, s):
        if b in ("git-filter-repo", "git-filter-branch"):
            self.hit("H1", b)
            return
        if b == "git":
            self.git(ww, s)
        elif b == "gh":
            self.gh(ww)

    def git(self, ww, s):
        r = ww[1:]
        i = 0; gl_c = []; dirs = []
        while i < len(r):
            x = r[i]
            if x in ("-C", "--git-dir", "--work-tree", "-c", "--namespace", "--exec-path", "--config-env", "--super-prefix", "--attr-source") and i + 1 < len(r):
                if x == "-c":
                    gl_c.append(r[i + 1])
                elif x in ("-C", "--git-dir", "--work-tree"):
                    dirs.append(r[i + 1])
                i += 2
            elif x.startswith(("--git-dir=", "--work-tree=")):
                dirs.append(x.split("=", 1)[1]); i += 1
            elif x.startswith("-"):
                i += 1
            else:
                break
        for kv in gl_c:
            if R.SENSITIVE_CONFIG_KEYS.match(kv.split("=", 1)[0]):
                self.hit("H5", "git -c %s" % kv.split("=", 1)[0])
        base = self.cwd
        for d in dirs:
            ap = self.real(d)
            if ap is None:
                self.hit("H9", "git -C %s: the directory is unknown" % d)
                continue
            if not (self.inside(ap) or self.is_tmp(ap)):
                self.hit("H6", "git -C/--git-dir/--work-tree outside the worktree: %s" % d)
        if i >= len(r):
            return
        sub = r[i]; rest = r[i + 1:]
        if "$" in sub or "`" in sub:
            self.hit("H9", "git subcommand is not literal: %s" % sub)
            return
        rf = [x for x in rest if x.startswith("-")]
        rp = [x for x in self.positionals(rest)]
        after_dd = rest[rest.index("--") + 1:] if "--" in rest else []
        refs_before = [x for x in (rest[:rest.index("--")] if "--" in rest else rest) if not x.startswith("-")]

        def flag(*names):
            return any(f in names or f.split("=")[0] in names for f in rf)

        def cluster(ch):
            return any(re.fullmatch(r"-[A-Za-z]*" + ch + r"[A-Za-z]*", f) for f in rf)
        if sub in R.HOOK_RUNNING_SUBS:
            self.hook_guard(sub)
        if "--no-verify" in rf or (sub == "commit" and cluster("n")) or flag("--no-gpg-sign") and False:
            self.hit("H2", "git %s --no-verify" % sub)
        if sub == "push":
            force = flag("--force", "-f", "--force-with-lease", "--force-if-includes", "--delete", "-d", "--mirror", "--prune") or cluster("f") or cluster("d") \
                or any(x.startswith(("+", ":")) for x in rp) or any(f.startswith(("--force-with-lease", "--delete")) for f in rf)
            self.hit("H1" if force else "H2", "git push" + (" (force/delete)" if force else ""))
            if any(x == "." for x in rp[:1]) or (len(rp) > 1 and rp[0] == "."):
                self.hit("H6", "git push . touches another branch")
        elif sub in ("filter-branch", "filter-repo"):
            self.hit("H1", "git " + sub)
        elif sub == "branch":
            if flag("-d", "-D", "--delete", "-f", "--force") or cluster("d") or cluster("D") or cluster("f"):
                self.hit("H1", "git branch delete/force")
            elif flag("-m", "-M", "-c", "-C", "--move", "--copy", "-u", "--set-upstream-to", "--unset-upstream") or cluster("m") or cluster("M") or \
                    (rp and not flag("-l", "--list", "--contains", "--merged", "--no-merged", "--points-at", "-a", "-r", "-v", "-vv", "--show-current")):
                self.hit("H6", "git branch changes another branch")
        elif sub == "update-ref":
            if flag("-d", "--delete"):
                self.hit("H1", "git update-ref -d")
            elif not (rp and (rp[0] == "HEAD" or rp[0] in ("refs/heads/" + self.ctx.auto_branch,) and self.ctx.auto_branch)):
                self.hit("H6", "git update-ref touches another ref")
        elif sub == "symbolic-ref":
            if len(rp) >= 2 or flag("-d", "--delete"):
                self.hit("H6", "git symbolic-ref changes what a ref points to")
        elif sub == "reflog":
            if rp[:1] in (["expire"], ["delete"]):
                self.hit("H1", "git reflog " + rp[0])
        elif sub == "gc":
            if any(f.startswith("--prune") for f in rf):
                self.hit("H1", "git gc --prune")
        elif sub == "prune":
            self.hit("H1", "git prune")
        elif sub == "stash":
            if rp[:1] in (["drop"], ["clear"]):
                self.hit("H1", "git stash " + rp[0])
        elif sub == "clean":
            if not (flag("-n", "--dry-run") or cluster("n")):
                self.hit("H1", "git clean")
        elif sub == "worktree":
            if rp[:1] in (["remove"], ["prune"]):
                self.hit("H1", "git worktree " + rp[0])
            elif rp[:1] in (["add"], ["move"], ["repair"]):
                self.hit("H6", "git worktree " + rp[0])
        elif sub == "tag":
            if flag("-d", "--delete", "-f", "--force") or cluster("d") or cluster("f"):
                self.hit("H1", "git tag delete/force")
            elif not flag("-l", "--list", "-n", "--contains", "--no-contains", "--points-at", "--merged", "--no-merged", "-v", "--verify", "--sort", "--format") and not cluster("l"):
                for nm in rp:                                 # a tag named like a branch wins over the branch in `git merge <name>` (ref hijack)
                    if nm in ("main", "master", "HEAD", "FETCH_HEAD", "ORIG_HEAD", "MERGE_HEAD", "@") or nm.startswith(("auto/", "refs/", "heads/")) or "$" in nm:
                        self.hit("H6", "git tag %s names a branch or another ref" % nm)
                        break
        elif sub == "reset":
            cand = [x for x in refs_before if not os.path.exists(os.path.join(self.cwd, x))]
            for ref in cand:
                if not self.ref_ok(ref):
                    self.hit("H1", "git reset to %s" % ref)
        elif sub == "rebase":
            if not any(f in ("--abort", "--continue", "--skip", "--quit", "--edit-todo", "--show-current-patch") for f in rf):
                for ref in refs_before:
                    if not self.ref_ok(ref):
                        self.hit("H1", "git rebase onto %s" % ref)
                for k, x in enumerate(rest):
                    if x == "--onto" and k + 1 < len(rest) and not self.ref_ok(rest[k + 1]):
                        self.hit("H1", "git rebase --onto %s" % rest[k + 1])
        elif sub == "commit":
            if flag("--amend") and not (self.ctx.ahead is not None and self.ctx.ahead >= 1):
                self.hit("H1", "git commit --amend (no commit of this CR to amend)")
        elif sub in ("checkout", "switch"):
            if sub == "checkout":
                self.git_restore(sub, rest, rf, refs_before, after_dd)
            self.checkout(sub, rest, rf, rp, refs_before)
        elif sub == "restore":
            self.git_restore(sub, rest, rf, refs_before, after_dd)
        elif sub in ("read-tree", "update-index"):
            self.git_index_rules(sub, rest, rf, rp)
        elif sub == "rm":
            self.cover(after_dd or [x for x in rp], "remove", "git rm", ww)
        elif sub == "mv":
            for t in rp:
                ap = self.real(t)
                if ap is None:
                    self.hit("H9", "git mv with an unknown path")
                elif not self.scope_ok(ap):
                    self.hit("H6", "git mv outside the scope: %s" % t)
        elif sub in ("apply", "am"):
            self.git_apply_paths(rest)
            if not flag("--check", "--stat", "--numstat", "--summary", "--dry-run"):
                self.hit("H9", "git %s: the files it changes are not known" % sub)
        elif sub == "config":
            readonly = flag("--get", "--get-all", "--get-regexp", "--list", "-l", "--get-urlmatch", "--show-origin", "--show-scope", "--default", "--name-only") and not flag("--add", "--unset", "--replace-all")
            writes = flag("--add", "--unset", "--unset-all", "--replace-all", "--edit", "-e", "--rename-section", "--remove-section", "--global", "--system", "--file", "-f", "--worktree") \
                or len(rp) >= 2
            if not readonly and writes:
                self.hit("H5", "git config write")
            elif not readonly and rp and rp[0].lower().startswith("alias."):
                self.hit("H5", "git config alias")
        elif sub == "remote":
            if rp[:1] and rp[0] in ("add", "remove", "rm", "rename", "set-url", "set-head", "set-branches", "prune", "update"):
                self.hit("H5", "git remote " + rp[0])
        elif sub in ("credential", "credential-store", "credential-osxkeychain"):
            self.hit("H5", "git " + sub)
        elif sub in ("clone", "fetch", "pull", "ls-remote", "submodule", "daemon", "send-email", "svn", "instaweb"):
            self.git_network(sub, rp, rf)
        elif sub in ("hook",):
            pass

    def hook_guard(self, sub):
        """C1: a git command that runs hooks, while a hooks folder (.githooks, .husky, the configured core.hooksPath folder) is changed against the CR base or
        untracked, is H5 (the hook would run owner-level code written by the model)."""
        dirs = [d for d in R.HOOK_DIRS] + [_fold(d) for d in (self.ctx.hooks_rel or []) if d]
        for c in self.changed:
            if any(c == d or c.startswith(d + "/") for d in dirs):
                self.hit("H5", "git %s would run hooks, and %s is changed or untracked" % (sub, c))
                return

    def git_network(self, sub, rp, rf):
        if sub in ("send-email", "svn"):
            self.hit("H2", "git " + sub)
            return
        if sub == "daemon":
            self.hit("H3", "git daemon")
            return
        if sub == "submodule":
            if rp[:1] == ["add"]:
                self.hit("H3", "git submodule add")
            return
        if sub in ("fetch", "pull"):                          # H1: a refspec with a destination (or +) writes any local ref, `.` fetches from this very repository
            if any(f in ("--update-head-ok", "-u") or f.startswith("--update-head-ok") for f in rf):
                self.hit("H6", "git %s --update-head-ok" % sub)
            if rp[:1] == ["."]:
                self.hit("H6", "git %s from the local repository (.)" % sub)
            for x in rp[1:]:
                if ":" in x or x.startswith("+"):
                    self.hit("H6", "git %s with a refspec that writes a local ref: %s" % (sub, x))
                    break
        for x in rp:
            if URL_LIKE.match(x) or re.match(r"^[\w.-]+@[\w.-]+:", x):
                if not LOCAL_URL.match(x):
                    self.hit("H3", "git %s from a non-local host: %s" % (sub, x))

    def checkout(self, sub, rest, rf, rp, refs_before):
        if "-" in rest:
            self.hit("H6", "git %s - leaves the auto branch" % sub)
            return
        if "--" in rest and sub == "checkout":
            return                                        # file restore (possibly from a ref)
        if any(f in ("-b", "-B", "-c", "-C", "--orphan", "--detach", "-d") or f.startswith(("--orphan", "-b", "-B")) for f in rf):
            self.hit("H6", "git %s creates or moves to another branch" % sub)
            return
        if not rp:
            return
        t = rp[0]
        if t == "-" or "$" in t:
            self.hit("H6", "git %s to an unknown branch" % sub)
            return
        if sub == "checkout" and (t == "." or os.path.exists(os.path.join(self.cwd, t))):
            return                                        # restoring files
        if t in ("HEAD", self.ctx.auto_branch) and t:
            return
        self.hit("H6", "git %s %s leaves the auto branch" % (sub, t))

    def gh(self, ww):
        r = ww[1:]
        pos = []; i = 0
        while i < len(r):
            x = r[i]
            if x in ("-R", "--repo", "--hostname") and i + 1 < len(r):
                if x == "--hostname" and r[i + 1] not in ("github.com",):
                    self.hit("H3", "gh --hostname %s" % r[i + 1])
                i += 2; continue
            if not x.startswith("-"):
                pos.append(x)
            i += 1
        flags = [x for x in r if x.startswith("-")]
        if not pos:
            return
        grp = pos[0]; verb = pos[1] if len(pos) > 1 else ""
        if "$" in grp or "$" in verb:
            self.hit("H9", "gh with a non-literal subcommand")
            return
        if grp == "api":
            meth = ""
            for k, x in enumerate(r):
                if x in ("-X", "--method") and k + 1 < len(r):
                    meth = r[k + 1].upper()
                elif x.startswith("--method="):
                    meth = x.split("=", 1)[1].upper()
                elif re.match(r"^-X.+", x):
                    meth = x[2:].upper()
            if meth == "DELETE":
                self.hit("H1", "gh api -X DELETE")
            elif (meth and meth != "GET") or any(x in ("-f", "-F", "--field", "--raw-field", "--input") or x.startswith(("--field=", "--raw-field=", "--input=")) for x in flags):
                self.hit("H2", "gh api write")
            return
        if (grp, verb) in R.GH_DELETE:
            self.hit("H1", "gh %s %s" % (grp, verb))
            return
        if grp in ("auth", "config", "secret", "ssh-key", "gpg-key", "alias", "extension", "codespace", "attestation"):
            if (grp == "auth" and verb == "status") or (grp == "config" and verb in ("get", "list")) or (grp == "extension" and verb in ("list", "search", "browse")):
                return
            self.hit("H5", "gh %s %s" % (grp, verb))
            return
        if grp == "pr" and verb == "merge":
            self.hit("H6", "gh pr merge")
            return
        if grp == "pr" and verb == "checkout":
            self.hit("H6", "gh pr checkout")
            return
        if grp == "repo" and verb in ("clone", "fork", "sync"):
            self.hit("H3", "gh repo %s" % verb)
            return
        if grp in ("--version", "version", "help", "status", "search", "completion", "browse"):
            return
        if verb in R.GH_READ_VERBS:
            return
        self.hit("H2", "gh %s %s" % (grp, verb))

    # -------- network, paid, publish
    def net_rules(self, b, ww, s):
        r = ww[1:]
        full = " ".join(ww)
        if b in R.NET_RAW or (b in ("python", "python3") and False):
            if any(x in ("--version", "-V", "--help", "-h") for x in r) and len(r) == 1:
                return
            toks = []; k = 0
            tool_vopts = R.NET_TOOL_VALUE.get(b, ())
            while k < len(r):
                x = r[k]
                if (x in R.NET_VALUE_OPTS or x in tool_vopts) and k + 1 < len(r):
                    k += 2; continue
                if x == "--url" and k + 1 < len(r):
                    toks.append(r[k + 1]); k += 2; continue
                if x.startswith("--url="):
                    toks.append(x[6:])
                elif not x.startswith(("-", "+")):
                    toks.append(x)
                k += 1
            if b in ("nc", "ncat", "netcat") and any(re.fullmatch(r"-[A-Za-z]*l[A-Za-z]*", f) or f == "--listen" for f in r):
                bind = [t for t in toks if not t.isdigit()]
                if bind and all(_LISTEN_LOCAL.match(t) for t in bind):
                    return
                self.hit("H3", "%s listens on %s" % (b, "a non-local address" if bind else "all interfaces (no local bind address)"))
                return
            if b in ("http", "https", "xh", "httpie"):
                toks = [x for x in toks if x.upper() not in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS") and "=" not in x.replace("==", "=", 1)[:0] and not re.match(r"^[\w.-]+(?:==?|:=|:)[^/]", x) or LOCAL_URL.match(x)]
            if not toks:
                self.hit("H3", "%s with no local host" % b)
            for t in toks:
                if "$" in t or "`" in t:
                    self.hit("H3", "%s to an unknown host: %s" % (b, t))
                elif not LOCAL_URL.match(t):
                    self.hit("H3", "%s to a non-local host: %s" % (b, t))
            return
        if b == "openssl":
            pos0 = self.positionals(r)[:1]
            if pos0 and pos0[0] in ("s_client", "s_time", "ocsp"):
                hosts = [r[i + 1] for i, x in enumerate(r) if x in ("-connect", "-host", "-proxy", "-url") and i + 1 < len(r)] + [x for x in r[r.index(pos0[0]) + 1:] if not x.startswith("-") and (":" in x or "." in x)][:1]
                for h in hosts or []:
                    if not LOCAL_URL.match(h):
                        self.hit("H3", "openssl %s to a non-local host: %s" % (pos0[0], h))
                        break
            elif pos0 and pos0[0] == "s_server":
                acc = _opt_value(r, ("-accept",))
                if not (acc and _LISTEN_LOCAL.match(acc)):
                    self.hit("H3", "openssl s_server listens on all interfaces")
        if b in ("open",) and any(URL_LIKE.match(x) and not LOCAL_URL.match(x) for x in r):
            self.hit("H3", "open of a remote URL")
        if b in R.CLOUD_CLIS:
            self.hit("H3", "%s CLI" % b)
        if b == "supabase":
            subs = [x for x in r if not x.startswith("-")]
            if not subs or subs[0] not in ("start", "stop", "status", "init", "gen", "test", "help", "--version", "migration") or (subs[:2] == ["db", "reset"]):
                if subs[:2] != ["db", "reset"]:
                    self.hit("H3", "supabase (non-local)")
        if re.match(r"^python[0-9.]*$", b) and "-m" in r:
            k = r.index("-m")
            if k + 1 < len(r) and r[k + 1] in ("http.client", "urllib.request", "ftplib", "smtplib", "telnetlib", "poplib", "imaplib", "xmlrpc.client", "httplib2", "requests", "aiohttp", "httpx"):
                tg = [x for x in r[k + 2:] if not x.startswith("-")]
                if not tg or any(not LOCAL_URL.match(x) for x in tg):
                    self.hit("H3", "python -m %s to a non-local host" % r[k + 1])
        # publish
        if b in R.JS_PM:
            pos = self.positionals(r)
            if pos[:1] and pos[0] in R.JS_PUBLISH_SUB:
                self.hit("H2", "%s %s" % (b, pos[0]))
            if pos[:1] and pos[0] in ("login", "adduser", "logout", "token", "whoami") and b != "bun":
                if pos[0] != "whoami":
                    self.hit("H5", "%s %s" % (b, pos[0]))
            if b in ("npm", "pnpm") and pos[:2] and pos[0] == "config" and pos[1] in ("set", "delete", "edit"):
                self.hit("H5", "%s config %s" % (b, pos[1]))
            if b == "yarn" and pos[:1] in (["npm"],) and pos[1:2] in (["publish"],):
                self.hit("H2", "yarn npm publish")
            if "--publish" in r:
                self.hit("H2", "%s --publish" % b)
        if b in R.PUBLISH_SIMPLE:
            subs = R.PUBLISH_SIMPLE[b]
            pos = self.positionals(r)
            if subs is None:
                if not (b == "vercel" and r[:1] and r[0] in ("--version", "-v", "dev", "-h", "--help", "whoami", "ls", "list", "inspect", "logs")):
                    self.hit("H2", b)
            elif pos and pos[0] in subs:
                self.hit("H2", "%s %s" % (b, pos[0]))
            elif b == "dotnet" and any(x in ("nuget",) for x in pos[:1]) and "push" in pos:
                self.hit("H2", "dotnet nuget push")
            elif b == "fastlane" and pos and any(x in subs for x in pos):
                self.hit("H2", "fastlane " + pos[0])
            elif b in ("wrangler", "netlify", "fly", "flyctl", "firebase", "eas", "expo", "appcenter") and not (pos and pos[0] in ("dev", "types", "emulators:start", "--version", "version", "whoami", "login_local")):
                self.hit("H3", "%s (non-local)" % b)
        if b == "twine" and "upload" in r:
            self.hit("H2", "twine upload")
        if re.match(r"^python[0-9.]*$", b) and "-m" in r:
            k = r.index("-m")
            if k + 1 < len(r) and r[k + 1] == "twine" and "upload" in r:
                self.hit("H2", "python -m twine upload")
            if k + 1 < len(r) and r[k + 1] == "build" and False:
                pass
        if b == "docker" or b == "podman" or b == "nerdctl" or b == "buildah":
            pos = self.positionals(r)
            if pos[:1] in (["push"], ["manifest"]) and (pos[0] == "push" or pos[1:2] == ["push"]):
                self.hit("H2", "docker push")
            if any(x == "--push" or x.startswith("--push=") for x in r) or any(re.search(r"type=registry|push=true", x) for x in r):
                self.hit("H2", "docker --push")
            if pos[:1] in (["login"], ["logout"]):
                self.hit("H5", "docker login")
            if pos[:2] == ["compose", "push"] or pos[:2] == ["buildx", "imagetools"]:
                self.hit("H2", "docker compose push")
        if b == "xcrun" or b == "altool":
            if any(x == "altool" for x in ww) and any(x.startswith("--upload") or x == "--validate-app" for x in r):
                self.hit("H2", "altool --upload")
            if "notarytool" in r and "submit" in r:
                self.hit("H2", "notarytool submit")
        if b == "altool" and any(x.startswith("--upload") for x in r):
            self.hit("H2", "altool --upload")
        if b == "pod" and r[:2] == ["trunk", "push"]:
            self.hit("H2", "pod trunk push")
        if b == "gh-pages":
            self.hit("H2", "gh-pages")
        if b in ("awk", "gawk", "mawk", "nawk"):
            prog = " ".join(r)
            for name, rule in R.scan_literals(prog):
                self.hit(rule, "awk program contains %s" % name)
            if re.search(r"\bsystem\s*\(|\|\s*getline|\|&|print\s*[^;]*\|\s*\"", prog):
                self.hit("H9", "awk program runs commands")
            self.inline_fs("awk", prog)

    def prod_rules(self, b, ww, s):
        r = ww[1:]
        pos = self.positionals(r)
        if b in R.TF_TOOLS:
            if b in ("terraform", "tofu", "terragrunt"):
                if pos[:1] and pos[0] in ("fmt", "validate", "plan", "init", "version", "show", "output", "providers", "graph", "console_local"):
                    if pos[0] in ("plan", "show", "output", "init"):
                        self.hit("H4", "%s %s reaches the remote state" % (b, pos[0])) if False else None
                    return
                self.hit("H4", "%s %s" % (b, pos[0] if pos else ""))
            elif b == "pulumi":
                if pos[:1] and pos[0] in ("version", "about", "plugin", "login_local"):
                    return
                self.hit("H4", "pulumi %s" % (pos[0] if pos else ""))
            elif b in ("kustomize",):
                if not (pos[:1] == ["build"] or pos[:1] == ["version"]):
                    self.hit("H4", "kustomize %s" % (pos[0] if pos else ""))
            else:
                self.hit("H4", b)
        elif b == "helm":
            if pos[:1] and pos[0] in ("template", "lint", "version", "create", "package", "show", "dependency", "dep", "env", "help", "completion", "search"):
                pass
            else:
                self.hit("H4", "helm %s" % (pos[0] if pos else ""))
        elif b in R.REMOTE_SHELLS:
            self.hit("H4", b)
        elif b == "rsync":
            for x in pos:
                if re.match(r"^(?:[\w.-]+@)?[\w.-]+:(?!//)", x) and not x.startswith(("./", "/")) and not re.match(r"^[A-Za-z]:[\\/]", x):
                    self.hit("H4", "rsync to/from a remote host: %s" % x)
                if x.startswith("rsync://"):
                    self.hit("H4", "rsync daemon")
            if any(x in ("-e", "--rsh") or x.startswith("--rsh=") for x in r) and not pos == []:
                if any(x in ("-e", "--rsh") for x in r) or any(x.startswith("--rsh=") for x in r):
                    pass
        elif b == "scp":
            self.hit("H4", "scp")
        if b in ("docker", "podman", "nerdctl"):
            for k, x in enumerate(r):
                if x in ("-H", "--host", "--context", "-c") and (x != "-c" or True) and x != "-c":
                    self.hit("H4", "docker %s" % x)
                    break
                if x.startswith(("--host=", "--context=", "-H")) and x != "-H" or (x.startswith("-H") and len(x) > 2):
                    self.hit("H4", "docker %s" % x.split("=")[0])
                    break
                if not x.startswith("-"):
                    break
            if "--privileged" in r or any(x in ("--pid=host", "--userns=host", "--cap-add=ALL", "--cap-add=SYS_ADMIN") for x in r):
                self.hit("H5", "docker with host privileges")
            for k2, x2 in enumerate(r):
                v2 = r[k2 + 1] if x2 in ("-v", "--volume") and k2 + 1 < len(r) else (x2.split("=", 1)[1] if x2.startswith("--volume=") else (x2[2:] if x2.startswith("-v") and len(x2) > 2 else None))
                if v2 and v2.startswith(("/", "~")):
                    ap2 = self.real(v2.split(":", 1)[0])
                    if ap2 is not None and not self.inside(ap2) and not self.is_tmp(ap2):
                        self.hit("H6", "docker mounts a folder outside the worktree: %s" % v2.split(":", 1)[0])
            if pos[:2] in (["context", "use"], ["context", "create"], ["machine", "ssh"]) or pos[:1] == ["swarm"]:
                self.hit("H4", "docker context/swarm")
            if any(re.match(r"^DOCKER_HOST=", x) for x in ww):
                self.hit("H4", "DOCKER_HOST")

    # -------- dependencies (H3)
    def deps_rules(self, b, ww, s):
        r = ww[1:]
        pos = self.positionals(r)
        kind = None; names = []; filemode = False
        if b in ("npm", "pnpm", "yarn", "bun") or b == "npx" or b == "bunx":
            if b in ("npx", "bunx"):
                self.runner_rules(b, "npm", r)
                return
            if b == "bun" and pos[:1] == ["x"]:
                self.runner_rules("bun x", "npm", r[r.index("x") + 1:])
                return
            sub = pos[0] if pos else None
            if b == "yarn" and not pos and not any(x.startswith("-") and x not in ("--frozen-lockfile", "--immutable", "--silent", "--non-interactive", "--offline") for x in r):
                sub = "install"
            if b in ("pnpm", "yarn") and sub == "dlx":
                self.hit("H3", "%s dlx downloads and runs a package" % b)
                return
            if sub in ("exec", "x") and b == "npm":
                self.runner_rules("npm exec", "npm", r[r.index(sub) + 1:])
                return
            if sub not in R.JS_INSTALL_SUB:
                return
            kind = "npm"; names = pos[1:]
            if sub in ("ci", "ic", "install-test", "it", "rebuild", "link", "dedupe"):
                names = []
            if sub in ("ci", "ic"):
                filemode = True
            if sub in ("remove", "uninstall", "rm", "un"):
                self.hit("H3", "%s %s changes the dependencies" % (b, sub)) if self.ctx.deps_mode == "none" else None
                if self.ctx.deps_mode != "none":
                    pass
                return
            if sub in ("update", "up", "upgrade") and not names:
                names = ["*all*"]
            if b == "yarn" and sub == "add" or sub in ("add",):
                if not names:
                    return
        elif b in ("pip", "pip3") or re.match(r"^pip3?\.\d+$", b) or (re.match(r"^python[0-9.]*$", b) and "-m" in r and r[r.index("-m") + 1:r.index("-m") + 2] == ["pip"]) or (b == "uv" and pos[:2] == ["pip", "install"]):
            rr = r
            if re.match(r"^python[0-9.]*$", b):
                rr = r[r.index("-m") + 2:]
            elif b == "uv":
                rr = r[r.index("pip") + 1:]
            pp = self.positionals(rr)
            if not pp or pp[0] not in ("install", "uninstall", "download", "wheel"):
                return
            if pp[0] == "uninstall":
                return
            kind = "pip"
            names = []; k = 1; filemode = False
            args = rr[rr.index(pp[0]) + 1:]
            j = 0
            while j < len(args):
                x = args[j]
                if x in ("-r", "--requirement", "-c", "--constraint") and j + 1 < len(args):
                    filemode = True; j += 2; continue
                if x in ("-e", "--editable") and j + 1 < len(args):
                    if args[j + 1] in (".", "./") or args[j + 1].startswith(("./", ".[")) or args[j + 1].startswith("."):
                        filemode = True
                    else:
                        names.append(args[j + 1])
                    j += 2; continue
                if x in ("-i", "--index-url", "--extra-index-url", "-f", "--find-links", "-t", "--target", "--prefix", "--root", "--python", "--platform", "--only-binary", "--no-binary", "--constraint") and j + 1 < len(args):
                    j += 2; continue
                if x.startswith("-"):
                    j += 1; continue
                if x in (".", "./") or x.startswith(".["):
                    filemode = True
                else:
                    names.append(x)
                j += 1
        elif b == "uv" and pos[:1] in (["add"], ["remove"], ["tool"], ["run"]) and pos[:2] != ["tool", "run"]:
            if pos[0] == "run" and not any(x.startswith("--with") for x in r):
                return
            self.hit("H3", "uv %s changes or fetches dependencies" % pos[0])
            return
        elif b == "uv" and pos[:1] in (["sync"], ["lock"]):
            kind = "file"; filemode = True
        elif b == "pipx" and pos[:1] == ["run"]:
            self.runner_rules("pipx run", "pip", r[r.index("run") + 1:])
            return
        elif b == "uvx" or (b == "uv" and pos[:2] == ["tool", "run"]):
            self.runner_rules(b, "pip", r if b == "uvx" else r[r.index("run") + 1:])
            return
        elif b == "pipx" and pos[:1] and pos[0] in ("install", "upgrade", "inject", "install-all"):
            self.hit("H3", "pipx %s" % pos[0])
            return
        elif b == "brew" and pos[:1] and pos[0] in ("install", "reinstall", "upgrade", "tap", "link", "bundle", "cask", "update", "uninstall"):
            self.hit("H3", "brew %s" % pos[0])
            return
        elif b == "go" and pos[:1] in (["get"], ["install"], ["mod"]) and not (pos[:2] == ["mod", "tidy"] and False):
            if pos[:1] == ["mod"] and pos[1:2] not in (["download"], ["tidy"], ["vendor"], ["edit"], ["init"]):
                return
            if pos[:1] == ["install"] and not any("@" in x for x in pos[1:]):
                return
            kind = "other"
        elif b == "cargo" and pos[:1] and pos[0] in ("add", "install", "update", "remove", "rm"):
            kind = "other"
        elif b == "gem" and pos[:1] and pos[0] in ("install", "update", "uninstall"):
            kind = "other"
        elif b == "bundle" and pos[:1] and pos[0] in ("add", "install", "update", "remove"):
            if pos[0] == "install":
                kind = "file"; filemode = True
            else:
                kind = "other"
        elif b == "composer" and pos[:1] and pos[0] in ("require", "install", "update", "remove"):
            if pos[0] == "install":
                kind = "file"; filemode = True
            else:
                kind = "other"
        elif b == "pod" and pos[:1] and pos[0] in ("install", "update", "repo"):
            kind = "file"; filemode = True
        elif b == "swift" and pos[:2] and pos[0] == "package" and pos[1] in ("update", "resolve", "add", "add-dependency"):
            kind = "file"; filemode = pos[1] == "resolve"
            if pos[1] in ("update", "add", "add-dependency"):
                kind = "other"
        elif b == "poetry" and pos[:1] and pos[0] in ("add", "install", "update", "remove"):
            if pos[0] == "install":
                kind = "file"; filemode = True
            else:
                kind = "other"
        if kind is None:
            return
        mode = self.ctx.deps_mode
        changed_dep = bool(self.dep_files & self.changed)
        if kind == "other":
            self.hit("H3", "%s changes dependencies (only npm and pip can be listed)" % b)
            return
        if kind == "file" or (filemode and not names):
            if mode == "none" and changed_dep:
                self.hit("H3", "%s install while the dependency files changed since the base" % b)
            elif changed_dep and mode == "listed":
                self.hit("H3", "%s install while the dependency files changed since the base" % b)
            return
        if not names:
            if changed_dep:
                self.hit("H3", "%s install while the dependency files changed since the base" % b)
            return
        if mode != "listed":
            self.hit("H3", "%s installs a package (deps=none): %s" % (b, " ".join(names)[:60]))
            return
        allowed = {n.lower().replace("_", "-") for n in self.ctx.deps_names}
        for n in names:
            nm = _pkg_name(kind, n)
            if nm is None or nm.lower().replace("_", "-") not in allowed:
                self.hit("H3", "%s installs a package that is not in deps: %s" % (b, n[:60]))
                return

    # -------- running unclear code (H9)
    def exec_rules(self, b, ww, s):
        r = ww[1:]
        pos = self.positionals(r)
        if s.xargs and (b in F.SHELLS or R.INTERP_RE.match(b)) and not any(re.match(r"^-\w*c$", x) for x in r):
            self.hit("H9", "xargs into %s" % b)
        if self.reads_stdin_program(ww) and b not in ("eval", "source", "."):
            # shell / interpreter whose program comes from stdin: only fine when stdin is a heredoc we scan (handled in heredoc()) -- a < redirect or here-string is not
            if any(re.match(r"^\d*<(?!<)", x) or x == "<<<" or x.startswith("<<<") for x in ww[1:]) or any(x == "<" for x in ww[1:]):
                self.hit("H9", "%s reads its program from a redirect" % b)
        # inline code
        fam = _family(b)
        if fam in R.INLINE_FLAGS or b in F.SHELLS:
            code = None
            if fam in R.INLINE_FLAGS:
                for k, x in enumerate(r):
                    if _inline_flag(b, x) and k + 1 < len(r):
                        code = r[k + 1]; break
                    if fam == "deno" and x == "eval" and k + 1 < len(r):
                        code = r[k + 1]; break
            if code is not None:
                self.inline(b, code)
            elif b in F.SHELLS:
                k = next((i for i in range(len(r) - 1) if re.match(r"^-\w*c$", r[i])), None)
                if k is not None and re.match(r"\s*(?:\$|`)", r[k + 1]):
                    self.hit("H9", "%s -c runs a program that comes from a substitution or variable" % b)
        # script files
        if b in F.SHELLS or R.INTERP_RE.match(b) and b != "osascript":
            self.script_arg(b, r, s)
        elif "/" in ww[0] and os.path.basename(ww[0]) not in KNOWN_TOOLS:
            self.run_path(ww[0], s, shell_guess=True)
        elif "/" in ww[0] and os.path.basename(ww[0]) in KNOWN_TOOLS and not ww[0].startswith(R.SYSTEM_DIRS):
            self.run_path(ww[0], s, shell_guess=True)
        # package / make scripts
        self.script_runners(b, r, pos, s)
        # test runners scan the added lines of changed files
        if self.is_test_runner(b, r, pos, s):
            self.scan_changed(" ".join(ww)[:60])

    def is_test_runner(self, b, r, pos, s):
        c = self.ctx
        if c.test_command and " ".join(s.raw).strip() == c.test_command.strip():
            return True
        if b in R.TEST_RUNNERS:
            return True
        if b in JS_PM_ALL and pos[:1] in (["test"], ["t"], ["tst"]):
            return True
        if b in JS_PM_ALL and pos[:2] and pos[0] in ("run", "run-script") and pos[1].startswith("test"):
            return True
        if b == "yarn" and pos[:1] and pos[0].startswith("test"):
            return True
        if re.match(r"^python[0-9.]*$", b) and "-m" in r:
            k = r.index("-m")
            if k + 1 < len(r) and r[k + 1] in ("pytest", "unittest", "tox", "nose2", "nose", "coverage"):
                return True
        for p0, p1 in R.TEST_PAIRS:
            if b == p0 and p1 in pos[:3] and (p0 != "bundle" or "rspec" in pos):
                return True
        if b in ("go", "swift", "cargo") and "test" in pos[:1]:
            return True
        if b == "make" and any(x in ("test", "check", "tests") for x in pos):
            return True
        return False

    def scan_changed(self, what):
        budget = 2000000; n = 0
        self.changed
        for rel in sorted(self._changed_raw)[:300]:
            if R.SCAN_SKIP.search(rel):
                continue
            t = self.added(rel)
            if not t:
                continue
            t = t[:min(len(t), budget)]
            budget -= len(t)
            for name, rule in R.scan_literals(t):
                self.hit("H9", "%s: the added lines of %s contain '%s'" % (what, rel, name))
                n += 1
                break
            if budget <= 0 or n >= 3:
                break

    def inline(self, b, code):
        if re.match(r"\s*(?:\$|`)", code):
            self.hit("H9", "%s inline code comes from a substitution" % b)
        for name, rule in R.scan_literals(code):
            self.hit(rule, "%s inline code contains '%s'" % (b, name))
        if R.DYNAMIC_CODE.search(code[:200000]):
            self.hit("H9", "%s inline code runs dynamic text" % b)
        self.inline_fs(b, code)

    def heredoc(self, prefix, body, depth):
        sgs = F.cmd_segments(prefix)
        if not sgs:
            return
        a, u, ww = F.norm_seg(sgs[-1])
        ww, _x = self.strip_extra(list(ww))
        while ww and ww[0] in KEYWORDS:
            ww = ww[1:]
        if not ww:
            return
        b = os.path.basename(ww[0])
        if b in F.SHELLS or b == "fish":
            if any(re.match(r"^-\w*c$", x) for x in ww[1:]):
                return
            if depth >= R.MAX_DEPTH:
                self.hit("H9", "heredoc into a shell nested too deep")
            else:
                self.nested(body, depth + 1, "heredoc into %s" % b)
        elif R.INTERP_RE.match(b) or b in ("source", "."):
            self.inline(b, body)
        elif b in R.SQL_CLIENTS:
            if R.SQL_BAD.search(body):
                self.hit("H1", "%s heredoc with DROP/TRUNCATE" % b)
            if b == "sqlite3" and R.SQLITE_DOT.search(body):
                self.hit("H5", "sqlite3 heredoc with a dot-command that runs a program or reads/writes a file")
        elif b in R.REMOTE_SHELLS or b in ("ssh",):
            pass

    def nested(self, text, depth, what):
        """Run all checks on a piece of shell text found inside the command (heredoc into sh, changed script, package script)."""
        sub = _Run(self.ctx, self.cwd)
        sub.cwd = self.root
        sub.bash(text, depth, cwd=self.root)
        for h in sub.hits:
            self.hits.append(h)

    def source(self, ww, s):
        pos = self.positionals(ww[1:])
        if not pos:
            self.hit("H9", "source without a file")
            return
        if pos[0].startswith(("<", "/dev/")):
            self.hit("H9", "source of a stream")
            return
        self.run_path(pos[0], s, shell_guess=True, what="source")

    def script_arg(self, b, r, s):
        """bash x.sh / python3 x.py / node x.js: the first non-option word is the program file (python -m mod: the module)."""
        fam = _family(b)
        shellish = b in F.SHELLS
        i = 0
        while i < len(r):
            x = r[i]
            if shellish and re.match(r"^-\w*c$", x):
                return
            if fam in R.INLINE_FLAGS and _inline_flag(b, x):
                return
            if x == "-m" and fam == "python" and i + 1 < len(r):
                mod = r[i + 1]
                for cand in (mod.replace(".", "/") + ".py", mod.replace(".", "/") + "/__init__.py", mod.replace(".", "/") + "/__main__.py"):
                    if _fold(cand) in self.changed:
                        self.changed_script(cand, False, "python -m " + mod)
                        break
                return
            if x in ("-o", "+o", "-O", "-W", "-X", "-r", "--require", "--import", "--loader", "-I", "-C", "-F", "-M", "-l") and not x == "-I":
                i += 2; continue
            if x.startswith("-") or x.startswith("+"):
                i += 1; continue
            if x in ("-", "/dev/stdin") or x.startswith("/dev/fd/") or x.startswith("<"):
                return
            self.run_path(x, s, shell_guess=shellish, what=b)
            return

    def run_path(self, p, s, shell_guess=False, what=None):
        ap = self.real(p)
        if ap is None:
            self.hit("H9", "%s runs a path that is not known: %s" % (what or "command", p))
            return
        if self.inside(ap):
            rel = self.rel(ap)
            if _fold(rel) in self.changed:
                self.changed_script(rel, shell_guess, what or p)
            elif _fold(ap) in self.written:
                self.hit("H9", "%s runs %s, which the same command writes" % (what or "command", p))
            return
        if ap.startswith(R.SYSTEM_DIRS) or ap in ("/usr/bin/env",):
            return
        k = _fold(ap)
        if os.path.isfile(ap) or self.is_tmp(ap):
            self.hit("H9", "%s runs a file outside the worktree: %s" % (what or "command", p))

    def changed_script(self, rel, shell_guess, what):
        fr = _fold(rel)
        if not any(rx.match(fr) for rx in self.test_re):
            self.hit("H9", "%s runs %s, which changed since the base and is not a test file" % (what, rel))
            return
        text = self.read_rel(rel)
        if text is None:
            self.hit("H9", "%s runs %s, which cannot be read" % (what, rel))
            return
        shell = shell_guess or rel.endswith((".sh", ".bash", ".zsh")) or text.startswith(("#!/bin/sh", "#!/bin/bash", "#!/usr/bin/env bash", "#!/usr/bin/env sh", "#!/bin/zsh"))
        if re.match(r"#!.*\b(python|node|ruby|perl)", text) and not rel.endswith(".sh"):
            shell = False
        if rel.endswith((".py", ".js", ".mjs", ".rb", ".pl", ".ts", ".swift", ".php")):
            shell = False
        bad = []
        if shell:
            sub = _Run(self.ctx, self.root)
            sub.cwd = self.root
            sub.bash(text, R.MAX_DEPTH, cwd=self.root)           # no further nesting through a script's own `bash -c`
            bad = [h[0] for h in sub.hits]
            if bad:
                self.hit("H9", "%s runs %s, whose content fails the scan (%s)" % (what, rel, ",".join(sorted(set(bad)))))
        else:
            lits = R.scan_literals(text)
            if lits or R.DYNAMIC_CODE.search(text[:500000]):
                self.hit("H9", "%s runs %s, whose content fails the scan (%s)" % (what, rel, lits[0][0] if lits else "dynamic code"))

    def script_runners(self, b, r, pos, s):
        c = self.ctx
        if b in JS_PM_ALL or b in ("make", "gmake", "just", "rake"):
            pj = _fold("package.json") in self.changed
            mk = any(_fold(m) in self.changed for m in ("Makefile", "makefile", "GNUmakefile", "Justfile", "justfile"))
            if b in JS_PM_ALL and pj:
                name = None
                if pos[:1] and pos[0] in ("run", "run-script", "run-s", "test", "start", "t", "stop", "restart", "tst") and b != "yarn" or (b == "yarn" and pos):
                    if pos[:1] and pos[0] in ("run", "run-script"):
                        name = pos[1] if len(pos) > 1 else None
                    elif pos[:1] and pos[0] in ("test", "t", "tst", "start", "stop", "restart"):
                        name = {"t": "test", "tst": "test"}.get(pos[0], pos[0])
                    elif b == "yarn" and pos[0] not in R.JS_INSTALL_SUB + ("install", "add", "remove", "publish", "upgrade", "link", "up", "init", "info", "why", "list", "config", "cache", "dlx", "npm", "workspace", "workspaces", "exec", "node"):
                        name = pos[0]
                if name is not None:
                    self.pkg_script(name)
                elif pos[:1] and pos[0] in ("run", "run-script") and len(pos) == 1:
                    pass
            elif b in ("make", "gmake") and mk:
                self.make_target(r, pos)

    def pkg_script(self, name):
        t = self.read_rel("package.json")
        try:
            sc = (json.loads(t) or {}).get("scripts") if t else None
        except ValueError:
            sc = None
        if not isinstance(sc, dict) or not isinstance(sc.get(name), str):
            self.hit("H9", "npm script %s cannot be read from the changed package.json" % name)
            return
        for nm in ("pre" + name, name, "post" + name):
            if isinstance(sc.get(nm), str):
                self.script_text(sc[nm], "npm script %s" % nm)

    def script_text(self, text, what):
        if self.depth_guard() >= R.MAX_DEPTH:
            self.hit("H9", "%s nested too deep" % what)
            return
        sub = _Run(self.ctx, self.root)
        sub.cwd = self.root
        sub.nest = self.depth_guard() + 1
        sub.bash(text, 1, cwd=self.root)
        bad = [h for h in sub.hits]
        for h in bad:
            self.hits.append((h[0], "%s: %s" % (what, h[1]), h[2], h[3]))

    nest = 0

    def depth_guard(self):
        return self.nest

    def make_target(self, r, pos):
        fname = "Makefile"
        for k, x in enumerate(r):
            if x in ("-f", "--file", "--makefile") and k + 1 < len(r):
                fname = r[k + 1]
        t = None
        for cand in (fname, "makefile", "GNUmakefile"):
            t = self.read_rel(cand)
            if t is not None:
                break
        if t is None:
            self.hit("H9", "make: the changed Makefile cannot be read")
            return
        prereq = {}; recipe = {}; order = []; cur = []
        for ln in t.splitlines():
            if ln.startswith("\t"):
                for c in cur:
                    recipe.setdefault(c, []).append(ln.lstrip("\t").lstrip("@-+ "))
                continue
            m = re.match(r"^([^\s:=#][^:=#]*?)\s*::?(?!=)\s*([^#]*)", ln)
            if m and "=" not in ln.split(":", 1)[0]:
                cur = m.group(1).split()
                for c in cur:
                    if c not in prereq:
                        order.append(c)
                    prereq.setdefault(c, []).extend(m.group(2).split())
            elif ln.strip() and not ln.startswith("#"):
                cur = []
        goals = [x for x in pos if "=" not in x] or [next((o for o in order if not o.startswith(".")), None)]
        seen = set(); todo = list(goals); n = 0
        while todo and n < 50:
            g = todo.pop(0); n += 1
            if g is None or g in seen:
                continue
            seen.add(g)
            if g not in prereq and g not in recipe:
                if not os.path.exists(os.path.join(self.root, g)):
                    self.hit("H9", "make target %s is not in the changed Makefile" % g)
                continue
            todo.extend(prereq.get(g, []))
            for rc in recipe.get(g, [])[:200]:
                self.script_text(rc, "make %s" % g)

    # -------- Phase 6 hardening (red-team K01..K23): inline deletes and writes, archives, listeners, npx, git restore, recursive reads of secrets
    def inline_fs(self, b, code):
        """Inline interpreter code (python/node/perl/ruby/php -c/-e, heredoc bodies, awk programs) that deletes files (H1 / H6 / H5 by the target, H9 when the
        target is not a literal) or, for perl/ruby/awk, writes a file outside the charter (H6 / H5). python and node writes are covered by flow's parser."""
        fam = _family(b) if b != "awk" else "awk"
        code = code[:200000]
        lits, dynamic, seen = [], False, 0
        for rx, allargs, method in _DEL_RES.get(fam, ()):
            for m in rx.finditer(code):
                seen += 1
                if seen > 200:
                    self.hit("H9", "%s inline code has more than 200 delete calls" % b)
                    return
                if method:
                    if fam == "ruby" and "Pathname" not in code[max(0, m.start() - 200):m.start()]:
                        continue
                    t = _method_target(fam, code[:m.start()])
                    if t is None:
                        dynamic = True
                    else:
                        lits.append(t)
                    continue
                args = _split_args(code, m.end())
                args = args if allargs else args[:1]
                if not args:
                    dynamic = True
                for a in args:
                    t = _literal(a, fam)
                    if t is None:
                        dynamic = True
                    else:
                        lits.append(t)
        if dynamic:
            self.hit("H9", "%s inline code deletes a target that is not a literal path" % b)
        if lits:
            self.cover(lits[:200], "remove", "%s inline delete" % b, None)
        for rx, kind in _WRITE_RES.get(fam, ()):
            for m in rx.finditer(code):
                p = m.group(1)
                if not p or "$" in p or "@" in p or "#{" in p or p.startswith(("&", "-", "=")) or p == "-":
                    continue
                if kind == "ruby-open" and not re.search(r"[wa+]", m.group(2) or ""):
                    continue
                self.write_target(p, "%s inline code writes" % b)

    def write_target(self, p, label):
        ap = self.real(p)
        if ap is None or ap.startswith("/dev/"):
            return
        if self.protected(ap, "write"):
            self.hit("H5", "%s a protected file: %s" % (label, p))
        elif not self.scope_ok(ap):
            self.hit("H6", "%s outside the charter scope: %s" % (label, p))

    def new_rules(self, b, ww, s):
        r = ww[1:]
        if b in _ARCHIVE_TOOLS:
            self.archive_rules(b, r, ww)
        self.listen_rules(b, r)
        self.reach_rules(b, r, ww, s)

    # ---- archives (K08, K09)
    def archive_rules(self, b, r, ww):
        dest = None; arch = None; extract = False; stdout = False
        if b in ("tar", "bsdtar", "gtar"):
            i = 0; first = True
            while i < len(r):
                x = r[i]
                if x == "--":
                    break
                if x in ("-C", "--directory") and i + 1 < len(r):
                    dest = r[i + 1]; i += 2; first = False; continue
                if x.startswith("--directory="):
                    dest = x.split("=", 1)[1]
                elif x in ("-f", "--file") and i + 1 < len(r):
                    arch = r[i + 1]; i += 2; first = False; continue
                elif x.startswith("--file="):
                    arch = x.split("=", 1)[1]
                elif x in ("--extract", "--get"):
                    extract = True
                elif x in ("--to-stdout",):
                    stdout = True
                elif x.startswith("--"):
                    pass
                elif (x.startswith("-") and len(x) > 1) or (first and re.fullmatch(r"[A-Za-z]+", x)):
                    letters = x.lstrip("-")
                    if x.startswith("-C") and len(x) > 2 and not x.startswith("-C" + "="):
                        dest = x[2:]
                    else:
                        j = i
                        for ch in letters:
                            if ch == "x":
                                extract = True
                            elif ch == "O":
                                stdout = True
                            elif ch == "f" and j + 1 < len(r):
                                arch = r[j + 1]; j += 1
                            elif ch == "C" and j + 1 < len(r):
                                dest = r[j + 1]; j += 1
                        i = j
                    if "c" in letters.replace("--", "") and not x.startswith("--") and "x" not in letters:
                        pass
                first = False
                i += 1
            if extract and stdout:
                return
            if extract and arch in (None, "-"):
                arch = None
        elif b == "unzip":
            pos = []
            i = 0
            while i < len(r):
                x = r[i]
                if x == "-d" and i + 1 < len(r):
                    dest = r[i + 1]; i += 2; continue
                if x.startswith("-d") and len(x) > 2 and not x.startswith("--"):
                    dest = x[2:]
                elif x.startswith("-") and len(x) > 1:
                    if set(x[1:]) & set("ltvZpz") and "d" not in x[1:]:
                        return                                # list / test / pipe only
                elif x == "-x":
                    pass
                else:
                    pos.append(x)
                i += 1
            extract = True
            arch = pos[0] if pos else None
        elif b == "cpio":
            mode_i = False; mode_other = False; i = 0; pos = []
            while i < len(r):
                x = r[i]
                if x in ("-D", "--directory") and i + 1 < len(r):
                    dest = r[i + 1]; i += 2; continue
                if x.startswith("--directory="):
                    dest = x.split("=", 1)[1]
                elif x in ("-I", "--file") and i + 1 < len(r):
                    arch = r[i + 1]; i += 2; continue
                elif x == "--extract":
                    mode_i = True
                elif x in ("--list", "--create", "--pass-through"):
                    mode_other = True
                elif x.startswith("-") and not x.startswith("--"):
                    letters = x[1:]
                    if "i" in letters and "o" not in letters:
                        mode_i = True
                    if "t" in letters or "o" in letters:
                        mode_other = True
                    if "p" in letters:
                        mode_other = True
                        pos.append("__pass__")
                else:
                    pos.append(x)
                i += 1
            if "__pass__" in pos:
                tgt = [x for x in pos if x != "__pass__"]
                if tgt:
                    self.write_target(tgt[-1], "cpio -p writes")
                return
            if not mode_i or mode_other:
                return
            extract = True
            if arch is None:
                for x in ww:
                    m = re.match(r"^\d*<(?!<)(.+)$", x)
                    if m:
                        arch = m.group(1)
                if arch is None and "<" in ww and ww.index("<") + 1 < len(ww):
                    arch = ww[ww.index("<") + 1]
        elif b == "ditto":
            pos = [x for x in r if not x.startswith("-")]
            if any(x == "-x" or re.fullmatch(r"-[A-Za-z]*x[A-Za-z]*", x) for x in r if x.startswith("-")):
                extract = True
                arch = pos[0] if pos else None
                dest = pos[-1] if len(pos) > 1 else None
            elif len(pos) >= 2:
                self.write_target(pos[-1], "ditto writes")
                return
            else:
                return
        elif b in ("7z", "7za", "7zr", "7zz", "7zA"):
            pos = [x for x in r if not x.startswith("-")]
            if not pos or pos[0] not in ("x", "e"):
                return
            extract = True
            arch = pos[1] if len(pos) > 1 else None
            for x in r:
                if x.startswith("-o") and len(x) > 2:
                    dest = x[2:]
        if not extract:
            return
        label = b
        if dest is None:
            ap = os.path.realpath(self.cwd)
        else:
            ap = self.real(dest)
            if ap is None:
                self.hit("H9", "%s extracts into a directory that is not known: %s" % (label, dest))
                return
        if self.is_tmp(ap) and not self.inside(ap):
            return
        if not self.inside(ap):
            self.hit("H6", "%s extracts outside the worktree: %s" % (label, dest or ap))
            return
        if self.protected(ap, "write"):
            self.hit("H5", "%s extracts into a protected path: %s" % (label, dest or ap))
            return
        if self.protected(ap, "remove"):
            # the worktree root (or a folder holding protected ones): the members could be .claude/.githooks/...; only a tracked, unchanged archive may be unpacked there
            aap = self.real(arch) if arch else None
            ok = False
            if aap and self.inside(aap):
                rel = self.rel(aap)
                ok = bool(self.tracked_under(rel)) and _fold(rel) not in self.changed
            if not ok:
                self.hit("H9", "%s extracts an archive that is not a tracked, unchanged file into %s (its members cannot be checked)" % (label, dest or "the current folder"))
            return
        if not (self.in_scope(self.rel(ap)) or self.in_scope(self.rel(ap) + "/x")):
            self.hit("H6", "%s extracts outside the charter scope: %s" % (label, dest or ap))

    # ---- listening servers (K23)
    def listen_rules(self, b, r):
        host = None; found = False
        if re.match(r"^python[0-9.]*$", b) and "-m" in r:
            k = r.index("-m")
            mod = r[k + 1] if k + 1 < len(r) else ""
            if mod in ("http.server", "SimpleHTTPServer", "pyftpdlib", "smtpd", "aiosmtpd"):
                found = True
                host = _opt_value(r[k + 2:], ("--bind", "-b", "--address", "-H", "--host"))
        elif b == "php" and ("-S" in r or any(x.startswith("-S") and len(x) > 2 for x in r)):
            found = True
            v = _opt_value(r, ("-S",))
            host = (v or "").rsplit(":", 1)[0] if v and ":" in v else v
            if v and v.startswith("["):
                host = v.rsplit("]:", 1)[0] + "]"
        elif b == "ruby" and ("-run" in r or ("-r" in r and "un" in r)) and "httpd" in r:
            found = True
            host = _opt_value(r, ("-b", "--bind-address", "--bind"))
        elif b in _LISTEN_PKGS:
            found = True
            host = _opt_value(r, _LISTEN_PKGS[b])
        if not found:
            return
        if host is None or not _LISTEN_LOCAL.match(host):
            self.hit("H3", "%s opens a listening server%s" % (b, " on %s" % host if host else " on all interfaces (no local --bind)"))

    # ---- npx and friends (K21, K22)
    def declared(self, kind, name):
        """Is a package named in the project's own declarations (package.json / requirements / pyproject) or installed in its local bin?"""
        c = self.ctx
        if c.declared is not None:
            return bool(c.declared(kind, name))
        key = (kind, name)
        if key in self._declared:
            return self._declared[key]
        ok = False
        if kind == "npm":
            alias = _BIN_ALIAS.get(name)
            cands = {name} | ({alias} if alias else set())
            t = self.read_rel("package.json")
            try:
                pj = json.loads(t) if t else {}
            except ValueError:
                pj = {}
            if isinstance(pj, dict):
                for sec in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
                    d = pj.get(sec)
                    if isinstance(d, dict) and cands & set(d):
                        ok = True
            if not ok and re.fullmatch(r"[A-Za-z0-9._-]+", name or ""):
                ok = os.path.isfile(os.path.join(self.root, "node_modules", ".bin", name))
        else:
            nm = re.sub(r"[-_.]+", "-", name.lower())
            for f in ("requirements.txt", "requirements-dev.txt", "requirements_dev.txt", "pyproject.toml", "Pipfile", "setup.cfg", "setup.py"):
                t = self.read_rel(f)
                if not t:
                    continue
                for ln in t.splitlines():
                    m = re.match(r"""^\s*[-"']?\s*([A-Za-z0-9][A-Za-z0-9._-]*)""", ln)
                    if m and re.sub(r"[-_.]+", "-", m.group(1).lower()) == nm:
                        ok = True
                    if re.search(r"""["']\s*%s\s*(?:[\[<>=!~;"',]|$)""" % re.escape(nm).replace("\\-", "[-_.]"), ln.lower()):
                        ok = True
            if not ok and re.fullmatch(r"[A-Za-z0-9._-]+", name or ""):
                ok = os.path.isfile(os.path.join(self.root, ".venv", "bin", name))
        self._declared[key] = ok
        return ok

    def runner_rules(self, label, kind, r):
        """npx / bunx / npm exec / pipx run / uvx: the first package spec (or every --package) must be declared by the project."""
        explicit = []; spec = None; no_install = False; i = 0
        valued = {"-c", "--call", "--shell", "--node-arg", "--cache", "--userconfig", "--registry", "-n", "--prefix", "--workspace", "-w", "--python", "--index-url", "-i", "--with"}
        while i < len(r):
            x = r[i]
            if x == "--":
                spec = r[i + 1] if i + 1 < len(r) else None
                break
            if x in ("--no-install", "--no", "--offline", "--no-fund"):
                no_install = x != "--no-fund" or no_install
            elif x in ("-p", "--package") and i + 1 < len(r):
                explicit.append(r[i + 1]); i += 2; continue
            elif x.startswith("--package="):
                explicit.append(x.split("=", 1)[1])
            elif x == "--spec" and i + 1 < len(r):
                explicit.append(r[i + 1]); i += 2; continue
            elif x.startswith("--spec="):
                explicit.append(x.split("=", 1)[1])
            elif x in ("-c", "--call") and i + 1 < len(r):
                self.nested(r[i + 1], 1, "%s -c" % label)
                return
            elif x in valued and i + 1 < len(r):
                i += 2; continue
            elif x.startswith("-"):
                pass
            else:
                spec = x
                break
            i += 1
        if no_install:
            return
        specs = explicit or ([spec] if spec else [])
        if not specs:
            return
        for sp in specs:
            if sp.startswith((".", "/", "~")) and kind == "npm":
                continue
            nm = _pkg_name(kind, sp)
            ver = bool(re.search(r"(?<=[\w])@\S", sp)) if kind == "npm" else bool(re.search(r"(?:==|>=|<=|~=|!=|<|>|@)", sp))
            if nm is None or ver or not self.declared(kind, nm):
                if self.ctx.deps_mode == "listed" and nm and not ver and nm.lower().replace("_", "-") in {n.lower().replace("_", "-") for n in self.ctx.deps_names}:
                    continue
                self.hit("H3", "%s runs a package that the project does not declare: %s" % (label, sp[:60]))
                return
        if kind == "npm":
            name0 = _pkg_name("npm", specs[0]) or ""
            if name0 in _LISTEN_PKGS:
                self.listen_rules(name0, r[r.index(spec) + 1:] if spec in r else [])

    # ---- git restore of protected paths (K15, K16)
    def pathspec_protected(self, p, strict):
        """Does a git pathspec name (or contain, when strict) a protected path? strict: the source is another revision, so a folder holding protected files counts."""
        if not p or p.startswith(":"):
            return p.startswith(":") and any(k in p for k in (".claude", ".shipmiracle", ".githooks", ".git/", ".mcp.json", ".env"))
        kind = "remove" if strict else "write"
        if re.search(r"[*?\[]", p):
            full = p if os.path.isabs(p) else os.path.join(self.cwd, p)
            hits = _glob.glob(full)
            top = os.path.dirname(os.path.realpath(full))
            if _fold(top) == self.froot or self.inside(top) and False:
                hits += [os.path.join(self.root, n) for n in (".shipmiracle", ".claude", ".githooks", ".git", ".mcp.json", ".env") if fnmatch.fnmatchcase(n, os.path.basename(full))]
            for h in hits:
                if self.protected(os.path.realpath(h), kind):
                    return True
            return False
        ap = self.real(p)
        if ap is None:
            return True
        return self.protected(ap, kind)

    def git_restore(self, sub, rest, rf, refs_before, after_dd):
        explicit_src = False; paths = []
        if sub == "restore":
            i = 0
            while i < len(rest):
                x = rest[i]
                if x in ("-s", "--source") and i + 1 < len(rest):
                    explicit_src = explicit_src or not self.ref_ok(rest[i + 1]); i += 2; continue
                if x.startswith(("--source=", "-s=")) or (x.startswith("-s") and len(x) > 2 and not x.startswith("--")):
                    explicit_src = explicit_src or not self.ref_ok(x.split("=", 1)[1] if "=" in x else x[2:])
                elif x == "--":
                    paths += rest[i + 1:]
                    break
                elif x.startswith("--pathspec-from-file"):
                    self.hit("H9", "git restore --pathspec-from-file: the paths are not known")
                elif not x.startswith("-"):
                    paths.append(x)
                i += 1
        else:                                          # checkout <rev> -- paths / checkout <rev> paths
            if "--" in rest:
                refs = [x for x in rest[:rest.index("--")] if not x.startswith("-")]
                explicit_src = any(not self.ref_ok(x) for x in refs)
                paths = list(after_dd)
            else:
                pos = [x for x in rest if not x.startswith("-")]
                if len(pos) >= 2 and not os.path.exists(os.path.join(self.cwd, pos[0])):
                    explicit_src = not self.ref_ok(pos[0]); paths = pos[1:]
                else:
                    paths = pos
        for p in paths:
            if p in (".", "./") and explicit_src or p not in (".", "./") and self.pathspec_protected(p, explicit_src):
                self.hit("H5", "git %s writes a protected path: %s" % (sub, p))
                return

    def git_index_rules(self, sub, rest, rf, rp):
        if sub == "read-tree":
            if any(f in ("-h", "--help", "--empty") for f in rf) and False:
                return
            pre = next((f.split("=", 1)[1] for f in rf if f.startswith("--prefix=")), None)
            if pre is not None and not any(re.fullmatch(r"-[A-Za-z]*u[A-Za-z]*", f) or f in ("--reset",) for f in rf):
                ap = self.real(pre)
                if ap is not None and self.inside(ap) and not self.protected(ap) and not self.protected(ap, "remove"):
                    return
            self.hit("H5", "git read-tree replaces the index or the tree, protected files included")
            return
        paths = []
        i = 0
        while i < len(rest):
            x = rest[i]
            if x == "--cacheinfo" and i + 1 < len(rest):
                v = rest[i + 1]
                if "," in v:
                    paths.append(v.split(",", 2)[-1]); i += 2; continue
                if i + 3 < len(rest):
                    paths.append(rest[i + 3]); i += 4; continue
            elif x in ("--index-info", "--stdin", "--stdin"):
                self.hit("H5", "git update-index %s: the paths are not known" % x)
            elif x == "--" :
                paths += rest[i + 1:]
                break
            elif not x.startswith("-"):
                paths.append(x)
            i += 1
        for p in paths:
            if self.pathspec_protected(p, False):
                self.hit("H5", "git update-index on a protected path: %s" % p)
                return

    def git_apply_paths(self, rest):
        """git apply / am with a readable patch: the files it names (H5 when one is protected). The H9 for an unknown change set stays."""
        for x in rest:
            if x.startswith("-") or x in ("-",):
                continue
            ap = self.real(x)
            if not ap or not os.path.isfile(ap) or not (self.inside(ap) or self.is_tmp(ap)):
                continue
            try:
                with open(ap, encoding="utf-8", errors="replace") as f:
                    txt = f.read(2000000)
            except OSError:
                continue
            for m in re.finditer(r"^(?:diff --git a/(\S+) b/(\S+)|\+\+\+ b/(\S+)|--- a/(\S+)|rename (?:to|from) (\S+))", txt, re.M):
                for g in m.groups():
                    if g:
                        a2 = self.real(g, self.root)
                        if a2 and self.protected(a2, "write"):
                            self.hit("H5", "git patch touches a protected path: %s" % g)
                            return

    # ---- recursive reads and copies that reach secret files (K17)
    def env_names_in(self, ap):
        """Names of .env* files (not .env.example) below a directory; the folders above the worktree and the credential folders always count."""
        key = _fold(ap)
        if key in self._env_cache:
            return self._env_cache[key]
        out = []
        k = key.rstrip("/")
        if (self.froot.startswith(k + "/") and k != self.froot) or k == "" or k == _fold(self.home).rstrip("/"):
            out = [".env", ".env.local", ".env.production"]
        elif self.sens_word(ap):
            out = [".env"]
        elif os.path.isdir(ap):
            n = 0
            for dp, dn, fn in os.walk(ap):
                dn[:] = [d for d in dn if d not in (".git", "node_modules", ".venv", "venv", "__pycache__")]
                for f in fn:
                    if f.startswith(".env") and f != ".env.example":
                        out.append(f)
                n += len(fn) + len(dn)
                if n > 20000 or len(out) >= 8:
                    break
        self._env_cache[key] = out
        return out

    def reach_dirs(self, targets):
        """Directories among the (possibly glob) targets; a missing target is not a directory."""
        out = []
        for t in targets:
            if "$" in t or "`" in t:
                if self.expand(t) is None:
                    continue
            ex = self.expand(t) or t
            full = ex if os.path.isabs(ex) else os.path.join(self.cwd, ex)
            cands = [full]
            if re.search(r"[*?\[]", ex):
                cands = [c for c in sorted(_glob.glob(full))[:500] if not os.path.basename(c).startswith(".") or os.path.basename(ex).startswith(".")]
            for c in cands:
                ap = os.path.realpath(c)
                if os.path.isdir(ap):
                    out.append(ap)
        return out

    def secret_hit(self, label, names, includes=(), excludes=(), iexcl=False):
        left = []
        for n in names:
            if includes and not any(fnmatch.fnmatchcase(n, g) for g in includes):
                continue
            if any(fnmatch.fnmatchcase(n, g) for g in excludes):
                continue
            left.append(n)
        if left:
            self.hit("H5", "%s reaches secret files (%s)" % (label, left[0]))
            return True
        return False

    def reach_rules(self, b, r, ww, s):
        if b in ("grep", "egrep", "fgrep", "zgrep", "ggrep", "bsdgrep", "rg", "ag", "ack"):
            self.search_reach(b, r)
        elif b == "find":
            self.find_reach(ww, s)
        elif b == "tar" or b == "bsdtar":
            if any(re.fullmatch(r"-?[A-Za-z]*c[A-Za-z]*", x) for x in r[:1]) or "--create" in r:
                self.copy_reach(b, [x for x in r[1:] if not x.startswith("-")] if r and not r[0].startswith("-") else self.positionals(r))
        elif b == "zip":
            if any(x.startswith("-") and "r" in x[1:] for x in r if not x.startswith("--")) or "--recurse-paths" in r:
                self.copy_reach(b, self.positionals(r)[1:])
        elif b in ("cp", "rsync", "ditto"):
            if any((x.startswith("-") and not x.startswith("--") and ("r" in x or "R" in x or "a" in x)) or x in ("--recursive", "--archive") for x in r) or b == "ditto":
                pos = self.positionals(r)
                self.copy_reach(b, pos[:-1] if len(pos) > 1 else pos)

    def copy_reach(self, label, srcs):
        for ap in self.reach_dirs(srcs):
            names = self.env_names_in(ap)
            if names:
                self.hit("H5", "%s copies a folder that holds secret files (%s)" % (label, names[0]))
                return

    def search_reach(self, b, r):
        recursive = False; includes = []; excludes = []; pos = []; pat_given = False; hidden = False; uu = 0; pglobs = []; nglobs = []
        vopts = {"grep": {"-e", "-f", "-m", "-A", "-B", "-C", "-d", "-D", "--include", "--exclude", "--exclude-dir", "--exclude-from", "--label", "--max-count", "--file", "--regexp", "--context"},
                 "rg": {"-e", "-f", "-g", "--glob", "--iglob", "-t", "-T", "--type", "--type-not", "-m", "-A", "-B", "-C", "-j", "-M", "--max-depth", "-d", "--max-filesize", "--regexp", "--file", "--pre", "--sort", "--sortr", "-E", "--encoding", "-r", "--replace", "--path-separator", "--ignore-file", "--max-columns", "--threads", "--context", "--max-count"},
                 "ag": {"-A", "-B", "-C", "-G", "-g", "-m", "--depth", "--ignore", "--ignore-dir", "-p", "--path-to-ignore", "-W", "--workers", "--pager", "--file-search-regex", "-S"}}
        opts = vopts["grep"] if b not in ("rg", "ag", "ack") else vopts.get(b, vopts["rg"])
        i = 0
        while i < len(r):
            x = r[i]
            if x == "--":
                pos += r[i + 1:]
                break
            if x.startswith("--"):
                name, eq, val = x.partition("=")
                if name in ("--recursive", "--dereference-recursive"):
                    recursive = True
                elif name == "--directories" and val == "recurse":
                    recursive = True
                elif name == "--include" or (b != "grep" and name == "--glob" and False):
                    v = val if eq else (r[i + 1] if i + 1 < len(r) else ""); includes.append(v)
                    i += 1 if not eq else 0
                elif name == "--exclude":
                    v = val if eq else (r[i + 1] if i + 1 < len(r) else ""); excludes.append(v)
                    i += 1 if not eq else 0
                elif name in ("--glob", "--iglob"):
                    v = val if eq else (r[i + 1] if i + 1 < len(r) else "")
                    (nglobs if v.startswith("!") else pglobs).append(v.lstrip("!"))
                    i += 1 if not eq else 0
                elif name in ("--hidden", "--no-ignore-dot") and name == "--hidden":
                    hidden = True
                elif name == "--unrestricted":
                    uu += 1
                elif name in ("--regexp", "--file") :
                    pat_given = True
                    i += 1 if not eq else 0
                elif name in opts and not eq:
                    i += 1
                i += 1
                continue
            if x.startswith("-") and len(x) > 1:
                letters = x[1:]
                if b in ("rg", "ag"):
                    uu += letters.count("u") if set(letters) <= set("uU") else 0
                    if x == "-." or letters == ".":
                        hidden = True
                if b not in ("rg", "ag") and set(letters) & set("rR"):
                    recursive = True
                if x in opts and i + 1 < len(r):
                    v = r[i + 1]
                    if x in ("-e", "-f"):
                        pat_given = True
                    elif x == "-d" and v == "recurse":
                        recursive = True
                    elif x in ("-g",) and b == "rg":
                        (nglobs if v.startswith("!") else pglobs).append(v.lstrip("!"))
                    i += 2
                    continue
                if re.fullmatch(r"-[A-Za-z]*[eEf]", letters) and b != "rg" and i + 1 < len(r) and letters[-1] in "ef":
                    pat_given = True
                    i += 2
                    continue
                i += 1
                continue
            pos.append(x)
            i += 1
        if b in ("rg", "ag"):
            recursive = True
            if uu >= 2 or (b == "ag" and uu >= 1):
                hidden = True
        if b == "ack":
            recursive = True
        if not recursive:
            return
        targets = pos if pat_given else pos[1:]
        if not targets:
            targets = ["."]
        names_filter = None
        if b in ("rg", "ag"):
            inplay = [".env", ".env.local", ".env.production"] if hidden else []
            for g in pglobs:
                for n in (".env", ".env.local", ".env.production"):
                    if fnmatch.fnmatchcase(n, g) and n not in inplay:
                        inplay.append(n)
            excl = nglobs
        else:
            inplay = None
            excl = excludes
        for ap in self.reach_dirs(targets):
            names = self.env_names_in(ap)
            if inplay is not None:
                names = [n for n in names if n in inplay or any(fnmatch.fnmatchcase(n, g) for g in pglobs)] if (hidden or pglobs) else []
            if self.secret_hit(b + " over " + os.path.basename(ap.rstrip("/")) , names, includes, excl):
                return

    def find_reach(self, ww, s):
        r = ww[1:]
        k = next((i for i, x in enumerate(r) if x in ("-exec", "-execdir", "-ok", "-okdir")), None)
        if k is None:
            return
        sub = []
        for x in r[k + 1:]:
            if x in (";", "+"):
                break
            sub.append(x)
        sub, _x = self.strip_extra(sub)
        if sub and os.path.basename(sub[0]) in _READERS:
            self.find_secret(r, os.path.basename(sub[0]))

    def find_secret(self, r, reader):
        starts = []
        for x in r:
            if x.startswith("-") or x in ("(", "!"):
                break
            starts.append(x)
        starts = starts or ["."]
        incl = []; excl = []; neg = False
        for i, x in enumerate(r):
            if x in ("!", "-not"):
                neg = True
                continue
            if x in ("-name", "-iname") and i + 1 < len(r):
                (excl if neg else incl).append(r[i + 1])
            neg = False
        for ap in self.reach_dirs(starts):
            if self.secret_hit("find | %s" % reader, self.env_names_in(ap), incl, excl):
                return

    def pipe_xargs(self, segs):
        for k, sg in enumerate(segs):
            if (sg.xargs or any(os.path.basename(x) == "xargs" for x in sg.lead)) and sg.ww and os.path.basename(sg.ww[0]) in _READERS and k > 0 and sg.depth == segs[k - 1].depth:
                prev = segs[k - 1].ww
                if prev and os.path.basename(prev[0]) == "find":
                    self.find_secret(prev[1:], os.path.basename(sg.ww[0]))

    # -------- C1: a copied/moved/linked FOLDER lands at dest/basename(src) (or, for `src/`, `src/.` and ditto, with its members directly in dest)
    _COPY_VAL = {"cp": ("-t", "--target-directory", "-S", "--suffix"), "mv": ("-t", "--target-directory", "-S", "--suffix"), "install": ("-t", "-m", "-o", "-g", "-S"),
                 "ln": ("-t", "--target-directory", "-S", "--suffix"), "ditto": ("-V",),
                 "rsync": ("-e", "--rsh", "--exclude", "--include", "--filter", "-f", "--exclude-from", "--include-from", "--files-from", "--rsync-path", "--backup-dir", "--suffix",
                           "--partial-dir", "--log-file", "--bwlimit", "--max-size", "--min-size", "--timeout", "--port", "--chmod", "--chown", "--usermod", "--groupmod", "-M",
                           "--info", "--debug", "--compare-dest", "--copy-dest", "--link-dest", "--temp-dir", "-T", "--address", "--sockopts", "--out-format", "--iconv",
                           "--protocol", "-B", "--block-size", "--compress-level", "--skip-compress", "--modify-window")}

    def copy_members(self, b, r):
        val = self._COPY_VAL.get(b, ())
        pos = []; tdir = None; i = 0
        while i < len(r):
            x = r[i]
            if x == "--":
                pos += r[i + 1:]
                break
            if (x in ("-t", "--target-directory") or (b in ("cp", "mv", "ln") and re.fullmatch(r"-[A-Za-z]*t", x))) and b != "rsync" and b != "ditto":
                if i + 1 < len(r):
                    tdir = r[i + 1]
                i += 2; continue
            if x.startswith("--target-directory="):
                tdir = x.split("=", 1)[1]; i += 1; continue
            if x.startswith("-") and x != "-":
                i += 2 if x in val else 1
                continue
            pos.append(x); i += 1
        if tdir is not None:
            dest, srcs = tdir, pos
        elif len(pos) >= 2:
            dest, srcs = pos[-1], pos[:-1]
        elif b == "ln" and len(pos) == 1:
            dest, srcs = ".", pos
        else:
            return
        if b == "rsync" and ":" in dest and not dest.startswith(("/", ".", "~")):
            return                                             # remote destination: the network rules judge it
        D = self.real(dest)
        if D is None:
            return                                             # an unknown destination is judged by flow's write-target parser (H9)
        dest_dir = os.path.isdir(D) or dest.endswith("/") or dest in (".", "..") or b == "ditto" or len(srcs) > 1
        recursive = b in ("ditto", "mv", "rsync") or any(re.fullmatch(r"-[A-Za-z]*[rRa][A-Za-z]*", x) or x in ("--recursive", "--archive") for x in r if x.startswith("-"))

        def land(ap):
            if self.protected(ap, "write"):
                self.hit("H5", "%s puts a protected file in place: %s" % (b, ap[len(self.root) + 1:] if self.inside(ap) else ap))
                return True
            if self.inside(ap) and self.is_always_excluded(_cf(self.rel(ap))):
                self.hit("H6", "%s writes outside the charter scope: %s" % (b, self.rel(ap)))
                return True
            return False
        for tok in srcs:
            if b == "rsync" and ":" in tok and not tok.startswith(("/", ".", "~")):
                continue
            if "$" in tok or "`" in tok:
                if self.expand(tok) is None:
                    if recursive:
                        self.hit("H9", "%s with a source folder that is not known: %s" % (b, tok))
                    continue
            ex = self.expand(tok) or tok
            full = ex if os.path.isabs(ex) else os.path.join(self.cwd, ex)
            cands = [full]
            if re.search(r"[*?\[]", ex):
                try:
                    cands = sorted(_glob.glob(full))[:2000]
                except Exception:
                    cands = [full]
            for c in cands:
                if not os.path.lexists(c):
                    continue
                srcp = os.path.realpath(c) if not os.path.islink(c) or recursive else os.path.abspath(c)
                base = os.path.basename(srcp.rstrip("/"))
                prefixes = ([os.path.join(D, base)] if dest_dir else []) + [D]
                for pre in prefixes:
                    if land(pre):
                        return
                if recursive and os.path.isdir(srcp) and not (os.path.islink(c) and b != "ditto" and False):
                    n = 0
                    failed = []
                    for root, dirs, files in os.walk(srcp, followlinks=False, onerror=lambda e: failed.append(e)):
                        for nm in dirs + files:
                            n += 1
                            if n > 20000:
                                self.hit("H9", "%s of a folder with more than 20000 entries: %s" % (b, tok))
                                return
                            m = os.path.relpath(os.path.join(root, nm), srcp)
                            for pre in prefixes:
                                if land(os.path.join(pre, m)):
                                    return
                    if failed:
                        self.hit("H9", "%s of a folder that cannot be read completely: %s" % (b, tok))
                        return

    # -------- outside the charter (H6 beyond writes)
    def outside_rules(self, b, ww, s):
        r = ww[1:]
        for k, x in enumerate(r):
            d = None
            if b in ("make", "gmake") and x in ("-C", "--directory") and k + 1 < len(r):
                d = r[k + 1]
            elif b in ("make", "gmake") and (x.startswith("-C") and len(x) > 2):
                d = x[2:]
            elif b in ("make", "gmake") and x.startswith("--directory="):
                d = x.split("=", 1)[1]
            elif b in ("npm", "pnpm", "yarn", "bun", "cargo", "swift", "tar", "pip", "pip3", "uv", "go", "zip") and x in ("--prefix", "--cwd", "--dir", "--directory", "--manifest-path", "-C", "--chdir", "--package-path", "--target", "--file") and k + 1 < len(r):
                d = r[k + 1]
            elif b in ("npm", "pnpm", "yarn", "bun", "cargo", "swift", "tar", "uv") and x.startswith(("--prefix=", "--cwd=", "--dir=", "--directory=", "--manifest-path=", "--chdir=", "--package-path=")):
                d = x.split("=", 1)[1]
            if d is not None:
                if b == "tar" and not any(re.match(r"^-?[A-Za-z]*x", r[0]) or y in ("--extract", "-x", "--get") for y in r[:1]) and "-x" not in r:
                    continue
                ap = self.real(d)
                if ap is None:
                    self.hit("H9", "%s %s: the directory is unknown" % (b, x))
                elif not (self.inside(ap) or self.is_tmp(ap)):
                    self.hit("H6", "%s %s points outside the worktree" % (b, x))
        if b == "ln":
            pos = self.positionals(r)
            symbolic = any(re.fullmatch(r"-[A-Za-z]*s[A-Za-z]*", x) or x == "--symbolic" for x in r)
            if len(pos) >= 1:
                tgt = pos[0]
                link = pos[1] if len(pos) > 1 else os.path.basename(tgt)
                lp = self.real(link)
                if symbolic:
                    base = os.path.dirname(lp) if lp else self.cwd
                    ap = self.real(tgt, base)
                else:
                    ap = self.real(tgt)
                if ap is None or lp is None:
                    self.hit("H9", "ln with an unknown path")
                elif not self.scope_ok(ap) and not (self.is_tmp(ap) and not symbolic):
                    self.hit("H6", "ln %s points outside the charter" % ("-s" if symbolic else ""))
                elif self.inside(ap) is False and symbolic:
                    self.hit("H6", "ln -s to outside the worktree")
        if b in ("cp", "install", "rsync", "ditto", "mv", "ln") and not s.xargs:
            self.copy_members(b, r)
        if b in ("patch",) and not any(x in ("--dry-run", "--check") for x in r):
            self.hit("H9", "patch: the files it changes are not known")
        if b in ("cat", "head", "tail", "less", "more", "bat", "nl", "tac"):
            pass


SENS_KEYS = (".ssh", ".aws", ".gnupg", ".kube", ".docker", ".netrc", ".pypirc", ".git-credentials", "Library/Launch", "config/gh", ".env", "keyrings", "environ")
PROC_ENV_TEXT = re.compile(r"/proc/(?!self/|thread-self/)[^\s;|&<>]*?/(?:task/[^\s/]*/)?environ\b")      # on the raw command text, with ${..} and $(..) collapsed (the word splitter cuts at { and })
PROC_ENVIRON = re.compile(r"(?:^|/)proc/(?!self/|thread-self/)[^/]+/(?:task/[^/]+/)?environ$")      # another process's environment (D9 M3); /proc/self/environ is what `env` prints anyway
KNOWN_TOOLS = {"git", "gh", "curl", "wget", "ssh", "scp", "rsync", "docker", "npm", "yarn", "pnpm", "pip", "pip3", "python", "python3", "node", "bash", "sh", "zsh", "env", "make", "ls", "cat", "rm",
                "mv", "cp", "sed", "awk", "grep", "find", "xargs", "tar", "open", "sudo", "kubectl", "terraform"}
HIDING_TOOLS = {"git", "gh", "rm", "unlink", "docker", "npm", "yarn", "pnpm", "pip", "pip3", "curl", "wget", "kubectl", "terraform", "ssh", "scp", "mv", "cp", "ln", "python", "python3", "node", "cargo", "gem", "twine",
                "brew", "sudo", "find", "rsync", "psql", "sqlite3", "mysql"}
JS_PM_ALL = ("npm", "yarn", "pnpm", "bun")
URL_LIKE = R.URL_RE
LOCAL_URL = R.LOCAL_HOST_RE


def _family(b):
    f = re.sub(r"[0-9.]+$", "", b)
    return {"nodejs": "node"}.get(f, f)


def _inline_flag(b, x):
    fam = _family(b)
    if fam == "python":
        return bool(re.fullmatch(r"-[A-Za-z]*c", x))
    if fam == "node":
        return x in ("-e", "--eval", "-p", "--print", "-pe") or bool(re.fullmatch(r"-[A-Za-z]*[ep]", x))
    if fam in ("ruby", "lua", "julia", "swift", "Rscript", "bun"):
        return x in ("-e", "--eval") or bool(re.fullmatch(r"-[A-Za-z]*e", x))
    if fam == "perl":
        return bool(re.fullmatch(r"-[A-Za-z]*[eE]", x))
    if fam == "php":
        return x == "-r"
    return False


def _pkg_name(kind, spec):
    s = spec.strip()
    if not s or s.startswith((".", "/", "~", "file:", "git+", "http", "github:", "link:", "workspace:")) or "://" in s:
        return None
    if kind == "npm":
        if s.startswith("@"):
            m = re.match(r"^(@[a-z0-9._-]+/[a-z0-9._-]+)(?:@.*)?$", s, re.I)
        else:
            m = re.match(r"^([a-z0-9._-]+)(?:@.*)?$", s, re.I)
        return m.group(1) if m else None
    m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?(?:\s*(?:==|>=|<=|~=|!=|<|>|===).*)?$", s)
    return m.group(1) if m else None



# ---- helpers of the hardening rules (K01..K23): a tiny call-argument scanner, literal strings, option values
_ARCHIVE_TOOLS = R.ARCHIVE_TOOLS
_READERS = R.READERS
_LISTEN_PKGS = R.LISTEN_PKGS
_LISTEN_LOCAL = R.LISTEN_LOCAL
_BIN_ALIAS = R.BIN_ALIAS
_DEL_RES = R.DEL_RES
_WRITE_RES = R.WRITE_RES


def _split_args(code, i):
    """Top-level arguments of the call whose name ends at code[i]: `(a, b)` or a bare list (perl/ruby). Quotes and brackets are respected."""
    n = min(len(code), i + 2000)                         # a call longer than this is not a plain path: its tail is cut, the argument then is not a literal
    while i < n and code[i] in " \t":
        i += 1
    paren = i < n and code[i] == "("
    if paren:
        i += 1
    args = []; cur = []; depth = 0; q = None
    while i < n:
        ch = code[i]
        if q:
            cur.append(ch)
            if ch == "\\" and i + 1 < n:
                cur.append(code[i + 1]); i += 2
                continue
            if ch == q:
                q = None
        elif ch in "'\"`":
            q = ch; cur.append(ch)
        elif ch in "([{":
            depth += 1; cur.append(ch)
        elif ch in ")]}":
            if depth == 0:
                break
            depth -= 1; cur.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(cur).strip()); cur = []
        elif ch in ";\n" and depth == 0 and not paren:
            break
        else:
            cur.append(ch)
        i += 1
    last = "".join(cur).strip()
    if last or args:
        args.append(last)
    return args


_STR_RE = re.compile(r"""^(?:[rRbBuU]{0,2})('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")$""", re.S)


def _literal(arg, fam):
    """The text of a plain string literal argument, or None (a variable, an expression, an interpolated or f-string)."""
    a = (arg or "").strip()
    if fam == "perl":
        m = re.match(r"^glob\s*\((.*)\)$", a, re.S) or re.match(r"^glob\s+(.*)$", a, re.S) or re.match(r"^<([^<>$@]+)>$", a)
        if m:
            a = m.group(1).strip()
            if not a.startswith(("'", '"')):
                return a
    if fam == "node" and a.startswith("`") and a.endswith("`") and len(a) >= 2:
        return None if ("${" in a) else a[1:-1]
    m = _STR_RE.match(a)
    if not m:
        return None
    q = m.group(1); body = q[1:-1]
    if q[0] == '"' and ((fam == "perl" and re.search(r"[$@]", body)) or (fam == "ruby" and ("#{" in body or "#$" in body or "#@" in body)) or (fam == "php" and "$" in body)):
        return None
    if fam == "python" and not re.match(r"^[rRbBuU]{0,2}['\"]", a):
        return None
    return body or None


def _method_target(fam, before):
    """`Path('x').unlink()` / `Pathname.new('x').rmtree`: the literal the method is called on, or None."""
    if fam == "python":
        m = re.search(r"""(?:pathlib\.)?(?:Path|PurePath)\s*\(\s*((?:[rRbBuU]{0,2})(?:'[^']*'|"[^"]*"))\s*\)\s*$""", before)
    elif fam == "ruby":
        m = re.search(r"""Pathname(?:\.new)?\s*\(\s*('[^']*'|"[^"]*")\s*\)\s*$""", before)
    else:
        m = None
    return _literal(m.group(1), fam) if m else None


def _opt_value(args, names):
    for i, x in enumerate(args):
        for n in names:
            if x == n and i + 1 < len(args):
                return args[i + 1]
            if x.startswith(n + "="):
                return x[len(n) + 1:]
            if len(n) == 2 and x.startswith(n) and len(x) > 2 and not x.startswith("--") and n != "-b":
                return x[2:]
    return None

def admin_hit(a, u, ww):
    try:
        return bool(F.admin_seg(a, u, ww))
    except Exception:
        return False


def full_of(s):
    return " ".join(s.raw)


# ---------------------------------------------------------------------------------------------------------------------------------------------
# File tools, MCP, agents, limits
def _file_target(tool, ti):
    if tool == "NotebookEdit":
        return F.sp(ti.get("notebook_path")) or F.sp(ti.get("file_path"))
    return F.sp(ti.get("file_path")) or F.sp(ti.get("path")) or F.sp(ti.get("notebook_path"))


def _mcp_allowed(tool, allow):
    for e in allow or []:
        if not isinstance(e, str) or not e:
            continue
        if tool == e or tool.startswith(e.rstrip("*")) and e.endswith("*") or tool.startswith(e + "__"):
            return True
    return False


def _file_rules(run, tool, ti, post):
    p = _file_target(tool, ti)
    if not p:
        return "", None
    ap = run.real(p)
    if ap is None:
        run.hit("H9", "%s with a path that is not known: %s" % (tool, p))
        return p, None
    if run.protected(ap, "write"):
        run.hit("H5", "%s %s" % (tool, p), subject=p)
    elif not run.scope_ok(ap):
        run.hit("H6", "%s outside the charter scope: %s" % (tool, p), subject=p)
    if run.ctx.deps_mode == "none" and run.inside(ap) and _fold(run.rel(ap)) in run.dep_files:
        run.hit("H3", "%s of a dependency file (deps=none): %s" % (tool, p), subject=p)
    return p, ap


def _limit_rules(run, tool, ti, ap):
    lim = run.ctx.limit
    if not lim:
        return
    if lim == "near":
        if tool in R.AGENT_TOOLS:
            run.hit("H8", "limit_near: no new stage", sub="H8-limit_near")
        return
    label = {"budget": "H8-budget", "time": "H8-time", "budget_unknown": "H8-budget_unknown"}.get(lim, "H8-limits")
    if tool in R.READ_TOOLS or tool in ("WebSearch", "WebFetch", "TodoWrite", "ExitPlanMode", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet"):
        return
    if tool in R.FILE_TOOLS and ap is not None and run.inside(ap) and run.is_record(run.rel(ap)):
        return
    run.hit("H8", "%s limit reached" % lim, sub=label)


def check(event, tool, tool_input, cwd, ctx):
    """The hard stops that apply to one hook call: a list of Stop (empty = nothing to stop)."""
    ti = tool_input if isinstance(tool_input, dict) else {}
    tool = tool if isinstance(tool, str) else ""
    run = _Run(ctx, cwd)
    subject = ""
    try:
        if event == "SubagentStop":
            if ctx.engine_block == "verify_twice":
                run.hit("H7", "the verifier failed twice (verify_twice)")
            subject = "SubagentStop"
        elif event in ("Stop", "UserPromptSubmit"):
            if ctx.limit in ("budget", "time", "budget_unknown"):
                run.hit("H8", "%s limit reached" % ctx.limit, sub={"budget": "H8-budget", "time": "H8-time", "budget_unknown": "H8-budget_unknown"}[ctx.limit])
            subject = event
        elif event in ("PreToolUse", "PostToolUse"):
            post = event == "PostToolUse"
            ap = None
            if tool == "Bash":
                cmd = F.sp(ti.get("command"))
                subject = cmd
                if ti.get("dangerouslyDisableSandbox") is True or str(ti.get("dangerouslyDisableSandbox")).lower() == "true":
                    run.hit("H9", "dangerouslyDisableSandbox=true")
                if not post:
                    if run.cwd and not (run.inside(os.path.realpath(run.cwd)) or run.is_tmp(os.path.realpath(run.cwd))):
                        run.hit("H6", "Bash cwd is outside the worktree: %s" % run.cwd)
                    run.bash(cmd, 0)
                    _limit_rules(run, tool, ti, None)
            elif tool in R.FILE_TOOLS:
                p, ap = _file_rules(run, tool, ti, post)
                subject = p
                if not post:
                    _limit_rules(run, tool, ti, ap)
            elif tool in R.READ_TOOLS:
                if not post:
                    for k in ("file_path", "path", "notebook_path", "glob", "pattern" if tool == "Glob" else "glob"):
                        v = F.sp(ti.get(k))
                        if v and run.sens_word(v):
                            run.hit("H5", "%s %s" % (tool, v), subject=v)
                    subject = F.sp(ti.get("file_path")) or F.sp(ti.get("path")) or F.sp(ti.get("pattern"))
            elif tool in R.AGENT_TOOLS:
                subject = tool + ":" + (ctx.active_cr or "")
                if not post:
                    if ctx.active_cr and run.cr_ends and ctx.active_cr not in run.cr_ends:
                        run.hit("H6", "%s call while the active CR %s is not in the charter ends" % (tool, ctx.active_cr), subject=subject)
                    _limit_rules(run, tool, ti, None)
            elif tool.startswith("mcp__"):
                subject = tool
                if not post:
                    if not _mcp_allowed(tool, ctx.mcp_allow):
                        run.hit("H3", "MCP tool %s is not in autopilot.mcp_allow" % tool, subject=tool)
                    _limit_rules(run, tool, ti, None)
            else:
                subject = tool
                if not post:
                    if tool not in R.ALLOWED_TOOLS:
                        run.hit("H9", "tool not allowed in an autopilot run: %s" % (tool[:60] or "(no name)"), subject=tool or "(none)")
                    _limit_rules(run, tool, ti, None)
        else:
            subject = event
    except Exception as e:                                       # fail closed
        if RAISE:
            raise
        run.hit("H9", "the hard-stop check failed (%s)" % type(e).__name__)
    return _stops(run, subject or "")


def _stops(run, subject):
    out = []; seen = set()
    for rule, exc, subj, sub in run.hits:
        if rule in R.RULE_IDS and rule in DISABLED:
            continue
        if rule in seen:
            continue
        seen.add(rule)
        subj = subject if not subj else subj
        sid = R.new_stop_id()
        label = sub or R.LABELS[rule]
        out.append(Stop(rule, sid, R.DENY.format(label=label, sid=sid, excerpt=exc), label, exc, hashlib.sha256(subj.encode("utf-8", "surrogateescape")).hexdigest()))
    out.sort(key=lambda s: s.rule)
    return out
