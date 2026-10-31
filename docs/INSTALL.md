# Install

macOS is first-class. Linux and WSL 2 are experimental (see the support table in the README). Native Windows is refused with a
"use WSL 2" message and nothing is changed.

Nothing here is run for you with `sudo`, and Shipmiracle never runs a package manager. It prints the command; you run it.

## 1. Prerequisites

| Need | Why | Check |
|---|---|---|
| git | clone and project history | `git --version` |
| python3 3.9 or newer | the command line and hooks (standard library only) | `python3 --version` |
| node 18 or newer | the VS Code panel tests and tools | `node --version` |
| Claude Code, signed in (Pro or Max) | Shipmiracle drives it; it never stores your login | `claude --version` |
| VS Code, with the `code` command on PATH | the status panel | `code --version` |
| git name and email set | commits | `git config user.name` and `git config user.email` |

Optional: GitHub CLI (`gh`, signed in with `gh auth login --web`), gitleaks (for `shipm release-check`).
The README has the install lines for macOS, Ubuntu, Debian, WSL 2 and Fedora.

### macOS, on a fresh Mac, in this order

1. `xcode-select --install` (a window opens). It gives git and python3; check `python3 --version` shows 3.9 or newer.
2. Node 18 or newer. `brew install node` needs Homebrew first: install it from [brew.sh](https://brew.sh), or get node from [nodejs.org](https://nodejs.org/en/download).
3. VS Code: [download](https://code.visualstudio.com/download), then in VS Code run "Shell Command: Install 'code' command in PATH".
4. Claude Code: follow the [official overview](https://docs.claude.com/en/docs/claude-code/overview) to install it, then run `claude` once in a terminal and sign in.
5. Git name and email (commands: [TROUBLESHOOTING.md](TROUBLESHOOTING.md), problem 10).

### Linux and WSL 2

Use your package manager (lines in the README). On WSL 2 do everything inside Ubuntu, and keep projects in the Linux home folder
(for example `~/Developer`), not under `/mnt/c`. Not available on Linux and WSL 2: the awake guard. On WSL 2 there are no
desktop pop-ups; the panel is the notification.

## 2. Get it and start setup

```
git clone <URL from the green Code button of this repository> ~/Developer/shipmiracle
cd ~/Developer/shipmiracle
./bin/shipm init
```

Run `init` in a normal terminal, not inside a Claude chat: setup is an owner command and refuses to run in a chat.

## 3. What `shipm init` does

Three stages. It is safe to re-run; a finished step does nothing. If the input ends (you close the terminal), it stops cleanly and the
next `shipm init` resumes.

**Stage 1, Check (read only).** One screen: your system, and each item with a mark (ready, needs you, optional).
You can see it at any time without changing anything: `shipm init --check` (add `--json` for data; `shipm init --more` on its own lists every row; the two cannot be combined).

**Stage 2, Quick setup.** At most five choices; pressing Enter keeps the recommended answer:

1. Language for reports (English or Arabic).
2. Projects folder (default `~/Developer`).
3. How much the team does by itself (normal, step by step, or on its own; "on its own" never turns full autopilot on).
4. Keep the computer awake while Claude works (asked on macOS, and on Linux only where a keep-awake tool exists).
5. Where notifications show (VS Code, system, or none).

The answers are saved in `~/.config/shipmiracle/config.json`, user-level only, never inside a project. Ask again later with
`shipm init --prefs`; undo with `shipm init --undo prefs`.

**Stage 3, Connect.** Only what is missing, in dependency order, each verified before the next:
base tools, node, git name and email, Claude Code sign-in, projects folder, engine, project registry, VS Code panel, GitHub sign-in.
Sign-ins happen in the tool's own login (browser); Shipmiracle never sees or stores a password or token.

`shipm init --yes` answers yes to the required and recommended steps (including the GitHub sign-in) but never to an optional one such as the awake guard (two LaunchAgents): opt in by name with `shipm init --step guard`.

## 4. What each stage changes on your machine

| Step | Writes |
|---|---|
| Check | nothing |
| Quick setup | the answers in `~/.config/shipmiracle/config.json` |
| Engine | `~/.config/shipmiracle/config.json`; the Shipmiracle hook entries in `~/.claude/settings.json` (backup first, other entries untouched); the agent files in `~/.claude/agents/`; the link `~/.local/bin/shipm` |
| Projects folder | creates the folder if it is missing (asks first) |
| Project registry | adds your existing projects to `~/.config/shipmiracle/registry.json` |
| VS Code panel | `code --install-extension` for the Shipmiracle panel, and for Claude Code's extension if you say yes |
| Awake guard (optional, macOS; only with `shipm init --step guard`) | two LaunchAgents, `com.shipmiracle.guard.plist` and `com.shipmiracle.daily.plist`; the sudoers line is printed, never written. The guard job runs the watcher about every minute; with `auto` on in `config/watch.json` (the default) the watcher ends processes it can prove are orphans of a dead chat (leftover test runs, automation browsers) and deletes Claude task output files older than 7 days in `/private/tmp/claude-<uid>`. It never ends a live chat. |
| Daily job (optional, Linux and WSL 2) | a systemd user timer, no root |
| Everything | the install manifest `~/.local/state/shipmiracle/v1/install-manifest.json`, so each write can be undone |

It never edits `~/.gitconfig`, your shell startup files, or anything inside your projects.

Optional extras are off until you ask: `shipm init --step remote-control`, `shipm init --step ask-inbox`.

## 5. Verify

```
shipm init --check      # last line "Ready: yes." when no required item is left; the exit code is always 0
shipm init --check --json   # the same as data: "ready": true or false
shipm init --more       # every row, including the optional ones
```

Then reload VS Code and open the Shipmiracle panel in the activity bar. The panel lists your registered projects. If something does not
work, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md). To remove everything, see [UNINSTALL.md](UNINSTALL.md).

Hint: `shipm` is linked to `~/.local/bin/shipm`. If your shell does not find it, add `~/.local/bin` to PATH yourself, or call `./bin/shipm`
from the clone. Shipmiracle never edits your shell startup files.
