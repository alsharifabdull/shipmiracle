#!/usr/bin/env python3
"""Flow gate Bash pre-check (bash_targets): table-driven refuse/allow rows, warn and off levels, fallback, timing.
Run: python3 tests/flow_gate_bash_test.py"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import shipmiracle_isolation; shipmiracle_isolation.apply_to_environ()   # test isolation: fresh HOME/SHIPMIRACLE_HOME/CONFIG/STATE unless already temp
import json, os, pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import flow_fixture as F
from flow_fixture import deny, note

fails = []
def check(n, c, info=""):
    print(("PASS " if c else "FAIL ") + n + ("" if c else " " + str(info)[:300]))
    if not c: fails.append(n)

p = F.make_project()
p.put("src/my file.py", "x\n"); p.put("src/a.js", "x\n"); p.put("src/app.py", "x = 1\n")
p.put("lib/a.py", "x\n")
p.prompt()

REFUSE = [
    ("cp /tmp/x src/app.py", None),
    ("cp -R lib/ src/", None),
    ("mv src/app.py src/main.py", None),
    ("mv src/app.py /tmp/", None),
    ("install -m644 x src/y", None),
    ("rsync -a /tmp/x/ src/", None),
    ("dd if=/dev/zero of=src/b.bin count=1", None),
    ("git apply /tmp/p.diff", None),
    ("git -C . apply p.diff", None),
    ("patch -p1 < /tmp/p.diff", None),
    ("""python3 -c "open('src/app.py','w').write('x')" """, None),
    ("""python3 -c 'import pathlib; pathlib.Path("src/app.py").write_text("x")'""", None),
    ("python3 - <<EOF\nimport shutil\nshutil.copy('/tmp/x', 'src/app.py')\nEOF", None),
    ("""node -e "require('fs').writeFileSync('src/a.js','x')" """, None),
    ("cat <<EOF > src/new.py\nprint(1)\nEOF", None),
    ("cat > src/new.py <<EOF\nprint(1)\nEOF", None),
    ('echo x > "$(pwd)/src/app.py"', None),
    ("echo x > `pwd`/src/app.py", None),
    ("echo x > $(git rev-parse --show-toplevel)/src/app.py", None),
    ('echo x > "$CLAUDE_PROJECT_DIR/src/app.py"', None),
    ("echo x > $(foo)/src/app.py", None),
    ("echo x 2> src/err.log", None),
    ("echo x &> src/o.txt", None),
    ('echo x > "src/my file.py"', None),
    ("echo x > src/my\\ file.py", None),
    ("cd src && echo x > app.py", None),
    ("echo x > app.py", "src"),                                   # hook cwd is a subfolder
    ("perl -pi -e s/a/b/ src/app.py", None),
    ("sed -i '' 's/a/b/' src/app.py", None),
    ("echo x | tee src/a src/b", None),
    ('bash -c "echo x > src/app.py"', None),
    ("(cd /tmp; true); echo x > src/app.py", None),
    ("git commit -m ok && echo x > src/app.py", None),
    ('echo "unterminated > src/app.py', None),                    # shlex error: regex fallback still refuses
    ("cp --target-directory=src /tmp/x", None),
    ("cp -t src /tmp/x", None),
    ("cp /tmp/x -t src", None),
    ("mv -t /tmp src/app.py", None),
    ("mv --target-directory=src /tmp/a", None),
    ("truncate -s 0 src/app.py", None),
    ("""awk '{print > "src/out.txt"}' /tmp/in""", None),
    ("""awk '{print >> "src/out.txt"}' /tmp/in""", None),
    ("sed -n 'w src/out.txt' /tmp/in", None),
    ("sed 's/a/b/w src/out.txt' /tmp/in", None),
    ("cat <<EOF | python3 -\nopen('src/app.py','w').write('x')\nEOF", None),
    ("cat <<'EOF' | bash\necho x > src/app.py\nEOF", None),
    ("pushd /tmp; popd; echo x > app.py", None),
    ("echo x > .env", None),
    ("echo x > .gitignore", None),
    ("x=5; [[ $x > 3 ]] && echo y > src/app.py", None),
    ("[[ -f x ]]; echo y > src/app.py", None),
    ("(( a > b )); echo y > src/app.py", None),
    ("echo x > $HOME/" + "../" * (len(os.path.realpath(os.environ.get("HOME", "/x")).split("/")) - 1) + str(p.P).lstrip("/") + "/src/app.py", None),     # enough ../ to reach / from any HOME depth (a temp HOME is deep)
    ("echo x >! src/app.py", None),                               # zsh clobber redirects
    ("echo x >>! src/app.py", None),
    ("echo x >| src/app.py", None),
    ("echo x >!src/app.py", None),
    ("""awk 'BEGIN{print "x" > "src/app.py"}'""", None),
    ("""awk '{print "a" "b" >> "src/o"}' /tmp/in""", None),
    ("""awk 'BEGIN{printf "%s\\n","x" > "src/app.py"}'""", None),
    ("ex -sc 'wq' src/app.py", None),
    ("ed -s src/app.py <<EOF\nw\nq\nEOF", None),
    ("ex src/app.py", None),
]
ALLOW = [
    ('git commit -m "a -> b > c"', None),
    ('git commit -m "fix: a -> b"', None),
    ("git commit -F - <<EOF\nmessage\n> src/app.py\nEOF", None),
    ("git commit -m \"$(cat <<'EOF'\ndon't touch\n> src/app.py\nEOF\n)\"", None),
    ("ls > /tmp/x 2>&1", None),
    ("cp src/app.py /tmp/", None),
    ("cd /tmp && cp a b", None),
    ("mv /tmp/a /tmp/b", None),
    ("""python3 -c "print(open('src/app.py').read())" """, None),
    ("python3 - <<EOF\nopen('docs/STATUS.md', 'a').write('x')\nEOF", None),
    ("echo x >> docs/STATUS.md", None),
    ("cat > $P/settings.json", None),
    ('cp x "$TMPDIR/y"', None),
    ("git apply --check p.diff", None),
    ("""node -e "fs.writeFileSync(p,x)" """, None),
    ("echo x > $(foo)/nothere.txt", None),
    ("echo x > /dev/null", None),
    ("grep '>' src/app.py", None),
    ("ls", None),
    ("git status", None),
    ("", None),
    ("rm src/x", None),
    ("echo x > ../outside.txt", None),
    ("pushd /tmp; echo x > app.py", None),
    ("x=5; [[ $x > 3 ]] && echo y", None),
    ("if [[ $a < $b ]]; then echo y; fi", None),
    ("(( a > b )) && echo y", None),
    ("echo $(( 3 > 2 ))", None),
    ("echo x > .git/info/exclude", None),
    ("git commit -F - <<EOF\nmsg\n  EOF  \n> src/app.py\nEOF", None),
    ("rsync -t /tmp/a /tmp/b", None),
    ("""awk '{print "a" > "/tmp/o"}' /tmp/in""", None),
    ("""awk '{print "a > b"}' /tmp/in""", None),
    ("ex -sc 'wq' /tmp/x", None),
    ("echo x >! /tmp/x", None),
]
# gate paths (tamper): refused for the main chat with the plain tamper message, even where the source-write check would allow them
TAMPER = [
    "mv ~/.claude ~/.claude.bak", f"mv {p.WSF} /tmp/x", f"rm -rf {p.WSF}/hooks", f"rm -rf {p.WSF}", f"rm -rf {p.STATE}", "rm -rf ~/.claude", f"mv {p.P}/.claude /tmp/c",
    f"find {p.WSF}/hooks -delete", f"find {p.WSF} -name '*.sh' -exec rm {{}} +", f"ed {p.WSF}/hooks/a.sh", f"ditto /tmp/x {p.WSF}/hooks/a.sh",
    f"ln -s {p.WSF}/config/flow.json /tmp/lnk", f"ln -sf /tmp/x {p.WSF}/config/flow.json",
    "cd - && echo x > .claude/settings.json", "cd $SOMEWHERE && echo x > .claude/hooks/a.sh", "cd $SOMEWHERE && cp /tmp/x .claude/settings.local.json", "cd $D && rm -rf .claude/agents", "cd - ; echo x > config/flow.json", "export HOME=/tmp/h; echo x > $HOME/.claude/settings.json",
    "HOME=/tmp/h cp /tmp/x ~/.claude/hooks/y",
    f"echo x > {p.P}/.claude/hooks/x.sh", f"cp /tmp/x {p.P}/.claude/hooks/new.sh", f"rm -rf {p.P}/.claude/hooks", "echo x > ~/.claude/hooks/y.sh", "tee .claude/hooks/z.sh",
    f"""python3 -c "open('{p.WSF}/config/flow.json','w').write('x')" """, f"""python3 -c "open('{p.P}/.claude/settings.local.json', 'w').write('x')" """,
    f"""node -e "require('fs').writeFileSync('{p.P}/.claude/hooks/a.sh','x')" """, """python3 -c "open('.claude/settings.json','w')" """,
    """cd $X && python3 -c "open('settings.json','w')" """, "export HOME=/tmp; echo x > ~/.claude/settings.json", "rm -rf .", f"rm -rf {p.P}", "find . -delete", "find . -name settings.json -delete",
    "ln -sfn /tmp/evil ~/.local/share/shipmiracle/engine", "echo x > ~/.local/share/shipmiracle/engine/hooks/x.sh", "rm -rf ~/.local/share/shipmiracle", "cp /tmp/x $HOME/.local/share/shipmiracle/engine",   # L4: the engine link folder
    "find .claude -name '*.md' -delete", f"find {p.WSF} -type f -exec rm -f {{}} +", "echo x >! ~/.claude/settings.json", "echo x >| ~/.claude/settings.json",
]
TAMPER_OK = ["export HOME=/tmp", "find . -name '*.pyc' -delete", "find . -name x -exec rm {} +", "find . -type f -exec rm -f {} \\;", "ls ~/.claude", "rm -rf /tmp/zz", "mv /tmp/a /tmp/b", f"cat {p.WSF}/config/flow.json", "cd - ; echo x > /tmp/ok", "rm -rf src/build", f"find {p.P}/src -name x",
             """python3 -c "print(open('/tmp/zz/flow.json').read())" """, "echo hi > /tmp/hooks/x",
             'cd "$APP_DIR" && echo x > src/hooks/useX.ts', 'cd "$D" && cp a.json .claude-backup/x', """python3 -c "open('.idea/settings.json','w')" """,       # D14 M1: .vscode/settings.json is now judged by content (python computes it: refused, see gate_persist_test); another editor folder's settings.json keeps the old point of this case: a settings.json outside .claude is no gate file
             """python3 -c "open('/tmp/settings.json','w')" """, """node -e "require('fs').writeFileSync('/tmp/out/flow.json','x')" """, 'echo "abc > $OUT/hooks/x',
             """python3 -c "open('/tmp/zz/flow.json','w').write('x')" """, """cd $X && python3 -c "open('/tmp/zz/settings.json','w')" """, "cd $SOMEWHERE && cat hooks" "/a.sh",
             "echo x > docs/STATUS.md"]

from concurrent.futures import ThreadPoolExecutor
_n = [0]
def run_many(jobs):
    """jobs: [(command, extra hook kwargs)]. Every job gets its own session, so they are independent (and a fresh session has no refusals yet): run 8 at a time."""
    def one(j):
        i, (cmd, kw) = j
        return p.hook("PreToolUse", f"j{i}", tool_name="Bash", tool_input={"command": cmd}, **kw)
    base = _n[0]; _n[0] += len(jobs)
    with ThreadPoolExecutor(8) as ex:
        return list(ex.map(one, [(base + i, j) for i, j in enumerate(jobs)]))
AG = {"agent_id": "a", "agent_type": "backend-engineer"}
for (cmd, cwd), o in zip(REFUSE, run_many([(c, {"cwd": str(p.P / w)} if w else {}) for c, w in REFUSE])):
    check("refuse: " + repr(cmd)[:70], deny(o), o)
for (cmd, cwd), o in zip(ALLOW, run_many([(c, {"cwd": str(p.P / w)} if w else {}) for c, w in ALLOW])):
    check("allow:  " + repr(cmd)[:70], not deny(o), o)
for cmd, o in zip(TAMPER, run_many([(c, {}) for c in TAMPER])):
    check("tamper refuse: " + repr(cmd)[:70], deny(o) and ("control the team-flow" in json.dumps(o) or ((cmd.startswith(("find ", "cd -")) or "HOME=" in cmd) and "Project isolation" in json.dumps(o))), o)   # G11: a find rooted at the whole workspace is refused by project isolation first (no exemption: it was spoofable)
for cmd, o, oa in zip(TAMPER_OK, run_many([(c, {}) for c in TAMPER_OK]), run_many([(c, AG) for c in TAMPER_OK])):
    check("tamper allow:  " + repr(cmd)[:70], not deny(o) or "control the team-flow" not in json.dumps(o), o)   # main chat: the source-write check may still refuse project files
    check("tamper allow (agent): " + repr(cmd)[:70], not deny(oa), oa)

_lk = os.path.join(os.environ["HOME"], ".local/share/shipmiracle/engine")
for _ag in (None, "backend-engineer"):
    check("L4 Write/Edit into ~/.local/share/shipmiracle (engine link folder) refused" + (" (agent)" if _ag else ""),
          all(deny(o) for o in (p.pre("Write", {"file_path": _lk, "content": "x"}, agent=_ag), p.pre("Edit", {"file_path": _lk + "/hooks/a.sh", "old_string": "a", "new_string": "b"}, agent=_ag))))
# Owner proof (OP6): wrappers that run their arguments, raw command text and launchers. Both gate copies; each refusal is ONE plain sentence naming what to run instead.
OP_DENY = ["script -q /dev/null shipm autopilot checkpoint", "script -q /dev/null env -u CLAUDECODE shipm autopilot start", "expect -c 'spawn shipm autopilot admit CR-1'",
           "unbuffer shipm autopilot allow H-aaaaaa", "python3 -c \"import subprocess;subprocess.run(['shipm','autopilot','checkpoint'])\"",
           "osascript -e 'tell application \"Terminal\" to do script \"shipm autopilot checkpoint\"'", "tmux send-keys -t 0 'shipm autopilot checkpoint' Enter",
           "env -i PATH=$PATH shipm autopilot resume", "timeout 5 shipm autopilot drop CR-1", "launchctl submit -l x -- shipm autopilot start", "echo 'shipm autopilot checkpoint' | at now",
           "stdbuf -oL shipm autopilot admit CR-2", "setsid shipm autopilot checkpoint", "caffeinate -t 5 shipm autopilot allow H-aaaaaa", "flock /tmp/x shipm autopilot start",
           "python3 - <<'EOF'\nimport subprocess\nsubprocess.run(['shipm', 'autopilot', 'probe', 'pass'])\nEOF", "bash -c 'script -q /dev/null shipm autopilot checkpoint'",
           "ruby -e 'system(\"shipm autopilot start\")'", "perl -e 'system(\"shipm\", \"switch\", \"autopilot.standing.enabled\", \"on\")'", "tmux new-session -d 'claude'"]
import base64 as _b64
_enc = lambda t: _b64.b64encode(t.encode("utf-16-le")).decode()
OP_DENY += ["powershell.exe -EncodedCommand " + _enc("wsl shipm autopilot start"), "pwsh -enc " + _enc("wsl shipm autopilot resume"), "powershell -NoProfile -e not-base64!!",
            "wt.exe wsl shipm autopilot resume", "cmd.exe /c start wsl shipm autopilot drop CR-1", "schtasks.exe /create /tn x /tr \"wsl shipm autopilot allow H-1\"",
            "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -c \"(New-Object -ComObject WScript.Shell).SendKeys('claude')\"",
            "xdotool type 'shipm autopilot checkpoint'", "systemd-run --user shipm autopilot start", "gnome-terminal -- shipm autopilot checkpoint",
            "wsl.exe -d Ubuntu -u me shipm autopilot start", "runuser -u me -- shipm autopilot start", "ionice -c 3 shipm autopilot admit CR-1", "taskset 0x1 shipm autopilot allow H-1",
            "chrt -f 1 shipm autopilot resume", "systemd-inhibit --what=idle shipm autopilot checkpoint", "wezterm cli send-text 'shipm autopilot start'"]
OP_ALLOW = ["shipm autopilot show", "shipm autopilot charter show", "grep -n autopilot shipmiracle/autopilot/cli.py", "rg \"cmd_checkpoint\" shipmiracle/", "osascript -e 'display notification \"x\"'",
            "tmux ls", "tmux display-message hi", "tmux list-sessions", "open https://example.org", "open notes.pdf", "open .", "launchctl list", "crontab -l", "osascript -e 'display notification \"done\" with title \"shipm\"'", "cat shipmiracle/autopilot/cli.py", "git commit -q -m \"Option C: shipm autopilot checkpoint and admit\"",
            "git log --oneline --grep='shipm autopilot checkpoint'", "python3 -c \"print('autopilot')\"", "ls shipmiracle/autopilot && git status", "sed -n 1,5p shipmiracle/autopilot/state.py",
            "powershell.exe -c Get-Date", "cmd.exe /c dir", "wsl.exe -l -v", "wt.exe", "xdotool getactivewindow", "gnome-terminal --version", "systemd-run --version", "schtasks.exe /query", "timeout 5 ls", "script -q /dev/null ls", "stdbuf -oL echo hi", "caffeinate -t 5 ls", "open -a Calculator", "launchctl list"]
# Review round 2 (F1-F4): the files that decide who counts as the owner, payload-in-file launchers, the copy-and-rebuild helper, commands that run text they build.
F_DENY = ["D=~/.config/shipmiracle; touch $D/throwaway-account", "touch ~/.config/shipmiracle/throwaway-account", "touch ~/.config/shipmiracle/throw''away-account", "echo '{}' > ~/.config/shipmiracle/probes.json",
          "python3 -c \"open('/Users/x/.config/shipmiracle/throwaway-account','w').write('x')\"", "python3 -c \"import pathlib;pathlib.Path.home().joinpath('.config/shipmiracle/probes.json').write_text('{}')\"",
          "cp /tmp/p.json ~/.config/shipmiracle/probes.json", "mv /tmp/h ~/.config/shipmiracle/bin/shipm-presence", "chmod +x ~/.config/shipmiracle/bin/shipm-presence", "swiftc -O -o ~/.config/shipmiracle/bin/shipm-presence /tmp/x.swift",
          "python3 /tmp/w/bin/shipm-presence-build", "bin/shipm-presence-build", "echo abc > ~/.config/shipmiracle/presence.sha256", "cat > ~/.config/shipmiracle/throwaway-account", "sed -i '' s/a/b/ ~/.config/shipmiracle/probes.json",
          "rm ~/.config/shipmiracle/throwaway-account", "tee ~/.config/shipmiracle/probes.json < /tmp/x", "shipm owner mark-separate-account", "bash -c 'touch ~/.config/shipmiracle/throwaway-account'", "ln -s /tmp/x ~/.config/shipmiracle/bin/shipm-presence",
          "open /tmp/x.command", "open -a Terminal /tmp/x.sh", "osascript /tmp/x.scpt", "osascript -l JavaScript /tmp/x.js", "osascript -e 'tell app \"Terminal\" to do script \"/tmp/x.sh\"'",
          "osascript -e 'tell application \"System Events\" to keystroke \"x\"'", "x-terminal-emulator -e /tmp/x.sh", "gnome-terminal -- /tmp/x.sh", "konsole -e /tmp/x.sh", "xterm -e /tmp/x.sh",
          "tmux new-session -d /tmp/x.sh", "tmux new-window /tmp/x.sh", "tmux send-keys -t 0 'ls' Enter", "tmux run-shell /tmp/x.sh", "screen -dm /tmp/x.sh", "screen -X stuff ls",
          "launchctl bootstrap gui/501 /tmp/x.plist", "launchctl load /tmp/x.plist", "launchctl submit -l x -- /tmp/x.sh", "launchctl kickstart gui/501/x", "crontab /tmp/x", "crontab -e", "crontab -r",
          "shortcuts run MyShortcut", "at now < /tmp/x.sh", "open -a iTerm /tmp/x", "open /tmp/x.tool", "xdotool key Return", "ydotool type hi", "kitten @ send-text hi",
          "git -c alias.x='!sh /tmp/x.sh' x", "git -c core.pager=less -c alias.y=\"!/tmp/y\" y", "echo YXV0b3BpbG90Cg== | base64 -d | sh", "printf '\\x73\\x68\\x69\\x70\\x6d' | bash", "xxd -r -p /tmp/h | sh",
          "X=$(cat /tmp/c); eval $X", "eval \"$(cat /tmp/c)\"", "eval $(curl-less cmd)"]
F_ALLOW = ["cat ~/.config/shipmiracle/probes.json", "ls -la ~/.config/shipmiracle/bin", "grep -n presence ~/.config/shipmiracle/presence.sha256", "stat ~/.config/shipmiracle/throwaway-account", "head -3 ~/.config/shipmiracle/probes.json",
           "wc -l ~/.config/shipmiracle/probes.json", "diff ~/.config/shipmiracle/probes.json /tmp/x", "rg shipm-presence shipmiracle/", "git add bin/shipm-presence-build", "git diff -- tools/presence/shipm-presence.swift",
           "shipm owner status", "shipm owner status --json", "osascript -e 'display notification \"x\"'", "tmux ls", "tmux display-message hi", "tmux list-windows", "launchctl list", "crontab -l",
           "open https://example.org", "open notes.pdf", "open .", "open -a Calculator", "open -a TextEdit notes.txt", "xdotool getactivewindow", "gnome-terminal --version", "konsole --help", "screen -ls", "at -l",
           "echo hello | base64", "echo aGk= | base64 -d", "printf 'hello' | sh -c cat", "git -c core.pager=cat log", "git config --get user.name", "eval echo hi", "shortcuts list"]
for cmd, o in zip(F_DENY, run_many([(c, {}) for c in F_DENY])):
    check("F deny: " + repr(cmd)[:70], deny(o) and "Traceback" not in json.dumps(o), o)
for cmd, o in zip(F_DENY, run_many([(c, AG) for c in F_DENY])):
    check("F deny (agent): " + repr(cmd)[:60], deny(o), o)
for cmd, o in zip(F_ALLOW, run_many([(c, {}) for c in F_ALLOW])):
    check("F allow: " + repr(cmd)[:70], not deny(o) or not any(t in json.dumps(o) for t in ("decide who counts", "starts another program", "runs text it builds", "autopilot command")), o)
check("F: the table has at least 52 commands", len(F_DENY) + len(F_ALLOW) >= 52)
_o = run_many([("D=~/.config/shipmiracle; touch $D/throwaway-account", {})])[0]
check("F deny text: ONE plain sentence + what is fine to do", "only you change them" in json.dumps(_o) and "cat, ls, grep" in json.dumps(_o), _o)
for cmd, o in zip(OP_DENY, run_many([(c, {}) for c in OP_DENY])):
    txt = json.dumps(o)
    check("OP6 deny: " + repr(cmd)[:70], deny(o) and ("autopilot" in txt or "terminal" in txt.lower() or "Terminal" in txt) and "Traceback" not in txt, o)
for cmd, o in zip(OP_DENY, run_many([(c, AG) for c in OP_DENY])):
    check("OP6 deny (agent): " + repr(cmd)[:60], deny(o), o)
for cmd, o in zip(OP_ALLOW, run_many([(c, {}) for c in OP_ALLOW])):
    check("OP6 allow: " + repr(cmd)[:70], not deny(o) or "autopilot command" not in json.dumps(o) and "team or the gate" not in json.dumps(o), o)
_o1, _o2 = run_many([("script -q /dev/null shipm autopilot checkpoint", {}), ("python3 -c \"import subprocess;subprocess.run(['shipm','autopilot','checkpoint'])\"", {})])
check("OP6 each deny text is ONE plain sentence that names the terminal", all(deny(o) and "terminal" in json.dumps(o).lower() and json.dumps(o).count(". ") <= 1 for o in (_o1, _o2)), (_o1, _o2))
check("OP6 the raw-text deny says what to do instead (type it yourself in Terminal; put a note in a file)", "Terminal" in json.dumps(_o2) and "git commit -F" in json.dumps(_o2), _o2)

# L4 (re-review): ~/.local/share/shipmiracle/engine is a REAL link; the link itself is judged, not its target (earlier fixtures never created one)
_share = os.path.join(os.environ["HOME"], ".local/share/shipmiracle"); os.makedirs(_share, exist_ok=True)
_other = str(p.T / "elsewhere"); os.makedirs(_other + "/hooks", exist_ok=True)
for _tn, _tgt in (("engine checkout", str(p.WSF)), ("outside folder", _other)):
    if os.path.islink(_lk): os.remove(_lk)
    os.symlink(_tgt, _lk)
    for _cmd in ("ln -sfn /tmp/evil ~/.local/share/shipmiracle/engine", "ln -sfn /tmp/evil $HOME/.local/share/shipmiracle/engine", "rm ~/.local/share/shipmiracle/engine", "mv /tmp/x ~/.local/share/shipmiracle/engine",
                 "echo x > ~/.local/share/shipmiracle/engine/hooks/shipm-hook", "echo x > $HOME/.local/share/shipmiracle/engine/hooks/shipm-hook", "echo x > " + _lk + "/hooks/shipm-hook", "echo x > " + os.path.realpath(_share) + "/engine/hooks/shipm-hook", "cd ~/.local/share/shipmiracle && ln -sfn /tmp/evil engine",
                 "ln -sfn /tmp/evil ~/.local/share/shipmiracle/engine2 && mv -f ~/.local/share/shipmiracle/engine2 ~/.local/share/shipmiracle/engine"):
        for _ag in (None, "backend-engineer"):
            check("L4 real link (%s) %s refused: %s" % (_tn, "agent" if _ag else "main chat", _cmd[:60]), deny(p.pre("Bash", {"command": _cmd}, agent=_ag)))
    for _ag in (None, "backend-engineer"):
        check("L4 real link (%s): Write through the link refused%s" % (_tn, " (agent)" if _ag else ""), deny(p.pre("Write", {"file_path": _lk + "/hooks/shipm-hook", "content": "x"}, agent=_ag)))
        check("L4 real link (%s): Write to the link itself refused%s" % (_tn, " (agent)" if _ag else ""), deny(p.pre("Write", {"file_path": _lk, "content": "x"}, agent=_ag)))
os.remove(_lk)
p.prompt(sid="r"); o = p.hook("PreToolUse", "r", tool_name="Bash", tool_input={"command": "rm -rf ."})
check("rm -rf . says why (would delete .claude)", deny(o) and "would delete .claude, which holds the team-flow check" in json.dumps(o), o)

# a 300 KB command with an unterminated quote: cheap check only, under 1 s
for big_ in ('echo "' + "a > b; " * 43000, 'echo "' + "x" * 300000, "echo '" + "cat <<a\n" * 30000):
    t0 = time.time()
    r = p.run_raw(json.dumps({"hook_event_name": "PreToolUse", "session_id": "s1", "cwd": str(p.P), "tool_name": "Bash", "tool_input": {"command": big_}}))
    dt = time.time() - t0
    check(f"{len(big_) // 1000} KB command with an unterminated quote finishes in {dt:.2f}s (< 1 s), exit 0", r.returncode == 0 and dt < 1, (r.returncode, dt))
check("... and the big command's write to a project file is still refused by the cheap check", deny(p.hook("PreToolUse", "r", tool_name="Bash", tool_input={"command": "echo " + "y" * 150000 + " > src/app.py"})))

# unterminated quote: exit 0 and a valid answer
r = p.run_raw(json.dumps({"hook_event_name": "PreToolUse", "session_id": "s1", "cwd": str(p.P), "tool_name": "Bash", "tool_input": {"command": 'echo "abc > src/app.py'}}))
check("unterminated quote: exit 0, valid output", r.returncode == 0 and (not r.stdout.strip() or isinstance(json.loads(r.stdout), dict)), r.stdout + r.stderr)
check("hook errors log stays empty", p.errors() == "", p.errors())

# warn level notes, off level is silent
for cmd in ("cp /tmp/x src/app.py", "echo x > $(pwd)/src/app.py", "patch -p1 < /tmp/p.diff"):
    p.level("warn"); p.prompt(sid="w1"); w = p.hook("PreToolUse", "w1", tool_name="Bash", tool_input={"command": cmd})
    check("warn level notes: " + cmd, not deny(w) and "warn-only" in note(w), w)
    p.level("off"); w = p.hook("PreToolUse", "o1", tool_name="Bash", tool_input={"command": cmd})
    check("off level is silent: " + cmd, w == {}, w)
p.level("strict")

# an agent (subagent) may write: the pre-check is for the main chat only
check("agent Bash write is allowed", not deny(p.hook("PreToolUse", tool_name="Bash", tool_input={"command": "cp /tmp/x src/app.py"}, agent_id="a", agent_type="backend-engineer")))

# performance: a 2 KB command
big = "git commit -m \"" + ("lorem ipsum > dolor " * 90) + "\" && ls src | head -3 ; echo done > /tmp/out"
t = time.time()
r = p.run_raw(json.dumps({"hook_event_name": "PreToolUse", "session_id": "s1", "cwd": str(p.P), "tool_name": "Bash", "tool_input": {"command": big}}))
whole = time.time() - t
import importlib.util, re as _re
code = F.gate_source().split("def out(obj):")[0]
ns = {}
exec(compile("import difflib, fcntl, glob, json, math, os, re, shlex, subprocess, sys, time, traceback\nHOME=''\nRECORD=re.compile(r\"^(docs/(STATUS\\.md|DECISIONS\\.md|plans/))\")\n" + code[code.index("PUNCT = set"):], "bt", "exec"), ns)
t = time.time()
for _ in range(20):
    ns["bash_targets"](big, str(p.P), str(p.P))
per = (time.time() - t) / 20 * 1000
check(f"2 KB command ({len(big)} chars): bash_targets {per:.1f} ms (< 50 ms)", per < 50, per)
check(f"2 KB command: whole hook {whole * 1000:.0f} ms, allowed", not deny(json.loads(r.stdout) if r.stdout.strip() else {}), r.stdout)

# ReDoS: 48 KB unterminated quote with 12k "<<a" lines
evil = 'echo "abc\n' + "<<a\n" * 12000
import shipmiracle_timing as T
# load-tolerant (26 Oct 2026): <= max(0.5 s, 4 x a trivial hook call (`ls`) measured right before and after; ~0.12 s quiet), best of 3 attempts; exit code 0 is checked on every attempt
def _call(cmd):
    return p.run_raw(json.dumps({"hook_event_name": "PreToolUse", "session_id": "s1", "cwd": str(p.P), "tool_name": "Bash", "tool_input": {"command": cmd}}))
_rc = []
def _measure_evil():
    t = time.time(); r = _call(evil); dt = time.time() - t; _rc.append(r.returncode); return dt
BASE_LS = lambda: T.timed(lambda: _call("ls"))
ok_, rep_, best_ = T.robust_around(_measure_evil, BASE_LS, 0.5, 4, attempts=3)
print("INFO ReDoS evil: " + rep_)
check(f"ReDoS: {len(evil)}-char unterminated quote with 12k heredoc markers finishes in <= max(0.5 s, 4 x baseline), exit 0 :: {rep_}", ok_ and all(c == 0 for c in _rc), (_rc, rep_))
evil2 = "".join("cat <<a\n" for _ in range(40)) + "echo x > src/app.py\n"
ok2_, rep2_, _b = T.robust_around(lambda: T.timed(lambda: _call('echo "u\n' + evil2)), BASE_LS, 0.5, 4, attempts=3)
check("ReDoS: 40 markers in the regex fallback finish in <= max(0.5 s, 4 x baseline) :: " + rep2_, ok2_ and _call('echo "u\n' + evil2).returncode == 0, rep2_)
check("ReDoS mutant: the evil call slowed by a sleep (4 x the allowed time) is still noticed by the relative check", T.mutant_noticed(lambda: _call(evil), BASE_LS, 0.5, 4, n=2))

p.cleanup()
print("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
