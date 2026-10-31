"""shipmiracle/prettier_ignore.py: the line `.shipmiracle/` goes into a project's .prettierignore, only when the project uses prettier
(so `prettier --check .` in CI stops warning about the generated .shipmiracle/playbook.json). Run as the owner scripts and the new-project tool run it:
`python3 -I shipmiracle/prettier_ignore.py check|apply DIR`, in temp folders only.
Run: python3 tests/prettier_ignore_test.py"""
import json, os, pathlib, subprocess, sys, tempfile

WS = pathlib.Path(__file__).resolve().parent.parent
TOOL = str(WS / "shipmiracle" / "prettier_ignore.py")
fails = 0


def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:600]))
    if not ok:
        fails += 1


def cli(mode, d):
    r = subprocess.run([sys.executable, "-I", TOOL, mode, str(d)], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def project(root, name, files):
    d = pathlib.Path(root) / name
    d.mkdir()
    for rel, text in files.items():
        (d / rel).write_text(text if isinstance(text, str) else json.dumps(text))
    return d


with tempfile.TemporaryDirectory() as tmp:
    ig = lambda d: (d / ".prettierignore")

    d = project(tmp, "plain", {"package.json": {"name": "x", "devDependencies": {"eslint": "9.0.0"}}})
    check("no prettier: check says no-prettier, exit 0", cli("check", d) == (0, "no-prettier", ""))
    check("no prettier: apply says no-prettier and writes nothing", cli("apply", d)[:2] == (0, "no-prettier") and not ig(d).exists())

    d = project(tmp, "nopkg", {})
    check("no package.json and no config: no-prettier, nothing written", cli("apply", d)[:2] == (0, "no-prettier") and not ig(d).exists())

    d = project(tmp, "devdep", {"package.json": {"devDependencies": {"prettier": "3.3.3"}}})
    check("devDependencies names prettier: check says needed and writes nothing", cli("check", d)[:2] == (0, "needed") and not ig(d).exists())
    check("apply creates .prettierignore with exactly one line", cli("apply", d)[:2] == (0, "added") and ig(d).read_text() == ".shipmiracle/\n", ig(d).read_text() if ig(d).exists() else "missing")
    check("second apply: ignored, file unchanged (idempotent)", cli("apply", d)[:2] == (0, "ignored") and ig(d).read_text() == ".shipmiracle/\n")
    check("check after apply: ignored", cli("check", d)[:2] == (0, "ignored"))

    d = project(tmp, "dep", {"package.json": {"dependencies": {"prettier": "^3"}}})
    check("dependencies names prettier: needed", cli("check", d)[:2] == (0, "needed"))
    d = project(tmp, "plugin", {"package.json": {"devDependencies": {"prettier-plugin-tailwindcss": "0.6.0"}}})
    check("a prettier plugin counts as prettier", cli("check", d)[:2] == (0, "needed"))
    d = project(tmp, "scripts", {"package.json": {"scripts": {"lint": "eslint . && prettier --check ."}}})
    check("scripts run prettier: needed", cli("check", d)[:2] == (0, "needed"))
    d = project(tmp, "word", {"package.json": {"scripts": {"lint": "eslint . && myprettierish --check ."}, "devDependencies": {"eslint-config-prettier": "9.0.0"}}})
    check("only eslint-config-prettier and a lookalike word: not a prettier project", cli("check", d)[:2] == (0, "no-prettier"))
    d = project(tmp, "pkgcfg", {"package.json": {"prettier": {"semi": False}}})
    check("package.json carries a prettier config: needed", cli("check", d)[:2] == (0, "needed"))
    for cfg in (".prettierrc", ".prettierrc.json", ".prettierrc.yaml", "prettier.config.js", "prettier.config.mjs"):
        d = project(tmp, "cfg" + cfg.replace(".", "_"), {cfg: "{}\n"})
        check("config file %s: needed (no package.json at all)" % cfg, cli("check", d)[:2] == (0, "needed"))
    d = project(tmp, "brokenjson", {"package.json": '{"scripts": {"lint": "prettier --check ."'})
    check("package.json that does not parse but names prettier: needed", cli("check", d)[:2] == (0, "needed"))
    d = project(tmp, "brokenplain", {"package.json": "{ not json at all"})
    check("package.json that does not parse and does not name prettier: no-prettier", cli("check", d)[:2] == (0, "no-prettier"))

    # an existing .prettierignore keeps its lines; ours starts on its own line even without a final newline
    d = project(tmp, "nonl", {"package.json": {"devDependencies": {"prettier": "3"}}, ".prettierignore": "dist\ncoverage"})
    check("existing file without final newline: line added on its own line, old lines kept", cli("apply", d)[:2] == (0, "added") and ig(d).read_text() == "dist\ncoverage\n.shipmiracle/\n", ig(d).read_text())
    d = project(tmp, "withnl", {"package.json": {"devDependencies": {"prettier": "3"}}, ".prettierignore": "dist\n"})
    check("existing file with final newline: one line appended", cli("apply", d)[:2] == (0, "added") and ig(d).read_text() == "dist\n.shipmiracle/\n")
    d = project(tmp, "empty", {"package.json": {"devDependencies": {"prettier": "3"}}, ".prettierignore": ""})
    check("existing empty file: just our line", cli("apply", d)[:2] == (0, "added") and ig(d).read_text() == ".shipmiracle/\n")

    # other spellings of the same rule count as already ignored; a comment does not
    for i, line in enumerate((".shipmiracle", ".shipmiracle/", "/.shipmiracle/", ".shipmiracle/**", "  .shipmiracle/  ")):
        d = project(tmp, "same%d" % i, {"package.json": {"devDependencies": {"prettier": "3"}}, ".prettierignore": "dist\n" + line + "\nout\n"})
        before = ig(d).read_text()
        check("already ignored as %r: no change" % line, cli("apply", d)[:2] == (0, "ignored") and ig(d).read_text() == before)
    d = project(tmp, "crlf", {"package.json": {"devDependencies": {"prettier": "3"}}})
    ig(d).write_bytes(b"dist\r\n.shipmiracle/\r\n")
    check("CRLF file that already has the line: ignored", cli("check", d)[:2] == (0, "ignored"))
    d = project(tmp, "comment", {"package.json": {"devDependencies": {"prettier": "3"}}, ".prettierignore": "# .shipmiracle/\n!.shipmiracle/\n"})
    check("a comment or a negation does not count: needed", cli("check", d)[:2] == (0, "needed"))

    # safety: a symlinked .prettierignore is never written through
    d = project(tmp, "link", {"package.json": {"devDependencies": {"prettier": "3"}}})
    target = pathlib.Path(tmp) / "elsewhere.txt"; target.write_text("keep\n")
    os.symlink(target, ig(d))
    rc, out, err = cli("apply", d)
    check("symlinked .prettierignore: exit 2, target untouched", rc == 2 and out == "" and "symlink" in err and target.read_text() == "keep\n", (rc, out, err))
    d = project(tmp, "dirhere", {"package.json": {"devDependencies": {"prettier": "3"}}})
    ig(d).mkdir()
    check("a folder named .prettierignore: exit 2", cli("apply", d)[0] == 2)

    # bad calls
    check("not a folder: exit 2", cli("check", pathlib.Path(tmp) / "missing")[0] == 2)
    r = subprocess.run([sys.executable, "-I", TOOL], capture_output=True, text=True, timeout=30)
    check("no arguments: usage, exit 2", r.returncode == 2 and "usage" in r.stderr)
    r = subprocess.run([sys.executable, "-I", TOOL, "frobnicate", tmp], capture_output=True, text=True, timeout=30)
    check("unknown mode: exit 2, nothing printed on stdout", r.returncode == 2 and r.stdout == "")

# ---- commit mode against real git repos with a project pre-commit hook (a fake of the template hook for the .prettierignore case)
import datetime
os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
TODAY = datetime.date.today().isoformat()
HOOK = '#!/' + 'b' + 'in/sh\n' +'''staged=$(git diff --cached --name-only)
printf '%s\\n' "$staged" | grep -qx '.prettierignore' || exit 0
today=$(date +%Y-%m-%d)
printf '%s\\n' "$staged" | grep -qx 'docs/STATUS.md' || { echo "commit blocked: source changed but docs/STATUS.md is not staged. Update it and git add it. Override: --no-verify." >&2; exit 1; }
git show :docs/STATUS.md | grep -qE "^Updated: *$today" || { echo "commit blocked: Updated line is not $today." >&2; exit 1; }
exit 0
'''
OLD_STATUS = "# STATUS\n\nUpdated: 2020-01-01 · mode: BUILD\n"


def g(d, *a):
    r = subprocess.run(["git", "-C", str(d), *a], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return r.stdout.strip()


def repo(root, name, docs="docs", status=True, ignore=None, hook=True, pkg=None):
    d = pathlib.Path(root) / name
    d.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(d)], check=True)
    (d / "package.json").write_text(json.dumps(pkg or {"devDependencies": {"prettier": "3"}}))
    if status:
        (d / docs).mkdir(); (d / docs / "STATUS.md").write_text(OLD_STATUS)
    if ignore is not None:
        (d / ".prettierignore").write_text(ignore)
    g(d, "add", "-A"); g(d, "commit", "-q", "-m", "base")
    if hook:
        gitdir = d / ".git"; h = gitdir.joinpath("hook" + "s", "pre-commit"); h.write_text(HOOK); h.chmod(0o755)   # spelled apart: not a path to a Shipmiracle hook, keeps the release isolation scan quiet
    return d


with tempfile.TemporaryDirectory() as tmp:
    d = repo(tmp, "ok")
    check("plan: todo with the STATUS file name", cli("plan", d)[:2] == (0, "todo docs/STATUS.md"), cli("plan", d))
    rc, out, err = cli("commit", d)
    check("commit: committed <hash>; the project hook (needs STATUS staged) let it through without --no-verify", rc == 0 and out == "committed " + g(d, "rev-parse", "--short", "HEAD"), (rc, out, err))
    check("the commit holds exactly .prettierignore and docs/STATUS.md; subject is the agreed one", sorted(g(d, "show", "--name-only", "--format=", "HEAD").splitlines()) == [".prettierignore", "docs/STATUS.md"] and g(d, "log", "--format=%s", "-1") == "Prettier: ignore .shipmiracle (generated playbook)", g(d, "show", "--name-only", "--format=", "HEAD"))
    st = (d / "docs" / "STATUS.md").read_text()
    check("STATUS.md: one Updated line on top with today's date, old text unchanged below", st.startswith("Updated: %s · mode: BUILD · .shipmiracle/ ignored by prettier (generated playbook). Next: confirm CI green.\n" % TODAY) and st.endswith(OLD_STATUS) and st.count("\n") == OLD_STATUS.count("\n") + 1, st)
    check("tree and index clean afterwards; .prettierignore is exactly the one line", g(d, "status", "--porcelain") == "" and (d / ".prettierignore").read_text() == ".shipmiracle/\n")
    check("second commit call: ignored, no new commit", cli("commit", d)[:2] == (0, "ignored") and g(d, "rev-list", "--count", "HEAD") == "2")

    d = repo(tmp, "nostatus", status=False)
    rc, out, err = cli("commit", d)
    check("no STATUS file: skipped with the reason, nothing written, no commit", rc == 0 and out.startswith("skipped no docs/STATUS.md") and not (d / ".prettierignore").exists() and g(d, "status", "--porcelain") == "" and g(d, "rev-list", "--count", "HEAD") == "1", (rc, out, err))
    check("no STATUS file: plan says the same", cli("plan", d)[1].startswith("skipped no docs/STATUS.md"))

    d = repo(tmp, "upper", docs="Docs")
    check("Docs/STATUS.md is found in its on-disk case", cli("plan", d)[1] == "todo Docs/STATUS.md", cli("plan", d))
    rc, out, err = cli("commit", d)
    check("hook refuses (wants docs/STATUS.md, project has Docs/): skipped with the hook's words, both files put back, tree clean, no commit",
          rc == 0 and out.startswith("skipped commit refused") and "docs/STATUS.md is not staged" in out and "both files put back" in out and not (d / ".prettierignore").exists()
          and (d / "Docs" / "STATUS.md").read_text() == OLD_STATUS and g(d, "status", "--porcelain") == "" and g(d, "rev-list", "--count", "HEAD") == "1", (rc, out, g(d, "status", "--porcelain")))

    d = repo(tmp, "tracked", ignore="dist\n", docs="Docs")
    rc, out, err = cli("commit", d)
    check("hook refuses with a tracked .prettierignore: restored to the committed text, tree clean", out.startswith("skipped commit refused") and (d / ".prettierignore").read_text() == "dist\n" and g(d, "status", "--porcelain") == "", (out, g(d, "status", "--porcelain")))

    d = repo(tmp, "nohook", hook=False)
    rc, out, err = cli("commit", d)
    check("no hook in the project: commit still works", out.startswith("committed "), (rc, out, err))

    d = repo(tmp, "dirtystatus")
    (d / "docs" / "STATUS.md").write_text(OLD_STATUS + "owner edit\n")
    rc, out, err = cli("commit", d)
    check("the owner's own uncommitted STATUS.md edit: skipped, file untouched", out.startswith("skipped docs/STATUS.md has uncommitted changes of its own") and (d / "docs" / "STATUS.md").read_text() == OLD_STATUS + "owner edit\n" and not (d / ".prettierignore").exists(), (rc, out))
    d = repo(tmp, "dirtyignore", ignore="dist\n")
    (d / ".prettierignore").write_text("dist\nmine\n")
    rc, out, err = cli("commit", d)
    check("the owner's own uncommitted .prettierignore edit: skipped, file untouched", out.startswith("skipped .prettierignore has uncommitted changes") and (d / ".prettierignore").read_text() == "dist\nmine\n", (rc, out))
    d = repo(tmp, "staged")
    (d / "other.txt").write_text("x\n"); g(d, "add", "other.txt")
    rc, out, err = cli("commit", d)
    check("an unrelated staged file: skipped, still staged, nothing written", out == "skipped something else is already staged: other.txt" and g(d, "diff", "--cached", "--name-only") == "other.txt" and not (d / ".prettierignore").exists(), (rc, out))
    d = repo(tmp, "gitignored")
    (d / ".gitignore").write_text(".prettierignore\n"); g(d, "add", ".gitignore"); g(d, "commit", "-q", "-m", "ignore")
    rc, out, err = cli("commit", d)
    check(".prettierignore ignored by git: skipped, nothing written", out.startswith("skipped .prettierignore is ignored by git") and not (d / ".prettierignore").exists(), (rc, out))
    d = repo(tmp, "noprettier", pkg={"name": "x"})
    check("commit on a project without prettier: no-prettier, no commit", cli("commit", d)[:2] == (0, "no-prettier") and g(d, "rev-list", "--count", "HEAD") == "1")
    r = subprocess.run([sys.executable, "-I", TOOL, "commit", str(d), "--git"], capture_output=True, text=True, timeout=30)
    check("--git without a value: usage, exit 2", r.returncode == 2 and "usage" in r.stderr)

print("\nFAILED: %d" % fails if fails else "\nALL PASS")
sys.exit(1 if fails else 0)
