#!/usr/bin/env python3
"""bin/new-project in a temp HOME: --about fills Purpose, default "(fill in)", bad input refused.
Run: python3 tests/new_project_test.py"""
import json, os, pathlib, pwd, subprocess, sys, tempfile

WS = pathlib.Path(__file__).resolve().parent.parent
TOOL = str(WS / "bin" / "new-project")
# no background gc / maintenance after a commit: it would write into a temp folder while the test removes it
os.environ.update(GIT_CONFIG_COUNT="2", GIT_CONFIG_KEY_0="gc.auto", GIT_CONFIG_VALUE_0="0", GIT_CONFIG_KEY_1="maintenance.auto", GIT_CONFIG_VALUE_1="false")
fails = 0

def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " " + str(info)))
    if not ok: fails += 1

with tempfile.TemporaryDirectory() as home:
    h = pathlib.Path(home)
    (h / "Developer").mkdir()
    env = dict(os.environ, HOME=home, GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@example.com",
               GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@example.com", GIT_CONFIG_GLOBAL=os.devnull,
               SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=home, SHIPMIRACLE_DEV=home + "/Developer", SHIPMIRACLE_CONFIG=home + "/cfg", SHIPMIRACLE_STATE=home + "/state")   # Shipmiracle reads and writes only the temp folders
    env.pop("CLAUDECODE", None)
    def run(*a):
        return subprocess.run([TOOL, *a, "--no-github", "--no-open"], env=env, capture_output=True, text=True, timeout=120)
    purpose = lambda n: next((l for l in (h/"Developer"/n/"CLAUDE.md").read_text().splitlines() if l.startswith("- Purpose:")), None)

    r = run("with-about", "--type", "python", "--about", "A tool for\ttracking\x07 books\nand more")
    check("create with --about succeeds", r.returncode == 0, r.stderr)
    check("Purpose filled, control characters turned into spaces", purpose("with-about") == "- Purpose: A tool for tracking books and more", purpose("with-about"))
    check("no placeholder left", "{{" not in (h/"Developer"/"with-about"/"CLAUDE.md").read_text())
    check("first commit made", subprocess.run(["git", "-C", str(h/"Developer"/"with-about"), "log", "--oneline"], capture_output=True, text=True, env=env).stdout.strip() != "")
    fc = h/"Developer"/"with-about"/".claude"/"commands"/"feature.md"
    check("new project has the /feature command with EnterPlanMode", fc.is_file() and "EnterPlanMode" in fc.read_text())

    ag = h/"Developer"/"with-about"/".claude"/"agents"
    masters = {p.name: p.read_bytes() for p in (WS/"agents"/"claude").glob("*.md")}
    check("legacy layout (default): the ten new-name masters are copied into the project, byte for byte, and no old name",
          len(masters) == 10 and {p.name: p.read_bytes() for p in ag.glob("*.md")} == masters, sorted(p.name for p in ag.glob("*.md")))
    reg = json.loads((h/"cfg"/"registry.json").read_text()) if (h/"cfg"/"registry.json").exists() else {"projects": {}}
    ents = [e for e in reg["projects"].values() if e.get("name") == "with-about"]
    check("new-project writes a registry entry (team on) for the project", len(ents) == 1 and ents[0]["team"] == "on" and ents[0]["agents"] == {}, ents)
    r = subprocess.run([sys.executable, str(WS/"bin"/"shipm"), "config", "set", "agents.layout", "userlevel"], env=env, capture_output=True, text=True)
    check("config set agents.layout userlevel (temp config)", r.returncode == 0, r.stderr)
    r = run("user-level", "--type", "python")
    uag = h/"Developer"/"user-level"/".claude"/"agents"
    check("userlevel layout: new-project copies no agents", r.returncode == 0 and not (uag.exists() and any(uag.iterdir())), r.stderr)
    ents = [e for e in json.loads((h/"cfg"/"registry.json").read_text())["projects"].values() if e.get("name") == "user-level"]
    check("userlevel layout: the registry entry exists (the gate activates by it)", len(ents) == 1 and ents[0]["team"] == "on", ents)
    subprocess.run([sys.executable, str(WS/"bin"/"shipm"), "config", "set", "agents.layout", "legacy"], env=env, capture_output=True, text=True)

    r = run("no-about", "--type", "notes")
    check("create without --about succeeds", r.returncode == 0, r.stderr)
    check('Purpose is "(fill in)" without --about', purpose("no-about") == "- Purpose: (fill in)", purpose("no-about"))

    r = run("long-about", "--about", "x" * 300)
    check("about is cut to 140 characters", r.returncode == 0 and purpose("long-about") == "- Purpose: " + "x" * 140, purpose("long-about"))

    r = run("blank-about", "--about", " \t\n ")
    check("blank about falls back to (fill in)", purpose("blank-about") == "- Purpose: (fill in)", purpose("blank-about"))

    r = run("Tidy Me!", "--about", "quote ' and \" and $(rm -rf x)")
    check("name is tidied, about with quotes kept as plain text", r.returncode == 0 and purpose("tidy-me") == "- Purpose: quote ' and \" and $(rm -rf x)", purpose("tidy-me") if (h/"Developer"/"tidy-me").exists() else r.stderr)

    before = sorted(p.name for p in (h/"Developer").iterdir())
    r = run("bad-type", "--type", "nonsense")
    check("unknown type refused (exit 2), nothing created", r.returncode == 2 and "unknown type" in r.stderr and sorted(p.name for p in (h/"Developer").iterdir()) == before, r.stderr)
    r = run("!!!")
    check("name with no letter or digit refused", r.returncode == 2 and "at least one letter" in r.stderr, r.stderr)
    r = subprocess.run([TOOL, "--no-github", "--no-open"], env=env, capture_output=True, text=True)
    check("no name refused (usage)", r.returncode == 2 and "usage" in r.stderr, r.stderr)
    r = subprocess.run([TOOL, "x", "--about"], env=env, capture_output=True, text=True)
    check("--about without a value refused", r.returncode == 2, r.stderr)

    (h/"Developer"/"with-about"/"CLAUDE.md").write_text((h/"Developer"/"with-about"/"CLAUDE.md").read_text() + "\nEDIT\n")
    r = run("with-about", "--about", "other")
    check("re-run keeps the project's own edits and Purpose", r.returncode == 0 and "EDIT" in (h/"Developer"/"with-about"/"CLAUDE.md").read_text() and purpose("with-about").endswith("and more"), r.stderr)

    # opening: a fake `code` on PATH records its argv
    fb = h / "fakebin"; fb.mkdir()
    (fb / "code").write_text(f'#!/bin/sh\necho "$@" >> {h}/code.log\n'); (fb / "code").chmod(0o755)
    env["PATH"] = str(fb) + os.pathsep + env["PATH"]
    def run_raw(*a):
        return subprocess.run([TOOL, *a, "--no-github"], env=env, capture_output=True, text=True, timeout=120)
    r = run_raw("open-default")
    check("default opens no window (code not called) and says where to open it", r.returncode == 0 and not (h/"code.log").exists() and "Open it from the Shipmiracle panel: it is already listed there" in r.stdout, r.stdout + r.stderr)
    r = run_raw("open-alias", "--no-open")
    check("--no-open accepted, code not called", r.returncode == 0 and not (h/"code.log").exists(), r.stderr)
    r = run_raw("open-explicit", "--open")
    check("--open runs code -r <dir>", r.returncode == 0 and (h/"code.log").exists() and (h/"code.log").read_text().strip() == "-r " + str(h/"Developer"/"open-explicit"), (h/"code.log").read_text() if (h/"code.log").exists() else r.stderr)

# ---- a fake HOME without SHIPMIRACLE_TEST must not write the real registry (Shipmiracle ignores $HOME)
with tempfile.TemporaryDirectory() as home:
    h = pathlib.Path(home); (h / "Developer").mkdir()
    real_reg = pathlib.Path(os.path.expanduser("~")) / ".config" / "shipmiracle" / "registry.json"
    before = real_reg.stat().st_mtime_ns if real_reg.exists() else None
    env = dict(os.environ, HOME=home, GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@example.com", GIT_CONFIG_GLOBAL=os.devnull)
    for k in ("SHIPMIRACLE_TEST", "SHIPMIRACLE_HOME", "SHIPMIRACLE_CONFIG", "SHIPMIRACLE_STATE", "SHIPMIRACLE_DEV", "CLAUDECODE"): env.pop(k, None)
    r = subprocess.run([TOOL, "fakehome", "--type", "notes", "--no-github", "--no-open"], env=env, capture_output=True, text=True, timeout=120)
    after = real_reg.stat().st_mtime_ns if real_reg.exists() else None
    check("fake HOME, no SHIPMIRACLE_TEST: the real registry is not touched and the note says so", r.returncode == 0 and before == after and "project registry not updated" in r.stdout, (r.stdout[-200:], before, after))

# ---- an existing unmigrated folder (AGENTS.md rules, no managed block): CLAUDE.md and docs/standards stay as they are
with tempfile.TemporaryDirectory() as home:
    h = pathlib.Path(home); old = h / "Developer" / "legacyproj"; old.mkdir(parents=True)
    (old / "AGENTS.md").write_text("# rules\nStack rules \u2014 Python\n"); (old / "CLAUDE.md").write_text("@AGENTS.md\nmy notes\n")
    (old / "docs" / "standards").mkdir(parents=True); (old / "docs" / "standards" / "team.md").write_text("MINE\n")
    env = dict(os.environ, HOME=home, GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@example.com", GIT_CONFIG_GLOBAL=os.devnull)
    for k in ("SHIPMIRACLE_TEST", "SHIPMIRACLE_HOME", "SHIPMIRACLE_CONFIG", "SHIPMIRACLE_STATE", "SHIPMIRACLE_DEV", "CLAUDECODE"): env.pop(k, None)
    r = subprocess.run([TOOL, "legacyproj", "--type", "python", "--no-github", "--no-open"], env=env, capture_output=True, text=True, timeout=120)
    check("existing unmigrated project: CLAUDE.md untouched (no fragment appended, no block added)", (old / "CLAUDE.md").read_text() == "@AGENTS.md\nmy notes\n" and not (old / "CLAUDE.fragment.md").exists(), (old / "CLAUDE.md").read_text())
    check("existing unmigrated project: docs/standards/ not overwritten", (old / "docs" / "standards" / "team.md").read_text() == "MINE\n", r.stderr[-200:])

# ---- guard: under a fake HOME without SHIPMIRACLE_TEST, new-project and delete-project never write the real registry
with tempfile.TemporaryDirectory() as home:
    h = pathlib.Path(home); (h / "Developer").mkdir()
    realcfg = pathlib.Path(pwd.getpwuid(os.getuid()).pw_dir) / ".config" / "shipmiracle"
    def canary():
        return [(str(p), p.stat().st_mtime_ns) for p in [realcfg] + (sorted(realcfg.iterdir()) if realcfg.is_dir() else []) if p.exists()]
    before = canary()
    env = dict(os.environ, HOME=home, GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@example.com", GIT_CONFIG_GLOBAL=os.devnull)
    for k in ("SHIPMIRACLE_TEST", "SHIPMIRACLE_HOME", "SHIPMIRACLE_CONFIG", "SHIPMIRACLE_STATE", "SHIPMIRACLE_DEV", "CLAUDECODE"): env.pop(k, None)
    r1 = subprocess.run([TOOL, "canary1", "--type", "notes", "--no-github", "--no-open"], env=env, capture_output=True, text=True, timeout=120)
    DEL = WS / "bin" / "delete-project"          # the delete tool is owner-only: not part of the public export
    r2 = subprocess.run([str(DEL), "canary1", "--where", "mac", "--yes"], env=env, capture_output=True, text=True, timeout=120) if DEL.exists() else None
    check("fake HOME, no SHIPMIRACLE_TEST: new-project then delete-project leave the real ~/.config/shipmiracle exactly as it was", r1.returncode == 0 and (r2 is None or r2.returncode == 0) and canary() == before, (before, canary(), r1.stderr[-150:], r2.stdout[-150:] if r2 else ""))

# ---- GitHub outcome: exit 0 only when the repo exists and the push worked, or --no-github
with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as fake:
    h = pathlib.Path(home); (h / "Developer").mkdir()
    gh = pathlib.Path(fake) / "gh"
    log = pathlib.Path(fake) / "gh.log"
    def make_gh(create_ok, auth_ok=True):
        gh.write_text('#!/bin/bash\necho "$@" >> %s\n'
                      'if [ "$1" = auth ]; then exit %d; fi\n'
                      'if [ "$2" = create ]; then %s; fi\nexit 0\n' % (log, 0 if auth_ok else 1,
                      "exit 0" if create_ok else 'echo "GraphQL: Name already exists on this account (createRepository)" >&2; exit 1'))
        gh.chmod(0o755)
    env = dict(os.environ, HOME=home, PATH=fake + ":" + os.environ["PATH"], GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@example.com",
               GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@example.com", GIT_CONFIG_GLOBAL=os.devnull)
    for k in ("SHIPMIRACLE_TEST", "SHIPMIRACLE_HOME", "SHIPMIRACLE_CONFIG", "SHIPMIRACLE_STATE", "SHIPMIRACLE_DEV", "SHIPMIRACLE_WS", "CLAUDECODE"): env.pop(k, None)   # fake HOME only: the playbook step then only prints a note
    def run2(*a):
        return subprocess.run([TOOL, *a], env=env, capture_output=True, text=True, timeout=120)
    make_gh(False)
    r = run2("gh-fail", "--about", "Books")
    check("gh fails: exit 3, one GitHub: FAILED line on stderr (not stdout)", r.returncode == 3 and "GitHub: FAILED - GraphQL: Name already exists on this account (createRepository)" in r.stderr and "FAILED" not in r.stdout, (r.returncode, r.stderr, r.stdout))
    check("gh fails: the local project is complete (files, commit, Project ready)", (h/"Developer"/"gh-fail"/"CLAUDE.md").exists() and "Project ready" in r.stdout and subprocess.run(["git", "-C", str(h/"Developer"/"gh-fail"), "log", "--oneline"], capture_output=True, text=True, env=env).stdout.strip() != "")
    make_gh(True)
    r = run2("gh-ok", "--about", "Books")
    check("gh succeeds: exit 0, nothing on stderr", r.returncode == 0 and r.stderr.strip() == "" and "created and pushed" in r.stdout, (r.returncode, r.stderr))
    check("gh create got --description with the about text", "--description Books" in log.read_text(), log.read_text())
    r = run2("gh-off", "--no-github")
    check("--no-github: exit 0, gh never called for it", r.returncode == 0 and r.stderr.strip() == "", (r.returncode, r.stderr))
    make_gh(True, auth_ok=False)
    r = run2("gh-noauth")
    check("gh not logged in: exit 3 with GitHub: skipped on stderr", r.returncode == 3 and "GitHub: skipped - not logged in" in r.stderr, (r.returncode, r.stderr))
    gh.unlink()
    r = subprocess.run([TOOL, "gh-missing"], env=dict(env, PATH="/usr/bin:/bin:/usr/sbin:/sbin"), capture_output=True, text=True, timeout=120)
    check("gh missing (if not installed in /usr/bin): exit 3 skipped", r.returncode == 3 and "GitHub: skipped" in r.stderr or os.path.exists("/usr/bin/gh"), (r.returncode, r.stderr))

# ---- about sanitising for CLAUDE.md, and the name rule shared with the panel
with tempfile.TemporaryDirectory() as home:
    h = pathlib.Path(home); (h / "Developer").mkdir()
    env = dict(os.environ, HOME=home, GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@example.com", GIT_CONFIG_GLOBAL=os.devnull)
    def run3(*a):
        return subprocess.run([TOOL, *a, "--no-github"], env=env, capture_output=True, text=True, timeout=120)
    pu = lambda n: next((l for l in (h/"Developer"/n/"CLAUDE.md").read_text().splitlines() if l.startswith("- Purpose:")), None)
    run3("at-one", "--about", "@../../etc/passwd import")
    check("leading @ stripped from about", pu("at-one") == "- Purpose: ../../etc/passwd import", pu("at-one"))
    run3("hash-one", "--about", "## Heading\n# more\n@x")
    check("leading # stripped and newlines collapsed (@ made inert)", pu("hash-one") == "- Purpose: Heading # more \uff20x", pu("hash-one"))
    run3("only-at", "--about", "@@ ##")
    check("about that is only @ and # falls back to (fill in)", pu("only-at") == "- Purpose: (fill in)", pu("only-at"))
    r = run3("..Dotty.Name-.", "--type", "notes")
    check("name: leading dots and trailing -. stripped, lowercase", (h/"Developer"/"dotty.name").is_dir(), sorted(p.name for p in (h/"Developer").iterdir()))
    r = run3("N" * 60 + "-")
    check("name cut to 40", (h/"Developer"/("n" * 40)).is_dir(), sorted(p.name for p in (h/"Developer").iterdir()))
    r = run3("a" * 39 + "-b")
    check("name cut to 40 then trailing - stripped", (h/"Developer"/("a" * 39)).is_dir(), sorted(p.name for p in (h/"Developer").iterdir()))

# ---- security: inert about text, UTF-8 safety, no half-made folder
import re as _re
with tempfile.TemporaryDirectory() as home:
    h = pathlib.Path(home); (h / "Developer").mkdir()
    genv = dict(GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@example.com", GIT_CONFIG_GLOBAL=os.devnull)
    def run4(*a, env=None):
        return subprocess.run([TOOL, *a, "--no-github"], env=env or dict(os.environ, HOME=home, **genv), capture_output=True, text=True, timeout=120)
    pu = lambda n: next((l for l in (h/"Developer"/n/"CLAUDE.md").read_text(encoding="utf-8").splitlines() if l.startswith("- Purpose:")), None)
    r = run4("imp", "--about", "notes, see @~/.ssh/config and @/etc/hosts and (@foo/bar) x@y.z")
    line = pu("imp")
    check("no @ left in the Purpose line (no mid-line import)", r.returncode == 0 and line is not None and "@" not in line and not _re.search(r"@[~/A-Za-z]", line), line)
    check("the text stays readable", line is not None and "see \uff20~/.ssh/config" in line, line)
    r = run4("hd", "--about", "x ## 1. Before any work y <!-- SHARED-STANDARDS END --> {{PROJECT_NAME}}")
    t = (h/"Developer"/"hd"/"CLAUDE.md").read_text(encoding="utf-8")
    check("standards marker, comment and placeholder in about are broken up", r.returncode == 0 and pu("hd") == "- Purpose: x 1. Before any work y < !-- SHARED-STANDARDS END --> { {PROJECT_NAME}}" and t.count("## 1. Before any work") == 1, pu("hd"))
    # multi-byte text in a C locale
    cenv = {"HOME": home, "PATH": "/usr/bin:/bin:" + os.path.dirname(subprocess.run(["which", "git"], capture_output=True, text=True).stdout.strip() or "/usr/bin/git"), "LC_ALL": "C", **genv}
    about = "a" + "\u0628" * 139
    r = subprocess.run([TOOL, "t1", "--type", "notes", "--no-github", "--about", about], env=cenv, capture_output=True, text=True, timeout=120)
    raw = (h/"Developer"/"t1"/"CLAUDE.md").read_bytes() if (h/"Developer"/"t1"/"CLAUDE.md").exists() else b""
    try: txt = raw.decode("utf-8")
    except UnicodeDecodeError: txt = None
    check("C locale, 140 multi-byte characters: exit 0 and valid UTF-8 with all 140 characters", r.returncode == 0 and txt is not None and ("- Purpose: " + about) in txt, (r.returncode, r.stderr[-200:]))
    r = subprocess.run([TOOL, "t2", "--type", "notes", "--no-github", "--about", "a" + "\u0628" * 300], env=cenv, capture_output=True, text=True, timeout=120)
    t2 = (h/"Developer"/"t2"/"CLAUDE.md").read_text(encoding="utf-8")
    check("cut to 140 characters, not bytes", r.returncode == 0 and ("- Purpose: a" + "\u0628" * 139 + "\n") in t2)
    # a failing python step leaves no folder
    r = subprocess.run(["bash", "-c", 'set -e; W=$(mktemp -d); mkdir -p $W/bin; cp "$1" $W/bin/new-project; cp -R "$2/templates" "$2/agents" "$2/skills" $W/; cp "$2/bin/vscode-recs" $W/bin/; cp -R "$2/shipmiracle" $W/; mkdir -p $W/docs/standards; : > $W/docs/standards/base.md; set +e; "$W/bin/new-project" doomed --type notes --no-github; echo rc=$?', "x", TOOL, str(WS)], env=dict(os.environ, HOME=home, **genv), capture_output=True, text=True, timeout=120)
    check("python step fails (empty docs/standards/base.md of the workspace): exit non-zero", "rc=0" not in r.stdout and "rc=" in r.stdout, r.stdout + r.stderr[-200:])
    check("...and the half-made folder is removed", not (h/"Developer"/"doomed").exists(), sorted(p.name for p in (h/"Developer").iterdir()))
    (h/"Developer"/"keepme").mkdir(); (h/"Developer"/"keepme"/"mine.txt").write_text("x")
    r = run4("__proto__"); check("reserved name __proto__ refused (exit 2)", r.returncode == 2 and "reserved" in r.stderr and not (h/"Developer"/"__proto__").exists(), r.stderr)
    r = run4("constructor"); check("reserved name constructor refused", r.returncode == 2 and "reserved" in r.stderr)


# ---- P8: folders from the shipm config; the engine folder is written into hooks (@SHIPMIRACLE_ENGINE@); delete-project refuses protected projects (temp sandbox only)
with tempfile.TemporaryDirectory() as home:
    h = pathlib.Path(home); (h / "work").mkdir(); (h / "cfg").mkdir(); (h / "bin-stub").mkdir()
    (h / "cfg" / "config.json").write_text(json.dumps({"paths.projects_dir": "~/work", "engine.dir": "/opt/engine-x"}))
    gh = h / "bin-stub" / "gh"; gh.write_text('#!/bin/sh\necho "$@" >> "%s"\nexit 1\n' % (h / "gh.log")); gh.chmod(0o755)
    env = dict(os.environ, HOME=home, GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@example.com",
               GIT_CONFIG_GLOBAL=os.devnull, SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=home, SHIPMIRACLE_DEV=home + "/work", SHIPMIRACLE_CONFIG=home + "/cfg", SHIPMIRACLE_STATE=home + "/state",
               PATH=str(h / "bin-stub") + ":" + os.environ.get("PATH", ""))
    env.pop("CLAUDECODE", None)
    r = subprocess.run([TOOL, "cfg-demo", "--type", "notes", "--no-github", "--no-open"], env=env, capture_output=True, text=True, timeout=120)
    pd = h / "work" / "cfg-demo"
    check("paths.projects_dir (~/work) decides where the project is created", r.returncode == 0 and (pd / "CLAUDE.md").is_file() and not (h / "Developer").exists(), r.stderr[-200:])
    ss = (pd / ".claude/hooks/session-start.sh").read_text() if (pd / ".claude/hooks/session-start.sh").is_file() else ""
    check("session-start.sh has the engine folder written in (engine.dir), no placeholder", "/opt/engine-x/bin/status-extract" in ss and "@SHIPMIRACLE_ENGINE@" not in ss, ss[:300])
    pc = (pd / ".githooks/post-commit").read_text() if (pd / ".githooks/post-commit").is_file() else ""
    check("post-commit has the engine folder written in and nothing else changed", 'engine_hint="/opt/engine-x"' in pc and "@SHIPMIRACLE_ENGINE@" not in pc, pc[:200])
    # apply-template renders the same way, and a second run changes nothing
    ssf = pd / ".claude/hooks/session-start.sh"; good = ssf.read_text(); ssf.write_text(good + "# drift\n")
    at = str(WS / "bin" / "apply-template")
    r1 = subprocess.run([at, str(pd)], env=env, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    r2 = subprocess.run([at, str(pd)], env=env, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    check("apply-template restores the hook with the engine folder written in (no placeholder), a second run finds it current",
          ssf.read_text() == good and "updated .claude/hooks/session-start.sh" in r1.stdout and "updated .claude/hooks/session-start.sh" not in r2.stdout and "@SHIPMIRACLE_ENGINE@" not in ssf.read_text(), (r1.stdout[-300:], r2.stdout[-200:], r1.stderr[-200:]))
    # delete-project: a registry-protected project and the engine folder's own name are refused before anything is touched
    if os.path.exists(str(WS / "bin" / "delete-project")):          # the delete tool is owner-only: not part of the public export
        dp = str(WS / "bin" / "delete-project")
        for name in ("guard-me", "engine-x"):
            (h / "work" / name).mkdir(); subprocess.run(["git", "init", "-q", str(h / "work" / name)], env=env, check=True)
            (h / "work" / name / "keep.txt").write_text("x")
        subprocess.run([sys.executable, str(WS / "bin" / "shipm"), "registry", "sync"], env=env, capture_output=True, text=True, timeout=60)
        regf = h / "cfg" / "registry.json"
        reg = json.loads(regf.read_text()); hit = [e for e in reg["projects"].values() if e.get("name") == "guard-me"]
        for e in hit: e["protected"] = True
        regf.write_text(json.dumps(reg))
        r = subprocess.run([dp, "guard-me", "--where", "mac", "--yes"], env=env, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        check("delete-project refuses a project the registry marks protected (exit 2), folder and files intact, gh not called",
              bool(hit) and r.returncode == 2 and "protected in the registry" in r.stderr and (h / "work/guard-me/keep.txt").is_file() and not (h / "gh.log").exists(), (r.returncode, r.stderr, hit))
        r = subprocess.run([dp, "engine-x", "--where", "mac", "--yes"], env=env, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        check("delete-project refuses the folder named like engine.dir (exit 2), nothing touched",
              r.returncode == 2 and "engine folder" in r.stderr and (h / "work/engine-x/keep.txt").is_file() and not (h / "gh.log").exists(), (r.returncode, r.stderr))

# ---- playbook step: real shipm in the temp sandbox, then a fake shipm that records the call (mapping, --playbook override, fail-soft)
with tempfile.TemporaryDirectory() as home:
    h = pathlib.Path(home); (h / "Developer").mkdir()
    env = dict(os.environ, HOME=home, GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@example.com",
               GIT_CONFIG_GLOBAL=os.devnull, SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=home, SHIPMIRACLE_DEV=home + "/Developer", SHIPMIRACLE_CONFIG=home + "/cfg", SHIPMIRACLE_STATE=home + "/state")
    env.pop("CLAUDECODE", None)
    def runp(*a, e=None):
        return subprocess.run([TOOL, *a, "--no-github", "--no-open"], env=e or env, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    r = runp("pb-real", "--type", "web")
    pj = h / "Developer" / "pb-real" / ".shipmiracle" / "playbook.json"
    pbd = json.loads(pj.read_text()) if pj.is_file() else {}
    check("real shipm: playbook.json with type software exists after create (timeline gets its playbook)", r.returncode == 0 and pbd.get("type") == "software" and "Playbook: type software set" in r.stdout, (r.returncode, r.stdout[-200:], r.stderr[-300:]))
    st = subprocess.run(["git", "-C", str(h / "Developer" / "pb-real"), "status", "--porcelain"], capture_output=True, text=True, env=env).stdout.strip()
    check("real shipm: the playbook is committed (clean tree)", st == "", st)
    # a re-run on a project that already has a playbook leaves it alone (no set call)
    fakes = h / "fake"; fakes.mkdir(); calls = h / "calls.log"
    def fake(rc):
        f = fakes / "shipm"; f.write_text('#!/bin/sh\necho "$@" >> %s\nexit %d\n' % (calls, rc)); f.chmod(0o755)
        return dict(env, SHIPMIRACLE_SHIPM=str(f))
    # the fake also answers config/registry calls (those use bin/shipm directly, not the fake)
    fenv = fake(0)
    for typ, want in (("web", "software"), ("api", "software"), ("python", "software"), ("ios", "app"), ("home", "app"), ("notes", "notes"), ("other", "software")):
        if calls.exists(): calls.unlink()
        r = runp("map-" + typ, "--type", typ, e=fenv)
        got = calls.read_text().strip() if calls.exists() else ""
        check("--type %s -> playbook set type %s --project <dir>" % (typ, want), r.returncode == 0 and got == "playbook set type %s --project map-%s --allow-open-chat" % (want, typ), (r.returncode, got, r.stderr[-200:]))
    if calls.exists(): calls.unlink()
    r = runp("ov", "--type", "web", "--playbook", "ops", e=fenv)
    check("--playbook ops overrides the mapping", r.returncode == 0 and calls.read_text().strip().split()[:4] == ["playbook", "set", "type", "ops"], (calls.read_text() if calls.exists() else "", r.stderr))
    calls.unlink()
    r = runp("skip", "--type", "web", "--playbook", "none", e=fenv)
    check("--playbook none: shipm playbook never called, project created", r.returncode == 0 and not calls.exists() and (h / "Developer" / "skip" / "CLAUDE.md").is_file(), (r.returncode, r.stderr))
    r = runp("badpb", "--playbook", "nonsense", e=fenv)
    check("--playbook with an unknown type refused (exit 2), nothing created", r.returncode == 2 and "unknown playbook type" in r.stderr and not (h / "Developer" / "badpb").exists(), (r.returncode, r.stderr))
    r = subprocess.run([TOOL, "x", "--playbook"], env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    check("--playbook without a value refused", r.returncode == 2, r.stderr)
    fenv = fake(1)
    r = runp("failsoft", "--type", "ios", e=fenv)
    warn = [l for l in r.stderr.splitlines() if l.startswith("warning: playbook not set")]
    check("fail-soft: playbook set fails -> exit 0, project complete, one warning line with the exact command",
          r.returncode == 0 and (h / "Developer" / "failsoft" / "CLAUDE.md").is_file() and len(warn) == 1 and warn[0].endswith("shipm playbook set type app --project failsoft"), (r.returncode, r.stderr))
    # a project that already has a playbook: default re-run does not call set, explicit --playbook does
    calls.unlink()
    (h / "Developer" / "failsoft" / ".shipmiracle").mkdir(exist_ok=True); (h / "Developer" / "failsoft" / ".shipmiracle" / "playbook.json").write_text("{}")
    r = runp("failsoft", "--type", "ios", e=fenv)
    check("existing playbook.json: default re-run does not call playbook set", r.returncode == 0 and not calls.exists(), (r.returncode, r.stderr))
    r = runp("failsoft", "--type", "ios", "--playbook", "app", e=fenv)
    check("existing playbook.json: explicit --playbook does call it", calls.exists(), r.stderr)

# ---- prettier: .shipmiracle/ must not be checked by the project's formatter (CI `prettier --check .` warned about .shipmiracle/playbook.json)
PI_MSG = "Prettier: ignore .shipmiracle (generated playbook)"
check("the web template ships a .prettierignore that already holds the line", (WS / "templates" / "web" / ".prettierignore").read_text() == ".shipmiracle/\n")
with tempfile.TemporaryDirectory() as home:
    h = pathlib.Path(home); (h / "Developer").mkdir()
    env = dict(os.environ, HOME=home, GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@example.com",
               GIT_CONFIG_GLOBAL=os.devnull, SHIPMIRACLE_TEST="1", SHIPMIRACLE_HOME=home, SHIPMIRACLE_DEV=home + "/Developer", SHIPMIRACLE_CONFIG=home + "/cfg", SHIPMIRACLE_STATE=home + "/state")
    env.pop("CLAUDECODE", None)
    def runq(*a):
        return subprocess.run([TOOL, *a, "--no-github", "--no-open"], env=env, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    def git(d, *a):
        return subprocess.run(["git", "-C", str(d), *a], capture_output=True, text=True, env=env).stdout.strip()
    def subjects(d):
        return git(d, "log", "--format=%s").splitlines()
    # a new web project: the template line is in the first commit, the step finds nothing to do
    r = runq("pi-web", "--type", "web")
    d = h / "Developer" / "pi-web"
    check("new web project: .prettierignore is there with the one line, in the template commit; no extra prettier commit", r.returncode == 0 and (d / ".prettierignore").read_text() == ".shipmiracle/\n" and PI_MSG not in subjects(d) and ".prettierignore" in git(d, "ls-files"), (r.returncode, r.stderr[-300:], subjects(d)))
    # the project later adds prettier (package.json committed): a re-run keeps it as is (already ignored), no commit
    (d / "package.json").write_text(json.dumps({"devDependencies": {"prettier": "3.3.3"}})); git(d, "add", "package.json"); git(d, "commit", "-q", "-m", "add prettier")
    r = runq("pi-web", "--type", "web")
    check("web project with prettier that already ignores it: re-run adds no prettier commit and leaves the file and the tree as they were", r.returncode == 0 and PI_MSG not in subjects(d) and (d / ".prettierignore").read_text() == ".shipmiracle/\n" and git(d, "status", "--porcelain") == "", (r.stderr[-300:], subjects(d)[:3]))
    # a python project (no .prettierignore in its template) that uses prettier: one line, one commit of just that file
    r = runq("pi-py", "--type", "python")
    d = h / "Developer" / "pi-py"
    check("python project without prettier: no .prettierignore, no prettier commit", r.returncode == 0 and not (d / ".prettierignore").exists() and PI_MSG not in subjects(d), (r.stderr[-300:], subjects(d)))
    (d / "package.json").write_text(json.dumps({"scripts": {"lint": "eslint . && prettier --check ."}})); git(d, "add", "package.json"); git(d, "commit", "-q", "-m", "add package.json")
    (d / "keep-out.txt").write_text("not mine\n")            # an unrelated file in the tree: the first commit of a re-run takes it, the prettier commit must hold only .prettierignore
    st0 = (d / "docs" / "STATUS.md").read_text()
    r = runq("pi-py", "--type", "python")
    check("project that uses prettier: one line added, one prettier commit (the last) holding only .prettierignore + docs/STATUS.md; the template pre-commit hook let it through (no --no-verify)", r.returncode == 0 and (d / ".prettierignore").read_text() == ".shipmiracle/\n" and subjects(d)[0] == PI_MSG and subjects(d).count(PI_MSG) == 1
          and sorted(git(d, "show", "--name-only", "--format=", "HEAD").splitlines()) == [".prettierignore", "docs/STATUS.md"] and "Prettier: .shipmiracle/ added to .prettierignore" in r.stdout, (r.returncode, r.stdout[-300:], r.stderr[-300:], subjects(d)[:4]))
    stl = (d / "docs" / "STATUS.md").read_text().splitlines()
    check("STATUS.md has the Updated line (today) on top and the rest as it was", stl[0].startswith("Updated: %s " % __import__("datetime").date.today().isoformat()) and ".shipmiracle/ ignored by prettier" in stl[0] and "\n".join(stl[1:]) + "\n" == st0, stl[:3])
    check("keep-out.txt went into the earlier template commit, not the prettier one", "keep-out.txt" not in git(d, "show", "--name-only", "--format=", "HEAD"), git(d, "show", "--name-only", "--format=", "HEAD"))
    before = (d / ".prettierignore").read_text(); r = runq("pi-py", "--type", "python")
    check("second run: no change, no prettier commit, line still there exactly once", r.returncode == 0 and subjects(d).count(PI_MSG) == 1 and (d / ".prettierignore").read_text() == before and before.count(".shipmiracle/") == 1 and git(d, "status", "--porcelain") == "", (r.stderr[-300:], subjects(d)[:3]))
    # an existing .prettierignore (no final newline) keeps its content
    r = runq("pi-old", "--type", "python"); d = h / "Developer" / "pi-old"
    (d / "package.json").write_text(json.dumps({"devDependencies": {"prettier": "3"}})); (d / ".prettierignore").write_bytes(b"dist\ncoverage")
    git(d, "add", "-A"); git(d, "commit", "-q", "-m", "prettier setup")
    r = runq("pi-old", "--type", "python")
    check("existing .prettierignore without final newline: old lines kept, our line on its own line, one prettier commit", r.returncode == 0 and (d / ".prettierignore").read_text() == "dist\ncoverage\n.shipmiracle/\n" and subjects(d)[0] == PI_MSG, (r.stderr[-300:], (d / ".prettierignore").read_text()))
    # fail-soft: a symlinked .prettierignore is not written through; the project stays, a warning names the fix, exit 0
    r = runq("pi-link", "--type", "python"); d = h / "Developer" / "pi-link"
    (d / "package.json").write_text(json.dumps({"devDependencies": {"prettier": "3"}})); (h / "elsewhere.txt").write_text("keep\n"); os.symlink(h / "elsewhere.txt", d / ".prettierignore")
    git(d, "add", "-A"); git(d, "commit", "-q", "-m", "prettier setup")
    r = runq("pi-link", "--type", "python")
    check("symlinked .prettierignore: warning on stderr, exit 0, target untouched, no prettier commit", r.returncode == 0 and "warning: prettier ignore not set" in r.stderr and (h / "elsewhere.txt").read_text() == "keep\n" and PI_MSG not in subjects(d), (r.returncode, r.stderr[-300:]))

# ---- a fake HOME without SHIPMIRACLE_TEST: the playbook (like the registry) is not written, a note says how
with tempfile.TemporaryDirectory() as home:
    h = pathlib.Path(home); (h / "Developer").mkdir()
    env = dict(os.environ, HOME=home, GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@example.com", GIT_CONFIG_GLOBAL=os.devnull)
    for k in ("SHIPMIRACLE_TEST", "SHIPMIRACLE_HOME", "SHIPMIRACLE_CONFIG", "SHIPMIRACLE_STATE", "SHIPMIRACLE_DEV", "CLAUDECODE"): env.pop(k, None)
    r = subprocess.run([TOOL, "fakepb", "--type", "web", "--no-github", "--no-open"], env=env, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    check("fake HOME, no SHIPMIRACLE_TEST: playbook not set, note names the command, exit 0", r.returncode == 0 and "playbook not set (run: shipm playbook set type software" in r.stdout and not (h / "Developer" / "fakepb" / ".shipmiracle").exists(), (r.returncode, r.stdout[-300:]))

print("\nFAILED: %d" % fails if fails else "\nALL PASS")
sys.exit(1 if fails else 0)
