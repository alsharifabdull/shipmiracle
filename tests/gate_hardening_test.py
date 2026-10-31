#!/usr/bin/env python3
"""gate_hardening_test: checklist D9, the security hardening of the gate and the hard stop (Linux security review M1-M3, m1-m5 and the older launcher spellings).
Both gate copies (the legacy shell gate where it exists, and shipmiracle/hooks/flow.py through the v1 shim) and the autopilot hard stop must
  M1  refuse `systemctl` start|restart|enable|link|edit|set-environment|daemon-reload|... (user or system instance, options in between, -M/-H) and refuse writes into
      ~/.config/systemd, ~/.config/autostart, ~/.config/environment.d (Bash and Write/Edit), but keep status / list-* / show / cat / is-* / help;
  M2  look through `env -S` / `--split-string` / `-iS` / `-S'...'` and judge the inner command like a command;
  M3  refuse gio launch, gtk-launch, kioclient exec, dex, exo-open, qdbus calls, dbus-launch, dbus-update-activation-environment, gsettings set, dconf write, pkexec, run0,
      flatpak-spawn --host (the hard stop also reads /proc/<pid>/environ and the keyring as secrets);
  B   refuse an execution-capable option or environment value that names shipm / claude / a launcher (git -c core.sshCommand=, GIT_SSH_COMMAND=, GIT_PAGER=, --upload-pack=,
      rsync -e, scp -S, ssh -o ProxyCommand=, man -P, less +!, every find -exec clause) and a direct run of tools/private/shipm-migrate.
Benign commands (status, list, a commit message that mentions systemd-run, grep/echo of the words, `GIT_EDITOR=true git rebase --continue`) stay allowed.
Run: python3 tests/gate_hardening_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation
import json, os, pathlib, re, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import flow_fixture as F
from flow_fixture import deny, text
from shipmiracle.autopilot import hardstop as H

fails = []


def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)[:500]))
    if not ok:
        fails.append(name)


HOME = os.path.realpath(os.environ["HOME"])
UNIT_VERBS = ["start", "restart", "reload-or-restart", "try-restart", "enable", "reenable", "link", "edit", "set-environment", "import-environment", "unset-environment",
              "daemon-reload", "preset", "mask", "revert", "add-wants", "add-requires"]
DENIED = (
    # M1: the verbs, user instance, system instance, options in between, remote / machine forms, wrappers
    ["systemctl --user %s x.service" % v for v in UNIT_VERBS]
    + ["systemctl %s x.service" % v for v in ("start", "enable", "daemon-reload", "restart", "mask")]
    + ["systemctl --user --now enable x.service", "systemctl --now --user enable x.service", "systemctl --user --no-block start x.service", "systemctl --user -M me@ start x.service",
       "systemctl --user --machine=me@ start x.service", "systemctl -H root@host restart x.service", "systemctl --user --quiet --no-pager daemon-reload",
       "sudo systemctl --user start x.service", "env systemctl --user start x.service", "/usr/bin/systemctl --user enable x.service", "SYSTEMCTL_X=1 systemctl --user start x",
       "bash -c 'systemctl --user start x.service'", "systemctl --user -- start x.service", "systemctl --user --type=service start x.service",
       "SYSTEMCTL=1 timeout 5 systemctl --user restart x.service", "FOO=1 systemctl --user start x"]
    # M2: env -S and friends
    + ["env -S 'systemd-run --user true'", "env -iS 'systemd-run --user true'", "env -S'systemd-run --user true'", "env --split-string='systemd-run --user true'",
       "env --split-string 'crontab -'", "env -S 'launchctl load x.plist'", "env -S 'systemctl --user start x'", "env -S 'FOO=1 systemd-run x'", "env -S\"systemd-run x\"",
       "env -i -S 'osascript /tmp/x.scpt'", "env -S 'crontab -e'", "env -u FOO -S 'tmux new-session -d x'", "env -S 'env -S \"systemd-run x\"'", "env -vS 'systemd-run x'",
       "env -S 'systemd-run x' y", "env FOO=1 -S 'systemd-run x'", "env -iS 'echo hi'", "env -i -S 'echo hi'", "env -iS'echo hi'",
       # review fixes: the env -S caps fail closed (more than 20 re-tokenisations, a value over 20000 characters), alias and power verbs, machinectl
       "env " + "-S " * 30 + "ls", "env -S 'echo " + "a" * 25000 + "'", "env --split-string=" + "a" * 25000,
       "systemctl --user condrestart x", "systemctl --user force-reload x", "systemctl --user reload-or-try-restart x", "systemctl --user condreload x", "systemctl --user daemon-reexec",
       "systemctl --user kill x", "systemctl --user freeze x", "systemctl --user thaw x", "systemctl --user set-property x CPUWeight=1", "systemctl set-default multi-user.target",
       "systemctl switch-root /new", "systemctl reboot", "systemctl poweroff", "systemctl halt", "systemctl suspend", "systemctl hibernate", "systemctl kexec", "systemctl rescue",
       "systemctl emergency", "systemctl hybrid-sleep", "systemctl soft-reboot", "systemctl --user try-reload-or-restart x",
       "machinectl shell me@.host", "machinectl login c", "machinectl start c", "machinectl enable c", "machinectl import-tar a.tar c", "machinectl import-raw a.raw c", "machinectl import-fs d c",
       "machinectl pull-tar http://x/a.tar", "machinectl --user shell x", "machinectl -H me@host shell x", "sudo machinectl shell x", "machinectl poweroff c", "machinectl terminate c",
       # names a launcher AND names shipm: refused like osascript (HARD_LAUNCHERS)
       "gsettings get shipm key", "dconf read shipm", "gio info shipm", "flatpak-spawn shipm", "kioclient5 ls shipm", "qdbus shipm", "gtk-launch shipm", "exo-open shipm"]
    # M3
    + ["gio launch x.desktop", "gtk-launch app", "kioclient exec x", "kioclient5 exec x.desktop", "kioclient6 exec x", "dex x.desktop", "exo-open --launch TerminalEmulator", "exo-open x.desktop",
       "qdbus org.x /x org.x.Run", "qdbus-qt5 org.x /x org.x.Run arg", "dbus-launch ls", "dbus-update-activation-environment --all", "dbus-update-activation-environment --systemd PATH",
       "gsettings set org.x k v", "gsettings reset org.x k", "gsettings reset-recursively org.x", "dconf write /a/b 1", "dconf load / < x.ini", "dconf reset /a/b", "pkexec ls", "run0 ls",
       "flatpak-spawn --host ls", "flatpak-spawn --host-env=A=b --host ls", "flatpak-spawn --forward-fd=1 --host ls", "sudo run0 ls", "gio  launch  x.desktop", "gio -- launch x.desktop"]
    # B: execution-capable option and environment values that name shipm / claude / a launcher
    + ["git -c core.sshCommand='shipm autopilot start' fetch", "git -c core.pager='shipm sync' log", "git -c core.editor='osascript /tmp/x.scpt' commit", "git -c core.sshCommand=systemd-run fetch",
       "git -c alias.x='!shipm autopilot stop' x", "git -c core.fsmonitor='tmux new-session -d x' status", "git -c diff.external='shipm sync' diff", "git -c sequence.editor='crontab -' rebase -i HEAD~2",
       "GIT_SSH_COMMAND='shipm autopilot start' git fetch", "GIT_SSH='systemd-run x' git fetch", "GIT_EXTERNAL_DIFF='shipm sync' git diff", "GIT_PAGER='shipm autopilot stop' git log",
       "PAGER='shipm autopilot stop' man ls", "EDITOR='shipm sync' git commit", "VISUAL='osascript x.scpt' git commit", "GIT_EDITOR='crontab -' git commit", "MANPAGER='systemd-run x' man ls",
       "LESSOPEN='|shipm sync %s' less x", "env GIT_PAGER='shipm sync' git log", "export GIT_SSH_COMMAND='shipm sync'", "GIT_ASKPASS='shipm sync' git fetch",
       "git fetch --upload-pack='shipm sync' origin", "git push --receive-pack='shipm sync' origin main", "git ls-remote --upload-pack 'shipm sync' origin", "git clone -u 'shipm sync' x y",
       "git fetch --upload-pack='osascript /tmp/x.scpt' origin", "git --exec-path=. fetch --upload-pack='tmux new x'",
       "rsync -e 'shipm sync' u@h:/tmp/a /tmp/out", "rsync --rsh='shipm sync' u@h:/tmp/a /tmp/out", "rsync --rsh 'systemd-run x' u@h:/tmp/a /tmp/out", "rsync -avze 'osascript x.scpt' u@h:/tmp/a /tmp/out", "rsync -e'shipm sync' u@h:/tmp/a /tmp/out",
       "rsync --rsync-path='shipm sync' u@h:/tmp/a /tmp/out", "scp -S 'shipm sync' u@h:/tmp/a /tmp/out", "sftp -S 'systemd-run x' b", "scp -S'shipm sync' u@h:/tmp/a /tmp/out",
       "ssh -o ProxyCommand='shipm sync' h", "ssh -o LocalCommand='shipm sync' h", "ssh -oProxyCommand='shipm sync' h", "ssh -o 'ProxyCommand shipm sync' h", "scp -o ProxyCommand='shipm sync' u@h:/tmp/a /tmp/out",
       "ssh -o ProxyCommand=systemd-run h", "man -P 'shipm sync' ls", "man -P'shipm sync' ls", "man --pager='shipm sync' ls", "man --pager 'osascript x' ls",
       "less '+!shipm autopilot start' f", "more '+!shipm sync' f", "less +'!systemd-run x' f",
       "find . -name x -exec systemd-run x \\;", "find . -name x -exec echo {} \\; -exec systemd-run x \\;", "find . -execdir osascript x.scpt \\;", "find . -ok tmux new x \\;",
       "find . -name x -exec sh -c 'shipm autopilot start' \\;", "find . -exec echo a \\; -exec sh -c 'systemd-run x' \\;", "find . -exec echo a {} + -execdir crontab - \\;",
       "echo x | xargs -I{} systemd-run {}", "echo x | xargs sh -c 'shipm autopilot start'", "echo a | xargs -n1 osascript /tmp/x.scpt",
       "busctl --address unix:path=/run/x call org.x /x org.x Run", "busctl -H me@host call org.x /x org.x Run", "busctl -M c call org.x /x org.x Run", "busctl --user set-property org.x /x org.x P s v",
       "busctl --system --user call org.x /x org.x Run", "gdbus --address unix:path=/run/x call --dest org.x --object-path /x --method org.x.Run", "busctl --user emit /x org.x Sig",
       "xdg-open run", "xdg-open ./run", "gio open run", "xdg-open tool.bin", "xdg-open 'run#1'", "xdg-open 'doc.txt '", "open run", "kde-open5 run", "xdg-open  --  run", "gnome-open run", "gvfs-open run",
       "tools/private/shipm-migrate", "./tools/private/shipm-migrate --apply", "bash tools/private/shipm-migrate", "python3 tools/private/shipm-migrate", "/x/tools/private/shipm-migrate --dry-run",
       "sh -c 'tools/private/shipm-migrate'", "env tools/private/shipm-migrate", "shipm-migrate", "python3 -I tools/private/shipm-migrate x"]
)
ALLOWED = [
    # M1
    "systemctl --user status", "systemctl --user list-units", "systemctl --user is-active x.service", "systemctl --user status x.service", "systemctl --user show x.service", "systemctl --user cat x.service",
    "systemctl --user is-enabled x.service", "systemctl --user list-timers", "systemctl status", "systemctl --user help", "systemctl --user list-unit-files", "systemctl is-system-running",
    "busctl --user list", "busctl --user tree org.x", "busctl --address unix:path=/run/x list", "busctl -H me@host status", "gdbus introspect --session --dest org.x --object-path /x",
    "xdg-open notes", "xdg-open readme.md", "xdg-open page.html", "xdg-open https://example.com/run", "xdg-open nothere", "gio open notes", "open notes", "open page.html", "xdg-open note.txt",
    "systemctl get-default", "systemctl --user get-default", "systemctl --user list-sockets", "systemctl --user show -p KillMode x", "systemctl --user show -p ExecStart x", "systemctl is-failed x",
    "machinectl list", "machinectl status c", "machinectl show c", "machinectl list-images", "machinectl --no-pager list",
    "systemctl --user list-dependencies", "systemctl --user show-environment", "systemctl --user --no-pager status x.service", "systemctl --user -p Id show x.service", "systemctl --version",
    "git commit -m 'mentions systemd-run'", "git commit -m 'systemctl --user start x is refused'", "grep -rn systemd-run docs", "echo systemd-run", "echo systemctl --user start x", "grep 'systemctl --user enable' README.md",
    "busctl --user status", "gio info x.txt", "gsettings get org.x k", "xdg-open https://example.com", "systemd-analyze verify x.service", "ls ~/.config/systemd/user",
    # M2
    "env -S 'ls -l'", "env -S 'echo hi'", "env FOO=1 true", "env -S'ls -l'", "env --split-string='echo hi'", "env", "env -u FOO ls", "env -S 'systemctl --user status'",
    # M3
    "gio open https://example.com", "gio mount -l", "gio trash old.txt", "gsettings list-keys org.x", "gsettings list-schemas", "dconf read /a/b", "dconf list /", "dconf dump /", "flatpak-spawn ls", "flatpak list",
    "qdbus", "qdbus org.x", "qdbus org.x /x", "kioclient5 ls", "exo-open https://example.com", "gio info -a standard::name x",
    # B: ordinary values stay allowed
    "git -c core.sshCommand='ssh -i key' fetch", "git -c user.name='Ada' commit -m x", "git -c core.pager=cat log", "git -c core.editor=true commit", "GIT_EDITOR=true git rebase --continue",
    "GIT_SSH_COMMAND='ssh -i key' git fetch", "GIT_PAGER=cat git log", "PAGER=less man ls", "EDITOR=vim git commit", "VISUAL=true git commit", "GIT_EXTERNAL_DIFF=difft git diff",
    "git fetch --upload-pack=git-upload-pack origin", "git push -u origin main", "git push --set-upstream origin x", "git clone -u git-upload-pack x y", "git commit -m 'shipm autopilot start docs'",
    "rsync -e 'ssh -p 22' u@h:/tmp/a /tmp/out", "rsync -avz -e ssh u@h:/tmp/a /tmp/out", "rsync --rsh='ssh -i k' u@h:/tmp/a /tmp/out", "scp -S /usr/bin/ssh u@h:/tmp/a /tmp/out", "scp -P 22 u@h:/tmp/a /tmp/out", "sftp -S /usr/bin/ssh b",
    "ssh -o ProxyCommand='ssh -W %h:%p jump' h", "ssh -o StrictHostKeyChecking=no h", "ssh -o LocalCommand=true h", "man -P cat ls", "man ls", "man --pager=less ls", "less README.md", "less +G README.md", "more README.md",
    "less '+/shipm' README.md", "grep -n shipm README.md",
    "find . -name x -exec echo {} \\;", "find . -name '*.py' -exec grep -l shipment {} +", "find . -exec ls -l {} \\; -exec echo done \\;", "find . -execdir cat {} \\;", "find . -name shipm", "echo x | xargs echo",
    "echo a b | xargs -n1 echo", "ls | xargs wc -l", "cat tools/private/shipm-migrate", "grep -n x tools/private/shipm-migrate", "git add tools/private/shipm-migrate", "ls tools/private", "head -3 tools/private/shipm-migrate",
    "python3 -m py_compile tools/private/shipm-migrate", "git log --oneline -- tools/private/shipm-migrate", "echo shipm-migrate",
]
# the hard stop refuses every launcher in any form (by design), so these gate-allowed names differ
HS_ONLY_DENIED = ["machinectl list", "env -S 'ls -l'", "env --split-string='echo hi'", "env -iS 'ls'", "env -S'ls'", "env -vS 'ls'",       # the hard stop keeps its H9 for any env -S (ENVSPLIT marker)
                  "gio info x.txt", "gsettings get org.x k", "dconf read /a/b", "flatpak-spawn ls", "qdbus", "xdg-open https://example.com"]

# writes into the persistence folders: Bash (many spellings) and Write / Edit
PERSIST_DIRS = [".config/systemd/user", ".config/autostart", ".config/environment.d"]
BASH_WRITES = ["echo x > {p}/x.service", "echo x >> {p}/x.service", "printf x | tee {p}/x.service", "tee {p}/x.service < /dev/null", "cp /tmp/a {p}/x.service", "mv /tmp/a {p}/x.service",
               "install -m 644 /tmp/a {p}/x.service", "ln -s /tmp/a {p}/x.service", "sed -i s/a/b/ {p}/x.service", "python3 -c \"open('{p}/x.service','w').write('x')\"",
               "cat > {p}/x.service <<EOF\nx\nEOF", "rm {p}/x.service", "touch {p}/x.service", "cp -r /tmp/a {p}/"]
BASH_READS = ["cat {p}/x.service", "ls {p}", "cp {p}/x.service /tmp/x", "grep -n Exec {p}/x.service", "head -3 {p}/x.service", "ls -l {p}/", "wc -l {p}/x.service"]
BASH_OTHER = ["echo x > {h}/.config/other/x.service", "cp /tmp/a {h}/.config/gtk-3.0/x.css", "echo x > {h}/.config/systemd-notes.txt"]

p = F.make_project()
p.put("src/a.py", "x\n")
for _n, _exec in (("run", True), ("tool.bin", True), ("doc.txt ", True), ("page.html", True), ("notes", False), ("readme.md", False), ("note.txt", True)):
    _f = p.put(_n, "#!/bin/sh\nexit 0\n"); os.chmod(_f, 0o755 if _exec else 0o644)      # files in the project folder: the hook runs with that folder as its working directory
p.prompt()
IMPLS = []
if F.LEGACY_HOOK.exists():
    IMPLS.append(("legacy shell gate", str(F.LEGACY_HOOK)))
IMPLS.append(("v1 gate (shipmiracle/hooks/flow.py)", str(F.V1_HOOK)))
cnt = [0]
home = os.environ["HOME"]


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


for label, hook in IMPLS:
    with ThreadPoolExecutor(6) as ex:
        den = list(ex.map(lambda c: run_cmd(hook, c), DENIED))
        alw = list(ex.map(lambda c: run_cmd(hook, c), ALLOWED))
    for c, o in zip(DENIED, den):
        check("%s DENIED: %r" % (label, c[:70]), deny(o) and "Traceback" not in text(o), o)
    for c, o in zip(ALLOWED, alw):
        check("%s ALLOWED: %r" % (label, c[:70]), not deny(o), o)
    # protected write targets: Bash and the file tools, main chat and agent
    wr = [(c.format(p=hm + "/" + d), True) for d in PERSIST_DIRS for hm in (home,) for c in BASH_WRITES]
    wr += [(c.format(p=hm + "/" + d), False) for d in PERSIST_DIRS for hm in (home,) for c in BASH_READS]
    wr += [(c.format(h=home), False) for c in BASH_OTHER]
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda t: run_cmd(hook, t[0]), wr))
    for (c, want), o in zip(wr, res):
        check("%s Bash %s %r" % (label, "REFUSED" if want else "allowed", c[:70].replace(home, "~")), deny(o) == want, o)
    for d in PERSIST_DIRS:
        for name in ("x.service", "sub/y.conf", "10-x.conf"):
            for agent in (None, "backend-engineer"):
                for tool in ("Write", "Edit"):
                    ti = {"file_path": "%s/%s/%s" % (home, d, name)}
                    ti.update({"content": "x"} if tool == "Write" else {"old_string": "a", "new_string": "b"})
                    o = run_cmd(hook, "", tool=tool, ti=ti, agent=agent)
                    check("%s %s %s/%s is refused%s" % (label, tool, d, name, " (agent)" if agent else ""), deny(o), o)
    o = run_cmd(hook, "", tool="Write", ti={"file_path": home + "/.config/gtk-3.0/x.css", "content": "x"}, agent="backend-engineer")
    check("%s Write of ~/.config/gtk-3.0/x.css is not a gate path (no tamper refusal)" % label, "These files control" not in text(o), o)
    # an absolute XDG_CONFIG_HOME moves the three folders with it; a relative one is not a path the gate can trust and moves nothing
    xdg = str(p.T / "xdgcfg")
    for sub in ("systemd/user/x.service", "autostart/x.desktop", "environment.d/10-x.conf"):
        o = run_cmd(hook, "", tool="Write", ti={"file_path": "%s/%s" % (xdg, sub), "content": "x"}, agent="backend-engineer", env=dict(p.ENV, XDG_CONFIG_HOME=xdg))
        check("%s Write %s below an absolute XDG_CONFIG_HOME is refused" % (label, sub), deny(o), o)
        o = run_cmd(hook, "", tool="Write", ti={"file_path": "%s/%s" % (xdg, sub), "content": "x"}, agent="backend-engineer")
        check("%s Write %s below a folder that is not XDG_CONFIG_HOME is not a gate path" % (label, sub), "These files control" not in text(o), o)
    o = run_cmd(hook, "", tool="Write", ti={"file_path": "%s/other/x" % xdg, "content": "x"}, agent="backend-engineer", env=dict(p.ENV, XDG_CONFIG_HOME=xdg))
    check("%s Write %s/other/x is not a gate path" % (label, "XDG"), "These files control" not in text(o), o)
check("hook errors log stays empty", p.errors() == "", p.errors())

# ------------------------------------------------------------------ the autopilot hard stop
WT = pathlib.Path(tempfile.mkdtemp()).resolve() / "dev" / ".worktrees" / "sandbox" / "auto-CR-012"
WT.mkdir(parents=True)
(WT / "src").mkdir(); (WT / "src/a.py").write_text("x\n"); (WT / "docs").mkdir(); (WT / "docs/STATUS.md").write_text("s\n")


def hs(cmd, tool="Bash", ti=None):
    c = H.Ctx(root=str(WT), base_sha="abc123", scope=["src/**"], tracked=lambda rel: ["src/a.py"], changed=set(), read_text=lambda r: None, added_text=lambda r: None,
              home=HOME, tmp_roots=["/tmp", "/private/tmp"], active_cr="CR-012", ends=["CR-012"], auto_branch="auto/CR-012", ahead=1)
    return H.check("PreToolUse", tool, ti or {"command": cmd}, str(WT), c)


H.RAISE = True
for c in DENIED + HS_ONLY_DENIED:
    if c == "open run":
        continue                                                  # the hard stop looks at the opener's extension only (no such file in its worktree)
    if c.startswith(("tools/private", "./tools/private", "bash tools", "python3 tools", "/x/tools", "sh -c 'tools", "env tools", "shipm-migrate", "python3 -I tools")):
        continue                                                  # shipm-migrate is refused by the gate's admin set; the hard stop sees it through the same admin_seg (checked below)
    got = hs(c)
    check("hard stop DENIED: %r" % c[:70], bool(got), [s.rule for s in got])
for c in DENIED:
    if c.startswith(("tools/private", "./tools/private", "bash tools", "python3 tools", "/x/tools", "sh -c 'tools", "env tools", "shipm-migrate", "python3 -I tools")):
        got = hs(c)
        check("hard stop DENIED (admin set): %r" % c[:70], bool(got), [s.rule for s in got])
for c in ("ls src", "cat src/a.py", "git status", "echo systemctl --user start x", "git commit -m 'mentions systemd-run'", "grep -rn systemd-run src", "cat tools/private/shipm-migrate"):
    check("hard stop ALLOWED: %r" % c, not hs(c), [(s.rule, s.text[:60]) for s in hs(c)])
for d in PERSIST_DIRS:
    for c in ("echo x > {p}/x.service", "cp x {p}/x.desktop", "tee {p}/x.conf < /dev/null"):
        c = c.format(p=HOME + "/" + d)
        check("hard stop refuses a write to a persistence folder: %r" % c.replace(HOME, "~"), bool(hs(c)), [])
    got = hs("", tool="Write", ti={"file_path": HOME + "/" + d + "/x.conf", "content": "x"})
    check("hard stop refuses the Write tool in ~/%s" % d, bool(got), [])
# secrets that are read: /proc/<pid>/environ (another process's environment) and the keyring; the own environment (/proc/self) stays readable like `env`
SECRET_READS = ["cat /proc/1/environ", "cat /proc/12345/environ", "cat /proc/$PPID/environ", "cat /proc/*/environ", "cat /proc/${PPID}/environ", "cat /proc/$$/environ", "cat '/proc/$PPID/environ'", "cat /proc/$(pgrep -n x)/environ", "tr '\\0' '\\n' < /proc/1/environ", "strings /proc/999/environ",
                "cat /proc/self/../1/environ", "cat /proc/self/task/../../1/environ", "cat %s/.local/share/keyrings/login.keyring" % HOME, "ls %s/.local/share/keyrings" % HOME,
                "cat ~/.local/share/keyrings/login.keyring", "grep x %s/.local/share/keyrings/*" % HOME, "cat /proc/1/task/1/environ"]
for c in SECRET_READS:
    got = hs(c)
    check("hard stop refuses to read %r" % c.replace(HOME, "~")[:70], bool(got), [])
for tool, path in (("Read", "/proc/1/environ"), ("Read", "/proc/4242/environ"), ("Read", HOME + "/.local/share/keyrings/login.keyring"), ("Grep", HOME + "/.local/share/keyrings")):
    got = hs("", tool=tool, ti={"file_path": path, "path": path, "pattern": "x"})
    check("hard stop refuses %s of %s" % (tool, path.replace(HOME, "~")), bool(got), [])
print("INFO documented limit (DECISIONS D9 review fixes): hard stop on `cd /proc/123 && cat environ` -> %s" % ([x.rule for x in hs("cd /proc/123 && cat environ")] or "not seen"))
for c in ("cat /proc/self/environ", "cat /proc/cpuinfo", "cat /proc/self/status", "cat /proc/1/status", "ls /proc/1", "cat /proc/meminfo", "env", "printenv HOME"):
    check("hard stop allows %r" % c, not hs(c), [(s.rule, s.text[:60]) for s in hs(c)])
got = hs("", tool="Read", ti={"file_path": "/proc/self/environ"})
check("hard stop allows Read of /proc/self/environ (like `env`)", not got, [(s.rule, s.text[:60]) for s in got])

def mkrun():
    return H._Run(H.Ctx(root=str(WT), base_sha="abc", scope=["src/**"], tracked=lambda rel: [], changed=set(), read_text=lambda r: None, added_text=lambda r: None,
                        home=HOME, tmp_roots=["/tmp"], active_cr="CR-012", ends=["CR-012"], auto_branch="auto/CR-012", ahead=1), str(WT))


# m1: docs/STATUS.md is exempt from the limits/scope rule by exact name where the file system keeps case; a case variant is a different file there
real_platform = sys.platform
try:
    sys.platform = "linux"
    os.environ.pop("SHIPMIRACLE_FAKE_OS", None)
    run = mkrun()
    for rel, want in (("docs/STATUS.md", True), ("docs/DECISIONS.md", True), ("DOCS/STATUS.MD", False), ("docs/status.md", False), ("Docs/Decisions.md", False), ("docs/STATUS.md.bak", False)):
        got = run.in_scope(rel) if run else None
        check("case-sensitive file system: in_scope(%r) record exemption is %s" % (rel, want), got is want, got)
    sys.platform = "darwin"
    for rel, want in (("docs/STATUS.md", True), ("DOCS/STATUS.MD", True), ("docs/status.md", True)):
        got = run.in_scope(rel) if run else None
        check("case-insensitive file system (macOS): in_scope(%r) is %s" % (rel, want), got is want, got)
    # the limit rule (H8): the same exact-name rule for the file tools
    sys.platform = "linux"
    check("record exemption helper exists (is_record)", run is not None and hasattr(run, "is_record"))
    if run is not None and hasattr(run, "is_record"):
        check("is_record exact on Linux", run.is_record("docs/STATUS.md") and not run.is_record("DOCS/STATUS.MD"))
        sys.platform = "darwin"
        check("is_record folded on macOS", run.is_record("DOCS/STATUS.MD"))
    # m4: protected() compares case-folded on every OS, like the gate's pfold
    sys.platform = "linux"
    run2 = mkrun()
    for pth in (HOME + "/.CONFIG/SYSTEMD/user/x.service", HOME + "/.Config/Autostart/x.desktop", HOME + "/.config/ENVIRONMENT.D/x.conf", HOME + "/.SSH/id_rsa", HOME + "/.Local/Share/Keyrings/x"):
        check("protected() folds case on Linux: %s" % pth.replace(HOME, "~"), run2.protected(pth), [])
    check("protected() leaves an ordinary Linux path alone", not run2.protected(HOME + "/.config/other/x"), [])
finally:
    sys.platform = real_platform

from shipmiracle.autopilot import rules as R
for c in ("gio", "gtk-launch", "kioclient", "kioclient5", "dex", "exo-open", "qdbus", "dbus-launch", "dbus-update-activation-environment", "gsettings", "dconf", "pkexec", "run0", "flatpak-spawn", "machinectl"):
    check("persist table (rules.PERSIST_CMDS) names %s" % c, c in R.PERSIST_CMDS)

p.cleanup()
print("\nFAILED: %d" % len(fails) if fails else "\nALL PASS")
sys.exit(1 if fails else 0)
