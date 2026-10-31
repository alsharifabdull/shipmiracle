#!/usr/bin/env python3
"""Keep the generated .shipmiracle/ folder out of a project's prettier checks.

Why: `shipm playbook set` writes .shipmiracle/playbook.json (compact JSON). A project whose CI runs `prettier --check .`
then fails with "[warn] .shipmiracle/playbook.json  Code style issues found". The fix is one line in the project's
.prettierignore, and only for projects that use prettier.

The projects' pre-commit hook (apply-template) refuses a commit with source files unless the STATUS file is staged with today's
"Updated:" line, and .prettierignore counts as source. So the commit holds two files: .prettierignore and the project's STATUS file
(docs/STATUS.md or Docs/STATUS.md, the case that is on disk) with one Updated line put on top. Never --no-verify. A project without
a STATUS file is skipped and reported, nothing is written.

Stdlib only and standalone, so the owner scripts and bin/new-project can run it as a file (all print ONE line, exit 0):
  python3 -I prettier_ignore.py check  DIR              no-prettier | ignored | needed          (nothing is written; no git)
  python3 -I prettier_ignore.py plan   DIR [--git GIT]  no-prettier | ignored | todo STATUSFILE | skipped REASON      (read-only)
  python3 -I prettier_ignore.py commit DIR [--git GIT]  no-prettier | ignored | committed HASH | skipped REASON
  python3 -I prettier_ignore.py apply  DIR              no-prettier | ignored | added           (only writes .prettierignore; no git, no STATUS)
`commit` re-runs the plan, writes both files, then `git add` + `git commit -- <those two paths>`; when the commit is refused (the hook) it puts
both files back (git restore; a .prettierignore it created is removed) and says skipped. Exit 2 and a message on stderr for a bad call or a file
that cannot be handled safely (.prettierignore is a symlink or not a regular file)."""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys

LINE = ".shipmiracle/"
MESSAGE = "Prettier: ignore .shipmiracle (generated playbook)"
STATUS_LINE = "Updated: %s · mode: BUILD · .shipmiracle/ ignored by prettier (generated playbook). Next: confirm CI green."
IGNORE_FILE = ".prettierignore"
# every spelling of "ignore the .shipmiracle folder" that prettier (gitignore syntax) understands; none of them needs another line
_SAME = {".shipmiracle", ".shipmiracle/", "/.shipmiracle", "/.shipmiracle/", ".shipmiracle/**", "/.shipmiracle/**", "**/.shipmiracle", "**/.shipmiracle/"}
_DEP_SECTIONS = ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")
_WORD = re.compile(r"(?<![A-Za-z0-9_-])prettier(?![A-Za-z0-9_])")
_MAX_JSON = 4 * 1024 * 1024


class IgnoreError(Exception):
    pass


def _package_uses_prettier(path: str) -> bool:
    try:
        if os.path.getsize(path) > _MAX_JSON:
            return False
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return False
    text = raw.decode("utf-8", "replace")
    try:
        data = json.loads(text)
    except ValueError:
        return bool(_WORD.search(text))          # a package.json that does not parse: a plain word match is the best guess
    if not isinstance(data, dict):
        return False
    for sec in _DEP_SECTIONS:
        deps = data.get(sec)
        if isinstance(deps, dict) and any(isinstance(k, str) and (k == "prettier" or k.startswith(("prettier-", "@prettier/"))) for k in deps):
            return True
    if "prettier" in data:                       # package.json "prettier": {...} is prettier's own config
        return True
    scripts = data.get("scripts")
    if isinstance(scripts, dict) and any(isinstance(v, str) and _WORD.search(v) for v in scripts.values()):
        return True
    return False


def uses_prettier(project: str) -> bool:
    """package.json names prettier in its dependencies or scripts (or carries a prettier config), or a prettier config file sits in the project root."""
    try:
        names = os.listdir(project)
    except OSError as e:
        raise IgnoreError("cannot read %s: %s" % (project, e.strerror or e))
    for n in names:
        if (n == ".prettierrc" or n.startswith(".prettierrc.") or n.startswith("prettier.config.")) and os.path.isfile(os.path.join(project, n)):
            return True
    return "package.json" in names and _package_uses_prettier(os.path.join(project, "package.json"))


def _already_ignored(data: bytes) -> bool:
    for raw in data.decode("utf-8", "replace").splitlines():
        if raw.strip() in _SAME:
            return True
    return False


def check(project: str) -> str:
    if not os.path.isdir(project):
        raise IgnoreError("not a folder: %s" % project)
    if not uses_prettier(project):
        return "no-prettier"
    path = os.path.join(project, IGNORE_FILE)
    if os.path.islink(path) or (os.path.lexists(path) and not os.path.isfile(path)):
        raise IgnoreError("%s is a symlink or not a regular file; not touching it" % path)
    data = b""
    if os.path.exists(path):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as e:
            raise IgnoreError("cannot read %s: %s" % (path, e.strerror or e))
    return "ignored" if _already_ignored(data) else "needed"


def apply(project: str) -> str:
    """Write the one line into .prettierignore (no git, no STATUS file)."""
    state = check(project)
    if state != "needed":
        return state
    path = os.path.join(project, IGNORE_FILE)
    add = b""
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, "rb") as f:
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b"\n":
                add = b"\n"                      # the file had no final newline: ours must start on its own line
    add += LINE.encode("ascii") + b"\n"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o644)
        try:
            os.write(fd, add)
        finally:
            os.close(fd)
    except OSError as e:
        raise IgnoreError("cannot write %s: %s" % (path, e.strerror or e))
    return "added"


def status_file(project: str):
    """The project's STATUS file as it is on disk ('docs/STATUS.md' or 'Docs/STATUS.md'); None when there is none (or it is a symlink)."""
    names = os.listdir(project)
    for dn in ("docs", "Docs"):
        d = os.path.join(project, dn)
        if dn in names and os.path.isdir(d) and not os.path.islink(d) and "STATUS.md" in os.listdir(d):
            f = os.path.join(d, "STATUS.md")
            if os.path.isfile(f) and not os.path.islink(f):
                return dn + "/STATUS.md"
    return None


def _git(git: str, project: str, *args: str):
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")}
    try:
        r = subprocess.run([git, "-C", project] + list(args), capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120, env=env)
    except (OSError, subprocess.SubprocessError) as e:
        return 127, "", str(e)
    return r.returncode, r.stdout, r.stderr


def _first_line(text: str, n: int = 160) -> str:
    for ln in text.replace("\r", "\n").splitlines():
        if ln.strip():
            return ln.strip()[:n]
    return ""


def plan(project: str, git: str = "git"):
    """(word, detail): no-prettier | ignored | todo STATUSFILE | skipped REASON. Reads only."""
    state = check(project)
    if state != "needed":
        return state, ""
    sp = status_file(project)
    if sp is None:
        return "skipped", "no docs/STATUS.md (or Docs/STATUS.md): the commit hook of the project needs it, nothing was written"
    paths = [IGNORE_FILE, sp]
    if _git(git, project, "rev-parse", "--git-dir")[0] != 0:
        return "skipped", "not a git repository"
    rc, out, err = _git(git, project, "status", "--porcelain", "--", *paths)
    if rc != 0:
        return "skipped", "git status failed: %s" % _first_line(err)
    if out.strip():
        return "skipped", "%s has uncommitted changes of its own; left alone" % out.splitlines()[0][3:]
    for pth in paths:
        if _git(git, project, "check-ignore", "-q", "--", pth)[0] == 0:
            return "skipped", "%s is ignored by git; left alone" % pth
    rc, out, err = _git(git, project, "diff", "--cached", "--name-only")
    if rc != 0:
        return "skipped", "git diff --cached failed: %s" % _first_line(err)
    if out.strip():
        return "skipped", "something else is already staged: %s" % ", ".join(out.split()[:3])
    return "todo", sp


def _prepend_status(project: str, sp: str) -> None:
    path = os.path.join(project, sp)
    with open(path, "rb") as f:
        old = f.read()
    line = (STATUS_LINE % datetime.date.today().isoformat()).encode("utf-8") + b"\n"
    with open(path, "wb") as f:
        f.write(line + old)


def commit(project: str, git: str = "git"):
    word, sp = plan(project, git)
    if word != "todo":
        return word, sp
    paths = [IGNORE_FILE, sp]
    had_ignore = _git(git, project, "cat-file", "-e", "HEAD:" + IGNORE_FILE)[0] == 0
    apply(project)
    _prepend_status(project, sp)
    rc, out, err = _git(git, project, "add", "-A", "--", *paths)
    if rc == 0:
        rc, out, err = _git(git, project, "commit", "-q", "-m", MESSAGE, "--", *paths)
    if rc != 0:
        why = _first_line(err) or _first_line(out) or "git exit %d" % rc
        bad = []
        if had_ignore:
            ok = _git(git, project, "restore", "--source=HEAD", "--staged", "--worktree", "--", IGNORE_FILE)[0] == 0
        else:
            ok = _git(git, project, "restore", "--staged", "--", IGNORE_FILE)[0] == 0
            try:
                os.remove(os.path.join(project, IGNORE_FILE))
            except OSError:
                ok = False
        if not ok:
            bad.append(IGNORE_FILE)
        if _git(git, project, "restore", "--source=HEAD", "--staged", "--worktree", "--", sp)[0] != 0:
            bad.append(sp)
        tail = "; COULD NOT put back %s: check git status" % " and ".join(bad) if bad else "; both files put back"
        return "skipped", "commit refused (%s)%s" % (why, tail)
    rc, out, err = _git(git, project, "rev-parse", "--short", "HEAD")
    return "committed", out.strip() or "(unknown)"


def main(argv: list) -> int:
    args = list(argv[1:])
    git = "git"
    if "--git" in args:
        i = args.index("--git")
        if i + 1 >= len(args) or not args[i + 1]:
            args = []
        else:
            git = args[i + 1]
            del args[i:i + 2]
    if len(args) != 2 or args[0] not in ("check", "plan", "commit", "apply") or not args[1]:
        sys.stderr.write("usage: prettier_ignore.py check|plan|commit|apply PROJECT_DIR [--git GIT]\n")
        return 2
    mode, project = args
    try:
        if mode == "check":
            res = (check(project), "")
        elif mode == "apply":
            res = (apply(project), "")
        elif mode == "plan":
            res = plan(project, git)
        else:
            res = commit(project, git)
    except IgnoreError as e:
        sys.stderr.write("prettier_ignore: %s\n" % e)
        return 2
    print((res[0] + " " + " ".join(str(res[1]).split())).strip())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
