#!/usr/bin/env python3
"""gate_persist_test: checklist D14 / M1, the persistence-file protection is ONE table (shipmiracle/autopilot/rules.py PERSIST_*) shared by the autopilot hard stop and BOTH flow-gate copies
(the legacy shell gate where it exists, shipmiracle/hooks/flow.py through the v1 shim). Nothing that is denied today is allowed here; this only adds denies:
  1  the table: the gate copies carry the same literal PERSIST_* tuples as rules.py (a test, not an import: the gate is stdlib-only and standalone); the hard stop is built from the table;
  2  strict files, main chat and agent, Write / Edit / MultiEdit and Bash (redirect, tee, cp, mv, install, ln, sed -i, python open, heredoc, rm, touch): ~/.zshrc ~/.zprofile ~/.zshenv ~/.bashrc
     ~/.bash_profile ~/.profile ~/.gitconfig ~/.netrc ~/.pypirc ~/.git-credentials ~/.npmrc ~/.gitignore_global, ~/Library/LaunchAgents/**, ~/.config/git/**, <project>/.envrc,
     <project>/.vscode/tasks.json (reading them stays allowed);
  3  <project>/.vscode/settings.json is judged by what is written: refused when the text holds a code-running key (terminal.*, *path, executable, command, shell, args, interpreter, script, task,
     env, exec, tsdk, launch, debug, ...) or when the content cannot be seen (cp / mv / install / ln / cat / jq ... onto it); a plain editor setting passes;
  4  a benign corpus of 40 ordinary dev edits that must stay allowed for the main chat and for an agent (the false-refusal measure).
Run: python3 tests/gate_persist_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation
import ast, json, os, pathlib, re, shlex, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import flow_fixture as F
from flow_fixture import deny, text
from shipmiracle.autopilot import hardstop as H, rules as R

fails = []


def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:500]))
    if not ok:
        fails.append(name)


HOME = os.path.realpath(os.environ["HOME"])
NAMES = ("PERSIST_HOME_FILES", "PERSIST_HOME_DIRS", "PERSIST_ABS_DIRS", "PERSIST_PROJECT_FILES", "PERSIST_PROJECT_DIRS", "PERSIST_PROJECT_SUFFIXES", "PERSIST_SETTINGS_FILES", "PERSIST_SETTINGS_RISKY", "PERSIST_SETTINGS_ALLOW")

# ------------------------------------------------------------------ 1  one table
def literals(src):
    out = {}
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in NAMES:
            out[node.targets[0].id] = ast.literal_eval(node.value)
    return out


copies = [("v1 gate source (shipmiracle/hooks/flow.py)", (ROOT / "shipmiracle/hooks/flow.py").read_text())]
if F.LEGACY_HOOK.exists():
    copies.append(("legacy shell gate", F.LEGACY_HOOK.read_text().split("\n#--PYTHON-BEGIN--\n", 1)[1]))
for label, src in copies:
    lit = literals(src)
    for n in NAMES:
        check("%s: %s equals rules.py" % (label, n), lit.get(n) == getattr(R, n, None) and lit.get(n) is not None, (lit.get(n), getattr(R, n, None)))
check("rules.ALWAYS_EXCLUDED still holds the original three project files (charter text unchanged)", all(f in R.ALWAYS_EXCLUDED for f in (".vscode/tasks.json", ".vscode/settings.json", ".envrc")))
check("the settings file is part of the project table", all(f in R.PERSIST_PROJECT_FILES for f in R.PERSIST_SETTINGS_FILES))
for need in (".zshrc", ".zprofile", ".zshenv", ".bashrc", ".bash_profile", ".profile", ".gitconfig"):
    check("table lists ~/%s" % need, need in R.PERSIST_HOME_FILES)
check("table lists LaunchAgents and ~/.config/git", "Library/LaunchAgents" in R.PERSIST_HOME_DIRS and ".config/git" in R.PERSIST_HOME_DIRS and "/Library/LaunchAgents" in R.PERSIST_ABS_DIRS)
check("table lists .envrc, tasks.json and settings.json", set(R.PERSIST_PROJECT_FILES) >= {".envrc", ".vscode/tasks.json", ".vscode/settings.json"})

WT = pathlib.Path(tempfile.mkdtemp()).resolve() / "dev" / ".worktrees" / "sandbox" / "auto-CR-012"
WT.mkdir(parents=True)
(WT / "src").mkdir(); (WT / "src/a.py").write_text("x\n")


def hs_protected(path, kind="write"):
    c = H.Ctx(root=str(WT), base_sha="abc123", scope=["src/**"], tracked=lambda rel: ["src/a.py"], changed=set(), read_text=lambda r: None, added_text=lambda r: None,
              home=HOME, tmp_roots=["/tmp", "/private/tmp"], active_cr="CR-012", ends=["CR-012"], auto_branch="auto/CR-012", ahead=1)
    run = H._Run(c, str(WT))
    return run.protected(os.path.realpath(path) if os.path.exists(path) else path, kind)


for f in R.PERSIST_HOME_FILES:
    check("hard stop protects ~/%s (built from the table)" % f, hs_protected(HOME + "/" + f))
for d in R.PERSIST_HOME_DIRS:
    check("hard stop protects ~/%s/x (built from the table)" % d, hs_protected(HOME + "/" + d + "/x"))
for d in R.PERSIST_ABS_DIRS:
    check("hard stop protects %s/x" % d, hs_protected(d + "/x"))
for f in R.PERSIST_PROJECT_FILES:
    check("hard stop protects <worktree>/%s" % f, hs_protected(str(WT / f)))
os.makedirs(HOME + "/Library/Python/3.9/lib/python/site-packages", exist_ok=True)
check("hard stop protects the macOS user site-packages (glob in the table)", hs_protected(HOME + "/Library/Python/3.9/lib/python/site-packages/usercustomize.py"))
check("hard stop leaves a plain project file alone", not hs_protected(str(WT / "src/a.py")))
check("hard stop leaves .vscode/launch.json alone (a trade-off recorded in DECISIONS)", not hs_protected(str(WT / ".vscode/launch.json")))

# ------------------------------------------------------------------ 2-4  the flow gate, both copies
p = F.make_project()
p.ENV["SHIPMIRACLE_ISOLATION"] = "off"                           # G11: this suite is about the persistence table; OTHER is a second project whose files it reads and writes on purpose (project isolation has its own suites: gate_isolation_test, gate_secret_read_test)
p.put("src/a.py", "x\n")
p.put(".vscode/settings.json", '{"editor.tabSize": 2}\n')
p.put(".githooks/post-commit", "#!/bin/sh\nexit 0\n")
with open(os.path.join(str(p.P), ".git/config"), "a") as _gc:
    _gc.write("[core]\n\thooksPath = custom-hooks\n")
OTHER = p.DEV / "other-project"                                  # another project below the projects folder
(OTHER / ".git").mkdir(parents=True)
p.prompt()
IMPLS = []
if F.LEGACY_HOOK.exists():
    IMPLS.append(("legacy shell gate", str(F.LEGACY_HOOK)))
IMPLS.append(("v1 gate (shipmiracle/hooks/flow.py)", str(F.V1_HOOK)))
cnt = [0]


def run_cmd(hook, cmd, tool="Bash", ti=None, agent=None, env=None):
    cnt[0] += 1
    d = {"hook_event_name": "PreToolUse", "session_id": "g%d" % cnt[0], "cwd": str(p.P), "tool_name": tool, "tool_input": ti or {"command": cmd}}
    if agent:
        d.update({"agent_id": "ag1", "agent_type": agent})
    r = subprocess.run(["bash", hook], input=json.dumps(d), capture_output=True, text=True, env=env or p.ENV, cwd=str(p.P))
    try:
        return json.loads(r.stdout) if r.stdout.strip() else {}
    except Exception:
        return {"raw": r.stdout, "err": r.stderr}


PROJ = str(p.P)
STRICT = ([HOME + "/" + f for f in R.PERSIST_HOME_FILES]
          + [HOME + "/Library/LaunchAgents/com.x.plist", HOME + "/Library/LaunchAgents/sub/y.plist", HOME + "/.config/git/config", HOME + "/.config/git/ignore", HOME + "/.config/git/attributes"]
          + [HOME + "/" + d + "/x.conf" for d in R.PERSIST_HOME_DIRS if d not in (".config/systemd", ".config/autostart", ".config/environment.d")]
          + [d + "/x.plist" for d in R.PERSIST_ABS_DIRS]
          + [r_ + "/" + f_ for r_ in (PROJ, PROJ + "/packages/app", str(OTHER)) for f_ in R.PERSIST_PROJECT_FILES if f_ not in R.PERSIST_SETTINGS_FILES and not f_.startswith(".claude/")]
          + [r_ + "/" + d_ + "/pre-commit" for r_ in (PROJ, PROJ + "/packages/app", str(OTHER)) for d_ in R.PERSIST_PROJECT_DIRS]
          + [PROJ + "/custom-hooks/pre-commit", PROJ + "/my.code-workspace", str(OTHER) + "/x.code-workspace", str(OTHER) + "/.claude/settings.json", str(OTHER) + "/.claude/settings.local.json"])
WRITES = ["echo x > {f}", "echo x >> {f}", "printf x | tee {f}", "tee {f} < /dev/null", "tee -a {f} < /dev/null", "cp /tmp/a {f}", "mv /tmp/a {f}", "install -m 644 /tmp/a {f}",
          "ln -sf /tmp/a {f}", "sed -i s/a/b/ {f}", "sed -i '' s/a/b/ {f}", "python3 -c \"open('{f}','w').write('x')\"", "cat > {f} <<EOF\nx\nEOF", "rm {f}", "touch {f}",
          "echo 'export A=1' >> {f}", "bash -c 'echo x >> {f}'", "cd /tmp && echo x >> {f}"]
READS = ["cat {f}", "grep -n alias {f}", "head -3 {f}", "cp {f} /tmp/backup.copy", "ls -l {f}", "wc -l {f}", "diff {f} /tmp/other", "tail -2 {f}"]
FILE_TOOLS = [("Write", {"content": "x"}), ("Edit", {"old_string": "a", "new_string": "b"}), ("MultiEdit", {"edits": [{"old_string": "a", "new_string": "b"}]})]
SETTINGS = PROJ + "/.vscode/settings.json"
RISKY = ['{"terminal.integrated.profiles.osx": {"x": {"path": "/tmp/evil"}}}', '{"git.path": "/tmp/git"}', '{"python.defaultInterpreterPath": "/tmp/py"}',
         '{"terminal.integrated.automationProfile.osx": {"path": "/tmp/x"}}', '{"typescript.tsdk": "/tmp/ts"}', '{"php.validate.executablePath": "/tmp/php"}',
         '{"eslint.runtime": "/tmp/node"}', '{"eslint.nodePath": "/tmp/n"}', '{"terminal.integrated.defaultProfile.osx": "evil"}', '{"terminal.integrated.env.osx": {"A": "b"}}', '{"task.autoDetect": "on"}']
M1_BENIGN = ['{"files.exclude": {"**/.venv": true, "**/venv": true, "**/.env": true}}', '{"search.exclude": {"**/.venv": true, "**/node_modules": true}}', '{"files.watcherExclude": {"**/.venv/**": true, "**/.env": true}}',
             '{"files.associations": {"*.env": "properties", "*.cmd": "bat"}}', '{"python.analysis.extraPaths": ["./src", "./lib"]}', '{"python.testing.pytestArgs": ["tests", "-x"]}',
             '{"python.envFile": "${workspaceFolder}/.env"}', '{"terminal.integrated.shellIntegration.enabled": true}', '{"debug.console.fontSize": 14}', '{"editor.environment": "x"}',
             '{"terminal.integrated.fontSize": 13}', '{"python.terminal.activateEnvironment": false}', '{"[javascript]": {"editor.defaultFormatter": "esbenp.prettier-vscode", "editor.tabSize": 2}}',
             '{"typescript.preferences.importModuleSpecifier": "relative"}', '{"git.autofetch": true}', '{"cSpell.words": ["shipm", "tamper"]}']
BENIGN_SETTINGS = ['{"editor.tabSize": 2}', '{"editor.formatOnSave": true, "files.eol": "\\n"}', '{"files.exclude": {"**/.DS_Store": true}}', '{"editor.rulers": [100]}',
                   '{"[python]": {"editor.defaultFormatter": "ms-python.black-formatter"}}', '{"search.exclude": {"dist": true}}']

cases = []          # (label, tool, ti, agent, want_deny)
for f in STRICT:
    short = f.replace(HOME, "~").replace(PROJ, "<proj>")
    for agent in (None, "backend-engineer"):
        who = " (agent)" if agent else ""
        for tool, extra in FILE_TOOLS:
            cases.append(("%s %s%s" % (tool, short, who), tool, dict(extra, file_path=f), agent, True))
        fq = shlex.quote(f) if " " in f else f
        for tpl in WRITES:
            if " " in f and ("open('" in tpl or "bash -c" in tpl):
                continue
            cases.append(("Bash %r%s" % (tpl.format(f=short)[:60], who), "Bash", {"command": tpl.format(f=fq)}, agent, True))
        for tpl in READS:
            cases.append(("Bash read %r%s" % (tpl.format(f=short)[:60], who), "Bash", {"command": tpl.format(f=fq)}, agent, False))
for agent in (None, "backend-engineer"):
    who = " (agent)" if agent else ""
    for body in RISKY:
        cases.append(("Write settings.json risky %s%s" % (body[:40], who), "Write", {"file_path": SETTINGS, "content": body}, agent, True))
        cases.append(("Edit settings.json risky %s%s" % (body[:40], who), "Edit", {"file_path": SETTINGS, "old_string": '"editor.tabSize": 2', "new_string": body[1:-1]}, agent, True))
        cases.append(("Bash redirect settings.json risky %s%s" % (body[:40], who), "Bash", {"command": "echo '%s' > %s" % (body, SETTINGS)}, agent, True))
    cases.append(("MultiEdit settings.json risky%s" % who, "MultiEdit", {"file_path": SETTINGS, "edits": [{"old_string": "2", "new_string": "4"}, {"old_string": "4", "new_string": '2, "git.path": "/x"'}]}, agent, True))
    for tpl in ("cp /tmp/a {f}", "mv /tmp/a {f}", "install -m 644 /tmp/a {f}", "cat /tmp/a > {f}", "jq . /tmp/a > {f}", "ln -sf /tmp/a {f}", "tee {f} < /tmp/a", "sed -i s/a/b/ {f} < /tmp/a"):
        cases.append(("Bash settings.json content unseen %r%s" % (tpl.format(f=".vscode/settings.json"), who), "Bash", {"command": tpl.format(f=SETTINGS)}, agent, True))
    for body in BENIGN_SETTINGS:
        cases.append(("Write settings.json benign %s%s" % (body[:40], who), "Write", {"file_path": SETTINGS, "content": body}, agent, False))
        cases.append(("Edit settings.json benign %s%s" % (body[:40], who), "Edit", {"file_path": SETTINGS, "old_string": '"editor.tabSize": 2', "new_string": body[1:-1]}, agent, False))
        cases.append(("Bash redirect settings.json (EVERY Bash write is refused, even a benign one) %s%s" % (body[:40], who), "Bash", {"command": "echo '%s' > %s" % (body, SETTINGS)}, agent, True))
    cases.append(("Write settings.json unparseable with a code-running key%s" % who, "Write", {"file_path": SETTINGS, "content": '{"git.path": "/x",'}, agent, True))
    cases.append(("Write settings.json unparseable and plain%s" % who, "Write", {"file_path": SETTINGS, "content": '{"editor.tabSize": 2,'}, agent, False))
    cases.append(("Write settings.json with comments and a trailing comma (JSONC) plain%s" % who, "Write", {"file_path": SETTINGS, "content": '{\n // size\n "editor.tabSize": 2,\n}\n'}, agent, False))
    cases.append(("Write settings.json with a unicode-escaped code-running key%s" % who, "Write", {"file_path": SETTINGS, "content": '{"\\u0067it.path": "/x"}'}, agent, True))
    cases.append(("Bash python writes settings.json (content computed)%s" % who, "Bash", {"command": "python3 -c \"open('.vscode/settings.json','w')\""}, agent, True))
    cases.append(("Bash sed -i on settings.json (every Bash write refused)%s" % who, "Bash", {"command": "sed -i 's/2/4/' %s" % SETTINGS}, agent, True))
    cases.append(("Bash fragment-built settings.json (printf %%s pieces)%s" % who, "Bash", {"command": "printf '%%s%%s' '{\"git.pa' 'th\": 1}' > " + SETTINGS}, agent, True))
    cases.append(("Edit settings.json whose old_string does not match (not judged: refused)%s" % who, "Edit", {"file_path": SETTINGS, "old_string": "NOT IN THE FILE", "new_string": "x"}, agent, True))
    cases.append(("Edit settings.json with curly quotes in old_string (refused)%s" % who, "Edit", {"file_path": SETTINGS, "old_string": "\u201ceditor.tabSize\u201d: 2", "new_string": '"git.path": "/x"'}, agent, True))
    for w_ in R.PERSIST_SETTINGS_RISKY:
        cases.append(("Write settings.json with a setting named x.%s%s" % (w_, who), "Write", {"file_path": SETTINGS, "content": '{"x.%s": "v"}' % w_}, agent, True))
    for nm_ in ("java.jdt.ls.java.home", "go.goroot", "go.alternateTools", "lldb.library", "r.rterm.mac", "typescript.npm", "prettier.configPath", "python.defaultInterpreterPath"):
        cases.append(("Write settings.json real code-running setting %s%s" % (nm_, who), "Write", {"file_path": SETTINGS, "content": '{"%s": "x"}' % nm_}, agent, True))
        cases.append(("Edit settings.json a [language] block carrying %s%s" % (nm_, who), "Edit", {"file_path": SETTINGS, "old_string": '"editor.tabSize": 2', "new_string": '"[python]": {"%s": "x"}' % nm_}, agent, True))
    for body_ in M1_BENIGN:
        cases.append(("Write settings.json benign (M-1) %s%s" % (body_[:50], who), "Write", {"file_path": SETTINGS, "content": body_}, agent, False))
        cases.append(("Edit settings.json benign (M-1) %s%s" % (body_[:50], who), "Edit", {"file_path": SETTINGS, "old_string": '"editor.tabSize": 2', "new_string": body_[1:-1]}, agent, False))
    for cmd_ in ("git commit -m x", "git commit --allow-empty -m x", "git status", "git log --oneline", "git add -A", "git config --local --list", "cat .git/config", "cat .githooks/post-commit", "ls .git/hooks", "grep -n hooksPath .git/config", "cp .githooks/post-commit /tmp/h.copy", "cat .husky/pre-commit"):
        cases.append(("Bash %s stays allowed%s" % (cmd_, who), "Bash", {"command": cmd_}, agent, False))
    cases.append(("Bash cat settings.json%s" % who, "Bash", {"command": "cat %s" % SETTINGS}, agent, False))

# D14 D2: git config / husky forms that set up code which runs later
GIT_DENY = ["git config --local core.hooksPath .husky", "git config core.hooksPath /tmp/h", "git config --global core.hooksPath /tmp/h", "git config --system core.hooksPath x", "git config --worktree core.fsmonitor x",
            "git config core.fsmonitor 'sh -c x'", "git config --local core.sshCommand 'ssh -v'", "git config core.pager x", "git config core.editor vim", "git config core.askPass x", "git config alias.x '!sh -c id'",
            "git config --global alias.x '!echo'", "git config --add include.path /tmp/evil", "git config includeIf.gitdir:/x/.path /tmp/evil", "git config -f .git/config user.name x",
            "git config --file ~/.gitconfig user.name x", "git config --edit", "git config -e", "git config --global --edit", "git config edit", "git config set core.hooksPath x", "git config credential.helper '!x'",
            "git config gpg.program x", "git config diff.x.textconv x", "git config filter.x.clean x", "git config filter.x.smudge x", "git config merge.x.driver x", "git config pager.log x", "git config sequence.editor x",
            "git config url.https://evil/.insteadOf https://github.com/", "git config remote.origin.receivepack x", "git config remote.origin.uploadpack x", "git config http.sslCAInfo /tmp/ca",
            "git config Core.HooksPath x", "git config 'Core.HooksPath' x", "git config \"core.hooksPath\" x", "git config core.\\hooksPath x", "git -c core.hooksPath=/tmp/h commit -m x", "git -c core.fsmonitor=x status", "git -c core.fsmonitor=/tmp/x status", "git -c core.hooksPath=/dev/null commit -m x", "git -C . config core.hooksPath x", "git init --template /tmp/t newrepo", "git clone --template=/tmp/t url dir",
            "npx husky install", "npx husky init", "npx husky add .husky/pre-commit x", "pnpm dlx husky-init", "yarn dlx husky install", "bunx husky", "npx husky", "husky install", "npm exec husky install",
            "npx --yes husky@9 init", "yarn husky install", "pnpm husky init", "sudo git config core.hooksPath x", "env FOO=1 git config core.hooksPath x", "bash -c 'git config core.hooksPath x'", "git config core.hooksPath x && echo ok",
            "git config --local --replace-all core.hooksPath x", "git config --global --add core.fsmonitor x"]
GIT_ALLOW = ["git config --get core.hooksPath", "git config core.hooksPath", "git config --local --list", "git config -l", "git config --get-regexp alias", "git config user.name", "git config --global user.name",
             "git config --list --show-origin", "git config --local user.name Ada", "git config --local user.email a@b.c", "git config pull.rebase true", "git config init.defaultBranch main", "git config core.autocrlf input",
             "git config commit.gpgsign false", "git config push.default simple", "git config --global user.email x@y.z", "git config branch.main.rebase true", "git config alias.st status", "git config color.ui auto",
             "git config --local --unset core.hooksPath", "git config --unset-all alias.x", "git config --global --unset core.fsmonitor", "git config get user.name", "git config list",
             "git -c user.name=x commit -m y", "git -c color.ui=always diff", "git -c core.autocrlf=false status", "git -c core.fsmonitor=false status", "git -c core.editor=true commit", "git -c core.pager=cat log", "git -c core.sshCommand='ssh -i key' fetch", "git init newrepo", "git init --bare x", "git clone url dir", "git clone --template= url d",
             "git init --template= x", "npx prettier --write .", "npx eslint .", "npx husky --version", "npx husky --help", "echo husky install", "git commit -m 'husky install'", "npm install husky --save-dev",
             "npm i -D husky", "yarn add -D husky", "pnpm add husky", "cat .husky/pre-commit", "git config --local core.autocrlf false"]
cases_git = []
for agent in (None, "backend-engineer"):
    for c_ in GIT_DENY:
        cases_git.append(("D2 git/husky REFUSED %r%s" % (c_[:60], " (agent)" if agent else ""), "Bash", {"command": c_}, agent, True))
    for c_ in GIT_ALLOW:
        cases_git.append(("D2 git/husky allowed %r%s" % (c_[:60], " (agent)" if agent else ""), "Bash", {"command": c_}, agent, False))
    for pth_ in (HOME + "/Library/Python/3.9/lib/python/site-packages/x.pth", HOME + "/.local/lib/python3.11/site-packages/usercustomize.py"):
        cases_git.append(("m1 user site-packages write says it is a persistence file %s%s" % (pth_[-40:], " (agent)" if agent else ""), "Write", {"file_path": pth_, "content": "x"}, agent, True))
cases += cases_git
if os.environ.get("PERSIST_QUICK") == "git":                  # mutation runs only: the D2 / m1 cases alone (the default run is the whole table)
    cases = cases_git

# the corpus of 40 ordinary development edits that must stay allowed
CORPUS = [("Write", {"file_path": PROJ + "/src/app.py", "content": "x = 1\n"}), ("Write", {"file_path": PROJ + "/README.md", "content": "# t\n"}),
          ("Write", {"file_path": PROJ + "/package.json", "content": "{}\n"}), ("Write", {"file_path": PROJ + "/.gitignore", "content": "dist\n"}),
          ("Write", {"file_path": PROJ + "/.gitattributes", "content": "* text=auto\n"}), ("Write", {"file_path": PROJ + "/.editorconfig", "content": "root = true\n"}),
          ("Write", {"file_path": PROJ + "/.vscode/extensions.json", "content": '{"recommendations": []}'}), ("Write", {"file_path": PROJ + "/.vscode/launch.json", "content": '{"version": "0.2.0"}'}),
          ("Write", {"file_path": PROJ + "/.vscode/settings.json", "content": '{"editor.tabSize": 2}'}), ("Write", {"file_path": PROJ + "/.envrc.example", "content": "export A=\n"}),
          ("Write", {"file_path": PROJ + "/.env.example", "content": "A=\n"}), ("Write", {"file_path": PROJ + "/docs/guide.md", "content": "g\n"}),
          ("Write", {"file_path": PROJ + "/tests/test_x.py", "content": "def test(): pass\n"}), ("Write", {"file_path": PROJ + "/Makefile", "content": "all:\n"}),
          ("Write", {"file_path": PROJ + "/scripts/build.sh", "content": "#!/bin/sh\n"}), ("Write", {"file_path": PROJ + "/.github/ISSUE_TEMPLATE/bug.md", "content": "b\n"}),
          ("Write", {"file_path": PROJ + "/dotfiles/.zshrc", "content": "alias l=ls\n"}), ("Write", {"file_path": PROJ + "/templates/.gitconfig", "content": "[user]\n"}),
          ("Write", {"file_path": PROJ + "/docs/zshrc.md", "content": "z\n"}),           ("Write", {"file_path": HOME + "/.config/other/app.conf", "content": "x\n"}), ("Write", {"file_path": HOME + "/Library/Preferences/x.plist", "content": "x\n"}),
          ("Write", {"file_path": HOME + "/.config/gtk-3.0/x.css", "content": "x\n"}), ("Write", {"file_path": "/tmp/scratch.txt", "content": "x\n"}),
          ("Edit", {"file_path": PROJ + "/src/a.py", "old_string": "x", "new_string": "y"}), ("Edit", {"file_path": PROJ + "/.vscode/settings.json", "old_string": "2", "new_string": "4"}),
          ("Bash", {"command": "echo x > src/new.txt"}), ("Bash", {"command": "sed -i s/a/b/ src/a.py"}), ("Bash", {"command": "echo hi >> .gitignore"}),
          ("Bash", {"command": "git config --local user.name Ada"}), ("Bash", {"command": "git config user.email"}), ("Bash", {"command": "cat ~/.zshrc"}),
          ("Bash", {"command": "grep alias ~/.zshrc ~/.bashrc"}), ("Bash", {"command": "cp ~/.zshrc /tmp/zshrc.bak"}), ("Bash", {"command": "ls ~/Library/LaunchAgents"}),
          ("Bash", {"command": "tee /tmp/out.txt < /dev/null"}), ("Bash", {"command": "mv src/a.py src/b.py"}), ("Bash", {"command": "install -m 644 /tmp/a src/inst.txt"}),
          ("Bash", {"command": "cat ~/.gitconfig ~/.config/git/config"}), ("Bash", {"command": "python3 -c \"open('src/z.py','w').write('x')\""}),
          ("Bash", {"command": "echo 'export A=1' >> dotfiles/.zshrc"}), ("Bash", {"command": "cp .vscode/settings.json /tmp/settings.bak"}),
          ("Write", {"file_path": PROJ + "/.vscode/extensions.json", "content": "{}"}), ("Write", {"file_path": PROJ + "/.prettierrc", "content": "{}"}), ("Write", {"file_path": PROJ + "/.eslintrc.json", "content": "{}"}),
          ("Write", {"file_path": PROJ + "/pyproject.toml", "content": "[tool.black]\n"}), ("Write", {"file_path": PROJ + "/Dockerfile", "content": "FROM x\n"}), ("Write", {"file_path": PROJ + "/docker-compose.yml", "content": "a: 1\n"}),
          ("Write", {"file_path": PROJ + "/.github/workflows/ci.yml", "content": "on: push\n"}), ("Write", {"file_path": PROJ + "/.git-blame-ignore-revs", "content": "\n"}), ("Write", {"file_path": PROJ + "/.gitmodules", "content": "\n"}),
          ("Write", {"file_path": PROJ + "/hooks/useThing.ts", "content": "export {}\n"}), ("Write", {"file_path": PROJ + "/src/githooks.md", "content": "x\n"}), ("Write", {"file_path": PROJ + "/docs/husky.md", "content": "x\n"}),
          ("Write", {"file_path": PROJ + "/tools/mise.md", "content": "x\n"}), ("Write", {"file_path": PROJ + "/.vscode/launch.json", "content": "{}"}), ("Write", {"file_path": PROJ + "/.vscode/snippets.code-snippets", "content": "{}"}),
          ("Write", {"file_path": PROJ + "/.devcontainer/Dockerfile", "content": "FROM x\n"}), ("Write", {"file_path": PROJ + "/.ssh-notes.md", "content": "x\n"}), ("Write", {"file_path": PROJ + "/ssh/config.example", "content": "x\n"}),
          ("Write", {"file_path": PROJ + "/notes/.git-notes.txt", "content": "x\n"}), ("Write", {"file_path": HOME + "/.config/other/x.toml", "content": "x\n"}), ("Write", {"file_path": HOME + "/projects-notes.md", "content": "x\n"}),
          ("Edit", {"file_path": PROJ + "/.githooks-notes.md", "old_string": "a", "new_string": "b"}), ("Edit", {"file_path": PROJ + "/README.md", "old_string": "t", "new_string": "u"}),
          ("Bash", {"command": "npm test"}), ("Bash", {"command": "git commit -m 'fix hooks'"}), ("Bash", {"command": "git diff"}), ("Bash", {"command": "ls -la ~/.ssh"}), ("Bash", {"command": "cat ~/.ssh/config"}),
          ("Bash", {"command": "cat ~/.aws/config"}), ("Bash", {"command": "cat ~/.vimrc ~/.tmux.conf"}), ("Bash", {"command": "ls .git/hooks"}), ("Bash", {"command": "cat .devcontainer/devcontainer.json"}),
          ("Bash", {"command": "echo ok > /tmp/out.txt"}), ("Bash", {"command": "mkdir -p src/new && touch src/new/a.py"}), ("Bash", {"command": "echo y >> docs/notes.md"}), ("Bash", {"command": "mv docs/a.md docs/b.md"}),
          ("Bash", {"command": "cp -r src /tmp/src.bak"}), ("Bash", {"command": "sed -i s/a/b/ docs/guide.md"}), ("Bash", {"command": "tee docs/log.txt < /dev/null"}), ("Bash", {"command": "ln -s src /tmp/srclink"}),
          ("Bash", {"command": "python3 -c \"print(1)\""}), ("Bash", {"command": "echo 'a=1' > config/app.env"}), ("Bash", {"command": "echo '{}' > package-lock.json"}), ("Bash", {"command": "rm -f /tmp/zz.txt"}),
          ("Bash", {"command": "touch src/x.py"}), ("Bash", {"command": "echo x > .prettierrc"}), ("Bash", {"command": "head -5 .git/config"}), ("Bash", {"command": "git log -1 --format=%H"})]
for agent in (None, "backend-engineer"):
    for tool, ti in CORPUS:
        short = (ti.get("file_path") or ti.get("command")).replace(HOME, "~").replace(PROJ, "<proj>")
        cases.append(("corpus %s %s%s" % (tool, short[:60], " (agent)" if agent else ""), tool, ti, agent, False))
check("the benign corpus holds at least 80 ordinary edits and reads (plus the M-1 settings list as Write/Edit cases)", len(CORPUS) >= 80, len(CORPUS))

for label, hook in IMPLS:
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda c: run_cmd(hook, "", tool=c[1], ti=c[2], agent=c[3]), cases))
    wrong = 0
    for (name, _tool, _ti, _agent, want), o in zip(cases, res):
        if want:
            ok = deny(o) and ("runs code later" in text(o) or "control the team-flow" in text(o))
            if ok and not any(x_ in name for x_ in (".config/systemd", ".config/autostart", ".config/environment.d", ".claude/settings")):
                ok = "runs code later" in text(o) and "team-flow" not in text(o)         # a persistence file says so; it is not described as a team-flow file
        elif _agent is None and _tool == "Bash":
            ok = "These files control" not in text(o) and "shipm admin" not in text(o)         # the main chat's separate rule against shell writes to project files is not under test here
        else:
            ok = not deny(o)
        ok = ok and "Traceback" not in text(o)
        wrong += 0 if ok else 1
        check("%s %s %s" % (label, "REFUSED" if want else "allowed", name), ok, o)
    check("%s: %d cases, %d wrong" % (label, len(cases), wrong), wrong == 0)
for label, hook in IMPLS:
    ccd = str(p.T / "movedclaude")
    env_cc = dict(p.ENV, CLAUDE_CONFIG_DIR=ccd)
    for nm_ in ("settings.json", "settings.local.json"):
        for agent in (None, "backend-engineer"):
            o = run_cmd(hook, "", tool="Write", ti={"file_path": ccd + "/" + nm_, "content": "{}"}, agent=agent, env=env_cc)
            check("%s D14 #7 a moved CLAUDE_CONFIG_DIR/%s is a gate file%s" % (label, nm_, " (agent)" if agent else ""), deny(o), o)
    o = run_cmd(hook, "", tool="Write", ti={"file_path": ccd + "/notes.txt", "content": "x"}, agent="backend-engineer", env=env_cc)
    check("%s ... other files in it are not" % label, not deny(o), o)
    o = run_cmd(hook, "", tool="Write", ti={"file_path": ccd + "/settings.json", "content": "{}"}, agent="backend-engineer")
    check("%s ... and without the variable it is just another folder" % label, not deny(o), o)
for label, hook in IMPLS:
    realhome = os.path.realpath(HOME)
    link = str(p.T / "homelink")
    if not os.path.islink(link):
        os.symlink(realhome, link)
    env_l = dict(p.ENV, HOME=link)
    for agent in (None, "backend-engineer"):
        o = run_cmd(hook, "", tool="Write", ti={"file_path": realhome + "/Library/Python/3.9/lib/python/site-packages/x.pth", "content": "x"}, agent=agent, env=env_l)
        check("%s m2 symlinked HOME: the resolved user site-packages path is refused as a persistence file%s" % (label, " (agent)" if agent else ""), deny(o) and "runs code later" in text(o), o)
        o = run_cmd(hook, "", tool="Write", ti={"file_path": link + "/Library/Python/3.9/lib/python/site-packages/x.pth", "content": "x"}, agent=agent, env=env_l)
        check("%s m2 symlinked HOME: the path through the link is refused too%s" % (label, " (agent)" if agent else ""), deny(o) and "runs code later" in text(o), o)
        o = run_cmd(hook, "", tool="Write", ti={"file_path": realhome + "/Library/Python/3.9/lib/other/x.txt", "content": "x"}, agent=agent, env=env_l)
        check("%s m2 ... a neighbouring folder is not%s" % (label, " (agent)" if agent else ""), not deny(o), o)
check("hook errors log stays empty", p.errors() == "", p.errors())
print("persist tests: %d failed" % len(fails))
sys.exit(1 if fails else 0)
