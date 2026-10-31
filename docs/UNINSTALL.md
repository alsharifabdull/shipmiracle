# Uninstall

Nothing in your projects is deleted. Close chats that use the panel first.

## Steps

```
bin/shipm uninstall                   # 1. dry run: read the list
bin/shipm uninstall --apply           # 2. reverse each write, newest first
bin/shipm uninstall --apply --purge   # 3. optional: also remove the config and state folders
```

Run it in a normal terminal, not inside a Claude chat. Step 2 reverses every write recorded in the install manifest
(`~/.local/state/shipmiracle/v1/install-manifest.json`), newest first, and only where the file is still exactly as setup left it.
A file you changed since is skipped and reported, never overwritten. `--purge` asks you to type the word `PURGE` (or pass
`--confirm PURGE` when there is no terminal), and removes `~/.config/shipmiracle` and `~/.local/state/shipmiracle` only when every
step was reversed.

To undo only one optional piece: `shipm init --undo ROW` (for example `remote-control`, `ask-inbox`, `prefs`).

## What is removed

- The Shipmiracle hook entries in `~/.claude/settings.json` (only those entries; every other entry is left alone).
- The Shipmiracle agent files in `~/.claude/agents/`.
- The link `~/.local/bin/shipm` (if it still points at this clone).
- The VS Code extensions that setup installed.
- The macOS LaunchAgents setup installed.
- The config keys and registry entries setup added.
- With `--purge`: the config and state folders.

## What stays

- Your project repositories and the projects folder.
- Your Claude and GitHub logins, Homebrew packages, git settings.
- This clone. Uninstall prints the `rm -rf` line; run it yourself when you are sure.
- `/etc/sudoers.d/shipm-guard`, only if you ran `shipm-guard-admin` (the optional lid-closed keep-awake rule): removing it needs `sudo rm /etc/sudoers.d/shipm-guard`; uninstall cannot do that for you.
- The panel's small diagnostic folder `~/.local/state/shipmiracle-diag` (trace and render files, see [PRIVACY.md](PRIVACY.md)): delete it by hand.
- Files Shipmiracle created inside a project you made with it (`docs/`, `.shipmiracle/`, reports). They belong to the project.

## Known gap

On Linux and WSL 2 the removal of the daily systemd user timer is not wired into uninstall yet (planned). If you turned it on, remove it
yourself:

```
systemctl --user disable --now com.shipmiracle.daily.timer
rm ~/.config/systemd/user/com.shipmiracle.daily.service ~/.config/systemd/user/com.shipmiracle.daily.timer
systemctl --user daemon-reload
```

## Check afterwards

- `~/.claude/settings.json` has no hook command that mentions shipmiracle (open it and search).
- `ls ~/.local/bin/shipm` says the file is gone.
- VS Code: Extensions view, search Shipmiracle; uninstall by hand if it is still listed.
- If Claude Code prints "Shipmiracle gate OFF" after removal, a stale hook entry is left: delete that line in `~/.claude/settings.json`.

Backups made by setup stay in the state folder until you purge.
